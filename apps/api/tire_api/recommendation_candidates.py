"""Current reviewed exact-axle candidates, without performance inference."""
from copy import deepcopy
from typing import Literal

from fastapi import Depends, HTTPException, Query, Request, Response
from pydantic import ConfigDict, Field, StrictInt
from sqlalchemy import func, select

from .auth import session_scope
from .domain import StrictModel, digest
from .fitment_relation_models import FitmentRelation, FitmentRelationRevision
from .fitment_relations import (OFFICIAL_OE, RelationSelection, accepted_vehicle, current_binding,
    fixed_scope, frozen_evidence, latest_vehicle, stale_reasons, technical_checks, vehicle_parts)
from .interest_events import _relation_side
from .research import preference_state
from .vehicles import fitment_fact_hash

POLICY_VERSION = 'reviewed-exact-axle@1'
MAX_RELATIONS = 200
DIMENSIONS = ('dry', 'wet', 'quiet', 'comfort', 'wear', 'energy', 'appearance')


class VehicleSelection(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    vehicle_id: str = Field(strict=True, min_length=1, max_length=80)
    vehicle_snapshot_id: str = Field(strict=True, min_length=1, max_length=64)
    trim_id: str = Field(strict=True, min_length=1, max_length=120)
    wheel_option_id: str = Field(strict=True, min_length=1, max_length=64)
    axle: Literal['front', 'rear']


class FitmentCandidatesRequest(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    selection: VehicleSelection
    expected_preference_revision: StrictInt = Field(ge=0)
    expected_preference_fingerprint: str = Field(strict=True, min_length=64, max_length=64,
                                                pattern=r'^[0-9a-f]{64}$')


def fail(code, message, status=409):
    raise HTTPException(status, {'code': code, 'message': message}, headers={'Cache-Control': 'no-store'})


def vehicle_context(db, selected):
    snapshot = accepted_vehicle(db, selected.vehicle_snapshot_id)
    _, trim, fit = vehicle_parts(snapshot, selected)
    current = latest_vehicle(db, selected.vehicle_id)
    if current is None:
        fail('fitment_candidate_vehicle_changed', '当前没有已采纳的车型事实，请重新选择。')
    current = accepted_vehicle(db, current.id)
    if (fitment_fact_hash(snapshot.payload) != snapshot.fact_hash
            or fitment_fact_hash(current.payload) != current.fact_hash):
        fail('fitment_candidate_vehicle_evidence_invalid', '车型事实与已采纳证据哈希不一致。', 422)
    try:
        _, current_trim, current_fit = vehicle_parts(current, selected)
    except HTTPException:
        fail('fitment_candidate_vehicle_changed', '当前车型配置或轴位已变化，请重新选择。')
    scope = fixed_scope(snapshot, trim, selected)
    if (snapshot.fact_hash != current.fact_hash
            or digest(scope) != digest(fixed_scope(current, current_trim, selected))):
        fail('fitment_candidate_vehicle_changed', '所选车型快照已不代表当前事实，请重新载入。')
    if fit.get('availability') not in ('standard', 'optional') or current_fit.get('availability') not in ('standard', 'optional'):
        fail('fitment_candidate_wheel_unavailable', '所选轮毂当前不是可用的标配或选配。', 422)
    return {'snapshot_id': snapshot.id, 'current_snapshot_id': current.id, 'fact_hash': current.fact_hash,
            'fact_version': current.fact_version, 'scope': scope}


def relation_heads(db, selected):
    heads = select(FitmentRelationRevision.relation_id, func.max(FitmentRelationRevision.revision).label('revision'))\
        .group_by(FitmentRelationRevision.relation_id).subquery()
    statement = select(FitmentRelation, FitmentRelationRevision).join(FitmentRelationRevision,
        FitmentRelationRevision.relation_id == FitmentRelation.id).join(heads,
        (heads.c.relation_id == FitmentRelation.id) & (heads.c.revision == FitmentRelationRevision.revision)).where(
        FitmentRelation.vehicle_id == selected.vehicle_id, FitmentRelation.trim_id == selected.trim_id,
        FitmentRelation.wheel_option_id == selected.wheel_option_id, FitmentRelation.axle == selected.axle)
    count = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    return db.execute(statement.order_by(FitmentRelation.id).limit(MAX_RELATIONS)).all(), count


def projection(db, session_id, payload):
    preference = preference_state(db, session_scope(db, session_id))
    if (preference['revision'] != payload.expected_preference_revision
            or preference['fingerprint'] != payload.expected_preference_fingerprint):
        fail('fitment_candidate_preference_changed', '本人驾驶偏好已变化，请重新载入后查看。')
    vehicle = vehicle_context(db, payload.selection)
    rows, count = relation_heads(db, payload.selection)
    candidates, excluded, signatures = {}, [], []
    for relation, row in rows:
        stored_selection = row.selection if isinstance(row.selection, dict) else {}
        reasons, state, binding, evidence = [], row.review_state, None, []
        selected = None
        if row.review_state != 'reviewed':
            reasons.append('relation_not_reviewed')
        try:
            selected = RelationSelection.model_validate(row.selection)
            if (digest(relation.scope) != digest(vehicle['scope'])
                    or any(getattr(selected, field) != getattr(payload.selection, field)
                           for field in ('vehicle_id', 'trim_id', 'wheel_option_id', 'axle'))):
                reasons.append('fixed_relation_scope_mismatch')
            binding = current_binding(db, selected)
            stale = stale_reasons(row.binding, binding)
            if stale and row.review_state != 'revoked':
                state = 'needs_review'
            reasons.extend(stale)
            if row.binding_hash != digest(row.binding):
                reasons.append('relation_binding_invalid')
            # Check the actual original bytes and exact archived members, not
            # merely the current semantic fingerprint from relation_summary.
            side, evidence = _relation_side(db, row, row.created_at)
            if not side['evidence_valid']:
                reasons.append('relation_evidence_invalid')
            frozen_vehicle, frozen_tire, frozen_scope = frozen_evidence(db, selected)
            if (digest(row.vehicle_evidence) != digest(frozen_vehicle)
                    or digest(row.tire_evidence) != digest(frozen_tire)):
                reasons.append('relation_evidence_invalid')
            checks = technical_checks(frozen_vehicle, frozen_tire)
            if any(item['status'] in ('unknown', 'not_declared') for item in checks) and not row.acknowledged_unknowns:
                reasons.append('relation_unknowns_not_acknowledged')
            if digest(frozen_scope) != digest(vehicle['scope']) or frozen_vehicle['fact_hash'] != vehicle['fact_hash']:
                reasons.append('vehicle_evidence_stale')
            reasons.extend('conflict_' + item['field'] for item in checks if item['status'] == 'conflict')
            tire = binding['tire']
            if tire['identity_contract']['state'] != 'current':
                reasons.append('identity_contract_review_required')
            if tire['lifecycle']['state'] != 'active':
                reasons.append('tire_lifecycle_revoked')
            if tire['identity_resolution']['state'] == 'blocked':
                reasons.append('tire_identity_review_required')
            if not tire['catalogs'] or any(not item['present'] for item in tire['catalogs']):
                reasons.append('tire_catalog_membership_changed')
        except (HTTPException, ValueError, TypeError, KeyError, AttributeError):
            reasons.append('relation_evidence_invalid')
        signatures.append({'relation_id': relation.id, 'revision_id': row.id, 'revision': row.revision,
            'binding_hash': row.binding_hash, 'binding': binding, 'evidence': evidence, 'reasons': reasons,
            'vehicle_evidence': row.vehicle_evidence, 'tire_evidence': row.tire_evidence})
        if reasons:
            excluded.append({'relation_id': relation.id, 'revision': row.revision,
                'variant_id': stored_selection.get('variant_id', ''), 'effective_state': state,
                'reason_codes': list(dict.fromkeys(reasons))})
            continue
        variant_id = selected.variant_id
        item = candidates.setdefault(variant_id, {'variant_id': variant_id,
            'identity': deepcopy(binding['tire']['identity']), 'relations': [], 'performance_score': None,
            'ranking': 'not_computed', 'official_oe': deepcopy(OFFICIAL_OE)})
        item['relations'].append({'relation_id': relation.id, 'revision_id': row.id, 'revision': row.revision,
            'binding_hash': row.binding_hash, 'selection': deepcopy(row.selection),
            'vehicle_evidence': deepcopy(row.vehicle_evidence), 'tire_evidence': deepcopy(row.tire_evidence),
            'checks': checks, 'unknown_fields': [r['field'] for r in checks if r['status'] in ('unknown', 'not_declared')],
            'acknowledged_unknowns': row.acknowledged_unknowns, 'evidence': evidence})
    preference = {key: deepcopy(preference[key]) for key in ('revision', 'fingerprint', 'weights')}
    weights = preference['weights']
    dimensions = sorted(DIMENSIONS, key=lambda d: (-weights[d], DIMENSIONS.index(d))) if weights else DIMENSIONS
    result = {'schema': 'fitment-candidates@1', 'policy_version': POLICY_VERSION, 'data_state': 'local_snapshot',
        'scope': 'actor', 'evidence_scope': 'local_workspace', 'selection': payload.selection.model_dump(),
        'vehicle_binding': vehicle, 'preference': preference,
        'research_focus': [{'dimension': dimension, 'weight': weights[dimension] if weights else None,
                           'evidence_status': 'exact_sku_performance_not_established'} for dimension in dimensions],
        'items': [candidates[key] for key in sorted(candidates)], 'excluded_relations': excluded,
        'inspected_count': len(rows), 'relation_count': count, 'truncated': count > len(rows),
        'ranking': 'not_computed', 'performance_score': None, 'official_oe': deepcopy(OFFICIAL_OE),
        'notices': ['仅显示本地人工关系仍通过当前证据门禁的精确轴位候选；顺序按标识排列，不表示性能优劣。',
            '偏好只列研究重点，各维精确SKU性能证据尚未建立；不计算综合分，不关联同名参测胎或跨测试排名。',
            '未知要求保持未知；人工复核不代表官方原配、当前库存或安装安全结论。',
            '前后轴独立候选不代表整车组合已验证；响应到达后来源或本地状态可能已变化。']}
    return result, digest({'vehicle': vehicle, 'preference': preference, 'count': count, 'relations': signatures})


def register_fitment_candidate_routes(app):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post('/v1/fitment-candidates/preview')
    def preview(payload: FitmentCandidatesRequest, request: Request, response: Response,
                mode: Literal['history'] = Query(...), db=Depends(get_db)):
        response.headers['Cache-Control'] = 'no-store'
        with db.no_autoflush:
            result, signature = projection(db, request.state.session_id, payload)
            # Release any read snapshot before optimistic tail validation. No
            # write lock, audit, persistent run or commit is involved.
            db.rollback()
            _, after = projection(db, request.state.session_id, payload)
            if signature != after:
                fail('fitment_candidate_binding_changed', '读取期间关系或双侧证据已变化，请重新载入。')
            return result
