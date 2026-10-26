"""Read-only composition of exact fitment candidates and same-event observations."""
from copy import deepcopy
from typing import Literal

from fastapi import Depends, HTTPException, Query, Request, Response
from pydantic import Field, StrictInt, model_validator

from .auth import current_user, session_scope
from .domain import digest
from .fitment_relations import OFFICIAL_OE
from .recommendation_candidates import FitmentCandidatesRequest, VehicleSelection, projection as candidate_projection
from .research import preference_state
from .test_events import EventPayload, latest as latest_event, metadata
from .test_preference_interpretation import (Fingerprint, MetricDimension, PreferenceInterpretationRequest,
    interpret_test_preferences)
from .test_sku_links import (BOUNDARY, Closed, current_link_binding, latest_revision, link_view,
    reconstruct_link_revision)


SCHEMA = 'test-candidate-interpretation@1'
POLICY_VERSION = 'same-event-candidate-interpretation@1'
LINK_FIELDS = ('id', 'revision_id', 'revision', 'fingerprint', 'binding_hash', 'selection',
    'review_state', 'effective_state', 'eligibility', 'evidence_level', 'materials', 'material_evidence',
    'assertions', 'checks', 'required_identity_fields', 'unknown_fields', 'blockers', 'stale_reasons',
    'boundary', 'declaration_revision_id', 'confirmed_event_revision_id', 'confirmed_participant_hash')


class CandidateReference(Closed):
    variant_id: str = Field(min_length=1, max_length=64)
    link_id: str = Field(min_length=1, max_length=64)
    expected_link_revision_id: str = Field(min_length=1, max_length=64)
    expected_link_revision: StrictInt = Field(ge=1)
    expected_link_fingerprint: Fingerprint


class CandidateInterpretationRequest(Closed):
    selection: VehicleSelection
    expected_event_revision_id: str = Field(min_length=1, max_length=64)
    expected_event_revision: StrictInt = Field(ge=1)
    expected_event_fingerprint: Fingerprint
    expected_preference_revision: StrictInt = Field(ge=1)
    expected_preference_fingerprint: Fingerprint
    candidates: list[CandidateReference] = Field(min_length=2, max_length=60)
    metric_dimensions: list[MetricDimension] = Field(min_length=1, max_length=24)

    @model_validator(mode='after')
    def unique_candidates(self):
        if (len({ref.variant_id for ref in self.candidates}) != len(self.candidates)
                or len({ref.link_id for ref in self.candidates}) != len(self.candidates)):
            raise ValueError('精确候选及显式身份桥不得重复')
        return self


def fail(code, message, status=409):
    raise HTTPException(status, {'code': code, 'message': message}, headers={'Cache-Control': 'no-store'})


def projection(db, session_id, event_id, payload):
    """Rebuild every input without writes; callers own the read-snapshot fence."""
    actor = current_user(db, session_id)
    if actor is None:
        fail('test_candidate_actor_required', '请登录本人账户后核对精确候选。', 401)
    try:
        row = latest_event(db, event_id)
    except HTTPException as error:
        if error.status_code == 404:
            fail('test_candidate_event_not_found', '未找到测试事件。', 404)
        raise
    try:
        event_payload = EventPayload.model_validate(row.payload).model_dump(mode='json')
    except (ValueError, TypeError):
        fail('test_candidate_event_evidence_invalid', '测试事件原始记录不完整，请重新核对。', 422)
    if (event_payload != row.payload or digest(event_payload) != row.fingerprint
            or row.state not in ('active', 'revoked')):
        fail('test_candidate_event_evidence_invalid', '测试事件原始记录与证据摘要不一致。', 422)
    if row.state != 'active':
        fail('test_candidate_event_revoked', '已撤销测试事件不能产生新的候选解释。')
    if (row.id != payload.expected_event_revision_id or row.revision != payload.expected_event_revision
            or row.fingerprint != payload.expected_event_fingerprint):
        fail('test_candidate_event_changed', '测试事件修订已变化，请重新载入。')
    event = {**metadata(row), 'event': event_payload}
    preference = preference_state(db, session_scope(db, session_id))
    if preference['weights'] is None:
        fail('test_candidate_preference_missing', '请先保存本人驾驶偏好。')
    if (preference['revision'] != payload.expected_preference_revision
            or preference['fingerprint'] != payload.expected_preference_fingerprint):
        fail('test_candidate_preference_changed', '本人驾驶偏好已变化，请重新载入。')
    candidates, candidate_fingerprint = candidate_projection(db, session_id, FitmentCandidatesRequest(
        selection=payload.selection, expected_preference_revision=payload.expected_preference_revision,
        expected_preference_fingerprint=payload.expected_preference_fingerprint))
    if candidates['truncated']:
        fail('test_candidate_candidate_scope_incomplete', '当前轴位关系扫描范围不足，不能产生完整候选解释。')
    mappings = {mapping.metric_key: mapping.dimension for mapping in payload.metric_dimensions}
    metric_keys = {metric['key'] for metric in event_payload['metrics']}
    if len(mappings) != len(payload.metric_dimensions) or set(mappings) != metric_keys:
        fail('test_candidate_invalid_metric_mapping', '请显式映射本场全部指标，排除项使用null。', 422)
    canonical_mapping = [{'metric_key': metric['key'], 'dimension': mappings[metric['key']]}
                         for metric in event_payload['metrics']]
    current_variants = {item['variant_id'] for item in candidates['items']}
    participant_keys = {participant['key'] for participant in event_payload['participants']}
    selected_participants = set()
    items, excluded, bound_candidates = [], [], []
    for ref in payload.candidates:
        link_row = latest_revision(db, ref.link_id)
        if (link_row.id != ref.expected_link_revision_id or link_row.revision != ref.expected_link_revision
                or link_row.fingerprint != ref.expected_link_fingerprint):
            fail('test_candidate_link_changed', '所选身份桥已产生新修订，请重新核对。')
        link = link_view(db, link_row, actor=None, history=False)
        selected = reconstruct_link_revision(db, link_row)
        binding = current_link_binding(db, selected)
        if (selected.variant_id != ref.variant_id or selected.event_id != event_id
                or selected.event_revision_id != row.id or selected.participant_key not in participant_keys):
            fail('test_candidate_scope_mismatch', '显式身份桥与当前场次、参测对象或精确SKU不一致。', 422)
        if selected.participant_key in selected_participants:
            fail('test_candidate_participant_duplicate', '所选精确候选必须对应本场不同参测对象。', 422)
        selected_participants.add(selected.participant_key)
        reasons = []
        if ref.variant_id not in current_variants:
            reasons.append('candidate_not_current')
        if link['eligibility'] != 'conditional_reviewed_transcription' or link['review_state'] != 'reviewed':
            reasons.append('link_not_eligible')
            reasons.extend(link['blockers'])
            reasons.extend(link['stale_reasons'])
        reasons = list(dict.fromkeys(reasons))
        participant_id = event_id + ':' + selected.participant_key
        items.append({'variant_id': ref.variant_id, 'participant_id': participant_id,
            'participant_key': selected.participant_key, 'eligible': not reasons, 'reason_codes': reasons,
            'link': {key: deepcopy(link[key]) for key in LINK_FIELDS}})
        if reasons:
            excluded.append({'variant_id': ref.variant_id, 'link_id': ref.link_id, 'reason_codes': reasons[:]})
        bound_candidates.append({'request': ref.model_dump(), 'link': link, 'current_binding': binding})
    selection = PreferenceInterpretationRequest(
        expected_event_revision=row.revision, expected_event_fingerprint=row.fingerprint,
        expected_preference_revision=preference['revision'], expected_preference_fingerprint=preference['fingerprint'],
        participant_ids=[item['participant_id'] for item in items], metric_dimensions=payload.metric_dimensions)
    interpreted = interpret_test_preferences(event, preference, selection)
    comparable = any(metric['observation_comparison'] is not None
                     for metric in interpreted['personal_interpretation']['metrics'])
    eligible_count = sum(item['eligible'] for item in items)
    reason_codes = []
    if excluded:
        reason_codes.append('selected_candidates_excluded')
    if eligible_count < 2:
        reason_codes.append('insufficient_eligible_candidates')
    if not comparable:
        reason_codes.append('no_comparable_mapped_metrics')
    signature = digest({'schema': 'test-candidate-interpretation-binding@1', 'policy_version': POLICY_VERSION,
        'actor_user_id': actor.id, 'event': event, 'preference': candidates['preference'],
        'candidate_fingerprint': candidate_fingerprint, 'selection': payload.selection.model_dump(),
        'candidates': bound_candidates, 'metric_dimensions': canonical_mapping})
    result = {'schema': SCHEMA, 'policy_version': POLICY_VERSION, 'data_state': 'local_snapshot',
        'scope': 'actor', 'evidence_scope': 'local_workspace', 'comparison_scope': 'same_event_only',
        'status': 'conditional_observations' if not excluded and eligible_count >= 2 and comparable else 'insufficient_evidence',
        'ranking': 'source_reported_only', 'performance_score': None, 'official_oe': deepcopy(OFFICIAL_OE),
        'boundary': deepcopy(BOUNDARY), 'selection': payload.selection.model_dump(),
        'binding': {'event': {key: event[key] for key in ('id', 'revision_id', 'revision', 'fingerprint')},
            'preference': {key: preference[key] for key in ('revision', 'fingerprint')},
            'candidate_fingerprint': candidate_fingerprint, 'interpretation_fingerprint': signature},
        'candidate_projection': candidates, 'items': items, 'requested_count': len(items),
        'eligible_count': eligible_count, 'excluded': excluded, 'reason_codes': reason_codes,
        'source_evidence': interpreted['source_evidence'],
        'personal_interpretation': None if excluded else interpreted['personal_interpretation'],
        'notices': ['仅限当前精确轴位候选、本场已录观察与当前有效的条件性人工身份桥；不代表全性能推荐或安装安全。',
            '原始测试记录仍为未在线核验的人工转录；参测名称保持来源身份，SKU关联单列证据。',
            '任一所选项未准入时不产生个人解释；请明确重新选择后核对。',
            '本地材料及派生解释不增加模型或导出许可；本人权重只组织逐项观察，不重算来源名次或综合分。',
            '结果绑定本次读取的完整证据及修订；响应到达时本地状态可能已经变化。']}
    return result, signature


def register_test_candidate_interpretation_routes(app):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post('/v1/test-events/{event_id}/candidate-interpretation')
    def preview(event_id: str, payload: CandidateInterpretationRequest, request: Request, response: Response,
                mode: Literal['history'] = Query(...), db=Depends(get_db)):
        response.headers['Cache-Control'] = 'no-store'
        with db.no_autoflush:
            result, signature = projection(db, request.state.session_id, event_id, payload)
            db.rollback()
            db.expire_all()
            _, after = projection(db, request.state.session_id, event_id, payload)
            if signature != after:
                fail('test_candidate_binding_changed', '读取期间账户、候选或完整证据已变化，请重新核对。')
            return result
