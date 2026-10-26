"""Local management decisions, independent source contexts and exact original rows."""
from copy import deepcopy
from datetime import datetime
import hashlib
from typing import Literal

from fastapi import Depends, HTTPException, Query
from sqlalchemy import desc, func, select

from .db import FactVersion, ManualFactRevision, Snapshot, VariantLifecycleEvent, Verification, uid, utc
from .domain import digest
from .identity_models import IdentityRevision
from .interest_catalog_models import TireCatalogRevision
from .interest_applicability_models import TireCurationApplicabilityEvent
from .interest_events import _event, _reference, _reviewed_contexts, _tire_side
from .interest_models import InterestEvent
from .service import timestamp

KINDS = {'tire_curation_revision': ('tire_curation', ManualFactRevision),
         'tire_lifecycle_event': ('tire_lifecycle', VariantLifecycleEvent),
         'tire_identity_revision': ('tire_identity', IdentityRevision),
         'tire_catalog_revision': ('tire_catalog', TireCatalogRevision),
         'tire_curation_applicability_event': ('tire_curation_validity', TireCurationApplicabilityEvent)}
OriginalKind = Literal['tire_curation_revision', 'tire_lifecycle_event', 'tire_identity_revision',
                       'tire_catalog_revision', 'tire_curation_applicability_event']


def public_record(row):
    # Session ids are bearer cookie identifiers, not public decision evidence.
    return {column.name: timestamp(value) if isinstance(value, datetime) else deepcopy(value)
            for column in row.__table__.columns
            if not column.name.endswith('session_id') and column.name not in {'idempotency_key', 'request_hash'}
            for value in [getattr(row, column.name)]}


def primary_reference(kind, row):
    extra = {}
    if kind == 'tire_catalog_revision':
        extra = {'snapshot': row.snapshot_id, 'previous': row.previous_snapshot_id,
            'url': row.binding['after']['source_url'],
            'verifications': [value for value in (row.verification_id, row.previous_verification_id) if value]}
    elif kind == 'tire_curation_applicability_event':
        before, after = row.binding['before'], row.binding['after']
        extra = {'snapshot': after['snapshot_id'], 'previous': before['snapshot_id'], 'url': after['source_url'],
            'verifications': list(dict.fromkeys(value for value in (row.verification_id,
                before['verification_id'], after['verification_id']) if value))}
    return _reference(kind, row.id, row.variant_id, revision=row.revision,
        source=getattr(row, 'source_id', None), fingerprint=digest(public_record(row)), **extra)


def snapshot_context(db, snapshot_id, variant_id, asof, fact=None):
    snapshot = db.get(Snapshot, snapshot_id)
    if snapshot is None:
        return {'evidence_valid': False}, []
    members = [member for member in snapshot.parsed_variants
               if isinstance(member, dict) and member.get('id') == variant_id]
    if fact is None and len(members) == 1:
        fact = db.scalar(select(FactVersion).where(FactVersion.variant_id == variant_id,
            FactVersion.source_id == snapshot.source_id, FactVersion.version == members[0].get('fact_version')))
    side, refs = _tire_side(db, snapshot_id, variant_id, fact, asof, reconciliation=True)
    side['source_id'] = snapshot.source_id
    return side, refs


def _contexts_from_references(db, row):
    contexts, refs = [], []
    seen = set()
    for reference in row.evidence:
        snapshot_id = reference.get('snapshot_id')
        if not snapshot_id or snapshot_id in seen:
            continue
        seen.add(snapshot_id)
        context, more = snapshot_context(db, snapshot_id, row.variant_id, row.created_at)
        refs.extend(more)
        if context.get('evidence_valid'):
            contexts.append(context)
    return contexts, refs


def _side(contexts, state, **extra):
    return {'source_contexts': deepcopy(contexts), 'state': state,
            'evidence_valid': bool(contexts), **deepcopy(extra)}


def _attach_relations(db, side, row, *, lifecycle=None, resolution=None, catalog=None):
    if not side.get('evidence_valid'):
        side['reviewed_contexts'] = []
        return []
    contexts = side.get('source_contexts', [side])
    reviewed, refs = [], []
    for context in contexts:
        if not context.get('evidence_valid'):
            continue
        values, more = _reviewed_contexts(db, context, 'tire', row.variant_id, row.created_at,
            lifecycle_override=lifecycle, resolution_override=resolution, catalog_override=catalog)
        reviewed.extend(values)
        refs.extend(more)
    side['reviewed_contexts'] = reviewed
    return refs


def _label(contexts, fallback):
    identity = (contexts[0].get('identity') or {}) if contexts else {}
    return ' '.join(str(identity.get(key) or '') for key in ('brand', 'model', 'size')).strip() or fallback


def freeze_curation(db, row):
    fact = db.get(FactVersion, row.base_fact_id)
    base, refs = snapshot_context(db, fact.snapshot_id, row.variant_id, row.created_at, fact) if fact else ({'evidence_valid': False}, [])
    valid = (base.get('evidence_valid') and fact.variant_id == row.variant_id and fact.source_id == row.source_id)
    source = deepcopy(fact.facts) if fact else {}
    effective = deepcopy(source)
    prior = db.scalars(select(ManualFactRevision).where(ManualFactRevision.variant_id == row.variant_id,
        ManualFactRevision.source_id == row.source_id, ManualFactRevision.revision < row.revision)
        .order_by(ManualFactRevision.revision)).all()
    heads = {item.field: item for item in prior}
    for field, item in heads.items():
        if item.base_fact_id != row.base_fact_id or item.action == 'clear_override':
            continue
        if item.action == 'manual_override':
            effective[field] = deepcopy(item.after['value'])
        elif item.action == 'revoke':
            effective.pop(field, None)
        refs.append(primary_reference('tire_curation_revision', item))
    field_value = lambda values: {'present': row.field in values, 'value': deepcopy(values.get(row.field))}
    valid = bool(valid and field_value(source) == row.source_before and field_value(effective) == row.before)
    prior_field = heads.get(row.field)
    before_state = ('source' if prior_field is None else 'cleared' if prior_field.action == 'clear_override'
        else 'needs_review' if prior_field.base_fact_id != row.base_fact_id
        else 'revoked' if prior_field.action == 'revoke' else 'manual_override')
    expected_after = (row.source_before if row.action == 'clear_override' else
                      {'present': False, 'value': None} if row.action == 'revoke' else
                      {'present': True, 'value': row.after.get('value')})
    valid = bool(valid and row.after == expected_after)
    before_curation = {'field': row.field}
    if prior_field:
        before_curation.update(action=prior_field.action, revision=prior_field.revision)
    before = {**deepcopy(base), 'facts': deepcopy(effective), 'source_facts': source,
        'state': before_state, 'curation': before_curation, 'evidence_valid': valid}
    if row.after['present']:
        effective[row.field] = deepcopy(row.after['value'])
    else:
        effective.pop(row.field, None)
    state = {'manual_override': 'manual_override', 'revoke': 'revoked', 'clear_override': 'cleared'}[row.action]
    after = {**deepcopy(base), 'facts': effective, 'source_facts': deepcopy(source), 'state': state,
        'curation': {'field': row.field, 'action': row.action, 'revision': row.revision}, 'evidence_valid': valid}
    for side in (before, after):
        refs.extend(_attach_relations(db, side, row))
    refs.append(primary_reference('tire_curation_revision', row))
    return _event('tire_curation', row, row.action, state, row.revision, row.variant_id,
                  _label([base], row.variant_id), before, after, refs, row.created_at)


def freeze_lifecycle(db, row):
    contexts, refs = _contexts_from_references(db, row)
    before, after = _side(contexts, row.before_state), _side(contexts, row.after_state)
    refs.extend(_attach_relations(db, before, row, lifecycle={'revision': row.revision - 1, 'state': row.before_state}))
    refs.extend(_attach_relations(db, after, row, lifecycle={'revision': row.revision, 'state': row.after_state}))
    refs.append(primary_reference('tire_lifecycle_event', row))
    payload = _event('tire_lifecycle', row, row.action, row.after_state, row.revision, row.variant_id,
                    _label(contexts, row.variant_id), before, after, refs, row.created_at)
    payload['changed_paths'] = ['state']
    payload['event_hash'] = digest({key: value for key, value in payload.items() if key != 'event_hash'})
    return payload


def _endpoint_contexts(db, endpoint, variant_id, asof):
    contexts, refs = [], []
    if not isinstance(endpoint, dict) or endpoint.get('id') != variant_id:
        return contexts, refs
    for item in endpoint.get('facts', []):
        fact = db.get(FactVersion, item.get('id'))
        if (fact is None or fact.variant_id != variant_id or fact.source_id != item.get('source_id')
                or fact.version != item.get('version') or fact.snapshot_id != item.get('snapshot_id')):
            contexts.append({'evidence_valid': False})
            continue
        context, more = snapshot_context(db, item.get('snapshot_id'), variant_id, asof, fact)
        refs.extend(more)
        contexts.append(context)
    return contexts, refs


def freeze_identity(db, row):
    valid = digest(row.binding) == row.binding_hash
    contexts, refs = _endpoint_contexts(db, row.binding.get('source'), row.variant_id, row.created_at)
    previous = db.scalar(select(IdentityRevision).where(IdentityRevision.variant_id == row.variant_id,
        IdentityRevision.revision == row.revision - 1))
    prior_state = 'independent' if previous is None else 'cleared' if previous.action == 'clear' else 'redirected'
    prior_mapping = {'revision': previous.revision, 'action': previous.action, 'target_id': previous.target_id,
                     'binding': deepcopy(previous.binding)} if previous else {'revision': 0, 'target_id': None}
    before_contexts, before_refs = (_endpoint_contexts(db, previous.binding.get('source'), row.variant_id, row.created_at)
                                   if previous else (contexts, []))
    refs.extend(before_refs)
    state = 'cleared' if row.action == 'clear' else 'redirected'
    before = _side(before_contexts, prior_state, identity_resolution=prior_mapping)
    after = _side(contexts, state, identity_resolution={'revision': row.revision, 'action': row.action,
        'target_id': row.target_id, 'binding': deepcopy(row.binding)})
    if not valid or previous and digest(previous.binding) != previous.binding_hash:
        before['evidence_valid'] = after['evidence_valid'] = False
    refs.extend(_attach_relations(db, before, row, resolution={'revision': row.revision - 1,
        'state': 'cleared' if previous and previous.action == 'clear' else 'blocked' if previous else 'independent'}))
    refs.extend(_attach_relations(db, after, row, resolution={'revision': row.revision,
        'state': 'cleared' if row.action == 'clear' else 'blocked'}))
    if previous:
        refs.append(primary_reference('tire_identity_revision', previous))
    # Target is a decision basis, never a condition-matching subject.
    if row.target_id:
        _, more = _endpoint_contexts(db, row.binding.get('target'), row.target_id, row.created_at)
        refs.extend(more)
    refs.append(primary_reference('tire_identity_revision', row))
    return _event('tire_identity', row, row.action, state, row.revision, row.variant_id,
                  _label(contexts, row.variant_id), before, after, refs, row.created_at)


def catalog_basis(db, verification, variant_id):
    snapshot = db.get(Snapshot, verification.snapshot_id)
    if snapshot is None:
        return None
    members = [(index, item) for index, item in enumerate(snapshot.parsed_variants)
               if isinstance(item, dict) and item.get('id') == variant_id]
    return {'snapshot_id': snapshot.id, 'raw_hash': snapshot.raw_hash, 'source_id': snapshot.source_id,
        'query_key': snapshot.query_key, 'source_url': snapshot.source_url,
        'identity_contract_version': snapshot.identity_contract_version,
        'parsed_variants_hash': digest(snapshot.parsed_variants),
        'verification_id': verification.id, 'verification_status': verification.status,
        'verified_at': timestamp(verification.verified_at), 'present': bool(members),
        'member_hash': digest(members[0][1]) if len(members) == 1 else None,
        'structured_locator': f'/parsed_variants/{members[0][0]}' if len(members) == 1 else None}


def _catalog_proof(db, row, verification_id, snapshot_id, present, side):
    if verification_id is None:
        return snapshot_id is None and not present and row.binding.get(side) is None
    proof = db.get(Verification, verification_id)
    snapshot = db.get(Snapshot, snapshot_id)
    if proof is None or snapshot is None:
        return False
    members = [item for item in snapshot.parsed_variants if isinstance(item, dict) and item.get('id') == row.variant_id]
    return (proof.snapshot_id == snapshot.id and proof.source_id == snapshot.source_id == row.source_id
        and proof.query_key == snapshot.query_key == row.query_key
        and proof.status in (('ok',) if side == 'after' else ('ok', 'not_modified'))
        and utc(proof.verified_at) <= utc(row.created_at)
        and utc(snapshot.observed_at) <= utc(proof.verified_at)
        and hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest() == snapshot.raw_hash
        and len(members) == (1 if present else 0)
        and catalog_basis(db, proof, row.variant_id) == row.binding.get(side))


def freeze_catalog(db, row):
    before_context, before_refs = (snapshot_context(db, row.previous_snapshot_id, row.variant_id, row.created_at)
                                  if row.before_present else ({'evidence_valid': False}, []))
    after_context, after_refs = (snapshot_context(db, row.snapshot_id, row.variant_id, row.created_at)
                                if row.after_present else ({'evidence_valid': False}, []))
    # Absence is proven by an accepted whole resource; it is not a fabricated member.
    present_context = after_context if row.after_present else before_context
    valid = bool(present_context.get('evidence_valid') and row.before_present != row.after_present
        and row.action == ('added' if row.after_present else 'removed')
        and _catalog_proof(db, row, row.verification_id, row.snapshot_id, row.after_present, 'after')
        and _catalog_proof(db, row, row.previous_verification_id, row.previous_snapshot_id, row.before_present, 'before'))
    before = _side([before_context] if row.before_present and before_context.get('evidence_valid') else [],
        'present' if row.before_present else 'absent', catalog_membership={'present': row.before_present})
    after = _side([after_context] if row.after_present and after_context.get('evidence_valid') else [],
        'present' if row.after_present else 'absent', catalog_membership={'present': row.after_present})
    # Valid absence still has no tire context. Matching can use the complete other side.
    before['evidence_valid'] = after['evidence_valid'] = valid
    refs = [*before_refs, *after_refs, primary_reference('tire_catalog_revision', row)]
    for side, include_current in ((before, False), (after, True)):
        refs.extend(_attach_relations(db, side, row, catalog={'source_id': row.source_id,
            'query_key': row.query_key, 'previous_verification_id': row.previous_verification_id,
            'verification_id': row.verification_id, 'include_current': include_current}))
    payload = _event('tire_catalog', row, row.action, after['state'], row.revision, row.variant_id,
        _label([present_context], row.variant_id), before, after, refs, row.created_at)
    payload['changed_paths'] = ['catalog_membership', 'state']
    payload['event_hash'] = digest({key: value for key, value in payload.items() if key != 'event_hash'})
    return payload


def freeze_validity(db, row):
    from .interest_applicability import freeze_applicability
    return freeze_applicability(db, row)


FREEZERS = {'tire_curation': freeze_curation, 'tire_lifecycle': freeze_lifecycle,
            'tire_identity': freeze_identity, 'tire_catalog': freeze_catalog, 'tire_curation_validity': freeze_validity}


def append_catalog(db, verification, previous):
    if verification.status != 'ok':
        return []
    snapshot = db.get(Snapshot, verification.snapshot_id)
    old_snapshot = db.get(Snapshot, previous.snapshot_id) if previous else None
    before = {item['id'] for item in old_snapshot.parsed_variants} if old_snapshot else set()
    after = {item['id'] for item in snapshot.parsed_variants}
    from .interest_events import publish
    rows = []
    for variant_id in sorted(before ^ after):
        existing = db.scalar(select(TireCatalogRevision).where(TireCatalogRevision.variant_id == variant_id,
            TireCatalogRevision.verification_id == verification.id))
        if existing:
            continue
        revision = db.scalar(select(func.max(TireCatalogRevision.revision)).where(
            TireCatalogRevision.variant_id == variant_id, TireCatalogRevision.source_id == verification.source_id,
            TireCatalogRevision.query_key == verification.query_key)) or 0
        row = TireCatalogRevision(id=uid(), variant_id=variant_id, source_id=verification.source_id,
            query_key=verification.query_key, verification_id=verification.id,
            previous_verification_id=previous.id if previous else None, snapshot_id=snapshot.id,
            previous_snapshot_id=old_snapshot.id if old_snapshot else None, revision=revision + 1,
            action='added' if variant_id in after else 'removed', before_present=variant_id in before,
            after_present=variant_id in after,
            binding={'before': catalog_basis(db, previous, variant_id) if previous else None,
                     'after': catalog_basis(db, verification, variant_id)}, created_at=verification.verified_at)
        db.add(row)
        db.flush()
        publish(db, 'tire_catalog', row, allow_indeterminate=True)
        rows.append(row)
    return rows


def register_governance_routes(app):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get('/v1/interest-evidence/{kind}/{record_id}')
    def original(kind: OriginalKind, record_id: str, mode: Literal['history'] = Query(...), db=Depends(get_db)):
        domain, model = KINDS[kind]
        row = db.get(model, record_id)
        if row is None:
            raise HTTPException(404, {'code': 'interest_evidence_not_found', 'message': '未找到该精确原始记录'})
        if kind == 'tire_curation_applicability_event':
            from .interest_applicability import validate_original
            if not validate_original(db, row):
                raise HTTPException(409, {'code': 'interest_evidence_mismatch', 'message': '派生原行、人工修订或来源依据不一致'})
        record = public_record(row)
        fingerprint = digest(record)
        stored = db.scalar(select(InterestEvent).where(InterestEvent.domain == domain, InterestEvent.origin_id == row.id))
        payload = stored.payload if stored else FREEZERS[domain](db, row)
        primary = next((item for item in payload['evidence'] if item['kind'] == kind and item['record_id'] == row.id), None)
        payload_hash = digest({key: value for key, value in payload.items() if key != 'event_hash'})
        if (primary is None or primary['fingerprint'] != fingerprint or primary['entity_id'] != row.variant_id
                or primary['revision'] != row.revision or payload['event_hash'] != payload_hash
                or stored and stored.event_hash != payload_hash):
            raise HTTPException(409, {'code': 'interest_evidence_mismatch', 'message': '原始记录与冻结指纹不一致'})
        return {'schema': 'interest-original-evidence@1', 'scope': 'local_workspace', 'data_state': 'local_snapshot',
            'kind': kind, 'record_id': row.id, 'entity_id': row.variant_id, 'revision': row.revision,
            'fingerprint': fingerprint, 'record': record, 'evidence': payload['evidence']}
