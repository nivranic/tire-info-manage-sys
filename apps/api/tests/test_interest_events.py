"""Producer contracts with private databases and synthetic accepted observations."""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, func, select

from admin_support import register_admin
from test_core import FixtureRegistry, VARIANT, success
from tire_api.db import ChangeEvent, FactVersion, Snapshot, Verification
from tire_api.domain import digest
from tire_api.interest_events import publish
from tire_api.interest_models import InterestEvent, InterestNotification
from tire_api.interest_catalog_models import TireCatalogRevision
from tire_api.main import create_app


@pytest.fixture
def producer(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    for key in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(key, '0')
    registry = FixtureRegistry()
    app = create_app('sqlite:///' + (tmp_path / 'private-interest-events.sqlite').as_posix(), registry)
    with TestClient(app) as client:
        register_admin(client)
        yield client, registry, app.state.database


def watch(client):
    response = client.post('/v1/interests', json={'name': 'Synthetic producer observations', 'enabled': True,
        'conditions': [{'kind': 'brand', 'values': ['Fixture Brand']}], 'metric_keys': [],
        'changed_fields': ['facts.utqg_treadwear']})
    assert response.status_code == 201, response.text
    return response.json()


def adopt(client, *, broad=False):
    response = client.post('/v1/sources/fixture/live-query', json={
        'query': {'size': '265/40R20', **({'model': 'Fixture Tire'} if broad else {})}, 'fallback_policy': 'never'})
    assert response.status_code == 200, response.text
    assert response.json()['data_state'] in ('live', 'live_verified_304'), response.text
    return response.json()


@pytest.mark.parametrize('status', ['ok', 'not_modified'])
def test_tire_reconcile_freezes_actual_version_and_archived_member_independently(producer, status):
    client, registry, database = producer
    watch(client)
    known = {**deepcopy(VARIANT), 'facts': {**VARIANT['facts'], 'product_code_type': 'FIXTURE_CODE'}}
    registry.result = success(variants=[known])
    first = adopt(client)
    registry.result = success('Synthetic changed facts body', [{**known, 'facts': {**known['facts'], 'utqg_treadwear': 320}}])
    adopt(client, broad=True)
    registry.result = success(variants=[known]) if status == 'ok' else {
        'status': 'not_modified', 'url': 'https://fixture.example/tires/product', 'etag': '"fixture-etag"'}
    third = adopt(client)
    assert third['variants'][0]['fact_version'] == 3
    with database.sessions() as db:
        rows = db.scalars(select(InterestEvent).where(InterestEvent.domain == 'tire').order_by(InterestEvent.observed_at)).all()
        assert len(rows) == 3
        frozen = rows[-1].payload
        assert frozen['after']['evidence_valid'] is True
        assert frozen['after']['fact_version'] == 3
        assert frozen['after']['snapshot_member_fact_version'] == 1
        assert frozen['after']['snapshot_id'] == first['provenance'][0]['snapshot_id']
        assert frozen['before']['fact_version'] == 2
        actual = db.get(FactVersion, frozen['after']['fact_version_id'])
        assert actual.facts_hash == frozen['after']['facts_hash'] == digest(actual.facts)
        assert frozen['event_hash'] == digest({key: value for key, value in frozen.items() if key != 'event_hash'})
        origin = db.get(ChangeEvent, rows[-1].origin_id)
        assert publish(db, 'tire', origin).payload == frozen
        db.commit()
    response = client.get('/v1/interest-notifications?mode=history').json()
    assert response['total'] == 3
    # Re-verification of the same raw snapshot changes neither event nor evidence.
    registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product', 'etag': '"fixture-etag"'}
    adopt(client)
    assert client.get('/v1/interest-notifications?mode=history').json()['total'] == 3
    with database.sessions() as db:
        assert db.get(InterestEvent, frozen['id']).payload == frozen


def test_delivery_failure_rolls_back_tire_adoption_with_verification_and_event(producer):
    client, registry, database = producer
    watch(client)
    models = (Snapshot, FactVersion, ChangeEvent, Verification, InterestEvent, InterestNotification, TireCatalogRevision)
    def counts():
        with database.sessions() as db:
            return tuple(db.scalar(select(func.count()).select_from(model)) for model in models)
    before = counts()
    def fail(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith('insert into interest_notifications'):
            raise RuntimeError('synthetic_tire_interest_delivery_failure')
    event.listen(database.engine, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='synthetic_tire_interest_delivery_failure'):
            adopt(client)
    finally:
        event.remove(database.engine, 'before_cursor_execute', fail)
    assert counts() == before
    adopt(client)
    after = counts()
    assert after[:4] == (1, 1, 1, 1)
    assert after[5:] == (1, 1)  # One fact-filtered notice and one initial catalog membership.
    with database.sessions() as db:
        assert dict(db.execute(select(InterestEvent.domain, func.count()).group_by(InterestEvent.domain)).all()) == {
            'tire': 1, 'tire_catalog': 1}


def test_notification_keeps_matching_criteria_after_interest_is_revised(producer):
    client, registry, _ = producer
    watched = watch(client)
    adopt(client)
    original = client.get('/v1/interest-notifications?mode=history').json()['items'][0]
    frozen_criteria = {key: watched[key] for key in ('conditions', 'metric_keys', 'changed_fields')}
    assert original['match']['criteria'] == frozen_criteria
    payload = {key: watched[key] for key in ('name', 'enabled', 'conditions', 'metric_keys', 'changed_fields')}
    response = client.put('/v1/interests/' + watched['id'], json={**payload, 'name': 'Synthetic revised scope',
        'conditions': [{'kind': 'brand', 'values': ['A different brand']}], 'expected_revision': watched['revision']})
    assert response.status_code == 200, response.text
    reopened = client.get('/v1/interest-notifications/' + original['id'] + '?mode=history').json()
    assert reopened == original
    assert reopened['match']['criteria'] == frozen_criteria


def test_source_declared_vehicle_axle_size_needs_no_inferred_sku_review():
    from tire_api.interest_matching import InterestCriteria, changed_paths, match_event
    before = None
    after = {'vehicle': {'id': 'synthetic-vehicle'}, 'fitments': [{'id': 'option', 'trim_id': 'trim',
             'front': {'size': '245/40R20'}, 'rear': {'size': '265/40R20'}}]}
    event = {'domain': 'vehicle', 'before': before, 'after': after, 'changed_paths': changed_paths(before, after)}
    criteria = InterestCriteria.model_validate({'conditions': [
        {'kind': 'vehicle_fitment', 'values': [{'vehicle_id': 'synthetic-vehicle', 'trim_id': 'trim', 'axle': 'rear'}]},
        {'kind': 'size', 'values': ['265/40R20']}], 'metric_keys': [], 'changed_fields': ['fitments']})
    assert match_event(event, criteria)['state'] == 'matched'
    vehicle_condition = next(group for group in criteria.conditions if group.kind == 'vehicle_fitment')
    vehicle_condition.values[0]['axle'] = 'front'
    assert match_event(event, criteria)['state'] != 'matched'
    criteria.conditions.append(type(vehicle_condition).model_validate({'kind': 'brand', 'values': ['Guessed Brand']}))
    assert match_event(event, criteria)['state'] != 'matched'
