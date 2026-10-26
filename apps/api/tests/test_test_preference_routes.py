"""Private temporary SQLite API checks for actor-owned, read-only explanations."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sql_event, func, select

from tire_api.db import AuditEvent, DrivingPreferenceRevision, FactVersion, Snapshot, TireVariant, Verification
from tire_api.domain import digest
from tire_api.main import create_app
from tire_api.test_events import TireTestEvent, TireTestRevision
from test_auth_accounts import login, register
from test_core import FixtureRegistry
from test_research import WEIGHTS
from test_test_events import PAYLOAD, compare, create


@pytest.fixture
def setup(tmp_path):
    registry = FixtureRegistry()
    app = create_app('sqlite:///' + (tmp_path / 'preference-routes.sqlite').as_posix(), registry)
    with TestClient(app) as client:
        yield client, app, registry


def preference_fingerprint(state):
    return digest({'schema': 'driving-preference-state@1', 'revision': state['revision'], 'weights': state['weights']})


def save_preference(client, revision=0, weights=None):
    response = client.put('/v1/driving-preferences', json={
        'expected_revision': revision, 'weights': WEIGHTS if weights is None else weights})
    assert response.status_code == 200, response.text
    return response.json()


def request_body(row, preference):
    return {
        'expected_event_revision': row['revision'],
        'expected_event_fingerprint': row['fingerprint'],
        'expected_preference_revision': max(1, preference['revision']),
        'expected_preference_fingerprint': preference_fingerprint(preference),
        'participant_ids': [p['id'] for p in row['participants']],
        'metric_dimensions': [{'metric_key': 'wet', 'dimension': 'wet'}, {'metric_key': 'noise', 'dimension': 'quiet'}],
    }


def interpret(client, row, preference, **changes):
    return client.post(f'/v1/test-events/{row["id"]}/preference-interpretation?mode=history',
                       json={**request_body(row, preference), **changes})


def assert_error(response, status, code, *, framework=False):
    assert response.status_code == status, response.text
    detail = response.json()['detail']
    assert detail['code'] == code and isinstance(detail['message'], str)
    assert set(detail) == ({'code', 'message', 'errors'} if framework else {'code', 'message'})
    if framework:
        assert detail['errors']
        assert all(set(error) == {'loc', 'msg', 'type'} for error in detail['errors'])
    assert response.headers['cache-control'] == 'no-store'


def test_preference_fingerprint_follows_the_single_read_save_and_clear_state(setup):
    client, _, _ = setup
    initial = client.get('/v1/driving-preferences').json()
    assert initial['fingerprint'] == preference_fingerprint(initial)
    saved = save_preference(client)
    assert saved['fingerprint'] == preference_fingerprint(saved) != initial['fingerprint']
    assert client.get('/v1/driving-preferences').json() == saved
    assert save_preference(client, saved['revision']) == saved
    cleared = client.post('/v1/driving-preferences/clear', json={'expected_revision': saved['revision']}).json()
    assert cleared['weights'] is None and cleared['revision'] > saved['revision']
    assert cleared['fingerprint'] == preference_fingerprint(cleared)
    assert cleared['fingerprint'] not in {initial['fingerprint'], saved['fingerprint']}
    assert client.get('/v1/driving-preferences').json() == cleared


def test_result_uses_read_snapshots_without_appending_records_or_changing_plain_comparison(setup):
    client, app, registry = setup
    row = create(client)
    preference = save_preference(client)
    original_comparison = compare(client, row).json()
    models = (TireTestEvent, TireTestRevision, DrivingPreferenceRevision, AuditEvent,
              Snapshot, TireVariant, FactVersion, Verification)

    def counts():
        with app.state.database.sessions() as db:
            return [db.scalar(select(func.count()).select_from(model)) for model in models]

    before = counts()
    writes = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().split(' ', 1)[0].upper() in {'INSERT', 'UPDATE', 'DELETE'}:
            writes.append(statement)

    sql_event.listen(app.state.database.engine, 'before_cursor_execute', record)
    try:
        response = interpret(client, row, preference)
    finally:
        sql_event.remove(app.state.database.engine, 'before_cursor_execute', record)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    result = response.json()
    assert result['scope'] == 'actor' and result['evidence_scope'] == 'local_workspace'
    assert result['binding']['event'] == {key: row[key] for key in ('id', 'revision_id', 'revision', 'fingerprint')}
    assert result['binding']['preference'] == {'revision': preference['revision'], 'fingerprint': preference_fingerprint(preference)}
    assert result['personal_interpretation']['weights'] == WEIGHTS
    assert [m['raw_value'] for m in result['source_evidence']['measurements']] == ['38.00', '40.0', '70']
    assert [m['source_rank'] for m in result['source_evidence']['measurements']] == [3, 5, None]
    assert before == counts() and writes == [] and registry.calls == []
    assert compare(client, row).json() == original_comparison


@pytest.mark.parametrize('field,value,code', [
    ('expected_event_revision', 2, 'test_event_changed'),
    ('expected_event_fingerprint', 'f' * 64, 'test_event_changed'),
    ('expected_preference_revision', 2, 'driving_preference_changed'),
    ('expected_preference_fingerprint', 'f' * 64, 'driving_preference_changed'),
])
def test_both_revision_and_content_bindings_are_enforced(setup, field, value, code):
    client, _, _ = setup
    row, preference = create(client), save_preference(client)
    assert_error(interpret(client, row, preference, **{field: value}), 409, code)


def test_binding_checks_follow_event_not_found_revoked_changed_missing_preference_then_changed_preference(setup):
    client, _, _ = setup
    row = create(client)
    preference = client.get('/v1/driving-preferences').json()
    body = request_body(row, preference)
    body['participant_ids'] = [row['participants'][0]['id']] * 2  # Semantic failure comes last.
    missing_path = '/v1/test-events/not-present/preference-interpretation?mode=history'
    assert_error(client.post(missing_path, json=body), 404, 'test_event_not_found')
    path = f'/v1/test-events/{row["id"]}/preference-interpretation?mode=history'
    assert_error(client.post(path, json={**body, 'expected_event_fingerprint': 'f' * 64}), 409, 'test_event_changed')
    assert_error(client.post(path, json=body), 409, 'driving_preference_missing')
    saved = save_preference(client)
    assert_error(client.post(path, json=body), 409, 'driving_preference_changed')
    assert_error(interpret(client, row, saved, participant_ids=body['participant_ids']), 422, 'invalid_preference_interpretation')
    revoked = client.post(f'/v1/test-events/{row["id"]}/state', json={
        'expected_revision': row['revision'], 'action': 'revoke', 'operator': 'Fixture reviewer',
        'reason': 'Synthetic withdrawal for ordering check'}).json()
    assert revoked['fingerprint'] == row['fingerprint']
    assert_error(client.post(path, json=body), 409, 'test_event_revoked')


def test_changed_event_and_saved_or_cleared_preferences_invalidate_old_requests(setup):
    client, _, _ = setup
    row, preference = create(client), save_preference(client)
    revised_payload = deepcopy(PAYLOAD)
    revised_payload['event']['measurements'][0]['raw_value'] = '38.10'
    revised = client.put(f'/v1/test-events/{row["id"]}', json={**revised_payload, 'expected_revision': row['revision']}).json()
    assert_error(interpret(client, row, preference), 409, 'test_event_changed')
    changed = save_preference(client, preference['revision'], {**WEIGHTS, 'dry': 25, 'wet': 20})
    assert_error(interpret(client, revised, preference), 409, 'driving_preference_changed')
    assert interpret(client, revised, changed).status_code == 200
    cleared = client.post('/v1/driving-preferences/clear', json={'expected_revision': changed['revision']}).json()
    assert cleared['weights'] is None
    assert_error(interpret(client, revised, changed), 409, 'driving_preference_missing')


def test_shared_events_do_not_expose_other_anonymous_actors_preferences(setup):
    client, app, _ = setup
    row, preference = create(client), save_preference(client)
    other = TestClient(app)
    try:
        assert_error(interpret(other, row, preference), 409, 'driving_preference_missing')
        own = save_preference(other, weights={**WEIGHTS, 'dry': 25, 'wet': 20})
        assert_error(interpret(other, row, preference), 409, 'driving_preference_changed')
        assert interpret(other, row, own).json()['personal_interpretation']['weights'] == own['weights']
        assert interpret(client, row, preference).json()['personal_interpretation']['weights'] == WEIGHTS
    finally:
        other.close()


def test_same_account_sessions_share_preferences_while_other_account_is_isolated(setup):
    client, app, _ = setup
    assert register(client, username='fixture_alice').status_code == 200
    row, preference = create(client), save_preference(client)
    same, other = TestClient(app), TestClient(app)
    try:
        assert login(same, 'fixture_alice').status_code == 200
        assert interpret(same, row, preference).json()['binding']['preference']['fingerprint'] == preference_fingerprint(preference)
        assert register(other, username='fixture_bob').status_code == 200
        assert_error(interpret(other, row, preference), 409, 'driving_preference_missing')
        save_preference(other)  # Global revisions skip across actors.
        shared = save_preference(same, preference['revision'], {**WEIGHTS, 'dry': 25, 'wet': 20})
        assert shared['revision'] > preference['revision'] + 1
        assert_error(interpret(client, row, preference), 409, 'driving_preference_changed')
        assert interpret(client, row, shared).json()['personal_interpretation']['weights'] == shared['weights']
    finally:
        same.close()
        other.close()


@pytest.mark.parametrize('change', ['duplicate_participant', 'foreign_participant', 'unknown_participant',
                                  'duplicate_metric', 'missing_metric', 'unknown_metric'])
def test_semantic_set_and_mapping_errors_use_stable_422(setup, change):
    client, _, _ = setup
    row, preference = create(client), save_preference(client)
    body = request_body(row, preference)
    if change == 'duplicate_participant': body['participant_ids'][1] = body['participant_ids'][0]
    elif change == 'foreign_participant': body['participant_ids'][1] = create(client)['participants'][1]['id']
    elif change == 'unknown_participant': body['participant_ids'][1] = row['id'] + ':unknown'
    elif change == 'duplicate_metric': body['metric_dimensions'][1] = deepcopy(body['metric_dimensions'][0])
    elif change == 'missing_metric': body['metric_dimensions'].pop()
    elif change == 'unknown_metric': body['metric_dimensions'][1]['metric_key'] = 'unknown'
    assert_error(client.post(f'/v1/test-events/{row["id"]}/preference-interpretation?mode=history', json=body),
                 422, 'invalid_preference_interpretation')


@pytest.mark.parametrize('field,value', [
    ('expected_event_revision', True), ('expected_event_revision', 0), ('expected_event_revision', '1'),
    ('expected_preference_revision', True), ('expected_preference_revision', 0), ('expected_preference_revision', 1.0),
    ('expected_event_fingerprint', 'F' * 64), ('expected_event_fingerprint', 'f' * 63),
    ('expected_preference_fingerprint', ' ' + 'f' * 64), ('expected_preference_fingerprint', None),
    ('participant_ids', ['only-one']), ('participant_ids', ['a'] * 61), ('participant_ids', [1, 2]),
    ('metric_dimensions', []), ('metric_dimensions', [{'metric_key': 'wet', 'dimension': None}] * 25),
    ('metric_dimensions', [{'metric_key': 'wet', 'dimension': 'speed'}]),
    ('metric_dimensions', [{'metric_key': 'wet'}]),
    ('metric_dimensions', [{'metric_key': 'wet', 'dimension': None, 'direction': 'lower'}]),
])
def test_framework_shape_errors_precede_business_checks_with_sanitized_stable_detail(setup, field, value):
    client, _, _ = setup
    body = request_body({'revision': 1, 'fingerprint': 'a' * 64, 'participants': [{'id': 'a'}, {'id': 'b'}]},
                        {'revision': 1, 'weights': WEIGHTS})
    body[field] = value
    assert_error(client.post('/v1/test-events/not-present/preference-interpretation?mode=history', json=body),
                 422, 'invalid_preference_interpretation', framework=True)


@pytest.mark.parametrize('field', ['expected_event_revision', 'expected_event_fingerprint',
                                  'expected_preference_revision', 'expected_preference_fingerprint',
                                  'participant_ids', 'metric_dimensions'])
def test_each_of_the_six_fields_is_required(setup, field):
    client, _, _ = setup
    row, preference = create(client), save_preference(client)
    body = request_body(row, preference)
    del body[field]
    assert_error(client.post(f'/v1/test-events/{row["id"]}/preference-interpretation?mode=history', json=body),
                 422, 'invalid_preference_interpretation', framework=True)


@pytest.mark.parametrize('field', ['actor', 'weights', 'direction', 'raw_value', 'source_rank', 'sku', 'url'])
def test_client_cannot_override_actor_or_source_evidence(setup, field):
    client, _, _ = setup
    row, preference = create(client), save_preference(client)
    response = interpret(client, row, preference, **{field: 'DO_NOT_ECHO_REQUEST_VALUE'})
    assert_error(response, 422, 'invalid_preference_interpretation', framework=True)
    assert 'DO_NOT_ECHO_REQUEST_VALUE' not in response.text


@pytest.mark.parametrize('query', ['', '?mode=live'])
def test_mode_is_required_and_history_only(setup, query):
    client, _, _ = setup
    row, preference = create(client), save_preference(client)
    assert_error(client.post(f'/v1/test-events/{row["id"]}/preference-interpretation{query}',
                             json=request_body(row, preference)),
                 422, 'invalid_preference_interpretation', framework=True)


def test_other_routes_keep_the_existing_framework_validation_shape(setup):
    client, _, _ = setup
    row = create(client)
    response = client.post(f'/v1/test-events/{row["id"]}/compare?mode=history', json={'expected_revision': True})
    assert response.status_code == 422 and isinstance(response.json()['detail'], list)
