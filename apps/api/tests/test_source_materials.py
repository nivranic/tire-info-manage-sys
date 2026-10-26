"""Synthetic licensed material workflow; no real publication or permission claim."""
from copy import deepcopy
import hashlib
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from admin_support import register_admin
from tire_api.main import create_app


POLICY = {'policy_id': 'synthetic-report', 'title': 'Synthetic material', 'publisher': 'Project fixtures',
    'edition': None, 'published_at': None, 'source_reference_url': 'https://example.com/report',
    'download_url': 'https://example.com/report.pdf', 'redirect_urls': [],
    'rights': {'rights_holder': 'Project fixtures', 'basis': 'Project-authored synthetic material',
        'license_url': None, 'store_original': True, 'workspace_reopen': True,
        'quote_identifiers': True, 'provider_use': False, 'export': False}}
PDF = b'%PDF-1.7\nsynthetic original \xff\x00\xfe'


def obtained(policy):
    return {'body': PDF, 'started_at': '2026-10-18T00:00:00+00:00',
        'completed_at': '2026-10-18T00:00:01+00:00', 'initial_url': policy['download_url'],
        'final_url': policy['download_url'], 'redirects': [], 'robot_objects': [],
        'robots': [{'url': 'https://example.com/robots.txt', 'status': 404, 'raw_hash': None,
            'byte_count': 0, 'allowed': True, 'minimum_interval': 2.0, 'target_url': policy['download_url']}]}


@pytest.fixture
def material_app(tmp_path, monkeypatch):
    path = tmp_path / 'policies.json'
    path.write_text(json.dumps({'schema': 'source-material-policies@1', 'policies': [POLICY]}), encoding='utf-8')
    monkeypatch.setenv('TI_SOURCE_MATERIAL_POLICIES_FILE', str(path))
    app = create_app('sqlite:///' + (tmp_path / 'materials.sqlite').as_posix())
    with TestClient(app) as client:
        register_admin(client, 'material-admin')
        yield client, app, path


def payload(client):
    row = client.get('/v1/source-materials/policies').json()['items'][0]
    return {'policy_id': row['policy_id'], 'expected_policy_fingerprint': row['policy_fingerprint'],
        'idempotency_key': str(uuid4()), 'operator': 'Synthetic operator', 'rights_confirmed': True}


def test_empty_catalog_and_admin_guard(tmp_path, monkeypatch):
    monkeypatch.delenv('TI_SOURCE_MATERIAL_POLICIES_FILE', raising=False)
    with TestClient(create_app('sqlite:///' + (tmp_path / 'empty.sqlite').as_posix())) as client:
        assert client.get('/v1/source-materials/policies').json()['items'] == []
        assert client.post('/v1/source-materials/captures', json={'unexpected': True}).status_code == 403


def test_capture_receipt_is_not_content_authentication(material_app, monkeypatch):
    client, app, _ = material_app
    calls = []
    async def fetch(policy):
        calls.append(policy['policy_id'])
        return obtained(policy)
    monkeypatch.setattr(app.state.material_transport, 'fetch', fetch)
    body = payload(client)
    preview = client.post('/v1/source-materials/preview', json={key: body[key] for key in (
        'policy_id', 'expected_policy_fingerprint')})
    assert preview.status_code == 200 and preview.json()['can_capture']
    result = client.post('/v1/source-materials/captures', json=body)
    assert result.status_code == 201, result.text
    first = result.json()
    assert first['state'] == 'succeeded' and not first['replayed']
    receipt = first['receipt']
    assert receipt['raw_hash'] == hashlib.sha256(PDF).hexdigest()
    assert receipt['content_authenticity'] == 'unverified'
    assert receipt['source_reference_relation'] == 'operator_configured'
    assert first['document']['source_url'] == POLICY['source_reference_url']
    document_id = first['document']['id']
    assert client.get('/v1/documents/' + document_id + '/content?mode=history').content == PDF
    second = client.post('/v1/source-materials/captures', json=body).json()
    assert second['replayed'] and second['request_id'] == first['request_id'] and calls == [POLICY['policy_id']]
    assert client.get('/v1/source-materials/documents/' + document_id + '?mode=history').json()['receipt'] == receipt
    wrong = client.post('/v1/source-materials/captures', json={**body, 'operator': 'Changed operator'})
    assert wrong.status_code == 409


@pytest.mark.parametrize('field,value', [('download_url', 'https://127.0.0.1/a.pdf'),
    ('download_url', 'https://example.com/a.pdf?token=secret'), ('download_url', 'https://EXAMPLE.com/a.pdf'),
    ('redirect_urls', ['https://example.com/a.pdf'] * 4), ('published_at', 'not-a-date')])
def test_policy_rejects_ambiguous_or_unbounded_config(tmp_path, monkeypatch, field, value):
    from tire_api.material_source_policy import load_policies, MaterialPolicyError
    item = {**deepcopy(POLICY), field: value}
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps({'schema': 'source-material-policies@1', 'policies': [item]}), encoding='utf-8')
    monkeypatch.setenv('TI_SOURCE_MATERIAL_POLICIES_FILE', str(path))
    with pytest.raises(MaterialPolicyError):
        load_policies()


def success_transport(app, monkeypatch, callback=None):
    calls = []
    async def fetch(policy):
        calls.append(policy['policy_id'])
        if callback:
            callback()
        return obtained(policy)
    monkeypatch.setattr(app.state.material_transport, 'fetch', fetch)
    return calls


def test_failed_capture_is_terminal_and_unknown_error_is_sanitized(material_app, monkeypatch):
    from tire_api.material_source_transport import MaterialTransportError
    client, app, _ = material_app
    calls = []
    async def fetch(_):
        calls.append(True)
        raise MaterialTransportError('credential=DO_NOT_RETAIN')
    monkeypatch.setattr(app.state.material_transport, 'fetch', fetch)
    body = payload(client)
    first = client.post('/v1/source-materials/captures', json=body)
    assert first.status_code == 201, first.text
    assert first.json()['failure_code'] == 'source_material_capture_failed'
    assert 'DO_NOT_RETAIN' not in first.text
    replay = client.post('/v1/source-materials/captures', json=body).json()
    assert replay['state'] == 'failed' and replay['document'] is replay['receipt'] is None
    assert len(calls) == 1


def test_policy_snapshot_and_replay_survive_current_catalog_removal(material_app, monkeypatch):
    from tire_api.material_source_policy import PolicyCatalog
    client, app, path = material_app
    calls = success_transport(app, monkeypatch)
    body = payload(client)
    path.write_text('invalid replacement on disk', encoding='utf-8')
    first = client.post('/v1/source-materials/captures', json=body).json()
    assert first['state'] == 'succeeded'
    app.state.material_policies = PolicyCatalog([])
    assert client.post('/v1/source-materials/captures', json=body).json()['replayed']
    assert client.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history').json()['receipt'] == first['receipt']
    assert client.post('/v1/source-materials/captures', json={**body, 'idempotency_key': str(uuid4())}).status_code == 404
    assert len(calls) == 1


def test_role_withdrawal_during_network_cannot_publish_document(material_app, monkeypatch):
    from sqlalchemy import select
    from tire_api.db import EvidenceDocument, User
    client, app, _ = material_app
    def revoke():
        with app.state.database.sessions() as db:
            db.scalar(select(User)).is_admin = False
            db.commit()
    calls = success_transport(app, monkeypatch, revoke)
    result = client.post('/v1/source-materials/captures', json=payload(client)).json()
    assert result['state'] == 'failed' and result['failure_code'] == 'source_material_authorization_changed'
    with app.state.database.sessions() as db:
        assert db.scalar(select(EvidenceDocument)) is None
    assert len(calls) == 1


def test_commit_failure_stays_unknown_and_same_key_never_fetches_again(material_app, monkeypatch):
    from sqlalchemy import event
    client, app, _ = material_app
    calls = success_transport(app, monkeypatch)
    body = payload(client)
    def reject(_connection, _cursor, sql, *_):
        if sql.startswith('INSERT INTO evidence_documents'):
            raise RuntimeError('private database detail')
    event.listen(app.state.database.engine, 'before_cursor_execute', reject)
    try:
        result = client.post('/v1/source-materials/captures', json=body)
    finally:
        event.remove(app.state.database.engine, 'before_cursor_execute', reject)
    assert result.status_code == 503 and 'private database detail' not in result.text
    replay = client.post('/v1/source-materials/captures', json=body).json()
    assert replay['state'] == 'processing_unconfirmed' and replay['replayed']
    assert replay['receipt'] is replay['document'] is None and len(calls) == 1


@pytest.mark.parametrize('table', ['source_material_requests', 'source_material_outcomes'])
@pytest.mark.parametrize('operation', ['update', 'delete', 'replace'])
def test_raw_sql_cannot_rewrite_request_or_terminal(material_app, monkeypatch, table, operation):
    from sqlalchemy.exc import IntegrityError
    client, app, _ = material_app
    success_transport(app, monkeypatch)
    assert client.post('/v1/source-materials/captures', json=payload(client)).json()['state'] == 'succeeded'
    with app.state.database.engine.connect() as connection:
        if operation == 'update':
            column = 'operator' if table.endswith('requests') else 'state'
            sql = f'UPDATE {table} SET {column}={column}'
        elif operation == 'delete':
            sql = f'DELETE FROM {table}'
        else:
            sql = f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'
        with pytest.raises(IntegrityError, match='source_material_immutable'):
            connection.exec_driver_sql(sql)
        connection.rollback()


def test_damaged_source_object_fails_closed_for_history(material_app, monkeypatch):
    client, app, _ = material_app
    success_transport(app, monkeypatch)
    first = client.post('/v1/source-materials/captures', json=payload(client)).json()
    app.state.database.object_store.path(first['document']['raw_hash']).write_bytes(b'damaged')
    result = client.get('/v1/source-materials/documents/' + first['document']['id'] + '?mode=history')
    assert result.status_code == 503 and result.json()['detail']['code'] == 'source_material_integrity_failed'


def test_same_bytes_uploaded_document_never_inherits_receipt(material_app, monkeypatch):
    import base64
    client, app, _ = material_app
    success_transport(app, monkeypatch)
    captured = client.post('/v1/source-materials/captures', json=payload(client)).json()
    metadata = {'title': POLICY['title'], 'source_url': POLICY['source_reference_url'],
        'operator': 'Synthetic author', 'rights_basis': POLICY['rights']['basis']}
    upload = client.post('/v1/documents', content=PDF, headers={'Content-Type': 'application/pdf',
        'X-Evidence-Metadata': base64.b64encode(json.dumps(metadata).encode()).decode()}).json()
    assert upload['raw_hash'] == captured['document']['raw_hash'] and upload['id'] != captured['document']['id']
    assert client.get('/v1/source-materials/documents/' + upload['id'] + '?mode=history').status_code == 404


def test_upgrade_from_019_and_repeat_initialization_preserve_rows(material_app):
    from version_registry import EXPECTED_SCHEMA_VERSIONS
    client, app, _ = material_app
    database = app.state.database
    with database.engine.begin() as connection:
        connection.exec_driver_sql('DROP TABLE source_material_outcomes')
        connection.exec_driver_sql('DROP TABLE source_material_requests')
        connection.exec_driver_sql("DELETE FROM tire_schema_versions WHERE version='020_source_materials'")
        connection.exec_driver_sql('CREATE TABLE r72_old_marker (value TEXT)')
        connection.exec_driver_sql("INSERT INTO r72_old_marker VALUES ('preserve')")
    database.initialize()
    database.initialize()
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT value FROM r72_old_marker').scalar() == 'preserve'
        assert set(connection.exec_driver_sql('SELECT version FROM tire_schema_versions').scalars()) == set(EXPECTED_SCHEMA_VERSIONS)
        triggers = connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'source_material_%'").all()
        assert {row[0] for row in triggers} == {f'source_material_{table}_no_{action}'
            for table in ('requests', 'outcomes', 'stops') for action in ('update', 'delete', 'replace')}


def test_request_lookup_uses_stable_user_and_is_private_to_other_accounts(material_app, monkeypatch):
    from admin_support import ADMIN_PASSWORD
    client, app, _ = material_app
    calls = success_transport(app, monkeypatch)
    body = payload(client)
    first = client.post('/v1/source-materials/captures', json=body).json()
    with TestClient(app) as same, TestClient(app) as other:
        assert same.post('/v1/auth/login', json={'username': 'material-admin', 'password': ADMIN_PASSWORD}).status_code == 200
        reopened = same.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history')
        assert reopened.status_code == 200 and reopened.json()['request_id'] == first['request_id']
        assert same.post('/v1/source-materials/captures', json=body).json()['replayed']
        register_admin(other, 'material-other')
        assert other.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history').status_code == 404
        assert other.get('/v1/source-materials/requests?mode=history').json()['items'] == []
    assert len(calls) == 1


def test_concurrent_duplicate_observes_reservation_without_network_or_db_lock(material_app, monkeypatch):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    import threading
    client, app, _ = material_app
    entered, release = threading.Event(), threading.Event()
    calls = []
    async def fetch(policy):
        calls.append(True)
        entered.set()
        async with asyncio.timeout(4):
            while not release.is_set():
                await asyncio.sleep(.01)
        return obtained(policy)
    monkeypatch.setattr(app.state.material_transport, 'fetch', fetch)
    body = payload(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, '/v1/source-materials/captures', json=body)
        try:
            assert entered.wait(2)
            second = pool.submit(client.post, '/v1/source-materials/captures', json=body).result(timeout=2)
            assert second.status_code == 201 and second.json()['state'] == 'processing_unconfirmed'
            assert second.json()['replayed']
        finally:
            release.set()
        final = first.result(timeout=4)
    assert final.status_code == 201 and final.json()['state'] == 'succeeded' and len(calls) == 1


def robots_failure(status=429):
    from tire_api.material_source_transport import MaterialTransportError
    error = MaterialTransportError('source_material_robots_unavailable')
    error.phase, error.http_status = 'robots_http_status', status
    return error


def failure_audits(app):
    from sqlalchemy import select
    from tire_api.db import AuditEvent
    with app.state.database.sessions() as db:
        return [(row.session_id, deepcopy(row.detail)) for row in db.scalars(
            select(AuditEvent).where(AuditEvent.action == 'source_material_failed')).all()]


def test_robots_failure_audit_uses_original_session_and_replays_once(material_app, monkeypatch):
    from admin_support import ADMIN_PASSWORD
    from tire_api.source_material_models import SourceMaterialRequest
    client, app, _ = material_app
    calls = []
    async def fetch(_policy):
        calls.append(1)
        raise robots_failure()
    monkeypatch.setattr(app.state.material_transport, 'fetch', fetch)
    body = payload(client)
    first = client.post('/v1/source-materials/captures', json=body).json()
    assert first['state'] == 'failed' and first['failure_code'] == 'source_material_robots_unavailable'
    assert first['document'] is first['receipt'] is None
    assert not {'phase', 'http_status', 'diagnostic'} & first.keys()
    with app.state.database.sessions() as db:
        original_session = db.get(SourceMaterialRequest, first['request_id']).actor_session_id
    expected = [(original_session, {'request_id': first['request_id'],
        'failure_code': 'source_material_robots_unavailable', 'phase': 'robots_http_status', 'http_status': 429})]
    assert failure_audits(app) == expected
    with TestClient(app) as same_user:
        assert same_user.post('/v1/auth/login', json={
            'username': 'material-admin', 'password': ADMIN_PASSWORD}).status_code == 200
        replay = same_user.post('/v1/source-materials/captures', json=body).json()
        assert replay['replayed'] and replay['request_id'] == first['request_id']
        history = same_user.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history').json()
        assert history == {key: value for key, value in first.items() if key != 'replayed'}
    assert calls == [1] and failure_audits(app) == expected


def test_robots_failure_rejects_extra_diagnostic_fields_without_changing_public_code(material_app, monkeypatch):
    client, app, _ = material_app
    async def fetch(_policy):
        error = robots_failure()
        error.headers = {'Authorization': 'DO_NOT_RETAIN'}
        error.body = 'DO_NOT_RETAIN'
        raise error
    monkeypatch.setattr(app.state.material_transport, 'fetch', fetch)
    body = payload(client)
    response = client.post('/v1/source-materials/captures', json=body)
    assert response.status_code == 201
    assert response.json()['failure_code'] == 'source_material_robots_unavailable'
    assert response.json()['document'] is response.json()['receipt'] is None
    assert 'DO_NOT_RETAIN' not in response.text and failure_audits(app) == []


def test_inflight_robots_failure_replay_has_one_fetch_and_one_audit(material_app, monkeypatch):
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor
    client, app, _ = material_app
    entered, release, calls = threading.Event(), threading.Event(), []
    async def fetch(_policy):
        calls.append(1)
        entered.set()
        async with asyncio.timeout(4):
            while not release.is_set():
                await asyncio.sleep(.01)
        raise robots_failure()
    monkeypatch.setattr(app.state.material_transport, 'fetch', fetch)
    body = payload(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, '/v1/source-materials/captures', json=body)
        try:
            assert entered.wait(2)
            replay = pool.submit(client.post, '/v1/source-materials/captures', json=body).result(timeout=2)
            assert replay.status_code == 201 and replay.json()['state'] == 'processing_unconfirmed'
            assert replay.json()['replayed'] and failure_audits(app) == []
        finally:
            release.set()
        final = first.result(timeout=4)
    assert final.status_code == 201 and final.json()['state'] == 'failed'
    assert calls == [1] and len(failure_audits(app)) == 1


def test_robots_failure_audit_does_not_add_a_role_recheck(material_app, monkeypatch):
    from sqlalchemy import select
    from tire_api.db import User
    from tire_api.source_material_models import SourceMaterialRequest
    client, app, _ = material_app
    async def fetch(_policy):
        with app.state.database.sessions() as db:
            db.scalar(select(User)).is_admin = False
            db.commit()
        raise robots_failure(403)
    monkeypatch.setattr(app.state.material_transport, 'fetch', fetch)
    body = payload(client)
    first = client.post('/v1/source-materials/captures', json=body)
    assert first.status_code == 201 and first.json()['state'] == 'failed'
    request_id = first.json()['request_id']
    with app.state.database.sessions() as db:
        original_session = db.get(SourceMaterialRequest, request_id).actor_session_id
    assert failure_audits(app) == [(original_session, {'request_id': request_id,
        'failure_code': 'source_material_robots_unavailable', 'phase': 'robots_http_status', 'http_status': 403})]
    assert client.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history').json()['state'] == 'failed'
    assert client.post('/v1/source-materials/captures', json=body).status_code == 403
    assert len(failure_audits(app)) == 1


@pytest.mark.parametrize('failure_at', ['audit-call', 'audit-insert'])
def test_failure_audit_error_rolls_back_outcome_and_keeps_reservation(material_app, monkeypatch, failure_at):
    from sqlalchemy import event
    from tire_api.service import QueryService
    from tire_api.source_material_models import SourceMaterialOutcome
    client, app, _ = material_app
    calls, armed = [], []
    async def fetch(_policy):
        calls.append(1)
        armed.append(True)
        raise robots_failure()
    monkeypatch.setattr(app.state.material_transport, 'fetch', fetch)
    audit = QueryService.audit
    def reject_call(service, session_id, action, **detail):
        if action == 'source_material_failed':
            raise RuntimeError('synthetic failure audit unavailable')
        return audit(service, session_id, action, **detail)
    def reject_insert(_connection, _cursor, sql, *_args):
        if armed and sql.startswith('INSERT INTO audit_events'):
            raise RuntimeError('synthetic failure audit unavailable')
    body = payload(client)
    with monkeypatch.context() as local:
        if failure_at == 'audit-call':
            local.setattr(QueryService, 'audit', reject_call)
        else:
            event.listen(app.state.database.engine, 'before_cursor_execute', reject_insert)
        try:
            response = client.post('/v1/source-materials/captures', json=body)
        finally:
            if failure_at == 'audit-insert':
                event.remove(app.state.database.engine, 'before_cursor_execute', reject_insert)
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'source_material_commit_unconfirmed'
    history = client.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history').json()
    assert history['state'] == 'processing_unconfirmed'
    with app.state.database.sessions() as db:
        assert db.get(SourceMaterialOutcome, history['request_id']) is None
    assert failure_audits(app) == []
    assert client.post('/v1/source-materials/captures', json=body).json()['replayed']
    assert calls == [1] and failure_audits(app) == []


@pytest.mark.parametrize('acknowledged', [False, True], ids=['rollback-before-commit', 'lost-ack-after-commit'])
def test_failed_outcome_and_diagnostic_audit_share_commit_uncertainty(material_app, monkeypatch, acknowledged):
    from sqlalchemy.orm import Session
    from tire_api.db import AuditEvent
    from tire_api.source_material_models import SourceMaterialOutcome
    client, app, _ = material_app
    calls, triggered = [], []
    async def fetch(_policy):
        calls.append(1)
        raise robots_failure()
    monkeypatch.setattr(app.state.material_transport, 'fetch', fetch)
    commit = Session.commit
    def uncertain(db):
        if not triggered and any(isinstance(row, SourceMaterialOutcome) and row.state == 'failed' for row in db.new):
            triggered.append(1)
            assert len([row for row in db.new if isinstance(row, AuditEvent)
                and row.action == 'source_material_failed']) == 1
            if acknowledged:
                commit(db)
            raise RuntimeError('synthetic failed terminal acknowledgement lost')
        return commit(db)
    body = payload(client)
    with monkeypatch.context() as local:
        local.setattr(Session, 'commit', uncertain)
        response = client.post('/v1/source-materials/captures', json=body)
    assert response.status_code == 503 and triggered == [1]
    history = client.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history').json()
    assert history['state'] == ('failed' if acknowledged else 'processing_unconfirmed')
    assert history['document'] is history['receipt'] is None
    with app.state.database.sessions() as db:
        assert (db.get(SourceMaterialOutcome, history['request_id']) is not None) is acknowledged
    assert len(failure_audits(app)) == int(acknowledged)
    assert client.post('/v1/source-materials/captures', json=body).json()['replayed']
    assert calls == [1] and len(failure_audits(app)) == int(acknowledged)


def unconfirmed_material(client, app, monkeypatch):
    """A real capture reservation whose arbitrary transport error remains unknown."""
    calls = []
    async def uncertain(_policy):
        calls.append(1)
        raise RuntimeError('synthetic unconfirmed transport')
    monkeypatch.setattr(app.state.material_transport, 'fetch', uncertain)
    body = payload(client)
    response = client.post('/v1/source-materials/captures', json=body)
    assert response.status_code == 503
    view = client.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history').json()
    assert view['state'] == 'processing_unconfirmed'
    return body, view, calls


def stop_payload(view):
    return {'expected_request_id': view['request_id'], 'operator': '停止操作人', 'reason': '不再采纳此未确认请求'}


def stop_request(client, body, view, **changes):
    return client.post('/v1/source-materials/requests/' + body['idempotency_key'] + '/stop',
        json={**stop_payload(view), **changes})


def test_stop_unknown_is_durable_and_never_reacquires_or_reads_current_policy_or_objects(material_app, monkeypatch):
    from tire_api.material_source_policy import PolicyCatalog
    client, app, _ = material_app
    body, original, calls = unconfirmed_material(client, app, monkeypatch)
    with app.state.database.engine.connect() as connection:
        original_rows = connection.exec_driver_sql('SELECT * FROM source_material_requests').all()
    app.state.material_policies = PolicyCatalog([])
    def forbidden(*_args, **_kwargs):
        raise AssertionError('stopping must use frozen request metadata only')
    monkeypatch.setattr(app.state.database.object_store, 'get', forbidden)
    monkeypatch.setattr(app.state.database.object_store, 'put', forbidden)
    response = stop_request(client, body, original)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['effect'] == 'stopped'
    stopped = value['request']
    assert stopped['state'] == 'stopped_unconfirmed'
    assert stopped['completed_at'] is stopped['failure_code'] is stopped['document'] is stopped['receipt'] is None
    assert stopped['stop'] == {'schema': 'source-material-stop@1', 'request_id': original['request_id'],
        'idempotency_key': body['idempotency_key'], 'operator': '停止操作人', 'reason': '不再采纳此未确认请求',
        'stopped_at': stopped['stop']['stopped_at']}
    assert not {'actor_user_id', 'actor_session_id'} & stopped['stop'].keys()
    assert stop_request(client, body, original).json() == {'effect': 'already_stopped', 'request': stopped}
    assert stop_request(client, body, original, reason='另一原因').status_code == 409
    assert client.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history').json() == stopped
    assert client.get('/v1/source-materials/requests?mode=history').json()['items'] == [stopped]
    replay = client.post('/v1/source-materials/captures', json=body).json()
    assert replay == {**stopped, 'replayed': True} and calls == [1]
    with app.state.database.engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT * FROM source_material_requests').all() == original_rows
        assert connection.exec_driver_sql('SELECT * FROM source_material_outcomes').all() == []


@pytest.mark.parametrize('terminal', ['succeeded', 'failed'])
def test_terminal_capture_wins_before_stop_without_any_stop_write(material_app, monkeypatch, terminal):
    from sqlalchemy import text
    client, app, _ = material_app
    if terminal == 'succeeded':
        success_transport(app, monkeypatch)
    else:
        async def failed(_policy):
            raise robots_failure()
        monkeypatch.setattr(app.state.material_transport, 'fetch', failed)
    body = payload(client)
    captured = client.post('/v1/source-materials/captures', json=body).json()
    assert captured['state'] == terminal
    before = {key: value for key, value in captured.items() if key != 'replayed'}
    response = stop_request(client, body, captured)
    assert response.status_code == 200, response.text
    assert response.json() == {'effect': 'already_terminal', 'request': before}
    with app.state.database.sessions() as db:
        assert db.execute(text('SELECT COUNT(*) FROM source_material_stops')).scalar() == 0


@pytest.mark.parametrize('completion', ['success-after-put', 'robots-failure', 'cancelled'])
def test_stop_wins_before_late_capture_completion_and_blocks_all_database_adoption(material_app, monkeypatch, completion):
    import asyncio
    import threading
    from concurrent.futures import CancelledError, ThreadPoolExecutor
    from sqlalchemy import func, select, text
    from tire_api.db import AuditEvent, EvidenceDocument, EvidenceObject
    from tire_api.source_material_models import SourceMaterialOutcome
    client, app, _ = material_app
    entered, release, calls, physical_puts = threading.Event(), threading.Event(), [], []
    original_put = app.state.database.object_store.put
    async def fetch(policy):
        calls.append(1)
        if completion == 'success-after-put':
            return obtained(policy)
        entered.set()
        async with asyncio.timeout(8):
            while not release.is_set():
                await asyncio.sleep(.01)
        if completion == 'cancelled':
            raise asyncio.CancelledError()
        raise robots_failure()
    def hold_after_put(data):
        raw_hash = original_put(data)
        physical_puts.append(raw_hash)
        entered.set()
        assert release.wait(8)
        return raw_hash
    monkeypatch.setattr(app.state.material_transport, 'fetch', fetch)
    if completion == 'success-after-put':
        monkeypatch.setattr(app.state.database.object_store, 'put', hold_after_put)
    body = payload(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(client.post, '/v1/source-materials/captures', json=body)
        try:
            assert entered.wait(4)
            view = client.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history').json()
            response = stop_request(client, body, view)
            assert response.status_code == 200, response.text
            assert response.json()['effect'] == 'stopped'
            from tire_api.material_source_policy import PolicyCatalog
            app.state.material_policies = PolicyCatalog([])
        finally:
            release.set()
        try:
            late = pending.result(timeout=8)
        except (CancelledError, asyncio.CancelledError):
            assert completion == 'cancelled'
        except RuntimeError as exc:
            # BaseHTTPMiddleware may translate a propagated cancellation with
            # no response into this exact wrapper. Keep the strict DB checks.
            assert completion == 'cancelled' and str(exc) == 'No response returned.'
        else:
            assert completion != 'cancelled'
            assert late.status_code == 201 and late.json()['state'] == 'stopped_unconfirmed'
    stopped = client.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history').json()
    assert stopped['state'] == 'stopped_unconfirmed' and calls == [1]
    assert bool(physical_puts) is (completion == 'success-after-put')
    with app.state.database.sessions() as db:
        for model in (SourceMaterialOutcome, EvidenceDocument, EvidenceObject):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.execute(text('SELECT COUNT(*) FROM source_material_stops')).scalar() == 1
        actions = db.scalars(select(AuditEvent.action).where(AuditEvent.action.like('source_material_%'))).all()
        assert sorted(actions) == ['source_material_requested', 'source_material_stopped']


def test_stop_guard_payload_owner_and_original_request_binding(material_app, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from tire_api.db import User
    client, app, _ = material_app
    body, view, _calls = unconfirmed_material(client, app, monkeypatch)
    with TestClient(app) as anonymous, TestClient(app) as other:
        assert stop_request(anonymous, body, view, unexpected=True).status_code == 403
        register_admin(other, 'stop-other')
        assert stop_request(other, body, view).status_code == 403
        with app.state.database.sessions() as db:
            db.scalar(select(User).where(User.username == 'stop-other')).is_admin = True
            db.commit()
        assert stop_request(other, body, view).status_code == 404
    assert stop_request(client, body, view, expected_request_id=str(uuid4())).status_code == 409
    for changes in ({'reason': ''}, {'reason': 'x' * 501}, {'reason': '一行\n两行'}, {'reason': '一段\u2028两段'},
                    {'operator': '\tbad'}, {'unexpected': True}, {'expected_request_id': 'not-uuid'}):
        assert stop_request(client, body, view, **changes).status_code == 422
    assert client.post('/v1/source-materials/requests/not-uuid/stop', json=stop_payload(view)).status_code == 422


@pytest.mark.parametrize('phase', ['stop-insert', 'audit', 'lost-ack'])
def test_stop_commit_uncertainty_is_atomic_and_recovered_only_by_original_lookup(material_app, monkeypatch, phase):
    from sqlalchemy import event, text
    from sqlalchemy.orm import Session
    from tire_api.service import QueryService
    client, app, _ = material_app
    body, view, calls = unconfirmed_material(client, app, monkeypatch)
    audit, commit, reached = QueryService.audit, Session.commit, []
    def reject_insert(_connection, _cursor, sql, *_args):
        if sql.startswith('INSERT INTO source_material_stops'):
            reached.append(phase)
            raise RuntimeError('private stop insertion detail')
    def reject_audit(service, session_id, action, **detail):
        if action == 'source_material_stopped':
            reached.append(phase)
            raise RuntimeError('private stop audit detail')
        return audit(service, session_id, action, **detail)
    def lose_ack(db):
        if any(row.__class__.__name__ == 'SourceMaterialStop' for row in db.new):
            reached.append(phase)
            commit(db)
            raise RuntimeError('private stop acknowledgement detail')
        return commit(db)
    with monkeypatch.context() as local:
        if phase == 'stop-insert':
            event.listen(app.state.database.engine, 'before_cursor_execute', reject_insert)
        elif phase == 'audit':
            local.setattr(QueryService, 'audit', reject_audit)
        else:
            local.setattr(Session, 'commit', lose_ack)
        try:
            response = stop_request(client, body, view)
        finally:
            if phase == 'stop-insert':
                event.remove(app.state.database.engine, 'before_cursor_execute', reject_insert)
    assert reached == [phase]
    assert response.status_code == 503 and response.json()['detail']['code'] == 'source_material_stop_commit_unconfirmed'
    assert 'private stop' not in response.text
    recovered = client.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history').json()
    assert recovered['state'] == ('stopped_unconfirmed' if phase == 'lost-ack' else 'processing_unconfirmed')
    with app.state.database.sessions() as db:
        assert db.execute(text('SELECT COUNT(*) FROM source_material_stops')).scalar() == int(phase == 'lost-ack')
    assert calls == [1]


def test_two_stop_writers_share_one_immutable_decision_and_one_audit(material_app, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import select, text
    from tire_api.db import AuditEvent
    client, app, _ = material_app
    body, view, _calls = unconfirmed_material(client, app, monkeypatch)
    barrier = Barrier(2)
    def write():
        barrier.wait(timeout=4)
        return stop_request(client, body, view)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(write), pool.submit(write)
        responses = [first.result(timeout=8), second.result(timeout=8)]
    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()['effect'] for response in responses) == ['already_stopped', 'stopped']
    assert responses[0].json()['request'] == responses[1].json()['request']
    with app.state.database.sessions() as db:
        assert db.execute(text('SELECT COUNT(*) FROM source_material_stops')).scalar() == 1
        audits = db.scalars(select(AuditEvent).where(AuditEvent.action == 'source_material_stopped')).all()
        assert len(audits) == 1 and audits[0].detail == {'request_id': view['request_id'],
            'operator': stop_payload(view)['operator'], 'reason': stop_payload(view)['reason']}


@pytest.mark.parametrize('operation', ['sql-update', 'sql-delete', 'sql-replace', 'orm-update', 'orm-delete'])
def test_stop_is_append_only_in_sql_and_orm(material_app, monkeypatch, operation):
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from tire_api.source_material_models import SourceMaterialStop
    client, app, _ = material_app
    body, view, _calls = unconfirmed_material(client, app, monkeypatch)
    response = stop_request(client, body, view)
    assert response.status_code == 200
    if operation.startswith('sql-'):
        sql = {'sql-update': 'UPDATE source_material_stops SET reason=reason',
            'sql-delete': 'DELETE FROM source_material_stops',
            'sql-replace': 'INSERT OR REPLACE INTO source_material_stops SELECT * FROM source_material_stops'}[operation]
        with app.state.database.engine.connect() as connection:
            with pytest.raises(IntegrityError, match='source_material_immutable'):
                connection.exec_driver_sql(sql)
            connection.rollback()
    else:
        with app.state.database.sessions() as db:
            row = db.scalar(select(SourceMaterialStop))
            if operation == 'orm-update':
                row.reason = '改写'
            else:
                db.delete(row)
            with pytest.raises(ValueError, match='只能追加'):
                db.flush()
            db.rollback()
    assert client.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history').json() == response.json()['request']


@pytest.mark.parametrize('damage', ['fingerprint', 'request-fingerprint-rehashed', 'owner-rehashed',
    'payload-hash-rehashed', 'payload-request-rehashed', 'reason-rehashed', 'time-rehashed', 'both-ledgers', 'request'])
def test_damaged_stop_or_both_stop_and_outcome_fail_closed_on_every_read(material_app, monkeypatch, damage):
    from datetime import timedelta
    from sqlalchemy import select, text
    from tire_api.source_material_models import SourceMaterialOutcome, SourceMaterialStop
    from tire_api.source_materials import outcome_fingerprint, stop_fingerprint
    from tire_api.db import utcnow
    client, app, _ = material_app
    body, view, _calls = unconfirmed_material(client, app, monkeypatch)
    assert stop_request(client, body, view).status_code == 200
    if damage == 'both-ledgers':
        with app.state.database.sessions() as db:
            outcome = SourceMaterialOutcome(request_id=view['request_id'], state='failed',
                failure_code='source_material_timeout', document_id=None, receipt=None,
                created_at=utcnow())
            outcome.fingerprint = outcome_fingerprint(outcome)
            db.add(outcome)
            db.commit()
    else:
        with app.state.database.sessions() as db:
            row = db.scalar(select(SourceMaterialStop))
            if damage == 'fingerprint':
                updates = {'fingerprint': '0' * 64}
            elif damage == 'request':
                updates = {'operator': '篡改请求'}
            else:
                if damage == 'request-fingerprint-rehashed':
                    row.request_fingerprint = '0' * 64
                elif damage == 'owner-rehashed':
                    row.actor_user_id = str(uuid4())
                elif damage == 'payload-hash-rehashed':
                    row.payload_hash = '0' * 64
                elif damage == 'payload-request-rehashed':
                    row.payload = {**row.payload, 'expected_request_id': str(uuid4())}
                    from tire_api.domain import digest
                    row.payload_hash = digest(row.payload)
                elif damage == 'reason-rehashed':
                    row.reason = '与冻结payload不符'
                elif damage == 'time-rehashed':
                    row.stopped_at -= timedelta(days=365)
                updates = {column.name: getattr(row, column.name) for column in row.__table__.columns}
                updates['fingerprint'] = stop_fingerprint(row)
            db.rollback()
        table = 'source_material_requests' if damage == 'request' else 'source_material_stops'
        with app.state.database.engine.begin() as connection:
            connection.exec_driver_sql(f'DROP TRIGGER {table}_no_update')
            params = {key: json.dumps(value, ensure_ascii=False) if key == 'payload' else value
                for key, value in updates.items()}
            connection.execute(text(f'UPDATE {table} SET ' + ','.join(key + '=:' + key for key in params)), params)
    for response in (client.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history'),
                     client.get('/v1/source-materials/requests?mode=history'),
                     client.post('/v1/source-materials/captures', json=body), stop_request(client, body, view)):
        assert response.status_code == 503 and response.json()['detail']['code'] == 'source_material_integrity_failed'


def test_stop_remains_visible_across_same_user_sessions_and_logout(material_app, monkeypatch):
    from admin_support import ADMIN_PASSWORD
    client, app, _ = material_app
    body, view, calls = unconfirmed_material(client, app, monkeypatch)
    with TestClient(app) as same:
        assert same.post('/v1/auth/login', json={'username': 'material-admin', 'password': ADMIN_PASSWORD}).status_code == 200
        stopped = stop_request(same, body, view)
        assert stopped.status_code == 200
        assert same.post('/v1/auth/logout').status_code == 200
    assert client.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history').json() == stopped.json()['request']
    assert calls == [1]


@pytest.mark.parametrize('change', ['role', 'session-owner'])
def test_stop_rereads_authentication_after_acquiring_ingestion_lock(material_app, monkeypatch, change):
    from sqlalchemy import select, update
    from tire_api.db import User, UserSession
    from tire_api.service import QueryService
    client, app, _ = material_app
    body, view, _calls = unconfirmed_material(client, app, monkeypatch)
    lock, reached = QueryService.lock_ingestion, []
    def revoke(service):
        if not reached:
            reached.append(1)
            service.db.rollback()
            with app.state.database.sessions() as db:
                if change == 'role':
                    db.scalar(select(User)).is_admin = False
                else:
                    db.execute(update(UserSession).values(user_id=None))
                db.commit()
        return lock(service)
    with monkeypatch.context() as local:
        local.setattr(QueryService, 'lock_ingestion', revoke)
        response = stop_request(client, body, view)
    assert reached == [1] and response.status_code == 403


@pytest.mark.parametrize('completion', ['success', 'failure'])
def test_late_capture_reloads_and_checks_original_request_even_after_fully_rehashed_corruption(material_app, monkeypatch, completion):
    from sqlalchemy import func, select, text
    from tire_api.db import EvidenceDocument, EvidenceObject
    from tire_api.domain import digest
    from tire_api.source_material_models import SourceMaterialOutcome, SourceMaterialRequest
    from tire_api.source_materials import request_fingerprint
    client, app, _ = material_app
    async def fetch(policy):
        with app.state.database.sessions() as db:
            row = db.scalar(select(SourceMaterialRequest))
            row.operator = '不同的署名'
            row.payload = {**row.payload, 'operator': row.operator}
            row.request_hash = digest(row.payload)
            updates = {'operator': row.operator, 'payload': json.dumps(row.payload),
                'request_hash': row.request_hash, 'fingerprint': request_fingerprint(row)}
            db.rollback()
        with app.state.database.engine.begin() as connection:
            connection.exec_driver_sql('DROP TRIGGER source_material_requests_no_update')
            connection.execute(text('UPDATE source_material_requests SET operator=:operator,payload=:payload,'
                'request_hash=:request_hash,fingerprint=:fingerprint'), updates)
        if completion == 'failure':
            raise robots_failure()
        return obtained(policy)
    monkeypatch.setattr(app.state.material_transport, 'fetch', fetch)
    response = client.post('/v1/source-materials/captures', json=payload(client))
    assert response.status_code == 503 and response.json()['detail']['code'] == 'source_material_integrity_failed'
    with app.state.database.sessions() as db:
        for model in (SourceMaterialOutcome, EvidenceDocument, EvidenceObject):
            assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize('damage', ['stop-json', 'stop-time', 'request-json', 'outcome-json'])
def test_raw_undecodable_stopped_graph_fails_closed_after_owner_scope(material_app, monkeypatch, damage):
    from sqlalchemy import select
    from tire_api.db import User, utcnow
    from tire_api.source_material_models import SourceMaterialOutcome
    from tire_api.source_materials import outcome_fingerprint
    client, app, _ = material_app
    body, view, calls = unconfirmed_material(client, app, monkeypatch)
    assert stop_request(client, body, view).status_code == 200
    if damage == 'outcome-json':
        # Deliberate impossible graph: even an undecodable outcome must not
        # bypass the fixed response for stop/outcome coexistence.
        with app.state.database.sessions() as db:
            outcome = SourceMaterialOutcome(request_id=view['request_id'], state='failed',
                failure_code='source_material_timeout', document_id=None, receipt=None, created_at=utcnow())
            outcome.fingerprint = outcome_fingerprint(outcome)
            db.add(outcome)
            db.commit()
    table, column, value = {
        'stop-json': ('source_material_stops', 'payload', '{invalid-json'),
        'stop-time': ('source_material_stops', 'stopped_at', 'not-a-timestamp'),
        'request-json': ('source_material_requests', 'payload', '{invalid-json'),
        'outcome-json': ('source_material_outcomes', 'receipt', '{invalid-json'),
    }[damage]
    with app.state.database.engine.begin() as connection:
        connection.exec_driver_sql(f'DROP TRIGGER {table}_no_update')
        connection.exec_driver_sql(f'UPDATE {table} SET {column}=?', (value,))
    with TestClient(app) as other:
        register_admin(other, 'stop-corruption-other')
        with app.state.database.sessions() as db:
            db.scalar(select(User).where(User.username == 'stop-corruption-other')).is_admin = True
            db.commit()
        assert other.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history').status_code == 404
        assert other.get('/v1/source-materials/requests?mode=history').json()['items'] == []
        assert stop_request(other, body, view).status_code == 404
    # Turning off exception propagation exposes the actual HTTP failure mode;
    # 500 is a failure, not an accepted substitute for integrity 503.
    with TestClient(app, raise_server_exceptions=False) as owner:
        owner.cookies.update(client.cookies)
        responses = (owner.get('/v1/source-materials/requests/' + body['idempotency_key'] + '?mode=history'),
            owner.get('/v1/source-materials/requests?mode=history'),
            owner.post('/v1/source-materials/captures', json=body), stop_request(owner, body, view))
        assert [(response.status_code, response.json().get('detail', {}).get('code')
            if response.status_code == 503 else None) for response in responses] == [
            (503, 'source_material_integrity_failed')] * 4
    assert calls == [1]


def test_terminal_winner_commits_while_overlapping_stop_waits_on_the_real_ingestion_lock(material_app, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sqlalchemy import event, func, select, text
    from tire_api.db import AuditEvent, EvidenceDocument, EvidenceObject
    from tire_api.source_material_models import SourceMaterialOutcome, SourceMaterialRequest
    client, app, _ = material_app
    calls = success_transport(app, monkeypatch)
    body = payload(client)
    terminal_entered, release_terminal, stop_lock_attempted = Event(), Event(), Event()
    winning_connections = []
    def observe(connection, _cursor, statement, *_args):
        if statement.startswith('INSERT INTO source_material_outcomes'):
            assert connection.in_transaction()
            winning_connections.append(connection)
            terminal_entered.set()
            assert release_terminal.wait(8), 'terminal SQL gate was not released'
        elif (statement.strip().upper() == 'BEGIN IMMEDIATE' and terminal_entered.is_set()
                and winning_connections and connection is not winning_connections[0]):
            # This is the real competing SQL attempt, before sqlite blocks on
            # the winner's write transaction, rather than a thread-start flag.
            stop_lock_attempted.set()
    # The capture's synchronous SQL event pauses its ASGI event loop. A second
    # TestClient without a lifespan uses a separate portal for the actual Stop.
    stopper = TestClient(app)
    stopper.cookies.update(client.cookies)
    event.listen(app.state.database.engine, 'before_cursor_execute', observe)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending_capture = pool.submit(client.post, '/v1/source-materials/captures', json=body)
            try:
                assert terminal_entered.wait(4)
                with app.state.database.sessions() as db:
                    reserved = db.scalar(select(SourceMaterialRequest).where(
                        SourceMaterialRequest.idempotency_key == body['idempotency_key']))
                    assert reserved is not None
                    view = {'request_id': reserved.id}
                pending_stop = pool.submit(stop_request, stopper, body, view)
                assert stop_lock_attempted.wait(4), 'Stop never attempted the real ingestion lock'
                assert not pending_stop.done()
            finally:
                release_terminal.set()
            captured = pending_capture.result(timeout=8)
            stopped = pending_stop.result(timeout=8)
    finally:
        release_terminal.set()
        event.remove(app.state.database.engine, 'before_cursor_execute', observe)
        stopper.close()
    assert captured.status_code == 201 and captured.json()['state'] == 'succeeded'
    assert stopped.status_code == 200 and stopped.json() == {'effect': 'already_terminal',
        'request': {key: value for key, value in captured.json().items() if key != 'replayed'}}
    assert len(winning_connections) == 1 and calls == [POLICY['policy_id']]
    with app.state.database.sessions() as db:
        assert db.execute(text('SELECT COUNT(*) FROM source_material_stops')).scalar() == 0
        for model in (SourceMaterialOutcome, EvidenceDocument, EvidenceObject):
            assert db.scalar(select(func.count()).select_from(model)) == 1
        assert sorted(db.scalars(select(AuditEvent.action).where(AuditEvent.action.like('source_material_%')))) == [
            'source_material_received', 'source_material_requested']
