"""Independent R76 review mutations over explicitly supplied HTTP observations.

Set R76_REVIEW_ACTUAL_DIR to the exact private runner's ``actuals`` directory.
These tests import neither the application nor a database client. They never
construct expected answers from product functions or discover a latest run.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from tire_api import professional_golden_checks as checks
from tire_api.professional_golden_corpus import strict_json_loads


ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / 'packages/domain-types/fixtures/professional-test-bridge-v1'
MANIFEST_SHA256 = 'd222b70c14dc09584f06590902fd13eac9559ac72e3d1a203adc35c341eb91f2'
CASE_IDS = frozenset({
    'real-r74-trwp-identity-unknown', 'synthetic-exact-two',
    'synthetic-identity-conflict', 'synthetic-incomplete-explicit',
    'synthetic-manual-unknown', 'synthetic-revoked-selection',
    'synthetic-same-code-different-namespace',
})


def canonical_sha(value):
    """The declared canonical JSON preimage, independently implemented here."""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def rebind_response(observation):
    # Rebind after mutation so a test cannot pass merely on an outdated hash.
    observation['response_sha256'] = canonical_sha(observation['response_body'])


def json_result(value):
    return value.model_dump(mode='json', by_alias=True) if hasattr(value, 'model_dump') else value


def evaluate(case, actual):
    return json_result(checks.evaluate_case(case, actual))


@pytest.fixture(scope='module')
def frozen_cases():
    raw = (CORPUS / 'manifest.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == MANIFEST_SHA256
    manifest = strict_json_loads(raw)
    assert set(manifest['case_ids']) == CASE_IDS
    cases = {}
    for row in manifest['files']:
        bound = (CORPUS / row['path']).read_bytes()
        assert len(bound) == row['byte_count']
        assert hashlib.sha256(bound).hexdigest() == row['sha256']
        if row['role'] == 'case':
            value = strict_json_loads(bound)
            assert value['case_id'] not in cases
            cases[value['case_id']] = value
    assert set(cases) == CASE_IDS
    return cases


@pytest.fixture(scope='module')
def observed_set(frozen_cases):
    supplied = os.environ.get('R76_REVIEW_ACTUAL_DIR')
    if supplied is None:
        pytest.skip('Set R76_REVIEW_ACTUAL_DIR to one explicit private HTTP run')
    directory = Path(supplied)
    assert directory.is_absolute() and directory.is_dir()
    assert {path.name for path in directory.iterdir()} == {case_id + '.json' for case_id in CASE_IDS}
    actuals = {}
    for case_id in CASE_IDS:
        value = strict_json_loads((directory / (case_id + '.json')).read_bytes())
        assert value['case_id'] == case_id
        actuals[case_id] = value
    # Every mutation starts from a separately observed, passing baseline.
    for case_id in CASE_IDS:
        result = evaluate(frozen_cases[case_id], actuals[case_id])
        assert result['state'] == 'passed', (case_id, result)
    return frozen_cases, actuals


def pair(observed_set, case_id='synthetic-exact-two'):
    cases, actuals = observed_set
    return deepcopy(cases[case_id]), deepcopy(actuals[case_id])


def report(cases, actuals):
    return json_result(checks.evaluate_corpus(
        list(cases), list(actuals), manifest_sha256=MANIFEST_SHA256,
        contract_fingerprint='a' * 64,
    ))


def test_frozen_oracle_keeps_raw_values_namespace_coverage_and_group_exclusion(frozen_cases):
    exact = frozen_cases['synthetic-exact-two']
    rows = exact['input']['event']['measurements']
    assert [(row['raw_value'], row['source_rank']) for row in rows] == [
        ('38.00', 3), ('40.0', 5), ('70', None), ('-0', None), ('0', 8),
    ]
    expected = exact['expected']['candidate']
    assert expected['coverage'] == {
        'mapped_weight': 65, 'fully_comparable_weight': 50,
        'unmapped_weight': 35, 'mapped_not_fully_comparable_weight': 15,
    }
    assert expected['metric_comparisons'][0]['favorable_participant_keys'] == ['a']
    assert expected['metric_comparisons'][1]['favorable_participant_keys'] is None
    assert expected['metric_comparisons'][2]['favorable_participant_keys'] == ['a', 'b']
    namespace = frozen_cases['synthetic-same-code-different-namespace']
    left, right = [sku['value'] for sku in namespace['input']['skus']]
    assert left['manufacturer_product_code'] == right['manufacturer_product_code']
    assert left['facts']['product_code_type'] == 'MSPN'
    assert right['facts']['product_code_type'] == 'EAN'
    assert namespace['expected']['distinct_pairs'][0]['truth'] == 'distinct'
    for case_id in ['synthetic-manual-unknown', 'synthetic-revoked-selection']:
        candidate = frozen_cases[case_id]['expected']['candidate']
        assert candidate['personal_interpretation_allowed'] is False
        assert candidate['metric_comparisons'] == [] and candidate['coverage'] is None
    real = frozen_cases['real-r74-trwp-identity-unknown']
    assert real['input']['mode'] == 'source_review_only'
    assert real['input']['event'] is None and real['input']['skus'] == []
    assert real['input']['source_review']['exact_sku_truth'] == 'unknown'
    assert all(case['review']['state'] == 'pending_external_review' for case in frozen_cases.values())


def test_snapshot_baseline_does_not_authenticate_live_http_or_human_truth(observed_set):
    cases, actuals = observed_set
    result = report(cases.values(), actuals.values())
    assert result['state'] == 'passed'
    assert result['evaluation_mode'] == 'offline_bound_snapshot'
    assert result['release_gate'] == 'inconclusive'
    assert result['human_truth_status'] == 'pending_external_review'
    assert result['coverage']['human_reviewed_case_count'] == 0
    assert result['wrong_merge_count'] is None
    assert result['observed_wrong_merge_count'] == 0
    assert all(row['private_http_observed'] is False for row in result['case_results'])


def test_unknown_safe_rejection_does_not_become_a_known_negative(observed_set):
    for case_id in ['synthetic-manual-unknown', 'synthetic-incomplete-explicit']:
        case, actual = pair(observed_set, case_id)
        result = evaluate(case, actual)
        assert result['state'] == 'passed'
        assert result['unknown_link_assertion_count'] == 2
        assert result['known_link_assertion_count'] == 0
        assert result['observed_wrong_link_count'] == 0
        assert result['observed_unsupported_link_count'] == 0


@pytest.mark.parametrize('same_identity', [False, True])
def test_observed_wrong_merge_survives_other_binding_failures(observed_set, same_identity):
    case, actual = pair(observed_set, 'synthetic-same-code-different-namespace')
    left, right = actual['sku_bindings']
    if same_identity:
        # Equal code, different namespace is the sole identity distinction.
        right['identity'] = deepcopy(left['identity'])
    else:
        right['variant_id'] = left['variant_id']
    # Preview/current bindings deliberately remain untouched: their mismatch
    # must not hide an already observed merge in the independent SKU bindings.
    result = evaluate(case, actual)
    assert result['state'] == 'failed'
    assert result['observed_wrong_merge_count'] >= 1


def test_all_rejected_cannot_pass_expected_positive_bridges(observed_set):
    case, actual = pair(observed_set)
    for bridge in actual['bridge_results']:
        bridge['preview']['response_body']['can_submit'] = False
        bridge['preview']['response_body']['blockers'] = ['identity_assertions_incomplete']
        bridge['current'] = None
        bridge['decisions'] = []
        rebind_response(bridge['preview'])
    actual['candidate_result'] = None
    result = evaluate(case, actual)
    assert result['state'] == 'failed'
    assert result['expected_positive_link_count'] == 2
    assert result['positive_link_count'] == 0


def test_unknown_eligibility_is_reported_as_unsupported_admission(observed_set):
    case, actual = pair(observed_set, 'synthetic-manual-unknown')
    current = actual['bridge_results'][0]['current']
    current['response_body']['eligibility'] = 'conditional_reviewed_transcription'
    current['response_body']['effective_state'] = 'reviewed'
    rebind_response(current)
    result = evaluate(case, actual)
    assert result['state'] == 'failed'
    assert result['observed_unsupported_link_count'] >= 1


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'duplicate'])
def test_actual_set_must_match_all_frozen_case_ids(observed_set, mutation):
    cases, observed = observed_set
    actuals = deepcopy(list(observed.values()))
    if mutation == 'missing':
        actuals.pop()
    elif mutation == 'extra':
        extra = deepcopy(actuals[0])
        extra['case_id'] = 'synthetic-unregistered-extra'
        actuals.append(extra)
    else:
        actuals.append(deepcopy(actuals[0]))
    result = report(cases.values(), actuals)
    assert result['state'] == 'failed'
    assert result['failure_codes']
    assert result['wrong_merge_count'] is None


def test_self_declared_human_tier_cannot_qualify_a_release(observed_set):
    case, actual = pair(observed_set)
    case['tier'] = 'real_source_human_reviewed'
    result = report([case], [actual])
    assert result['release_gate'] == 'inconclusive'
    assert result['human_truth_status'] == 'pending_external_review'
    assert result['coverage']['human_reviewed_case_count'] == 0
    assert result['wrong_merge_count'] is None


@pytest.mark.parametrize('location,value', [
    ('preview_boolean', 1), ('preview_boolean', 'true'),
    ('boundary_false', 0), ('participant_present', 1),
    ('candidate_eligible', 1), ('candidate_count', True),
    ('complete_comparable', 1),
])
def test_nested_http_types_cannot_use_bool_integer_string_equivalence(observed_set, location, value):
    case, actual = pair(observed_set)
    if location in {'preview_boolean', 'boundary_false', 'participant_present'}:
        observation = actual['bridge_results'][0]['preview']
        body = observation['response_body']
        if location == 'preview_boolean':
            body['can_submit'] = value
        elif location == 'boundary_false':
            body['boundary']['provider_use'] = value
        else:
            body['frozen_evidence']['test']['participant_present'] = value
    else:
        observation = actual['candidate_result']
        body = observation['response_body']
        if location == 'candidate_eligible':
            body['items'][0]['eligible'] = value
        elif location == 'candidate_count':
            body['requested_count'] = value
        else:
            body['personal_interpretation']['metrics'][0]['complete_comparable'] = value
    rebind_response(observation)
    assert evaluate(case, actual)['state'] == 'failed'


@pytest.mark.parametrize('field,replacement', [('raw_value', '0'), ('source_rank', 1)])
def test_response_rebinding_cannot_hide_original_value_or_source_rank_rewrite(observed_set, field, replacement):
    case, actual = pair(observed_set)
    observation = actual['candidate_result']
    measurements = observation['response_body']['source_evidence']['measurements']
    source = next(row for row in measurements if row['metric_key'] == 'dry' and row['raw_value'] == '-0')
    source[field] = replacement
    rebind_response(observation)
    assert evaluate(case, actual)['state'] == 'failed'


def test_revoked_selection_forbids_the_whole_personal_interpretation(observed_set):
    case, actual = pair(observed_set, 'synthetic-revoked-selection')
    _, positive = pair(observed_set)
    observation = actual['candidate_result']
    assert observation['response_body']['personal_interpretation'] is None
    observation['response_body']['personal_interpretation'] = deepcopy(
        positive['candidate_result']['response_body']['personal_interpretation'])
    rebind_response(observation)
    assert evaluate(case, actual)['state'] == 'failed'


def test_missing_distinct_pair_coverage_keeps_wrong_merge_unestablished(observed_set):
    case, actual = pair(observed_set, 'synthetic-manual-unknown')
    result = report([case], [actual])
    assert result['coverage']['known_distinct_pairs'] == 0
    assert result['coverage']['checked_distinct_pairs'] == 0
    assert result['wrong_merge_count'] is None
    case, actual = pair(observed_set)
    actual['sku_bindings'].pop()
    result = report([case], [actual])
    assert result['state'] == 'failed'
    assert result['coverage']['known_distinct_pairs'] == 1
    assert result['coverage']['checked_distinct_pairs'] == 0
    assert result['wrong_merge_count'] is None


@pytest.mark.parametrize('field', ['event_id', 'revision', 'metric_key'])
def test_measurement_reference_cannot_cross_event_revision_or_observation(observed_set, field):
    case, actual = pair(observed_set)
    observation = actual['candidate_result']
    measurement = observation['response_body']['source_evidence']['measurements'][0]
    reference = measurement['reference']
    if field == 'event_id':
        reference[field] += '-other'
    elif field == 'revision':
        reference[field] += 1
    else:
        reference[field] = 'dry' if reference[field] != 'dry' else 'wet'
    rebind_response(observation)
    assert evaluate(case, actual)['state'] == 'failed'
