"""User-owned vehicle records must never become official fitment facts."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from tire_api.db import GarageRevision, GarageVehicle, Snapshot, TireVariant
from tire_api.main import create_app
from tire_api.vehicles import VehicleSnapshot, register_vehicle_routes
from test_core import FixtureRegistry, count, live, setup
from test_lifecycle import request_for
from test_vehicles import FixtureVehicleAdapter

PROFILE = {'nickname': '合成车库车辆', 'manufacturer': 'TEST', 'model': 'Synthetic Car',
           'model_year': None, 'generation': None, 'trim': None, 'wheel_option': None,
           'optional_wheels': [], 'front': {'size': '245/40R20', 'current_variant_id': None},
           'rear': {'size': '265/40ZR20', 'current_variant_id': None}}


def create(client, **fields):
    response = client.post('/v1/garage', json={**PROFILE, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def test_garage_create_edit_archive_restore_is_append_only_and_does_not_fetch(setup):
    client, registry, database = setup
    created = create(client)
    vehicle_id = created['id']
    assert created['basis'] == 'user_entry' and created['revision'] == 1
    assert created['profile']['model_year'] is None and not created['fitment_reference']
    assert created['current_tires'] == {'front': None, 'rear': None}
    edited = client.put('/v1/garage/' + vehicle_id, json={'expected_revision': 1,
        'profile': {**created['profile'], 'nickname': '新名称', 'optional_wheels': ['测试 20 英寸', '测试 21 英寸']}})
    assert edited.status_code == 200 and edited.json()['revision'] == 2
    assert client.put('/v1/garage/' + vehicle_id, json={'expected_revision': 1, 'profile': PROFILE}).status_code == 409
    archived = client.post(f'/v1/garage/{vehicle_id}/state', json={'expected_revision': 2, 'action': 'archive'}).json()
    assert archived['archived'] and archived['revision'] == 3
    assert client.get('/v1/garage').json()['items'] == []
    assert client.get('/v1/garage?archived=true').json()['items'][0]['id'] == vehicle_id
    assert client.put('/v1/garage/' + vehicle_id, json={'expected_revision': 3, 'profile': PROFILE}).status_code == 409
    restored = client.post(f'/v1/garage/{vehicle_id}/state', json={'expected_revision': 3, 'action': 'restore'}).json()
    assert not restored['archived'] and restored['revision'] == 4
    assert client.get('/v1/garage/' + vehicle_id).status_code == 422
    history = client.get(f'/v1/garage/{vehicle_id}?mode=history').json()['history']
    assert [row['operation'] for row in history] == ['restore', 'archive', 'update', 'create']
    assert history[-1]['profile']['nickname'] == PROFILE['nickname']
    assert registry.calls == [] and count(database, Snapshot) == count(database, TireVariant) == 0
    with database.sessions() as db:
        row = db.scalar(select(GarageRevision))
        row.profile = {**row.profile, 'nickname': 'erase history'}
        with pytest.raises(ValueError, match='只能追加'): db.commit()
        db.rollback()
        db.delete(db.scalar(select(GarageVehicle)))
        with pytest.raises(ValueError, match='只能追加'): db.commit()


def test_local_workspace_garage_survives_session_change_and_restart(tmp_path):
    url = f"sqlite:///{(tmp_path/'persistent-garage.db').as_posix()}"
    with TestClient(create_app(url, FixtureRegistry())) as first:
        created = create(first)
    # Deliberately no old cookies: this is one local workspace, not a cloud account.
    with TestClient(create_app(url, FixtureRegistry())) as second:
        response = second.get('/v1/garage').json()
        assert response['scope'] == 'local_workspace' and response['items'][0]['id'] == created['id']


def test_current_tires_have_exact_axle_sizes_and_revocation_is_not_hidden(setup):
    client, _, database = setup
    tire = live(client).json()
    vid = tire['variants'][0]['id']
    car = create(client)
    path = f"/v1/garage/{car['id']}/tires"
    assert client.post(path, json={'expected_revision': 1, 'axle': 'front', 'variant_id': vid}).status_code == 422
    assigned = client.post(path, json={'expected_revision': 1, 'axle': 'rear', 'variant_id': vid}).json()
    assert assigned['revision'] == 2 and assigned['current_tires']['rear']['manufacturer_product_code'] == 'FIX-001'
    assert 'facts' not in assigned['current_tires']['rear']
    client.post(f'/v1/tire-variants/{vid}/lifecycle-events', json=request_for(tire))
    saved = client.get('/v1/garage').json()['items'][0]
    assert saved['current_tires']['rear']['lifecycle']['state'] == 'revoked'
    changed = client.put('/v1/garage/' + car['id'], json={'expected_revision': 2,
        'profile': {**saved['profile'], 'nickname': '保留旧轮胎记录'}})
    assert changed.status_code == 200
    other = create(client, front={'size': None, 'current_variant_id': None})
    assert client.post(f"/v1/garage/{other['id']}/tires", json={
        'expected_revision': 1, 'axle': 'front', 'variant_id': vid}).status_code == 422
    cleared = client.post(path, json={'expected_revision': 3, 'axle': 'rear', 'variant_id': None}).json()
    assert cleared['current_tires']['rear'] is None and cleared['profile']['rear']['size'] == '265/40ZR20'
    assert count(database, Snapshot) == 1


def test_unknown_axle_size_can_be_explicitly_filled_from_selected_sku(setup):
    client, _, _ = setup
    tire = live(client).json()['variants'][0]
    car = create(client, front={'size': None, 'current_variant_id': None})
    assigned = client.post(f"/v1/garage/{car['id']}/tires", json={
        'expected_revision': 1, 'axle': 'front', 'variant_id': tire['id']}).json()
    assert assigned['profile']['front']['size'] == tire['size']
    assert assigned['profile']['rear']['current_variant_id'] is None


@pytest.mark.parametrize('change', [
    {'vin': 'not-collected'}, {'model_year': True}, {'model_year': 1899}, {'nickname': ' '},
    {'front': {'size': '20 inch'}}, {'optional_wheels': ['same', 'same']},
    {'front': {'current_variant_id': 'unknown'}}, {'fitment_reference': {'verified': True}},
])
def test_invalid_or_forged_personal_profiles_are_rejected(setup, change):
    client, _, database = setup
    assert client.post('/v1/garage', json={**PROFILE, **change}).status_code == 422
    assert count(database, GarageVehicle) == count(database, GarageRevision) == 0


def test_copy_fitment_retains_source_and_never_infers_oe_sku_or_year():
    adapter = FixtureVehicleAdapter()
    app = create_app('sqlite://', FixtureRegistry())
    register_vehicle_routes(app, adapter)
    with TestClient(app) as client:
        from tire_api.adapters import xiaomi
        response = client.post(f'/v1/vehicles/{xiaomi.CURRENT_ID}/live-fitments', json={'fallback_policy': 'never'}).json()
        fitment = next(row for row in response['fitments'] if row['availability'] == 'standard')
        snapshot_id = response['provenance'][0]['snapshot_id']
        car = client.post('/v1/garage/from-fitment', json={'snapshot_id': snapshot_id,
            'fitment_id': fitment['id'], 'nickname': '合成适配复制'}).json()
        assert car['basis'] == 'copied_fitment' and car['profile']['model_year'] is None
        assert car['profile']['front']['size'] == '245/40R20' and car['profile']['rear']['size'] == '265/40R20'
        assert all(value is None for value in car['current_tires'].values())
        assert car['fitment_reference']['raw_hash'] == response['provenance'][0]['raw_hash']
        unavailable = next(row for row in response['fitments'] if row['availability'] == 'unavailable')
        assert client.post('/v1/garage/from-fitment', json={'snapshot_id': snapshot_id,
            'fitment_id': unavailable['id'], 'nickname': '不可用配置'}).status_code == 422
        assert client.post('/v1/garage/from-fitment', json={'snapshot_id': 'unknown',
            'fitment_id': fitment['id'], 'nickname': '未验证快照'}).status_code == 422
        changed = client.put('/v1/garage/' + car['id'], json={'expected_revision': 1,
            'profile': {**car['profile'], 'model_year': 2025}}).json()
        assert changed['basis'] == 'user_entry' and changed['fitment_reference'] == car['fitment_reference']
        assert count(app.state.database, VehicleSnapshot) == 1
        assert len(adapter.calls) == 1  # Copy/edit did not query the official source.


def test_garage_pagination_noop_and_failed_query_do_not_inject_local_data(setup):
    client, registry, database = setup
    first = create(client)
    second = create(client, nickname='第二辆合成车')
    page = client.get('/v1/garage?offset=1').json()
    assert page['total'] == 2 and len(page['items']) == 1 and page['items'][0]['id'] == first['id']
    assert client.put('/v1/garage/' + first['id'], json={'expected_revision': 1, 'profile': first['profile']}).json()['revision'] == 1
    assert count(database, GarageRevision) == 2
    registry.result = {'status': 'unavailable', 'reason': 'synthetic_outage'}
    statements = []
    def record(_conn, _cursor, sql, *_): statements.append(sql.lower())
    event.listen(database.engine, 'before_cursor_execute', record)
    try:
        response = live(client).json()
    finally:
        event.remove(database.engine, 'before_cursor_execute', record)
    assert response['data_state'] == 'consent_required' and response['variants'] == []
    assert all('garage_' not in sql for sql in statements)


def test_copy_preserves_selected_trim_year_instead_of_guessing_from_generation():
    from tire_api.adapters import xiaomi
    adapter = FixtureVehicleAdapter()
    for trim in adapter.result['payload']['trims']:
        trim['model_year'] = 2025
    app = create_app('sqlite://', FixtureRegistry())
    register_vehicle_routes(app, adapter)
    with TestClient(app) as client:
        response = client.post(f'/v1/vehicles/{xiaomi.CURRENT_ID}/live-fitments', json={'fallback_policy': 'never'}).json()
        fitment = next(row for row in response['fitments'] if row['availability'] == 'standard')
        car = client.post('/v1/garage/from-fitment', json={'snapshot_id': response['provenance'][0]['snapshot_id'],
            'fitment_id': fitment['id'], 'nickname': '合成年款核验'}).json()
        assert response['vehicle']['model_year'] is None
        assert car['profile']['model_year'] == 2025


def test_concurrent_garage_edit_has_one_winner(tmp_path):
    url = f"sqlite:///{(tmp_path/'garage-race.db').as_posix()}"
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        car = create(client)
        cookies = dict(client.cookies)
        barrier = Barrier(2)
        def update(nickname):
            with TestClient(app, cookies=cookies) as actor:
                barrier.wait(timeout=5)
                return actor.put('/v1/garage/' + car['id'], json={
                    'expected_revision': 1, 'profile': {**car['profile'], 'nickname': nickname}}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(update, ['第一份修改', '第二份修改'])) == [200, 409]
