"""Independent R75 counterexamples over GUID-private synthetic evidence.

The expected composition digest is built from the frozen literal contract with
stdlib JSON/SHA, never from the candidate-interpretation production signer.
Public APIs establish evidence; SQL is only an observer or a deliberate private
corruption/session-rebind arrangement. No real publisher or human Golden claim.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4

import pytest
from sqlalchemy import event as sql_event, inspect, select, text
from sqlalchemy.orm import Session

from candidate_interpretation_support import candidate_case, interpret, ok, reference, request_body
from test_fitment_relations import decision as relation_decision, post as relation_post, seed_tire
from test_identity_resolution import decision as identity_decision, post as identity_post
from test_interest_governance_review import lifecycle
from test_test_events import create as create_event
from test_test_preference_routes import save_preference
from test_test_sku_links import operation, stored
from tire_api.db import UserSession
from tire_api.recommendation_candidates import FitmentCandidatesRequest, projection as r69_projection
from tire_api.test_sku_links import current_link_binding, latest_revision, link_view, reconstruct_link_revision


def independent_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def assert_error(response, status, code=None):
    assert response.status_code == status, response.text
    assert response.headers['cache-control'] == 'no-store'
    detail = response.json()['detail']
    assert isinstance(detail, dict), response.text
    assert set(detail) <= {'code', 'message', 'errors'}
    if code is not None:
        assert detail['code'] == code, response.text


def literal_preimage(case, body):
    """Independent literal assembly; reuse only the separately specified R69/R71 inputs."""
    with case.database.sessions() as db:
        candidate_projection, candidate_fingerprint = r69_projection(db, case.session,
            FitmentCandidatesRequest(selection=body['selection'],
                expected_preference_revision=body['expected_preference_revision'],
                expected_preference_fingerprint=body['expected_preference_fingerprint']))
        bound_candidates = []
        for requested in body['candidates']:
            row = latest_revision(db, requested['link_id'])
            bound_candidates.append({'request': deepcopy(requested),
                'link': link_view(db, row, actor=None, history=False),
                'current_binding': current_link_binding(db, reconstruct_link_revision(db, row))})
        actor_id = db.get(UserSession, case.session).user_id
    # API detail adds these fields to metadata. Everything else is the exact
    # metadata literal, including summary, original recorded_at and verification.
    event = {key: deepcopy(value) for key, value in case.event.items() if key not in {
        'data_state', 'scope', 'participants', 'history', 'history_truncated'}}
    mapping = {item['metric_key']: item['dimension'] for item in body['metric_dimensions']}
    return {'schema': 'test-candidate-interpretation-binding@1',
        'policy_version': 'same-event-candidate-interpretation@1', 'actor_user_id': actor_id,
        'event': event, 'preference': candidate_projection['preference'],
        'candidate_fingerprint': candidate_fingerprint, 'selection': deepcopy(body['selection']),
        'candidates': bound_candidates,
        'metric_dimensions': [{'metric_key': metric['key'], 'dimension': mapping[metric['key']]}
            for metric in case.event['event']['metrics']]}, candidate_projection


def business_snapshot(database):
    """Compare contents as well as counts so an UPDATE cannot hide in equal counts."""
    def observed(value):
        # Password salts/hashes are binary. Compare their digest without
        # persisting or displaying their contents in the review artifacts.
        return {'binary_sha256': hashlib.sha256(value).hexdigest(), 'bytes': len(value)} \
            if isinstance(value, bytes) else value
    with database.engine.connect() as connection:
        return {name: independent_digest(sorted([[observed(value) for value in row] for row in connection.execute(
                    text('SELECT * FROM "' + name + '"'))], key=repr))
            for name in inspect(connection).get_table_names() if name != 'local_sessions'}


def assert_excluded(result, variant_id):
    assert result['status'] == 'insufficient_evidence'
    assert result['personal_interpretation'] is None
    assert result['performance_score'] is None
    assert any(row['variant_id'] == variant_id and row['reason_codes'] for row in result['excluded'])
    assert all(row['identity_status'] == 'participant_only' for row in result['source_evidence']['participants'])


def test_review_literal_binding_sha_and_permutation_contract(candidate_case):
    case = candidate_case
    body = request_body(case)
    preimage, candidate_projection = literal_preimage(case, body)
    result = ok(interpret(case, body))
    expected = independent_digest(preimage)
    assert result['binding']['interpretation_fingerprint'] == expected
    assert result['candidate_projection'] == candidate_projection
    assert result['binding']['candidate_fingerprint'] == preimage['candidate_fingerprint']
    assert all(item['link']['allowed_actions'] == [] and 'history' not in item['link']
               and item['current_binding']['identity_contract']['binding_id']
               for item in preimage['candidates'])
    without_current = deepcopy(preimage)
    for item in without_current['candidates']:
        del item['current_binding']
    assert independent_digest(without_current) != expected
    swapped_mapping = deepcopy(body)
    swapped_mapping['metric_dimensions'].reverse()
    assert ok(interpret(case, swapped_mapping))['binding']['interpretation_fingerprint'] == expected
    swapped_candidates = deepcopy(body)
    swapped_candidates['candidates'].reverse()
    swapped = ok(interpret(case, swapped_candidates))
    other_preimage, _ = literal_preimage(case, swapped_candidates)
    assert swapped['binding']['interpretation_fingerprint'] == independent_digest(other_preimage) != expected
    assert [row['participant_key'] for row in swapped['items']] == ['b', 'a']
    assert [row['key'] for row in swapped['source_evidence']['participants']] == ['a', 'b']
    assert swapped['source_evidence'] == result['source_evidence']
    # Same product name and size are deliberately distinct exact manufacturer codes.
    assert case.tires[0]['brand'] == case.tires[1]['brand']
    assert case.tires[0]['model'] == case.tires[1]['model']
    assert case.tires[0]['manufacturer_product_code'] != case.tires[1]['manufacturer_product_code']
    assert len({row['variant_id'] for row in result['items']}) == 2
    assert [row['raw_value'] for row in result['source_evidence']['measurements']] == ['38.00', '40.0', '70', '-0', '0']
    assert [row['source_rank'] for row in result['source_evidence']['measurements']] == [3, 5, None, None, 8]
    evidence_root = os.environ.get('R75_REVIEW_OUTPUT')
    if evidence_root:
        Path(evidence_root, 'literal-oracle.json').write_text(json.dumps({
            'expected_sha256': expected, 'actual_sha256': result['binding']['interpretation_fingerprint'],
            'preimage': preimage}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def test_review_success_and_error_leave_all_business_contents_and_audit_unchanged(candidate_case):
    case = candidate_case
    before = business_snapshot(case.database)
    writes = []
    session_updates = []
    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if re.search(r'\b(?:INSERT\s+INTO|UPDATE\s+|DELETE\s+FROM|REPLACE\s+INTO|CREATE\s+|DROP\s+|ALTER\s+)\b',
                     statement, re.IGNORECASE):
            (session_updates if 'local_sessions' in statement.lower() else writes).append(statement)
    sql_event.listen(case.database.engine, 'before_cursor_execute', observe)
    try:
        ok(interpret(case))
        changed = request_body(case, expected_event_revision=999)
        assert_error(interpret(case, changed), 409, 'test_candidate_event_changed')
        changed = request_body(case)
        changed['candidates'][0]['variant_id'] = 'another-exact-sku'
        assert_error(interpret(case, changed), 422, 'test_candidate_scope_mismatch')
        changed['unexpected_raw_value'] = 'DO_NOT_REFLECT_THIS_INPUT'
        response = interpret(case, changed)
        assert_error(response, 422, 'test_candidate_invalid_request')
        assert 'DO_NOT_REFLECT_THIS_INPUT' not in response.text
    finally:
        sql_event.remove(case.database.engine, 'before_cursor_execute', observe)
    assert writes == []
    assert business_snapshot(case.database) == before
    # Existing middleware may refresh only its local session. This is not a
    # claim that the entire HTTP request executes zero SQL writes.
    assert all('UPDATE local_sessions' in sql for sql in session_updates)


def test_review_event_restore_same_payload_does_not_reuse_revision_identity(candidate_case):
    case = candidate_case
    original = request_body(case)
    path = '/v1/test-events/' + case.event['id'] + '/state'
    control = {'expected_revision': case.event['revision'], 'action': 'revoke',
        'operator': 'Synthetic R75 reviewer', 'reason': 'Synthetic event ABA counterexample'}
    revoked = ok(case.client.post(path, json=control))
    restored = ok(case.client.post(path, json={**control,
        'expected_revision': revoked['revision'], 'action': 'restore'}))
    assert restored['event'] == case.event['event']
    assert restored['fingerprint'] == case.event['fingerprint']
    assert restored['revision_id'] != case.event['revision_id']
    assert_error(interpret(case, original), 409, 'test_candidate_event_changed')
    original.update(expected_event_revision_id=restored['revision_id'],
                    expected_event_revision=restored['revision'])
    # Even with the new event tuple the old bridge is scoped to the old revision.
    assert_error(interpret(case, original), 422, 'test_candidate_scope_mismatch')


def test_review_old_bridge_revision_is_rejected_even_when_old_fingerprint_is_valid(candidate_case):
    case = candidate_case
    original = request_body(case)
    revoked = stored(case.reviewer, operation(case.proposals[0], case.links[0]['id'], 'revoke'))
    current = deepcopy(original)
    current['candidates'][0] = reference(revoked)
    assert_excluded(ok(interpret(case, current)), case.selections[0]['variant_id'])
    assert_error(interpret(case, original), 409, 'test_candidate_link_changed')
    restored = stored(case.reviewer, operation(case.proposals[0], case.links[0]['id'], 'restore'))
    current['candidates'][0] = reference(restored)
    assert_excluded(ok(interpret(case, current)), case.selections[0]['variant_id'])
    assert_error(interpret(case, original), 409, 'test_candidate_link_changed')


def test_review_current_axle_candidate_exclusion_keeps_source_observations_without_partial_result(candidate_case):
    case = candidate_case
    front = ok(interpret(case))
    body = request_body(case)
    body['selection']['axle'] = 'rear'
    rear = ok(interpret(case, body))
    assert rear['candidate_projection']['items'] == []
    assert rear['eligible_count'] == 0 and len(rear['excluded']) == 2
    assert all(row['reason_codes'] == ['candidate_not_current'] for row in rear['excluded'])
    assert rear['personal_interpretation'] is None
    assert rear['source_evidence'] == front['source_evidence']
    assert rear['binding']['interpretation_fingerprint'] != front['binding']['interpretation_fingerprint']
    revoked = ok(relation_post(case.client, relation_decision(case.client,
        case.selections[0], 'revoke', case.relations[0]['id'])), 201)
    assert revoked['relation']['review_state'] == 'revoked'
    result = ok(interpret(case))
    assert result['eligible_count'] == 1
    assert_excluded(result, case.selections[0]['variant_id'])


@pytest.mark.parametrize('kind', ['lifecycle', 'identity', 'catalog'])
def test_review_current_binding_aba_never_reactivates_review(candidate_case, kind):
    case = candidate_case
    before = ok(interpret(case))
    selected = case.selections[0]
    if kind == 'lifecycle':
        ok(lifecycle(case.client, selected['variant_id'], [selected['tire_snapshot_id']]), 201)
        ok(lifecycle(case.client, selected['variant_id'], [selected['tire_snapshot_id']],
            action='restore', revision=1), 201)
    elif kind == 'identity':
        snapshots = [row['tire_snapshot_id'] for row in case.selections]
        target = case.selections[1]['variant_id']
        ok(identity_post(case.client, selected['variant_id'], identity_decision(case.client,
            selected['variant_id'], target, snapshots)), 201)
        ok(identity_post(case.client, selected['variant_id'], identity_decision(case.client,
            selected['variant_id'], None, snapshots[:1], action='clear')), 201)
    else:
        # Actual accepted source/query observations remove and reenter the exact
        # member. Existing immutable reviews retain their original generation.
        seed_tire(case.database, case.session, case.tires[0], variant_id=selected['variant_id'],
            source='synthetic-candidate-source-0', empty=True)
        seed_tire(case.database, case.session, case.tires[0], variant_id=selected['variant_id'],
            source='synthetic-candidate-source-0', metadata_only=True)
    result = ok(interpret(case))
    assert_excluded(result, selected['variant_id'])
    assert result['binding']['interpretation_fingerprint'] != before['binding']['interpretation_fingerprint']
    preimage, _ = literal_preimage(case, request_body(case))
    current = preimage['candidates'][0]['current_binding']
    if kind == 'lifecycle':
        assert current['lifecycle']['state'] == 'active' and current['lifecycle']['revision'] == 2
    elif kind == 'identity':
        assert current['identity_resolution']['state'] == 'cleared'
        assert current['identity_resolution']['revision'] == 2
    else:
        assert current['catalogs'][0]['present'] is True
        assert current['catalogs'][0]['transition_revision'] == 3
    assert result['binding']['interpretation_fingerprint'] == independent_digest(preimage)


def test_review_same_length_original_corruption_is_not_hash_or_size_evidence(candidate_case):
    case = candidate_case
    ok(interpret(case))
    with case.database.sessions() as db:
        store = db.info['object_store']
    path = store.path(case.document['raw_hash'])
    original = path.read_bytes()
    altered = original[:-1] + bytes([original[-1] ^ 1])
    assert len(altered) == len(original) and hashlib.sha256(altered).hexdigest() != case.document['raw_hash']
    path.write_bytes(altered)
    response = interpret(case)
    assert response.status_code == 422, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert 'detail' in response.json() and 'SYNTHETIC' not in response.text


def test_review_cross_event_and_duplicate_participant_scope_rejected_at_creation(candidate_case):
    case = candidate_case
    other_event = create_event(case.client, case.event_payload)
    response = case.client.post('/v1/test-events/' + other_event['id']
        + '/candidate-interpretation?mode=history', json=request_body(case,
            expected_event_revision_id=other_event['revision_id'],
            expected_event_revision=other_event['revision'],
            expected_event_fingerprint=other_event['fingerprint']))
    assert_error(response, 422, 'test_candidate_scope_mismatch')
    proposal = deepcopy(case.proposals[1])
    proposal['selection']['participant_key'] = 'a'
    # R71 enforces unique event/participant scope before such a second bridge
    # can exist. Keep that real public guard instead of weakening its DB/schema
    # or mocking the bridge reconstruction to reach an impossible fixture.
    from test_test_sku_links import decision, post
    response = post(case.client, decision(case.client, proposal))
    assert_error(response, 409, 'test_sku_link_gate_failed')
    assert 'test_sku_link_scope_exists' in response.text


def test_review_truncated_real_relation_scan_is_never_a_complete_candidate_set(candidate_case, monkeypatch):
    import tire_api.recommendation_candidates as candidates
    # Lower only the scan budget; both real reviewed DB rows still exist and
    # production SQL, evidence admission and projection execute unchanged.
    monkeypatch.setattr(candidates, 'MAX_RELATIONS', 1)
    assert_error(interpret(candidate_case), 409, 'test_candidate_candidate_scope_incomplete')


def test_review_six_and_sixty_are_request_bounds_not_device_wire_six(candidate_case):
    from tire_api.test_candidate_interpretation import CandidateInterpretationRequest
    body = request_body(candidate_case)
    for count in (2, 6, 7, 60):
        refs = [{**body['candidates'][0], 'variant_id': 'synthetic-variant-' + str(index),
                 'link_id': 'synthetic-link-' + str(index)} for index in range(count)]
        assert len(CandidateInterpretationRequest.model_validate({**body, 'candidates': refs}).candidates) == count
    for count in (0, 1, 61):
        with pytest.raises(ValueError):
            CandidateInterpretationRequest.model_validate({**body, 'candidates': [
                {**body['candidates'][0], 'variant_id': str(index), 'link_id': str(index)}
                for index in range(count)]})


def test_review_main_registers_one_post_and_sanitizes_framework_validation(candidate_case):
    case = candidate_case
    route_path = '/v1/test-events/{event_id}/candidate-interpretation'
    routes = [route for route in case.app.routes if getattr(route, 'path', None) == route_path]
    assert len(routes) == 1 and routes[0].methods == {'POST'}
    path = '/v1/test-events/' + case.event['id'] + '/candidate-interpretation'
    responses = [case.client.post(path, json=request_body(case)),
        case.client.post(path + '?mode=live', json=request_body(case)),
        case.client.post(path + '?mode=history', content=b'{"selection":',
                         headers={'content-type': 'application/json'}),
        case.client.post(path + '?mode=history', content=b'{"selection":NaN}',
                         headers={'content-type': 'application/json'})]
    for response in responses:
        assert_error(response, 422, 'test_candidate_invalid_request')
        errors = response.json()['detail']['errors']
        assert errors and all(set(error) == {'loc', 'msg', 'type'} for error in errors)


def tail_change(case, monkeypatch, change):
    """Mutate via a separate transaction only after the route releases its snapshot."""
    import tire_api.test_candidate_interpretation as module
    original_projection, original_rollback = module.projection, Session.rollback
    state = {'reads': 0, 'target': None, 'fired': False}
    def observed_projection(db, *args, **kwargs):
        state['reads'] += 1
        result = original_projection(db, *args, **kwargs)
        if state['reads'] == 1:
            state['target'] = db
        return result
    def observed_rollback(db):
        original_rollback(db)
        if db is state['target'] and not state['fired']:
            state['fired'] = True
            change()
    monkeypatch.setattr(module, 'projection', observed_projection)
    monkeypatch.setattr(Session, 'rollback', observed_rollback)
    response = interpret(case)
    assert state['fired'] and state['reads'] == 2
    return response


def test_review_tail_rereads_actual_actor_even_when_preference_and_evidence_are_equal(candidate_case, monkeypatch):
    case = candidate_case
    reviewer_session = case.reviewer.cookies['tire_local_session']
    with case.database.sessions() as db:
        reviewer_actor = db.get(UserSession, reviewer_session).user_id
    def switch_actor():
        with case.database.engine.begin() as connection:
            connection.execute(text('UPDATE local_sessions SET user_id=:actor WHERE id=:session'),
                {'actor': reviewer_actor, 'session': case.session})
    # Preference belongs to this same session, so it follows the rebind. The
    # response must fail because actor_user_id changed, even if all other
    # signature inputs and request bindings remain byte-for-byte identical.
    assert_error(tail_change(case, monkeypatch, switch_actor), 409, 'test_candidate_binding_changed')


def test_review_tail_rereads_preference_from_a_committed_second_connection(candidate_case, monkeypatch):
    case = candidate_case
    weights = deepcopy(case.preference['weights'])
    weights['wet'], weights['dry'] = weights['dry'], weights['wet']
    if weights == case.preference['weights']:
        weights['wet'] += 1
        weights['dry'] -= 1
    def change():
        save_preference(case.client, case.preference['revision'], weights)
    assert_error(tail_change(case, monkeypatch, change), 409, 'test_candidate_preference_changed')


def test_review_tail_rereads_current_binding_after_real_lifecycle_commit(candidate_case, monkeypatch):
    case = candidate_case
    def change():
        selected = case.selections[0]
        ok(lifecycle(case.client, selected['variant_id'], [selected['tire_snapshot_id']]), 201)
    assert_error(tail_change(case, monkeypatch, change), 409, 'test_candidate_binding_changed')


def test_review_tail_reopens_original_bytes_after_snapshot_release(candidate_case, monkeypatch):
    case = candidate_case
    with case.database.sessions() as db:
        path = db.info['object_store'].path(case.document['raw_hash'])
    original = path.read_bytes()
    def change():
        path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    response = tail_change(case, monkeypatch, change)
    assert response.status_code == 422, response.text
    assert response.headers['cache-control'] == 'no-store'
