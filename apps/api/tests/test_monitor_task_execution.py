"""Durable Worker attempt behavior with private synthetic sources only."""
import asyncio
from datetime import timedelta
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from tire_api import monitoring, recall_monitoring
from tire_api.db import MonitorJob, MonitorRun, QueryRun, RawCapture, utc, utcnow
from tire_api.monitor_task_models import MonitorTaskAttempt, MonitorTaskEvent
from tire_api.recall_models import RecallMonitorJob, RecallMonitorRun
from test_source_access import access_app, change_source, during_fetch, mutate_source
from test_core import QUERY
from test_recalls import CAMPAIGN


spec = importlib.util.spec_from_file_location(
    'task_execution_monitor', Path(__file__).resolve().parents[3] / 'apps/worker/monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


def queue_for(kind):
    return monitoring if kind == 'tire' else recall_monitoring


def models_for(kind):
    return (MonitorJob, MonitorRun) if kind == 'tire' else (RecallMonitorJob, RecallMonitorRun)


def events_for(database, claim=None):
    with database.sessions() as db:
        statement = select(MonitorTaskEvent)
        if claim is not None:
            statement = statement.where(MonitorTaskEvent.attempt_id == claim['attempt_id'])
        return db.scalars(statement.order_by(MonitorTaskEvent.sequence)).all()


def run_worker(env, kind, monkeypatch):
    database = env[1].state.database
    if kind == 'tire':
        monkeypatch.setattr(monitor, 'registry', env[2]['tire'])
        return asyncio.run(monitor.run_scheduled_cycle(database, max_jobs=1))
    return asyncio.run(monitor.run_recall_cycle(database, max_jobs=1, adapter=env[2]['recall']))


def create_rule(env, kind):
    client = env[0]
    if kind == 'tire':
        response = client.post('/v1/alert-rules', json={'name': 'Synthetic progress rule',
            'source_id': 'fixture', 'query': QUERY['query'], 'enabled': True})
    else:
        response = client.post('/v1/recall-monitor-rules', json={'name': 'Synthetic campaign progress',
            'query': {'campaign_number': CAMPAIGN}, 'enabled': True})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize('kind', ['tire', 'recall'])
def test_claim_returns_a_durable_attempt_identity(access_app, kind):
    create_rule(access_app, kind)
    database = access_app[1].state.database
    claim = queue_for(kind).claim_job(database)
    assert claim is not None
    assert isinstance(claim.get('attempt_id'), str) and claim['attempt_id'], claim
    assert claim['kind'] == kind
    job_model, _ = models_for(kind)
    with database.sessions() as db:
        attempt = db.get(MonitorTaskAttempt, claim['attempt_id'])
        job = db.get(job_model, claim['id'])
        assert attempt.job_id == job.id and job.lease_token == claim['token']
        assert attempt.query == claim['query'] and attempt.source_id == claim['source_id']
        assert attempt.source_access_generation == claim['source_access_generation']
        assert utc(attempt.started_at) == claim['started_at']
        assert attempt.lease_token_hash != claim['token']
    event, = events_for(database, claim)
    assert (event.phase, event.state, event.sequence) == ('claimed', 'running', 1)


@pytest.mark.parametrize('kind', ['tire', 'recall'])
def test_failed_attempt_creation_rolls_back_the_lease(access_app, monkeypatch, kind):
    from tire_api import monitor_tasks
    rule = create_rule(access_app, kind)
    database = access_app[1].state.database
    start = monitor_tasks.start_attempt_locked

    def fail_after_start(db, lane, claim):
        start(db, lane, claim)
        raise RuntimeError('synthetic transaction failure')

    monkeypatch.setattr(monitor_tasks, 'start_attempt_locked', fail_after_start)
    with pytest.raises(RuntimeError, match='synthetic transaction failure'):
        queue_for(kind).claim_job(database)
    job_model, _ = models_for(kind)
    with database.sessions() as db:
        job = db.get(job_model, rule['job']['id'])
        assert job.lease_token is None and job.lease_until is None
        assert db.scalar(select(func.count()).select_from(MonitorTaskAttempt)) == 0
        assert db.scalar(select(func.count()).select_from(MonitorTaskEvent)) == 0


@pytest.mark.parametrize('kind', ['tire', 'recall'])
def test_worker_commits_three_phases_with_real_query_and_run_ids(access_app, monkeypatch, kind):
    create_rule(access_app, kind)
    result = run_worker(access_app, kind, monkeypatch)
    assert result['jobs'] == 1 and result['results'][0]['state'] == 'live'
    assert result['results'][0]['finalized'] is True
    database = access_app[1].state.database
    events = events_for(database)
    assert [row.phase for row in events] == ['claimed', 'running', 'finished']
    assert [row.sequence for row in events] == [1, 2, 3]
    assert len({row.attempt_id for row in events}) == 1
    finished = events[-1]
    assert finished.state == 'succeeded' and finished.result_state == 'live'
    _, run_model = models_for(kind)
    with database.sessions() as db:
        query = db.get(QueryRun, finished.query_id)
        run = db.get(run_model, finished.run_id)
        assert query is not None and query.state == 'live' and query.fallback_policy == 'never'
        assert run is not None and run.job_id == finished.job_id and run.state == 'live'
        assert db.scalar(select(func.count()).select_from(run_model)) == 1


@pytest.mark.parametrize('kind', ['tire', 'recall'])
@pytest.mark.parametrize('mutation,expected', [('pause', 'blocked'), ('aba', 'blocked'), ('notes', 'succeeded')])
def test_worker_stage_receipt_preserves_generation_fencing(access_app, monkeypatch, kind, mutation, expected):
    create_rule(access_app, kind)
    during_fetch(access_app, kind, monkeypatch, mutation)
    result = run_worker(access_app, kind, monkeypatch)
    assert result['results'][0]['finalized'] is True
    database = access_app[1].state.database
    events = events_for(database)
    assert [row.phase for row in events] == ['claimed', 'running', 'finished']
    assert events[-1].state == expected
    assert events[-1].result_state == ('live' if expected == 'succeeded' else 'source_unavailable')
    assert events[-1].reason == (None if expected == 'succeeded' else 'source_access_changed')
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(RawCapture)) == 1


@pytest.mark.parametrize('kind', ['tire', 'recall'])
@pytest.mark.parametrize('mutation,reason', [('pause', 'source_access_changed'), ('archive', 'source_access_changed'),
                                          ('aba', 'source_access_changed'), ('unpin', 'source_access_pin_missing')])
def test_block_before_worker_entry_does_not_invent_running_phase(access_app, monkeypatch, kind, mutation, reason):
    create_rule(access_app, kind)
    queue = queue_for(kind)
    original = queue.claim_job

    def claim_and_change(database):
        claim = original(database)
        if mutation == 'unpin':
            claim.pop('source_access_generation')
        elif mutation == 'archive':
            change_source(access_app, kind, 'archive')
        else:
            mutate_source(access_app, kind, mutation)
        return claim

    monkeypatch.setattr(monitor if kind == 'tire' else queue, 'claim_job', claim_and_change)
    result = run_worker(access_app, kind, monkeypatch)
    assert result['results'][0]['reason'] == reason and result['results'][0]['finalized']
    events = events_for(access_app[1].state.database)
    assert [row.phase for row in events] == ['claimed', 'finished']
    assert events[-1].state == 'blocked' and events[-1].result_state == 'source_unavailable'
    assert events[-1].reason == reason and events[-1].query_id is None
    assert access_app[2][kind].calls == []


@pytest.mark.parametrize('kind', ['tire', 'recall'])
@pytest.mark.parametrize('blocker', ['pause', 'archive', 'disabled_rule', 'archived_rule'])
def test_expiry_recovery_commits_even_when_every_job_is_ineligible(access_app, kind, blocker):
    rule = create_rule(access_app, kind)
    database = access_app[1].state.database
    queue = queue_for(kind)
    now = utcnow()
    claim = queue.claim_job(database, now=now)
    if blocker in {'pause', 'archive'}:
        change_source(access_app, kind, blocker)
    elif kind == 'tire' and blocker == 'archived_rule':
        response = access_app[0].post('/v1/alert-rules/' + rule['id'] + '/state',
            json={'expected_revision': 1, 'action': 'archive'})
        assert response.status_code == 200, response.text
    else:
        values = {'expected_revision': 1, 'name': rule['name'], 'enabled': False}
        if kind == 'recall':
            values['archived'] = blocker == 'archived_rule'
            response = access_app[0].post('/v1/recall-monitor-rules/' + rule['id'] + '/revisions', json=values)
        else:
            response = access_app[0].put('/v1/alert-rules/' + rule['id'], json=values)
        assert response.status_code == 200, response.text
    after = now + timedelta(seconds=queue.LEASE_SECONDS + 1)
    assert queue.claim_job(database, now=after) is None
    assert queue.claim_job(database, now=after) is None
    events = events_for(database, claim)
    assert [row.phase for row in events] == ['claimed', 'finished']
    assert events[-1].state == 'interrupted' and events[-1].result_state == 'lease_lost'
    assert events[-1].reason in {'lease_expired', 'lease_lost'}
    assert utc(events[-1].created_at) == after


@pytest.mark.parametrize('kind', ['tire', 'recall'])
def test_stale_finish_cannot_change_replacement_or_duplicate_legacy_run(access_app, kind):
    create_rule(access_app, kind)
    database = access_app[1].state.database
    queue = queue_for(kind)
    now = utcnow()
    stale = queue.claim_job(database, now=now)
    later = now + timedelta(seconds=queue.LEASE_SECONDS + 1)
    replacement = queue.claim_job(database, now=later)
    assert replacement['attempt_id'] != stale['attempt_id']
    assert not queue.finish_job(database, stale, 'live', now=later)
    job_model, run_model = models_for(kind)
    with database.sessions() as db:
        assert db.get(job_model, replacement['id']).lease_token == replacement['token']
        assert db.scalar(select(func.count()).select_from(run_model)) == 0
    assert queue.finish_job(database, replacement, 'live_verified_304', now=later + timedelta(seconds=1))
    assert not queue.finish_job(database, replacement, 'worker_error', now=later + timedelta(seconds=2))
    assert [row.state for row in events_for(database, stale)] == ['running', 'interrupted']
    assert [row.state for row in events_for(database, replacement)] == ['running', 'succeeded']
    assert [row.sequence for row in events_for(database)] == [1, 2, 3, 4]
    with database.sessions() as db:
        run, = db.scalars(select(run_model)).all()
        assert run.state == 'live_verified_304'


@pytest.mark.parametrize('kind', ['tire', 'recall'])
@pytest.mark.parametrize('failure,outcome', [(monitoring.LeaseLost, 'interrupted'), (RuntimeError, 'failed')])
def test_worker_exception_paths_record_one_safe_terminal(access_app, monkeypatch, kind, failure, outcome):
    from tire_api.recalls import RecallService
    create_rule(access_app, kind)
    marker = 'synthetic private exception details'

    async def fail(*_args, **_kwargs):
        raise failure(marker)

    monkeypatch.setattr(monitor.QueryService if kind == 'tire' else RecallService, 'execute', fail)
    result = run_worker(access_app, kind, monkeypatch)
    assert result['results'][0]['state'] == ('lease_lost' if outcome == 'interrupted' else 'worker_error')
    events = events_for(access_app[1].state.database)
    assert [row.phase for row in events] == ['claimed', 'running', 'finished']
    assert events[-1].state == outcome
    assert marker not in json.dumps(result) and marker not in str([row.reason for row in events])
    _, run_model = models_for(kind)
    with access_app[1].state.database.sessions() as db:
        # Recall interruption now records completion before releasing its shared
        # source reservation, so discovery observes the actual cooldown.
        expected_runs = 0 if outcome == 'interrupted' and kind == 'tire' else 1
        assert db.scalar(select(func.count()).select_from(run_model)) == expected_runs


@pytest.mark.parametrize('kind', ['tire', 'recall'])
def test_legacy_lease_finishes_without_backfilling_attempts(access_app, kind):
    rule = create_rule(access_app, kind)
    database = access_app[1].state.database
    queue = queue_for(kind)
    job_model, run_model = models_for(kind)
    now = utcnow()
    claim = {'id': rule['job']['id'], 'token': 'synthetic-legacy-token', 'started_at': now}
    with database.sessions() as db:
        job = db.get(job_model, claim['id'])
        job.lease_token, job.lease_until = claim['token'], now + timedelta(minutes=10)
        db.commit()
    assert queue.finish_job(database, claim, 'live', now=now + timedelta(seconds=1))
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(MonitorTaskAttempt)) == 0
        assert db.scalar(select(func.count()).select_from(MonitorTaskEvent)) == 0
        assert db.scalar(select(func.count()).select_from(run_model)) == 1


@pytest.mark.parametrize('kind', ['tire', 'recall'])
def test_rejected_finish_rolls_back_run_event_and_schedule_together(access_app, monkeypatch, kind):
    from tire_api import monitor_tasks
    create_rule(access_app, kind)
    database = access_app[1].state.database
    queue = queue_for(kind)
    claim = queue.claim_job(database)
    finish = monitor_tasks.finish_attempt_locked

    def reject_after_event(*args, **kwargs):
        assert finish(*args, **kwargs)
        return False

    monkeypatch.setattr(monitor_tasks, 'finish_attempt_locked', reject_after_event)
    assert not queue.finish_job(database, claim, 'live')
    job_model, run_model = models_for(kind)
    with database.sessions() as db:
        job = db.get(job_model, claim['id'])
        assert job.lease_token == claim['token'] and job.last_finished_at is None
        assert db.scalar(select(func.count()).select_from(run_model)) == 0
    assert [row.phase for row in events_for(database, claim)] == ['claimed']
    monkeypatch.setattr(monitor_tasks, 'finish_attempt_locked', finish)
    assert queue.finish_job(database, claim, 'live')
