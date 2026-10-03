"""Vehicle quality uses separate trim and fitment baselines, never tire identities."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from tire_api.adapters import xiaomi
from tire_api.db import RejectedObservation
from tire_api.main import create_app
from tire_api.vehicle_quality import assess_vehicle_quality
from tire_api.vehicles import VehicleQuarantine, VehicleSnapshot, VehicleTrim, VehicleVerification, WheelFitment, register_vehicle_routes
from test_vehicles import FixtureVehicleAdapter, OfflineTireRegistry, count, grant, live, setup


def rebody(adapter):
    adapter.result['body'] = json.dumps(adapter.result['payload'], ensure_ascii=False)


def remove_trim(adapter):
    payload = adapter.result['payload']
    removed = payload['trims'].pop()
    payload['fitments'] = [row for row in payload['fitments'] if row['trim_id'] != removed['id']]
    rebody(adapter)


def health(client):
    return next(row for row in client.get('/v1/source-health').json()['sources'] if row['source_id'] == xiaomi.SOURCE_ID)


def test_trim_loss_quarantine_preserves_only_accepted_fallback_and_history(setup):
    client, adapter, database = setup
    accepted = live(client).json()
    original = deepcopy(adapter.result)
    remove_trim(adapter)
    failed = live(client).json()
    assert failed['data_state'] == 'consent_required' and failed['reason'] == 'source_quality_quarantined'
    assert failed['fitments'] == [] and failed['vehicle'] is None and failed['provenance'] == []
    assert count(database, VehicleSnapshot) == count(database, VehicleVerification) == 1
    assert count(database, WheelFitment) == 4 and count(database, VehicleTrim) == 2
    assert count(database, VehicleQuarantine) == 1
    assert health(client)['status'] == 'quarantined' and health(client)['quarantined_count'] == 1
    consent = grant(client, failed['query_id']).json()
    offline = live(client, {'fallback_policy': 'ask', 'consent_id': consent['id']}).json()
    assert offline['data_state'] == 'local_snapshot' and offline['fitments'] == accepted['fitments']
    assert offline['provenance'] == accepted['provenance']
    assert live(client, {'fallback_policy': 'ask', 'consent_id': consent['id']}).status_code == 409
    record = client.get('/v1/quarantines?source_id=' + xiaomi.SOURCE_ID).json()['items'][0]
    assert record['target_kind'] == 'vehicle' and record['previous_snapshot_id'] == accepted['provenance'][0]['snapshot_id']
    assert record['metrics']['lost_rows'] == 3  # 1 trim + 2 wheel options
    assert client.get('/v1/quarantines/' + record['id']).status_code == 422
    detail = client.get('/v1/quarantines/' + record['id'] + '?mode=history').json()
    assert detail['accepted'] is False and detail['body'] == adapter.result['body']
    assert detail['quality']['groups']['trims']['row_loss_ratio'] == .5
    assert detail['quality']['groups']['fitments']['row_loss_ratio'] == .5
    assert detail['vehicle_payload'] == adapter.result['payload']
    with database.sessions() as db:
        row = db.get(VehicleQuarantine, record['id'])
        row.body = 'replaced'
        with pytest.raises(ValueError, match='只能追加'): db.commit()
    adapter.result = original
    assert live(client).json()['data_state'] == 'live'
    assert count(database, VehicleSnapshot) == 1 and count(database, VehicleVerification) == 2
    assert health(client)['status'] == 'healthy' and health(client)['quarantined_count'] == 1


def test_first_observation_and_reorder_do_not_invent_loss(setup):
    client, adapter, database = setup
    remove_trim(adapter)
    assert live(client).json()['data_state'] == 'live'
    adapter.result['payload']['fitments'].reverse()
    adapter.result['payload']['trims'][0]['wheel_option_ids'].reverse()
    rebody(adapter)
    result = live(client).json()
    assert result['data_state'] == 'live' and result['fact_version'] == 1
    assert count(database, VehicleQuarantine) == 0


def test_known_axle_field_loss_is_quarantined_but_legitimate_values_can_change(setup):
    client, adapter, database = setup
    for row in adapter.result['payload']['fitments']:
        for axle in ('front', 'rear'):
            row[axle].update(load_index='104', speed_rating='Y', oe_mark='TEST', manufacturer_product_code='TEST-AXLE')
    rebody(adapter)
    assert live(client).json()['data_state'] == 'live'
    for row in adapter.result['payload']['fitments']:
        row['front']['load_index'] = '105'
        row['rear']['load_index'] = '105'
    rebody(adapter)
    assert live(client).json()['fact_version'] == 2
    for row in adapter.result['payload']['fitments']:
        for axle in ('front', 'rear'):
            for key in ('load_index', 'speed_rating', 'oe_mark', 'manufacturer_product_code'):
                row[axle][key] = None
    rebody(adapter)
    failure = live(client, {'fallback_policy': 'never'}).json()
    assert failure['data_state'] == 'source_unavailable' and failure['fitments'] == []
    record = client.get('/v1/quarantines').json()['items'][0]
    detail = client.get(record['evidence_path']).json()
    report = detail['quality']['groups']['fitments']
    assert report['field_loss_ratio'] >= .3 and 'field_loss_threshold' in report['reason_codes']
    assert count(database, VehicleVerification) == 2


def test_exact_thirty_percent_and_separate_group_denominators():
    baseline = FixtureVehicleAdapter().result['payload']
    original = baseline['fitments'][0]
    baseline['fitments'] = [{**deepcopy(original), 'id': f'option-{i}'} for i in range(10)]
    candidate = deepcopy(baseline)
    candidate['fitments'] = candidate['fitments'][2:]
    assert not assess_vehicle_quality(baseline, candidate)['reason_codes']
    candidate['fitments'] = candidate['fitments'][1:]
    assert assess_vehicle_quality(baseline, candidate)['groups']['fitments']['row_loss_ratio'] == .3
    assert 'row_loss_threshold' in assess_vehicle_quality(baseline, candidate)['reason_codes']
    candidate = deepcopy(baseline)
    candidate['trims'].pop()
    report = assess_vehicle_quality(baseline, candidate)
    assert report['row_loss_ratio'] < .3 and 'row_loss_threshold' in report['reason_codes']


@pytest.mark.parametrize('change', ['duplicate_trim', 'wrong_options', 'renamed_mapping', 'bad_year', 'missing_manufacturer'])
def test_malformed_structure_rejects_before_baseline_and_preserves_raw(setup, change):
    client, adapter, database = setup
    payload = adapter.result['payload']
    if change == 'duplicate_trim': payload['trims'].append(deepcopy(payload['trims'][0]))
    elif change == 'wrong_options': payload['trims'][0]['wheel_option_ids'] = ['invented']
    elif change == 'renamed_mapping': payload['fitments'][0]['trim_name'] = 'another trim'
    elif change == 'bad_year': payload['vehicle']['model_year'] = True
    else: payload['vehicle'].pop('manufacturer')
    rebody(adapter)
    result = live(client).json()
    assert result['reason'] == 'vehicle_source_schema_changed'
    assert count(database, VehicleSnapshot) == count(database, VehicleTrim) == 0
    assert count(database, RejectedObservation) == 1


def test_identity_drift_and_missing_stable_ids_are_not_auto_merged(setup):
    client, adapter, database = setup
    live(client)
    adapter.result['payload']['vehicle']['generation'] = 'different generation'
    rebody(adapter)
    assert live(client).json()['reason'] == 'source_quality_quarantined'
    record = client.get('/v1/quarantines').json()['items'][0]
    assert 'vehicle_identity_changed' in record['reason_codes']
    assert count(database, VehicleSnapshot) == 1
    baseline = FixtureVehicleAdapter().result['payload']
    bad = deepcopy(baseline)
    bad['fitments'][0]['id'] = None
    assert 'ambiguous_alignment' in assess_vehicle_quality(baseline, bad)['reason_codes']


def test_vehicle_quarantine_listing_is_metadata_only_and_mixed_sources(setup):
    client, adapter, _ = setup
    live(client)
    remove_trim(adapter)
    live(client)
    statements = []
    database = client.app.state.database
    def capture(_connection, _cursor, statement, *_args): statements.append(statement.lower())
    event.listen(database.engine, 'before_cursor_execute', capture)
    try:
        listing = client.get('/v1/quarantines').json()
    finally:
        event.remove(database.engine, 'before_cursor_execute', capture)
    assert listing['source_ids'] == [xiaomi.SOURCE_ID]
    selected = [sql.split('from')[0] for sql in statements if sql.startswith('select') and 'vehicle_quarantines' in sql]
    assert selected and all('vehicle_quarantines.body' not in sql and 'vehicle_quarantines.payload' not in sql for sql in selected)
    assert not {'body', 'payload', 'vehicle_payload', 'candidates'} & listing['items'][0].keys()


def test_concurrent_vehicle_rejections_share_accepted_baseline(tmp_path):
    adapter = FixtureVehicleAdapter()
    app = create_app('sqlite:///' + (tmp_path / 'vehicle-quality.db').as_posix(), OfflineTireRegistry())
    register_vehicle_routes(app, adapter)
    with TestClient(app) as client:
        baseline = live(client).json()
        remove_trim(adapter)
        barrier = Barrier(2)
        def query(_):
            with TestClient(app) as other:
                barrier.wait(timeout=10)
                return live(other).json()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(query, range(2)))
        assert all(result['reason'] == 'source_quality_quarantined' for result in results)
        with app.state.database.sessions() as db:
            rows = db.scalars(select(VehicleQuarantine)).all()
            assert len(rows) == 2 and all(row.previous_snapshot_id == baseline['provenance'][0]['snapshot_id'] for row in rows)
