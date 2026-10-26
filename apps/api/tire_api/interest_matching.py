"""Exact, three-valued matching over frozen evidence; no database or acquisition."""
from copy import deepcopy
from typing import Literal
import unicodedata

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from .domain import StrictModel, parse_size, stable_json

POLICY_VERSION = 'explicit-interest@1'
KINDS = ('brand', 'model', 'size', 'oe', 'technology', 'test_organization', 'vehicle_fitment')
InterestKind = Literal['brand', 'model', 'size', 'oe', 'technology', 'test_organization', 'vehicle_fitment']
CHANGED_FIELDS = (
    'identity.brand', 'identity.model', 'identity.size', 'identity.oe_mark',
    'identity.acoustic_technology', 'identity.technology_features', 'facts',
    'facts.utqg_treadwear', 'facts.utqg_traction', 'facts.utqg_temperature',
    'facts.tread_depth', 'facts.tread_depths', 'event.organization', 'event.participants',
    'event.metrics', 'event.measurements', 'event.metadata', 'state', 'vehicle',
    'trims', 'fitments', 'footnotes', 'selection', 'review_state', 'vehicle_evidence',
    'tire_evidence', 'binding', 'curation', 'identity_resolution', 'catalog_membership', 'curation_applicability',
)


def normalize_text(value):
    if (not isinstance(value, str) or not value or len(value) > 200
            or any(unicodedata.category(char).startswith('C') for char in value)):
        raise ValueError('兴趣文本须为1–200字符，不能包含控制或不可见字符')
    result = ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
    if not result or len(result) > 200:
        raise ValueError('规范化后的兴趣文本须为1–200字符')
    return result


class ModelValue(StrictModel):
    brand: str = Field(strict=True, min_length=1, max_length=120)
    model: str = Field(strict=True, min_length=1, max_length=200)

    @field_validator('brand', 'model')
    @classmethod
    def exact_text(cls, value):
        return normalize_text(value)


class VehicleValue(StrictModel):
    vehicle_id: str = Field(strict=True, min_length=1, max_length=80)
    trim_id: str | None = Field(default=None, min_length=1, max_length=120, strict=True)
    wheel_option_id: str | None = Field(default=None, min_length=1, max_length=64, strict=True)
    axle: Literal['front', 'rear'] | None = None

    @model_validator(mode='after')
    def wheel_scope(self):
        if self.wheel_option_id and not self.trim_id:
            raise ValueError('轮毂项必须明确所属配置trim_id')
        return self


class InterestCondition(StrictModel):
    kind: InterestKind
    values: list = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def canonical_values(self):
        values = []
        for value in self.values:
            if self.kind == 'model':
                values.append(ModelValue.model_validate(value).model_dump())
            elif self.kind == 'vehicle_fitment':
                values.append(VehicleValue.model_validate(value).model_dump(exclude_none=True))
            elif self.kind == 'size':
                if not isinstance(value, str):
                    raise ValueError('尺寸必须为明确文本')
                values.append(parse_size(value))
            else:
                values.append(normalize_text(value))
        unique = {stable_json(value): value for value in values}
        self.values = [unique[key] for key in sorted(unique)]
        return self


class InterestCriteria(StrictModel):
    conditions: list[InterestCondition] = Field(min_length=1, max_length=8)
    metric_keys: list[StrictStr] = Field(max_length=24)
    changed_fields: list[StrictStr] = Field(max_length=24)

    @field_validator('metric_keys')
    @classmethod
    def exact_metric_keys(cls, values):
        import re
        if any(not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', value) for value in values):
            raise ValueError('只能显式选择已录原始metric key')
        return sorted(set(values))

    @field_validator('changed_fields')
    @classmethod
    def supported_paths(cls, values):
        if any(value not in CHANGED_FIELDS for value in values):
            raise ValueError('变化筛选字段不在受控集合内')
        return sorted(set(values))

    @model_validator(mode='after')
    def canonical_conditions(self):
        # Repeated kinds are intentional AND groups; alternatives inside each
        # group are OR. Only exactly redundant groups are removed.
        groups = {stable_json(value.model_dump()): value for value in self.conditions}
        self.conditions = [groups[key] for key in sorted(groups)]
        return self


class InterestSettings(InterestCriteria):
    name: str = Field(strict=True, min_length=1, max_length=120)
    enabled: StrictBool
    source_quality_notifications: StrictBool = False

    @field_validator('name')
    @classmethod
    def name_text(cls, value):
        normalize_text(value)
        return value


class InterestEdit(InterestSettings):
    expected_revision: StrictInt = Field(ge=1)


class InterestState(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    action: Literal['archive', 'restore']


class InterestReadState(StrictModel):
    read: StrictBool


def capabilities():
    return {
        'schema': 'interest-capabilities@1', 'kinds': list(KINDS),
        'domains': [
            {'domain': 'tire', 'supported': True, 'event_kinds': ['variant_observed', 'facts_changed'],
             'limitations': ['accepted_source_facts_only', 'historical_snapshot_identity_only']},
            {'domain': 'test_event', 'supported': True, 'event_kinds': ['create', 'revise', 'revoke', 'restore'],
             'limitations': ['manual_transcription_unverified', 'participant_only_not_sku', 'explicit_metric_keys_only']},
            {'domain': 'vehicle', 'supported': True, 'event_kinds': ['vehicle_observed', 'vehicle_facts_changed'],
             'limitations': ['accepted_fact_version_changes_only', 'no_inferred_tire_fitment']},
            {'domain': 'fitment', 'supported': True, 'event_kinds': ['create', 'revise', 'review', 'revoke', 'restore'],
             'limitations': ['manual_relation_not_official_oe', 'mixed_conditions_require_reviewed_frozen_relation']},
            {'domain': 'tire_curation', 'supported': True, 'event_kinds': ['manual_override', 'revoke', 'clear_override'],
             'limitations': ['local_manual_decision_not_source_fact', 'source_bound_overlay_only']},
            {'domain': 'tire_lifecycle', 'supported': True, 'event_kinds': ['revoke', 'restore'],
             'limitations': ['local_entity_state_not_official_recall', 'source_contexts_not_pooled']},
            {'domain': 'tire_identity', 'supported': True, 'event_kinds': ['correct', 'merge', 'clear'],
             'limitations': ['local_mapping_no_fact_or_interest_retargeting', 'source_contexts_only_target_is_basis']},
            {'domain': 'tire_catalog', 'supported': True, 'event_kinds': ['added', 'removed'],
             'limitations': ['source_query_membership_only_not_entity_revocation', 'accepted_adjacent_results_only', 'no_304_membership_event']},
            {'domain': 'tire_curation_validity', 'supported': True, 'event_kinds': ['invalidate'],
             'limitations': ['source_bound_overlay_applicability_only', 'derived_transition_not_manual_decision',
                             'actual_fact_replacement_including_304_reconciliation']},
            {'domain': 'tire_source_quality', 'supported': True, 'event_kinds': ['quarantined'],
             'limitations': ['explicit_subscription_required', 'verified_baseline_members_only',
                            'unaccepted_candidates_never_matched', 'no_quality_history_preview',
                            'local_notifications_only']},
        ],
        'changed_fields': list(CHANGED_FIELDS),
        'unsupported_events': [
            {'kind': 'source_quality_rejection', 'reason': 'only_tire_quarantine_with_verified_baseline_supported'},
            {'kind': 'metadata_only_verification', 'reason': 'unchanged_facts_are_not_new_publications'},
        ],
        'network_refresh': False,
        'notice': '参数与治理事件按原有规则匹配；来源质量隔离仅向明确订阅且有可核对历史基线的兴趣提醒，'
                  '不代表候选已采纳，暂不提供质量历史预览。保存关注不抓取或联网，不代表车型适配或官方OE认证。',
    }


def changed_paths(before, after, prefix=''):
    """Preserve actual presence and values, including removals and real zero."""
    if isinstance(before, dict) != isinstance(after, dict):
        value = after if isinstance(after, dict) else before
        paths = [prefix] if prefix else []
        for key, item in sorted(value.items()):
            path = f'{prefix}.{key}' if prefix else key
            paths.extend(changed_paths(None, item, path) if isinstance(item, dict) else [path])
        return list(dict.fromkeys(paths))
    if isinstance(before, dict) and isinstance(after, dict):
        left, right = before if isinstance(before, dict) else {}, after if isinstance(after, dict) else {}
        paths = []
        for key in sorted(set(left) | set(right)):
            path = f'{prefix}.{key}' if prefix else key
            if key not in left or key not in right:
                value = right[key] if key in right else left[key]
                paths.extend(changed_paths(None, value, path) if isinstance(value, dict) else [path])
            else:
                paths.extend(changed_paths(left[key], right[key], path))
        return paths
    return [prefix] if type(before) is not type(after) or before != after else []


def _field_changed(selected, paths):
    for field in selected:
        if field == 'event.metadata':
            if any(path.startswith('event.') and not any(path == group or path.startswith(group + '.')
                   for group in ('event.organization', 'event.participants', 'event.metrics', 'event.measurements'))
                   for path in paths):
                return True
        elif any(path == field or path.startswith(field + '.') for path in paths):
            return True
    return False


def _metric_changed(event, keys):
    if event['domain'] != 'test_event':
        return False
    before, after = event.get('before') or {}, event.get('after') or {}
    left, right = before.get('event', {}), after.get('event', {})
    if before.get('state') != after.get('state'):
        return any(metric.get('key') in keys for metric in left.get('metrics', []) + right.get('metrics', []))
    for key in keys:
        for collection, key_name in (('metrics', 'key'), ('measurements', 'metric_key')):
            a = [value for value in left.get(collection, []) if value.get(key_name) == key]
            b = [value for value in right.get(collection, []) if value.get(key_name) == key]
            if a != b:
                return True
    return False


def _contexts(side, domain):
    if not side:
        return []
    if side.get('evidence_valid') is False:
        return [{'evidence_valid': False}]
    if 'source_contexts' in side:
        return deepcopy(side['source_contexts'])
    if domain == 'test_event':
        payload = side.get('event', {})
        return [{'identity': {**person, 'size': payload['tested_size']}, 'facts': {},
                 'organization': payload.get('organization'), 'participant_only': True,
                 'evidence_valid': side.get('evidence_valid', True)}
                for person in payload.get('participants', [])]
    if domain == 'fitment':
        tire = side.get('tire_evidence', {})
        selected = side.get('selection', {})
        return [{'identity': tire.get('identity'), 'facts': tire.get('facts', {}),
                 'vehicle_scope': {key: selected[key] for key in ('vehicle_id', 'trim_id', 'wheel_option_id', 'axle') if key in selected},
                 'reviewed_relation': side.get('review_state') == 'reviewed',
                 'evidence_valid': side.get('evidence_valid', True)}]
    if domain == 'vehicle':
        result = []
        for fit in side.get('fitments', []):
            for axle in ('front', 'rear'):
                if isinstance(fit.get(axle), dict):
                    result.append({'vehicle_scope': {'vehicle_id': side['vehicle']['id'], 'trim_id': fit['trim_id'],
                                   'wheel_option_id': fit['id'], 'axle': axle},
                                   'identity': {'size': fit[axle].get('size')}, 'facts': {},
                                   'declared_fitment': True, 'evidence_valid': side.get('evidence_valid', True)})
        return result or [{'vehicle_scope': {'vehicle_id': side.get('vehicle', {}).get('id')},
                           'facts': {}, 'evidence_valid': side.get('evidence_valid', True)}]
    context = {'identity': side.get('identity'), 'facts': side.get('facts', {}),
               'evidence_valid': side.get('evidence_valid', True)}
    return [context]


def _condition_known(context, condition):
    kind, values = condition['kind'], condition['values']
    if not context.get('evidence_valid', True):
        return None, 'historical_evidence_unverifiable'
    if kind == 'vehicle_fitment':
        actual = context.get('vehicle_scope')
        if not actual:
            return None, 'missing_vehicle_scope'
        return any(all(actual.get(key) == value for key, value in target.items()) for target in values), 'condition_not_matched'
    if kind == 'test_organization':
        actual = context.get('organization')
        if not actual:
            return None, 'missing_test_organization'
        return normalize_text(actual) in values, 'condition_not_matched'
    identity = context.get('identity')
    if not identity:
        return None, 'missing_tire_identity'
    field = {'oe': 'oe_mark', 'technology': 'acoustic_technology'}.get(kind, kind)
    conflicts = context.get('facts', {}).get('source_field_conflicts', [])
    dependencies = {field}
    if kind == 'model':
        dependencies.add('brand')
    if kind == 'technology':
        dependencies.add('technology_features')
    conflict_fields = dependencies | {'identity.' + value for value in dependencies} | {'facts.' + value for value in dependencies}
    if not isinstance(conflicts, list) or any(isinstance(item, dict) and item.get('field') in conflict_fields for item in conflicts):
        return None, 'source_field_conflict'
    if kind == 'model':
        if not identity.get('brand') or not identity.get('model'):
            return None, 'missing_tire_identity'
        actual = {'brand': normalize_text(identity['brand']), 'model': normalize_text(identity['model'])}
        return actual in values, 'condition_not_matched'
    if kind == 'technology':
        candidates = [identity.get('acoustic_technology')]
        features = identity.get('technology_features', context.get('facts', {}).get('technology_features'))
        if isinstance(features, list):
            candidates.extend(features)
        declared = [normalize_text(value) for value in candidates if isinstance(value, str) and value.strip()
                    and normalize_text(value) not in {'unknown', 'unspecified'}]
        if not declared:
            return None, 'missing_declared_technology'
        return bool(set(declared).intersection(values)), 'condition_not_matched'
    actual = identity.get(field)
    if not isinstance(actual, str) or not actual.strip() or normalize_text(actual) in {'unknown', 'unspecified'}:
        return None, 'missing_declared_' + kind
    actual = parse_size(actual) if kind == 'size' else normalize_text(actual)
    return actual in values, 'condition_not_matched'


def _condition(context, condition):
    # An old source string outside the current supported grammar is unknown;
    # this narrow data boundary never hides producer/database integrity errors.
    try:
        return _condition_known(context, condition)
    except (ValueError, TypeError):
        return None, 'historical_evidence_unverifiable'


def match_event(event, criteria):
    """A full AND must hold on one side and one evidence subject, never pooled."""
    if event.get('domain') == 'tire_source_quality':
        from .interest_source_quality import match_source_quality_event
        return match_source_quality_event(event, criteria)
    criteria = criteria.model_dump() if isinstance(criteria, InterestCriteria) else criteria
    result = {'state': 'no_match', 'matched_sides': [], 'reasons': [], 'policy_version': POLICY_VERSION,
              'criteria': deepcopy({key: criteria[key] for key in ('conditions', 'metric_keys', 'changed_fields')})}
    if criteria['changed_fields'] and not _field_changed(criteria['changed_fields'], event['changed_paths']):
        return {**result, 'reasons': ['selected_changed_field_absent']}
    if criteria['metric_keys'] and not _metric_changed(event, criteria['metric_keys']):
        return {**result, 'reasons': ['selected_metric_change_absent']}
    kinds = {condition['kind'] for condition in criteria['conditions']}
    mixed_vehicle = 'vehicle_fitment' in kinds and bool(kinds.intersection({'brand', 'model', 'size', 'oe', 'technology'}))
    unknown = set()
    for side_name in ('before', 'after'):
        side = event.get(side_name)
        if criteria['metric_keys'] and side and side.get('evidence_valid', True):
            available = {metric.get('key') for metric in side.get('event', {}).get('metrics', [])}
            if not available.intersection(criteria['metric_keys']):
                continue
        contexts = _contexts(side, event['domain'])
        # Relationships are frozen in the event producer, never loaded from the
        # current graph here. They bind the exact SKU identity and vehicle axle;
        # a new tire fact remains this side's independently verified observation.
        if mixed_vehicle and side and side.get('evidence_valid', True):
            contexts.extend(deepcopy(side.get('reviewed_contexts', [])))
        for context in contexts:
            checks = [_condition(context, condition) for condition in criteria['conditions']]
            direct_size = (context.get('declared_fitment') and
                           kinds.issubset({'vehicle_fitment', 'size'}))
            if mixed_vehicle and not context.get('reviewed_relation') and not direct_size:
                checks.append((None, 'reviewed_relation_required'))
            if all(value is True for value, _reason in checks):
                result['matched_sides'].append(side_name)
                break
            if not any(value is False for value, _reason in checks):
                unknown.update(reason for value, reason in checks if value is None)
    if result['matched_sides']:
        return {**result, 'state': 'matched', 'reasons': ['matches_' + side for side in result['matched_sides']]}
    if unknown:
        return {**result, 'state': 'indeterminate', 'reasons': sorted(unknown)}
    return {**result, 'reasons': ['condition_not_matched']}
