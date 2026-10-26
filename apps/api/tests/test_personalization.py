"""Actor projections over synthetic, GUID-isolated local evidence only."""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, select, text

from test_core import VARIANT, success
from test_interest_events import producer, adopt
from test_fitment_relations import relation_setup, decision, post, seed_tire, tire_payload
from tire_api.db import Snapshot
from tire_api.interest_models import InterestEvent


def interest(client, name='Synthetic current interest', brand='Fixture Brand'):
    response = client.post('/v1/interests', json={'name': name, 'enabled': True,
        'conditions': [{'kind': 'brand', 'values': [brand]}], 'metric_keys': [], 'changed_fields': []})
    assert response.status_code == 201, response.text
    return response.json()


def feed(client, **changes):
    return client.post('/v1/personal-feed/preview?mode=history', json=changes)


def candidate_request(client, selection):
    preference = client.get('/v1/driving-preferences').json()
    return {'selection': {key: selection[key] for key in
            ('vehicle_id', 'vehicle_snapshot_id', 'trim_id', 'wheel_option_id', 'axle')},
        'expected_preference_revision': preference['revision'],
        'expected_preference_fingerprint': preference['fingerprint']}


def candidates(client, payload):
    return client.post('/v1/fitment-candidates/preview?mode=history', json=payload)


def test_feed_matches_history_before_interest_and_merges_independent_reasons_without_writes(producer):
    client, registry, database = producer
    adopt(client)
    first = interest(client)
    second = interest(client, 'Another explicit interest')
    before = client.get('/v1/interest-notifications?mode=history').json()
    writes = []
    def record(_conn, _cursor, sql, _params, _context, _many):
        if sql.lstrip().lower().startswith(('insert ', 'update ', 'delete ', 'begin immediate')):
            writes.append(sql)
    event.listen(database.engine, 'before_cursor_execute', record)
    try:
        response = feed(client, domain='tire')
    finally:
        event.remove(database.engine, 'before_cursor_execute', record)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['feed_scope'] == 'current_interests_history' and body['active_interest_count'] == 2
    assert body['matched_count'] == 1 and body['scanned_count'] == 1
    assert len(body['items']) == 1 and body['items'][0]['state'] == 'matched'
    assert {m['interest_id'] for m in body['items'][0]['matches']} == {first['id'], second['id']}
    assert body['items'][0]['event']['after']['evidence_valid'] is True
    assert response.headers['cache-control'] == 'no-store'
    assert writes == [] and len(registry.calls) == 1
    assert client.get('/v1/interest-notifications?mode=history').json() == before


def test_feed_empty_page_advances_and_signed_cursor_rejects_other_actor_and_new_members(producer):
    client, registry, _ = producer
    adopt(client)
    registry.result = success('Synthetic newer nonmatching event', [{**deepcopy(VARIANT),
        'brand': 'Other brand', 'manufacturer_product_code': 'FIX-OTHER'}])
    accepted = client.post('/v1/sources/fixture-two/live-query', json={
        'query': {'size': '265/40R20'}, 'fallback_policy': 'never'})
    assert accepted.status_code == 200 and accepted.json()['data_state'] == 'live'
    interest(client)
    first = feed(client, domain='tire', limit=1)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body['items'] == [] and body['scanned_count'] == 1 and body['has_more']
    cursor = body['next_cursor']
    second = feed(client, domain='tire', limit=1, cursor=cursor)
    assert second.status_code == 200 and second.json()['matched_count'] == 1
    stranger = TestClient(client.app)
    stranger.get('/health')
    denied = feed(stranger, domain='tire', limit=1, cursor=cursor)
    assert denied.status_code == 400 and denied.json()['detail']['code'] == 'personal_feed_cursor_invalid'
    tampered = feed(client, domain='tire', limit=1, cursor=cursor[:-1] + ('A' if cursor[-1] != 'A' else 'B'))
    assert tampered.status_code == 400
    registry.result = success('Synthetic third event', [{**deepcopy(VARIANT), 'facts': {'utqg_treadwear': 440}}])
    adopt(client)
    changed = feed(client, domain='tire', limit=1, cursor=cursor)
    assert changed.status_code == 409 and changed.json()['detail']['code'] == 'personal_feed_binding_changed'


def test_feed_no_interest_has_no_scan_and_shape_is_strict(producer):
    client, _, _ = producer
    adopt(client)
    response = feed(client)
    assert response.status_code == 200, response.text
    assert response.json()['scanned_count'] == response.json()['active_interest_count'] == 0
    for body in ({'limit': True}, {'limit': 1.0}, {'limit': 51}, {'actor': 'someone'}, {'domain': 'unknown'}):
        assert feed(client, **body).status_code == 422
    assert client.post('/v1/personal-feed/preview', json={}).status_code == 422


def test_feed_rejects_corrupt_stored_event_instead_of_matching_it(producer):
    client, _, database = producer
    adopt(client)
    interest(client)
    with database.engine.begin() as connection:
        identifier = connection.execute(select(InterestEvent.id).where(InterestEvent.domain == 'tire')).scalar_one()
        connection.execute(text('UPDATE interest_events SET event_hash = :bad WHERE id = :id'),
                           {'bad': '0' * 64, 'id': identifier})
    response = feed(client, domain='tire')
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'personal_feed_evidence_unavailable'


def test_candidates_require_review_and_keep_exact_revision_and_unknowns_without_scores(relation_setup):
    client, database, _, selected = relation_setup
    created = post(client, decision(client, selected)).json()['relation']
    payload = candidate_request(client, selected)
    pending = candidates(client, payload)
    assert pending.status_code == 200, pending.text
    assert pending.json()['items'] == [] and pending.json()['excluded_relations'][0]['reason_codes']
    reviewed = post(client, decision(client, selected, 'review', created['id'])).json()['relation']
    response = candidates(client, payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['relation_count'] == body['inspected_count'] == 1 and not body['truncated']
    item = body['items'][0]
    assert item['variant_id'] == selected['variant_id'] and item['performance_score'] is None
    assert item['ranking'] == 'not_computed' and item['official_oe']['state'] == 'not_established'
    relation = item['relations'][0]
    assert relation['relation_id'] == reviewed['id'] and relation['revision'] == 2
    assert relation['revision_id'] and relation['binding_hash'] and relation['evidence']
    assert 'load_index' in relation['unknown_fields'] and relation['acknowledged_unknowns']
    assert body['preference']['weights'] is None
    assert all(row['weight'] is None and row['evidence_status'] == 'exact_sku_performance_not_established'
               for row in body['research_focus'])
    assert response.headers['cache-control'] == 'no-store'
    # A new exact fact invalidates the reviewed binding; size equality cannot retain it.
    seed_tire(database, client.cookies['tire_local_session'], tire_payload(facts={'utqg_treadwear': 400}),
              variant_id=selected['variant_id'], version=2)
    stale = candidates(client, payload).json()
    assert stale['items'] == [] and stale['excluded_relations'][0]['effective_state'] == 'needs_review'


def test_candidates_reject_damaged_raw_and_preference_override_or_stale_binding(relation_setup):
    client, database, _, selected = relation_setup
    rid = post(client, decision(client, selected)).json()['relation']['id']
    post(client, decision(client, selected, 'review', rid))
    payload = candidate_request(client, selected)
    assert candidates(client, {**payload, 'expected_preference_fingerprint': '0' * 64}).status_code == 409
    assert candidates(client, {**payload, 'weights': {'wet': 100}}).status_code == 422
    with database.engine.begin() as connection:
        connection.execute(text('UPDATE snapshots SET body = :body WHERE id = :id'),
                           {'body': 'Synthetic corrupted bytes', 'id': selected['tire_snapshot_id']})
    response = candidates(client, payload)
    assert response.status_code == 200, response.text
    assert response.json()['items'] == []
    assert 'relation_evidence_invalid' in response.json()['excluded_relations'][0]['reason_codes']
