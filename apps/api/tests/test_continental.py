"""Synthetic examples of the reviewed Chinese public specification response."""
import asyncio
import importlib
import json

import pytest

from tire_api import parser_runtime
from tire_api.domain import VariantInput


def row(**changes):
    value = {'size': '235/45R19', 'level': '95Y', 'load': '', 'protect': 'FR',
             'ems': '', 'silent': '', 'type': 'CAR/SUV', 'pattern': ''}
    return {**value, **changes}


def parse(value=None, query=None):
    adapter = importlib.import_module('tire_api.adapters.continental')
    return adapter.parse_html(json.dumps({'19': [row()]} if value is None else value), query or {})


def test_source_scoped_rows_preserve_unknown_code_and_distinct_silent_versions():
    values = parse({'19': [row(silent='是'), row()]})
    assert len(values) == 2
    assert values[0]['acoustic_technology'] == 'ContiSilent'
    assert values[1]['acoustic_technology'] is None
    for value in values:
        assert (value['brand'], value['model'], value['region']) == ('Continental', 'SportContact SC7', 'CN')
        assert all(value[key] is None for key in ['manufacturer_product_code', 'oe_mark', 'xl', 'hl', 'run_flat'])
        assert not {'gtin', 'product_code_type', 'eprel_id'} & value['facts'].keys()
        assert value['facts']['rim_guard'] is True
        assert value['facts']['service_description'] == '95Y'
        spans = value['facts']['evidence_spans']
        assert all('facts.' + key in spans for key in value['facts'] if key != 'evidence_spans')
    identities = [VariantInput.model_validate(value).identity_key('continental-cn', 'query', index)
                  for index, value in enumerate(values)]
    assert all(scope == 'source_scoped' for _, scope in identities)
    assert len({key for key, _ in identities}) == 2


def test_complete_response_validation_and_r_zr_filtering():
    values = {'19': [row()], '20': [row(size='245/35ZR20', level='95Y', load='XL', protect='')]}
    selected = parse(values, {'model': 'sportcontact sc7', 'size': '245/35R20'})
    assert len(selected) == 1 and selected[0]['size'] == '245/35ZR20'
    assert selected[0]['xl'] is True and selected[0]['facts']['load_id'] == 'XL'
    assert 'rim_guard' not in selected[0]['facts']
    assert selected[0]['facts']['evidence_spans']['size'] == '$["20"][0].size'
    assert parse(values, {'model': 'SportContact 6'}) == []
    assert parse(values, {'size': '225/40R18'}) == []
    assert parse(values, {'size': 'invalid'}) == []


@pytest.mark.parametrize('changes', [
    {'size': 'invalid'}, {'size': '235/45R18'}, {'level': '95FAST'}, {'level': ''},
    {'load': 'SL'}, {'protect': 'yes'}, {'ems': 'SSR'}, {'silent': 'yes'}, {'level': '95I'},
    {'pattern': 'unknown'}, {'type': 'unknown'}, {'silent': None}, {'load': True},
    {'extra': 'unexpected'},
])
def test_unmatched_corrupt_row_rejects_whole_response(changes):
    with pytest.raises(ValueError, match='^parser_schema_changed$'):
        parse({'19': [row(), row(**changes)]}, {'size': '225/40R18'})


@pytest.mark.parametrize('value', [{}, [], {'19': []}, {'019': [row()]},
    {'19': [row(), row()]}, {'19': [None]}, {'19': [row() for _ in range(501)]}])
def test_missing_duplicate_or_unbounded_data_is_rejected(value):
    with pytest.raises(ValueError, match='^parser_schema_changed$'):
        parse(value)


def test_duplicate_json_members_and_incomplete_response_are_rejected():
    adapter = importlib.import_module('tire_api.adapters.continental')
    for body in ['{"19":[],"19":[]}', '{"19":', '<html>challenge</html>',
                 '{"19":[' + json.dumps(row())[:-1] + ',"silent":"是"}]}']:
        with pytest.raises(ValueError, match='^parser_schema_changed$'):
            adapter.parse_html(body, {})


def test_fixed_query_url_and_redirect_allowlist():
    from tire_api.adapters import registry
    adapter = importlib.import_module('tire_api.adapters.continental')
    url = adapter.SOURCE_CONFIG['model_urls']['SportContact SC7']
    assert registry.query_url({}, 'continental-cn') == url
    assert registry.query_url({'model': 'SportContact SC7'}, 'continental-cn') == url
    assert registry.permitted_path(url, 'continental-cn')
    for value in [url + '&extra=1', url.replace('https:', 'http:'),
                  url.replace('SportContact%20SC7', 'SportContact%206'),
                  url.replace('www.continental-tires.cn', 'example.invalid'), url + '#fragment']:
        assert not registry.permitted_path(value, 'continental-cn')
    with pytest.raises(registry.SourceAccessError, match='unsupported_model'):
        registry.query_url({'model': 'SportContact 6'}, 'continental-cn')


def test_reconstructed_twelve_entry_archive_keeps_own_execution(tmp_path, monkeypatch):
    from tire_api import parser_bundles as bundles
    from test_parser_bundles import execute_bundle, pre_continental_install, trusted_copy

    source = trusted_copy(tmp_path, monkeypatch)
    catalog = parser_runtime.source_catalog()
    pre_continental_install(source)
    with monkeypatch.context() as previous:
        previous.setattr(parser_runtime, 'source_catalog', lambda: {
            key: value for key, value in catalog.items() if key in bundles._BRIDGESTONE_SOURCES})
        old = bundles.seal_deployed_bundle()
    assert set(old['parsers']) == set(bundles._BRIDGESTONE_SOURCES)
    assert 'adapters/continental.py' not in old['files']
    trusted_copy(tmp_path, monkeypatch)
    current = bundles.seal_deployed_bundle()
    assert set(current['parsers']) == set(bundles._SAFETY_GATE_SOURCES)
    parsed = asyncio.run(execute_bundle(old))
    assert len(parsed['payload']) == 2
    assert parsed['receipt']['bundle_id'] == old['bundle_id']
    assert parsed['receipt']['exit_code'] == 0 and parsed['receipt']['reaped']


def test_fixed_query_capture_requires_registered_source_url_and_mime():
    from tire_api.adapters.continental import PARSER_VERSION, SOURCE_CONFIG
    from tire_api.captures import validated_observation

    observation = {'url': SOURCE_CONFIG['model_urls']['SportContact SC7'],
                   'body': json.dumps({'19': [row()]}), 'content_type': 'application/json',
                   'parser_version': PARSER_VERSION}
    assert validated_observation(observation, source_id='continental-cn') is not None
    for source_id in [None, 'michelin-cn', 'unknown', {}]:
        assert validated_observation(observation, source_id=source_id) is None
    for url in [observation['url'] + '&extra=1',
                observation['url'].replace('SportContact%20SC7', 'SportContact%206'),
                observation['url'].replace('www.continental-tires.cn', 'example.invalid')]:
        assert validated_observation({**observation, 'url': url}, source_id='continental-cn') is None
    assert validated_observation({**observation, 'content_type': 'text/html'}, source_id='continental-cn') is None


@pytest.mark.parametrize('variation', ['body', 'payload'])
def test_identical_uncoded_response_reuses_evidence_and_changed_input_is_quarantined(tmp_path, monkeypatch, variation):
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from tire_api.adapters import registry
    from tire_api.adapters.robots import RobotsPolicy
    from tire_api.adapters.transport import FetchResult
    from tire_api.db import FactVersion, RawCapture, Snapshot, SourceQuarantine, Verification
    from tire_api.main import create_app

    body = json.dumps({'19': [row(silent='是'), row()]})

    class Transport:
        calls = 0
        def __init__(self, *_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def get(self, url, **_):
            Transport.calls += 1
            text = body + ('\n' if Transport.calls == 3 and variation == 'body' else '')
            return FetchResult(200, url, text, 'application/json', None, None)

    async def robots(*_):
        return RobotsPolicy('', 'TireEvidenceResearch')

    original_parse = registry.parse_isolated

    async def isolated(*args, **kwargs):
        value = await original_parse(*args, **kwargs)
        if Transport.calls == 3 and variation == 'payload':
            value['payload'][0]['facts']['source_note'] = 'controlled altered output'
        return value

    monkeypatch.setattr(registry, 'SafeHttpClient', Transport)
    monkeypatch.setattr(registry, '_robots_policy', robots)
    monkeypatch.setattr(registry, 'parse_isolated', isolated)
    monkeypatch.setattr(registry, '_states', {})
    app = create_app('sqlite:///' + (tmp_path / 'reverify.db').as_posix())
    payload = {'query': {'model': 'SportContact SC7', 'size': '235/45R19'}, 'fallback_policy': 'ask'}
    path = '/v1/sources/continental-cn/live-query'
    with TestClient(app) as client:
        first = client.post(path, json=payload).json()
        assert first['data_state'] == 'live' and len(first['variants']) == 2
        registry._states.clear()
        second = client.post(path, json=payload).json()
        assert second['data_state'] == 'live'
        assert [row['id'] for row in second['variants']] == [row['id'] for row in first['variants']]
        assert second['provenance'][0]['snapshot_id'] == first['provenance'][0]['snapshot_id']
        assert all(row['identity_status'] == 'source_scoped' for row in second['variants'])
        registry._states.clear()
        changed = client.post(path, json=payload).json()
        assert changed['data_state'] == 'consent_required' and changed['reason'] == 'source_quality_quarantined'
        assert changed['variants'] == []
        with app.state.database.sessions() as db:
            for model, expected in [(Snapshot, 1), (FactVersion, 2), (Verification, 2),
                                    (RawCapture, 3), (SourceQuarantine, 1)]:
                assert db.scalar(select(func.count()).select_from(model)) == expected


def test_new_source_executes_in_real_parser_child_and_telemetry_is_attributed():
    from tire_api.adapters import registry
    from tire_api.adapters.transport import SafeHttpClient
    from tire_api.telemetry import TelemetryRuntime, observe
    from test_adapters import FakeResponse, FakeSession

    source = registry.SPECS['continental-cn']
    assert source.region == 'CN' and source.content_types == ('application/json',)
    descriptor = parser_runtime.current_parser(source.id)
    parsed = asyncio.run(parser_runtime.parse_isolated(source.id, json.dumps({'19': [row()]}), {},
        descriptor['parser_version'], descriptor['parser_digest']))
    assert parsed['payload'] == parse()
    assert parsed['receipt']['exit_code'] == 0 and parsed['receipt']['reaped']
    runtime = TelemetryRuntime('tire-test', logs_enabled=False)
    client = SafeHttpClient(frozenset({source.host}))
    client.session = FakeSession([FakeResponse(200, chunks=[b'synthetic'])])
    try:
        with runtime.scope(), observe('source.query', component='crawler', source=source.id):
            asyncio.run(client.get(next(iter(source.model_urls.values()))))
        spans = runtime.finished_spans()
        assert [span['name'] for span in spans] == ['source.http', 'source.query']
        assert all(span['attributes']['source'] == source.id for span in spans)
        assert 'synthetic' not in str(spans) and source.host not in str(spans)
    finally:
        runtime.shutdown()
