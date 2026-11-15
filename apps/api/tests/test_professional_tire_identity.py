"""Real manufacturer catalogue SKU identity against the archived Dunlop original.

The literal binds the exact bytes a normal live query observed (raw_hash chained
to its receipt) and freezes the two real exact-SKU identities the production
parser must resolve from them. Values stay agent_transcription_unverified;
nothing here claims human Golden review."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from tire_api.adapters import dunlop
from tire_api.domain import VariantInput

ROOT = Path(__file__).resolve().parents[3]
LITERAL_PATH = ROOT / 'packages/domain-types/fixtures/professional-tire-source-v1/real-dunlop-sportmaxx-rt2-identity.json'
LITERAL_SHA256 = 'c6652754b862f9f8dcbd71e553bf3d3cdb9cf2aea25487b9fa8d24b03317ec23'

TOP_LEVEL_FIELDS = ('manufacturer_product_code', 'brand', 'model', 'size', 'load_index', 'xl', 'region')
FACT_FIELDS = ('product_code_type', 'gtin', 'eprel_id', 'source_label_url', 'service_description',
    'source_catalog_status', 'eu_fuel_class', 'eu_wet_grip', 'eu_noise_class')


def load_literal():
    raw = LITERAL_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == LITERAL_SHA256
    return json.loads(raw)


def binding_error(literal, body):
    """Return the frozen-binding failure for bytes, or None when they match."""
    expected = literal['original']
    if len(body) != expected['byte_count']:
        return 'byte_count_mismatch'
    digest = hashlib.sha256(body).hexdigest()
    if digest != expected['sha256'] or digest != literal['observation']['raw_hash']:
        return 'sha256_mismatch'
    return None


def read_original(literal):
    path = ROOT / literal['original']['path']
    if not path.exists():
        pytest.skip('Requires the archived Dunlop original with its pinned hash')
    body = path.read_bytes()
    error = binding_error(literal, body)
    assert error is None, error
    return body


def gtin_check_digit(gtin):
    total = sum(int(value) * (3 if index % 2 == 0 else 1)
                for index, value in enumerate(reversed(gtin[:-1])))
    return gtin[-1] == str(-total % 10)


def identity_comparison(literal, parsed):
    """Per-variant mismatch list between the frozen literal and parsed output."""
    mismatches = []
    rows = {row['manufacturer_product_code']: row for row in literal['variants']}
    if len(parsed) != literal['expected']['variant_count']:
        mismatches.append('variant_count')
    if {value['manufacturer_product_code'] for value in parsed} != set(rows):
        return mismatches + ['variant_codes']
    for value in parsed:
        row = rows[value['manufacturer_product_code']]
        for field in TOP_LEVEL_FIELDS:
            if value.get(field) != row[field]:
                mismatches.append(row['variant_label'] + ':' + field)
        for field in FACT_FIELDS:
            if value['facts'].get(field) != row[field]:
                mismatches.append(row['variant_label'] + ':facts.' + field)
    return mismatches


def test_literal_keeps_real_observation_scope_and_conservative_rights():
    literal = load_literal()
    assert literal['schema'] == 'professional-tire-source-identity@1'
    assert literal['source_id'] == 'dunlop-eu'
    observation = literal['observation']
    assert observation['transcription'] == 'agent_transcription_unverified'
    assert observation['human_golden_review'] == 'pending_external_review'
    assert observation['raw_hash'] == literal['original']['sha256']
    rights = literal['rights']
    assert rights['store_original'] and rights['workspace_reopen'] and rights['quote_identifiers']
    assert rights['provider_use'] is False and rights['export'] is False
    assert len(literal['variants']) == 2
    assert [row['size'] for row in literal['variants']] == ['235/55R19', '235/55R19']
    for row in literal['variants']:
        assert gtin_check_digit(row['gtin'])
    assert literal['expected']['identity_status'] == 'source_scoped'
    assert literal['expected']['identity_keys_distinct'] is True


def test_archived_original_matches_frozen_binding():
    literal = load_literal()
    read_original(literal)


def test_production_parser_resolves_both_bound_real_skus():
    literal = load_literal()
    body = read_original(literal)
    parsed = dunlop.parse_html(body.decode('utf-8'), literal['query'])
    assert identity_comparison(literal, parsed) == []
    for value in parsed:
        spans = value['facts']['evidence_spans']
        for field in literal['expected']['identity_fact_evidence_required']:
            assert spans.get('facts.' + field), field


def test_same_size_variants_keep_distinct_source_scoped_identity():
    literal = load_literal()
    body = read_original(literal)
    parsed = dunlop.parse_html(body.decode('utf-8'), literal['query'])
    keys = [VariantInput.model_validate(value).identity_key('dunlop-eu', 'query', index)
            for index, value in enumerate(parsed)]
    assert keys[0][0] != keys[1][0]
    assert all(status == literal['expected']['identity_status'] for _key, status in keys)
    first, second = parsed
    differing_top = sorted(field for field in TOP_LEVEL_FIELDS if first.get(field) != second.get(field))
    differing_facts = sorted(field for field in FACT_FIELDS
                             if first['facts'].get(field) != second['facts'].get(field))
    assert differing_top == ['load_index', 'manufacturer_product_code', 'xl']
    assert differing_facts == ['eprel_id', 'eu_fuel_class', 'gtin', 'service_description', 'source_label_url']
    assert literal['expected']['same_size_distinct_by'] == [
        'manufacturer_product_code', 'gtin', 'load_index', 'xl', 'eprel_id']


def test_tampered_original_bytes_fail_the_frozen_binding():
    literal = load_literal()
    body = bytearray(read_original(literal))
    body[len(body) // 2] ^= 1
    assert binding_error(literal, bytes(body)) == 'sha256_mismatch'
    trimmed = read_original(literal)[:-1]
    assert binding_error(literal, trimmed) == 'byte_count_mismatch'


def test_literal_drift_against_parser_output_is_detected():
    literal = load_literal()
    body = read_original(literal)
    parsed = dunlop.parse_html(body.decode('utf-8'), literal['query'])
    for change in ({'gtin': '5452000703940'}, {'load_index': '109'}, {'xl': True}):
        drifted = deepcopy(literal)
        row = drifted['variants'][0]
        row.update(change)
        assert identity_comparison(drifted, parsed)
    dropped = deepcopy(literal)
    dropped['expected']['variant_count'] = 3
    assert identity_comparison(dropped, parsed) == ['variant_count']
