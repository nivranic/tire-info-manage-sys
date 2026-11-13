"""Synthetic three-table examples for the reviewed Singapore page contract."""
import asyncio
import importlib
from html import escape

import pytest

from tire_api.domain import VariantInput


MODELS = ('Eagle F1 Asymmetric 6', 'Eagle F1 Asymmetric 6 SUV')


def document(main=None, suv=None):
    groups = [main if main is not None else [
        ('19', '245/45R19', '102', '', 'XL (EDR)'),
        ('19', '235/50R19', '103', 'T', 'MO XL'),
        ('21', '255/40R21', '102', 'Y *', 'XL')],
        suv if suv is not None else [('20', '255/55R20', '110', 'Y', 'X (EDR)')]]
    primary = '<tr>' + ''.join('<th>' + name + '</th>' for name in ['Pattern', 'Rim', 'Size', 'Load', 'Speed', 'XL']) + '</tr>'
    layouts = []
    for model, rows in zip(MODELS, groups):
        primary += '<tr><td rowspan="99">' + model.upper() + '</td></tr>'
        for row in rows:
            primary += '<tr>' + ''.join('<td>' + escape(value) + '</td>' for value in row) + '</tr>'
        cells = [' '.join((size, load + speed, marks)).strip() for _, size, load, speed, marks in rows]
        layouts.append('<table class="table table-hover table-bordered"><thead><tr><th>Tyre Rim: 19&quot;</th></tr></thead><tbody>'
                       + ''.join('<tr><td>' + escape(value) + '</td></tr>' for value in cells) + '</tbody></table>')
    return ('<html><head><title>Goodyear Eagle F1 Asymmetric 6 | Goodyear Singapore</title></head><body>'
            + '<table><thead>' + primary[:primary.index('</tr>') + 5] + '</thead><tbody>'
            + primary[primary.index('</tr>') + 5:] + '</tbody></table>' + ''.join(layouts) + '</body></html>')


def parse(body=None, query=None):
    return importlib.import_module('tire_api.adapters.goodyear').parse_html(document() if body is None else body, query or {})


def test_missing_speed_unknown_codes_and_original_markings():
    values = parse()
    assert len(values) == 4
    assert values[0]['speed_rating'] is None and values[0]['load_index'] == '102'
    assert values[0]['xl'] is True
    assert values[1]['facts']['source_load_marking'] == 'MO XL'
    assert values[2]['speed_rating'] == 'Y' and values[2]['facts']['source_speed_marking'] == 'Y *'
    assert values[3]['model'] == MODELS[1] and values[3]['xl'] is None
    assert values[3]['facts']['source_load_marking'] == 'X (EDR)'
    for value in values:
        assert value['brand'] == 'Goodyear' and value['region'] == 'SG'
        assert all(value[key] is None for key in ['manufacturer_product_code', 'oe_mark', 'run_flat', 'acoustic_technology'])
        spans = value['facts']['evidence_spans']
        assert spans['load_index'].startswith('(//table)[1]/tbody/tr[')
        assert all('facts.' + key in spans for key in value['facts'] if key != 'evidence_spans')
        assert VariantInput.model_validate(value).identity_key('goodyear-sg', 'query', 0)[1] == 'source_scoped'
    assert 'speed_rating' not in values[0]['facts']['evidence_spans']


def test_model_size_filters_and_r_zr_equivalence():
    body = document(main=[('19', '245/45ZR19', '102', '(Y)', 'XL FP')])
    values = parse(body, {'model': MODELS[0].upper(), 'size': '245/45R19'})
    assert len(values) == 1 and values[0]['size'] == '245/45ZR19' and values[0]['speed_rating'] == '(Y)'
    assert parse(body, {'model': MODELS[1]})[0]['model'] == MODELS[1]
    assert parse(body, {'model': 'other'}) == []
    assert parse(body, {'size': 'invalid'}) == []


@pytest.mark.parametrize('row', [
    ('18', '245/45R19', '102', 'Y', 'XL'), ('19', 'invalid', '102', 'Y', 'XL'),
    ('19', '245/45R19', 'bad', 'Y', 'XL'), ('19', '245/45R19', '102', 'I', 'XL'),
    ('19', '245/45R19', '102', 'Y SSR', 'XL'), ('19', '245/45R19', '102', 'Y', 'SSR'),
    ('19', '245/45R19', '102', 'Y', 'XL ' + 'A' * 600),
])
def test_invalid_unmatched_row_rejects_whole_response(row):
    with pytest.raises(ValueError, match='^parser_schema_changed$'):
        parse(document(main=[row]), {'model': MODELS[1]})


@pytest.mark.parametrize('mutation', [
    lambda body: body.replace('Pattern</th>', 'Changed</th>'),
    lambda body: body.replace('Goodyear Singapore</title>', 'Other Region</title>'),
    lambda body: body.replace('102Y * XL</td>', '103Y * XL</td>'),
    lambda body: body.replace('Y *</td>', 'Y *<script>unsafe</script></td>'),
    lambda body: body.replace('</table>', '', 1),
    lambda body: body.replace('EAGLE F1 ASYMMETRIC 6 SUV</td>', 'OTHER MODEL</td>'),
    lambda body: body.replace('</tbody></table></body>', '</tbody></table><table></table></body>'),
    lambda body: body.replace('<td>102</td>', '<td colspan="2">102</td>', 1),
])
def test_layout_drift_or_malformed_contract_is_rejected(mutation):
    with pytest.raises(ValueError, match='^parser_schema_changed$'):
        parse(mutation(document()))


def test_duplicate_and_unbounded_primary_observations_are_rejected():
    row = ('19', '245/45R19', '102', 'Y', 'XL')
    for rows in [[row, row], [row] * 501, []]:
        with pytest.raises(ValueError, match='^parser_schema_changed$'):
            parse(document(main=rows))


def test_fixed_url_and_real_parser_child():
    from tire_api import parser_runtime
    from tire_api.adapters import registry
    adapter = importlib.import_module('tire_api.adapters.goodyear')
    url = next(iter(adapter.SOURCE_CONFIG['model_urls'].values()))
    assert registry.query_url({'model': MODELS[1]}, 'goodyear-sg') == url
    assert registry.permitted_path(url, 'goodyear-sg')
    for changed in [url + '?extra=1', url + '#fragment', url.replace('https:', 'http:'), url.replace('www.goodyear.com.sg', 'example.invalid')]:
        assert not registry.permitted_path(changed, 'goodyear-sg')
    descriptor = parser_runtime.current_parser('goodyear-sg')
    parsed = asyncio.run(parser_runtime.parse_isolated('goodyear-sg', document(), {},
        descriptor['parser_version'], descriptor['parser_digest']))
    assert parsed['payload'] == parse() and parsed['receipt']['exit_code'] == 0 and parsed['receipt']['reaped']


def test_thirteen_entry_archive_executes_own_source_after_install(tmp_path, monkeypatch):
    from tire_api import parser_bundles as bundles, parser_runtime
    from test_parser_bundles import execute_bundle, pre_goodyear_install, trusted_copy
    source = trusted_copy(tmp_path, monkeypatch)
    catalog = parser_runtime.source_catalog()
    pre_goodyear_install(source)
    with monkeypatch.context() as previous:
        previous.setattr(parser_runtime, 'source_catalog', lambda: {
            key:value for key,value in catalog.items() if key in bundles._CONTINENTAL_SOURCES})
        old = bundles.seal_deployed_bundle()
    trusted_copy(tmp_path, monkeypatch)
    current = bundles.seal_deployed_bundle()
    assert set(old['parsers']) == set(bundles._CONTINENTAL_SOURCES)
    assert set(current['parsers']) == set(bundles._GOODYEAR_SOURCES)
    assert 'adapters/goodyear.py' not in old['files']
    result = asyncio.run(execute_bundle(old))
    assert len(result['payload']) == 2 and result['receipt']['exit_code'] == 0 and result['receipt']['reaped']


def test_source_telemetry_is_attributed_without_raw_content():
    from tire_api.adapters.transport import SafeHttpClient
    from tire_api.telemetry import TelemetryRuntime, observe
    from test_adapters import FakeResponse, FakeSession
    runtime = TelemetryRuntime('tire-test', logs_enabled=False)
    client = SafeHttpClient(frozenset({'www.goodyear.com.sg'}))
    client.session = FakeSession([FakeResponse(200, chunks=[b'synthetic'])])
    try:
        with runtime.scope(), observe('source.query', component='crawler', source='goodyear-sg'):
            asyncio.run(client.get('https://www.goodyear.com.sg/tyres/goodyear-eagle-f1-asymmetric-6'))
        spans = runtime.finished_spans()
        assert [span['name'] for span in spans] == ['source.http', 'source.query']
        assert all(span['attributes']['source'] == 'goodyear-sg' for span in spans)
        assert 'synthetic' not in str(spans) and 'www.goodyear.com.sg' not in str(spans)
    finally:
        runtime.shutdown()
