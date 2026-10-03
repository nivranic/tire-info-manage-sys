"""Synthetic SafeHttp boundaries; never contacts a source or runs a Parser."""
import asyncio
from types import SimpleNamespace

import aiohttp
from fastapi.testclient import TestClient
import pytest

from tire_api.adapters import registry as builtins, xiaomi
from tire_api.adapters.transport import SourceAccessError
from tire_api.captures import CaptureWriteError
from tire_api.main import create_app
from tire_api.query_fallback_policies import QueryFallbackUse
from test_query_fallback_policies49 import (FourDomainRegistry, NormalizedVehicleFixture, allow, count, scope)


@pytest.fixture
def transport(monkeypatch):
    state = {'error': None, 'hang': False, 'posts': 0, 'parser_calls': 0}
    policy = SimpleNamespace(can_fetch=lambda _url: True, minimum_interval=0)
    monkeypatch.delenv('TI_DISABLED_SOURCES', raising=False)
    monkeypatch.setattr(xiaomi, '_busy', False)
    monkeypatch.setattr(xiaomi, '_last_fetch', -float('inf'))
    monkeypatch.setattr(xiaomi, '_robots', {host: (xiaomi.time.monotonic(), policy)
                                         for host in (xiaomi.HOST, 'www.xiaomiev.com')})
    monkeypatch.setattr(xiaomi, 'supports_parser_deployments', False)
    descriptor = {'parser_version': 'synthetic-vehicle@1', 'parser_digest': 'b' * 64}
    monkeypatch.setattr(xiaomi, 'current_parser', lambda _source: descriptor)
    monkeypatch.setattr(builtins, 'pin_parser_selection', lambda *_args, **_kw:
                        (descriptor, {'parser_version': descriptor['parser_version']}, {}))
    async def no_parser(*_args, **_kwargs):
        state['parser_calls'] += 1
        pytest.fail('this boundary must not enter a Parser')
    monkeypatch.setattr(xiaomi, 'parse_isolated', no_parser)
    class Client:
        def __init__(self, _hosts):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            pass
        async def get(self, *_args, **_kwargs):
            pytest.fail('fresh cached robots must not fetch')
        async def post(self, url, **_kwargs):
            state['posts'] += 1
            if state['hang']:
                await asyncio.sleep(1)
            if state['error'] is not None:
                raise state['error']
            return SimpleNamespace(url=url, body='synthetic already fetched body', content_type='application/json')
    monkeypatch.setattr(xiaomi, 'SafeHttpClient', Client)
    return state


@pytest.mark.parametrize('error,cause', [(TimeoutError(), 'upstream_timeout'),
    (aiohttp.ClientConnectionError(), 'upstream_network_error'), (OSError(), 'upstream_network_error'),
    (SourceAccessError('upstream_http_403'), None), (ValueError('synthetic transport schema'), None)])
def test_only_exact_safe_http_failures_classify_a_precise_cause(transport, error, cause):
    transport['error'] = error
    result = asyncio.run(xiaomi.fetch(xiaomi.CURRENT_ID))
    assert result.get('fallback_failure_reason') == cause
    if cause is not None:
        assert result['reason'] == 'vehicle_network_unavailable'
    assert transport['posts'] == 1 and transport['parser_calls'] == 0


def test_asyncio_deadline_inside_http_await_classifies_timeout(transport, monkeypatch):
    transport['hang'] = True
    monkeypatch.setattr(xiaomi, 'asyncio', SimpleNamespace(timeout=lambda _seconds: asyncio.timeout(.01),
                                                        CancelledError=asyncio.CancelledError))
    result = asyncio.run(xiaomi.fetch(xiaomi.CURRENT_ID))
    assert result['reason'] == 'vehicle_network_unavailable'
    assert result['fallback_failure_reason'] == 'upstream_timeout' and transport['parser_calls'] == 0


@pytest.mark.parametrize('stage', ['capture_file', 'capture_write', 'parser_file', 'local_selection_file'])
def test_body_capture_parser_and_local_file_errors_never_gain_network_eligibility(transport, monkeypatch, stage):
    observation = None
    if stage == 'capture_file':
        def observation(_body):
            raise OSError('synthetic local object file failure')
    elif stage == 'capture_write':
        def observation(_body):
            raise CaptureWriteError('synthetic durable capture failure')
    elif stage == 'parser_file':
        async def file_error(*_args, **_kwargs):
            raise OSError('synthetic Parser file failure; no Parser runs')
        monkeypatch.setattr(xiaomi, 'parse_isolated', file_error)
    else:
        def local_error(_source):
            raise OSError('synthetic local selection file failure')
        monkeypatch.setattr(xiaomi, 'current_parser', local_error)
    result = asyncio.run(xiaomi.fetch(xiaomi.CURRENT_ID, on_observation=observation))
    assert result['status'] == 'unavailable' and 'fallback_failure_reason' not in result
    assert transport['posts'] == (0 if stage == 'local_selection_file' else 1)
    assert transport['parser_calls'] == 0


@pytest.mark.parametrize('error,cause', [(TimeoutError(), 'upstream_timeout'),
                                      (aiohttp.ClientConnectionError(), 'upstream_network_error')])
def test_real_transport_failure_metadata_binds_actual_query_and_continuous_receipt(tmp_path, monkeypatch, transport, error, cause):
    for name in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(name, '0')
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    app = create_app('sqlite:///' + (tmp_path / 'private-transport.sqlite').as_posix(), FourDomainRegistry())
    normalized = NormalizedVehicleFixture()
    normalized.payload['vehicle']['id'] = xiaomi.CURRENT_ID
    normalized.candidates = lambda: [{'id': xiaomi.CURRENT_ID, 'status': 'ready'}]
    app.state.vehicle_adapter = normalized
    endpoint = '/v1/vehicles/' + xiaomi.CURRENT_ID + '/live-fitments'
    with TestClient(app) as client:
        original = client.post(endpoint, json={}).json()
        assert original['data_state'] == 'live'
        app.state.vehicle_adapter = xiaomi
        transport['error'] = error
        failed = client.post(endpoint, json={}).json()
        assert failed['reason'] == 'vehicle_network_unavailable' and failed['data_state'] == 'consent_required'
        assert failed['fallback_failure'] == {'scope': 'source_response', 'reason': cause, 'query_id': failed['query_id']}
        selected = scope(source=xiaomi.SOURCE_ID, kind='vehicle_fitments')
        policy = allow(client, selected=selected)
        monkeypatch.setattr(xiaomi, '_last_fetch', -float('inf'))
        response = client.post(endpoint, json={}).json()
        assert response['data_state'] == 'local_snapshot' and response['reason'] == 'vehicle_network_unavailable'
        assert response['fitments'] == original['fitments']
        use = response['fallback_authorization']['use']
        assert use['policy_id'] == policy['id'] and use['reason'] == cause and use['query_id'] == response['query_id']
        assert count(app.state.database, QueryFallbackUse) == 1 and transport['parser_calls'] == 0


def test_legacy_generic_vehicle_failure_cannot_invent_precise_source_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    app = create_app('sqlite:///' + (tmp_path / 'legacy.sqlite').as_posix(), FourDomainRegistry())
    adapter = NormalizedVehicleFixture()
    app.state.vehicle_adapter = adapter
    with TestClient(app) as client:
        endpoint = '/v1/vehicles/synthetic-vehicle/live-fitments'
        client.post(endpoint, json={})
        allow(client, selected=scope(source=xiaomi.SOURCE_ID, kind='vehicle_fitments'))
        async def generic(*_args, **_kwargs):
            return {'status': 'unavailable', 'reason': 'vehicle_network_unavailable'}
        adapter.fetch = generic
        response = client.post(endpoint, json={}).json()
        assert response['data_state'] == 'consent_required' and 'fallback_failure' not in response
        assert count(app.state.database, QueryFallbackUse) == 0


@pytest.mark.parametrize('stage', ['parser_file', 'capture_file', 'capture_write'])
def test_public_successfully_fetched_body_then_local_failure_emits_no_auto_cause(tmp_path, monkeypatch, transport, stage):
    import tire_api.vehicles as service
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    app = create_app('sqlite:///' + (tmp_path / 'post-body.sqlite').as_posix(), FourDomainRegistry())
    normalized = NormalizedVehicleFixture()
    normalized.payload['vehicle']['id'] = xiaomi.CURRENT_ID
    normalized.candidates = lambda: [{'id': xiaomi.CURRENT_ID, 'status': 'ready'}]
    app.state.vehicle_adapter = normalized
    endpoint = '/v1/vehicles/' + xiaomi.CURRENT_ID + '/live-fitments'
    with TestClient(app) as client:
        assert client.post(endpoint, json={}).json()['data_state'] == 'live'
        allow(client, selected=scope(source=xiaomi.SOURCE_ID, kind='vehicle_fitments'))
        app.state.vehicle_adapter = xiaomi
        if stage == 'parser_file':
            async def parser_file(*_args, **_kwargs):
                raise OSError('synthetic local Parser file failure; no Parser runs')
            monkeypatch.setattr(xiaomi, 'parse_isolated', parser_file)
        else:
            def capture_file(_observation):
                error = CaptureWriteError if stage == 'capture_write' else OSError
                raise error('synthetic local capture file failure')
            monkeypatch.setattr(service, 'before_parse_recorder', lambda *_args: capture_file)
        response = client.post(endpoint, json={})
        assert response.status_code == 200, response.text
        failed = response.json()
        assert failed['data_state'] == 'consent_required' and failed['fitments'] == []
        assert 'fallback_failure' not in failed and 'fallback_authorization' not in failed
        assert failed['query_id'] and count(app.state.database, QueryFallbackUse) == 0
        assert transport['posts'] == 1 and transport['parser_calls'] == 0
        assert client.post(endpoint, json={'fallback_failure': {'reason': 'upstream_timeout'}}).status_code == 422
