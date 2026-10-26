"""Independent interest edge cases; only private synthetic API/SQLite fixtures."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sql_event, func, select

from tire_api.interest_models import InterestEvent, InterestNotification
from tire_api.main import create_app
from tire_api.test_events import TireTestEvent, TireTestRevision
from test_auth_accounts import login, register
from test_core import FixtureRegistry, success
from test_test_events import PAYLOAD, create as create_event


@pytest.mark.parametrize('before,after', [
    ({'facts': {}}, {'facts': {'x': {}}}),
    ({'facts': {'x': {}}}, {'facts': {}}),
    ({'facts': {'x': {}}}, {'facts': {'x': None}}),
    ({'facts': {'x': None}}, {'facts': {'x': {}}}),
    ({'facts': {'x': []}}, {'facts': {'x': {}}}),
])
def test_review_pure_empty_objects_and_presence_are_real_changed_fields(before, after):
    from tire_api.interest_matching import changed_paths
    assert 'facts.x' in changed_paths(before, after)


def test_review_pure_before_and_after_require_independent_complete_and():
    from tire_api.interest_matching import InterestCriteria, match_event
    criteria = InterestCriteria.model_validate({'conditions': [condition('brand', 'Synthetic'),
        condition('technology', 'Acoustic')], 'metric_keys': [], 'changed_fields': []})
    event = {'domain': 'tire', 'before': {'identity': {'brand': 'Synthetic', 'acoustic_technology': 'Other'}},
             'after': {'identity': {'brand': 'Other', 'acoustic_technology': 'Acoustic'}}, 'changed_paths': []}
    assert match_event(event, criteria)['state'] != 'matched'


def test_review_pure_repeated_technology_groups_are_and_with_explicit_feature_array():
    from tire_api.interest_matching import InterestCriteria, match_event
    criteria = InterestCriteria.model_validate({'conditions': [condition('technology', 'Acoustic'),
        condition('technology', 'Foam')], 'metric_keys': [], 'changed_fields': []})
    event = {'domain': 'tire', 'before': None, 'after': {'identity': {'acoustic_technology': 'Acoustic'}}, 'changed_paths': []}
    assert match_event(event, criteria)['state'] != 'matched'
    event['after']['identity']['technology_features'] = ['Foam']
    assert match_event(event, criteria)['state'] == 'matched'


@pytest.mark.parametrize('kind,value,identity,conflict', [
    ('model', {'brand': 'Synthetic', 'model': 'Model'},
     {'brand': 'Synthetic', 'model': 'Model'}, 'brand'),
    ('technology', 'Foam', {'acoustic_technology': None, 'technology_features': ['Foam']},
     'technology_features'),
])
def test_review_pure_conflicted_dependency_cannot_prove_a_condition(kind, value, identity, conflict):
    from tire_api.interest_matching import InterestCriteria, match_event
    criteria = InterestCriteria.model_validate({'conditions': [condition(kind, value)],
                                               'metric_keys': [], 'changed_fields': []})
    event = {'domain': 'tire', 'before': None, 'after': {'identity': identity,
        'facts': {'source_field_conflicts': [{'field': conflict, 'values': ['Synthetic A', 'Synthetic B']}]}}
        , 'changed_paths': []}
    result = match_event(event, criteria)
    assert result['state'] == 'indeterminate' and 'source_field_conflict' in result['reasons']


def test_review_pure_first_observation_retains_exact_fact_path_filtering():
    from tire_api.interest_matching import InterestCriteria, changed_paths, match_event
    after = {'identity': {'brand': 'Synthetic'}, 'facts': {'utqg_treadwear': 0}}
    criteria = InterestCriteria.model_validate({'conditions': [condition('brand', 'Synthetic')],
        'metric_keys': [], 'changed_fields': ['facts.utqg_treadwear']})
    event = {'domain': 'tire', 'before': None, 'after': after, 'changed_paths': changed_paths(None, after)}
    assert match_event(event, criteria)['state'] == 'matched'


@pytest.mark.parametrize('domain,after,criterion', [
    ('test_event', {'event': deepcopy(PAYLOAD['event']), 'evidence_valid': False},
     {'kind': 'test_organization', 'values': ['Fixture Test Lab']}),
    ('vehicle', {'vehicle': {'id': 'synthetic-car'}, 'fitments': [], 'evidence_valid': False},
     {'kind': 'vehicle_fitment', 'values': [{'vehicle_id': 'synthetic-car'}]}),
    ('vehicle', {'evidence_valid': False},
     {'kind': 'vehicle_fitment', 'values': [{'vehicle_id': 'synthetic-car'}]}),
])
def test_review_pure_invalid_history_cannot_match_or_crash(domain, after, criterion):
    from tire_api.interest_matching import InterestCriteria, match_event
    criteria = InterestCriteria.model_validate({'conditions': [criterion], 'metric_keys': [], 'changed_fields': []})
    result = match_event({'domain': domain, 'before': None, 'after': after, 'changed_paths': []}, criteria)
    assert result['state'] == 'indeterminate'


@pytest.fixture
def private_api(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    for key in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(key, '0')
    registry = FixtureRegistry()
    registry.supports_parser_deployments = False
    app = create_app('sqlite:///' + (tmp_path / 'private-interest-review.sqlite').as_posix(), registry)
    app.state.review_registry = registry
    with TestClient(app) as client:
        assert register(client, username='interest-review-owner').status_code == 200
        yield client, app


def condition(kind, *values):
    return {'kind': kind, 'values': list(values)}


def interest(client, *conditions, **changes):
    payload = {'name': 'Synthetic independent review', 'enabled': True,
               'conditions': list(conditions) or [condition('test_organization', 'Fixture Test Lab')],
               'metric_keys': [], 'changed_fields': [], **changes}
    response = client.post('/v1/interests', json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def revise(client, row, **changes):
    event = {**deepcopy(row['event']), **changes}
    response = client.put('/v1/test-events/' + row['id'], json={
        'event': event, 'operator': 'Synthetic independent reviewer',
        'reason': 'Synthetic interest edge case only', 'expected_revision': row['revision']})
    assert response.status_code == 200, response.text
    return response.json()


def notices(client, **query):
    response = client.get('/v1/interest-notifications', params={'mode': 'history', **query})
    assert response.status_code == 200, response.text
    return response.json()


def update_interest(client, row, **changes):
    payload = {key: row[key] for key in ('name', 'enabled', 'conditions', 'metric_keys', 'changed_fields')}
    response = client.put('/v1/interests/' + row['id'], json={
        **payload, **changes, 'expected_revision': row['revision']})
    assert response.status_code == 200, response.text
    return response.json()


def state(client, row, action):
    response = client.post('/v1/interests/' + row['id'] + '/state', json={
        'action': action, 'expected_revision': row['revision']})
    assert response.status_code == 200, response.text
    return response.json()


def test_review_same_kind_and_groups_cannot_be_satisfied_by_different_participants(private_api):
    client, _ = private_api
    interest(client, condition('brand', 'Fixture A'), condition('brand', 'Fixture B'))
    create_event(client)
    assert notices(client)['total'] == 0


def test_review_model_and_brand_cannot_be_spliced_across_test_participants(private_api):
    client, _ = private_api
    interest(client, condition('brand', 'Fixture A'),
             condition('model', {'brand': 'Fixture B', 'model': 'Synthetic tire'}))
    create_event(client)
    assert notices(client)['total'] == 0


def test_review_before_and_after_cannot_be_spliced_to_satisfy_and(private_api):
    client, _ = private_api
    original = deepcopy(PAYLOAD)
    original['event']['participants'] = [{**person, 'brand': 'Old Brand'}
                                          for person in original['event']['participants']]
    row = create_event(client, original)
    interest(client, condition('test_organization', 'Fixture Test Lab'), condition('brand', 'New Brand'))
    revise(client, row, organization='Other Synthetic Lab',
           participants=[{**person, 'brand': 'New Brand'} for person in row['event']['participants']])
    assert notices(client)['total'] == 0


def test_review_removed_metric_is_matched_from_the_complete_before_side(private_api):
    client, _ = private_api
    row = create_event(client)
    watched = interest(client, metric_keys=['noise'], changed_fields=['event.metrics'])
    revised = revise(client, row,
        metrics=[metric for metric in row['event']['metrics'] if metric['key'] != 'noise'],
        measurements=[measurement for measurement in row['event']['measurements']
                      if measurement['metric_key'] != 'noise'])
    found = notices(client)['items']
    assert len(found) == 1 and found[0]['interest_id'] == watched['id']
    assert found[0]['event']['revision'] == revised['revision']
    assert found[0]['match']['matched_sides'] == ['before']
    assert any(metric['key'] == 'noise' for metric in found[0]['event']['before']['event']['metrics'])
    assert all(metric['key'] != 'noise' for metric in found[0]['event']['after']['event']['metrics'])


def test_review_revoke_and_restore_are_distinct_even_when_payload_hash_is_unchanged(private_api):
    client, _ = private_api
    row = create_event(client)
    interest(client, metric_keys=['noise'], changed_fields=['state'])
    revisions = []
    for action in ('revoke', 'restore'):
        response = client.post('/v1/test-events/' + row['id'] + '/state', json={
            'action': action, 'expected_revision': row['revision'],
            'operator': 'Synthetic reviewer', 'reason': 'Synthetic state edge case only'})
        assert response.status_code == 200, response.text
        row = response.json()
        revisions.append(row)
    found = notices(client)['items']
    assert len(found) == 2
    assert {item['event']['action'] for item in found} == {'revoke', 'restore'}
    assert len({item['event']['id'] for item in found}) == len({item['event']['event_hash'] for item in found}) == 2
    assert revisions[0]['fingerprint'] == revisions[1]['fingerprint']


def test_review_unselected_metric_change_does_not_notify_selected_measurements(private_api):
    client, _ = private_api
    row = create_event(client)
    interest(client, metric_keys=['noise'], changed_fields=['event.measurements'])
    measurements = deepcopy(row['event']['measurements'])
    measurements[0]['raw_value'] = '39.00'  # wet only; the selected noise record is unchanged.
    revise(client, row, measurements=measurements)
    assert notices(client)['total'] == 0


def test_review_state_event_does_not_bypass_an_unrelated_field_filter(private_api):
    client, _ = private_api
    row = create_event(client)
    interest(client, metric_keys=['noise'], changed_fields=['event.metrics'])
    response = client.post('/v1/test-events/' + row['id'] + '/state', json={
        'action': 'revoke', 'expected_revision': row['revision'],
        'operator': 'Synthetic reviewer', 'reason': 'Synthetic nonmatching field filter'})
    assert response.status_code == 200, response.text
    assert notices(client)['total'] == 0


def test_review_session_scope_applies_to_detail_update_notifications_and_read_state(private_api):
    client, app = private_api
    watched = interest(client)
    create_event(client)
    notice = notices(client)['items'][0]
    same_owner = TestClient(app)
    assert login(same_owner, 'interest-review-owner').status_code == 200
    assert same_owner.get('/v1/interests/' + watched['id'], params={'mode': 'history'}).status_code == 200
    assert notices(same_owner)['items'][0]['id'] == notice['id']
    same_response = same_owner.put('/v1/interest-notifications/' + notice['id'] + '/read', json={'read': True})
    assert same_response.status_code == 200, same_response.text
    assert notices(client, unread=True)['total'] == 0
    stranger = TestClient(app)
    assert register(stranger, username='interest-review-other').status_code == 200
    assert stranger.get('/v1/interests/' + watched['id'], params={'mode': 'history'}).status_code == 404
    assert stranger.get('/v1/interest-notifications/' + notice['id'], params={'mode': 'history'}).status_code == 404
    assert stranger.put('/v1/interest-notifications/' + notice['id'] + '/read', json={'read': False}).status_code == 404
    payload = {key: watched[key] for key in ('name', 'enabled', 'conditions', 'metric_keys', 'changed_fields')}
    assert stranger.put('/v1/interests/' + watched['id'], json={**payload, 'expected_revision': watched['revision']}).status_code == 404
    assert notices(stranger)['total'] == 0


def test_review_pause_archive_restore_and_new_revision_do_not_backfill_old_events(private_api):
    client, _ = private_api
    row = create_event(client)
    watched = interest(client, enabled=False)
    row = revise(client, row, title='Synthetic event while disabled')
    watched = update_interest(client, watched, enabled=True)
    assert notices(client)['total'] == 0
    row = revise(client, row, title='Synthetic event while enabled')
    first = notices(client)['items'][0]
    watched = state(client, watched, 'archive')
    row = revise(client, row, title='Synthetic event while archived')
    watched = state(client, watched, 'restore')
    assert watched['enabled'] is False and not watched['archived']
    watched = update_interest(client, watched, enabled=True)
    assert notices(client)['total'] == 1
    row = revise(client, row, title='Synthetic event after explicit re-enable')
    found = notices(client)['items']
    assert len(found) == 2 and first['id'] in {item['id'] for item in found}
    assert {item['interest_revision'] for item in found} == {2, watched['revision']}
    assert {item['event']['revision'] for item in found} == {3, row['revision']}


def test_review_notification_failure_rolls_back_the_original_domain_write(private_api):
    client, app = private_api
    interest(client)
    models = (TireTestEvent, TireTestRevision, InterestEvent, InterestNotification)

    def counts():
        with app.state.database.sessions() as db:
            return tuple(db.scalar(select(func.count()).select_from(model)) for model in models)

    before = counts()

    def fail_delivery(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith('insert into interest_notifications'):
            raise RuntimeError('synthetic_interest_notification_failure')

    sql_event.listen(app.state.database.engine, 'before_cursor_execute', fail_delivery)
    try:
        with pytest.raises(RuntimeError, match='synthetic_interest_notification_failure'):
            client.post('/v1/test-events', json=PAYLOAD)
    finally:
        sql_event.remove(app.state.database.engine, 'before_cursor_execute', fail_delivery)
    assert counts() == before
    create_event(client)
    assert notices(client)['total'] == 1


def test_review_preview_is_read_only_and_notification_pages_do_not_duplicate(private_api):
    client, app = private_api
    watched = interest(client)
    row = create_event(client)
    row = revise(client, row, title='Synthetic second revision')
    revise(client, row, title='Synthetic third revision')
    pages = [notices(client, limit=1, offset=offset) for offset in range(3)]
    assert all(page['total'] == 3 for page in pages)
    assert len({page['items'][0]['id'] for page in pages}) == 3
    with app.state.database.sessions() as db:
        before = db.scalar(select(func.count()).select_from(InterestNotification))
    response = client.post('/v1/interests/preview?mode=history', json={
        key: watched[key] for key in ('conditions', 'metric_keys', 'changed_fields')})
    assert response.status_code == 200, response.text
    assert response.json()['matched_count'] == 3
    with app.state.database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(InterestNotification)) == before


def test_review_reviewed_vehicle_sku_chain_delivers_later_exact_sku_fact_changes(private_api):
    """Use real source adoption hooks, not a hand-made reviewed_contexts object."""
    from tire_api.db import FactVersion
    from tire_api.vehicles import VehicleSnapshot, WheelFitment
    from test_fitment_relations import decision, post, seed_vehicle, tire_payload

    client, app = private_api
    registry = app.state.review_registry
    tire = tire_payload(acoustic_technology='Acoustic')

    def adopt(value, body, source='fixture'):
        registry.result = success(body, [value])
        response = client.post('/v1/sources/' + source + '/live-query', json={
            'query': {'model': value['model'], 'size': value['size']}, 'fallback_policy': 'never'})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['data_state'] == 'live', result
        return result

    initial = adopt(tire, 'Synthetic first source observation for reviewed fitment')
    variant_id = initial['variants'][0]['id']
    snapshot_id = initial['provenance'][0]['snapshot_id']
    session_id = client.cookies['tire_local_session']
    vehicle_snapshot_id = seed_vehicle(app.state.database, session_id)
    with app.state.database.sessions() as db:
        vehicle_snapshot = db.get(VehicleSnapshot, vehicle_snapshot_id)
        # seed_vehicle freezes the accepted raw snapshot; production adoption
        # also registers these immutable option directory rows.
        db.add_all([WheelFitment(option_id=fit['id'], trim_id=fit['trim_id'],
            snapshot_id=vehicle_snapshot.id, version=vehicle_snapshot.fact_version, specification=deepcopy(fit))
            for fit in vehicle_snapshot.payload['fitments']])
        db.commit()
        fact_id = db.scalar(select(FactVersion.id).where(FactVersion.variant_id == variant_id,
                                                       FactVersion.snapshot_id == snapshot_id))
    selection = {'vehicle_id': 'synthetic-vehicle-gen1', 'vehicle_snapshot_id': vehicle_snapshot_id,
        'trim_id': 'synthetic-trim', 'wheel_option_id': 'synthetic-option', 'axle': 'front',
        'variant_id': variant_id, 'tire_snapshot_id': snapshot_id, 'fact_version_id': fact_id}
    created = post(client, decision(client, selection))
    assert created.status_code == 201, created.text
    relation_id = created.json()['relation']['id']
    reviewed = post(client, decision(client, selection, action='review', relation_id=relation_id))
    assert reviewed.status_code == 201, reviewed.text
    watched = interest(client,
        condition('vehicle_fitment', {'vehicle_id': 'synthetic-vehicle-gen1', 'trim_id': 'synthetic-trim',
                                     'wheel_option_id': 'synthetic-option', 'axle': 'front'}),
        condition('size', '245/40R20'), condition('technology', 'Acoustic'),
        changed_fields=['facts.utqg_treadwear'])
    assert notices(client)['total'] == 0
    changed = deepcopy(tire)
    changed['facts']['utqg_treadwear'] = 420
    latest = adopt(changed, 'Synthetic later UTQG observation with exactly the same SKU identity')
    assert latest['variants'][0]['id'] == variant_id
    found = notices(client)['items']
    assert len(found) == 1, 'A reviewed exact identity relation must connect later tire facts to this vehicle interest'
    notice = found[0]
    assert notice['interest_id'] == watched['id'] and notice['event']['domain'] == 'tire'
    assert notice['event']['before']['facts']['utqg_treadwear'] == 300
    assert notice['event']['after']['facts']['utqg_treadwear'] == 420
    assert notice['event']['after']['identity']['size'] == '245/40R20'
    assert notice['event']['after']['identity']['acoustic_technology'] == 'Acoustic'
    assert notice['event']['evidence']
    # The earlier reviewed relation proves only its exact SKU/axle scope. A
    # visually identical tire with another product code must not inherit it.
    different_sku = {**deepcopy(changed), 'manufacturer_product_code': 'UNRELATED-SYNTHETIC-SKU'}
    unrelated = adopt(different_sku, 'Synthetic distinct product code with the same visible size and technology',
                      source='fixture-two')
    assert unrelated['variants'][0]['id'] != variant_id
    assert notices(client)['total'] == 1


def test_review_legacy_change_without_a_ledger_cannot_backfill_a_new_interest(private_api):
    from sqlalchemy import delete
    from tire_api.db import ChangeEvent
    from tire_api.interest_events import publish
    from tire_api.service import QueryService

    client, app = private_api
    response = client.post('/v1/sources/fixture/live-query', json={
        'query': {'model': 'Fixture Tire', 'size': '265/40ZR20'}, 'fallback_policy': 'never'})
    assert response.status_code == 200 and response.json()['data_state'] == 'live', response.text
    with app.state.database.sessions() as db:
        old_change_id = db.scalar(select(ChangeEvent.id))
        # Reconstruct a genuine pre-016 origin: its source/fact/verification
        # records exist, but no interest ledger was present when it occurred.
        db.execute(delete(InterestEvent).where(InterestEvent.origin_id == old_change_id))
        db.commit()
    interest(client, condition('brand', 'Fixture Brand'))
    with app.state.database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        publish(db, 'tire', db.get(ChangeEvent, old_change_id))
        db.commit()
    assert notices(client)['total'] == 0


def test_review_reconciliation_keeps_archived_member_and_actual_fact_versions_separate(private_api):
    from test_core import VARIANT

    client, app = private_api
    registry = app.state.review_registry

    first_query = {'size': '265/40ZR20'}
    second_query = {'model': 'Fixture Tire', 'size': '265/40ZR20'}

    def adopt(value, body, query):
        registry.result = success(body, [{**deepcopy(VARIANT),
            'facts': {'utqg_treadwear': value, 'product_code_type': 'SYNTHETIC_CODE'}}])
        response = client.post('/v1/sources/fixture/live-query', json={
            'query': query, 'fallback_policy': 'never'})
        assert response.status_code == 200 and response.json()['data_state'] == 'live', response.text
        return response.json()

    first = adopt(300, 'Synthetic frozen original source A', first_query)
    interest(client, condition('brand', 'Fixture Brand'), changed_fields=['facts.utqg_treadwear'])
    other_query = adopt(420, 'Synthetic intervening source B', second_query)
    assert other_query['variants'][0]['id'] == first['variants'][0]['id']
    registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product',
                       'etag': '"fixture-etag"'}
    response = client.post('/v1/sources/fixture/live-query', json={
        'query': first_query, 'fallback_policy': 'never'})
    assert response.status_code == 200 and response.json()['data_state'] == 'live_verified_304', response.text
    restored = response.json()
    assert restored['provenance'][0]['snapshot_id'] == first['provenance'][0]['snapshot_id']
    found = notices(client)['items']
    assert len(found) == 2
    reconciled = next(item['event'] for item in found if item['event']['revision'] == 3)
    assert reconciled['after']['evidence_valid'] is True
    assert reconciled['after']['fact_version'] == 3
    assert reconciled['after']['snapshot_member_fact_version'] == 1
    assert reconciled['before']['fact_version'] == 2
    assert reconciled['after']['facts']['utqg_treadwear'] == 300
    assert reconciled['before']['facts']['utqg_treadwear'] == 420
