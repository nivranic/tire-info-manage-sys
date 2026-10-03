"""Local evidence relations: vehicle requirements and tire facts retain distinct roles."""
from copy import deepcopy
import hashlib
from typing import Literal
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, Request
from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator
from sqlalchemy import Text, cast, desc, func, select

from .db import FactVersion, Snapshot, TireVariant, VariantLifecycleEvent, Verification, uid
from .domain import IDENTITY_CONTRACT_VERSION, StrictModel, VariantInput, digest
from .fitment_relation_models import FitmentRelation, FitmentRelationRevision
from .identity_models import IdentityRevision
from .identity_contract import contract_metadata
from .service import QueryService, business_facts, provenance, timestamp
from .vehicles import VehicleSnapshot, VehicleVerification, vehicle_provenance

NOTICE = '本地共享工作区的人工候选/复核关系；不代表官方原配认证，不改写车型要求、轮胎事实、车库或关注。'
OFFICIAL_OE = {'state': 'not_established', 'missing_evidence': [
    '缺少由官方证据明确连接此车型代际、年款、市场、配置、轮毂及轴位与此精确SKU的跨侧桥接记录',
    '尺寸或型号相同、人工复核和轮胎侧OE标记均不能单独确立官方原配']}
BASE = {'data_state': 'local_snapshot', 'scope': 'local_workspace'}
BLOCKER_MESSAGES = {
    'fixed_relation_scope_mismatch': '关系固定的车型、代际、年款、市场、配置、轮毂或轴位不一致，请另建关系',
    'revise_required_for_changed_selection': '更换SKU或证据须先追加修订',
    'already_revoked': '关系已撤销', 'relation_not_revoked': '关系尚未撤销，无需恢复',
    'restore_required': '关系已撤销，须先核对并恢复为待复核候选',
    'wheel_option_unavailable': '车型来源明确标记该轮毂项不可用',
    'current_wheel_option_unavailable': '当前车型来源明确标记该轮毂项不可用',
    'vehicle_evidence_stale': '所选车型证据已不符合当前事实或范围，请选取对应的新证据',
    'tire_evidence_stale': '所选SKU事实版本已变化，请选取对应的新证据',
    'tire_catalog_membership_changed': '精确SKU已不在某个关联来源的当前目录中',
    'tire_lifecycle_revoked': '精确SKU已被本地撤销',
    'tire_identity_review_required': '精确SKU存在身份转向或待复核决定；不会自动替换为目标SKU',
    'identity_contract_review_required': '精确SKU编码命名空间尚未完成核对，不能据旧混合身份建立新关系',
}
FIELD_NAMES = {'size': '尺寸（R与ZR分别核对）', 'load_index': '载重指数', 'speed_rating': '速度级别',
               'manufacturer_product_code': '制造商产品代码', 'product_code_type': '产品代码类型',
               'oe_mark': 'OE标记', 'region': '市场/地区',
               'xl': 'XL', 'hl': 'HL', 'acoustic_technology': '静音技术', 'run_flat': '缺气保用'}


def verify_raw(snapshot):
    if hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest() != snapshot.raw_hash:
        fail('evidence_raw_hash_mismatch', '来源原文与已记录哈希不一致，不能用于关系证据', 422)


def fail(code, message, status=409):
    raise HTTPException(status, {'code': code, 'message': message})


class RelationSelection(StrictModel):
    vehicle_id: str = Field(min_length=1, max_length=80)
    vehicle_snapshot_id: str = Field(min_length=1, max_length=64)
    trim_id: str = Field(min_length=1, max_length=120)
    wheel_option_id: str = Field(min_length=1, max_length=64)
    axle: Literal['front', 'rear']
    variant_id: str = Field(min_length=1, max_length=64)
    tire_snapshot_id: str = Field(min_length=1, max_length=64)
    fact_version_id: str = Field(min_length=1, max_length=64)


class RelationPreviewRequest(StrictModel):
    mode: Literal['history']
    action: Literal['create', 'revise', 'review', 'revoke', 'restore']
    relation_id: str | None = Field(default=None, min_length=1, max_length=64)
    selection: RelationSelection

    @model_validator(mode='after')
    def correct_target(self):
        if (self.action == 'create') != (self.relation_id is None):
            raise ValueError('创建不得指定已有关系；其余操作必须指定关系')
        return self


class RelationDecision(RelationPreviewRequest):
    expected_revision: StrictInt = Field(ge=0)
    expected_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    operator: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=5, max_length=2000)
    acknowledged: StrictBool
    acknowledge_unknowns: StrictBool = False

    @field_validator('operator', 'reason')
    @classmethod
    def meaningful(cls, value):
        if any(ord(c) < 32 and c not in '\n\t' for c in value):
            raise ValueError('署名和原因包含无效字符')
        return value

    @field_validator('acknowledged')
    @classmethod
    def explicit_acknowledgement(cls, value):
        if not value:
            raise ValueError('必须明确确认人工关系及非官方原配边界')
        return value


def accepted_vehicle(db, snapshot_id):
    row = db.get(VehicleSnapshot, snapshot_id)
    accepted = row and db.scalar(select(VehicleVerification.id).where(
        VehicleVerification.snapshot_id == row.id, VehicleVerification.vehicle_id == row.vehicle_id).limit(1))
    if not accepted:
        fail('vehicle_snapshot_not_accepted', '必须选择正式已采纳的车型快照', 422)
    verify_raw(row)
    return row


def accepted_tire(db, snapshot_id):
    row = db.get(Snapshot, snapshot_id)
    accepted = row and db.scalar(select(Verification.id).where(Verification.snapshot_id == row.id,
        Verification.source_id == row.source_id, Verification.query_key == row.query_key).limit(1))
    if not accepted:
        fail('tire_snapshot_not_accepted', '必须选择正式已采纳的轮胎快照', 422)
    verify_raw(row)
    return row


def latest_vehicle(db, vehicle_id):
    return db.scalar(select(VehicleSnapshot).join(VehicleVerification,
        VehicleVerification.snapshot_id == VehicleSnapshot.id).where(
        VehicleVerification.vehicle_id == vehicle_id, VehicleSnapshot.vehicle_id == vehicle_id)
        .order_by(desc(VehicleVerification.verified_at), desc(VehicleVerification.id)).limit(1))


def vehicle_parts(snapshot, selected):
    payload = snapshot.payload
    if snapshot.vehicle_id != selected.vehicle_id or payload['vehicle'].get('id') != selected.vehicle_id:
        fail('vehicle_snapshot_scope_mismatch', '车型证据不能借用另一车型或代际', 422)
    fits = [(index, fit) for index, fit in enumerate(payload.get('fitments', []))
            if fit.get('id') == selected.wheel_option_id]
    trims = [trim for trim in payload.get('trims', []) if trim.get('id') == selected.trim_id]
    if len(fits) != 1 or len(trims) != 1:
        fail('vehicle_fitment_missing', '所选快照没有唯一对应的配置和轮毂项', 422)
    index, fit = fits[0]
    if fit.get('trim_id') != selected.trim_id or selected.wheel_option_id not in trims[0].get('wheel_option_ids', []):
        fail('vehicle_trim_scope_mismatch', '轮毂项不属于所选配置，不能跨配置借用', 422)
    if not isinstance(fit.get(selected.axle), dict):
        fail('vehicle_axle_missing', '来源没有所选轴位的独立要求', 422)
    return index, trims[0], fit


def fixed_scope(snapshot, trim, selected):
    vehicle = snapshot.payload['vehicle']
    return {'vehicle_id': selected.vehicle_id, 'generation': vehicle.get('generation'),
            'model_year': vehicle.get('model_year'), 'region': vehicle.get('region'),
            'source_vehicle_id': vehicle.get('source_vehicle_id'), 'trim_id': selected.trim_id,
            'trim_model_year': trim.get('model_year'), 'wheel_option_id': selected.wheel_option_id,
            'axle': selected.axle}


def frozen_evidence(db, selected):
    vehicle = accepted_vehicle(db, selected.vehicle_snapshot_id)
    index, trim, fit = vehicle_parts(vehicle, selected)
    tire = accepted_tire(db, selected.tire_snapshot_id)
    matches = [(i, item) for i, item in enumerate(tire.parsed_variants) if item.get('id') == selected.variant_id]
    variant = db.get(TireVariant, selected.variant_id)
    fact = db.get(FactVersion, selected.fact_version_id)
    if len(matches) != 1 or variant is None:
        fail('tire_variant_evidence_mismatch', '轮胎证据必须包含所选精确SKU，不能只凭同型号或同尺寸', 422)
    tire_index, item = matches[0]
    try:
        parsed = VariantInput.model_validate({key: value for key, value in item.items()
                                             if key in VariantInput.model_fields})
    except (ValueError, TypeError):
        fail('tire_identity_evidence_mismatch', '历史快照中的精确SKU身份字段无效', 422)
    contract = contract_metadata(db, selected.variant_id)
    if tire.identity_contract_version == IDENTITY_CONTRACT_VERSION:
        parsed_identity = parsed.identity()
        expected_identity = contract['current_identity']
        parsed_key, parsed_status = parsed.identity_key(tire.source_id, tire.query_key, tire_index)
        expected_key, expected_status = contract['current_key'], contract['identity_status']
    elif tire.identity_contract_version in {None, 'variant-identity@1'}:
        parsed_identity = parsed.legacy_identity()
        expected_identity = variant.identity
        parsed_key, parsed_status = parsed.legacy_identity_key(tire.source_id, tire.query_key, tire_index)
        expected_key, expected_status = variant.identity_key, variant.identity_status
    else:
        fail('tire_identity_contract_unsupported', '所选历史证据的身份合同版本无法验证', 422)
    if (expected_identity is None or digest(parsed_identity) != digest(expected_identity)
            or parsed_key != expected_key or parsed_status != expected_status
            or item.get('identity_key') != expected_key or item.get('identity_status') != expected_status):
        fail('tire_identity_evidence_mismatch', '快照内精确SKU身份与已存身份不一致', 422)
    if contract['state'] == 'current' and (digest(parsed.identity()) != digest(contract['current_identity'])
            or parsed.identity_key(tire.source_id, tire.query_key, tire_index)[0] != contract['current_key']):
        fail('tire_identity_evidence_mismatch', '历史证据与当前权威身份绑定不一致', 422)
    # A metadata-only snapshot legitimately points back to a prior FactVersion.
    # Do not require fact.snapshot_id == tire.id, or invent a new fact version.
    if (fact is None or fact.variant_id != selected.variant_id or fact.source_id != tire.source_id
            or fact.version != item.get('fact_version')
            or fact.facts_hash != digest(business_facts(item.get('facts', {})))):
        fail('tire_fact_evidence_mismatch', '事实版本必须对应所选快照中的精确SKU、来源与参数版本', 422)
    vehicle_evidence = {'role': 'vehicle_requirement', 'vehicle': deepcopy(vehicle.payload['vehicle']),
        'trim': deepcopy(trim), 'wheel': deepcopy(fit), 'axle': selected.axle,
        'requirements': deepcopy(fit[selected.axle]), 'fact_version': vehicle.fact_version,
        'fact_hash': vehicle.fact_hash, 'provenance': vehicle_provenance(vehicle),
        'structured_locator': {'kind': 'vehicle_snapshot_payload', 'json_pointer': f'/fitments/{index}/{selected.axle}',
            'snapshot_id': vehicle.id, 'fitment_index': index, 'wheel_option_id': fit['id'], 'axle': selected.axle},
        'source_locator_marker': fit.get('evidence_locator'),
        'source_locator_notice': '来源位置标记；未宣称自动解析该标记的原文语义'}
    tire_evidence = {'role': 'tire_sku_fact', 'variant_id': variant.id, 'identity': deepcopy(parsed_identity),
        'identity_contract_version': tire.identity_contract_version, 'identity_contract': contract,
        'identity_status': variant.identity_status, 'facts': deepcopy(fact.facts),
        'fact_version_id': fact.id, 'fact_version': fact.version, 'facts_hash': fact.facts_hash,
        'provenance': provenance(tire), 'query_key': tire.query_key,
        'structured_locator': {'kind': 'tire_snapshot_parsed_variants',
            'json_pointer': f'/parsed_variants/{tire_index}', 'snapshot_id': tire.id,
            'variant_index': tire_index, 'variant_id': variant.id},
        'source_locator_markers': deepcopy(item.get('facts', {}).get('evidence_spans', [])),
        'source_locator_notice': '来源位置标记；未宣称自动解析该标记的原文语义'}
    return vehicle_evidence, tire_evidence, fixed_scope(vehicle, trim, selected)


def current_binding(db, selected):
    vehicle = latest_vehicle(db, selected.vehicle_id)
    scope = None
    if vehicle:
        try:
            _, trim, fit = vehicle_parts(vehicle, selected)
            scope = {**fixed_scope(vehicle, trim, selected), 'availability': fit.get('availability'),
                     'requirements': fit[selected.axle]}
        except HTTPException:
            pass
    variant = db.get(TireVariant, selected.variant_id)
    contract = contract_metadata(db, selected.variant_id) if variant else None
    ranked = select(FactVersion.id, FactVersion.version, FactVersion.source_id, FactVersion.facts_hash, func.row_number().over(
        partition_by=FactVersion.source_id, order_by=FactVersion.version.desc()).label('n'))\
        .where(FactVersion.variant_id == selected.variant_id).subquery()
    facts = [dict(row) for row in db.execute(select(ranked.c.id, ranked.c.version, ranked.c.source_id, ranked.c.facts_hash)
             .where(ranked.c.n == 1).order_by(ranked.c.source_id)).mappings()]
    lifecycle = db.scalar(select(VariantLifecycleEvent).where(VariantLifecycleEvent.variant_id == selected.variant_id)
                          .order_by(desc(VariantLifecycleEvent.revision)).limit(1))
    identity = db.scalar(select(IdentityRevision).where(IdentityRevision.variant_id == selected.variant_id)
                         .order_by(desc(IdentityRevision.revision)).limit(1))
    # Track memberships only in catalogs that have actually contained this SKU.
    # Transport validators, raw hashes, parser locators and observation times do
    # not participate in semantic staleness.
    catalogs = set()
    accepted = select(Snapshot).where(cast(Snapshot.parsed_variants, Text).contains(selected.variant_id, autoescape=True),
        select(Verification.id).where(Verification.snapshot_id == Snapshot.id,
        Verification.source_id == Snapshot.source_id, Verification.query_key == Snapshot.query_key).exists())
    for snapshot in db.scalars(accepted):
        if any(item.get('id') == selected.variant_id for item in snapshot.parsed_variants):
            catalogs.add((snapshot.source_id, snapshot.query_key))
    memberships = []
    for source, query in sorted(catalogs):
        history = db.scalars(select(Snapshot).join(Verification, Verification.snapshot_id == Snapshot.id)
            .where(Verification.source_id == source, Verification.query_key == query,
                   Snapshot.source_id == source, Snapshot.query_key == query)
            .order_by(Verification.verified_at, Verification.id))
        present, transition_revision = None, 0
        for snapshot in history:
            next_present = any(item.get('id') == selected.variant_id for item in snapshot.parsed_variants)
            if present != next_present:
                transition_revision += 1
            present = next_present
        memberships.append({'source_id': source, 'query_key': query,
                            'present': present, 'transition_revision': transition_revision})
    return {'vehicle': {'fact_hash': vehicle.fact_hash if vehicle else None,
                        'fact_version': vehicle.fact_version if vehicle else None, 'scope': scope},
        'tire': {'variant_id': selected.variant_id,
            'identity': (contract['current_identity'] or variant.identity) if variant else None,
            'identity_contract': contract,
            'identity_status': variant.identity_status if variant else None, 'facts': facts, 'catalogs': memberships,
            'lifecycle': {'revision': lifecycle.revision if lifecycle else 0,
                          'state': lifecycle.after_state if lifecycle else 'active'},
            'identity_resolution': {'revision': identity.revision if identity else 0,
                'state': 'independent' if identity is None else 'cleared' if identity.action == 'clear' else 'blocked',
                'target_id': identity.target_id if identity else None}}}


def technical_checks(vehicle, tire):
    requirements, identity = vehicle['requirements'], tire['identity']
    result = []
    for field in ('size', 'load_index', 'speed_rating', 'manufacturer_product_code', 'product_code_type', 'oe_mark',
                  'region', 'xl', 'hl', 'acoustic_technology', 'run_flat'):
        left = vehicle['vehicle'].get('region') if field == 'region' else requirements.get(field)
        right = identity.get(field)
        if field in {'xl', 'hl', 'acoustic_technology', 'run_flat'} and left is None:
            status = 'not_declared'
        elif left is None or right is None or left == '' or right == '':
            status = 'unknown'
        else:
            status = 'match' if digest(left) == digest(right) else 'conflict'
        result.append({'field': field, 'status': status, 'vehicle_value': left, 'tire_value': right})
    return result


def latest_revision(db, relation_id):
    return db.scalar(select(FitmentRelationRevision).where(FitmentRelationRevision.relation_id == relation_id)
                     .order_by(desc(FitmentRelationRevision.revision)).limit(1))


def load_relation(db, relation_id):
    relation = db.get(FitmentRelation, relation_id)
    previous = latest_revision(db, relation_id) if relation else None
    if relation is None or previous is None:
        fail('fitment_relation_missing', '未找到独立车型轴位关系', 404)
    return relation, previous


def stale_reasons(before, current):
    reasons = []
    if digest(before.get('vehicle')) != digest(current['vehicle']):
        reasons.append('vehicle_facts_or_scope_changed')
    for key in ('identity', 'identity_status', 'identity_contract', 'facts', 'catalogs', 'lifecycle', 'identity_resolution'):
        if digest(before.get('tire', {}).get(key)) != digest(current['tire'].get(key)):
            reasons.append('tire_' + key + '_changed')
    return reasons


def preview(db, payload):
    selected = payload.selection
    relation, previous = load_relation(db, payload.relation_id) if payload.relation_id else (None, None)
    vehicle, tire, scope = frozen_evidence(db, selected)
    binding = current_binding(db, selected)
    checks = technical_checks(vehicle, tire)
    blockers = []
    if relation and digest(scope) != digest(relation.scope):
        blockers.append('fixed_relation_scope_mismatch')
    if previous:
        if payload.action in {'review', 'revoke', 'restore'} and selected.model_dump() != previous.selection:
            blockers.append('revise_required_for_changed_selection')
        if payload.action == 'revoke' and previous.review_state == 'revoked':
            blockers.append('already_revoked')
        if payload.action == 'restore' and previous.review_state != 'revoked':
            blockers.append('relation_not_revoked')
        if payload.action == 'review' and previous.review_state == 'revoked':
            blockers.append('restore_required')
    if payload.action != 'revoke':
        if binding['tire']['identity_contract']['state'] != 'current':
            blockers.append('identity_contract_review_required')
        blockers.extend('conflict_' + item['field'] for item in checks if item['status'] == 'conflict')
        if vehicle['wheel'].get('availability') == 'unavailable':
            blockers.append('wheel_option_unavailable')
        current_vehicle = binding['vehicle']
        if current_vehicle['scope'] is None or vehicle['fact_hash'] != current_vehicle['fact_hash']:
            blockers.append('vehicle_evidence_stale')
        if current_vehicle['scope'] and current_vehicle['scope'].get('availability') == 'unavailable':
            blockers.append('current_wheel_option_unavailable')
        source = tire['provenance']['source_id']
        current_fact = next((row for row in binding['tire']['facts'] if row['source_id'] == source), None)
        if not current_fact or current_fact['facts_hash'] != tire['facts_hash']:
            blockers.append('tire_evidence_stale')
        if not binding['tire']['catalogs'] or any(not item['present'] for item in binding['tire']['catalogs']):
            blockers.append('tire_catalog_membership_changed')
        if binding['tire']['lifecycle']['state'] != 'active':
            blockers.append('tire_lifecycle_revoked')
        if binding['tire']['identity_resolution']['state'] == 'blocked':
            blockers.append('tire_identity_review_required')
    revision = previous.revision if previous else 0
    fingerprint = digest({'selection': selected.model_dump(), 'action': payload.action,
        'relation_id': payload.relation_id, 'revision': revision, 'binding': binding})
    return {**BASE, 'selection': selected.model_dump(), 'revision': revision, 'fingerprint': fingerprint,
        'vehicle_evidence': vehicle, 'tire_evidence': tire, 'binding': binding, 'checks': checks,
        'unknown_fields': [item['field'] for item in checks if item['status'] in {'unknown', 'not_declared'}],
        'blockers': list(dict.fromkeys(blockers)), 'can_submit': not blockers,
        'blocker_messages': [{'code': code, 'message': BLOCKER_MESSAGES.get(code,
            '双方已知字段冲突：' + FIELD_NAMES.get(code.removeprefix('conflict_'), code))}
            for code in dict.fromkeys(blockers)],
        'official_oe': deepcopy(OFFICIAL_OE), 'notice': NOTICE}


def serialize_event(row):
    return {key: getattr(row, key) for key in ('id', 'relation_id', 'revision', 'action', 'review_state',
        'selection', 'vehicle_evidence', 'tire_evidence', 'binding', 'binding_hash', 'checks', 'before', 'after',
        'acknowledged_unknowns', 'operator', 'reason', 'idempotency_key')} | {
        'created_at': timestamp(row.created_at), 'official_oe': deepcopy(OFFICIAL_OE)}


def relation_summary(db, relation, row):
    binding = current_binding(db, RelationSelection(**row.selection))
    stale = stale_reasons(row.binding, binding)
    state = 'needs_review' if stale and row.review_state != 'revoked' else row.review_state
    return {**BASE, 'id': relation.id, 'vehicle_id': relation.vehicle_id, 'trim_id': relation.trim_id,
        'wheel_option_id': relation.wheel_option_id, 'axle': relation.axle, 'variant_id': row.selection['variant_id'],
        'revision': row.revision, 'review_state': row.review_state, 'effective_state': state,
        'needs_review': bool(stale), 'stale_reasons': stale, 'selection': row.selection,
        'vehicle_evidence': row.vehicle_evidence, 'tire_evidence': row.tire_evidence, 'checks': row.checks,
        'official_oe': deepcopy(OFFICIAL_OE), 'operator': row.operator, 'reason': row.reason,
        'updated_at': timestamp(row.created_at), 'fingerprint': digest({'revision': row.revision, 'binding': binding}),
        'notice': NOTICE}


def detail(db, relation_id):
    relation, row = load_relation(db, relation_id)
    history = db.scalars(select(FitmentRelationRevision).where(FitmentRelationRevision.relation_id == relation_id)
                        .order_by(desc(FitmentRelationRevision.revision)).limit(101)).all()
    return {**relation_summary(db, relation, row), 'history': [serialize_event(item) for item in history[:100]],
            'history_truncated': len(history) > 100}


def append_revision(db, payload, session_id, idempotency_key):
    try:
        key = str(UUID(idempotency_key))
    except (TypeError, ValueError, AttributeError):
        fail('invalid_idempotency_key', '请提供固定UUID请求标识', 422)
    shared = QueryService(db, None)
    shared.lock_ingestion()
    request_hash = digest(payload.model_dump())
    replay = db.scalar(select(FitmentRelationRevision).where(FitmentRelationRevision.actor_session_id == session_id,
        FitmentRelationRevision.idempotency_key == key))
    if replay:
        if replay.request_hash != request_hash:
            fail('idempotency_payload_mismatch', '同一UUID已绑定不同的关系操作')
        result = {'relation': detail(db, replay.relation_id), 'event': serialize_event(replay), 'idempotent_replay': True}
        db.commit()
        return result
    proposed = preview(db, payload)
    if proposed['revision'] != payload.expected_revision or proposed['fingerprint'] != payload.expected_fingerprint:
        fail('fitment_relation_revision_conflict', '关系或双侧证据已变化，请重新预览核对')
    if not proposed['can_submit']:
        fail('fitment_relation_gate_failed', '当前关系操作存在已知冲突或状态限制：' + ', '.join(proposed['blockers']))
    if payload.action != 'revoke' and proposed['unknown_fields'] and not payload.acknowledge_unknowns:
        fail('fitment_relation_unknown_acknowledgement_required', '必须明确确认尚未声明/未知的要求，不能推断为已满足', 422)
    previous = None
    if payload.relation_id:
        relation, previous = load_relation(db, payload.relation_id)
    else:
        vehicle = accepted_vehicle(db, payload.selection.vehicle_snapshot_id)
        _, trim, _ = vehicle_parts(vehicle, payload.selection)
        relation = FitmentRelation(id=uid(), vehicle_id=payload.selection.vehicle_id,
            trim_id=payload.selection.trim_id, wheel_option_id=payload.selection.wheel_option_id,
            axle=payload.selection.axle, scope=fixed_scope(vehicle, trim, payload.selection))
        db.add(relation)
        db.flush()
    state = 'reviewed' if payload.action == 'review' else 'revoked' if payload.action == 'revoke' else 'pending_review'
    if previous and previous.review_state == 'revoked' and payload.action == 'revise':
        state = 'revoked'
    before = {'revision': previous.revision, 'review_state': previous.review_state,
              'selection': previous.selection, 'binding_hash': previous.binding_hash,
              'vehicle_evidence': previous.vehicle_evidence, 'tire_evidence': previous.tire_evidence} if previous else None
    after = {'revision': proposed['revision'] + 1, 'review_state': state, 'selection': proposed['selection'],
             'binding_hash': digest(proposed['binding']), 'vehicle_evidence': proposed['vehicle_evidence'],
             'tire_evidence': proposed['tire_evidence']}
    # Revocation preserves the previous reviewed binding: withdrawing a stale
    # relation must never make its old evidence appear freshly reviewed.
    bound = previous.binding if payload.action == 'revoke' else proposed['binding']
    after['binding_hash'] = digest(bound)
    row = FitmentRelationRevision(id=uid(), relation_id=relation.id, revision=after['revision'],
        action=payload.action, review_state=state, selection=proposed['selection'],
        vehicle_evidence=proposed['vehicle_evidence'], tire_evidence=proposed['tire_evidence'],
        binding=bound, binding_hash=digest(bound), checks=proposed['checks'], before=before, after=after,
        acknowledged_unknowns=payload.acknowledge_unknowns, operator=payload.operator, reason=payload.reason,
        actor_session_id=session_id, idempotency_key=key, request_hash=request_hash)
    db.add(row)
    shared.audit(session_id, 'fitment_relation_revision_appended', relation_id=relation.id, event_id=row.id,
                 revision=row.revision, action_kind=row.action, before=before, after=after)
    db.flush()
    result = {'relation': detail(db, relation.id), 'event': serialize_event(row), 'idempotent_replay': False}
    db.commit()
    return result


def snapshot_summary(row):
    return {'id': row.id, 'vehicle_id': row.vehicle_id, 'vehicle': row.payload['vehicle'],
            'fact_version': row.fact_version, 'fact_hash': row.fact_hash, 'provenance': vehicle_provenance(row),
            'fitment_count': len(row.payload.get('fitments', []))}


def register_fitment_relation_routes(app):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get('/v1/fitment-relations/vehicle-snapshots')
    def vehicle_snapshots(mode: Literal['history'] = Query(...), vehicle_id: str | None = Query(None, max_length=80),
                          offset: int = Query(0, ge=0, le=100000), limit: int = Query(20, ge=1, le=100), db=Depends(get_db)):
        statement = select(VehicleSnapshot).where(select(VehicleVerification.id).where(
            VehicleVerification.snapshot_id == VehicleSnapshot.id,
            VehicleVerification.vehicle_id == VehicleSnapshot.vehicle_id).exists())
        if vehicle_id:
            statement = statement.where(VehicleSnapshot.vehicle_id == vehicle_id)
        total = db.scalar(select(func.count()).select_from(statement.subquery()))
        rows = db.scalars(statement.order_by(desc(VehicleSnapshot.observed_at), VehicleSnapshot.id).offset(offset).limit(limit))
        return {**BASE, 'items': [snapshot_summary(row) for row in rows], 'total': total, 'offset': offset, 'limit': limit}

    @app.get('/v1/fitment-relations/vehicle-snapshots/{snapshot_id}')
    def vehicle_snapshot(snapshot_id: str, mode: Literal['history'] = Query(...), db=Depends(get_db)):
        row = accepted_vehicle(db, snapshot_id)
        return {**BASE, **snapshot_summary(row), 'trims': row.payload['trims'], 'fitments': row.payload['fitments'],
                'coverage': row.payload.get('coverage')}

    @app.get('/v1/fitment-relations/tire-evidence/{variant_id}')
    def tire_evidence(variant_id: str, mode: Literal['history'] = Query(...),
                      offset: int = Query(0, ge=0, le=100000), limit: int = Query(20, ge=1, le=100), db=Depends(get_db)):
        variant = db.get(TireVariant, variant_id)
        if variant is None:
            fail('tire_variant_missing', '未找到精确SKU', 404)
        items = []
        statement = select(Snapshot).where(cast(Snapshot.parsed_variants, Text).contains(variant_id, autoescape=True),
            select(Verification.id).where(Verification.snapshot_id == Snapshot.id,
            Verification.source_id == Snapshot.source_id, Verification.query_key == Snapshot.query_key).exists())
        for snapshot in db.scalars(statement.order_by(desc(Snapshot.observed_at), Snapshot.id)):
            for item in snapshot.parsed_variants:
                if item.get('id') != variant_id:
                    continue
                fact = db.scalar(select(FactVersion).where(FactVersion.variant_id == variant_id,
                    FactVersion.source_id == snapshot.source_id, FactVersion.version == item.get('fact_version'),
                    FactVersion.facts_hash == digest(business_facts(item.get('facts', {})))).limit(1))
                if fact:
                    items.append({'snapshot_id': snapshot.id, 'source_id': snapshot.source_id,
                        'provenance': provenance(snapshot), 'fact_version_id': fact.id,
                        'fact_version': fact.version, 'facts_hash': fact.facts_hash})
        return {**BASE, 'variant_id': variant_id, 'identity': variant.identity,
                'identity_contract': contract_metadata(db, variant_id), 'items': items[offset:offset + limit],
                'total': len(items), 'offset': offset, 'limit': limit}

    @app.post('/v1/fitment-relations/preview')
    def proposed(payload: RelationPreviewRequest, db=Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        result = preview(db, payload)
        db.commit()
        return result

    @app.post('/v1/fitment-relations/revisions', status_code=201)
    def append(payload: RelationDecision, request: Request,
               idempotency_key: str = Header(alias='Idempotency-Key', max_length=64), db=Depends(get_db)):
        return append_revision(db, payload, request.state.session_id, idempotency_key)

    @app.get('/v1/fitment-relations')
    def listing(mode: Literal['history'] = Query(...), vehicle_id: str | None = Query(None, max_length=80),
                axle: Literal['front', 'rear'] | None = Query(None),
                state: Literal['pending_review', 'reviewed', 'revoked', 'needs_review'] | None = Query(None),
                offset: int = Query(0, ge=0, le=100000), limit: int = Query(20, ge=1, le=100), db=Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        statement = select(FitmentRelation)
        if vehicle_id:
            statement = statement.where(FitmentRelation.vehicle_id == vehicle_id)
        if axle:
            statement = statement.where(FitmentRelation.axle == axle)
        rows = []
        for relation in db.scalars(statement.order_by(desc(FitmentRelation.created_at), FitmentRelation.id)):
            row = latest_revision(db, relation.id)
            if row:
                item = relation_summary(db, relation, row)
                if state is None or item['effective_state'] == state:
                    rows.append(item)
        result = {**BASE, 'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'limit': limit}
        db.commit()
        return result

    @app.get('/v1/fitment-relations/{relation_id}')
    def read(relation_id: str, mode: Literal['history'] = Query(...), db=Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        result = detail(db, relation_id)
        db.commit()
        return result
