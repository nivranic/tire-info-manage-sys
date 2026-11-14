"""Pure contract/graph/error visibility tests; these are not live HTTP evidence."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
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
        loaded = checks.load_case(case)
        assert loaded.case_id == case['case_id']
        assert loaded.model_dump(mode='json', by_alias=True) == case


def test_mixed_sizes_are_preserved_by_independent_literals(cases):
    event = deepcopy(cases['synthetic-exact-two']['input']['event'])
    legacy = checks.EventLiteral.model_validate(event).model_dump()
    assert all('tested_size' not in person for person in legacy['participants'])
    event['tested_size'] = None
    for person, size in zip(event['participants'], ('225/50R17', '205/55R16')):
        person['tested_size'] = size
    assert checks.EventLiteral.model_validate(event).model_dump() == event
    for common, sizes in [(None, [None, '205/55R16']), (None, ['205/55R16', '205/55R16']),
                          ('225/50R17', ['225/50R17', '205/55R16'])]:
        invalid = deepcopy(event)
        invalid['tested_size'] = common
        for person, size in zip(invalid['participants'], sizes):
            person['tested_size'] = size
        with pytest.raises(ValueError):
            checks.EventLiteral.model_validate(invalid)


def pdf_event_case(cases):
    case = deepcopy(cases['synthetic-exact-two'])
    case['case_id'] = 'synthetic-pdf-event'
    case['input'].update(mode='test_event_http', skus=[], bridge_attempts=[], candidate=None, source_review=None)
    case['expected'].update(bridges=[], distinct_pairs=[], candidate=None, source_review_findings=[])
    case['input']['event']['publication'] = {'role': 'original_report', 'basis': 'Project-authored synthetic report'}
    case['input']['event']['measurements'][0]['pdf_reference'] = {
        'material_label': case['materials'][0]['material_label'],
        'extractor_version': 'pdf-page-text@1+pypdf@6.19.0', 'page': 1, 'start': 0, 'end': 1200}
    return case


def test_pdf_event_contract_preserves_source_literals_and_binds_runtime_ids(cases):
    case = pdf_event_case(cases)
    loaded = checks.load_case(case).model_dump(mode='json', by_alias=True)
    assert loaded == case
    binding = {'material_label': case['materials'][0]['material_label'], 'document_id': 'synthetic-runtime-document',
        'raw_sha256': case['materials'][0]['original']['sha256'],
        'byte_count': case['materials'][0]['original']['byte_count'], 'metadata_sha256': 'e' * 64}
    bound = checks.bound_event(loaded, [binding])
    expected = {'document_id': binding['document_id'], 'document_fingerprint': 'e' * 64,
        'raw_hash': binding['raw_sha256'], 'extractor_version': 'pdf-page-text@1+pypdf@6.19.0',
        'page': 1, 'start': 0, 'end': 1200}
    assert bound['measurements'][0]['pdf_reference'] == {**expected, 'chunk_id': checks.json_sha256(expected)}
    assert case['input']['event']['measurements'][0]['pdf_reference']['material_label'] == binding['material_label']
    assert bound['publication'] == case['input']['event']['publication']


@pytest.mark.parametrize('change', [{'page': True}, {'page': 0}, {'page': 2001}, {'start': -1},
    {'start': 1}, {'start': '0'}, {'end': 0}, {'end': 1201}, {'material_label': 'absent'}, {'extra': 'unbound'}])
def test_pdf_event_rejects_invalid_reference_ranges_and_unknown_material(cases, change):
    case = pdf_event_case(cases)
    case['input']['event']['measurements'][0]['pdf_reference'].update(change)
    with pytest.raises(checks.ProfessionalGoldenError):
        checks.load_case(case)


def observe_http_case(case, directory, capture):
    from fastapi.testclient import TestClient
    from tire_api.main import create_app
    from test_core import FixtureRegistry
    root = Path(__file__).resolve().parents[3]
    url = 'sqlite:///' + (directory / 'workspace.sqlite').as_posix()
    with pytest.MonkeyPatch.context() as patch:
        for name, value in {'TIRE_DATABASE_URL': url, 'DATABASE_URL': url,
                'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0',
                'TI_OBJECT_STORE_ROOT': str(directory / 'objects'),
                'TI_PARSER_BUNDLE_ROOT': str(directory / 'bundles')}.items():
            patch.setenv(name, value)
        app = create_app(url, FixtureRegistry())
        sources = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((root / 'apps/api/tire_api').rglob('*.py'))}
        execution = {'mode': case['input']['mode'], 'run_id': uuid4().hex,
            'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'product_source_fingerprint': checks.json_sha256(sources), 'private_http_observed': True}
        try:
            with TestClient(app) as client:
                actual = capture(client, case, execution)
        finally:
            app.state.database.close()
    result = checks.evaluate_case(case, actual)
    for name, value in [('case', case), ('actual', actual), ('report', result)]:
        (directory / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    assert result['state'] == 'passed', result
    return actual


@pytest.fixture(scope='module')
def observed_pdf_event(cases, tmp_path_factory):
    from professional_golden_support import run_test_event_case
    from test_document_pdf import pdf_bytes
    case = pdf_event_case(cases)
    directory = tmp_path_factory.mktemp('pdf-golden')
    raw = pdf_bytes((case['input']['event']['measurements'][0]['evidence_span'] + ' Original synthetic source ' * 80,))
    path = directory / 'original.pdf'
    path.write_bytes(raw)
    case['materials'][0]['original'] = {'path': path.relative_to(Path(__file__).resolve().parents[3]).as_posix(),
        'byte_count': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    return case, observe_http_case(case, directory, run_test_event_case)


def test_pdf_event_normal_http_preserves_values_publication_and_scope(observed_pdf_event):
    case, actual = observed_pdf_event
    assert actual['sku_bindings'] == [] and actual['bridge_results'] == []
    assert actual['execution']['mode'] == 'test_event_http'
    assert actual['event_snapshot']['event']['publication'] == case['input']['event']['publication']
    assert actual['event_snapshot']['event']['measurements'][0]['pdf_reference']['page'] == 1
    report = checks.evaluate_corpus([case], [actual], 'a' * 64, 'b' * 64)
    assert report['coverage']['real_positive_case_count'] == 0
    assert report['coverage']['human_reviewed_case_count'] == 0


@pytest.mark.parametrize('change', ['raw_value', 'page', 'start', 'end', 'raw_hash', 'document_id',
    'document_fingerprint', 'extractor_version', 'chunk_id', 'publication', 'execution_scope'])
def test_pdf_event_rejects_rehashed_original_or_scope_changes(observed_pdf_event, change):
    case, actual = observed_pdf_event
    damaged = deepcopy(actual)
    event = damaged['event_snapshot']['event']
    measured = event['measurements'][0]
    if change == 'raw_value':
        measured['raw_value'] = '999.0000'
    elif change in ('page', 'start', 'end'):
        measured['pdf_reference'][change] += 1
    elif change == 'publication':
        event['publication']['role'] = 'secondary_report'
    elif change == 'execution_scope':
        damaged['execution']['mode'] = 'private_http'
    else:
        measured['pdf_reference'][change] = 'd' * 64
    reference = measured['pdf_reference']
    if change != 'chunk_id':
        reference['chunk_id'] = checks.json_sha256({key: value for key, value in reference.items() if key != 'chunk_id'})
    fingerprint = checks.json_sha256(event)
    damaged['event_binding']['fingerprint'] = fingerprint
    damaged['event_snapshot']['fingerprint'] = fingerprint
    damaged['event_snapshot']['history'][0]['fingerprint'] = fingerprint
    assert checks.evaluate_case(case, damaged)['state'] == 'failed'


def real_pdf_case():
    root = Path(__file__).resolve().parents[3]
    raw = (root / 'packages/domain-types/fixtures/professional-test-pdf-v1/real-crr2017-original-measurements.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == 'c6a2653c02618cb2dcf61577c7adbef15832bb5c5702bc020096ba446cb3dcb4'
    return strict_json_loads(raw)


def test_real_crr2017_case_keeps_independent_22_values_and_original_source_scope():
    case = real_pdf_case()
    assert checks.load_case(case).model_dump(mode='json', by_alias=True) == case
    assert case['tier'] == 'real_source_unknown_or_inadmissible'
    assert case['input']['skus'] == [] and case['expected']['bridges'] == []
    event = case['input']['event']
    assert [value['raw_value'] for value in event['measurements']] == [
        '0.0110', '0.0068', '0.0108', '0.0064', '0.0105', '0.0059', '0.0113', '0.0053',
        '0.0160', '0.0082', '0.0141', '0.0074', '0.0088', '0.0041', '0.0130', '0.0058',
        '0.0109', '0.0052', '0.0081', '0.0045', '0.0104', '0.0050']
    assert event['reported_participants'] == 4 and event['coverage'] == 'selected_results'
    assert event['metrics'][-1]['protocol'].find('50 km/h') >= 0
    assert all(value['pdf_reference']['page'] == 4 for value in event['measurements'])


def test_real_crr2017_normal_http_golden_event_with_saved_original(tmp_path):
    from professional_golden_support import run_test_event_case
    root = Path(__file__).resolve().parents[3]
    case = real_pdf_case()
    if not (root / case['materials'][0]['original']['path']).exists():
        pytest.skip('Requires the captured licensed CRR2017 original with its pinned hash')
    actual = observe_http_case(case, tmp_path, run_test_event_case)
    assert len(actual['event_snapshot']['event']['measurements']) == 22
    assert all(value['pdf_reference']['page'] == 4 for value in actual['event_snapshot']['event']['measurements'])
    assert actual['sku_bindings'] == [] and actual['bridge_results'] == []
    assert actual['event_snapshot']['verification_status'] == 'unverified'


@pytest.mark.parametrize('case_id', ['synthetic-exact-two', 'synthetic-identity-conflict',
    'synthetic-incomplete-explicit', 'synthetic-manual-unknown',
    'synthetic-revoked-selection', 'synthetic-same-code-different-namespace'])
def test_existing_synthetic_bridge_cases_replay_through_normal_private_http(cases, tmp_path, case_id):
    from professional_golden_support import run_private_case
    actual = observe_http_case(cases[case_id], tmp_path, run_private_case)
    assert actual['execution']['mode'] == 'private_http'
    assert actual['bridge_results']


def test_event_only_scope_cannot_claim_sku_bridge_or_source_review(cases):
    case = pdf_event_case(cases)
    for change in [{'mode': 'private_http'}, {'skus': cases['synthetic-exact-two']['input']['skus']},
            {'bridge_attempts': cases['synthetic-exact-two']['input']['bridge_attempts']}]:
        invalid = deepcopy(case)
        invalid['input'].update(change)
        with pytest.raises(checks.ProfessionalGoldenError):
            checks.load_case(invalid)
    invalid = deepcopy(case)
    invalid['expected']['source_review_findings'] = ['human_review_completed']
    with pytest.raises(checks.ProfessionalGoldenError):
        checks.load_case(invalid)


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
