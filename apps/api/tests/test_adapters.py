import asyncio
import socket
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import pytest

from tire_api.adapters import registry
from tire_api.adapters.transport import (
    PublicResolver, SafeHttpClient, SourceAccessError, validate_public_ip, validate_url,
)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.2.3.4", "172.16.0.1", "192.168.0.1",
    "169.254.169.254", "0.0.0.0", "100.64.0.1", "224.0.0.1", "::1", "fe80::1",
    "fc00::1", "::ffff:127.0.0.1", "2002:7f00:1::", "not-an-ip"])
def test_non_public_ips_rejected(ip):
    with pytest.raises(SourceAccessError):
        validate_public_ip(ip)


@pytest.mark.parametrize("url", ["http://www.michelinman.com/", "https://evil.test/",
    "https://www.michelinman.com.evil.test/", "https://www.michelinman.com@evil.test/",
    "https://user@www.michelinman.com/", "https://www.michelinman.com:444/",
    "https://www.michelinman.com/#secret", "https://127.0.0.1/", "file:///etc/passwd"])
def test_unsafe_urls_rejected(url):
    with pytest.raises(SourceAccessError):
        validate_url(url, frozenset({"www.michelinman.com"}))


def test_public_addresses_and_pinned_resolver():
    validate_public_ip("1.1.1.1")
    async def run():
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))]
        loop = asyncio.get_running_loop()
        with patch.object(loop, "getaddrinfo", AsyncMock(return_value=records)):
            result = await PublicResolver(frozenset({"www.michelinman.com"})).resolve("www.michelinman.com", 443)
        assert result[0]["host"] == "1.1.1.1"
        assert result[0]["hostname"] == "www.michelinman.com"
    asyncio.run(run())


def test_mixed_public_and_private_dns_rejected_entirely():
    async def run():
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ["1.1.1.1", "127.0.0.1"]]
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=records)):
            with pytest.raises(SourceAccessError, match="non_public"):
                await PublicResolver(frozenset({"www.michelinman.com"})).resolve("www.michelinman.com", 443)
    asyncio.run(run())


def test_user_cannot_control_host_or_model_path():
    assert registry.query_url({"model": "PSEV"}).endswith("/michelin-pilot-sport-ev")
    assert registry.query_url({"model": "PS4S"}).endswith("/michelin-pilot-sport-4-s")
    for value in ["https://evil.test", "../../metadata", "Pilot Sport EV?sku=1"]:
        with pytest.raises(SourceAccessError):
            registry.query_url({"model": value})
    assert not registry.permitted_path("https://www.michelinman.com/api/products")
    assert not registry.permitted_path(registry.query_url({}) + "?tyreSize=20")


def test_pirelli_metadata_and_fixed_size_url_preserve_other_source_defaults(monkeypatch):
    monkeypatch.setenv('TI_DISABLED_SOURCES', '')
    rows = {row['id']: row for row in registry.sources()}
    assert rows['pirelli-us']['requires_size'] is True
    assert rows['pirelli-us']['supported_models'] == ['P ZERO (PZ4)']
    assert rows['michelin-us']['requires_size'] is False
    expected = 'https://www.pirelli.com/tires/en-us/car/catalog/product/new-p-zero/265_40-r20'
    for query in ({'size': '265/40R20'}, {'model': 'p zero (pz4)', 'size': '265/40ZR20'}):
        assert registry.query_url(query, 'pirelli-us') == expected
    assert registry.permitted_path(expected, 'pirelli-us')
    assert registry.query_url({'model': 'PSEV'}) == rows['michelin-us']['product_page_urls']['Pilot Sport EV']


@pytest.mark.parametrize('suffix', ['', '/sheet/details/2524000', '/265_40-r20?ipcode=2524000',
    '/265_40-r20?ipCode=2524000', '/265_40-r20?product=1', '/265_40-r20#details',
    '/invalid', '/../../265_40-r20'])
def test_pirelli_registry_allows_only_reviewed_dimension_pages(suffix):
    assert not registry.permitted_path('https://www.pirelli.com/tires/en-us/car/catalog/product/new-p-zero' + suffix,
                                       'pirelli-us')


@pytest.mark.parametrize('query,reason', [
    ({'model': 'P ZERO (PZ4)'}, 'source_size_required'),
    ({'model': 'P ZERO (PZ4)', 'size': ''}, 'source_size_required'),
    ({'model': 'P ZERO', 'size': '265/40R20'}, 'unsupported_model'),
    ({'model': 'P ZERO (PZ4)', 'size': '265/40R20?ipcode=2524000'}, 'invalid_size'),
])
@pytest.mark.parametrize('state_kind', ['empty', 'cooldown', 'circuit_open', 'busy'])
def test_pirelli_bad_query_never_opens_network_or_child_or_trips_source_circuit(monkeypatch, query, reason, state_kind):
    monkeypatch.setenv('TI_DISABLED_SOURCES', '')
    state = {'last': 0.0, 'failures': 0, 'until': 0, 'busy': False, 'interval': 2.0}
    if state_kind == 'cooldown':
        state['last'] = 99.0
    elif state_kind == 'circuit_open':
        state.update(failures=3, until=101.0)
    elif state_kind == 'busy':
        state['busy'] = True
    states = {} if state_kind == 'empty' else {registry.SPECS['pirelli-us'].origin: state}
    monkeypatch.setattr(registry, '_states', states)
    monkeypatch.setattr(registry, 'time', SimpleNamespace(monotonic=lambda: 100.0))
    monkeypatch.setattr(registry, '_robots', {})
    monkeypatch.setattr(registry, '_robots_requests', {})
    before = {origin: dict(value) for origin, value in states.items()}
    monkeypatch.setattr(registry, 'current_parser', lambda source: {
        'source_id': source, 'target_kind': 'tire', 'parser_version': 'safe-fixture@1', 'parser_digest': 'a' * 64})
    def forbidden(*_args, **_kwargs):
        pytest.fail('invalid dimension query must stop before opening the transport or parser')
    monkeypatch.setattr(registry, 'SafeHttpClient', forbidden)
    monkeypatch.setattr(registry, 'parse_isolated', forbidden)
    with pytest.raises(SourceAccessError, match='^' + reason + '$'):
        registry.query_url(query, 'pirelli-us')
    for _ in range(4):
        result = asyncio.run(registry.fetch('pirelli-us', query))
        assert result['status'] == 'unavailable' and result['reason'] == reason
    assert registry._states == before and registry._robots == {} and registry._robots_requests == {}


def test_disabled_unimplemented_sources_never_fetch(monkeypatch):
    monkeypatch.setenv("TI_DISABLED_SOURCES", "michelin-us")
    for source, reason in [("michelin-us", "disabled"), ("eprel", "configuration_required"),
                           ("evil", "source_not_found")]:
        assert asyncio.run(registry.fetch(source, {})) == {"status": "unavailable", "reason": reason}


class FakeResponse:
    def __init__(self, status=200, headers=None, chunks=()):
        self.status = status
        self.headers = headers or {"Content-Type": "text/html"}
        self.content_length = None
        self.charset = "utf-8"
        self.url = registry.query_url({})
        self.content = self
        self.chunks = chunks

    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    async def iter_chunked(self, _):
        for chunk in self.chunks: yield chunk


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def get(self, *_, **__):
        self.calls += 1
        return next(self.responses)

    def post(self, *_, **__):
        self.calls += 1
        return next(self.responses)


def test_binary_transport_preserves_non_utf8_bytes_with_same_bounds():
    async def run():
        payload = b'%PDF-1.7\n\xff\x00\xfe'
        client = SafeHttpClient(frozenset({"www.michelinman.com"}))
        client.session = FakeSession([FakeResponse(headers={"Content-Type": "application/pdf"}, chunks=[payload])])
        result = await client.get_bytes(registry.query_url({}), allowed_types=('application/pdf',))
        assert result.body == payload and result.content_type == 'application/pdf'
        client.session = FakeSession([FakeResponse(headers={"Content-Type": "application/pdf"}, chunks=[payload])])
        with pytest.raises(SourceAccessError, match='response_too_large'):
            await client.get_bytes(registry.query_url({}), allowed_types=('application/pdf',), max_bytes=3)
        client.session = FakeSession([FakeResponse(302, {'Location': 'https://127.0.0.1/file.pdf'})])
        with pytest.raises(SourceAccessError, match='url_not_allowed'):
            await client.get_bytes(registry.query_url({}), allowed_types=('application/pdf',))
    asyncio.run(run())


def test_redirect_to_private_or_unapproved_host_never_requested():
    async def run():
        client = SafeHttpClient(frozenset({"www.michelinman.com"}))
        client.session = FakeSession([FakeResponse(302, {"Location": "https://127.0.0.1/"})])
        with pytest.raises(SourceAccessError, match="url_not_allowed"):
            await client.get(registry.query_url({}))
        assert client.session.calls == 1
    asyncio.run(run())


@pytest.mark.parametrize("response,limit,reason", [
    (FakeResponse(headers={"Content-Type": "application/octet-stream"}), 100, "unsupported_content_type"),
    (FakeResponse(chunks=(b"123456", b"789012")), 10, "response_too_large"),
    (FakeResponse(304), 100, "unexpected_304"),
])
def test_bounded_response_and_validator_requirement(response, limit, reason):
    async def run():
        client = SafeHttpClient(frozenset({"www.michelinman.com"}))
        client.session = FakeSession([response])
        with pytest.raises(SourceAccessError, match=reason):
            await client.get(registry.query_url({}), max_bytes=limit)
    asyncio.run(run())


def test_post_catalog_does_not_follow_redirect_or_relax_mime():
    async def run():
        client = SafeHttpClient(frozenset({"www.michelinman.com"}))
        client.session = FakeSession([FakeResponse(307, {"Location": registry.query_url({})})])
        with pytest.raises(SourceAccessError, match="post_redirect_not_allowed"):
            await client.post(registry.query_url({}), json_body=[{}], allowed_types=("application/json",))
        assert client.session.calls == 1
        client.session = FakeSession([FakeResponse(headers={"Content-Type": "text/html"})])
        with pytest.raises(SourceAccessError, match="unsupported_content_type"):
            await client.post(registry.query_url({}), json_body=[{}], allowed_types=("application/json",))
    asyncio.run(run())


def test_absent_robots_exception_does_not_allow_missing_product():
    async def run():
        client = SafeHttpClient(frozenset({"www.michelinman.com"}))
        client.session = FakeSession([FakeResponse(404), FakeResponse(404)])
        result = await client.get("https://www.michelinman.com/robots.txt", allowed_statuses=(200, 404, 410))
        assert result.status == 404 and result.body == ""
        with pytest.raises(SourceAccessError, match="upstream_http_404"):
            await client.get(registry.query_url({}))
    asyncio.run(run())


@pytest.mark.parametrize("failure", [SourceAccessError("upstream_http_403"), TimeoutError()])
def test_failed_robots_request_keeps_network_budget_without_postponing_retry(monkeypatch, failure):
    """Repeated UI retries must not hammer an uncached, failing robots endpoint."""
    clock = [0.0]
    calls = []

    class RobotsFailureClient:
        def __init__(self, *_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

        async def get(self, url, **_):
            calls.append((clock[0], url))
            raise failure

    monkeypatch.setenv("TI_DISABLED_SOURCES", "")
    monkeypatch.setattr(registry, "SafeHttpClient", RobotsFailureClient)
    monkeypatch.setattr(registry, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(registry, "_states", {})
    monkeypatch.setattr(registry, "_robots", {})
    monkeypatch.setattr(registry, "_robots_requests", {}, raising=False)

    async def run():
        first = await registry.fetch("michelin-us", {"model": "PSEV"})
        assert first["status"] == "unavailable"
        for instant in (0.1, 0.5, 1.9):
            clock[0] = instant
            limited = await registry.fetch("michelin-us", {"model": "PSEV"})
            assert limited["reason"] == "source_rate_limited"
        assert len(calls) == 1
        clock[0] = 2.0
        retry = await registry.fetch("michelin-us", {"model": "PSEV"})
        assert retry["reason"] == first["reason"]
        assert [instant for instant, _ in calls] == [0.0, 2.0]
        assert all(url.endswith("/robots.txt") for _, url in calls)

    asyncio.run(run())
