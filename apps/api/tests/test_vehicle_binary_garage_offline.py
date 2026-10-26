"""Managed R94 garage/offline use boundaries; historical S2, private SQLite.

Execute only through the managed runner. Sixteen binary cases each adopt once
through the actual reviewed S2 child; the last two use the synthetic JSON adapter
without a child. Local policy fixtures never grant Provider/export. Inserted old
offline plans/packages are explicit synthetic counterexamples, not evidence of
past production permission. All corruption uses Core, never ORM history edits.
"""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from test_fitment_relations import seed_tire, tire_payload
from test_garage import PROFILE
from test_offline_packs import EMPTY_SCOPE, confirm, download, plan
from test_vehicle_binary_ingestion import adopt, assert_completed, private
from test_vehicle_pdf_runtime import reviewed_pdf
from test_vehicles import live as json_live, setup as legacy_setup
from tire_api import parser_runtime, vehicle_raw
from tire_api.db import AuditEvent, EvidenceObject, GarageRevision, GarageVehicle, uid, utcnow
from tire_api.documents import record_object
from tire_api.domain import digest, stable_json
from tire_api.object_store import ObjectStoreError
from tire_api.offline_evidence import documents
from tire_api.offline_models import OfflinePack, OfflinePackPlan
from tire_api.offline_packs import CanonicalJSON
from tire_api.parser_release_models import ParserExecution
from tire_api.service import timestamp
from tire_api.vehicles import (VehicleSnapshot, VehicleVerification, WheelFitment,
                               fitment_fact_hash, vehicle_provenance)


TRACKED = (GarageVehicle, GarageRevision, AuditEvent, OfflinePackPlan, OfflinePack)
SOURCE_KEYS = {'source_id', 'source_url', 'raw_hash', 'parser_version', 'parser_identity',
               'observed_at', 'verified_at', 'verification_id'}
RECEIPT_KEYS = {'verification_id', 'verified_at', 'fact_hash'}
MEMBER_PAYLOAD_KEYS = {'vehicle', 'trims', 'fitments', 'footnotes',
                       'fact_hash', 'fact_version', 'excluded_document_count'}
STRUCTURED_DENIED = 'vehicle_structured_fact_use_not_allowed'
EXPORT_DENIED = 'vehicle_export_use_not_allowed'
RAW_FAILED = 'vehicle_raw_integrity_failed'
FROZEN_FAILED = 'offline_frozen_object_unavailable'


def counts(ctx):
    with ctx.database.sessions() as db:
        return tuple(db.scalar(select(func.count()).select_from(model)) for model in TRACKED)


def rows(ctx, model):
    with ctx.database.sessions() as db:
        return deepcopy([dict(item) for item in db.execute(select(model.__table__)).mappings()])


def error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json() == {'detail': {'code': code}}


def local_permission(monkeypatch, allowed=True):
    original = vehicle_raw._vehicle_consumer_rights

    def policy(capsule):
        fixed = original(capsule)
        assert fixed['provider_use'] is False and fixed['export_or_redistribution'] is False
        return {**fixed, 'structured_fact_use': 'allowed' if allowed else 'pending_review'}

    monkeypatch.setattr(vehicle_raw, '_vehicle_consumer_rights', policy)


@pytest.fixture
def allowed_local(monkeypatch):
    local_permission(monkeypatch)


def _safe_parser_receipt(receipt):
    values = receipt if type(receipt) is dict else {}
    pid, exit_code = values.get('pid'), values.get('exit_code')
    return {
        'pid_present': type(pid) is int and pid > 0,
        'exit_code': exit_code if type(exit_code) is int and -(2 ** 31) <= exit_code < 2 ** 32 else 'unknown',
        'reaped': values['reaped'] if type(values.get('reaped')) is bool else 'unknown',
    }


@pytest.fixture
def binary(private, monkeypatch, tmp_path):
    # Observe the real await; preserve its inputs, result, exception and deadline.
    codes = {
        'parser_timeout', 'parser_cancelled', 'parser_crashed', 'parser_cleanup_failed',
        'parser_isolation_unavailable', 'parser_protocol_invalid', 'parser_code_mismatch',
        'parser_input_invalid', 'parser_input_too_large', 'parser_output_too_large',
        'parser_stderr_too_large', 'parser_source_not_allowed', 'parser_version_mismatch',
        'parser_schema_changed', 'parser_failed',
    }
    observation = {'runtime_call_count': 0, 'error_code': 'none',
                   'receipt': _safe_parser_receipt(None), 'is_live': 'unknown'}
    original = parser_runtime.parse_isolated

    async def observed(*args, **kwargs):
        observation['runtime_call_count'] += 1
        try:
            parsed = await original(*args, **kwargs)
        except parser_runtime.ParserRunError as failure:
            try:
                code = failure.code
                observation.update(error_code=code if type(code) is str and code in codes else 'unknown',
                                   receipt=_safe_parser_receipt(failure.receipt))
            except Exception:
                observation.update(error_code='unknown', receipt=_safe_parser_receipt(None))
            raise
        else:
            try:
                observation['receipt'] = _safe_parser_receipt(parsed.get('receipt') if type(parsed) is dict else None)
            except Exception:
                observation.update(error_code='unknown', receipt=_safe_parser_receipt(None))
            return parsed

    monkeypatch.setattr(parser_runtime, 'parse_isolated', observed)
    try:
        result = adopt(private)
        observation['is_live'] = result.get('data_state') == 'live' if type(result) is dict else 'unknown'
    finally:
        # IO runs after the real await. Failure to write cannot mask an original
        # exception or change a successful result; a missing/invalid file is a gap.
        try:
            with (tmp_path / 'r94-parser-diagnostic.json').open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(observation, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write('\n')
        except Exception:
            observation['diagnostic_write'] = 'missing'

    assert result['data_state'] == 'live'
    private.snapshot_id = result['provenance'][0]['snapshot_id']
    private.capture_id = assert_completed(private, result['query_id'])
    private.query_id = result['query_id']
    with private.database.sessions() as db:
        snapshot = db.get(VehicleSnapshot, private.snapshot_id)
        receipt = db.scalar(select(VehicleVerification).where(
            VehicleVerification.snapshot_id == snapshot.id))
        assert snapshot.body is None and snapshot.body_encoding == 'binary'
        assert snapshot.raw_capture_id == private.capture_id
        private.payload = deepcopy(snapshot.payload)
        private.provenance = deepcopy(vehicle_provenance(snapshot))
        private.receipt = {'verification_id': receipt.id,
                           'verified_at': timestamp(receipt.verified_at), 'fact_hash': snapshot.fact_hash}
        private.fitment = deepcopy(next(row for row in snapshot.payload['fitments']
            if row['availability'] == 'standard'))
        private.unavailable = deepcopy(next(row for row in snapshot.payload['fitments']
            if row['availability'] == 'unavailable'))
    calls = {'provider': 0}

    async def forbidden(*_args, **_kwargs):
        calls['provider'] += 1
        raise AssertionError('R94 local consumer must not call a Provider')

    private.app.state.ai_adapter = SimpleNamespace(generate=forbidden, stream=forbidden)
    yield private
    assert calls == {'provider': 0}
    assert len(private.adapter.results) == len(private.adapter.captures) == 1


def copy_request(ctx, **changes):
    return {'snapshot_id': ctx.snapshot_id, 'fitment_id': ctx.fitment['id'],
            'nickname': 'Private R94 copied facts', **changes}


def copied(ctx):
    response = ctx.client.post('/v1/garage/from-fitment', json=copy_request(ctx))
    assert response.status_code == 201, response.text
    return response.json()


def ref_for(ctx):
    return {**ctx.provenance, 'fitment_id': ctx.fitment['id'],
            **{key: deepcopy(ctx.fitment.get(key, [] if key == 'constraints' else None))
               for key in ('availability', 'constraints', 'source_description')}}


def tire(ctx, car):
    value = tire_payload(size=car['profile']['front']['size'])
    return seed_tire(ctx.database, ctx.session_id, value)[0]


def denied(ctx, requests, status, code):
    before, history = counts(ctx), rows(ctx, GarageRevision)
    for request in requests:
        error(request(), status, code)
        assert counts(ctx) == before
        assert rows(ctx, GarageRevision) == history


def garage_requests(ctx, car, variant=None, *, include_copy=False):
    path = '/v1/garage/' + car['id']
    requests = [
        lambda: ctx.client.get('/v1/garage'),
        lambda: ctx.client.get(path, params={'mode': 'history'}),
        lambda: ctx.client.put(path, json={'expected_revision': car['revision'],
            'profile': {**car['profile'], 'nickname': 'Private R94 attempted edit'}}),
        lambda: ctx.client.put(path, json={'expected_revision': car['revision'], 'profile': car['profile']}),
        lambda: ctx.client.post(path + '/tires', json={'expected_revision': car['revision'],
            'axle': 'front', 'variant_id': variant}),
        lambda: ctx.client.post(path + '/tires', json={'expected_revision': car['revision'],
            'axle': 'front', 'variant_id': car['profile']['front']['current_variant_id']}),
        lambda: ctx.client.post(path + '/state', json={'expected_revision': car['revision'], 'action': 'archive'}),
        lambda: ctx.client.post(path + '/state', json={'expected_revision': car['revision'], 'action': 'restore'}),
    ]
    if include_copy:
        requests.insert(0, lambda: ctx.client.post('/v1/garage/from-fitment', json=copy_request(ctx)))
    return requests


def corrupt(ctx, kind, monkeypatch):
    with ctx.database.sessions() as db:
        snapshot = db.get(VehicleSnapshot, ctx.snapshot_id)
        if kind == 'object':
            original = ctx.database.object_store.get
            expected_hash = snapshot.raw_hash

            def missing(raw_hash, byte_count):
                if raw_hash == expected_hash:
                    raise ObjectStoreError('private_r94_missing_original')
                return original(raw_hash, byte_count)

            monkeypatch.setattr(ctx.database.object_store, 'get', missing)
        elif kind == 'execution':
            execution = db.get(ParserExecution, ctx.query_id)
            db.execute(ParserExecution.__table__.update().where(
                ParserExecution.query_run_id == ctx.query_id).values(
                    receipt={**execution.receipt, 'input_hash': '0' * 64}))
        elif kind == 'provenance':
            payload = deepcopy(snapshot.payload)
            payload['parse_provenance']['mapping_id'] = 'xiaomi-su7-first-generation-pdf@999'
            db.execute(VehicleSnapshot.__table__.update().where(VehicleSnapshot.id == snapshot.id).values(
                payload=payload, fact_hash=fitment_fact_hash(payload)))
        elif kind == 'utf8':
            raw = stable_json(snapshot.payload)
            db.execute(VehicleSnapshot.__table__.update().where(VehicleSnapshot.id == snapshot.id).values(
                body=raw, body_encoding='utf-8', raw_capture_id=None,
                content_type='application/json', raw_hash=hashlib.sha256(raw.encode('utf-8')).hexdigest(),
                source_url='https://fixture.invalid/r94-disguised.json'))
        else:
            raise AssertionError('unlisted R94 damage')
        db.commit()


def scope_for(ctx, *, selector='explicit'):
    scope = deepcopy(EMPTY_SCOPE)
    if selector == 'explicit':
        scope['references'] = [{'kind': 'vehicle', 'snapshot_id': ctx.snapshot_id,
                                'verification_id': ctx.receipt['verification_id']}]
    elif selector == 'recent':
        scope['recent'] = {'include': True, 'limit': 20}
    return scope


def assert_omitted(prepared, selector, *, blocking):
    assert any(item['selector'] == selector and item['reason'] == EXPORT_DENIED
               and item['blocking'] is blocking for item in prepared['omissions'])
    assert prepared['resolved'] == []
    assert prepared['can_confirm'] is not blocking


def old_member(ctx):
    """Minimal normalized old projection, assembled without authorizing export."""
    reference = {'kind': 'vehicle', 'snapshot_id': ctx.snapshot_id,
                 'verification_id': ctx.receipt['verification_id']}
    payload = {key: deepcopy(ctx.payload.get(key, [])) for key in ('vehicle', 'trims', 'fitments', 'footnotes')}
    payload.update(fact_hash=ctx.receipt['fact_hash'], fact_version=1,
                   excluded_document_count=len(ctx.payload.get('documents', [])))
    source = {key: deepcopy(ctx.provenance[key]) for key in (
        'source_id', 'source_url', 'raw_hash', 'parser_version', 'parser_identity', 'observed_at')}
    source.update(verification_id=ctx.receipt['verification_id'], verified_at=ctx.receipt['verified_at'])
    assert set(source) == SOURCE_KEYS and set(payload) == MEMBER_PAYLOAD_KEYS
    return {'key': digest({'kind': 'vehicle', 'snapshot_id': ctx.snapshot_id}), 'reference': reference,
            'member_reasons': [{'selector': 'explicit', 'scope': 'explicit',
                'object_id': None, 'revision': None, 'axle': None}],
            'privacy_class': 'private', 'raw_included': False, 'source': source, 'payload': payload}


def old_context(car, reference):
    return {'id': 'garage:' + car['id'], 'kind': 'garage', 'scope': 'local_workspace',
            'privacy_class': 'private', 'payload': {'vehicle_id': car['id'], 'revision': car['revision'],
                'basis': 'user_entry', 'profile': deepcopy(car['profile']),
                'fitment_reference': deepcopy(reference), 'created_at': car['updated_at']},
            'evidence_keys': []}



def freeze_old(ctx, *, contexts=(), members=(), blocked=False, mutate=None):
    """Insert explicitly synthetic old bytes and receipts, never grant export.

    No prepare/confirm or permissive production gate is called by this fixture.
    The blocked branch deliberately has no content_hash and no published pack.
    """
    created = utcnow()
    plan_id, package_id = uid(), uid()
    context_rows, member_rows = deepcopy(list(contexts)), deepcopy(list(members))
    docs = documents(context_rows, member_rows)
    omissions = [{'selector': 'garage', 'object_id': None,
                  'reason': 'offline_vehicle_snapshot_missing', 'blocking': False}] if contexts and not members else []
    envelope = {'schema': 'offline-pack@1', 'package_id': package_id, 'created_at': timestamp(created),
        'owner_scope_id': digest({'namespace': 'offline-owner-scope@1', 'session': ctx.session_id}),
        'privacy_class': 'private', 'data_state': 'local_snapshot', 'source_refresh_performed': False,
        'base_pack_id': None, 'scope': deepcopy(EMPTY_SCOPE), 'contracts': {},
        'contexts': context_rows, 'members': member_rows, 'documents': docs, 'omissions': omissions}
    if mutate is not None:
        mutate(envelope)
    fingerprint = CanonicalJSON().measure(envelope)[1]
    envelope['plan_fingerprint'] = fingerprint
    raw = stable_json(envelope).encode('utf-8')
    assert hashlib.sha256(raw).hexdigest() == CanonicalJSON().measure(envelope)[1]
    measured = len(raw)
    content_hash = hashlib.sha256(raw).hexdigest()
    preview = {'schema': 'offline-pack-plan@1', 'id': plan_id, 'package_id': package_id,
        'state': 'blocked' if blocked else 'ready', 'created_at': timestamp(created),
        'expires_at': timestamp(created + timedelta(minutes=10)), 'fingerprint': fingerprint,
        'owner_scope_id': envelope['owner_scope_id'], 'privacy_class': 'private',
        'requested_scope': deepcopy(EMPTY_SCOPE), 'base_pack_id': None,
        'resolved': [{key: deepcopy(item[key]) for key in
            ('key', 'reference', 'member_reasons', 'privacy_class', 'raw_included')} for item in envelope['members']],
        'contexts': deepcopy(envelope['contexts']), 'documents': deepcopy(envelope['documents']),
        'omissions': deepcopy(omissions), 'counts': {'garage_profiles': len(context_rows), 'watch_items': 0,
            'recent_queries': 0, 'distinct_evidence': len(member_rows), 'searchable_documents': len(docs)},
        'measured_bytes': measured, 'content_sha256': None if blocked else content_hash,
        'can_confirm': not blocked}
    key = str(uuid4())
    request = {'plan_id': plan_id, 'expected_fingerprint': fingerprint, 'allow_device_storage': True}
    descriptor = {'schema': 'offline-pack-descriptor@1', 'id': package_id, 'plan_id': plan_id,
        'created_at': timestamp(created), 'content_created_at': timestamp(created),
        'plan_fingerprint': fingerprint, 'owner_scope_id': envelope['owner_scope_id'],
        'privacy_class': 'private', 'sha256': content_hash, 'byte_count': measured, 'base_pack_id': None,
        'counts': deepcopy(preview['counts']), 'download_path': f'/v1/offline-packs/{package_id}/download?mode=history',
        'data_state': 'local_snapshot', 'source_refresh_performed': False}
    with ctx.database.sessions() as db:
        if not blocked:
            assert record_object(db, raw) == content_hash
        db.add(OfflinePackPlan(id=plan_id, package_id=package_id, actor_session_id=ctx.session_id,
            fingerprint=fingerprint, preview=preview, content_hash=None if blocked else content_hash,
            byte_count=measured, created_at=created, expires_at=created + timedelta(minutes=10)))
        db.flush()
        if not blocked:
            db.add(OfflinePack(id=package_id, plan_id=plan_id, actor_session_id=ctx.session_id,
                idempotency_key=key, request_hash=digest(request), content_hash=content_hash,
                byte_count=measured, descriptor=descriptor, created_at=created))
        db.commit()
    return SimpleNamespace(plan=preview, descriptor=descriptor if not blocked else None,
        raw=raw if not blocked else None, content_hash=None if blocked else content_hash,
        key=key, request=request)


def frozen_requests(ctx, frozen):
    requests = [lambda: ctx.client.get('/v1/offline-pack-plans/' + frozen.plan['id'],
                                       params={'mode': 'history'}),
                lambda: confirm(ctx.client, frozen.plan)]
    if frozen.descriptor is not None:
        requests.append(lambda: ctx.client.get(frozen.descriptor['download_path']))
    return requests


def assert_frozen_denied(ctx, frozen, status, code):
    before_plans, before_packs = rows(ctx, OfflinePackPlan), rows(ctx, OfflinePack)
    denied(ctx, frozen_requests(ctx, frozen), status, code)
    assert rows(ctx, OfflinePackPlan) == before_plans and rows(ctx, OfflinePack) == before_packs
    if frozen.raw is not None:
        assert ctx.database.object_store.get(frozen.content_hash, len(frozen.raw)) == frozen.raw


def test_default_binary_copy_is_pending_and_has_no_garage_or_audit(binary):
    before = counts(binary)
    error(binary.client.post('/v1/garage/from-fitment', json=copy_request(binary)), 403, STRUCTURED_DENIED)
    assert counts(binary) == before


def test_local_copy_uses_exact_receipt_and_bad_latest_does_not_replace_it(binary, allowed_local):
    ctx = binary
    car = copied(ctx)
    assert car['basis'] == 'copied_fitment' and car['fitment_reference'] == {**ref_for(ctx), **ctx.receipt}
    assert car['profile']['front']['size'] == ctx.fitment['front']['size']
    assert all(value is None for value in car['current_tires'].values())
    error(ctx.client.get(f'/v1/vehicle-evidence/{ctx.snapshot_id}/content', params={'mode': 'history'}),
          403, 'vehicle_original_read_not_allowed')
    with ctx.database.sessions() as db:
        receipt = db.get(VehicleVerification, ctx.receipt['verification_id'])
        db.add(VehicleVerification(id=uid(), snapshot_id=receipt.snapshot_id, query_id=receipt.query_id,
            vehicle_id=receipt.vehicle_id, parser_identity={**receipt.parser_identity, 'parser_digest': '0' * 64},
            verified_at=utcnow() + timedelta(seconds=10)))
        db.commit()
    denied(ctx, [lambda: ctx.client.post('/v1/garage/from-fitment', json=copy_request(ctx))], 503, RAW_FAILED)
    saved = ctx.client.get('/v1/garage/' + car['id'], params={'mode': 'history'})
    assert saved.status_code == 200 and saved.json()['fitment_reference'] == car['fitment_reference']


def test_original_read_permission_does_not_grant_local_fact_copy(binary, monkeypatch):
    original = vehicle_raw._vehicle_original_policy

    def original_only(binding):
        return {**original(binding), 'local_original_read': 'allowed'}

    monkeypatch.setattr(vehicle_raw, '_vehicle_original_policy', original_only)
    content = binary.client.get(f'/v1/vehicle-evidence/{binary.snapshot_id}/content', params={'mode': 'history'})
    assert content.status_code == 200 and hashlib.sha256(content.content).hexdigest() == binary.provenance['raw_hash']
    denied(binary, [lambda: binary.client.post('/v1/garage/from-fitment', json=copy_request(binary))],
           403, STRUCTURED_DENIED)


def test_unavailable_and_extra_reference_fields_never_create_a_copy(binary, allowed_local):
    requests = [copy_request(binary, fitment_id=binary.unavailable['id']),
                copy_request(binary, fitment_reference=ref_for(binary)),
                copy_request(binary, verification_id=binary.receipt['verification_id']),
                copy_request(binary, snapshot_id='private-r94-missing-snapshot')]
    before = counts(binary)
    for request in requests:
        response = binary.client.post('/v1/garage/from-fitment', json=request)
        assert response.status_code == 422, response.text
        assert counts(binary) == before


@pytest.mark.parametrize('kind', ['object', 'execution', 'provenance', 'utf8'])
def test_integrity_damage_precedes_copy_reads_noops_and_all_revision_writes(binary, allowed_local, monkeypatch, kind):
    car = copied(binary)
    variant = tire(binary, car)
    corrupt(binary, kind, monkeypatch)
    denied(binary, garage_requests(binary, car, variant, include_copy=True), 503, RAW_FAILED)


def test_personal_basis_edits_tires_and_state_retain_the_reference_and_permission_gate(binary, allowed_local, monkeypatch):
    ctx = binary
    car = copied(ctx)
    reference = deepcopy(car['fitment_reference'])
    path = '/v1/garage/' + car['id']
    response = ctx.client.put(path, json={'expected_revision': 1,
        'profile': {**car['profile'], 'nickname': 'Private R94 user edit'}})
    assert response.status_code == 200
    car = response.json()
    assert car['basis'] == 'user_entry' and car['fitment_reference'] == reference
    variant = tire(ctx, car)
    response = ctx.client.post(path + '/tires', json={'expected_revision': car['revision'],
        'axle': 'front', 'variant_id': variant})
    assert response.status_code == 200
    car = response.json()
    assert car['fitment_reference'] == reference
    for action in ('archive', 'restore'):
        response = ctx.client.post(path + '/state', json={'expected_revision': car['revision'], 'action': action})
        assert response.status_code == 200
        car = response.json()
        assert car['fitment_reference'] == reference
    local_permission(monkeypatch, False)
    denied(ctx, garage_requests(ctx, car, variant), 403, STRUCTURED_DENIED)


def test_old_binary_reference_checks_current_source_without_backfilling_receipt(binary, allowed_local, monkeypatch):
    ctx = binary
    car = copied(ctx)
    old_reference = {key: value for key, value in car['fitment_reference'].items() if key not in RECEIPT_KEYS}
    with ctx.database.sessions() as db:
        db.execute(GarageRevision.__table__.update().where(GarageRevision.vehicle_id == car['id']).values(
            fitment_reference=old_reference))
        db.commit()
    before = rows(ctx, GarageRevision)
    response = ctx.client.get('/v1/garage/' + car['id'], params={'mode': 'history'})
    assert response.status_code == 200 and response.json()['fitment_reference'] == old_reference
    assert rows(ctx, GarageRevision) == before
    local_permission(monkeypatch, False)
    denied(ctx, garage_requests(ctx, car), 403, STRUCTURED_DENIED)


def test_missing_or_forged_reference_cannot_become_a_manual_revision(binary, allowed_local):
    ctx = binary
    first = copied(ctx)
    response = ctx.client.put('/v1/garage/' + first['id'], json={'expected_revision': 1,
        'profile': {**first['profile'], 'nickname': 'Private R94 edited before corruption'}})
    assert response.status_code == 200
    car = response.json()
    reference = deepcopy(car['fitment_reference'])
    for replacement in (None, {**reference, 'snapshot_id': 'private-r94-forged-snapshot'},
            {**reference, 'source_url': 'https://fixture.invalid/forged.json', 'raw_hash': '0' * 64},
            {**reference, 'fitment_id': 'private-r94-forged-fitment'},
            {key: value for key, value in reference.items() if key != 'verified_at'}):
        with ctx.database.sessions() as db:
            db.execute(GarageRevision.__table__.update().where(
                GarageRevision.vehicle_id == car['id'], GarageRevision.revision == car['revision']).values(
                    fitment_reference=replacement))
            db.commit()
        denied(ctx, garage_requests(ctx, car), 503, RAW_FAILED)



def test_explicit_vehicle_export_is_blocking_and_never_publishes(binary, allowed_local):
    before = counts(binary)
    object_rows_before = rows(binary, EvidenceObject)
    object_count_before = len(object_rows_before)
    prepared = plan(binary.client, scope_for(binary))
    assert_omitted(prepared, 'explicit', blocking=True)
    assert prepared['contexts'] == prepared['documents'] == []
    with binary.database.sessions() as db:
        persisted = db.get(OfflinePackPlan, prepared['id'])
        assert persisted is not None and persisted.content_hash is None
        assert db.scalar(select(func.count()).select_from(EvidenceObject)) == object_count_before
    assert rows(binary, EvidenceObject) == object_rows_before
    after = counts(binary)
    assert after[:2] == before[:2] and after[3] == before[3] + 1 and after[4] == before[4]
    denied(binary, [lambda: confirm(binary.client, prepared)], 409, 'offline_plan_blocked')


def test_recent_binary_export_omits_all_facts_but_keeps_an_empty_legal_package(binary, allowed_local):
    prepared = plan(binary.client, scope_for(binary, selector='recent'))
    assert_omitted(prepared, 'recent', blocking=False)
    assert prepared['contexts'] == prepared['documents'] == []
    descriptor_response = confirm(binary.client, prepared)
    assert descriptor_response.status_code == 201, descriptor_response.text
    raw, envelope = download(binary.client, descriptor_response.json())
    assert envelope['members'] == envelope['contexts'] == envelope['documents'] == []
    assert binary.snapshot_id.encode() not in raw
    assert binary.provenance['raw_hash'].encode() not in raw


def test_garage_export_checks_before_profile_tires_members_and_search_text(binary, allowed_local):
    ctx = binary
    car = copied(ctx)
    variant = tire(ctx, car)
    response = ctx.client.post('/v1/garage/' + car['id'] + '/tires', json={
        'expected_revision': 1, 'axle': 'front', 'variant_id': variant})
    assert response.status_code == 200
    car = response.json()
    response = ctx.client.put('/v1/garage/' + car['id'], json={'expected_revision': car['revision'],
        'profile': {**car['profile'], 'nickname': 'Private R94 excluded copied profile'}})
    assert response.status_code == 200 and response.json()['basis'] == 'user_entry'
    manual = ctx.client.post('/v1/garage', json={**deepcopy(PROFILE), 'nickname': 'Private R94 permitted manual'})
    assert manual.status_code == 201
    manual = manual.json()
    for explicit in (True, False):
        scope = deepcopy(EMPTY_SCOPE)
        scope['garage'] = {'include': True, **({'vehicle_ids': [car['id']]} if explicit else {})}
        prepared = plan(ctx.client, scope)
        assert_omitted(prepared, 'garage', blocking=explicit)
        garage_contexts = [item for item in prepared['contexts'] if item['kind'] == 'garage']
        assert prepared['counts']['garage_profiles'] == len(garage_contexts)
        assert all(item['payload']['vehicle_id'] != car['id'] for item in prepared['contexts'])
        assert all(item.get('context_id') != 'garage:' + car['id'] for item in prepared['documents'])
        if explicit:
            assert prepared['contexts'] == prepared['documents'] == []
        else:
            assert [item['payload']['vehicle_id'] for item in prepared['contexts']] == [manual['id']]
            published = confirm(ctx.client, prepared)
            assert published.status_code == 201
            raw, envelope = download(ctx.client, published.json())
            assert envelope['members'] == []
            assert envelope['contexts'] == prepared['contexts']
            assert b'Private R94 excluded copied profile' not in raw and variant.encode() not in raw
            assert ctx.snapshot_id.encode() not in raw and b'Private R94 permitted manual' in raw


def test_frozen_binary_member_preview_confirm_download_and_malformed_objects_are_closed(binary):
    ctx = binary
    frozen = freeze_old(ctx, members=[old_member(ctx)])
    assert_frozen_denied(ctx, frozen, 403, EXPORT_DENIED)
    # Existing descriptor/idempotent receipt reads stay historical metadata.
    replay = ctx.client.post('/v1/offline-packs', headers={'Idempotency-Key': frozen.key}, json=frozen.request)
    assert replay.status_code == 201 and replay.json() == frozen.descriptor
    detail = ctx.client.get('/v1/offline-packs/' + frozen.descriptor['id'], params={'mode': 'history'})
    listing = ctx.client.get('/v1/offline-packs', params={'mode': 'history'})
    assert detail.status_code == listing.status_code == 200
    assert detail.json() == frozen.descriptor and frozen.descriptor in listing.json()['items']

    # Root's bounded decision: old bytes may be used internally for a diff.
    # Only the newly selected, independently permitted material can be frozen.
    manual = ctx.client.post('/v1/garage', json={**deepcopy(PROFILE), 'nickname': 'Private R94 safe replacement'})
    assert manual.status_code == 201
    manual = manual.json()
    scope = deepcopy(EMPTY_SCOPE)
    scope['garage'] = {'include': True, 'vehicle_ids': [manual['id']]}
    replacement = plan(ctx.client, scope, base_pack_id=frozen.descriptor['id'])
    update_response = ctx.client.post('/v1/offline-pack-updates:prepare', json={
        'mode': 'history', 'base_pack_id': frozen.descriptor['id'],
        'expected_base_sha256': frozen.descriptor['sha256'], 'scope': scope})
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()['state'] == 'planned'
    for prepared in (replacement, update_response.json()['plan']):
        assert prepared['can_confirm'] and prepared['resolved'] == []
        assert [item['payload']['vehicle_id'] for item in prepared['contexts']] == [manual['id']]
        assert all(item['context_id'] == 'garage:' + manual['id'] for item in prepared['documents'])
        published = confirm(ctx.client, prepared)
        assert published.status_code == 201, published.text
        raw, envelope = download(ctx.client, published.json())
        assert envelope['members'] == []
        assert b'Private R94 safe replacement' in raw
        assert ctx.snapshot_id.encode() not in raw and ctx.provenance['raw_hash'].encode() not in raw
        assert ctx.payload['vehicle']['id'].encode() not in raw
    assert ctx.database.object_store.get(frozen.content_hash, len(frozen.raw)) == frozen.raw

    def bad_context_id(envelope):
        envelope['documents'][0]['context_id'] = []

    def bad_member_key(envelope):
        envelope['documents'][0]['member_key'] = {}

    def duplicate_member(envelope):
        envelope['members'].append(deepcopy(envelope['members'][0]))

    for mutation in (bad_context_id, bad_member_key, duplicate_member):
        malformed = freeze_old(ctx, members=[old_member(ctx)], mutate=mutation)
        assert_frozen_denied(ctx, malformed, 503, FROZEN_FAILED)
    # Existing object bytes are checked before the source's pending export use.
    ctx.database.object_store.path(frozen.content_hash).write_bytes(b'private R94 damaged frozen object')
    denied(ctx, frozen_requests(ctx, frozen), 503, FROZEN_FAILED)


def test_context_only_and_blocked_previews_cannot_hide_missing_or_utf8_sources(binary, allowed_local, monkeypatch):
    ctx = binary
    car = copied(ctx)
    old_reference = {key: value for key, value in car['fitment_reference'].items() if key not in RECEIPT_KEYS}
    source_row = next(item for item in rows(ctx, VehicleSnapshot) if item['id'] == ctx.snapshot_id)
    forged = {**old_reference, 'source_url': 'https://fixture.invalid/pretend-legacy.json',
              'raw_hash': '1' * 64, 'parser_identity': None}
    for variant in ('intact', 'utf8', 'forged_ref', 'missing'):
        if variant == 'utf8':
            corrupt(ctx, 'utf8', monkeypatch)
        else:
            with ctx.database.sessions() as db:
                db.execute(VehicleSnapshot.__table__.update().where(
                    VehicleSnapshot.id == ctx.snapshot_id).values(**source_row))
                db.commit()
        if variant == 'missing':
            with ctx.database.sessions() as db:
                # Explicit private destructive corruption; no ORM edits.
                db.execute(WheelFitment.__table__.delete().where(WheelFitment.snapshot_id == ctx.snapshot_id))
                db.execute(VehicleVerification.__table__.delete().where(
                    VehicleVerification.snapshot_id == ctx.snapshot_id))
                db.execute(VehicleSnapshot.__table__.delete().where(VehicleSnapshot.id == ctx.snapshot_id))
                db.commit()
        references = (old_reference, forged) if variant == 'missing' else (
            forged if variant == 'forged_ref' else old_reference,)
        for reference in references:
            for blocked in (False, True):
                frozen = freeze_old(ctx, contexts=[old_context(car, reference)], blocked=blocked)
                if blocked:
                    assert frozen.content_hash is None and frozen.plan['documents']
                assert_frozen_denied(ctx, frozen, 403 if variant == 'intact' else 503,
                                     EXPORT_DENIED if variant == 'intact' else RAW_FAILED)


def test_manual_wire_reads_noops_tires_and_state_never_infer_a_source(legacy_setup):
    client, adapter, database = legacy_setup
    ctx = SimpleNamespace(client=client, database=database, session_id=client.cookies['tire_local_session'])
    response = client.post('/v1/garage', json=deepcopy(PROFILE))
    assert response.status_code == 201
    car = response.json()
    assert car['profile'] == PROFILE and car['fitment_reference'] is None and car['basis'] == 'user_entry'
    assert set(car) == {'id', 'revision', 'archived', 'profile', 'basis', 'fitment_reference',
                        'updated_at', 'data_state', 'current_tires'}
    path = '/v1/garage/' + car['id']
    assert client.get('/v1/garage').json()['items'] == [car]
    response = client.get(path, params={'mode': 'history'})
    assert response.status_code == 200 and len(response.json()['history']) == 1
    for changed in (False, True, False):
        profile = {**car['profile'], **({'nickname': 'Private R94 manual edited'} if changed else {})}
        previous_revision = car['revision']
        response = client.put(path, json={'expected_revision': previous_revision, 'profile': profile})
        assert response.status_code == 200
        car = response.json()
        assert car['revision'] == previous_revision + int(changed)
        assert car['fitment_reference'] is None
    variant = tire(ctx, car)
    for expected in (3, 3):
        response = client.post(path + '/tires', json={'expected_revision': car['revision'],
            'axle': 'front', 'variant_id': variant})
        assert response.status_code == 200
        car = response.json()
        assert car['revision'] == expected and car['fitment_reference'] is None
    for action, expected in (('archive', 4), ('restore', 5)):
        response = client.post(path + '/state', json={'expected_revision': car['revision'], 'action': action})
        assert response.status_code == 200
        car = response.json()
        assert car['revision'] == expected and car['fitment_reference'] is None
    history = client.get(path, params={'mode': 'history'})
    assert history.status_code == 200 and len(history.json()['history']) == 5
    before = counts(ctx)
    assert client.post('/v1/garage', json={**deepcopy(PROFILE), 'fitment_reference': {'snapshot_id': 'forged'}}).status_code == 422
    assert client.put(path, json={'expected_revision': 5, 'profile': car['profile'],
                                  'fitment_reference': None}).status_code == 422
    assert counts(ctx) == before and adapter.calls == []


def test_true_legacy_text_copy_and_frozen_bytes_survive_late_body_corruption(legacy_setup):
    client, adapter, database = legacy_setup
    response = json_live(client, {'fallback_policy': 'never'})
    assert response.status_code == 200
    observed = response.json()
    snapshot_id = observed['provenance'][0]['snapshot_id']
    fitment = next(item for item in observed['fitments'] if item['availability'] == 'standard')
    response = client.post('/v1/garage/from-fitment', json={'snapshot_id': snapshot_id,
        'fitment_id': fitment['id'], 'nickname': 'Private R94 legacy copied facts'})
    assert response.status_code == 201
    car = response.json()
    assert not RECEIPT_KEYS.intersection(car['fitment_reference'])
    scope = deepcopy(EMPTY_SCOPE)
    scope['references'] = [{'kind': 'vehicle', 'snapshot_id': snapshot_id}]
    first, second = plan(client, scope), plan(client, scope)
    original_descriptor = confirm(client, first)
    assert original_descriptor.status_code == 201
    original_descriptor = original_descriptor.json()
    original_raw, envelope = download(client, original_descriptor)
    member = envelope['members'][0]
    assert set(member['source']) == SOURCE_KEYS and set(member['payload']) == MEMBER_PAYLOAD_KEYS
    assert member['raw_included'] is False and 'documents' not in member['payload']
    with database.sessions() as db:
        pending = db.get(OfflinePackPlan, second['id'])
        pending_raw = database.object_store.get(pending.content_hash, pending.byte_count)
        db.execute(VehicleSnapshot.__table__.update().where(VehicleSnapshot.id == snapshot_id).values(
            body='private R94 corrupt after legacy freeze'))
        db.commit()
    assert client.get('/v1/offline-pack-plans/' + second['id'], params={'mode': 'history'}).status_code == 200
    published = confirm(client, second)
    assert published.status_code == 201, published.text
    assert download(client, published.json())[0] == pending_raw
    assert download(client, original_descriptor)[0] == original_raw
    saved = client.get('/v1/garage/' + car['id'], params={'mode': 'history'})
    assert saved.status_code == 200 and saved.json()['fitment_reference'] == car['fitment_reference']
    assert len(adapter.calls) == 1

