"""Adapter contracts for pinned releases, conditional fetches and failure receipts."""
import asyncio
from copy import deepcopy

import pytest

from tire_api.adapters import registry, xiaomi
from tire_api.adapters.robots import RobotsPolicy
from tire_api.adapters.transport import FetchResult, SourceAccessError, USER_AGENT
from tire_api.captures import CaptureWriteError
from tire_api.parser_runtime import ParserRunError


class AdapterHarness:
    def __init__(self, monkeypatch, kind, source='michelin-us'):
        from tire_api import parser_bundles
        self.module = registry if kind == 'tire' else xiaomi
        self.source = source if kind == 'tire' else xiaomi.SOURCE_ID
        self.kind = kind
        self.query = {'model': 'P ZERO (PZ4)', 'size': '265/40R20'} if source == 'pirelli-us' else {}
        self.url = registry.query_url(self.query, self.source) if kind == 'tire' else xiaomi.API_URL
        self.events, self.requests, self.parses, self.observations = [], [], [], []
        self.status, self.network_hook, self.parse_error = 200, None, None
        self.descriptor = {'source_id': self.source, 'target_kind': kind, 'parser_version': 'fixture-parser@1',
                           'parser_digest': 'b' * 64, 'bundle_id': 'a' * 64}
        self.selection = {'source_id': self.source, 'query_run_id': 'query-fixture',
                          'bundle_id': 'a' * 64, 'deployment_revision': 3,
                          'parser_version': 'fixture-parser@1', 'parser_digest': 'b' * 64,
                          'bundle_manifest': {'fixture_bundle': 'a' * 64}}

        def describe(manifest, source):
            self.events.append('descriptor')
            assert source == self.source and manifest['fixture_bundle'] == 'a' * 64
            return deepcopy(self.descriptor)

        def builtin(source):
            self.events.append('builtin_descriptor')
            assert source == self.source
            return deepcopy(self.descriptor)

        async def parse(*args, **kwargs):
            self.events.append('parse')
            self.parses.append((args, deepcopy(kwargs)))
            if self.parse_error:
                raise self.parse_error
            return {'payload': [] if kind == 'tire' else {}, 'receipt': {'run_id': 'child-run', 'reaped': True}}

        owner = self

        class Transport:
            def __init__(self, hosts):
                owner.events.append('network_constructed')
                owner.hosts = hosts

            async def __aenter__(self):
                owner.events.append('network_entered')
                if owner.network_hook:
                    owner.network_hook()
                return self

            async def __aexit__(self, *_):
                pass

            async def get(self, url, **options):
                if url.endswith('/robots.txt'):
                    return FetchResult(200, url, 'User-agent: *\nAllow: /', 'text/plain', None, None)
                owner.requests.append((url, options))
                return FetchResult(owner.status, url, 'source body' if owner.status == 200 else '',
                                   'text/html', 'source-etag', None)

            async def post(self, url, **options):
                owner.requests.append((url, options))
                return FetchResult(200, url, 'source body', 'application/json', None, None)

        async def robots(*_):
            return RobotsPolicy('User-agent: *\nAllow: /', USER_AGENT)

        monkeypatch.setattr(parser_bundles, 'bundle_descriptor', describe)
        monkeypatch.setattr(self.module, 'current_parser', builtin)
        monkeypatch.setattr(self.module, 'parse_isolated', parse)
        monkeypatch.setattr(self.module, 'SafeHttpClient', Transport)
        monkeypatch.setenv('TI_DISABLED_SOURCES', '')
        monkeypatch.setattr(registry, '_states', {})
        monkeypatch.setattr(registry, '_robots_policy', robots)
        monkeypatch.setattr(xiaomi, '_busy', False)
        monkeypatch.setattr(xiaomi, '_last_fetch', -float('inf'))
        monkeypatch.setattr(xiaomi, '_robots', {})
        monkeypatch.setattr(xiaomi, '_robots_requests', {})

    @property
    def identity(self):
        return {'bundle_id': 'a' * 64, 'parser_digest': 'b' * 64, 'deployment_revision': 3}

    def observe(self, observation):
        self.events.append('observation_committed')
        self.observations.append(deepcopy(observation))

    def fetch(self, *, selected=True, cached=None, observe=None):
        options = {'on_observation': observe or self.observe,
                   'parser_selection': self.selection if selected else None}
        request = (registry.fetch(self.source, self.query, cached=cached, **options) if self.kind == 'tire'
                   else xiaomi.fetch(xiaomi.CURRENT_ID, **options))
        return asyncio.run(request)

    def cache(self):
        return {'url': self.url, 'body': 'previous body', 'etag': 'prior-etag',
                'parser_version': 'fixture-parser@1', 'parser_identity': self.identity}


@pytest.fixture(params=[('tire', 'michelin-us'), ('tire', 'pirelli-us'), ('vehicle', xiaomi.SOURCE_ID)],
                ids=['michelin', 'pirelli', 'xiaomi'])
def adapter(monkeypatch, request):
    return AdapterHarness(monkeypatch, *request.param)


def test_selected_release_is_fixed_before_network_and_receipt_before_child(adapter):
    frozen_manifest = deepcopy(adapter.selection['bundle_manifest'])

    def change_deployment():
        adapter.selection.update(bundle_id='c' * 64, parser_digest='d' * 64, deployment_revision=4)
        adapter.selection['bundle_manifest']['fixture_bundle'] = 'c' * 64
        adapter.descriptor.update(bundle_id='c' * 64, parser_digest='d' * 64)

    adapter.network_hook = change_deployment
    result = adapter.fetch()
    assert result['status'] == 'ok' and result['parser_identity'] == adapter.identity
    assert result['parser_version'] == 'fixture-parser@1'
    assert adapter.events.index('descriptor') < adapter.events.index('network_constructed')
    assert adapter.events.count('descriptor') == 1
    assert adapter.events.index('observation_committed') < adapter.events.index('parse')
    args, options = adapter.parses[0]
    assert args[0] == adapter.source and args[3:] == ('fixture-parser@1', 'b' * 64)
    assert options == {'bundle_manifest': frozen_manifest, 'deployment_revision': 3}
    assert adapter.observations[0]['parser_identity'] == adapter.identity
    assert result['parser_receipt'] == {'run_id': 'child-run', 'reaped': True}
    expected_hosts = ({registry.SPECS[adapter.source].host} if adapter.kind == 'tire'
                      else {'www.xiaomiev.com', xiaomi.HOST})
    assert adapter.hosts == expected_hosts


def test_builtin_canary_descriptor_is_selected_once_before_network(adapter):
    adapter.network_hook = lambda: adapter.descriptor.update(parser_digest='e' * 64)
    result = adapter.fetch(selected=False)
    assert result['status'] == 'ok'
    assert result['parser_identity'] == {**adapter.identity, 'deployment_revision': None}
    assert adapter.events.count('builtin_descriptor') == 1
    assert adapter.events.index('builtin_descriptor') < adapter.events.index('network_constructed')
    assert adapter.parses[0][0][4] == 'b' * 64 and adapter.parses[0][1] == {}


@pytest.mark.parametrize('field,value', [
    ('source_id', 'other-source'), ('query_run_id', ''), ('query_run_id', None),
    ('bundle_id', ''), ('bundle_id', 'c' * 64), ('parser_version', 'other-version'),
    ('parser_digest', 'd' * 64), ('deployment_revision', None), ('deployment_revision', True),
    ('deployment_revision', 0), ('bundle_manifest', None),
])
def test_invalid_selection_never_opens_transport_or_runs_child(adapter, field, value):
    adapter.selection[field] = value
    result = adapter.fetch()
    assert result['status'] == 'unavailable'
    assert result['reason'] in {'parser_selection_invalid', 'parser_selection_mismatch'}
    assert 'network_constructed' not in adapter.events
    assert not adapter.parses and not adapter.observations


def test_bundle_verification_failure_has_explicit_reason_without_network(adapter, monkeypatch):
    from tire_api import parser_bundles

    def damaged(*_):
        raise parser_bundles.BundleError('parser_bundle_integrity_failed')

    monkeypatch.setattr(parser_bundles, 'bundle_descriptor', damaged)
    result = adapter.fetch()
    assert result['reason'] == 'parser_bundle_integrity_failed'
    assert not adapter.requests and not adapter.parses and 'network_constructed' not in adapter.events


def test_capture_failure_never_runs_selected_child(adapter):
    def rejected(_):
        raise CaptureWriteError('evidence_capture_failed')

    result = adapter.fetch(observe=rejected)
    assert result['reason'] == 'evidence_capture_failed' and result['parser_identity'] == adapter.identity
    assert not adapter.parses


@pytest.mark.parametrize('code,expected', [
    ('parser_crashed', 'parser_crashed'), ('parser_timeout', 'parser_timeout'),
    ('parser_cancelled', 'parser_cancelled'), ('parser_schema_changed', 'parser_schema_changed'),
    ('parser_isolation_unavailable', 'parser_isolation_unavailable'),
    ('unclassified-private-detail', 'parser_failed'),
])
def test_parser_failure_keeps_selected_identity_and_complete_receipt(adapter, code, expected):
    receipt = {'run_id': 'crashed-child', 'reaped': True, 'exit_code': 71, 'bundle_id': 'a' * 64}
    adapter.parse_error = ParserRunError(code, receipt)
    result = adapter.fetch()
    assert result['status'] == 'unavailable' and result['parser_error'] == result['reason'] == expected
    assert result['parser_receipt'] == receipt and result['parser_identity'] == adapter.identity
    assert result['rejected_observation']['parser_identity'] == adapter.identity
    assert result['rejected_observation']['parser_error'] == expected
    assert len(adapter.parses) == 1


@pytest.mark.parametrize('change', ['legacy', 'empty', 'bundle', 'digest', 'revision', 'boolean_revision', 'version'])
def test_mismatched_cache_cannot_send_conditional_headers(monkeypatch, change):
    adapter = AdapterHarness(monkeypatch, 'tire')
    cached = adapter.cache()
    if change == 'legacy':
        del cached['parser_identity']
    elif change == 'empty':
        cached['parser_identity'] = {}
    elif change == 'version':
        cached['parser_version'] = 'different-version'
    else:
        field, value = {'bundle': ('bundle_id', 'c' * 64), 'digest': ('parser_digest', 'd' * 64),
                        'revision': ('deployment_revision', 2), 'boolean_revision': ('deployment_revision', True)}[change]
        cached['parser_identity'][field] = value
        if change == 'boolean_revision':
            adapter.selection['deployment_revision'] = 1
    result = adapter.fetch(cached=cached)
    assert result['status'] == 'ok' and adapter.requests[0][1]['headers'] == {}
    assert len(adapter.parses) == 1


@pytest.mark.parametrize('source', ['michelin-us', 'pirelli-us'])
def test_matching_deployment_304_keeps_identity_without_capture_or_child(monkeypatch, source):
    adapter = AdapterHarness(monkeypatch, 'tire', source)
    adapter.status = 304
    result = adapter.fetch(cached=adapter.cache())
    assert adapter.requests[0][1]['headers'] == {'If-None-Match': 'prior-etag'}
    assert result['status'] == 'not_modified' and result['parser_identity'] == adapter.identity
    assert result['parser_version'] == 'fixture-parser@1'
    assert not adapter.observations and not adapter.parses


def test_pirelli_cache_for_another_dimension_cannot_send_conditional_headers(monkeypatch):
    adapter = AdapterHarness(monkeypatch, 'tire', 'pirelli-us')
    cached = adapter.cache()
    cached['url'] = registry.query_url({'model': 'P ZERO (PZ4)', 'size': '265/40R21'}, 'pirelli-us')
    result = adapter.fetch(cached=cached)
    assert result['status'] == 'ok' and adapter.requests[0][1]['headers'] == {}
    assert adapter.parses[0][0][2] == adapter.query and len(adapter.observations) == 1


def test_builtin_canary_never_reuses_deployed_cache_or_accepts_unsolicited_304(monkeypatch):
    adapter = AdapterHarness(monkeypatch, 'tire')
    adapter.status = 304
    result = adapter.fetch(selected=False, cached=adapter.cache())
    assert adapter.requests[0][1]['headers'] == {}
    assert result['reason'] == 'unexpected_304'
    assert not adapter.observations and not adapter.parses


def test_transport_failure_returns_fixed_identity_and_does_not_reselect(adapter):
    def fail():
        raise SourceAccessError('upstream_http_403')

    adapter.network_hook = fail
    result = adapter.fetch()
    assert result['reason'] == 'upstream_http_403' and result['parser_identity'] == adapter.identity
    assert adapter.events.count('descriptor') == 1 and not adapter.parses


def test_deployment_support_is_advertised():
    assert registry.supports_parser_deployments is True and xiaomi.supports_parser_deployments is True
