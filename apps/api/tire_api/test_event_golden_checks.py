"""Strict independent expectations and bounded, type-exact local comparisons."""
from copy import deepcopy
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from .domain import stable_json
from .professional_golden_checks import Closed, EventLiteral
from .test_sku_links import BridgeMaterial, BridgeRights, OpenedMaterial

SHA = r'^[0-9a-f]{64}$'
KEY = r'^[a-z][a-z0-9_-]{0,39}$'
BOUNDARY = {'scope': 'local_workspace', 'data_state': 'local_snapshot', 'accepted_as_facts': False,
    'review_identity': 'self_reported_local_operator', 'human_truth_status': 'pending_external_review',
    'provider_use': False, 'export': False}


class SignedFence(Closed):
    operator: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)
    expected_revision: StrictInt = Field(ge=0)
    expected_fingerprint: str | None = Field(pattern=SHA)

    @field_validator('operator', 'reason')
    @classmethod
    def text(cls, value):
        if not value.strip() or '\x00' in value:
            raise ValueError('署名及理由必须是非空文字')
        value.encode('utf-8', errors='strict')
        return value

    @model_validator(mode='after')
    def fence(self):
        if (self.expected_revision == 0) != (self.expected_fingerprint is None):
            raise ValueError('首次操作必须使用0/null，修订须使用精确版本及指纹')
        return self


class EventRef(Closed):
    event_id: str = Field(min_length=1, max_length=64)
    event_revision_id: str = Field(min_length=1, max_length=64)
    event_fingerprint: str = Field(pattern=SHA)


class LinkRef(Closed):
    participant_key: str = Field(pattern=KEY)
    link_id: str = Field(min_length=1, max_length=64)
    link_revision_id: str = Field(min_length=1, max_length=64)
    link_fingerprint: str = Field(pattern=SHA)


class TestResultRights(BridgeRights):
    quote_test_results: StrictBool

    @field_validator('quote_test_results')
    @classmethod
    def result_rights(cls, value):
        if value is not True:
            raise ValueError('必须另行声明测试成绩短引文权限')
        return value


class Material(BridgeMaterial):
    rights: TestResultRights


class IdentityExpectation(Closed):
    participant_key: str = Field(pattern=KEY)
    truth: Literal['linked', 'not_linked', 'unknown']
    sku_label: str | None = Field(min_length=1, max_length=100)
    expected_variant_id: str | None = Field(min_length=1, max_length=64)

    @model_validator(mode='after')
    def independent_identity(self):
        if self.truth == 'unknown':
            if self.sku_label is not None or self.expected_variant_id is not None:
                raise ValueError('未知身份不能猜测SKU标签或variant')
        elif self.sku_label is None or self.expected_variant_id is None or not self.sku_label.strip():
            raise ValueError('已知身份判断须明确SKU标签与目标variant')
        return self


class DistinctPair(Closed):
    left_sku_label: str = Field(min_length=1, max_length=100)
    right_sku_label: str = Field(min_length=1, max_length=100)


class Expected(Closed):
    event: EventLiteral
    identity_assertions: list[IdentityExpectation] = Field(min_length=1, max_length=60)
    distinct_pairs: list[DistinctPair] = Field(max_length=1770)

    @model_validator(mode='after')
    def graph(self):
        event = self.event
        people, metrics = {p.key for p in event.participants}, {m.key for m in event.metrics}
        if len(people) != len(event.participants) or len(metrics) != len(event.metrics):
            raise ValueError('预期事件不得重复参测胎或指标')
        pairs = {(m.participant_key, m.metric_key) for m in event.measurements}
        if (len(pairs) != len(event.measurements) or {p for p, _ in pairs} != people
                or {m for _, m in pairs} != metrics):
            raise ValueError('预期成绩必须完整关联本场参测胎及指标')
        if event.reported_participants is not None and event.reported_participants < len(people):
            raise ValueError('参测总数不能少于已录入参测胎')
        if event.coverage == 'full_event' and event.reported_participants != len(people):
            raise ValueError('完整场次须有准确参测总数')
        if any(m.source_rank and event.reported_participants and m.source_rank > event.reported_participants
               for m in event.measurements):
            raise ValueError('来源名次超出参测总数')
        keys = [a.participant_key for a in self.identity_assertions]
        if len(set(keys)) != len(keys) or set(keys) != people:
            raise ValueError('身份预期须逐一覆盖参测胎且不能重复')
        labels = {}
        for assertion in self.identity_assertions:
            if assertion.sku_label is not None:
                previous = labels.setdefault(assertion.sku_label, assertion.expected_variant_id)
                if previous != assertion.expected_variant_id:
                    raise ValueError('同一SKU标签不能对应互相矛盾的variant预期')
        seen = set()
        for pair in self.distinct_pairs:
            left, right = pair.left_sku_label, pair.right_sku_label
            key = tuple(sorted((left, right)))
            if left == right or left not in labels or right not in labels or key in seen:
                raise ValueError('不同SKU对须使用两个已知标签且不可重复或反向重复')
            seen.add(key)
        if sum(len(m.evidence_span) for m in event.measurements) > 8000:
            raise ValueError('预期仅允许有界证据短引文')
        if len(stable_json(self.model_dump(mode='json')).encode('utf-8')) > 500_000:
            raise ValueError('预期超过大小限制')
        return self


class CaseContent(SignedFence):
    title: str = Field(min_length=1, max_length=200)
    event_ref: EventRef
    materials: list[Material] = Field(min_length=1, max_length=3)
    link_refs: list[LinkRef] = Field(max_length=60)
    expected: Expected
    evidence_note: str = Field(min_length=1, max_length=2000)

    @field_validator('title', 'evidence_note')
    @classmethod
    def nonempty(cls, value):
        return SignedFence.text(value)

    @model_validator(mode='after')
    def references(self):
        if len({m.document_id for m in self.materials}) != len(self.materials):
            raise ValueError('材料不可重复')
        keys = {r.participant_key for r in self.link_refs}
        people = {a.participant_key for a in self.expected.identity_assertions}
        if len(keys) != len(self.link_refs) or not keys <= people:
            raise ValueError('身份桥须唯一关联本场参测胎')
        if any(a.truth != 'unknown' and a.participant_key not in keys for a in self.expected.identity_assertions):
            raise ValueError('已知身份预期必须提供精确身份桥引用')
        return self


class ReviewRequest(SignedFence):
    case_revision: StrictInt = Field(ge=1)
    case_fingerprint: str = Field(pattern=SHA)
    action: Literal['approve', 'reject', 'revoke']
    acknowledged: StrictBool
    opened_materials: list[OpenedMaterial] = Field(max_length=3)

    @field_validator('acknowledged')
    @classmethod
    def acknowledgement(cls, value):
        if value is not True:
            raise ValueError('请明确确认本机人工审核边界')
        return value


class CaseRef(Closed):
    case_id: str = Field(min_length=1, max_length=64)
    case_revision: StrictInt = Field(ge=1)
    case_fingerprint: str = Field(pattern=SHA)
    review_revision: StrictInt = Field(ge=1)
    review_fingerprint: str = Field(pattern=SHA)


class SetWrite(SignedFence):
    title: str = Field(min_length=1, max_length=200)
    action: Literal['freeze', 'revoke']
    case_refs: list[CaseRef] = Field(max_length=3)
    acknowledged: StrictBool

    @model_validator(mode='after')
    def members(self):
        if not self.acknowledged or not self.title.strip():
            raise ValueError('冻结必须署名并确认边界')
        if ((self.action == 'freeze' and not self.case_refs) or (self.action == 'revoke' and self.case_refs)
                or len({r.case_id for r in self.case_refs}) != len(self.case_refs)):
            raise ValueError('冻结需1–3个不重复案例；撤回须使用空引用列表')
        return self


class EvaluateRequest(Closed):
    expected_set_revision: StrictInt = Field(ge=1)
    expected_set_fingerprint: str = Field(pattern=SHA)
    target: Literal['frozen_revision', 'current_head']


_MISSING = object()


def _display(value):
    if value is _MISSING:
        return {'missing': True}
    encoded = stable_json(value)
    if len(encoded) > 2000:
        return {'truncated': True, 'preview': encoded[:1900]}
    return deepcopy(value)


def compare_values(expected, actual, *, path='event', limit=100):
    """Never equate booleans with numbers, missing with null, or normalize strings."""
    differences, total = [], 0

    def add(at, left, right):
        nonlocal total
        total += 1
        if len(differences) < limit:
            differences.append({'path': at, 'expected': _display(left), 'actual': _display(right),
                                'code': 'value_mismatch'})

    def walk(left, right, at):
        if type(left) is not type(right):
            add(at, left, right)
        elif isinstance(left, dict):
            for key in sorted(left.keys() | right.keys()):
                walk(left.get(key, _MISSING), right.get(key, _MISSING), f'{at}.{key}')
        elif isinstance(left, list):
            for index in range(max(len(left), len(right))):
                walk(left[index] if index < len(left) else _MISSING,
                     right[index] if index < len(right) else _MISSING, f'{at}[{index}]')
        elif left != right:
            add(at, left, right)

    walk(expected, actual, path)
    return differences, total > limit


def compare_identities(expected, observations):
    """Observe only the selected real links; unknowns never count as checked negatives."""
    results, by_label = [], {}
    for assertion in expected['identity_assertions']:
        observed = observations.get(assertion['participant_key'])
        known = assertion['truth'] != 'unknown'
        checked = known and observed is not None
        linked = bool(observed and observed['linked'])
        variant_matches = checked and observed['variant_id'] == assertion['expected_variant_id']
        matches = variant_matches and (linked == (assertion['truth'] == 'linked'))
        blockers = deepcopy(observed['blockers']) if observed else ['identity_unknown']
        if checked and not variant_matches:
            blockers.append('identity_variant_mismatch')
        result = {**deepcopy(assertion), 'checked': checked,
            'actual_variant_id': observed['variant_id'] if observed else None,
            'actual_identity_key': observed['identity_key'] if observed else None,
            'actual_linked': linked if observed else None,
            'state': 'passed' if matches else 'failed' if checked else 'inconclusive',
            'blockers': list(dict.fromkeys(blockers))}
        results.append(result)
        if assertion['sku_label'] is not None:
            by_label.setdefault(assertion['sku_label'], []).append((assertion, observed))
    distinct, wrong, checked_count = [], 0, 0
    for pair in expected['distinct_pairs']:
        left, right = by_label[pair['left_sku_label']], by_label[pair['right_sku_label']]
        # A collision can be observed even when a bridge cannot prove a positive link.
        # Passing distinctness still requires two eligible, known positive identities.
        usable = all(a['truth'] == 'linked' and o is not None and o['linked'] for a, o in left + right)
        merged = any(
            (isinstance(a['variant_id'], str) and bool(a['variant_id'].strip()) and a['variant_id'] == b['variant_id']) or
            (isinstance(a['identity_key'], str) and bool(a['identity_key'].strip()) and a['identity_key'] == b['identity_key'])
            for left_assertion, a in left for right_assertion, b in right
            if left_assertion['truth'] != 'unknown' and right_assertion['truth'] != 'unknown'
            and a is not None and b is not None)
        checked_count += int(usable)
        wrong += int(merged)
        distinct.append({**pair, 'checked': usable, 'observed_wrong_merge': bool(merged),
            'state': 'failed' if merged else 'passed' if usable else 'inconclusive'})
    return results, distinct, wrong, checked_count
