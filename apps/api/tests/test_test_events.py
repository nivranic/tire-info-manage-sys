"""Synthetic event evidence, never seeded into the normal working database."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sql_event, func, select

from tire_api.db import FactVersion, Snapshot, TireVariant, Verification
from tire_api.main import create_app
from tire_api.test_events import TireTestEvent, TireTestRevision


PAYLOAD = {
    'event': {'title': 'Synthetic wet braking comparison', 'organization': 'Fixture Test Lab',
        'relationship': 'independent', 'publication_date': '2026-09-01',
        'source_url': 'https://fixture.example/test-2026', 'rights_basis': 'Project-authored synthetic data',
        'tested_size': '225/50 R17', 'vehicle': None, 'surface': 'Fixture wet asphalt',
        'conditions': 'Synthetic 80 to 20 km/h wet braking; temperature not reported',
        'coverage': 'selected_results', 'reported_participants': 20,
        'participants': [{'key': 'a', 'brand': 'Fixture A', 'model': 'Synthetic tire'},
                         {'key': 'b', 'brand': 'Fixture B', 'model': 'Synthetic tire'}],
        'metrics': [{'key': 'wet', 'label': 'Wet braking', 'unit': 'm', 'protocol': '80 to 20 km/h, wet asphalt', 'direction': 'lower'},
                    {'key': 'noise', 'label': 'Noise', 'unit': 'dB', 'protocol': 'Synthetic method; speed not reported'}],
        'measurements': [{'participant_key': 'a', 'metric_key': 'wet', 'raw_value': '38.00', 'source_rank': 3,
                          'evidence_span': 'Fixture A: 38.00 m, rank 3', 'evidence_locator': 'Synthetic table, wet row A'},
                         {'participant_key': 'b', 'metric_key': 'wet', 'raw_value': '40.0', 'source_rank': 5,
                          'evidence_span': 'Fixture B: 40.0 m, rank 5', 'evidence_locator': 'Synthetic table, wet row B'},
                         {'participant_key': 'a', 'metric_key': 'noise', 'raw_value': '70',
                          'evidence_span': 'Fixture A: 70 dB', 'evidence_locator': 'Synthetic noise row A'}]},
    'operator': 'Fixture reviewer', 'reason': 'Synthetic flow acceptance only'}


@pytest.fixture
def setup():
    app = create_app('sqlite://')
    with TestClient(app) as client:
        yield client, app.state.database


def count(database, model):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model))


def create(client, payload=None):
    response = client.post('/v1/test-events', json=payload or PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()


def compare(client, row, **changes):
    return client.post(f'/v1/test-events/{row["id"]}/compare?mode=history', json={
        'expected_revision': row['revision'], 'participant_ids': [p['id'] for p in row['participants']],
        'metric_keys': ['wet', 'noise'], **changes})


def test_event_preserves_conditions_decimal_source_rank_and_unknown_identity_without_product_facts(setup):
    client, database = setup
    row = create(client)
    assert row['event']['tested_size'] == '225/50R17'
    assert row['event']['vehicle'] is None and row['verification_status'] == 'unverified'
    assert row['record_kind'] == 'manual_transcription' and row['verified_at'] is None
    assert all(p['identity_status'] == 'participant_only' for p in row['participants'])
    response = compare(client, row)
    assert response.status_code == 200
    result = response.json()
    assert result['comparison_scope'] == 'same_event_only' and result['ranking'] == 'source_reported_only'
    assert result['measurements'][0]['raw_value'] == '38.00' and result['measurements'][0]['source_rank'] == 3
    assert not any(m['participant_key'] == 'b' and m['metric_key'] == 'noise' for m in result['measurements'])
    one = compare(client, row, participant_ids=[row['participants'][0]['id']]).json()
    assert one['measurements'][0]['source_rank'] == 3  # Never rerank the selected subset.
    assert all(count(database, model) == 0 for model in (Snapshot, TireVariant, FactVersion, Verification))
    assert client.get('/v1/test-events').status_code == 422
    listing = client.get('/v1/test-events?mode=history').json()
    assert listing['total'] == 1 and 'event' not in listing['items'][0]


def test_cross_event_participants_even_same_local_key_are_rejected(setup):
    client, _ = setup
    one, two = create(client), create(client)
    assert compare(client, one, participant_ids=[one['participants'][0]['id'], two['participants'][1]['id']]).status_code == 422
    assert compare(client, one, participant_ids=[one['participants'][0]['id']] * 2).status_code == 422
    assert compare(client, one, metric_keys=['unknown']).status_code == 422
    assert compare(client, one, event_ids=[one['id'], two['id']]).status_code == 422


@pytest.mark.parametrize('field,value', [('source_url', 'https://u:p@fixture.example/'),
    ('source_url', 'https://fixture.example/?secret=x'), ('tested_size', 'unknown'),
    ('relationship', 'automatically_verified'), ('rights_basis', ''), ('conditions', ''),
    ('publication_date', '2026-02-30'), ('reported_participants', True)])
def test_invalid_event_metadata_is_rejected(setup, field, value):
    client, database = setup
    payload = deepcopy(PAYLOAD)
    payload['event'][field] = value
    assert client.post('/v1/test-events', json=payload).status_code == 422
    assert count(database, TireTestEvent) == 0


@pytest.mark.parametrize('change', ['duplicate', 'foreign', 'nan', 'float', 'rank', 'bool_rank', 'protocol', 'citation', 'full_event', 'link_sku'])
def test_metric_and_event_graph_validation(setup, change):
    client, _ = setup
    payload = deepcopy(PAYLOAD)
    event = payload['event']; metric = event['measurements'][0]
    if change == 'duplicate': event['measurements'].append(deepcopy(metric))
    elif change == 'foreign': metric['participant_key'] = 'not_this_event'
    elif change == 'nan': metric['raw_value'] = 'NaN'
    elif change == 'float': metric['raw_value'] = 38.0
    elif change == 'rank': metric['source_rank'] = 21
    elif change == 'bool_rank': metric['source_rank'] = True
    elif change == 'protocol': event['metrics'][0]['protocol'] = ''
    elif change == 'citation': metric['evidence_span'] = ''
    elif change == 'full_event': event['coverage'] = 'full_event'
    elif change == 'link_sku': event['participants'][0]['variant_id'] = 'guessed-from-name'
    assert client.post('/v1/test-events', json=payload).status_code == 422


def test_revision_history_conflict_revoke_restore_and_immutable_records(setup):
    client, database = setup
    row = create(client)
    revised = deepcopy(PAYLOAD)
    revised['event']['measurements'][0]['raw_value'] = '38.10'
    path = f'/v1/test-events/{row["id"]}'
    response = client.put(path, json={**revised, 'expected_revision': 1})
    assert response.status_code == 200
    assert response.json()['revision'] == 2 and response.json()['fingerprint'] != row['fingerprint']
    assert compare(client, row).status_code == 409
    assert client.put(path, json={**revised, 'expected_revision': 1}).status_code == 409
    old = client.get(path + '?mode=history&revision=1').json()
    assert old['event'] == row['event'] and old['fingerprint'] == row['fingerprint']
    state_payload = {'expected_revision': 2, 'action': 'revoke', 'operator': 'Reviewer', 'reason': 'Synthetic withdrawal'}
    revoked = client.post(path + '/state', json=state_payload).json()
    assert revoked['state'] == 'revoked' and revoked['revision'] == 3
    assert compare(client, revoked).status_code == 409
    restored = client.post(path + '/state', json={**state_payload, 'expected_revision': 3, 'action': 'restore'}).json()
    expected = deepcopy(row['event'])
    expected['measurements'][0]['raw_value'] = '38.10'
    assert restored['revision'] == 4 and restored['event'] == expected
    assert compare(client, restored).status_code == 200
    with database.sessions() as db:
        item = db.scalar(select(TireTestRevision))
        db.delete(item)
        with pytest.raises(ValueError): db.commit()


def verify_event_persistence(url):
    app = create_app(url)
    with TestClient(app) as client:
        row = create(client)
    with TestClient(create_app(url)) as client:
        saved = client.get(f'/v1/test-events/{row["id"]}?mode=history').json()
        assert saved['event'] == row['event'] and saved['fingerprint'] == row['fingerprint']
    barrier = Barrier(2)
    def change(index):
        with TestClient(create_app(url)) as client:
            payload = deepcopy(PAYLOAD)
            payload['event']['title'] += str(index)
            barrier.wait(timeout=10)
            return client.put(f'/v1/test-events/{row["id"]}', json={**payload, 'expected_revision': 1}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change, range(2))) == [200, 409]


def test_restart_and_concurrent_event_revision(tmp_path):
    verify_event_persistence('sqlite:///' + (tmp_path / 'events.db').as_posix())


def test_event_list_does_not_read_measurements_or_evidence_spans(setup):
    client, database = setup
    create(client)
    statements = []
    def record(_conn, _cursor, sql, _params, _context, _many): statements.append(sql)
    sql_event.listen(database.engine, 'before_cursor_execute', record)
    try:
        assert client.get('/v1/test-events?mode=history').status_code == 200
    finally:
        sql_event.remove(database.engine, 'before_cursor_execute', record)
    assert statements and not any('test_event_revisions.payload' in sql for sql in statements)
