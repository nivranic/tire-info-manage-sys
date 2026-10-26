"""R75 public HTTP checks over private, explicitly synthetic evidence only."""
import pytest
from sqlalchemy import event as sql_event

from candidate_interpretation_support import (business_counts, candidate_case, interpret, ok,
    reference, request_body)
from test_test_sku_links import operation, stored


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()['detail']['code'] == code, response.text
    assert response.headers['cache-control'] == 'no-store'


def assert_invalid_request(response):
    assert_error(response, 422, 'test_candidate_invalid_request')
    detail = response.json()['detail']
    assert set(detail) == {'code', 'message', 'errors'}
    assert isinstance(detail['message'], str) and 1 <= len(detail['errors']) <= 20
    assert all(set(error) == {'loc', 'msg', 'type'} for error in detail['errors'])


def test_complete_two_sku_closure_preserves_source_axes_and_is_read_only(candidate_case):
    case = candidate_case
    before = business_counts(case.database)
    writes = []
    def record(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().split(' ', 1)[0].upper() in {'INSERT', 'UPDATE', 'DELETE'}:
            if 'sessions' not in statement.lower():
                writes.append(statement)
    sql_event.listen(case.database.engine, 'before_cursor_execute', record)
    try:
        response = interpret(case)
    finally:
        sql_event.remove(case.database.engine, 'before_cursor_execute', record)
    result = ok(response)
    assert response.headers['cache-control'] == 'no-store'
    assert result['schema'] == 'test-candidate-interpretation@1'
    assert result['status'] == 'conditional_observations'
    assert result['requested_count'] == result['eligible_count'] == 2
    assert result['excluded'] == [] and result['reason_codes'] == []
    assert result['performance_score'] is None and result['ranking'] == 'source_reported_only'
    assert result['boundary']['provider_use'] is result['boundary']['export'] is False
    assert [item['variant_id'] for item in result['items']] == [s['variant_id'] for s in case.selections]
    assert all(item['eligible'] and item['reason_codes'] == [] for item in result['items'])
    assert all(p['identity_status'] == 'participant_only' for p in result['source_evidence']['participants'])
    assert [m['raw_value'] for m in result['source_evidence']['measurements']] == ['38.00', '40.0', '70', '-0', '0']
    assert [m['source_rank'] for m in result['source_evidence']['measurements']] == [3, 5, None, None, 8]
    wet, noise, dry = result['personal_interpretation']['metrics']
    assert wet['observation_comparison']['favorable_participant_ids'] == [case.event['id'] + ':a']
    assert noise['observation_comparison'] is None and 'missing_measurements' in noise['limitations']
    assert dry['observation_comparison']['favorable_participant_ids'] == [case.event['id'] + ':a', case.event['id'] + ':b']
    assert before == business_counts(case.database) and writes == []


def test_old_review_reference_rejected_after_revoke_restore(candidate_case):
    case = candidate_case
    old = request_body(case)
    proposal, link = case.proposals[0], case.links[0]
    stored(case.reviewer, operation(proposal, link['id'], 'revoke'))
    restored = stored(case.reviewer, operation(proposal, link['id'], 'restore'))
    assert_error(interpret(case, old), 409, 'test_candidate_link_changed')
    current = request_body(case)
    current['candidates'][0] = reference(restored)
    result = ok(interpret(case, current))
    assert result['status'] == 'insufficient_evidence'
    assert result['personal_interpretation'] is None and result['eligible_count'] == 1
    assert result['excluded'][0]['variant_id'] == case.selections[0]['variant_id']


@pytest.mark.parametrize('mutate', ['duplicate_variant', 'duplicate_link', 'wrong_variant', 'extra_weights'])
def test_explicit_scope_and_closed_input_cannot_be_overridden(candidate_case, mutate):
    payload = request_body(candidate_case)
    if mutate == 'duplicate_variant':
        payload['candidates'][1]['variant_id'] = payload['candidates'][0]['variant_id']
    elif mutate == 'duplicate_link':
        payload['candidates'][1]['link_id'] = payload['candidates'][0]['link_id']
    elif mutate == 'wrong_variant':
        payload['candidates'][0]['variant_id'] = 'not-the-explicit-bridge-variant'
    else:
        payload['weights'] = {'wet': 100}
    response = interpret(candidate_case, payload)
    if mutate == 'wrong_variant':
        assert_error(response, 422, 'test_candidate_scope_mismatch')
    else:
        assert_invalid_request(response)


def test_null_mapping_is_insufficient_and_never_creates_a_score(candidate_case):
    result = ok(interpret(candidate_case, metric_dimensions=[
        {'metric_key': key, 'dimension': None} for key in ('wet', 'noise', 'dry')]))
    assert result['status'] == 'insufficient_evidence' and result['performance_score'] is None
    assert result['personal_interpretation']['coverage']['fully_comparable_weight'] == 0
    assert all(item['observation_comparison'] is None for item in result['personal_interpretation']['metrics'])


@pytest.mark.parametrize('field,value', [
    ('expected_event_revision_id', 'another-event-revision'),
    ('expected_event_revision', 2), ('expected_event_fingerprint', '0' * 64),
])
def test_full_current_event_revision_tuple_is_required(candidate_case, field, value):
    assert_error(interpret(candidate_case, **{field: value}), 409, 'test_candidate_event_changed')


@pytest.mark.parametrize('field,value', [
    ('expected_preference_revision', 99), ('expected_preference_fingerprint', '0' * 64),
])
def test_current_actor_preference_revision_and_content_are_required(candidate_case, field, value):
    assert_error(interpret(candidate_case, **{field: value}), 409, 'test_candidate_preference_changed')


def test_cleared_preference_is_not_replaced_by_default_weights(candidate_case):
    case = candidate_case
    ok(case.client.post('/v1/driving-preferences/clear',
        json={'expected_revision': case.preference['revision']}))
    assert_error(interpret(case), 409, 'test_candidate_preference_missing')


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'unknown'])
def test_mapping_must_explicitly_cover_every_event_metric(candidate_case, change):
    payload = request_body(candidate_case)
    if change == 'missing':
        payload['metric_dimensions'].pop()
    elif change == 'duplicate':
        payload['metric_dimensions'].append(payload['metric_dimensions'][0])
    else:
        payload['metric_dimensions'][0]['metric_key'] = 'not_this_event'
    assert_error(interpret(candidate_case, payload), 422, 'test_candidate_invalid_metric_mapping')


@pytest.mark.parametrize('field,value', [
    ('expected_event_revision', True), ('expected_event_revision', '1'),
    ('expected_preference_revision', 1.0), ('expected_event_revision_id', ' '),
    ('expected_event_fingerprint', 'F' * 64), ('participant_ids', ['client-supplied']),
    ('direction', 'lower'), ('raw_value', '0'), ('performance_score', 100),
])
def test_binding_types_and_derived_fields_are_strict(candidate_case, field, value):
    response = interpret(candidate_case, **{field: value})
    assert_invalid_request(response)


def test_history_mode_is_explicit_and_anonymous_actor_cannot_borrow_private_interpretation(candidate_case):
    from fastapi.testclient import TestClient
    case = candidate_case
    path = '/v1/test-events/' + case.event['id'] + '/candidate-interpretation'
    assert_invalid_request(case.client.post(path, json=request_body(case)))
    assert_invalid_request(case.client.post(path + '?mode=live', json=request_body(case)))
    with TestClient(case.app) as anonymous:
        assert_error(interpret(case, client=anonymous), 401, 'test_candidate_actor_required')
