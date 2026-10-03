"""Private synthetic API/journal checks; no source, Parser, model or normal DB."""
from datetime import timedelta
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from tire_api.db import uid, utcnow
from tire_api.main import SESSION_COOKIE, create_app
from tire_api import monitor_tasks as tasks
from tire_api.monitor_task_models import MonitorTaskAttempt, MonitorTaskEvent
from tire_api.recall_discovery_monitor_models import (RecallDiscoveryJob, RecallDiscoveryRule,
    RecallDiscoveryRuleRevision, RecallDiscoveryRun, RecallDiscoveryPage, RecallDiscoveryCandidate, RecallDiscoveryNotification)
from tire_api.recall_discovery_monitoring import claim_job
from tire_api.service import QueryService


@pytest.fixture
def setup(monkeypatch):
    for key in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(key, '0')
    app = create_app('sqlite://')
    with TestClient(app) as client:
        client.get('/health')
        yield client, app.state.database, app


def create(client, **changes):
    payload = {'name': '合成名称发现', 'query': {'search': '  SYNTHETIC   DEMO  '}, 'enabled': True,
               'interval_seconds': 3600, **changes}
    response = client.post('/v1/recall-discovery-rules', json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def edit_body(rule, **changes):
    return {'expected_revision': rule['revision'], 'name': rule['name'], 'enabled': rule['enabled'],
            'archived': rule['archived'], 'interval_seconds': rule['interval_seconds'], **changes}


def test_private_api_smoke_normalization_dedup_and_task_kind(setup):
    client, database, app = setup
    first = create(client)
    second = create(client, name='独立订阅', query={'search': 'SYNTHETIC DEMO'})
    assert first['query'] == {'search': 'SYNTHETIC DEMO'}
    assert first['job']['id'] == second['job']['id'] and first['id'] != second['id']
    assert first['write_result']['revision'] == 1 and not first['write_result']['replayed']
    task = client.get('/v1/monitor-tasks', params={'kind': 'recall_discovery'}).json()
    assert task['total'] == 1 and task['items'][0]['scope'] == 'session'
    assert task['items'][0]['state'] == 'never_run' and task['items'][0]['rule_count'] == 2
    assert task['items'][0]['query'] == first['query']
    path = '/v1/recall-discovery-rules/' + first['id']
    detail = client.get(path, params={'mode': 'history'}).json()
    assert 'write_result' not in detail and len(detail['history']) == 1
    with TestClient(app) as other:
        other.get('/health')
        assert other.get('/v1/recall-discovery-rules').json()['total'] == 0
        assert other.get('/v1/monitor-tasks?kind=recall_discovery').json()['total'] == 0
        assert other.get(path + '?mode=history').status_code == 404
        task_path = '/v1/monitor-tasks/recall_discovery/' + first['job']['id']
        for suffix in ('', '/events', '/events/stream'):
            assert other.get(task_path + suffix).status_code == 404
        for route in ('/v1/recall-discovery-runs?mode=history&job_id=' + first['job']['id'],
                      '/v1/recall-discovery-jobs/' + first['job']['id'] + '/scans?mode=history'):
            assert other.get(route).status_code == 404
        separate = create(other)
        assert separate['job']['id'] != first['job']['id']


def test_idempotent_writes_return_original_receipt_with_current_projection(setup):
    client, database, _ = setup
    payload = {'name': '合成', 'query': {'search': 'fixture'}}
    headers = {'Idempotency-Key': str(uuid4())}
    response = client.post('/v1/recall-discovery-rules', json=payload, headers=headers)
    assert response.status_code == 201
    rule = response.json()
    path = '/v1/recall-discovery-rules/' + rule['id'] + '/revisions'
    key = {'Idempotency-Key': str(uuid4())}
    revision_body = edit_body(rule, name='第二版')
    second = client.post(path, json=revision_body, headers=key).json()
    third = client.post(path, json=edit_body(second, name='第三版')).json()
    assert third['revision'] == 3
    replay = client.post(path, json=revision_body, headers=key)
    assert replay.status_code == 201
    assert replay.json()['revision'] == 3 and replay.json()['name'] == '第三版'
    assert replay.json()['write_result'] == {**second['write_result'], 'replayed': True}
    creation = client.post('/v1/recall-discovery-rules', json=payload, headers=headers).json()
    assert creation['revision'] == 3
    assert creation['write_result'] == {**rule['write_result'], 'replayed': True}
    assert client.post(path, json={**revision_body, 'name': '冲突'}, headers=key).status_code == 409
    assert client.post(path, json=revision_body).status_code == 409
    assert client.post('/v1/recall-discovery-rules', json={**payload, 'name': '冲突'}, headers=headers).status_code == 409
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(RecallDiscoveryRule)) == 1
        assert db.scalar(select(func.count()).select_from(RecallDiscoveryRuleRevision)) == 3
    public = json.dumps(creation) + replay.text
    assert headers['Idempotency-Key'] not in public and key['Idempotency-Key'] not in public
    assert 'request_hash' not in public and 'idempotency_key' not in public


def test_revision_and_new_subscription_preserve_active_source_reservation(setup):
    client, database, _ = setup
    rule = create(client)
    claim = claim_job(database)
    assert claim and claim['kind'] == 'recall_discovery'
    path = '/v1/recall-discovery-rules/' + rule['id'] + '/revisions'
    response = client.post(path, json=edit_body(rule, archived=True))
    assert response.status_code == 201 and not response.json()['enabled']
    create(client, name='同任务另一个规则')
    with database.sessions() as db:
        job = db.get(RecallDiscoveryJob, rule['job']['id'])
        assert job.lease_token == claim['token'] and job.lease_until is not None
        attempts, events = tasks.journal_models('recall_discovery')
        assert db.scalar(select(func.count()).select_from(events)) == 1
        assert db.scalar(select(func.count()).select_from(attempts)) == 1
        assert db.scalar(select(func.count()).select_from(MonitorTaskAttempt)) == 0
        assert db.scalar(select(func.count()).select_from(MonitorTaskEvent)) == 0


@pytest.mark.parametrize('payload', [
    {'query': {'search': 'fixture', 'offset': 10}}, {'query': {'search': ''}}, {'query': {'search': '\x00'}},
    {'interval_seconds': 3599}, {'interval_seconds': 604801}, {'interval_seconds': True},
    {'enabled': 'true'}, {'name': ''}, {'archived': True},
])
def test_strict_create_validation(setup, payload):
    client, _, _ = setup
    assert client.post('/v1/recall-discovery-rules', json={
        'name': '合成', 'query': {'search': 'fixture'}, **payload}).status_code == 422


def test_uuid_and_list_bounds_and_immutable_query_validation(setup):
    client, _, _ = setup
    assert client.post('/v1/recall-discovery-rules', json={'name': 'x', 'query': {'search': 'x'}},
                       headers={'Idempotency-Key': 'invalid'}).status_code == 422
    rule = create(client)
    path = '/v1/recall-discovery-rules/' + rule['id'] + '/revisions'
    assert client.post(path, json=edit_body(rule, query={'search': 'different'})).status_code == 422
    for endpoint in ('recall-discovery-rules', 'recall-discovery-notifications'):
        assert client.get('/v1/' + endpoint + '?limit=101').status_code == 422
        assert client.get('/v1/' + endpoint + '?offset=-1').status_code == 422
    assert client.get('/v1/recall-discovery-rules/' + rule['id']).status_code == 422


def finish_synthetic(database, claim, state, reason=None, *, interrupted=False):
    """Journal/read projection fixture only; scanner acceptance has separate tests."""
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        assert tasks.mark_running_locked(db, claim)
        complete = state == 'discovery_complete'
        run = RecallDiscoveryRun(id=uid(), job_id=claim['id'], attempt_id=claim['attempt_id'],
            lease_token=claim['token'], state=state, reason=reason, started_at=claim['started_at'],
            finished_at=utcnow(), coverage='complete' if complete else 'incomplete',
            pass_fingerprints=['a' * 64, 'a' * 64] if complete else [])
        db.add(run)
        db.flush()
        if interrupted:
            assert tasks.interrupt_attempt_locked(db, claim, reason, run_id=run.id)
        else:
            assert tasks.finish_attempt_locked(db, claim, state, reason, run_id=run.id)
        job = db.get(RecallDiscoveryJob, claim['id'])
        job.lease_token, job.lease_until = None, None
        db.commit()
        return run.id


@pytest.mark.parametrize('state,reason,outcome', [
    ('discovery_complete', None, 'succeeded'),
    ('discovery_incomplete', 'discovery_content_changed', 'failed'),
    ('discovery_incomplete', 'source_access_changed', 'blocked'),
    ('lease_lost', 'recall_discovery_rule_changed', 'interrupted'),
])
def test_discovery_task_receipts_states_cursors_and_no_private_fields(setup, state, reason, outcome):
    client, database, app = setup
    rule = create(client)
    path = '/v1/monitor-tasks/recall_discovery/' + rule['job']['id']
    initial = client.get(path).json()
    claim = claim_job(database)
    run_id = finish_synthetic(database, claim, state, reason, interrupted=outcome == 'interrupted')
    detail = client.get(path).json()
    assert detail['task']['state'] == outcome and detail['task']['terminal']
    assert detail['task']['last_attempt']['query_id'] is None
    assert detail['task']['last_attempt']['reason'] == reason
    assert detail['legacy_runs'] == [] and detail['legacy_runs_total'] == 0
    first = client.get(path + '/events', params={'cursor': initial['cursor'], 'limit': 2}).json()
    second = client.get(path + '/events', params={'cursor': first['next_cursor'], 'limit': 2}).json()
    assert first['has_more'] and not second['has_more']
    assert [row['phase'] for row in first['items'] + second['items']] == ['claimed', 'running', 'finished']
    assert second['items'][0]['run_id'] == run_id and second['items'][0]['state'] == outcome
    assert second['items'][0]['query_id'] is None
    assert client.get('/v1/monitor-tasks', params={'kind': 'recall_discovery', 'state': outcome}).json()['total'] == 1
    read = client.get('/v1/recall-discovery-runs/' + run_id + '?mode=history').json()
    assert read['coverage']['baseline_advanced'] == (outcome == 'succeeded')
    assert read['coverage']['is_initial_baseline'] == (outcome == 'succeeded')
    assert read['query'] == rule['query']
    runs = client.get('/v1/recall-discovery-runs', params={'mode': 'history', 'job_id': claim['id']}).json()
    assert runs['total'] == 1 and runs['items'][0]['id'] == run_id
    body = json.dumps(detail) + json.dumps(read) + json.dumps(second)
    assert claim['token'] not in body and client.cookies.get(SESSION_COOKIE) not in body
    assert 'lease_token' not in body and 'session_id' not in body
    with database.sessions() as db:
        assert not tasks.interrupt_attempt_locked(db, claim, 'lease_lost', run_id=run_id)
        assert not tasks.finish_attempt_locked(db, claim, state, reason, run_id=run_id)
        db.commit()
    assert client.get(path + '/events').json()['items'][-1]['sequence'] == 3
    with TestClient(app) as other:
        other.get('/health')
        assert other.get('/v1/recall-discovery-runs/' + run_id + '?mode=history').status_code == 404


def test_discovery_running_filter_detects_replaced_lease_and_wrong_cursor(setup):
    client, database, _ = setup
    rule = create(client)
    value = claim_job(database)
    path = '/v1/monitor-tasks/recall_discovery/' + value['id']
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        job = db.get(RecallDiscoveryJob, value['id'])
        job.lease_token, job.lease_until = uid(), utcnow() + timedelta(seconds=600)
        db.commit()
    assert client.get(path).json()['task']['state'] == 'result_unknown'
    assert client.get('/v1/monitor-tasks?kind=recall_discovery&state=running').json()['total'] == 0
    assert client.get('/v1/monitor-tasks?kind=recall_discovery&state=result_unknown').json()['total'] == 1
    for cursor in (tasks._cursor('recall', value['id']), tasks._cursor('recall_discovery', uid()), 'not-a-cursor'):
        response = client.get(path + '/events', params={'cursor': cursor})
        assert response.status_code == 409 and response.json()['detail']['code'] == 'task_cursor_reset_required'


def test_failed_page_projection_is_bounded_and_notification_read_is_private(setup):
    client, database, app = setup
    rule = create(client)
    value = claim_job(database)
    run_id = finish_synthetic(database, value, 'discovery_incomplete', 'discovery_page_failed')
    with database.sessions() as db:
        pages = [RecallDiscoveryPage(job_id=value['id'], attempt_id=value['attempt_id'], pass_number=1,
                                     offset=index * 10, raw_bytes=12) for index in range(3)]
        db.add_all(pages)
        db.flush()
        # A synthetic immutable candidate exercises the transport projection;
        # real baseline/notification eligibility is tested by scanner fixtures.
        candidate = RecallDiscoveryCandidate(job_id=value['id'], campaign_number='26T001000',
            first_seen_run_id=run_id, campaign={'campaign_number': '26T001000'},
            evidence=[{'page_id': pages[0].id, 'snapshot_id': 'synthetic', 'query_id': 'synthetic', 'product_ids': [1]}])
        db.add(candidate)
        db.flush()
        revision = db.scalar(select(RecallDiscoveryRuleRevision).where(RecallDiscoveryRuleRevision.rule_id == rule['id']))
        notification = RecallDiscoveryNotification(session_id=client.cookies.get(SESSION_COOKIE),
            rule_id=rule['id'], rule_revision_id=revision.id, candidate_id=candidate.id)
        db.add(notification)
        db.commit()
        notification_id = notification.id
    detail_path = '/v1/recall-discovery-runs/' + run_id
    detail = client.get(detail_path, params={'mode': 'history', 'page_offset': 1, 'page_limit': 1}).json()
    assert detail['pages_total'] == 3 and len(detail['pages']) == 1 and detail['pages'][0]['offset'] == 10
    assert detail['pages'][0]['verification_id'] is None and detail['pages'][0]['content_fingerprint'] is None
    assert detail['coverage']['pages_completed'] == 0 and not detail['coverage']['baseline_advanced']
    assert detail['candidates_total'] == 1 and detail['candidates'][0]['applicability'] == 'not_assessed'
    original = client.get('/v1/recall-discovery-notifications').json()['items'][0]
    revised = client.post('/v1/recall-discovery-rules/' + rule['id'] + '/revisions', json=edit_body(rule, name='新名字'))
    assert revised.status_code == 201
    assert client.get('/v1/recall-discovery-notifications').json()['items'][0] == original
    mark = '/v1/recall-discovery-notifications/' + notification_id + '/read'
    assert client.post(mark, json={'read': True}).json()['read_at'] is not None
    assert client.get('/v1/recall-discovery-notifications?unread_only=true').json()['total'] == 0
    assert client.post(mark, json={'read': False}).json()['read_at'] is None
    assert client.get('/v1/recall-discovery-notifications?unread_only=true').json()['total'] == 1
    with TestClient(app) as other:
        other.get('/health')
        assert other.get('/v1/recall-discovery-notifications').json()['total'] == 0
        assert other.post('/v1/recall-discovery-notifications/' + notification_id + '/read', json={'read': True}).status_code == 404
