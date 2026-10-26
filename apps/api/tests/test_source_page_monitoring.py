"""Synthetic accepted-text monitoring; no real source, Provider or retained DB."""
from copy import deepcopy
import asyncio
from datetime import timedelta
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, insert, select
from sqlalchemy.exc import DBAPIError

from tire_api.db import (AlertRule, AlertRuleRevision, ChangeEvent, FactVersion, MonitorJob,
                        Snapshot, UserSession, Verification, utcnow)
from tire_api.domain import LiveQueryRequest
from tire_api.service import QueryService
from tire_api.source_page_models import SourcePageChange, SourcePageNotification
from tire_api.source_page_monitoring import append_page_change
from test_core import QUERY, VARIANT, count, live, setup, success


def create(client, **changes):
    return client.post('/v1/alert-rules', json={'name': '合成来源文本监控', 'source_id': 'fixture',
        'query': QUERY['query'], 'enabled': True, 'kinds': ['page_changed'],
        'fields': [], 'conditions': {}, 'variant_id': None, **changes})


def edit(client, rule, **changes):
    settings = {key: rule[key] for key in ('name', 'interval_seconds', 'enabled', 'kinds', 'fields', 'conditions')}
    return client.put('/v1/alert-rules/' + rule['id'], json={**settings,
        'expected_revision': rule['revision'], **changes})


def notices(client, **params):
    response = client.get('/v1/source-page-notifications', params={'mode': 'history', **params})
    assert response.status_code == 200, response.text
    return response.json()


def change(client, registry, body='synthetic-page-body-B', **values):
    registry.result = success(body, **values)
    response = live(client)
    assert response.status_code == 200 and response.json()['data_state'] == 'live', response.text
    return response.json()


def replay(database, event_id):
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        row = db.get(SourcePageChange, event_id)
        assert append_page_change(db, db.get(Verification, row.verification_id),
                                  db.get(Verification, row.previous_verification_id)).id == row.id
        db.commit()


def test_page_body_change_without_fact_or_member_change_has_separate_frozen_evidence(setup):
    client, registry, database = setup
    rule = create(client).json()
    first = live(client).json()
    assert notices(client)['total'] == 0
    second = change(client, registry)
    data = notices(client)
    assert set(data) == {'scope', 'data_state', 'items', 'total', 'offset', 'limit'}
    assert data['scope'] == 'local_workspace' and data['data_state'] == 'local_snapshot'
    assert data['total'] == 1 and data['offset'] == 0 and data['limit'] == 25
    notice = data['items'][0]
    assert set(notice) == {'id', 'rule_id', 'rule_name', 'rule_revision', 'read_at', 'delivered_at', 'event'}
    assert notice['rule_id'] == rule['id'] and notice['rule_revision'] == 1
    evidence = notice['event']
    assert set(evidence) == {'id', 'kind', 'source_id', 'query', 'source_url', 'before', 'after'}
    assert evidence['kind'] == 'page_changed' and evidence['query'] == QUERY['query']
    assert evidence['before']['snapshot_id'] == first['provenance'][0]['snapshot_id']
    assert evidence['after']['snapshot_id'] == second['provenance'][0]['snapshot_id']
    for side in (evidence['before'], evidence['after']):
        assert set(side) == {'snapshot_id', 'verification_id', 'raw_hash', 'observed_at', 'verified_at', 'parser_version'}
        assert all(value is not None for value in side.values())
    assert evidence['before']['raw_hash'] != evidence['after']['raw_hash']
    assert count(database, FactVersion) == count(database, ChangeEvent) == 1
    assert client.get('/v1/notifications').json()['total'] == 0
    detail = client.get('/v1/source-page-notifications/' + notice['id'], params={'mode': 'history'})
    assert detail.status_code == 200 and detail.json() == {
        'scope': 'local_workspace', 'data_state': 'local_snapshot', 'item': notice}
    assert 'synthetic-page-body-B' not in json.dumps(detail.json())
    assert client.get('/v1/evidence/' + evidence['after']['snapshot_id']).json()['body'] == 'synthetic-page-body-B'


def test_page_and_fact_rules_share_one_job_but_publish_independent_types(setup):
    client, registry, database = setup
    create(client)
    create(client, kinds=['facts_changed'], name='合成参数规则')
    assert count(database, MonitorJob) == 1
    live(client)
    rows = [{**deepcopy(VARIANT), 'facts': {'utqg_treadwear': 400}}]
    change(client, registry, variants=rows)
    assert notices(client)['total'] == 1
    assert client.get('/v1/notifications').json()['total'] == 1
    assert count(database, SourcePageChange) == 1


def test_same_text_parser_only_and_valid_304_do_not_invent_page_events(setup):
    client, registry, database = setup
    create(client)
    first = live(client).json()
    change(client, registry, body='fixture-body-v1')
    change(client, registry, body='fixture-body-v1', parser_version='fixture@2')
    registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product', 'etag': '"fixture-etag"'}
    result = live(client).json()
    assert result['data_state'] == 'live_verified_304'
    assert result['snapshot_observed_at'] != first['snapshot_observed_at']
    assert count(database, SourcePageChange) == count(database, SourcePageNotification) == 0


def test_changed_observation_after_304_keeps_raw_observed_time_separate(setup):
    client, registry, _ = setup
    create(client)
    first = live(client).json()
    registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product', 'etag': '"fixture-etag"'}
    verified = live(client).json()
    change(client, registry)
    before = notices(client)['items'][0]['event']['before']
    assert before['snapshot_id'] == first['provenance'][0]['snapshot_id']
    assert before['observed_at'] == first['snapshot_observed_at']
    assert before['verified_at'] == verified['verified_at']


def test_url_drift_resets_only_this_query_comparison_chain(setup):
    client, registry, database = setup
    create(client)
    live(client)
    change(client, registry, body='moved-page-B', url='https://fixture.example/tires/new-page')
    assert count(database, SourcePageChange) == 0
    moved = change(client, registry, body='moved-page-C', url='https://fixture.example/tires/new-page')
    notice = notices(client)['items'][0]
    assert notice['event']['source_url'] == 'https://fixture.example/tires/new-page'
    assert notice['event']['after']['snapshot_id'] == moved['provenance'][0]['snapshot_id']


def test_scope_uses_exact_source_and_canonical_query_not_sku_size_matching(setup):
    client, registry, _ = setup
    create(client)
    live(client)
    registry.result = success('other-source-B')
    assert live(client, source='fixture-two').json()['data_state'] == 'live'
    assert live(client, {'query': {'model': 'Fixture Tire', 'size': '265/40ZR20'}, 'fallback_policy': 'never'}).json()['data_state'] == 'live'
    assert notices(client)['total'] == 0
    registry.result = success('original-query-C')
    result = live(client, {**QUERY, 'filters': [{'field': 'utqg_treadwear', 'op': 'eq', 'value': 999}]}).json()
    assert result['variants'] == []
    data = notices(client)
    assert data['total'] == 1 and data['items'][0]['event']['query']['size'] == '265/40R20'


def test_empty_accepted_source_has_page_events_without_fabricating_skus(setup):
    client, registry, database = setup
    create(client)
    change(client, registry, body='empty-page-A', variants=[])
    change(client, registry, body='empty-page-B', variants=[])
    assert notices(client)['total'] == 1
    assert count(database, FactVersion) == count(database, ChangeEvent) == 0


@pytest.mark.parametrize('failure', ['unavailable', 'quarantined', 'bad_schema'])
def test_rejected_or_failed_observation_does_not_advance_accepted_page_baseline(setup, failure):
    client, registry, database = setup
    create(client)
    first = live(client).json()
    if failure == 'unavailable':
        registry.result = {'status': 'unavailable', 'reason': 'synthetic_offline'}
    elif failure == 'quarantined':
        registry.result = success('quarantined-page', [])
    else:
        registry.result = success('bad-schema-page', [{'not': 'a variant'}])
    result = live(client).json()
    assert result['data_state'] != 'live'
    assert count(database, SourcePageChange) == count(database, SourcePageNotification) == 0
    change(client, registry, body='accepted-after-failure')
    assert notices(client)['items'][0]['event']['before']['snapshot_id'] == first['provenance'][0]['snapshot_id']


@pytest.mark.parametrize('values', [
    {'kinds': ['page_changed', 'facts_changed']}, {'fields': ['utqg_treadwear']},
    {'conditions': {'technology': 'Acoustic'}}, {'variant_id': 'not-a-page-identity'},
])
def test_page_rule_rejects_sku_or_mixed_conditions_before_writing(setup, values):
    client, _, database = setup
    assert create(client, **values).status_code == 422
    assert count(database, AlertRule) == count(database, MonitorJob) == 0


def test_nullable_sku_rule_is_still_sku_mode_and_page_mode_cannot_be_switched(setup):
    client, _, database = setup
    page = create(client).json()
    sku = create(client, kinds=['facts_changed']).json()
    assert page['variant_id'] is None and sku['variant_id'] is None
    assert edit(client, sku, kinds=['page_changed']).status_code == 422
    assert edit(client, page, kinds=['facts_changed']).status_code == 422
    assert edit(client, sku, kinds=['facts_changed', 'variant_observed']).status_code == 200
    assert count(database, AlertRuleRevision) == 3


def test_recurring_hash_pairs_are_distinct_but_event_replays_never_backfill_any_rule(setup):
    client, registry, database = setup
    first_rule = create(client).json()
    live(client)
    for body in ('page-B', 'fixture-body-v1', 'page-B'):
        change(client, registry, body=body)
    assert count(database, SourcePageChange) == notices(client)['total'] == 3
    original = notices(client)['items'][-1]
    later = create(client, enabled=False, name='晚建暂停规则').json()
    replay(database, original['event']['id'])
    later = edit(client, later, enabled=True).json()
    replay(database, original['event']['id'])
    first_rule = edit(client, first_rule, enabled=False).json()
    replay(database, original['event']['id'])
    edit(client, first_rule, name='新名称不改变旧提醒')
    replay(database, original['event']['id'])
    assert notices(client)['total'] == 3
    detail = client.get('/v1/source-page-notifications/' + original['id'], params={'mode': 'history'}).json()['item']
    assert detail['rule_name'] == '合成来源文本监控' and detail['rule_revision'] == 1


def test_pause_resume_and_archive_are_future_only(setup):
    client, registry, _ = setup
    rule = create(client, enabled=False).json()
    live(client)
    change(client, registry, body='paused-B')
    rule = edit(client, rule, enabled=True).json()
    assert notices(client)['total'] == 0
    change(client, registry, body='enabled-C')
    assert notices(client)['total'] == 1
    archived = client.post('/v1/alert-rules/' + rule['id'] + '/state', json={
        'expected_revision': rule['revision'], 'action': 'archive'}).json()
    change(client, registry, body='archived-D')
    restored = client.post('/v1/alert-rules/' + rule['id'] + '/state', json={
        'expected_revision': archived['revision'], 'action': 'restore'}).json()
    assert not restored['enabled'] and notices(client)['total'] == 1


def test_notice_failure_rolls_back_snapshot_verification_facts_and_page_event(setup):
    client, registry, database = setup
    create(client)
    live(client)
    before = {model: count(database, model) for model in (Snapshot, Verification, FactVersion, ChangeEvent)}
    registry.result = success('rollback-B', [{**deepcopy(VARIANT), 'facts': {'utqg_treadwear': 450}}])
    def fail(_connection, _cursor, statement, *_args):
        if statement.startswith('INSERT INTO source_page_notifications'):
            raise RuntimeError('synthetic-page-notice-failure')
    event.listen(database.engine, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='synthetic-page-notice-failure'):
            live(client)
    finally:
        event.remove(database.engine, 'before_cursor_execute', fail)
    assert all(count(database, model) == value for model, value in before.items())
    assert count(database, SourcePageChange) == count(database, SourcePageNotification) == 0
    assert live(client).json()['data_state'] == 'live'
    assert notices(client)['total'] == 1


def test_lists_are_metadata_only_and_shared_reads_marks_are_idempotent(setup):
    client, registry, database = setup
    create(client)
    live(client)
    change(client, registry)
    statements = []
    def observe(_connection, _cursor, statement, *_args):
        statements.append(statement.replace('"', '').lower())
    event.listen(database.engine, 'before_cursor_execute', observe)
    try:
        item = notices(client)['items'][0]
    finally:
        event.remove(database.engine, 'before_cursor_execute', observe)
    assert not any('snapshots.body' in sql or 'snapshots.parsed_variants' in sql for sql in statements)
    assert client.get('/v1/source-page-notifications').status_code == 422
    assert client.get('/v1/source-page-notifications', params={'mode': 'history', 'limit': 51}).status_code == 422
    other = TestClient(client.app)
    assert notices(other)['items'][0] == item
    path = '/v1/source-page-notifications/' + item['id'] + '/read'
    first = other.put(path, json={'read': True}).json()
    assert first['read_at'] and other.put(path, json={'read': True}).json() == first
    assert notices(client, unread=True)['total'] == 0
    assert other.put(path, json={'read': False}).json() == {'id': item['id'], 'read_at': None}
    assert other.put(path, json={'read': 'yes'}).status_code == 422
    missing = client.get('/v1/source-page-notifications/missing', params={'mode': 'history'})
    assert missing.status_code == 404 and missing.json()['detail']['code'] == 'source_page_notification_not_found'
    other.close()


def test_detail_rechecks_text_hash_while_list_does_not_read_text(setup):
    client, registry, database = setup
    create(client)
    live(client)
    change(client, registry)
    item = notices(client)['items'][0]
    with database.engine.begin() as connection:
        connection.execute(Snapshot.__table__.update().where(
            Snapshot.id == item['event']['before']['snapshot_id']).values(body='synthetic externally damaged text'))
    assert notices(client)['total'] == 1
    result = client.get('/v1/source-page-notifications/' + item['id'], params={'mode': 'history'})
    assert result.status_code == 503 and result.json()['detail']['code'] == 'source_page_history_invalid'
    assert 'externally damaged' not in result.text


def test_invalid_retained_query_json_returns_fixed_history_error_for_all_notice_routes(setup):
    client, registry, database = setup
    create(client)
    live(client)
    change(client, registry)
    item = notices(client)['items'][0]
    with database.engine.begin() as connection:
        connection.exec_driver_sql('UPDATE query_runs SET "query" = ? WHERE id = '
            '(SELECT query_id FROM verifications WHERE id = ?)',
            ('{"synthetic-invalid-query-json":', item['event']['before']['verification_id']))
    responses = [
        client.get('/v1/source-page-notifications', params={'mode': 'history'}),
        client.get('/v1/source-page-notifications/' + item['id'], params={'mode': 'history'}),
        client.put('/v1/source-page-notifications/' + item['id'] + '/read', json={'read': True}),
    ]
    for response in responses:
        assert response.status_code == 503
        assert response.json()['detail']['code'] == 'source_page_history_invalid'
        assert 'synthetic-invalid-query-json' not in response.text


@pytest.mark.parametrize('table', ['source_page_changes', 'source_page_notifications'])
@pytest.mark.parametrize('operation', ['update_fixed', 'delete', 'replace_id', 'replace_unique'])
def test_native_page_history_guards_preserve_all_unique_identities(setup, table, operation):
    client, registry, database = setup
    create(client)
    live(client)
    change(client, registry)
    model = SourcePageChange if table == 'source_page_changes' else SourcePageNotification
    with database.engine.connect() as connection:
        values = dict(connection.execute(select(model.__table__)).mappings().one())
    with pytest.raises(DBAPIError):
        with database.engine.begin() as connection:
            connection.exec_driver_sql('PRAGMA recursive_triggers=OFF')
            if operation == 'update_fixed':
                connection.exec_driver_sql(f"UPDATE {table} SET fingerprint = 'modified'")
            elif operation == 'delete':
                connection.exec_driver_sql(f'DELETE FROM {table}')
            else:
                if operation == 'replace_unique':
                    values['id'] = 'different-primary-key'
                connection.execute(insert(model).prefix_with('OR REPLACE').values(**values))
    assert count(database, model) == 1


@pytest.mark.parametrize('model', [SourcePageChange, SourcePageNotification])
@pytest.mark.parametrize('operation', ['update', 'delete'])
def test_orm_page_history_guards_allow_only_notification_read_at(setup, model, operation):
    client, registry, database = setup
    create(client)
    live(client)
    change(client, registry)
    with database.sessions() as db:
        row = db.scalar(select(model))
        if operation == 'delete':
            db.delete(row)
        else:
            row.fingerprint = 'modified'
        with pytest.raises(ValueError, match='source_page_.*immutable'):
            db.flush()
        db.rollback()


def test_page_notice_pagination_retains_all_rule_notifications(setup):
    client, registry, _ = setup
    for index in range(3):
        assert create(client, name=f'Synthetic page rule {index}').status_code == 201
    live(client)
    change(client, registry)
    first, second = notices(client, limit=2), notices(client, offset=2, limit=2)
    assert first['total'] == second['total'] == 3
    assert len(first['items']) == 2 and len(second['items']) == 1
    assert len({row['id'] for row in first['items'] + second['items']}) == 3
    assert len({row['event']['id'] for row in first['items'] + second['items']}) == 1


@pytest.mark.parametrize('corruption', ['wrong_snapshot_scope', 'wrong_job_query', 'changed_frozen_revision'])
def test_metadata_closure_and_frozen_rule_payload_fail_closed(setup, corruption):
    client, registry, database = setup
    rule = create(client).json()
    live(client)
    change(client, registry)
    item = notices(client)['items'][0]
    with database.engine.begin() as connection:
        if corruption == 'wrong_snapshot_scope':
            connection.execute(Snapshot.__table__.update().where(Snapshot.id == item['event']['before']['snapshot_id'])
                .values(query_key='0' * 64))
        elif corruption == 'wrong_job_query':
            connection.execute(MonitorJob.__table__.update().where(MonitorJob.id == rule['job']['id'])
                .values(query={'model': 'Different source query'}))
        else:
            connection.execute(AlertRuleRevision.__table__.update().where(AlertRuleRevision.rule_id == rule['id'])
                .values(name='synthetic externally changed frozen name'))
    result = client.get('/v1/source-page-notifications?mode=history')
    assert result.status_code == 503 and result.json()['detail']['code'] == 'source_page_history_invalid'
    assert 'externally changed' not in result.text


def test_expired_worker_lease_cannot_publish_page_event_or_notification(setup):
    from tire_api.monitoring import LeaseLost, claim_job, guard_claim
    client, registry, database = setup
    create(client)
    live(client)
    old = claim_job(database)
    with database.sessions() as db:
        db.get(MonitorJob, old['id']).lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert claim_job(database)
    registry.result = success('expired-worker-page-B')
    with database.sessions() as db:
        session = db.scalar(select(UserSession))
        with pytest.raises(LeaseLost):
            asyncio.run(QueryService(db, registry, ingestion_guard=lambda current: guard_claim(current, old)).execute(
                'fixture', LiveQueryRequest(**{**QUERY, 'fallback_policy': 'never'}), session.id))
    assert count(database, Snapshot) == 1
    assert count(database, SourcePageChange) == count(database, SourcePageNotification) == 0


def test_source_generation_change_during_fetch_cannot_publish_page_event(setup):
    from tire_api.source_settings import (SourceSettingDecision, SourceSettingPreview,
        append_source_setting, preview_source_setting)
    client, registry, database = setup
    create(client)
    live(client)
    registry.result = success('revoked-source-page-B')
    original = registry.fetch
    async def changed_source(source_id, query, cached=None, *, on_observation=None):
        result = await original(source_id, query, cached, on_observation=on_observation)
        with database.sessions() as db:
            preview = preview_source_setting(db, 'fixture', SourceSettingPreview(action='pause'), registry=registry)
            payload = SourceSettingDecision(action='pause', expected_revision=preview['revision'],
                expected_fingerprint=preview['fingerprint'], operator='Synthetic page test',
                reason='Synthetic pause during fetch')
            append_source_setting(db, 'fixture', payload, 'synthetic-page-test', str(uuid4()), registry=registry)
        return result
    registry.fetch = changed_source
    result = live(client).json()
    assert result['data_state'] == 'source_unavailable'
    assert result['reason'] in {'source_access_changed', 'source_paused'}
    assert count(database, Snapshot) == 1
    assert count(database, SourcePageChange) == count(database, SourcePageNotification) == 0
