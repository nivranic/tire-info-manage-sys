"""R79 private SQL/ASGI contracts; generated bearer values never enter receipts."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest

if not os.environ.get('R79_TEST_STORAGE_ROOT') or os.environ.get('TIRE_DATABASE_URL') != os.environ.get('DATABASE_URL'):
    raise RuntimeError('r79_private_runner_required')

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from admin_support import register_admin
from test_core import FixtureRegistry
from webhook_support import configured_environment, create_subscription, add_tire_notification, seed_webhook_case
from tire_api.db import UserSession, utcnow
from tire_api.external_api_models import ApiKey, ApiKeyMinute, ApiKeyOperation, ApiKeyRevocation
from tire_api.main import create_app


class PrivateCase(SimpleNamespace):
    def __repr__(self):
        return '<PrivateExternalApiCase>'


@pytest.fixture
def case(tmp_path, monkeypatch):
    assert tmp_path.resolve().is_relative_to(Path(os.environ['R79_TEST_STORAGE_ROOT']).resolve())
    url = configured_environment(monkeypatch, tmp_path)
    app = create_app(url, FixtureRegistry())
    with TestClient(app, backend_options={'loop_factory': asyncio.SelectorEventLoop}) as client:
        password = secrets.token_urlsafe(18)
        user = register_admin(client, 'r79-owner', password)['user']
        yield PrivateCase(client=client, app=app, database=app.state.database, user=user, password=password)


def create(case, scopes=None, key=None, client=None, **changes):
    return (client or case.client).post('/v1/api-keys', json={'name': '合成API Key',
        'scopes': scopes if scopes is not None else ['sources:read', 'webhooks:read'], 'expires_in_days': 30,
        'acknowledged': True, **changes}, headers={'Idempotency-Key': key or str(uuid4())})


def created(case, **changes):
    response = create(case, **changes)
    assert response.status_code == 201
    return response.json()


def bearer(case, token, path='/external/v1/sources', **kwargs):
    return case.client.get(path, headers={'Authorization': 'Bearer ' + token}, **kwargs)


def test_create_token_once_and_operation_recovery_never_persists_bearer(case):
    key = str(uuid4())
    first = created(case, key=key)
    token = first['token']
    if type(token) is not str or len(token) != 100:
        pytest.fail('invalid_generated_bearer_shape', pytrace=False)
    assert set(first) == {'schema', 'idempotency_key', 'action', 'key', 'token', 'replayed'}
    assert set(first['key']) == {'schema', 'id', 'name', 'scopes', 'created_at', 'expires_at', 'revoked_at'}
    replay = create(case, key=key).json()
    assert replay['token'] is None and replay['replayed'] is True and replay['key'] == first['key']
    recovery = case.client.get('/v1/api-key-operations?mode=history&key=' + key).json()
    assert recovery == replay
    listing = case.client.get('/v1/api-keys?mode=history').json()
    assert listing['items'] == [first['key']]
    with case.database.sessions() as db:
        from tire_api.webhook_delivery import row_values
        stored = json.dumps([row_values(row) for model in (ApiKey, ApiKeyOperation, ApiKeyRevocation)
            for row in db.scalars(select(model)).all()])
        if token in stored:
            pytest.fail('bearer_plaintext_persisted', pytrace=False)
    assert bearer(case, token).status_code == 200


def test_management_guard_and_cross_owner_resource_precede_body(case):
    other = TestClient(case.app, backend_options={'loop_factory': asyncio.SelectorEventLoop})
    try:
        assert other.post('/v1/api-keys', json={'malformed': True}).status_code == 401
        register_admin(other, 'r79-other', secrets.token_urlsafe(18))
        key = created(case)['key']
        assert other.post('/v1/api-keys/' + key['id'] + '/revoke', json={'malformed': True}).status_code == 404
        assert other.get('/v1/api-keys?mode=history').json()['items'] == []
    finally:
        other.close()


@pytest.mark.parametrize('changes', [{'acknowledged': 1}, {'acknowledged': False}, {'scopes': ['unknown:read']},
    {'scopes': []}, {'scopes': ['sources:read', 'sources:read']}, {'expires_in_days': True},
    {'expires_in_days': 0}, {'expires_in_days': 91}, {'name': '   '}, {'name': 'bad\x00name'}])
def test_closed_bounded_key_input(case, changes):
    assert create(case, **changes).status_code == 422


def test_idempotency_conflict_and_terminal_revocation(case):
    key = str(uuid4())
    first = created(case, key=key)
    assert create(case, key=key, name='different').status_code == 409
    path = '/v1/api-keys/' + first['key']['id'] + '/revoke'
    assert case.client.post(path, json={'acknowledged': True}, headers={'Idempotency-Key': key}).status_code == 409
    one = case.client.post(path, json={'acknowledged': True}, headers={'Idempotency-Key': str(uuid4())})
    two = case.client.post(path, json={'acknowledged': True}, headers={'Idempotency-Key': str(uuid4())})
    assert one.status_code == two.status_code == 200
    assert one.json()['key']['revoked_at'] == two.json()['key']['revoked_at']
    assert one.json()['token'] is two.json()['token'] is None
    assert bearer(case, first['token']).status_code == 401


def test_same_uuid_concurrent_create_emits_only_one_token(case):
    key = str(uuid4())
    cookie = case.client.cookies.get('tire_local_session')
    def issue():
        with TestClient(case.app, backend_options={'loop_factory': asyncio.SelectorEventLoop}) as client:
            client.cookies.set('tire_local_session', cookie)
            result = create(case, key=key, client=client)
            assert result.status_code == 201
            value = result.json()
            return value['token'] is not None, value['key']['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: issue(), range(2)))
    assert sum(value[0] for value in results) == 1
    assert len({value[1] for value in results}) == 1


def test_sixteen_active_limit_frees_only_on_revoke_or_expiry(case):
    values = [created(case) for _ in range(16)]
    assert create(case).status_code == 409
    assert case.client.post('/v1/api-keys/' + values[0]['key']['id'] + '/revoke',
        json={'acknowledged': True}, headers={'Idempotency-Key': str(uuid4())}).status_code == 200
    assert create(case).status_code == 201
    assert len(case.client.get('/v1/api-keys?mode=history').json()['items']) == 17


def test_external_auth_does_not_create_or_renew_cookie_and_rejects_local_bearer(case):
    value = created(case)
    with case.database.sessions() as db:
        before = db.scalar(select(func.count()).select_from(UserSession))
        expires = db.get(UserSession, case.client.cookies.get('tire_local_session')).expires_at
    fresh = TestClient(case.app, backend_options={'loop_factory': asyncio.SelectorEventLoop})
    try:
        bad = fresh.get('/external/v1/sources')
        good = fresh.get('/external/v1/sources', headers={'Authorization': 'Bearer ' + value['token']})
        assert bad.status_code == 401 and bad.headers['www-authenticate'] == 'Bearer'
        assert good.status_code == 200 and 'set-cookie' not in good.headers
        assert fresh.get('/external/unknown').status_code == 401
        assert case.client.get('/v1/sources', headers={'Authorization': 'Bearer ' + value['token']}).status_code == 401
    finally:
        fresh.close()
    with case.database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(UserSession)) == before
        assert db.get(UserSession, case.client.cookies.get('tire_local_session')).expires_at == expires


def test_scopes_projection_and_strict_queries(case):
    source = created(case, scopes=['sources:read'])
    assert bearer(case, source['token'], '/external/v1/webhook-deliveries').status_code == 403
    result = bearer(case, source['token'])
    assert result.status_code == 200
    assert all(set(row) == {'id', 'name', 'source_class', 'region', 'parser_version', 'status'} for row in result.json()['items'])
    for query in ('limit=1&limit=2', 'unknown=1', 'token=forbidden', 'limit=true', 'limit=101', 'cursor='):
        assert bearer(case, source['token'], '/external/v1/sources?' + query).status_code == 422
    assert result.headers['cache-control'] == 'no-store' and result.headers['x-content-type-options'] == 'nosniff'


def test_persistent_fixed_minute_counts_valid_failures_and_survives_restart(case, monkeypatch):
    from tire_api import external_api
    value = created(case)
    now = utcnow().replace(second=0, microsecond=0)
    monkeypatch.setattr(external_api, 'utcnow', lambda: now)
    for _ in range(60):
        assert bearer(case, value['token'], '/external/v1/unknown').status_code == 404
    denied = bearer(case, value['token'])
    assert denied.status_code == 429 and denied.headers['retry-after'] == '60'
    from tire_api.db import Database
    restarted = Database(str(case.database.engine.url))
    with restarted.sessions() as db:
        bucket = db.get(ApiKeyMinute, value['key']['id'])
        assert bucket.requests == 60
    restarted.close()
    now += timedelta(minutes=1)
    assert bearer(case, value['token']).status_code == 200


def test_sources_cursor_is_signed_key_route_limit_bound_and_catalog_pinned(case):
    value = created(case)
    first = bearer(case, value['token'], '/external/v1/sources?limit=1').json()
    cursor = first['next_cursor']
    assert cursor is not None
    final = bearer(case, value['token'], '/external/v1/sources?limit=1&cursor=' + cursor)
    assert final.status_code == 200 and final.json()['next_cursor'] is None
    other = created(case)
    assert bearer(case, other['token'], '/external/v1/sources?limit=1&cursor=' + cursor).status_code == 422
    assert bearer(case, value['token'], '/external/v1/sources?limit=2&cursor=' + cursor).status_code == 422
    assert bearer(case, value['token'], '/external/v1/webhook-deliveries?limit=1&cursor=' + cursor).status_code == 422
    original = case.app.state.registry.sources
    case.app.state.registry.sources = lambda: [{**row, 'status': 'changed'} for row in original()]
    assert bearer(case, value['token'], '/external/v1/sources?limit=1&cursor=' + cursor).status_code == 409


def test_delivery_cursor_freezes_window_and_enforces_frozen_owner(case):
    producer = seed_webhook_case(case.client)
    subscription = create_subscription(producer, ['tire_monitor'], enabled=True)['response']
    for _ in range(3):
        add_tire_notification(producer)
    value = created(case)
    first = bearer(case, value['token'], '/external/v1/webhook-deliveries?limit=2').json()
    assert len(first['items']) == 2
    add_tire_notification(producer)
    second = bearer(case, value['token'], '/external/v1/webhook-deliveries?limit=2&cursor=' + first['next_cursor']).json()
    assert len(second['items']) == 1 and second['next_cursor'] is None
    detail = bearer(case, value['token'], '/external/v1/webhook-deliveries/' + first['items'][0]['id'])
    assert detail.status_code == 200 and detail.json()['schema'] == 'webhook-delivery@1'
    assert detail.json()['webhook_id'] == subscription['id']


def test_password_reset_revokes_all_keys_in_same_transaction(case):
    key = created(case)
    response = case.client.post('/v1/auth/users/' + case.user['id'] + '/password',
        json={'new_password': secrets.token_urlsafe(18)})
    assert response.status_code == 200
    assert bearer(case, key['token']).status_code == 401
    with case.database.sessions() as db:
        assert db.get(ApiKeyRevocation, key['key']['id']).reason == 'password_reset'


def test_password_reset_revocation_failure_rolls_back_password_and_sessions(case):
    from tire_api.auth import verify_password
    from tire_api.db import User
    key = created(case)
    def fail_insert(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lower().startswith('insert into external_api_key_revocations'):
            raise RuntimeError('synthetic_key_revocation_failure')
    event.listen(case.database.engine, 'before_cursor_execute', fail_insert)
    try:
        with pytest.raises(RuntimeError, match='synthetic_key_revocation_failure'):
            case.client.post('/v1/auth/users/' + case.user['id'] + '/password',
                json={'new_password': secrets.token_urlsafe(18)})
    finally:
        event.remove(case.database.engine, 'before_cursor_execute', fail_insert)
    with case.database.sessions() as db:
        if not verify_password(case.password, db.get(User, case.user['id']).password_hash):
            pytest.fail('password_changed_despite_revocation_rollback', pytrace=False)
        assert db.get(UserSession, case.client.cookies.get('tire_local_session')).user_id == case.user['id']
    assert bearer(case, key['token']).status_code == 200


def test_cli_reset_revokes_key_without_child_process(case, monkeypatch, capsys):
    from tire_api import manage
    import sys
    value = created(case)
    monkeypatch.setenv('TI_MANAGE_NEW_PASSWORD', secrets.token_urlsafe(18))
    monkeypatch.setattr(sys, 'argv', ['manage', 'reset-password', '--username', 'r79-owner'])
    manage.main()
    assert json.loads(capsys.readouterr().out)['ok'] is True
    assert bearer(case, value['token']).status_code == 401


def test_sources_cursor_has_owner_commitment_and_fixed_expiry(case, monkeypatch):
    from tire_api import external_api
    import base64
    now = utcnow()
    monkeypatch.setattr(external_api, 'utcnow', lambda: now)
    value = created(case)
    first = bearer(case, value['token'], '/external/v1/sources?limit=1').json()
    cursor = first['next_cursor']
    encoded = cursor.split('.')[0]
    payload = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    if case.user['id'] in json.dumps(payload):
        pytest.fail('cursor_exposes_owner_identifier', pytrace=False)
    assert payload['expires'] == int(now.timestamp()) + 900
    now += timedelta(seconds=900)
    assert bearer(case, value['token'], '/external/v1/sources?limit=1&cursor=' + cursor).status_code == 422


@pytest.mark.parametrize('field,value', [('name', 'x' * 501), ('status', 'bad\nstatus'), ('region', 123)])
def test_source_directory_rejects_invalid_projected_text(case, field, value):
    key = created(case)
    original = case.app.state.registry.sources
    case.app.state.registry.sources = lambda: [{**row, field: value} for row in original()]
    assert bearer(case, key['token']).status_code == 409


@pytest.fixture
def pre023(tmp_path, monkeypatch):
    """Synthetic current-shape/pre023-ledger fixture, not a historical backup."""
    from tire_api.db import Base
    from tire_api.external_api_models import TABLES
    from tire_api.knowledge_models import initialize_search
    from test_identity_migration import seed_legacy
    from version_registry import EXPECTED_SCHEMA_VERSIONS
    url = configured_environment(monkeypatch, tmp_path)
    database = create_app(url).state.database
    with database.engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables if table.name not in TABLES])
        connection.exec_driver_sql('CREATE TABLE tire_schema_versions '
            '(version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version in EXPECTED_SCHEMA_VERSIONS[:22]:
            connection.execute(text('INSERT INTO tire_schema_versions (version) VALUES (:version)'), {'version': version})
        initialize_search(connection)
    with database.sessions() as db:
        seed_legacy(db, namespace='SYNTHETIC-R79', product_code='SYNTHETIC-PRE023', watch=True)
    yield database
    database.close()


def test_023_additive_file_migration_preserves_every_old_row_and_ddl(pre023):
    from test_ai_stream_migration import snapshot
    from tire_api.external_api_models import TABLES
    from version_registry import EXPECTED_SCHEMA_VERSIONS
    from historical_migration_support import assert_target_delta, initialize_observing_version
    database = pre023
    before = snapshot(database)
    assert not set(TABLES) & before['tables']
    stage = initialize_observing_version(database, '023_external_api_keys')
    assert_target_delta(before, stage, TABLES)
    first = snapshot(database)
    database.initialize()
    after = snapshot(database)
    assert first == after
    assert after['tables'] - before['tables'] == set(TABLES)
    assert [row for row in after['schema'] if row[2] in before['tables']] == before['schema']
    for table in before['tables'] - {'tire_schema_versions'}:
        assert after['rows'][table] == before['rows'][table], table
    assert all(not after['rows'][table] for table in TABLES)
    with database.engine.connect() as connection:
        assert connection.execute(text('SELECT version FROM tire_schema_versions ORDER BY version')).scalars().all() == EXPECTED_SCHEMA_VERSIONS
        assert connection.exec_driver_sql('PRAGMA integrity_check').scalar_one() == 'ok'
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []


def test_023_failure_rolls_back_new_schema_and_version(pre023, monkeypatch):
    from test_ai_stream_migration import snapshot
    from tire_api import migrations
    before = snapshot(pre023)
    upgrade = migrations.upgrade
    def failed(connection):
        upgrade(connection)
        raise RuntimeError('synthetic_external_migration_failure')
    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'upgrade', failed)
        with pytest.raises(RuntimeError, match='synthetic_external_migration_failure'):
            pre023.initialize()
    assert snapshot(pre023) == before
    pre023.initialize()
