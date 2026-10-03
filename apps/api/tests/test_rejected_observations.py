"""Obtained but unusable source bodies remain evidence, never answer data."""
import asyncio
import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from tire_api.adapters import registry as official, xiaomi
from tire_api.adapters.robots import RobotsPolicy
from tire_api.adapters.transport import FetchResult, SourceAccessError
from tire_api.db import ChangeEvent, FactVersion, RejectedObservation, Snapshot, TireVariant, Verification
from tire_api.main import create_app
from tire_api.vehicles import register_vehicle_routes, VehicleSnapshot
from query_evidence_assertions import assert_frozen_query_evidence
from test_core import QUERY, count, grant, live, setup, success
from test_vehicles import FixtureVehicleAdapter, OfflineTireRegistry

BODY = '已取得但不可解析\x00<script>window.__rejectedExecuted = true</script>'


def rejected():
    return {"status": "unavailable", "reason": "parser_schema_changed", "rejected_observation": {
        "body": BODY, "url": "https://fixture.example/tires/product", "content_type": "text/html",
        "parser_version": "fixture@broken", "etag": '"must-not-cache"'}}


def test_first_failed_parse_retains_binary_exact_body_without_any_accepted_data(setup):
    client, registry, database = setup
    registry.result = rejected()
    failed = live(client).json()
    assert failed['data_state'] == 'consent_required'
    assert failed['variants'] == failed['provenance'] == []
    assert all(count(database, model) == 0 for model in (Snapshot, TireVariant, FactVersion, Verification, ChangeEvent))
    assert count(database, RejectedObservation) == 1
    listing = client.get('/v1/quarantines').json()
    row = listing['items'][0]
    assert row['kind'] == 'response_rejected' and row['metrics'] is None and row['previous_snapshot_id'] is None
    assert 'body' not in row and 'candidates' not in row and row['stage'] == 'parser'
    assert listing['source_ids'] == ['fixture']
    assert client.get(f"/v1/quarantines/{row['id']}").status_code == 422
    detail = client.get(row['evidence_path']).json()
    assert detail['body'] == BODY and detail['candidates'] == [] and detail['accepted'] is False
    assert detail['raw_hash'] == hashlib.sha256(BODY.encode()).hexdigest()
    consent = grant(client, failed['query_id']).json()
    fallback = live(client, {**QUERY, 'consent_id': consent['id']}).json()
    assert fallback['variants'] == fallback['provenance'] == []
    assert fallback['reason'] == 'no_matching_local_snapshot'
    health = client.get('/v1/source-health').json()['sources'][0]
    assert health['rejected_count'] == 1 and health['successes'] == 0 and health['failures'] == 1
    with database.sessions() as db:
        evidence = db.get(RejectedObservation, row['id'])
        assert evidence.raw_body == BODY.encode()
        evidence.raw_body = b'changed'
        with pytest.raises(ValueError, match='只能追加'):
            db.commit()
        db.rollback()
        db.delete(db.get(RejectedObservation, row['id']))
        with pytest.raises(ValueError, match='只能追加'):
            db.commit()


def test_rejected_body_cannot_poison_fallback_or_conditional_cache(setup):
    client, registry, database = setup
    accepted = live(client).json()
    registry.result = rejected()
    failed = live(client).json()
    assert not failed['variants']
    denied = grant(client, failed['query_id'], 'deny').json()
    assert live(client, {**QUERY, 'consent_id': denied['id']}).status_code == 403
    failed = live(client).json()
    permitted = grant(client, failed['query_id']).json()
    local = live(client, {**QUERY, 'consent_id': permitted['id']}).json()
    assert_frozen_query_evidence(accepted, local, expected_state='local_snapshot')
    assert local['snapshot_observed_at'] == accepted['snapshot_observed_at']
    registry.result = {"status": "not_modified", "url": "https://fixture.example/tires/product",
                       "parser_version": "fixture@1", "etag": '"fixture-etag"'}
    verified = live(client).json()
    assert verified['data_state'] == 'live_verified_304'
    assert_frozen_query_evidence(accepted, verified, expected_state='live_verified_304', reverified=True)
    assert registry.calls[-1][2]['body'] == 'fixture-body-v1'
    assert registry.calls[-1][2]['etag'] == '"fixture-etag"'
    assert count(database, Snapshot) == count(database, FactVersion) == 1


def test_schema_rejection_preserves_raw_without_storing_invalid_candidates(setup):
    client, registry, database = setup
    registry.result = success(body=BODY, variants=[{'load_index': 'not-valid'}])
    result = live(client, {**QUERY, 'fallback_policy': 'never'}).json()
    assert result['data_state'] == 'source_unavailable' and not result['variants']
    metadata = client.get('/v1/quarantines').json()['items'][0]
    assert metadata['stage'] == 'schema' and metadata['reason_codes'] == ['source_schema_validation_failed']
    detail = client.get(metadata['evidence_path']).json()
    assert detail['body'] == BODY and detail['candidates'] == []
    assert count(database, FactVersion) == count(database, Snapshot) == 0


def test_list_and_health_do_not_load_raw_bodies(setup):
    client, registry, database = setup
    registry.result = rejected()
    live(client)
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            statements.append(statement.lower())

    event.listen(database.engine, 'before_cursor_execute', capture)
    try:
        assert len(client.get('/v1/quarantines?limit=1').json()['items']) == 1
        assert client.get('/v1/quarantines?source_id=fixture-two').json()['items'] == []
        client.get('/v1/source-health')
    finally:
        event.remove(database.engine, 'before_cursor_execute', capture)
    assert any('rejected_observations' in statement for statement in statements)
    assert all('raw_body' not in statement for statement in statements)


@pytest.mark.parametrize('bad_kind', ['no_response', 'empty', 'oversize', 'non_utf8', 'credentials', 'query_secret', 'http', 'mime', 'parser_control'])
def test_unobtained_or_unsafe_envelopes_do_not_fabricate_evidence(setup, bad_kind):
    client, registry, database = setup
    response = rejected()
    observation = response['rejected_observation']
    if bad_kind == 'no_response':
        response = {'status': 'unavailable', 'reason': 'upstream_timeout'}
    elif bad_kind == 'empty': observation['body'] = ''
    elif bad_kind == 'oversize': observation['body'] = 'x' * (8 * 1024 * 1024 + 1)
    elif bad_kind == 'non_utf8': observation['body'] = '\ud800'
    elif bad_kind == 'credentials': observation['url'] = 'https://user:fixture-secret@fixture.example/x'
    elif bad_kind == 'query_secret': observation['url'] += '?token=fixture-secret'
    elif bad_kind == 'http': observation['url'] = 'http://fixture.example/x'
    elif bad_kind == 'mime': observation['content_type'] = 'application/octet-stream'
    else: observation['parser_version'] = 'bad\x00version'
    registry.result = response
    assert live(client).status_code == 200
    assert count(database, RejectedObservation) == 0


@pytest.mark.parametrize('error', [ValueError('do-not-expose'), RuntimeError('do-not-expose'), SourceAccessError('do-not-expose')])
def test_official_registry_hands_off_obtained_body_after_parser_error(monkeypatch, error):
    spec = official.SPECS['michelin-us']

    async def bad_parser(*_): raise error

    class Transport:
        def __init__(self, *_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def get(self, url, **_): return FetchResult(200, url, BODY, 'text/html', '"bad"', None)

    async def robots(*_): return RobotsPolicy('', 'TireEvidenceResearch')

    monkeypatch.setenv('TI_DISABLED_SOURCES', '')
    monkeypatch.setattr(official, 'parse_isolated', bad_parser)
    monkeypatch.setattr(official, '_states', {})
    monkeypatch.setattr(official, '_robots_policy', robots)
    monkeypatch.setattr(official, 'SafeHttpClient', Transport)
    response = asyncio.run(official.fetch('michelin-us', {'model': 'PSEV'}))
    assert response['status'] == 'unavailable' and response['reason'] == 'parser_schema_changed'
    assert response['rejected_observation']['body'] == BODY
    assert 'do-not-expose' not in str(response)
    assert official._states[spec.origin]['failures'] == 1
    assert official._states[spec.origin]['busy'] is False


def test_xiaomi_transport_hands_off_invalid_obtained_json(monkeypatch):
    class Transport:
        def __init__(self, *_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def get(self, url, **_): return FetchResult(200, url, '', 'text/plain', None, None)
        async def post(self, url, **_): return FetchResult(200, url, BODY, 'application/json', None, None)

    monkeypatch.setenv('TI_DISABLED_SOURCES', '')
    monkeypatch.setattr(xiaomi, 'SafeHttpClient', Transport)
    monkeypatch.setattr(xiaomi, '_last_fetch', -float('inf'))
    monkeypatch.setattr(xiaomi, '_busy', False)
    monkeypatch.setattr(xiaomi, '_robots', {})
    monkeypatch.setattr(xiaomi, '_robots_requests', {})
    response = asyncio.run(xiaomi.fetch(xiaomi.CURRENT_ID))
    assert response['status'] == 'unavailable'
    assert response['reason'] == response['parser_error'] == 'parser_schema_changed'
    assert response['rejected_observation']['body'] == BODY
    assert 'payload' not in response
    adapter = FixtureVehicleAdapter()
    adapter.result = response
    app = create_app('sqlite://', OfflineTireRegistry())
    register_vehicle_routes(app, adapter)
    with TestClient(app) as client:
        failed = client.post(f'/v1/vehicles/{xiaomi.CURRENT_ID}/live-fitments',
            json={'fallback_policy': 'never'}).json()
        assert failed['reason'] == 'parser_schema_changed'
        assert failed['fitments'] == failed['provenance'] == []
        assert count(app.state.database, RejectedObservation) == 1
        assert all(count(app.state.database, model) == 0 for model in
            (VehicleSnapshot, Snapshot, FactVersion, Verification, ChangeEvent))


@pytest.mark.parametrize('stage', ['parser', 'schema'])
def test_vehicle_rejected_response_is_not_a_fitment_or_fallback_candidate(stage):
    adapter = FixtureVehicleAdapter()
    if stage == 'parser':
        adapter.result = rejected()
        adapter.result['rejected_observation'].update(url=xiaomi.API_URL, content_type='application/json')
    else:
        adapter.result['payload']['fitments'] = []
    app = create_app('sqlite://', OfflineTireRegistry())
    register_vehicle_routes(app, adapter)
    with TestClient(app) as client:
        endpoint = f'/v1/vehicles/{xiaomi.CURRENT_ID}/live-fitments'
        failed = client.post(endpoint, json={'fallback_policy': 'ask'}).json()
        assert failed['fitments'] == failed['provenance'] == []
        metadata = client.get('/v1/quarantines').json()['items'][0]
        assert metadata['target_kind'] == 'vehicle' and metadata['stage'] == stage
        consent = grant(client, failed['query_id']).json()
        local = client.post(endpoint, json={'fallback_policy': 'ask', 'consent_id': consent['id']}).json()
        assert local['fitments'] == local['provenance'] == []
        assert count(app.state.database, VehicleSnapshot) == 0
