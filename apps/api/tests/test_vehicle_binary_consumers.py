"""Private actual-S2 consumer qualification; no production source-use grant.

Run only through the managed runner. Only local structured-use permission is
overridden in explicitly trusted fixtures; Provider/export remain forbidden.
"""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, func, select, update

from test_fitment_relations import (decision, post, preview, read, relation_setup,
                                   seed_tire, tire_payload)
from test_vehicle_binary_approval import decide, frozen_q, loss
from test_vehicle_binary_ingestion import adopt, assert_completed, private, reviewed_pdf
from test_vehicle_pdf_runtime import VEHICLE
from tire_api import report_rendering, vehicle_raw
from tire_api.db import (AuditEvent, CaptureObject, EvidenceObject, QueryRun, RawCapture, Snapshot,
                         QuarantineApprovalUse, uid, utcnow)
from tire_api.fitment_relation_models import FitmentRelation, FitmentRelationRevision
from tire_api.fitment_relations import RelationSelection, current_binding
from tire_api.interest_models import InterestEvent, InterestNotification
from tire_api.object_store import ObjectStoreError
from tire_api.parser_release_models import (ParserBundle, ParserDeploymentRevision,
                                           ParserExecution, ParserSelection)
from tire_api.vehicle_raw import (VehicleRawIntegrityError, VehicleUseNotAllowed,
                                 checked_vehicle_consumer_capsule, require_vehicle_consumer_use)
from tire_api.vehicles import VehicleSnapshot, VehicleVerification, fitment_fact_hash


CAPSULE_KEYS = {'snapshot_id', 'vehicle_id', 'source_id', 'raw_hash', 'parser_version',
    'parser_identity', 'observed_at', 'verification_id', 'verified_at', 'payload', 'fact_hash', 'provenance'}
TRACKED = (FitmentRelation, FitmentRelationRevision, AuditEvent, InterestEvent, InterestNotification)


def counts(ctx, models=TRACKED):
    with ctx.database.sessions() as db:
        return tuple(db.scalar(select(func.count()).select_from(model)) for model in models)


def snapshot(ctx, snapshot_id):
    with ctx.database.sessions() as db:
        row = db.get(VehicleSnapshot, snapshot_id)
        return deepcopy({column.name: getattr(row, column.name) for column in row.__table__.columns})


def choose(ctx, response):
    snapshot_id = response['provenance'][0]['snapshot_id']
    data = snapshot(ctx, snapshot_id)['payload']
    fit = next(item for item in data['fitments'] if item.get('availability') != 'unavailable')
    axle = fit['front']
    value = tire_payload(size=axle['size'], load_index=axle.get('load_index') or '101',
        speed_rating=axle.get('speed_rating') or 'Y', oe_mark=axle.get('oe_mark') or 'SYNTH',
        manufacturer_product_code=axle.get('manufacturer_product_code') or 'PRIVATE-R91-001')
    variant, tire, fact = seed_tire(ctx.database, ctx.session_id, value)
    return {'vehicle_id': VEHICLE, 'vehicle_snapshot_id': snapshot_id, 'trim_id': fit['trim_id'],
        'wheel_option_id': fit['id'], 'axle': 'front', 'variant_id': variant,
        'tire_snapshot_id': tire, 'fact_version_id': fact}


@pytest.fixture
def allowed_local(monkeypatch):
    # This is the sole grant fixture: it never enables Provider or export.
    original = vehicle_raw._vehicle_consumer_rights
    monkeypatch.setattr(vehicle_raw, '_vehicle_consumer_rights', lambda capsule:
        {**original(capsule), 'structured_fact_use': 'allowed'})
    # The imported loss()/decide() review flow also reads approved originals.
    # approval.py's autouse rights patch ends at that module, so grant the same
    # private original-read rights here instead of relying on import side effects.
    original_policy = vehicle_raw._vehicle_original_policy
    monkeypatch.setattr(vehicle_raw, '_vehicle_original_policy', lambda scope:
        {**original_policy(scope), 'local_original_read': 'allowed', 'structured_fact_use': 'allowed'})


@pytest.fixture
def binary_relation(private):
    result = adopt(private)
    assert result['data_state'] == 'live'
    capture_id = assert_completed(private, result['query_id'])
    selected = choose(private, result)
    stored = snapshot(private, selected['vehicle_snapshot_id'])
    assert stored['body'] is None and stored['body_encoding'] == 'binary'
    assert stored['raw_capture_id'] == capture_id
    return SimpleNamespace(ctx=private, result=result, selected=selected, frozen=stored)


def forbid_side_effects(ctx, monkeypatch):
    calls = {'provider': 0, 'renderer': 0, 'object_write': 0}

    async def provider(*_args, **_kwargs):
        calls['provider'] += 1
        raise AssertionError('private R91 consumer must not call a Provider')

    def renderer(*_args, **_kwargs):
        calls['renderer'] += 1
        raise AssertionError('private R91 relation must not render a report')

    def object_write(*_args, **_kwargs):
        calls['object_write'] += 1
        raise AssertionError('private R91 relation must not write an object')

    monkeypatch.setattr(ctx.app.state, 'ai_adapter', SimpleNamespace(generate=provider, stream=provider))
    monkeypatch.setattr(report_rendering, 'render_report', renderer)
    monkeypatch.setattr(ctx.database.object_store, 'put', object_write)
    return calls


def test_actual_r90_approved_binary_supports_local_relations_without_side_effects(private, allowed_local, monkeypatch):
    qid, _baseline, _failed = loss(private)
    original_q = frozen_q(private, qid)
    assert decide(private, qid).status_code == 201
    accepted = adopt(private)
    assert accepted['data_state'] == 'live'
    assert_completed(private, accepted['query_id'])
    selected = choose(private, accepted)
    original_snapshot = snapshot(private, selected['vehicle_snapshot_id'])
    assert original_snapshot['body'] is None
    with private.database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(QuarantineApprovalUse)) == 1
        capsule = checked_vehicle_consumer_capsule(db, selected['vehicle_snapshot_id'])
        assert set(capsule) == CAPSULE_KEYS
        capsule['payload']['vehicle']['model'] = 'caller mutation cannot edit evidence'
        capsule['provenance']['parser_identity']['bundle_id'] = '0' * 64
    assert snapshot(private, selected['vehicle_snapshot_id']) == original_snapshot
    calls = forbid_side_effects(private, monkeypatch)
    listing = private.client.get(f'/v1/fitment-relations/vehicle-snapshots?mode=history&vehicle_id={VEHICLE}')
    assert listing.status_code == 200 and listing.json()['total'] == 2
    detail = private.client.get(f'/v1/fitment-relations/vehicle-snapshots/{selected["vehicle_snapshot_id"]}?mode=history')
    assert detail.status_code == 200 and detail.json()['fitments'] == original_snapshot['payload']['fitments']
    proposed = preview(private.client, selected)
    assert proposed['can_submit'] and proposed['official_oe']['state'] == 'not_established'
    created = post(private.client, decision(private.client, selected))
    assert created.status_code == 201, created.text
    rid = created.json()['relation']['id']
    reviewed = post(private.client, decision(private.client, selected, 'review', rid))
    assert reviewed.status_code == 201 and reviewed.json()['relation']['effective_state'] == 'reviewed'
    assert reviewed.json()['event']['vehicle_evidence']['structured_locator']['snapshot_id'] == selected['vehicle_snapshot_id']
    assert reviewed.json()['event']['vehicle_evidence']['provenance']['raw_hash'] == original_snapshot['raw_hash']
    assert read(private.client, rid)['official_oe']['state'] == 'not_established'
    assert calls == {'provider': 0, 'renderer': 0, 'object_write': 0}
    assert snapshot(private, selected['vehicle_snapshot_id']) == original_snapshot
    assert frozen_q(private, qid) == original_q


def test_production_pending_rejects_list_detail_preview_and_new_revision(binary_relation, monkeypatch):
    ctx, selected = binary_relation.ctx, binary_relation.selected
    calls = forbid_side_effects(ctx, monkeypatch)
    before = counts(ctx)
    selection = {'mode': 'history', 'action': 'create', 'relation_id': None, 'selection': selected}
    responses = [ctx.client.get('/v1/fitment-relations/vehicle-snapshots?mode=history'),
        ctx.client.get(f'/v1/fitment-relations/vehicle-snapshots/{selected["vehicle_snapshot_id"]}?mode=history'),
        ctx.client.post('/v1/fitment-relations/preview', json=selection),
        post(ctx.client, {**selection, 'expected_revision': 0, 'expected_fingerprint': '0' * 64,
            'operator': 'Private R91 fixture', 'reason': 'No production structured-use permission',
            'acknowledged': True, 'acknowledge_unknowns': True})]
    assert all(row.status_code == 403 and row.json()['detail']['code'] ==
               'vehicle_structured_fact_use_not_allowed' for row in responses)
    assert counts(ctx) == before and snapshot(ctx, selected['vehicle_snapshot_id']) == binary_relation.frozen
    assert calls == {'provider': 0, 'renderer': 0, 'object_write': 0}


@pytest.mark.parametrize('purpose,code', [
    ('provider', 'vehicle_provider_use_not_allowed'), ('export', 'vehicle_export_use_not_allowed')])
def test_trusted_local_permission_cannot_enable_provider_or_export(binary_relation, allowed_local, purpose, code):
    ctx = binary_relation.ctx
    with ctx.database.sessions() as db:
        capsule = checked_vehicle_consumer_capsule(db, binary_relation.selected['vehicle_snapshot_id'])
        require_vehicle_consumer_use(capsule, 'local_structured')
        with pytest.raises(VehicleUseNotAllowed) as error:
            require_vehicle_consumer_use(capsule, purpose)
        assert error.value.code == code and error.value.status_code == 403


def damage(ctx, selected, kind, monkeypatch):
    snapshot_id = selected['vehicle_snapshot_id']
    with ctx.database.sessions() as db:
        row = db.get(VehicleSnapshot, snapshot_id)
        capture = db.get(RawCapture, row.raw_capture_id)
        verification = db.scalar(select(VehicleVerification).where(VehicleVerification.snapshot_id == row.id)
            .order_by(VehicleVerification.verified_at.desc(), VehicleVerification.id.desc()).limit(1))
        if kind in {'object_missing', 'object_same_length'}:
            original_get = ctx.database.object_store.get

            def corrupt(raw_hash, byte_count):
                if raw_hash == row.raw_hash:
                    if kind == 'object_missing':
                        raise ObjectStoreError('private_r91_missing')
                    raw = original_get(raw_hash, byte_count)
                    return raw[:-1] + bytes([raw[-1] ^ 1])
                return original_get(raw_hash, byte_count)

            monkeypatch.setattr(ctx.database.object_store, 'get', corrupt)
        elif kind == 'capture_bytes':
            raw = capture.raw_body
            db.execute(update(RawCapture).where(RawCapture.id == capture.id).values(
                raw_body=raw[:-1] + bytes([raw[-1] ^ 1])))
        elif kind == 'capture_size':
            db.execute(update(EvidenceObject).where(EvidenceObject.raw_hash == capture.raw_hash).values(
                byte_count=capture.byte_count + 1))
        elif kind == 'capture_receipt':
            db.execute(delete(CaptureObject).where(CaptureObject.capture_id == capture.id))
        elif kind in {'schema', 'provenance'}:
            payload = deepcopy(row.payload)
            if kind == 'schema':
                payload['fitments'][0]['front']['size'] = 'not-a-private-tire-size'
            else:
                payload['parse_provenance']['mapping_id'] = 'xiaomi-su7-first-generation-pdf@999'
            db.execute(update(VehicleSnapshot).where(VehicleSnapshot.id == row.id).values(
                payload=payload, fact_hash=fitment_fact_hash(payload)))
        elif kind == 'fact_hash':
            db.execute(update(VehicleSnapshot).where(VehicleSnapshot.id == row.id).values(fact_hash='0' * 64))
        elif kind == 'encoding_downgrade':
            db.execute(update(VehicleSnapshot).where(VehicleSnapshot.id == row.id).values(
                body_encoding='utf-8', body='private downgrade', raw_capture_id=None, content_type='application/json'))
        elif kind == 'verification':
            db.execute(update(VehicleVerification).where(VehicleVerification.id == verification.id).values(
                parser_identity={**verification.parser_identity, 'parser_digest': '0' * 64}))
        elif kind == 'verification_vehicle':
            db.execute(update(VehicleVerification).where(VehicleVerification.id == verification.id).values(
                vehicle_id='private-r91-wrong-formal-vehicle'))
        elif kind == 'formal_query':
            run = db.get(QueryRun, verification.query_id)
            db.execute(update(QueryRun).where(QueryRun.id == run.id).values(query_key='0' * 64))
        elif kind == 'selection':
            selection = db.get(ParserSelection, verification.query_id)
            db.execute(update(ParserSelection).where(ParserSelection.query_run_id == selection.query_run_id).values(
                descriptor={**selection.descriptor, 'target_kind': 'tire'}))
        elif kind == 'execution':
            execution = db.get(ParserExecution, capture.query_id)
            db.execute(update(ParserExecution).where(ParserExecution.query_run_id == execution.query_run_id).values(
                receipt={**execution.receipt, 'input_hash': '0' * 64}))
        else:
            raise AssertionError('unlisted private damage case')
        db.commit()


@pytest.mark.parametrize('kind', ['object_missing', 'object_same_length', 'capture_bytes', 'capture_size',
    'capture_receipt', 'schema', 'provenance', 'fact_hash', 'encoding_downgrade', 'verification',
    'verification_vehicle', 'formal_query', 'selection', 'execution'])
def test_binary_selected_damage_fails_before_policy_and_never_returns_partial_list(binary_relation, monkeypatch, kind):
    ctx, selected = binary_relation.ctx, binary_relation.selected
    damage(ctx, selected, kind, monkeypatch)
    before = counts(ctx)
    responses = [ctx.client.get('/v1/fitment-relations/vehicle-snapshots?mode=history'),
        ctx.client.get(f'/v1/fitment-relations/vehicle-snapshots/{selected["vehicle_snapshot_id"]}?mode=history'),
        ctx.client.post('/v1/fitment-relations/preview', json={'mode': 'history', 'action': 'create',
            'relation_id': None, 'selection': selected})]
    assert all(item.status_code == 503 and item.json()['detail']['code'] ==
               'vehicle_raw_integrity_failed' for item in responses)
    assert counts(ctx) == before


def test_latest_bad_verification_never_falls_back_to_valid_older_row(binary_relation, allowed_local):
    ctx, selected = binary_relation.ctx, binary_relation.selected
    with ctx.database.sessions() as db:
        valid = db.scalar(select(VehicleVerification).where(
            VehicleVerification.snapshot_id == selected['vehicle_snapshot_id']))
        exact_id = valid.id
        db.add(VehicleVerification(id=uid(), snapshot_id=valid.snapshot_id, query_id=valid.query_id,
            vehicle_id=valid.vehicle_id, parser_identity={**valid.parser_identity, 'parser_digest': '0' * 64},
            verified_at=utcnow() + timedelta(seconds=1)))
        db.commit()
    with ctx.database.sessions() as db:
        assert checked_vehicle_consumer_capsule(db, selected['vehicle_snapshot_id'], exact_id)['verification_id'] == exact_id
        with pytest.raises(VehicleRawIntegrityError):
            checked_vehicle_consumer_capsule(db, selected['vehicle_snapshot_id'])
        with pytest.raises(VehicleRawIntegrityError):
            checked_vehicle_consumer_capsule(db, selected['vehicle_snapshot_id'], 'missing-private-verification')


@pytest.mark.parametrize('kind', ['execution', 'verification_vehicle', 'encoding_downgrade'])
def test_current_head_damage_cannot_be_hidden_by_valid_selected_snapshot(private, allowed_local, monkeypatch, kind):
    qid, baseline, _failed = loss(private)
    selected = choose(private, baseline)
    created = post(private.client, decision(private.client, selected))
    assert created.status_code == 201, created.text
    rid = created.json()['relation']['id']
    assert decide(private, qid).status_code == 201
    latest = adopt(private)
    head_selected = {**selected, 'vehicle_snapshot_id': latest['provenance'][0]['snapshot_id']}
    assert head_selected['vehicle_snapshot_id'] != selected['vehicle_snapshot_id']
    damage(private, head_selected, kind, monkeypatch)
    with private.database.sessions() as db:
        # The exact selected older evidence is independently still valid.
        assert checked_vehicle_consumer_capsule(db, selected['vehicle_snapshot_id'])
        with pytest.raises(HTTPException) as error:
            current_binding(db, RelationSelection(**selected))
        assert error.value.status_code == 503 and error.value.detail['code'] == 'vehicle_raw_integrity_failed'
    response = private.client.get(f'/v1/fitment-relations/{rid}?mode=history')
    assert response.status_code == 503 and response.json()['detail']['code'] == 'vehicle_raw_integrity_failed'


def test_stale_binary_relation_revokes_without_rebinding_and_pending_never_bypasses_revoke(private, allowed_local, monkeypatch):
    qid, baseline, _failed = loss(private)
    selected = choose(private, baseline)
    created = post(private.client, decision(private.client, selected))
    rid = created.json()['relation']['id']
    first_binding = created.json()['event']['binding_hash']
    assert decide(private, qid).status_code == 201
    assert adopt(private)['data_state'] == 'live'
    summary = read(private.client, rid)
    assert summary['effective_state'] == 'needs_review' and 'vehicle_facts_or_scope_changed' in summary['stale_reasons']
    review = post(private.client, decision(private.client, selected, 'review', rid))
    assert review.status_code == 409
    request = decision(private.client, selected, 'revoke', rid)
    revoked = post(private.client, request)
    assert revoked.status_code == 201 and revoked.json()['event']['binding_hash'] == first_binding
    before = counts(private)
    monkeypatch.setattr(vehicle_raw, '_vehicle_consumer_rights', lambda _capsule: {'structured_fact_use': 'pending_review'})
    rejected = private.client.post('/v1/fitment-relations/preview', json={key: request[key]
        for key in ('mode', 'action', 'relation_id', 'selection')})
    assert rejected.status_code == 403 and rejected.json()['detail']['code'] == 'vehicle_structured_fact_use_not_allowed'
    assert post(private.client, request).status_code == 403
    assert counts(private) == before


def test_binary_relation_keeps_semantic_aba_review_and_fingerprint_contract(binary_relation, allowed_local):
    ctx, selected = binary_relation.ctx, binary_relation.selected
    created = post(ctx.client, decision(ctx.client, selected))
    assert created.status_code == 201, created.text
    rid = created.json()['relation']['id']
    assert post(ctx.client, decision(ctx.client, selected, 'review', rid)).status_code == 201
    old_request = decision(ctx.client, selected, 'review', rid)
    with ctx.database.sessions() as db:
        item = db.get(Snapshot, selected['tire_snapshot_id']).parsed_variants[0]
        original = {key: deepcopy(item[key]) for key in tire_payload()}
    seed_tire(ctx.database, ctx.session_id, {**original, 'facts': {**original['facts'], 'utqg_treadwear': 700}},
        variant_id=selected['variant_id'], version=2)
    seed_tire(ctx.database, ctx.session_id, original, variant_id=selected['variant_id'], version=3,
        observed_at=utcnow() + timedelta(seconds=1))
    summary = read(ctx.client, rid)
    assert summary['review_state'] == 'reviewed' and summary['effective_state'] == 'needs_review'
    assert post(ctx.client, old_request).status_code == 409
    assert post(ctx.client, decision(ctx.client, selected, 'review', rid)).status_code == 201
    assert read(ctx.client, rid)['effective_state'] == 'reviewed'
    assert read(ctx.client, rid)['official_oe']['state'] == 'not_established'


@pytest.mark.parametrize('model', [VehicleSnapshot, VehicleVerification, QueryRun, RawCapture,
    CaptureObject, EvidenceObject, ParserSelection, ParserExecution, ParserBundle, ParserDeploymentRevision])
def test_pending_evidence_never_flushes_or_gets_overwritten(binary_relation, model):
    ctx = binary_relation.ctx
    with ctx.database.sessions() as db:
        pending = model()
        db.add(pending)
        flushes = []

        def before_flush(*_args):
            flushes.append(True)

        event.listen(db, 'before_flush', before_flush)
        try:
            with pytest.raises(VehicleRawIntegrityError):
                checked_vehicle_consumer_capsule(db, binary_relation.selected['vehicle_snapshot_id'])
            assert pending in db.new and flushes == []
        finally:
            event.remove(db, 'before_flush', before_flush)


def test_fresh_capsule_rejects_external_change_and_preserves_unrelated_dirty(binary_relation, allowed_local):
    ctx, selected = binary_relation.ctx, binary_relation.selected
    with ctx.database.sessions() as held:
        row = held.get(VehicleSnapshot, selected['vehicle_snapshot_id'])
        original = deepcopy(row.payload)
        unrelated = AuditEvent(session_id=ctx.session_id, action='private_r91_pending', detail={})
        held.add(unrelated)
        capsule = checked_vehicle_consumer_capsule(held, row.id)
        assert capsule['payload'] == original and unrelated in held.new
        with ctx.database.sessions() as other:
            other.execute(update(VehicleSnapshot).where(VehicleSnapshot.id == row.id).values(fact_hash='0' * 64))
            other.commit()
        with pytest.raises(VehicleRawIntegrityError):
            checked_vehicle_consumer_capsule(held, row.id)
        assert unrelated in held.new and held.is_active


def test_local_binary_notification_insert_failure_rolls_back_relation_and_retries_once(binary_relation, allowed_local):
    ctx, selected = binary_relation.ctx, binary_relation.selected
    interest = ctx.client.post('/v1/interests', json={'name': 'Private binary relation observation', 'enabled': True,
        'conditions': [{'kind': 'vehicle_fitment', 'values': [{key: selected[key]
            for key in ('vehicle_id', 'trim_id', 'wheel_option_id', 'axle')}]}],
        'metric_keys': [], 'changed_fields': []})
    assert interest.status_code == 201, interest.text
    request = decision(ctx.client, selected)
    before = counts(ctx)

    def fail_notification(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith('insert into interest_notifications'):
            raise RuntimeError('private_r91_notification_failure')

    event.listen(ctx.database.engine, 'before_cursor_execute', fail_notification)
    try:
        with pytest.raises(RuntimeError, match='private_r91_notification_failure'):
            post(ctx.client, request)
    finally:
        event.remove(ctx.database.engine, 'before_cursor_execute', fail_notification)
    assert counts(ctx) == before
    retried = post(ctx.client, request)
    assert retried.status_code == 201, retried.text
    with ctx.database.sessions() as db:
        notice = db.scalar(select(InterestNotification).where(InterestNotification.interest_id == interest.json()['id']))
        assert notice is not None
        frozen = db.get(InterestEvent, notice.event_id)
        assert frozen.payload['after']['evidence_valid'] is True
        assert frozen.payload['after']['selection']['vehicle_snapshot_id'] == selected['vehicle_snapshot_id']


def test_real_legacy_text_retains_existing_relation_and_hash_contract(relation_setup):
    client, database, _session, selected = relation_setup
    with database.sessions() as db:
        row = db.get(VehicleSnapshot, selected['vehicle_snapshot_id'])
        original = deepcopy({column.name: getattr(row, column.name) for column in row.__table__.columns})
        assert checked_vehicle_consumer_capsule(db, row.id) is None
        for purpose in ('local_structured', 'provider', 'export'):
            require_vehicle_consumer_use(None, purpose)
    assert preview(client, selected)['can_submit']
    assert post(client, decision(client, selected)).status_code == 201
    with database.sessions() as db:
        row = db.get(VehicleSnapshot, selected['vehicle_snapshot_id'])
        assert {column.name: getattr(row, column.name) for column in row.__table__.columns} == original
