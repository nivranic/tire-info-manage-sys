"""Independent R72 adversarial review. All material, DNS and HTTP are synthetic.

Tests execute production policy/transport/API logic. In-memory HTTP responses
replace the network boundary; they do not establish a real publisher or license.
"""
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import aiohttp
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, text
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError
from multidict import CIMultiDict

from tire_api import material_source_policy as policy_module
from tire_api import material_source_transport as transport_module
from tire_api.adapters.transport import PublicResolver, SourceAccessError
from tire_api.db import EvidenceDocument, EvidenceObject, User, UserSession
from tire_api.domain import digest
from tire_api.main import create_app
from tire_api.material_source_policy import MaterialPolicyError, canonical_policy, load_policies
from tire_api.material_source_transport import MaterialSourceTransport, MaterialTransportError
from tire_api.source_material_models import SourceMaterialOutcome, SourceMaterialRequest


PRIVATE = Path(os.environ['R72_REVIEW_STORAGE_ROOT'])
PASSWORD = secrets.token_urlsafe(20)
BASE = '/v1/source-materials'
PDF = b'%PDF-1.7\nSYNTHETIC ORIGINAL - NO PROFESSIONAL CLAIM\n\xff\x00\xfe\r\n%%EOF\n'
ROBOTS = b'User-agent: *\nAllow: /\n'
POLICY = {'policy_id': 'review-synthetic', 'title': 'Independent synthetic original',
    'publisher': 'Project fixture authors', 'edition': None, 'published_at': None,
    'source_reference_url': 'https://example.com/reference',
    'download_url': 'https://example.com/original.pdf', 'redirect_urls': [],
    'rights': {'rights_holder': 'Project fixture authors', 'basis': 'Project-authored synthetic fixture only',
        'license_url': None, 'store_original': True, 'workspace_reopen': True,
        'quote_identifiers': True, 'provider_use': False, 'export': False}}


def run(coroutine):
    return asyncio.run(coroutine)


def passed(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def policy_file(tmp_path, monkeypatch, *, items=None, raw=None):
    path = tmp_path / 'private-policies.json'
    path.write_bytes(raw if raw is not None else json.dumps({
        'schema': 'source-material-policies@1', 'policies': items if items is not None else [POLICY]}).encode())
    monkeypatch.setenv('TI_SOURCE_MATERIAL_POLICIES_FILE', str(path))
    return path


@pytest.mark.parametrize('url', [
    'http://example.com/a.pdf', 'https://127.0.0.1/a.pdf', 'https://[::1]/a.pdf',
    'https://2130706433/a.pdf', 'https://localhost/a.pdf', 'https://host.local/a.pdf',
    'https://host.internal/a.pdf', 'https://EXAMPLE.com/a.pdf', 'https://example.com./a.pdf',
    'https://example.com:444/a.pdf', 'https://user:password@example.com/a.pdf',
    'https://example.com/a.pdf?token=do-not-return', 'https://example.com/a.pdf?',
    'https://example.com/a.pdf#fragment', 'https://example.com/a.pdf#',
    'https://example.com/a\\b.pdf', 'https://example.com/a\nb.pdf',
    'https://example.com/../a.pdf', 'https://example.com/./a.pdf',
    'https://example%2ecom/a.pdf', 'https://例子.example/a.pdf'])
def test_configuration_rejects_nonexact_urls(tmp_path, monkeypatch, url):
    row = {**deepcopy(POLICY), 'download_url': url}
    policy_file(tmp_path, monkeypatch, items=[row])
    with pytest.raises(MaterialPolicyError, match='^source_material_policy_invalid$'):
        load_policies()


@pytest.mark.parametrize('change', [
    {'extra': 'caller-selected'}, {'policy_id': 'bad/id'}, {'policy_id': ''},
    {'title': 'x' * 161}, {'publisher': '\tunsafe'}, {'edition': 'x' * 81},
    {'published_at': '2026-02-30'}, {'redirect_urls': [POLICY['download_url']]},
    {'redirect_urls': ['https://example.com/b.pdf'] * 2},
    {'redirect_urls': [f'https://example.com/{n}.pdf' for n in range(4)]},
    {'rights': {**POLICY['rights'], 'store_original': 1}},
    {'rights': {**POLICY['rights'], 'workspace_reopen': False}},
    {'rights': {**POLICY['rights'], 'provider_use': True}},
    {'rights': {**POLICY['rights'], 'export': True}},
    {'rights': {**POLICY['rights'], 'quote_identifiers': 'true'}},
    {'rights': {**POLICY['rights'], 'additional_permission': True}},
])
def test_configuration_rejects_unsupported_types_rights_and_bounds(tmp_path, monkeypatch, change):
    policy_file(tmp_path, monkeypatch, items=[{**deepcopy(POLICY), **change}])
    with pytest.raises(MaterialPolicyError):
        load_policies()


@pytest.mark.parametrize('raw', [
    b'{"schema":"source-material-policies@1","schema":"source-material-policies@1","policies":[]}',
    b'{"schema":"source-material-policies@2","policies":[]}',
    b'{"schema":"source-material-policies@1","policies":{},"unknown":1}',
    b'\xff', b'{' + b' ' * (256 * 1024), b'[]'],
    ids=['duplicate-key', 'schema', 'shape', 'invalid-utf8', 'over-file-bound', 'not-object'])
def test_configuration_file_failures_have_fixed_safe_error(tmp_path, monkeypatch, raw):
    path = policy_file(tmp_path, monkeypatch, raw=raw)
    with pytest.raises(MaterialPolicyError) as caught:
        load_policies()
    assert str(caught.value) == 'source_material_policy_invalid'
    assert str(path) not in str(caught.value)


def test_catalog_bounds_snapshot_and_no_external_license_fetch(tmp_path, monkeypatch):
    policy_file(tmp_path, monkeypatch, items=[POLICY, POLICY])
    with pytest.raises(MaterialPolicyError):
        load_policies()
    policy_file(tmp_path, monkeypatch, items=[{**POLICY, 'policy_id': f'id-{n}'} for n in range(17)])
    with pytest.raises(MaterialPolicyError):
        load_policies()
    path = policy_file(tmp_path, monkeypatch)
    catalog = load_policies()
    item = catalog.items()[0]
    item['rights']['provider_use'] = True
    item['redirect_urls'].append('https://evil.example/stolen.pdf')
    assert catalog.get(POLICY['policy_id']) == canonical_policy(POLICY)
    path.write_text('invalid after snapshot', encoding='utf-8')
    assert catalog.get(POLICY['policy_id']) == canonical_policy(POLICY)
    changed = deepcopy(POLICY)
    changed['rights']['basis'] += ' Additional declared restriction.'
    assert canonical_policy(changed)['policy_fingerprint'] != canonical_policy(POLICY)['policy_fingerprint']


class MemoryResponse:
    def __init__(self, status=200, body=PDF, content_type='application/pdf', *, headers=None,
                 length='auto', chunks=None, failure=None):
        self.status, self.body = status, body
        self.headers = {'Content-Type': content_type, **(headers or {})}
        self.content_length = len(body) if length == 'auto' else length
        self.chunks = chunks if chunks is not None else [body]
        self.failure = failure
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def iter_chunked(self, _size):
        for chunk in self.chunks:
            yield chunk
        if self.failure is not None:
            raise self.failure


def robots(status=200, body=ROBOTS, **kwargs):
    return MemoryResponse(status, body, 'text/plain', **kwargs)


class MemoryHTTP:
    def __init__(self, monkeypatch, responses):
        self.responses, self.requests = list(responses), []
        self.session_options = self.connector_options = None
        self.session = None
        self.clock = 100.0
        owner = self
        class Session:
            _retry_connection = True
            def __init__(self, **kwargs):
                owner.session_options, owner.session = kwargs, self
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_args):
                return None
            def get(self, url, **kwargs):
                owner.requests.append((str(url), kwargs))
                assert owner.responses, 'Unexpected additional HTTP request'
                response = owner.responses.pop(0)
                if isinstance(response, BaseException):
                    raise response
                return response
        def connector(**kwargs):
            owner.connector_options = kwargs
            return SimpleNamespace()
        async def sleep(delay):
            owner.clock += delay
        monkeypatch.setattr(transport_module.aiohttp, 'ClientSession', Session)
        monkeypatch.setattr(transport_module.aiohttp, 'TCPConnector', connector)
        monkeypatch.setattr(transport_module.time, 'monotonic', lambda: owner.clock)
        monkeypatch.setattr(transport_module.asyncio, 'sleep', sleep)


def transport_fetch(monkeypatch, responses, policy=None):
    http = MemoryHTTP(monkeypatch, responses)
    result = run(MaterialSourceTransport().fetch(canonical_policy(policy or POLICY)))
    return result, http


def test_production_transport_preserves_original_bytes_and_safe_session(monkeypatch):
    result, http = transport_fetch(monkeypatch, [robots(), MemoryResponse(headers={'Content-Type': 'application/pdf; charset=utf-16'})])
    assert result['body'] == PDF
    assert result['initial_url'] == result['final_url'] == POLICY['download_url']
    assert result['robot_objects'] == [{'raw_hash': hashlib.sha256(ROBOTS).hexdigest(), 'body': ROBOTS}]
    assert result['robots'][0]['raw_hash'] == hashlib.sha256(ROBOTS).hexdigest()
    options = http.session_options
    assert options['trust_env'] is False and options['auto_decompress'] is False
    assert options['headers']['Accept-Encoding'] == 'identity'
    assert isinstance(options['cookie_jar'], aiohttp.DummyCookieJar)
    assert options['timeout'].connect == 4 and options['timeout'].sock_read == 8
    assert http.connector_options['use_dns_cache'] is False
    resolver = http.connector_options['resolver']
    assert isinstance(resolver, PublicResolver) and resolver.allow_loopback is False
    assert resolver.hosts == frozenset({'example.com'})
    assert [kwargs for _, kwargs in http.requests] == [
        {'allow_redirects': False, 'headers': {'Accept': 'text/plain'}}, {'allow_redirects': False}]
    assert [url for url, _ in http.requests] == ['https://example.com/robots.txt', POLICY['download_url']]


@pytest.mark.parametrize('response,code', [
    (MemoryResponse(206), 'source_material_http_rejected'),
    (MemoryResponse(304), 'source_material_http_rejected'),
    (MemoryResponse(500), 'source_material_http_rejected'),
    (MemoryResponse(content_type='text/html'), 'source_material_content_type_rejected'),
    (MemoryResponse(body=b'not a PDF'), 'source_material_pdf_marker_missing'),
    (MemoryResponse(headers={'Content-Encoding': 'gzip'}), 'source_material_encoding_rejected'),
    (MemoryResponse(headers={'Content-Encoding': 'br'}), 'source_material_encoding_rejected'),
    (MemoryResponse(headers={'Content-Encoding': 'identity,gzip'}), 'source_material_encoding_rejected'),
    (MemoryResponse(length=8 * 1024 * 1024 + 1), 'source_material_too_large'),
    (MemoryResponse(length=len(PDF) + 1), 'source_material_incomplete_body'),
    (MemoryResponse(length=None, chunks=[PDF, b'x' * (8 * 1024 * 1024)]), 'source_material_too_large'),
    (MemoryResponse(failure=aiohttp.ClientPayloadError('sensitive body')), 'source_material_network_failed'),
])
def test_transport_rejects_unsafe_or_partial_pdf(monkeypatch, response, code):
    http = MemoryHTTP(monkeypatch, [robots(), response])
    with pytest.raises(MaterialTransportError, match='^' + code + '$'):
        run(MaterialSourceTransport().fetch(canonical_policy(POLICY)))
    assert len(http.requests) == 2


def test_exact_eight_mib_and_identity_encoding_are_accepted(monkeypatch):
    body = PDF + b'\x80' * (8 * 1024 * 1024 - len(PDF))
    result, _ = transport_fetch(monkeypatch, [robots(), MemoryResponse(body=body, headers={'Content-Encoding': 'identity'})])
    assert result['body'] == body and len(result['body']) == 8 * 1024 * 1024


def test_duplicate_encoding_headers_cannot_hide_compression(monkeypatch):
    response = MemoryResponse()
    response.headers = CIMultiDict([('Content-Type', 'application/pdf'),
        ('Content-Encoding', 'identity'), ('Content-Encoding', 'gzip')])
    MemoryHTTP(monkeypatch, [robots(), response])
    with pytest.raises(MaterialTransportError, match='source_material_encoding_rejected'):
        run(MaterialSourceTransport().fetch(canonical_policy(POLICY)))


@pytest.mark.parametrize('response,code', [
    (robots(403), 'source_material_robots_unavailable'),
    (robots(406), 'source_material_robots_unavailable'),
    (robots(429), 'source_material_robots_unavailable'),
    (robots(500), 'source_material_robots_unavailable'),
    (robots(302, headers={'Location': 'https://example.com/other'}), 'source_material_robots_unavailable'),
    (robots(body=b'User-agent: *\nDisallow: /\n'), 'source_material_robots_disallowed'),
    (robots(body=b'\xff'), 'source_material_network_failed'),
    (robots(body=b'x' * (64 * 1024 + 1)), 'source_material_too_large'),
    (robots(headers={'Content-Encoding': 'gzip'}), 'source_material_encoding_rejected'),
])
def test_robots_fail_closed_before_pdf(monkeypatch, response, code):
    http = MemoryHTTP(monkeypatch, [response])
    with pytest.raises(MaterialTransportError, match='^' + code + '$') as error:
        run(MaterialSourceTransport().fetch(canonical_policy(POLICY)))
    assert len(http.requests) == 1
    expected = {'phase': 'robots_http_status', 'http_status': response.status} if code == 'source_material_robots_unavailable' else None
    assert transport_module.robots_failure_diagnostic(error.value) == expected
    assert str(error.value) == code


@pytest.mark.parametrize('status', [404, 410])
def test_missing_robots_receipt_is_distinct_from_observed_body(monkeypatch, status):
    result, _ = transport_fetch(monkeypatch, [robots(status, b''), MemoryResponse()])
    assert result['robots'][0]['status'] == status
    assert result['robots'][0]['raw_hash'] is None and result['robots'][0]['byte_count'] == 0
    assert result['robot_objects'] == []


def test_empty_successful_robots_is_observed_empty_bytes_not_missing(monkeypatch):
    result, _ = transport_fetch(monkeypatch, [robots(200, b''), MemoryResponse()])
    assert result['body'] == PDF
    assert result['robots'][0]['status'] == 200 and result['robots'][0]['byte_count'] == 0
    assert result['robots'][0]['raw_hash'] == hashlib.sha256(b'').hexdigest()
    assert result['robot_objects'] == []


@pytest.mark.parametrize('location', [
    'https://evil.example/a.pdf', '//evil.example/a.pdf',
    'https://example.com/original.pdf?token=secret', 'https://example.com/original.pdf#x',
    'https://user@example.com/original.pdf', 'https://127.0.0.1/a.pdf',
    '/original.pdf', 'https://example.com/a\rb.pdf'])
def test_redirect_never_requests_unconfigured_or_cyclic_destination(monkeypatch, location):
    http = MemoryHTTP(monkeypatch, [robots(), MemoryResponse(302, headers={'Location': location})])
    with pytest.raises(MaterialTransportError):
        run(MaterialSourceTransport().fetch(canonical_policy(POLICY)))
    assert [url for url, _ in http.requests] == ['https://example.com/robots.txt', POLICY['download_url']]


def test_cross_host_redirect_checks_second_robots_before_pdf(monkeypatch):
    second = 'https://cdn.example.org/final.pdf'
    policy = {**deepcopy(POLICY), 'redirect_urls': [second]}
    result, http = transport_fetch(monkeypatch, [robots(), MemoryResponse(302, headers={'Location': second}),
        robots(), MemoryResponse()], policy)
    assert [url for url, _ in http.requests] == ['https://example.com/robots.txt', POLICY['download_url'],
        'https://cdn.example.org/robots.txt', second]
    assert result['final_url'] == second
    assert result['redirects'] == [{'from_url': POLICY['download_url'], 'to_url': second, 'status': 302}]
    assert {entry['target_url'] for entry in result['robots']} == {POLICY['download_url'], second}
    assert [kwargs.get('headers', {}).get('Accept') for _, kwargs in http.requests] == [
        'text/plain', None, 'text/plain', None]


def test_fourth_redirect_and_cycle_are_rejected(monkeypatch):
    chain = [f'https://example.com/{n}.pdf' for n in range(3)]
    responses = []
    for target in chain + [POLICY['download_url']]:
        responses += [robots(), MemoryResponse(302, headers={'Location': target})]
    http = MemoryHTTP(monkeypatch, responses)
    with pytest.raises(MaterialTransportError, match='source_material_redirect_rejected'):
        run(MaterialSourceTransport().fetch(canonical_policy({**POLICY, 'redirect_urls': chain})))
    assert len(http.requests) == 8


@pytest.mark.parametrize('addresses', [
    ['127.0.0.1'], ['10.2.3.4'], ['169.254.169.254'], ['100.64.0.1'], ['0.0.0.0'],
    ['::1'], ['fe80::1'], ['::ffff:8.8.8.8'], ['2002:0808:0808::'], ['2001:0000:4136:e378:8000:63bf:3fff:fdd2'],
    ['8.8.8.8', '127.0.0.1'], []])
def test_real_public_resolver_rejects_entire_mixed_or_nonpublic_answer(monkeypatch, addresses):
    async def exercise():
        loop = asyncio.get_running_loop()
        calls = []
        async def lookup(host, port, **kwargs):
            calls.append((host, port))
            return [(socket.AF_INET6 if ':' in ip else socket.AF_INET, socket.SOCK_STREAM,
                     socket.IPPROTO_TCP, '', (ip, port)) for ip in addresses]
        monkeypatch.setattr(loop, 'getaddrinfo', lookup)
        with pytest.raises(SourceAccessError):
            await PublicResolver(frozenset({'example.com'})).resolve('example.com', 443)
        assert calls == [('example.com', 443)]
    run(exercise())


def test_real_public_resolver_preserves_hostname_and_does_not_resolve_unknown_host(monkeypatch):
    async def exercise():
        loop = asyncio.get_running_loop()
        calls = []
        async def lookup(host, port, **kwargs):
            calls.append(host)
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('8.8.8.8', port))] * 2
        monkeypatch.setattr(loop, 'getaddrinfo', lookup)
        resolver = PublicResolver(frozenset({'example.com'}))
        with pytest.raises(SourceAccessError):
            await resolver.resolve('evil.example', 443)
        assert calls == []
        result = await resolver.resolve('example.com', 443)
        assert len(result) == 1 and result[0]['hostname'] == 'example.com' and result[0]['host'] == '8.8.8.8'
        assert result[0]['flags'] == socket.AI_NUMERICHOST
    run(exercise())


@pytest.mark.parametrize('error_type', [aiohttp.ClientOSError, aiohttp.ServerDisconnectedError])
def test_actual_aiohttp_request_loop_does_not_retry_capture(monkeypatch, error_type):
    """Exercise installed aiohttp retry code, not just the option's value."""
    real_session = aiohttp.ClientSession
    attempts, sessions = [], []
    class FailingRequest(aiohttp.ClientRequest):
        async def send(self, connection):
            attempts.append(str(self.url))
            raise error_type('synthetic connection failure')
    def factory(**kwargs):
        session = real_session(**kwargs, request_class=FailingRequest)
        async def connect(*_args, **_kwargs):
            return SimpleNamespace(protocol=SimpleNamespace(set_response_params=lambda **kwargs: None), close=lambda: None)
        session.connector.connect = connect
        sessions.append(session)
        return session
    monkeypatch.setattr(transport_module.aiohttp, 'ClientSession', factory)
    with pytest.raises(MaterialTransportError, match='source_material_network_failed'):
        run(MaterialSourceTransport().fetch(canonical_policy(POLICY)))
    assert attempts == ['https://example.com/robots.txt']
    assert sessions[0].closed


def test_total_deadline_covers_entire_fetch_and_releases_capacity(monkeypatch):
    async def exercise():
        transport = MaterialSourceTransport()
        entered = asyncio.Event()
        async def slow(_policy, _claimed):
            entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(transport_module, 'TOTAL_SECONDS', 0.025)
        monkeypatch.setattr(transport, '_fetch', slow)
        with pytest.raises(MaterialTransportError, match='source_material_timeout'):
            await transport.fetch(canonical_policy(POLICY))
        assert entered.is_set() and transport._active == 0 and transport._hosts == set()
    run(exercise())


def test_busy_is_shared_across_policies_and_cancellation_releases_slot(monkeypatch):
    async def exercise():
        transport = MaterialSourceTransport()
        entered, release = asyncio.Queue(), asyncio.Event()
        async def blocked(policy, _claimed):
            await entered.put(policy['policy_id'])
            await release.wait()
            return {'policy': policy['policy_id']}
        monkeypatch.setattr(transport, '_fetch', blocked)
        first = asyncio.create_task(transport.fetch({'policy_id': 'one'}))
        second = asyncio.create_task(transport.fetch({'policy_id': 'two'}))
        await entered.get()
        await entered.get()
        with pytest.raises(MaterialTransportError, match='source_material_busy'):
            await transport.fetch({'policy_id': 'three'})
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        await second
        assert transport._active == 0
    run(exercise())


def test_host_limiter_rejection_does_not_extend_cooldown(monkeypatch):
    http = MemoryHTTP(monkeypatch, [robots(), MemoryResponse(), robots(), MemoryResponse()])
    transport = MaterialSourceTransport()
    run(transport.fetch(canonical_policy(POLICY)))
    previous = dict(transport._last)
    with pytest.raises(MaterialTransportError, match='source_material_rate_limited'):
        run(transport.fetch(canonical_policy({**POLICY, 'policy_id': 'different-policy'})))
    assert transport._last == previous and len(http.requests) == 2
    http.clock += 2.0
    run(transport.fetch(canonical_policy(POLICY)))
    assert len(http.requests) == 4 and transport._active == 0


@pytest.fixture
def case(monkeypatch):
    root = PRIVATE / uuid4().hex[:8]
    root.mkdir()
    monkeypatch.setenv('TI_OBJECT_STORE_BACKEND', 'filesystem')
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(root / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(root / 'bundles'))
    path = policy_file(root, monkeypatch)
    app = create_app('sqlite:///' + (root / 'private.sqlite').as_posix())
    with TestClient(app) as client:
        user = passed(client.post('/v1/auth/register', json={'username': 'review-admin', 'password': PASSWORD}))['user']
        calls = []
        async def fetch(policy):
            calls.append(deepcopy(policy))
            return acquired(policy)
        monkeypatch.setattr(app.state.material_transport, 'fetch', fetch)
        yield SimpleNamespace(root=root, path=path, app=app, client=client, database=app.state.database,
            user=user, calls=calls, monkeypatch=monkeypatch)


def acquired(policy, *, robot_body=ROBOTS):
    robot_hash = hashlib.sha256(robot_body).hexdigest()
    return {'body': PDF, 'initial_url': policy['download_url'], 'final_url': policy['download_url'],
        'redirects': [], 'robots': [{'url': 'https://example.com/robots.txt', 'status': 200,
            'raw_hash': robot_hash, 'byte_count': len(robot_body), 'allowed': True,
            'minimum_interval': 2.0, 'target_url': policy['download_url']}],
        'robot_objects': [{'raw_hash': robot_hash, 'body': robot_body}] if robot_body else [],
        'started_at': '2026-10-18T00:00:00+00:00', 'completed_at': '2026-10-18T00:00:01+00:00'}


def payload(case):
    policy = passed(case.client.get(BASE + '/policies'))['items'][0]
    return {'policy_id': policy['policy_id'], 'expected_policy_fingerprint': policy['policy_fingerprint'],
        'idempotency_key': str(uuid4()), 'operator': 'Independent synthetic operator', 'rights_confirmed': True}


def capture(case, body=None):
    body = body or payload(case)
    result = passed(case.client.post(BASE + '/captures', json=body), 201)
    assert result['state'] == 'succeeded', result
    return body, result


def row_counts(case):
    with case.database.sessions() as db:
        return tuple(db.scalar(select(func.count()).select_from(model)) for model in (
            SourceMaterialRequest, SourceMaterialOutcome, EvidenceDocument, EvidenceObject))


def lookup(case, key, client=None):
    return (client or case.client).get(BASE + '/requests/' + key + '?mode=history')


def raw_change(case, model, key, **values):
    """Deliberate private corruption; production immutable guards are tested separately."""
    table = model.__tablename__
    with case.database.engine.begin() as connection:
        connection.exec_driver_sql('DROP TRIGGER ' + table + '_no_update')
        connection.exec_driver_sql('PRAGMA ignore_check_constraints=ON')
        primary = 'id' if model is SourceMaterialRequest else 'request_id'
        params = {name: json.dumps(value) if name in {'payload', 'policy', 'receipt'} and value is not None else value
                  for name, value in values.items()}
        assignments = ', '.join(name + '=:' + name for name in params)
        connection.execute(text('UPDATE ' + table + ' SET ' + assignments + ' WHERE ' + primary + '=:row_key'),
                           {**params, 'row_key': key})


def test_admin_guard_precedes_body_and_callers_cannot_override_transport(case):
    before = row_counts(case)
    with TestClient(case.app) as anonymous:
        assert anonymous.post(BASE + '/captures', json={'download_url': 'https://evil.example/a'}).status_code == 403
        assert anonymous.post(BASE + '/preview', json={'bad': True}).status_code == 403
    body = payload(case)
    for extra in ({'download_url': 'https://evil.example/a.pdf'}, {'headers': {'Authorization': 'forbidden'}},
                  {'actor_user_id': 'forged'}, {'rights': POLICY['rights']}, {'rights_confirmed': 1}):
        assert case.client.post(BASE + '/captures', json={**body, **extra}).status_code == 422
    assert row_counts(case) == before and case.calls == []


def test_stale_or_unknown_policy_refuses_without_reserving_or_fetching(case):
    before, body = row_counts(case), payload(case)
    for change, status in [({'expected_policy_fingerprint': '0' * 64}, 409), ({'policy_id': 'unknown'}, 404)]:
        assert case.client.post(BASE + '/captures', json={**body, **change}).status_code == status
    assert row_counts(case) == before and case.calls == []


def test_preview_and_catalog_are_snapshot_only_and_do_not_capture(case):
    before, body = row_counts(case), payload(case)
    case.path.write_text('invalid after application startup', encoding='utf-8')
    value = passed(case.client.post(BASE + '/preview', json={key: body[key] for key in (
        'policy_id', 'expected_policy_fingerprint')}))
    assert value['can_capture'] is True and value['policy'] == canonical_policy(POLICY)
    assert row_counts(case) == before and case.calls == []


def test_success_receipt_independent_original_roundtrip_and_no_authenticity_upgrade(case):
    body, first = capture(case)
    document, receipt = first['document'], first['receipt']
    assert document['source_url'] == POLICY['source_reference_url']
    assert receipt['initial_url'] == receipt['final_url'] == POLICY['download_url']
    assert receipt['source_reference_relation'] == 'operator_configured'
    assert receipt['transport_verification'] == 'https_transport_observed'
    assert receipt['content_authenticity'] == 'unverified'
    assert first['policy']['rights']['provider_use'] is first['policy']['rights']['export'] is False
    response = case.client.get('/v1/documents/' + document['id'] + '/content?mode=history')
    assert response.status_code == 200 and response.content == PDF
    assert response.headers['x-evidence-sha256'] == hashlib.sha256(PDF).hexdigest()
    assert 'attachment' in response.headers['content-disposition']
    second = passed(lookup(case, body['idempotency_key']))
    assert second['receipt'] == receipt
    reopened = passed(case.client.get(BASE + '/documents/' + document['id'] + '?mode=history'))
    assert reopened['receipt'] == receipt and len(case.calls) == 1
    assert document.get('accepted_as_facts') is False


def test_same_user_other_session_replays_even_when_policy_removed(case):
    body, first = capture(case)
    from tire_api.material_source_policy import PolicyCatalog
    case.app.state.material_policies = PolicyCatalog([])
    with TestClient(case.app) as other:
        passed(other.post('/v1/auth/login', json={'username': 'review-admin', 'password': PASSWORD}))
        replay = passed(other.post(BASE + '/captures', json=body), 201)
        assert replay['replayed'] is True and replay['request_id'] == first['request_id']
        assert passed(lookup(case, body['idempotency_key'], other))['receipt'] == first['receipt']
        mismatch = {**body, 'operator': 'Changed after response loss'}
        assert other.post(BASE + '/captures', json=mismatch).status_code == 409
    assert len(case.calls) == 1 and row_counts(case)[:3] == (1, 1, 1)


def test_another_user_cannot_lookup_private_request_and_has_separate_uuid_namespace(case):
    body, first = capture(case)
    with TestClient(case.app) as other:
        user = passed(other.post('/v1/auth/register', json={'username': 'other-reader', 'password': PASSWORD}))['user']
        assert lookup(case, body['idempotency_key'], other).status_code == 404
        assert passed(other.get(BASE + '/requests?mode=history'))['total'] == 0
        assert other.post(BASE + '/captures', json=body).status_code == 403
        passed(case.client.post('/v1/auth/users/' + user['id'] + '/role', json={'is_admin': True}))
        second = passed(other.post(BASE + '/captures', json=body), 201)
        assert second['state'] == 'succeeded' and second['request_id'] != first['request_id']
    assert len(case.calls) == 2 and row_counts(case)[:3] == (2, 2, 2)


@pytest.mark.parametrize('failure_code', ['source_material_timeout', 'source_material_robots_disallowed',
    'source_material_rate_limited', 'source_material_network_failed', 'source_material_robots_unavailable'])
def test_failure_is_durable_and_same_uuid_never_refetches(case, failure_code):
    calls = []
    async def fail(_policy):
        calls.append(1)
        raise MaterialTransportError(failure_code)
    case.monkeypatch.setattr(case.app.state.material_transport, 'fetch', fail)
    body = payload(case)
    first = passed(case.client.post(BASE + '/captures', json=body), 201)
    assert first['state'] == 'failed' and first['failure_code'] == failure_code
    assert first['document'] is first['receipt'] is None
    second = passed(case.client.post(BASE + '/captures', json=body), 201)
    assert second['replayed'] and second['request_id'] == first['request_id']
    assert passed(lookup(case, body['idempotency_key']))['state'] == 'failed'
    assert calls == [1] and row_counts(case)[:3] == (1, 1, 0)


def test_unknown_exception_leaves_unconfirmed_reservation_without_automatic_recovery(case):
    calls = []
    async def crash(_policy):
        calls.append(1)
        raise RuntimeError('sensitive local path must not be returned')
    case.monkeypatch.setattr(case.app.state.material_transport, 'fetch', crash)
    body = payload(case)
    response = case.client.post(BASE + '/captures', json=body)
    assert response.status_code == 503 and 'sensitive' not in response.text
    first = passed(lookup(case, body['idempotency_key']))
    assert first['state'] == 'processing_unconfirmed' and first['completed_at'] is None
    assert first['document'] is first['receipt'] is first['failure_code'] is None
    replay = passed(case.client.post(BASE + '/captures', json=body), 201)
    assert replay['replayed'] and replay['state'] == 'processing_unconfirmed'
    assert calls == [1] and row_counts(case)[:3] == (1, 0, 0)


@pytest.mark.parametrize('change', ['demote', 'delete', 'rebind'])
def test_authorization_change_during_network_cannot_publish(case, change):
    async def fetch(policy):
        with case.database.sessions() as db:
            if change == 'demote':
                db.get(User, case.user['id']).is_admin = False
            elif change == 'delete':
                # Preserve FK-bound user sessions, as account deletion does.
                db.execute(update(UserSession).where(UserSession.user_id == case.user['id']).values(user_id=None))
                db.delete(db.get(User, case.user['id']))
            else:
                original = db.get(User, case.user['id'])
                replacement = User(username='rebound-admin', display_name='Rebound account',
                    password_hash=original.password_hash, is_admin=True)
                db.add(replacement)
                db.flush()
                db.execute(update(UserSession).where(UserSession.user_id == case.user['id']).values(user_id=replacement.id))
            db.commit()
        return acquired(policy)
    case.monkeypatch.setattr(case.app.state.material_transport, 'fetch', fetch)
    body = payload(case)
    result = passed(case.client.post(BASE + '/captures', json=body), 201)
    assert result['state'] == 'failed' and result['failure_code'] == 'source_material_authorization_changed'
    assert result['document'] is result['receipt'] is None
    assert row_counts(case)[:3] == (1, 1, 0)
    if change != 'rebind':
        assert case.client.post(BASE + '/captures', json=body).status_code == 403


def test_same_hash_manual_upload_does_not_gain_receipt_or_replace_attribution(case):
    metadata = {'title': 'Earlier manual synthetic upload', 'source_url': 'https://example.org/manual',
        'operator': 'Earlier manual operator', 'rights_basis': 'Independent project fixture manual upload'}
    old = passed(case.client.post('/v1/documents', content=PDF, headers={'Content-Type': 'application/pdf',
        'X-Evidence-Metadata': base64.b64encode(json.dumps(metadata).encode()).decode()}), 201)
    _, captured = capture(case)
    assert captured['document']['raw_hash'] == old['raw_hash']
    assert captured['document']['id'] != old['id'] and captured['document']['source_url'] != old['source_url']
    assert case.client.get(BASE + '/documents/' + old['id'] + '?mode=history').status_code == 404
    documents = passed(case.client.get('/v1/documents?mode=history'))['items']
    assert next(row for row in documents if row['id'] == old['id']) == old


@pytest.mark.parametrize('model_name,action', [(name, action) for name in ('request', 'outcome')
    for action in ('update', 'delete', 'replace')])
def test_sql_append_only_protects_request_and_outcome(case, model_name, action):
    body, captured = capture(case)
    table = 'source_material_requests' if model_name == 'request' else 'source_material_outcomes'
    with case.database.engine.begin() as connection:
        if action == 'update':
            statement = 'UPDATE ' + table + ' SET fingerprint=fingerprint'
        elif action == 'delete':
            statement = 'DELETE FROM ' + table
        else:
            statement = 'INSERT OR REPLACE INTO ' + table + ' SELECT * FROM ' + table
        with pytest.raises(DBAPIError, match='source_material_immutable'):
            connection.execute(text(statement))
    assert passed(lookup(case, body['idempotency_key']))['receipt'] == captured['receipt']


@pytest.mark.parametrize('model_name,action', [(name, action) for name in ('request', 'outcome')
    for action in ('update', 'delete')])
def test_orm_append_only_protects_request_and_outcome(case, model_name, action):
    _, captured = capture(case)
    model = SourceMaterialRequest if model_name == 'request' else SourceMaterialOutcome
    with case.database.sessions() as db:
        row = db.get(model, captured['request_id'])
        if action == 'delete':
            db.delete(row)
        else:
            row.fingerprint = '0' * 64
        with pytest.raises(ValueError, match='只能追加'):
            db.flush()
        db.rollback()


@pytest.mark.parametrize('target', ['pdf', 'robots', 'document', 'object-size', 'request-policy', 'outcome-receipt'])
def test_success_history_detects_each_independent_corruption(case, target):
    body, captured = capture(case)
    receipt = captured['receipt']
    if target in {'pdf', 'robots'}:
        raw_hash = receipt['raw_hash'] if target == 'pdf' else receipt['robots'][0]['raw_hash']
        case.database.object_store.path(raw_hash).write_bytes(b'corrupted synthetic bytes')
    elif target == 'document':
        with case.database.engine.begin() as connection:
            connection.execute(text('UPDATE evidence_documents SET title=:title WHERE id=:id'),
                {'title': 'altered metadata', 'id': captured['document']['id']})
    elif target == 'object-size':
        with case.database.engine.begin() as connection:
            connection.execute(text('UPDATE evidence_objects SET byte_count=byte_count+1 WHERE raw_hash=:hash'),
                {'hash': receipt['raw_hash']})
    elif target == 'request-policy':
        changed = deepcopy(captured['policy'])
        changed['rights']['basis'] += ' corrupted'
        raw_change(case, SourceMaterialRequest, captured['request_id'], policy=changed)
    else:
        changed = deepcopy(receipt)
        changed['initial_url'] = 'https://evil.example/unobserved.pdf'
        raw_change(case, SourceMaterialOutcome, captured['request_id'], receipt=changed)
    assert lookup(case, body['idempotency_key']).status_code == 503
    assert case.client.get(BASE + '/documents/' + captured['document']['id'] + '?mode=history').status_code == 503


def test_unknown_outcome_state_even_with_recomputed_hash_fails_closed(case):
    from tire_api.source_materials import outcome_fingerprint
    body, captured = capture(case)
    with case.database.sessions() as db:
        row = db.get(SourceMaterialOutcome, captured['request_id'])
        row.state = 'unknown_future_state'
        fingerprint = outcome_fingerprint(row)
        db.rollback()
    raw_change(case, SourceMaterialOutcome, captured['request_id'], state='unknown_future_state', fingerprint=fingerprint)
    assert lookup(case, body['idempotency_key']).status_code == 503


@pytest.mark.parametrize('field,value', [('initial_url', 'https://evil.example/unobserved.pdf'),
    ('final_url', 'https://evil.example/unobserved.pdf'), ('content_authenticity', 'verified'),
    ('source_reference_relation', 'independently_verified'), ('content_encoding', 'gzip')])
def test_semantically_impossible_receipt_is_rejected_even_if_rehashed(case, field, value):
    from tire_api.source_materials import outcome_fingerprint
    body, captured = capture(case)
    changed = deepcopy(captured['receipt'])
    changed[field] = value
    changed['fingerprint'] = digest({key: val for key, val in changed.items() if key != 'fingerprint'})
    with case.database.sessions() as db:
        row = db.get(SourceMaterialOutcome, captured['request_id'])
        row.receipt = changed
        fingerprint = outcome_fingerprint(row)
        db.rollback()
    raw_change(case, SourceMaterialOutcome, captured['request_id'], receipt=changed, fingerprint=fingerprint)
    assert lookup(case, body['idempotency_key']).status_code == 503


@pytest.mark.parametrize('field,value', [('raw_hash', '0' * 64), ('byte_count', 1)])
def test_empty_robots_provenance_is_validated_on_reopen(case, field, value):
    from tire_api.source_materials import outcome_fingerprint
    async def fetch(policy):
        return acquired(policy, robot_body=b'')
    case.monkeypatch.setattr(case.app.state.material_transport, 'fetch', fetch)
    body, captured = capture(case)
    assert captured['receipt']['robots'][0]['raw_hash'] == hashlib.sha256(b'').hexdigest()
    changed = deepcopy(captured['receipt'])
    changed['robots'][0][field] = value
    changed['fingerprint'] = digest({key: val for key, val in changed.items() if key != 'fingerprint'})
    with case.database.sessions() as db:
        row = db.get(SourceMaterialOutcome, captured['request_id'])
        row.receipt = changed
        fingerprint = outcome_fingerprint(row)
        db.rollback()
    raw_change(case, SourceMaterialOutcome, captured['request_id'], receipt=changed, fingerprint=fingerprint)
    assert lookup(case, body['idempotency_key']).status_code == 503


def test_concurrent_same_user_key_has_one_network_owner_and_no_database_lock_during_network(case):
    entered, release, calls = threading.Event(), threading.Event(), []
    async def blocked(policy):
        calls.append(1)
        entered.set()
        assert await asyncio.to_thread(release.wait, 6), 'Review worker was not released'
        return acquired(policy)
    case.monkeypatch.setattr(case.app.state.material_transport, 'fetch', blocked)
    body = payload(case)
    with TestClient(case.app) as second:
        passed(second.post('/v1/auth/login', json={'username': 'review-admin', 'password': PASSWORD}))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(case.client.post, BASE + '/captures', json=body)
            try:
                assert entered.wait(5), 'Production transport was not entered'
                # A real write on a separate connection must proceed while network is suspended.
                with case.database.engine.begin() as connection:
                    connection.execute(text('UPDATE users SET display_name=display_name WHERE id=:id'), {'id': case.user['id']})
                replay = passed(second.post(BASE + '/captures', json=body), 201)
                assert replay['state'] == 'processing_unconfirmed' and replay['replayed'] is True
                assert calls == [1]
            finally:
                release.set()
            success = passed(future.result(timeout=8), 201)
    assert success['state'] == 'succeeded' and success['request_id'] == replay['request_id']
    assert calls == [1] and row_counts(case)[:3] == (1, 1, 1)


@pytest.mark.parametrize('acknowledged', [False, True], ids=['rollback-before-commit', 'lost-ack-after-commit'])
def test_terminal_commit_uncertainty_never_refetches_or_leaks_partial_document(case, acknowledged):
    from sqlalchemy.orm import Session
    commit = Session.commit
    triggered = []
    def uncertain(db):
        if not triggered and any(isinstance(row, SourceMaterialOutcome) and row.state == 'succeeded' for row in db.new):
            triggered.append(1)
            if acknowledged:
                commit(db)
            raise RuntimeError('synthetic lost commit acknowledgement')
        return commit(db)
    body = payload(case)
    with case.monkeypatch.context() as local:
        local.setattr(Session, 'commit', uncertain)
        response = case.client.post(BASE + '/captures', json=body)
    assert response.status_code == 503 and triggered == [1]
    first = passed(lookup(case, body['idempotency_key']))
    assert first['state'] == ('succeeded' if acknowledged else 'processing_unconfirmed')
    assert (first['document'] is not None) is acknowledged
    assert row_counts(case)[:3] == ((1, 1, 1) if acknowledged else (1, 0, 0))
    second = passed(case.client.post(BASE + '/captures', json=body), 201)
    assert second['replayed'] and second['state'] == first['state'] and len(case.calls) == 1


def test_transport_exception_cannot_persist_unbounded_secret_failure(case):
    async def fail(_policy):
        raise MaterialTransportError('https://user:secret@example.org/?token=private-body')
    case.monkeypatch.setattr(case.app.state.material_transport, 'fetch', fail)
    body = payload(case)
    response = case.client.post(BASE + '/captures', json=body)
    value = passed(response, 201)
    assert value['state'] == 'failed'
    assert value['failure_code'] == 'source_material_capture_failed'
    assert 'secret' not in response.text and 'private-body' not in response.text
    assert passed(lookup(case, body['idempotency_key']))['failure_code'] == 'source_material_capture_failed'


def test_robots_larger_interval_is_respected_under_global_deadline(monkeypatch):
    http = MemoryHTTP(monkeypatch, [robots(body=b'User-agent: *\nAllow: /\nCrawl-delay: 7\n'), MemoryResponse()])
    run(MaterialSourceTransport().fetch(canonical_policy(POLICY)))
    assert http.clock >= 107.0
    assert len(http.requests) == 2


def test_real_stream_deadline_rejects_drip_body_and_releases_claim(monkeypatch):
    class Drip(MemoryResponse):
        async def iter_chunked(self, _size):
            yield b'%PDF-'
            await asyncio.Event().wait()
    async def exercise():
        transport = MaterialSourceTransport()
        replies = [robots(404, b''), Drip(length=None)]
        class Session:
            def __init__(self, **_kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_args):
                pass
            def get(self, *_args, **_kwargs):
                return replies.pop(0)
        async def pace(host, claimed):
            claimed.add(host)
            transport._hosts.add(host)
        monkeypatch.setattr(transport_module.aiohttp, 'ClientSession', Session)
        monkeypatch.setattr(transport_module.aiohttp, 'TCPConnector', lambda **kwargs: None)
        monkeypatch.setattr(transport_module, 'TOTAL_SECONDS', 0.025)
        monkeypatch.setattr(transport, '_pace', pace)
        with pytest.raises(MaterialTransportError, match='source_material_timeout'):
            await transport.fetch(canonical_policy(POLICY))
        assert transport._active == 0 and transport._hosts == set() and replies == []
    run(exercise())


@pytest.mark.parametrize('framing', ['single', 'duplicate', 'conflicting', 'transfer-and-length', 'nonnumeric'])
def test_real_aiohttp_client_parser_rejects_ambiguous_content_length(monkeypatch, framing):
    """Raw response bytes enter aiohttp's installed parser and actual request loop."""
    from aiohttp.client_proto import ResponseHandler
    real_session = aiohttp.ClientSession
    attempts = []
    length = str(len(PDF)).encode()
    headers = {
        'single': b'Content-Length: ' + length + b'\r\n',
        'duplicate': b'Content-Length: ' + length + b'\r\nContent-Length: ' + length + b'\r\n',
        'conflicting': b'Content-Length: ' + length + b'\r\nContent-Length: 1\r\n',
        'transfer-and-length': b'Transfer-Encoding: chunked\r\nContent-Length: ' + length + b'\r\n',
        'nonnumeric': b'Content-Length: invalid\r\n',
    }[framing]
    class WireRequest(aiohttp.ClientRequest):
        async def send(self, connection):
            attempts.append(str(self.url))
            wire = (b'HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n' if self.url.path == '/robots.txt'
                else b'HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\n' + headers + b'\r\n' + PDF)
            connection.protocol.data_received(wire)
            self.response = self.response_class(self.method, self.original_url, writer=None,
                continue100=self._continue, timer=self._timer, request_info=self.request_info,
                traces=self._traces, loop=self.loop, session=self._session,
                stream_writer=SimpleNamespace(output_size=0))
            return self.response
    def factory(**kwargs):
        session = real_session(**kwargs, request_class=WireRequest)
        async def connect(*_args, **_kwargs):
            return SimpleNamespace(protocol=ResponseHandler(asyncio.get_running_loop()),
                close=lambda: None, release=lambda: None, add_callback=lambda callback: None)
        session.connector.connect = connect
        return session
    monkeypatch.setattr(transport_module.aiohttp, 'ClientSession', factory)
    transport = MaterialSourceTransport()
    async def pace(_host, _claimed):
        return None
    monkeypatch.setattr(transport, '_pace', pace)
    if framing == 'single':
        result = run(transport.fetch(canonical_policy(POLICY)))
        assert result['body'] == PDF
    else:
        with pytest.raises(MaterialTransportError, match='source_material_network_failed'):
            run(transport.fetch(canonical_policy(POLICY)))
    assert attempts == ['https://example.com/robots.txt', POLICY['download_url']]


@pytest.mark.parametrize('status', [100, 201, 302, 403, 406, 429, 500, 599])
def test_robots_failure_diagnostic_is_bounded_and_copied(status):
    error = MaterialTransportError('source_material_robots_unavailable')
    error.phase, error.http_status = 'robots_http_status', status
    expected = {'phase': 'robots_http_status', 'http_status': status}
    first = transport_module.robots_failure_diagnostic(error)
    assert first == expected and str(error) == 'source_material_robots_unavailable'
    first['http_status'] = 999
    assert transport_module.robots_failure_diagnostic(error) == expected


@pytest.mark.parametrize('variant', ['subclass', 'foreign', 'missing', 'extra', 'url', 'headers', 'body',
    'notes', 'phase', 'phase-subclass', 'code', 'code-subclass', 'two-args', 'bool', 'float', 'text',
    'low', 'high', 'accepted-200', 'accepted-404', 'accepted-410'])
def test_robots_failure_diagnostic_rejects_forged_fields(variant):
    class Derived(MaterialTransportError):
        pass
    class Text(str):
        pass
    error = Derived('source_material_robots_unavailable') if variant == 'subclass' else (
        RuntimeError('source_material_robots_unavailable') if variant == 'foreign' else
        MaterialTransportError('source_material_robots_unavailable'))
    error.phase, error.http_status = 'robots_http_status', 429
    if variant == 'missing':
        del error.http_status
    elif variant in {'extra', 'url', 'headers', 'body'}:
        setattr(error, variant, 'DO_NOT_RETAIN')
    elif variant == 'notes':
        error.add_note('DO_NOT_RETAIN')
    elif variant == 'phase':
        error.phase = 'DO_NOT_RETAIN'
    elif variant == 'phase-subclass':
        error.phase = Text('robots_http_status')
    elif variant == 'code':
        error.args = ('DO_NOT_RETAIN',)
    elif variant == 'code-subclass':
        error.args = (Text('source_material_robots_unavailable'),)
    elif variant == 'two-args':
        error.args = ('source_material_robots_unavailable', 'DO_NOT_RETAIN')
    elif variant in {'bool', 'float', 'text', 'low', 'high', 'accepted-200', 'accepted-404', 'accepted-410'}:
        error.http_status = {'bool': True, 'float': 429.0, 'text': '429', 'low': 99, 'high': 600,
            'accepted-200': 200, 'accepted-404': 404, 'accepted-410': 410}[variant]
    assert transport_module.robots_failure_diagnostic(error) is None


@pytest.mark.parametrize('robots_status', [200, 404, 410])
def test_real_aiohttp_robots_and_pdf_send_distinct_accept_headers(monkeypatch, robots_status):
    """Inspect installed aiohttp's final ClientRequest headers without a socket."""
    from aiohttp.client_proto import ResponseHandler
    real_session = aiohttp.ClientSession
    attempts, sessions = [], []
    class HeaderRequest(aiohttp.ClientRequest):
        async def send(self, connection):
            attempts.append((str(self.url), dict(self.headers)))
            is_robots = self.url.path == '/robots.txt'
            status = robots_status if is_robots else 200
            body = (ROBOTS if robots_status == 200 else b'') if is_robots else PDF
            kind = b'text/plain' if is_robots else b'application/pdf'
            wire = (f'HTTP/1.1 {status} Synthetic\r\n'.encode() + b'Content-Type: ' + kind
                + b'\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
            connection.protocol.data_received(wire)
            self.response = self.response_class(self.method, self.original_url, writer=None,
                continue100=self._continue, timer=self._timer, request_info=self.request_info,
                traces=self._traces, loop=self.loop, session=self._session,
                stream_writer=SimpleNamespace(output_size=0))
            return self.response
    def factory(**kwargs):
        session = real_session(**kwargs, request_class=HeaderRequest)
        async def connect(*_args, **_kwargs):
            return SimpleNamespace(protocol=ResponseHandler(asyncio.get_running_loop()),
                close=lambda: None, release=lambda: None, add_callback=lambda callback: None)
        session.connector.connect = connect
        sessions.append(session)
        return session
    monkeypatch.setattr(transport_module.aiohttp, 'ClientSession', factory)
    transport = MaterialSourceTransport()
    async def pace(_host, _claimed):
        return None
    monkeypatch.setattr(transport, '_pace', pace)
    result = run(transport.fetch(canonical_policy(POLICY)))
    assert result['body'] == PDF
    assert [url for url, _ in attempts] == ['https://example.com/robots.txt', POLICY['download_url']]
    assert [headers['Accept'] for _, headers in attempts] == ['text/plain', 'application/pdf']
    assert all(headers['User-Agent'] == transport_module.USER_AGENT
        and headers['Accept-Encoding'] == 'identity' for _, headers in attempts)
    assert len(sessions) == 1 and sessions[0].closed
