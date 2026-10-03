"""Field defaults must explain preference without destroying conflicting evidence."""
from copy import deepcopy
from itertools import permutations

import pytest

from tire_api.field_authority import (evidence_value_key, known_values_differ, policy_catalog,
                                      policy_descriptor, resolve_fields, source_authority)


def candidate(value, *, field='utqg_treadwear', source='maker', **changes):
    return {'id': source + ':' + field, 'variant_id': 'sku-1', 'field': field, 'source_field': field,
            'present': True, 'value': value, 'source_id': source, 'source_name': source,
            'source_class': 'manufacturer_official', 'source_region': 'US', 'snapshot_id': source + '-snap',
            'fact_version_id': source + '-fact', 'source_url': 'https://example.test/' + source,
            'raw_hash': 'a' * 64, 'parser_version': 'fixture@1',
            'observed_at': '2026-09-29T00:00:00+00:00', 'verified_at': '2026-09-30T00:00:00+00:00',
            'published_at': None, 'evidence_locator': 'SKU/UTQG', 'identity_match': 'exact',
            'region_match': 'exact', 'evidence_valid': True, 'missing_evidence': [],
            'source_conflicted': False, 'sku_specific': True, **changes}


def resolved(items):
    return resolve_fields(items, variant_id='sku-1', scope='history')


def test_different_fields_choose_their_own_authority_and_keep_both_sources():
    items = [candidate(300), candidate(500, source='regulator', source_class='regulatory',
                                      observed_at='2026-09-30T00:00:00Z'),
             candidate('A', field='eu_wet_grip'), candidate('B', field='eu_wet_grip', source='regulator',
                                      source_class='regulatory', observed_at='2026-09-30T00:00:00Z')]
    saved = deepcopy(items)
    fields = {row['field']: row for row in resolved(items)['fields']}
    assert fields['utqg_treadwear']['default_value'] == 300
    assert fields['eu_wet_grip']['default_value'] == 'B'
    for row in fields.values():
        assert row['state'] == 'conflict_preferred' and row['has_default']
        assert len(row['candidates']) == 2 and row['reasons']
        assert all(set(c['dimensions']) >= {'authority', 'identity', 'region', 'time', 'evidence'} for c in row['candidates'])
    assert items == saved


def test_true_ties_never_choose_an_id_or_input_order_winner():
    items = [candidate(300, source='a'), candidate(400, source='z')]
    signatures = []
    for order in permutations(items):
        value = resolved(list(order))
        row = value['fields'][0]
        assert row['state'] == 'conflict_tied' and not row['has_default']
        assert row['default_candidate_ids'] == [] and row['default_value'] is None
        signatures.append(value['fingerprint'])
    assert len(set(signatures)) == 1


def test_equal_values_keep_all_supporting_candidates():
    row = resolved([candidate(300, source='a'), candidate(300.0, source='b')])['fields'][0]
    assert row['state'] == 'uncontested' and row['has_default']
    assert row['default_candidate_ids'] == ['a:utqg_treadwear', 'b:utqg_treadwear']


@pytest.mark.parametrize('other', [None, False, 0, '0', '001'])
def test_unknown_boolean_number_and_code_semantics(other):
    row = resolved([candidate(1), candidate(other, source='other')])['fields'][0]
    assert row['state'] == ('uncontested' if other is None else 'conflict_tied')
    assert len(row['candidates']) == 2


def test_false_is_not_zero_and_missing_is_not_explicit_null():
    rows = resolved([candidate(False), candidate(0, source='other'),
                     candidate(None, source='missing', present=False), candidate(None, source='unknown')])['fields'][0]
    assert rows['state'] == 'conflict_tied' and not rows['has_default']
    by_id = {item['source_id']: item for item in rows['candidates']}
    assert by_id['missing']['present'] is False and by_id['unknown']['present'] is True


@pytest.mark.parametrize('changes', [
    {'identity_match': 'unverified'}, {'identity_match': 'mismatch'},
    {'region_match': 'mismatch'}, {'evidence_valid': False}, {'source_conflicted': True},
    {'variant_id': 'different-namespace'}, {'identity_match': 'reviewed_merge', 'variant_id': 'other'},
])
def test_ineligible_candidate_cannot_become_a_default(changes):
    row = resolved([candidate(300, **changes)])['fields'][0]
    assert not row['has_default']
    assert not row['candidates'][0]['eligible'] and row['candidates'][0]['exclusion_reasons']


def test_explicit_reviewed_merge_preserves_original_variant_reference():
    row = resolved([candidate(300, variant_id='original', identity_match='reviewed_merge',
                              equivalence_event_id='selected-valid-merge')])['fields'][0]
    assert row['has_default'] and row['candidates'][0]['variant_id'] == 'original'


def test_revalidation_time_does_not_break_a_content_tie():
    row = resolved([candidate(300), candidate(400, source='later304',
                        verified_at='2026-10-01T00:00:00Z')])['fields'][0]
    assert row['state'] == 'conflict_tied'


def test_content_time_and_then_evidence_completeness_explain_preference():
    row = resolved([candidate(300), candidate(400, source='later',
                        observed_at='2026-09-30T00:00:00Z')])['fields'][0]
    assert row['default_value'] == 400 and row['state'] == 'conflict_preferred'
    row = resolved([candidate(300), candidate(400, source='incomplete',
                        evidence_locator=None, missing_evidence=['field_locator'])])['fields'][0]
    assert row['default_value'] == 300 and row['state'] == 'conflict_preferred'


def test_unknown_source_does_not_become_official_by_name_and_acoustic_requires_sku_evidence():
    assert source_authority('utqg_treadwear', 'manual_test')['tier'] is None
    assert source_authority('utqg_treadwear', 'regulatory')['tier'] is None
    assert source_authority('eu_wet_grip', 'regulatory')['tier'] == 1
    assert source_authority('acoustic_technology', 'manufacturer_official', sku_specific=False)['tier'] is None
    assert source_authority('acoustic_technology', 'manufacturer_official', sku_specific=True)['tier'] == 1
    row = resolved([candidate(300, source_name='EPREL 官方 ADAC', source_class='unclassified'),
                    candidate(400, source='official')])['fields'][0]
    assert row['default_value'] == 400


def test_aliases_share_a_decision_but_preserve_original_source_fields():
    row = resolved([candidate(300), candidate(400, field='treadwear', source='other')])['fields'][0]
    assert row['field'] == 'utqg_treadwear' and row['state'] == 'conflict_tied'
    assert {item['source_field'] for item in row['candidates']} == {'utqg_treadwear', 'treadwear'}


def test_policy_and_candidate_content_bind_fingerprint():
    result = resolved([candidate(300)])
    assert result['policy'] == policy_descriptor()
    assert policy_catalog()['policy'] == policy_descriptor()
    assert result['policy']['version'] == 'field-authority@1'
    assert len(result['policy']['digest']) == 64
    assert resolved([candidate(301)])['fingerprint'] != result['fingerprint']


def test_empty_or_only_unknown_evidence_has_no_invented_default():
    assert resolved([])['fields'] == []
    row = resolved([candidate(None), candidate(None, source='absent', present=False)])['fields'][0]
    assert row['state'] == 'unknown' and not row['has_default']


def test_shared_semantics_preserve_long_integer_precision_and_ignore_only_null():
    assert not known_values_differ([None, 1, 1.0])
    assert known_values_differ([False, 0])
    assert known_values_differ([10**45, 10**45 + 1])
    assert evidence_value_key({'value': [1, None]}) == evidence_value_key({'value': [1.0, None]})
    assert evidence_value_key('001') != evidence_value_key(1)


def test_different_offerings_are_not_a_sku_fact_conflict_or_a_default():
    row = resolved([candidate(True, field='for_sale'), candidate(False, field='for_sale', source='shop')])['fields'][0]
    assert row['state'] == 'unavailable' and not row['has_default']
    assert all(not value['eligible'] for value in row['candidates'])
    assert len(row['candidates']) == 2
