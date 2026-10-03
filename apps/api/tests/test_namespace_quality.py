"""Namespace regression references never establish SKU equivalence."""
from copy import deepcopy

import pytest

from tire_api.quality import assess_quality, stable_key
from tire_api.reparse import compare_candidate
from test_quality import ROW, reduced


def typed(value, code_type):
    row = deepcopy(value)
    row['facts']['product_code_type'] = code_type
    return row


def test_same_digits_different_namespaces_align_independently_on_repeated_observation():
    rows = [typed(ROW, 'MSPN'), typed(ROW, 'CAI')]
    report = assess_quality(rows, list(reversed(rows)))
    assert report['aligned_rows'] == 2 and report['reason_codes'] == []
    assert stable_key(rows[0]) != stable_key(rows[1])
    assert report['namespace_reference_alignments'] == []


def test_unknown_to_known_is_a_reference_with_added_removed_identity_keys():
    after = typed(ROW, 'MSPN')
    quality, difference = compare_candidate({'payload': [ROW]}, [after], 'tire')
    assert quality['aligned_rows'] == 1 and not quality['blocked']
    assert quality['namespace_reference_alignments'] == [{
        'baseline_key': stable_key(ROW), 'candidate_key': stable_key(after), 'entity_equivalence': False}]
    assert difference['removed_row_keys'] == [stable_key(ROW)]
    assert difference['added_row_keys'] == [stable_key(after)]
    assert difference['changed_rows'][0]['changes'][0]['path'] == 'facts.product_code_type'
    assert difference['identity_changed_row_keys'] == []


def test_namespace_enrichment_does_not_hide_field_loss_or_other_identity_changes():
    after = typed(reduced(6), 'MSPN')
    after['load_index'] = '105'
    quality, difference = compare_candidate({'payload': [ROW]}, [after], 'tire')
    assert quality['known_fields'] == 20 and quality['lost_field_count'] == 6
    assert {'field_loss_threshold', 'tire_identity_changed'} <= set(quality['reason_codes'])
    assert quality['blocked'] and difference['identity_changed_row_keys']


@pytest.mark.parametrize('old,new', [
    ([ROW], [typed(ROW, 'MSPN'), typed(ROW, 'CAI')]),
    ([ROW, typed(ROW, 'CAI')], [typed(ROW, 'MSPN')]),
    ([ROW, ROW], [typed(ROW, 'MSPN')]),
])
def test_namespace_family_ambiguity_never_becomes_a_reference(old, new):
    report = assess_quality(old, new)
    assert report['namespace_reference_alignments'] == []
    assert report['reason_codes'] and report['lost_rows']


def test_known_namespace_change_is_not_enrichment_even_below_loss_threshold():
    before = [typed({**deepcopy(ROW), 'manufacturer_product_code': str(index)}, 'MSPN') for index in range(10)]
    after = deepcopy(before)
    after[0]['facts']['product_code_type'] = 'CAI'
    report, difference = compare_candidate({'payload': before}, after, 'tire')
    assert report['row_loss_ratio'] == .1
    assert report['namespace_reference_alignments'] == []
    assert report['reason_codes'] == ['tire_identity_changed'] and report['blocked']
    assert difference['identity_changed_row_keys'] == [stable_key(before[0])]


def test_known_namespace_loss_fails_closed():
    report = assess_quality([typed(ROW, 'MSPN')], [ROW])
    assert report['namespace_reference_alignments'] == []
    assert report['reason_codes'] == ['row_loss_threshold']


@pytest.mark.parametrize('invalid', [False, 0, [], {}, '', ' MSPN '])
def test_invalid_legacy_namespace_cannot_become_unknown_reference(invalid):
    report = assess_quality([typed(ROW, invalid)], [typed(ROW, 'MSPN')])
    assert report['namespace_reference_alignments'] == []
    assert 'ambiguous_alignment' in report['reason_codes']


def test_reference_key_preserves_code_leading_zeroes():
    before = {**deepcopy(ROW), 'manufacturer_product_code': '001'}
    after = typed({**deepcopy(ROW), 'manufacturer_product_code': '1'}, 'MSPN')
    report = assess_quality([before], [after])
    assert report['namespace_reference_alignments'] == [] and report['lost_rows'] == 1
