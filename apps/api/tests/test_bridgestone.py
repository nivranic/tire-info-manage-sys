"""Synthetic copies of the reviewed JP table structure and explicit faults."""
import asyncio
import importlib

import pytest

from tire_api import parser_runtime
from tire_api.domain import VariantInput


HEADERS = ['購入', '偏平率(%)', 'タイヤサイズ', 'エクストラロード', 'メーカー希望小売価格',
           '転がり抵抗係数', 'ウェットグリップ性能', '低車外音タイヤ', 'リムガード',
           '外径(mm)', '標準リム幅(インチ)', 'タイヤ幅(mm)', '注記', '商品コード']


def row(code='PSR99001', *, size='245/45R19 102Y', xl='XL', prefix=True, **changes):
    values = {'size': size, 'xl': xl, 'price': '¥1', 'pretax': '(¥1)', 'rolling': 'B',
              'wet': 'b', 'noise': '◎', 'guard': '●', 'diameter': '703', 'rim': '8½',
              'width': '243', 'note': '', 'code': code}
    values.update(changes)
    cells = '<td class="ec"><a href="https://shop.invalid/">cart</a></td>'
    if prefix:
        cells += '<td class="flatness" rowspan="2">45</td>'
    cells += ''.join(f'<td class="{"tiresize" if name == "size" else "taC"}">{value}</td>'
                     for name, value in values.items())
    return '<tr>' + cells + '</tr>'


def table(rows=None, *, headers=None):
    labels = HEADERS if headers is None else headers
    heading = ''.join(f'<th>{label}</th>' if label != '転がり抵抗係数'
                      else '<th><img alt="転がり抵抗係数" src="/synthetic.png"></th>' for label in labels)
    return ('<table class="table_basic01 table_sizeList01"><thead><tr>' + heading
            + '</tr><tr><th>税込</th><th>(本体価格)</th></tr></thead><tbody>'
            + (row() if rows is None else ''.join(rows)) + '</tbody></table>')


def body(tables=None):
    return ('<html><head><title>POTENZA S007A - synthetic specification table</title></head><body>'
            + (table() if tables is None else ''.join(tables)) + '</body></html>')


def parse(value=None, query=None):
    adapter = importlib.import_module('tire_api.adapters.bridgestone')
    return adapter.parse_html(body() if value is None else value, {} if query is None else query)


def test_exact_jp_identity_unknown_attributes_units_and_per_field_evidence():
    value = parse()[0]
    assert (value['brand'], value['model'], value['region']) == ('Bridgestone', 'POTENZA S007A', 'JP')
    assert (value['manufacturer_product_code'], value['size'], value['load_index'], value['speed_rating']) == (
        'PSR99001', '245/45R19', '102', 'Y')
    assert value['xl'] is True
    assert all(value[name] is None for name in ['hl', 'oe_mark', 'acoustic_technology', 'run_flat'])
    facts = value['facts']
    assert facts['product_code_type'] == 'PRODUCT_CODE'
    assert facts['overall_diameter_mm'] == 703 and facts['overall_width_mm'] == 243
    assert facts['standard_rim_width_in'] == 8.5
    assert (facts['jp_rolling_resistance_grade'], facts['jp_wet_grip_grade']) == ('B', 'b')
    assert facts['jp_low_external_noise'] is True and facts['rim_guard'] is True
    assert not {'eu_fuel_efficiency', 'eu_wet_grip', 'gtin', 'utqg_treadwear'} & facts.keys()
    spans = facts['evidence_spans']
    assert all('facts.' + name in spans for name in facts if name != 'evidence_spans')
    assert spans['manufacturer_product_code'].endswith('/td[15]')
    assert VariantInput.model_validate(value).identity()['product_code_type'] == 'PRODUCT_CODE'


def test_rowspan_and_same_size_distinct_codes_do_not_merge():
    rows = parse(body([table([row(), row('PSR99002', prefix=False, xl='')])]))
    assert len(rows) == 2 and rows[1]['xl'] is None
    assert rows[1]['facts']['evidence_spans']['manufacturer_product_code'].endswith('/td[14]')
    assert len({VariantInput.model_validate(value).identity_key('bridgestone-jp', 'q', index)[0]
                for index, value in enumerate(rows)}) == 2


def test_missing_japanese_label_grades_remain_unknown():
    values = parse(body([table([row(rolling='', wet='')])]))
    assert len(values) == 1
    assert not {'jp_rolling_resistance_grade', 'jp_wet_grip_grade'} & values[0]['facts'].keys()


def test_all_tables_are_validated_before_model_and_size_filters():
    value = body([table(), table([row('PSR99002', size='205/50R16 87V', xl='',
                                   rim='6½', rolling='C', wet='a', noise='', guard='', note='source note')])])
    selected = parse(value, {'model': 'POTENZA S007A', 'size': '205/50ZR16'})
    assert len(selected) == 1 and selected[0]['speed_rating'] == 'V'
    assert selected[0]['facts']['standard_rim_width_in'] == 6.5
    assert selected[0]['facts']['source_note'] == 'source note'
    assert 'jp_low_external_noise' not in selected[0]['facts'] and 'rim_guard' not in selected[0]['facts']
    assert parse(value, {'model': 'POTENZA SPORT'}) == []
    assert parse(value, {'size': 'bad'}) == []
    assert parse(value, {'size': '225/40R18'}) == []


@pytest.mark.parametrize('changes', [
    {'code': ''}, {'code': 'other'}, {'size': '245/45R19 102FAST'}, {'size': 'unknown'},
    {'xl': 'SL'}, {'rolling': 'AAAA'}, {'wet': 'A'}, {'noise': 'no'}, {'guard': '?'},
    {'diameter': '-703'}, {'width': 'nan'}, {'rim': 'eight'}, {'diameter': ''},
    {'rim': '<script>8</script>'},
])
def test_corrupt_unmatched_row_rejects_complete_response(changes):
    with pytest.raises(ValueError, match='^parser_schema_changed$'):
        parse(body([table([row(), row(**{'code': 'PSR99002', **changes})])]), {'size': '225/40R18'})


@pytest.mark.parametrize('value', [
    body([table([])]), body([table([row(), row()])]),
    body([table(headers=list(reversed(HEADERS)))]),
    body().replace('table_sizeList01', 'other'),
    body().replace('POTENZA S007A -', 'POTENZA SPORT -'),
    body().replace('class="tiresize"', 'class="other"'),
    body().replace('</tbody>', ''), body().replace('</table>', ''),
    body().replace('PSR99001</td>', 'PSR99001<table></table></td>'),
    '<html><title>challenge</title></html>',
])
def test_unreviewed_or_incomplete_structure_is_rejected(value):
    with pytest.raises(ValueError, match='^parser_schema_changed$'):
        parse(value)


def test_marketing_scripts_and_other_tables_do_not_supply_facts():
    value = body().replace('<body>', '<body><script>"PNCS XL RUNFLAT"</script>'
                          '<table><tr><td>unknown</td></tr></table>')
    assert parse(value) == parse()


def test_registered_fixed_source_runs_in_actual_parser_child():
    from tire_api.adapters import registry
    source = registry.SPECS['bridgestone-jp']
    assert source.region == 'JP' and source.source_class == 'manufacturer_official'
    assert registry.query_url({'model': 'POTENZA S007A'}, source.id) == source.origin + '/potenza/s007a/size.html'
    descriptor = parser_runtime.current_parser(source.id)
    value = asyncio.run(parser_runtime.parse_isolated(source.id, body(), {},
        descriptor['parser_version'], descriptor['parser_digest']))
    assert value['payload'] == parse() and value['receipt']['exit_code'] == 0 and value['receipt']['reaped']


def test_previous_eleven_entry_bundle_still_executes_after_jp_install(tmp_path, monkeypatch):
    from tire_api import parser_bundles as bundles
    from test_parser_bundles import execute_bundle, pre_bridgestone_install, trusted_copy

    source = trusted_copy(tmp_path, monkeypatch)
    catalog = parser_runtime.source_catalog()
    pre_bridgestone_install(source)
    with monkeypatch.context() as previous:
        previous.setattr(parser_runtime, 'source_catalog', lambda: {
            key: value for key, value in catalog.items() if key in bundles._DOCUMENT_SOURCES})
        old = bundles.seal_deployed_bundle()
    assert set(old['parsers']) == set(bundles._DOCUMENT_SOURCES)
    assert 'adapters/bridgestone.py' not in old['files']
    trusted_copy(tmp_path, monkeypatch)
    current = bundles.seal_deployed_bundle()
    assert set(current['parsers']) == set(bundles._YOKOHAMA_SOURCES)
    value = asyncio.run(execute_bundle(old))
    assert len(value['payload']) == 2
    assert value['receipt']['bundle_id'] == old['bundle_id']
    assert value['receipt']['exit_code'] == 0 and value['receipt']['reaped']


def test_http_and_query_telemetry_keep_bounded_jp_source_attribution():
    from tire_api.adapters.transport import SafeHttpClient
    from tire_api.telemetry import TelemetryRuntime, observe
    from test_adapters import FakeResponse, FakeSession

    runtime = TelemetryRuntime('tire-test', logs_enabled=False)
    client = SafeHttpClient(frozenset({'tire.bridgestone.co.jp'}))
    client.session = FakeSession([FakeResponse(200, chunks=[b'synthetic-private-body'])])
    try:
        with runtime.scope(), observe('source.query', component='crawler', source='bridgestone-jp'):
            value = asyncio.run(client.get('https://tire.bridgestone.co.jp/potenza/s007a/size.html'))
        assert value.body == 'synthetic-private-body'
        spans = runtime.finished_spans()
        assert [row['name'] for row in spans] == ['source.http', 'source.query']
        assert all(row['attributes']['source'] == 'bridgestone-jp' for row in spans)
        assert spans[0]['parent_span_id'] == spans[1]['span_id']
        assert 'synthetic-private-body' not in str(spans) and 'tire.bridgestone.co.jp' not in str(spans)
    finally:
        runtime.shutdown()
