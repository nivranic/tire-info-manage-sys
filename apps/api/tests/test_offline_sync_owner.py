"""Background device synchronization cannot bootstrap or switch its HTTP owner."""
from copy import deepcopy
from datetime import timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from tire_api.db import UserSession, uid, utcnow
from tire_api.main import SESSION_COOKIE
from test_garage import PROFILE
from test_offline_packs import EMPTY_SCOPE, confirm, download, plan, setup
from test_offline_updates import ENDPOINT, stored_counts


OWNER_HEADER = 'X-Tire-Offline-Owner-Scope'


def headers(owner):
    return {'X-Tire-Offline-Sync': '1', 'X-Tire-Offline-Expected-Owner': owner}


def session_count(database):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(UserSession))


def payload(base, scope=EMPTY_SCOPE):
    return {'mode': 'history', 'base_pack_id': base['id'],
        'expected_base_sha256': base['sha256'], 'scope': scope}


@pytest.mark.parametrize('session_state', ['missing', 'unknown', 'expired'])
def test_marked_missing_unknown_or_expired_cookie_returns_401_without_bootstrap(setup, session_state):
    client, _, database = setup
    base = confirm(client, plan(client, EMPTY_SCOPE)).json()
    before_sessions, before_data = session_count(database), stored_counts(database)
    marked = TestClient(client.app)
    if session_state == 'unknown':
        marked.cookies.set(SESSION_COOKIE, uid())
    elif session_state == 'expired':
        marked.cookies.update(client.cookies)
        with database.sessions() as db:
            row = db.get(UserSession, client.cookies.get(SESSION_COOKIE))
            row.expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
    response = marked.post(ENDPOINT, headers=headers(base['owner_scope_id']), json=payload(base))
    assert response.status_code == 401, response.text
    assert response.json()['detail']['code'] == 'offline_sync_session_required'
    assert 'set-cookie' not in response.headers
    assert response.headers['cache-control'] == 'no-store'
    assert session_count(database) == before_sessions
    assert stored_counts(database) == before_data


@pytest.mark.parametrize('route', ['prepare', 'confirm', 'descriptor', 'download'])
def test_marked_owner_mismatch_rejects_before_endpoint_and_writes_nothing(setup, monkeypatch, route):
    client, _, database = setup
    prepared = plan(client, EMPTY_SCOPE)
    base = confirm(client, prepared).json()
    before_sessions, before_data = session_count(database), stored_counts(database)
    import tire_api.offline_packs as module
    def forbidden(*args, **kwargs):
        raise AssertionError('Owner fence must reject before invoking any offline endpoint')
    monkeypatch.setattr(module, 'prepare_update', forbidden)
    monkeypatch.setattr(module, 'confirm_plan', forbidden)
    monkeypatch.setattr(module, 'owned', forbidden)
    request_headers = headers('0' * 64)
    if route == 'prepare':
        response = client.post(ENDPOINT, headers=request_headers, json=payload(base))
    elif route == 'confirm':
        response = client.post('/v1/offline-packs', headers={**request_headers, 'Idempotency-Key': uid()},
            json={'plan_id': prepared['id'], 'expected_fingerprint': prepared['fingerprint'],
                'allow_device_storage': True})
    else:
        path = '/v1/offline-packs/' + base['id'] + ('/download' if route == 'download' else '')
        response = client.get(path + '?mode=history', headers=request_headers)
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'offline_sync_owner_mismatch'
    assert response.headers[OWNER_HEADER] == base['owner_scope_id']
    assert 'set-cookie' not in response.headers
    assert session_count(database) == before_sessions
    assert stored_counts(database) == before_data


@pytest.mark.parametrize('request_headers', [
    {'X-Tire-Offline-Sync': '1'}, {'X-Tire-Offline-Expected-Owner': '0' * 64},
    {'X-Tire-Offline-Sync': '0', 'X-Tire-Offline-Expected-Owner': '0' * 64},
    {'X-Tire-Offline-Sync': 'true', 'X-Tire-Offline-Expected-Owner': '0' * 64},
    {'X-Tire-Offline-Sync': '1', 'X-Tire-Offline-Expected-Owner': 'A' * 64},
    {'X-Tire-Offline-Sync': '1', 'X-Tire-Offline-Expected-Owner': '0' * 63},
    [('X-Tire-Offline-Sync', '1'), ('X-Tire-Offline-Sync', '1'), ('X-Tire-Offline-Expected-Owner', '0' * 64)],
    [('X-Tire-Offline-Sync', '1'), ('X-Tire-Offline-Expected-Owner', '0' * 64),
        ('X-Tire-Offline-Expected-Owner', '0' * 64)],
])
def test_invalid_or_duplicate_marker_headers_reject_without_bootstrap(setup, request_headers):
    client, _, database = setup
    before = session_count(database)
    response = TestClient(client.app).post(ENDPOINT, headers=request_headers, json={})
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'offline_sync_headers_invalid'
    assert 'set-cookie' not in response.headers
    assert session_count(database) == before


@pytest.mark.parametrize('method,path', [
    ('GET', '/health'), ('GET', '/v1/observability'), ('POST', '/v1/sources/fixture/live-query'),
    ('POST', '/v1/offline-pack-plans'), ('GET', '/v1/offline-packs?mode=history'),
    ('GET', '/v1/offline-pack-plans/missing?mode=history'),
    ('PUT', '/v1/offline-packs/missing?mode=history'),
    ('GET', '/v1/offline-packs/missing?mode=live'),
    ('GET', '/v1/offline-packs/missing'),
    ('GET', '/v1/offline-packs/missing/download?mode=history&mode=live'),
])
def test_marker_is_limited_to_fixed_sync_routes_and_history_descriptors(setup, method, path):
    client, registry, database = setup
    before_sessions, before_data, before_calls = session_count(database), stored_counts(database), len(registry.calls)
    response = TestClient(client.app).request(method, path, headers=headers('0' * 64))
    assert response.status_code == 400, response.text
    assert response.json()['detail']['code'] == 'offline_sync_route_invalid'
    assert 'set-cookie' not in response.headers
    assert session_count(database) == before_sessions and stored_counts(database) == before_data
    assert len(registry.calls) == before_calls


def test_legal_marked_prepare_confirm_descriptor_and_download_keep_same_authority(setup):
    client, _, database = setup
    base = confirm(client, plan(client, EMPTY_SCOPE)).json()
    before_sessions = session_count(database)
    client.post('/v1/garage', json=deepcopy(PROFILE))
    scope = deepcopy(EMPTY_SCOPE)
    scope['garage']['include'] = True
    owner = base['owner_scope_id']
    request_headers = headers(owner)
    response = client.post(ENDPOINT, headers=request_headers, json=payload(base, scope))
    assert response.status_code == 200, response.text
    assert response.headers[OWNER_HEADER] == owner and response.json()['state'] == 'planned'
    prepared = response.json()['plan']
    response = client.post('/v1/offline-packs', headers={**request_headers, 'Idempotency-Key': uid()},
        json={'plan_id': prepared['id'], 'expected_fingerprint': prepared['fingerprint'],
            'allow_device_storage': True})
    assert response.status_code == 201, response.text
    assert response.headers[OWNER_HEADER] == owner
    descriptor = response.json()
    response = client.get('/v1/offline-packs/' + descriptor['id'] + '?mode=history', headers=request_headers)
    assert response.status_code == 200 and response.headers[OWNER_HEADER] == owner
    assert response.json() == descriptor
    response = client.get(descriptor['download_path'], headers=request_headers)
    assert response.status_code == 200 and response.headers[OWNER_HEADER] == owner
    assert response.content == download(client, descriptor)[0]
    assert session_count(database) == before_sessions


def test_cors_allows_sync_headers_uuid_confirmation_and_exposes_owner_authority(setup):
    client, _, _ = setup
    response = client.options(ENDPOINT, headers={'Origin': 'http://localhost:3000',
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'content-type,idempotency-key,x-tire-offline-sync,x-tire-offline-expected-owner'})
    assert response.status_code == 200, response.text
    allowed = {value.strip().lower() for value in response.headers['access-control-allow-headers'].split(',')}
    assert {'content-type', 'idempotency-key', 'x-tire-offline-sync', 'x-tire-offline-expected-owner'} <= allowed
    base = confirm(client, plan(client, EMPTY_SCOPE)).json()
    response = client.post(ENDPOINT, headers={**headers(base['owner_scope_id']), 'Origin': 'http://localhost:3000'},
        json=payload(base))
    assert response.status_code == 200, response.text
    assert OWNER_HEADER.lower() in response.headers['access-control-expose-headers'].lower()
    assert response.headers[OWNER_HEADER] == base['owner_scope_id']


def test_ordinary_requests_keep_existing_bootstrap_behavior_without_owner_header(setup):
    client, _, database = setup
    before = session_count(database)
    fresh = TestClient(client.app)
    response = fresh.get('/health')
    assert response.status_code == 200 and 'set-cookie' in response.headers
    assert OWNER_HEADER not in response.headers
    assert session_count(database) == before + 1
