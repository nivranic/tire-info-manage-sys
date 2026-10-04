"""Evidence-bound logical resolution. Never rewrite a source identity or move facts."""
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator
from sqlalchemy import Text, cast, desc, func, select

from .auth import make_admin_guard
from .curation import EvidenceReference
from .db import FactVersion, Snapshot, TireVariant, VariantLifecycleEvent, uid
from .domain import StrictModel, digest, product_code_namespace
from .identity_contract import contract_context, contract_metadata
from .identity_models import IdentityRevision
from .service import QueryService, provenance, timestamp

NOTICE = '本地人工身份决定；不改写来源SKU、事实或旧引用，不迁移关注和监控，不代表厂商确认。'
IDENTITY_POLICY_VERSION = 'identity-resolution@2'


def fail(code, message, status=409):
    raise HTTPException(status, {'code': code, 'message': message})


def stable_identifier(field, value):
    """JSON facts can hold anything; only validated identifiers are merge anchors."""
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if field == 'manufacturer_product_code':
        return len(value) <= 100 and value.isprintable() and any(char.isalnum() for char in value)
    if not value.isascii() or not value.isdecimal():
        return False
    if field == 'eprel_id':
        return len(value) <= 12 and int(value) > 0
    if field == 'gtin' and len(value) in {8, 12, 13, 14}:
        # GS1 check digit, from the rightmost data digit with weight 3.
        total = sum(int(char) * (3 if index % 2 == 0 else 1) for index, char in enumerate(reversed(value[:-1])))
        return (10 - total % 10) % 10 == int(value[-1]) and any(char != '0' for char in value)
    return False


class IdentityPreviewRequest(StrictModel):
    mode: Literal['history']
    target_id: str | None = Field(default=None, min_length=1, max_length=64)


class IdentityDecision(IdentityPreviewRequest):
    action: Literal['correct', 'merge', 'clear']
    expected_revision: StrictInt = Field(ge=0)
    expected_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    operator: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=5, max_length=2000)
    field_reasons: dict[str, str] = Field(default_factory=dict, max_length=30)
    acknowledge_unknowns: StrictBool = False
    acknowledged: StrictBool
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=5)

    @field_validator('operator', 'reason')
    @classmethod
    def clean(cls, value):
        if any(ord(c) < 32 and c not in '\n\t' for c in value):
            raise ValueError('署名或理由包含无效字符')
        return value

    @model_validator(mode='after')
    def valid_action(self):
        if not self.acknowledged:
            raise ValueError('必须明确确认身份决定及其历史边界')
        if (self.action == 'clear') != (self.target_id is None):
            raise ValueError('更正/合并必须指定目标，撤回不得提供目标')
        if len({e.snapshot_id for e in self.evidence}) != len(self.evidence):
            raise ValueError('证据不能重复')
        if any(len(key) > 80 or not 5 <= len(value.strip()) <= 1000 for key, value in self.field_reasons.items()):
            raise ValueError('每个身份差异必须提供5–1000字说明')
        return self


def latest(db, variant_id):
    return db.scalar(select(IdentityRevision).where(IdentityRevision.variant_id == variant_id)
                     .order_by(desc(IdentityRevision.revision)).limit(1))


def endpoint(db, variant_id, context=None):
    if context is not None:
        value = context['endpoints'].get(variant_id)
        if value is None:
            fail('identity_variant_missing', '未找到精确轮胎版本', 404)
        return value
    variant = db.get(TireVariant, variant_id)
    if variant is None:
        fail('identity_variant_missing', '未找到精确轮胎版本', 404)
    ranks = select(FactVersion.id, FactVersion.source_id, FactVersion.version, FactVersion.snapshot_id,
        func.row_number().over(partition_by=FactVersion.source_id,
            order_by=FactVersion.version.desc()).label('n')).where(FactVersion.variant_id == variant_id).subquery()
    facts = [dict(row) for row in db.execute(select(ranks.c.id, ranks.c.source_id, ranks.c.version,
             ranks.c.snapshot_id).where(ranks.c.n == 1).order_by(ranks.c.source_id)).mappings()]
    lifecycle = db.scalar(select(VariantLifecycleEvent).where(VariantLifecycleEvent.variant_id == variant_id)
                          .order_by(desc(VariantLifecycleEvent.revision)).limit(1))
    return {'id': variant_id, 'identity': variant.identity, 'identity_status': variant.identity_status,
            'identity_contract': contract_metadata(db, variant_id),
            'facts': facts, 'lifecycle': {'revision': lifecycle.revision if lifecycle else 0,
                'state': lifecycle.after_state if lifecycle else 'active'}}


def binding_context(db, events, contracts=None):
    """Load current bindings once per call, without retaining a cross-request cache."""
    pending = [row for row in events if row is not None and row.action != 'clear']
    ids = {row.variant_id for row in pending} | {row.target_id for row in pending if row.target_id}
    context = {'endpoints': {}, 'target_revisions': {}}
    if not ids:
        return context
    contracts = contracts if contracts is not None else contract_context(db, ids)
    for row in db.execute(select(TireVariant.id, TireVariant.identity, TireVariant.identity_status)
                          .where(TireVariant.id.in_(ids))).mappings():
        context['endpoints'][row['id']] = {**row,
            'identity_contract': contract_metadata(db, row['id'], context=contracts),
            'facts': [], 'lifecycle': {'revision': 0, 'state': 'active'}}
    ranks = select(FactVersion.id, FactVersion.variant_id, FactVersion.source_id, FactVersion.version,
        FactVersion.snapshot_id, func.row_number().over(
            partition_by=(FactVersion.variant_id, FactVersion.source_id),
            order_by=FactVersion.version.desc()).label('n')).where(FactVersion.variant_id.in_(ids)).subquery()
    facts = db.execute(select(ranks.c.id, ranks.c.variant_id, ranks.c.source_id, ranks.c.version,
        ranks.c.snapshot_id).where(ranks.c.n == 1).order_by(ranks.c.variant_id, ranks.c.source_id)).mappings()
    for row in facts:
        context['endpoints'][row['variant_id']]['facts'].append(
            {key: row[key] for key in ('id', 'source_id', 'version', 'snapshot_id')})
    lifecycles = select(VariantLifecycleEvent.variant_id, VariantLifecycleEvent.revision,
        VariantLifecycleEvent.after_state, func.row_number().over(partition_by=VariantLifecycleEvent.variant_id,
            order_by=VariantLifecycleEvent.revision.desc()).label('n'))\
        .where(VariantLifecycleEvent.variant_id.in_(ids)).subquery()
    for row in db.execute(select(lifecycles.c.variant_id, lifecycles.c.revision, lifecycles.c.after_state)
                          .where(lifecycles.c.n == 1)).mappings():
        context['endpoints'][row['variant_id']]['lifecycle'] = {'revision': row['revision'], 'state': row['after_state']}
    targets = {row.target_id for row in pending if row.target_id}
    if targets:
        context['target_revisions'] = dict(db.execute(select(IdentityRevision.variant_id,
            func.max(IdentityRevision.revision)).where(IdentityRevision.variant_id.in_(targets))
            .group_by(IdentityRevision.variant_id)).all())
    return context


def binding(db, variant_id, target_id, context=None):
    if context is None:
        target_revision = latest(db, target_id) if target_id else None
        revision = target_revision.revision if target_revision else 0
    else:
        revision = context['target_revisions'].get(target_id, 0)
    return {'policy_version': IDENTITY_POLICY_VERSION, 'source': endpoint(db, variant_id, context),
            'target': endpoint(db, target_id, context) if target_id else None,
            'target_resolution_revision': revision}


def summary(db, row, context=None):
    if row is None:
        return {'state': 'independent', 'revision': 0, 'target_id': None, 'event_id': None}
    current = row.action == 'clear' or digest(binding(db, row.variant_id, row.target_id, context)) == row.binding_hash
    return {'state': 'cleared' if row.action == 'clear' else 'redirected' if current else 'needs_review',
            'revision': row.revision, 'target_id': row.target_id, 'event_id': row.id, 'action': row.action,
            'changed_at': timestamp(row.created_at), 'notice': NOTICE}


def annotate_identities(db, rows):
    """Called only after successful live/304, explicit history or valid fallback consent."""
    ids = list({row['id'] for row in rows})
    if not ids:
        return rows
    ranks = select(IdentityRevision.variant_id, func.max(IdentityRevision.revision).label('revision'))\
        .where(IdentityRevision.variant_id.in_(ids)).group_by(IdentityRevision.variant_id).subquery()
    events = db.scalars(select(IdentityRevision).join(ranks,
        (IdentityRevision.variant_id == ranks.c.variant_id) & (IdentityRevision.revision == ranks.c.revision))).all()
    contracts = contract_context(db, set(ids) | {row.target_id for row in events if row.target_id})
    context = binding_context(db, events, contracts)
    states = {row.variant_id: summary(db, row, context) for row in events}
    return [{**row, 'identity_contract': contract_metadata(db, row['id'], context=contracts),
             **({'identity_resolution': states[row['id']]} if row['id'] in states else {})} for row in rows]


def blocked_variant_ids(db):
    ranks = select(IdentityRevision.variant_id, func.max(IdentityRevision.revision).label('revision'))\
        .group_by(IdentityRevision.variant_id).subquery()
    return set(db.scalars(select(IdentityRevision.variant_id).join(ranks,
        (IdentityRevision.variant_id == ranks.c.variant_id) & (IdentityRevision.revision == ranks.c.revision))
        .where(IdentityRevision.action != 'clear')))


def require_ai_identity(db, variant_ids):
    require_current_contracts(db, variant_ids)
    for row in annotate_identities(db, [{'id': key} for key in set(variant_ids)]):
        if row.get('identity_resolution', {}).get('state') in {'redirected', 'needs_review'}:
            fail('identity_review_required', '所选版本有本地身份更正/合并或待复核决定，请先核对并明确选择目标版本；未替换或外发证据')


def require_current_contracts(db, variant_ids):
    ids = set(variant_ids)
    context = contract_context(db, ids)
    for variant_id in ids:
        if contract_metadata(db, variant_id, context=context)['state'] != 'current':
            fail('identity_contract_review_required', '所选精确SKU的编码命名空间尚未完成核对；未自动映射或外发证据')


def serialize(row):
    return {key: getattr(row, key) for key in ('id', 'variant_id', 'target_id', 'revision', 'action', 'binding',
        'binding_hash', 'differences', 'field_reasons', 'acknowledged_unknowns', 'evidence', 'operator', 'reason')} | {
        'created_at': timestamp(row.created_at)}


def review(db, variant_id):
    source = endpoint(db, variant_id)
    records = db.scalars(select(IdentityRevision).where(IdentityRevision.variant_id == variant_id)
                        .order_by(desc(IdentityRevision.revision)).limit(101)).all()
    incoming_ranks = select(IdentityRevision.variant_id, func.max(IdentityRevision.revision).label('revision'))\
        .group_by(IdentityRevision.variant_id).subquery()
    incoming = db.scalars(select(IdentityRevision).join(incoming_ranks,
        (IdentityRevision.variant_id == incoming_ranks.c.variant_id) &
        (IdentityRevision.revision == incoming_ranks.c.revision))
        .where(IdentityRevision.target_id == variant_id, IdentityRevision.action != 'clear')
        .order_by(IdentityRevision.variant_id).limit(101)).all()
    context = binding_context(db, records[:1] + incoming[:100])
    return {'data_state': 'local_snapshot', 'scope': 'local_workspace', 'source': source,
            'resolution': summary(db, records[0] if records else None, context),
            'history': [serialize(row) for row in records[:100]], 'history_truncated': len(records) > 100,
            'incoming': [{'variant_id': row.variant_id, **summary(db, row, context)} for row in incoming[:100]],
            'incoming_truncated': len(incoming) > 100, 'notice': NOTICE}


def preview(db, variant_id, target_id):
    if target_id == variant_id:
        fail('identity_self_target', '不能指向自身', 422)
    bound = binding(db, variant_id, target_id)
    source, target = bound['source'], bound['target']
    previous = latest(db, variant_id)
    target_decision = latest(db, target_id) if target_id else None
    differences, unknowns, anchors, contradictions = [], [], [], []
    if target:
        source_identity = source['identity_contract']['current_identity'] or source['identity']
        target_identity = target['identity_contract']['current_identity'] or target['identity']
        for key in sorted(source_identity.keys() | target_identity.keys()):
            left, right = source_identity.get(key), target_identity.get(key)
            if left is None or right is None:
                unknowns.append(key)
            # JSON identity preserves types, including inside lists/dicts: Python
            # equality otherwise treats true as 1 and false as 0.
            different = digest(left) != digest(right) or (key in source_identity) != (key in target_identity)
            if different:
                differences.append({'field': key, 'before': {'present': key in source_identity, 'value': left},
                                    'after': {'present': key in target_identity, 'value': right}})
                if left is not None and right is not None:
                    contradictions.append(key)
            if key in {'manufacturer_product_code', 'gtin', 'eprel_id'} and stable_identifier(key, left) and not different:
                if key != 'manufacturer_product_code':
                    anchors.append(key)
                else:
                    try:
                        left_type = product_code_namespace(source_identity.get('product_code_type'))
                        right_type = product_code_namespace(target_identity.get('product_code_type'))
                    except ValueError:
                        left_type = right_type = None
                    if left_type is not None and left_type == right_type:
                        anchors.append(key)
    blockers = []
    if target and any(item['identity_contract']['state'] != 'current' for item in (source, target)):
        blockers.append('identity_contract_review_required')
    if not source['facts'] or (target and not target['facts']):
        blockers.append('accepted_evidence_required')
    if target and any(item['lifecycle']['state'] != 'active' for item in (source, target)):
        blockers.append('active_variants_required')
    if target_decision and target_decision.action != 'clear':
        blockers.append('target_has_identity_decision')
    if not target and (previous is None or previous.action == 'clear'):
        blockers.append('nothing_to_clear')
    revision = previous.revision if previous else 0
    return {'data_state': 'local_snapshot', 'binding': bound, 'revision': revision,
            'fingerprint': digest({'binding': bound, 'revision': revision}), 'differences': differences,
            'unknown_fields': unknowns, 'stable_anchors': anchors, 'known_contradictions': contradictions,
            'blockers': blockers, 'can_merge': bool(target and anchors and not contradictions and not blockers),
            'can_correct': bool(target and differences and not blockers), 'can_clear': not target and not blockers,
            'notice': NOTICE}


def append_decision(db, variant_id, payload, session_id, idempotency_key):
    try:
        key = str(UUID(idempotency_key))
    except (ValueError, TypeError, AttributeError):
        fail('invalid_idempotency_key', '请提供固定UUID请求标识', 422)
    shared = QueryService(db, None)
    shared.lock_ingestion()
    request_hash = digest({'variant_id': variant_id, 'payload': payload.model_dump()})
    previous = db.scalar(select(IdentityRevision).where(IdentityRevision.actor_session_id == session_id,
                         IdentityRevision.idempotency_key == key))
    if previous:
        if previous.request_hash != request_hash:
            fail('idempotency_payload_mismatch', '同一UUID已绑定不同的身份操作')
        return {'event': serialize(previous), 'review': review(db, variant_id), 'idempotent_replay': True}
    proposed = preview(db, variant_id, payload.target_id)
    if payload.expected_revision != proposed['revision'] or payload.expected_fingerprint != proposed['fingerprint']:
        fail('identity_revision_conflict', '身份、来源事实或版本状态已变化，请重新读取并核对')
    if not proposed['can_' + payload.action]:
        fail('identity_gate_failed', '该身份操作不符合预览约束，请核对差异、目标状态及稳定标识')
    expected_fields = {item['field'] for item in proposed['differences']}
    if set(payload.field_reasons) != expected_fields:
        fail('identity_field_reasons_required', '必须逐项解释全部身份差异，不得增加无关字段', 422)
    if proposed['unknown_fields'] and not payload.acknowledge_unknowns:
        fail('identity_unknown_acknowledgement_required', '双方存在未知身份字段，须明确确认；未知不能自动当作无', 422)
    required = {variant_id} | ({payload.target_id} if payload.target_id else set())
    covered, evidence = set(), []
    for reference in payload.evidence:
        snapshot = db.get(Snapshot, reference.snapshot_id)
        matches = required & {row.get('id') for row in snapshot.parsed_variants} if snapshot else set()
        if not matches or len(reference.locator.strip()) < 3:
            fail('identity_evidence_mismatch', '证据须是包含本次双方精确版本的已采纳快照及可核对位置', 422)
        covered |= matches
        evidence.append({**provenance(snapshot), 'locator': reference.locator.strip(), 'variant_ids': sorted(matches)})
    if covered != required:
        fail('identity_evidence_incomplete', '证据必须分别覆盖来源和目标精确版本', 422)
    row = IdentityRevision(id=uid(), variant_id=variant_id, target_id=payload.target_id,
        revision=proposed['revision'] + 1, action=payload.action, binding=proposed['binding'],
        binding_hash=digest(proposed['binding']), differences=proposed['differences'],
        field_reasons={key: value.strip() for key, value in payload.field_reasons.items()},
        acknowledged_unknowns=payload.acknowledge_unknowns, evidence=evidence,
        operator=payload.operator, reason=payload.reason, actor_session_id=session_id,
        idempotency_key=key, request_hash=request_hash)
    db.add(row)
    shared.audit(session_id, 'identity_resolution_changed', variant_id=variant_id, target_id=payload.target_id,
                 revision=row.revision, event_id=row.id, action_kind=row.action)
    db.commit()
    return {'event': serialize(row), 'review': review(db, variant_id), 'idempotent_replay': False}


def resolve_comparison_ids(db, ids):
    require_current_contracts(db, ids)
    result, mappings = [], []
    for row in annotate_identities(db, [{'id': key} for key in ids]):
        state = row.get('identity_resolution', {})
        if state.get('state') == 'needs_review':
            fail('identity_review_required', '所选身份决定已过期，请先复核；未自动沿用旧目标')
        target = state['target_id'] if state.get('state') == 'redirected' else row['id']
        mappings.append({'requested_id': row['id'], 'resolved_id': target,
                         'revision': state.get('revision', 0), 'event_id': state.get('event_id')})
        if target not in result:
            result.append(target)
    require_current_contracts(db, result)
    return result, mappings


def register_identity_routes(app):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    admin_guard = make_admin_guard(get_db)

    @app.get('/v1/identity-candidates')
    def candidates(mode: Literal['history'] = Query(...), q: str = Query('', max_length=120),
                   offset: int = Query(0, ge=0, le=100000), db=Depends(get_db)):
        statement = select(TireVariant).where(select(FactVersion.id).where(FactVersion.variant_id == TireVariant.id).exists())
        if q.strip():
            escaped = q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            statement = statement.where(cast(TireVariant.identity, Text).ilike('%' + escaped + '%', escape='\\'))
        total = db.scalar(select(func.count()).select_from(statement.subquery()))
        rows = db.scalars(statement.order_by(desc(TireVariant.created_at), TireVariant.id).offset(offset).limit(20)).all()
        return {'data_state': 'local_snapshot', 'items': annotate_identities(db, [
            {'id': row.id, 'identity': row.identity, 'identity_status': row.identity_status} for row in rows]),
            'total': total, 'offset': offset, 'limit': 20}

    @app.get('/v1/tire-variants/{variant_id}/identity-resolution')
    def read(variant_id: str, mode: Literal['history'] = Query(...), db=Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        result = review(db, variant_id)
        db.commit()
        return result

    @app.post('/v1/tire-variants/{variant_id}/identity-preview')
    def proposed(variant_id: str, payload: IdentityPreviewRequest, db=Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        result = preview(db, variant_id, payload.target_id)
        db.commit()
        return result

    @app.post('/v1/tire-variants/{variant_id}/identity-revisions', status_code=201, dependencies=[Depends(admin_guard)])
    def decide(variant_id: str, payload: IdentityDecision, request: Request,
               idempotency_key: str = Header(alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return append_decision(db, variant_id, payload, request.state.session_id, idempotency_key)
