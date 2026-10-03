"""Golden counterexamples independent of Parser-generated expected values."""
from copy import deepcopy

import pytest

from tire_api.domain import VariantInput
from tire_api.golden_checks import aggregate_reports, compare_case, contract_descriptor, validate_expected


SOURCE = {'case_id': 'case-1', 'source_id': 'michelin-us', 'query_key': 'a' * 64,
          'query': {'model': 'Human Fixture', 'size': '265/40ZR20'}}


def tire(code='001', **changes):
    value = {'brand': 'Human Fixture', 'model': 'Human Fixture', 'region': 'US',
        'manufacturer_product_code': code, 'size': '265/40ZR20', 'load_index': '104',
        'speed_rating': 'Y', 'xl': True, 'hl': False, 'oe_mark': 'LUC',
        'acoustic_technology': 'Acoustic', 'run_flat': False,
        'source_variant_name': code, 'facts': {'product_code_type': 'MSPN', 'utqg_treadwear': 300}}
    value.update(changes)
    return value


def expected(*rows):
    return {'records': [{'golden_sku_id': f'sku-{index}', 'value': row} for index, row in enumerate(rows)]}


def report(values, actual=None, source=None):
    return compare_case('tire', expected(*values), values if actual is None else actual, source or SOURCE)


def aggregate(*reports, count=None):
    return aggregate_reports(list(reports), expected_case_count=len(reports) if count is None else count)


def test_permutation_preserves_exact_record_matching_and_distinct_domain_keys():
    rows = [tire('001'), tire('002'), tire('003')]
    checked = report(rows, list(reversed(rows)))
    assert checked['state'] == 'passed' and checked['matched_records'] == 3
    assert [item['actual_index'] for item in checked['identity_bindings']] == [2, 1, 0]
    gate = aggregate(checked)
    assert gate['state'] == 'passed'
    assert gate['expected_distinct_pairs'] == gate['checked_distinct_pairs'] == 3
    assert gate['wrong_merge_count'] == 0


def test_one_lost_sku_out_of_four_fails_below_existing_relative_loss_threshold():
    rows = [tire(f'00{i}') for i in range(4)]
    checked = report(rows, rows[:3])
    assert checked['state'] == 'failed'
    assert checked['expected_records'] == 4 and checked['actual_records'] == 3
    gate = aggregate(checked)
    assert gate['state'] == 'failed'
    assert gate['expected_distinct_pairs'] == 6 and gate['checked_distinct_pairs'] == 3
    assert gate['wrong_merge_count'] is None


def test_unchanged_count_cannot_hide_replaced_or_duplicated_identity():
    rows = [tire('001'), tire('002')]
    for actual in ([rows[0], tire('003')], [rows[0], deepcopy(rows[0])]):
        checked = report(rows, actual)
        assert checked['state'] == aggregate(checked)['state'] == 'failed'
        assert checked['actual_records'] == checked['expected_records'] == 2
        assert any(item['code'] in {'golden_identity_missing', 'golden_identity_ambiguous'} for item in checked['failures'])


@pytest.mark.parametrize('change', [
    {'region': 'CN'}, {'size': '265/40R20'}, {'load_index': '105'}, {'speed_rating': '(Y)'},
    {'xl': None}, {'hl': True}, {'oe_mark': 'T0'}, {'run_flat': True},
    {'acoustic_technology': None}, {'manufacturer_product_code': '1'},
])
def test_each_precise_identity_difference_blocks_the_gate(change):
    rows = [tire('001'), tire('002')]
    actual = deepcopy(rows)
    actual[1].update(change)
    assert aggregate(report(rows, actual))['state'] == 'failed'


@pytest.mark.parametrize('before,after', [(None, False), (False, 0), (True, 1.0), (0, 0.01), ('001', 1), ('19', 19.0)])
def test_unknown_booleans_different_numbers_and_strings_are_not_interchangeable(before, after):
    rows = [tire('001'), tire('002')]
    rows[1]['facts']['manual_field'] = before
    actual = deepcopy(rows)
    actual[1]['facts']['manual_field'] = after
    checked = report(rows, actual)
    assert checked['state'] == 'failed'
    assert any(item['code'] == 'golden_value_mismatch' for item in checked['failures'])


@pytest.mark.parametrize('before,after', [(0, 0.0), (19, 19.0), (1235, 1235.0), (7.0, 7)])
def test_equal_json_numbers_survive_browser_serialization(before, after):
    rows = [tire('001'), tire('002')]
    rows[1]['facts']['nested_numeric_fields'] = {'values': [before]}
    actual = deepcopy(rows)
    actual[1]['facts']['nested_numeric_fields'] = {'values': [after]}
    assert aggregate(report(rows, actual))['state'] == 'passed'


def test_absent_field_is_not_explicit_unknown_and_locations_are_not_parameter_truth():
    rows = [tire('001'), tire('002')]
    actual = deepcopy(rows)
    actual[1]['facts']['manual_field'] = None
    checked = report(rows, actual)
    assert any(item['code'] == 'golden_field_presence_mismatch' for item in checked['failures'])
    actual = deepcopy(rows)
    actual[1]['facts']['evidence_spans'] = {'marker': 'different source layout'}
    assert aggregate(report(rows, actual))['state'] == 'passed'


def test_domain_v2_separates_namespaces_that_collided_under_legacy_identity():
    rows = [tire('001'), tire('001')]
    rows[1]['facts']['product_code_type'] = 'CAI'
    assert VariantInput.model_validate(rows[0]).legacy_identity_key('michelin-us', 'query', 0)[0] == (
        VariantInput.model_validate(rows[1]).legacy_identity_key('michelin-us', 'query', 1)[0])
    assert VariantInput.model_validate(rows[0]).identity_key('michelin-us', 'query', 0)[0] != (
        VariantInput.model_validate(rows[1]).identity_key('michelin-us', 'query', 1)[0])
    checked = report(rows)
    assert checked['matched_records'] == 2 and checked['wrong_merge_count'] == 0
    assert checked['state'] == aggregate(checked)['state'] == 'passed'


def test_golden_still_detects_namespace_collision_if_domain_regresses(monkeypatch):
    rows = [tire('001'), tire('001')]
    rows[1]['facts']['product_code_type'] = 'CAI'
    monkeypatch.setattr(VariantInput, 'identity_key', VariantInput.legacy_identity_key)
    checked = report(rows)
    assert checked['matched_records'] == 2 and checked['wrong_merge_count'] == 1
    assert checked['state'] == 'failed'
    gate = aggregate(checked)
    assert gate['state'] == 'failed' and 'golden_wrong_merge' in gate['failure_codes']


def test_golden_retains_missing_and_null_namespace_claims_after_domain_defaults():
    rows = [tire('001'), tire('001')]
    del rows[0]['facts']['product_code_type']
    rows[1]['facts']['product_code_type'] = None
    checked = report(rows)
    assert checked['matched_records'] == 2 and aggregate(checked)['state'] == 'passed'
    actual = deepcopy(rows)
    actual[0]['facts']['product_code_type'] = None
    assert aggregate(report(rows, actual))['state'] == 'failed'


def test_cross_capture_collision_is_checked_over_the_entire_frozen_set():
    first = compare_case('tire', {'records': [{'golden_sku_id': 'first-physical-sku', 'value': tire()}]}, [tire()], SOURCE)
    second_source = {**SOURCE, 'case_id': 'case-2', 'query_key': 'b' * 64}
    second = compare_case('tire', {'records': [{'golden_sku_id': 'second-physical-sku', 'value': tire()}]}, [tire()], second_source)
    gate = aggregate(first, second)
    assert gate['state'] == 'failed' and gate['wrong_merge_count'] == 1
    assert gate['expected_distinct_pairs'] == gate['checked_distinct_pairs'] == 1


def test_reusing_one_human_label_cannot_hide_incompatible_namespace_with_a_third_label():
    first_rows = [tire('001'), tire('002')]
    first = report(first_rows)
    other = tire('001')
    other['facts']['product_code_type'] = 'CAI'
    second = compare_case('tire', {'records': [{'golden_sku_id': 'sku-0', 'value': other}]}, [other],
                          {**SOURCE, 'case_id': 'case-2'})
    gate = aggregate(first, second)
    assert gate['state'] == 'failed'
    assert 'golden_sku_label_conflict' in gate['failure_codes']


def test_same_label_same_identity_across_captures_is_not_a_false_wrong_merge():
    first = report([tire('001'), tire('002')])
    second = report([tire('001'), tire('002')], source={**SOURCE, 'case_id': 'case-2'})
    gate = aggregate(first, second)
    assert gate['state'] == 'passed' and gate['wrong_merge_count'] == 0


def test_single_sku_missing_member_failed_execution_and_contract_drift_never_pass():
    single = report([tire()])
    assert single['state'] == 'passed' and single['wrong_merge_count'] is None
    assert aggregate(single)['state'] == 'inconclusive'
    pair = report([tire('001'), tire('002')])
    assert aggregate(pair, count=2)['state'] == 'failed'
    assert aggregate(pair, None)['state'] == 'failed'
    pair['contract']['digest'] = '0' * 64
    assert 'golden_comparison_contract_changed' in aggregate(pair)['failure_codes']


@pytest.mark.parametrize('case', ['missing_field', 'duplicate_group', 'duplicate_identity', 'empty', 'nonfinite', 'unsupported'])
def test_invalid_or_ambiguous_human_expectations_cannot_be_frozen(case):
    value = expected(tire('001'), tire('002'))
    kind = 'tire'
    if case == 'missing_field':
        del value['records'][0]['value']['hl']
    elif case == 'duplicate_group':
        value['records'][1]['golden_sku_id'] = value['records'][0]['golden_sku_id']
    elif case == 'duplicate_identity':
        value['records'][1]['value'] = deepcopy(value['records'][0]['value'])
    elif case == 'empty':
        value['records'] = []
    elif case == 'nonfinite':
        value['records'][0]['value']['facts']['bad'] = float('nan')
    else:
        kind = 'test_event'
    with pytest.raises(ValueError):
        validate_expected(kind, value)


def vehicle():
    return {'vehicle': {'id': 'vehicle-1', 'model': 'SU7 synthetic',
        'manufacturer': {'id': 'xiaomi', 'name': 'synthetic manufacturer'}, 'generation': 'synthetic-first',
        'model_year': None, 'region': 'CN'}, 'trims': [{'id': 'trim-1', 'name': 'Max', 'wheel_option_ids': ['wheel-1']}],
        'fitments': [{'id': 'wheel-1', 'trim_id': 'trim-1', 'wheel_diameter_inches': 20,
            'availability': 'optional', 'front': {'size': '245/40R20'}, 'rear': {'size': '265/40R20'}}]}


@pytest.mark.parametrize('case', ['generation', 'market', 'year', 'model', 'manufacturer', 'front_rear', 'availability', 'missing_wheel'])
def test_vehicle_scope_and_axles_are_complete_golden_truth(case):
    baseline, actual = vehicle(), vehicle()
    if case == 'generation':
        actual['vehicle']['generation'] = 'synthetic-new'
    elif case == 'market':
        actual['vehicle']['region'] = 'US'
    elif case == 'year':
        actual['vehicle']['model_year'] = 2026
    elif case == 'model':
        actual['vehicle']['model'] = 'different model'
    elif case == 'manufacturer':
        actual['vehicle']['manufacturer']['id'] = 'different manufacturer'
    elif case == 'front_rear':
        actual['fitments'][0]['front'], actual['fitments'][0]['rear'] = actual['fitments'][0]['rear'], actual['fitments'][0]['front']
    elif case == 'availability':
        actual['fitments'][0]['availability'] = 'standard'
    else:
        actual['fitments'] = []
    checked = compare_case('vehicle', baseline, actual, {**SOURCE, 'query': {'vehicle_id': 'vehicle-1'}})
    assert checked['state'] == aggregate(checked)['state'] == 'failed'


def test_vehicle_golden_pass_does_not_claim_sku_zero_wrong_merge():
    value = vehicle()
    actual = deepcopy(value)
    actual['fitments'][0]['evidence_locator'] = 'new-parser-location'
    checked = compare_case('vehicle', value, actual, {**SOURCE, 'query': {'vehicle_id': 'vehicle-1'}})
    gate = aggregate(checked)
    assert gate['state'] == 'passed' and gate['scope'] == 'vehicle_structure'
    assert gate['wrong_merge_count'] is None


def test_vehicle_core_projection_accepts_real_parser_shape_without_asserting_metadata():
    from tire_api.adapters.xiaomi import CURRENT_ID, parse_config
    from test_vehicles import body

    actual = parse_config(body())
    expected = {key: deepcopy(actual[key]) for key in ('vehicle', 'trims', 'fitments')}
    actual['coverage'] = {'notice': 'outside Golden vehicle structure contract'}
    actual['documents'] = []
    actual['footnotes'] = ['not compared by the three-group contract']
    source = {**SOURCE, 'query': {'vehicle_id': CURRENT_ID}}
    checked = compare_case('vehicle', expected, actual, source)
    assert aggregate(checked)['state'] == 'passed'
    actual['vehicle']['source_version'] = 'changed within asserted group'
    assert compare_case('vehicle', expected, actual, source)['state'] == 'failed'


def test_vehicle_wheel_references_follow_unordered_membership_without_hiding_missing_or_duplicate_ids():
    from tire_api.adapters.xiaomi import CURRENT_ID, parse_config
    from test_vehicles import body

    actual = parse_config(body())
    expected = {key: deepcopy(actual[key]) for key in ('vehicle', 'trims', 'fitments')}
    source = {**SOURCE, 'query': {'vehicle_id': CURRENT_ID}}
    actual['trims'].reverse()
    actual['fitments'].reverse()
    for trim in actual['trims']:
        trim['wheel_option_ids'].reverse()
    assert aggregate(compare_case('vehicle', expected, actual, source))['state'] == 'passed'
    broken = deepcopy(actual)
    broken['trims'][0]['wheel_option_ids'].pop()
    assert compare_case('vehicle', expected, broken, source)['state'] == 'failed'
    actual['trims'][0]['wheel_option_ids'].append(actual['trims'][0]['wheel_option_ids'][0])
    assert compare_case('vehicle', expected, actual, source)['state'] == 'failed'


@pytest.mark.parametrize('mutation', ['missing_manufacturer', 'invalid_manufacturer', 'name_instead_of_model', 'extra_group'])
def test_vehicle_expected_requires_current_core_scope(mutation):
    expected = vehicle()
    if mutation == 'missing_manufacturer':
        del expected['vehicle']['manufacturer']
    elif mutation == 'invalid_manufacturer':
        expected['vehicle']['manufacturer'] = 'unstructured'
    elif mutation == 'name_instead_of_model':
        expected['vehicle']['name'] = expected['vehicle'].pop('model')
    else:
        expected['coverage'] = {}
    with pytest.raises(ValueError):
        validate_expected('vehicle', expected)


def test_contract_has_a_stable_content_digest_and_reports_are_bounded():
    descriptor = contract_descriptor()
    assert descriptor == contract_descriptor() and len(descriptor['digest']) == 64
    rows = [tire('001'), tire('002')]
    rows[0]['facts'] = {f'field-{index}': 0 for index in range(95)}
    rows[1]['facts'] = deepcopy(rows[0]['facts'])
    actual = deepcopy(rows)
    for item in actual:
        item['facts'] = {key: 1 for key in item['facts']}
    checked = report(rows, actual)
    assert checked['failure_count'] == 190 and len(checked['failures']) == 100
    assert checked['failures_truncated'] and aggregate(checked)['state'] == 'failed'


@pytest.mark.parametrize('name', ['reparse.py', 'service.py', 'vehicles.py', 'quality.py',
                                'vehicle_quality.py', 'golden.py', 'parser_releases.py'])
def test_host_candidate_or_gate_semantics_change_invalidates_saved_report(monkeypatch, name):
    from pathlib import Path
    from tire_api import golden_checks

    rows = [tire('001'), tire('002')]
    saved = report(rows, deepcopy(rows))
    assert aggregate(saved)['state'] == 'passed'
    target = Path(golden_checks.__file__).resolve().parent / name
    read = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda path: read(path) + b'\n# changed host semantics\n'
                        if path.resolve() == target else read(path))
    current = aggregate(saved)
    assert current['state'] == 'failed'
    assert 'golden_comparison_contract_changed' in current['failure_codes']
