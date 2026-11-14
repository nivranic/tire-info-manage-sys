"""Synthetic specification contracts, without copied manufacturer page content."""
import asyncio
from html import escape

import pytest

from tire_api.adapters import yokohama
from tire_api.domain import VariantInput


def document(rows=None):
    rows = rows if rows is not None else [
        ('40', '225/40ZR18 (92Y)', 'XL/RF', 'BMW', 'D', 'A', '71DB/B', '-', '-', '123456'),
        ('30', 'HL295/30ZR21 (105(Y))', '-', '-', 'C', 'B', '73DB/A', '-', '-', '123457'),
    ]
    icons = ''.join('<th><span class="icon-header ' + icon + '"></span></th>' for icon in yokohama.ICONS)
    headers = '<th>Series</th><th>Size</th><th>XL/RF</th><th>OE Info</th>' + icons + '<th>EU LABEL GRADE</th>'
    body = ''.join('<tr>' + ''.join('<td>' + escape(value) + '</td>' for value in row[:9])
                   + '<td><a href="https://eprel.ec.europa.eu/qr/' + row[9] + '">View</a></td></tr>'
                   for row in rows)
    return ('<html><head><title>ADVAN Sport V107 tyres - Yokohama</title>'
            '<link rel="canonical" href="' + yokohama.URL + '"></head><body>'
            '<table><thead><tr>' + headers + '</tr></thead><tbody>' + body + '</tbody></table></body></html>')


def test_fields_preserve_ambiguous_markings_and_manufacturer_identity():
    first, second = yokohama.parse_html(document(), {})
    assert first['size'] == '225/40ZR18' and first['load_index'] == '92' and first['speed_rating'] == 'Y'
    assert second['hl'] is True and second['speed_rating'] == '(Y)' and second['size'] == '295/30ZR21'
    assert first['hl'] is None
    for value in (first, second):
        assert value['brand'] == 'Yokohama' and value['region'] == 'EU'
        assert all(value[key] is None for key in ('manufacturer_product_code', 'xl', 'run_flat', 'oe_mark'))
        assert VariantInput.model_validate(value).identity_key('yokohama-eu', 'query', 0)[1] == 'source_scoped'
        assert all('facts.' + key in value['facts']['evidence_spans']
                   for key in value['facts'] if key != 'evidence_spans')
    assert first['facts']['source_load_marking'] == 'XL/RF'
    assert first['facts']['source_oe_info'] == 'BMW'
    assert first['facts']['eu_fuel_class'] == 'D' and first['facts']['eu_wet_grip'] == 'A'
    assert first['facts']['eu_external_noise_db'] == 71 and first['facts']['eu_noise_class'] == 'B'
    assert first['facts']['eprel_id'] == '123456'
    assert first['facts']['evidence_spans']['facts.eprel_id'] == '(//table)[1]/tbody/tr[1]/td[10]'


def test_geometry_filter_preserves_zr_and_unknown_values():
    value = yokohama.parse_html(document(), {'model': 'advan sport v107', 'size': '225/40R18'})
    assert len(value) == 1 and value[0]['size'] == '225/40ZR18'
    assert yokohama.parse_html(document(), {'model': 'other'}) == []
    assert yokohama.parse_html(document(), {'size': 'invalid'}) == []
    body = document().replace('<td>D</td><td>A</td><td>71DB/B</td>', '<td>-</td><td>-</td><td>-</td>')
    value = yokohama.parse_html(body, {})[0]
    assert all(field not in value['facts'] for field in ('eu_fuel_class', 'eu_wet_grip', 'eu_external_noise_db', 'eu_noise_class'))


@pytest.mark.parametrize('before,after', [
    ('Series</th>', 'Other</th>'),
    ('fuel-efficiency-icon-header', 'wet-grip-icon-header'),
    ('tyres - Yokohama</title>', 'tires - Yokohama</title>'),
    (yokohama.URL, yokohama.URL + '?region=US'),
    ('225/40ZR18 (92Y)', '225/40ZR18 (92I)'),
    ('<td>40</td>', '<td>45</td>'),
    ('<td>XL/RF</td>', '<td>XL</td>'),
    ('<td>D</td>', '<td>F</td>'),
    ('71DB/B', '71dBA/B'),
    ('https://eprel.ec.europa.eu/qr/123456', 'https://example.invalid/qr/123456'),
    ('/qr/123456', '/qr/123457'),
    ('<td>BMW</td>', '<td colspan="2">BMW</td>'),
    ('<td>BMW</td>', '<td><script>unsafe()</script>BMW</td>'),
    ('</tbody>', ''),
])
def test_layout_or_unmatched_row_drift_rejects_whole_document(before, after):
    with pytest.raises(ValueError, match='^parser_schema_changed$'):
        yokohama.parse_html(document().replace(before, after), {'size': '295/30R21'})


def test_empty_duplicate_and_oversized_tables_fail():
    row = ('40', '225/40ZR18 (92Y)', 'XL/RF', '-', 'D', 'A', '71DB/B', '-', '-', '123456')
    for rows in ([], [row, row], [row] * 501):
        with pytest.raises(ValueError, match='^parser_schema_changed$'):
            yokohama.parse_html(document(rows), {})


def test_fixed_source_and_actual_isolated_parser():
    from tire_api.adapters import registry
    from tire_api import parser_runtime
    assert registry.query_url({'model': yokohama.MODEL}, 'yokohama-eu') == yokohama.URL
    assert registry.permitted_path(yokohama.URL, 'yokohama-eu')
    for url in (yokohama.URL + '?x=1', yokohama.URL + '#x', yokohama.URL.replace('https:', 'http:'),
                yokohama.URL.replace('www.yokohama.eu', 'example.invalid')):
        assert not registry.permitted_path(url, 'yokohama-eu')
    descriptor = parser_runtime.current_parser('yokohama-eu')
    result = asyncio.run(parser_runtime.parse_isolated('yokohama-eu', document(), {},
        descriptor['parser_version'], descriptor['parser_digest']))
    assert result['payload'] == yokohama.parse_html(document(), {})
    assert result['receipt']['reaped'] and result['receipt']['exit_code'] == 0


def test_old_fifteen_source_bundle_executes_after_new_install(tmp_path, monkeypatch):
    from tire_api import parser_bundles as bundles, parser_runtime
    from test_parser_bundles import execute_bundle, pre_yokohama_install, trusted_copy
    source = trusted_copy(tmp_path, monkeypatch)
    catalog = parser_runtime.source_catalog()
    pre_yokohama_install(source)
    with monkeypatch.context() as previous:
        previous.setattr(parser_runtime, 'source_catalog', lambda: {
            key: value for key, value in catalog.items() if key in bundles._SAFETY_GATE_SOURCES})
        old = bundles.seal_deployed_bundle()
    trusted_copy(tmp_path, monkeypatch)
    current = bundles.seal_deployed_bundle()
    assert set(old['parsers']) == set(bundles._SAFETY_GATE_SOURCES)
    assert set(current['parsers']) == set(bundles._DUNLOP_SOURCES)
    assert 'adapters/yokohama.py' not in old['files']
    result = asyncio.run(execute_bundle(old))
    assert result['payload'] and result['receipt']['exit_code'] == 0 and result['receipt']['reaped']


def test_source_telemetry_is_attributed_without_raw_content():
    from tire_api.adapters.transport import SafeHttpClient
    from tire_api.telemetry import TelemetryRuntime, observe
    from test_adapters import FakeResponse, FakeSession
    runtime = TelemetryRuntime('tire-test', logs_enabled=False)
    client = SafeHttpClient(frozenset({'www.yokohama.eu'}))
    client.session = FakeSession([FakeResponse(200, chunks=[b'synthetic'])])
    try:
        with runtime.scope(), observe('source.query', component='crawler', source='yokohama-eu'):
            asyncio.run(client.get(yokohama.URL))
        spans = runtime.finished_spans()
        assert [span['name'] for span in spans] == ['source.http', 'source.query']
        assert all(span['attributes']['source'] == 'yokohama-eu' for span in spans)
        assert 'synthetic' not in str(spans) and 'www.yokohama.eu' not in str(spans)
    finally:
        runtime.shutdown()


@pytest.mark.parametrize('source,expected', [
    ('yokohama-eu', 'yokohama-eu'), ('bridgestone-jp', 'bridgestone-jp'),
    ('continental-cn', 'continental-cn'), ('goodyear-sg', 'goodyear-sg'),
    ('private.example/path?token=SECRET', 'unknown'),
])
def test_normal_query_entry_uses_shared_bounded_source_taxonomy(monkeypatch, source, expected):
    from tire_api.domain import LiveQueryRequest
    from tire_api.service import QueryService
    from tire_api.telemetry import TelemetryRuntime

    async def result(*args, **kwargs):
        return {'data_state': 'live'}

    monkeypatch.setattr(QueryService, '_execute', result)
    runtime = TelemetryRuntime('tire-test', logs_enabled=False)
    try:
        with runtime.scope():
            asyncio.run(QueryService(None, None).execute(source, LiveQueryRequest(query={'model': yokohama.MODEL}), 'synthetic'))
        span, = runtime.finished_spans()
        assert span['attributes']['source'] == expected
        assert 'SECRET' not in str(span)
    finally:
        runtime.shutdown()
