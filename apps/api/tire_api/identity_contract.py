"""Explicit v2 identity mapping; never rewrite historical entities, facts or subscriptions."""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field, StrictBool, StrictInt, field_validator
from sqlalchemy import Text, cast, desc, func, or_, select

from .db import AlertRule, FactVersion, QueryRun, Snapshot, TireVariant, Verification, WatchItem, uid, utc
from .domain import StrictModel, VariantInput, digest, stable_json
from .identity_contract_models import VariantIdentityBinding, VariantIdentityMigrationApplication

SCOPE = {'scope': 'local_workspace', 'data_state': 'local_snapshot'}
NOTICE = ('迁移只新增身份键绑定和审核记录，保留旧实体、事实、快照与订阅。'
          '未知或混合代码类型不自动认定同一实体；相关新版本不会自动接管旧关注或提醒。')
MAX_LEGACY_VARIANTS = 10000


class IdentityContractError(Exception):
    def __init__(self, code, status_code=409):
        self.code, self.status_code = code, status_code
        super().__init__(code)


def schema_version():
    from .domain import IDENTITY_CONTRACT_VERSION
    return IDENTITY_CONTRACT_VERSION


def migration_descriptor():
    root = Path(__file__).resolve().parent
    return {'schema': schema_version(), 'digest': digest({name: hashlib.sha256((root / name).read_bytes()).hexdigest()
             for name in ('domain.py', 'identity_contract.py', 'identity_contract_models.py')})}


class MigrationApply(StrictModel):
    mode: Literal['history']
    contract_schema: str = Field(alias='schema', min_length=1, max_length=80)
    expected_revision: StrictInt = Field(ge=0)
    expected_preview_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    acknowledged: StrictBool
    operator: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator('operator', 'reason')
    @classmethod
    def signed_text(cls, value, info):
        allowed = {'\n', '\r'} if info.field_name == 'reason' else set()
        if not value.strip() or any(ord(ch) < 32 and ch not in allowed for ch in value):
            raise ValueError('署名与理由须为非空文本，不能包含控制字符')
        value.encode('utf-8', errors='strict')
        return value


def _binding_hash(row):
    return digest({key: getattr(row, key) for key in ('schema', 'canonical_key', 'variant_id', 'current_identity',
        'identity_status', 'origin', 'proof', 'migration_id', 'legacy_candidate_id')})


def _checked_binding(row):
    if row and row.fingerprint != _binding_hash(row):
        raise IdentityContractError('identity_binding_integrity_failed', 503)
    return row


def _application_hash(row):
    return digest({key: getattr(row, key) for key in ('revision', 'schema', 'contract_digest', 'preview_fingerprint',
        'summary', 'assessments', 'binding_ids', 'operator', 'reason')})


def _checked_application(row):
    if row and row.fingerprint != _application_hash(row):
        raise IdentityContractError('identity_migration_integrity_failed', 503)
    return row


def _latest_application(db):
    return _checked_application(db.scalar(select(VariantIdentityMigrationApplication)
        .order_by(desc(VariantIdentityMigrationApplication.revision)).limit(1)))


def _assessments(db):
    result = {}
    for row in db.scalars(select(VariantIdentityMigrationApplication)
                         .where(VariantIdentityMigrationApplication.schema == schema_version())
                         .order_by(desc(VariantIdentityMigrationApplication.revision))):
        _checked_application(row)
        for item in row.assessments:
            result.setdefault(item['variant_id'], item)
    return result


def contract_context(db, variant_ids):
    ids = set(variant_ids)
    if not ids:
        return {'variants': {}, 'bindings': {}, 'related': {}, 'assessments': {}}
    variants = {row.id: row for row in db.scalars(select(TireVariant).where(TireVariant.id.in_(ids)))}
    bindings = {row.variant_id: _checked_binding(row) for row in db.scalars(select(VariantIdentityBinding).where(
        VariantIdentityBinding.schema == schema_version(), VariantIdentityBinding.variant_id.in_(ids)))}
    related = defaultdict(list)
    for row in db.scalars(select(VariantIdentityBinding).where(VariantIdentityBinding.schema == schema_version(),
            VariantIdentityBinding.legacy_candidate_id.in_(ids))):
        _checked_binding(row)
        related[row.legacy_candidate_id].append({'variant_id': row.variant_id, 'relationship': 'unconfirmed_current',
            'product_code_type': row.current_identity.get('product_code_type')})
    for row in bindings.values():
        if row.legacy_candidate_id:
            related[row.variant_id].append({'variant_id': row.legacy_candidate_id, 'relationship': 'unconfirmed_legacy',
                                            'product_code_type': None})
    legacy = ids - bindings.keys()
    assessments = _assessments(db) if legacy else {}
    return {'variants': variants, 'bindings': bindings, 'related': related, 'assessments': assessments}


def contract_metadata(db, variant_id, *, context=None):
    context = context or contract_context(db, [variant_id])
    if variant_id not in context['variants']:
        raise IdentityContractError('variant_not_found', 404)
    bound = context['bindings'].get(variant_id)
    assessment = context['assessments'].get(variant_id)
    state = 'current' if bound else 'legacy_needs_review' if assessment else 'legacy_unbound'
    return {'schema': schema_version(), 'state': state,
        'current_key': bound.canonical_key if bound else None,
        'current_identity': deepcopy(bound.current_identity) if bound else None,
        'identity_status': bound.identity_status if bound else None, 'origin': bound.origin if bound else None,
        'reason_codes': [] if bound else assessment['reason_codes'] if assessment else ['identity_migration_required'],
        'related_candidates': sorted(context['related'].get(variant_id, []), key=lambda item: item['variant_id']),
        'tracking_state': 'current' if bound else 'identity_review_required',
        'notice': NOTICE if not bound or context['related'].get(variant_id) else '现行身份来自独立绑定，原证据字段保持不变。'}


def annotate_identity_contracts(db, rows):
    context = contract_context(db, [row['id'] for row in rows])
    return [{**row, 'identity_contract': contract_metadata(db, row['id'], context=context)} for row in rows]


def require_current_identity(db, variant_id):
    metadata = contract_metadata(db, variant_id)
    if metadata['state'] != 'current':
        raise IdentityContractError('identity_contract_review_required')
    return metadata['current_identity']


def _model(row):
    return VariantInput.model_validate({key: value for key, value in row.items() if key in VariantInput.model_fields})


def _proof_plan(db, variant_ids=None, *, assessments=None):
    """All immutable accepted history is checked, never the latest facts or manual overlays alone."""
    descriptor = migration_descriptor()
    application = _latest_application(db)
    statement = select(TireVariant).where(~select(VariantIdentityBinding.id).where(
        VariantIdentityBinding.schema == schema_version(), VariantIdentityBinding.variant_id == TireVariant.id,
        VariantIdentityBinding.origin == 'source_observation').exists())
    if variant_ids is not None:
        statement = statement.where(TireVariant.id.in_(variant_ids))
    variants = db.scalars(statement.order_by(TireVariant.id).limit(MAX_LEGACY_VARIANTS + 1)).all()
    if len(variants) > MAX_LEGACY_VARIANTS:
        raise IdentityContractError('identity_migration_inventory_too_large', 422)
    binding_statement = select(VariantIdentityBinding).where(VariantIdentityBinding.schema == schema_version())
    if variant_ids is not None:
        binding_statement = binding_statement.where(VariantIdentityBinding.variant_id.in_(variant_ids))
    bindings = {row.variant_id: _checked_binding(row) for row in db.scalars(binding_statement)}
    variants = [row for row in variants if row.id not in bindings or bindings[row.id].origin == 'legacy_migration']
    ids = {row.id for row in variants}
    observations, facts = defaultdict(list), defaultdict(list)
    snapshot_rows, snapshots, invalid_raw, duplicate_members, verification_proofs = {}, {}, set(), set(), {}
    snapshot_statement = select(Snapshot)
    if variant_ids is not None:
        snapshot_statement = snapshot_statement.where(or_(
            Snapshot.id.in_(select(FactVersion.snapshot_id).where(FactVersion.variant_id.in_(ids))),
            *[cast(Snapshot.parsed_variants, Text).contains(variant_id, autoescape=True) for variant_id in ids]))
    for snapshot in db.scalars(snapshot_statement.order_by(Snapshot.id)):
        members = [(index, member) for index, member in enumerate(snapshot.parsed_variants) if member.get('id') in ids]
        if not members:
            continue
        if hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest() != snapshot.raw_hash:
            invalid_raw.add(snapshot.id)
        snapshots[snapshot.id] = snapshot
        counts = Counter(member['id'] for _, member in members)
        duplicate_members.update((snapshot.id, variant_id) for variant_id, count in counts.items() if count != 1)
        snapshot_rows[snapshot.id] = {member['id']: member for _, member in members if counts[member['id']] == 1}
        for index, member in members:
            observations[member['id']].append((snapshot, index, member))
    for snapshot_id, snapshot in snapshots.items():
        rows = db.execute(select(Verification, QueryRun).join(QueryRun, Verification.query_id == QueryRun.id)
            .where(Verification.snapshot_id == snapshot_id).order_by(Verification.id)).all()
        verification_proofs[snapshot_id] = [{'id': verification.id, 'query_id': run.id,
            'source_id': verification.source_id, 'query_key': verification.query_key,
            'status': verification.status, 'run_source_id': run.source_id, 'run_query_key': run.query_key,
            'query_hash': digest(run.query)} for verification, run in rows]
    for fact in db.scalars(select(FactVersion).where(FactVersion.variant_id.in_(ids)).order_by(FactVersion.id)):
        facts[fact.variant_id].append(fact)
    watches = Counter(db.scalars(select(WatchItem.variant_id).where(WatchItem.variant_id.in_(ids))))
    rules = Counter(db.scalars(select(AlertRule.variant_id).where(AlertRule.variant_id.in_(ids))))
    items, proofs = [], {}
    from .service import business_facts
    for variant in variants:
        reasons, keys, identities, statuses = set(), set(), {}, set()
        evidence = []
        bound = bindings.get(variant.id)
        if not observations[variant.id] or not facts[variant.id]:
            reasons.add('legacy_evidence_missing')
        for snapshot, index, member in observations[variant.id]:
            evidence.append({'snapshot_id': snapshot.id, 'source_id': snapshot.source_id,
                'query_key': snapshot.query_key, 'raw_hash': snapshot.raw_hash, 'row_index': index,
                'actual_body_hash': hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest(),
                'source_url': snapshot.source_url, 'parser_version': snapshot.parser_version,
                'parser_identity': snapshot.parser_identity, 'content_type': snapshot.content_type,
                'member_hash': digest(member), 'identity_contract_version': snapshot.identity_contract_version,
                'verifications': verification_proofs[snapshot.id]})
            if snapshot.id in invalid_raw:
                reasons.add('legacy_raw_integrity_failed')
            if (snapshot.id, variant.id) in duplicate_members:
                reasons.add('legacy_duplicate_snapshot_member')
            if not any(item['source_id'] == item['run_source_id'] == snapshot.source_id
                       and item['query_key'] == item['run_query_key'] == item['query_hash'] == snapshot.query_key
                       and item['status'] in {'ok', 'not_modified'} for item in verification_proofs[snapshot.id]):
                reasons.add('legacy_verification_missing')
            try:
                parsed = _model(member)
                if snapshot.identity_contract_version is None:
                    legacy_key, legacy_status = parsed.legacy_identity_key(snapshot.source_id, snapshot.query_key, index)
                    if (stable_json(parsed.legacy_identity()) != stable_json(variant.identity)
                            or legacy_key != variant.identity_key or legacy_status != variant.identity_status
                            or member.get('identity_key') != variant.identity_key
                            or member.get('identity_status') != variant.identity_status):
                        reasons.add('legacy_identity_evidence_mismatch')
                elif snapshot.identity_contract_version == schema_version():
                    key, status = parsed.identity_key(snapshot.source_id, snapshot.query_key, index)
                    if (bound is None or key != bound.canonical_key or status != bound.identity_status
                            or stable_json(parsed.identity()) != stable_json(bound.current_identity)
                            or member.get('identity_key') != key or member.get('identity_status') != status):
                        reasons.add('legacy_identity_evidence_mismatch')
                else:
                    reasons.add('identity_contract_version_unknown')
                namespace = parsed.identity().get('product_code_type')
                if namespace is None:
                    reasons.add('legacy_namespace_unknown')
                key, status = parsed.identity_key(snapshot.source_id, snapshot.query_key, index)
                keys.add(key); identities[digest(parsed.identity())] = parsed.identity(); statuses.add(status)
            except (ValueError, TypeError, KeyError):
                reasons.add('legacy_identity_invalid')
        fact_proofs = []
        for fact in facts[variant.id]:
            member = snapshot_rows.get(fact.snapshot_id, {}).get(variant.id)
            fact_proofs.append({'id': fact.id, 'source_id': fact.source_id, 'snapshot_id': fact.snapshot_id,
                                'version': fact.version, 'facts_hash': fact.facts_hash, 'payload_hash': digest(fact.facts)})
            snapshot = snapshots.get(fact.snapshot_id)
            if (member is None or snapshot is None or fact.source_id != snapshot.source_id
                    or fact.version != member.get('fact_version') or fact.facts_hash != digest(fact.facts)
                    or fact.facts_hash != digest(business_facts(member.get('facts', {})))):
                reasons.add('legacy_fact_evidence_mismatch')
        if len(keys) != 1 or len(identities) != 1 or len(statuses) != 1:
            reasons.add('legacy_identity_ambiguous')
        current_key = next(iter(keys)) if len(keys) == 1 else None
        current_identity = next(iter(identities.values())) if len(identities) == 1 else None
        identity_status = next(iter(statuses)) if len(statuses) == 1 else None
        proof = {'legacy_key': variant.identity_key, 'legacy_identity': variant.identity,
                 'legacy_status': variant.identity_status, 'observations': evidence, 'facts': fact_proofs}
        proofs[variant.id] = proof
        items.append({'variant_id': variant.id, 'state': 'already_bound' if bound else 'needs_review' if reasons else 'eligible',
            'reason_codes': sorted(reasons), 'current_identity': deepcopy(bound.current_identity if bound else current_identity),
            'current_key': bound.canonical_key if bound else current_key,
            'identity_status': bound.identity_status if bound else identity_status,
            'proof_fingerprint': digest(proof), 'affected_watch_count': watches[variant.id], 'affected_rule_count': rules[variant.id]})
    by_key = defaultdict(list)
    for item in items:
        if item['current_key']:
            by_key[item['current_key']].append(item)
    occupied = {row.canonical_key: row.variant_id for row in bindings.values()}
    for key, group in by_key.items():
        if len(group) > 1 or any(key in occupied and occupied[key] != item['variant_id'] for item in group):
            for item in group:
                if item['state'] != 'already_bound':
                    item['state'] = 'needs_review'
                    item['reason_codes'] = sorted(set(item['reason_codes']) | {'canonical_key_collision'})
    summary = {'legacy_total': len(items), 'eligible': sum(item['state'] == 'eligible' for item in items),
        'needs_review': sum(item['state'] == 'needs_review' for item in items),
        'already_bound': sum(item['state'] == 'already_bound' for item in items),
        'watch_risk_count': sum(item['affected_watch_count'] for item in items if item['state'] == 'needs_review'),
        'rule_risk_count': sum(item['affected_rule_count'] for item in items if item['state'] == 'needs_review')}
    basis = {'schema': descriptor['schema'], 'contract_digest': descriptor['digest'],
             'revision': application.revision if application else 0, 'items': items,
             'bindings': sorted((row.id, row.fingerprint) for row in bindings.values())}
    assessed = _assessments(db) if assessments is None else assessments
    can_apply = any(item['state'] == 'eligible' or item['variant_id'] not in assessed for item in items)
    return {**SCOPE, 'can_apply': can_apply, **{key: basis[key] for key in ('schema', 'contract_digest', 'revision')},
        'preview_fingerprint': digest(basis), 'summary': summary, 'items': items, 'notice': NOTICE}, proofs


def migration_preview(db):
    return _proof_plan(db)[0]


def _new_binding(*, variant_id, key, identity, status, origin, proof, migration_id=None, legacy_candidate_id=None, binding_id=None):
    row = VariantIdentityBinding(id=binding_id or uid(), schema=schema_version(), canonical_key=key, variant_id=variant_id,
        current_identity=deepcopy(identity), identity_status=status, origin=origin, proof=deepcopy(proof),
        migration_id=migration_id, legacy_candidate_id=legacy_candidate_id)
    row.fingerprint = _binding_hash(row)
    return row


def application_view(db, row, *, replay=False):
    _checked_application(row)
    latest = _latest_application(db)
    return {**SCOPE, **{key: getattr(row, key) for key in ('id', 'revision', 'schema', 'contract_digest',
        'preview_fingerprint', 'summary', 'assessments', 'binding_ids', 'fingerprint', 'operator', 'reason')},
        'created_at': utc(row.created_at).isoformat(), 'idempotent_replay': replay,
        'current_revision': latest.revision if latest else 0, 'notice': NOTICE}


def apply_migration(db, payload, actor_session_id, idempotency_key):
    try:
        key = str(UUID(idempotency_key))
    except (ValueError, TypeError, AttributeError):
        raise IdentityContractError('invalid_idempotency_key', 422) from None
    request_hash = digest(payload.model_dump(mode='json', by_alias=True))
    from .service import QueryService
    QueryService(db, None).lock_ingestion()
    replay = db.scalar(select(VariantIdentityMigrationApplication).where(
        VariantIdentityMigrationApplication.actor_session_id == actor_session_id,
        VariantIdentityMigrationApplication.idempotency_key == key))
    if replay:
        if replay.request_hash != request_hash:
            raise IdentityContractError('idempotency_payload_mismatch')
        return application_view(db, replay, replay=True)
    preview, proofs = _proof_plan(db)
    if payload.contract_schema != preview['schema']:
        raise IdentityContractError('identity_contract_version_conflict')
    if payload.expected_revision != preview['revision']:
        raise IdentityContractError('identity_migration_revision_conflict')
    if payload.expected_preview_fingerprint != preview['preview_fingerprint']:
        raise IdentityContractError('identity_migration_preview_stale')
    if not payload.acknowledged:
        raise IdentityContractError('identity_migration_acknowledgement_required', 422)
    if not preview['can_apply']:
        raise IdentityContractError('identity_migration_no_changes')
    application_id = uid()
    bindings = [_new_binding(variant_id=item['variant_id'], key=item['current_key'], identity=item['current_identity'],
        status=item['identity_status'], origin='legacy_migration', proof=proofs[item['variant_id']], migration_id=application_id)
        for item in preview['items'] if item['state'] == 'eligible']
    row = VariantIdentityMigrationApplication(id=application_id, revision=preview['revision'] + 1, schema=preview['schema'],
        contract_digest=preview['contract_digest'], preview_fingerprint=preview['preview_fingerprint'], summary=preview['summary'],
        assessments=preview['items'], binding_ids=[binding.id for binding in bindings], operator=payload.operator, reason=payload.reason,
        actor_session_id=actor_session_id, idempotency_key=key, request_hash=request_hash)
    row.fingerprint = _application_hash(row)
    db.add(row); db.flush()
    db.add_all(bindings)
    db.commit()
    return application_view(db, row)


def resolve_variant(db, variant, source_id, query_key, row_index, snapshot_id, *, context=None):
    """Called under ingestion lock. Caller rolls back the entire adoption on any error."""
    key, status = variant.identity_key(source_id, query_key, row_index)
    binding = _checked_binding(db.scalar(select(VariantIdentityBinding).where(
        VariantIdentityBinding.schema == schema_version(), VariantIdentityBinding.canonical_key == key)))
    if binding:
        if stable_json(binding.current_identity) != stable_json(variant.identity()) or binding.identity_status != status:
            raise IdentityContractError('identity_binding_value_mismatch', 503)
        stored = db.get(TireVariant, binding.variant_id)
        if stored is None:
            raise IdentityContractError('identity_binding_target_missing', 503)
        return stored, key, status
    legacy_key, _ = variant.legacy_identity_key(source_id, query_key, row_index)
    legacy = db.scalar(select(TireVariant).where(TireVariant.identity_key == legacy_key))
    if legacy is not None:
        if context is None:
            context = {}
        if 'assessments' not in context:
            context['assessments'] = _assessments(db)
        assessment = context['assessments'].get(legacy.id)
        if assessment is None:
            raise IdentityContractError('identity_migration_required')
        legacy_binding = _checked_binding(db.scalar(select(VariantIdentityBinding).where(
            VariantIdentityBinding.schema == schema_version(), VariantIdentityBinding.variant_id == legacy.id)))
        if legacy_binding is not None:
            # A signed CAI entity does not absorb a later MSPN observation with
            # the same v1 projection. The current namespace key remains distinct.
            if legacy_binding.origin != 'legacy_migration' or legacy_binding.canonical_key == key:
                raise IdentityContractError('identity_migration_binding_missing', 503)
        else:
            if assessment['state'] != 'needs_review':
                raise IdentityContractError('identity_migration_binding_missing', 503)
            if legacy.id not in context:
                preview, _ = _proof_plan(db, [legacy.id], assessments=context['assessments'])
                context[legacy.id] = preview['items'][0]['proof_fingerprint'] if preview['items'] else None
            if context[legacy.id] != assessment['proof_fingerprint']:
                raise IdentityContractError('identity_migration_stale')
    stored = db.scalar(select(TireVariant).where(TireVariant.identity_key == key))
    if stored is not None and (stable_json(stored.identity) != stable_json(variant.identity()) or stored.identity_status != status):
        raise IdentityContractError('identity_unregistered_key_conflict', 503)
    if stored is None:
        stored = TireVariant(id=uid(), identity_key=key, identity=variant.identity(), identity_status=status)
        db.add(stored); db.flush()
    binding = _new_binding(variant_id=stored.id, key=key, identity=variant.identity(), status=status,
        origin='source_observation', proof={'snapshot_id': snapshot_id, 'source_id': source_id, 'query_key': query_key,
                                         'row_index': row_index, 'legacy_key': legacy_key},
        legacy_candidate_id=legacy.id if legacy else None)
    db.add(binding); db.flush()
    return stored, key, status


def register_identity_contract_routes(app: FastAPI):
    @app.exception_handler(IdentityContractError)
    async def identity_error(_request, error):
        return JSONResponse(status_code=error.status_code, content={'detail': {'code': error.code}})

    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get('/v1/identity-contract/migration-preview')
    def preview(mode: Literal['history'] = Query(...), db=Depends(get_db)):
        return migration_preview(db)

    @app.post('/v1/identity-contract/migration-applications', status_code=201)
    def apply(payload: MigrationApply, request: Request,
              idempotency_key: str = Header(..., alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return apply_migration(db, payload, request.state.session_id, idempotency_key)

    @app.get('/v1/identity-contract/migration-applications')
    def applications(mode: Literal['history'] = Query(...), offset: int = Query(0, ge=0),
                     limit: int = Query(10, ge=1, le=25), db=Depends(get_db)):
        rows = db.scalars(select(VariantIdentityMigrationApplication)
            .order_by(desc(VariantIdentityMigrationApplication.revision)).offset(offset).limit(limit)).all()
        return {**SCOPE, 'items': [application_view(db, row) for row in rows], 'offset': offset, 'limit': limit,
                'total': db.scalar(select(func.count()).select_from(VariantIdentityMigrationApplication)), 'notice': NOTICE}

    @app.get('/v1/identity-contract/migration-applications/{application_id}')
    def application(application_id: str, mode: Literal['history'] = Query(...), db=Depends(get_db)):
        row = db.get(VariantIdentityMigrationApplication, application_id)
        if row is None:
            raise IdentityContractError('identity_migration_not_found', 404)
        return application_view(db, row)


def cli_engine(database_url, *, readonly):
    """Open an existing schema only; preview cannot create files, DDL or sessions."""
    import sqlite3
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.engine import make_url
    url = make_url(database_url)
    if url.get_backend_name() == 'sqlite':
        if not url.database or url.database == ':memory:':
            raise IdentityContractError('identity_contract_schema_required')
        path = Path(url.database).resolve()
        if not path.is_file():
            raise IdentityContractError('identity_contract_schema_required')
        uri = path.as_uri() + ('?mode=ro' if readonly else '?mode=rw')
        engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(uri, uri=True, timeout=30))
    else:
        engine = create_engine(url)
    try:
        with engine.connect() as connection:
            if readonly and connection.dialect.name == 'postgresql':
                connection.exec_driver_sql('SET TRANSACTION READ ONLY')
            inspector = inspect(connection)
            if not {'tire_schema_versions', 'variant_identity_bindings', 'variant_identity_migration_applications'} <= set(inspector.get_table_names()):
                raise IdentityContractError('identity_contract_schema_required')
            if ('005_variant_identity_contract' not in set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars())
                    or 'identity_contract_version' not in {column['name'] for column in inspector.get_columns('snapshots')}):
                raise IdentityContractError('identity_contract_schema_required')
        return engine
    except Exception:
        engine.dispose()
        raise


def main():
    import argparse
    import json
    import os
    from sqlalchemy.orm import Session
    parser = argparse.ArgumentParser(description='本机命名空间身份迁移预览与签署；保留全部旧证据')
    parser.add_argument('action', choices=['preview', 'apply', 'history'])
    parser.add_argument('--request')
    parser.add_argument('--idempotency-key')
    args = parser.parse_args()
    database_url = os.getenv('TIRE_DATABASE_URL') or os.getenv('DATABASE_URL') or (
        'sqlite:///' + (Path(__file__).resolve().parents[3] / 'data' / 'dev.db').as_posix())
    engine = cli_engine(database_url, readonly=args.action != 'apply')
    try:
        with Session(engine, expire_on_commit=False) as db:
            if args.action != 'apply' and engine.dialect.name == 'postgresql':
                db.connection().exec_driver_sql('SET TRANSACTION READ ONLY')
            if args.action == 'preview':
                result = migration_preview(db)
            elif args.action == 'apply':
                if not args.request:
                    parser.error('apply requires --request')
                raw = Path(args.request).read_bytes()
                if len(raw) > 16384:
                    raise ValueError('request too large')
                from .parser_runtime import strict_json
                result = apply_migration(db, MigrationApply.model_validate(strict_json(raw)), 'local-cli', args.idempotency_key)
            else:
                result = {'items': [application_view(db, row) for row in db.scalars(select(VariantIdentityMigrationApplication)
                    .order_by(desc(VariantIdentityMigrationApplication.revision)).limit(25))]}
        print(json.dumps(result, ensure_ascii=False))
    finally:
        engine.dispose()
