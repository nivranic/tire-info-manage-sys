"""Source access fences use private synthetic evidence; no network or Parser."""
from copy import deepcopy
import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from tire_api.adapters import nhtsa, xiaomi
from tire_api.ai_models import AIEvidencePack
from tire_api.db import (AlertEvent, ChangeEvent, FactVersion, FallbackConsent, NotificationDelivery,
                         QueryRun, RawCapture, Snapshot, Verification)
from tire_api.main import create_app
from tire_api.recall_discovery import RecallSearchSnapshot, RecallSearchVerification
from tire_api.recall_models import RecallEvent, RecallRevision, RecallSnapshot, RecallVerification
from tire_api.source_settings import (SourceSettingDecision, SourceSettingPreview,
    append_source_setting, preview_source_setting)
from tire_api.vehicles import VehicleSnapshot, VehicleVerification, WheelFitment
from test_core import FixtureRegistry, QUERY, count, grant, live, setup
from test_recall_discovery import SearchFixture
from test_recalls import CAMPAIGN, RecallFixture
from test_vehicles import FixtureVehicleAdapter


class RecordingRegistry(FixtureRegistry):
    def sources(self):
        return super().sources() + [nhtsa.source_metadata()]

    async def fetch(self, source_id, query, cached=None, *, on_observation=None):
        result = await super().fetch(source_id, query, cached=cached)
        if result['status'] == 'ok' and on_observation:
            on_observation(result)
        return result


class RecordingVehicle(FixtureVehicleAdapter):
    async def fetch(self, vehicle_id, *, on_observation=None):
        result = await super().fetch(vehicle_id)
        if result['status'] == 'ok' and on_observation:
            on_observation(result)
        return result


ACCEPTED = (Snapshot, FactVersion, Verification, ChangeEvent, AlertEvent, NotificationDelivery,
            VehicleSnapshot, WheelFitment, VehicleVerification, RecallSnapshot, RecallRevision,
            RecallEvent, RecallVerification, RecallSearchSnapshot, RecallSearchVerification)


@pytest.fixture
def access_app(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '0')
    monkeypatch.setenv('TI_OBSERVABILITY_ENABLED', '0')
    monkeypatch.setenv('TI_OBSERVABILITY_LOGS', '0')
    registry = RecordingRegistry()
    app = create_app('sqlite:///' + (tmp_path / 'source-access.db').as_posix(), registry)
    vehicle, recall, search = RecordingVehicle(), RecallFixture(), SearchFixture()
    app.state.vehicle_adapter = vehicle
    with TestClient(app) as client:
        yield client, app, {'tire': registry, 'vehicle': vehicle, 'recall': recall, 'search': search}


def source_id(lane):
    return 'fixture' if lane == 'tire' else xiaomi.SOURCE_ID if lane == 'vehicle' else nhtsa.SOURCE_ID


def request_lane(env, lane, **extra):
    client, app, adapters = env
    if lane == 'tire':
        return live(client, {**deepcopy(QUERY), **extra})
    if lane == 'vehicle':
        return client.post('/v1/vehicles/' + xiaomi.CURRENT_ID + '/live-fitments', json=extra)
    app.state.recall_adapter = adapters[lane]
    path = '/v1/recalls/live-query' if lane == 'recall' else '/v1/recalls/search'
    query = {'campaign_number': CAMPAIGN} if lane == 'recall' else {'search': 'SYNTHETIC DEMO'}
    return client.post(path, json={'query': query, **extra})


def change_source(env, lane, action, notes=None):
    _, app, _ = env
    values = {'action': action, **({'notes': notes} if notes is not None else {})}
    with app.state.database.sessions() as db:
        preview = preview_source_setting(db, source_id(lane), SourceSettingPreview(**values), registry=app.state.registry)
        payload = SourceSettingDecision(**values, expected_revision=preview['revision'],
            expected_fingerprint=preview['fingerprint'], operator='Synthetic tester', reason='Synthetic access race test')
        return append_source_setting(db, source_id(lane), payload, 'synthetic-access-test', str(uuid4()),
                                     registry=app.state.registry)


def mutate_source(env, lane, mutation):
    if mutation == 'notes':
        change_source(env, lane, 'edit_notes', 'Synthetic notes do not revoke access')
    else:
        change_source(env, lane, 'pause')
        if mutation == 'aba':
            change_source(env, lane, 'enable')


def during_fetch(env, lane, monkeypatch, mutation):
    adapter = env[2][lane]
    original = adapter.fetch

    async def fetch(*args, **kwargs):
        result = await original(*args, **kwargs)
        mutate_source(env, lane, mutation)
        return result

    monkeypatch.setattr(adapter, 'fetch', fetch)


def set_offline(env, lane):
    adapter = env[2][lane]
    if lane in {'tire', 'vehicle'}:
        adapter.result = {'status': 'unavailable', 'reason': 'synthetic_outage'}
    else:
        adapter.offline = True


def accepted_counts(database):
    return {model.__name__: count(database, model) for model in ACCEPTED}


def assert_blocked(response, reason):
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['data_state'] == 'source_unavailable' and value['reason'] == reason
    assert value['provenance'] == [] and value['consent_id'] is None
    assert all(not value.get(key) for key in ('variants', 'fitments', 'records', 'products', 'vehicle'))
    return value


@pytest.mark.parametrize('lane', ['tire', 'vehicle', 'recall', 'search'])
@pytest.mark.parametrize('action,reason', [('pause', 'source_paused'), ('archive', 'source_archived')])
def test_management_blocks_before_fetch_and_never_offers_fallback(access_app, lane, action, reason):
    change_source(access_app, lane, action)
    value = assert_blocked(request_lane(access_app, lane), reason)
    assert access_app[2][lane].calls == []
    database = access_app[1].state.database
    assert not any(accepted_counts(database).values()) and count(database, RawCapture) == 0
    response = grant(access_app[0], value['query_id'])
    assert response.status_code == 409 and count(database, FallbackConsent) == 0


@pytest.mark.parametrize('lane', ['tire', 'vehicle', 'recall', 'search'])
@pytest.mark.parametrize('mutation', ['pause', 'aba', 'notes'])
def test_inflight_adoption_fence_retains_received_raw(access_app, monkeypatch, lane, mutation):
    during_fetch(access_app, lane, monkeypatch, mutation)
    response = request_lane(access_app, lane)
    database = access_app[1].state.database
    assert count(database, RawCapture) == 1
    if mutation == 'notes':
        assert response.status_code == 200 and response.json()['data_state'] == 'live', response.text
        assert any(accepted_counts(database).values())
    else:
        assert_blocked(response, 'source_access_changed')
        assert not any(accepted_counts(database).values())


@pytest.mark.parametrize('lane', ['tire', 'vehicle', 'recall', 'search'])
def test_outage_during_pause_does_not_issue_fallback(access_app, monkeypatch, lane):
    set_offline(access_app, lane)
    during_fetch(access_app, lane, monkeypatch, 'pause')
    value = assert_blocked(request_lane(access_app, lane), 'source_access_changed')
    assert grant(access_app[0], value['query_id']).status_code == 409
    assert count(access_app[1].state.database, FallbackConsent) == 0


@pytest.mark.parametrize('lane', ['tire', 'recall', 'search'])
def test_inflight_304_cannot_append_verification_after_pause(access_app, monkeypatch, lane):
    first = request_lane(access_app, lane)
    assert first.status_code == 200 and first.json()['data_state'] == 'live', first.text
    database = access_app[1].state.database
    before = accepted_counts(database)
    adapter = access_app[2][lane]
    if lane == 'tire':
        adapter.result = {'status': 'not_modified', 'url': adapter.result['url'],
                          'parser_version': adapter.result['parser_version']}
    else:
        adapter.not_modified = True
    during_fetch(access_app, lane, monkeypatch, 'pause')
    assert_blocked(request_lane(access_app, lane), 'source_access_changed')
    assert accepted_counts(database) == before and count(database, RawCapture) == 1


@pytest.mark.parametrize('lane', ['tire', 'recall', 'search'])
def test_notes_only_change_preserves_a_valid_304(access_app, monkeypatch, lane):
    assert request_lane(access_app, lane).json()['data_state'] == 'live'
    adapter = access_app[2][lane]
    if lane == 'tire':
        adapter.result = {'status': 'not_modified', 'url': adapter.result['url'],
                          'parser_version': adapter.result['parser_version']}
    else:
        adapter.not_modified = True
    during_fetch(access_app, lane, monkeypatch, 'notes')
    response = request_lane(access_app, lane)
    assert response.status_code == 200 and response.json()['data_state'] == 'live_verified_304', response.text
    assert count(access_app[1].state.database, RawCapture) == 1


@pytest.mark.parametrize('lane', ['tire', 'vehicle', 'recall', 'search'])
@pytest.mark.parametrize('mutation', ['pause', 'aba', 'notes'])
def test_issued_consent_is_generation_bound_but_notes_do_not_revoke(access_app, lane, mutation):
    assert request_lane(access_app, lane).json()['data_state'] == 'live'
    set_offline(access_app, lane)
    pending = request_lane(access_app, lane).json()
    issued = grant(access_app[0], pending['query_id'])
    assert issued.status_code == 201, issued.text
    consent_id = issued.json()['id']
    mutate_source(access_app, lane, mutation)
    response = request_lane(access_app, lane, consent_id=consent_id)
    database = access_app[1].state.database
    if mutation == 'notes':
        assert response.status_code == 200 and response.json()['data_state'] == 'local_snapshot', response.text
    else:
        assert_blocked(response, 'source_access_changed')
        with database.sessions() as db:
            assert db.get(FallbackConsent, consent_id).used_at is None


def test_vehicle_catalog_preserves_unverified_generation(access_app):
    change_source(access_app, 'vehicle', 'pause')
    rows = access_app[0].get('/v1/vehicles').json()['vehicles']
    current = next(row for row in rows if row['id'] == xiaomi.CURRENT_ID)
    assert current['status'] == 'paused'
    assert current['source_setting']['source_id'] == 'xiaomi-cn-vehicles'
    assert any(row['status'] == 'requires_source_verification' for row in rows)


@pytest.mark.parametrize('lane', ['tire', 'vehicle', 'recall', 'search'])
def test_pending_consent_cannot_be_issued_after_pause_resume(access_app, lane):
    set_offline(access_app, lane)
    pending = request_lane(access_app, lane).json()
    mutate_source(access_app, lane, 'aba')
    response = grant(access_app[0], pending['query_id'])
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'source_access_changed'
    assert count(access_app[1].state.database, FallbackConsent) == 0


@pytest.mark.parametrize('lane', ['tire', 'recall'])
def test_claimed_worker_cannot_cross_pause_resume_and_can_finish(access_app, lane):
    from tire_api import monitoring, recall_monitoring
    from tire_api.domain import LiveQueryRequest
    from tire_api.recall_models import RecallLiveRequest
    from tire_api.recalls import RecallService
    from tire_api.service import QueryService
    client, app, adapters = access_app
    database = app.state.database
    if lane == 'tire':
        response = client.post('/v1/alert-rules', json={'name': 'Synthetic tire rule', 'enabled': True,
            'source_id': 'fixture', 'query': QUERY['query']})
        queue, rule_path = monitoring, '/v1/alert-rules/'
    else:
        response = client.post('/v1/recall-monitor-rules', json={'name': 'Synthetic recall rule', 'enabled': True,
            'query': {'campaign_number': CAMPAIGN}})
        queue, rule_path = recall_monitoring, '/v1/recall-monitor-rules/'
    assert response.status_code == 201, response.text
    rule = response.json()
    claim = queue.claim_job(database)
    assert claim['source_access_generation'] == 0
    change_source(access_app, lane, 'pause')
    assert queue.claim_job(database) is None
    change_source(access_app, lane, 'enable')
    with database.sessions() as db:
        guard = lambda session: queue.guard_claim(session, claim)
        if lane == 'tire':
            value = asyncio.run(QueryService(db, adapters[lane], ingestion_guard=guard).execute(
                'fixture', LiveQueryRequest(**QUERY), claim.get('session_id') or _session_id(database)))
        else:
            value = asyncio.run(RecallService(db, adapters[lane], ingestion_guard=guard).execute(
                RecallLiveRequest(query={'campaign_number': CAMPAIGN}), claim['session_id']))
    assert value['data_state'] == 'source_unavailable' and value['reason'] == 'source_access_changed'
    assert adapters[lane].calls == [] and not any(accepted_counts(database).values())
    assert queue.finish_job(database, claim, value['data_state'], value['reason'])
    detail = client.get(rule_path + rule['id'] + '?mode=history')
    assert detail.status_code == 200, detail.text
    assert detail.json()['enabled'] is True and detail.json()['revision'] == rule['revision']


def _session_id(database):
    from tire_api.db import UserSession
    with database.sessions() as db:
        return db.scalar(select(UserSession.id))


def test_paused_job_does_not_starve_another_source(access_app):
    from tire_api.monitoring import claim_job
    client, app, _ = access_app
    for source in ('fixture', 'fixture-two'):
        response = client.post('/v1/alert-rules', json={'name': 'Synthetic independent job',
            'enabled': True, 'source_id': source, 'query': QUERY['query']})
        assert response.status_code == 201, response.text
    change_source(access_app, 'tire', 'pause')
    claim = claim_job(app.state.database)
    assert claim['source_id'] == 'fixture-two' and claim['source_access_generation'] == 0


@pytest.mark.parametrize('mutation', ['pause', 'aba', 'notes'])
def test_current_ai_pack_rechecks_source_at_freeze_but_history_is_readable(access_app, monkeypatch, mutation):
    from tire_api.ai_evidence import PackBuilder
    original = PackBuilder.tire

    def tire(builder, *args, **kwargs):
        original(builder, *args, **kwargs)
        mutate_source(access_app, 'tire', mutation)

    monkeypatch.setattr(PackBuilder, 'tire', tire)
    client, app, _ = access_app
    response = client.post('/v1/ai/evidence-packs', json={'mode': 'current', 'source_id': 'fixture', 'query': QUERY['query']})
    assert response.status_code == 200, response.text
    if mutation == 'notes':
        assert response.json()['pack'] is not None and count(app.state.database, AIEvidencePack) == 1
    else:
        assert response.json()['pack'] is None and response.json()['reason'] == 'source_access_changed'
        assert count(app.state.database, AIEvidencePack) == 0
    monkeypatch.setattr(PackBuilder, 'tire', original)
    with app.state.database.sessions() as db:
        snapshot = db.scalar(select(Snapshot))
        reference = {'kind': 'tire', 'snapshot_id': snapshot.id, 'variant_id': snapshot.parsed_variants[0]['id']}
    historical = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [reference]})
    assert historical.status_code == 200 and historical.json()['pack']['data_state'] == 'local_snapshot', historical.text


def clear_pin(database, query_id):
    """Represent a pre-migration pending query without assigning today's policy."""
    with database.sessions() as db:
        row = db.get(QueryRun, query_id)
        row.source_access_generation = None
        db.commit()


def test_legacy_pending_query_cannot_issue_new_fallback_consent(setup):
    client, registry, database = setup
    registry.result = {'status': 'unavailable', 'reason': 'synthetic_outage'}
    pending = live(client).json()
    clear_pin(database, pending['query_id'])
    response = grant(client, pending['query_id'])
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'source_access_pin_missing'
    assert count(database, FallbackConsent) == 0


def test_legacy_issued_consent_cannot_read_history_via_live_query(setup):
    client, registry, database = setup
    previous = live(client).json()
    snapshot_id = previous['provenance'][0]['snapshot_id']
    registry.result = {'status': 'unavailable', 'reason': 'synthetic_outage'}
    pending = live(client).json()
    issued = grant(client, pending['query_id'])
    assert issued.status_code == 201, issued.text
    consent_id = issued.json()['id']
    clear_pin(database, pending['query_id'])
    response = live(client, {**deepcopy(QUERY), 'consent_id': consent_id})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['data_state'] == 'source_unavailable'
    assert value['reason'] == 'source_access_pin_missing'
    assert value['variants'] == value['provenance'] == [] and value['consent_id'] is None
    with database.sessions() as db:
        assert db.get(FallbackConsent, consent_id).used_at is None
        assert db.scalar(select(Snapshot.id)) == snapshot_id
    history = client.get('/v1/evidence/' + snapshot_id)
    assert history.status_code == 200 and history.json()['data_state'] == 'local_snapshot'
