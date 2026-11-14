"""Chinese recall subscriptions through the normal API, Worker and task stream."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import importlib.util
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from tire_api.adapters import samr as source
from tire_api.db import utcnow
from tire_api.samr_monitor_models import SamrMonitorJob, SamrMonitorRun, SamrNotification
from test_samr import IDENTITY, NOTICE, notice_body, search_body
from test_samr_recalls import context, run

RULES = '/v1/samr-recall-monitor-rules'
NOTIFICATIONS = '/v1/samr-recall-notifications'


def create_rule(client, **settings):
    response = client.post(RULES, json={'name': 'Synthetic Chinese recall monitor', 'enabled': True,
        'query': {'operation': 'search', 'keyword': '轮胎', 'page_limit': 2, 'notice_limit': 2, 'text': ''}, **settings})
    assert response.status_code == 201, response.text
    return response.json()


def notifications(client, **params):
    response = client.get(NOTIFICATIONS, params={'mode': 'history', **params})
    assert response.status_code == 200, response.text
    return response.json()


def worker():
    spec = importlib.util.spec_from_file_location('samr_monitor_worker',
        Path(__file__).resolve().parents[3] / 'apps/worker/monitor.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def rolling(context, monkeypatch):
    from tire_api import samr_monitoring as queue
    client, adapter, database = context
    monkeypatch.setattr(queue, 'SOURCE_INTERVAL', 0)
    adapter.total = 2
    adapter.search_calls = 0
    adapter.listing_change = False
    adapter.duplicate = False
    adapter.content = 'Initial batch'
    adapter.fail_reference = None
    adapter.after_receive = None

    async def fetch(query, cached=None, *, on_observation=None):
        adapter.calls.append(deepcopy(query))
        if adapter.offline or adapter.fail_reference is not None and query.get('reference') == adapter.fail_reference:
            return {'status': 'unavailable', 'reason': 'upstream_timeout'}
        value = {'status': 'not_modified' if adapter.not_modified else 'ok', 'url': source.query_url(query),
            'content_type': 'application/json' if query['operation'] == 'search' else 'text/html',
            'parser_version': source.PARSER_VERSION, 'parser_identity': deepcopy(IDENTITY), 'etag': '"synthetic"'}
        if not adapter.not_modified:
            if query['operation'] == 'search':
                adapter.search_calls += 1
                body = search_body(total=adapter.total, page=int(query['page']))
                if adapter.listing_change and adapter.search_calls > 1:
                    body = body.replace('合成轮胎公告', '合成轮胎修订公告')
                    body = body.replace('胎</em>公告', '胎</em>修订公告')
                if adapter.duplicate and query['page'] == '2':
                    body = body.replace(f'{15:032x}', f'{0:032x}')
            else:
                body = notice_body(query['reference']).replace('合成处理措施。', adapter.content)
            value.update(body=body, document=source.parse_document(body, query))
            if on_observation:
                on_observation(value)
        if adapter.after_receive:
            adapter.after_receive(query)
        return value

    adapter.fetch = fetch
    return client, adapter, database


def cycle(env):
    return asyncio.run(worker().run_samr_cycle(env[2], max_jobs=1, adapter=env[1]))


def due(database, rule):
    with database.sessions() as db:
        db.get(SamrMonitorJob, rule['job']['id']).next_due_at = utcnow() - timedelta(seconds=1)
        db.commit()


def latest_run(client, rule):
    response = client.get(RULES + '/' + rule['id'] + '/runs', params={'mode': 'history'})
    assert response.status_code == 200, response.text
    return response.json()['items'][0]


def test_search_worker_records_two_pass_coverage_evidence_and_task_events(rolling):
    client, adapter, _ = rolling
    rule = create_rule(client)
    result = cycle(rolling)
    assert result['results'][0]['state'] == 'samr_complete', result
    assert [item['operation'] for item in adapter.calls] == ['search', 'search', 'notice', 'notice']
    saved = latest_run(client, rule)
    assert saved['coverage']['status'] == 'complete'
    assert saved['coverage']['source_results_fully_covered'] is True
    assert saved['coverage']['listing_consistency'] == 'two_pass_equal'
    assert len(saved['selected_notices']) == 2 and len(saved['checks']) == 4
    assert all(item['snapshot_id'] and item['verification_id'] for item in saved['checks'])
    path = '/v1/monitor-tasks/samr/' + rule['job']['id']
    task = client.get(path).json()['task']
    assert task['state'] == 'succeeded' and task['source_id'] == source.SOURCE_ID
    events = client.get(path + '/events').json()
    assert [item['phase'] for item in events['items']] == ['claimed', 'running', 'finished']
    assert events['items'][-1]['run_id'] == saved['id']
    assert notifications(client)['total'] == 2
    item = notifications(client)['items'][0]
    assert item['run_id'] == saved['id'] and item['lag_seconds'] >= 0
    assert item['queued_at'] and item['observed_at'] and item['applicability'] == 'not_assessed'
    assert client.get(item['observation']['evidence_path']).status_code == 200
    assert client.get('/v1/monitor-tasks', params={'kind': 'samr', 'source_id': source.SOURCE_ID, 'state': 'succeeded'}).json()['total'] == 1
    assert client.get('/v1/monitor-tasks', params={'kind': 'samr', 'source_id': 'nhtsa-us-recalls'}).json()['total'] == 0
    assert cycle(rolling)['jobs'] == 0


def test_configured_scope_completion_preserves_uncovered_source_results(rolling):
    client, adapter, _ = rolling
    adapter.total = 16
    rule = create_rule(client, query={'operation': 'search', 'keyword': '', 'page_limit': 1, 'notice_limit': 1})
    assert cycle(rolling)['results'][0]['state'] == 'samr_complete'
    coverage = latest_run(client, rule)['coverage']
    assert coverage['status'] == 'complete' and coverage['declared_total'] == 16
    assert coverage['expected_pages'] == 1 and coverage['selected_notice_count'] == 1
    assert coverage['source_results_fully_covered'] is False


def test_notifications_are_visible_before_the_next_notice_and_before_final_run(rolling):
    client, adapter, _ = rolling
    rule = create_rule(client)
    observed = []

    def inspect(query):
        if query.get('reference', '').endswith(f'{1:032x}.html'):
            item = notifications(client)['items'][0]
            assert item['run_id'] is None and item['attempt_id']
            observed.append(item['id'])

    adapter.after_receive = inspect
    assert cycle(rolling)['results'][0]['state'] == 'samr_complete'
    assert len(observed) == 1 and latest_run(client, rule)['notification_count'] == 2


def test_partial_failure_retains_deliveries_and_retry_deduplicates(rolling):
    client, adapter, database = rolling
    rule = create_rule(client)
    adapter.fail_reference = NOTICE['reference'].replace('a' * 32, f'{1:032x}')
    assert cycle(rolling)['results'][0]['state'] == 'source_unavailable'
    saved = latest_run(client, rule)
    assert saved['coverage']['status'] == 'incomplete' and saved['notification_count'] == 1
    assert saved['checks'][-1]['snapshot_id'] is None
    adapter.fail_reference = None
    due(database, rule)
    assert cycle(rolling)['results'][0]['state'] == 'samr_complete'
    assert notifications(client)['total'] == 2


@pytest.mark.parametrize('kind', ['listing_change', 'duplicate'])
def test_unstable_or_duplicate_listing_saves_incomplete_receipts(rolling, kind):
    client, adapter, _ = rolling
    setattr(adapter, kind, True)
    adapter.total = 16 if kind == 'duplicate' else 2
    rule = create_rule(client)
    result = cycle(rolling)
    assert result['results'][0]['state'] == 'samr_incomplete', result
    assert latest_run(client, rule)['coverage']['status'] == 'incomplete'
    assert notifications(client)['total'] == 0
    assert all(item['operation'] == 'search' for item in adapter.calls)


def test_notice_304_deduplicates_and_keyword_matches_removed_text(rolling):
    client, adapter, database = rolling
    rule = create_rule(client, query={**NOTICE, 'text': 'Initial batch'})
    assert cycle(rolling)['results'][0]['state'] == 'samr_complete'
    adapter.not_modified = True
    due(database, rule)
    assert cycle(rolling)['results'][0]['state'] == 'samr_complete'
    assert latest_run(client, rule)['checks'][0]['state'] == 'live_verified_304'
    assert notifications(client)['total'] == 1
    adapter.not_modified, adapter.content = False, 'Revised batch'
    due(database, rule)
    assert cycle(rolling)['results'][0]['state'] == 'samr_complete'
    items = notifications(client)['items']
    assert len(items) == 2 and items[0]['observation']['event']['kind'] == 'content_changed'


def test_old_observation_is_excluded_and_read_state_is_private(rolling):
    client, adapter, database = rolling
    run(client)
    rule = create_rule(client, query={**NOTICE, 'text': ''})
    assert cycle(rolling)['results'][0]['state'] == 'samr_complete'
    assert notifications(client)['total'] == 0
    adapter.content = 'Changed batch'
    due(database, rule)
    cycle(rolling)
    item = notifications(client)['items'][0]
    path = NOTIFICATIONS + '/' + item['id'] + '/read'
    assert client.put(path, json={'read': True}).status_code == 200
    assert notifications(client, unread=True)['total'] == 0
    assert client.put(path, json={'read': False}).json()['read_at'] is None
    with TestClient(client.app) as other:
        assert notifications(other)['total'] == 0
        assert other.put(path, json={'read': True}).status_code == 404
        assert other.get(RULES + '/' + rule['id'], params={'mode': 'history'}).status_code == 404
        assert other.get('/v1/monitor-tasks/samr/' + rule['job']['id']).status_code == 404


@pytest.mark.parametrize('enabled', [False, True])
def test_pause_or_revision_during_fetch_blocks_adoption_and_delivery(rolling, enabled):
    client, adapter, _ = rolling
    rule = create_rule(client, query={**NOTICE, 'text': ''})

    def revise(_query):
        response = client.post(RULES + '/' + rule['id'] + '/revisions', json={
            'name': 'Revised', 'enabled': enabled, 'interval_seconds': 3600, 'expected_revision': 1})
        assert response.status_code == 200

    adapter.after_receive = revise
    result = cycle(rolling)
    assert result['results'][0]['state'] == 'lease_lost', result
    assert notifications(client)['total'] == 0
    assert latest_run(client, rule)['checks'] == []
    assert client.get('/v1/monitor-tasks/samr/' + rule['job']['id']).json()['task']['state'] == 'interrupted'


def test_source_generation_change_blocks_adoption(rolling):
    from tire_api.source_settings import SourceSettingPreview, SourceSettingDecision, preview_source_setting, append_source_setting
    client, adapter, database = rolling
    rule = create_rule(client, query={**NOTICE, 'text': ''})

    def pause(_query):
        with database.sessions() as db:
            preview = preview_source_setting(db, source.SOURCE_ID, SourceSettingPreview(action='pause'), registry=client.app.state.registry)
            decision = SourceSettingDecision(action='pause', expected_revision=preview['revision'],
                expected_fingerprint=preview['fingerprint'], operator='Synthetic tester', reason='Synthetic generation test')
            append_source_setting(db, source.SOURCE_ID, decision, 'synthetic-samr', str(uuid4()), registry=client.app.state.registry)

    adapter.after_receive = pause
    result = cycle(rolling)
    assert result['results'][0]['state'] == 'source_unavailable', result
    assert notifications(client)['total'] == 0
    assert client.get('/v1/monitor-tasks/samr/' + rule['job']['id']).json()['task']['state'] == 'blocked'


def test_lease_is_renewed_before_query_and_expired_attempt_is_recoverable(rolling):
    from tire_api import samr_monitoring as queue
    client, adapter, database = rolling
    rule = create_rule(client, query={**NOTICE, 'text': ''})
    abandoned = queue.claim_job(database)
    with database.sessions() as db:
        db.get(SamrMonitorJob, rule['job']['id']).lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    claim = queue.claim_job(database)
    assert claim['attempt_id'] != abandoned['attempt_id']
    worker().begin_attempt(database, claim, queue.guard_claim)
    with database.sessions() as db:
        db.get(SamrMonitorJob, rule['job']['id']).lease_until = utcnow() + timedelta(seconds=5)
        db.commit()
    assert asyncio.run(queue.execute_scan(database, claim, adapter))[0] == 'samr_complete'
    with database.sessions() as db:
        from tire_api.db import utc
        assert utc(db.get(SamrMonitorJob, rule['job']['id']).lease_until) > utcnow() + timedelta(seconds=500)
    assert queue.finish_job(database, claim, 'samr_complete')
    assert not queue.finish_job(database, abandoned, 'samr_complete')
    events = client.get('/v1/monitor-tasks/samr/' + rule['job']['id'] + '/events').json()['items']
    assert any(item['reason'] == 'lease_expired' for item in events)


def test_rule_idempotency_revision_history_and_archival(rolling):
    client, _, _ = rolling
    key = str(uuid4())
    payload = {'name': 'Synthetic replay', 'enabled': True, 'query': NOTICE}
    first = client.post(RULES, json=payload, headers={'Idempotency-Key': key}).json()
    assert client.post(RULES, json=payload, headers={'Idempotency-Key': key}).json()['id'] == first['id']
    assert client.post(RULES, json={**payload, 'name': 'Different'}, headers={'Idempotency-Key': key}).status_code == 409
    path = RULES + '/' + first['id'] + '/revisions'
    edit = {'name': first['name'], 'enabled': True, 'archived': True, 'interval_seconds': 3600, 'expected_revision': 1}
    edit_key = str(uuid4())
    for _ in range(2):
        response = client.post(path, json=edit, headers={'Idempotency-Key': edit_key})
        assert response.status_code == 200 and response.json()['revision'] == 2
        assert not response.json()['enabled'] and response.json()['job']['next_due_at'] is None
    assert client.post(path, json=edit).status_code == 409
    assert client.get(RULES).json()['total'] == 0
    detail = client.get(RULES + '/' + first['id'], params={'mode': 'history'}).json()
    assert [item['revision'] for item in detail['history']] == [2, 1]
    assert cycle(rolling)['jobs'] == 0


@pytest.mark.parametrize('query', [
    {'operation': 'search', 'page_limit': True}, {'operation': 'search', 'page_limit': 61},
    {'operation': 'search', 'notice_limit': 901}, {'operation': 'search', 'keyword': 'a\x00b'},
    {'operation': 'notice', 'reference': 'https://other.example/recall'},
    {**NOTICE, 'page_limit': 1}, {'operation': 'search', 'reference': NOTICE['reference']},
])
def test_invalid_query_scope_is_rejected(rolling, query):
    assert rolling[0].post(RULES, json={'name': 'Invalid scope', 'query': query}).status_code == 422


def test_journal_and_notification_bindings_are_immutable(rolling):
    client, _, database = rolling
    create_rule(client, query=NOTICE)
    cycle(rolling)
    with database.sessions() as db:
        notification = db.scalar(select(SamrNotification))
        notification.attempt_id = 'different'
        with pytest.raises(ValueError, match='仅可修改'):
            db.commit()
        db.rollback()
        saved = db.scalar(select(SamrMonitorRun))
        saved.coverage = {}
        with pytest.raises(ValueError, match='只能追加'):
            db.commit()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(SamrMonitorRun)) == 1


def test_normal_scheduler_includes_samr_and_reconnectable_stream(rolling, monkeypatch):
    from tire_api import monitor_tasks
    client, adapter, database = rolling
    rule = create_rule(client, query=NOTICE)
    module = worker()
    original = module.run_samr_cycle

    async def configured(database, **options):
        return await original(database, adapter=adapter, **options)

    monkeypatch.setattr(module, 'run_samr_cycle', configured)
    result = asyncio.run(module.run_scheduled_cycle(database, max_jobs=1))
    assert result['jobs'] == 1 and result['results'][0]['kind'] == 'samr', result
    path = '/v1/monitor-tasks/samr/' + rule['job']['id']
    before = client.get(path + '/events').json()
    monkeypatch.setattr(monitor_tasks, 'STREAM_SECONDS', 0.01)
    monkeypatch.setattr(monitor_tasks, 'POLL_SECONDS', 0.001)
    response = client.get(path + '/events/stream', headers={'Last-Event-ID': before['items'][0]['cursor']})
    assert response.status_code == 200 and 'text/event-stream' in response.headers['content-type']
    assert before['items'][0]['id'] not in response.text
    assert before['items'][-1]['id'] in response.text
    assert client.get(path + '/events').json()['items'] == before['items']
