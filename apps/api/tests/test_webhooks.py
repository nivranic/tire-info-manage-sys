"""Private real SQL/ASGI contracts; only the outbound HTTP edge is controlled."""
from datetime import timedelta
import asyncio
import hashlib
import hmac
import os
from pathlib import Path
from uuid import uuid4

import pytest

if not os.environ.get('R78_TEST_STORAGE_ROOT') or os.environ.get('TIRE_DATABASE_URL') != os.environ.get('DATABASE_URL'):
    raise RuntimeError('r78_private_runner_required')

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from test_core import FixtureRegistry
from webhook_support import (ControlledWebhookAdapter, add_private_notification, add_tire_notification,
    configured_environment, create_subscription, seed_webhook_case)
from tire_api.db import AlertEvent, ChangeEvent, NotificationDelivery, utc, utcnow
from tire_api.main import create_app
from tire_api.monitoring import record_alerts
from tire_api.service import QueryService
from tire_api.webhook_delivery import claim_delivery, dispatch_claim, finish_delivery, run_webhook_cycle
from tire_api.webhook_models import WebhookAttempt, WebhookCompletion, WebhookEnvelope, WebhookQueue


@pytest.fixture
def case(tmp_path, monkeypatch):
    assert tmp_path.resolve().is_relative_to(Path(os.environ['R78_TEST_STORAGE_ROOT']).resolve())
    url = configured_environment(monkeypatch, tmp_path)
    app = create_app(url, FixtureRegistry())
    with TestClient(app, backend_options={'loop_factory': asyncio.SelectorEventLoop}) as client:
        yield seed_webhook_case(client)


def rows(case, subscription):
    result = case.client.get('/v1/webhooks/' + subscription['id'] + '/deliveries?mode=history')
    assert result.status_code == 200, result.text
    return result.json()['items']


def detail(case, subscription, delivery):
    result = case.client.get('/v1/webhooks/' + subscription['id'] + '/deliveries/' + delivery['id'] + '?mode=history')
    assert result.status_code == 200, result.text
    return result.json()


def test_paused_default_and_future_only_explicit_enable(case):
    subscription = create_subscription(case, ['tire_monitor'])['response']
    add_tire_notification(case)
    assert rows(case, subscription) == []
    response = case.client.post('/v1/webhooks/' + subscription['id'] + '/state',
        json={'expected_revision': 1, 'action': 'resume', 'target_fingerprint': subscription['target_fingerprint'],
            'acknowledged_external_delivery': True}, headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 200, response.text
    add_tire_notification(case)
    assert len(rows(case, subscription)) == 1


@pytest.mark.parametrize('channel', ['tire_monitor', 'recall_monitor', 'interest'])
def test_three_real_producers_freeze_reference_only_body(case, channel):
    subscription = create_subscription(case, [channel], enabled=True)['response']
    notice = add_tire_notification(case) if channel == 'tire_monitor' else add_private_notification(case, channel)
    deliveries = rows(case, subscription)
    assert len(deliveries) >= 1
    for delivery in deliveries:
        frozen = detail(case, subscription, delivery)
        assert set(frozen['body']) == {'schema', 'delivery_id', 'channel', 'notification_id', 'event_id',
            'domain', 'occurred_at', 'data_scope', 'notice'}
        assert frozen['body']['channel'] == channel
        assert frozen['body']['data_scope'] == 'notification_reference_only'
        assert frozen['body']['domain'] == ('tire' if channel == 'interest' else None)
        assert frozen['attempt_history'] == []


def test_hmac_exact_bytes_stable_delivery_and_retry_after(case):
    subscription = create_subscription(case, ['tire_monitor'], enabled=True)['response']
    add_tire_notification(case)
    delivery = rows(case, subscription)[0]
    now = utcnow()
    adapter = ControlledWebhookAdapter(outcomes=[{'http_status': 503, 'error_code': None, 'retry_after': 3}, 204])
    claim = claim_delivery(case.database, now=now)
    assert asyncio.run(dispatch_claim(case.database, claim, adapter=adapter, now=now))['finalized']
    first = detail(case, subscription, delivery)
    assert first['state'] == 'pending'
    assert utc(__import__('datetime').datetime.fromisoformat(first['next_attempt_at'])) == utc(now) + timedelta(seconds=3)
    assert claim_delivery(case.database, now=now + timedelta(seconds=2)) is None
    claim = claim_delivery(case.database, now=now + timedelta(seconds=3))
    assert asyncio.run(dispatch_claim(case.database, claim, adapter=adapter, now=now + timedelta(seconds=3)))['finalized']
    assert adapter.calls[0]['raw_body'] == adapter.calls[1]['raw_body']
    target = next(iter(case.database.webhook_catalog.targets.values()))
    for call in adapter.calls:
        headers = call['headers']
        prefix = '.'.join(headers[key] for key in ('X-Tire-Webhook-Timestamp', 'X-Tire-Webhook-Id', 'X-Tire-Webhook-Attempt')) + '.'
        expected = hmac.new(target.key, prefix.encode('ascii') + call['raw_body'], hashlib.sha256).hexdigest()
        assert headers['X-Tire-Webhook-Signature'] == 'v1=' + expected
        assert hashlib.sha256(call['raw_body']).hexdigest() == delivery['body_sha256']
    assert detail(case, subscription, delivery)['state'] == 'delivered'


def test_notification_and_outbox_rollback_as_one_transaction(case):
    subscription = create_subscription(case, ['tire_monitor'], enabled=True)['response']
    def fail(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lower().startswith('insert into webhook_queue'):
            raise RuntimeError('synthetic_outbox_failure')
    with case.database.sessions() as db:
        before = db.scalar(select(func.count()).select_from(NotificationDelivery))
    event.listen(case.database.engine, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='synthetic_outbox_failure'):
            add_tire_notification(case)
    finally:
        event.remove(case.database.engine, 'before_cursor_execute', fail)
    with case.database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(NotificationDelivery)) == before
    assert rows(case, subscription) == []


def test_dedup_producer_replay_and_read_state_do_not_enqueue(case):
    subscription = create_subscription(case, ['tire_monitor'], enabled=True)['response']
    notice = add_tire_notification(case)
    with case.database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        record_alerts(db, [db.get(ChangeEvent, notice['change_id'])])
        db.commit()
    assert case.client.put('/v1/notifications/' + notice['id'] + '/read', json={'read': True}).status_code == 200
    assert len(rows(case, subscription)) == 1
    assert detail(case, subscription, rows(case, subscription)[0])['body']['notification_id'] == notice['id']


def test_expiry_unknown_fences_late_response_and_retains_same_body(case):
    subscription = create_subscription(case, ['tire_monitor'], enabled=True)['response']
    add_tire_notification(case)
    now = utcnow()
    claim = claim_delivery(case.database, now=now)
    assert claim_delivery(case.database, now=now + timedelta(seconds=31)) is None
    assert not finish_delivery(case.database, claim, {'http_status': 204, 'error_code': None}, now=now + timedelta(seconds=32))
    history = detail(case, subscription, rows(case, subscription)[0])
    assert history['attempt_history'][0]['state'] == 'unknown'
    assert history['state'] == 'pending'
    new = claim_delivery(case.database, now=now + timedelta(seconds=91))
    assert new['number'] == 2 and new['token'] != claim['token']
    assert not finish_delivery(case.database, claim, {'http_status': 204}, now=now + timedelta(seconds=92))
    assert finish_delivery(case.database, new, {'http_status': 204}, now=now + timedelta(seconds=92))


def test_cancel_inflight_stops_future_dispatch_but_keeps_factual_completion(case):
    subscription = create_subscription(case, ['tire_monitor'], enabled=True)['response']
    add_tire_notification(case)
    now = utcnow()
    claim = claim_delivery(case.database, now=now)
    delivery = rows(case, subscription)[0]
    response = case.client.post('/v1/webhooks/' + subscription['id'] + '/deliveries/' + delivery['id'] + '/cancel',
        json={'expected_attempts': 1, 'acknowledged': True}, headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 200, response.text
    assert finish_delivery(case.database, claim, {'http_status': 204}, now=now + timedelta(seconds=1))
    frozen = detail(case, subscription, delivery)
    assert frozen['state'] == 'cancelled' and frozen['attempt_history'][0]['state'] == 'delivered'
    assert claim_delivery(case.database, now=now + timedelta(seconds=2)) is None


def test_manual_retry_adds_budget_with_operation_and_replay_is_read_only(case):
    subscription = create_subscription(case, ['tire_monitor'], enabled=True)['response']
    add_tire_notification(case)
    now = utcnow()
    claim = claim_delivery(case.database, now=now)
    assert finish_delivery(case.database, claim, {'http_status': 400}, now=now)
    delivery = rows(case, subscription)[0]
    path = '/v1/webhooks/' + subscription['id'] + '/deliveries/' + delivery['id'] + '/retry'
    key = str(uuid4())
    body = {'expected_attempts': 1, 'acknowledged': True}
    result = case.client.post(path, json=body, headers={'Idempotency-Key': key})
    assert result.status_code == 200, result.text
    assert result.json()['response']['max_attempts'] == 10
    replay = case.client.post(path, json=body, headers={'Idempotency-Key': key})
    assert replay.status_code == 200 and replay.json()['replayed'] is True
    assert replay.json()['response'] == result.json()['response']
    assert rows(case, subscription)[0]['max_attempts'] == 10


def test_mutable_queue_cannot_invent_attempt_budget(case):
    subscription = create_subscription(case, ['tire_monitor'], enabled=True)['response']
    add_tire_notification(case)
    delivery = rows(case, subscription)[0]
    with case.database.engine.begin() as connection:
        connection.execute(text('UPDATE webhook_queue SET max_attempts=20 WHERE id=:id'), {'id': delivery['id']})
    response = case.client.get('/v1/webhooks/' + subscription['id'] + '/deliveries/' + delivery['id'] + '?mode=history')
    assert response.status_code == 409
    assert claim_delivery(case.database) is None


def test_authenticated_guard_runs_before_invalid_body(case):
    other = TestClient(case.app, backend_options={'loop_factory': asyncio.SelectorEventLoop})
    try:
        response = other.post('/v1/webhooks', json={'bad': 'body'})
        assert response.status_code == 401
        assert other.get('/v1/webhooks/targets').status_code == 401
    finally:
        other.close()


@pytest.fixture
def pre022(tmp_path, monkeypatch):
    from tire_api.db import Base
    from tire_api.knowledge_models import initialize_search
    from tire_api.webhook_models import MODELS
    from tire_api.external_api_models import TABLES as EXTERNAL_TABLES
    from test_identity_migration import seed_legacy
    from version_registry import EXPECTED_SCHEMA_VERSIONS
    url = configured_environment(monkeypatch, tmp_path)
    database = create_app(url).state.database
    new_tables = {model.__tablename__ for model in MODELS} | set(EXTERNAL_TABLES)
    with database.engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables
            if table.name not in new_tables])
        connection.exec_driver_sql('CREATE TABLE tire_schema_versions '
            '(version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version in EXPECTED_SCHEMA_VERSIONS[:21]:
            connection.execute(text('INSERT INTO tire_schema_versions (version) VALUES (:version)'), {'version': version})
        initialize_search(connection)
    with database.sessions() as db:
        seed_legacy(db, namespace='SYNTHETIC-R78', product_code='SYNTHETIC-PRE022', watch=True)
    yield database, new_tables
    database.close()


def test_022_only_adds_tables_preserves_all_predecessor_rows_and_is_idempotent(pre022):
    from test_ai_stream_migration import snapshot
    from version_registry import EXPECTED_SCHEMA_VERSIONS
    database, new_tables = pre022
    before = snapshot(database)
    assert not new_tables & before['tables']
    database.initialize()
    first = snapshot(database)
    database.initialize()
    after = snapshot(database)
    assert first == after
    assert after['tables'] - before['tables'] == new_tables
    assert not before['tables'] - after['tables']
    assert [row for row in after['schema'] if row[2] in before['tables']] == before['schema']
    for table in before['tables'] - {'tire_schema_versions'}:
        assert after['rows'][table] == before['rows'][table], table
    assert all(not after['rows'][table] for table in new_tables)
    with database.engine.connect() as connection:
        assert connection.execute(text('SELECT version FROM tire_schema_versions ORDER BY version')).scalars().all() == EXPECTED_SCHEMA_VERSIONS
        assert connection.exec_driver_sql('PRAGMA integrity_check').scalar_one() == 'ok'
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []


def test_022_failure_rolls_back_tables_triggers_and_version(pre022, monkeypatch):
    from tire_api import migrations
    from test_ai_stream_migration import snapshot
    database, new_tables = pre022
    before = snapshot(database)
    upgrade = migrations.upgrade
    def failed(connection):
        upgrade(connection)
        raise RuntimeError('synthetic_webhook_migration_failure')
    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'upgrade', failed)
        with pytest.raises(RuntimeError, match='synthetic_webhook_migration_failure'):
            database.initialize()
    assert snapshot(database) == before
    database.initialize()
    assert snapshot(database)['tables'] - before['tables'] == new_tables


def test_webhooks_once_cli_dispatches_real_queue_without_acquisition(case, monkeypatch, capsys):
    import importlib.util
    import sys
    from tire_api import webhook_delivery
    spec = importlib.util.spec_from_file_location('r78_webhook_cli',
        Path(__file__).resolve().parents[3] / 'apps/worker/monitor.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    subscription = create_subscription(case, ['tire_monitor'], enabled=True)['response']
    add_tire_notification(case)
    adapter = ControlledWebhookAdapter()
    monkeypatch.setattr(webhook_delivery, 'WebhookTransport', lambda: adapter)
    async def forbidden(*_args, **_kwargs):
        raise AssertionError('acquisition_cycle_must_not_run_for_webhooks_once')
    monkeypatch.setattr(worker, 'run_scheduled_cycle', forbidden)
    monkeypatch.setattr(worker, 'run_cycle', forbidden)
    monkeypatch.setattr(sys, 'argv', ['monitor', '--webhooks-once'])
    asyncio.run(worker.main())
    assert len(adapter.calls) == 1
    assert rows(case, subscription)[0]['state'] == 'delivered'
    import json
    output = json.loads(capsys.readouterr().out.strip())
    assert output['jobs'] == 1 and output['results'][0]['finalized'] is True
