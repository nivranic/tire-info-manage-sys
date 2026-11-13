"""Safety Gate subscriptions through normal APIs and the durable Worker."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import importlib.util
from pathlib import Path
from uuid import uuid4
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from tire_api.adapters import safety_gate as source
from tire_api.db import utcnow
from test_safety_gate import context, index, report, IDENTITY


def create_rule(client, **settings):
    payload = {'name': 'Synthetic rolling safety reports', 'enabled': True,
        'query': {'report_limit': 2, 'text': 'tyre'}, **settings}
    response = client.post('/v1/safety-gate-monitor-rules', json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def notifications(client, **params):
    response = client.get('/v1/safety-gate-notifications', params={'mode': 'history', **params})
    assert response.status_code == 200, response.text
    return response.json()


def worker():
    spec = importlib.util.spec_from_file_location('safety_monitor_worker',
        Path(__file__).resolve().parents[3] / 'apps/worker/monitor.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normal_rule_entry_supports_history_pause_and_account_scope(context):
    client, _adapter, _database = context
    rule = create_rule(client)
    assert rule['query'] == {'report_limit': 2, 'text': 'tyre'}
    assert rule['job']['next_due_at'] and rule['revision'] == 1
    response = client.post('/v1/safety-gate-monitor-rules/' + rule['id'] + '/revisions', json={
        'name': rule['name'], 'enabled': False, 'interval_seconds': 21600, 'expected_revision': 1})
    assert response.status_code == 200, response.text
    assert response.json()['revision'] == 2 and response.json()['job']['next_due_at'] is None
    detail = client.get('/v1/safety-gate-monitor-rules/' + rule['id'], params={'mode': 'history'})
    assert [row['revision'] for row in detail.json()['history']] == [2, 1]
    with TestClient(client.app) as other:
        assert other.get('/v1/safety-gate-monitor-rules').json()['total'] == 0
        assert other.get('/v1/safety-gate-monitor-rules/' + rule['id'], params={'mode': 'history'}).status_code == 404
        assert other.get('/v1/monitor-tasks/safety_gate/' + rule['job']['id']).status_code == 404


def test_rule_create_and_revision_replay_preserve_single_write(context):
    client, _adapter, _database = context
    key = str(uuid4())
    payload = {'name': 'Synthetic replay', 'query': {'report_limit': 4, 'text': ''}, 'enabled': True}
    first = client.post('/v1/safety-gate-monitor-rules', json=payload, headers={'Idempotency-Key': key})
    assert first.status_code == 201, first.text
    repeat = client.post('/v1/safety-gate-monitor-rules', json=payload, headers={'Idempotency-Key': key})
    assert repeat.json()['id'] == first.json()['id']
    assert client.post('/v1/safety-gate-monitor-rules', json={**payload, 'name': 'Different'},
        headers={'Idempotency-Key': key}).status_code == 409
    edit_key = str(uuid4())
    path = '/v1/safety-gate-monitor-rules/' + first.json()['id'] + '/revisions'
    edit = {'name': 'Updated', 'enabled': False, 'interval_seconds': 3600, 'expected_revision': 1}
    for _ in range(2):
        response = client.post(path, json=edit, headers={'Idempotency-Key': edit_key})
        assert response.status_code == 200 and response.json()['revision'] == 2, response.text
    assert client.post(path, json=edit).status_code == 409


@pytest.fixture
def rolling(context, monkeypatch):
    from tire_api import safety_gate_monitoring as queue
    client, adapter, database = context
    monkeypatch.setattr(queue, 'SOURCE_INTERVAL', 0)
    adapter.reports = {}
    adapter.fail_id = None
    adapter.after_receive = None

    def add(identity, week, published, name='Original tyre'):
        reference = 'Report-2026-' + week
        query = {'operation': 'report', 'report_id': identity, 'reference': reference}
        item = ET.fromstring(index(reference, published)).find('weeklyReport')
        item.find('URL').text = source.query_url(query)
        root = ET.fromstring(report())
        root.find('report_week').text = str(int(week))
        root.find('report_date').text = published
        root.find('notifications/name').text = name
        adapter.reports[identity] = (item, ET.tostring(root, encoding='unicode'))

    add('900001', '19', '15/05/2026')
    add('900002', '20', '22/05/2026')

    async def fetch(query, cached=None, *, on_observation=None):
        adapter.calls.append(deepcopy(query))
        if adapter.offline or adapter.fail_id is not None and query.get('report_id') == adapter.fail_id:
            return {'status': 'unavailable', 'reason': 'upstream_timeout'}
        result = {'status': 'ok', 'url': source.query_url(query), 'content_type': 'application/xml',
            'parser_version': source.PARSER_VERSION, 'parser_identity': deepcopy(IDENTITY), 'etag': '"synthetic-monitor"'}
        if adapter.not_modified and cached:
            return {**result, 'status': 'not_modified'}
        if query['operation'] == 'reports':
            root = ET.Element('Safety-Gate')
            for item, _ in adapter.reports.values():
                root.append(deepcopy(item))
            body = ET.tostring(root, encoding='unicode')
        else:
            body = adapter.reports[query['report_id']][1]
        result.update(body=body, document=source.parse_xml(body, query))
        on_observation(result)
        if adapter.after_receive:
            adapter.after_receive(query)
        return result

    adapter.fetch = fetch
    return client, adapter, database, add


def due(database, rule):
    from tire_api.safety_gate_monitor_models import SafetyGateMonitorJob
    with database.sessions() as db:
        db.get(SafetyGateMonitorJob, rule['job']['id']).next_due_at = utcnow() - timedelta(seconds=1)
        db.commit()


def cycle(env):
    return asyncio.run(worker().run_safety_gate_cycle(env[2], max_jobs=1, adapter=env[1]))


def test_worker_scans_newest_reports_and_records_three_task_phases(rolling):
    client, adapter, database, _add = rolling
    rule = create_rule(client)
    result = cycle(rolling)
    assert result['results'][0]['state'] == 'safety_gate_complete', result
    assert [query.get('report_id') for query in adapter.calls] == [None, '900002', '900001']
    task_path = '/v1/monitor-tasks/safety_gate/' + rule['job']['id']
    task = client.get(task_path).json()
    assert task['task']['state'] == 'succeeded' and task['task']['source_id'] == source.SOURCE_ID
    events = client.get(task_path + '/events').json()
    assert [row['phase'] for row in events['items']] == ['claimed', 'running', 'finished']
    assert events['items'][-1]['run_id']
    runs = client.get('/v1/safety-gate-monitor-rules/' + rule['id'] + '/runs', params={'mode': 'history'}).json()
    assert len(runs['items'][0]['checks']) == 3 and runs['items'][0]['coverage'] == 'complete'
    assert notifications(client)['total'] == 1
    notice = notifications(client)['items'][0]
    assert notice['observation']['event']['kind'] == 'first_observed' and notice['applicability'] == 'not_assessed'
    assert client.get(notice['observation']['evidence_path']).status_code == 200
    assert client.get('/v1/monitor-tasks', params={'source_id': source.SOURCE_ID, 'state': 'succeeded'}).json()['total'] == 1
    assert client.get('/v1/monitor-tasks', params={'source_id': 'nhtsa-us-recalls'}).json()['total'] == 0
    assert cycle(rolling)['jobs'] == 0


def test_304_is_deduplicated_and_new_week_enters_rolling_scope(rolling):
    client, adapter, database, add = rolling
    rule = create_rule(client, query={'report_limit': 1, 'text': 'tyre'})
    assert cycle(rolling)['results'][0]['state'] == 'safety_gate_complete'
    adapter.not_modified = True
    due(database, rule)
    assert cycle(rolling)['results'][0]['state'] == 'safety_gate_complete'
    assert notifications(client)['total'] == 1
    runs = client.get('/v1/safety-gate-monitor-rules/' + rule['id'] + '/runs', params={'mode': 'history'}).json()
    assert all(row['state'] == 'live_verified_304' for row in runs['items'][0]['checks'])
    adapter.not_modified = False
    add('900003', '21', '29/05/2026', 'Revised tyre')
    due(database, rule)
    assert cycle(rolling)['results'][0]['state'] == 'safety_gate_complete'
    assert adapter.calls[-1]['report_id'] == '900003'
    values = notifications(client)
    assert values['total'] == 2
    assert values['items'][0]['observation']['event']['changes']['fields.name'] == {'before': 'Original tyre', 'after': 'Revised tyre'}


def test_partial_scan_retains_accepted_checks_and_retry_deduplicates(rolling):
    client, adapter, database, _ = rolling
    rule = create_rule(client)
    adapter.fail_id = '900001'
    result = cycle(rolling)
    assert result['results'][0]['state'] == 'source_unavailable', result
    runs = client.get('/v1/safety-gate-monitor-rules/' + rule['id'] + '/runs', params={'mode': 'history'}).json()
    run = runs['items'][0]
    assert run['coverage'] == 'incomplete' and len(run['checks']) == 3
    assert run['checks'][-1]['snapshot_id'] is None and run['notification_count'] == 1
    adapter.fail_id = None
    due(database, rule)
    assert cycle(rolling)['results'][0]['state'] == 'safety_gate_complete'
    assert notifications(client)['total'] == 1


def test_rule_change_during_fetch_rejects_late_adoption(rolling):
    from tire_api.safety_gate import SafetyGateSnapshot
    from tire_api.safety_gate_alerts import AlertObservation
    client, adapter, database, _ = rolling
    rule = create_rule(client)

    def pause(query):
        if query['operation'] == 'report':
            response = client.post('/v1/safety-gate-monitor-rules/' + rule['id'] + '/revisions', json={
                'name': rule['name'], 'enabled': False, 'interval_seconds': 21600, 'expected_revision': 1})
            assert response.status_code == 200

    adapter.after_receive = pause
    result = cycle(rolling)
    assert result['results'][0]['state'] == 'lease_lost', result
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(SafetyGateSnapshot)) == 1
        assert db.scalar(select(func.count()).select_from(AlertObservation)) == 0
    assert notifications(client)['total'] == 0
    task = client.get('/v1/monitor-tasks/safety_gate/' + rule['job']['id']).json()['task']
    assert task['state'] == 'interrupted' and task['last_attempt']['reason'] == 'safety_gate_monitor_rule_disabled'


@pytest.mark.parametrize('restore', [False, True])
def test_source_generation_blocks_inflight_adoption(rolling, restore):
    from tire_api.source_settings import SourceSettingPreview, SourceSettingDecision, preview_source_setting, append_source_setting
    client, adapter, database, _ = rolling
    rule = create_rule(client)

    def change(query):
        if query['operation'] != 'report':
            return
        for action in (['pause', 'enable'] if restore else ['pause']):
            with database.sessions() as db:
                preview = preview_source_setting(db, source.SOURCE_ID, SourceSettingPreview(action=action), registry=client.app.state.registry)
                decision = SourceSettingDecision(action=action, expected_revision=preview['revision'],
                    expected_fingerprint=preview['fingerprint'], operator='Synthetic tester', reason='Synthetic generation fence')
                append_source_setting(db, source.SOURCE_ID, decision, 'synthetic-safety-gate', str(uuid4()), registry=client.app.state.registry)

    adapter.after_receive = change
    result = cycle(rolling)
    assert result['results'][0]['state'] == 'source_unavailable', result
    assert result['results'][0]['reason'] == 'source_access_changed'
    assert notifications(client)['total'] == 0
    task = client.get('/v1/monitor-tasks/safety_gate/' + rule['job']['id']).json()['task']
    assert task['state'] == 'blocked'


def test_claim_exclusion_expiration_and_stale_completion(rolling):
    from tire_api import safety_gate_monitoring as queue
    from tire_api.monitor_tasks import expire_attempts_locked
    from tire_api.service import QueryService
    from tire_api.safety_gate_monitor_models import SafetyGateMonitorJob
    client, _adapter, database, _ = rolling
    rule = create_rule(client)
    claim = queue.claim_job(database)
    assert queue.claim_job(database) is None
    with database.sessions() as db:
        db.get(SafetyGateMonitorJob, claim['id']).lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    detail = client.get('/v1/monitor-tasks/safety_gate/' + rule['job']['id']).json()
    assert detail['task']['state'] == 'result_unknown'
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        assert expire_attempts_locked(db, 'safety_gate') == 1
        db.commit()
    replacement = queue.claim_job(database)
    assert replacement['token'] != claim['token']
    assert queue.finish_job(database, claim, 'safety_gate_complete') is False
    assert queue.finish_job(database, replacement, 'lease_lost', 'worker_cancelled') is True


def test_notifications_are_private_readable_and_match_previous_content(rolling):
    client, adapter, database, add = rolling
    add('900002', '20', '22/05/2026', 'Specific-Match')
    rule = create_rule(client, query={'report_limit': 1, 'text': 'Specific-Match'})
    cycle(rolling)
    add('900003', '21', '29/05/2026', 'Replacement name')
    due(database, rule)
    cycle(rolling)
    values = notifications(client)
    assert values['total'] == 2
    item = values['items'][0]
    path = '/v1/safety-gate-notifications/' + item['id'] + '/read'
    assert client.put(path, json={'read': True}).json()['read_at']
    assert notifications(client, unread=True)['total'] == 1
    with TestClient(client.app) as other:
        assert notifications(other)['total'] == 0
        assert other.put(path, json={'read': True}).status_code == 404


def test_task_event_pages_and_sse_resume(rolling, monkeypatch):
    from tire_api import monitor_tasks
    client, _adapter, _database, _ = rolling
    rule = create_rule(client)
    cycle(rolling)
    path = '/v1/monitor-tasks/safety_gate/' + rule['job']['id'] + '/events'
    first = client.get(path, params={'limit': 1}).json()
    second = client.get(path, params={'cursor': first['next_cursor'], 'limit': 2}).json()
    assert [item['sequence'] for item in second['items']] == [2, 3]
    monkeypatch.setattr(monitor_tasks, 'STREAM_SECONDS', 0.05)
    monkeypatch.setattr(monitor_tasks, 'POLL_SECONDS', 0.001)
    stream = client.get(path + '/stream', headers={'Last-Event-ID': first['next_cursor']})
    assert stream.status_code == 200 and stream.text.count('event: task_event') == 2
    # Production proxies must not compress and buffer small task events.
    assert 'no-transform' in stream.headers['cache-control']
    assert 'event: stream_end' in stream.text


def test_worker_timeout_has_terminal_receipt(rolling, monkeypatch):
    from tire_api import safety_gate_monitoring as queue
    client, adapter, _database, _ = rolling
    rule = create_rule(client)
    monkeypatch.setattr(queue, 'MAX_SECONDS', 0.02)

    async def delayed(*_args, **_kwargs):
        await asyncio.sleep(10)

    adapter.fetch = delayed
    result = cycle(rolling)
    assert result['results'][0]['reason'] == 'safety_gate_monitor_timeout', result
    task = client.get('/v1/monitor-tasks/safety_gate/' + rule['job']['id']).json()['task']
    assert task['state'] == 'failed' and task['terminal']


def test_main_worker_entry_executes_safety_gate_queue(rolling, monkeypatch):
    client, adapter, database, _ = rolling
    create_rule(client)
    monkeypatch.setattr(source, 'fetch', adapter.fetch)
    monkeypatch.setattr(source, 'supports_parser_deployments', False)
    result = asyncio.run(worker().run_scheduled_cycle(database, max_jobs=1))
    assert result['jobs'] == 1 and result['results'][0]['kind'] == 'safety_gate', result
    assert result['results'][0]['state'] == 'safety_gate_complete', result


def test_success_requires_persisted_query_coverage(rolling):
    from tire_api import safety_gate_monitoring as queue
    client, _adapter, database, _ = rolling
    rule = create_rule(client)
    claim = queue.claim_job(database)
    assert queue.finish_job(database, claim, 'safety_gate_complete')
    assert claim['final_result'] == {'state': 'source_unavailable', 'reason': 'safety_gate_monitor_incomplete'}
    task = client.get('/v1/monitor-tasks/safety_gate/' + rule['job']['id']).json()['task']
    assert task['state'] == 'failed'


def test_old_observations_are_not_relabelled_as_new_notifications(rolling):
    client, adapter, _database, _ = rolling
    query = {'operation': 'report', 'report_id': '900002', 'reference': 'Report-2026-20'}
    assert client.post('/v1/safety-gate/query', json={'query': query}).json()['data_state'] == 'live'
    create_rule(client)
    assert cycle(rolling)['results'][0]['state'] == 'safety_gate_complete'
    assert notifications(client)['total'] == 0


def test_lease_loss_after_projection_rolls_back_adoption(context):
    from tire_api.monitoring import LeaseLost
    from tire_api.safety_gate import SafetyGateService, SafetyGateRequest, SafetyGateSnapshot
    from tire_api.safety_gate_alerts import AlertChange
    from tire_api.safety_gate_monitor_models import SafetyGateMonitorRule
    client, adapter, database = context
    rule = create_rule(client)
    with database.sessions() as db:
        session_id = db.get(SafetyGateMonitorRule, rule['id']).session_id
    guards = []

    def guard(db):
        guards.append(True)
        if len(guards) == 3:
            assert db.scalar(select(func.count()).select_from(AlertChange)) == 1
            raise LeaseLost('safety_gate_monitor_lease_lost')

    async def execute():
        with database.sessions() as db:
            await SafetyGateService(db, adapter, ingestion_guard=guard).execute(SafetyGateRequest(query={
                'operation': 'report', 'report_id': '900001', 'reference': 'Report-2026-19'}, fallback_policy='never'), session_id)

    with pytest.raises(LeaseLost):
        asyncio.run(execute())
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(SafetyGateSnapshot)) == 0
        assert db.scalar(select(func.count()).select_from(AlertChange)) == 0
