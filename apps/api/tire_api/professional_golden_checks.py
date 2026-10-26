"""Pure comparison of independent professional-test literals and bound snapshots.

No application, database or network is imported. An archived observation cannot
authenticate current HTTP execution, authorization, representative data or people.
"""
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, JsonValue, model_validator

from .domain import StrictModel


CONTRACT_VERSION = 'professional-test-golden@1'
CASE_SCHEMA = 'professional-golden-case@1'
ACTUAL_SCHEMA = 'professional-golden-actual@1'
REPORT_SCHEMA = 'professional-golden-report@1'
HUMAN_TRUTH_STATUS = 'pending_external_review'
TIERS = ('synthetic_contract', 'real_source_unknown_or_inadmissible', 'real_source_human_reviewed')
MAX_CASES = 300
MAX_DIFFS = 100
MAX_INPUT_BYTES = 512_000
MAX_ACTUAL_BYTES = 512_000

Tier = Literal['synthetic_contract', 'real_source_unknown_or_inadmissible', 'real_source_human_reviewed']
Sha256 = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
Label = Annotated[str, Field(min_length=1, max_length=100, pattern=r'^[a-z][a-z0-9_-]{0,99}$')]
Code = Annotated[str, Field(min_length=1, max_length=160, pattern=r'^[a-z][a-z0-9_-]{0,159}$')]
ParticipantKey = Annotated[str, Field(pattern=r'^[a-z][a-z0-9_-]{0,39}$')]
IdentityField = Literal['brand', 'model', 'manufacturer_product_code', 'region', 'size', 'load_index',
    'speed_rating', 'xl', 'hl', 'oe_mark', 'acoustic_technology', 'run_flat', 'product_code_type',
    'gtin', 'technology_features', 'eprel_id']
Dimension = Literal['dry', 'wet', 'quiet', 'comfort', 'wear', 'energy', 'appearance']
Eligibility = Literal['none', 'conditional_reviewed_transcription']
EffectiveState = Literal['pending_review', 'reviewed', 'revoked', 'needs_review']


class Closed(StrictModel):
    model_config = ConfigDict(strict=True, extra='forbid', str_strip_whitespace=False, allow_inf_nan=False)


class BoundFile(Closed):
    path: str = Field(min_length=1, max_length=4096)
    byte_count: int = Field(ge=0, le=32_000_000)
    sha256: Sha256


class MaterialRights(Closed):
    rights_holder: str = Field(min_length=1, max_length=160)
    basis: str = Field(min_length=5, max_length=1000)
    license_url: str | None = Field(max_length=2048)
    attribution: str = Field(min_length=1, max_length=2000)
    store_original: Literal[True]
    workspace_reopen: Literal[True]
    quote_identifiers: Literal[True]
    provider_use: Literal[False]
    export: Literal[False]

    @model_validator(mode='before')
    @classmethod
    def literal_boolean_types(cls, value):
        if type(value) is dict and any(type(value.get(key)) is not bool for key in
                ('store_original', 'workspace_reopen', 'quote_identifiers', 'provider_use', 'export')):
            raise ValueError('Rights must use explicit JSON booleans')
        return value


class MaterialLiteral(Closed):
    material_label: Label
    origin: Literal['synthetic', 'real_source']
    title: str = Field(min_length=1, max_length=300)
    publisher: str = Field(min_length=1, max_length=200)
    publication_date: str | None = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    doi: str | None = Field(max_length=200)
    source_reference_url: str = Field(min_length=1, max_length=2048)
    download_url: str | None = Field(max_length=2048)
    original: BoundFile
    capture_receipt: BoundFile | None
    agent_review_record: BoundFile | None
    rights: MaterialRights


class ParticipantLiteral(Closed):
    key: ParticipantKey
    brand: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=200)
    source_designation: str = Field(max_length=300)


class MetricLiteral(Closed):
    key: ParticipantKey
    label: str = Field(min_length=1, max_length=120)
    unit: str = Field(min_length=1, max_length=40)
    protocol: str = Field(min_length=3, max_length=1000)
    direction: Literal['lower', 'higher', 'unspecified']


class MeasurementLiteral(Closed):
    participant_key: ParticipantKey
    metric_key: ParticipantKey
    raw_value: str = Field(pattern=r'^-?\d{1,12}(?:\.\d{1,8})?$', max_length=22)
    source_rank: int | None = Field(ge=1, le=10000)
    evidence_span: str = Field(min_length=1, max_length=300)
    evidence_locator: str = Field(min_length=1, max_length=300)


class EventLiteral(Closed):
    """All EventPayload fields are explicit; no product normalization is called."""
    title: str = Field(min_length=1, max_length=200)
    organization: str = Field(min_length=1, max_length=160)
    relationship: Literal['independent', 'manufacturer_commissioned', 'unknown']
    publication_date: str | None = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    source_url: str = Field(min_length=1, max_length=2048)
    rights_basis: str = Field(min_length=5, max_length=1000)
    tested_size: str = Field(min_length=1, max_length=24)
    vehicle: str | None = Field(max_length=200)
    surface: str | None = Field(max_length=200)
    conditions: str = Field(min_length=3, max_length=2000)
    coverage: Literal['selected_results', 'full_event']
    reported_participants: int | None = Field(ge=1, le=10000)
    participants: list[ParticipantLiteral] = Field(min_length=1, max_length=60)
    metrics: list[MetricLiteral] = Field(min_length=1, max_length=24)
    measurements: list[MeasurementLiteral] = Field(min_length=1, max_length=1000)


class VariantLiteral(Closed):
    """The complete 14-field VariantInput shape, preserving original JSON claims."""
    brand: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=200)
    manufacturer_product_code: str | None = Field(max_length=100)
    region: str = Field(min_length=1, max_length=40)
    size: str = Field(min_length=1, max_length=24)
    load_index: str | None = Field(max_length=12)
    speed_rating: str | None = Field(max_length=12)
    xl: bool | None
    hl: bool | None
    oe_mark: str | None = Field(max_length=100)
    acoustic_technology: str | None = Field(max_length=100)
    run_flat: bool | None
    source_variant_name: str | None = Field(max_length=400)
    facts: dict[str, JsonValue] = Field(max_length=100)


class SkuLiteral(Closed):
    sku_label: Label
    value: VariantLiteral


class LocatorLiteral(Closed):
    page: int = Field(ge=1, le=100000)
    region: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=300)


class AssertionLiteral(LocatorLiteral):
    field: IdentityField
    material_label: Label
    material_value: str | bool


class BridgeAttemptLiteral(Closed):
    attempt_id: Label
    participant_key: ParticipantKey
    sku_label: Label
    material_labels: list[Label] = Field(max_length=3)
    event_locator: LocatorLiteral | None
    participant_locator: LocatorLiteral | None
    assertions: list[AssertionLiteral] = Field(max_length=20)
    evidence_level: Literal['manual_assertion', 'source_explicit_identifiers_in_supplied_material']
    review: bool
    revoke: bool

    @model_validator(mode='after')
    def explicit_material_locators(self):
        if self.material_labels and (self.event_locator is None or self.participant_locator is None):
            raise ValueError('Referenced materials require both literal locators')
        if not self.material_labels and (self.event_locator is not None or self.participant_locator is not None):
            raise ValueError('Material-free assertions must not invent material locators')
        return self


class DrivingWeights(Closed):
    dry: int = Field(ge=0, le=100)
    wet: int = Field(ge=0, le=100)
    quiet: int = Field(ge=0, le=100)
    comfort: int = Field(ge=0, le=100)
    wear: int = Field(ge=0, le=100)
    energy: int = Field(ge=0, le=100)
    appearance: int = Field(ge=0, le=100)

    @model_validator(mode='after')
    def complete_weight(self):
        if sum(self.model_dump().values()) != 100:
            raise ValueError('Explicit driving weights must sum to 100')
        return self


class MetricMapping(Closed):
    metric_key: ParticipantKey
    dimension: Dimension | None


class CandidateLiteral(Closed):
    vehicle_fixture: Literal['synthetic-staggered-245-265@1']
    axle: Literal['front', 'rear']
    reviewed_fitment_sku_labels: list[Label] = Field(max_length=60)
    attempt_ids: list[Label] = Field(min_length=2, max_length=60)
    preference_weights: DrivingWeights
    metric_dimensions: list[MetricMapping] = Field(min_length=1, max_length=24)


class SourceReviewLiteral(Closed):
    material_label: Label
    findings: list[Code] = Field(min_length=1, max_length=40)
    exact_sku_truth: Literal['unknown']
    review_origin: Literal['existing_agent_document_review']


class CaseInput(Closed):
    mode: Literal['private_http', 'source_review_only']
    event: EventLiteral | None
    skus: list[SkuLiteral] = Field(max_length=60)
    bridge_attempts: list[BridgeAttemptLiteral] = Field(max_length=60)
    candidate: CandidateLiteral | None
    source_review: SourceReviewLiteral | None

    @model_validator(mode='after')
    def explicit_execution_scope(self):
        if self.mode == 'source_review_only':
            if self.event is not None or self.skus or self.bridge_attempts or self.candidate is not None or self.source_review is None:
                raise ValueError('Source review cannot invent an event, SKU, bridge or HTTP interpretation')
        elif self.event is None or not self.skus or not self.bridge_attempts or self.source_review is not None:
            raise ValueError('Private HTTP cases require explicit event, SKU and bridge literals')
        return self


class ExpectedPreview(Closed):
    http_status: int = Field(ge=200, le=599)
    can_submit: bool | None
    blockers: list[Code] = Field(max_length=60)
    error_code: Code | None


class ExpectedCurrentBridge(Closed):
    http_status: int = Field(ge=200, le=599)
    eligibility: Eligibility | None
    effective_state: EffectiveState | None
    blockers: list[Code] = Field(max_length=60)
    stale_reasons: list[Code] = Field(max_length=60)
    error_code: Code | None


class ExpectedBridge(Closed):
    attempt_id: Label
    truth: Literal['linked', 'not_linked', 'unknown']
    preview: ExpectedPreview
    current: ExpectedCurrentBridge | None


class ExpectedPair(Closed):
    left_sku_label: Label
    right_sku_label: Label
    truth: Literal['distinct', 'same', 'unknown']
    evidence_refs: list[str] = Field(max_length=20)


class ExpectedMetricComparison(Closed):
    metric_key: ParticipantKey
    dimension: Dimension | None
    observed_participant_keys: list[ParticipantKey] = Field(max_length=60)
    missing_participant_keys: list[ParticipantKey] = Field(max_length=60)
    complete_comparable: bool
    limitations: list[Code] = Field(max_length=10)
    favorable_participant_keys: list[ParticipantKey] | None = Field(max_length=60)


class ExpectedWeightCoverage(Closed):
    mapped_weight: int = Field(ge=0, le=100)
    fully_comparable_weight: int = Field(ge=0, le=100)
    unmapped_weight: int = Field(ge=0, le=100)
    mapped_not_fully_comparable_weight: int = Field(ge=0, le=100)


class ExpectedExcluded(Closed):
    sku_label: Label
    reason_codes: list[Code] = Field(min_length=1, max_length=60)


class ExpectedCandidate(Closed):
    http_status: int = Field(ge=200, le=599)
    error_code: Code | None
    status: Literal['conditional_observations', 'insufficient_evidence'] | None
    eligible_sku_labels: list[Label] = Field(max_length=60)
    excluded: list[ExpectedExcluded] = Field(max_length=60)
    personal_interpretation_allowed: bool
    metric_comparisons: list[ExpectedMetricComparison] = Field(max_length=24)
    coverage: ExpectedWeightCoverage | None


class CaseExpected(Closed):
    bridges: list[ExpectedBridge] = Field(max_length=60)
    distinct_pairs: list[ExpectedPair] = Field(max_length=1770)
    candidate: ExpectedCandidate | None
    source_review_findings: list[Code] = Field(max_length=40)


class ReviewDeclaration(Closed):
    state: Literal['pending_external_review']
    record: BoundFile | None


class ProfessionalGoldenCase(Closed):
    schema_id: Literal['professional-golden-case@1'] = Field(alias='schema')
    case_id: Label
    tier: Tier
    materials: list[MaterialLiteral] = Field(min_length=1, max_length=3)
    input: CaseInput
    expected: CaseExpected
    review: ReviewDeclaration


R71_VIEW_FIELDS = frozenset({'schema', 'scope', 'data_state', 'id', 'revision_id', 'revision', 'review_state',
    'effective_state', 'eligibility', 'boundary', 'selection', 'materials', 'evidence_level', 'frozen_evidence',
    'material_evidence', 'assertions', 'checks', 'required_identity_fields', 'unknown_fields', 'blockers',
    'stale_reasons', 'binding_hash', 'fingerprint', 'declared_by_user_id', 'declaration_revision_id',
    'confirmed_event_revision_id', 'confirmed_participant_hash', 'allowed_actions'})
R71_CURRENT_FIELDS = R71_VIEW_FIELDS | {'history', 'history_truncated'}
R71_PREVIEW_FIELDS = R71_VIEW_FIELDS | {'binding', 'can_submit'}
R75_FIELDS = frozenset({'schema', 'policy_version', 'data_state', 'scope', 'evidence_scope', 'comparison_scope',
    'status', 'ranking', 'performance_score', 'official_oe', 'boundary', 'selection', 'binding',
    'candidate_projection', 'items', 'requested_count', 'eligible_count', 'excluded', 'reason_codes',
    'source_evidence', 'personal_interpretation', 'notices'})


class HttpObservation(Closed):
    operation: Literal['r71_preview', 'r71_decision', 'r71_current', 'r75_interpretation']
    method: Literal['GET', 'POST']
    path: str = Field(min_length=1, max_length=2048)
    request_body: dict[str, JsonValue] | None
    request_sha256: Sha256
    http_status: int = Field(ge=200, le=599)
    response_body: dict[str, JsonValue]
    response_sha256: Sha256

    @model_validator(mode='after')
    def preserve_complete_protocol_body(self):
        if self.method != ('GET' if self.operation == 'r71_current' else 'POST'):
            raise ValueError('HTTP method must match the existing protocol operation')
        if self.http_status >= 400:
            expected = {'detail'}
        elif self.operation == 'r71_preview':
            expected = R71_PREVIEW_FIELDS
        elif self.operation == 'r71_current':
            expected = R71_CURRENT_FIELDS
        elif self.operation == 'r71_decision':
            expected = {'link', 'event', 'idempotent_replay'}
            link = self.response_body.get('link')
            if not isinstance(link, dict) or set(link) != R71_CURRENT_FIELDS:
                raise ValueError('Decision must retain its complete original current link body')
        else:
            expected = R75_FIELDS
        if set(self.response_body) != expected:
            raise ValueError('HTTP body must contain exactly the complete existing protocol fields')
        return self


class BridgeActual(Closed):
    attempt_id: Label
    preview: HttpObservation
    decisions: list[HttpObservation] = Field(max_length=3)
    current: HttpObservation | None


class SkuBinding(Closed):
    sku_label: Label
    variant_id: str = Field(min_length=1, max_length=64)
    tire_snapshot_id: str = Field(min_length=1, max_length=64)
    fact_version_id: str = Field(min_length=1, max_length=64)
    snapshot_member: dict[str, JsonValue]
    identity: dict[str, JsonValue]


class MaterialBinding(Closed):
    material_label: Label
    document_id: str = Field(min_length=1, max_length=64)
    raw_sha256: Sha256
    byte_count: int = Field(ge=1, le=8_388_608)
    metadata_sha256: Sha256


class EventBinding(Closed):
    id: str = Field(min_length=1, max_length=64)
    revision_id: str = Field(min_length=1, max_length=64)
    revision: int = Field(ge=1)
    fingerprint: Sha256


class ExecutionBinding(Closed):
    mode: Literal['private_http', 'source_review_only']
    run_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    runner_sha256: Sha256
    product_source_fingerprint: Sha256
    private_http_observed: bool


class SourceReviewActual(Closed):
    original_verified: bool
    capture_receipt_verified: bool
    agent_review_record_verified: bool
    exact_sku_truth: Literal['unknown']
    findings: list[Code] = Field(max_length=40)


class ProfessionalGoldenActual(Closed):
    schema_id: Literal['professional-golden-actual@1'] = Field(alias='schema')
    case_id: Label
    input_sha256: Sha256
    execution: ExecutionBinding
    event_binding: EventBinding | None
    event_snapshot: dict[str, JsonValue] | None
    sku_bindings: list[SkuBinding] = Field(max_length=60)
    material_bindings: list[MaterialBinding] = Field(max_length=3)
    bridge_results: list[BridgeActual] = Field(max_length=60)
    candidate_result: HttpObservation | None
    source_review_result: SourceReviewActual | None

    @model_validator(mode='after')
    def preserve_execution_scope(self):
        if self.execution.mode == 'source_review_only':
            if (self.execution.private_http_observed or self.event_binding is not None or self.event_snapshot is not None or self.sku_bindings
                    or self.bridge_results or self.candidate_result is not None or self.source_review_result is None):
                raise ValueError('Source-only review cannot claim fabricated R71/R75 HTTP execution')
        elif not self.execution.private_http_observed or self.source_review_result is not None:
            raise ValueError('Private HTTP actuals must contain an observed private HTTP execution')
        return self


class Difference(Closed):
    code: Code
    path: str = Field(max_length=4096)
    expected_present: bool
    expected: JsonValue
    actual_present: bool
    actual: JsonValue


class TierCoverage(Closed):
    total: int = Field(ge=0, le=MAX_CASES)
    completed: int = Field(ge=0, le=MAX_CASES)
    passed: int = Field(ge=0, le=MAX_CASES)
    failed: int = Field(ge=0, le=MAX_CASES)
    known_link_assertions: int = Field(ge=0)
    checked_known_link_assertions: int = Field(ge=0)
    expected_positive_links: int = Field(ge=0)
    observed_positive_links: int = Field(ge=0)
    unknown_link_assertions: int = Field(ge=0)
    known_distinct_pairs: int = Field(ge=0)
    checked_distinct_pairs: int = Field(ge=0)
    observed_wrong_links: int = Field(ge=0)
    observed_unsupported_links: int = Field(ge=0)
    observed_wrong_merges: int = Field(ge=0)


class CoverageByTier(Closed):
    synthetic_contract: TierCoverage
    real_source_unknown_or_inadmissible: TierCoverage
    real_source_human_reviewed: TierCoverage


class GoldenCoverage(Closed):
    by_tier: CoverageByTier
    known_link_assertions: int = Field(ge=0)
    checked_known_link_assertions: int = Field(ge=0)
    expected_positive_links: int = Field(ge=0)
    observed_positive_links: int = Field(ge=0)
    real_positive_case_count: int = Field(ge=0)
    human_reviewed_case_count: Literal[0]
    known_distinct_pairs: int = Field(ge=0)
    checked_distinct_pairs: int = Field(ge=0)
    unknown_link_assertions: int = Field(ge=0)


class CaseResult(Closed):
    case_id: Label
    tier: Tier
    state: Literal['passed', 'failed', 'inconclusive']
    private_http_observed: Literal[False]
    evaluation_mode: Literal['offline_bound_snapshot']
    positive_link_count: int = Field(ge=0)
    known_link_assertion_count: int = Field(ge=0)
    checked_known_link_assertion_count: int = Field(ge=0)
    expected_positive_link_count: int = Field(ge=0)
    unknown_link_assertion_count: int = Field(ge=0)
    known_distinct_pair_count: int = Field(ge=0)
    checked_distinct_pair_count: int = Field(ge=0)
    observed_wrong_link_count: int = Field(ge=0)
    observed_unsupported_link_count: int = Field(ge=0)
    observed_wrong_merge_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    failures: list[Difference] = Field(max_length=MAX_DIFFS)
    failures_truncated: bool


class GateResult(Closed):
    state: Literal['passed', 'failed', 'inconclusive']
    reason_codes: list[Code] = Field(max_length=MAX_DIFFS)


class ReportGates(Closed):
    schema_integrity: GateResult
    case_coverage: GateResult
    decision_and_distinct_coverage: GateResult
    human_truth_qualification: GateResult


class ProfessionalGoldenReport(Closed):
    schema_id: Literal['professional-golden-report@1'] = Field(alias='schema')
    state: Literal['passed', 'failed', 'inconclusive']
    evaluation_mode: Literal['offline_bound_snapshot']
    release_gate: Literal['inconclusive']
    human_truth_status: Literal['pending_external_review']
    gate_scope: Literal['frozen_professional_set_only']
    contract_fingerprint: Sha256
    manifest_sha256: Sha256
    expected_case_count: int = Field(ge=1, le=MAX_CASES)
    completed_case_count: int = Field(ge=0, le=MAX_CASES)
    case_results: list[CaseResult] = Field(max_length=MAX_CASES)
    coverage: GoldenCoverage
    gates: ReportGates
    observed_wrong_link_count: int = Field(ge=0)
    observed_unsupported_link_count: int = Field(ge=0)
    observed_wrong_merge_count: int = Field(ge=0)
    wrong_merge_count: None
    failure_codes: list[Code] = Field(max_length=MAX_DIFFS)
    limitations: list[str] = Field(max_length=40)


# Comparison implementation is deliberately separate from the closed design above.
from copy import deepcopy
import hashlib
import json
import re

from pydantic import ValidationError

from .professional_golden_corpus import strict_json_loads

_MISSING = object()
_SHA = re.compile(r'^[0-9a-f]{64}$')
_LABEL = re.compile(r'^[a-z][a-z0-9_-]{0,99}$')
_IDENTITY_BASE = ('brand', 'model', 'manufacturer_product_code', 'region', 'size', 'load_index',
    'speed_rating', 'xl', 'hl', 'oe_mark', 'acoustic_technology', 'run_flat')
_PREVIEW_REQUEST = {'mode', 'action', 'link_id', 'selection', 'materials', 'assertions', 'evidence_level'}
_DECISION_EXTRA = {'expected_revision', 'expected_fingerprint', 'declaration_revision_id', 'operator',
    'reason', 'acknowledged', 'opened_materials', 'confirmed_event_revision_id', 'confirmed_participant_hash'}
_R75_REQUEST = {'selection', 'expected_event_revision_id', 'expected_event_revision', 'expected_event_fingerprint',
    'expected_preference_revision', 'expected_preference_fingerprint', 'candidates', 'metric_dimensions'}
_BOUNDARY = {'material_origin': 'operator_supplied', 'origin_verification': 'unverified',
    'read_scope': 'local_workspace', 'test_record_kind': 'manual_transcription', 'test_verification': 'unverified',
    'provider_use': False, 'export': False}
_HISTORY_FIELDS = {'revision', 'action', 'review_state', 'declaration_revision_id', 'declared_by_user_id',
    'actor_user_id', 'operator', 'reason', 'fingerprint', 'revision_id', 'created_at'}


class ProfessionalGoldenError(ValueError):
    """Fixed error codes only; schema errors never echo a rejected body."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False).encode('utf-8', errors='strict')


def json_sha256(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _raw(value):
    if isinstance(value, Closed):
        value = value.model_dump(mode='json', by_alias=True)
    if type(value) is bytes:
        return strict_json_loads(value)
    return strict_json_loads(canonical_bytes(value))


def load_case(value):
    try:
        result = ProfessionalGoldenCase.model_validate(_raw(value))
        _case_graph(result)
        return result
    except ProfessionalGoldenError:
        raise
    except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ProfessionalGoldenError('professional_golden_case_invalid') from None


def load_actual(value):
    try:
        return ProfessionalGoldenActual.model_validate(_raw(value))
    except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ProfessionalGoldenError('professional_golden_actual_invalid') from None


def _unique(values):
    return len(values) == len(set(values))


def _case_graph(case):
    """Validate the independent oracle graph without consulting product output."""
    data = case.input
    materials = {m.material_label for m in case.materials}
    skus = {s.sku_label for s in data.skus}
    attempts = {a.attempt_id for a in data.bridge_attempts}
    valid = (_unique([m.material_label for m in case.materials])
        and _unique([s.sku_label for s in data.skus]) and _unique([a.attempt_id for a in data.bridge_attempts])
        and _unique([e.attempt_id for e in case.expected.bridges])
        and {e.attempt_id for e in case.expected.bridges} == attempts)
    if data.mode == 'source_review_only':
        valid = (valid and case.tier == 'real_source_unknown_or_inadmissible'
            and not case.expected.bridges and not case.expected.distinct_pairs and case.expected.candidate is None
            and data.source_review.material_label in materials
            and case.expected.source_review_findings == data.source_review.findings
            and _unique(data.source_review.findings))
    else:
        event = data.event
        people = {p.key for p in event.participants}
        metrics = {m.key for m in event.metrics}
        pairs = [(m.participant_key, m.metric_key) for m in event.measurements]
        valid = (valid and _unique([p.key for p in event.participants])
            and _unique([m.key for m in event.metrics]) and _unique(pairs)
            and all(p in people and m in metrics for p, m in pairs)
            and {p for p, _m in pairs} == people and {m for _p, m in pairs} == metrics
            and (event.reported_participants is None or event.reported_participants >= len(people))
            and (event.coverage != 'full_event' or event.reported_participants == len(people)))
        evidence_refs = set()
        for attempt in data.bridge_attempts:
            valid = (valid and attempt.sku_label in skus and attempt.participant_key in people
                and _unique(attempt.material_labels) and set(attempt.material_labels) <= materials
                and _unique([a.field for a in attempt.assertions])
                and all(a.material_label in attempt.material_labels for a in attempt.assertions))
            if attempt.participant_locator is not None:
                evidence_refs.update(f'{label}:page{attempt.participant_locator.page}:participant-{attempt.participant_key}'
                                     for label in attempt.material_labels)
        pair_ids = []
        for pair in case.expected.distinct_pairs:
            pair_ids.append(tuple(sorted((pair.left_sku_label, pair.right_sku_label))))
            valid = (valid and pair.left_sku_label in skus and pair.right_sku_label in skus
                and pair.left_sku_label != pair.right_sku_label and bool(pair.evidence_refs)
                and _unique(pair.evidence_refs) and set(pair.evidence_refs) <= evidence_refs)
            if pair.truth == 'distinct' and pair.left_sku_label in skus and pair.right_sku_label in skus:
                values = {sku.sku_label: sku.value.model_dump(mode='json') for sku in data.skus}
                valid = valid and _oracle_identity(values[pair.left_sku_label]) != _oracle_identity(values[pair.right_sku_label])
                for label in (pair.left_sku_label, pair.right_sku_label):
                    identity = _oracle_identity(values[label])
                    valid = (valid and type(identity['manufacturer_product_code']) is str
                        and bool(identity['manufacturer_product_code'])
                        and type(identity['product_code_type']) is str and bool(identity['product_code_type'])
                        and all(type(identity[key]) is bool for key in ('xl', 'hl', 'run_flat'))
                        and all(type(identity[key]) is str and bool(identity[key]) for key in
                            ('brand', 'model', 'region', 'size', 'load_index', 'speed_rating')))
                    label_refs = {f'{material}:page{attempt.participant_locator.page}:participant-{attempt.participant_key}'
                        for attempt in data.bridge_attempts if attempt.sku_label == label and attempt.participant_locator is not None
                        for material in attempt.material_labels}
                    valid = valid and bool(label_refs & set(pair.evidence_refs))
        valid = valid and _unique(pair_ids) and not case.expected.source_review_findings
        candidate = data.candidate
        valid = valid and ((candidate is None) == (case.expected.candidate is None))
        if candidate is not None:
            mapping = [m.metric_key for m in candidate.metric_dimensions]
            selected = {a.attempt_id: a for a in data.bridge_attempts}
            expected = case.expected.candidate
            valid = (valid and _unique(candidate.attempt_ids) and set(candidate.attempt_ids) <= attempts
                and _unique(candidate.reviewed_fitment_sku_labels)
                and set(candidate.reviewed_fitment_sku_labels) <= skus and _unique(mapping) and set(mapping) == metrics
                and _unique(expected.eligible_sku_labels) and set(expected.eligible_sku_labels) <= skus
                and _unique([e.sku_label for e in expected.excluded])
                and {e.sku_label for e in expected.excluded} <= skus
                and _unique([m.metric_key for m in expected.metric_comparisons]))
            if set(candidate.attempt_ids) <= attempts:
                valid = (valid and _unique([selected[a].sku_label for a in candidate.attempt_ids])
                    and _unique([selected[a].participant_key for a in candidate.attempt_ids]))
            for comparison in expected.metric_comparisons:
                valid = (valid and comparison.metric_key in metrics
                    and _unique(comparison.observed_participant_keys) and _unique(comparison.missing_participant_keys)
                    and set(comparison.observed_participant_keys) <= people
                    and set(comparison.missing_participant_keys) <= people
                    and not set(comparison.observed_participant_keys) & set(comparison.missing_participant_keys)
                    and (comparison.favorable_participant_keys is None or
                         set(comparison.favorable_participant_keys) <= set(comparison.observed_participant_keys)))
    if not valid:
        raise ProfessionalGoldenError('professional_golden_case_graph_invalid')


def _display(value):
    try:
        raw = canonical_bytes(value)
    except (ValueError, TypeError, UnicodeError):
        return None
    return value if len(raw) <= 1000 else {'sha256': hashlib.sha256(raw).hexdigest(), 'truncated': True}


class _Failures:
    def __init__(self):
        self.items, self.count = [], 0

    def add(self, code, path='', expected=_MISSING, actual=_MISSING):
        self.count += 1
        if len(self.items) < MAX_DIFFS:
            self.items.append({'code': 'professional_golden_' + code, 'path': path,
                'expected_present': expected is not _MISSING,
                'expected': None if expected is _MISSING else _display(expected),
                'actual_present': actual is not _MISSING,
                'actual': None if actual is _MISSING else _display(actual)})

    def compare(self, expected, actual, path, code='value_mismatch'):
        if expected is _MISSING or actual is _MISSING:
            if expected is not actual:
                self.add(code, path, expected, actual)
        elif type(expected) is not type(actual):
            self.add(code, path, expected, actual)
            if code != 'actual_schema_invalid':
                self.add('actual_schema_invalid', path)
        elif type(expected) is dict:
            for key in sorted(set(expected) | set(actual)):
                self.compare(expected.get(key, _MISSING), actual.get(key, _MISSING), path + '/' + key, code)
        elif type(expected) is list:
            for index in range(max(len(expected), len(actual))):
                self.compare(expected[index] if index < len(expected) else _MISSING,
                    actual[index] if index < len(actual) else _MISSING, path + '/' + str(index), code)
        elif expected != actual:
            self.add(code, path, expected, actual)


def _fields(value, fields, failures, path):
    if type(value) is not dict or set(value) != set(fields):
        failures.add('actual_schema_invalid', path)
        return False
    return True


def _oracle_identity(value):
    """Independent literal projection; never imports the product identity function."""
    result = {key: deepcopy(value[key]) for key in _IDENTITY_BASE}
    for key in ('gtin', 'technology_features', 'eprel_id'):
        item = value['facts'].get(key)
        if item is not None:
            result[key] = sorted(item, key=lambda child: canonical_bytes(child)) if type(item) is list else deepcopy(item)
    result['product_code_type'] = value['facts'].get('product_code_type')
    return result


def _pair_observations(case, raw):
    """Observe known-label collisions before rejecting an otherwise broken actual."""
    bindings = raw.get('sku_bindings', []) if type(raw) is dict else []
    available = {}
    if type(bindings) is list:
        for binding in bindings:
            if type(binding) is not dict or type(binding.get('sku_label')) is not str:
                continue
            label = binding['sku_label']
            if label not in {s.sku_label for s in case.input.skus}:
                continue
            identifier = binding.get('variant_id')
            member = binding.get('snapshot_member')
            key = member.get('identity_key') if type(member) is dict else None
            identity = binding.get('identity')
            valid_id = type(identifier) is str and 1 <= len(identifier) <= 64
            valid_key = type(key) is str and _SHA.fullmatch(key) is not None
            identity_hash = None
            if type(identity) is dict:
                try:
                    identity_hash = json_sha256(identity)
                except (ValueError, TypeError, UnicodeError):
                    pass
            available.setdefault(label, []).append((identifier if valid_id else None,
                                                    key if valid_key else None, identity_hash))
    known, checked, wrong = 0, 0, 0
    for pair in case.expected.distinct_pairs:
        if pair.truth != 'distinct':
            continue
        known += 1
        left, right = available.get(pair.left_sku_label, []), available.get(pair.right_sku_label, [])
        if len(left) == len(right) == 1 and all(item[0] is not None and item[1] is not None for item in left + right):
            checked += 1
        if any(any(a[index] is not None and a[index] == b[index] for index in (0, 1, 2)) for a in left for b in right):
            wrong += 1
    return known, checked, wrong


def _link_observations(case, raw):
    """Keep independently observed bad admissions visible despite unrelated damage."""
    expectations = {item.attempt_id: item for item in case.expected.bridges}
    runs = raw.get('bridge_results') if type(raw) is dict else None
    positive, wrong, unsupported = set(), set(), set()
    if type(runs) is not list:
        return positive, wrong, unsupported
    for run in runs:
        if type(run) is not dict or type(run.get('attempt_id')) is not str:
            continue
        identifier = run['attempt_id']
        expectation = expectations.get(identifier)
        current = run.get('current')
        if expectation is None or type(current) is not dict or type(current.get('response_body')) is not dict:
            continue
        if current['response_body'].get('eligibility') != 'conditional_reviewed_transcription':
            continue
        positive.add(identifier)
        if expectation.truth == 'not_linked':
            wrong.add(identifier)
        if (expectation.truth == 'unknown' or expectation.current is None
                or expectation.current.eligibility != 'conditional_reviewed_transcription'):
            unsupported.add(identifier)
    return positive, wrong, unsupported


def _boundary(value, failures, path):
    if _fields(value, set(_BOUNDARY) | {'notice'}, failures, path):
        for key, expected in _BOUNDARY.items():
            failures.compare(expected, value[key], path + '/' + key, 'rights_mismatch')
        if type(value['notice']) is not str or not value['notice']:
            failures.add('actual_schema_invalid', path + '/notice')


def _event_snapshot(case, actual, failures):
    path = '/event_snapshot'
    snapshot, bound, event = actual['event_snapshot'], actual['event_binding'], case['input']['event']
    fields = {'id', 'revision', 'revision_id', 'state', 'title', 'organization', 'tested_size', 'publication_date',
        'relationship', 'coverage', 'participant_count', 'metric_count', 'recorded_at', 'fingerprint',
        'record_kind', 'verification_status', 'verified_at', 'data_state', 'scope', 'event', 'participants',
        'history', 'history_truncated'}
    if not _fields(snapshot, fields, failures, path):
        return
    expected = {**bound, **{key: event[key] for key in
        ('title', 'organization', 'tested_size', 'publication_date', 'relationship', 'coverage')},
        'state': 'active', 'participant_count': len(event['participants']), 'metric_count': len(event['metrics']),
        'record_kind': 'manual_transcription', 'verification_status': 'unverified', 'verified_at': None,
        'data_state': 'local_snapshot', 'scope': 'local_workspace', 'event': event, 'history_truncated': False,
        'participants': [{**person, 'id': bound['id'] + ':' + person['key'], 'identity_status': 'participant_only'}
                         for person in event['participants']]}
    for key, value in expected.items():
        failures.compare(value, snapshot[key], path + '/' + key, 'source_value_mismatch')
    if type(snapshot['recorded_at']) is not str or not snapshot['recorded_at']:
        failures.add('actual_schema_invalid', path + '/recorded_at')
    history = snapshot['history']
    if type(history) is not list or len(history) != 1:
        failures.add('actual_schema_invalid', path + '/history')
    elif _fields(history[0], {'id', 'revision', 'action', 'state', 'operator', 'reason', 'recorded_at', 'fingerprint'}, failures, path + '/history/0'):
        for key, value in {'id': bound['revision_id'], 'revision': bound['revision'], 'action': 'create',
                'state': 'active', 'recorded_at': snapshot['recorded_at'], 'fingerprint': bound['fingerprint']}.items():
            failures.compare(value, history[0][key], path + '/history/0/' + key, 'binding_mismatch')
        for key in ('operator', 'reason'):
            if type(history[0][key]) is not str or not history[0][key]:
                failures.add('actual_schema_invalid', path + '/history/0/' + key)


def _candidate_projection(case, actual, request, projection, failures):
    """Check exact candidate identity and axis without trusting a declared projection."""
    path = '/candidate_result/response_body/candidate_projection'
    fields = {'schema', 'policy_version', 'data_state', 'scope', 'evidence_scope', 'selection', 'vehicle_binding',
        'preference', 'research_focus', 'items', 'excluded_relations', 'inspected_count', 'relation_count',
        'truncated', 'ranking', 'performance_score', 'official_oe', 'notices'}
    if not _fields(projection, fields, failures, path):
        return
    data = case['input']['candidate']
    dimensions = ('dry', 'wet', 'quiet', 'comfort', 'wear', 'energy', 'appearance')
    ordered = sorted(dimensions, key=lambda key: (-data['preference_weights'][key], dimensions.index(key)))
    preference = {'revision': request['expected_preference_revision'],
        'fingerprint': request['expected_preference_fingerprint'], 'weights': data['preference_weights']}
    expected_fingerprint = json_sha256({'schema': 'driving-preference-state@1',
        'revision': preference['revision'], 'weights': preference['weights']})
    failures.compare(expected_fingerprint, preference['fingerprint'], path + '/preference/fingerprint', 'binding_mismatch')
    for key, value in {'schema': 'fitment-candidates@1', 'policy_version': 'reviewed-exact-axle@1',
            'data_state': 'local_snapshot', 'scope': 'actor', 'evidence_scope': 'local_workspace',
            'selection': request['selection'], 'preference': preference, 'truncated': False,
            'ranking': 'not_computed', 'performance_score': None, 'excluded_relations': [],
            'inspected_count': len(data['reviewed_fitment_sku_labels']),
            'relation_count': len(data['reviewed_fitment_sku_labels']),
            'research_focus': [{'dimension': key, 'weight': data['preference_weights'][key],
                'evidence_status': 'exact_sku_performance_not_established'} for key in ordered]}.items():
        failures.compare(value, projection[key], path + '/' + key, 'binding_mismatch')
    selected = request['selection']
    if _fields(selected, {'vehicle_id', 'vehicle_snapshot_id', 'trim_id', 'wheel_option_id', 'axle'}, failures, path + '/selection'):
        for key, value in {'vehicle_id': 'synthetic-vehicle-gen1', 'trim_id': 'synthetic-trim',
                'wheel_option_id': 'synthetic-option', 'axle': data['axle']}.items():
            failures.compare(value, selected[key], path + '/selection/' + key, 'binding_mismatch')
    vehicle = projection['vehicle_binding']
    if _fields(vehicle, {'snapshot_id', 'current_snapshot_id', 'fact_hash', 'fact_version', 'scope'}, failures, path + '/vehicle_binding'):
        for key in ('snapshot_id', 'current_snapshot_id'):
            failures.compare(selected['vehicle_snapshot_id'], vehicle[key], path + '/vehicle_binding/' + key, 'binding_mismatch')
        failures.compare(1, vehicle['fact_version'], path + '/vehicle_binding/fact_version')
        failures.compare({'vehicle_id': selected['vehicle_id'], 'generation': 'generation-1', 'model_year': None,
            'region': 'CN', 'source_vehicle_id': 'synthetic-source-gen1', 'trim_id': selected['trim_id'],
            'trim_model_year': None, 'wheel_option_id': selected['wheel_option_id'], 'axle': selected['axle']},
            vehicle['scope'], path + '/vehicle_binding/scope', 'binding_mismatch')
        if type(vehicle['fact_hash']) is not str or _SHA.fullmatch(vehicle['fact_hash']) is None:
            failures.add('actual_schema_invalid', path + '/vehicle_binding/fact_hash')
    skus = {row['variant_id']: row for row in actual['sku_bindings'] if row['sku_label'] in data['reviewed_fitment_sku_labels']}
    items = projection['items']
    if type(items) is not list or len(items) != len(skus):
        failures.add('coverage_incomplete', path + '/items')
        return
    failures.compare(sorted(skus), [item.get('variant_id') for item in items if type(item) is dict], path + '/items/variant_ids', 'binding_mismatch')
    for index, item in enumerate(items):
        location = path + '/items/' + str(index)
        if not _fields(item, {'variant_id', 'identity', 'relations', 'performance_score', 'ranking', 'official_oe'}, failures, location):
            continue
        sku = skus.get(item['variant_id']) if type(item['variant_id']) is str else None
        if sku is None:
            failures.add('binding_mismatch', location)
            continue
        for key, value in {'identity': sku['identity'], 'performance_score': None, 'ranking': 'not_computed',
                'official_oe': projection['official_oe']}.items():
            failures.compare(value, item[key], location + '/' + key, 'binding_mismatch')
        relations = item['relations']
        if type(relations) is not list or len(relations) != 1:
            failures.add('coverage_incomplete', location + '/relations')
            continue
        relation = relations[0]
        if not _fields(relation, {'relation_id', 'revision_id', 'revision', 'binding_hash', 'selection',
                'vehicle_evidence', 'tire_evidence', 'checks', 'unknown_fields', 'acknowledged_unknowns', 'evidence'}, failures, location + '/relations/0'):
            continue
        failures.compare(2, relation['revision'], location + '/relations/0/revision')
        failures.compare(True, relation['acknowledged_unknowns'], location + '/relations/0/acknowledged_unknowns')
        failures.compare({**selected, **{key: sku[key] for key in ('variant_id', 'tire_snapshot_id', 'fact_version_id')}},
            relation['selection'], location + '/relations/0/selection', 'binding_mismatch')
        tire = relation['tire_evidence']
        if type(tire) is not dict:
            failures.add('actual_schema_invalid', location + '/relations/0/tire_evidence')
        else:
            for key, value in {'variant_id': sku['variant_id'], 'identity': sku['identity'],
                    'facts': sku['snapshot_member']['facts'], 'fact_version_id': sku['fact_version_id'],
                    'facts_hash': json_sha256(sku['snapshot_member']['facts'])}.items():
                failures.compare(value, tire.get(key, _MISSING), location + '/relations/0/tire_evidence/' + key, 'binding_mismatch')
            locator = tire.get('structured_locator')
            failures.compare({'kind': 'tire_snapshot_parsed_variants', 'json_pointer': '/parsed_variants/0',
                'snapshot_id': sku['tire_snapshot_id'], 'variant_index': 0, 'variant_id': sku['variant_id']},
                locator, location + '/relations/0/tire_evidence/structured_locator', 'binding_mismatch')


def _observation(value, operation, path, failures, location):
    failures.compare(operation, value['operation'], location + '/operation', 'http_binding_mismatch')
    failures.compare('GET' if operation == 'r71_current' else 'POST', value['method'], location + '/method', 'http_binding_mismatch')
    failures.compare(path, value['path'], location + '/path', 'http_binding_mismatch')
    failures.compare(json_sha256(value['request_body']), value['request_sha256'], location + '/request_sha256', 'http_binding_mismatch')
    failures.compare(json_sha256(value['response_body']), value['response_sha256'], location + '/response_sha256', 'http_binding_mismatch')


def _error_code(observation):
    detail = observation['response_body'].get('detail')
    return detail.get('code') if type(detail) is dict else None


def _source_participant(event, key):
    return next(p for p in event['participants'] if p['key'] == key)


def _bridge_request(case, attempt, actual):
    sku = next(s for s in actual['sku_bindings'] if s['sku_label'] == attempt['sku_label'])
    materials = {m['material_label']: m for m in actual['material_bindings']}
    literals = {m['material_label']: m for m in case['materials']}
    selected = actual['event_binding']
    return {'mode': 'history', 'action': 'create', 'link_id': None,
        'selection': {'event_id': selected['id'], 'event_revision_id': selected['revision_id'],
            'participant_key': attempt['participant_key'], 'variant_id': sku['variant_id'],
            'tire_snapshot_id': sku['tire_snapshot_id'], 'fact_version_id': sku['fact_version_id']},
        'materials': [{'document_id': materials[label]['document_id'],
            'expected_raw_hash': materials[label]['raw_sha256'], 'expected_metadata_hash': materials[label]['metadata_sha256'],
            'event_locator': attempt['event_locator'], 'participant_locator': attempt['participant_locator'],
            'rights': {key: literals[label]['rights'][key] for key in
                       ('rights_holder', 'basis', 'store_original', 'workspace_reopen', 'quote_identifiers')}}
            for label in attempt['material_labels']],
        'assertions': [{**{k: a[k] for k in ('field', 'material_value', 'page', 'region', 'quote')},
            'material_document_id': materials[a['material_label']]['document_id']} for a in attempt['assertions']],
        'evidence_level': attempt['evidence_level']}


def _preview_binding(case, attempt, actual, binding, failures, path):
    if not _fields(binding, {'policy_version', 'test', 'identity_contract', 'identity_resolution', 'lifecycle', 'catalogs'}, failures, path):
        return
    bound = actual['event_binding']
    person = _source_participant(case['input']['event'], attempt['participant_key'])
    sku = next(row for row in actual['sku_bindings'] if row['sku_label'] == attempt['sku_label'])
    member = sku['snapshot_member']
    failures.compare('supplied-test-sku-link@1', binding['policy_version'], path + '/policy_version')
    failures.compare({'event_id': bound['id'], 'revision_id': bound['revision_id'], 'revision': bound['revision'],
        'state': 'active', 'fingerprint': bound['fingerprint'], 'participant_hash': json_sha256(person),
        'participant_present': True}, binding['test'], path + '/test', 'binding_mismatch')
    contract = binding['identity_contract']
    if _fields(contract, {'schema', 'state', 'binding_id', 'binding_fingerprint', 'identity', 'identity_status', 'current_key'}, failures, path + '/identity_contract'):
        for key, value in {'schema': 'variant-identity@2', 'state': 'current', 'identity': sku['identity'],
                'identity_status': member.get('identity_status'), 'current_key': member.get('identity_key')}.items():
            failures.compare(value, contract[key], path + '/identity_contract/' + key, 'binding_mismatch')
        if type(contract['binding_id']) is not str or not 1 <= len(contract['binding_id']) <= 64:
            failures.add('actual_schema_invalid', path + '/identity_contract/binding_id')
        if type(contract['binding_fingerprint']) is not str or _SHA.fullmatch(contract['binding_fingerprint']) is None:
            failures.add('actual_schema_invalid', path + '/identity_contract/binding_fingerprint')
    failures.compare({'id': None, 'revision': 0, 'state': 'independent'}, binding['identity_resolution'], path + '/identity_resolution', 'binding_mismatch')
    failures.compare({'id': None, 'revision': 0, 'state': 'active'}, binding['lifecycle'], path + '/lifecycle', 'binding_mismatch')
    catalogs = binding['catalogs']
    if type(catalogs) is not list or len(catalogs) != 1:
        failures.add('binding_mismatch', path + '/catalogs')
    else:
        tire = next(run['preview']['response_body']['frozen_evidence']['tire'] for run in actual['bridge_results']
            if run['attempt_id'] == attempt['attempt_id'])
        failures.compare([{'source_id': tire['source_id'], 'query_key': tire['query_key'], 'present': True,
            'transition_revision': 1}], catalogs, path + '/catalogs', 'binding_mismatch')


def _bridge_chain(case, attempt, actual, run, actions, failures, path):
    """Bind every acknowledgement, declaration, revision and final current view."""
    preview = run['preview']['response_body']
    events, links = [], []
    bound = actual['event_binding']
    person_hash = json_sha256(_source_participant(case['input']['event'], attempt['participant_key']))
    link_id = None
    for index, decision in enumerate(run['decisions']):
        if decision['http_status'] != 201:
            continue
        location = path + '/decisions/' + str(index)
        response, request = decision['response_body'], decision['request_body']
        link, event = response['link'], response['event']
        action = actions[index] if index < len(actions) else None
        review_state = {'create': 'pending_review', 'review': 'reviewed', 'revoke': 'revoked'}.get(action)
        failures.compare(False, response['idempotent_replay'], location + '/idempotent_replay')
        if not _fields(event, _HISTORY_FIELDS, failures, location + '/event'):
            continue
        if index == 0:
            link_id = link['id']
        if type(link_id) is not str or not 1 <= len(link_id) <= 64:
            failures.add('actual_schema_invalid', location + '/link/id')
        declaration = link['revision_id'] if index == 0 else links[0]['revision_id']
        actor = event['actor_user_id']
        if type(actor) is not str or not 1 <= len(actor) <= 64:
            failures.add('actual_schema_invalid', location + '/event/actor_user_id')
        if index and action == 'review' and actor == events[0]['actor_user_id']:
            failures.add('binding_mismatch', location + '/event/actor_user_id')
        expected_link = {'id': link_id, 'revision': index + 1, 'review_state': review_state,
            'effective_state': review_state, 'declared_by_user_id': events[0]['actor_user_id'] if events else actor,
            'declaration_revision_id': declaration, 'binding_hash': preview['binding_hash'], 'history_truncated': False}
        for key, value in expected_link.items():
            failures.compare(value, link[key], location + '/link/' + key, 'binding_mismatch')
        if type(link['revision_id']) is not str or not 1 <= len(link['revision_id']) <= 64 or any(
                previous['revision_id'] == link['revision_id'] for previous in links):
            failures.add('binding_mismatch', location + '/link/revision_id')
        for key in ('revision_id', 'revision', 'review_state', 'declared_by_user_id', 'declaration_revision_id', 'fingerprint'):
            failures.compare(link[key], event[key], location + '/event/' + key, 'binding_mismatch')
        failures.compare(action, event['action'], location + '/event/action', 'binding_mismatch')
        for key in ('operator', 'reason'):
            failures.compare(request[key], event[key], location + '/event/' + key, 'binding_mismatch')
            if type(event[key]) is not str or not event[key].strip():
                failures.add('actual_schema_invalid', location + '/event/' + key)
        if type(event['created_at']) is not str or not event['created_at']:
            failures.add('actual_schema_invalid', location + '/event/created_at')
        failures.compare(list(reversed(events + [event])), link['history'], location + '/link/history', 'binding_mismatch')
        for key, value in {'link_id': None if index == 0 else link_id,
                'declaration_revision_id': None if index == 0 else links[0]['revision_id'],
                'confirmed_event_revision_id': bound['revision_id'], 'confirmed_participant_hash': person_hash,
                'opened_materials': [{'document_id': row['document_id'], 'raw_hash': row['raw_hash'],
                    'metadata_hash': row['metadata_hash']} for row in preview['material_evidence']]}.items():
            failures.compare(value, request[key], location + '/request_body/' + key, 'binding_mismatch')
        request_preview = {key: request[key] for key in _PREVIEW_REQUEST}
        basis = {'request': request_preview, 'revision': index,
            'previous_fingerprint': links[-1]['fingerprint'] if links else None,
            'frozen_evidence': preview['frozen_evidence'], 'material_evidence': preview['material_evidence'],
            'assertions': preview['assertions'], 'binding': preview['binding'], 'actor_user_id': actor}
        failures.compare(json_sha256(basis), request['expected_fingerprint'], location + '/request_body/expected_fingerprint', 'binding_mismatch')
        if index == 0:
            failures.compare(preview['fingerprint'], request['expected_fingerprint'], location + '/request_body/expected_fingerprint', 'binding_mismatch')
        links.append(link)
        events.append(event)
    if links and run['current'] is not None and run['current']['http_status'] == 200:
        final = run['current']['response_body']
        failures.compare({key: value for key, value in links[-1].items() if key != 'allowed_actions'},
            {key: value for key, value in final.items() if key != 'allowed_actions'}, path + '/current/decision_binding', 'binding_mismatch')


def _bridge_body(case, attempt, actual, body, failures, path, *, preview=False):
    """Check original literals and critical nested shapes, without accepting projections as truth."""
    request = _bridge_request(case, attempt, actual)
    for key in ('selection', 'materials', 'evidence_level'):
        failures.compare(request[key], body[key], path + '/' + key, 'binding_mismatch')
    expected_assertions = [{**a, 'quote_sha256': hashlib.sha256(a['quote'].encode('utf-8')).hexdigest()}
                           for a in request['assertions']]
    failures.compare(expected_assertions, body['assertions'], path + '/assertions', 'source_value_mismatch')
    failures.compare('test-sku-link@1', body['schema'], path + '/schema', 'actual_schema_invalid')
    failures.compare('local_workspace', body['scope'], path + '/scope', 'actual_schema_invalid')
    failures.compare('local_snapshot', body['data_state'], path + '/data_state', 'actual_schema_invalid')
    _boundary(body['boundary'], failures, path + '/boundary')
    frozen = body['frozen_evidence']
    if not _fields(frozen, {'test', 'tire'}, failures, path + '/frozen_evidence'):
        return
    event = case['input']['event']
    bound = actual['event_binding']
    participant = _source_participant(event, attempt['participant_key'])
    expected_test = {'event_id': bound['id'], 'revision_id': bound['revision_id'], 'revision': bound['revision'],
        'state': 'active', 'fingerprint': bound['fingerprint'], 'event': event, 'participant': participant,
        'participant_hash': json_sha256(participant), 'participant_present': True}
    failures.compare(expected_test, frozen['test'], path + '/frozen_evidence/test', 'source_value_mismatch')
    sku = next(s for s in actual['sku_bindings'] if s['sku_label'] == attempt['sku_label'])
    tire = frozen['tire']
    tire_fields = {'snapshot_id', 'identity', 'identity_key', 'identity_status', 'identity_contract_version', 'facts',
        'fact_version_id', 'fact_version', 'facts_hash', 'structured_locator', 'variant_id', 'source_id', 'query_key',
        'raw_hash', 'snapshot_member', 'parsed_variants_hash', 'provenance'}
    if _fields(tire, tire_fields, failures, path + '/frozen_evidence/tire'):
        for key, expected in {'variant_id': sku['variant_id'], 'snapshot_id': sku['tire_snapshot_id'],
                'fact_version_id': sku['fact_version_id'], 'identity': sku['identity'],
                'snapshot_member': sku['snapshot_member'], 'identity_key': sku['snapshot_member'].get('identity_key'),
                'facts': sku['snapshot_member'].get('facts'),
                'identity_status': 'complete' if all(value is not None for value in sku['identity'].values()) else 'source_scoped',
                'identity_contract_version': 'variant-identity@2', 'fact_version': 1,
                'structured_locator': '/parsed_variants/0',
                'parsed_variants_hash': json_sha256([sku['snapshot_member']])}.items():
            failures.compare(expected, tire[key], path + '/frozen_evidence/tire/' + key, 'source_value_mismatch')
        for key in ('raw_hash', 'facts_hash', 'parsed_variants_hash'):
            if type(tire[key]) is not str or _SHA.fullmatch(tire[key]) is None:
                failures.add('actual_schema_invalid', path + '/frozen_evidence/tire/' + key)
        failures.compare(json_sha256(tire['facts']), tire['facts_hash'], path + '/facts_hash', 'binding_mismatch')
    failures.compare(bound['revision_id'], body['confirmed_event_revision_id'], path + '/confirmed_event_revision_id', 'binding_mismatch')
    failures.compare(json_sha256(participant), body['confirmed_participant_hash'], path + '/confirmed_participant_hash', 'binding_mismatch')
    expected_materials = []
    bindings = {m['material_label']: m for m in actual['material_bindings']}
    for label in attempt['material_labels']:
        binding = bindings[label]
        literal = next(m for m in case['materials'] if m['material_label'] == label)
        expected_materials.append((binding, literal))
    material_evidence = body['material_evidence']
    if type(material_evidence) is not list or len(material_evidence) != len(expected_materials):
        failures.add('material_binding_mismatch', path + '/material_evidence')
    else:
        for index, (evidence, (binding, literal)) in enumerate(zip(material_evidence, expected_materials)):
            location = path + '/material_evidence/' + str(index)
            fields = {'document_id', 'event_locator', 'participant_locator', 'rights', 'metadata', 'raw_hash',
                      'metadata_hash', 'material_origin', 'origin_verification', 'read_scope'}
            if not _fields(evidence, fields, failures, location):
                continue
            for key, expected in {'document_id': binding['document_id'], 'raw_hash': literal['original']['sha256'],
                    'metadata_hash': binding['metadata_sha256'], 'material_origin': 'operator_supplied',
                    'origin_verification': 'unverified', 'read_scope': 'local_workspace',
                    'rights': request['materials'][index]['rights']}.items():
                failures.compare(expected, evidence[key], location + '/' + key, 'material_binding_mismatch')
            for key in ('event_locator', 'participant_locator'):
                locator = request['materials'][index][key]
                failures.compare({**locator, 'quote_sha256': hashlib.sha256(locator['quote'].encode()).hexdigest()},
                                 evidence[key], location + '/' + key, 'source_value_mismatch')
            metadata = evidence['metadata']
            metadata_fields = {'id', 'raw_hash', 'byte_count', 'title', 'source_url', 'operator', 'rights_basis',
                               'content_type', 'created_at', 'status', 'accepted_as_facts'}
            if _fields(metadata, metadata_fields, failures, location + '/metadata'):
                for key, expected in {'id': binding['document_id'], 'raw_hash': literal['original']['sha256'],
                        'byte_count': literal['original']['byte_count'], 'title': literal['title'],
                        'source_url': literal['source_reference_url'], 'rights_basis': literal['rights']['basis'],
                        'content_type': 'application/pdf', 'status': 'unparsed_receipt', 'accepted_as_facts': False}.items():
                    failures.compare(expected, metadata[key], location + '/metadata/' + key, 'material_binding_mismatch')
    checks = body['checks']
    identity = _oracle_identity(next(row['value'] for row in case['input']['skus'] if row['sku_label'] == attempt['sku_label']))
    assertions = {row['field']: row for row in attempt['assertions']}
    expected_checks = []
    for field, value in identity.items():
        assertion = assertions.get(field)
        claimed = assertion['material_value'] if assertion is not None else None
        state = ('unsupported' if value is not None and type(value) not in (str, bool) else
            'unknown' if value is None or assertion is None else
            'match' if type(claimed) is type(value) and claimed == value else 'conflict')
        expected_checks.append({'field': field, 'status': state, 'material_value': claimed, 'sku_value': value})
    for field, value, key in [('test_size_scope', event['tested_size'], 'size'),
            ('test_participant_brand', participant['brand'], 'brand'), ('test_participant_model', participant['model'], 'model')]:
        expected_checks.append({'field': field, 'status': 'match' if type(value) is type(identity[key]) and value == identity[key] else 'conflict',
            'material_value': value, 'sku_value': identity[key]})
    failures.compare(expected_checks, checks, path + '/checks', 'source_value_mismatch')
    failures.compare(list(identity), body['required_identity_fields'], path + '/required_identity_fields', 'source_value_mismatch')
    failures.compare([check['field'] for check in expected_checks if check['status'] in ('unknown', 'unsupported')],
        body['unknown_fields'], path + '/unknown_fields', 'source_value_mismatch')
    if type(checks) is not list:
        failures.add('actual_schema_invalid', path + '/checks')
    else:
        for index, check in enumerate(checks):
            if _fields(check, {'field', 'status', 'material_value', 'sku_value'}, failures, path + '/checks/' + str(index)):
                if type(check['field']) is not str or check['status'] not in ('match', 'conflict', 'unknown', 'unsupported'):
                    failures.add('actual_schema_invalid', path + '/checks/' + str(index))
    for field in ('fingerprint', 'binding_hash'):
        if type(body[field]) is not str or _SHA.fullmatch(body[field]) is None:
            failures.add('actual_schema_invalid', path + '/' + field)
    if preview:
        _preview_binding(case, attempt, actual, body['binding'], failures, path + '/binding')
        failures.compare(json_sha256(body['binding']), body['binding_hash'], path + '/binding_hash', 'binding_mismatch')
        failures.compare('none', body['eligibility'], path + '/eligibility', 'unsupported_link')
        for key, value in {'id': None, 'revision': 0, 'revision_id': None, 'review_state': None,
                'declared_by_user_id': None, 'declaration_revision_id': None, 'allowed_actions': ['create']}.items():
            failures.compare(value, body[key], path + '/' + key, 'binding_mismatch')


def _candidate_body(case, actual, observation, failures):
    path = '/candidate_result'
    expected = case['expected']['candidate']
    _observation(observation, 'r75_interpretation', '/v1/test-events/' + actual['event_binding']['id']
                 + '/candidate-interpretation?mode=history', failures, path)
    failures.compare(expected['http_status'], observation['http_status'], path + '/http_status')
    failures.compare(expected['error_code'], _error_code(observation), path + '/error_code')
    if observation['http_status'] >= 400:
        return
    body = observation['response_body']
    request = observation['request_body']
    if not _fields(request, _R75_REQUEST, failures, path + '/request_body'):
        return
    data = case['input']['candidate']
    event = case['input']['event']
    bound = actual['event_binding']
    for key, value in {'expected_event_revision_id': bound['revision_id'], 'expected_event_revision': bound['revision'],
            'expected_event_fingerprint': bound['fingerprint'], 'metric_dimensions': data['metric_dimensions']}.items():
        failures.compare(value, request[key], path + '/request_body/' + key, 'binding_mismatch')
    if type(request['expected_preference_revision']) is not int or request['expected_preference_revision'] < 1:
        failures.add('actual_schema_invalid', path + '/request_body/expected_preference_revision')
    if type(request['expected_preference_fingerprint']) is not str or _SHA.fullmatch(request['expected_preference_fingerprint']) is None:
        failures.add('actual_schema_invalid', path + '/request_body/expected_preference_fingerprint')
    attempts = {a['attempt_id']: a for a in case['input']['bridge_attempts']}
    runs = {a['attempt_id']: a for a in actual['bridge_results']}
    skus = {s['sku_label']: s for s in actual['sku_bindings']}
    selected = [attempts[key] for key in data['attempt_ids']]
    expected_refs = []
    for attempt in selected:
        current = runs[attempt['attempt_id']]['current']
        if current is None or current['http_status'] != 200:
            failures.add('http_observation_missing', path)
            return
        link = current['response_body']
        expected_refs.append({'variant_id': skus[attempt['sku_label']]['variant_id'], 'link_id': link['id'],
            'expected_link_revision_id': link['revision_id'], 'expected_link_revision': link['revision'],
            'expected_link_fingerprint': link['fingerprint']})
    failures.compare(expected_refs, request['candidates'], path + '/request_body/candidates', 'binding_mismatch')
    failures.compare('test-candidate-interpretation@1', body['schema'], path + '/schema', 'actual_schema_invalid')
    failures.compare('same-event-candidate-interpretation@1', body['policy_version'], path + '/policy_version', 'actual_schema_invalid')
    for key, value in {'data_state': 'local_snapshot', 'scope': 'actor', 'evidence_scope': 'local_workspace',
            'comparison_scope': 'same_event_only', 'ranking': 'source_reported_only', 'performance_score': None,
            'status': expected['status'], 'selection': request['selection'], 'requested_count': len(selected),
            'eligible_count': len(expected['eligible_sku_labels'])}.items():
        failures.compare(value, body[key], path + '/' + key)
    _boundary(body['boundary'], failures, path + '/boundary')
    if type(body['official_oe']) is not dict or body['official_oe'].get('state') != 'not_established':
        failures.add('actual_schema_invalid', path + '/official_oe')
    elif not _fields(body['official_oe'], {'state', 'missing_evidence'}, failures, path + '/official_oe') or (
            type(body['official_oe'].get('missing_evidence')) is not list
            or not body['official_oe']['missing_evidence']
            or any(type(value) is not str or not value for value in body['official_oe']['missing_evidence'])):
        failures.add('actual_schema_invalid', path + '/official_oe/missing_evidence')
    _candidate_projection(case, actual, request, body['candidate_projection'], failures)
    failures.compare(body['official_oe'], body['candidate_projection'].get('official_oe', _MISSING)
        if type(body['candidate_projection']) is dict else _MISSING, path + '/candidate_projection/official_oe')
    if _fields(body['binding'], {'event', 'preference', 'candidate_fingerprint', 'interpretation_fingerprint'}, failures, path + '/binding'):
        failures.compare(bound, body['binding']['event'], path + '/binding/event', 'binding_mismatch')
        preference = {'revision': request['expected_preference_revision'], 'fingerprint': request['expected_preference_fingerprint']}
        failures.compare(preference, body['binding']['preference'], path + '/binding/preference', 'binding_mismatch')
        for key in ('candidate_fingerprint', 'interpretation_fingerprint'):
            if type(body['binding'][key]) is not str or _SHA.fullmatch(body['binding'][key]) is None:
                failures.add('actual_schema_invalid', path + '/binding/' + key)
    source = body['source_evidence']
    source_fields = {'event', 'participants', 'metrics', 'measurements', 'record_kind', 'verification_status',
        'verified_at', 'recorded_at', 'recorded_participant_count', 'selected_participant_count'}
    if _fields(source, source_fields, failures, path + '/source_evidence'):
        participant_keys = {attempt['participant_key'] for attempt in selected}
        participants = [{**p, 'id': bound['id'] + ':' + p['key'], 'identity_status': 'participant_only'}
                        for p in event['participants'] if p['key'] in participant_keys]
        failures.compare({k: v for k, v in event.items() if k not in ('participants', 'metrics', 'measurements')},
                         source['event'], path + '/source_evidence/event', 'source_value_mismatch')
        failures.compare(participants, source['participants'], path + '/source_evidence/participants', 'source_value_mismatch')
        failures.compare(event['metrics'], source['metrics'], path + '/source_evidence/metrics', 'source_value_mismatch')
        measurements = []
        for value in event['measurements']:
            if value['participant_key'] not in participant_keys:
                continue
            pid = bound['id'] + ':' + value['participant_key']
            evidence_id = 'test-measurement:' + json_sha256({'schema': 'test-event-measurement-evidence@1',
                'event_id': bound['id'], 'revision_id': bound['revision_id'], 'event_revision': bound['revision'],
                'event_fingerprint': bound['fingerprint'], 'participant_id': pid, 'metric_key': value['metric_key']})
            measurements.append({**value, 'participant_id': pid, 'evidence_id': evidence_id,
                'reference': {'event_id': bound['id'], 'revision': bound['revision'],
                              'participant_id': pid, 'metric_key': value['metric_key']}})
        failures.compare(measurements, source['measurements'], path + '/source_evidence/measurements', 'source_value_mismatch')
        for key, value in {'record_kind': 'manual_transcription', 'verification_status': 'unverified', 'verified_at': None,
                'recorded_at': actual['event_snapshot']['recorded_at'], 'recorded_participant_count': len(event['participants']),
                'selected_participant_count': len(selected)}.items():
            failures.compare(value, source[key], path + '/source_evidence/' + key, 'source_value_mismatch')
    items = body['items']
    excluded = []
    eligible = []
    if type(items) is not list or len(items) != len(selected):
        failures.add('coverage_incomplete', path + '/items')
    else:
        for index, (attempt, item) in enumerate(zip(selected, items)):
            location = path + '/items/' + str(index)
            if not _fields(item, {'variant_id', 'participant_id', 'participant_key', 'eligible', 'reason_codes', 'link'}, failures, location):
                continue
            label = attempt['sku_label']
            current = runs[attempt['attempt_id']]['current']['response_body']
            for key, value in {'variant_id': skus[label]['variant_id'], 'participant_id': bound['id'] + ':' + attempt['participant_key'],
                    'participant_key': attempt['participant_key']}.items():
                failures.compare(value, item[key], location + '/' + key, 'binding_mismatch')
            failures.compare(label in expected['eligible_sku_labels'], item['eligible'], location + '/eligible')
            if type(item['eligible']) is bool and item['eligible']:
                eligible.append(label)
            else:
                excluded.append({'sku_label': label, 'reason_codes': item['reason_codes']})
            compact_fields = {'id', 'revision_id', 'revision', 'fingerprint', 'binding_hash', 'selection', 'review_state',
                'effective_state', 'eligibility', 'evidence_level', 'materials', 'material_evidence', 'assertions', 'checks',
                'required_identity_fields', 'unknown_fields', 'blockers', 'stale_reasons', 'boundary',
                'declaration_revision_id', 'confirmed_event_revision_id', 'confirmed_participant_hash'}
            failures.compare({key: current[key] for key in compact_fields}, item['link'], location + '/link', 'binding_mismatch')
    failures.compare(expected['eligible_sku_labels'], eligible, path + '/eligible_sku_labels')
    failures.compare(expected['excluded'], excluded, path + '/excluded')
    expected_excluded = [{'variant_id': skus[row['sku_label']]['variant_id'],
        'link_id': next(runs[a['attempt_id']]['current']['response_body']['id'] for a in selected if a['sku_label'] == row['sku_label']),
        'reason_codes': row['reason_codes']} for row in expected['excluded']]
    failures.compare(expected_excluded, body['excluded'], path + '/excluded', 'binding_mismatch')
    personal = body['personal_interpretation']
    failures.compare(expected['personal_interpretation_allowed'], personal is not None, path + '/personal_interpretation_allowed')
    if personal is not None:
        personal_fields = {'mapping_origin', 'weights', 'metric_dimensions', 'dimensions', 'metrics', 'coverage'}
        if not _fields(personal, personal_fields, failures, path + '/personal_interpretation'):
            return
        failures.compare('user_explicit_once', personal['mapping_origin'], path + '/personal_interpretation/mapping_origin')
        failures.compare(data['preference_weights'], personal['weights'], path + '/personal_interpretation/weights')
        canonical_mapping = [{'metric_key': m['key'], 'dimension': next(x['dimension'] for x in data['metric_dimensions'] if x['metric_key'] == m['key'])}
                             for m in event['metrics']]
        failures.compare(canonical_mapping, personal['metric_dimensions'], path + '/personal_interpretation/metric_dimensions')
        failures.compare(expected['coverage'], personal['coverage'], path + '/personal_interpretation/coverage')
        dimensions = ('dry', 'wet', 'quiet', 'comfort', 'wear', 'energy', 'appearance')
        comparisons = expected['metric_comparisons']
        expected_dimensions = [{'dimension': dimension, 'weight': data['preference_weights'][dimension],
            'metric_keys': [metric['metric_key'] for metric in comparisons if metric['dimension'] == dimension],
            'complete_comparable_metric_keys': [metric['metric_key'] for metric in comparisons
                if metric['dimension'] == dimension and metric['complete_comparable']]}
            for dimension in sorted(dimensions, key=lambda key: (-data['preference_weights'][key], dimensions.index(key)))]
        failures.compare(expected_dimensions, personal['dimensions'], path + '/personal_interpretation/dimensions')
        actual_comparisons = []
        for index, metric in enumerate(personal['metrics'] if type(personal['metrics']) is list else []):
            location = path + '/personal_interpretation/metrics/' + str(index)
            fields = {'metric_key', 'dimension', 'observed_participant_ids', 'missing_participant_ids', 'evidence_ids',
                      'limitations', 'complete_comparable', 'observation_comparison'}
            if not _fields(metric, fields, failures, location):
                continue
            prefix = bound['id'] + ':'
            def keys(ids):
                if type(ids) is not list or any(type(pid) is not str or not pid.startswith(prefix) for pid in ids):
                    failures.add('binding_mismatch', location)
                    return []
                return [pid[len(prefix):] for pid in ids]
            comparison = metric['observation_comparison']
            evidence_by_person = {item['participant_id']: item['evidence_id'] for item in source['measurements']
                if item['metric_key'] == metric['metric_key']}
            failures.compare([evidence_by_person.get(pid) for pid in metric['observed_participant_ids']],
                metric['evidence_ids'], location + '/evidence_ids', 'binding_mismatch')
            favorable = None
            if comparison is not None:
                if _fields(comparison, {'scope', 'favorable_participant_ids', 'evidence_ids'}, failures, location + '/observation_comparison'):
                    failures.compare('selected_recorded_observations', comparison['scope'], location + '/scope')
                    favorable = keys(comparison['favorable_participant_ids'])
                    failures.compare([evidence_by_person.get(pid) for pid in comparison['favorable_participant_ids']],
                        comparison['evidence_ids'], location + '/observation_comparison/evidence_ids', 'binding_mismatch')
            actual_comparisons.append({'metric_key': metric['metric_key'], 'dimension': metric['dimension'],
                'observed_participant_keys': keys(metric['observed_participant_ids']),
                'missing_participant_keys': keys(metric['missing_participant_ids']),
                'complete_comparable': metric['complete_comparable'], 'limitations': metric['limitations'],
                'favorable_participant_keys': favorable})
        failures.compare(expected['metric_comparisons'], actual_comparisons, path + '/personal_interpretation/metrics')


def evaluate_case(case, actual):
    """Compare independently authored literals with a bound snapshot; never certify live I/O."""
    failures = _Failures()
    known = checked = wrong_merge = positive = known_links = checked_links = expected_positive = unknown = 0
    wrong_links, unsupported = set(), set()
    case_id, tier = 'invalid-case', 'synthetic_contract'
    try:
        case_model = load_case(case)
        case_id, tier = case_model.case_id, case_model.tier
    except ProfessionalGoldenError as error:
        failures.add(error.code.removeprefix('professional_golden_'))
        case_model = None
    if case_model is not None:
        try:
            raw_actual = _raw(actual)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raw_actual = actual if type(actual) is dict else {}
        known, checked, wrong_merge = _pair_observations(case_model, raw_actual)
        positives, wrong_links, unsupported = _link_observations(case_model, raw_actual)
        positive = len(positives)
        if wrong_merge:
            failures.add('wrong_merge', '/sku_bindings', 0, wrong_merge)
        known_links = sum(e.truth != 'unknown' for e in case_model.expected.bridges)
        unknown = sum(e.truth == 'unknown' for e in case_model.expected.bridges)
        expected_positive = sum(e.truth == 'linked' and e.current is not None
            and e.current.eligibility == 'conditional_reviewed_transcription' for e in case_model.expected.bridges)
        try:
            actual_model = load_actual(actual)
            data = actual_model.model_dump(mode='json', by_alias=True)
            literal = case_model.model_dump(mode='json', by_alias=True)
            failures.compare(case_id, data['case_id'], '/case_id', 'binding_mismatch')
            failures.compare(json_sha256(literal['input']), data['input_sha256'], '/input_sha256', 'binding_mismatch')
            failures.compare(literal['input']['mode'], data['execution']['mode'], '/execution/mode', 'binding_mismatch')
            if case_model.input.mode == 'source_review_only':
                review = data['source_review_result']
                if review is None:
                    failures.add('source_review_missing')
                else:
                    for key in ('original_verified', 'capture_receipt_verified', 'agent_review_record_verified'):
                        failures.compare(True, review[key], '/source_review_result/' + key, 'source_binding_mismatch')
                    failures.compare(literal['expected']['source_review_findings'], review['findings'], '/source_review_result/findings')
                if data['material_bindings']:
                    failures.add('source_binding_mismatch', '/material_bindings')
            else:
                sku_labels = [s['sku_label'] for s in data['sku_bindings']]
                material_labels = [m['material_label'] for m in data['material_bindings']]
                attempt_ids = [r['attempt_id'] for r in data['bridge_results']]
                if (not _unique(sku_labels) or set(sku_labels) != {s.sku_label for s in case_model.input.skus}
                        or not _unique(material_labels) or set(material_labels) != {m.material_label for m in case_model.materials}
                        or not _unique(attempt_ids) or set(attempt_ids) != {a.attempt_id for a in case_model.input.bridge_attempts}
                        or data['event_binding'] is None or data['event_snapshot'] is None):
                    raise ProfessionalGoldenError('professional_golden_actual_graph_invalid')
                bound, snapshot = data['event_binding'], data['event_snapshot']
                _event_snapshot(literal, data, failures)
                for key in bound:
                    failures.compare(bound[key], snapshot.get(key, _MISSING), '/event_snapshot/' + key, 'binding_mismatch')
                failures.compare(literal['input']['event'], snapshot.get('event', _MISSING), '/event_snapshot/event', 'source_value_mismatch')
                failures.compare(json_sha256(literal['input']['event']), bound['fingerprint'], '/event_binding/fingerprint', 'binding_mismatch')
                expected_skus = {s['sku_label']: s['value'] for s in literal['input']['skus']}
                for sku in data['sku_bindings']:
                    path = '/sku_bindings/' + sku['sku_label']
                    member = sku['snapshot_member']
                    fields = set(VariantLiteral.model_fields)
                    if (not fields <= set(member) or not set(member) <= fields | {'id', 'identity_key', 'identity_status',
                            'identity_contract_version', 'fact_version', 'snapshot_id'}):
                        failures.add('actual_schema_invalid', path + '/snapshot_member')
                    failures.compare(expected_skus[sku['sku_label']], {k: member[k] for k in fields if k in member},
                                     path + '/snapshot_member', 'source_value_mismatch')
                    failures.compare(sku['variant_id'], member.get('id', _MISSING), path + '/variant_id', 'binding_mismatch')
                    failures.compare(_oracle_identity(expected_skus[sku['sku_label']]), sku['identity'], path + '/identity', 'source_value_mismatch')
                    status = 'complete' if all(value is not None for value in sku['identity'].values()) else 'source_scoped'
                    failures.compare(status, member.get('identity_status', _MISSING), path + '/identity_status', 'source_value_mismatch')
                    failures.compare(1, member.get('fact_version', _MISSING), path + '/fact_version', 'source_value_mismatch')
                    if status == 'complete':
                        failures.compare(json_sha256({'contract': 'variant-identity@2', 'identity': sku['identity']}),
                            member.get('identity_key', _MISSING), path + '/identity_key', 'binding_mismatch')
                    if type(member.get('identity_key')) is not str or _SHA.fullmatch(member['identity_key']) is None:
                        failures.add('actual_schema_invalid', path + '/identity_key')
                for material in data['material_bindings']:
                    expected_material = next(m for m in literal['materials'] if m['material_label'] == material['material_label'])
                    failures.compare(expected_material['original']['sha256'], material['raw_sha256'], '/material_bindings/raw_sha256', 'material_binding_mismatch')
                    failures.compare(expected_material['original']['byte_count'], material['byte_count'], '/material_bindings/byte_count', 'material_binding_mismatch')
                attempts = {a['attempt_id']: a for a in literal['input']['bridge_attempts']}
                expectations = {e['attempt_id']: e for e in literal['expected']['bridges']}
                for run in data['bridge_results']:
                    attempt_id = run['attempt_id']
                    attempt, expectation = attempts[attempt_id], expectations[attempt_id]
                    path = '/bridge_results/' + attempt_id
                    preview = run['preview']
                    _observation(preview, 'r71_preview', '/v1/test-sku-links/preview', failures, path + '/preview')
                    expected_request = _bridge_request(literal, attempt, data)
                    failures.compare(expected_request, preview['request_body'], path + '/preview/request_body', 'binding_mismatch')
                    failures.compare(expectation['preview']['http_status'], preview['http_status'], path + '/preview/http_status')
                    failures.compare(expectation['preview']['error_code'], _error_code(preview), path + '/preview/error_code')
                    if preview['http_status'] < 400:
                        body = preview['response_body']
                        failures.compare(expectation['preview']['can_submit'], body['can_submit'], path + '/preview/can_submit')
                        failures.compare(expectation['preview']['blockers'], body['blockers'], path + '/preview/blockers')
                        _bridge_body(literal, attempt, data, body, failures, path + '/preview/body', preview=True)
                    expected_actions = (['create'] + (['review'] if attempt['review'] else []) + (['revoke'] if attempt['revoke'] else [])) if expectation['current'] is not None else []
                    failures.compare(len(expected_actions), len(run['decisions']), path + '/decisions/count', 'coverage_incomplete')
                    for index, decision in enumerate(run['decisions']):
                        location = path + '/decisions/' + str(index)
                        _observation(decision, 'r71_decision', '/v1/test-sku-links/decisions', failures, location)
                        request = decision['request_body']
                        if _fields(request, _PREVIEW_REQUEST | _DECISION_EXTRA, failures, location + '/request_body'):
                            if index < len(expected_actions):
                                failures.compare(expected_actions[index], request['action'], location + '/action', 'http_binding_mismatch')
                            for key in ('selection', 'materials', 'assertions', 'evidence_level', 'mode'):
                                failures.compare(expected_request[key], request[key], location + '/request_body/' + key, 'binding_mismatch')
                            failures.compare(True, request['acknowledged'], location + '/acknowledged', 'actual_schema_invalid')
                            if type(request['expected_revision']) is not int or request['expected_revision'] != index:
                                failures.add('binding_mismatch', location + '/expected_revision')
                        if decision['http_status'] != 201:
                            failures.add('decision_failed', location)
                        else:
                            _bridge_body(literal, attempt, data, decision['response_body']['link'], failures, location + '/body')
                    _bridge_chain(literal, attempt, data, run, expected_actions, failures, path)
                    current = run['current']
                    if (current is None) != (expectation['current'] is None):
                        failures.add('coverage_incomplete', path + '/current')
                    elif current is not None:
                        body = current['response_body']
                        link_id = body.get('id')
                        _observation(current, 'r71_current', '/v1/test-sku-links/' + (link_id if type(link_id) is str else '') + '?mode=history', failures, path + '/current')
                        failures.compare(None, current['request_body'], path + '/current/request_body', 'http_binding_mismatch')
                        failures.compare(expectation['current']['http_status'], current['http_status'], path + '/current/http_status')
                        failures.compare(expectation['current']['error_code'], _error_code(current), path + '/current/error_code')
                        if current['http_status'] < 400:
                            _bridge_body(literal, attempt, data, body, failures, path + '/current/body')
                            for field in ('eligibility', 'effective_state', 'blockers', 'stale_reasons'):
                                failures.compare(expectation['current'][field], body[field], path + '/current/' + field)
                            if body['eligibility'] == 'conditional_reviewed_transcription':
                                if expectation['truth'] == 'not_linked':
                                    wrong_links.add(attempt_id)
                                if expectation['truth'] == 'unknown' or expectation['current']['eligibility'] != 'conditional_reviewed_transcription':
                                    unsupported.add(attempt_id)
                            history = body.get('history')
                            if type(history) is not list:
                                failures.add('actual_schema_invalid', path + '/history')
                            else:
                                for item in history:
                                    _fields(item, _HISTORY_FIELDS, failures, path + '/history')
                                failures.compare(list(reversed(expected_actions)), [h.get('action') for h in history if type(h) is dict], path + '/history/actions', 'binding_mismatch')
                            if expectation['truth'] != 'unknown':
                                checked_links += 1
                    elif expectation['truth'] != 'unknown' and preview['http_status'] < 400:
                        checked_links += 1
                if (literal['input']['candidate'] is None) != (data['candidate_result'] is None):
                    failures.add('coverage_incomplete', '/candidate_result')
                elif data['candidate_result'] is not None:
                    _candidate_body(literal, data, data['candidate_result'], failures)
        except ProfessionalGoldenError as error:
            failures.add(error.code.removeprefix('professional_golden_'))
        except (KeyError, TypeError, ValueError, IndexError, StopIteration, AttributeError):
            failures.add('actual_schema_invalid')
    for _item in sorted(wrong_links):
        failures.add('wrong_link', '/bridge_results')
    for _item in sorted(unsupported):
        failures.add('unsupported_link', '/bridge_results')
    result = {'case_id': case_id, 'tier': tier, 'state': 'failed' if failures.count else 'passed',
        'private_http_observed': False, 'evaluation_mode': 'offline_bound_snapshot', 'positive_link_count': positive,
        'known_link_assertion_count': known_links, 'checked_known_link_assertion_count': checked_links,
        'expected_positive_link_count': expected_positive, 'unknown_link_assertion_count': unknown,
        'known_distinct_pair_count': known, 'checked_distinct_pair_count': checked,
        'observed_wrong_link_count': len(wrong_links), 'observed_unsupported_link_count': len(unsupported),
        'observed_wrong_merge_count': wrong_merge, 'failure_count': failures.count, 'failures': failures.items,
        'failures_truncated': failures.count > len(failures.items)}
    return CaseResult.model_validate(result).model_dump(mode='json', by_alias=True)


def evaluate_corpus(cases, actuals, manifest_sha256, contract_fingerprint):
    """Require the exact frozen case-ID set and report engineering separately from human truth."""
    if (type(cases) is not list or not 1 <= len(cases) <= MAX_CASES or type(actuals) is not list
            or type(manifest_sha256) is not str or _SHA.fullmatch(manifest_sha256) is None
            or type(contract_fingerprint) is not str or _SHA.fullmatch(contract_fingerprint) is None):
        raise ProfessionalGoldenError('professional_golden_corpus_invalid')
    raw_cases, raw_actuals = [], []
    try:
        raw_cases = [_raw(case) for case in cases]
        raw_actuals = [_raw(actual) for actual in actuals]
        if sum(len(canonical_bytes(row)) for row in raw_actuals) > 32_000_000:
            raise ValueError('bound exceeded')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ProfessionalGoldenError('professional_golden_corpus_invalid') from None
    expected_ids = [row.get('case_id') for row in raw_cases if type(row) is dict]
    actual_ids = [row.get('case_id') for row in raw_actuals if type(row) is dict]
    failure_codes = set()
    if (len(expected_ids) != len(cases) or len(actual_ids) != len(actuals)
            or any(type(identifier) is not str or _LABEL.fullmatch(identifier) is None for identifier in expected_ids + actual_ids)
            or not _unique(expected_ids) or not _unique(actual_ids) or set(expected_ids) != set(actual_ids)):
        failure_codes.add('professional_golden_case_coverage_incomplete')
    by_id = {row.get('case_id'): row for row in raw_actuals if type(row) is dict and type(row.get('case_id')) is str}
    safe_expected_ids = {identifier for identifier in expected_ids if type(identifier) is str}
    safe_actual_ids = {identifier for identifier in actual_ids if type(identifier) is str}
    results = [evaluate_case(case, by_id.get(case.get('case_id'), {})
        if type(case) is dict and type(case.get('case_id')) is str else {}) for case in raw_cases]
    tier_rows = {tier: {'total': 0, 'completed': 0, 'passed': 0, 'failed': 0, 'known_link_assertions': 0,
        'checked_known_link_assertions': 0, 'expected_positive_links': 0, 'observed_positive_links': 0,
        'unknown_link_assertions': 0, 'known_distinct_pairs': 0, 'checked_distinct_pairs': 0,
        'observed_wrong_links': 0, 'observed_unsupported_links': 0, 'observed_wrong_merges': 0} for tier in TIERS}
    stats_map = {'known_link_assertions': 'known_link_assertion_count', 'checked_known_link_assertions': 'checked_known_link_assertion_count',
        'expected_positive_links': 'expected_positive_link_count', 'observed_positive_links': 'positive_link_count',
        'unknown_link_assertions': 'unknown_link_assertion_count', 'known_distinct_pairs': 'known_distinct_pair_count',
        'checked_distinct_pairs': 'checked_distinct_pair_count'}
    for result in results:
        row = tier_rows[result['tier']]
        row['total'] += 1
        row['completed'] += int(result['case_id'] in by_id)
        row['passed' if result['state'] == 'passed' else 'failed'] += 1
        for key, source in stats_map.items():
            row[key] += result[source]
        for key, source in {'observed_wrong_links': 'observed_wrong_link_count',
                'observed_unsupported_links': 'observed_unsupported_link_count',
                'observed_wrong_merges': 'observed_wrong_merge_count'}.items():
            row[key] += result[source]
        failure_codes.update(item['code'] for item in result['failures'])
        if result['state'] != 'passed' and not result['failures']:
            failure_codes.add('professional_golden_case_failed')
    coverage = {'by_tier': tier_rows, **{key: sum(row[key] for row in tier_rows.values()) for key in stats_map},
        'real_positive_case_count': 0,
        'human_reviewed_case_count': 0}
    schema_errors = sorted(code for code in failure_codes if any(fragment in code for fragment in
        ('schema', 'invalid', 'http_binding', 'binding_mismatch', 'source_value', 'source_binding', 'rights_mismatch')))
    case_errors = sorted(code for code in failure_codes if code == 'professional_golden_case_coverage_incomplete')
    decision_errors = sorted(failure_codes - set(schema_errors) - set(case_errors))
    incomplete_decisions = coverage['known_link_assertions'] != coverage['checked_known_link_assertions']
    incomplete_pairs = coverage['known_distinct_pairs'] != coverage['checked_distinct_pairs']
    if incomplete_decisions or incomplete_pairs:
        decision_errors.append('professional_golden_decision_coverage_incomplete')
    decision_state = 'failed' if decision_errors else ('passed' if
        coverage['known_link_assertions'] and coverage['known_distinct_pairs'] else 'inconclusive')
    gates = {'schema_integrity': {'state': 'failed' if schema_errors else 'passed', 'reason_codes': schema_errors[:MAX_DIFFS]},
        'case_coverage': {'state': 'failed' if case_errors else 'passed', 'reason_codes': case_errors[:MAX_DIFFS]},
        'decision_and_distinct_coverage': {'state': decision_state, 'reason_codes': decision_errors[:MAX_DIFFS]},
        'human_truth_qualification': {'state': 'inconclusive',
            'reason_codes': ['professional_golden_pending_external_review',
                'professional_golden_real_positive_qualification_unestablished']}}
    report = {'schema': REPORT_SCHEMA, 'state': 'failed' if failure_codes else 'passed',
        'evaluation_mode': 'offline_bound_snapshot', 'release_gate': 'inconclusive',
        'human_truth_status': HUMAN_TRUTH_STATUS, 'gate_scope': 'frozen_professional_set_only',
        'contract_fingerprint': contract_fingerprint, 'manifest_sha256': manifest_sha256,
        'expected_case_count': len(cases), 'completed_case_count': len(safe_actual_ids & safe_expected_ids),
        'case_results': results, 'coverage': coverage, 'gates': gates,
        'observed_wrong_link_count': sum(r['observed_wrong_link_count'] for r in results),
        'observed_unsupported_link_count': sum(r['observed_unsupported_link_count'] for r in results),
        'observed_wrong_merge_count': sum(r['observed_wrong_merge_count'] for r in results),
        'wrong_merge_count': None, 'failure_codes': sorted(failure_codes)[:MAX_DIFFS],
        'limitations': ['Pure comparison evaluates bound offline snapshots and cannot certify current HTTP execution or latest authorization.',
            'Human truth qualification is pending external review; agent notes, declared tiers and two accounts do not authenticate people.',
            'Synthetic or safely excluded unknown cases do not establish representative real positive or human Golden coverage.',
            'Material provider use and export remain false; this report does not grant new uses.']}
    return ProfessionalGoldenReport.model_validate(report).model_dump(mode='json', by_alias=True)
