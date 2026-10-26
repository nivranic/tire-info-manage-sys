"""Private binary review through actual S2 children; no production/release consent.

The imported replay hard-checks S2 on every use, retains an independent durable
journal and executes the real isolated parser. Private mapping/deployment/Golden
fixtures do not establish human or production release acceptance. Run only under
the reviewed managed runner; this module performs no external fetch or Provider.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, update

from test_vehicle_binary_ingestion import (
    adopt, assert_completed, count, private, private_mapping_revision, reviewed_pdf, watch)
from test_vehicle_pdf_runtime import MAPPING_FILE, SOURCE, VEHICLE
from test_quality import live as tire_live, reduced, result as tire_result, setup as text_setup
from tire_api import parser_releases, quarantine_review as reviews, vehicle_raw
from tire_api.db import (AuditEvent, QueryRun, QuarantineApprovalUse, QuarantineReview, RawCapture,
                         RejectedObservation, SourceQuarantine, utcnow)
from tire_api.domain import digest
from tire_api.interest_models import InterestEvent, InterestNotification
from tire_api.parser_release_models import ParserBundle, ParserDeploymentRevision, ParserExecution
from tire_api.quality import SourceQualityQuarantined
from tire_api.source_settings import (SourceSettingDecision, SourceSettingPreview, append_source_setting,
                                     preview_source_setting)
from tire_api.vehicle_quality import assess_vehicle_quality
from tire_api.vehicle_raw import VehicleRawIntegrityError
from tire_api.vehicles import (VehicleQuarantine, VehicleService, VehicleSnapshot,
                               VehicleVerification, WheelFitment)


V2 = '?mode=history&format=raw-evidence-v2'
STATE_KEYS = {'quarantine_id', 'scope', 'state', 'revision', 'can_approve', 'restriction',
    'baseline_snapshot_id', 'current_snapshot_id', 'applied_query_id', 'comparison', 'history',
    'history_truncated', 'evidence_format', 'binding_contract', 'binding_hash', 'raw_evidence'}
EVIDENCE_KEYS = {'body_encoding', 'body', 'raw_capture_id', 'raw_hash', 'byte_count', 'content_type',
                 'source_url', 'parser_version', 'parser_identity', 'parse_provenance'}
FACT_MODELS = (VehicleSnapshot, VehicleVerification, WheelFitment, InterestEvent, InterestNotification)


@pytest.fixture(autouse=True)
def _private_review_original_purposes(monkeypatch):
    """Private local review rights; production original/structured policy stays pending."""
    original = vehicle_raw._vehicle_original_policy
    monkeypatch.setattr(vehicle_raw, '_vehicle_original_policy', lambda scope:
        {**original(scope), 'local_original_read': 'allowed', 'structured_fact_use': 'allowed'})


def loss(ctx):
    baseline = adopt(ctx)
    assert baseline['data_state'] == 'live'
    private_mapping_revision(ctx, reduce=True)
    failed = adopt(ctx)
    assert failed['reason'] == 'source_quality_quarantined'
    assert_completed(ctx, failed['query_id'])
    with ctx.database.sessions() as db:
        row = db.scalar(select(VehicleQuarantine).where(VehicleQuarantine.query_id == failed['query_id']))
        return row.id, baseline, failed


def state(ctx, qid):
    response = ctx.client.get(f'/v1/quarantines/{qid}/review{V2}')
    assert response.status_code == 200, response.text
    return response.json()


def body(current, *, action='approve', **extra):
    return {'action': action, 'expected_revision': current['revision'],
        'expected_binding_hash': current['binding_hash'], 'operator': 'Private R90 fixture',
        'reason': 'Synthetic explicit confirmation of exact reviewed loss', 'confirmed_loss': True, **extra}


def decide(ctx, qid, current=None, *, action='approve', **extra):
    account = ctx.client.get('/v1/auth/me').json()['user']['id']
    return ctx.client.post(f'/v1/quarantines/{qid}/reviews{V2}',
        json=body(current if current is not None else state(ctx, qid), action=action, **extra),
        headers={'X-Tire-Expected-Account': account})


def counts(ctx, models=FACT_MODELS):
    with ctx.database.sessions() as db:
        return {model.__tablename__: db.scalar(select(func.count()).select_from(model)) for model in models}


def frozen_q(ctx, qid):
    with ctx.database.sessions() as db:
        row = db.get(VehicleQuarantine, qid)
        return deepcopy({column.name: getattr(row, column.name) for column in row.__table__.columns})


def test_v2_review_is_metadata_only_and_post_cannot_parse_or_adopt(private):
    ctx = private
    qid, _, _ = loss(ctx)
    current = state(ctx, qid)
    assert set(current) == STATE_KEYS and current['state'] == 'pending' and current['can_approve']
    assert current['evidence_format'] == 'raw-evidence-v2' and current['binding_contract'] == 'vehicle-binary@1'
    raw = current['raw_evidence']
    assert set(raw) == EVIDENCE_KEYS and raw['body'] is None and raw['body_encoding'] == 'binary'
    assert raw['content_type'] == 'application/pdf'
    assert set(raw['parser_identity']) == {'bundle_id', 'parser_digest', 'deployment_revision'}
    assert set(raw['parse_provenance']) == {'contract', 'method', 'mapping_id', 'source_raw_hash',
                                          'bundle_id', 'mapping_file_sha256'}
    before = counts(ctx, (*FACT_MODELS, RawCapture, ParserExecution, VehicleQuarantine, QuarantineApprovalUse))
    calls = len(ctx.adapter.results)
    frozen = frozen_q(ctx, qid)
    saved = decide(ctx, qid, current)
    assert saved.status_code == 201, saved.text
    assert set(saved.json()) == STATE_KEYS and saved.json()['state'] == 'approved_waiting_online'
    assert saved.json()['revision'] == 1 and saved.json()['binding_hash'] == current['binding_hash']
    assert counts(ctx, (*FACT_MODELS, RawCapture, ParserExecution, VehicleQuarantine, QuarantineApprovalUse)) == before
    assert len(ctx.adapter.results) == calls and frozen_q(ctx, qid) == frozen
    assert count(ctx, QuarantineReview) == 1
    with ctx.database.sessions() as db:
        record = db.scalar(select(QuarantineReview))
        assert record.quarantine_id == qid and record.binding_hash == current['binding_hash']
        assert record.expires_at - record.created_at >= timedelta(hours=23, minutes=59)
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == 'quarantine_review_recorded'))


def test_new_actual_observation_uses_new_capture_once_without_rewriting_original(private):
    ctx = private
    qid, baseline, failed = loss(ctx)
    frozen = frozen_q(ctx, qid)
    approved = decide(ctx, qid)
    assert approved.status_code == 201, approved.text
    accepted = adopt(ctx)
    assert accepted['data_state'] == 'live' and len(accepted['fitments']) == 10
    assert accepted['fact_version'] == baseline['fact_version'] + 1
    new_cap = assert_completed(ctx, accepted['query_id'])
    assert new_cap != frozen['raw_capture_id']
    snapshot_id = accepted['provenance'][0]['snapshot_id']
    with ctx.database.sessions() as db:
        snapshot = db.get(VehicleSnapshot, snapshot_id)
        assert snapshot.raw_capture_id == new_cap and snapshot.body is None
        use = db.scalar(select(QuarantineApprovalUse))
        assert use.query_id == accepted['query_id'] and use.query_id != failed['query_id']
        record = db.get(QuarantineReview, use.review_id)
        assert record.quarantine_id == qid
        assert db.get(QueryRun, use.query_id).created_at > record.created_at
        assert snapshot.payload['parse_provenance'] == frozen['payload']['parse_provenance']
    assert frozen_q(ctx, qid) == frozen
    current = state(ctx, qid)
    assert current['state'] == 'applied_on_online_fetch' and current['applied_query_id'] == accepted['query_id']
    assert not current['can_approve'] and decide(ctx, qid, current).status_code == 409
    repeated = adopt(ctx)
    assert repeated['data_state'] == 'live' and repeated['provenance'][0]['snapshot_id'] == snapshot_id
    assert_completed(ctx, repeated['query_id'])
    assert count(ctx, QuarantineApprovalUse) == 1
    assert count(ctx, RawCapture) == count(ctx, ParserExecution) == 4
    assert count(ctx, VehicleSnapshot) == 2 and count(ctx, VehicleQuarantine) == 1


def test_binary_binding_is_the_exact_fifteen_key_historical_contract(private):
    ctx = private
    qid, _, _ = loss(ctx)
    current = state(ctx, qid)
    with ctx.database.sessions() as db:
        row = db.get(VehicleQuarantine, qid)
        run = db.get(QueryRun, row.query_id)
        cap = db.get(RawCapture, row.raw_capture_id)
        expected = {'binding_contract': 'vehicle-binary@1', 'target': 'vehicle',
            'source': row.source_id, 'query_key': run.query_key, 'baseline': row.previous_snapshot_id,
            'raw_hash': row.raw_hash, 'url': row.source_url, 'parser': row.parser_version,
            'content_type': row.content_type, 'payload': row.payload, 'quality': row.quality,
            'parser_identity': row.parser_identity, 'body_encoding': 'binary', 'byte_count': cap.byte_count,
            'mapping_id': row.payload['parse_provenance']['mapping_id']}
        assert len(expected) == 15 and current['binding_hash'] == digest(expected)
    altered = {**expected, 'mapping_id': 'xiaomi-su7-first-generation-pdf@999'}
    assert digest(altered) != current['binding_hash']
    assert decide(ctx, qid, current, expected_binding_hash='0' * 64).status_code == 409
    assert count(ctx, QuarantineReview) == 0


def test_binary_negotiation_refuses_legacy_and_mismatched_closed_bodies(private):
    ctx = private
    qid, _, _ = loss(ctx)
    current = state(ctx, qid)
    legacy = body(current)
    del legacy['expected_binding_hash']
    refused = [ctx.client.get(f'/v1/quarantines/{qid}/review?mode=history'),
        ctx.client.post(f'/v1/quarantines/{qid}/reviews', json=legacy),
        ctx.client.get(f'/v1/quarantines/{qid}?mode=history')]
    assert all(item.status_code == 409 and item.json()['detail'] ==
               {'code': 'binary_evidence_format_required'} for item in refused)
    invalid = [ctx.client.get(f'/v1/quarantines/{qid}/review?format=raw-evidence-v2'),
        ctx.client.get(f'/v1/quarantines/{qid}/review?mode=history&format=unknown'),
        ctx.client.post(f'/v1/quarantines/{qid}/reviews?format=raw-evidence-v2', json=body(current)),
        ctx.client.post(f'/v1/quarantines/{qid}/reviews{V2}', json=legacy)]
    for extra in ({'capture': 'forged'}, {'payload': {}}, {'parse_provenance': {}},
                  {'expected_binding_hash': 'BAD'}, {'confirmed_loss': False}, {'expected_revision': True}):
        invalid.append(decide(ctx, qid, current, **extra))
    assert all(item.status_code == 422 for item in invalid)
    assert count(ctx, QuarantineReview) == count(ctx, QuarantineApprovalUse) == 0


def test_v2_and_binary_body_cannot_be_used_for_text_target(text_setup):
    client, registry, database = text_setup
    assert tire_live(client).json()['data_state'] == 'live'
    registry.result = tire_result([reduced()])
    assert tire_live(client).json()['reason'] == 'source_quality_quarantined'
    with database.sessions() as db:
        qid = db.scalar(select(SourceQuarantine)).id
    legacy = {'action': 'approve', 'expected_revision': 0, 'operator': 'Private R90 text fixture',
        'reason': 'Exact old text body compatibility', 'confirmed_loss': True}
    assert client.get(f'/v1/quarantines/{qid}/review{V2}').status_code == 422
    assert client.post(f'/v1/quarantines/{qid}/reviews{V2}', json=legacy).status_code == 422
    assert client.post(f'/v1/quarantines/{qid}/reviews',
                       json={**legacy, 'expected_binding_hash': '0' * 64}).status_code == 422
    assert client.post(f'/v1/quarantines/{qid}/reviews', json=legacy).status_code == 201


def test_actual_binary_schema_rejection_is_never_a_quality_review(private):
    ctx = private
    def invalid(result):
        result['payload']['fitments'].append(deepcopy(result['payload']['fitments'][0]))
    ctx.adapter.after_parse = invalid
    failed = adopt(ctx)
    assert failed['reason'] == 'vehicle_source_schema_changed'
    assert_completed(ctx, failed['query_id'])
    with ctx.database.sessions() as db:
        rejected = db.scalar(select(RejectedObservation).where(RejectedObservation.query_id == failed['query_id']))
        qid = rejected.id
    assert ctx.client.get(f'/v1/quarantines/{qid}/review{V2}').status_code == 409
    assert decide(ctx, qid, {'revision': 0, 'binding_hash': '0' * 64}).status_code == 409
    assert count(ctx, QuarantineReview) == count(ctx, VehicleQuarantine) == 0


@pytest.mark.parametrize('damage', ['capture', 'receipt'])
def test_new_completed_chain_damage_cannot_use_existing_approval(private, monkeypatch, damage):
    ctx = private
    qid, _, _ = loss(ctx)
    assert decide(ctx, qid).status_code == 201
    original = parser_releases.record_execution
    def record(db, query_id, outcome):
        execution = original(db, query_id, outcome)
        if damage == 'capture':
            raw = db.scalar(select(RawCapture.raw_body).where(RawCapture.query_id == query_id))
            db.execute(update(RawCapture).where(RawCapture.query_id == query_id).values(
                raw_body=raw[:-1] + bytes([raw[-1] ^ 1])))
        else:
            db.execute(update(ParserExecution).where(ParserExecution.query_run_id == query_id).values(
                receipt={**execution.receipt, 'input_hash': '0' * 64}))
        return execution
    monkeypatch.setattr(parser_releases, 'record_execution', record)
    failed = adopt(ctx)
    assert failed['reason'] == 'vehicle_raw_integrity_failed'
    assert count(ctx, RawCapture) == count(ctx, ParserExecution) == 3
    assert count(ctx, QuarantineApprovalUse) == 0 and count(ctx, VehicleSnapshot) == 1
    assert state(ctx, qid)['state'] == 'approved_waiting_online'


def damage_q(ctx, qid, damage):
    frozen = frozen_q(ctx, qid)
    values = {}
    if damage in {'duplicate_fitment', 'unknown_trim', 'invalid_axle', 'provenance'}:
        payload = deepcopy(frozen['payload'])
        if damage == 'duplicate_fitment':
            payload['fitments'].append(deepcopy(payload['fitments'][0]))
        elif damage == 'unknown_trim':
            payload['fitments'][0]['trim_id'] = 'missing-private-trim'
        elif damage == 'invalid_axle':
            payload['fitments'][0]['front']['size'] = 'invalid-private-size'
        else:
            payload['parse_provenance']['mapping_id'] = 'xiaomi-su7-first-generation-pdf@999'
        values['payload'] = payload
        if damage != 'provenance':
            # A plausible recomputed quality must not turn invalid structure into
            # a human-approvable loss; schema validation is an independent gate.
            with ctx.database.sessions() as db:
                baseline = db.get(VehicleSnapshot, frozen['previous_snapshot_id'])
                values['quality'] = assess_vehicle_quality(baseline.payload, payload)
    elif damage == 'quality':
        values['quality'] = {**frozen['quality'], 'threshold': 0.99}
    elif damage == 'encoding':
        values = {'body_encoding': 'utf-8', 'body': 'private low-level legal-CHECK downgrade',
                  'content_type': 'application/json'}
    elif damage == 'capture_reference':
        with ctx.database.sessions() as db:
            values['raw_capture_id'] = db.get(VehicleSnapshot, frozen['previous_snapshot_id']).raw_capture_id
    with ctx.database.engine.begin() as connection:
        if damage == 'receipt':
            with ctx.database.sessions() as db:
                receipt = deepcopy(db.get(ParserExecution, frozen['query_id']).receipt)
            receipt['input_hash'] = '0' * 64
            connection.execute(update(ParserExecution).where(
                ParserExecution.query_run_id == frozen['query_id']).values(receipt=receipt))
        elif damage == 'capture_bytes':
            with ctx.database.sessions() as db:
                raw = db.get(RawCapture, frozen['raw_capture_id']).raw_body
            changed = raw[:-1] + bytes([raw[-1] ^ 1])
            connection.execute(update(RawCapture).where(
                RawCapture.id == frozen['raw_capture_id']).values(raw_body=changed))
        else:
            connection.execute(update(VehicleQuarantine).where(VehicleQuarantine.id == qid).values(**values))


@pytest.mark.parametrize('damage', ['duplicate_fitment', 'unknown_trim', 'invalid_axle', 'quality',
    'provenance', 'encoding', 'capture_reference', 'receipt', 'capture_bytes'])
def test_review_and_later_consumption_recheck_original_q_not_only_new_hash(private, damage):
    ctx = private
    qid, _, _ = loss(ctx)
    current = state(ctx, qid)
    assert decide(ctx, qid, current).status_code == 201
    damage_q(ctx, qid, damage)
    for response in (ctx.client.get(f'/v1/quarantines/{qid}/review{V2}'), decide(ctx, qid, current)):
        assert response.status_code == 503, response.text
        assert response.json()['detail'] == {'code': 'vehicle_raw_integrity_failed'}
    accepted_before = counts(ctx)
    failed = adopt(ctx)
    assert failed['reason'] == 'vehicle_raw_integrity_failed' and failed['vehicle'] is None
    assert_completed(ctx, failed['query_id'])
    assert counts(ctx) == accepted_before and count(ctx, QuarantineApprovalUse) == 0


@pytest.mark.parametrize('damage', ['fact_hash', 'verification_query', 'verification_vehicle', 'verification_identity'])
def test_binary_review_requires_verified_baseline_query_and_fact_integrity(private, damage):
    ctx = private
    qid, baseline, _ = loss(ctx)
    current = state(ctx, qid)
    assert decide(ctx, qid, current).status_code == 201
    baseline_id = baseline['provenance'][0]['snapshot_id']
    wrong_run_id = None
    if damage == 'verification_query':
        with ctx.database.sessions() as db:
            wrong = QueryRun(session_id=ctx.session_id, source_id=SOURCE,
                query={'vehicle_id': 'private-unrelated-vehicle'},
                query_key=digest({'vehicle_id': 'private-unrelated-vehicle'}), fallback_policy='never')
            db.add(wrong)
            db.commit()
            wrong_run_id = wrong.id
    with ctx.database.engine.begin() as connection:
        if damage == 'fact_hash':
            connection.execute(update(VehicleSnapshot).where(VehicleSnapshot.id == baseline_id).values(fact_hash='0' * 64))
        else:
            values = ({'query_id': wrong_run_id} if damage == 'verification_query' else
                {'vehicle_id': 'private-unrelated-vehicle'} if damage == 'verification_vehicle' else
                {'parser_identity': {'bundle_id': '0' * 64, 'parser_digest': '0' * 64, 'deployment_revision': 99}})
            connection.execute(update(VehicleVerification).where(
                VehicleVerification.snapshot_id == baseline_id).values(**values))
    response = ctx.client.get(f'/v1/quarantines/{qid}/review{V2}')
    assert response.status_code == 503 and response.json()['detail'] == {'code': 'vehicle_raw_integrity_failed'}
    failed = adopt(ctx)
    assert failed['reason'] == 'vehicle_raw_integrity_failed'
    assert count(ctx, QuarantineApprovalUse) == 0 and count(ctx, VehicleSnapshot) == 1


@pytest.mark.parametrize('damage', ['missing', 'same_length_corruption'])
def test_authoritative_object_is_rechecked_after_review(private, damage):
    ctx = private
    qid, _, _ = loss(ctx)
    current = state(ctx, qid)
    assert decide(ctx, qid, current).status_code == 201
    path = ctx.database.object_store.path(current['raw_evidence']['raw_hash'])
    if damage == 'missing':
        path.unlink()
    else:
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    response = ctx.client.get(f'/v1/quarantines/{qid}/review{V2}')
    assert response.status_code == 503 and response.json()['detail'] == {'code': 'vehicle_raw_integrity_failed'}
    assert count(ctx, QuarantineApprovalUse) == 0


def test_shared_revision_latest_keep_revokes_pending_and_expiry_never_auto_renews(private, monkeypatch):
    ctx = private
    qid, _, _ = loss(ctx)
    again = adopt(ctx)
    with ctx.database.sessions() as db:
        other = db.scalar(select(VehicleQuarantine).where(VehicleQuarantine.query_id == again['query_id'])).id
    pending = state(ctx, qid)
    assert state(ctx, other)['binding_hash'] == pending['binding_hash']
    assert decide(ctx, qid, pending).status_code == 201
    assert state(ctx, other)['revision'] == 1
    assert decide(ctx, other, pending).status_code == 409
    kept = decide(ctx, other, action='keep_quarantined')
    assert kept.status_code == 201 and state(ctx, qid)['state'] == 'kept_quarantined'
    assert adopt(ctx)['reason'] == 'source_quality_quarantined'
    assert count(ctx, QuarantineApprovalUse) == 0
    approved = decide(ctx, qid)
    assert approved.status_code == 201 and approved.json()['revision'] == 3
    with monkeypatch.context() as clock:
        clock.setattr(reviews, 'utcnow', lambda: utcnow() + timedelta(days=2))
        expired = state(ctx, other)
        assert expired['state'] == 'expired' and expired['can_approve']
        assert adopt(ctx)['reason'] == 'source_quality_quarantined'
        assert count(ctx, QuarantineReview) == 3 and count(ctx, QuarantineApprovalUse) == 0


def test_existing_inflight_run_and_original_capture_cannot_consume_new_approval(private):
    ctx = private
    qid, _, failed = loss(ctx)
    current = state(ctx, qid)
    assert decide(ctx, qid, current).status_code == 201
    observation = deepcopy(ctx.adapter.results[-1])
    with ctx.database.sessions() as db:
        selected = parser_releases.pin_selection(db, failed['query_id'], SOURCE)
        run = db.get(QueryRun, failed['query_id'])
        with pytest.raises(SourceQualityQuarantined):
            VehicleService(db, ctx.adapter).persist(run, observation, observation['payload'], parser_selection=selected)
        db.rollback()
    assert count(ctx, QuarantineApprovalUse) == 0 and state(ctx, qid)['state'] == 'approved_waiting_online'
    # Even a deliberately moved private review timestamp cannot authorize
    # reusing its own capture; no new durable fetch/observation has occurred.
    with ctx.database.sessions() as db:
        created = db.get(QueryRun, failed['query_id']).created_at
    with ctx.database.engine.begin() as connection:
        connection.execute(update(QuarantineReview).values(created_at=created - timedelta(seconds=1)))
    with ctx.database.sessions() as db:
        selected = parser_releases.pin_selection(db, failed['query_id'], SOURCE)
        run = db.get(QueryRun, failed['query_id'])
        with pytest.raises(VehicleRawIntegrityError):
            VehicleService(db, ctx.adapter).persist(run, observation, observation['payload'], parser_selection=selected)
        db.rollback()
    assert count(ctx, QuarantineApprovalUse) == 0 and count(ctx, RawCapture) == 2


def private_deployment(ctx, revision, *, bundle_id=None):
    """Append only a synthetic private active revision, never a release decision."""
    with ctx.database.sessions() as db:
        if bundle_id is None:
            bundle_id = parser_releases.register_deployed_bundle(db, 'Private R90 fixture',
                'Synthetic mapping/ABA exercise, no production release acceptance')['id']
        bundle = db.get(ParserBundle, bundle_id)
        db.add(ParserDeploymentRevision(source_id=SOURCE, revision=revision, state='active', bundle_id=bundle_id,
            descriptor=deepcopy(bundle.descriptors[SOURCE]), action='bootstrap', actor_session_id=ctx.session_id,
            idempotency_key=str(uuid4()), request_hash=digest(['r90-private-revision', revision, bundle_id]),
            operator='Private R90 fixture', reason='Synthetic deployment only, no release acceptance'))
        db.commit()


def test_mapping_and_parser_aba_do_not_consume_previous_identity(private):
    ctx = private
    qid, _, _ = loss(ctx)
    current = state(ctx, qid)
    assert decide(ctx, qid, current).status_code == 201
    original_bundle = current['raw_evidence']['parser_identity']['bundle_id']
    path = ctx.source / MAPPING_FILE
    code = path.read_bytes()
    old = b'MAPPING_ID = "xiaomi-su7-first-generation-pdf@2"'
    assert code.count(old) == 1
    path.write_bytes(code.replace(old, b'MAPPING_ID = "xiaomi-su7-first-generation-pdf@3"', 1))
    private_deployment(ctx, 3)
    changed = adopt(ctx)
    assert changed['reason'] == 'source_quality_quarantined'
    assert_completed(ctx, changed['query_id'])
    assert count(ctx, QuarantineApprovalUse) == 0
    private_deployment(ctx, 4, bundle_id=original_bundle)
    returned = adopt(ctx)
    assert returned['reason'] == 'source_quality_quarantined'
    assert_completed(ctx, returned['query_id'])
    with ctx.database.sessions() as db:
        row = db.scalar(select(VehicleQuarantine).where(VehicleQuarantine.query_id == returned['query_id']))
        assert row.parser_identity['bundle_id'] == original_bundle
        assert row.parser_identity['deployment_revision'] == 4
    assert count(ctx, QuarantineApprovalUse) == 0 and state(ctx, qid)['state'] == 'approved_waiting_online'


def test_source_inflight_fence_preserved_without_invalidating_historical_review(private):
    ctx = private
    qid, _, _ = loss(ctx)
    current = state(ctx, qid)
    assert decide(ctx, qid, current).status_code == 201
    def pause(_result):
        with ctx.database.sessions() as db:
            preview = preview_source_setting(db, SOURCE, SourceSettingPreview(action='pause'), registry=ctx.app.state.registry)
            append_source_setting(db, SOURCE, SourceSettingDecision(action='pause', expected_revision=preview['revision'],
                expected_fingerprint=preview['fingerprint'], operator='Private R90 fixture', reason='Concurrent private pause'),
                ctx.session_id, str(uuid4()), registry=ctx.app.state.registry)
    ctx.adapter.after_parse = pause
    failed = adopt(ctx)
    assert failed['reason'] == 'source_access_changed'
    assert_completed(ctx, failed['query_id'])
    assert count(ctx, QuarantineApprovalUse) == 0
    assert state(ctx, qid)['state'] == 'approved_waiting_online'


def test_notification_insert_failure_rolls_back_use_and_domain_writes_together(private):
    ctx = private
    watch(ctx)
    qid, _, _ = loss(ctx)
    assert decide(ctx, qid).status_code == 201
    before = counts(ctx)
    frozen = frozen_q(ctx, qid)
    def stop(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith('insert into interest_notifications'):
            raise RuntimeError('r90-private-notification-insert-failure')
    event.listen(ctx.database.engine, 'before_cursor_execute', stop)
    try:
        with pytest.raises(RuntimeError, match='r90-private-notification-insert-failure'):
            adopt(ctx)
    finally:
        event.remove(ctx.database.engine, 'before_cursor_execute', stop)
    assert counts(ctx) == before and count(ctx, QuarantineApprovalUse) == 0
    assert count(ctx, RawCapture) == count(ctx, ParserExecution) == 3
    assert_completed(ctx, ctx.adapter.captures[-1][0])
    assert frozen_q(ctx, qid) == frozen and state(ctx, qid)['state'] == 'approved_waiting_online'
    assert adopt(ctx)['data_state'] == 'live'
    assert count(ctx, QuarantineApprovalUse) == 1 and count(ctx, InterestNotification) == 2


def test_concurrent_decisions_and_actual_queries_use_only_one_approval(private):
    ctx = private
    qid, _, _ = loss(ctx)
    pending = state(ctx, qid)
    barrier = Barrier(2)
    def review(_):
        barrier.wait(timeout=10)
        return decide(ctx, qid, pending).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(review, range(2)))
    assert sorted(statuses) == [201, 409]
    assert count(ctx, QuarantineReview) == 1
    def query(_):
        barrier.wait(timeout=10)
        return adopt(ctx)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(query, range(2)))
    assert [item['data_state'] for item in responses] == ['live', 'live']
    caps = {assert_completed(ctx, item['query_id']) for item in responses}
    assert len(caps) == 2 and count(ctx, RawCapture) == count(ctx, ParserExecution) == 4
    assert count(ctx, QuarantineApprovalUse) == 1 and count(ctx, VehicleSnapshot) == 2
    assert count(ctx, VehicleVerification) == 3
