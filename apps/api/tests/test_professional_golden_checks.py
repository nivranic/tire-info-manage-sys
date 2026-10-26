"""Pure contract/graph/error visibility tests; these are not live HTTP evidence."""
from copy import deepcopy
import os
from pathlib import Path
import pytest

from tire_api import professional_golden_checks as checks
from tire_api.professional_golden_corpus import ProfessionalGoldenCorpus, strict_json_loads


@pytest.fixture(scope='module')
def cases():
    return {case['case_id']: case for case in ProfessionalGoldenCorpus().read_cases()}


def source_snapshot(case):
    return {'schema': checks.ACTUAL_SCHEMA, 'case_id': case['case_id'],
        'input_sha256': checks.json_sha256(case['input']),
        'execution': {'mode': 'source_review_only', 'run_id': '1' * 32,
            'runner_sha256': '2' * 64, 'product_source_fingerprint': '3' * 64,
            'private_http_observed': False},
        'event_binding': None, 'event_snapshot': None, 'sku_bindings': [], 'material_bindings': [],
        'bridge_results': [], 'candidate_result': None,
        'source_review_result': {'original_verified': True, 'capture_receipt_verified': True,
            'agent_review_record_verified': True, 'exact_sku_truth': 'unknown', 'findings': [
                'exact_sku_not_established', 'tested_size_not_established',
                'study_codes_not_manufacturer_codes', 'particle_classification_not_whole_tire_performance',
                'source_review_only_no_product_event', 'agent_review_not_human_golden']}}


def report(cases, actuals):
    return checks.evaluate_corpus(cases, actuals, 'a' * 64, 'b' * 64)


def test_contract_and_synthetic_scope():
    assert checks.CONTRACT_VERSION == 'professional-test-golden@1'
    assert checks.TIERS == ('synthetic_contract', 'real_source_unknown_or_inadmissible',
                            'real_source_human_reviewed')
    assert checks.Closed.model_config['strict'] is True
    assert checks.Closed.model_config['extra'] == 'forbid'
    assert checks.HUMAN_TRUTH_STATUS == 'pending_external_review'
    assert callable(checks.evaluate_case)


def test_every_frozen_case_has_a_closed_independent_graph(cases):
    assert len(cases) == 7
    for case in cases.values():
        assert checks.load_case(case).case_id == case['case_id']


@pytest.mark.parametrize('field,value', [('store_original', 1), ('workspace_reopen', 'true'),
    ('quote_identifiers', None), ('provider_use', 0), ('export', 'false')])
def test_license_flags_cannot_use_pydantic_literal_coercion(cases, field, value):
    case = deepcopy(cases['synthetic-exact-two'])
    case['materials'][0]['rights'][field] = value
    with pytest.raises(checks.ProfessionalGoldenError, match='professional_golden_case_invalid'):
        checks.load_case(case)


@pytest.mark.parametrize('mutation', ['same_sku_identity', 'one_sided_basis', 'duplicate_participant',
    'duplicate_measurement', 'dangling_assertion', 'duplicate_expected_bridge'])
def test_oracle_graph_must_be_independent_and_closed(cases, mutation):
    case = deepcopy(cases['synthetic-exact-two'])
    data = case['input']
    if mutation == 'same_sku_identity':
        data['skus'][1]['value'] = deepcopy(data['skus'][0]['value'])
    elif mutation == 'one_sided_basis':
        case['expected']['distinct_pairs'][0]['evidence_refs'].pop()
    elif mutation == 'duplicate_participant':
        data['event']['participants'][1]['key'] = data['event']['participants'][0]['key']
    elif mutation == 'duplicate_measurement':
        data['event']['measurements'].append(deepcopy(data['event']['measurements'][0]))
    elif mutation == 'dangling_assertion':
        data['bridge_attempts'][0]['assertions'][0]['material_label'] = 'absent-material'
    else:
        case['expected']['bridges'].append(deepcopy(case['expected']['bridges'][0]))
    with pytest.raises(checks.ProfessionalGoldenError, match='professional_golden_case_graph_invalid'):
        checks.load_case(case)


def test_four_gates_keep_source_review_and_human_truth_separate(cases):
    case = cases['real-r74-trwp-identity-unknown']
    result = report([case], [source_snapshot(case)])
    assert result['state'] == 'passed'
    assert {key: value['state'] for key, value in result['gates'].items()} == {
        'schema_integrity': 'passed', 'case_coverage': 'passed',
        'decision_and_distinct_coverage': 'inconclusive', 'human_truth_qualification': 'inconclusive'}
    assert result['release_gate'] == 'inconclusive'
    assert result['wrong_merge_count'] is None
    assert result['coverage']['real_positive_case_count'] == 0


@pytest.mark.parametrize('case_id', [None, [], {}, True, 5])
def test_unhashable_or_wrong_typed_actual_id_produces_failed_report(cases, case_id):
    case = cases['real-r74-trwp-identity-unknown']
    actual = source_snapshot(case)
    actual['case_id'] = case_id
    result = report([case], [actual])
    assert result['state'] == 'failed'
    assert result['gates']['case_coverage']['state'] == 'failed'
    assert result['gates']['schema_integrity']['state'] == 'failed'
    assert result['release_gate'] == 'inconclusive'


def test_bad_admission_and_collision_remain_observed_despite_invalid_envelope(cases):
    case = cases['synthetic-revoked-selection']
    # Deliberately incomplete observation: no claimed current execution or hashes.
    # A bad declared decision is still visible; nothing else becomes validated.
    actual = {'sku_bindings': [
        {'sku_label': sku['sku_label'], 'variant_id': 'same-variant',
            'snapshot_member': {'identity_key': 'c' * 64}, 'identity': {'marker': 'same'}}
        for sku in case['input']['skus']],
        'bridge_results': [{'attempt_id': 'bridge-b', 'current': {
            'response_body': {'eligibility': 'conditional_reviewed_transcription'}}}]}
    result = checks.evaluate_case(case, actual)
    assert result['state'] == 'failed'
    assert result['observed_wrong_merge_count'] == 1
    assert result['observed_unsupported_link_count'] == 1
    assert result['private_http_observed'] is False


@pytest.mark.parametrize('actual', [b'{"case_id":"x","case_id":"y"}', b'{"value":NaN}',
    b'{"value":Infinity}', b'{"value":-Infinity}', b'\xff', b'{}' * 256001],
    ids=['duplicate-key', 'nan', 'infinity', 'negative-infinity', 'invalid-utf8', 'oversize'])
def test_invalid_json_cannot_become_a_passed_actual(cases, actual):
    result = checks.evaluate_case(cases['real-r74-trwp-identity-unknown'], actual)
    assert result['state'] == 'failed'
    assert result['failure_count'] >= 1


@pytest.fixture(scope='module')
def observed_actuals(cases):
    supplied = os.environ.get('R76_REVIEW_ACTUAL_DIR')
    if supplied is None:
        pytest.skip('Requires one explicitly supplied private HTTP actual directory')
    directory = Path(supplied)
    assert directory.is_absolute()
    actuals = {key: strict_json_loads((directory / (key + '.json')).read_bytes()) for key in cases}
    for key in cases:
        assert checks.evaluate_case(cases[key], actuals[key])['state'] == 'passed', key
    return actuals


@pytest.mark.parametrize('mutation', ['candidate_identity', 'candidate_axle', 'candidate_boolean',
    'dimension_weight', 'metric_evidence', 'comparison_evidence', 'event_participant_count'])
def test_rebound_nested_projection_cannot_escape_literal_identity_or_evidence(cases, observed_actuals, mutation):
    case = cases['synthetic-exact-two']
    actual = deepcopy(observed_actuals[case['case_id']])
    observation = actual['candidate_result']
    body = observation['response_body']
    if mutation == 'candidate_identity':
        body['candidate_projection']['items'][0]['identity']['run_flat'] = True
    elif mutation == 'candidate_axle':
        body['candidate_projection']['selection']['axle'] = 'rear'
    elif mutation == 'candidate_boolean':
        body['candidate_projection']['truncated'] = 0
    elif mutation == 'dimension_weight':
        body['personal_interpretation']['dimensions'][0]['weight'] += 1
    elif mutation == 'metric_evidence':
        body['personal_interpretation']['metrics'][0]['evidence_ids'][0] = 'other-evidence'
    elif mutation == 'comparison_evidence':
        body['personal_interpretation']['metrics'][0]['observation_comparison']['evidence_ids'][0] = 'other-evidence'
    else:
        actual['event_snapshot']['participant_count'] = True
    observation['response_sha256'] = checks.json_sha256(body)
    assert checks.evaluate_case(case, actual)['state'] == 'failed'


@pytest.mark.parametrize('mutation', ['empty_checks', 'check_status', 'required_identity', 'unknown_fields',
    'identity_status', 'identity_contract', 'event_state', 'decision_revision', 'decision_request_previous',
    'decision_replay_type', 'decision_subject', 'decision_material_ack'])
def test_complete_bridge_protocol_preserves_checks_scope_and_revision_chain(cases, observed_actuals, mutation):
    case = cases['synthetic-exact-two']
    actual = deepcopy(observed_actuals[case['case_id']])
    run = actual['bridge_results'][0]
    observation = run['preview']
    body = observation['response_body']
    if mutation == 'empty_checks':
        body['checks'] = []
    elif mutation == 'check_status':
        body['checks'][0]['status'] = 'conflict'
    elif mutation == 'required_identity':
        body['required_identity_fields'].pop()
    elif mutation == 'unknown_fields':
        body['unknown_fields'].append('run_flat')
    elif mutation == 'identity_status':
        body['frozen_evidence']['tire']['identity_status'] = 'source_scoped'
    elif mutation == 'identity_contract':
        body['frozen_evidence']['tire']['identity_contract_version'] = 'variant-identity@1'
    elif mutation == 'event_state':
        actual['event_snapshot']['state'] = 'revoked'
    else:
        observation = run['decisions'][1]
        body = observation['response_body']
        if mutation == 'decision_revision':
            body['link']['revision'] += 1
        elif mutation == 'decision_replay_type':
            body['idempotent_replay'] = 0
        elif mutation == 'decision_request_previous':
            observation['request_body']['expected_fingerprint'] = 'f' * 64
        elif mutation == 'decision_subject':
            observation['request_body']['confirmed_participant_hash'] = 'f' * 64
        else:
            observation['request_body']['opened_materials'] = []
    observation['request_sha256'] = checks.json_sha256(observation['request_body'])
    observation['response_sha256'] = checks.json_sha256(body)
    assert checks.evaluate_case(case, actual)['state'] == 'failed'


def test_nested_boolean_count_failure_is_visible_in_schema_gate(cases, observed_actuals):
    case = cases['synthetic-exact-two']
    actual = deepcopy(observed_actuals[case['case_id']])
    observation = actual['candidate_result']
    observation['response_body']['requested_count'] = True
    observation['response_sha256'] = checks.json_sha256(observation['response_body'])
    result = report([case], [actual])
    assert result['state'] == 'failed'
    assert result['gates']['schema_integrity']['state'] == 'failed'
    assert 'professional_golden_actual_schema_invalid' in result['gates']['schema_integrity']['reason_codes']
    assert result['gates']['human_truth_qualification']['state'] == 'inconclusive'
