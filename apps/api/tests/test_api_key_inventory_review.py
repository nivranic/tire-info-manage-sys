"""Independent R80 cookie-bound inventory contracts on GUID private SQLite.

Run exclusively through the R80 prebound, network-denying target runner.
Secrets have safe repr and never form expected DTOs or written evidence.
"""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from uuid import uuid4

import pytest

_PRIVATE = os.environ.get('R80_TEST_STORAGE_ROOT')
if not _PRIVATE or not os.environ.get('TIRE_DATABASE_URL', '').startswith(
        'sqlite:///' + Path(_PRIVATE).as_posix() + '/'):
    raise RuntimeError('r80_review_private_harness_required_before_product_import')

from sqlalchemy import event, select, text
from tire_api.db import User, UserSession, utc, utcnow
from tire_api.external_api_models import ApiKey, ApiKeyRevocation
from tire_api.webhook_delivery import seal
from test_external_api_review import (PrivateText, account, factory, issued,
    ok, operation, revoke, snapshot, KEY_FIELDS)

ACTIVE = '/v1/api-keys/active'
HISTORY = '/v1/api-key-history'
HEADER = 'X-Tire-Expected-Account'
ACTIVE_FIELDS = {'schema', 'items', 'read_at'}
PAGE_FIELDS = {'schema', 'items', 'limit', 'next_cursor', 'window_started_at', 'read_at'}


def instant(value):
    assert isinstance(value, str)
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    assert result.tzinfo is not None
    return result.astimezone(timezone.utc)


def read(case, path=HISTORY, *, client=None, owner=None, headers=None, params=None):
    return (client or case.client).get(path, headers=headers if headers is not None else {
        HEADER: owner or case.actor['id']}, params={'mode': 'history', **(params or {})})


def error(response, status, code=None):
    assert response.status_code == status, ('unexpected_inventory_status', response.status_code)
    body = response.json()
    if code is not None:
        assert body.get('detail', {}).get('code') == code
    assert response.headers.get('cache-control') == 'no-store'
    assert response.headers.get('x-content-type-options') == 'nosniff'


def records(body, *, active=False):
    assert set(body) == (ACTIVE_FIELDS if active else PAGE_FIELDS)
    assert body['schema'] == ('active-api-keys@1' if active else 'api-key-history@1')
    at = instant(body['read_at'])
    assert isinstance(body['items'], list)
    if not active:
        assert type(body['limit']) is int and 1 <= body['limit'] <= 100
        assert len(body['items']) <= body['limit']
        assert instant(body['window_started_at']) <= at
        assert body['next_cursor'] is None or (isinstance(body['next_cursor'], str)
            and 0 < len(body['next_cursor']) <= 2048)
    for row in body['items']:
        assert set(row) == KEY_FIELDS and row['schema'] == 'api-key@1'
        assert re.fullmatch(r'[a-f0-9]{32}', row['id'])
        assert instant(row['created_at']) < instant(row['expires_at'])
        if row['revoked_at'] is not None:
            instant(row['revoked_at'])
        if active:
            assert row['revoked_at'] is None and instant(row['expires_at']) > at
    order = [(instant(v['created_at']), v['id']) for v in body['items']]
    assert order == sorted(order, reverse=True) and len({v['id'] for v in body['items']}) == len(order)
    return body


def page(case, **params):
    return records(ok(read(case, params=params)))


def all_pages(case, limit=7, first=None):
    result, cursors = [], set()
    value = first or page(case, limit=limit)
    window = value['window_started_at']
    for _ in range(150):
        assert value['window_started_at'] == window and value['limit'] == limit
        result.extend(value['items'])
        cursor = value['next_cursor']
        if cursor is None:
            break
        assert cursor not in cursors
        cursors.add(cursor)
        value = page(case, limit=limit, cursor=cursor)
    else:
        pytest.fail('history_cursor_did_not_terminate')
    assert len({v['id'] for v in result}) == len(result)
    assert [(instant(v['created_at']), v['id']) for v in result] == sorted(
        [(instant(v['created_at']), v['id']) for v in result], reverse=True)
    return result


def seeded(case, count=4):
    return [issued(case, name='合成库存-' + str(n)) for n in range(count)]


def cursor_parts(cursor):
    parts = cursor.split('.')
    assert len(parts) == 2
    raw = base64.urlsafe_b64decode(parts[0] + '=' * (-len(parts[0]) % 4))
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload, raw, parts[1]


def test_empty_inventory_has_closed_empty_shapes_and_no_cursor(factory):
    case = factory()
    active = records(ok(read(case, ACTIVE)), active=True)
    history = page(case)
    assert active['items'] == history['items'] == [] and history['next_cursor'] is None


def test_http_issuance_101_newer_revocations_cannot_hide_old_valid_keys(factory):
    case = factory()
    oldest = seeded(case, 2)
    values = list(oldest)
    for n in range(101):
        value = issued(case, name='已撤销合成历史-' + str(n))
        operation(revoke(case, value))
        values.append(value)
    old_ids = {v['key']['id'] for v in oldest}
    legacy = ok(case.client.get('/v1/api-keys?mode=history'))
    assert len(legacy['items']) == 100 and old_ids.isdisjoint({v['id'] for v in legacy['items']})
    active = records(ok(read(case, ACTIVE)), active=True)
    assert {v['id'] for v in active['items']} == old_ids
    history = all_pages(case)
    assert {v['id'] for v in history} == {v['key']['id'] for v in values}
    operation(revoke(case, oldest[0]))
    assert {v['id'] for v in records(ok(read(case, ACTIVE)), active=True)['items']} == {oldest[1]['key']['id']}


@pytest.mark.parametrize('limit', [1, 4, 100])
def test_same_microsecond_rows_use_id_tie_break_and_finish_without_gaps(factory, monkeypatch, limit):
    from tire_api import external_api, api_key_inventory
    case = factory()
    now = utcnow().replace(microsecond=123456)
    monkeypatch.setattr(external_api, 'utcnow', lambda: now)
    monkeypatch.setattr(api_key_inventory, 'utcnow', lambda: now)
    values = seeded(case, 12)
    result = all_pages(case, limit)
    expected = sorted([v['key'] for v in values], key=lambda v: (instant(v['created_at']), v['id']), reverse=True)
    assert result == expected
    assert all(instant(v['created_at']).microsecond == 123456 for v in result)


@pytest.mark.parametrize('path', [ACTIVE, HISTORY])
@pytest.mark.parametrize('kind', ['missing', 'empty', 'space', 'punctuation', 'too_long', 'duplicate_same', 'duplicate_other'])
def test_expected_account_header_is_single_closed_and_required(factory, path, kind):
    case = factory(); actor = case.actor['id']
    headers = {'missing': [], 'empty': [(HEADER, '')], 'space': [(HEADER, 'a b')],
        'punctuation': [(HEADER, '../owner')], 'too_long': [(HEADER, 'a' * 65)],
        'duplicate_same': [(HEADER, actor), (HEADER.lower(), actor)],
        'duplicate_other': [(HEADER, actor), (HEADER, 'other')]}[kind]
    error(read(case, path, headers=headers), 422, 'api_key_expected_account_invalid')


@pytest.mark.parametrize('path', [ACTIVE, HISTORY])
def test_cookie_authority_precedes_header_query_and_header_is_not_credential(factory, path):
    case = factory(login=False)
    error(case.client.get(path + '?wrong=1', headers={HEADER: 'invented-owner'}), 401, 'api_key_login_required')
    case = factory()
    error(read(case, path, owner='not-this-owner', params={'wrong': '1'}), 409, 'api_key_owner_changed')
    error(read(case, path, headers=[], params={'wrong': '1'}), 422, 'api_key_expected_account_invalid')
    value = issued(case)
    response = read(case, path, headers={HEADER: case.actor['id'], 'Authorization': 'Bearer ' + value['token']})
    assert response.status_code in {401, 403}, 'bearer_must_not_enter_cookie_inventory'


@pytest.mark.parametrize('path,query', [
    (ACTIVE, ''), (HISTORY, ''), (ACTIVE, 'mode=live'), (HISTORY, 'mode=live'),
    (ACTIVE, 'mode=history&mode=history'), (HISTORY, 'mode=history&mode=history'),
    (ACTIVE, 'mode=history&limit=1'), (ACTIVE, 'mode=history&cursor=x'),
    (HISTORY, 'mode=history&unknown=1'), (HISTORY, 'mode=history&limit=0'),
    (HISTORY, 'mode=history&limit=101'), (HISTORY, 'mode=history&limit=-1'),
    (HISTORY, 'mode=history&limit=1.0'), (HISTORY, 'mode=history&limit=1&limit=1'),
    (HISTORY, 'mode=history&cursor=x&cursor=x'),
])
def test_inventory_queries_are_closed_and_have_exact_mode(factory, path, query):
    case = factory()
    error(case.client.get(path + ('?' + query if query else ''), headers={HEADER: case.actor['id']}),
        422, 'api_key_inventory_query_invalid')


def test_expired_session_and_deleted_user_cannot_read_before_query_validation(factory):
    case = factory(); issued(case)
    with case.database.sessions.begin() as db:
        db.get(UserSession, case.client.cookies['tire_local_session']).expires_at = utcnow() - timedelta(seconds=1)
    error(read(case, params={'limit': 'bad'}), 401, 'api_key_login_required')
    case = factory(); issued(case)
    with case.database.sessions.begin() as db:
        db.delete(db.get(User, case.actor['id']))
    error(read(case), 401, 'api_key_login_required')


def test_cursor_continues_across_same_owner_session_but_not_cookie_rebind(factory):
    case = factory(); seeded(case)
    first = page(case, limit=1)
    same = account(case, same=True)
    try:
        answer = records(ok(read(case, client=same.client, params={'limit': 1, 'cursor': first['next_cursor']})))
        assert answer['items'][0]['id'] != first['items'][0]['id']
    finally:
        same.client.close()
    other = account(case)
    try:
        error(read(case, client=other.client, owner=other.actor['id'], params={'limit': 1, 'cursor': first['next_cursor']}),
            422, 'api_key_history_cursor_invalid')
        with case.database.sessions.begin() as db:
            db.get(UserSession, case.client.cookies['tire_local_session']).user_id = other.actor['id']
        error(read(case, params={'limit': 1, 'cursor': first['next_cursor']}), 409, 'api_key_owner_changed')
        error(read(case, owner=other.actor['id'], params={'limit': 1, 'cursor': first['next_cursor']}),
            422, 'api_key_history_cursor_invalid')
    finally:
        other.client.close()


def test_anchor_revocation_and_expiry_do_not_invalidate_history_and_no_key_rate_write(factory, monkeypatch):
    from tire_api import api_key_inventory
    case = factory(); values = seeded(case)
    first = page(case, limit=1); anchor = first['items'][0]['id']
    original = next(v for v in values if v['key']['id'] == anchor)
    operation(revoke(case, original))
    assert page(case, limit=1, cursor=first['next_cursor'])['items']
    when = instant(original['key']['expires_at']) + timedelta(seconds=1)
    # Sign a fresh window after the anchor has expired, then continue it. Its signing
    # key must be treated as an immutable anchor rather than a valid Bearer.
    monkeypatch.setattr(api_key_inventory, 'utcnow', lambda: when)
    first = page(case, limit=1)
    before = {k:v for k,v in snapshot(case).items() if k.startswith('external_api_')}
    result = all_pages(case, 1, first)
    assert {v['id'] for v in result} == {v['key']['id'] for v in values}
    assert records(ok(read(case, ACTIVE)), active=True)['items'] == []
    after = {k:v for k,v in snapshot(case).items() if k.startswith('external_api_')}
    assert before == after


def test_existing_cursor_survives_anchor_expiring_inside_its_original_ttl(factory, monkeypatch):
    from tire_api import external_api, api_key_inventory
    case = factory(); now = utcnow()
    with monkeypatch.context() as patch:
        patch.setattr(external_api, 'utcnow', lambda: now - timedelta(days=1) + timedelta(seconds=2))
        values = [issued(case, expires_in_days=1) for _ in range(3)]
    monkeypatch.setattr(api_key_inventory, 'utcnow', lambda: now)
    first = page(case, limit=1)
    assert len(records(ok(read(case, ACTIVE)), active=True)['items']) == 3
    monkeypatch.setattr(api_key_inventory, 'utcnow', lambda: now + timedelta(seconds=3))
    assert records(ok(read(case, ACTIVE)), active=True)['items'] == []
    assert {v['id'] for v in all_pages(case, 1, first)} == {v['key']['id'] for v in values}


def test_cursor_absolute_ttl_does_not_extend_and_preserves_window_time(factory, monkeypatch):
    from tire_api import api_key_inventory
    case = factory(); seeded(case, 5)
    start = utcnow(); monkeypatch.setattr(api_key_inventory, 'utcnow', lambda: start)
    first = page(case, limit=1)
    monkeypatch.setattr(api_key_inventory, 'utcnow', lambda: start + timedelta(seconds=899))
    second = page(case, limit=1, cursor=first['next_cursor'])
    assert second['window_started_at'] == first['window_started_at']
    assert instant(second['read_at']) > instant(first['read_at'])
    monkeypatch.setattr(api_key_inventory, 'utcnow', lambda: start + timedelta(seconds=900))
    error(read(case, params={'limit': 1, 'cursor': second['next_cursor']}), 409, 'api_key_history_cursor_expired')


def test_upper_window_excludes_newer_issuance_but_revocations_are_current_each_page(factory):
    case = factory(); values = seeded(case, 4)
    first = page(case, limit=1)
    late = issued(case, name='窗口之后签发')
    target = values[0]; operation(revoke(case, target))
    result = all_pages(case, 1, first)
    assert {v['id'] for v in result} == {v['key']['id'] for v in values}
    assert late['key']['id'] not in {v['id'] for v in result}
    assert next(v for v in result if v['id'] == target['key']['id'])['revoked_at'] is not None


@pytest.mark.parametrize('change', ['signature', 'padding', 'empty', 'oversize', 'extra_segment', 'wrong_limit'])
def test_invalid_or_wrong_limit_cursor_never_restarts_history(factory, change):
    case = factory(); seeded(case)
    cursor = page(case, limit=1)['next_cursor']
    variants = {'signature': cursor[:-1] + ('A' if cursor[-1] != 'A' else 'B'),
        'padding': cursor.split('.')[0] + '=.' + cursor.split('.')[1], 'empty': '',
        'oversize': 'a' * 2049, 'extra_segment': cursor + '.x', 'wrong_limit': cursor}
    error(read(case, params={'limit': 2 if change == 'wrong_limit' else 1, 'cursor': variants[change]}),
        422, 'api_key_history_cursor_invalid')


def test_cursor_payload_contains_no_raw_owner_or_secret(factory):
    case = factory(); values = seeded(case)
    cursor = page(case, limit=1)['next_cursor']; payload, raw, signature = cursor_parts(cursor)
    assert case.actor['id'] not in raw.decode('utf-8'), 'raw_account_id_in_history_cursor'
    with case.database.sessions() as db:
        secrets_in_memory = [row.cursor_secret for row in db.scalars(select(ApiKey))]
    leaked = any(value in raw.decode('utf-8') for value in secrets_in_memory)
    assert leaked is False, 'cursor_signing_secret_disclosed'
    assert all(value['token'] not in raw.decode('utf-8') for value in values), 'bearer_disclosed'


@pytest.mark.parametrize('mutation', [
    'extra_field', 'missing_field', 'bool_limit', 'wrong_route', 'wrong_schema',
    'raw_owner', 'wrong_owner_commitment', 'unknown_anchor', 'changed_upper_time',
    'after_above_upper', 'after_extra_member', 'after_naive', 'window_naive',
    'bool_expiry', 'renewed_expiry', 'wrong_namespace', 'wrong_signing_key',
    'duplicate_json_field', 'noncanonical_json',
])
def test_correctly_signed_but_malformed_or_misbound_cursor_is_rejected(factory, mutation):
    case = factory(); seeded(case)
    original = page(case, limit=1)['next_cursor']
    payload, _raw, _signature = cursor_parts(original)
    payload = deepcopy(payload)
    with case.database.sessions() as db:
        signing_hex = PrivateText(db.get(ApiKey, payload['anchor']).cursor_secret)
    namespace = b'tire-api-key-history@1\x00'
    if mutation == 'extra_field': payload['extra'] = 'unexpected'
    elif mutation == 'missing_field': del payload['owner']
    elif mutation == 'bool_limit': payload['limit'] = True
    elif mutation == 'wrong_route': payload['route'] = ACTIVE
    elif mutation == 'wrong_schema': payload['schema'] = 'api-key-history-cursor@0'
    elif mutation == 'raw_owner': payload['owner'] = case.actor['id']
    elif mutation == 'wrong_owner_commitment': payload['owner'] = '0' * 64
    elif mutation == 'unknown_anchor':
        payload['anchor'] = uuid4().hex; payload['upper'][1] = payload['anchor']
    elif mutation == 'changed_upper_time':
        payload['upper'][0] = (instant(payload['upper'][0]) + timedelta(microseconds=1)).isoformat()
    elif mutation == 'after_above_upper':
        payload['after'][0] = (instant(payload['upper'][0]) + timedelta(seconds=1)).isoformat()
    elif mutation == 'after_extra_member': payload['after'].append('extra')
    elif mutation == 'after_naive': payload['after'][0] = instant(payload['after'][0]).replace(tzinfo=None).isoformat()
    elif mutation == 'window_naive': payload['window_started_at'] = instant(payload['window_started_at']).replace(tzinfo=None).isoformat()
    elif mutation == 'bool_expiry': payload['expires'] = True
    elif mutation == 'renewed_expiry': payload['expires'] += 1
    elif mutation == 'wrong_namespace': namespace = b'tire-external-read@1\x00'
    elif mutation == 'wrong_signing_key': signing_hex = PrivateText('00' * 32)
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if mutation == 'duplicate_json_field': raw = b'{"limit":1,' + raw[1:]
    elif mutation == 'noncanonical_json': raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
    signature = hmac.new(bytes.fromhex(signing_hex), namespace + raw, hashlib.sha256).digest()
    bad_cursor = '.'.join(base64.urlsafe_b64encode(v).rstrip(b'=').decode('ascii') for v in [raw, signature])
    error(read(case, params={'limit': 1, 'cursor': bad_cursor}), 422, 'api_key_history_cursor_invalid')


def test_active_overflow_fails_closed_instead_of_hiding_seventeenth(factory):
    case = factory(); seeded(case, 16)
    assert len(records(ok(read(case, ACTIVE)), active=True)['items']) == 16
    now = utcnow()
    with case.database.sessions.begin() as db:
        db.add(seal(ApiKey(id=uuid4().hex, owner_user_id=case.actor['id'], name='异常第17把合成Key',
            scopes=['sources:read'], bearer_sha256=hashlib.sha256(uuid4().bytes).hexdigest(),
            cursor_secret=hashlib.sha256(uuid4().bytes).hexdigest(), created_at=now,
            expires_at=now + timedelta(days=1))))
    error(read(case, ACTIVE), 409, 'api_key_active_limit_invalid')
    assert len(page(case, limit=100)['items']) == 17


@pytest.mark.parametrize('path,continuation', [(ACTIVE, False), (HISTORY, False), (HISTORY, True)])
def test_one_joined_query_preserves_state_when_revocation_commits_after_select(factory, path, continuation):
    case = factory(); values = seeded(case, 3)
    params = {}
    target = values[-1]['key']['id']
    if continuation:
        first = page(case, limit=1)
        params = {'limit': 1, 'cursor': first['next_cursor']}
        target = values[-2]['key']['id']
    with case.database.engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA journal_mode=WAL').scalar() == 'wal'
    statements = []; inserted = []

    def after_select(_conn, _cursor, statement, _parameters, _context, _many):
        sql = statement.lower()
        if sql.lstrip().startswith('select') and ('external_api_keys' in sql or 'external_api_key_revocations' in sql):
            statements.append(sql)
            if 'join' in sql and not inserted:
                inserted.append(True)
                with case.database.sessions.begin() as db:
                    db.add(seal(ApiKeyRevocation(key_id=target, revoked_at=utcnow(), reason='manual')))

    event.listen(case.database.engine, 'after_cursor_execute', after_select)
    try:
        response = read(case, path, params=params)
    finally:
        event.remove(case.database.engine, 'after_cursor_execute', after_select)
    body = records(ok(response), active=path == ACTIVE)
    assert inserted == [True] and len(statements) == 1, 'inventory_requires_one_joined_state_query'
    assert next(v for v in body['items'] if v['id'] == target)['revoked_at'] is None
    assert target not in {v['id'] for v in records(ok(read(case, ACTIVE)), active=True)['items']}
    assert next(v for v in page(case)['items'] if v['id'] == target)['revoked_at'] is not None
