"""Namespace identities preserve identifiers; legacy reconstruction never migrates data."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from tire_api.domain import VariantInput, digest


def record(namespace='MSPN'):
    return {'brand': 'Synthetic Brand', 'model': 'Synthetic Tire', 'manufacturer_product_code': '001',
        'region': 'US', 'size': '265/40ZR20', 'load_index': '104', 'speed_rating': 'Y',
        'xl': True, 'hl': False, 'oe_mark': 'LUC', 'acoustic_technology': 'Acoustic', 'run_flat': False,
        'source_variant_name': 'synthetic-one', 'facts': {'product_code_type': namespace, 'weight_lb': 19.0}}


def parsed(namespace='MSPN', **changes):
    return VariantInput.model_validate({**record(namespace), **changes})


def test_known_namespaces_separate_same_code_that_collided_under_legacy_contract():
    mspn, cai = parsed(), parsed('CAI')
    assert mspn.legacy_identity_key('a', 'q', 0) == cai.legacy_identity_key('a', 'q', 1)
    assert mspn.identity_key('a', 'q', 0)[0] != cai.identity_key('a', 'q', 1)[0]
    assert mspn.identity()['product_code_type'] == 'MSPN'
    assert cai.identity()['product_code_type'] == 'CAI'


def test_complete_known_identity_is_stable_across_sources_queries_rows_and_ordinary_facts():
    original = parsed()
    changed = parsed(facts={'weight_lb': 20, 'product_code_type': 'MSPN'})
    assert original.identity_key('a', 'q', 0) == changed.identity_key('b', 'other', 12)
    assert original.identity_key('a', 'q', 0)[1] == 'complete'
    assert original.identity_key('a', 'q', 0)[0] != original.legacy_identity_key('a', 'q', 0)[0]


@pytest.mark.parametrize('explicit_null', [False, True])
def test_unknown_namespace_keeps_rows_and_queries_provisional_even_with_same_product_code(explicit_null):
    value = record(None)
    if not explicit_null:
        del value['facts']['product_code_type']
    variant = VariantInput.model_validate(value)
    original = variant.identity_key('a', 'q', 0)
    assert variant.identity()['product_code_type'] is None and original[1] == 'source_scoped'
    assert original == variant.identity_key('a', 'q', 0)
    assert len({original[0], variant.identity_key('b', 'q', 0)[0],
                variant.identity_key('a', 'other', 0)[0], variant.identity_key('a', 'q', 1)[0]}) == 4


def test_known_code_with_other_unknown_attributes_stays_source_scoped_but_not_row_scoped():
    variant = parsed(hl=None)
    assert variant.identity_key('a', 'q', 0)[1] == 'source_scoped'
    assert variant.identity_key('a', 'q', 0) == variant.identity_key('a', 'other', 3)
    assert variant.identity_key('a', 'q', 0) != variant.identity_key('b', 'q', 0)


def test_missing_code_is_provisional_even_when_namespace_is_known():
    variant = parsed(manufacturer_product_code=None)
    assert variant.identity_key('a', 'q', 0)[1] == 'source_scoped'
    assert variant.identity_key('a', 'q', 0) != variant.identity_key('a', 'q', 1)


@pytest.mark.parametrize('value', ['', ' ', 'MSPN\n', ' MSPN', '\x00MSPN', 0, False, {}, [], 'N' * 101])
def test_invalid_namespace_cannot_become_complete(value):
    with pytest.raises(ValidationError):
        parsed(value)


@pytest.mark.parametrize('value', ['', ' ', '\x00', 'A\tB'])
def test_empty_or_control_character_product_code_is_rejected(value):
    with pytest.raises(ValidationError):
        parsed(manufacturer_product_code=value)


def test_identifiers_keep_leading_zeros_and_namespaces_are_not_guessed_from_aliases():
    original = parsed()
    assert original.identity_key('a', 'q', 0) != parsed(manufacturer_product_code='1').identity_key('a', 'q', 0)
    assert original.identity_key('a', 'q', 0) != parsed('mspn').identity_key('a', 'q', 0)
    with_gtin = parsed(facts={**record()['facts'], 'gtin': '00012345678905'})
    other_gtin = parsed(facts={**record()['facts'], 'gtin': '00012345678912'})
    assert with_gtin.identity()['gtin'] == '00012345678905'
    assert with_gtin.identity_key('a', 'q', 0) != other_gtin.identity_key('a', 'q', 0)


def test_legacy_identity_reconstruction_exactly_preserves_original_complete_and_scoped_hashes():
    source = record()
    preserved = deepcopy(source)
    variant = VariantInput.model_validate(source)
    old_identity = variant.model_dump(exclude={'facts', 'source_variant_name'})
    assert variant.legacy_identity() == old_identity
    assert variant.legacy_identity_key('a', 'q', 0) == (digest(old_identity), 'complete')
    unknown = parsed(manufacturer_product_code=None, xl=None)
    old_identity = unknown.model_dump(exclude={'facts', 'source_variant_name'})
    old_scope = {'source_id': 'a', 'identity': old_identity, 'query_key': 'q',
                 'source_variant_name': unknown.source_variant_name, 'row_index': 2}
    assert unknown.legacy_identity_key('a', 'q', 2) == (digest(old_scope), 'source_scoped')
    assert source == preserved
