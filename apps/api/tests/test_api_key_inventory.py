"""R80 real ASGI/SQL inventory checks, with private fixture values kept opaque."""
import asyncio
from datetime import timedelta
import hashlib
import os
from pathlib import Path
import secrets
from uuid import uuid4

import pytest

if not os.environ.get('R80_TEST_STORAGE_ROOT') or os.environ.get('TIRE_DATABASE_URL') != os.environ.get('DATABASE_URL'):
    raise RuntimeError('r80_private_runner_required')

from fastapi.testclient import TestClient
from sqlalchemy import event, select
from test_external_api import case, created
from tire_api.db import utc, utcnow
from tire_api.external_api_models import ApiKey, ApiKeyRevocation
from tire_api.webhook_delivery import seal


ACTIVE = '/v1/api-keys/active?mode=history'
HISTORY = '/v1/api-key-history?mode=history'


def headers(case):
    return {'X-Tire-Expected-Account': case.user['id']}


def get(case, path, client=None):
    return (client or case.client).get(path, headers=headers(case))


def revoke(case, key_id):
    response = case.client.post('/v1/api-keys/' + key_id + '/revoke', json={'acknowledged': True},
        headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 200
    return response.json()['key']


def test_101_new_revoked_records_hide_old_key_only_in_legacy_list(case):
    old = created(case)['key']
    issued = {old['id']}
    for _ in range(101):
        key = created(case)['key']
        issued.add(key['id'])
        revoke(case, key['id'])
    legacy = case.client.get('/v1/api-keys?mode=history').json()['items']
    assert len(legacy) == 100 and old['id'] not in {row['id'] for row in legacy}
    active = get(case, ACTIVE)
    assert active.status_code == 200
    assert [row['id'] for row in active.json()['items']] == [old['id']]
    found, cursor, window = [], None, None
    while True:
        path = HISTORY + '&limit=37' + ('&cursor=' + cursor if cursor else '')
        response = get(case, path)
        assert response.status_code == 200
        body = response.json()
        if window is None:
            window = body['window_started_at']
        assert body['window_started_at'] == window
        found.extend(row['id'] for row in body['items'])
        cursor = body['next_cursor']
        if cursor is None:
            break
    assert len(found) == len(set(found)) == len(issued) == 102
    assert set(found) == issued
    assert found[-1] == old['id']
    revoke(case, old['id'])
    assert get(case, ACTIVE).json()['items'] == []


@pytest.mark.parametrize('path', [ACTIVE, HISTORY])
def test_expected_account_is_required_before_query_but_never_authenticates(case, path):
    assert case.client.get(path).status_code == 422
    assert case.client.get(path + '&unknown=1', headers={'X-Tire-Expected-Account': 'different'}).status_code == 409
    assert case.client.get(path, headers=[('X-Tire-Expected-Account', case.user['id']),
        ('X-Tire-Expected-Account', case.user['id'])]).status_code == 422
    assert case.client.get(path, headers={'X-Tire-Expected-Account': 'bad value'}).status_code == 422
    anonymous = TestClient(case.app, backend_options={'loop_factory': asyncio.SelectorEventLoop})
    try:
        assert anonymous.get(path, headers=headers(case)).status_code == 401
    finally:
        anonymous.close()


@pytest.mark.parametrize('path', [ACTIVE + '&limit=1', ACTIVE + '&mode=history', ACTIVE.replace('history', 'live'),
    '/v1/api-keys/active', HISTORY + '&unknown=1', HISTORY + '&limit=true', HISTORY + '&limit=0',
    HISTORY + '&limit=101', HISTORY + '&limit=1&limit=2'])
def test_inventory_query_is_closed_and_strict(case, path):
    response = get(case, path)
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'api_key_inventory_query_invalid'


def test_empty_inventory_and_history_have_no_cursor(case):
    active = get(case, ACTIVE).json()
    history = get(case, HISTORY).json()
    assert set(active) == {'schema', 'items', 'read_at'} and active['items'] == []
    assert set(history) == {'schema', 'items', 'limit', 'next_cursor', 'window_started_at', 'read_at'}
    assert history['items'] == [] and history['next_cursor'] is None
    assert history['window_started_at'] == history['read_at']


def test_active_overflow_is_rejected_without_silent_truncation(case):
    for _ in range(16):
        created(case)
    now = utcnow()
    with case.database.sessions() as db:
        db.add(seal(ApiKey(id=secrets.token_hex(16), owner_user_id=case.user['id'], name='Synthetic overflow',
            scopes=['sources:read'], bearer_sha256=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
            cursor_secret=secrets.token_hex(32), created_at=now, expires_at=now + timedelta(days=1))))
        db.commit()
    response = get(case, ACTIVE)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'api_key_active_limit_invalid'
    assert len(get(case, HISTORY + '&limit=100').json()['items']) == 17


def test_cursor_anchor_survives_revocation_expiry_and_same_owner_other_session(case, monkeypatch):
    from tire_api import api_key_inventory
    for _ in range(3):
        created(case, expires_in_days=1)
    with case.database.sessions() as db:
        anchor = db.scalar(select(ApiKey).order_by(ApiKey.created_at.desc(), ApiKey.id.desc()).limit(1))
        now = utc(anchor.expires_at) - timedelta(seconds=100)
    monkeypatch.setattr(api_key_inventory, 'utcnow', lambda: now)
    first = get(case, HISTORY + '&limit=1').json()
    revoke(case, first['items'][0]['id'])
    now += timedelta(seconds=200)
    other = TestClient(case.app, backend_options={'loop_factory': asyncio.SelectorEventLoop})
    try:
        assert other.post('/v1/auth/login', json={'username': 'r79-owner', 'password': case.password}).status_code == 200
        second = get(case, HISTORY + '&limit=1&cursor=' + first['next_cursor'], client=other)
        assert second.status_code == 200
        assert second.json()['window_started_at'] == first['window_started_at']
        assert second.json()['next_cursor'] is not None
        now += timedelta(seconds=700)
        expired = get(case, HISTORY + '&limit=1&cursor=' + second.json()['next_cursor'], client=other)
        assert expired.status_code == 409
        assert expired.json()['detail']['code'] == 'api_key_history_cursor_expired'
    finally:
        other.close()


def test_new_issuance_is_outside_history_window_and_cursor_is_limit_bound(case):
    issued = [created(case)['key']['id'] for _ in range(4)]
    first = get(case, HISTORY + '&limit=2').json()
    newer = created(case)['key']['id']
    cursor = first['next_cursor']
    assert get(case, HISTORY + '&limit=1&cursor=' + cursor).status_code == 422
    page = get(case, HISTORY + '&limit=2&cursor=' + cursor).json()
    found = [row['id'] for row in first['items'] + page['items']]
    assert set(found) == set(issued) and newer not in found
    assert page['next_cursor'] is None
    assert get(case, HISTORY + '&limit=2&cursor=' + cursor[:-1] + ('A' if cursor[-1] != 'A' else 'B')).status_code == 422


def test_active_projection_uses_one_joined_read_even_if_revoked_after_select(case):
    key = created(case)['key']
    seen = []
    injected = False
    def revoke_after_select(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal injected
        if ('SELECT' in statement.upper() and 'LEFT OUTER JOIN external_api_key_revocations' in statement
                and 'FROM external_api_keys' in statement):
            seen.append(statement)
            if not injected:
                injected = True
                with case.database.sessions() as db:
                    db.add(seal(ApiKeyRevocation(key_id=key['id'], revoked_at=utcnow(), reason='owner_revoke')))
                    db.commit()
    event.listen(case.database.engine, 'after_cursor_execute', revoke_after_select)
    try:
        response = get(case, ACTIVE)
    finally:
        event.remove(case.database.engine, 'after_cursor_execute', revoke_after_select)
    assert response.status_code == 200
    assert len(seen) == 1
    assert response.json()['items'][0]['revoked_at'] is None
    assert get(case, ACTIVE).json()['items'] == []
