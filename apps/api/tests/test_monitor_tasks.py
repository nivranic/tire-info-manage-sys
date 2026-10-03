"""Private monitor journal/API checks; no source, Parser, model or normal DB."""
import asyncio
from contextlib import contextmanager
from datetime import timedelta
import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, func, inspect, select, text

from tire_api.db import AlertRule, AlertRuleRevision, MonitorJob, MonitorRun, uid, utcnow
from tire_api.main import SESSION_COOKIE, create_app
from tire_api.monitor_task_models import MonitorTaskAttempt, MonitorTaskEvent
from tire_api import monitor_tasks as tasks
from tire_api.recall_models import RecallMonitorJob, RecallMonitorRule, RecallMonitorRun, RecallRuleRevision, SOURCE_ID
from tire_api.service import QueryService


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '0')
    monkeypatch.setenv('TI_OBSERVABILITY_ENABLED', '0')
    app = create_app('sqlite://')
    with TestClient(app) as client:
        client.get('/health')
        yield client, app.state.database, app


def seed(client, database, kind='tire', *, existing_job=None):
    owner = client.cookies.get(SESSION_COOKIE)
    with database.sessions() as db:
        job_id, rule_id = existing_job or uid(), uid()
        if kind == 'tire':
            job = db.get(MonitorJob, job_id)
            if job is None:
                db.add(MonitorJob(id=job_id, source_id='michelin-us', query={'model': 'Pilot Sport 4'}, next_due_at=utcnow()))
                db.flush()
            db.add(AlertRule(id=rule_id, job_id=job_id))
            db.flush()
            db.add(AlertRuleRevision(rule_id=rule_id, revision=1, name='Synthetic tire rule',
                interval_seconds=21600, enabled=True, archived=False, kinds=['facts_changed'], fields=[],
                conditions={}, actor_session_id=owner))
        else:
            db.add(RecallMonitorJob(id=job_id, session_id=owner, campaign_number='23T001000', next_due_at=utcnow()))
            db.flush()
            db.add(RecallMonitorRule(id=rule_id, session_id=owner, job_id=job_id))
            db.flush()
            db.add(RecallRuleRevision(rule_id=rule_id, revision=1, name='Synthetic recall rule',
                interval_seconds=21600, enabled=True, archived=False))
        db.commit()
    return job_id, rule_id, owner


def claim(database, kind, job_id, *, now=None):
    now = now or utcnow()
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        model = MonitorJob if kind == 'tire' else RecallMonitorJob
        job = db.get(model, job_id)
        job.lease_token, job.lease_until = uid(), now + timedelta(seconds=600)
        value = {'id': job.id, 'token': job.lease_token, 'started_at': now,
            'source_id': job.source_id if kind == 'tire' else SOURCE_ID,
            'query': job.query if kind == 'tire' else {'campaign_number': job.campaign_number},
            'source_access_generation': 0}
        value['attempt_id'] = tasks.start_attempt_locked(db, kind, value)
        db.commit()
        return value


def finish(database, value, *, state='live', reason=None, query_id=None):
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        assert tasks.mark_running_locked(db, value)
        kind = value['kind']
        job_model = MonitorJob if kind == 'tire' else RecallMonitorJob
        run_model = MonitorRun if kind == 'tire' else RecallMonitorRun
        job = db.get(job_model, value['id'])
        run = run_model(id=uid(), job_id=job.id, lease_token=value['token'], state=state,
            reason=reason, started_at=value['started_at'], finished_at=utcnow())
        db.add(run)
        db.flush()
        job.lease_token, job.lease_until = None, None
        assert tasks.finish_attempt_locked(db, value, state, reason, query_id=query_id, run_id=run.id)
        db.commit()
        return run.id


def url(kind, job_id):
    return f'/v1/monitor-tasks/{kind}/{job_id}'


@pytest.mark.parametrize('kind', ['tire', 'recall'])
def test_real_phases_pagination_original_run_link_and_private_fields(setup, kind):
    client, database, _ = setup
    job_id, rule_id, owner = seed(client, database, kind)
    before = client.get(url(kind, job_id)).json()
    assert before['task']['state'] == 'never_run' and before['attempts'] == []
    value = claim(database, kind, job_id)
    active = client.get(url(kind, job_id)).json()
    assert active['task']['state'] == 'running' and active['task']['phase'] == 'claimed'
    query_id = uid()
    run_id = finish(database, value, query_id=query_id)
    detail = client.get(url(kind, job_id)).json()
    assert detail['task']['state'] == 'succeeded' and detail['task']['terminal']
    assert detail['task']['last_attempt']['query_id'] == query_id
    assert detail['task']['last_attempt']['result_state'] == 'live'
    assert detail['attempts_total'] == 1 and detail['legacy_runs_total'] == 0
    assert detail['task']['last_run'] is None
    page = client.get(url(kind, job_id) + '/events', params={'cursor': before['cursor'], 'limit': 2}).json()
    assert page['has_more'] and [row['sequence'] for row in page['items']] == [1, 2]
    next_page = client.get(url(kind, job_id) + '/events', params={'cursor': page['next_cursor']}).json()
    assert not next_page['has_more'] and len(next_page['items']) == 1
    assert next_page['items'][0]['run_id'] == run_id
    assert next_page['items'][0]['query_id'] == query_id
    assert [row['phase'] for row in page['items'] + next_page['items']] == ['claimed', 'running', 'finished']
    body = json.dumps(detail) + json.dumps(page) + json.dumps(next_page)
    assert value['token'] not in body and owner not in body
    assert 'lease_token' not in body and 'actor_session_id' not in body
    assert client.get('/v1/monitor-tasks', params={'rule_id': rule_id, 'state': 'succeeded'}).json()['total'] == 1


def test_tire_is_shared_recall_owner_is_private_for_all_reads(setup):
    client, database, app = setup
    tire, _, _ = seed(client, database)
    recall, _, _ = seed(client, database, 'recall')
    with TestClient(app) as stranger:
        stranger.get('/health')
        assert stranger.get(url('tire', tire)).status_code == 200
        assert stranger.get('/v1/monitor-tasks').json()['total'] == 1
        for suffix in ('', '/events', '/events/stream'):
            assert stranger.get(url('recall', recall) + suffix).status_code == 404
        assert stranger.get(url('recall', recall) + '/events/stream', params={'cursor': 'bad'},
                            headers={'Last-Event-ID': 'other'}).status_code == 404


def test_shared_tire_job_one_row_and_archived_rules_keep_history(setup):
    client, database, _ = setup
    job_id, rule_id, owner = seed(client, database)
    seed(client, database, existing_job=job_id)
    value = claim(database, 'tire', job_id)
    finish(database, value)
    with database.sessions() as db:
        db.add(AlertRuleRevision(rule_id=rule_id, revision=2, name='Archived synthetic',
            interval_seconds=21600, enabled=False, archived=True, kinds=[], fields=[], conditions={}, actor_session_id=owner))
        db.commit()
    listing = client.get('/v1/monitor-tasks').json()
    assert listing['total'] == 1 and listing['items'][0]['rule_count'] == 2
    assert client.get(url('tire', job_id)).json()['attempts_total'] == 1


@pytest.mark.parametrize('reason', sorted(tasks.BLOCKED_REASONS))
def test_management_failures_are_blocked_without_exposing_generic_text(setup, reason):
    client, database, _ = setup
    job_id, _, _ = seed(client, database)
    value = claim(database, 'tire', job_id)
    finish(database, value, state='source_unavailable', reason=reason)
    result = client.get(url('tire', job_id)).json()['task']
    assert result['state'] == 'blocked'
    assert result['last_attempt']['result_state'] == 'source_unavailable'
    assert result['last_attempt']['reason'] == reason


def test_unknown_exception_text_and_legacy_reasons_are_never_returned(setup):
    client, database, _ = setup
    job_id, _, _ = seed(client, database)
    value = claim(database, 'tire', job_id)
    finish(database, value, state='worker_error', reason='synthetic_private_marker cookie token')
    detail = client.get(url('tire', job_id)).json()
    assert 'synthetic_private_marker' not in json.dumps(detail)
    assert detail['task']['last_attempt']['reason'] == 'task_execution_failed'


def test_expired_lease_get_is_pure_unknown_then_worker_reclaims_once(setup):
    client, database, _ = setup
    job_id, _, _ = seed(client, database)
    value = claim(database, 'tire', job_id, now=utcnow() - timedelta(seconds=700))
    for _ in range(2):
        detail = client.get(url('tire', job_id)).json()
        assert detail['task']['state'] == 'result_unknown' and not detail['task']['terminal']
    assert client.get('/v1/monitor-tasks?state=result_unknown').json()['total'] == 1
    assert client.get('/v1/monitor-tasks?state=running').json()['total'] == 0
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(MonitorTaskEvent)) == 1
        QueryService(db, None).lock_ingestion()
        assert tasks.expire_attempts_locked(db, 'tire') == 1
        assert tasks.expire_attempts_locked(db, 'tire') == 0
        assert not tasks.finish_attempt_locked(db, value, 'live')
        assert not tasks.interrupt_attempt_locked(db, value, 'lease_lost')
        db.commit()
    assert client.get(url('tire', job_id)).json()['task']['state'] == 'interrupted'
    assert client.get('/v1/monitor-tasks?state=interrupted').json()['total'] == 1
    newer = claim(database, 'tire', job_id)
    finish(database, newer)
    events = client.get(url('tire', job_id) + '/events').json()['items']
    assert [row['sequence'] for row in events] == [1, 2, 3, 4, 5]
    assert len({row['id'] for row in events}) == 5


def test_helpers_rollback_atomically_and_terminal_is_immutable(setup):
    client, database, _ = setup
    job_id, _, _ = seed(client, database)
    value = claim(database, 'tire', job_id)
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        assert tasks.mark_running_locked(db, value)
        db.rollback()
    assert len(client.get(url('tire', job_id) + '/events').json()['items']) == 1
    finish(database, value)
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        assert not tasks.finish_attempt_locked(db, value, 'worker_error')
        assert not tasks.mark_running_locked(db, value)
        row = db.scalar(select(MonitorTaskEvent).where(MonitorTaskEvent.phase == 'finished'))
        row.reason = 'lease_lost'
        with pytest.raises(ValueError, match='只能追加'):
            db.flush()
        db.rollback()


def test_legacy_runs_paginate_without_fake_events_or_backfill(setup):
    client, database, _ = setup
    job_id, _, _ = seed(client, database)
    with database.sessions() as db:
        for index in range(3):
            db.add(MonitorRun(id=uid(), job_id=job_id, lease_token=uid(), state='live', reason=None,
                started_at=utcnow() - timedelta(days=index + 1), finished_at=utcnow() - timedelta(days=index)))
        db.commit()
    response = client.get(url('tire', job_id), params={'legacy_offset': 1, 'legacy_limit': 1}).json()
    assert response['legacy_runs_total'] == 3 and len(response['legacy_runs']) == 1
    assert response['legacy_runs'][0]['legacy'] is True and response['attempts'] == []
    assert client.get(url('tire', job_id) + '/events').json()['items'] == []
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(MonitorTaskAttempt)) == 0


def test_cursor_binds_task_and_event_uuid_after_restore(setup):
    client, database, _ = setup
    first, _, _ = seed(client, database)
    second, _, _ = seed(client, database)
    value = claim(database, 'tire', first)
    original = client.get(url('tire', first) + '/events').json()['items'][0]
    cross = client.get(url('tire', second) + '/events', params={'cursor': original['cursor']})
    assert cross.status_code == 409
    with database.sessions() as db:
        # Simulate a restored database whose replacement event reuses sequence 1.
        db.execute(delete(MonitorTaskEvent))
        attempt = db.get(MonitorTaskAttempt, value['attempt_id'])
        tasks._append_event(db, attempt, 'claimed', 'running')
        db.commit()
    reset = client.get(url('tire', first) + '/events', params={'cursor': original['cursor']})
    assert reset.status_code == 409 and reset.json()['detail']['code'] == 'task_cursor_reset_required'
    assert client.get(url('tire', first)).json()['cursor'] != original['cursor']


@pytest.mark.parametrize('cursor', ['not-base64', 'W10', 'bnVsbA', 'eyJ2IjoxfQ'])
def test_malformed_cursor_resets_without_raw_echo(setup, cursor):
    client, database, _ = setup
    job_id, _, _ = seed(client, database)
    response = client.get(url('tire', job_id) + '/events', params={'cursor': cursor})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'task_cursor_reset_required'


def test_bounded_input_and_no_automatic_worker_calls(setup):
    client, database, _ = setup
    job_id, _, _ = seed(client, database)
    for path in ['/v1/monitor-tasks?limit=51', url('tire', job_id) + '?attempt_limit=101',
                 url('tire', job_id) + '?legacy_limit=101', url('tire', job_id) + '/events?limit=101']:
        assert client.get(path).status_code == 422
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(MonitorTaskAttempt)) == 0
        assert db.scalar(select(func.count()).select_from(MonitorTaskEvent)) == 0


def test_sse_replays_id_and_last_event_id_with_bounded_end(setup, monkeypatch):
    client, database, _ = setup
    monkeypatch.setattr(tasks, 'STREAM_SECONDS', 0.06)
    monkeypatch.setattr(tasks, 'HEARTBEAT_SECONDS', 0.01)
    monkeypatch.setattr(tasks, 'POLL_SECONDS', 0.01)
    job_id, _, _ = seed(client, database)
    value = claim(database, 'tire', job_id)
    finish(database, value)
    first = client.get(url('tire', job_id) + '/events', params={'limit': 1}).json()['items'][0]
    response = client.get(url('tire', job_id) + '/events/stream', headers={'Last-Event-ID': first['cursor']})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.text.count('event: task_event') == 2
    assert 'event: heartbeat' in response.text and 'event: stream_end' in response.text
    assert 'window_complete' in response.text and f'id: {first["cursor"]}\n' not in response.text
    for frame in response.text.split('\n\n'):
        if 'event: task_event' in frame:
            lines = frame.splitlines()
            assert lines[0][4:] == json.loads(lines[2][6:])['cursor']
    mismatched = client.get(url('tire', job_id) + '/events/stream', params={'cursor': 'other'},
                            headers={'Last-Event-ID': first['cursor']})
    assert mismatched.status_code == 409


def test_disconnected_stream_never_opens_a_database_session(setup):
    _client, _database, _app = setup

    class Disconnected:
        async def is_disconnected(self):
            return True

    class ForbiddenDatabase:
        def sessions(self):
            raise AssertionError('A disconnected stream must not open a session')

    async def consume():
        return [frame async for frame in tasks.stream_events(ForbiddenDatabase(), Disconnected(), 'tire', 'id', 'session', None)]

    assert asyncio.run(consume()) == []


def test_stream_rechecks_anchor_after_restore_and_releases_session_before_yield(setup, monkeypatch):
    client, database, _ = setup
    monkeypatch.setattr(tasks, 'POLL_SECONDS', 0.001)
    job_id, _, owner = seed(client, database)
    claim(database, 'tire', job_id)
    original_sessions = database.sessions
    active = {'count': 0}

    @contextmanager
    def tracked_sessions():
        active['count'] += 1
        try:
            with original_sessions() as db:
                yield db
        finally:
            active['count'] -= 1

    monkeypatch.setattr(database, 'sessions', tracked_sessions)

    class Connected:
        async def is_disconnected(self):
            return False

    async def consume():
        iterator = tasks.stream_events(database, Connected(), 'tire', job_id, owner, None)
        first = await anext(iterator)
        assert 'event: task_event' in first
        assert active['count'] == 0
        with database.sessions() as db:
            db.execute(delete(MonitorTaskEvent))
            db.commit()
        reset = await anext(iterator)
        assert 'event: reset' in reset and 'task_cursor_reset_required' in reset
        assert active['count'] == 0
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)

    asyncio.run(consume())


def test_stream_event_bound_retains_resumable_cursor(setup, monkeypatch):
    client, database, _ = setup
    monkeypatch.setattr(tasks, 'MAX_STREAM_EVENTS', 2)
    monkeypatch.setattr(tasks, 'POLL_SECONDS', 0.001)
    job_id, _, _ = seed(client, database)
    finish(database, claim(database, 'tire', job_id))
    response = client.get(url('tire', job_id) + '/events/stream')
    assert response.text.count('event: task_event') == 2
    ending = [frame for frame in response.text.split('\n\n') if 'event: stream_end' in frame][0]
    cursor = json.loads(ending.split('data: ', 1)[1])['cursor']
    remainder = client.get(url('tire', job_id) + '/events', params={'cursor': cursor}).json()
    assert len(remainder['items']) == 1 and remainder['items'][0]['phase'] == 'finished'


def test_cross_job_run_receipt_cannot_finalize_an_attempt(setup):
    client, database, _ = setup
    first, _, _ = seed(client, database)
    second, _, _ = seed(client, database)
    value = claim(database, 'tire', first)
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        receipt = MonitorRun(id=uid(), job_id=second, lease_token=uid(), state='live',
            started_at=utcnow(), finished_at=utcnow())
        db.add(receipt)
        db.flush()
        with pytest.raises(ValueError, match='run_mismatch'):
            tasks.finish_attempt_locked(db, value, 'live', run_id=receipt.id)
        db.rollback()
    assert client.get(url('tire', first)).json()['task']['terminal'] is False


@pytest.mark.parametrize('kind', ['tire', 'recall'])
def test_legacy_worker_replacing_live_token_has_consistent_unknown_filter(setup, kind):
    client, database, _ = setup
    job_id, _, _ = seed(client, database, kind)
    claim(database, kind, job_id)
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        model = MonitorJob if kind == 'tire' else RecallMonitorJob
        job = db.get(model, job_id)
        # A pre-journal Worker may replace the lease without recording an attempt.
        job.lease_token, job.lease_until = uid(), utcnow() + timedelta(seconds=600)
        db.commit()
    assert client.get(url(kind, job_id)).json()['task']['state'] == 'result_unknown'
    assert client.get('/v1/monitor-tasks', params={'kind': kind, 'state': 'running'}).json()['total'] == 0
    assert client.get('/v1/monitor-tasks', params={'kind': kind, 'state': 'result_unknown'}).json()['total'] == 1


def test_additive_migration_registers_two_tables_without_backfilling_jobs(setup):
    client, database, _ = setup
    job_id, _, _ = seed(client, database)
    with database.engine.begin() as connection:
        before_job = tuple(connection.execute(text('SELECT * FROM monitor_jobs WHERE id=:id'), {'id': job_id}).first())
        MonitorTaskEvent.__table__.drop(connection)
        MonitorTaskAttempt.__table__.drop(connection)
        connection.execute(text("DELETE FROM tire_schema_versions WHERE version='007_monitor_tasks'"))
        before_tables = set(inspect(connection).get_table_names())
    database.initialize()
    database.initialize()
    with database.engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) - before_tables == {'monitor_task_attempts', 'monitor_task_events'}
        assert tuple(connection.execute(text('SELECT * FROM monitor_jobs WHERE id=:id'), {'id': job_id}).first()) == before_job
        assert connection.execute(text("SELECT COUNT(*) FROM tire_schema_versions WHERE version='007_monitor_tasks'")).scalar() == 1
        assert connection.execute(text('SELECT COUNT(*) FROM monitor_task_attempts')).scalar() == 0
