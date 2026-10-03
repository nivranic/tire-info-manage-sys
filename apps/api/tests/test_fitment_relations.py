"""Synthetic independent relations, with explicit private storage and no external calls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, inspect, select

from tire_api.db import (Database, FactVersion, GarageRevision, QueryRun, Snapshot, TireVariant,
                         VariantLifecycleEvent, Verification, WatchItem, uid, utcnow)
from tire_api.domain import IDENTITY_CONTRACT_VERSION, VariantInput, digest
from tire_api.identity_contract import resolve_variant
from tire_api.fitment_relation_models import FitmentRelation, FitmentRelationRevision
from tire_api.fitment_relations import RelationDecision, append_revision
from tire_api.identity_models import IdentityRevision
from tire_api.main import create_app
from tire_api.vehicles import (VehicleManufacturer, VehicleModel, VehicleSnapshot, VehicleTrim,
                               VehicleVerification, WheelFitment, fitment_fact_hash)


class NoNetworkRegistry:
    def sources(self):
        return []

    async def fetch(self, *_args, **_kwargs):
        raise AssertionError('fitment relations must never call a source')


def vehicle_payload():
    axle = {'size': '245/40R20', 'load_index': None, 'speed_rating': None, 'oe_mark': None,
            'manufacturer_product_code': None, 'matched_tire_variant_id': None}
    return {'vehicle': {'id': 'synthetic-vehicle-gen1', 'model': 'Synthetic Vehicle', 'generation': 'generation-1',
            'model_year': None, 'region': 'CN', 'source_vehicle_id': 'synthetic-source-gen1',
            'manufacturer': {'id': 'synthetic-maker', 'name': 'Synthetic maker'}},
        'trims': [{'id': 'synthetic-trim', 'name': 'Synthetic trim', 'source_trim_id': 'synthetic-trim',
                   'model_year': None, 'wheel_option_ids': ['synthetic-option']}],
        'fitments': [{'id': 'synthetic-option', 'trim_id': 'synthetic-trim', 'trim_name': 'Synthetic trim',
            'wheel_option_name': 'Synthetic wheel', 'wheel_diameter_inches': 20, 'availability': 'standard',
            'front': axle, 'rear': {**axle, 'size': '265/40R20'}, 'staggered': True,
            'source_tire_description': 'Synthetic tire description', 'constraints': [],
            'source_description': 'Synthetic fixture only', 'evidence_locator': 'fixture raw marker'}],
        'coverage': {'exact_tire_sku': False}, 'footnotes': []}


def tire_payload(**changes):
    value = {'brand': 'Synthetic', 'model': 'Synthetic Tire', 'manufacturer_product_code': 'SYNTHETIC-001',
        'region': 'CN', 'size': '245/40R20', 'load_index': '101', 'speed_rating': 'Y',
        'xl': True, 'hl': False, 'oe_mark': 'SYNTH', 'acoustic_technology': 'Synthetic acoustic',
        'run_flat': False, 'facts': {'utqg_treadwear': 300}, **changes}
    value['facts'] = {'product_code_type': 'MSPN', **value['facts']}
    return value


def run_record(db, session_id, source, key):
    row = QueryRun(id=uid(), session_id=session_id, source_id=source, query_key=key,
                   query={'synthetic': True}, fallback_policy='never', state='live')
    db.add(row)
    db.flush()
    return row


def seed_vehicle(database, session_id, payload=None, *, fact_version=1, observed_at=None):
    payload = deepcopy(payload or vehicle_payload())
    with database.sessions() as db:
        if not db.get(VehicleManufacturer, 'synthetic-maker'):
            db.add(VehicleManufacturer(id='synthetic-maker', name='Synthetic maker'))
            db.flush()
        vehicle = payload['vehicle']
        if not db.get(VehicleModel, vehicle['id']):
            db.add(VehicleModel(id=vehicle['id'], manufacturer_id='synthetic-maker', name=vehicle['model'],
                generation=vehicle['generation'], model_year=vehicle.get('model_year'), region=vehicle['region'],
                source_vehicle_id=vehicle['source_vehicle_id']))
            db.flush()
        for trim in payload['trims']:
            if not db.get(VehicleTrim, trim['id']):
                db.add(VehicleTrim(id=trim['id'], vehicle_id=vehicle['id'], source_trim_id=trim['source_trim_id'],
                    name=trim['name'], model_year=trim.get('model_year')))
        run = run_record(db, session_id, 'synthetic-vehicle-source', vehicle['id'])
        body = json.dumps(payload, ensure_ascii=False)
        snapshot = VehicleSnapshot(id=uid(), vehicle_id=vehicle['id'], source_id=run.source_id,
            source_url='https://fixture.invalid/vehicle', raw_hash=hashlib.sha256(body.encode()).hexdigest(),
            body=body, content_type='application/json', parser_version='synthetic@1', payload=payload,
            fact_hash=fitment_fact_hash(payload), fact_version=fact_version, observed_at=observed_at or utcnow())
        db.add(snapshot)
        db.flush()
        db.add(VehicleVerification(snapshot_id=snapshot.id, query_id=run.id, vehicle_id=vehicle['id'],
                                    verified_at=observed_at or utcnow()))
        db.commit()
        return snapshot.id


def seed_tire(database, session_id, value=None, *, variant_id=None, source='synthetic-tire-source',
              version=1, metadata_only=False, empty=False, observed_at=None, legacy=False):
    value = deepcopy(value or tire_payload())
    parsed = VariantInput.model_validate(value)
    query_key = digest({'synthetic': True}) if legacy else 'synthetic-catalog'
    with database.sessions() as db:
        variant_id = variant_id or uid()
        key, status = (parsed.legacy_identity_key if legacy else parsed.identity_key)(source, query_key, 0)
        if not db.get(TireVariant, variant_id):
            db.add(TireVariant(id=variant_id, identity_key=key,
                              identity=parsed.legacy_identity() if legacy else parsed.identity(), identity_status=status))
            db.flush()
        run = run_record(db, session_id, source, query_key)
        body = json.dumps(value, ensure_ascii=False) + (' metadata' if metadata_only else '')
        snapshot = Snapshot(id=uid(), source_id=source, query_key=run.query_key,
            identity_contract_version=None if legacy else IDENTITY_CONTRACT_VERSION,
            source_url='https://fixture.invalid/tire', raw_hash=hashlib.sha256(body.encode()).hexdigest(), body=body,
            content_type='application/json', parser_version='synthetic@1', observed_at=observed_at or utcnow(),
            parsed_variants=[] if empty else [{**parsed.model_dump(), 'id': variant_id, 'identity_key': key,
                                              'identity_status': status, 'fact_version': version}])
        db.add(snapshot)
        db.flush()
        if not empty and not legacy:
            stored, _, _ = resolve_variant(db, parsed, source, run.query_key, 0, snapshot.id)
            assert stored.id == variant_id
        if not metadata_only and not empty:
            fact = FactVersion(id=uid(), variant_id=variant_id, source_id=source, snapshot_id=snapshot.id,
                facts=parsed.facts, facts_hash=digest(parsed.facts), version=version, observed_at=observed_at or utcnow())
            db.add(fact)
        else:
            fact = db.scalar(select(FactVersion).where(FactVersion.variant_id == variant_id,
                FactVersion.source_id == source, FactVersion.version == version))
        db.add(Verification(snapshot_id=snapshot.id, query_id=run.id, source_id=source, query_key=run.query_key,
                            status='ok', verified_at=observed_at or utcnow()))
        db.commit()
        return variant_id, snapshot.id, fact.id if fact else None


@pytest.fixture
def relation_setup(tmp_path, monkeypatch):
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '0')
    monkeypatch.setenv('TI_OBJECT_STORE_BACKEND', 'filesystem')
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    app = create_app('sqlite:///' + (tmp_path / 'relations.sqlite').as_posix(), NoNetworkRegistry())
    with TestClient(app) as client:
        client.get('/health')
        assert client.post('/v1/auth/register',
                           json={'username': 'admin', 'password': 'fixture-admin-pw'}).status_code == 200
        session_id = client.cookies['tire_local_session']
        database = app.state.database
        vehicle = seed_vehicle(database, session_id)
        variant, tire, fact = seed_tire(database, session_id)
        selection = {'vehicle_id': 'synthetic-vehicle-gen1', 'vehicle_snapshot_id': vehicle,
            'trim_id': 'synthetic-trim', 'wheel_option_id': 'synthetic-option', 'axle': 'front',
            'variant_id': variant, 'tire_snapshot_id': tire, 'fact_version_id': fact}
        yield client, database, session_id, selection


def preview(client, selection, action='create', relation_id=None):
    response = client.post('/v1/fitment-relations/preview', json={'mode': 'history', 'action': action,
        'relation_id': relation_id, 'selection': selection})
    assert response.status_code == 200, response.text
    return response.json()


def decision(client, selection, action='create', relation_id=None):
    proposed = preview(client, selection, action, relation_id)
    return {'mode': 'history', 'action': action, 'relation_id': relation_id, 'selection': selection,
        'expected_revision': proposed['revision'], 'expected_fingerprint': proposed['fingerprint'],
        'operator': '合成关系复核员', 'reason': '仅验证独立关系行为的合成数据，不是生产结论',
        'acknowledged': True, 'acknowledge_unknowns': True}


def post(client, payload, key=None):
    return client.post('/v1/fitment-relations/revisions', json=payload,
                       headers={'Idempotency-Key': key or str(uuid4())})


def read(client, relation_id):
    response = client.get(f'/v1/fitment-relations/{relation_id}?mode=history')
    assert response.status_code == 200, response.text
    return response.json()


def counts(database):
    models = [FactVersion, Snapshot, VehicleSnapshot, WheelFitment, GarageRevision, WatchItem]
    with database.sessions() as db:
        return {model.__name__: db.scalar(select(func.count()).select_from(model)) for model in models}


def test_legacy_evidence_validates_its_schema_then_requires_current_binding(relation_setup):
    client, database, session, selected = relation_setup
    variant, snapshot, fact = seed_tire(database, session,
        tire_payload(manufacturer_product_code='LEGACY-001'), legacy=True)
    selected = {**selected, 'variant_id': variant, 'tire_snapshot_id': snapshot, 'fact_version_id': fact}
    before = preview(client, selected)
    assert not before['can_submit'] and 'identity_contract_review_required' in before['blockers']
    assert 'product_code_type' not in before['tire_evidence']['identity']
    assert before['tire_evidence']['identity_contract_version'] is None
    migration = client.get('/v1/identity-contract/migration-preview?mode=history').json()
    assessment = next(item for item in migration['items'] if item['variant_id'] == variant)
    assert assessment['state'] == 'eligible', assessment['reason_codes']
    request = {'mode': 'history', 'schema': migration['schema'], 'expected_revision': migration['revision'],
        'expected_preview_fingerprint': migration['preview_fingerprint'], 'acknowledged': True,
        'operator': '合成命名空间复核员', 'reason': '仅验证历史schema与权威绑定分别校验'}
    response = client.post('/v1/identity-contract/migration-applications', json=request,
                           headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 201, response.text
    after = preview(client, selected)
    assert after['can_submit'], after['blockers']
    assert after['tire_evidence']['identity'] == before['tire_evidence']['identity']
    assert after['tire_evidence']['identity_contract']['current_identity']['product_code_type'] == 'MSPN'
    with database.sessions() as db:
        assert db.get(Snapshot, snapshot).identity_contract_version is None
        assert db.get(TireVariant, variant).identity == before['tire_evidence']['identity']


def test_freeze_both_roles_locators_local_mode_history_and_no_side_effects(relation_setup, monkeypatch):
    client, database, _, selected = relation_setup
    import aiohttp
    monkeypatch.setattr(aiohttp, 'ClientSession', lambda *_a, **_k: pytest.fail('unexpected network/model call'))
    before = counts(database)
    snapshots = client.get('/v1/fitment-relations/vehicle-snapshots?mode=history').json()
    assert snapshots['total'] == 1 and snapshots['items'][0]['id'] == selected['vehicle_snapshot_id']
    assert snapshots['scope'] == 'local_workspace'
    vehicle = client.get('/v1/fitment-relations/vehicle-snapshots/' + selected['vehicle_snapshot_id'] + '?mode=history').json()
    assert vehicle['fitments'][0]['id'] == selected['wheel_option_id']
    tire = client.get('/v1/fitment-relations/tire-evidence/' + selected['variant_id'] + '?mode=history').json()
    assert tire['items'][0]['fact_version_id'] == selected['fact_version_id']
    result = preview(client, selected)
    assert result['can_submit'] and result['official_oe']['state'] == 'not_established'
    assert result['vehicle_evidence']['structured_locator']['json_pointer'] == '/fitments/0/front'
    assert result['tire_evidence']['structured_locator']['json_pointer'] == '/parsed_variants/0'
    assert result['vehicle_evidence']['requirements'].get('xl') is None
    assert next(item for item in result['checks'] if item['field'] == 'xl')['status'] == 'not_declared'
    assert post(client, {**decision(client, selected), 'acknowledge_unknowns': False}).status_code == 422
    response = post(client, decision(client, selected))
    assert response.status_code == 201, response.text
    relation = response.json()['relation']
    assert relation['review_state'] == 'pending_review' and not relation['needs_review']
    assert relation['history'][0]['before'] is None
    assert 'actor_session_id' not in relation['history'][0]
    assert relation['vehicle_evidence']['role'] == 'vehicle_requirement'
    assert relation['tire_evidence']['role'] == 'tire_sku_fact'
    reviewed = post(client, decision(client, selected, 'review', relation['id'])).json()['relation']
    assert reviewed['review_state'] == 'reviewed' and reviewed['official_oe']['state'] == 'not_established'
    assert reviewed['history'][0]['before']['review_state'] == 'pending_review'
    assert counts(database) == before
    for url in ['/v1/fitment-relations', '/v1/fitment-relations/' + relation['id'],
                '/v1/fitment-relations/vehicle-snapshots',
                '/v1/fitment-relations/tire-evidence/' + selected['variant_id']]:
        assert client.get(url).status_code == 422
    assert client.get('/v1/fitment-relations?mode=history&state=reviewed&axle=front&limit=1').json()['total'] == 1


@pytest.mark.parametrize('field,value,code', [
    ('vehicle_id', 'other-generation', 'vehicle_snapshot_scope_mismatch'),
    ('trim_id', 'other-trim', 'vehicle_fitment_missing'),
    ('wheel_option_id', 'other-option', 'vehicle_fitment_missing'),
    ('variant_id', 'other-sku', 'tire_variant_evidence_mismatch'),
    ('fact_version_id', 'unrelated', 'tire_fact_evidence_mismatch'),
    ('vehicle_snapshot_id', 'unaccepted', 'vehicle_snapshot_not_accepted'),
    ('tire_snapshot_id', 'unaccepted', 'tire_snapshot_not_accepted'),
])
def test_exact_two_sided_scope_cannot_be_borrowed(relation_setup, field, value, code):
    client, _, _, selected = relation_setup
    response = client.post('/v1/fitment-relations/preview', json={'mode': 'history', 'action': 'create',
        'selection': {**selected, field: value}})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == code


@pytest.mark.parametrize('changes,expected', [({'region': 'US'}, 'conflict_region'),
    ({'size': '245/40ZR20'}, 'conflict_size'), ({'size': '265/40R20'}, 'conflict_size')])
def test_market_r_zr_and_front_rear_conflicts_are_blocked(relation_setup, changes, expected):
    client, database, session, selected = relation_setup
    variant, snapshot, fact = seed_tire(database, session, tire_payload(**changes), source='other-source')
    selected = {**selected, 'variant_id': variant, 'tire_snapshot_id': snapshot, 'fact_version_id': fact}
    proposed = preview(client, selected)
    assert expected in proposed['blockers'] and not proposed['can_submit']
    assert post(client, decision(client, selected)).status_code == 409


@pytest.mark.parametrize('field,value', [('load_index', '99'), ('speed_rating', 'W'),
    ('manufacturer_product_code', 'DIFFERENT-CODE'), ('oe_mark', 'DIFFERENT-OE')])
def test_known_axle_requirements_strictly_conflict(relation_setup, field, value):
    client, database, session, selected = relation_setup
    vehicle = vehicle_payload()
    vehicle['fitments'][0]['front'][field] = value
    selected['vehicle_snapshot_id'] = seed_vehicle(database, session, vehicle, fact_version=2)
    proposed = preview(client, selected)
    assert 'conflict_' + field in proposed['blockers']
    assert post(client, decision(client, selected)).status_code == 409


def test_unavailable_wheel_and_cross_axle_change(relation_setup):
    client, database, session, selected = relation_setup
    relation = post(client, decision(client, selected)).json()['relation']
    other = {**selected, 'axle': 'rear'}
    proposed = preview(client, other, 'revise', relation['id'])
    assert 'fixed_relation_scope_mismatch' in proposed['blockers']
    vehicle = vehicle_payload()
    vehicle['fitments'][0]['availability'] = 'unavailable'
    selected = {**selected, 'vehicle_snapshot_id': seed_vehicle(database, session, vehicle, fact_version=2)}
    assert 'wheel_option_unavailable' in preview(client, selected)['blockers']
    assert post(client, decision(client, selected)).status_code == 409


def test_revision_history_is_immutable_and_multiple_skus_per_axle(relation_setup):
    client, database, session, selected = relation_setup
    relation = post(client, decision(client, selected)).json()['relation']
    first = relation['history'][0]
    second, snapshot, fact = seed_tire(database, session, tire_payload(manufacturer_product_code='SYNTHETIC-002'), source='second-source')
    other = {**selected, 'variant_id': second, 'tire_snapshot_id': snapshot, 'fact_version_id': fact}
    assert post(client, decision(client, other)).status_code == 201
    assert client.get('/v1/fitment-relations?mode=history&axle=front').json()['total'] == 2
    result = post(client, decision(client, other, 'revise', relation['id']))
    assert result.status_code == 201, result.text
    changed = result.json()['relation']
    assert changed['variant_id'] == second and changed['review_state'] == 'pending_review'
    assert changed['history'][1] == first
    for model in [FitmentRelation, FitmentRelationRevision]:
        with database.sessions() as db:
            row = db.scalar(select(model))
            if model is FitmentRelation:
                row.axle = 'rear'
            else:
                row.reason = 'Overwrite attempt'
            with pytest.raises(ValueError, match='只能追加'):
                db.commit()
            db.rollback()
            db.delete(db.scalar(select(model)))
            with pytest.raises(ValueError, match='只能追加'):
                db.commit()


def test_idempotent_replay_after_revoke_and_payload_mismatch(relation_setup):
    client, database, _, selected = relation_setup
    payload, key = decision(client, selected), str(uuid4())
    original = post(client, payload, key).json()
    rid = original['relation']['id']
    assert post(client, decision(client, selected, 'revoke', rid)).status_code == 201
    repeated = post(client, payload, key).json()
    assert repeated['idempotent_replay'] and repeated['event'] == original['event']
    assert repeated['relation']['review_state'] == 'revoked'
    assert post(client, {**payload, 'reason': 'changed payload test'}, key).status_code == 409
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(FitmentRelationRevision)) == 2
    restored = post(client, decision(client, selected, 'restore', rid)).json()['relation']
    assert restored['review_state'] == 'pending_review' and restored['revision'] == 3


@pytest.mark.parametrize('same_key', [True, False])
def test_concurrent_revisions_serialize_and_replay(relation_setup, same_key):
    client, database, session, selected = relation_setup
    rid = post(client, decision(client, selected)).json()['relation']['id']
    payload = RelationDecision(**decision(client, selected, 'review', rid))
    gate, key = Barrier(2), str(uuid4())
    def execute(_):
        with database.sessions() as db:
            gate.wait(timeout=10)
            try:
                result = append_revision(db, payload, session, key if same_key else str(uuid4()))
                return 201, result['idempotent_replay']
            except HTTPException as error:
                return error.status_code, False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, range(2)))
    assert sorted(code for code, _ in results) == ([201, 201] if same_key else [201, 409])
    assert sum(replay for _, replay in results) == int(same_key)
    assert read(client, rid)['revision'] == 2


def test_stale_facts_close_review_but_allow_revoke_and_require_new_evidence(relation_setup):
    client, database, session, selected = relation_setup
    rid = post(client, decision(client, selected)).json()['relation']['id']
    stale_request = decision(client, selected, 'review', rid)
    _, snapshot, fact = seed_tire(database, session, tire_payload(facts={'utqg_treadwear': 400}),
                                  variant_id=selected['variant_id'], version=2)
    changed = read(client, rid)
    assert changed['effective_state'] == 'needs_review' and 'tire_facts_changed' in changed['stale_reasons']
    assert post(client, stale_request).status_code == 409
    assert post(client, decision(client, selected, 'review', rid)).status_code == 409
    assert post(client, decision(client, selected, 'revoke', rid)).status_code == 201
    assert post(client, decision(client, selected, 'restore', rid)).status_code == 409
    # A revoked record retains its original evidence and is not silently retargeted.
    assert read(client, rid)['variant_id'] == selected['variant_id']
    updated = {**selected, 'tire_snapshot_id': snapshot, 'fact_version_id': fact}
    assert preview(client, updated)['can_submit']
    revised = post(client, decision(client, updated, 'revise', rid))
    assert revised.status_code == 201, revised.text
    assert revised.json()['relation']['review_state'] == 'revoked'
    restored = post(client, decision(client, updated, 'restore', rid))
    assert restored.status_code == 201 and restored.json()['relation']['review_state'] == 'pending_review'


def test_vehicle_scope_change_stales_and_new_generation_cannot_revise(relation_setup):
    client, database, session, selected = relation_setup
    rid = post(client, decision(client, selected)).json()['relation']['id']
    value = vehicle_payload()
    value['vehicle']['generation'] = 'generation-2'
    snapshot = seed_vehicle(database, session, value, fact_version=2)
    assert read(client, rid)['effective_state'] == 'needs_review'
    assert 'vehicle_evidence_stale' in preview(client, selected, 'review', rid)['blockers']
    proposed = preview(client, {**selected, 'vehicle_snapshot_id': snapshot}, 'revise', rid)
    assert 'fixed_relation_scope_mismatch' in proposed['blockers']


@pytest.mark.parametrize('kind', ['lifecycle', 'identity', 'catalog'])
def test_lifecycle_identity_or_removed_catalog_close_operations(relation_setup, kind):
    client, database, session, selected = relation_setup
    rid = post(client, decision(client, selected)).json()['relation']['id']
    if kind == 'catalog':
        seed_tire(database, session, variant_id=selected['variant_id'], empty=True)
    else:
        with database.sessions() as db:
            if kind == 'lifecycle':
                db.add(VariantLifecycleEvent(id=uid(), variant_id=selected['variant_id'], revision=1,
                    action='revoke', before_state='active', after_state='revoked', operator_session_id=session,
                    operator='Synthetic', reason='Synthetic local revocation', evidence=[]))
            else:
                db.add(IdentityRevision(id=uid(), variant_id=selected['variant_id'], target_id=None, revision=1,
                    action='correct', binding={}, binding_hash=digest({}), differences=[], field_reasons={},
                    acknowledged_unknowns=True, evidence=[], operator='Synthetic', reason='Synthetic redirect',
                    actor_session_id=session, idempotency_key=str(uuid4()), request_hash=digest({})))
            db.commit()
    assert read(client, rid)['effective_state'] == 'needs_review'
    assert not preview(client, selected)['can_submit']
    assert post(client, decision(client, selected, 'review', rid)).status_code == 409
    assert post(client, decision(client, selected, 'revoke', rid)).status_code == 201
    assert post(client, decision(client, selected, 'restore', rid)).status_code == 409


def test_304_metadata_locators_do_not_stale_and_no_wheel_rows_required(relation_setup):
    client, database, session, selected = relation_setup
    rid = post(client, decision(client, selected)).json()['relation']['id']
    with database.sessions() as db:
        run = run_record(db, session, 'synthetic-tire-source', 'synthetic-catalog')
        db.add(Verification(snapshot_id=selected['tire_snapshot_id'], query_id=run.id,
            source_id=run.source_id, query_key=run.query_key, status='live_verified_304', verified_at=utcnow()))
        db.commit()
    assert not read(client, rid)['needs_review']
    vehicle = vehicle_payload()
    vehicle['vehicle']['source_version'] = 'metadata-2'
    vehicle['fitments'][0]['evidence_locator'] = 'new unrelated raw marker'
    vehicle['fitments'][0]['source_description'] = 'new prose'
    vehicle_snapshot = seed_vehicle(database, session, vehicle)
    variant, snapshot, fact = seed_tire(database, session, variant_id=selected['variant_id'], metadata_only=True)
    assert not read(client, rid)['needs_review']
    updated = {**selected, 'vehicle_snapshot_id': vehicle_snapshot, 'tire_snapshot_id': snapshot, 'fact_version_id': fact}
    proposed = preview(client, updated)
    assert proposed['can_submit'] and proposed['vehicle_evidence']['source_locator_marker'] == 'new unrelated raw marker'
    assert post(client, decision(client, updated)).status_code == 201
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(WheelFitment)) == 0
        assert db.scalar(select(func.count()).select_from(FactVersion)) == 1
    items = client.get('/v1/fitment-relations/tire-evidence/' + variant + '?mode=history').json()['items']
    assert {row['fact_version_id'] for row in items} == {fact}


def test_other_source_fact_version_cannot_be_attached_and_raw_hash_checked(relation_setup):
    client, database, session, selected = relation_setup
    _, _, wrong_fact = seed_tire(database, session, variant_id=selected['variant_id'], source='another-source')
    response = client.post('/v1/fitment-relations/preview', json={'mode': 'history', 'action': 'create',
        'selection': {**selected, 'fact_version_id': wrong_fact}})
    assert response.status_code == 422 and response.json()['detail']['code'] == 'tire_fact_evidence_mismatch'
    # Simulate out-of-band corruption, rather than bypassing normal ORM guards.
    with database.engine.begin() as connection:
        connection.exec_driver_sql('UPDATE snapshots SET raw_hash = ? WHERE id = ?', ('f' * 64, selected['tire_snapshot_id']))
    response = client.post('/v1/fitment-relations/preview', json={'mode': 'history', 'action': 'create', 'selection': selected})
    assert response.status_code == 422 and response.json()['detail']['code'] == 'evidence_raw_hash_mismatch'


def test_matching_product_code_and_oe_still_never_establish_official_bridge(relation_setup):
    client, database, session, selected = relation_setup
    vehicle = vehicle_payload()
    for key in ('manufacturer_product_code', 'oe_mark', 'load_index', 'speed_rating'):
        vehicle['fitments'][0]['front'][key] = tire_payload()[key]
    selected['vehicle_snapshot_id'] = seed_vehicle(database, session, vehicle, fact_version=2)
    rid = post(client, decision(client, selected)).json()['relation']['id']
    relation = post(client, decision(client, selected, 'review', rid)).json()['relation']
    assert relation['official_oe']['state'] == 'not_established' and relation['official_oe']['missing_evidence']
    assert post(client, {**decision(client, selected, 'review', rid), 'official_oe': True}).status_code == 422


def test_non_web_initialize_creates_new_tables_preserving_evidence(tmp_path):
    path = tmp_path / 'non-web.sqlite'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE preserved_legacy_marker (value TEXT NOT NULL)')
        connection.execute("INSERT INTO preserved_legacy_marker VALUES ('synthetic prior data')")
    environment = {**os.environ, 'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0',
        'TI_OBJECT_STORE_BACKEND': 'filesystem', 'TI_OBJECT_STORE_ROOT': str(tmp_path / 'objects'),
        'TI_PARSER_BUNDLE_ROOT': str(tmp_path / 'bundles'),
        'TIRE_DATABASE_URL': 'sqlite:///' + path.as_posix(), 'DATABASE_URL': 'sqlite:///' + path.as_posix()}
    code = """import os, sys
from tire_api.db import Database
from sqlalchemy import inspect, text
assert 'tire_api.main' not in sys.modules
database = Database(os.environ['TIRE_DATABASE_URL'])
database.initialize()
assert {'fitment_relations', 'fitment_relation_revisions'} <= set(inspect(database.engine).get_table_names())
with database.engine.connect() as connection:
    assert connection.execute(text('SELECT value FROM preserved_legacy_marker')).scalar() == 'synthetic prior data'
assert 'tire_api.main' not in sys.modules
database.close()
"""
    result = subprocess.run([sys.executable, '-c', code], env=environment, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr


def test_shared_history_never_exposes_another_session_auth_cookie(relation_setup):
    client, database, session, selected = relation_setup
    created = post(client, decision(client, selected))
    rid = created.json()['relation']['id']
    other = TestClient(client.app)
    try:
        viewed = other.get('/v1/fitment-relations/' + rid + '?mode=history')
        other_session = other.cookies['tire_local_session']
        assert other_session != session and viewed.status_code == 200
        for response in [created, viewed, other.get('/v1/fitment-relations?mode=history')]:
            assert session not in response.text and other_session not in response.text
            assert 'actor_session_id' not in response.text
        with database.sessions() as db:
            assert db.scalar(select(FitmentRelationRevision)).actor_session_id == session
    finally:
        other.close()


@pytest.mark.parametrize('kind', ['tire_facts', 'vehicle_facts', 'catalog'])
def test_semantic_aba_never_silently_restores_reviewed_or_old_preview(relation_setup, kind):
    client, database, session, selected = relation_setup
    rid = post(client, decision(client, selected)).json()['relation']['id']
    assert post(client, decision(client, selected, 'review', rid)).status_code == 201
    old_request = decision(client, selected, 'review', rid)
    later = utcnow() + timedelta(seconds=1)
    if kind == 'tire_facts':
        seed_tire(database, session, tire_payload(facts={'utqg_treadwear': 400}),
                  variant_id=selected['variant_id'], version=2)
        seed_tire(database, session, variant_id=selected['variant_id'], version=3, observed_at=later)
    elif kind == 'vehicle_facts':
        value = vehicle_payload()
        value['fitments'][0]['front']['load_index'] = '100'
        seed_vehicle(database, session, value, fact_version=2)
        seed_vehicle(database, session, fact_version=3, observed_at=later)
    else:
        seed_tire(database, session, variant_id=selected['variant_id'], empty=True)
        seed_tire(database, session, variant_id=selected['variant_id'], metadata_only=True, observed_at=later)
    relation = read(client, rid)
    assert relation['review_state'] == 'reviewed' and relation['effective_state'] == 'needs_review'
    assert post(client, old_request).status_code == 409
    # Explicit new human review can rebind the current semantic revision to the
    # unchanged accepted historical values; it remains non-official evidence.
    assert post(client, decision(client, selected, 'review', rid)).status_code == 201
    assert read(client, rid)['effective_state'] == 'reviewed'
