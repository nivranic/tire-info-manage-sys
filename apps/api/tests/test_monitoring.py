"""Synthetic behavior tests for rule revisions, fenced scheduling and local alerts."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from tire_api.db import AlertEvent, AlertRule, AlertRuleRevision, ChangeEvent, MonitorJob, MonitorRun, NotificationDelivery, Snapshot, UserSession, utcnow
from tire_api.main import create_app
from tire_api.monitoring import LEASE_SECONDS, LeaseLost, claim_job, finish_job, guard_claim, record_alerts
from tire_api.service import QueryService
from tire_api.domain import LiveQueryRequest
from test_core import FixtureRegistry, QUERY, VARIANT, count, live, setup, success


def create(client, **updates):
    return client.post('/v1/alert-rules', json={'name': '合成监控规则', 'source_id': 'fixture',
        'query': QUERY['query'], 'enabled': True, **updates})


def edit(client, rule, **updates):
    settings = {key: rule[key] for key in ('name', 'interval_seconds', 'enabled', 'kinds', 'fields', 'conditions')}
    return client.put('/v1/alert-rules/' + rule['id'], json={**settings, 'expected_revision': rule['revision'], **updates})


def changed(registry, value):
    registry.result = success(f'fixture-{value}', [{**VARIANT, 'facts': {'utqg_treadwear': value}}])


def test_alerts_are_future_only_deduplicated_and_cite_both_versions(setup):
    client, registry, database = setup
    first = live(client).json()
    rule = create(client).json()
    assert client.get('/v1/notifications').json()['total'] == 0
    changed(registry, 420)
    updated = live(client).json()
    live(client)
    notice = client.get('/v1/notifications').json()['items'][0]
    assert notice['rule_revision'] == 1 and notice['rule_id'] == rule['id']
    assert notice['snapshot_id'] == updated['provenance'][0]['snapshot_id']
    assert notice['previous_snapshot_id'] == first['provenance'][0]['snapshot_id']
    assert notice['changes']['utqg_treadwear']['before'] == 300
    assert notice['changes']['utqg_treadwear']['after'] == 420
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        record_alerts(db, [db.get(ChangeEvent, notice['change_id'])])
        db.commit()
    assert count(database, AlertEvent) == count(database, NotificationDelivery) == 1
    response = client.put('/v1/notifications/' + notice['id'] + '/read', json={'read': True})
    assert response.status_code == 200
    assert client.get('/v1/notifications?unread=true').json()['total'] == 0
    assert client.put('/v1/notifications/' + notice['id'] + '/read', json={'read': False}).json()['read_at'] is None
    assert client.get('/v1/notifications?unread=true').json()['total'] == 1


def test_filters_and_source_and_exact_sku_are_independent(setup):
    client, registry, database = setup
    original = live(client).json()['variants'][0]
    create(client, variant_id=original['id'], fields=['utqg_treadwear'])
    create(client, fields=['unobserved_metric'])
    create(client, source_id='fixture-two')
    changed(registry, 420)
    live(client)
    assert count(database, AlertEvent) == 1
    registry.result = success('second sku', [{**VARIANT, 'manufacturer_product_code': 'FIX-002'}])
    # Use no-size query, with its own quality baseline, to isolate the identity check.
    live(client, {'query': {'model': 'Fixture Tire'}, 'fallback_policy': 'never'})
    assert count(database, AlertEvent) == 1


def test_first_observation_is_explicit_opt_in_not_a_release_claim(setup):
    client, _, _ = setup
    create(client, kinds=['variant_observed'])
    create(client)
    live(client)
    data = client.get('/v1/notifications').json()
    assert data['total'] == 1 and data['items'][0]['kind'] == 'variant_observed'
    assert data['items'][0]['previous_snapshot_id'] is None


def test_pause_resume_archive_history_and_stale_edits(setup):
    client, registry, database = setup
    live(client)
    rule = create(client).json()
    paused = edit(client, rule, enabled=False).json()
    assert edit(client, rule, name='stale').status_code == 409
    changed(registry, 400)
    live(client)
    resumed = edit(client, paused, enabled=True).json()
    assert client.get('/v1/notifications').json()['total'] == 0
    changed(registry, 420)
    live(client)
    assert client.get('/v1/notifications').json()['total'] == 1
    path = '/v1/alert-rules/' + rule['id']
    archived = client.post(path + '/state', json={'expected_revision': resumed['revision'], 'action': 'archive'}).json()
    assert not archived['enabled']
    assert client.get('/v1/alert-rules').json()['total'] == 0
    assert client.get('/v1/alert-rules?archived=true').json()['total'] == 1
    assert edit(client, archived).status_code == 409
    restored = client.post(path + '/state', json={'expected_revision': archived['revision'], 'action': 'restore'}).json()
    assert not restored['enabled']
    assert claim_job(database) is None
    history = client.get(path + '?mode=history').json()['history']
    assert len(history) == 5 and history[-1]['enabled'] is True
    with database.sessions() as db:
        row = db.scalar(select(AlertRuleRevision))
        row.name = 'replacement'
        with pytest.raises(ValueError, match='只能追加'):
            db.commit()


@pytest.mark.parametrize('update', [
    {'source_id': 'https://evil.invalid'}, {'query': {'size': '265/40R20'}},
    {'variant_id': 'missing'}, {'interval_seconds': 60}, {'interval_seconds': True},
    {'enabled': 'yes'}, {'kinds': []}, {'kinds': ['recall']}, {'fields': ['../../secret']},
    {'name': 'a\x00b'}, {'webhook_url': 'https://evil.invalid'},
])
def test_rule_input_is_bounded_and_no_arbitrary_urls(setup, update):
    client, _, _ = setup
    assert create(client, **update).status_code == 422


@pytest.mark.parametrize('enabled', [False, True])
def test_required_size_rule_rejects_model_only_before_creating_jobs_or_rules(setup, enabled):
    client, registry, database = setup
    original = registry.sources
    registry.sources = lambda: [{**source, 'requires_size': True} for source in original()]
    response = create(client, query={'model': 'Fixture Tire'}, enabled=enabled)
    assert response.status_code == 422 and '尺寸' in response.json()['detail']
    assert count(database, MonitorJob) == count(database, AlertRule) == count(database, AlertRuleRevision) == 0
    assert registry.calls == []
    corrected = create(client, query={'model': 'Fixture Tire', 'size': '265/40ZR20'}, enabled=enabled)
    assert corrected.status_code == 201 and corrected.json()['query']['size'] == '265/40ZR20'
    assert count(database, MonitorJob) == count(database, AlertRule) == count(database, AlertRuleRevision) == 1


def test_required_size_exact_sku_does_not_silently_fill_the_job_query(setup):
    client, registry, database = setup
    sku = live(client).json()['variants'][0]['id']
    original = registry.sources
    registry.sources = lambda: [{**source, 'requires_size': True} for source in original()]
    assert create(client, query={'model': 'Fixture Tire'}, variant_id=sku).status_code == 422
    assert count(database, MonitorJob) == count(database, AlertRule) == 0
    assert create(client, variant_id=sku).status_code == 201


@pytest.mark.parametrize('requires_size', [None, False])
def test_optional_size_sources_still_accept_model_only_rules(setup, requires_size):
    client, registry, _ = setup
    if requires_size is not None:
        original = registry.sources
        registry.sources = lambda: [{**source, 'requires_size': requires_size} for source in original()]
    response = create(client, query={'model': 'Fixture Tire'})
    assert response.status_code == 201 and response.json()['query'] == {'model': 'Fixture Tire'}


def test_legacy_missing_size_target_cannot_be_enabled_but_can_be_paused_and_archived(setup):
    client, registry, database = setup
    # This represents a rule created before the source required a dimension.
    rule = create(client, query={'model': 'Fixture Tire'}).json()
    original = registry.sources
    registry.sources = lambda: [{**source, 'requires_size': True} for source in original()]
    paused = edit(client, rule, enabled=False).json()
    assert not paused['enabled'] and paused['revision'] == 2
    response = edit(client, paused, enabled=True)
    assert response.status_code == 422 and '尺寸' in response.json()['detail']
    assert count(database, AlertRuleRevision) == 2 and claim_job(database) is None
    archived = client.post('/v1/alert-rules/' + rule['id'] + '/state',
                           json={'expected_revision': paused['revision'], 'action': 'archive'})
    assert archived.status_code == 200 and archived.json()['archived']
    restored = client.post('/v1/alert-rules/' + rule['id'] + '/state',
                           json={'expected_revision': archived.json()['revision'], 'action': 'restore'})
    assert restored.status_code == 200 and not restored.json()['enabled']
    assert edit(client, restored.json(), enabled=True).status_code == 422


def test_size_capability_check_does_not_add_unrelated_disabled_source_edit_restrictions(setup):
    client, registry, _ = setup
    rule = create(client, query={'model': 'Fixture Tire'}).json()
    original = registry.sources
    registry.sources = lambda: [{**source, 'status': 'disabled'} for source in original()]
    paused = edit(client, rule, enabled=False)
    assert paused.status_code == 200
    assert edit(client, paused.json(), enabled=True).status_code == 200


def test_failed_and_quarantined_results_do_not_publish_alerts(setup):
    client, registry, database = setup
    live(client)
    create(client, kinds=['variant_observed', 'facts_changed'])
    registry.result = {'status': 'unavailable', 'reason': 'synthetic_offline'}
    assert live(client).json()['data_state'] == 'consent_required'
    registry.result = success('missing records', [])
    assert live(client).json()['reason'] == 'source_quality_quarantined'
    assert count(database, AlertEvent) == count(database, NotificationDelivery) == 0


def test_delivery_failure_rolls_back_facts_and_alerts_together(setup):
    client, registry, database = setup
    live(client)
    create(client)
    changed(registry, 420)

    def fail(_connection, _cursor, statement, *_args):
        if statement.startswith('INSERT INTO notification_deliveries'):
            raise RuntimeError('injected outbox failure')

    event.listen(database.engine, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='outbox'):
            live(client)
    finally:
        event.remove(database.engine, 'before_cursor_execute', fail)
    assert count(database, Snapshot) == 1
    assert count(database, AlertEvent) == 0
    live(client)
    assert count(database, AlertEvent) == count(database, NotificationDelivery) == 1


def test_job_dedup_interval_and_expired_owner_fencing(setup):
    client, _, database = setup
    create(client, interval_seconds=21600)
    create(client, interval_seconds=14400)
    assert count(database, MonitorJob) == 1
    now = utcnow() + timedelta(seconds=1)
    first = claim_job(database, now)
    assert first and claim_job(database, now) is None
    later = now + timedelta(seconds=LEASE_SECONDS + 1)
    second = claim_job(database, later)
    assert second and first['token'] != second['token']
    assert not finish_job(database, first, 'live', now=later)
    with database.sessions() as db:
        with pytest.raises(LeaseLost): guard_claim(db, first)
    assert finish_job(database, second, 'live', now=later)
    assert claim_job(database, later + timedelta(seconds=14399)) is None
    assert claim_job(database, later + timedelta(seconds=14400))
    assert count(database, MonitorRun) == 1


def test_jobs_serialize_by_source_across_distinct_queries(setup):
    client, _, database = setup
    create(client)
    create(client, query={'model': 'Fixture Tire'})
    now = utcnow() + timedelta(seconds=1)
    first = claim_job(database, now)
    assert first and claim_job(database, now) is None
    finish_job(database, first, 'live', now=now)
    assert claim_job(database, now + timedelta(seconds=2)) is None
    assert claim_job(database, now + timedelta(seconds=3))


def test_expired_worker_cannot_ingest_new_response(setup):
    client, registry, database = setup
    live(client)
    create(client)
    old = claim_job(database)
    with database.sessions() as db:
        db.get(MonitorJob, old['id']).lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert claim_job(database)
    changed(registry, 420)
    with database.sessions() as db:
        session = db.scalar(select(UserSession))
        with pytest.raises(LeaseLost):
            asyncio.run(QueryService(db, registry, ingestion_guard=lambda current: guard_claim(current, old)).execute(
                'fixture', LiveQueryRequest(**{**QUERY, 'fallback_policy': 'never'}), session.id))
    assert count(database, Snapshot) == 1 and count(database, AlertEvent) == 0


def test_concurrent_claim_single_winner_and_restart_persistence(tmp_path):
    url = 'sqlite:///' + (tmp_path / 'schedule.db').as_posix()
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        rule = create(client).json()
        barrier = Barrier(2)
        def claim(_):
            barrier.wait()
            return claim_job(app.state.database)
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(claim, range(2)))
        assert sum(item is not None for item in outcomes) == 1
    restarted = create_app(url, FixtureRegistry())
    with TestClient(restarted) as fresh:
        assert fresh.get('/v1/alert-rules').json()['items'][0]['id'] == rule['id']
        assert claim_job(restarted.state.database) is None
        assert claim_job(restarted.state.database, utcnow() + timedelta(seconds=LEASE_SECONDS + 1))
