"""Independent R69 adversarial review, private synthetic storage and no providers.

These tests exercise public preview endpoints rather than reimplementing ranking or
matching. Synthetic writes arrange history; the previews must not add business rows.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sql_event, inspect, select, text
from sqlalchemy.orm import Session

from tire_api.db import uid, utcnow
from tire_api.domain import digest
from tire_api.interest_models import Interest, InterestEvent, InterestRevision
from tire_api.test_events import TireTestRevision
from test_auth_accounts import register
from test_fitment_relations import decision, post, seed_vehicle
from test_interest_governance_review import adopt, curation, lifecycle, seed_reviewed_chain
from test_interest_review import condition, interest, notices, private_api, state, update_interest
from test_test_events import PAYLOAD, create as create_event
from test_test_preference_routes import save_preference


FEED = '/v1/personal-feed/preview'
CANDIDATES = '/v1/fitment-candidates/preview'
SELECTION_KEYS = ('vehicle_id', 'vehicle_snapshot_id', 'trim_id', 'wheel_option_id', 'axle')


@pytest.fixture(autouse=True)
def prohibit_external_clients(monkeypatch):
    import aiohttp
    monkeypatch.setattr(aiohttp, 'ClientSession',
                        lambda *_a, **_k: pytest.fail('R69 review attempted external source/model I/O'))


def feed(client, **payload):
    return client.post(FEED + '?mode=history', json=payload)


def ok(response):
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    return response.json()


def error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()['detail']['code'] == code, response.text
    assert response.headers['cache-control'] == 'no-store'


def candidate_body(client, selected):
    preference = ok(client.get('/v1/driving-preferences'))
    return {'selection': {key: selected[key] for key in SELECTION_KEYS},
            'expected_preference_revision': preference['revision'],
            'expected_preference_fingerprint': preference['fingerprint']}


def candidates(client, selected, **changes):
    return client.post(CANDIDATES + '?mode=history',
                       json={**candidate_body(client, selected), **changes})


def business_counts(database):
    """Ignore existing auth TTL maintenance, include every other present table."""
    with database.engine.connect() as connection:
        tables = inspect(connection).get_table_names()
        return {name: connection.execute(text('SELECT COUNT(*) FROM "' + name + '"')).scalar_one()
                for name in tables if 'session' not in name.lower()}


def revision_ids(database):
    with database.sessions() as db:
        return [row.id for row in db.scalars(select(TireTestRevision))]


def freeze_clock(at):
    def assign(_session, _context, _instances):
        for row in _session.new:
            if isinstance(row, TireTestRevision):
                row.created_at = at
    return assign


def test_review_feed_replays_before_interest_merges_reasons_without_backfill(private_api):
    client, app = private_api
    original = create_event(client)
    first = interest(client, name='Synthetic first interest')
    second = interest(client, condition('brand', 'Fixture A'), name='Synthetic second interest')
    before = business_counts(app.state.database)
    result = ok(feed(client, domain='test_event'))
    assert result['scope'] == 'actor' and result['data_state'] == 'local_snapshot'
    assert result['feed_scope'] == 'current_interests_history'
    assert result['active_interest_count'] == 2
    assert result['scanned_count'] == result['matched_count'] == 1
    assert result['indeterminate_count'] == 0
    item, = result['items']
    assert item['state'] == 'matched' and item['event']['subject_id'] == original['id']
    assert {row['interest_id'] for row in item['matches']} == {first['id'], second['id']}
    for row in item['matches']:
        expected = first if row['interest_id'] == first['id'] else second
        assert row['interest_revision'] == expected['revision']
        assert row['interest_name'] == expected['name']
        assert row['interest_fingerprint'] and row['match']['state'] == 'matched'
    assert not result['has_more'] and result['next_cursor'] is None
    assert notices(client)['total'] == 0
    assert business_counts(app.state.database) == before


def test_review_feed_without_active_interest_does_not_claim_or_scan_history(private_api):
    client, _app = private_api
    create_event(client)
    watched = interest(client)
    update_interest(client, watched, enabled=False)
    result = ok(feed(client, domain='test_event', limit=1))
    assert result['active_interest_count'] == result['scanned_count'] == 0
    assert result['items'] == [] and not result['has_more'] and result['next_cursor'] is None


def test_review_empty_scan_page_keeps_cursor_until_older_match(private_api):
    client, _app = private_api
    older = create_event(client)
    other = deepcopy(PAYLOAD)
    other['event']['organization'] = 'Synthetic Unrelated Lab'
    create_event(client, other)
    interest(client)
    first = ok(feed(client, domain='test_event', limit=1))
    assert first['items'] == [] and first['scanned_count'] == 1
    assert first['matched_count'] == first['indeterminate_count'] == 0
    assert first['has_more'] and first['next_cursor']
    second = ok(feed(client, domain='test_event', limit=1, cursor=first['next_cursor']))
    assert [row['event']['subject_id'] for row in second['items']] == [older['id']]
    assert not second['has_more'] and second['next_cursor'] is None


def test_review_equal_timestamps_page_in_total_order_without_loss_or_duplicates(private_api):
    client, app = private_api
    assign = freeze_clock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    sql_event.listen(Session, 'before_flush', assign)
    try:
        for _ in range(5):
            create_event(client)
    finally:
        sql_event.remove(Session, 'before_flush', assign)
    interest(client)
    expected = [digest({'schema': 'interest-event@1', 'domain': 'test_event', 'origin_id': key})
                for key in sorted(revision_ids(app.state.database))]
    seen, cursor = [], None
    for _ in range(6):
        page = ok(feed(client, domain='test_event', limit=1, cursor=cursor))
        seen.extend(row['event']['id'] for row in page['items'])
        cursor = page['next_cursor']
        if not page['has_more']:
            break
    assert cursor is None and seen == expected and len(set(seen)) == 5


@pytest.mark.parametrize('offset', [timedelta(0), timedelta(days=-7)])
def test_review_equal_time_insert_and_late_backfill_invalidate_cursor(private_api, offset):
    client, _app = private_api
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assign = freeze_clock(at)
    sql_event.listen(Session, 'before_flush', assign)
    try:
        create_event(client)
        create_event(client)
    finally:
        sql_event.remove(Session, 'before_flush', assign)
    interest(client)
    first = ok(feed(client, domain='test_event', limit=1))
    assert first['next_cursor']
    assign = freeze_clock(at + offset)
    sql_event.listen(Session, 'before_flush', assign)
    try:
        create_event(client)
    finally:
        sql_event.remove(Session, 'before_flush', assign)
    error(feed(client, domain='test_event', limit=1, cursor=first['next_cursor']),
          409, 'personal_feed_binding_changed')


@pytest.mark.parametrize('mutation', ['name', 'criteria', 'pause', 'archive', 'add'])
def test_review_any_frozen_interest_set_or_label_change_invalidates_cursor(private_api, mutation):
    client, _app = private_api
    create_event(client)
    create_event(client)
    watched = interest(client)
    first = ok(feed(client, domain='test_event', limit=1))
    if mutation == 'name':
        update_interest(client, watched, name='Synthetic renamed interest')
    elif mutation == 'criteria':
        update_interest(client, watched, conditions=[condition('brand', 'Fixture A')])
    elif mutation == 'pause':
        update_interest(client, watched, enabled=False)
    elif mutation == 'archive':
        state(client, watched, mutation)
    else:
        interest(client, name='Synthetic additional equal criteria')
    error(feed(client, domain='test_event', limit=1, cursor=first['next_cursor']),
          409, 'personal_feed_binding_changed')


def test_review_cursor_cannot_cross_actor_or_be_tampered(private_api):
    client, app = private_api
    create_event(client)
    create_event(client)
    interest(client)
    first = ok(feed(client, domain='test_event', limit=1))
    token = first['next_cursor']
    corrupted = ('A' if token[0] != 'A' else 'B') + token[1:]
    error(feed(client, domain='test_event', limit=1, cursor=corrupted),
          400, 'personal_feed_cursor_invalid')
    with TestClient(app) as other:
        assert register(other, username='personalization-review-other').status_code == 200
        interest(other)
        response = feed(other, domain='test_event', limit=1, cursor=token)
        error(response, 400, 'personal_feed_cursor_invalid')
        assert client.cookies['tire_local_session'] not in response.text


@pytest.mark.parametrize('changes', [{'domain': 'tire'}, {'limit': 2}])
def test_review_cursor_binds_domain_and_scan_budget(private_api, changes):
    client, _app = private_api
    create_event(client)
    create_event(client)
    interest(client)
    first = ok(feed(client, domain='test_event', limit=1))
    response = feed(client, **{'domain': 'test_event', 'limit': 1,
                              'cursor': first['next_cursor'], **changes})
    assert response.status_code in (400, 409), response.text


@pytest.mark.parametrize('payload', [
    {'limit': 0}, {'limit': -1}, {'limit': 51}, {'limit': True}, {'limit': 1.0}, {'limit': '1'},
    {'domain': 'unknown'}, {'domain': []}, {'cursor': 'x' * 4097},
    {'actor': 'another'}, {'conditions': []}, {'weights': {}},
])
def test_review_feed_rejects_coercions_overrides_and_unbounded_cursor(private_api, payload):
    client, _app = private_api
    assert feed(client, **payload).status_code == 422


@pytest.mark.parametrize('path', [FEED, CANDIDATES])
@pytest.mark.parametrize('query', ['', '?mode=live'])
def test_review_preview_requires_explicit_history_mode(private_api, path, query):
    client, _app = private_api
    assert client.post(path + query, json={}).status_code == 422


@pytest.mark.parametrize('corruption', ['payload', 'payload_hash', 'row_hash', 'row_id'])
def test_review_corrupt_stored_event_never_becomes_a_matched_fact(private_api, corruption):
    client, app = private_api
    create_event(client)
    interest(client)
    with app.state.database.sessions() as db:
        stored = db.scalar(select(InterestEvent).where(InterestEvent.domain == 'test_event'))
        key, payload = stored.id, deepcopy(stored.payload)
    values = {}
    if corruption == 'payload':
        payload['after']['event']['title'] = 'Synthetic corrupted stored history'
        values['payload'] = json.dumps(payload)
    elif corruption == 'payload_hash':
        payload['event_hash'] = 'f' * 64
        values['payload'] = json.dumps(payload)
    elif corruption == 'row_hash':
        values['event_hash'] = 'e' * 64
    else:
        values['id'] = 'synthetic-wrong-event-id'
    with app.state.database.engine.begin() as connection:
        for field, value in values.items():
            connection.execute(text('UPDATE interest_events SET ' + field + '=:value WHERE id=:key'),
                               {'value': value, 'key': key})
    response = feed(client, domain='test_event')
    if response.status_code == 200:
        assert all(row['state'] != 'matched' for row in response.json()['items']), response.text
    else:
        assert response.status_code == 409, response.text


def test_review_candidate_is_exact_reviewed_actor_context_with_explicit_performance_gap(private_api):
    client, app = private_api
    source, selected, relation_id = seed_reviewed_chain(client, app)
    # Same name and size is deliberately insufficient to connect a TestEvent to the SKU.
    payload = deepcopy(PAYLOAD)
    payload['event']['tested_size'] = source['size']
    for participant in payload['event']['participants']:
        participant.update(brand=source['brand'], model=source['model'])
    original = create_event(client, payload)
    preference = save_preference(client)
    before = business_counts(app.state.database)
    result = ok(candidates(client, selected))
    assert result['scope'] == 'actor' and result['evidence_scope'] == 'local_workspace'
    assert result['preference']['revision'] == preference['revision']
    assert result['preference']['fingerprint'] == preference['fingerprint']
    assert result['ranking'] == 'not_computed' and result['performance_score'] is None
    assert result['official_oe']['state'] == 'not_established'
    item, = result['items']
    assert item['variant_id'] == selected['variant_id']
    assert item['performance_score'] is None and item['ranking'] == 'not_computed'
    assert item['official_oe']['state'] == 'not_established'
    assert {row['relation_id'] for row in item['relations']} == {relation_id}
    relation = item['relations'][0]
    assert relation['selection'] == selected and relation['binding_hash']
    assert relation['vehicle_evidence'] and relation['tire_evidence'] and relation['evidence']
    assert {row['dimension'] for row in result['research_focus']} == set(preference['weights'])
    assert all(row['evidence_status'] == 'exact_sku_performance_not_established'
               for row in result['research_focus'])
    assert business_counts(app.state.database) == before
    reopened = ok(client.get('/v1/test-events/' + original['id'] + '?mode=history'))
    assert reopened['event']['measurements'][0]['raw_value'] == '38.00'
    assert reopened['event']['measurements'][0]['source_rank'] == 3
    assert all(row['identity_status'] == 'participant_only' for row in reopened['participants'])


def test_review_missing_preference_is_valid_unknown_context_without_default_weights(private_api):
    client, app = private_api
    _source, selected, _rid = seed_reviewed_chain(client, app)
    result = ok(candidates(client, selected))
    assert result['preference']['weights'] is None
    assert len(result['research_focus']) == 7
    assert all(row['weight'] is None for row in result['research_focus'])
    assert result['performance_score'] is None


@pytest.mark.parametrize('field,value', [
    ('expected_preference_revision', 999), ('expected_preference_fingerprint', 'f' * 64),
])
def test_review_candidate_binds_both_preference_revision_and_fingerprint(private_api, field, value):
    client, app = private_api
    _source, selected, _rid = seed_reviewed_chain(client, app)
    save_preference(client)
    error(candidates(client, selected, **{field: value}), 409, 'fitment_candidate_preference_changed')


def test_review_changed_or_cleared_preference_rejects_old_candidate_request(private_api):
    client, app = private_api
    _source, selected, _rid = seed_reviewed_chain(client, app)
    saved = save_preference(client)
    old = candidate_body(client, selected)
    cleared = client.post('/v1/driving-preferences/clear', json={'expected_revision': saved['revision']})
    assert cleared.status_code == 200, cleared.text
    error(client.post(CANDIDATES + '?mode=history', json=old), 409, 'fitment_candidate_preference_changed')


def test_review_candidate_does_not_guess_an_unreviewed_same_name_size_sku(private_api):
    client, app = private_api
    source, selected, _rid = seed_reviewed_chain(client, app)
    unrelated = deepcopy(source)
    unrelated['manufacturer_product_code'] = 'SYNTHETIC-OTHER-PRODUCT'
    unrelated['oe_mark'] = 'OTHER-OE'
    accepted = adopt(client, app, [source, unrelated], 'Synthetic same-name different exact SKU')
    assert len({row['id'] for row in accepted['variants']}) == 2
    result = ok(candidates(client, selected))
    assert [row['variant_id'] for row in result['items']] == [selected['variant_id']]


def test_review_front_review_never_qualifies_rear_or_other_generation(private_api):
    client, app = private_api
    _source, selected, _rid = seed_reviewed_chain(client, app)
    rear = ok(candidates(client, {**selected, 'axle': 'rear'}))
    assert rear['items'] == []
    response = candidates(client, {**selected, 'vehicle_id': 'synthetic-vehicle-gen2'})
    assert response.status_code in (409, 422), response.text


def test_review_relation_restore_returns_pending_and_does_not_revive_old_review(private_api):
    client, app = private_api
    _source, selected, rid = seed_reviewed_chain(client, app)
    revoked = post(client, decision(client, selected, 'revoke', rid))
    assert revoked.status_code == 201, revoked.text
    restored = post(client, decision(client, selected, 'restore', rid))
    assert restored.status_code == 201, restored.text
    result = ok(candidates(client, selected))
    assert result['items'] == []
    assert {row['relation_id'] for row in result['excluded_relations']} == {rid}


def test_review_lifecycle_restore_does_not_revive_prior_reviewed_relation(private_api):
    client, app = private_api
    _source, selected, rid = seed_reviewed_chain(client, app)
    evidence = [selected['tire_snapshot_id']]
    revoked = lifecycle(client, selected['variant_id'], evidence)
    assert revoked.status_code == 201, revoked.text
    restored = lifecycle(client, selected['variant_id'], evidence, action='restore', revision=1)
    assert restored.status_code == 201, restored.text
    result = ok(candidates(client, selected))
    assert result['items'] == []
    assert any(row['relation_id'] == rid and row['reason_codes'] for row in result['excluded_relations'])


@pytest.mark.parametrize('corruption', ['raw_body', 'binding_hash'])
def test_review_candidate_excludes_corrupt_original_or_relation_binding(private_api, corruption):
    client, app = private_api
    _source, selected, rid = seed_reviewed_chain(client, app)
    with app.state.database.engine.begin() as connection:
        if corruption == 'raw_body':
            connection.execute(text('UPDATE snapshots SET body=:body WHERE id=:key'),
                               {'body': 'Synthetic corrupted original', 'key': selected['tire_snapshot_id']})
        else:
            connection.execute(text('UPDATE fitment_relation_revisions SET binding_hash=:value '
                                    'WHERE relation_id=:key AND review_state=:state'),
                               {'value': 'f' * 64, 'key': rid, 'state': 'reviewed'})
    before = business_counts(app.state.database)
    result = ok(candidates(client, selected))
    assert result['items'] == []
    assert any(row['relation_id'] == rid and row['reason_codes'] for row in result['excluded_relations'])
    assert business_counts(app.state.database) == before


def test_review_both_previews_leave_all_business_row_counts_unchanged(private_api):
    client, app = private_api
    _source, selected, _rid = seed_reviewed_chain(client, app)
    create_event(client)
    interest(client)
    body = candidate_body(client, selected)
    before = business_counts(app.state.database)
    for _ in range(2):
        ok(feed(client, limit=1))
        ok(client.post(CANDIDATES + '?mode=history', json=body))
    assert business_counts(app.state.database) == before


def test_review_all_nine_declared_domains_are_replayable_without_notification_backfill(private_api):
    from test_identity_resolution import decision as identity_decision, post as identity_post
    from tire_api.vehicles import VehicleSnapshot, VehicleVerification
    client, app = private_api
    source, selected, _rid = seed_reviewed_chain(client, app)
    # The reused direct seed helper calls utcnow twice. Arrange one synthetic
    # accepted observation, as a producer would, rather than a later verification.
    with app.state.database.sessions() as db:
        at = db.get(VehicleSnapshot, selected['vehicle_snapshot_id']).observed_at
    with app.state.database.engine.begin() as connection:
        connection.execute(VehicleVerification.__table__.update().where(
            VehicleVerification.snapshot_id == selected['vehicle_snapshot_id']).values(verified_at=at))
    assert curation(client, selected['variant_id']).status_code == 201
    changed = deepcopy(source)
    changed['facts']['utqg_treadwear'] = 310
    adopt(client, app, [changed], 'Synthetic source update invalidates manual applicability')
    evidence = [selected['tire_snapshot_id']]
    assert lifecycle(client, selected['variant_id'], evidence).status_code == 201
    assert lifecycle(client, selected['variant_id'], evidence, action='restore', revision=1).status_code == 201
    target = deepcopy(changed)
    target['manufacturer_product_code'] = 'SYNTHETIC-IDENTITY-TARGET'
    observed = adopt(client, app, [changed, target], 'Synthetic identity source pair')
    target_id = next(row['id'] for row in observed['variants'] if row['id'] != selected['variant_id'])
    snapshots = [selected['tire_snapshot_id'], observed['provenance'][0]['snapshot_id']]
    corrected = identity_post(client, selected['variant_id'], identity_decision(
        client, selected['variant_id'], target_id, snapshots))
    assert corrected.status_code == 201, corrected.text
    payload = deepcopy(PAYLOAD)
    for participant in payload['event']['participants']:
        participant['brand'] = 'Synthetic'
    create_event(client, payload)
    interest(client, condition('brand', 'Synthetic'))
    interest(client, condition('vehicle_fitment', {'vehicle_id': selected['vehicle_id']}))
    before = business_counts(app.state.database)
    result = ok(feed(client, limit=50))
    assert not result['has_more']
    assert {row['event']['domain'] for row in result['items'] if row['state'] == 'matched'} == {
        'tire', 'test_event', 'vehicle', 'fitment', 'tire_curation', 'tire_lifecycle',
        'tire_identity', 'tire_catalog', 'tire_curation_validity'}
    assert notices(client)['total'] == 0
    assert business_counts(app.state.database) == before


def test_review_over_one_hundred_active_interests_is_explicit_capacity_failure(private_api):
    client, app = private_api
    watched = interest(client)
    with app.state.database.sessions() as db:
        owner = db.get(Interest, watched['id']).session_id
        for number in range(100):
            row = Interest(id=uid(), session_id=owner)
            db.add(row)
            db.flush()
            data = {key: deepcopy(watched[key])
                    for key in ('name', 'enabled', 'conditions', 'metric_keys', 'changed_fields')}
            data['name'] = 'Synthetic capacity interest ' + str(number)
            db.add(InterestRevision(interest_id=row.id, revision=1, **data, archived=False,
                fingerprint=digest({**data, 'archived': False}), actor_session_id=owner))
        db.commit()
    before = business_counts(app.state.database)
    error(feed(client), 409, 'personal_feed_capacity_exceeded')
    assert business_counts(app.state.database) == before


def test_review_invalid_original_test_history_remains_indeterminate_and_is_not_repaired(private_api):
    client, app = private_api
    create_event(client)
    interest(client)
    with app.state.database.engine.begin() as connection:
        connection.execute(text("DELETE FROM interest_events WHERE domain='test_event'"))
        connection.execute(text('UPDATE test_event_revisions SET fingerprint=:value'), {'value': 'f' * 64})
    before = business_counts(app.state.database)
    result = ok(feed(client, domain='test_event'))
    assert result['matched_count'] == 0 and result['indeterminate_count'] == 1
    assert result['items'][0]['state'] == 'indeterminate'
    assert result['items'][0]['event']['after']['evidence_valid'] is False
    assert business_counts(app.state.database) == before


@pytest.mark.parametrize('field,value', [
    ('expected_preference_revision', True), ('expected_preference_revision', -1),
    ('expected_preference_revision', 1.0), ('expected_preference_fingerprint', 'z' * 64),
    ('actor', 'another'), ('weights', {}), ('variant_id', 'guessed-sku'),
])
def test_review_candidate_rejects_binding_coercion_and_personal_overrides(private_api, field, value):
    client, app = private_api
    _source, selected, _rid = seed_reviewed_chain(client, app)
    assert candidates(client, selected, **{field: value}).status_code == 422


def test_review_same_sku_multiple_reviewed_relations_preserve_each_evidence_chain(private_api):
    client, app = private_api
    _source, selected, first_id = seed_reviewed_chain(client, app)
    created = post(client, decision(client, selected))
    assert created.status_code == 201, created.text
    second_id = created.json()['relation']['id']
    assert second_id != first_id
    reviewed = post(client, decision(client, selected, 'review', second_id))
    assert reviewed.status_code == 201, reviewed.text
    result = ok(candidates(client, selected))
    item, = result['items']
    assert {row['relation_id'] for row in item['relations']} == {first_id, second_id}
    assert result['relation_count'] == 2 and not result['truncated']


def test_review_identity_clear_does_not_revive_old_relation_or_replace_exact_sku(private_api):
    from test_identity_resolution import decision as identity_decision, post as identity_post
    client, app = private_api
    source, selected, rid = seed_reviewed_chain(client, app)
    target = deepcopy(source)
    target['manufacturer_product_code'] = 'SYNTHETIC-OTHER-EXACT-SKU'
    observed = adopt(client, app, [source, target], 'Synthetic exact identity alternatives')
    target_id = next(row['id'] for row in observed['variants'] if row['id'] != selected['variant_id'])
    snapshots = [selected['tire_snapshot_id'], observed['provenance'][0]['snapshot_id']]
    corrected = identity_post(client, selected['variant_id'], identity_decision(
        client, selected['variant_id'], target_id, snapshots))
    assert corrected.status_code == 201, corrected.text
    cleared = identity_post(client, selected['variant_id'], identity_decision(
        client, selected['variant_id'], None, snapshots, action='clear'))
    assert cleared.status_code == 201, cleared.text
    result = ok(candidates(client, selected))
    assert result['items'] == []
    assert any(row['relation_id'] == rid and row['reason_codes'] for row in result['excluded_relations'])


@pytest.mark.parametrize('part,field,value', [
    ('tire_evidence', 'facts', {'utqg_treadwear': 999999}),
    ('tire_evidence', 'structured_locator', {'snapshot_id': 'synthetic-wrong-snapshot',
                                          'json_pointer': '/parsed_variants/999'}),
    ('vehicle_evidence', 'vehicle', {'id': 'synthetic-other-generation', 'generation': 'generation-99'}),
])
def test_review_candidate_does_not_publish_corrupt_frozen_detail_with_valid_hash_labels(
        private_api, part, field, value):
    client, app = private_api
    _source, selected, rid = seed_reviewed_chain(client, app)
    with app.state.database.sessions() as db:
        from tire_api.fitment_relation_models import FitmentRelationRevision
        row = db.scalar(select(FitmentRelationRevision).where(
            FitmentRelationRevision.relation_id == rid, FitmentRelationRevision.review_state == 'reviewed'))
        tampered = deepcopy(getattr(row, part))
        tampered[field] = value
        revision_id = row.id
    with app.state.database.engine.begin() as connection:
        connection.execute(text('UPDATE fitment_relation_revisions SET ' + part + '=:value WHERE id=:key'),
                           {'value': json.dumps(tampered), 'key': revision_id})
    result = ok(candidates(client, selected))
    assert result['items'] == [], 'Corrupted frozen detail must not pass using unchanged hash labels'
    assert any(row['relation_id'] == rid and row['reason_codes'] for row in result['excluded_relations'])


def test_review_same_fact_metadata_snapshot_keeps_old_review_evidence_exact(private_api):
    from tire_api.vehicles import VehicleSnapshot
    client, app = private_api
    _source, selected, rid = seed_reviewed_chain(client, app)
    before = ok(candidates(client, selected))
    with app.state.database.sessions() as db:
        original = db.get(VehicleSnapshot, selected['vehicle_snapshot_id'])
        payload, version = deepcopy(original.payload), original.fact_version
    newer = seed_vehicle(app.state.database, client.cookies['tire_local_session'], payload,
                         fact_version=version, observed_at=utcnow() + timedelta(seconds=1))
    result = ok(candidates(client, {**selected, 'vehicle_snapshot_id': newer}))
    item, = result['items']
    assert item['variant_id'] == selected['variant_id']
    relation, = item['relations']
    assert relation['relation_id'] == rid
    assert relation['selection']['vehicle_snapshot_id'] == selected['vehicle_snapshot_id']
    assert relation['vehicle_evidence'] == before['items'][0]['relations'][0]['vehicle_evidence']
    assert result['vehicle_binding']['current_snapshot_id'] == newer


def test_review_expired_cursor_is_binding_change_and_does_not_slide_its_ttl(private_api, monkeypatch):
    import tire_api.personalized_feed as implementation
    client, _app = private_api
    create_event(client)
    create_event(client)
    interest(client)
    first = ok(feed(client, domain='test_event', limit=1))
    old_time = implementation.time.time
    monkeypatch.setattr(implementation.time, 'time', lambda: old_time() + 3601)
    error(feed(client, domain='test_event', limit=1, cursor=first['next_cursor']),
          409, 'personal_feed_binding_changed')


@pytest.mark.parametrize('mutation', ['interest', 'history'])
def test_review_feed_rechecks_binding_after_read_instead_of_returning_mixed_page(private_api, monkeypatch, mutation):
    import tire_api.personalized_feed as implementation
    client, _app = private_api
    create_event(client)
    watched = interest(client)
    original_match = implementation.match_event
    changed = False
    def match_then_append(event, criteria):
        nonlocal changed
        result = original_match(event, criteria)
        if not changed:
            changed = True
            if mutation == 'interest':
                update_interest(client, watched, name='Synthetic read-time interest change')
            else:
                create_event(client)
        return result
    monkeypatch.setattr(implementation, 'match_event', match_then_append)
    error(feed(client, domain='test_event'), 409, 'personal_feed_binding_changed')
    assert changed


def test_review_candidate_rechecks_preference_after_evidence_read(private_api, monkeypatch):
    import tire_api.recommendation_candidates as implementation
    client, app = private_api
    _source, selected, _rid = seed_reviewed_chain(client, app)
    saved = save_preference(client)
    original_checks = implementation.technical_checks
    changed = False
    def check_then_change(vehicle, tire):
        nonlocal changed
        result = original_checks(vehicle, tire)
        if not changed:
            changed = True
            weights = {**saved['weights'], 'dry': 25, 'wet': 20}
            save_preference(client, saved['revision'], weights)
        return result
    monkeypatch.setattr(implementation, 'technical_checks', check_then_change)
    error(candidates(client, selected), 409, 'fitment_candidate_preference_changed')
    assert changed


def test_review_catalog_removal_and_reentry_do_not_restore_prior_relation_review(private_api):
    client, app = private_api
    source, selected, rid = seed_reviewed_chain(client, app)
    background = [{**deepcopy(source), 'manufacturer_product_code': 'SYNTHETIC-CATALOG-' + str(index)}
                  for index in range(3)]
    # Preserve the existing source-quality gate: remove one of four members,
    # rather than replacing the entire one-member source by an unrelated SKU.
    adopt(client, app, [source, *background], 'Synthetic complete four-member source catalog')
    adopt(client, app, background, 'Synthetic original SKU absent from source catalog')
    adopt(client, app, [source, *background], 'Synthetic original SKU reenters source catalog')
    result = ok(candidates(client, selected))
    assert result['items'] == []
    assert any(row['relation_id'] == rid and row['reason_codes'] for row in result['excluded_relations'])


def test_review_over_two_hundred_relations_is_explicitly_truncated(private_api):
    from tire_api.fitment_relation_models import FitmentRelation, FitmentRelationRevision
    client, app = private_api
    _source, selected, rid = seed_reviewed_chain(client, app)
    with app.state.database.sessions() as db:
        relation = db.get(FitmentRelation, rid)
        head = db.scalar(select(FitmentRelationRevision).where(
            FitmentRelationRevision.relation_id == rid, FitmentRelationRevision.review_state == 'reviewed'))
        relation_data = {column.name: deepcopy(getattr(relation, column.name))
                         for column in FitmentRelation.__table__.columns}
        revision_data = {column.name: deepcopy(getattr(head, column.name))
                         for column in FitmentRelationRevision.__table__.columns}
    relations, revisions = [], []
    for _ in range(200):
        relation_id = uid()
        relations.append({**deepcopy(relation_data), 'id': relation_id})
        revisions.append({**deepcopy(revision_data), 'id': uid(), 'relation_id': relation_id,
                          'idempotency_key': uid()})
    with app.state.database.engine.begin() as connection:
        connection.execute(FitmentRelation.__table__.insert(), relations)
        connection.execute(FitmentRelationRevision.__table__.insert(), revisions)
    before = business_counts(app.state.database)
    result = ok(candidates(client, selected))
    assert result['truncated'] and result['relation_count'] == 201 and result['inspected_count'] == 200
    assert len(result['items']) == 1 and len(result['items'][0]['relations']) == 200
    assert business_counts(app.state.database) == before


def test_review_shared_relation_never_copies_another_actors_preference(private_api):
    client, app = private_api
    _source, selected, _rid = seed_reviewed_chain(client, app)
    save_preference(client)
    foreign_body = candidate_body(client, selected)
    with TestClient(app) as other:
        assert register(other, username='personalization-candidate-other').status_code == 200
        error(other.post(CANDIDATES + '?mode=history', json=foreign_body),
              409, 'fitment_candidate_preference_changed')
        own = ok(candidates(other, selected))
        assert own['preference']['weights'] is None
        assert len(own['items']) == 1  # Existing relations are explicitly shared local evidence.
        assert client.cookies['tire_local_session'] not in json.dumps(own)
