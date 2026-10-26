"""Actual S2 qualification with synthetic archived AI/report reservations.

No production Provider/export permission is granted. Historical preparations,
requests and exports below are private archive fixtures, not Device/Host or
human Golden acceptance. Only the managed runner may import/execute this file.
"""
import asyncio
from copy import deepcopy
from datetime import timedelta
import hashlib
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from tire_api import ai_analysis, ai_evidence, ai_execution, ai_stream_store, reports, vehicle_raw
from tire_api.ai_gateway import GatewayError, OpenAIConfig, analysis_contract, request_body
from tire_api.ai_models import AICompletion, AIEvidencePack, AIRequest
from tire_api.ai_stream_models import AIStreamExecution
from tire_api.ai_streaming import AIStreamSupervisor
from tire_api.db import AuditEvent, EvidenceObject, RawCapture, UserSession, uid, utcnow
from tire_api.device_ai import question_digest
from tire_api.device_ai_models import DeviceAIConsentClaim, DeviceAIPreparation
from tire_api.domain import digest, stable_json
from tire_api.embedding_budget import budget_usage
from tire_api.field_authority import policy_descriptor
from tire_api.offline_models import OfflinePack, OfflinePackPlan
from tire_api.report_models import ResearchReport, ResearchReportRevision, ReportExport
from tire_api.report_rendering import RENDERER_VERSION
from tire_api.service import timestamp
from tire_api.vehicles import VehicleModel, VehicleSnapshot, fitment_fact_hash, vehicle_provenance
from test_vehicle_pdf_runtime import reviewed_pdf
from test_vehicle_binary_ingestion import SOURCE, adopt, count, private
from test_vehicles import success

QUESTION = 'Explain the selected historical vehicle evidence.'
ZERO = {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}
SIDE_EFFECTS = (AIRequest, AICompletion, DeviceAIConsentClaim, AIStreamExecution,
                ResearchReport, ResearchReportRevision, ReportExport, AuditEvent)


class ForbidProvider:
    def __init__(self):
        self.generate_calls = self.stream_calls = 0

    async def generate(self, *_args):
        self.generate_calls += 1
        raise AssertionError('forbidden Provider generate was called')

    async def stream(self, *_args):
        self.stream_calls += 1
        raise AssertionError('forbidden Provider stream was called')

    def assert_unused(self):
        assert self.generate_calls == self.stream_calls == 0


@pytest.fixture
def dispatch_ctx(private, monkeypatch):
    accepted = adopt(private)
    private.snapshot_id = accepted['provenance'][0]['snapshot_id']
    private.config = OpenAIConfig(model='private-r91-model', api_key='synthetic-fixture', allow_private=True)
    private.provider = ForbidProvider()
    private.app.state.ai_adapter = private.provider
    monkeypatch.setattr(ai_analysis, 'configured_model', lambda: private.config)
    return private


def side_effects(ctx):
    return {model.__tablename__: count(ctx, model) for model in SIDE_EFFECTS}


def post(ctx, path, body, *, key=None):
    return ctx.client.post(path, json=body, headers={'Idempotency-Key': key or str(uuid4())})


def ordinary_content(snapshot):
    builder = ai_evidence.PackBuilder()
    data = snapshot.payload
    builder.add(kind='oem_fitment', label=data['vehicle']['model'] + ' · ' + data['vehicle']['generation'],
        provenance={**vehicle_provenance(snapshot), 'data_state': 'local_snapshot', 'verified_at': None},
        values={'车型': data['vehicle'], '配置版本': data['trims'], '轮毂与轴位': data['fitments']})
    return {'retrieval': 'exact_structured_lookup', 'evidence': builder.evidence, 'facts': builder.facts,
        'field_policy': policy_descriptor(), **ai_evidence.shared_field_materials([]), 'conflicts': [],
        'query_id': None, 'consent_id': None, 'source_state': 'snapshot'}


def archive_pack(ctx, *, snapshot_id=None, payload=None):
    with ctx.database.sessions() as db:
        if payload is None:
            payload = ordinary_content(db.get(VehicleSnapshot, snapshot_id or ctx.snapshot_id))
        row = AIEvidencePack(actor_session_id=ctx.session_id, mode='history', data_state='local_snapshot',
            privacy_class='public', payload=deepcopy(payload), fingerprint=digest(payload),
            expires_at=utcnow() + timedelta(minutes=30))
        db.add(row)
        db.commit()
        return row.id



def overwrite_archived_pack(ctx, pack_id, payload, *, update_fingerprint=True):
    # Explicit private durable corruption fixture, bypassing the ORM append-only
    # guard so the consumer, rather than the history guard, receives the damage.
    values = {'payload': payload}
    if update_fingerprint:
        values['fingerprint'] = digest(payload)
    with ctx.database.engine.begin() as connection:
        connection.execute(update(AIEvidencePack).where(AIEvidencePack.id == pack_id).values(**values))


def legacy_snapshot(ctx):
    parsed = success()
    payload = parsed['payload']
    with ctx.database.sessions() as db:
        vehicle = payload['vehicle']
        if db.get(VehicleModel, vehicle['id']) is None:
            db.add(VehicleModel(id=vehicle['id'], manufacturer_id=vehicle['manufacturer']['id'],
                name=vehicle['model'], generation=vehicle['generation'], model_year=vehicle.get('model_year'),
                region=vehicle['region'], source_vehicle_id=vehicle['source_vehicle_id']))
            db.flush()
        row = VehicleSnapshot(vehicle_id=payload['vehicle']['id'], source_id=SOURCE,
            source_url=parsed['url'], raw_hash=hashlib.sha256(parsed['body'].encode('utf-8')).hexdigest(),
            body=parsed['body'], body_encoding='utf-8', raw_capture_id=None,
            content_type=parsed['content_type'], parser_version=parsed['parser_version'], parser_identity=None,
            payload=payload, fact_hash=fitment_fact_hash(payload), fact_version=1)
        db.add(row)
        db.commit()
        return row.id


def archive_device_pack(ctx, *, reference_override=None):
    with ctx.database.sessions() as db:
        capsule = vehicle_raw.checked_vehicle_consumer_capsule(db, ctx.snapshot_id)
    reference = reference_override or {'kind': 'vehicle', 'snapshot_id': capsule['snapshot_id'],
                                       'verification_id': capsule['verification_id']}
    source = {key: capsule[key] for key in ('source_id', 'raw_hash', 'parser_version', 'parser_identity',
                                          'observed_at', 'verified_at', 'verification_id')}
    source['source_url'] = capsule['provenance']['source_url']
    member = digest('private-r91-vehicle-member')
    material = {key: deepcopy(capsule['payload'][key]) for key in ('vehicle', 'trims', 'fitments', 'footnotes')}
    material.update(fact_hash=capsule['fact_hash'], fact_version=1, excluded_document_count=0)
    projection = {'observations': [{'selector': {'reference': reference, 'member_key': member},
        'source': source, 'material': material, 'selection_reason': 'requested'}]}
    raw = stable_json(projection).encode('utf-8')
    sha = ctx.database.object_store.put(raw)
    selection_hash, context_hash = digest('private-r91-selection'), digest('private-r91-context')
    payload = {'purpose': 'device_history_analysis', 'origin': 'device_history', 'evidence': [{
        'id': 'e1', 'member_key': member, 'observed_at': source['observed_at'],
        'verified_at': source['verified_at'], 'reference': reference}],
        'facts': [], 'conflicts': [], 'source_state': 'snapshot', 'data_state': 'local_snapshot',
        'device_context': {'projection_sha256': sha, 'selection_sha256': selection_hash,
                           'device_context_fingerprint': context_hash}}
    pack_id = archive_pack(ctx, payload=payload)
    with ctx.database.sessions() as db:
        now = utcnow()
        if db.get(EvidenceObject, sha) is None:
            db.add(EvidenceObject(raw_hash=sha, byte_count=len(raw)))
            db.flush()
        package_id = uid()
        plan = OfflinePackPlan(package_id=package_id, actor_session_id=ctx.session_id,
            fingerprint=digest('private-r91-offline-plan'), preview={}, content_hash=sha,
            byte_count=len(raw), expires_at=now + timedelta(minutes=30))
        db.add(plan)
        db.flush()
        db.add(OfflinePack(id=package_id, plan_id=plan.id, actor_session_id=ctx.session_id,
            idempotency_key=str(uuid4()), request_hash=digest('private-r91-package'), content_hash=sha,
            byte_count=len(raw), descriptor={'schema': 'offline-pack@2', 'synthetic_archive': True}))
        db.flush()
        preparation = DeviceAIPreparation(actor_session_id=ctx.session_id, idempotency_key=str(uuid4()),
            request_hash=digest('private-r91-preparation'), offline_pack_id=package_id, offline_content_hash=sha,
            host_receipt_id=str(uuid4()), intent_id=str(uuid4()), selection_hash=selection_hash,
            projection_hash=sha, projection_byte_count=len(raw), device_context_fingerprint=context_hash,
            question_sha256=question_digest(QUESTION), ai_pack_id=pack_id,
            contract={'variant_ids': [], 'domain_references': {'vehicle': [reference]}},
            created_at=now, expires_at=now + timedelta(minutes=30))
        db.add(preparation)
        db.commit()
    return pack_id


def analysis_payload(ctx, pack_id):
    body = {'pack_id': pack_id, 'question': QUESTION, 'allow_external_processing': True}
    with ctx.database.sessions() as db:
        prep = db.scalar(select(DeviceAIPreparation).where(DeviceAIPreparation.ai_pack_id == pack_id))
        if prep is not None:
            body['device_submission'] = {'prepare_id': prep.id, 'host_receipt_id': prep.host_receipt_id,
                'device_context_fingerprint': prep.device_context_fingerprint, 'provider_consent': {
                    'expected_pack_fingerprint': db.get(AIEvidencePack, pack_id).fingerprint,
                    'expected_device_context_fingerprint': prep.device_context_fingerprint,
                    'question_sha256': prep.question_sha256, 'provider': ctx.config.provider,
                    'model': ctx.config.model,
                    'expected_provider_policy_fingerprint': ai_analysis.device_provider_policy_fingerprint(ctx.config)}}
    return body


def archive_reservation(ctx, pack_id, *, stream=False):
    with ctx.database.sessions() as db:
        pack = db.get(AIEvidencePack, pack_id)
        payload = {**pack.payload, 'data_state': pack.data_state}
        if pack.payload.get('origin') == 'device_history':
            payload = ai_analysis._device_request_evidence(payload)
        body, reserve = request_body(ctx.config, QUESTION, payload, stream=stream)
        row = AIRequest(actor_session_id=ctx.session_id, idempotency_key=str(uuid4()),
            request_hash=digest('private-r91-archived-request'), pack_id=pack.id, question=QUESTION,
            provider=ctx.config.provider, model=ctx.config.model, reserved_tokens=reserve,
            request_contract={**analysis_contract(pack.payload), 'body_hash': digest(body),
                              **({'delivery_mode': 'stream'} if stream else {})})
        db.add(row)
        db.flush()
        owner = str(uuid4())
        if stream:
            ai_stream_store.create_execution_locked(db, row, owner)
        db.commit()
        return SimpleNamespace(id=row.id, body=body, owner=owner, reserve=reserve,
            pack={'payload': deepcopy(pack.payload), 'data_state': pack.data_state})


def run_sync(ctx, reserved):
    with ctx.database.sessions() as db:
        row = db.get(AIRequest, reserved.id)
        return ai_execution.execute_response(db, ctx.app, row, ctx.config, reserved.body, lambda _text: None)


def run_stream(ctx, reserved):
    async def scenario():
        supervisor = AIStreamSupervisor(ctx.database, ctx.provider)
        assert supervisor.start(reserved.id, reserved.owner, ctx.config, reserved.body, reserved.pack)
        await asyncio.wait_for(supervisor._tasks[reserved.id], timeout=10)
        await supervisor.shutdown()
    asyncio.run(scenario())
    with ctx.database.sessions() as db:
        return db.get(AICompletion, reserved.id)


def assert_denied_completion(ctx, completion, code):
    assert completion.state == 'failed' and completion.error_code == code
    assert completion.answer is None and completion.provider_response_id is None and completion.usage == ZERO
    with ctx.database.sessions() as db:
        usage = budget_usage(db)
        assert usage['requests'] == 1 and usage['accounted_tokens'] == 0 and not usage['has_pending_request']
    ctx.provider.assert_unused()


def test_pending_pack_analysis_and_direct_reservation_have_no_side_effects(dispatch_ctx):
    ctx = dispatch_ctx
    pack_id = archive_pack(ctx)
    before = side_effects(ctx)
    response = post(ctx, '/v1/ai/evidence-packs', {'mode': 'history',
        'references': [{'kind': 'vehicle', 'snapshot_id': ctx.snapshot_id}]})
    assert response.status_code == 403 and response.json()['detail']['code'] == 'vehicle_structured_fact_use_not_allowed'
    assert ctx.client.get('/v1/ai/evidence-packs/' + pack_id + '?mode=history').status_code == 200
    response = post(ctx, '/v1/ai/analyses', analysis_payload(ctx, pack_id))
    assert response.status_code == 403 and response.json()['detail']['code'] == 'vehicle_provider_use_not_allowed'
    with ctx.database.sessions() as db:
        pack = db.get(AIEvidencePack, pack_id)
        with pytest.raises(HTTPException) as error:
            ai_execution.reserve_response(db, config=ctx.config, pack=pack, session_id=ctx.session_id,
                key=str(uuid4()), request_hash=digest('direct'), question=QUESTION, reserve=10, body={}, contract={})
        assert error.value.status_code == 403 and error.value.detail['code'] == 'vehicle_provider_use_not_allowed'
    assert side_effects(ctx) == before
    ctx.provider.assert_unused()


def test_device_admission_early_return_and_direct_reserve_cannot_bypass_source_use(dispatch_ctx):
    ctx = dispatch_ctx
    pack_id = archive_device_pack(ctx)
    before = side_effects(ctx)
    payload = ai_analysis.AnalysisRequest.model_validate(analysis_payload(ctx, pack_id))
    with ctx.database.sessions() as db:
        with pytest.raises(HTTPException) as error:
            ai_analysis.prepare_analysis(db, payload, ctx.session_id, stream=True)
        assert error.value.status_code == 403 and error.value.detail['code'] == 'vehicle_provider_use_not_allowed'
        assert ai_analysis.DEVICE_CLAIM_PLAN_KEY not in db.info
    with ctx.database.sessions() as db:
        pack = db.get(AIEvidencePack, pack_id)
        prep = db.scalar(select(DeviceAIPreparation).where(DeviceAIPreparation.ai_pack_id == pack_id))
        db.info[ai_analysis.DEVICE_CLAIM_PLAN_KEY] = {'preparation_id': prep.id, 'ai_pack_id': pack.id}
        with pytest.raises(HTTPException) as error:
            ai_execution.reserve_response(db, config=ctx.config, pack=pack, session_id=ctx.session_id,
                key=str(uuid4()), request_hash=digest('direct-device'), question=QUESTION, reserve=10, body={}, contract={})
        assert error.value.status_code == 403 and error.value.detail['code'] == 'vehicle_provider_use_not_allowed'
    assert side_effects(ctx) == before
    ctx.provider.assert_unused()


@pytest.mark.parametrize('device', [False, True], ids=['ordinary', 'device'])
def test_actual_sync_old_reservation_reaches_fresh_gate_and_releases_only_tokens(dispatch_ctx, monkeypatch, device):
    ctx = dispatch_ctx
    pack_id = archive_device_pack(ctx) if device else archive_pack(ctx)
    reserved = archive_reservation(ctx, pack_id)
    actual, calls, readers = ai_execution.require_vehicle_dispatch, [], []
    factory = ctx.database.sessions
    def sessions(*args, **kwargs):
        session = factory(*args, **kwargs)
        readers.append(session)
        return session
    def observed(*args, **kwargs):
        calls.append(True)
        return actual(*args, **kwargs)
    with factory() as db:
        row = db.get(AIRequest, reserved.id)
        monkeypatch.setattr(ctx.database, 'sessions', sessions)
        monkeypatch.setattr(ai_execution, 'require_vehicle_dispatch', observed)
        completion = ai_execution.execute_response(db, ctx.app, row, ctx.config, reserved.body, lambda _text: None)
    assert calls == [True] and readers and all(not session.in_transaction() for session in readers)
    assert_denied_completion(ctx, completion, 'vehicle_provider_use_not_allowed')


@pytest.mark.parametrize('device', [False, True], ids=['ordinary', 'device'])
def test_actual_queued_stream_uses_durable_pack_and_records_source_denial(dispatch_ctx, monkeypatch, device):
    ctx = dispatch_ctx
    pack_id = archive_device_pack(ctx) if device else archive_pack(ctx)
    reserved = archive_reservation(ctx, pack_id, stream=True)
    actual, calls = ai_execution.require_vehicle_dispatch, []
    def observed(*args, **kwargs):
        calls.append(True)
        try:
            return actual(*args, **kwargs)
        finally:
            assert ctx.database.engine.pool.checkedout() == 0
    monkeypatch.setattr(ai_execution, 'require_vehicle_dispatch', observed)
    completion = run_stream(ctx, reserved)
    assert calls == [True]
    assert_denied_completion(ctx, completion, 'vehicle_provider_use_not_allowed')


@pytest.mark.parametrize('stream', [False, True], ids=['sync', 'stream'])
def test_archived_reservation_rechecks_same_length_raw_damage_at_actual_dispatch(dispatch_ctx, monkeypatch, stream):
    ctx = dispatch_ctx
    reserved = archive_reservation(ctx, archive_pack(ctx), stream=stream)
    actual, calls = ai_execution.require_vehicle_dispatch, []
    def changed(*args, **kwargs):
        calls.append(True)
        with ctx.database.sessions() as db:
            snapshot = db.get(VehicleSnapshot, ctx.snapshot_id)
            cap = db.get(RawCapture, snapshot.raw_capture_id)
            capture_id, size = cap.id, cap.byte_count
        with ctx.database.engine.begin() as connection:
            connection.execute(update(RawCapture).where(RawCapture.id == capture_id).values(raw_body=b'!' * size))
        return actual(*args, **kwargs)
    monkeypatch.setattr(ai_execution, 'require_vehicle_dispatch', changed)
    completion = run_stream(ctx, reserved) if stream else run_sync(ctx, reserved)
    assert calls == [True]
    assert_denied_completion(ctx, completion, 'vehicle_raw_integrity_failed')


@pytest.mark.parametrize('changed', ['body', 'pack'], ids=['body', 'memory-pack'])
def test_replacing_memory_arguments_cannot_disable_durable_vehicle_gate(dispatch_ctx, changed):
    ctx = dispatch_ctx
    reserved = archive_reservation(ctx, archive_pack(ctx), stream=True)
    body, pack = deepcopy(reserved.body), deepcopy(reserved.pack)
    if changed == 'body':
        body = {'input': 'no vehicle'}
    else:
        pack = {'payload': {'evidence': [], 'facts': []}, 'data_state': 'local_snapshot'}
    with pytest.raises(GatewayError) as error:
        ai_execution.require_vehicle_dispatch(ctx.database, reserved.id, ctx.config, body, pack)
    assert str(error.value) == 'vehicle_evidence_binding_failed'
    ctx.provider.assert_unused()


@pytest.mark.parametrize('device', [False, True], ids=['ordinary', 'device'])
@pytest.mark.parametrize('stream', [False, True], ids=['sync', 'stream'])
def test_durable_vehicle_marker_removal_cannot_skip_actual_dispatch(dispatch_ctx, device, stream):
    ctx = dispatch_ctx
    pack_id = archive_device_pack(ctx) if device else archive_pack(ctx)
    reserved = archive_reservation(ctx, pack_id, stream=stream)
    with ctx.database.sessions() as db:
        payload = deepcopy(db.get(AIEvidencePack, pack_id).payload)
    payload['evidence'], payload['facts'] = [], []
    if device:
        payload.pop('origin')
        payload.pop('device_context')
    # Ordinary keeps its frozen fingerprint; Device updates it to prove that
    # the authoritative preparation still classifies a fully stripped payload.
    overwrite_archived_pack(ctx, pack_id, payload, update_fingerprint=device)
    completion = run_stream(ctx, reserved) if stream else run_sync(ctx, reserved)
    assert_denied_completion(ctx, completion, 'vehicle_evidence_binding_failed')


def test_same_user_session_visibility_is_preserved_before_binary_use_denial(dispatch_ctx):
    ctx = dispatch_ctx
    reserved = archive_reservation(ctx, archive_pack(ctx))
    with ctx.database.sessions() as db:
        original = db.get(UserSession, ctx.session_id)
        assert original.user_id
        session = UserSession(user_id=original.user_id, expires_at=utcnow() + timedelta(hours=1))
        db.add(session)
        db.commit()
        other_id = session.id
    with ctx.database.engine.begin() as connection:
        connection.execute(update(AIRequest).where(AIRequest.id == reserved.id).values(actor_session_id=other_id))
    with pytest.raises(GatewayError) as error:
        ai_execution.require_vehicle_dispatch(ctx.database, reserved.id, ctx.config, reserved.body)
    assert str(error.value) == 'vehicle_provider_use_not_allowed'
    ctx.provider.assert_unused()


@pytest.mark.parametrize('changed', ['kind', 'source', 'verification'], ids=['kind-alias', 'source-alias', 'exact-verification'])
def test_device_five_key_reference_contract_is_not_warehouse_shape(dispatch_ctx, changed):
    ctx = dispatch_ctx
    pack_id = archive_device_pack(ctx)
    with ctx.database.sessions() as db:
        row = db.get(AIEvidencePack, pack_id)
        payload = deepcopy(row.payload)
        if changed == 'verification':
            payload['evidence'][0]['reference']['verification_id'] = 'missing-private-r91-verification'
        else:
            payload['evidence'][0][changed] = 'vehicle' if changed == 'kind' else {'source_id': SOURCE}
    overwrite_archived_pack(ctx, pack_id, payload)
    with ctx.database.sessions() as db:
        with pytest.raises(HTTPException) as error:
            ai_evidence.require_vehicle_evidence(db, db.get(AIEvidencePack, pack_id).payload,
                purpose='provider', pack_id=pack_id)
        assert error.value.status_code == 409 and error.value.detail['code'] == 'vehicle_evidence_binding_failed'
    ctx.provider.assert_unused()


@pytest.mark.parametrize('changed', ['fact', 'source', 'kind'], ids=['fact-value', 'frozen-source', 'kind'])
def test_ordinary_binary_facts_and_provenance_bind_to_actual_capsule(dispatch_ctx, changed):
    ctx = dispatch_ctx
    pack_id = archive_pack(ctx)
    with ctx.database.sessions() as db:
        row = db.get(AIEvidencePack, pack_id)
        payload = deepcopy(row.payload)
        if changed == 'fact':
            payload['facts'][0]['value']['id'] = 'invented-private-vehicle'
        elif changed == 'source':
            payload['evidence'][0]['raw_hash'] = '0' * 64
        else:
            payload['evidence'][0]['kind'] = 'manual_test'
    overwrite_archived_pack(ctx, pack_id, payload)
    with ctx.database.sessions() as db:
        with pytest.raises(HTTPException) as error:
            ai_evidence.require_vehicle_evidence(db, db.get(AIEvidencePack, pack_id).payload,
                purpose='provider', pack_id=pack_id)
        assert error.value.status_code == 409 and error.value.detail['code'] == 'vehicle_evidence_binding_failed'
    ctx.provider.assert_unused()


@pytest.mark.parametrize('device', [False, True], ids=['ordinary', 'device'])
def test_binary_frozen_values_cannot_be_laundered_through_same_source_text_snapshot(dispatch_ctx, device):
    ctx = dispatch_ctx
    legacy_id = legacy_snapshot(ctx)
    if device:
        with ctx.database.sessions() as db:
            original = vehicle_raw.checked_vehicle_consumer_capsule(db, ctx.snapshot_id)
        pack_id = archive_device_pack(ctx, reference_override={'kind': 'vehicle', 'snapshot_id': legacy_id,
            'verification_id': original['verification_id']})
    else:
        pack_id = archive_pack(ctx)
        with ctx.database.sessions() as db:
            row = db.get(AIEvidencePack, pack_id)
            payload = deepcopy(row.payload)
            payload['evidence'][0]['snapshot_id'] = legacy_id
        overwrite_archived_pack(ctx, pack_id, payload)
    with ctx.database.sessions() as db:
        with pytest.raises(HTTPException) as error:
            ai_evidence.require_vehicle_evidence(db, db.get(AIEvidencePack, pack_id).payload,
                purpose='provider', pack_id=pack_id)
        assert error.value.status_code == 409 and error.value.detail['code'] == 'vehicle_evidence_binding_failed'
    ctx.provider.assert_unused()


def archive_report(ctx, pack_id):
    with ctx.database.sessions() as db:
        pack = db.get(AIEvidencePack, pack_id)
        evidence, facts = reports.canonical_facts(pack.payload)
        body = {'data_state': 'local_snapshot', 'privacy_class': 'private', 'evidence': evidence, 'facts': facts,
            'source_pack': {'id': pack.id, 'fingerprint': pack.fingerprint, 'mode': pack.mode,
                'data_state': pack.data_state, 'privacy_class': pack.privacy_class,
                'created_at': timestamp(pack.created_at), 'expires_at': timestamp(pack.expires_at)},
            'conflicts': [], 'analysis': None, 'notice': reports.HISTORY_NOTICE}
        create = {'mode': 'history', 'pack_id': pack.id, 'analysis_id': None,
                  'title': 'Private historical report', 'notes': ''}
        key = str(uuid4())
        report = ResearchReport(actor_session_id=ctx.session_id, idempotency_key=key,
            request_hash=digest(create), pack_id=pack.id, analysis_id=None, privacy_class='private',
            body=body, body_hash=digest(body))
        db.add(report)
        db.flush()
        revision = ResearchReportRevision(report_id=report.id, revision=1, title=create['title'], notes='',
            archived=False, operation='create')
        db.add(revision)
        db.flush()
        document_hash = digest(reports.document_for(report, revision))
        data = b'private pre-R91 frozen export fixture'
        sha = db.info['object_store'].put(data)
        export = ReportExport(report_id=report.id, revision=1, format='markdown', renderer_version=RENDERER_VERSION,
            document_hash=document_hash, content_type='text/markdown; charset=utf-8', sha256=sha, byte_count=len(data))
        db.add(export)
        db.commit()
        return SimpleNamespace(id=report.id, export_id=export.id, export_sha=sha, body_hash=report.body_hash,
                               create=create, key=key)


def test_report_new_freeze_existing_export_and_content_fail_before_all_side_effects(dispatch_ctx, monkeypatch):
    from tire_api import report_rendering
    ctx = dispatch_ctx
    pack_id = archive_pack(ctx)
    archived = archive_report(ctx, pack_id)
    calls = {'render': 0, 'put': 0, 'export_read': 0}
    store_type, original_get = type(ctx.database.object_store), type(ctx.database.object_store).get
    def render(*_args, **_kwargs):
        calls['render'] += 1
        raise AssertionError('forbidden report renderer was called')
    def put(*_args, **_kwargs):
        calls['put'] += 1
        raise AssertionError('forbidden object write was called')
    def get(store, sha, *args, **kwargs):
        if sha == archived.export_sha:
            calls['export_read'] += 1
            raise AssertionError('forbidden export bytes were read')
        return original_get(store, sha, *args, **kwargs)
    monkeypatch.setattr(report_rendering, 'render_report', render)
    monkeypatch.setattr(store_type, 'put', put)
    monkeypatch.setattr(store_type, 'get', get)
    before = side_effects(ctx)
    response = post(ctx, '/v1/reports', archived.create)
    assert response.status_code == 403 and response.json()['detail']['code'] == 'vehicle_structured_fact_use_not_allowed'
    for fmt in ('markdown', 'html', 'pdf'):
        response = post(ctx, '/v1/reports/' + archived.id + '/exports', {'revision': 1, 'format': fmt})
        assert response.status_code == 403 and response.json()['detail']['code'] == 'vehicle_export_use_not_allowed'
    response = ctx.client.get('/v1/reports/' + archived.id + '/exports/' + archived.export_id + '/content?mode=history&revision=1')
    assert response.status_code == 403 and response.json()['detail']['code'] == 'vehicle_export_use_not_allowed'
    assert side_effects(ctx) == before
    historical = ctx.client.get('/v1/reports/' + archived.id + '?mode=history')
    assert historical.status_code == 200 and historical.json()['body_hash'] == archived.body_hash
    replay = post(ctx, '/v1/reports', archived.create, key=archived.key)
    assert replay.status_code == 201 and replay.json()['body_hash'] == archived.body_hash
    assert calls == {'render': 0, 'put': 0, 'export_read': 0}
    ctx.provider.assert_unused()


def test_true_legacy_text_pack_is_unchanged_and_gets_no_binary_use_policy(dispatch_ctx):
    ctx = dispatch_ctx
    pack_id = archive_pack(ctx, snapshot_id=legacy_snapshot(ctx))
    with ctx.database.sessions() as db:
        row = db.get(AIEvidencePack, pack_id)
        before = deepcopy(row.payload), row.fingerprint
        assert ai_evidence.require_vehicle_evidence(db, row.payload, purpose='provider', pack_id=row.id) == []
        assert (row.payload, row.fingerprint) == before and not db.dirty
    ctx.provider.assert_unused()


def test_provider_later_using_same_error_code_does_not_get_local_zero_token_accounting(dispatch_ctx):
    ctx = dispatch_ctx
    reserved = archive_reservation(ctx, archive_pack(ctx, snapshot_id=legacy_snapshot(ctx)))
    class CalledProvider:
        calls = 0
        async def generate(self, *_args):
            self.calls += 1
            raise GatewayError('vehicle_provider_use_not_allowed')
    provider = CalledProvider()
    ctx.app.state.ai_adapter = provider
    completion = run_sync(ctx, reserved)
    assert provider.calls == 1 and completion.state == 'failed' and completion.usage is None
    with ctx.database.sessions() as db:
        usage = budget_usage(db)
        assert usage['requests'] == 1 and usage['accounted_tokens'] == reserved.reserve and not usage['has_pending_request']
    ctx.provider.assert_unused()


def test_stream_cancellation_waits_for_fresh_reader_and_never_calls_provider(dispatch_ctx, monkeypatch):
    ctx = dispatch_ctx
    reserved = archive_reservation(ctx, archive_pack(ctx), stream=True)
    entered, release, calls = threading.Event(), threading.Event(), []
    actual = ai_execution.require_vehicle_dispatch
    def held(*args, **kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return actual(*args, **kwargs)
    monkeypatch.setattr(ai_execution, 'require_vehicle_dispatch', held)
    async def scenario():
        supervisor = AIStreamSupervisor(ctx.database, ctx.provider)
        assert supervisor.start(reserved.id, reserved.owner, ctx.config, reserved.body, reserved.pack)
        assert await asyncio.to_thread(entered.wait, 5)
        task = supervisor._tasks[reserved.id]
        task.cancel()
        release.set()
        await asyncio.wait_for(task, timeout=10)
        await supervisor.shutdown()
        assert not supervisor._tasks
    asyncio.run(scenario())
    with ctx.database.sessions() as db:
        completion = db.get(AICompletion, reserved.id)
        assert completion.state == 'outcome_unknown' and completion.usage is None
    assert calls == [True] and ctx.database.engine.pool.checkedout() == 0
    ctx.provider.assert_unused()
