"""Synthetic Dunlop transfer-state contracts and source-scope regressions."""
import asyncio
import json

import pytest

from tire_api.adapters import dunlop
from tire_api.domain import VariantInput

STATE_KEY = 'a' * 64


def gtin(prefix):
    total = sum(int(value) * (3 if index % 2 == 0 else 1)
                for index, value in enumerate(reversed(prefix)))
    return prefix + str(-total % 10)


def row(**changes):
    value = {'material': '000123', 'rep_code': '000123', 'brand': 'Dunlop',
        'product_segment': 'SUMMER', 'vehicle_category': 'SUV', 'status_def': 'active',
        'tyre_size': '235/55R19', 'li_si': '101Y', 'ean_upc': gtin('123456789012'),
        'eu_label': {'fuel_efficiency_2020_740': 'C', 'wet_grip_2020_740': 'A',
            'external_rolling_noise_class_2020_740': 'B', 'external_rolling_noise_db_2020_740': '71'},
        'eu_label_exempt': False, 'snowflake': False, 'ice': False, 'mobility_technology': False,
        'mfs': True, 'commercial_vehicle_info': False, 'is_lt': False,
        'radial': 'R', 'lastindex_1': '101', 'lastindex_2': None, 'lastindex_3': None,
        'lastindex_4': None, 'geschwindigkeitsindex_1': 'Y', 'geschwindigkeitsindex_2': None,
        'extra_load': None, 'oem_brand': None, 'oe_models': None,
        'eprel_link': 'https://eprel.ec.europa.eu/qr/123456', 'eprel_reg_nr': '123456',
        'width_mm': 235, 'ratio': 55, 'rim_inch': 19,
        'technology_info': {'tokens': ['MFS'], 'flags': {'extended_mobility_technology': False,
            'noise_cancellation_technology': False, 'ms': False,
            'rim_protection': True, 'snowflake': False, 'ice': False}}}
    value.update(changes)
    return value


def payload(rows=None):
    return {'quickInfo': {'tyreModelname': dunlop.MODEL, 'slug': dunlop.SLUG,
        'languageCode': 'en', 'season': 'SUMMER', 'icons': {'snowflake': True, 'ice': True},
        'brands': ['Global Manufacturer']},
        'sizes': rows if rows is not None else [row(), row(material='000124', rep_code='000124',
            li_si='105Y XL', lastindex_1='105', extra_load='XL', ean_upc=gtin('123456789013'),
            eprel_link='https://eprel.ec.europa.eu/qr/123457', eprel_reg_nr='123457')],
        'dimensions': [{'oemBrand': 'SUMMARY ONLY', 'info': {'snowIcon': True}}],
        'otherTyres': [{'sizes': [row(material='ALIEN', brand='Other Brand')]}]}


def document(data=None, state=None):
    transfer = state if state is not None else {STATE_KEY: {'u': dunlop.RESPONSE_URL,
        's': 200, 'rt': 'text', 'b': json.dumps(data if data is not None else payload())}}
    return ('<html><head><title>SPORT MAXX RT2 – SUMMER – Dunlop</title>'
        '<link rel="canonical" href="' + dunlop.URL + '"></head><body>'
        '<script id="ng-state" type="application/json">' + json.dumps(transfer)
        + '</script></body></html>')


def test_same_size_material_codes_and_gtins_remain_distinct():
    values = dunlop.parse_html(document(), {'size': '235/55R19'})
    assert [value['manufacturer_product_code'] for value in values] == ['000123', '000124']
    assert [value['load_index'] for value in values] == ['101', '105']
    assert [value['xl'] for value in values] == [None, True]
    keys = [VariantInput.model_validate(value).identity_key('dunlop-eu', 'query', index)
            for index, value in enumerate(values)]
    assert keys[0][0] != keys[1][0] and all(status == 'source_scoped' for _, status in keys)
    assert values[0]['facts']['gtin'] != values[1]['facts']['gtin']
    for value in values:
        assert value['brand'] == 'Dunlop' and value['region'] == 'EU'
        assert value['facts']['product_code_type'] == 'MATERIAL_CODE'
        assert all(value[key] is None for key in ('oe_mark', 'run_flat', 'acoustic_technology'))
        assert value['facts']['three_peak_mountain_snowflake'] is False
        assert value['facts']['ice_grip'] is False
        assert value['facts']['m_plus_s'] is False
        assert value['facts']['rim_guard'] is True
        assert value['facts']['technology_features'] == ['MFS']
        assert 'oe_vehicle_scope' not in value['facts']
        assert all('facts.' + key in value['facts']['evidence_spans']
                   for key in value['facts'] if key != 'evidence_spans')


def test_geometry_and_speed_preserve_zr_and_parenthesized_y():
    value = row(tyre_size='235/55ZR19', radial='ZR', li_si='101(Y)', geschwindigkeitsindex_1='(Y)')
    parsed = dunlop.parse_html(document(payload([value])), {'size': '235/55R19'})
    assert parsed[0]['size'] == '235/55ZR19' and parsed[0]['speed_rating'] == '(Y)'
    assert dunlop.parse_html(document(), {'model': 'Other Model'}) == []
    assert dunlop.parse_html(document(), {'size': 'invalid'}) == []


@pytest.mark.parametrize('changes', [
    {'brand': 'Other'}, {'product_segment': 'WINTER'}, {'material': 123},
    {'rep_code': '999999'}, {'ean_upc': '1234567890129'}, {'width_mm': True},
    {'width_mm': 245}, {'radial': 'ZR'}, {'lastindex_1': '105'}, {'lastindex_2': '99'},
    {'geschwindigkeitsindex_1': '(Y)'}, {'extra_load': 'XL'}, {'li_si': '101I'},
    {'eu_label_exempt': True}, {'is_lt': True}, {'commercial_vehicle_info': True},
    {'snowflake': 0}, {'mfs': 1}, {'status_def': 'unknown'},
    {'eprel_link': 'https://example.invalid/qr/123456'}, {'eprel_reg_nr': '999999'},
    {'technology_info': {'tokens': [], 'flags': {}}},
])
def test_invalid_unmatched_row_rejects_entire_response(changes):
    values = [row(material='000124', rep_code='000124', ean_upc=gtin('123456789013')), row(**changes)]
    with pytest.raises(ValueError, match='^parser_schema_changed$'):
        dunlop.parse_html(document(payload(values)), {'size': '999/99R99'})


@pytest.mark.parametrize('field,value', [('fuel_efficiency_2020_740', 'F'),
    ('wet_grip_2020_740', True), ('external_rolling_noise_class_2020_740', 'D'),
    ('external_rolling_noise_db_2020_740', '71 dB')])
def test_label_units_and_types_are_checked(field, value):
    value_row = row()
    value_row['eu_label'][field] = value
    with pytest.raises(ValueError, match='^parser_schema_changed$'):
        dunlop.parse_html(document(payload([value_row])), {})


@pytest.mark.parametrize('before,after', [
    ('SPORT MAXX RT2 – SUMMER – Dunlop</title>', 'OTHER – SUMMER – Dunlop</title>'),
    (dunlop.URL, dunlop.URL + '?region=other'),
    ('id="ng-state"', 'id="other"'), ('type="application/json"', 'type="text/javascript"'),
    (dunlop.RESPONSE_URL, dunlop.RESPONSE_URL.replace('https:', 'http:')),
    ('"s": 200', '"s": 500'), ('"rt": "text"', '"rt": "json"'),
])
def test_document_binding_drift_fails(before, after):
    with pytest.raises(ValueError, match='^parser_schema_changed$'):
        dunlop.parse_html(document().replace(before, after), {})


def test_model_metadata_duplicate_state_and_duplicate_json_keys_fail():
    data = payload()
    data['quickInfo']['slug'] = 'other'
    duplicate = {key: {'u': dunlop.RESPONSE_URL, 's': 200, 'rt': 'text', 'b': json.dumps(payload())}
                 for key in ('a' * 64, 'b' * 64)}
    examples = [document(data), document(state=duplicate), document(payload([])),
        document(payload([row(), row()])), document().replace('"s": 200', '"s": 200, "s": 200')]
    for body in examples:
        with pytest.raises(ValueError, match='^parser_schema_changed$'):
            dunlop.parse_html(body, {})


def test_fixed_source_and_actual_isolated_child():
    from tire_api.adapters import registry
    from tire_api import parser_runtime
    assert registry.query_url({'model': dunlop.MODEL}, 'dunlop-eu') == dunlop.URL
    assert registry.permitted_path(dunlop.URL, 'dunlop-eu')
    for changed in (dunlop.URL + '?x=1', dunlop.URL + '#x', dunlop.RESPONSE_URL):
        assert not registry.permitted_path(changed, 'dunlop-eu')
    descriptor = parser_runtime.current_parser('dunlop-eu')
    result = asyncio.run(parser_runtime.parse_isolated('dunlop-eu', document(), {},
        descriptor['parser_version'], descriptor['parser_digest']))
    assert result['payload'] == dunlop.parse_html(document(), {})
    assert result['receipt']['reaped'] and result['receipt']['exit_code'] == 0


def test_old_sixteen_entry_archive_executes_after_new_install(tmp_path, monkeypatch):
    from tire_api import parser_bundles as bundles, parser_runtime
    from test_parser_bundles import execute_bundle, pre_dunlop_install, trusted_copy
    source = trusted_copy(tmp_path, monkeypatch)
    catalog = parser_runtime.source_catalog()
    pre_dunlop_install(source)
    with monkeypatch.context() as previous:
        previous.setattr(parser_runtime, 'source_catalog', lambda: {
            key: value for key, value in catalog.items() if key in bundles._YOKOHAMA_SOURCES})
        old = bundles.seal_deployed_bundle()
    trusted_copy(tmp_path, monkeypatch)
    current = bundles.seal_deployed_bundle()
    assert set(old['parsers']) == set(bundles._YOKOHAMA_SOURCES)
    assert set(current['parsers']) == set(bundles._DUNLOP_SOURCES)
    assert 'adapters/dunlop.py' not in old['files']
    result = asyncio.run(execute_bundle(old))
    assert result['payload'] and result['receipt']['reaped'] and result['receipt']['exit_code'] == 0
