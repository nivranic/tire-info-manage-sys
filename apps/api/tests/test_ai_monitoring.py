"""Frozen diff citations, including 304 reconciliation and missing-value semantics."""
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import desc, select

from tire_api.db import ChangeEvent, utcnow
from tire_api.main import create_app
from test_ai import ModelFixture, analyze
from test_core import FixtureRegistry, QUERY, VARIANT, live, success
from test_fitment_relations import seed_tire


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('TI_AI_ENABLED', '1')
    monkeypatch.setenv('TI_OPENAI_MODEL', 'synthetic-responses')
    monkeypatch.setenv('TI_OPENAI_API_KEY', 'synthetic-never-live')
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '1')
    registry = FixtureRegistry()
    app = create_app('sqlite://', registry)
    app.state.ai_adapter = ModelFixture()
    with TestClient(app) as client:
        yield client, registry, app.state.database


def change_pack(client, change_id):
    return client.post('/v1/ai/evidence-packs', json={'mode': 'history',
        'references': [{'kind': 'change_event', 'change_id': change_id}]})


def latest_change(database):
    with database.sessions() as db:
        return db.scalar(select(ChangeEvent).order_by(desc(ChangeEvent.observed_at), desc(ChangeEvent.id))).id


def test_change_uses_frozen_values_two_snapshots_and_not_conflicts(setup):
    client, registry, database = setup
    first = live(client).json()
    registry.result = success('changed', [{**VARIANT, 'facts': {'utqg_treadwear': 420}}])
    second = live(client).json()
    event_id = latest_change(database)
    response = change_pack(client, event_id)
    assert response.status_code == 200, response.text
    pack = response.json()['pack']
    evidence = pack['evidence'][0]
    assert pack['purpose'] == 'monitor_explanation' and pack['conflicts'] == []
    assert evidence['snapshot_id'] == second['provenance'][0]['snapshot_id']
    assert evidence['previous_snapshot_id'] == first['provenance'][0]['snapshot_id']
    assert evidence['raw_hash'] != evidence['previous_raw_hash']
    assert '300 → 420' in pack['facts'][0]['text']
    registry.result = success('later', [{**VARIANT, 'facts': {'utqg_treadwear': 440}}])
    live(client)
    result = analyze(client, pack).json()
    assert result['state'] == 'completed' and '300 → 420' in result['answer']['claims'][0]['text']
    assert '440' not in result['answer']['claims'][0]['text']


def test_first_observation_and_304_are_not_new_release_claims(setup):
    client, registry, database = setup
    known = {**deepcopy(VARIANT), 'facts': {**VARIANT['facts'], 'product_code_type': 'MSPN'}}
    registry.result = success(variants=[known])
    first = live(client).json()
    pack = change_pack(client, latest_change(database)).json()['pack']
    assert pack['evidence'][0]['previous_snapshot_id'] is None
    assert any('不代表产品刚发布' in fact['text'] for fact in pack['facts'])
    registry.result = success('other-query', [{**known, 'facts': {**known['facts'], 'utqg_treadwear': 420}}])
    other = live(client, {'query': {'model': 'Fixture Tire'}, 'fallback_policy': 'never'}).json()
    registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product', 'etag': '"fixture-etag"'}
    checked = live(client).json()
    assert checked['data_state'] == 'live_verified_304'
    pack = change_pack(client, latest_change(database)).json()['pack']
    evidence = pack['evidence'][0]
    assert evidence['snapshot_id'] == first['provenance'][0]['snapshot_id']
    assert evidence['previous_snapshot_id'] == other['provenance'][0]['snapshot_id']
    assert evidence['change_kind'] == 'facts_changed' and '420 → 300' in pack['facts'][0]['text']
    assert evidence['change_observed_at'] > evidence['observed_at']


@pytest.mark.parametrize('corruption', [None, 'wrong_variant', 'wrong_before_value', 'wrong_presence', 'wrong_before_snapshot'])
def test_exact_snapshot_membership_and_absent_versus_null(setup, corruption):
    client, _, database = setup
    identity = str(uuid4())
    client.get('/health')
    session = client.cookies['tire_local_session']
    _, before, _ = seed_tire(database, session, {**VARIANT, 'facts': {'product_code_type': 'MSPN'}},
        variant_id=identity, source='fixture', observed_at=utcnow() - timedelta(seconds=3))
    _, after, _ = seed_tire(database, session,
        {**VARIANT, 'facts': {'product_code_type': 'MSPN', 'utqg_treadwear': None}},
        variant_id=identity, source='fixture', version=2)
    delta = {'before': None, 'after': None, 'before_present': False, 'after_present': True}
    if corruption == 'wrong_before_value': delta['before'] = 300
    if corruption == 'wrong_presence': delta['before_present'] = True
    if corruption == 'wrong_before_snapshot': before = after
    if corruption == 'wrong_variant':
        identity = str(uuid4())
        seed_tire(database, session, {**VARIANT, 'manufacturer_product_code': 'OTHER-SYNTHETIC',
            'facts': {'product_code_type': 'MSPN'}}, variant_id=identity, source='fixture')
    with database.sessions() as db:
        row = ChangeEvent(variant_id=identity, source_id='fixture', snapshot_id=after,
            previous_snapshot_id=before, kind='facts_changed', changes={'utqg_treadwear': delta})
        db.add(row)
        db.commit()
        event_id = row.id
    response = change_pack(client, event_id)
    if corruption:
        assert response.status_code == 409, response.text
    else:
        assert response.status_code == 200, response.text
        assert '未声明此字段 → 明确未知（null）' in response.json()['pack']['facts'][0]['text']


def test_revoked_event_identity_cannot_prepare_or_analyze(setup):
    from test_lifecycle import request_for
    client, _, database = setup
    result = live(client).json()
    event_id = latest_change(database)
    pack = change_pack(client, event_id).json()['pack']
    assert client.post(f'/v1/tire-variants/{result["variants"][0]["id"]}/lifecycle-events', json=request_for(result)).status_code == 201
    assert change_pack(client, event_id).status_code == 409
    assert analyze(client, pack).status_code == 409


def test_first_observation_is_scoped_to_source_even_for_existing_exact_identity(setup):
    client, registry, database = setup
    registry.result = success(variants=[{**deepcopy(VARIANT),
        'facts': {**VARIANT['facts'], 'product_code_type': 'MSPN'}}])
    first = live(client).json()
    second = live(client, source='fixture-two').json()
    assert first['variants'][0]['id'] == second['variants'][0]['id']
    pack = change_pack(client, latest_change(database)).json()['pack']
    assert pack['evidence'][0]['source_id'] == 'fixture-two'
    assert any('在该来源首次观察' in fact['text'] for fact in pack['facts'])
