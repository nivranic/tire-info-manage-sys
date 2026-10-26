"""Source-quality subscription and matching contracts; synthetic private inputs only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import desc, event as sql_event, func, select

from tire_api.db import (ChangeEvent, FactVersion, QueryRun, Snapshot, SourceQuarantine,
                        TireVariant, Verification, utcnow)
from tire_api.domain import digest
from tire_api.interest_matching import InterestSettings, capabilities, match_event
from tire_api.interest_models import InterestEvent, InterestNotification, InterestRevision
from tire_api.service import QueryService
from test_auth_accounts import register
from test_core import QUERY, VARIANT, success
from test_interest_review import private_api


def settings(**changes):
    return {'name': 'Synthetic quality interest', 'enabled': True,
        'conditions': [{'kind': 'brand', 'values': ['Fixture Brand']}],
        'metric_keys': [], 'changed_fields': [], **changes}


def create(client, **changes):
    response = client.post('/v1/interests', json=settings(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def edit(client, row, **changes):
    # Deliberately reproduce an old client's omitted new option.
    payload = {key: row[key] for key in ('name', 'enabled', 'conditions', 'metric_keys', 'changed_fields')}
    return client.put('/v1/interests/' + row['id'], json={
        **payload, 'expected_revision': row['revision'], **changes})


def old_fingerprint(row):
    return digest({key: row[key] for key in
        ('name', 'enabled', 'conditions', 'metric_keys', 'changed_fields', 'archived')})


def criteria(**changes):
    return {'conditions': [{'kind': 'brand', 'values': ['fixture brand']},
                           {'kind': 'technology', 'values': ['acoustic']}],
            'metric_keys': [], 'changed_fields': [], 'source_quality_notifications': True, **changes}


def member(label, **identity):
    return {'variant_id': label, 'structured_locator': '/parsed_variants/' + label.rsplit('-', 1)[-1],
        'member_hash': digest({'label': label, 'identity': identity}),
        'identity': identity, 'facts': {}, 'evidence_valid': True}


def quality_event(*members, **after):
    return {'schema': 'interest-event@1', 'id': 'a' * 64, 'domain': 'tire_source_quality',
        'action': 'quarantined', 'state': 'quarantined', 'revision': 1,
        'subject_id': 'synthetic-quarantine', 'observed_at': '2026-01-02T00:00:00+00:00',
        'label': 'Synthetic source query update quarantined', 'before': None,
        'after': {'accepted': False, 'state': 'quarantined', 'evidence_valid': True,
                  'baseline_members': list(members), **after},
        'changed_paths': ['source_quality'], 'evidence': []}


def test_create_settings_omitted_option_defaults_to_false_without_changing_legacy_hash():
    payload = InterestSettings.model_validate(settings()).model_dump()
    assert payload.get('source_quality_notifications') is False


def test_create_settings_accepts_explicit_true_for_supported_unfiltered_scope():
    payload = InterestSettings.model_validate(settings(source_quality_notifications=True)).model_dump()
    assert payload['source_quality_notifications'] is True


@pytest.mark.parametrize('value', [None, 0, 1, 'true', 'false', [], {}])
def test_subscription_requires_a_strict_boolean(value):
    with pytest.raises(ValidationError):
        InterestSettings.model_validate(settings(source_quality_notifications=value))


def test_capabilities_declare_quality_domain_with_explicit_opt_in_and_no_history_preview():
    result = capabilities()
    domain = next((row for row in result['domains'] if row['domain'] == 'tire_source_quality'), None)
    assert domain is not None and domain['supported'] is True
    assert domain['event_kinds'] == ['quarantined']
    assert {'explicit_subscription_required', 'verified_baseline_members_only',
            'unaccepted_candidates_never_matched', 'no_quality_history_preview',
            'local_notifications_only'}.issubset(domain['limitations'])


def test_api_create_omitted_false_and_false_hash_remain_legacy(private_api):
    client, _app = private_api
    omitted = create(client)
    explicit = create(client, source_quality_notifications=False, name='Synthetic explicit false')
    for row in (omitted, explicit):
        assert row.get('source_quality_notifications') is False
        assert row['fingerprint'] == old_fingerprint(row)


def test_edit_omission_preserves_true_and_explicit_false_unsubscribes(private_api):
    client, _app = private_api
    initial = create(client, source_quality_notifications=True)
    assert initial['fingerprint'] != old_fingerprint(initial)
    response = edit(client, initial, name='Synthetic old client rename')
    assert response.status_code == 200, response.text
    renamed = response.json()
    assert renamed['source_quality_notifications'] is True and renamed['revision'] == 2
    response = edit(client, renamed, source_quality_notifications=False)
    assert response.status_code == 200, response.text
    unsubscribed = response.json()
    assert unsubscribed['source_quality_notifications'] is False and unsubscribed['revision'] == 3
    assert unsubscribed['fingerprint'] == old_fingerprint(unsubscribed)
    history = client.get('/v1/interests/' + initial['id'] + '?mode=history').json()['history']
    assert [row['source_quality_notifications'] for row in history] == [False, True, True]


@pytest.mark.parametrize('changes', [
    {'metric_keys': ['wet_braking']}, {'changed_fields': ['facts.utqg_treadwear']},
    {'conditions': [{'kind': 'test_organization', 'values': ['Synthetic Lab']}]},
    {'conditions': [{'kind': 'vehicle_fitment', 'values': [{'vehicle_id': 'synthetic-car'}]}]},
])
def test_edit_omitted_true_validates_the_effective_merged_settings(private_api, changes):
    client, _app = private_api
    initial = create(client, source_quality_notifications=True)
    response = edit(client, initial, **changes)
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'source_quality_interest_filter_unsupported'
    current = client.get('/v1/interests/' + initial['id'] + '?mode=history').json()
    assert current['revision'] == 1 and current['source_quality_notifications'] is True


def test_explicit_unsubscribe_allows_old_fact_filters_and_omitted_true_noop_stays_conflict(private_api):
    client, _app = private_api
    initial = create(client, source_quality_notifications=True)
    response = edit(client, initial)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'interest_state_conflict'
    response = edit(client, initial, source_quality_notifications=False,
                    changed_fields=['facts.utqg_treadwear'])
    assert response.status_code == 200 and response.json()['source_quality_notifications'] is False


def test_archive_and_restore_keep_option_but_restore_to_paused(private_api):
    client, _app = private_api
    row = create(client, source_quality_notifications=True)
    for action in ('archive', 'restore'):
        response = client.post('/v1/interests/' + row['id'] + '/state', json={
            'action': action, 'expected_revision': row['revision']})
        assert response.status_code == 200, response.text
        row = response.json()
        assert row['source_quality_notifications'] is True and row['enabled'] is False
        assert row['archived'] is (action == 'archive')


def test_pure_quality_match_freezes_subscription_and_exact_single_baseline_member():
    basis = member('synthetic-member-0', brand='Fixture Brand', acoustic_technology='Acoustic')
    original = criteria()
    result = match_event(quality_event(basis), original)
    assert result['state'] == 'matched' and result['policy_version'] == 'source-quality-interest@1'
    assert result['criteria'] == original and result['matched_sides'] == ['after']
    assert result['matched_baseline_members'] == [{key: basis[key] for key in
        ('variant_id', 'structured_locator', 'member_hash')}]
    original['conditions'][0]['values'][0] = 'changed after matching'
    assert result['criteria']['conditions'][0]['values'] == ['fixture brand']


def test_pure_quality_match_does_not_pool_baseline_members_or_accept_candidate_identity():
    first = member('synthetic-member-0', brand='Fixture Brand', acoustic_technology='Other')
    second = member('synthetic-member-1', brand='Other Brand', acoustic_technology='Acoustic')
    event = quality_event(first, second, candidates=[{
        'identity': {'brand': 'Fixture Brand', 'acoustic_technology': 'Acoustic'}}])
    assert match_event(event, criteria())['state'] == 'no_match'


@pytest.mark.parametrize('option', [False, None])
def test_pure_quality_match_requires_explicit_subscription(option):
    request = criteria()
    if option is None:
        request.pop('source_quality_notifications')
    else:
        request['source_quality_notifications'] = option
    result = match_event(quality_event(member('synthetic-member-0', brand='Fixture Brand',
        acoustic_technology='Acoustic')), request)
    assert result['state'] == 'no_match' and result['reasons'] == ['source_quality_not_subscribed']
    assert result.get('matched_baseline_members', []) == []


@pytest.mark.parametrize('damage', ['invalid_top', 'invalid_member', 'missing_identity', 'conflict'])
def test_pure_quality_missing_or_conflicted_baseline_is_indeterminate(damage):
    basis = member('synthetic-member-0', brand='Fixture Brand', acoustic_technology='Acoustic')
    event = quality_event(basis)
    if damage == 'invalid_top':
        event['after']['evidence_valid'] = False
    elif damage == 'invalid_member':
        basis['evidence_valid'] = False
    elif damage == 'missing_identity':
        basis['identity'] = None
    else:
        basis['facts']['source_field_conflicts'] = [{'field': 'brand'}]
    result = match_event(event, criteria())
    assert result['state'] == 'indeterminate' and result.get('matched_baseline_members', []) == []


def test_pure_quality_size_matching_preserves_r_and_zr():
    basis = member('synthetic-member-0', size='265/40ZR20')
    result = match_event(quality_event(basis), criteria(conditions=[{'kind': 'size', 'values': ['265/40R20']}]))
    assert result['state'] == 'no_match'


@pytest.mark.parametrize('changes', [{'metric_keys': ['wet_braking']},
                                  {'changed_fields': ['facts.utqg_treadwear']}])
def test_pure_quality_unsupported_historical_filters_are_indeterminate(changes):
    event = quality_event(member('synthetic-member-0', brand='Fixture Brand', acoustic_technology='Acoustic'))
    result = match_event(event, criteria(**changes))
    assert result['state'] == 'indeterminate'
    assert result['reasons'] == ['source_quality_interest_filter_unsupported']


def test_existing_accepted_event_matching_keeps_legacy_policy_and_frozen_criteria_shape():
    request = criteria(conditions=[{'kind': 'brand', 'values': ['fixture brand']}])
    event = {'domain': 'tire', 'before': None,
             'after': {'identity': {'brand': 'Fixture Brand'}, 'facts': {}, 'evidence_valid': True},
             'changed_paths': ['identity.brand']}
    result = match_event(event, request)
    assert result['state'] == 'matched' and result['policy_version'] == 'explicit-interest@1'
    assert result['criteria'] == {key: request[key] for key in ('conditions', 'metric_keys', 'changed_fields')}
    assert 'matched_baseline_members' not in result


# Stage 2: real private ASGI/SQLite producers and retained evidence. These are
# deliberately separate from the stage-1 pure matcher and schema assertions.
def online(client, *, source='fixture', query=None):
    return client.post('/v1/sources/' + source + '/live-query', json={
        'query': query or QUERY['query'], 'fallback_policy': 'never'})


def isolated_update(client, registry, body='synthetic-quality-rejected-body', *, variants=None):
    registry.result = success(body, variants=[] if variants is None else variants)
    response = online(client)
    assert response.status_code == 200, response.text
    assert response.json()['data_state'] == 'source_unavailable'
    assert response.json()['reason'] == 'source_quality_quarantined'
    assert response.json()['variants'] == response.json()['provenance'] == []
    return response.json()


def quality_notices(client):
    response = client.get('/v1/interest-notifications?mode=history')
    assert response.status_code == 200, response.text
    return [row for row in response.json()['items'] if row['event']['domain'] == 'tire_source_quality']


def only_quality_notice(client):
    rows = quality_notices(client)
    assert len(rows) == 1, rows
    return rows[0]


def model_count(database, model, *where):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model).where(*where))


def accepted_state(database):
    with database.engine.connect() as connection:
        return {model.__tablename__: [tuple(row) for row in connection.exec_driver_sql(
            'SELECT * FROM ' + model.__tablename__ + ' ORDER BY id')]
            for model in (Snapshot, Verification, TireVariant, FactVersion, ChangeEvent)}


def seeded_quality(private_api, **interest_changes):
    client, app = private_api
    row = create(client, source_quality_notifications=True, **interest_changes)
    baseline = online(client)
    assert baseline.status_code == 200 and baseline.json()['data_state'] == 'live', baseline.text
    return client, app.state.registry, app.state.database, row, baseline.json()


def test_new_quality_notice_freezes_only_status_and_baseline_without_accepting_candidate(private_api):
    client, registry, database, subscribed, first = seeded_quality(private_api)
    before = accepted_state(database)
    isolated_update(client, registry)
    notice = only_quality_notice(client)
    event = notice['event']
    assert notice['interest_id'] == subscribed['id'] and notice['interest_revision'] == 1
    assert event['schema'] == 'interest-event@1' and event['domain'] == 'tire_source_quality'
    assert event['action'] == event['state'] == 'quarantined' and event['revision'] == 1
    assert event['before'] is None and event['changed_paths'] == ['source_quality']
    assert event['event_hash'] == digest({key: value for key, value in event.items() if key != 'event_hash'})
    after = event['after']
    assert set(after) == {'accepted', 'state', 'evidence_valid', 'quarantine', 'baseline', 'baseline_members'}
    assert after['accepted'] is False and after['evidence_valid'] is True
    q, b = after['quarantine'], after['baseline']
    assert set(q) == {'id', 'query_id', 'source_id', 'query_key', 'query', 'source_url', 'raw_hash',
        'parser_version', 'observed_at', 'reason_codes', 'metrics', 'previous_snapshot_id'}
    assert set(b) == {'snapshot_id', 'source_id', 'query_key', 'source_url', 'raw_hash',
        'identity_contract_version', 'parsed_variants_hash', 'verification_id', 'verification_status',
        'verified_at', 'observed_at', 'parser_version'}
    assert q['previous_snapshot_id'] == b['snapshot_id'] == first['provenance'][0]['snapshot_id']
    assert q['source_id'] == b['source_id'] == 'fixture' and q['query_key'] == b['query_key'] == digest(QUERY['query'])
    assert q['query'] == QUERY['query'] and q['metrics'] and q['reason_codes'] == ['row_loss_threshold']
    assert event['subject_id'] == q['id'] and event['observed_at'] == q['observed_at']
    assert len(after['baseline_members']) == 1
    basis = after['baseline_members'][0]
    assert set(basis) == {'variant_id', 'structured_locator', 'member_hash', 'identity', 'facts',
        'fact_version_id', 'fact_version', 'facts_hash', 'evidence_valid'}
    assert basis['variant_id'] == first['variants'][0]['id'] and basis['facts']['utqg_treadwear'] == 300
    assert set(notice['match']) == {'policy_version', 'state', 'matched_sides', 'reasons',
                                   'matched_baseline_members', 'criteria'}
    assert notice['match']['policy_version'] == 'source-quality-interest@1'
    assert notice['match']['state'] == 'matched' and notice['match']['matched_sides'] == ['after']
    assert notice['match']['reasons'] == ['matches_baseline_member']
    assert notice['match']['matched_baseline_members'] == [
        {key: basis[key] for key in ('variant_id', 'structured_locator', 'member_hash')}]
    assert notice['match']['criteria'] == {key: subscribed[key] for key in
        ('conditions', 'metric_keys', 'changed_fields', 'source_quality_notifications')}
    refs = {ref['kind']: ref for ref in event['evidence']}
    assert set(refs) == {'tire_source_quarantine', 'tire_source_quality_baseline'}
    assert refs['tire_source_quarantine'] == {
        'kind': 'tire_source_quarantine', 'record_id': q['id'], 'entity_id': q['id'], 'revision': None,
        'snapshot_id': None, 'previous_snapshot_id': b['snapshot_id'], 'source_id': q['source_id'],
        'source_url': q['source_url'], 'verification_ids': [], 'fingerprint': q['raw_hash'],
        'contract_version': 'source-quality-interest@1'}
    assert refs['tire_source_quality_baseline'] == {
        'kind': 'tire_source_quality_baseline', 'record_id': b['snapshot_id'], 'entity_id': b['snapshot_id'],
        'revision': None, 'snapshot_id': b['snapshot_id'], 'previous_snapshot_id': None,
        'source_id': b['source_id'], 'source_url': b['source_url'], 'verification_ids': [b['verification_id']],
        'fingerprint': b['raw_hash'], 'contract_version': b['identity_contract_version']}
    assert accepted_state(database) == before and model_count(database, SourceQuarantine) == 1
    public = json.dumps(notice, ensure_ascii=False)
    assert 'synthetic-quality-rejected-body' not in public and 'candidates' not in public
    assert 'actor_session_id' not in public and 'session_id' not in public
    detail = client.get('/v1/interest-notifications/' + notice['id'] + '?mode=history')
    assert detail.status_code == 200 and detail.json() == notice
    assert client.get('/v1/quarantines/' + q['id'] + '?mode=history').json()['accepted'] is False
    assert client.get('/v1/evidence/' + b['snapshot_id']).json()['raw_hash'] == b['raw_hash']


def test_same_snapshot_multiple_304_uses_exact_latest_predecessor_not_earliest_verification(private_api):
    client, registry, database, _row, first = seeded_quality(private_api)
    with database.sessions() as db:
        first_id = db.scalar(select(Verification.id))
    for _index in range(2):
        registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product',
                           'etag': '"fixture-etag"'}
        last = online(client)
        assert last.status_code == 200 and last.json()['data_state'] == 'live_verified_304'
    with database.sessions() as db:
        previous_id = db.scalar(select(Verification.id).order_by(desc(Verification.verified_at), desc(Verification.id)))
    assert previous_id != first_id
    isolated_update(client, registry)
    baseline = only_quality_notice(client)['event']['after']['baseline']
    assert baseline['verification_id'] == previous_id and baseline['verification_status'] == 'not_modified'
    assert baseline['snapshot_id'] == first['provenance'][0]['snapshot_id']
    assert baseline['observed_at'] == first['snapshot_observed_at']
    assert baseline['verified_at'] == last.json()['verified_at']


def test_new_accepted_body_with_unchanged_facts_is_a_valid_later_quality_baseline(private_api):
    client, registry, database, _row, first = seeded_quality(private_api)
    registry.result = success('synthetic-new-accepted-body-with-same-facts')
    second = online(client)
    assert second.status_code == 200 and second.json()['data_state'] == 'live'
    second = second.json()
    assert second['provenance'][0]['snapshot_id'] != first['provenance'][0]['snapshot_id']
    assert model_count(database, FactVersion) == 1
    before = accepted_state(database)
    isolated_update(client, registry)
    event = only_quality_notice(client)['event']
    assert event['after']['baseline']['snapshot_id'] == second['provenance'][0]['snapshot_id']
    assert event['after']['baseline_members'][0]['fact_version'] == 1
    assert accepted_state(database) == before


def test_quality_delivery_failure_rolls_back_quarantine_event_and_notice_together(private_api):
    client, registry, database, _row, _first = seeded_quality(private_api)
    accepted_before = accepted_state(database)
    before = tuple(model_count(database, model) for model in (SourceQuarantine, InterestEvent, InterestNotification))
    def fail(_connection, _cursor, statement, *_args):
        if statement.lstrip().lower().startswith('insert into interest_notifications'):
            raise RuntimeError('synthetic-quality-notification-failure')
    sql_event.listen(database.engine, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='^synthetic-quality-notification-failure$'):
            isolated_update(client, registry)
    finally:
        sql_event.remove(database.engine, 'before_cursor_execute', fail)
    assert tuple(model_count(database, model) for model in (SourceQuarantine, InterestEvent, InterestNotification)) == before
    assert accepted_state(database) == accepted_before
    isolated_update(client, registry)
    assert len(quality_notices(client)) == 1


def test_integrated_baseline_conditions_cannot_pool_members_or_match_rejected_candidate(private_api):
    client, app = private_api
    create(client, source_quality_notifications=True, conditions=[
        {'kind': 'brand', 'values': ['Fixture Brand']},
        {'kind': 'technology', 'values': ['Target Acoustic']}])
    first = {**deepcopy(VARIANT), 'manufacturer_product_code': 'QUALITY-BASE-A', 'acoustic_technology': 'Other'}
    second = {**deepcopy(VARIANT), 'brand': 'Other Brand', 'manufacturer_product_code': 'QUALITY-BASE-B',
              'acoustic_technology': 'Target Acoustic'}
    app.state.registry.result = success('synthetic-two-member-baseline', variants=[first, second])
    assert online(client).json()['data_state'] == 'live'
    before = accepted_state(app.state.database)
    candidate = {**deepcopy(VARIANT), 'manufacturer_product_code': 'QUALITY-UNACCEPTED-C',
                 'acoustic_technology': 'Target Acoustic'}
    isolated_update(client, app.state.registry, variants=[candidate])
    assert quality_notices(client) == []
    assert accepted_state(app.state.database) == before
    with app.state.database.sessions() as db:
        assert all(row.get('manufacturer_product_code') != 'QUALITY-UNACCEPTED-C'
                   for row in db.scalars(select(TireVariant.identity)))


def test_latest_pause_archive_restore_and_late_subscription_do_not_backfill(private_api):
    client, registry, _database, original, _first = seeded_quality(private_api, enabled=False)
    isolated_update(client, registry, 'synthetic-paused-Q1')
    assert quality_notices(client) == []
    late = create(client, source_quality_notifications=True, name='Synthetic later subscription')
    enabled = edit(client, original, enabled=True).json()
    assert quality_notices(client) == []
    isolated_update(client, registry, 'synthetic-enabled-Q2')
    first_notices = quality_notices(client)
    assert {row['interest_id'] for row in first_notices} == {original['id'], late['id']}
    paused = edit(client, enabled, enabled=False, name='Synthetic renamed after notice').json()
    archived = client.post('/v1/interests/' + late['id'] + '/state', json={
        'action': 'archive', 'expected_revision': late['revision']}).json()
    isolated_update(client, registry, 'synthetic-paused-and-archived-Q3')
    assert quality_notices(client) == first_notices
    restored = client.post('/v1/interests/' + late['id'] + '/state', json={
        'action': 'restore', 'expected_revision': archived['revision']}).json()
    assert restored['enabled'] is False
    isolated_update(client, registry, 'synthetic-restored-paused-Q4')
    assert quality_notices(client) == first_notices
    assert paused['source_quality_notifications'] is True


@pytest.mark.parametrize('verification_status', ['ok', 'not_modified'])
@pytest.mark.parametrize('candidate', ['original_quarantine', 'restored_valid_result'])
def test_completed_quarantined_query_cannot_write_again_even_if_caller_commits(
        private_api, verification_status, candidate):
    from tire_api.db import AuditEvent
    from tire_api.quality import SourceQualityQuarantined
    client, registry, database, _row, _first = seeded_quality(private_api)
    isolated_update(client, registry)
    notice = only_quality_notice(client)
    accepted_before = accepted_state(database)
    models = (SourceQuarantine, InterestEvent, InterestNotification, AuditEvent)
    counts_before = {model: model_count(database, model) for model in models}
    # A changed transport response cannot revive a query which already ended
    # in quarantine. A genuinely new online request must have a new QueryRun.
    result = registry.result if candidate == 'original_quarantine' else success('synthetic-restored-response')
    with database.sessions() as db:
        run = db.get(QueryRun, notice['event']['after']['quarantine']['query_id'])
        variants = QueryService.validate_result(result, run.query)
        with pytest.raises(SourceQualityQuarantined):
            QueryService(db, registry).record_success(run, result, variants, verification_status)
        # Rollback would hide a second pending quarantine/audit. Committing
        # after the expected exception must still perform no new write.
        db.commit()
    assert accepted_state(database) == accepted_before
    assert {model: model_count(database, model) for model in models} == counts_before
    assert quality_notices(client) == [notice]


def test_concurrent_existing_origin_replay_never_backfills_new_subscription(private_api):
    client, registry, database, _row, _first = seeded_quality(private_api)
    isolated_update(client, registry)
    notice = only_quality_notice(client)
    create(client, source_quality_notifications=True, name='Synthetic too late for original')
    barrier = Barrier(2)
    def replay(_index):
        from tire_api.interest_source_quality import publish_quality_quarantine
        with database.sessions() as db:
            barrier.wait(timeout=10)
            QueryService(db, None).lock_ingestion()
            q = db.get(SourceQuarantine, notice['event']['subject_id'])
            previous = db.get(Verification, notice['event']['after']['baseline']['verification_id'])
            result = publish_quality_quarantine(db, q, previous)
            db.commit()
            return result.id
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(replay, range(2))) == [notice['event']['id']] * 2
    assert quality_notices(client) == [notice]


@pytest.mark.parametrize('corruption', ['deleted_quarantine', 'wrong_query_json', 'wrong_quarantine_source',
    'wrong_predecessor_scope', 'missing_baseline_member', 'lost_baseline_contract',
    'changed_revision_option', 'changed_event_hash', 'changed_notice_match'])
def test_successfully_frozen_quality_history_damage_fails_all_routes_before_marking_read(private_api, corruption):
    client, registry, database, _row, _first = seeded_quality(private_api)
    isolated_update(client, registry)
    notice = only_quality_notice(client)
    q, b = notice['event']['after']['quarantine'], notice['event']['after']['baseline']
    with database.engine.begin() as connection:
        if corruption == 'deleted_quarantine':
            connection.execute(SourceQuarantine.__table__.delete().where(SourceQuarantine.id == q['id']))
        elif corruption == 'wrong_query_json':
            connection.exec_driver_sql('UPDATE query_runs SET "query"=? WHERE id=?',
                                      ('{"synthetic-broken-quality-query":', q['query_id']))
        elif corruption == 'wrong_quarantine_source':
            connection.execute(SourceQuarantine.__table__.update().where(SourceQuarantine.id == q['id'])
                               .values(source_id='synthetic-wrong-source'))
        elif corruption == 'wrong_predecessor_scope':
            connection.execute(Verification.__table__.update().where(Verification.id == b['verification_id'])
                               .values(query_key='0' * 64))
        elif corruption == 'missing_baseline_member':
            connection.execute(Snapshot.__table__.update().where(Snapshot.id == b['snapshot_id'])
                               .values(parsed_variants=[]))
        elif corruption == 'lost_baseline_contract':
            connection.execute(Snapshot.__table__.update().where(Snapshot.id == b['snapshot_id'])
                               .values(identity_contract_version=None))
        elif corruption == 'changed_revision_option':
            connection.execute(InterestRevision.__table__.update().where(InterestRevision.interest_id == notice['interest_id'])
                               .values(source_quality_notifications=False))
        elif corruption == 'changed_event_hash':
            connection.execute(InterestEvent.__table__.update().where(InterestEvent.id == notice['event']['id'])
                               .values(event_hash='0' * 64))
        else:
            connection.execute(InterestNotification.__table__.update().where(InterestNotification.id == notice['id'])
                               .values(match={'state': 'matched', 'criteria': {}}))
    other = TestClient(client.app)
    try:
        assert register(other, username='quality-unrelated-reader').status_code == 200
        denied = other.get('/v1/interest-notifications/' + notice['id'] + '?mode=history')
        assert denied.status_code == 404 and denied.json()['detail']['code'] == 'interest_notification_not_found'
    finally:
        other.close()
    responses = [client.get('/v1/interest-notifications?mode=history'),
        client.get('/v1/interest-notifications/' + notice['id'] + '?mode=history'),
        client.put('/v1/interest-notifications/' + notice['id'] + '/read', json={'read': True})]
    for response in responses:
        assert response.status_code == 503, response.text
        assert response.json()['detail']['code'] == 'source_quality_interest_history_invalid'
        assert 'synthetic-broken-quality-query' not in response.text
    with database.sessions() as db:
        assert db.get(InterestNotification, notice['id']).read_at is None


def test_quality_notification_rejects_older_equivalent_revision_and_keeps_later_edits_readable(private_api):
    client, registry, database, first_revision, _baseline = seeded_quality(private_api)
    second_response = edit(client, first_revision, name='Synthetic name at quarantine',
                           source_quality_notifications=True)
    assert second_response.status_code == 200
    second_revision = second_response.json()
    assert second_revision['revision'] == 2
    isolated_update(client, registry)
    notice = only_quality_notice(client)
    assert notice['interest_revision'] == 2
    assert notice['interest_name'] == second_revision['name']

    # The cutoff must retain the actual published head, not today's latest head.
    later = edit(client, second_revision, name='Synthetic name after quarantine',
                 source_quality_notifications=True)
    assert later.status_code == 200 and later.json()['revision'] == 3
    assert quality_notices(client) == [notice]
    assert client.get('/v1/interest-notifications/' + notice['id'] + '?mode=history').json() == notice

    with database.sessions() as db:
        older_id = db.scalar(select(InterestRevision.id).where(
            InterestRevision.interest_id == notice['interest_id'], InterestRevision.revision == 1))
    assert older_id is not None
    # One pointer is damaged; the old revision itself is valid with equal criteria.
    with database.engine.begin() as connection:
        connection.execute(InterestNotification.__table__.update().where(
            InterestNotification.id == notice['id']).values(interest_revision_id=older_id))
    responses = [client.get('/v1/interest-notifications?mode=history'),
        client.get('/v1/interest-notifications/' + notice['id'] + '?mode=history'),
        client.put('/v1/interest-notifications/' + notice['id'] + '/read', json={'read': True})]
    assert [response.status_code for response in responses] == [503, 503, 503]
    assert all(response.json()['detail']['code'] == 'source_quality_interest_history_invalid'
               for response in responses)
    with database.sessions() as db:
        assert db.get(InterestNotification, notice['id']).read_at is None


@pytest.mark.parametrize('side', ['quarantine', 'baseline'])
def test_quality_list_never_reads_body_and_detail_rechecks_each_actual_text_hash(private_api, side):
    client, registry, database, _row, _first = seeded_quality(private_api)
    isolated_update(client, registry)
    notice = only_quality_notice(client)
    after = notice['event']['after']
    statements = []
    def observe(_connection, _cursor, statement, *_args):
        statements.append(statement.replace('"', '').lower())
    with database.engine.begin() as connection:
        if side == 'quarantine':
            connection.execute(SourceQuarantine.__table__.update().where(
                SourceQuarantine.id == after['quarantine']['id']).values(body='synthetic damaged quarantine text'))
        else:
            connection.execute(Snapshot.__table__.update().where(
                Snapshot.id == after['baseline']['snapshot_id']).values(body='synthetic damaged baseline text'))
    sql_event.listen(database.engine, 'before_cursor_execute', observe)
    try:
        assert quality_notices(client) == [notice]
    finally:
        sql_event.remove(database.engine, 'before_cursor_execute', observe)
    assert not any('snapshots.body' in sql or 'source_quarantines.body' in sql for sql in statements)
    response = client.get('/v1/interest-notifications/' + notice['id'] + '?mode=history')
    assert response.status_code == 503 and response.json()['detail']['code'] == 'source_quality_interest_history_invalid'
    assert 'synthetic damaged' not in response.text


def test_initial_legal_legacy_proof_gap_keeps_isolation_and_never_backfills_after_proof_appears(private_api):
    client, registry, database, _row, first = seeded_quality(private_api)
    with database.engine.begin() as connection:
        connection.execute(Snapshot.__table__.update().where(Snapshot.id == first['provenance'][0]['snapshot_id'])
                           .values(identity_contract_version=None))
    isolated_update(client, registry)
    assert model_count(database, SourceQuarantine) == 1
    assert model_count(database, InterestEvent, InterestEvent.domain == 'tire_source_quality') == 0
    assert quality_notices(client) == []
    with database.sessions() as db:
        old_origin = db.scalar(select(SourceQuarantine.id))
    with database.engine.begin() as connection:
        from tire_api.domain import IDENTITY_CONTRACT_VERSION
        connection.execute(Snapshot.__table__.update().where(Snapshot.id == first['provenance'][0]['snapshot_id'])
                           .values(identity_contract_version=IDENTITY_CONTRACT_VERSION))
    assert quality_notices(client) == []
    preview = client.post('/v1/interests/preview?mode=history', json={
        'conditions': [{'kind': 'brand', 'values': ['Fixture Brand']}], 'metric_keys': [], 'changed_fields': []})
    assert preview.status_code == 200
    assert model_count(database, InterestEvent, InterestEvent.domain == 'tire_source_quality') == 0
    isolated_update(client, registry, 'synthetic-new-isolation-after-proof-restored')
    notice = only_quality_notice(client)
    assert notice['event']['subject_id'] != old_origin
    assert model_count(database, InterestEvent, InterestEvent.domain == 'tire_source_quality') == 1


@pytest.mark.parametrize('damage', ['future_predecessor_time', 'baseline_body_hash'])
def test_initial_contradictory_baseline_cannot_be_downgraded_to_a_legal_proof_gap(private_api, damage):
    client, registry, database, _row, first = seeded_quality(private_api)
    with database.engine.begin() as connection:
        if damage == 'future_predecessor_time':
            connection.execute(Verification.__table__.update().values(verified_at=utcnow() + timedelta(days=1)))
        else:
            connection.execute(Snapshot.__table__.update().where(Snapshot.id == first['provenance'][0]['snapshot_id'])
                               .values(body='synthetic initial hash contradiction'))
    registry.result = success('synthetic-isolation-after-invalid-baseline', variants=[])
    response = online(client)
    assert response.status_code == 503 and response.json()['detail']['code'] == 'source_quality_interest_history_invalid'
    assert model_count(database, SourceQuarantine) == 0
    assert model_count(database, InterestEvent, InterestEvent.domain == 'tire_source_quality') == 0


def test_logged_in_quality_notice_never_enters_outbox_even_with_enabled_interest_webhook(tmp_path, monkeypatch):
    from tire_api.main import create_app
    from tire_api.webhook_models import WebhookEnvelope, WebhookQueue
    from test_core import FixtureRegistry
    from webhook_support import configured_environment, create_subscription, seed_webhook_case
    registry = FixtureRegistry()
    registry.supports_parser_deployments = False
    app = create_app(configured_environment(monkeypatch, tmp_path), registry)
    with TestClient(app) as client:
        case = seed_webhook_case(client)
        create_subscription(case, ['interest'], enabled=True)
        create(client, source_quality_notifications=True)
        before = tuple(model_count(app.state.database, model) for model in (WebhookEnvelope, WebhookQueue))
        isolated_update(client, registry)
        assert only_quality_notice(client)['event']['state'] == 'quarantined'
        assert tuple(model_count(app.state.database, model) for model in (WebhookEnvelope, WebhookQueue)) == before
        changed = deepcopy(VARIANT)
        changed['facts']['utqg_treadwear'] = 420
        registry.result = success('synthetic-accepted-old-domain-webhook', variants=[changed])
        assert online(client).json()['data_state'] == 'live'
        assert model_count(app.state.database, WebhookEnvelope) > before[0]


def test_quality_notice_read_state_is_owned_and_idempotent(private_api):
    client, registry, database, _row, _first = seeded_quality(private_api)
    isolated_update(client, registry)
    notice = only_quality_notice(client)
    path = '/v1/interest-notifications/' + notice['id'] + '/read'
    first = client.put(path, json={'read': True})
    assert first.status_code == 200 and first.json()['read_at']
    assert client.put(path, json={'read': True}).json() == first.json()
    assert client.put(path, json={'read': False}).json() == {'id': notice['id'], 'read_at': None}
    with database.sessions() as db:
        assert db.get(InterestNotification, notice['id']).read_at is None
