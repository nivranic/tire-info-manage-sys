"""Independent R68 business/transaction review; private synthetic SQLite only."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib

import pytest
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tire_api.db import Base, ChangeEvent, FactVersion, ManualFactRevision, Snapshot, Verification, uid, utc, utcnow
from tire_api.domain import digest
from tire_api.interest_events import freeze
from tire_api.interest_matching import match_event
from tire_api.interest_models import InterestEvent, InterestNotification
from test_interest_governance_review import adopt, domain_notices, original, tire
from test_interest_review import condition, interest, private_api


DOMAIN = 'tire_curation_validity'
KIND = 'tire_curation_applicability_event'
TABLE = 'tire_curation_applicability_events'


def model():
    from tire_api.interest_applicability_models import TireCurationApplicabilityEvent
    return TireCurationApplicabilityEvent


def ledger(app):
    with app.state.database.sessions() as db:
        return list(db.scalars(select(model()).order_by(model().revision)))


def review(client, variant_id, source='fixture'):
    response = client.get(f'/v1/tire-variants/{variant_id}/fact-review',
                          params={'mode': 'history', 'source_id': source})
    assert response.status_code == 200, response.text
    return response.json()


def curate(client, variant_id, *, field='utqg_treadwear', action='manual_override', value=420, source='fixture'):
    state = review(client, variant_id, source)
    payload = {'source_id': source, 'base_fact_id': state['base_fact_id'],
        'expected_revision': state['revision'], 'field': field, 'action': action,
        'operator': 'Synthetic independent R68 reviewer', 'reason': 'Synthetic applicability boundary only',
        'evidence': [{'snapshot_id': state['provenance']['snapshot_id'], 'locator': 'Synthetic original member'}]}
    if action == 'manual_override':
        payload['value'] = value
    response = client.post(f'/v1/tire-variants/{variant_id}/fact-revisions', json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def baseline(client, app, *, facts=None):
    row = tire(facts=facts if facts is not None else {
        'utqg_treadwear': 300, 'weight_kg': 10, 'tread_depth': {'value': 7, 'unit': 'mm'}})
    accepted = adopt(client, app, [row], 'Synthetic R68 source base')
    return row, accepted['variants'][0]['id']


def publish_change(client, app, row, *, marker='Synthetic R68 unrelated field update', **changes):
    changed = deepcopy(row)
    changed['facts'].update(changes or {'tread_depth': {'value': 8, 'unit': 'mm'}})
    return adopt(client, app, [changed], marker)


def public_payload(row):
    return {column.name: utc(value).isoformat() if isinstance(value, datetime) else deepcopy(value)
            for column in row.__table__.columns
            if not column.name.endswith('session_id') and column.name not in {'idempotency_key', 'request_hash'}
            for value in [getattr(row, column.name)]}


def frozen_event(app, record_id):
    with app.state.database.sessions() as db:
        event_row = db.scalar(select(InterestEvent).where(InterestEvent.domain == DOMAIN,
                                                         InterestEvent.origin_id == record_id))
        assert event_row is not None
        return deepcopy(event_row.payload)


def verify_basis(db, row, side):
    basis = row.binding[side]
    expected = {'snapshot_id', 'source_id', 'query_key', 'source_url', 'raw_hash',
        'identity_contract_version', 'parsed_variants_hash', 'verification_id', 'verification_status',
        'verified_at', 'member_hash', 'structured_locator', 'fact_version_id', 'fact_version',
        'facts_hash', 'snapshot_member_fact_version'}
    assert expected <= set(basis)
    fact = db.get(FactVersion, getattr(row, side + '_fact_id'))
    snapshot = db.get(Snapshot, fact.snapshot_id)
    verification = db.get(Verification, basis['verification_id'])
    assert basis['fact_version_id'] == fact.id
    assert basis['fact_version'] == fact.version
    assert basis['facts_hash'] == fact.facts_hash == digest(fact.facts)
    assert basis['snapshot_id'] == fact.snapshot_id == snapshot.id == verification.snapshot_id
    assert basis['source_id'] == fact.source_id == row.source_id == snapshot.source_id == verification.source_id
    assert basis['query_key'] == snapshot.query_key == verification.query_key
    assert basis['source_url'] == snapshot.source_url
    assert basis['identity_contract_version'] == snapshot.identity_contract_version
    assert basis['raw_hash'] == snapshot.raw_hash == hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest()
    assert basis['parsed_variants_hash'] == digest(snapshot.parsed_variants)
    assert basis['verification_status'] == verification.status
    assert utc(datetime.fromisoformat(basis['verified_at'])) == utc(verification.verified_at)
    prefix, index = basis['structured_locator'].rsplit('/', 1)
    assert prefix == '/parsed_variants'
    member = snapshot.parsed_variants[int(index)]
    assert member['id'] == row.variant_id
    assert basis['member_hash'] == digest(member)
    assert basis['snapshot_member_fact_version'] == member['fact_version']
    if side == 'after':
        assert verification.id == row.verification_id
        assert utc(verification.verified_at) == utc(fact.observed_at) == utc(row.created_at)
    return basis


def test_review_other_field_refresh_invalidates_all_current_heads_without_fabricating_a_manual_action(private_api):
    client, app = private_api
    row, origin = baseline(client, app)
    curate(client, origin)
    curate(client, origin, field='weight_kg', action='revoke')
    exact = interest(client, condition('brand', 'Fixture Brand'), changed_fields=['facts.utqg_treadwear'])
    validity = interest(client, condition('brand', 'Fixture Brand'), changed_fields=['curation_applicability'])
    with app.state.database.sessions() as db:
        manual_before = {item.id: public_payload(item) for item in db.scalars(select(ManualFactRevision))}
    publish_change(client, app, row)
    entries = ledger(app)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.action == 'invalidate' and entry.manual_revision_watermark == 2
    assert len(entry.affected) == 2
    assert {item['field'] for item in entry.affected} == {'utqg_treadwear', 'weight_kg'}
    with app.state.database.sessions() as db:
        assert {item.id: public_payload(item) for item in db.scalars(select(ManualFactRevision))} == manual_before
        for affected in entry.affected:
            manual = db.get(ManualFactRevision, affected['manual_revision_id'])
            assert affected['manual_revision'] == manual.revision
            assert affected['action'] == manual.action
            assert affected['before_status'] == ('revoked' if manual.action == 'revoke' else 'manual_override')
            assert affected['after_status'] == 'needs_review'
            assert affected['manual_fingerprint'] == digest(public_payload(manual))
        verify_basis(db, entry, 'before')
        verify_basis(db, entry, 'after')
    payload = frozen_event(app, entry.id)
    assert payload['before']['state'] == 'applicable' and payload['after']['state'] == 'needs_review'
    assert payload['before']['facts']['utqg_treadwear'] == 420
    assert 'weight_kg' not in payload['before']['facts']
    assert payload['after']['facts']['utqg_treadwear'] == 300 and payload['after']['facts']['weight_kg'] == 10
    assert payload['before']['source_facts']['utqg_treadwear'] == payload['after']['source_facts']['utqg_treadwear'] == 300
    assert 'facts.utqg_treadwear' in payload['changed_paths'] and 'curation_applicability' in payload['changed_paths']
    assert all(path == 'state' or path == 'curation_applicability' or path.startswith('facts.') for path in payload['changed_paths'])
    assert {item['interest_id'] for item in domain_notices(client, DOMAIN)} == {exact['id'], validity['id']}
    assert all(item['interest_id'] != exact['id'] for item in domain_notices(client, 'tire'))


def test_review_equal_effective_value_changes_validity_only_and_preserves_raw_source_event(private_api):
    client, app = private_api
    row, origin = baseline(client, app)
    curate(client, origin)
    exact = interest(client, condition('brand', 'Fixture Brand'), changed_fields=['facts.utqg_treadwear'])
    validity = interest(client, condition('brand', 'Fixture Brand'), changed_fields=['curation_applicability'])
    publish_change(client, app, row, utqg_treadwear=420)
    entry, = ledger(app)
    payload = frozen_event(app, entry.id)
    assert payload['before']['facts']['utqg_treadwear'] == payload['after']['facts']['utqg_treadwear'] == 420
    assert not any(path.startswith('facts') for path in payload['changed_paths'])
    assert set(payload['changed_paths']) == {'curation_applicability', 'state'}
    assert {item['interest_id'] for item in domain_notices(client, DOMAIN)} == {validity['id']}
    raw = [item for item in domain_notices(client, 'tire') if item['interest_id'] == exact['id']]
    assert len(raw) == 1
    assert raw[0]['event']['before']['facts']['utqg_treadwear'] == 300
    assert raw[0]['event']['after']['facts']['utqg_treadwear'] == 420


@pytest.mark.parametrize('source_facts,action,value,expected_before,expected_after', [
    ({'utqg_treadwear': 300}, 'manual_override', 0, {'present': True, 'value': 0}, {'present': True, 'value': 300}),
    ({'utqg_treadwear': None}, 'manual_override', 420, {'present': True, 'value': 420}, {'present': True, 'value': None}),
    ({}, 'manual_override', 420, {'present': True, 'value': 420}, {'present': False, 'value': None}),
    ({'utqg_treadwear': 0}, 'revoke', None, {'present': False, 'value': None}, {'present': True, 'value': 0}),
])
def test_review_zero_null_absence_and_revoked_field_have_distinct_effective_transitions(
        private_api, source_facts, action, value, expected_before, expected_after):
    client, app = private_api
    row, origin = baseline(client, app, facts={**source_facts, 'weight_kg': 10})
    curate(client, origin, action=action, value=value)
    watched = interest(client, condition('brand', 'Fixture Brand'), changed_fields=['facts.utqg_treadwear'])
    publish_change(client, app, row, weight_kg=11)
    entry, = ledger(app)
    payload = frozen_event(app, entry.id)
    for side, expected in [('before', expected_before), ('after', expected_after)]:
        facts = payload[side]['facts']
        assert {'present': 'utqg_treadwear' in facts, 'value': facts.get('utqg_treadwear')} == expected
    assert 'facts.utqg_treadwear' in payload['changed_paths']
    assert {item['interest_id'] for item in domain_notices(client, DOMAIN)} == {watched['id']}


def test_review_snapshot_metadata_and_no_new_fact_304_do_not_invalidate(private_api):
    client, app = private_api
    row, origin = baseline(client, app)
    first = curate(client, origin)
    interest(client, condition('brand', 'Fixture Brand'))
    publish_change(client, app, row, marker='Synthetic different body, same business facts',
                   evidence_spans={'utqg_treadwear': 'Synthetic new locator'}, source_updated_at='2099-01-01')
    assert review(client, origin)['base_fact_id'] == first['base_fact_id']
    app.state.review_registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product',
                                       'etag': '"fixture-etag"'}
    response = client.post('/v1/sources/fixture/live-query', json={'query': {'size': row['size']}, 'fallback_policy': 'never'})
    assert response.status_code == 200 and response.json()['data_state'] == 'live_verified_304', response.text
    assert review(client, origin)['fields']['utqg_treadwear']['status'] == 'manual_override'
    assert ledger(app) == [] and domain_notices(client, DOMAIN) == []


def test_review_catalog_removal_and_reentry_preserve_overlay_when_actual_fact_does_not_change(private_api):
    client, app = private_api
    rows = [tire(manufacturer_product_code=f'R68-CATALOG-{index}',
                 brand='Fixture Brand' if index == 0 else 'Synthetic Control') for index in range(4)]
    accepted = adopt(client, app, rows, 'Synthetic complete R68 catalog')
    origin = accepted['variants'][0]['id']
    initial = curate(client, origin)
    interest(client, condition('brand', 'Fixture Brand'), changed_fields=['catalog_membership'])
    adopt(client, app, rows[1:], 'Synthetic R68 catalog one member absent')
    adopt(client, app, rows, 'Synthetic complete R68 catalog')
    current = review(client, origin)
    assert current['base_fact_id'] == initial['base_fact_id']
    assert current['fields']['utqg_treadwear']['status'] == 'manual_override'
    assert ledger(app) == [] and domain_notices(client, DOMAIN) == []
    assert len(domain_notices(client, 'tire_catalog')) == 2


def test_review_clear_and_already_stale_heads_do_not_repeat_but_explicit_rereview_can_invalidate_again(private_api):
    client, app = private_api
    row, origin = baseline(client, app)
    curate(client, origin)
    curate(client, origin, action='clear_override')
    publish_change(client, app, row, marker='Synthetic cleared overlay new base', weight_kg=11)
    assert ledger(app) == [] and review(client, origin)['fields']['utqg_treadwear']['status'] == 'cleared'
    curate(client, origin)
    watched = interest(client, condition('brand', 'Fixture Brand'))
    publish_change(client, app, row, marker='Synthetic first invalidation', weight_kg=12)
    publish_change(client, app, row, marker='Synthetic stale head next base', weight_kg=13)
    assert len(ledger(app)) == 1
    curate(client, origin, value=500)
    publish_change(client, app, row, marker='Synthetic return to earlier source payload', weight_kg=12)
    entries = ledger(app)
    assert [entry.revision for entry in entries] == [1, 2]
    assert len({entry.after_fact_id for entry in entries}) == 2
    assert entries[0].manual_revision_watermark == 3 and entries[1].manual_revision_watermark == 4
    assert frozen_event(app, entries[1].id)['before']['facts']['utqg_treadwear'] == 500
    assert {item['interest_id'] for item in domain_notices(client, DOMAIN)} == {watched['id']}


def test_review_other_source_does_not_invalidate_this_source_and_cannot_supply_missing_and_evidence(private_api):
    client, app = private_api
    row = tire(facts={'utqg_treadwear': 300, 'weight_kg': 10,
                      'source_field_conflicts': [{'field': 'brand'}]})
    accepted = adopt(client, app, [row], 'Synthetic R68 source A brand conflict')
    origin = accepted['variants'][0]['id']
    curate(client, origin)
    other = tire(facts={'utqg_treadwear': 320, 'source_field_conflicts': [{'field': 'acoustic_technology'}]})
    second = adopt(client, app, [other], 'Synthetic R68 source B technology conflict', source='fixture-two')
    assert second['variants'][0]['id'] == origin
    assert ledger(app) == [] and review(client, origin)['fields']['utqg_treadwear']['status'] == 'manual_override'
    combined = interest(client, condition('brand', 'Fixture Brand'), condition('technology', 'Fixture Acoustic'))
    positive = interest(client, condition('technology', 'Fixture Acoustic'))
    publish_change(client, app, row, weight_kg=11)
    assert len(ledger(app)) == 1
    found = domain_notices(client, DOMAIN)
    assert {item['interest_id'] for item in found} == {positive['id']}
    assert all(item['interest_id'] != combined['id'] for item in found)


def test_review_cross_query_304_new_actual_fact_invalidates_and_freezes_different_member_version(private_api):
    client, app = private_api
    row = tire(facts={'utqg_treadwear': 300})
    query_a, query_b = {'size': row['size']}, {'size': row['size'], 'model': row['model']}
    first = adopt(client, app, [row], 'Synthetic R68 cached query A', query=query_a)
    origin = first['variants'][0]['id']
    newer = deepcopy(row)
    newer['facts']['utqg_treadwear'] = 320
    adopt(client, app, [newer], 'Synthetic R68 intervening query B', query=query_b)
    manual = curate(client, origin)
    watched = interest(client, condition('brand', 'Fixture Brand'), changed_fields=['facts.utqg_treadwear'])
    app.state.review_registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product',
                                       'etag': '"fixture-etag"'}
    response = client.post('/v1/sources/fixture/live-query', json={'query': query_a, 'fallback_policy': 'never'})
    assert response.status_code == 200 and response.json()['data_state'] == 'live_verified_304', response.text
    entry, = ledger(app)
    assert entry.before_fact_id == manual['base_fact_id']
    with app.state.database.sessions() as db:
        before, after = verify_basis(db, entry, 'before'), verify_basis(db, entry, 'after')
        assert before['query_key'] != after['query_key']
        assert after['snapshot_id'] == first['provenance'][0]['snapshot_id']
        assert after['fact_version'] == 3 and after['snapshot_member_fact_version'] == 1
        assert after['verification_status'] == 'not_modified'
        assert utc(entry.created_at) > utc(db.get(Snapshot, after['snapshot_id']).observed_at)
    payload = frozen_event(app, entry.id)
    assert payload['before']['facts']['utqg_treadwear'] == 420
    assert payload['after']['facts']['utqg_treadwear'] == 300
    assert {item['interest_id'] for item in domain_notices(client, DOMAIN)} == {watched['id']}


def test_review_equal_timestamps_use_manual_watermark_when_reopening_and_refreezing_old_transition(private_api):
    client, app = private_api
    fixed = utcnow() + timedelta(seconds=10)

    def same_time(session, _context, _instances):
        for row in session.new:
            for name in ('created_at', 'observed_at', 'verified_at'):
                if hasattr(row, name):
                    setattr(row, name, fixed)

    event.listen(Session, 'before_flush', same_time)
    try:
        row, origin = baseline(client, app)
        curate(client, origin)
        interest(client, condition('brand', 'Fixture Brand'))
        publish_change(client, app, row, marker='Synthetic timestamp tie first transition', weight_kg=11)
        first, = ledger(app)
        before = original(client, KIND, first.id)
        assert before.status_code == 200, before.text
        frozen = frozen_event(app, first.id)
        curate(client, origin, value=500)
        assert original(client, KIND, first.id).json() == before.json()
        with app.state.database.sessions() as db:
            rebuilt = freeze(db, DOMAIN, db.get(model(), first.id))
            assert rebuilt['before'] == frozen['before'] and rebuilt['after'] == frozen['after']
            assert rebuilt['event_hash'] == frozen['event_hash']
        publish_change(client, app, row, marker='Synthetic timestamp tie second transition', weight_kg=12)
        first, second = ledger(app)
        assert utc(first.created_at) == utc(second.created_at) == fixed
        assert first.manual_revision_watermark == 1 and second.manual_revision_watermark == 2
        assert frozen_event(app, second.id)['before']['facts']['utqg_treadwear'] == 500
        assert original(client, KIND, first.id).json() == before.json()
    finally:
        event.remove(Session, 'before_flush', same_time)


def accepted_counts(app):
    from tire_api.interest_catalog_models import TireCatalogRevision
    models = (Snapshot, FactVersion, ChangeEvent, Verification, ManualFactRevision,
              TireCatalogRevision, model(), InterestEvent, InterestNotification)
    with app.state.database.sessions() as db:
        return {item.__tablename__: db.scalar(select(func.count()).select_from(item)) for item in models}


@pytest.mark.parametrize('fail_table', [TABLE, 'interest_notifications'])
def test_review_failure_rolls_back_complete_adoption_and_catalog_then_retry_succeeds(private_api, fail_table):
    client, app = private_api
    rows = [tire(manufacturer_product_code=f'R68-ROLLBACK-{index}',
                 brand='Fixture Brand' if index == 0 else 'Synthetic Control') for index in range(4)]
    initial = adopt(client, app, rows, 'Synthetic R68 rollback initial directory')
    origin = initial['variants'][0]['id']
    manual = curate(client, origin)
    interest(client, condition('brand', 'Fixture Brand'), changed_fields=['facts.utqg_treadwear'])
    changed = deepcopy(rows[:3])
    changed[0]['facts']['tread_depth'] = {'value': 8, 'unit': 'mm'}
    before = accepted_counts(app)

    def reject(_connection, _cursor, statement, *_args):
        if statement.lstrip().lower().startswith('insert into ' + fail_table):
            raise RuntimeError('synthetic_r68_adoption_failure')

    event.listen(app.state.database.engine, 'before_cursor_execute', reject)
    try:
        with pytest.raises(RuntimeError, match='synthetic_r68_adoption_failure'):
            adopt(client, app, changed, 'Synthetic R68 failing accepted update and one catalog removal')
    finally:
        event.remove(app.state.database.engine, 'before_cursor_execute', reject)
    assert accepted_counts(app) == before
    current = review(client, origin)
    assert current['base_fact_id'] == manual['base_fact_id'] and current['effective_facts']['utqg_treadwear'] == 420
    adopt(client, app, changed, 'Synthetic R68 failing accepted update and one catalog removal')
    assert len(ledger(app)) == 1 and len(domain_notices(client, DOMAIN)) == 1
    assert accepted_counts(app)['tire_catalog_revisions'] == before['tire_catalog_revisions'] + 1


def test_review_legacy_before_identity_gap_does_not_block_legal_adoption_or_borrow_current_identity(private_api):
    from test_interest_governance_review import seed_historical_identity_gap
    client, app = private_api
    origin, _snapshot = seed_historical_identity_gap(client, app)
    curate(client, origin)
    watched = interest(client, condition('brand', 'Fixture Brand'))
    accepted = adopt(client, app, [tire(manufacturer_product_code='LEGACY-GAP-0',
        facts={'utqg_treadwear': 320})], 'Synthetic R68 valid source after preserved old identity gap')
    assert accepted['variants'][0]['id'] == origin
    entry, = ledger(app)
    assert domain_notices(client, DOMAIN) == []
    payload = frozen_event(app, entry.id)
    criteria = {key: watched[key] for key in ('conditions', 'metric_keys', 'changed_fields')}
    assert match_event(payload, criteria)['state'] == 'indeterminate'
    assert review(client, origin)['fields']['utqg_treadwear']['status'] == 'needs_review'


@pytest.mark.parametrize('invalidator', ['catalog', 'lifecycle', 'identity'])
def test_review_derived_event_cannot_revive_a_stale_reviewed_vehicle_chain(private_api, invalidator):
    from test_fitment_relations import read as relation_read
    from test_identity_resolution import decision as identity_decision, post as identity_post
    from test_interest_governance_review import lifecycle, mixed_interest, seed_reviewed_chain
    client, app = private_api
    source, selected, relation_id = seed_reviewed_chain(client, app)
    background = [{**deepcopy(source), 'manufacturer_product_code': f'SYNTHETIC-R68-CONTROL-{index}'}
                  for index in range(3)]
    full = [source, *background]
    adopt(client, app, full, 'Synthetic R68 complete directory before derived mixed check')
    origin = selected['variant_id']
    curate(client, origin)
    mixed = mixed_interest(client, changed_fields=['facts.utqg_treadwear'])
    positive = interest(client, condition('brand', 'Synthetic'), changed_fields=['facts.utqg_treadwear'])
    if invalidator == 'catalog':
        adopt(client, app, background, 'Synthetic R68 removes one reviewed catalog member')
        adopt(client, app, full, 'Synthetic R68 complete directory before derived mixed check')
    elif invalidator == 'lifecycle':
        removed = lifecycle(client, origin, [selected['tire_snapshot_id']])
        assert removed.status_code == 201, removed.text
        restored = lifecycle(client, origin, [selected['tire_snapshot_id']], action='restore', revision=1)
        assert restored.status_code == 201, restored.text
    else:
        target = {**deepcopy(source), 'manufacturer_product_code': 'SYNTHETIC-R68-OTHER-TARGET'}
        target_result = adopt(client, app, [target], 'Synthetic R68 distinct identity target', source='fixture-two')
        refs = [selected['tire_snapshot_id'], target_result['provenance'][0]['snapshot_id']]
        corrected = identity_post(client, origin, identity_decision(client, origin,
            target_result['variants'][0]['id'], refs))
        assert corrected.status_code == 201, corrected.text
        cleared = identity_post(client, origin, identity_decision(client, origin, None,
            [selected['tire_snapshot_id']], action='clear'))
        assert cleared.status_code == 201, cleared.text
    assert relation_read(client, relation_id)['effective_state'] == 'needs_review'
    assert review(client, origin)['fields']['utqg_treadwear']['status'] == 'manual_override'
    changed = deepcopy(full)
    changed[0]['facts']['tread_depth'] = {'value': 8, 'unit': 'mm'}
    adopt(client, app, changed, 'Synthetic R68 derived transition after old relation invalidated')
    assert len(ledger(app)) == 1
    found = domain_notices(client, DOMAIN)
    assert {item['interest_id'] for item in found} == {positive['id']}
    assert all(item['interest_id'] != mixed['id'] for item in found)


def test_review_later_interest_and_history_reads_never_backfill_derived_notifications(private_api):
    client, app = private_api
    row, origin = baseline(client, app)
    curate(client, origin)
    publish_change(client, app, row)
    entry, = ledger(app)
    assert domain_notices(client, DOMAIN) == []
    watched = interest(client, condition('brand', 'Fixture Brand'))
    before = accepted_counts(app)
    for _ in range(2):
        preview = client.post('/v1/interests/preview', params={'mode': 'history'}, json={
            key: watched[key] for key in ('conditions', 'metric_keys', 'changed_fields')})
        assert preview.status_code == 200, preview.text
        assert original(client, KIND, entry.id).status_code == 200
    assert accepted_counts(app) == before and domain_notices(client, DOMAIN) == []
    curate(client, origin, value=500)
    publish_change(client, app, row, marker='Synthetic truly future invalidation after follow', weight_kg=11)
    assert len(ledger(app)) == 2
    assert {item['interest_id'] for item in domain_notices(client, DOMAIN)} == {watched['id']}


@pytest.mark.parametrize('corrupt', ['origin', 'manual', 'before_body', 'after_fact'])
def test_review_exact_reader_remains_old_and_rejects_changed_origin_manual_or_basis(private_api, corrupt):
    client, app = private_api
    row, origin = baseline(client, app)
    curate(client, origin)
    interest(client, condition('brand', 'Fixture Brand'))
    publish_change(client, app, row, weight_kg=11)
    entry, = ledger(app)
    response = original(client, KIND, entry.id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['schema'] == 'interest-original-evidence@1' and body['kind'] == KIND
    assert body['record_id'] == entry.id and body['entity_id'] == origin and body['revision'] == entry.revision
    assert body['fingerprint'] == digest(body['record'])
    assert not any(key.endswith('session_id') for key in body['record'])
    assert 'valid_to' not in body['record']
    curate(client, origin, value=500)
    publish_change(client, app, row, marker='Synthetic newer source after exact original saved', weight_kg=12)
    assert original(client, KIND, entry.id).json() == body
    with app.state.database.engine.begin() as connection:
        if corrupt == 'origin':
            connection.execute(model().__table__.update().where(model().id == entry.id).values(action='synthetic_corruption'))
        elif corrupt == 'manual':
            connection.execute(ManualFactRevision.__table__.update().where(
                ManualFactRevision.id == entry.affected[0]['manual_revision_id']).values(reason='Synthetic raw row corruption'))
        elif corrupt == 'before_body':
            connection.execute(Snapshot.__table__.update().where(
                Snapshot.id == entry.binding['before']['snapshot_id']).values(body='Synthetic corrupted historical body'))
        else:
            connection.execute(FactVersion.__table__.update().where(
                FactVersion.id == entry.after_fact_id).values(facts={'utqg_treadwear': 999}))
    failed = original(client, KIND, entry.id)
    assert failed.status_code == 409 and failed.json()['detail']['code'] == 'interest_evidence_mismatch', failed.text
    missing = original(client, KIND, 'missing-synthetic-r68-origin')
    assert missing.status_code == 404 and missing.json()['detail']['code'] == 'interest_evidence_not_found'


@pytest.fixture
def pre018(tmp_path, monkeypatch):
    """Current table shapes/pre-018 ledger, not an exact historical backup."""
    from tire_api.knowledge_models import initialize_search
    from tire_api.main import create_app
    from tire_api.migrations import DEVICE_AI_LEDGER_TRIGGERS_SQLITE
    from test_identity_migration import seed_legacy
    from test_interest_migration import seed_interest_ledger
    from version_registry import EXPECTED_SCHEMA_VERSIONS
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    for name in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(name, '0')
    database = create_app('sqlite:///' + (tmp_path / 'private-pre018.sqlite').as_posix()).state.database
    with database.engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables if table.name != TABLE])
        connection.exec_driver_sql('CREATE TABLE tire_schema_versions '
                                  '(version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version in EXPECTED_SCHEMA_VERSIONS[:17]:
            connection.execute(text('INSERT INTO tire_schema_versions (version) VALUES (:version)'), {'version': version})
        for statement in DEVICE_AI_LEDGER_TRIGGERS_SQLITE:
            connection.exec_driver_sql(statement)
        initialize_search(connection)
    with database.sessions() as db:
        seed = seed_legacy(db, namespace='R68', product_code='SYNTHETIC-PRE018', watch=True,
                           extra_namespaces=('R68-OTHER',))
        db.add(ManualFactRevision(id=uid(), variant_id=seed['variant_id'], source_id='fixture',
            base_fact_id=seed['fact_ids'][0], revision=1, field='utqg_treadwear', action='manual_override',
            operator_session_id=seed['session_id'], operator='Synthetic pre018 reviewer',
            reason='Synthetic old overlay already outlived its base',
            before={'present': True, 'value': 300}, after={'present': True, 'value': 420},
            source_before={'present': True, 'value': 300}, evidence=[]))
        db.commit()
        seed_interest_ledger(db)
    try:
        yield database
    finally:
        database.close()


def test_review_018_preserves_all_predecessor_rows_schema_and_does_not_backfill_or_repeat(pre018):
    from test_ai_stream_migration import snapshot
    from version_registry import EXPECTED_SCHEMA_VERSIONS
    from historical_migration_support import (assert_full_chain_preserved, assert_target_delta,
        assert_trigger_contract, initialize_observing_version)
    before = snapshot(pre018)
    assert TABLE not in before['tables']
    assert_trigger_contract(before, device=True, candidate=False)
    stage = initialize_observing_version(pre018, '018_interest_manual_applicability')
    assert_target_delta(before, stage, {TABLE})
    assert_trigger_contract(stage, device=True, candidate=False)
    first = snapshot(pre018)
    pre018.initialize()
    after = snapshot(pre018)
    assert first == after
    assert after['tables'] - before['tables'] == {TABLE}
    assert not before['tables'] - after['tables']
    assert_full_chain_preserved(before, after)
    for table in before['tables'] - {'tire_schema_versions'}:
        assert after['rows'][table] == before['rows'][table], table
    assert after['rows'][TABLE] == []
    with pre018.engine.connect() as connection:
        versions = set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars())
        assert versions == set(EXPECTED_SCHEMA_VERSIONS)
        assert '018_interest_manual_applicability' in versions
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('PRAGMA integrity_check').scalar_one() == 'ok'
        constraints = [set(item['column_names']) for item in inspect(connection).get_unique_constraints(TABLE)]
        assert {'after_fact_id'} in constraints
        assert {'variant_id', 'source_id', 'revision'} in constraints


def test_review_018_ddl_and_schema_version_roll_back_together(pre018, monkeypatch):
    from tire_api import migrations
    from test_ai_stream_migration import snapshot
    before = snapshot(pre018)
    upgrade = migrations.upgrade

    def fail_after_upgrade(connection):
        upgrade(connection)
        raise RuntimeError('synthetic_r68_ddl_failure')

    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'upgrade', fail_after_upgrade)
        with pytest.raises(RuntimeError, match='synthetic_r68_ddl_failure'):
            pre018.initialize()
    assert snapshot(pre018) == before


def test_review_real_sqlite_unique_foreign_keys_and_append_only_orm_are_enforced(private_api):
    client, app = private_api
    row, origin = baseline(client, app)
    curate(client, origin)
    publish_change(client, app, row)
    entry, = ledger(app)
    with app.state.database.sessions() as db:
        payload = {column.name: deepcopy(getattr(entry, column.name))
                   for column in model().__table__.columns if column.name != 'id'}
        # Duplicate the after fact while giving the derived revision a fresh value.
        with pytest.raises(IntegrityError):
            db.add(model()(id=uid(), **{**payload, 'revision': entry.revision + 1000}))
            db.flush()
        db.rollback()
        # Duplicate the revision with a different, existing fact that has no ledger row.
        with pytest.raises(IntegrityError):
            db.add(model()(id=uid(), **{**payload, 'after_fact_id': entry.before_fact_id}))
            db.flush()
        db.rollback()
        for missing in ('before_fact_id', 'after_fact_id', 'verification_id'):
            replacement = {**payload, 'revision': entry.revision + 1000, 'after_fact_id': entry.before_fact_id,
                           missing: 'missing-synthetic-r68-foreign-key'}
            with pytest.raises(IntegrityError):
                db.add(model()(id=uid(), **replacement))
                db.flush()
            db.rollback()
        stored = db.get(model(), entry.id)
        stored.action = 'synthetic_rewrite'
        with pytest.raises(ValueError):
            db.flush()
        db.rollback()
        db.delete(db.get(model(), entry.id))
        with pytest.raises(ValueError):
            db.flush()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(model())) == 1


def test_review_applicability_table_and_indexes_compile_for_postgresql_without_runtime_claim():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable
    dialect = postgresql.dialect()
    table = model().__table__
    sql = str(CreateTable(table).compile(dialect=dialect))
    assert 'CREATE TABLE ' + TABLE in sql
    assert 'TIMESTAMP WITH TIME ZONE' in sql and 'PRAGMA' not in sql and 'AUTOINCREMENT' not in sql
    assert 'UNIQUE (after_fact_id)' in sql
    assert 'UNIQUE (variant_id, source_id, revision)' in sql
    for field in ('before_fact_id', 'after_fact_id', 'verification_id'):
        assert f'FOREIGN KEY({field})' in sql
    for index in table.indexes:
        assert 'CREATE INDEX' in str(CreateIndex(index).compile(dialect=dialect))
