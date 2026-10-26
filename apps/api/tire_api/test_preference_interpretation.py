"""Read-only, same-event personal explanations; never rescore source results."""
from copy import deepcopy
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import ConfigDict, Field, StrictInt

from .domain import StrictModel, digest


DIMENSIONS = ('dry', 'wet', 'quiet', 'comfort', 'wear', 'energy', 'appearance')
Dimension = Literal['dry', 'wet', 'quiet', 'comfort', 'wear', 'energy', 'appearance']
POLICY_VERSION = 'same-event-preference@1'
Fingerprint = Annotated[str, Field(strict=True, min_length=64, max_length=64, pattern=r'^[a-f0-9]{64}$')]
ParticipantId = Annotated[str, Field(strict=True, min_length=1, max_length=128)]


class MetricDimension(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    metric_key: str = Field(strict=True, pattern=r'^[a-z][a-z0-9_-]{0,39}$', max_length=40)
    dimension: Dimension | None


class PreferenceInterpretationRequest(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    expected_event_revision: StrictInt = Field(ge=1)
    expected_event_fingerprint: Fingerprint
    expected_preference_revision: StrictInt = Field(ge=1)
    expected_preference_fingerprint: Fingerprint
    participant_ids: list[ParticipantId] = Field(min_length=2, max_length=60)
    metric_dimensions: list[MetricDimension] = Field(min_length=1, max_length=24)


def invalid_selection():
    raise HTTPException(422, {'code': 'invalid_preference_interpretation',
                             'message': '请选择本场至少两项不同参测胎，并显式映射本场全部指标；排除项使用null。'})


def interpret_test_preferences(event: dict, preference: dict,
                               selection: PreferenceInterpretationRequest) -> dict:
    """Calculate from the already-read immutable snapshots, without I/O or mutation.

    The route checks current event state and both bindings before calling this
    function. The fingerprint binds content, not identity or authorization.
    """
    payload = event['event']
    people = [{**deepcopy(p), 'id': f'{event["id"]}:{p["key"]}',
               'identity_status': 'participant_only'} for p in payload['participants']]
    available = {p['id'] for p in people}
    selected_ids = set(selection.participant_ids)
    metric_keys = {m['key'] for m in payload['metrics']}
    mappings = {m.metric_key: m.dimension for m in selection.metric_dimensions}
    if (len(selected_ids) != len(selection.participant_ids) or not selected_ids <= available
            or len(mappings) != len(selection.metric_dimensions) or set(mappings) != metric_keys):
        invalid_selection()
    participants = [p for p in people if p['id'] in selected_ids]
    participant_ids = [p['id'] for p in participants]
    canonical_mapping = [{'metric_key': m['key'], 'dimension': mappings[m['key']]}
                         for m in payload['metrics']]
    event_binding = {key: event[key] for key in ('id', 'revision_id', 'revision', 'fingerprint')}
    preference_binding = {key: preference[key] for key in ('revision', 'fingerprint')}
    interpretation_fingerprint = digest({
        'schema': 'test-preference-interpretation-binding@1', 'policy_version': POLICY_VERSION,
        'event': event_binding, 'preference': preference_binding,
        'participant_ids': participant_ids, 'metric_dimensions': canonical_mapping,
    })
    selected_keys = {p['key'] for p in participants}
    measurements = []
    for value in payload['measurements']:
        if value['participant_key'] not in selected_keys:
            continue
        participant_id = f'{event["id"]}:{value["participant_key"]}'
        evidence_id = 'test-measurement:' + digest({
            'schema': 'test-event-measurement-evidence@1', 'event_id': event['id'],
            'revision_id': event['revision_id'], 'event_revision': event['revision'],
            'event_fingerprint': event['fingerprint'], 'participant_id': participant_id,
            'metric_key': value['metric_key'],
        })
        measurements.append({**deepcopy(value), 'participant_id': participant_id,
                             'evidence_id': evidence_id,
                             'reference': {'event_id': event['id'], 'revision': event['revision'],
                                           'participant_id': participant_id, 'metric_key': value['metric_key']}})
    by_pair = {(m['participant_id'], m['metric_key']): m for m in measurements}
    metrics = []
    for metric in payload['metrics']:
        key = metric['key']
        dimension = mappings[key]
        observed = [by_pair[(pid, key)] for pid in participant_ids if (pid, key) in by_pair]
        missing = [pid for pid in participant_ids if (pid, key) not in by_pair]
        limitations = []
        if dimension is None:
            limitations.append('excluded_by_user')
        if missing:
            limitations.append('missing_measurements')
        if metric['direction'] == 'unspecified':
            limitations.append('direction_unspecified')
        if len(observed) < 2:
            limitations.append('insufficient_observations')
        observation_comparison = None
        if dimension is not None and len(observed) >= 2 and metric['direction'] != 'unspecified':
            choose = min if metric['direction'] == 'lower' else max
            extreme = choose(Decimal(m['raw_value']) for m in observed)
            favorable = [m for m in observed if Decimal(m['raw_value']) == extreme]
            observation_comparison = {
                'scope': 'selected_recorded_observations',
                'favorable_participant_ids': [m['participant_id'] for m in favorable],
                'evidence_ids': [m['evidence_id'] for m in favorable],
            }
        metrics.append({
            'metric_key': key, 'dimension': dimension,
            'observed_participant_ids': [m['participant_id'] for m in observed],
            'missing_participant_ids': missing, 'evidence_ids': [m['evidence_id'] for m in observed],
            'limitations': limitations,
            'complete_comparable': dimension is not None and not missing and metric['direction'] != 'unspecified',
            'observation_comparison': observation_comparison,
        })
    weights = deepcopy(preference['weights'])
    dimensions = [{
        'dimension': dimension, 'weight': weights[dimension],
        'metric_keys': [m['metric_key'] for m in metrics if m['dimension'] == dimension],
        'complete_comparable_metric_keys': [m['metric_key'] for m in metrics
                                            if m['dimension'] == dimension and m['complete_comparable']],
    } for dimension in sorted(DIMENSIONS, key=lambda d: (-weights[d], DIMENSIONS.index(d)))]
    mapped_weight = sum(d['weight'] for d in dimensions if d['metric_keys'])
    comparable_weight = sum(d['weight'] for d in dimensions if d['complete_comparable_metric_keys'])
    return {
        'schema': 'test-preference-interpretation@1', 'data_state': 'local_snapshot',
        'scope': 'actor', 'evidence_scope': 'local_workspace', 'comparison_scope': 'same_event_only',
        'ranking': 'source_reported_only', 'policy_version': POLICY_VERSION,
        'binding': {'event': event_binding, 'preference': preference_binding,
                    'interpretation_fingerprint': interpretation_fingerprint},
        'source_evidence': {
            'event': {k: deepcopy(v) for k, v in payload.items()
                      if k not in {'participants', 'metrics', 'measurements'}},
            'participants': participants, 'metrics': deepcopy(payload['metrics']), 'measurements': measurements,
            'record_kind': 'manual_transcription', 'verification_status': 'unverified', 'verified_at': None,
            'recorded_at': event['recorded_at'], 'recorded_participant_count': len(people),
            'selected_participant_count': len(participants),
        },
        'personal_interpretation': {
            'mapping_origin': 'user_explicit_once', 'weights': weights, 'metric_dimensions': canonical_mapping,
            'dimensions': dimensions, 'metrics': metrics,
            'coverage': {'mapped_weight': mapped_weight, 'fully_comparable_weight': comparable_weight,
                         'unmapped_weight': 100 - mapped_weight,
                         'mapped_not_fully_comparable_weight': mapped_weight - comparable_weight},
        },
        'notices': [
            '人工转录的本地测试记录，未在线核验；仅比较本场、所选参测胎及已录观察，不代表完整来源排名。',
            '指标分类由本人本次显式选择，权重只组织解释；不是测试机构结论，不生成综合分或重算来源名次。',
            '缺失不等于零；方向未说明时不推断优劣。完整可比较权重不代表整个性能维度已充分测量，覆盖权重不放大到100。',
            '参测名称不自动关联精确SKU，也不证明车辆适配；结果绑定实际读取的修订，响应到达时可能已有新修订。',
        ],
    }
