"""Independent R79 adversarial contracts over synthetic, private ASGI/SQLite.

Expected fields, owner rules, cursor behavior and limits are hand written.
No product cursor/projection helper constructs an expected result. Credentials
exist only in process memory; run only through the prebound private harness.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import base64
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest


_PRIVATE_ROOT = os.environ.get('R79_TEST_STORAGE_ROOT')
if not _PRIVATE_ROOT or os.environ.get('TIRE_DATABASE_URL') != os.environ.get('DATABASE_URL'):
    raise RuntimeError('r79_review_private_harness_required_before_application_import')
if not os.environ['TIRE_DATABASE_URL'].startswith('sqlite:///' + Path(_PRIVATE_ROOT).as_posix() + '/'):
    raise RuntimeError('r79_review_bootstrap_database_must_be_private')

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from admin_support import register_admin
from test_core import FixtureRegistry, QUERY, VARIANT, live, success
from tire_api.db import User, UserSession, utc, utcnow
from tire_api.main import create_app


MANAGE = '/v1/api-keys'
OPERATIONS = '/v1/api-key-operations'
SOURCES = '/external/v1/sources'
DELIVERIES = '/external/v1/webhook-deliveries'
KEY_FIELDS = {'schema', 'id', 'name', 'scopes', 'created_at', 'expires_at', 'revoked_at'}
OP_FIELDS = {'schema', 'idempotency_key', 'action', 'key', 'token', 'replayed'}
SOURCE_FIELDS = {'id', 'name', 'source_class', 'region', 'parser_version', 'status'}
PAGE_FIELDS = {'schema', 'items', 'next_cursor', 'limit', 'data_state'}


class PrivateText(str):
    def __repr__(self):
        return '<r79-private-secret>'


class PrivateCase(SimpleNamespace):
    def __repr__(self):
        return '<r79-private-case>'


def ok(response, statuses=(200,)):
    assert response.status_code in statuses, ('unexpected_http_status', response.status_code)
    return response.json()


class CatalogRegistry(FixtureRegistry):
    def __init__(self):
        super().__init__()
        self.catalog = [{'id': name, 'name': 'Synthetic ' + name, 'region': 'US',
            'source_class': 'test_fixture', 'parser_version': 'synthetic@1',
            'status': 'ready', 'homepage': 'https://fixture.example/private-path',
            'private_setting': 'R79_NEVER_EXPORT_PRIVATE_SETTING'}
            for name in ['fixture-z', 'fixture-two', 'fixture', 'fixture-b', 'fixture-a']]

    def sources(self):
        return deepcopy(self.catalog)


@pytest.fixture
def factory(tmp_path, monkeypatch):
    assert tmp_path.resolve().is_relative_to(Path(_PRIVATE_ROOT).resolve())
    stack = ExitStack()

    def make(*, path=None, login=True):
        storage = path or tmp_path / uuid4().hex[:8]
        storage.mkdir(exist_ok=True)
        url = 'sqlite:///' + (storage / 'p.db').as_posix()
        for name in list(os.environ):
            if (name.startswith(('TI_', 'TIRE_', 'OPENAI_', 'ANTHROPIC_', 'AZURE_OPENAI_'))
                    or name == 'DATABASE_URL' or name.lower().endswith('_proxy')):
                monkeypatch.delenv(name, raising=False)
        catalog = storage / 'targets.json'
        catalog.write_text(json.dumps({'schema': 'webhook-targets@1', 'targets': [{
            'id': 'review', 'title': 'Synthetic only', 'url': 'https://receiver.example/hook',
            'signing_key_env': 'TI_WEBHOOK_SIGNING_R79_REVIEW'}]}), encoding='utf-8')
        for name, value in {'TIRE_DATABASE_URL': url, 'DATABASE_URL': url,
            'TI_OBJECT_STORE_BACKEND': 'filesystem', 'TI_OBJECT_STORE_ROOT': str(storage / 'o'),
            'TI_PARSER_BUNDLE_ROOT': str(storage / 'b'), 'TI_AI_ENABLED': '0',
            'TI_EMBEDDINGS_ENABLED': '0', 'TI_OBSERVABILITY_ENABLED': '0',
            'TI_WEBHOOK_TARGETS_FILE': str(catalog),
            'TI_WEBHOOK_SIGNING_R79_REVIEW': secrets.token_hex(32)}.items():
            monkeypatch.setenv(name, value)
        registry = CatalogRegistry()
        app = create_app(url, registry)
        client = stack.enter_context(TestClient(app,
            backend_options={'loop_factory': asyncio.SelectorEventLoop}))
        password = PrivateText(secrets.token_urlsafe(18))
        actor = register_admin(client, 'review-owner', password)['user'] if login else None
        stack.callback(app.state.database.engine.dispose)
        return PrivateCase(app=app, client=client, database=app.state.database,
            registry=registry, actor=actor, password=password, storage=storage, index=0)

    yield make
    stack.close()


def account(case, username='review-other', *, same=False):
    client = TestClient(case.app, backend_options={'loop_factory': asyncio.SelectorEventLoop})
    password = case.password if same else PrivateText(secrets.token_urlsafe(18))
    if same:
        actor = ok(client.post('/v1/auth/login', json={'username': 'review-owner', 'password': password}))['user']
    else:
        actor = register_admin(client, username, password)['user']
    return PrivateCase(client=client, actor=actor, password=password, username='review-owner' if same else username)


def create(case, *, client=None, key=None, **changes):
    payload = {'name': ' 独立合成凭据 ', 'scopes': ['webhooks:read', 'sources:read'],
        'expires_in_days': 30, 'acknowledged': True, **changes}
    return (client or case.client).post(MANAGE, json=payload,
        headers={'Idempotency-Key': key or str(uuid4())})


def operation(response, *, statuses=(200,), replayed=False, token=False):
    body = ok(response, statuses)
    assert set(body) == OP_FIELDS and body['schema'] == 'api-key-operation@1'
    assert body['action'] in {'create', 'revoke'} and body['replayed'] is replayed
    assert set(body['key']) == KEY_FIELDS and body['key']['schema'] == 'api-key@1'
    valid_token_shape = isinstance(body['token'], str) and bool(re.fullmatch(r'ti_[0-9a-f]{32}\.[0-9a-f]{64}', body['token']))
    assert valid_token_shape if token else body['token'] is None, 'unexpected_token_presence_or_shape'
    assert body['key']['scopes'] == sorted(set(body['key']['scopes']))
    if body['token'] is not None:
        body['token'] = PrivateText(body['token'])
    return body


def issued(case, **changes):
    return operation(create(case, **changes), statuses=(200, 201), token=True)


def revoke(case, value, *, client=None, key=None, **changes):
    return (client or case.client).post(MANAGE + '/' + value['key']['id'] + '/revoke',
        json={'acknowledged': True, **changes}, headers={'Idempotency-Key': key or str(uuid4())})


def external(case, path=SOURCES, *, token=None, client=None, headers=None, method='GET'):
    pairs = [] if token is None else [('Authorization', 'Bearer ' + token)]
    pairs += list((headers or {}).items()) if isinstance(headers, dict) else (headers or [])
    return (client or case.client).request(method, path, headers=pairs)


def snapshot(case):
    """Read-only fingerprints; never return or print private SQL row values."""
    with case.database.engine.connect() as connection:
        names = connection.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")).scalars().all()
        result = {}
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            rows = connection.execute(text('SELECT * FROM ' + quoted)).all()
            raw = json.dumps(sorted([list(row) for row in rows], key=repr), default=str,
                sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            result[name] = (len(rows), hashlib.sha256(raw).hexdigest())
        return result


def source_page(case, token, *, limit=1, cursor=None):
    params = {'limit': str(limit)}
    if cursor is not None:
        params['cursor'] = cursor
    response = case.client.get(SOURCES, params=params, headers={'Authorization': 'Bearer ' + token})
    return response


def test_create_first_response_only_reveal_and_frozen_metadata_replay(factory):
    case = factory()
    key = str(uuid4())
    first = issued(case, key=key)
    assert first['key']['name'] == '独立合成凭据' and first['key']['revoked_at'] is None
    again = operation(create(case, key=key), statuses=(200, 201), replayed=True)
    assert again == {**first, 'token': None, 'replayed': True}
    operation(revoke(case, first))
    recovered = operation(case.client.get(OPERATIONS + '?mode=history&key=' + key), replayed=True)
    assert recovered['key'] == first['key'] and recovered['key']['revoked_at'] is None
    listing = ok(case.client.get(MANAGE + '?mode=history'))
    assert set(listing) == {'schema', 'items'} and listing['schema'] == 'api-keys@1'
    assert listing['items'][0]['revoked_at'] is not None
    assert external(case, token=first['token']).status_code == 401


def test_secret_is_not_stored_or_returned_by_list_operation_or_revoke(factory):
    case = factory()
    value = issued(case)
    bearer = value['token']
    with case.database.engine.connect() as connection:
        names = connection.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")).scalars().all()
        encoded = []
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            encoded.append(json.dumps([list(row) for row in connection.execute(text('SELECT * FROM ' + quoted))], default=str))
    persisted_raw_bearer = any(bearer in row or bearer.split('.', 1)[1] in row for row in encoded)
    assert persisted_raw_bearer is False, 'raw_bearer_or_secret_persisted'
    responses = [case.client.get(MANAGE + '?mode=history'),
        case.client.get(OPERATIONS + '?mode=history&key=' + value['idempotency_key']), revoke(case, value)]
    for response in responses:
        assert response.status_code == 200
        contains_secret = bearer in response.text or bearer.split('.', 1)[1] in response.text
        assert contains_secret is False, 'non_initial_response_disclosed_secret'


@pytest.mark.parametrize('changes', [
    {'name': ''}, {'name': '   '}, {'name': 'a' * 81}, {'name': 'line\nbreak'},
    {'scopes': []}, {'scopes': ['admin']}, {'scopes': ['sources:write']},
    {'expires_in_days': 0}, {'expires_in_days': 91}, {'expires_in_days': True},
    {'expires_in_days': 1.0}, {'expires_in_days': '1'}, {'acknowledged': False},
    {'acknowledged': 1}, {'token': 'user_supplied_token'}],
    ids=['empty-name', 'space-name', 'long-name', 'control-name', 'empty-scopes',
         'unknown-scope', 'write-scope', 'days0', 'days91', 'days-bool', 'days-float',
         'days-string', 'no-ack', 'numeric-ack', 'chosen-token'])
def test_management_strict_closed_validation(factory, changes):
    case = factory()
    assert create(case, **changes).status_code == 422


def test_management_permission_precedes_invalid_body_and_bearer_cannot_manage(factory):
    case = factory(login=False)
    for path in [MANAGE, MANAGE + '/missing/revoke']:
        assert case.client.post(path, json={'bad': True}).status_code in {401, 403}
    owner = register_admin(case.client, 'review-owner', secrets.token_urlsafe(18))
    value = issued(case)
    before = snapshot(case)
    for method, path in [('GET', MANAGE + '?mode=history'), ('POST', MANAGE),
        ('GET', '/v1/sources'), ('GET', '/health'), ('GET', '/v1/auth/me')]:
        response = case.client.request(method, path, json={'bad': 1} if method == 'POST' else None,
            headers={'Authorization': 'Bearer ' + value['token']})
        assert response.status_code in {400, 401, 403}, path
    assert snapshot(case) == before


def test_cross_account_management_hides_key_and_operation_before_body(factory):
    case = factory()
    value = issued(case)
    other = account(case)
    try:
        assert ok(other.client.get(MANAGE + '?mode=history'))['items'] == []
        assert other.client.get(OPERATIONS + '?mode=history&key=' + value['idempotency_key']).status_code == 404
        assert other.client.post(MANAGE + '/' + value['key']['id'] + '/revoke', json={'bad': 1}).status_code == 404
        assert external(case, token=value['token'], client=other.client).status_code == 200
    finally:
        other.client.close()


def test_management_expired_session_not_authorized_and_key_survives_logout(factory):
    case = factory()
    value = issued(case)
    peer = account(case, same=True)
    try:
        assert peer.actor['id'] == case.actor['id']
        assert len(ok(peer.client.get(MANAGE + '?mode=history'))['items']) == 1
        with case.database.sessions() as db:
            db.get(UserSession, case.client.cookies['tire_local_session']).expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
        assert case.client.get(MANAGE + '?mode=history').status_code in {401, 403}
        assert external(case, token=value['token']).status_code == 200
        ok(peer.client.post('/v1/auth/logout'))
        assert external(case, token=value['token'], client=peer.client).status_code == 200
    finally:
        peer.client.close()


@pytest.mark.parametrize('authorization', [None, '', 'bearer TOKEN', 'Bearer  TOKEN',
    'Bearer\tTOKEN', 'Basic TOKEN', 'Bearer TOKEN ', 'Bearer TOKEN, Bearer TOKEN',
    'Bearer ti_' + 'a' * 32 + '.' + 'a' * 65],
    ids=['none', 'empty', 'lowercase', 'double-space', 'tab', 'basic', 'trailing-space', 'combined', 'long'])
def test_external_never_uses_cookie_for_missing_or_non_strict_bearer(factory, authorization):
    case = factory()
    value = issued(case)
    headers = [] if authorization is None else [('Authorization', authorization.replace('TOKEN', value['token']))]
    before = snapshot(case)
    response = external(case, headers=headers)
    assert response.status_code == 401
    assert response.headers.get('www-authenticate') == 'Bearer'
    assert 'set-cookie' not in response.headers and snapshot(case) == before


def test_duplicate_authorization_is_rejected_before_any_key_usage(factory):
    case = factory()
    first, second = issued(case), issued(case)
    before = snapshot(case)
    response = external(case, headers=[('Authorization', 'Bearer ' + first['token']),
        ('Authorization', 'Bearer ' + second['token'])])
    assert response.status_code == 401 and response.headers.get('www-authenticate') == 'Bearer'
    assert snapshot(case) == before


@pytest.mark.parametrize('path,method', [('/external', 'GET'), ('/external/v1', 'GET'),
    ('/external/v1/unknown', 'GET'), (SOURCES, 'POST'), (SOURCES, 'HEAD'), (SOURCES, 'OPTIONS')])
def test_external_unknown_path_and_methods_never_create_or_refresh_session(factory, path, method):
    case = factory()
    value = issued(case)
    empty = TestClient(case.app, backend_options={'loop_factory': asyncio.SelectorEventLoop})
    try:
        with case.database.sessions() as db:
            before = db.scalar(select(func.count()).select_from(UserSession))
        response = external(case, path, method=method, token=value['token'], client=empty)
        assert response.status_code in {404, 405}, (path, method, response.status_code)
        assert 'set-cookie' not in response.headers and not empty.cookies
        with case.database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(UserSession)) == before
    finally:
        empty.close()


def test_cookie_is_ignored_and_valid_external_reads_do_not_refresh_session(factory):
    case = factory()
    value = issued(case)
    session_id = case.client.cookies['tire_local_session']
    with case.database.sessions() as db:
        before = utc(db.get(UserSession, session_id).expires_at)
    response = external(case, token=value['token'])
    assert response.status_code == 200 and 'set-cookie' not in response.headers
    with case.database.sessions() as db:
        assert utc(db.get(UserSession, session_id).expires_at) == before


def test_scopes_are_exact_and_external_never_accepts_writes_or_model_calls(factory):
    case = factory()
    sources = issued(case, scopes=['sources:read'])
    hooks = issued(case, scopes=['webhooks:read'])
    assert external(case, DELIVERIES, token=sources['token']).status_code == 403
    assert external(case, token=hooks['token']).status_code == 403
    assert external(case, DELIVERIES, token=hooks['token']).status_code == 200
    for path in ['/external/v1/webhooks', '/external/v1/ai/analysis', '/external/v1/evidence/private']:
        assert external(case, path, token=sources['token'], method='POST').status_code in {404, 405}


def test_sources_closed_projection_order_and_keyset_last_page(factory):
    case = factory()
    value = issued(case)
    cursor, seen = None, []
    while True:
        page = ok(source_page(case, value['token'], limit=2, cursor=cursor))
        assert set(page) == PAGE_FIELDS and page['schema'] == 'external-sources@1'
        assert page['data_state'] == 'local_snapshot' and page['limit'] == 2
        for row in page['items']:
            assert set(row) == SOURCE_FIELDS
            assert all(item is None or isinstance(item, str) for item in row.values())
            seen.append(row['id'])
        forbidden = any(mark in json.dumps(page) for mark in ['https://', 'private_setting', 'R79_NEVER_EXPORT_PRIVATE_SETTING'])
        assert forbidden is False
        cursor = page['next_cursor']
        if cursor is None:
            break
        assert isinstance(cursor, str) and len(cursor) <= 2048
        assert len(seen) < 20
    assert seen == sorted(row['id'] for row in case.registry.catalog)


@pytest.mark.parametrize('query', ['limit=0', 'limit=101', 'limit=true', 'limit=1.0',
    'limit=1&limit=2', 'cursor=a&cursor=b', 'unknown=x', 'token=opaque', 'access_token=opaque',
    'channel=tire_monitor', 'cursor=' + 'x' * 2049],
    ids=['limit0', 'limit101', 'bool', 'float', 'duplicate-limit', 'duplicate-cursor',
         'unknown', 'token-query', 'access-token-query', 'wrong-filter', 'long-cursor'])
def test_sources_strict_queries_and_no_query_token_auth(factory, query):
    case = factory()
    value = issued(case)
    response = external(case, SOURCES + '?' + query, token=value['token'])
    assert response.status_code in {400, 401, 422}, response.status_code


def test_cursor_tamper_wrong_key_wrong_route_or_limit_does_not_replay(factory):
    case = factory()
    first, second = issued(case), issued(case)
    cursor = ok(source_page(case, first['token']))['next_cursor']
    assert cursor
    mutated = cursor[:len(cursor) // 2] + ('a' if cursor[len(cursor) // 2] != 'a' else 'b') + cursor[len(cursor) // 2 + 1:]
    requests = [source_page(case, first['token'], cursor=mutated),
        source_page(case, second['token'], cursor=cursor), source_page(case, first['token'], limit=2, cursor=cursor),
        external(case, DELIVERIES + '?limit=1&cursor=' + cursor, token=first['token'])]
    assert all(response.status_code in {400, 401, 409, 422} for response in requests)


def test_source_cursor_binds_complete_directory_digest(factory):
    case = factory()
    value = issued(case)
    cursor = ok(source_page(case, value['token']))['next_cursor']
    case.registry.catalog[-1]['status'] = 'paused'
    response = source_page(case, value['token'], cursor=cursor)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'external_catalog_changed'
    assert source_page(case, value['token']).status_code == 200


def test_cursor_fixed_fifteen_minutes_does_not_extend_when_advanced(factory, monkeypatch):
    case = factory()
    value = issued(case)
    from tire_api import external_api
    start = utcnow()
    monkeypatch.setattr(external_api, 'utcnow', lambda: start)
    first = ok(source_page(case, value['token']))['next_cursor']
    monkeypatch.setattr(external_api, 'utcnow', lambda: start + timedelta(minutes=14, seconds=59))
    later = ok(source_page(case, value['token'], cursor=first))['next_cursor']
    assert later
    monkeypatch.setattr(external_api, 'utcnow', lambda: start + timedelta(minutes=15, seconds=1))
    assert source_page(case, value['token'], cursor=first).status_code in {400, 401, 409, 422}
    assert source_page(case, value['token'], cursor=later).status_code in {400, 401, 409, 422}


def test_revocation_is_terminal_and_original_create_cannot_resurrect_token(factory):
    case = factory()
    key = str(uuid4())
    value = issued(case, key=key)
    cursor = ok(source_page(case, value['token']))['next_cursor']
    operation(revoke(case, value))
    operation(revoke(case, value))
    operation(create(case, key=key), statuses=(200, 201), replayed=True)
    for path in [SOURCES, SOURCES + '?limit=1&cursor=' + cursor, DELIVERIES]:
        response = external(case, path, token=value['token'])
        assert response.status_code == 401 and response.headers.get('www-authenticate') == 'Bearer'


def test_cursor_does_not_export_raw_owner_identifier(factory):
    case = factory()
    value = issued(case)
    cursor = ok(source_page(case, value['token']))['next_cursor']
    texts = [cursor]
    for part in cursor.split('.'):
        try:
            texts.append(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)).decode('utf-8'))
        except (ValueError, UnicodeError):
            pass
    exposes_owner = any(case.actor['id'] in item for item in texts)
    assert exposes_owner is False, 'cursor_disclosed_raw_owner_identifier'


def test_source_id_eighty_characters_is_legal_and_oversize_field_fails_closed(factory):
    case = factory()
    value = issued(case)
    case.registry.catalog[0]['id'] = 's' * 80
    page = ok(external(case, token=value['token']))
    assert any(item['id'] == 's' * 80 for item in page['items'])
    case.registry.catalog[0]['name'] = 'x' * 501
    assert external(case, token=value['token']).status_code == 409


def test_expired_key_is_unauthorized_without_session_fallback_or_sql_writes(factory, monkeypatch):
    case = factory()
    value = issued(case, expires_in_days=1)
    from tire_api import external_api
    expires = datetime.fromisoformat(value['key']['expires_at'].replace('Z', '+00:00'))
    monkeypatch.setattr(external_api, 'utcnow', lambda: expires)
    before = snapshot(case)
    response = external(case, token=value['token'])
    assert response.status_code == 401 and response.headers.get('www-authenticate') == 'Bearer'
    assert 'set-cookie' not in response.headers and snapshot(case) == before


def test_invalid_key_flood_never_allocates_rate_state_or_session(factory):
    case = factory()
    value = issued(case)
    bad = value['token'][:-1] + ('a' if value['token'][-1] != 'a' else 'b')
    before = snapshot(case)
    for _ in range(65):
        assert external(case, token=bad).status_code == 401
    assert snapshot(case) == before
    assert external(case, token=value['token']).status_code == 200


def test_valid_key_errors_consume_quota_and_restart_does_not_reset_it(factory, monkeypatch):
    case = factory()
    value = issued(case)
    from tire_api import external_api
    start = (utcnow() + timedelta(minutes=2)).replace(second=10, microsecond=0)
    monkeypatch.setattr(external_api, 'utcnow', lambda: start)
    for index in range(59):
        path = SOURCES + '?limit=0' if index % 3 == 0 else '/external/v1/missing' if index % 3 == 1 else DELIVERIES
        # sources-only key scope denied calls are also valid authenticated uses.
        response = external(case, path, token=value['token'], method='POST' if index % 3 == 2 else 'GET')
        assert response.status_code in {404, 405, 422}
    assert external(case, token=value['token']).status_code == 200
    blocked = external(case, token=value['token'])
    assert blocked.status_code == 429 and blocked.headers.get('retry-after') == '50'
    restarted = factory(path=case.storage, login=False)
    assert external(restarted, token=value['token']).status_code == 429
    monkeypatch.setattr(external_api, 'utcnow', lambda: start + timedelta(seconds=50))
    assert external(restarted, token=value['token']).status_code == 200


def test_scope_denial_is_counted_and_other_key_has_independent_quota(factory, monkeypatch):
    case = factory()
    source, other = issued(case, scopes=['sources:read']), issued(case)
    from tire_api import external_api
    now = (utcnow() + timedelta(minutes=2)).replace(second=0, microsecond=0)
    monkeypatch.setattr(external_api, 'utcnow', lambda: now)
    for _ in range(60):
        assert external(case, DELIVERIES, token=source['token']).status_code == 403
    assert external(case, token=source['token']).status_code == 429
    assert external(case, token=other['token']).status_code == 200


def test_rate_sixty_is_atomic_under_concurrent_asgi_requests(factory, monkeypatch):
    case = factory()
    value = issued(case)
    from tire_api import external_api
    now = (utcnow() + timedelta(minutes=2)).replace(second=1, microsecond=0)
    monkeypatch.setattr(external_api, 'utcnow', lambda: now)
    barrier = Barrier(8)
    def request(_index):
        barrier.wait(timeout=30)
        return external(case, token=value['token']).status_code
    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(request, range(64)))
    assert statuses.count(200) == 60 and statuses.count(429) == 4, {status: statuses.count(status) for status in set(statuses)}


def test_concurrent_create_limit_and_same_uuid_do_not_issue_multiple_secrets(factory):
    case = factory()
    for _ in range(15):
        issued(case)
    barrier = Barrier(2)
    def create_one(_index):
        barrier.wait(timeout=30)
        return create(case)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(create_one, range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert len(ok(case.client.get(MANAGE + '?mode=history'))['items']) == 16
    operation(revoke(case, {'key': responses[next(i for i, response in enumerate(responses) if response.status_code == 201)].json()['key']}))
    key = str(uuid4())
    barrier = Barrier(2)
    def duplicate(_index):
        barrier.wait(timeout=30)
        return create(case, key=key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(duplicate, range(2)))
    assert all(response.status_code in {200, 201} for response in responses)
    parsed = [response.json() for response in responses]
    assert sum(isinstance(value['token'], str) for value in parsed) == 1
    assert sum(value['replayed'] is False for value in parsed) == 1
    assert parsed[0]['key']['id'] == parsed[1]['key']['id']


def test_idempotency_conflicts_and_account_scope_are_exact(factory):
    case = factory()
    key = str(uuid4())
    value = issued(case, key=key)
    assert create(case, key=key, name='different').status_code == 409
    assert create(case, key=key, scopes=['sources:read']).status_code == 409
    assert revoke(case, value, key=key).status_code == 409
    other = account(case)
    try:
        created = issued(case, client=other.client, key=key)
        assert created['key']['id'] != value['key']['id']
    finally:
        other.client.close()


def test_active_limit_ignores_expired_and_revoked_but_history_caps_at_one_hundred(factory, monkeypatch):
    case = factory()
    from tire_api import external_api
    first = issued(case, expires_in_days=1)
    now = datetime.fromisoformat(first['key']['expires_at'].replace('Z', '+00:00')) + timedelta(seconds=1)
    monkeypatch.setattr(external_api, 'utcnow', lambda: now)
    # One expired key plus a rolling revoked history never consumes all16 active slots.
    for index in range(101):
        value = issued(case, name='Synthetic history ' + str(index))
        operation(revoke(case, value))
    page = ok(case.client.get(MANAGE + '?mode=history'))
    assert len(page['items']) == 100 and all(row['revoked_at'] for row in page['items'])
    assert first['key']['id'] not in {row['id'] for row in page['items']}


def test_password_reset_revokes_all_target_keys_and_unbinds_target_sessions(factory):
    case = factory()
    target = account(case)
    try:
        first, second = issued(case, client=target.client), issued(case, client=target.client)
        own = issued(case)
        response = case.client.post('/v1/auth/users/' + target.actor['id'] + '/password',
            json={'new_password': secrets.token_urlsafe(18)})
        assert response.status_code == 200
        assert external(case, token=first['token']).status_code == external(case, token=second['token']).status_code == 401
        assert target.client.get(MANAGE + '?mode=history').status_code in {401, 403}
        assert external(case, token=own['token']).status_code == 200
    finally:
        target.client.close()


def test_password_reset_and_key_revocation_roll_back_in_one_transaction(factory):
    case = factory()
    target = account(case)
    try:
        value = issued(case, client=target.client)
        with case.database.sessions() as db:
            before_hash = db.get(User, target.actor['id']).password_hash
            before_sessions = {row.id: row.user_id for row in db.scalars(select(UserSession).where(UserSession.user_id == target.actor['id']))}
        from tire_api.external_api_models import ApiKeyRevocation
        inserts = []
        def fail_revocation(_connection, _cursor, statement, _params, _context, _many):
            if statement.lstrip().lower().startswith('insert into ' + ApiKeyRevocation.__tablename__):
                inserts.append(True)
                raise RuntimeError('synthetic_reset_revocation_failure')
        event.listen(case.database.engine, 'before_cursor_execute', fail_revocation)
        try:
            with pytest.raises(RuntimeError, match='synthetic_reset_revocation_failure'):
                case.client.post('/v1/auth/users/' + target.actor['id'] + '/password',
                    json={'new_password': secrets.token_urlsafe(18)})
        finally:
            event.remove(case.database.engine, 'before_cursor_execute', fail_revocation)
        assert inserts
        with case.database.sessions() as db:
            intact_password = db.get(User, target.actor['id']).password_hash == before_hash
            assert intact_password, 'password_committed_despite_revocation_rollback'
            assert {sid: db.get(UserSession, sid).user_id for sid in before_sessions} == before_sessions
        assert external(case, token=value['token']).status_code == 200
    finally:
        target.client.close()


def test_deleted_account_key_is_never_rebound_when_same_username_registers_again(factory):
    case = factory()
    target = account(case)
    try:
        value = issued(case, client=target.client)
        assert case.client.delete('/v1/auth/users/' + target.actor['id']).status_code == 200
        assert external(case, token=value['token']).status_code == 401
        renewed = register_admin(target.client, target.username, secrets.token_urlsafe(18))['user']
        assert renewed['id'] != target.actor['id']
        assert ok(target.client.get(MANAGE + '?mode=history'))['items'] == []
        assert external(case, token=value['token'], client=target.client).status_code == 401
    finally:
        target.client.close()


def seed_deliveries(case, count=3):
    target = ok(case.client.get('/v1/webhooks/targets'))['items'][0]
    sub = ok(case.client.post('/v1/webhooks', json={'name': 'Synthetic R79 references',
        'target_id': target['id'], 'target_fingerprint': target['policy_fingerprint'],
        'channels': ['tire_monitor'], 'enabled': True, 'acknowledged_external_delivery': True},
        headers={'Idempotency-Key': str(uuid4())}), (201,))['response']
    assert live(case.client).status_code == 200
    assert case.client.post('/v1/alert-rules', json={'name': 'NEVER_EXPORT_PRIVATE_RULE',
        'source_id': 'fixture', 'query': QUERY['query'], 'enabled': True}).status_code == 201
    for _ in range(count):
        produce_delivery(case)
    return sub


def produce_delivery(case):
    case.index += 1
    case.registry.result = success('synthetic-r79-' + str(case.index),
        [{**deepcopy(VARIANT), 'facts': {'utqg_treadwear': 300 + case.index}}])
    assert live(case.client).status_code == 200


def test_delivery_cursor_freezes_membership_upper_bound_but_reads_current_state(factory):
    case = factory()
    sub = seed_deliveries(case)
    value = issued(case)
    from tire_api.webhook_models import WebhookEnvelope
    with case.database.sessions() as db:
        expected = [row.id for row in db.scalars(select(WebhookEnvelope).order_by(WebhookEnvelope.created_at, WebhookEnvelope.id))]
    first = ok(external(case, DELIVERIES + '?limit=1', token=value['token']))
    assert set(first) == PAGE_FIELDS and first['schema'] == 'external-webhook-deliveries@1'
    assert first['items'][0]['id'] == expected[0] and first['next_cursor']
    produce_delivery(case)
    cancel = case.client.post('/v1/webhooks/' + sub['id'] + '/deliveries/' + expected[-1] + '/cancel',
        json={'expected_attempts': 0, 'acknowledged': True}, headers={'Idempotency-Key': str(uuid4())})
    assert cancel.status_code == 200
    cursor, seen, states = first['next_cursor'], [expected[0]], {}
    while cursor:
        page = ok(case.client.get(DELIVERIES, params={'limit': '1', 'cursor': cursor},
            headers={'Authorization': 'Bearer ' + value['token']}))
        seen.extend(row['id'] for row in page['items'])
        states.update({row['id']: row['state'] for row in page['items']})
        cursor = page['next_cursor']
    assert seen == expected and states[expected[-1]] == 'cancelled'
    fresh = ok(external(case, DELIVERIES, token=value['token']))
    assert len(fresh['items']) == 4


def test_delivery_owner_is_permanent_even_when_cookie_session_rebinds(factory):
    case = factory()
    seed_deliveries(case, 1)
    own = issued(case)
    same = account(case, same=True)
    other = account(case)
    try:
        assert len(ok(same.client.get(MANAGE + '?mode=history'))['items']) == 1
        other_key = issued(case, client=other.client)
        ok(case.client.post('/v1/auth/logout'))
        ok(case.client.post('/v1/auth/login', json={'username': other.username, 'password': other.password}))
        assert ok(case.client.get(MANAGE + '?mode=history'))['items'][0]['id'] == other_key['key']['id']
        own_page = ok(external(case, DELIVERIES, token=own['token']))
        other_page = ok(external(case, DELIVERIES, token=other_key['token']))
        assert len(own_page['items']) == 1 and other_page['items'] == []
        delivery_id = own_page['items'][0]['id']
        assert external(case, DELIVERIES + '/' + delivery_id, token=other_key['token']).status_code == 404
        detail = ok(external(case, DELIVERIES + '/' + delivery_id, token=own['token']))
        assert detail['schema'] == 'webhook-delivery@1' and detail['current'] is False
        forbidden = any(mark in json.dumps(detail) for mark in [case.actor['id'], other.actor['id'],
            'NEVER_EXPORT_PRIVATE_RULE', 'utqg_treadwear', 'Fixture Brand', 'https://'])
        assert forbidden is False
    finally:
        same.client.close()
        other.client.close()


def test_delivery_cursor_filters_and_cross_account_cursor_are_bound(factory):
    case = factory()
    sub = seed_deliveries(case)
    own = issued(case)
    first = ok(external(case, DELIVERIES + '?limit=1&channel=tire_monitor&webhook_id=' + sub['id'], token=own['token']))
    cursor = first['next_cursor']
    assert cursor
    requests = [case.client.get(DELIVERIES, params=params, headers={'Authorization': 'Bearer ' + own['token']})
        for params in [
            {'limit': 1, 'cursor': cursor},
            {'limit': 1, 'cursor': cursor, 'channel': 'interest', 'webhook_id': sub['id']},
            {'limit': 1, 'cursor': cursor, 'channel': 'tire_monitor', 'webhook_id': 'other'}]]
    assert all(response.status_code in {400, 401, 409, 422} for response in requests)
    other = account(case)
    try:
        key = issued(case, client=other.client)
        response = other.client.get(DELIVERIES, params={'limit': 1, 'cursor': cursor,
            'channel': 'tire_monitor', 'webhook_id': sub['id']}, headers={'Authorization': 'Bearer ' + key['token']})
        assert response.status_code in {400, 401, 409, 422}
    finally:
        other.client.close()


def test_security_headers_apply_to_success_management_and_external_errors(factory, monkeypatch):
    case = factory()
    created = create(case)
    value = operation(created, statuses=(201,), token=True)
    responses = [created, case.client.get(MANAGE + '?mode=history'),
        external(case, token=value['token']), external(case),
        external(case, '/external/v1/missing', token=value['token']),
        external(case, SOURCES + '?limit=0', token=value['token']),
        external(case, token=value['token'], method='POST')]
    for response in responses:
        assert response.headers.get('cache-control') == 'no-store'
        assert response.headers.get('x-content-type-options') == 'nosniff'


def schema_snapshot(database):
    with database.engine.connect() as connection:
        schema = [tuple(row) for row in connection.execute(text(
            'SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name,tbl_name'))]
        tables = {row[1] for row in schema if row[0] == 'table' and not row[1].startswith('sqlite_')}
        rows = {}
        for name in sorted(tables):
            values = connection.execute(text('SELECT * FROM "' + name.replace('"', '""') + '"')).all()
            encoded = json.dumps(sorted([list(row) for row in values], key=repr), default=str,
                ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            rows[name] = (len(values), hashlib.sha256(encoded).hexdigest())
        versions = connection.execute(text('SELECT version FROM tire_schema_versions ORDER BY version')).scalars().all()
        return {'schema': schema, 'tables': tables, 'rows': rows, 'versions': versions}


@pytest.fixture
def predecessor(factory, monkeypatch):
    """Synthetic current-shape/pre023-ledger fixture, not a physical023 backup."""
    case = factory()
    from tire_api.db import Base, Database
    from tire_api.knowledge_models import initialize_search
    from test_identity_migration import seed_legacy
    from version_registry import EXPECTED_SCHEMA_VERSIONS
    assert EXPECTED_SCHEMA_VERSIONS[21:23] == ['022_webhook_delivery', '023_external_api_keys']
    url = 'sqlite:///' + (case.storage / 'pre023.db').as_posix()
    monkeypatch.setenv('TIRE_DATABASE_URL', url)
    monkeypatch.setenv('DATABASE_URL', url)
    database = Database(url)
    new_tables = {'external_api_keys', 'external_api_key_revocations',
        'external_api_key_operations', 'external_api_key_minutes'}
    with database.engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables
            if table.name not in new_tables])
        connection.exec_driver_sql('CREATE TABLE tire_schema_versions '
            '(version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version in EXPECTED_SCHEMA_VERSIONS[:22]:
            connection.execute(text('INSERT INTO tire_schema_versions (version) VALUES (:version)'), {'version': version})
        initialize_search(connection)
    with database.sessions() as db:
        seed_legacy(db, namespace='SYNTHETIC-R79', product_code='SYNTHETIC-PRE023', watch=True)
    yield database, new_tables
    database.close()


def test_023_migration_preserves_predecessor_ddl_rows_and_is_idempotent(predecessor):
    from historical_migration_support import (assert_target_delta, initialize_observing_version,
                                               snapshot_connection)
    from version_registry import EXPECTED_SCHEMA_VERSIONS
    database, new_tables = predecessor
    before = schema_snapshot(database)
    assert not new_tables & before['tables'] and len(before['versions']) == 22
    with database.engine.connect() as connection:
        before_stage = snapshot_connection(connection)
    stage = initialize_observing_version(database, '023_external_api_keys')
    assert_target_delta(before_stage, stage, new_tables)
    first = schema_snapshot(database)
    database.initialize()
    after = schema_snapshot(database)
    assert first == after
    assert after['tables'] - before['tables'] == new_tables
    assert not before['tables'] - after['tables']
    assert [row for row in after['schema'] if row[2] in before['tables']] == [row for row in before['schema'] if row[2] in before['tables']]
    assert after['versions'] == EXPECTED_SCHEMA_VERSIONS
    for table in before['tables'] - {'tire_schema_versions'}:
        assert after['rows'][table] == before['rows'][table], table
    assert all(after['rows'][table][0] == 0 for table in new_tables)
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA integrity_check').scalar_one() == 'ok'
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []


def test_023_migration_failure_rolls_back_new_tables_triggers_and_version(predecessor, monkeypatch):
    database, new_tables = predecessor
    from tire_api import migrations
    before = schema_snapshot(database)
    original = migrations.upgrade
    def failed(connection):
        original(connection)
        raise RuntimeError('synthetic_r79_migration_failure')
    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'upgrade', failed)
        with pytest.raises(RuntimeError, match='synthetic_r79_migration_failure'):
            database.initialize()
    assert schema_snapshot(database) == before
    database.initialize()
    assert schema_snapshot(database)['tables'] - before['tables'] == new_tables


