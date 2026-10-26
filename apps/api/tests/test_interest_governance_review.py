"""Independent governance boundaries; only private synthetic SQLite/API fixtures.

The browser suite covers the ordinary action flow. These cases concentrate on
ambiguous historical evidence, equal timestamps, transactional failure and the
pre-017 upgrade. They never open the normal database or use a real source.
"""
from copy import deepcopy
from datetime import timedelta
import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tire_api.db import (Base, ChangeEvent, FactVersion, ManualFactRevision, Snapshot,
                         TireVariant, VariantLifecycleEvent, Verification, uid, utc, utcnow)
from tire_api.domain import VariantInput, digest
from tire_api.identity_models import IdentityRevision
from tire_api.interest_matching import match_event
from tire_api.interest_models import InterestEvent, InterestNotification
from test_core import VARIANT, success
from test_interest_review import condition, interest, notices, private_api


def adopt(client, app, rows, marker, *, source='fixture', query=None):
    app.state.review_registry.result = success(marker, rows)
    response = client.post('/v1/sources/' + source + '/live-query', json={
        'query': query or {'size': rows[0]['size']}, 'fallback_policy': 'never'})
    assert response.status_code == 200, response.text
    assert response.json()['data_state'] == 'live', response.json()
    return response.json()


def tire(**changes):
    row = {**deepcopy(VARIANT), **changes}
    row['facts'] = {'product_code_type': 'MSPN', **row['facts']}
    return row


def domain_notices(client, domain):
    return [row for row in notices(client, limit=100)['items'] if row['event']['domain'] == domain]


def curation(client, variant_id, *, field='utqg_treadwear', action='manual_override', value=420):
    response = client.get('/v1/tire-variants/' + variant_id + '/fact-review',
                          params={'source_id': 'fixture', 'mode': 'history'})
    assert response.status_code == 200, response.text
    current = response.json()
    payload = {'source_id': 'fixture', 'base_fact_id': current['base_fact_id'],
        'expected_revision': current['revision'], 'field': field, 'action': action,
        'operator': 'Synthetic independent reviewer', 'reason': 'Synthetic governance review only',
        'evidence': [{'snapshot_id': current['provenance']['snapshot_id'],
                      'locator': 'Synthetic accepted source observation'}]}
    if action == 'manual_override':
        payload['value'] = value
    return client.post('/v1/tire-variants/' + variant_id + '/fact-revisions', json=payload)


def lifecycle(client, variant_id, snapshot_ids, *, action='revoke', revision=0):
    return client.post('/v1/tire-variants/' + variant_id + '/lifecycle-events', json={
        'action': action, 'expected_revision': revision, 'operator': 'Synthetic independent reviewer',
        'reason': 'Synthetic local lifecycle review only',
        'evidence': [{'snapshot_id': key, 'locator': 'Synthetic exact member'} for key in snapshot_ids]})


def original(client, kind, record_id):
    return client.get('/v1/interest-evidence/' + kind + '/' + record_id, params={'mode': 'history'})


def contexts(side):
    """Manual sides have one observation; other governance sides name sources."""
    return (side or {}).get('source_contexts', [side] if side else [])


def table_counts(database):
    from tire_api.interest_catalog_models import TireCatalogRevision
    models = (Snapshot, FactVersion, ChangeEvent, Verification, ManualFactRevision,
              VariantLifecycleEvent, IdentityRevision, TireCatalogRevision,
              InterestEvent, InterestNotification)
    with database.sessions() as db:
        return {model.__tablename__: db.scalar(select(func.count()).select_from(model)) for model in models}


def seed_reviewed_chain(client, app):
    from tire_api.vehicles import VehicleSnapshot, WheelFitment
    from test_fitment_relations import decision, post, seed_vehicle, tire_payload
    row = tire_payload(acoustic_technology='Acoustic')
    observed = adopt(client, app, [row], 'Synthetic r67 reviewed source observation')
    variant_id = observed['variants'][0]['id']
    snapshot_id = observed['provenance'][0]['snapshot_id']
    vehicle_snapshot_id = seed_vehicle(app.state.database, client.cookies['tire_local_session'])
    with app.state.database.sessions() as db:
        vehicle = db.get(VehicleSnapshot, vehicle_snapshot_id)
        db.add_all([WheelFitment(option_id=fit['id'], trim_id=fit['trim_id'], snapshot_id=vehicle.id,
            version=vehicle.fact_version, specification=deepcopy(fit)) for fit in vehicle.payload['fitments']])
        db.commit()
        fact_id = db.scalar(select(FactVersion.id).where(FactVersion.variant_id == variant_id,
                                                       FactVersion.snapshot_id == snapshot_id))
    selected = {'vehicle_id': 'synthetic-vehicle-gen1', 'vehicle_snapshot_id': vehicle_snapshot_id,
        'trim_id': 'synthetic-trim', 'wheel_option_id': 'synthetic-option', 'axle': 'front',
        'variant_id': variant_id, 'tire_snapshot_id': snapshot_id, 'fact_version_id': fact_id}
    created = post(client, decision(client, selected))
    assert created.status_code == 201, created.text
    relation_id = created.json()['relation']['id']
    reviewed = post(client, decision(client, selected, action='review', relation_id=relation_id))
    assert reviewed.status_code == 201, reviewed.text
    return row, selected, relation_id


def mixed_interest(client, **settings):
    return interest(client, condition('vehicle_fitment', {'vehicle_id': 'synthetic-vehicle-gen1',
        'trim_id': 'synthetic-trim', 'wheel_option_id': 'synthetic-option', 'axle': 'front'}),
        condition('brand', 'Synthetic'), condition('size', '245/40R20'), **settings)


def test_review_pure_invalid_top_evidence_cannot_escape_through_a_reviewed_context():
    criteria = {'conditions': [condition('vehicle_fitment', {'vehicle_id': 'synthetic-vehicle'}),
                              condition('brand', 'synthetic')], 'metric_keys': [], 'changed_fields': []}
    side = {'evidence_valid': False, 'source_contexts': [], 'reviewed_contexts': [
        {'identity': {'brand': 'Synthetic'}, 'facts': {}, 'vehicle_scope': {'vehicle_id': 'synthetic-vehicle'},
         'reviewed_relation': True, 'evidence_valid': True}]}
    result = match_event({'domain': 'tire_identity', 'before': None, 'after': side,
                          'changed_paths': ['identity_resolution']}, criteria)
    assert result['state'] == 'indeterminate'


def test_review_governance_full_and_cannot_pool_two_source_contexts(private_api):
    client, app = private_api
    first_row = tire(facts={'utqg_treadwear': 300, 'source_field_conflicts': [{'field': 'brand'}]})
    first = adopt(client, app, [first_row], 'Synthetic source A: conflicted brand')
    second_row = tire(facts={'utqg_treadwear': 300,
                            'source_field_conflicts': [{'field': 'acoustic_technology'}]})
    second = adopt(client, app, [second_row], 'Synthetic source B: conflicted technology', source='fixture-two')
    variant_id = first['variants'][0]['id']
    assert second['variants'][0]['id'] == variant_id
    combined = interest(client, condition('brand', 'Fixture Brand'),
                        condition('technology', 'Fixture Acoustic'))
    brand = interest(client, condition('brand', 'Fixture Brand'))
    technology = interest(client, condition('technology', 'Fixture Acoustic'))
    response = lifecycle(client, variant_id, [first['provenance'][0]['snapshot_id'],
                                            second['provenance'][0]['snapshot_id']])
    assert response.status_code == 201, response.text
    found = domain_notices(client, 'tire_lifecycle')
    assert {item['interest_id'] for item in found} == {brand['id'], technology['id']}
    assert all(item['interest_id'] != combined['id'] for item in found)


@pytest.mark.parametrize('kind', ['lifecycle', 'identity'])
def test_review_equal_timestamp_before_chain_and_restore_do_not_revive_an_old_review(private_api, kind):
    from tire_api.fitment_relation_models import FitmentRelationRevision
    from test_identity_resolution import decision as identity_decision, post as identity_post
    client, app = private_api
    clock = {'value': utcnow()}

    def equal_timestamp(_session, _context, _instances):
        for row in _session.new:
            for name in ('created_at', 'observed_at', 'verified_at'):
                if hasattr(row, name):
                    setattr(row, name, clock['value'])

    event.listen(Session, 'before_flush', equal_timestamp)
    try:
        source, selected, relation_id = seed_reviewed_chain(client, app)
        if kind == 'identity':
            target = {**deepcopy(source), 'manufacturer_product_code': 'SYNTHETIC-TARGET-OTHER-SKU'}
            accepted_target = adopt(client, app, [target], 'Synthetic identity target evidence', source='fixture-two')
            target_id = accepted_target['variants'][0]['id']
            target_snapshot = accepted_target['provenance'][0]['snapshot_id']
        watched = mixed_interest(client, changed_fields=['state' if kind == 'lifecycle' else 'identity_resolution'])
        with app.state.database.sessions() as db:
            reviewed = db.scalar(select(FitmentRelationRevision).where(
                FitmentRelationRevision.relation_id == relation_id).order_by(FitmentRelationRevision.revision.desc()))
            assert utc(reviewed.created_at) == clock['value']
        if kind == 'lifecycle':
            first = lifecycle(client, selected['variant_id'], [selected['tire_snapshot_id']])
        else:
            first = identity_post(client, selected['variant_id'], identity_decision(client,
                selected['variant_id'], target_id, [selected['tire_snapshot_id'], target_snapshot]))
        assert first.status_code == 201, first.text
        domain = 'tire_' + kind
        initial = domain_notices(client, domain)
        assert len(initial) == 1 and initial[0]['interest_id'] == watched['id']
        assert initial[0]['match']['matched_sides'] == ['before'], 'The just-written governance row must not erase the prior valid chain'
        if kind == 'lifecycle':
            restored = lifecycle(client, selected['variant_id'], [selected['tire_snapshot_id']], action='restore', revision=1)
        else:
            restored = identity_post(client, selected['variant_id'], identity_decision(client,
                selected['variant_id'], None, [selected['tire_snapshot_id']], action='clear'))
        assert restored.status_code == 201, restored.text
        assert len(domain_notices(client, domain)) == 1, 'State restoration cannot re-review an old relation binding'
        mixed = mixed_interest(client, changed_fields=['facts.utqg_treadwear'])
        positive = interest(client, condition('brand', 'Synthetic'), changed_fields=['facts.utqg_treadwear'])
        clock['value'] += timedelta(seconds=1)
        changed = deepcopy(source)
        changed['facts']['utqg_treadwear'] = 420
        adopt(client, app, [changed], 'Synthetic source change after governance restoration')
        changed_notices = domain_notices(client, 'tire')
        assert {item['interest_id'] for item in changed_notices} == {positive['id']}
        assert all(item['interest_id'] != mixed['id'] for item in changed_notices)
    finally:
        event.remove(Session, 'before_flush', equal_timestamp)


@pytest.mark.parametrize('kind', ['curation', 'lifecycle', 'identity', 'catalog'])
def test_review_governance_notification_failure_rolls_back_original_write(private_api, kind):
    from test_identity_resolution import decision as identity_decision, post as identity_post
    client, app = private_api
    rows = [tire(manufacturer_product_code=f'REVIEW-ROLLBACK-{index}',
                 brand='Review Target' if index == 0 else 'Review Background') for index in range(4)]
    accepted = adopt(client, app, rows, 'Synthetic four-row rollback baseline')
    origin = accepted['variants'][0]['id']
    source_snapshot = accepted['provenance'][0]['snapshot_id']
    interest(client, condition('brand', 'Review Target'))
    if kind == 'curation':
        operation = lambda: curation(client, origin)
    elif kind == 'lifecycle':
        operation = lambda: lifecycle(client, origin, [source_snapshot])
    elif kind == 'identity':
        payload = identity_decision(client, origin, accepted['variants'][1]['id'], [source_snapshot])
        operation = lambda: identity_post(client, origin, payload)
    else:
        operation = lambda: adopt(client, app, rows[1:], 'Synthetic one-row removal within the unchanged quality budget')
    before = table_counts(app.state.database)

    def fail_delivery(_connection, _cursor, statement, *_args):
        if statement.lower().lstrip().startswith('insert into interest_notifications'):
            raise RuntimeError('synthetic_governance_delivery_failure')

    event.listen(app.state.database.engine, 'before_cursor_execute', fail_delivery)
    try:
        with pytest.raises(RuntimeError, match='synthetic_governance_delivery_failure'):
            operation()
    finally:
        event.remove(app.state.database.engine, 'before_cursor_execute', fail_delivery)
    assert table_counts(app.state.database) == before
    result = operation()
    if kind != 'catalog':
        assert result.status_code == 201, result.text
    assert len(domain_notices(client, 'tire_' + kind)) == 1


def seed_historical_identity_gap(client, app, *, previous_mapping=False):
    """An old accepted fact can lack recoverable parsed identity without losing its management APIs."""
    from tire_api.identity_resolution import binding
    from test_fitment_relations import run_record
    database = app.state.database
    with database.sessions() as db:
        run = run_record(db, client.cookies['tire_local_session'], 'fixture', 'synthetic-historical-identity-gap')
        variant_ids = []
        for index in range(2 if previous_mapping else 1):
            parsed = VariantInput.model_validate(tire(manufacturer_product_code=f'LEGACY-GAP-{index}'))
            key, status = parsed.identity_key('fixture', run.query_key, index)
            row = TireVariant(id=uid(), identity_key=key, identity=parsed.identity(), identity_status=status)
            db.add(row)
            variant_ids.append(row.id)
        db.flush()
        body = 'Synthetic legacy observation with no recoverable structured identity'
        snapshot = Snapshot(id=uid(), source_id='fixture', query_key=run.query_key,
            source_url='https://fixture.invalid/historical-gap', raw_hash=hashlib.sha256(body.encode()).hexdigest(),
            body=body, content_type='text/plain', parser_version='synthetic-legacy@1',
            identity_contract_version=None, parsed_variants=[{'id': key} for key in variant_ids])
        db.add(snapshot)
        db.flush()
        for key in variant_ids:
            db.add(FactVersion(id=uid(), variant_id=key, source_id='fixture', snapshot_id=snapshot.id,
                version=1, facts={'utqg_treadwear': 300}, facts_hash=digest({'utqg_treadwear': 300})))
        db.add(Verification(snapshot_id=snapshot.id, query_id=run.id, source_id='fixture',
                            query_key=run.query_key, status='ok'))
        db.flush()
        if previous_mapping:
            bound = binding(db, variant_ids[0], variant_ids[1])
            db.add(IdentityRevision(id=uid(), variant_id=variant_ids[0], target_id=variant_ids[1],
                revision=1, action='correct', binding=bound, binding_hash=digest(bound), differences=[],
                field_reasons={}, acknowledged_unknowns=True, evidence=[], operator='Synthetic old reviewer',
                reason='Synthetic preserved legacy mapping', actor_session_id=run.session_id,
                idempotency_key=str(uuid4()), request_hash='a' * 64))
        db.commit()
        return variant_ids[0], snapshot.id


@pytest.mark.parametrize('kind', ['curation', 'lifecycle', 'identity'])
def test_review_legal_legacy_governance_without_historical_identity_is_indeterminate_not_blocked(private_api, kind):
    from test_identity_resolution import decision as identity_decision, post as identity_post
    client, app = private_api
    origin, snapshot_id = seed_historical_identity_gap(client, app, previous_mapping=kind == 'identity')
    watched = interest(client, condition('brand', 'Fixture Brand'))
    if kind == 'curation':
        result = curation(client, origin)
    elif kind == 'lifecycle':
        result = lifecycle(client, origin, [snapshot_id])
    else:
        result = identity_post(client, origin, identity_decision(client, origin, None, [snapshot_id], action='clear'))
    assert result.status_code == 201, result.text
    assert domain_notices(client, 'tire_' + kind) == []
    with app.state.database.sessions() as db:
        events = list(db.scalars(select(InterestEvent).where(InterestEvent.domain == 'tire_' + kind)))
        assert len(events) == 1
        criteria = {key: watched[key] for key in ('conditions', 'metric_keys', 'changed_fields')}
        assert match_event(events[0].payload, criteria)['state'] == 'indeterminate'


def test_review_catalog_presence_changes_survive_unchanged_facts_repeated_pairs_and_304(private_api):
    from tire_api.interest_catalog_models import TireCatalogRevision
    client, app = private_api
    rows = [tire(manufacturer_product_code=f'REVIEW-CATALOG-{index}',
                 brand='Review Target' if index == 0 else 'Review Background') for index in range(4)]
    first = adopt(client, app, rows, 'Synthetic catalog A')
    origin = first['variants'][0]['id']
    watched = interest(client, condition('brand', 'Review Target'), changed_fields=['catalog_membership'])
    facts_only = interest(client, condition('brand', 'Review Target'), changed_fields=['facts.utqg_treadwear'])
    before_facts = table_counts(app.state.database)['fact_versions']
    for values, body in ((rows[1:], 'Synthetic catalog B'), (rows, 'Synthetic catalog A'),
                         (rows[1:], 'Synthetic catalog B'), (rows, 'Synthetic catalog A')):
        adopt(client, app, values, body)
    found = domain_notices(client, 'tire_catalog')
    assert len(found) == 4 and {item['interest_id'] for item in found} == {watched['id']}
    assert all(item['interest_id'] != facts_only['id'] for item in found)
    assert {tuple(item['event']['changed_paths']) for item in found} == {('catalog_membership', 'state')}
    assert len({item['event']['id'] for item in found}) == 4
    assert [item['event']['action'] for item in reversed(found)] == ['removed', 'added', 'removed', 'added']
    assert table_counts(app.state.database)['fact_versions'] == before_facts
    with app.state.database.sessions() as db:
        recorded = list(db.scalars(select(TireCatalogRevision).where(TireCatalogRevision.variant_id == origin)
                                  .order_by(TireCatalogRevision.revision)))
        before_rows = len(recorded)
        assert len({row.id for row in recorded[-4:]}) == 4
        pairs = [(db.get(Snapshot, row.previous_snapshot_id).raw_hash,
                  db.get(Snapshot, row.snapshot_id).raw_hash) for row in recorded[-4:]]
        assert pairs[0] == pairs[2] and pairs[1] == pairs[3]
    app.state.review_registry.result = {'status': 'not_modified',
        'url': 'https://fixture.example/tires/product', 'etag': '"fixture-etag"'}
    response = client.post('/v1/sources/fixture/live-query', json={
        'query': {'size': rows[0]['size']}, 'fallback_policy': 'never'})
    assert response.status_code == 200 and response.json()['data_state'] == 'live_verified_304', response.text
    assert len(domain_notices(client, 'tire_catalog')) == 4
    with app.state.database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(TireCatalogRevision).where(
            TireCatalogRevision.variant_id == origin)) == before_rows


def test_review_catalog_reentry_does_not_reactivate_a_stale_reviewed_vehicle_chain(private_api):
    from test_fitment_relations import read as relation_read
    client, app = private_api
    source, selected, relation_id = seed_reviewed_chain(client, app)
    background = [{**deepcopy(source), 'manufacturer_product_code': f'SYNTHETIC-BACKGROUND-{index}'}
                  for index in range(3)]
    full = [source, *background]
    adopt(client, app, full, 'Synthetic four-row directory with the reviewed SKU')
    watched = mixed_interest(client, changed_fields=['facts.utqg_treadwear'])
    directory_watch = mixed_interest(client, changed_fields=['catalog_membership'])
    positive = interest(client, condition('brand', 'Synthetic'), changed_fields=['facts.utqg_treadwear'])
    adopt(client, app, background, 'Synthetic directory temporarily removes exactly one of four rows')
    removed = domain_notices(client, 'tire_catalog')
    assert len(removed) == 1 and removed[0]['interest_id'] == directory_watch['id']
    assert removed[0]['match']['matched_sides'] == ['before'], 'The removal must retain its preceding reviewed chain'
    adopt(client, app, full, 'Synthetic directory reintroduces the original unchanged SKU')
    assert len(domain_notices(client, 'tire_catalog')) == 1, 'Reentry cannot authorize the old relation on its after side'
    current = relation_read(client, relation_id)
    assert current['effective_state'] == 'needs_review', 'Directory transitions require a new review even after reentry'
    changed = deepcopy(source)
    changed['facts']['utqg_treadwear'] = 420
    adopt(client, app, [changed, *background], 'Synthetic later fact change after directory reentry')
    found = domain_notices(client, 'tire')
    assert {item['interest_id'] for item in found} == {positive['id']}, 'An old reviewed chain cannot resume merely because the SKU reappeared'
    assert all(item['interest_id'] != watched['id'] for item in found)


def test_review_manual_actual_base_after_304_does_not_require_equal_snapshot_member_version(private_api):
    client, app = private_api
    query_a, query_b = {'size': '265/40ZR20'}, {'model': 'Fixture Tire', 'size': '265/40ZR20'}
    first = adopt(client, app, [tire()], 'Synthetic archived member version one', query=query_a)
    origin = first['variants'][0]['id']
    adopt(client, app, [tire(facts={'utqg_treadwear': 420})], 'Synthetic intervening actual version two', query=query_b)
    app.state.review_registry.result = {'status': 'not_modified',
        'url': 'https://fixture.example/tires/product', 'etag': '"fixture-etag"'}
    response = client.post('/v1/sources/fixture/live-query', json={'query': query_a, 'fallback_policy': 'never'})
    assert response.status_code == 200 and response.json()['data_state'] == 'live_verified_304', response.text
    interest(client, condition('brand', 'Fixture Brand'), changed_fields=['facts.utqg_treadwear'])
    edited = curation(client, origin, value=500)
    assert edited.status_code == 201, edited.text
    with app.state.database.sessions() as db:
        row = db.scalar(select(ManualFactRevision).where(ManualFactRevision.variant_id == origin))
        base = db.get(FactVersion, row.base_fact_id)
        member = next(item for item in db.get(Snapshot, base.snapshot_id).parsed_variants if item['id'] == origin)
        assert base.version == 3 and member['fact_version'] == 1
        assert base.snapshot_id == first['provenance'][0]['snapshot_id']
    found = domain_notices(client, 'tire_curation')
    assert len(found) == 1 and found[0]['match']['state'] == 'matched'
    assert any(ctx['facts'].get('utqg_treadwear') == 300 for ctx in contexts(found[0]['event']['before']))
    assert any(ctx['facts'].get('utqg_treadwear') == 500 for ctx in contexts(found[0]['event']['after']))


def test_review_manual_reconstruction_does_not_apply_an_overlay_from_an_old_base(private_api):
    client, app = private_api
    baseline = tire(facts={'utqg_treadwear': 300, 'tread_depth': {'value': 7, 'unit': 'mm'}})
    first = adopt(client, app, [baseline], 'Synthetic first source base')
    origin = first['variants'][0]['id']
    assert curation(client, origin, value=420).status_code == 201
    changed = tire(facts={'utqg_treadwear': 320, 'tread_depth': {'value': 8, 'unit': 'mm'}})
    adopt(client, app, [changed], 'Synthetic newer source base invalidates the old override')
    interest(client, condition('brand', 'Fixture Brand'), changed_fields=['facts.tread_depth'])
    result = curation(client, origin, field='tread_depth', value={'value': 9, 'unit': 'mm'})
    assert result.status_code == 201, result.text
    found = domain_notices(client, 'tire_curation')
    assert len(found) == 1
    for side in ('before', 'after'):
        matching = [ctx for ctx in contexts(found[0]['event'][side]) if ctx['identity']['brand'] == 'Fixture Brand']
        assert matching and all(ctx['facts'].get('utqg_treadwear') == 320 for ctx in matching)
    assert contexts(found[0]['event']['before'])[0]['facts']['tread_depth']['value'] == 8
    assert contexts(found[0]['event']['after'])[0]['facts']['tread_depth']['value'] == 9


def test_review_exact_reader_reads_original_row_and_excludes_internal_session_fields(private_api):
    client, app = private_api
    accepted = adopt(client, app, [tire()], 'Synthetic reader original source')
    origin = accepted['variants'][0]['id']
    interest(client, condition('brand', 'Fixture Brand'))
    response = curation(client, origin, value=420)
    assert response.status_code == 201, response.text
    record_id = response.json()['history'][0]['id']
    found = domain_notices(client, 'tire_curation')[0]
    reference = next(ref for ref in found['event']['evidence'] if ref['kind'] == 'tire_curation_revision'
                     and ref['record_id'] == record_id)
    reopened = original(client, 'tire_curation_revision', record_id)
    assert reopened.status_code == 200, reopened.text
    body = reopened.json()
    assert body['record_id'] == record_id and body['entity_id'] == origin
    assert body['fingerprint'] == digest(body['record']) == reference['fingerprint']

    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    assert not {'session_id', 'actor_session_id', 'operator_session_id'}.intersection(keys(body['record']))
    # Deliberately corrupt only this private synthetic DB after the positive read.
    # A reader may reject an integrity mismatch or return the actual changed row;
    # it must never serve the saved notification copy as the original source.
    with app.state.database.engine.begin() as connection:
        connection.execute(ManualFactRevision.__table__.update().where(
            ManualFactRevision.id == record_id).values(reason='Synthetic raw-row reader integrity probe'))
    changed = original(client, 'tire_curation_revision', record_id)
    assert changed.status_code in {200, 409}, changed.text
    if changed.status_code == 200:
        assert changed.json()['record']['reason'] == 'Synthetic raw-row reader integrity probe'
        assert changed.json()['fingerprint'] != reference['fingerprint']
    else:
        assert changed.json()['detail']['code'] == 'interest_evidence_mismatch'


@pytest.fixture
def pre017(tmp_path, monkeypatch):
    """Current table shapes/pre-017 ledger, not an exact historical backup."""
    from tire_api.interest_catalog_models import TireCatalogRevision
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
    database = create_app('sqlite:///' + (tmp_path / 'private-pre017.sqlite').as_posix()).state.database
    with database.engine.begin() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables
            if table.name != TireCatalogRevision.__tablename__])
        connection.exec_driver_sql('CREATE TABLE tire_schema_versions '
            '(version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for version in EXPECTED_SCHEMA_VERSIONS[:16]:
            connection.execute(text('INSERT INTO tire_schema_versions (version) VALUES (:version)'), {'version': version})
        for statement in DEVICE_AI_LEDGER_TRIGGERS_SQLITE:
            connection.exec_driver_sql(statement)
        initialize_search(connection)
    with database.sessions() as db:
        seed_legacy(db, namespace='REVIEW-R67', product_code='SYNTHETIC-PRE017', watch=True)
        seed_interest_ledger(db)
    try:
        yield database
    finally:
        database.close()


def test_review_017_preserves_predecessor_schema_rows_and_has_no_notification_backfill(pre017):
    from tire_api.interest_catalog_models import TireCatalogRevision
    from test_ai_stream_migration import snapshot
    from version_registry import EXPECTED_SCHEMA_VERSIONS
    from historical_migration_support import (assert_full_chain_preserved, assert_target_delta,
        assert_trigger_contract, initialize_observing_version)
    before = snapshot(pre017)
    assert_trigger_contract(before, device=True, candidate=False)
    stage = initialize_observing_version(pre017, '017_interest_governance_catalog')
    assert_target_delta(before, stage, {TireCatalogRevision.__tablename__})
    assert_trigger_contract(stage, device=True, candidate=False)
    first = snapshot(pre017)
    pre017.initialize()
    after = snapshot(pre017)
    assert after == first
    assert after['tables'] - before['tables'] == {TireCatalogRevision.__tablename__}
    assert not before['tables'] - after['tables']
    assert_full_chain_preserved(before, after)
    for table in before['tables'] - {'tire_schema_versions'}:
        assert before['rows'][table] == after['rows'][table], table
    assert after['rows'][TireCatalogRevision.__tablename__] == []
    with pre017.engine.connect() as connection:
        assert set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == set(EXPECTED_SCHEMA_VERSIONS)
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('PRAGMA integrity_check').scalar_one() == 'ok'
        constraints = [set(item['column_names']) for item in inspect(connection).get_unique_constraints(
            TireCatalogRevision.__tablename__)]
        assert {'variant_id', 'source_id', 'query_key', 'revision'} in constraints


def test_review_017_ddl_and_schema_version_roll_back_together(pre017, monkeypatch):
    from tire_api import migrations
    from test_ai_stream_migration import snapshot
    before = snapshot(pre017)
    upgrade = migrations.upgrade

    def fail_after_upgrade(connection):
        upgrade(connection)
        raise RuntimeError('synthetic_governance_migration_failure')

    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'upgrade', fail_after_upgrade)
        with pytest.raises(RuntimeError, match='synthetic_governance_migration_failure'):
            pre017.initialize()
    assert snapshot(pre017) == before


def test_review_catalog_has_real_replay_constraints_foreign_keys_and_immutable_rows(private_api):
    from tire_api.interest_catalog_models import TireCatalogRevision
    client, app = private_api
    accepted = adopt(client, app, [tire()], 'Synthetic catalog constraint source')
    origin = accepted['variants'][0]['id']
    with app.state.database.sessions() as db:
        row = db.scalar(select(TireCatalogRevision).where(TireCatalogRevision.variant_id == origin))
        assert row is not None
        record_id = row.id
        payload = {column.name: deepcopy(getattr(row, column.name)) for column in row.__table__.columns
                   if column.name != 'id'}
        with pytest.raises(IntegrityError):
            db.add(TireCatalogRevision(id=uid(), **payload))
            db.flush()
        db.rollback()
        with pytest.raises(IntegrityError):
            db.add(TireCatalogRevision(id=uid(), **{**payload, 'revision': payload['revision'] + 1000,
                                                  'verification_id': 'missing-synthetic-verification'}))
            db.flush()
        db.rollback()
        row = db.get(TireCatalogRevision, record_id)
        row.action = 'removed'
        with pytest.raises(ValueError, match='只能追加'):
            db.flush()
        db.rollback()
        db.delete(db.get(TireCatalogRevision, record_id))
        with pytest.raises(ValueError, match='只能追加'):
            db.flush()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(TireCatalogRevision)) == 1


def test_review_catalog_table_and_indexes_compile_for_postgresql_without_runtime_claim():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable
    from tire_api.interest_catalog_models import TireCatalogRevision
    table = TireCatalogRevision.__table__
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert 'CREATE TABLE tire_catalog_revisions' in ddl
    assert 'FOREIGN KEY(verification_id)' in ddl
    assert 'UNIQUE (variant_id, verification_id)' in ddl
    for index in table.indexes:
        assert str(CreateIndex(index).compile(dialect=postgresql.dialect()))
