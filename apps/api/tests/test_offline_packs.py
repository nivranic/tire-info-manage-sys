"""Private synthetic offline freeze/ownership/capacity counterexamples."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from tire_api.db import EvidenceObject, QueryRun, Snapshot, Verification, uid, utcnow
from tire_api.main import create_app
from tire_api.offline_models import OfflinePack, OfflinePackPlan
from test_core import FixtureRegistry, live
from test_garage import PROFILE


EMPTY_SCOPE = {'garage': {'include': False}, 'watchlist': {'include': False}, 'recent': {'include': False}, 'references': []}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for key in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(key, '0')
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    registry = FixtureRegistry()
    app = create_app('sqlite:///' + (tmp_path / 'offline.sqlite').as_posix(), registry)
    with TestClient(app) as client:
        yield client, registry, app.state.database


def plan(client, scope=None, **kw):
    response = client.post('/v1/offline-pack-plans', json={'mode': 'history', **({'scope': scope} if scope else {}), **kw})
    assert response.status_code == 201, response.text
    return response.json()


def confirm(client, prepared, key=None, **kw):
    return client.post('/v1/offline-packs', headers={'Idempotency-Key': key or uid()}, json={
        'plan_id': prepared['id'], 'expected_fingerprint': prepared['fingerprint'], 'allow_device_storage': True, **kw})


def download(client, descriptor):
    response = client.get(descriptor['download_path'])
    assert response.status_code == 200, response.text
    assert len(response.content) == descriptor['byte_count'] == int(response.headers['content-length'])
    assert hashlib.sha256(response.content).hexdigest() == descriptor['sha256']
    assert response.headers['etag'] == '"' + descriptor['sha256'] + '"'
    assert response.headers['cache-control'] == 'no-store'
    return response.content, response.json()


def test_confirm_freezes_exact_reviewed_bytes_and_receipt_no_latest_reresolution(setup):
    client, registry, database = setup
    original = live(client).json()
    prepared = plan(client)
    assert prepared['can_confirm'] and prepared['counts']['distinct_evidence'] == 1
    with database.sessions() as db:
        receipt = db.scalar(select(Verification))
        saved_id = receipt.id
        # A new formal same-snapshot receipt arrives after preview.
        db.add(Verification(snapshot_id=receipt.snapshot_id, query_id=receipt.query_id,
            source_id=receipt.source_id, query_key=receipt.query_key, status='not_modified',
            parser_identity=receipt.parser_identity, verified_at=utcnow() + timedelta(seconds=10)))
        db.commit()
    calls = len(registry.calls)
    descriptor = confirm(client, prepared).json()
    raw, envelope = download(client, descriptor)
    assert descriptor['sha256'] == prepared['content_sha256']
    assert envelope['members'][0]['reference']['verification_id'] == saved_id
    assert b'fixture-body-v1' not in raw and b'actor_session_id' not in raw
    assert envelope['members'][0]['raw_included'] is False
    assert envelope['members'][0]['source']['raw_hash'] == original['provenance'][0]['raw_hash']
    assert len(registry.calls) == calls


def test_owner_expiry_fingerprint_storage_consent_and_uuid_replay(setup, monkeypatch):
    client, _, database = setup
    prepared = plan(client, EMPTY_SCOPE)
    assert confirm(client, prepared, allow_device_storage=False).status_code == 422
    assert confirm(client, prepared, allow_device_storage=1).status_code == 422
    assert confirm(client, prepared, expected_fingerprint='0' * 64).status_code == 409
    other = TestClient(client.app)
    assert other.get('/v1/offline-pack-plans/' + prepared['id'] + '?mode=history').status_code == 404
    assert confirm(other, prepared).status_code == 404
    key = uid()
    descriptor = confirm(client, prepared, key).json()
    assert confirm(client, prepared, key).json() == descriptor
    assert confirm(client, prepared, key, expected_fingerprint='1' * 64).status_code == 409
    assert other.get(descriptor['download_path']).status_code == 404
    later = plan(client, EMPTY_SCOPE)
    import tire_api.offline_packs as module
    monkeypatch.setattr(module, 'utcnow', lambda: utcnow() + timedelta(minutes=11))
    assert confirm(client, later).status_code == 409
    # Replay is a receipt lookup, even after the original planning deadline.
    assert confirm(client, prepared, key).json() == descriptor
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(OfflinePack)) == 1


def test_default_keeps_workspace_garage_but_watch_and_recent_are_session_scoped(setup):
    client, _, database = setup
    data = live(client).json()
    variant_id = data['variants'][0]['id']
    assert client.post('/v1/watchlists', json={'variant_id': variant_id}).status_code < 300
    garage = client.post('/v1/garage', json=deepcopy(PROFILE)).json()
    first = plan(client)
    assert first['counts']['garage_profiles'] == first['counts']['watch_items'] == first['counts']['recent_queries'] == 1
    garage_context = next(row for row in first['contexts'] if row['kind'] == 'garage')
    assert garage_context['payload']['profile']['nickname'] == PROFILE['nickname']
    assert garage_context['payload']['profile'] == PROFILE
    assert any(row['title'] == PROFILE['nickname'] and row['category'] == 'garage' for row in first['documents'])
    assert not any('actor_session_id' in json.dumps(row) for row in first['contexts'])
    other = TestClient(client.app)
    second = plan(other)
    assert second['counts']['garage_profiles'] == 1
    assert second['counts']['watch_items'] == second['counts']['recent_queries'] == 0
    _, envelope = download(other, confirm(other, second).json())
    assert second['contexts'] == envelope['contexts'] and second['documents'] == envelope['documents']
    assert envelope['contexts'][0]['payload']['vehicle_id'] == garage['id']
    assert envelope['contexts'][0]['scope'] == 'local_workspace'


def test_recent_failed_query_does_not_borrow_historical_snapshot(setup):
    client, registry, _ = setup
    live(client)
    registry.result = {'status': 'unavailable', 'reason': 'synthetic_offline'}
    failed = live(client).json()
    scope = deepcopy(EMPTY_SCOPE)
    scope['recent'] = {'include': True, 'limit': 1}
    prepared = plan(client, scope)
    assert prepared['counts']['distinct_evidence'] == 0
    assert any(x['object_id'] == failed['query_id'] and x['reason'] == 'query_has_no_formal_receipt' for x in prepared['omissions'])


def test_actual_byte_limit_blocks_without_cutting_reviewed_scope(setup, monkeypatch):
    client, _, _ = setup
    live(client)
    import tire_api.offline_packs as module
    monkeypatch.setitem(module.CAPACITY, 'max_package_bytes', 100)
    prepared = plan(client)
    assert prepared['measured_bytes'] > 100 and not prepared['can_confirm']
    assert len(prepared['resolved']) == 1 and prepared['content_sha256'] is None
    assert confirm(client, prepared).status_code == 409


def test_missing_explicit_evidence_and_unknown_fields_block(setup):
    client, _, _ = setup
    scope = deepcopy(EMPTY_SCOPE)
    scope['references'] = [{'kind': 'tire', 'snapshot_id': 'missing', 'variant_id': 'missing'}]
    prepared = plan(client, scope)
    assert not prepared['can_confirm'] and prepared['omissions'][0]['blocking']
    assert client.post('/v1/offline-pack-plans', json={'mode': 'history', 'raw_policy': 'authorized_only'}).status_code == 422


def test_manual_update_keeps_old_package_and_describes_changed_receipt(setup):
    client, _, database = setup
    live(client)
    first = plan(client)
    old = confirm(client, first).json()
    original, _ = download(client, old)
    with database.sessions() as db:
        receipt = db.scalar(select(Verification))
        db.add(Verification(snapshot_id=receipt.snapshot_id, query_id=receipt.query_id,
            source_id=receipt.source_id, query_key=receipt.query_key, status='not_modified',
            parser_identity=receipt.parser_identity, verified_at=utcnow() + timedelta(seconds=10)))
        db.commit()
    scope = deepcopy(EMPTY_SCOPE)
    scope['references'] = [{k: v for k, v in first['resolved'][0]['reference'].items() if k != 'verification_id'}]
    updated = plan(client, scope, base_pack_id=old['id'])
    assert updated['diff']['changed']
    new = confirm(client, updated).json()
    assert new['id'] != old['id'] and download(client, old)[0] == original


def test_corrupt_object_returns_sanitized_failure_after_owner_check(setup):
    client, _, database = setup
    prepared = plan(client, EMPTY_SCOPE)
    descriptor = confirm(client, prepared).json()
    database.object_store.path(descriptor['sha256']).write_bytes(b'corrupt')
    assert TestClient(client.app).get(descriptor['download_path']).status_code == 404
    response = client.get(descriptor['download_path'])
    assert response.status_code == 503 and str(database.object_store.root) not in response.text


def seed_domains(client, database):
    """Normalized synthetic material only; no Parser even for fixture seeding."""
    from tire_api.db import UserSession
    from tire_api.domain import digest
    from tire_api.recall_models import RecallRevision, RecallSnapshot, RecallVerification, SOURCE_ID
    from tire_api.recalls import canonical_records, campaign_url
    from tire_api.vehicles import VehicleManufacturer, VehicleModel, VehicleSnapshot, VehicleVerification, fitment_fact_hash
    from test_recalls import record, CAMPAIGN
    from test_test_events import PAYLOAD
    event = client.post('/v1/test-events', json=deepcopy(PAYLOAD)).json()
    refs = [{'kind': 'test_event', 'event_id': event['id'], 'event_revision': event['revision']}]
    with database.sessions() as db:
        session_id = db.scalar(select(UserSession.id).order_by(UserSession.created_at.desc()))
        def query(source, value):
            run = QueryRun(id=uid(), session_id=session_id, source_id=source, query=value,
                query_key=digest(value), fallback_policy='never', state='live')
            db.add(run)
            db.flush()
            return run
        rows = canonical_records([{**record('Model A'), 'make': 'Brand A'},
                                  {**record('Model B'), 'make': 'Brand B'}], CAMPAIGN)
        origin_id, revision_id = uid(), uid()
        for index in range(2):
            run = query(SOURCE_ID, {'campaign_number': CAMPAIGN})
            raw = 'Synthetic recall raw canary ' + str(index)
            snapshot = RecallSnapshot(id=origin_id if index == 0 else uid(), source_id=SOURCE_ID,
                campaign_number=CAMPAIGN, query_key=run.query_key, source_url=campaign_url(CAMPAIGN),
                raw_hash=hashlib.sha256(raw.encode()).hexdigest(), body=raw, content_type='application/json',
                parser_version='synthetic@1', parser_identity=None, records=rows, records_hash=digest(rows), revision=1)
            db.add(snapshot)
            db.flush()
            receipt = RecallVerification(id=uid(), snapshot_id=snapshot.id, query_id=run.id,
                query_key=run.query_key, status='ok', parser_identity=None)
            db.add(receipt)
            if index == 0:
                db.add(RecallRevision(id=revision_id, campaign_number=CAMPAIGN, revision=1,
                    snapshot_id=origin_id, previous_snapshot_id=None, records_hash=digest(rows), records=rows))
            else:
                refs.append({'kind': 'recall', 'snapshot_id': snapshot.id,
                             'recall_revision_id': revision_id, 'verification_id': receipt.id})
        run = query(SOURCE_ID, {'campaign_number': CAMPAIGN})
        raw = 'Synthetic empty recall canary'
        empty = RecallSnapshot(id=uid(), source_id=SOURCE_ID, campaign_number=CAMPAIGN,
            query_key=run.query_key, source_url=campaign_url(CAMPAIGN), raw_hash=hashlib.sha256(raw.encode()).hexdigest(),
            body=raw, content_type='application/json', parser_version='synthetic@1', parser_identity=None,
            records=[], records_hash=digest([]), revision=None)
        db.add(empty)
        db.flush()
        receipt = RecallVerification(id=uid(), snapshot_id=empty.id, query_id=run.id,
            query_key=run.query_key, status='ok', parser_identity=None)
        db.add(receipt)
        refs.append({'kind': 'recall', 'snapshot_id': empty.id, 'recall_revision_id': None, 'verification_id': receipt.id})
        manufacturer_id, vehicle_id, trim_id, fitment_id = uid(), uid(), uid(), uid()
        db.add(VehicleManufacturer(id=manufacturer_id, name='Synthetic OEM'))
        db.flush()
        db.add(VehicleModel(id=vehicle_id, manufacturer_id=manufacturer_id, name='Synthetic Car',
            generation='Synthetic generation', model_year=2026, region='CN', source_vehicle_id='synthetic-vehicle'))
        db.flush()
        payload = {'vehicle': {'id': vehicle_id, 'manufacturer': {'id': manufacturer_id, 'name': 'Synthetic OEM'},
            'model': 'Synthetic Car', 'generation': 'Synthetic generation', 'model_year': 2026,
            'region': 'CN', 'source_vehicle_id': 'synthetic-vehicle'},
            'trims': [{'id': trim_id, 'name': 'Synthetic trim', 'source_trim_id': 'synthetic-trim',
                      'model_year': 2026, 'wheel_option_ids': [fitment_id]}],
            'fitments': [{'id': fitment_id, 'trim_id': trim_id, 'trim_name': 'Synthetic trim',
                'wheel_option_name': 'Synthetic wheel', 'availability': 'standard', 'wheel_diameter_inches': 20,
                'front': {'size': '245/40R20'}, 'rear': {'size': '245/40R20'}, 'staggered': False,
                'constraints': [], 'source_description': 'Synthetic size only, no tire SKU or OE assertion',
                'evidence_locator': 'synthetic/config/wheel'}], 'footnotes': ['Synthetic fixture only'],
            'documents': [{'url': 'https://fixture.example/full.pdf', 'body': 'FULL PDF MUST BE EXCLUDED'}]}
        run = query('synthetic-oem', {'vehicle_id': vehicle_id})
        raw = 'Synthetic vehicle raw canary'
        vehicle = VehicleSnapshot(id=uid(), vehicle_id=vehicle_id, source_id=run.source_id,
            source_url='https://fixture.example/vehicle', raw_hash=hashlib.sha256(raw.encode()).hexdigest(),
            body=raw, content_type='application/json', parser_version='synthetic@1', parser_identity=None,
            payload=payload, fact_hash=fitment_fact_hash(payload), fact_version=1)
        db.add(vehicle)
        db.flush()
        receipt = VehicleVerification(id=uid(), snapshot_id=vehicle.id, query_id=run.id, vehicle_id=vehicle_id,
                                      parser_identity=None)
        db.add(receipt)
        refs.append({'kind': 'vehicle', 'snapshot_id': vehicle.id, 'verification_id': receipt.id})
        db.commit()
    return refs, origin_id


def test_all_domains_exact_revision_origin_empty_recall_and_per_record_search(setup):
    client, _, database = setup
    live(client)
    refs, origin_id = seed_domains(client, database)
    scope = deepcopy(EMPTY_SCOPE)
    scope['references'] = refs
    prepared = plan(client, scope)
    assert prepared['can_confirm'], prepared['omissions']
    raw, envelope = download(client, confirm(client, prepared).json())
    assert envelope['privacy_class'] == 'restricted'
    assert all(bad not in raw for bad in (b'Fixture reviewer', b'FULL PDF', b'raw canary', b'actor_session_id'))
    recall = next(x for x in envelope['members'] if x['reference']['kind'] == 'recall' and x['payload']['records'])
    assert recall['payload']['evidence']['revision_snapshot_id'] == origin_id
    assert recall['payload']['evidence']['snapshot_id'] != origin_id
    assert recall['payload']['boundary']['applicability'] == 'not_assessed'
    recall_docs = [x for x in envelope['documents'] if x['member_key'] == recall['key']]
    assert len(recall_docs) == 2
    assert not any(x['facets']['brand'] == 'Brand A' and x['facets']['model'] == 'Model B' for x in recall_docs)
    empty = next(x for x in envelope['members'] if x['reference']['kind'] == 'recall' and not x['payload']['records'])
    assert empty['reference']['recall_revision_id'] is None and len(empty['payload']['facts']) == 4
    assert all(x['scope'] == 'observation' for x in empty['payload']['facts'])
    event = next(x for x in envelope['members'] if x['reference']['kind'] == 'test_event')
    assert event['payload']['metadata']['verification_status'] == 'unverified'
    assert event['source']['verified_at'] is None
    assert len([x for x in envelope['documents'] if x['member_key'] == event['key']]) == 2
    vehicle = next(x for x in envelope['members'] if x['reference']['kind'] == 'vehicle')
    assert vehicle['payload']['excluded_document_count'] == 1
    assert 'documents' not in vehicle['payload']


def test_concurrent_same_uuid_creates_exactly_one_package(setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from tire_api.offline_packs import ConfirmRequest, confirm_plan
    client, _, database = setup
    prepared = plan(client, EMPTY_SCOPE)
    with database.sessions() as db:
        owner = db.get(OfflinePackPlan, prepared['id']).actor_session_id
    payload = ConfirmRequest(plan_id=prepared['id'], expected_fingerprint=prepared['fingerprint'], allow_device_storage=True)
    key, barrier = uid(), Barrier(3)
    def run():
        barrier.wait()
        with database.sessions() as db:
            return confirm_plan(db, payload, owner, key)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: run(), range(3)))
    assert results[0] == results[1] == results[2]
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(OfflinePack)) == 1


@pytest.mark.parametrize('limit_field,count_field', [('max_garage_profiles', 'garage_profiles'),
    ('max_watch_items', 'watch_items'), ('max_distinct_evidence', 'distinct_evidence'),
    ('max_searchable_documents', 'searchable_documents')])
def test_each_count_cap_rejects_before_unbounded_merge_without_a_partial_plan(setup, monkeypatch, limit_field, count_field):
    client, _, _ = setup
    data = live(client).json()
    client.post('/v1/garage', json=deepcopy(PROFILE))
    client.post('/v1/watchlists', json={'variant_id': data['variants'][0]['id']})
    import tire_api.offline_packs as module
    monkeypatch.setitem(module.CAPACITY, limit_field, 0)
    import tire_api.offline_evidence as evidence
    def unexpected_merge(*args, **kwargs):
        raise AssertionError('Over-count scopes must stop before field-group merge')
    monkeypatch.setattr(evidence, '_tire_resolution', unexpected_merge)
    response = client.post('/v1/offline-pack-plans', json={'mode': 'history'})
    assert response.status_code == 413, response.text
    detail = response.json()['detail']
    assert detail['code'] == 'offline_scope_capacity_exceeded' and detail['dimension'] == count_field
    assert detail['count'] == (3 if count_field == 'searchable_documents' else 1)
    assert detail['action'] == 'narrow_scope_and_prepare_again'


def test_complete_preview_transport_overage_fails_explicitly_without_empty_plan(setup, monkeypatch):
    client, _, database = setup
    client.post('/v1/garage', json=deepcopy(PROFILE))
    import tire_api.offline_packs as module
    monkeypatch.setattr(module, 'MAX_PREVIEW_BYTES', 100)
    response = client.post('/v1/offline-pack-plans', json={'mode': 'history'})
    assert response.status_code == 413
    assert response.json()['detail']['code'] == 'offline_preview_transport_limit_exceeded'
    assert response.json()['detail']['action'] == 'narrow_scope_and_prepare_again'
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(OfflinePackPlan)) == 0


def test_plan_and_package_are_append_only_and_confirmation_survives_later_source_corruption(setup):
    client, _, database = setup
    live(client)
    prepared = plan(client)
    with database.sessions() as db:
        item = db.get(OfflinePackPlan, prepared['id'])
        item.fingerprint = '0' * 64
        with pytest.raises(ValueError, match='只能追加'):
            db.commit()
    # Deliberate raw SQL adversarial corruption only in this private synthetic DB.
    with database.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE snapshots SET body='corrupt-after-freeze'")
    descriptor = confirm(client, prepared).json()
    assert download(client, descriptor)[1]['members']
    with database.sessions() as db:
        db.delete(db.get(OfflinePack, descriptor['id']))
        with pytest.raises(ValueError, match='只能追加'):
            db.commit()


def test_exact_reference_cannot_use_other_snapshot_receipt_and_raw_embedded_facts_block(setup):
    client, registry, database = setup
    first = live(client).json()
    registry.result['body'] = 'second synthetic raw'
    second = live(client).json()
    with database.sessions() as db:
        receipts = db.scalars(select(Verification).order_by(Verification.verified_at)).all()
        wrong = receipts[-1].id
    scope = deepcopy(EMPTY_SCOPE)
    scope['references'] = [{'kind': 'tire', 'snapshot_id': first['provenance'][0]['snapshot_id'],
        'variant_id': first['variants'][0]['id'], 'verification_id': wrong}]
    assert not plan(client, scope)['can_confirm']
    registry.result['variants'][0]['facts']['body'] = 'SHOULD NEVER EXPORT RAW BODY'
    registry.result['body'] = 'third synthetic raw'
    third = live(client).json()
    scope['references'] = [{'kind': 'tire', 'snapshot_id': third['provenance'][0]['snapshot_id'],
                            'variant_id': third['variants'][0]['id']}]
    prepared = plan(client, scope)
    assert not prepared['can_confirm']
    assert any(row['reason'] == 'offline_raw_or_secret_material_excluded' for row in prepared['omissions'])


def test_actual_eight_mib_limit_measures_complete_non_ascii_domain_material(setup):
    from tire_api.domain import digest
    from tire_api.recall_models import RecallRevision, RecallSnapshot, RecallVerification, SOURCE_ID
    from tire_api.recalls import canonical_records, campaign_url
    from test_recalls import record, CAMPAIGN
    client, _, database = setup
    live(client)
    with database.sessions() as db:
        owner = db.scalar(select(QueryRun.session_id))
        run = QueryRun(id=uid(), session_id=owner, source_id=SOURCE_ID, query={'campaign_number': CAMPAIGN},
            query_key=digest({'campaign_number': CAMPAIGN}), state='live', fallback_policy='never')
        db.add(run)
        db.flush()
        # Valid record limits, but complete domain facts+search text exceed 8MiB.
        rows = canonical_records([{**record(str(i)), 'summary': '合成容量' * 20000} for i in range(9)], CAMPAIGN)
        raw = 'Synthetic capacity only'
        snapshot = RecallSnapshot(id=uid(), source_id=SOURCE_ID, campaign_number=CAMPAIGN,
            query_key=run.query_key, source_url=campaign_url(CAMPAIGN), raw_hash=hashlib.sha256(raw.encode()).hexdigest(),
            body=raw, content_type='application/json', parser_version='synthetic@1', parser_identity=None,
            records=rows, records_hash=digest(rows), revision=1)
        db.add(snapshot)
        db.flush()
        revision = RecallRevision(id=uid(), campaign_number=CAMPAIGN, revision=1, snapshot_id=snapshot.id,
            previous_snapshot_id=None, records_hash=digest(rows), records=rows)
        db.add(revision)
        db.add(RecallVerification(id=uid(), snapshot_id=snapshot.id, query_id=run.id,
            query_key=run.query_key, status='ok', parser_identity=None))
        db.commit()
        ref = {'kind': 'recall', 'snapshot_id': snapshot.id, 'recall_revision_id': revision.id}
    scope = deepcopy(EMPTY_SCOPE)
    scope['references'] = [ref]
    prepared = plan(client, scope)
    assert prepared['measured_bytes'] > 8388608, prepared
    assert prepared['counts']['distinct_evidence'] == 1 and prepared['counts']['searchable_documents'] == 9
    assert not prepared['can_confirm'] and prepared['content_sha256'] is None
    assert confirm(client, prepared).status_code == 409


def test_same_snapshot_receipts_default_closure_keep_each_receipt_and_all_membership_reasons(setup):
    from tire_api.service import timestamp
    client, _, database = setup
    first = live(client).json()
    second = live(client).json()
    assert first['provenance'][0]['snapshot_id'] == second['provenance'][0]['snapshot_id']
    variant = first['variants'][0]
    profile = deepcopy(PROFILE)
    profile['rear'] = {'size': variant['size'], 'current_variant_id': variant['id']}
    assert client.post('/v1/garage', json=profile).status_code == 201
    assert client.post('/v1/watchlists', json={'variant_id': variant['id']}).status_code < 300
    with database.sessions() as db:
        receipts = db.scalars(select(Verification).order_by(Verification.verified_at, Verification.id)).all()
        expected = {row.id: timestamp(row.verified_at) for row in receipts}
        latest_id = receipts[-1].id
    prepared = plan(client)
    assert prepared['can_confirm'] and prepared['counts']['distinct_evidence'] == 2
    latest = next(row for row in prepared['resolved'] if row['reference']['verification_id'] == latest_id)
    assert {why['selector'] for why in latest['member_reasons']} == {'garage', 'watchlist', 'recent'}
    # A third receipt after preview must not become part of the frozen package.
    assert live(client).status_code == 200
    descriptor = confirm(client, prepared).json()
    raw, envelope = download(client, descriptor)
    assert {row['reference']['verification_id'] for row in envelope['members']} == set(expected)
    for member in envelope['members']:
        for field in member['payload']['field_resolution']['fields']:
            candidates = field['candidates']
            assert len({row['id'] for row in candidates}) == len(candidates)
            assert {row['verification_id']: row['verified_at'] for row in candidates} == expected
    assert download(client, descriptor)[0] == raw


def test_explicit_two_receipts_same_snapshot_preserve_fixed_candidate_ids_after_newer_receipt(setup):
    client, _, database = setup
    original = live(client).json()
    assert live(client).status_code == 200
    with database.sessions() as db:
        receipts = db.scalars(select(Verification).order_by(Verification.verified_at, Verification.id)).all()
        refs = [{'kind': 'tire', 'snapshot_id': row.snapshot_id, 'variant_id': original['variants'][0]['id'],
                 'verification_id': row.id} for row in receipts]
    scope = deepcopy(EMPTY_SCOPE)
    scope['references'] = refs
    prepared = plan(client, scope)
    descriptor = confirm(client, prepared).json()
    raw, old = download(client, descriptor)
    old_ids = {candidate['id'] for member in old['members'] for field in member['payload']['field_resolution']['fields']
               for candidate in field['candidates']}
    assert live(client).status_code == 200
    new_plan = plan(client, scope)
    _, new = download(client, confirm(client, new_plan).json())
    assert {member['reference']['verification_id'] for member in new['members']} == {ref['verification_id'] for ref in refs}
    assert {candidate['id'] for member in new['members'] for field in member['payload']['field_resolution']['fields']
            for candidate in field['candidates']} == old_ids
    assert [member['payload']['field_resolution'] for member in old['members']] == [member['payload']['field_resolution'] for member in new['members']]
    assert download(client, descriptor)[0] == raw


def test_missing_field_is_preserved_for_each_old_receipt_when_new_snapshot_adds_it(setup):
    from tire_api.service import timestamp
    client, registry, database = setup
    first = live(client).json()
    assert live(client).status_code == 200
    registry.result['body'] = 'synthetic changed facts with additional weight'
    registry.result['variants'][0]['facts']['weight_lb'] = 22
    third = live(client).json()
    assert first['variants'][0]['id'] == third['variants'][0]['id']
    with database.sessions() as db:
        receipts = db.scalars(select(Verification).order_by(Verification.verified_at, Verification.id)).all()
        expected = {row.id: timestamp(row.verified_at) for row in receipts}
        old_receipts = {row.id for row in receipts if row.snapshot_id == first['provenance'][0]['snapshot_id']}
    prepared = plan(client)
    assert prepared['can_confirm'] and prepared['counts']['distinct_evidence'] == 3
    _, envelope = download(client, confirm(client, prepared).json())
    for member in envelope['members']:
        weight = next(row for row in member['payload']['field_resolution']['fields'] if row['field'] == 'weight_lb')
        assert len(weight['candidates']) == 3
        assert len({row['id'] for row in weight['candidates']}) == 3
        assert {row['verification_id']: row['verified_at'] for row in weight['candidates']} == expected
        assert {row['verification_id'] for row in weight['candidates'] if not row['present']} == old_receipts
        assert [row['value'] for row in weight['candidates'] if row['present']] == [22]


def test_canonical_stream_preserves_exact_stable_json_bytes_hash_and_bounded_capture():
    from tire_api.domain import stable_json, digest
    from tire_api.offline_packs import CanonicalJSON, MAX_CANONICAL_CACHE_BYTES
    shared = {'中文': [None, True, False, 1.25, -0.0, 1e-9, 10**20], 'escaped': '\n\r\t"\\', 'unicode': 'é轮胎😀'}
    value = {'z': shared, 'a': shared, 'ordered': {'b': 2, 'a': 1}}
    expected = stable_json(value).encode('utf-8')
    writer = CanonicalJSON([shared])
    size, sha, raw = writer.measure(value, capture_limit=len(expected))
    assert raw == expected and size == len(expected) and sha == digest(value)
    assert writer.measure(value, capture_limit=len(expected) - 1) == (size, sha, None)
    assert 0 < writer.cached_bytes <= MAX_CANONICAL_CACHE_BYTES


def test_original_api_bytes_and_fingerprint_equal_reference_canonical_json(setup):
    from tire_api.domain import stable_json, digest
    client, _, database = setup
    live(client)
    refs, _ = seed_domains(client, database)
    scope = deepcopy(EMPTY_SCOPE)
    scope['references'] = refs
    prepared = plan(client, scope)
    descriptor = confirm(client, prepared).json()
    raw, envelope = download(client, descriptor)
    assert raw == stable_json(envelope).encode('utf-8')
    assert envelope['plan_fingerprint'] == digest({key: value for key, value in envelope.items() if key != 'plan_fingerprint'})


def test_duplicate_requested_references_load_once_and_do_not_pollute_alternate_receipt_keys(setup, monkeypatch):
    client, _, database = setup
    original = live(client).json()
    live(client)
    with database.sessions() as db:
        receipts = db.scalars(select(Verification).order_by(Verification.verified_at)).all()
        refs = [{'kind': 'tire', 'snapshot_id': row.snapshot_id, 'variant_id': original['variants'][0]['id'],
                 'verification_id': row.id} for row in receipts]
    import tire_api.offline_evidence as evidence
    original_loader, calls = evidence.load_member, []
    def counted(*args, **kwargs):
        calls.append(args[2])
        return original_loader(*args, **kwargs)
    monkeypatch.setattr(evidence, 'load_member', counted)
    scope = deepcopy(EMPTY_SCOPE)
    scope['references'] = refs * 500
    prepared = plan(client, scope)
    assert len(calls) == 2 and prepared['counts']['distinct_evidence'] == 2
    assert len(prepared['requested_scope']['references']) == 1000
    _, envelope = download(client, confirm(client, prepared).json())
    assert {row['reference']['verification_id'] for row in envelope['members']} == {ref['verification_id'] for ref in refs}
    assert len({row['key'] for row in envelope['members']}) == 2


def fixed_receipt_scope(setup, receipt_count):
    client, _, database = setup
    first = live(client).json()
    with database.sessions() as db:
        original = db.scalar(select(Verification))
        run = db.get(QueryRun, original.query_id)
        references = []
        for index in range(receipt_count):
            query = QueryRun(id=uid(), session_id=run.session_id, source_id=run.source_id,
                query_key=run.query_key, query=run.query, fallback_policy='never', state='live')
            db.add(query)
            db.flush()
            receipt = Verification(id=uid(), snapshot_id=original.snapshot_id, query_id=query.id,
                source_id=original.source_id, query_key=original.query_key, status='not_modified',
                parser_identity=original.parser_identity, verified_at=utcnow() + timedelta(seconds=index))
            db.add(receipt)
            references.append({'kind': 'tire', 'snapshot_id': original.snapshot_id,
                'variant_id': first['variants'][0]['id'], 'verification_id': receipt.id})
        db.commit()
    scope = deepcopy(EMPTY_SCOPE)
    scope['references'] = references
    return scope


def test_actual_201_distinct_receipts_reject_before_merge_or_serialization_without_partial_plan(setup, monkeypatch):
    client, _, database = setup
    scope = fixed_receipt_scope(setup, 201)
    import tire_api.offline_evidence as evidence
    import tire_api.offline_packs as packs
    def forbidden(*args, **kwargs):
        raise AssertionError('The 201st distinct receipt must stop before merge or serialization')
    monkeypatch.setattr(evidence, '_tire_resolution', forbidden)
    monkeypatch.setattr(packs.CanonicalJSON, 'measure', forbidden)
    response = client.post('/v1/offline-pack-plans', json={'mode': 'history', 'scope': scope})
    assert response.status_code == 413, response.text
    detail = response.json()['detail']
    assert detail['code'] == 'offline_scope_capacity_exceeded'
    assert detail['dimension'] == 'distinct_evidence'
    assert detail['count'] == 201 and detail['count_is_lower_bound'] is True
    assert detail['limit'] == 200 and detail['action'] == 'narrow_scope_and_prepare_again'
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(OfflinePackPlan)) == 0
        assert db.scalar(select(func.count()).select_from(OfflinePack)) == 0


@pytest.mark.parametrize('receipt_count', [20, 190])
def test_many_fixed_receipts_keep_true_size_and_full_preview_with_bounded_memory(setup, receipt_count, capsys):
    import tracemalloc
    import time
    client, _, _ = setup
    scope = fixed_receipt_scope(setup, receipt_count)
    references = scope['references']
    tracemalloc.start()
    started = time.monotonic()
    prepared = plan(client, scope)
    elapsed = time.monotonic() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert not prepared['can_confirm'] and prepared['measured_bytes'] > 8388608
    assert prepared['counts']['distinct_evidence'] == receipt_count
    assert len(prepared['resolved']) == len(prepared['documents']) == receipt_count
    assert {item['reference']['verification_id'] for item in prepared['resolved']} == {ref['verification_id'] for ref in references}
    assert peak < 96 * 1024 * 1024, (receipt_count, peak, elapsed)
    assert confirm(client, prepared).status_code == 409
    with capsys.disabled():
        print(json.dumps({'offline_resource_receipts': receipt_count, 'raw_bytes': prepared['measured_bytes'],
            'python_peak_bytes': peak, 'seconds_with_tracemalloc': round(elapsed, 3), 'can_confirm': prepared['can_confirm']}))
