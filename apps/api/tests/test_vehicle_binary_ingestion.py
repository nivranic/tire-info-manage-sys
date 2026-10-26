"""Private file-SQLite replay through the real S2 child and ingestion boundary.

The shared app/DB imports run only inside the managed test process. No online
fetch, normal database, Provider or receiver is used. Temporary mapping revisions
and directory rows are synthetic fixtures, not release or human-Golden approval.
"""
from copy import deepcopy
import os
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.pool import QueuePool

from admin_support import register_admin
from test_parser_bundles import trusted_copy
from test_vehicle_pdf_runtime import reviewed_pdf, MAPPING_FILE, S2_SHA, S2_SIZE, SOURCE, VEHICLE
from test_vehicles import OfflineTireRegistry
from tire_api import embedding_service, parser_releases, parser_runtime as runtime
from tire_api import quarantine_review, vehicles
from tire_api.db import QueryRun, RawCapture, QuarantineApprovalUse
from tire_api.domain import digest
from tire_api.embedding_gateway import EmbeddingConfig
from tire_api.embedding_models import EmbeddingPlan
from tire_api.interest_events import _vehicle_side
from tire_api.interest_models import InterestEvent, InterestNotification
from tire_api.knowledge_models import KnowledgeDocument, KnowledgeIndexState
from tire_api.main import create_app
from tire_api.parser_provenance import parser_identity
from tire_api.parser_release_models import ParserBundle, ParserDeploymentRevision, ParserExecution, ParserSelection
from tire_api.service import QueryService
from tire_api.source_settings import (SourceSettingDecision, SourceSettingPreview, append_source_setting,
                                     preview_source_setting)
from tire_api.vehicle_raw import (PDF_URL, PROVENANCE_KEYS, VehicleRawIntegrityError,
    checked_vehicle_bytes, checked_vehicle_capture, checked_vehicle_parse_provenance)
from tire_api.vehicles import (VehicleManufacturer, VehicleModel, VehicleQuarantine,
    VehicleSnapshot, VehicleVerification, WheelFitment, register_vehicle_routes)


@pytest.fixture(autouse=True)
def _r92_legacy_binary_index_local_only(request, monkeypatch):
    # Preserve the eight R89 integrity cases; grant only this private local use.
    if (request.node.originalname != 'test_binary_index_checks_before_cold_or_cached_search_and_embedding'
            or request.node.nodeid.replace('\\', '/').split('::', 1)[0].rsplit('/', 1)[-1]
            != 'test_vehicle_binary_ingestion.py' or 'private' not in request.fixturenames):
        return
    from tire_api import vehicle_raw
    original = vehicle_raw._vehicle_consumer_rights
    monkeypatch.setattr(vehicle_raw, '_vehicle_consumer_rights', lambda capsule:
        {**original(capsule), 'structured_fact_use': 'allowed'})


class PrivatePDFReplay:
    supports_parser_deployments = True

    def __init__(self, load):
        self.load = load
        self.database = None
        self.results, self.captures = [], []
        self.after_parse = None

    @staticmethod
    def candidates():
        # Private authorization fixture; production xiaomi.candidates is untouched.
        return [{'id': VEHICLE, 'status': 'ready'}]

    async def fetch(self, vehicle_id, *, on_observation, parser_selection):
        assert vehicle_id == VEHICLE and type(parser_selection) is dict
        raw = self.load()  # Hard size/SHA check on every use, before callback/child.
        selected = parser_selection
        observation = {'body': raw, 'body_encoding': 'binary', 'url': PDF_URL,
            'content_type': 'application/pdf', 'parser_version': selected['parser_version'],
            'parser_identity': parser_identity(selected)}
        on_observation(observation)
        # Independent checkout proves capture/object/selection committed before parsing.
        with self.database.sessions() as journal:
            run = journal.get(QueryRun, selected['query_run_id'])
            cap = checked_vehicle_capture(journal, run, observation)
            self.captures.append((run.id, cap.id))
            assert cap.byte_count == S2_SIZE and cap.raw_hash == S2_SHA
            assert self.database.object_store.get(cap.raw_hash, cap.byte_count) == raw
            assert journal.get(ParserExecution, run.id) is None
        parsed = await runtime.parse_isolated(SOURCE, raw, {'vehicle_id': vehicle_id},
            selected['parser_version'], selected['parser_digest'], bundle_manifest=selected['bundle_manifest'],
            deployment_revision=selected['deployment_revision'])
        receipt = parsed['receipt']
        assert receipt['pid'] and receipt['pid'] != os.getpid()
        assert receipt['exit_code'] == 0 and receipt['reaped'] is True
        assert receipt['input_hash'] == runtime.input_hash({**receipt, 'query': {'vehicle_id': vehicle_id}}, raw)
        result = {'status': 'ok', **observation, 'payload': parsed['payload'], 'parser_receipt': receipt}
        self.results.append(result)
        if self.after_parse is not None:
            self.after_parse(result)
        return result


@pytest.fixture
def private(tmp_path, monkeypatch, reviewed_pdf):
    source = trusted_copy(tmp_path, monkeypatch)
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    for name in ('TI_AI_ENABLED', 'TI_EMBEDDINGS_ENABLED', 'TI_OBSERVABILITY_ENABLED'):
        monkeypatch.setenv(name, '0')
    adapter = PrivatePDFReplay(reviewed_pdf)
    app = create_app('sqlite:///' + (tmp_path / 'r89-private.sqlite').as_posix(), OfflineTireRegistry())
    register_vehicle_routes(app, adapter)
    adapter.database = app.state.database
    assert type(adapter.database.engine.pool) is QueuePool
    original = vehicles.before_parse_recorder

    def guarded_recorder(db, run):
        record = original(db, run)
        def callback(observation):
            assert not db.in_transaction()
            record(observation)
            assert not db.in_transaction()
        return callback

    monkeypatch.setattr(vehicles, 'before_parse_recorder', guarded_recorder)
    with TestClient(app) as client:
        register_admin(client)
        yield SimpleNamespace(client=client, app=app, database=adapter.database, adapter=adapter,
                              source=source, session_id=client.cookies['tire_local_session'])


def adopt(ctx):
    response = ctx.client.post(f'/v1/vehicles/{VEHICLE}/live-fitments', json={'fallback_policy': 'never'})
    assert response.status_code == 200, response.text
    return response.json()


def count(ctx, model):
    with ctx.database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model))


def assert_completed(ctx, query_id):
    with ctx.database.sessions() as db:
        run = db.get(QueryRun, query_id)
        cap = db.scalar(select(RawCapture).where(RawCapture.query_id == run.id))
        selected = db.get(ParserSelection, run.id)
        execution = db.get(ParserExecution, run.id)
        assert execution.state == 'completed' and execution.error_code is None
        receipt = execution.receipt
        assert receipt['reaped'] and receipt['exit_code'] == 0
        assert receipt['input_hash'] == runtime.input_hash({**receipt, 'query': run.query}, cap.raw_body)
        selection = {'source_id': SOURCE, 'bundle_id': selected.bundle_id, 'query_run_id': run.id,
            'deployment_revision': selected.deployment_revision,
            'parser_version': selected.descriptor['parser_version'],
            'parser_digest': selected.descriptor['parser_digest'],
            'execution_digest': selected.descriptor['execution_digest']}
        assert execution.fingerprint == digest({'selection': selection, 'state': 'completed',
                                                'error_code': None, 'receipt': receipt})
        return cap.id


def watch(ctx):
    # A synthetic local directory permits creating an interest before observation.
    with ctx.database.sessions() as db:
        db.add(VehicleManufacturer(id='xiaomi', name='Synthetic directory only'))
        db.flush()
        db.add(VehicleModel(id=VEHICLE, manufacturer_id='xiaomi', name='Synthetic directory only',
            generation='首代', region='CN', source_vehicle_id='su7-first-generation'))
        db.commit()
    response = ctx.client.post('/v1/interests', json={'name': 'Private binary ingestion observation',
        'enabled': True, 'conditions': [{'kind': 'vehicle_fitment', 'values': [{'vehicle_id': VEHICLE}]}],
        'metric_keys': [], 'changed_fields': []})
    assert response.status_code == 201, response.text
    return response.json()


def private_mapping_revision(ctx, *, reduce=False):
    """Direct private active deployment fixture, not the production release Gate."""
    path = ctx.source / MAPPING_FILE
    code = path.read_bytes()
    old = b'MAPPING_ID = "xiaomi-su7-first-generation-pdf@1"'
    assert code.count(old) == 1
    code = code.replace(old, b'MAPPING_ID = "xiaomi-su7-first-generation-pdf@2"', 1)
    if reduce:
        assert code.count(b'enumerate(_TRIMS)') == 1
        code = code.replace(b'enumerate(_TRIMS)', b'enumerate(_TRIMS[:2])', 1)
    path.write_bytes(code)
    with ctx.database.sessions() as db:
        bundle_id = parser_releases.register_deployed_bundle(db, 'Private R89 fixture',
            'Synthetic mapping revision; no release acceptance')['id']
        bundle = db.get(ParserBundle, bundle_id)
        db.add(ParserDeploymentRevision(source_id=SOURCE, revision=2, state='active', bundle_id=bundle_id,
            descriptor=deepcopy(bundle.descriptors[SOURCE]), action='bootstrap', actor_session_id=ctx.session_id,
            idempotency_key=str(uuid4()), request_hash=digest('r89-private-revision'),
            operator='Private R89 fixture', reason='Synthetic mapping revision only'))
        db.commit()


def search(ctx):
    return ctx.client.post('/v1/knowledge/search', json={'mode': 'history', 'text': '',
                                                       'filters': {'kind': 'vehicle'}})


def test_actual_s2_journal_completed_receipt_dedupe_and_real_interest_delivery(private):
    ctx = private
    watched = watch(ctx)
    first = adopt(ctx)
    assert first['data_state'] == 'live' and first['fact_version'] == 1
    first_cap = assert_completed(ctx, first['query_id'])
    snapshot_id = first['provenance'][0]['snapshot_id']
    with ctx.database.sessions() as db:
        row = db.get(VehicleSnapshot, snapshot_id)
        assert row.body is None and row.body_encoding == 'binary' and row.raw_capture_id == first_cap
        provenance = checked_vehicle_parse_provenance(db, row)
        assert set(provenance) == PROVENANCE_KEYS and provenance == row.payload['parse_provenance']
        assert checked_vehicle_bytes(db, row) == ctx.adapter.results[0]['body']
        frozen = db.scalar(select(InterestEvent))
        assert frozen.payload['after']['evidence_valid'] is True
        assert frozen.payload['after']['parse_provenance'] == provenance
        notice = db.scalar(select(InterestNotification))
        assert notice.interest_id == watched['id'] and notice.event_id == frozen.id
    assert 'parse_provenance' not in ctx.adapter.results[0]
    assert 'parse_provenance' not in ctx.adapter.results[0]['payload']
    repeated = adopt(ctx)
    second_cap = assert_completed(ctx, repeated['query_id'])
    assert repeated['fact_version'] == 1 and repeated['provenance'][0]['snapshot_id'] == snapshot_id
    assert first_cap != second_cap and count(ctx, RawCapture) == count(ctx, VehicleVerification) == 2
    assert count(ctx, VehicleSnapshot) == count(ctx, InterestEvent) == count(ctx, InterestNotification) == 1
    assert count(ctx, WheelFitment) == 15
    with ctx.database.sessions() as db:
        assert db.get(VehicleSnapshot, snapshot_id).raw_capture_id == first_cap
        assert db.scalar(select(VehicleVerification).where(
            VehicleVerification.query_id == repeated['query_id'])).snapshot_id == snapshot_id
    response = ctx.client.get('/v1/vehicle-evidence/' + snapshot_id)
    assert response.status_code == 409 and response.json()['detail'] == {'code': 'binary_evidence_format_required'}


def test_same_raw_new_mapping_keeps_facts_and_original_snapshot_provenance(private):
    ctx = private
    first = adopt(ctx)
    assert first['data_state'] == 'live'
    old_id = first['provenance'][0]['snapshot_id']
    private_mapping_revision(ctx)
    second = adopt(ctx)
    assert second['data_state'] == 'live' and second['fact_version'] == 1
    assert_completed(ctx, first['query_id'])
    assert_completed(ctx, second['query_id'])
    new_id = second['provenance'][0]['snapshot_id']
    assert new_id != old_id and count(ctx, VehicleSnapshot) == 2 and count(ctx, InterestEvent) == 1
    with ctx.database.sessions() as db:
        old, new = db.get(VehicleSnapshot, old_id), db.get(VehicleSnapshot, new_id)
        before, after = checked_vehicle_parse_provenance(db, old), checked_vehicle_parse_provenance(db, new)
        assert old.raw_hash == new.raw_hash == S2_SHA and old.fact_hash == new.fact_hash
        assert before['mapping_id'].endswith('@1') and after['mapping_id'].endswith('@2')
        assert before['bundle_id'] != after['bundle_id']
        assert before['mapping_file_sha256'] != after['mapping_file_sha256']


def test_binary_quality_isolation_never_enters_legacy_approval_and_old_routes_refuse(private, monkeypatch):
    ctx = private
    first = adopt(ctx)
    private_mapping_revision(ctx, reduce=True)
    def forbidden(*_args, **_kwargs):
        raise AssertionError('binary quality must not use the text approval binding')
    monkeypatch.setattr(quarantine_review, 'consume_approval', forbidden)
    failed = adopt(ctx)
    assert failed['reason'] == 'source_quality_quarantined' and failed['vehicle'] is None
    cap_id = assert_completed(ctx, failed['query_id'])
    assert count(ctx, VehicleSnapshot) == count(ctx, VehicleVerification) == count(ctx, VehicleQuarantine) == 1
    assert count(ctx, QuarantineApprovalUse) == 0
    with ctx.database.sessions() as db:
        row = db.scalar(select(VehicleQuarantine))
        assert row.query_id == failed['query_id'] and row.raw_capture_id == cap_id
        assert row.previous_snapshot_id == first['provenance'][0]['snapshot_id']
        assert row.body is None and row.body_encoding == 'binary'
        assert checked_vehicle_parse_provenance(db, row)['mapping_id'].endswith('@2')
        quarantine_id = row.id
    routes = [ctx.client.get(f'/v1/quarantines/{quarantine_id}?mode=history'),
        ctx.client.get(f'/v1/quarantines/{quarantine_id}/review?mode=history'),
        ctx.client.post(f'/v1/quarantines/{quarantine_id}/reviews', json={'action': 'approve',
            'expected_revision': 0, 'operator': 'Private fixture', 'reason': 'Explicit binary legacy refusal',
            'confirmed_loss': True})]
    assert all(response.status_code == 409 and response.json()['detail'] ==
               {'code': 'binary_evidence_format_required'} for response in routes)


@pytest.mark.parametrize('location', ['observation', 'payload'], ids=['observation', 'payload'])
def test_caller_cannot_supply_server_parse_provenance(private, location):
    ctx = private
    def inject(result):
        target = result if location == 'observation' else result['payload']
        target['parse_provenance'] = {'mapping_id': 'forged-caller-block'}
    ctx.adapter.after_parse = inject
    failed = adopt(ctx)
    assert failed['reason'] == 'vehicle_raw_integrity_failed' and failed['vehicle'] is None
    assert_completed(ctx, failed['query_id'])
    assert count(ctx, VehicleSnapshot) == count(ctx, VehicleVerification) == count(ctx, VehicleQuarantine) == 0


@pytest.mark.parametrize('damage', ['capture', 'execution'], ids=['capture-bytes', 'execution-receipt'])
def test_damaged_durable_chain_fails_without_adoption_after_actual_child(private, monkeypatch, damage):
    ctx = private
    original = parser_releases.record_execution
    def record(db, query_id, outcome):
        row = original(db, query_id, outcome)
        if damage == 'capture':
            raw = db.scalar(select(RawCapture.raw_body).where(RawCapture.query_id == query_id))
            damaged = raw[:-1] + bytes([raw[-1] ^ 1])
            db.execute(update(RawCapture).where(RawCapture.query_id == query_id).values(raw_body=damaged))
        else:
            receipt = {**row.receipt, 'input_hash': '0' * 64}
            db.execute(update(ParserExecution).where(ParserExecution.query_run_id == query_id).values(receipt=receipt))
        return row
    monkeypatch.setattr(parser_releases, 'record_execution', record)
    failed = adopt(ctx)
    assert failed['reason'] == 'vehicle_raw_integrity_failed'
    assert count(ctx, RawCapture) == count(ctx, ParserExecution) == 1
    assert count(ctx, VehicleSnapshot) == count(ctx, VehicleVerification) == count(ctx, InterestEvent) == 0
    assert ctx.adapter.results[-1]['parser_receipt']['reaped']


@pytest.mark.parametrize('change', ['url', 'vehicle'], ids=['wrong-url', 'wrong-vehicle'])
def test_result_context_mismatch_is_schema_failure_after_durable_capture(private, change):
    ctx = private
    def inject(result):
        if change == 'url':
            result['url'] = 'https://invalid.example/untrusted.pdf'
        else:
            result['payload']['vehicle']['id'] = 'untrusted-vehicle'
    ctx.adapter.after_parse = inject
    failed = adopt(ctx)
    assert failed['reason'] == 'vehicle_source_schema_changed'
    assert_completed(ctx, failed['query_id'])
    assert count(ctx, VehicleSnapshot) == count(ctx, VehicleVerification) == 0


def test_notification_failure_rolls_back_adoption_but_keeps_actual_capture_and_execution(private):
    ctx = private
    watch(ctx)
    def stop(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith('insert into interest_notifications'):
            raise RuntimeError('r89-private-notification-write-failure')
    event.listen(ctx.database.engine, 'before_cursor_execute', stop)
    try:
        with pytest.raises(RuntimeError, match='r89-private-notification-write-failure'):
            adopt(ctx)
    finally:
        event.remove(ctx.database.engine, 'before_cursor_execute', stop)
    assert count(ctx, RawCapture) == count(ctx, ParserExecution) == 1
    assert_completed(ctx, ctx.adapter.captures[0][0])
    for model in (VehicleSnapshot, VehicleVerification, VehicleQuarantine, WheelFitment, InterestEvent, InterestNotification):
        assert count(ctx, model) == 0
    assert adopt(ctx)['data_state'] == 'live' and count(ctx, InterestNotification) == 1


@pytest.mark.parametrize('fence', ['source', 'selection'], ids=['source-paused', 'selection-paused'])
def test_binary_adoption_preserves_real_source_and_selection_fences(private, fence):
    ctx = private
    def pause(_result):
        with ctx.database.sessions() as db:
            if fence == 'selection':
                parser_releases.transition_deployment(db, SOURCE, parser_releases.DeploymentTransition(
                    action='pause', expected_revision=1, operator='Private fixture', reason='Concurrent private pause'),
                    ctx.session_id, str(uuid4()))
            else:
                preview = preview_source_setting(db, SOURCE, SourceSettingPreview(action='pause'), registry=ctx.app.state.registry)
                append_source_setting(db, SOURCE, SourceSettingDecision(action='pause', expected_revision=preview['revision'],
                    expected_fingerprint=preview['fingerprint'], operator='Private fixture', reason='Concurrent private pause'),
                    ctx.session_id, str(uuid4()), registry=ctx.app.state.registry)
    ctx.adapter.after_parse = pause
    failed = adopt(ctx)
    assert failed['reason'] == ('source_access_changed' if fence == 'source' else 'parser_deployment_changed')
    assert_completed(ctx, failed['query_id'])
    assert count(ctx, VehicleSnapshot) == count(ctx, VehicleVerification) == count(ctx, InterestEvent) == 0


def damage_snapshot(ctx, snapshot_id, damage):
    if damage == 'object':
        path = ctx.database.object_store.path(S2_SHA)
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        return
    # Deliberate low-level corruption of private fixtures, not an ORM mutation API.
    with ctx.database.engine.begin() as connection:
        if damage == 'execution':
            connection.execute(update(ParserExecution).values(fingerprint='0' * 64))
        elif damage == 'encoding':
            connection.execute(update(VehicleSnapshot).where(VehicleSnapshot.id == snapshot_id).values(
                body_encoding='utf-8', body='synthetic illegal downgrade', content_type='application/json'))
        else:
            with ctx.database.sessions() as db:
                payload = deepcopy(db.get(VehicleSnapshot, snapshot_id).payload)
            payload['parse_provenance']['mapping_id'] = 'forged-original-mapping'
            connection.execute(update(VehicleSnapshot).where(VehicleSnapshot.id == snapshot_id).values(payload=payload))


@pytest.mark.parametrize('warm', [False, True], ids=['cold-index', 'warm-index'])
@pytest.mark.parametrize('damage', ['object', 'execution', 'provenance', 'encoding'],
                         ids=['object', 'execution', 'provenance', 'encoding-downgrade'])
def test_binary_index_checks_before_cold_or_cached_search_and_embedding(private, monkeypatch, warm, damage):
    ctx = private
    accepted = adopt(ctx)
    assert accepted['data_state'] == 'live'
    snapshot_id = accepted['provenance'][0]['snapshot_id']
    config = EmbeddingConfig(model='private-r89-unused', dimensions=3, api_key='synthetic-never-used')
    monkeypatch.setattr(embedding_service, 'require_config', lambda _db: config)
    calls = []
    class ForbiddenProvider:
        async def embed(self, *_args, **_kwargs):
            calls.append(True)
            raise AssertionError('R89 never permits a Provider call')
    ctx.app.state.embedding_adapter = ForbiddenProvider()
    document_id, plan_id, signature = '0' * 64, None, None
    if warm:
        response = search(ctx)
        assert response.status_code == 200 and response.json()['total'] == 1
        item = response.json()['items'][0]
        document_id = item['id']
        assert not any(key in item for key in ('body', 'raw_body', 'raw_capture_id'))
        prepared = ctx.client.post('/v1/knowledge/embedding-plans', json={'document_ids': [document_id]})
        assert prepared.status_code == 200, prepared.text
        plan_id = prepared.json()['id']
        with ctx.database.sessions() as db:
            signature = db.get(KnowledgeIndexState, 'accepted').signature
    damage_snapshot(ctx, snapshot_id, damage)
    response = search(ctx)
    assert response.status_code == 409 and response.json()['detail'] == {'code': 'vehicle_raw_integrity_failed'}
    prepared = ctx.client.post('/v1/knowledge/embedding-plans', json={'document_ids': [document_id]})
    assert prepared.status_code == 409 and prepared.json()['detail'] == {'code': 'vehicle_raw_integrity_failed'}
    if plan_id:
        with ctx.database.sessions() as db:
            QueryService(db, None).lock_ingestion()
            with pytest.raises(HTTPException) as raised:
                embedding_service.validate_plan(db, ctx.app.state.registry, plan_id, ctx.session_id, config)
            assert raised.value.status_code == 409 and raised.value.detail == {'code': 'vehicle_raw_integrity_failed'}
    assert calls == [] and count(ctx, KnowledgeDocument) == int(warm)
    assert count(ctx, EmbeddingPlan) == int(warm)
    with ctx.database.sessions() as db:
        state = db.get(KnowledgeIndexState, 'accepted')
        assert (state.signature if state else None) == signature


def test_encoding_downgrade_cannot_bypass_event_or_previous_baseline_integrity(private):
    ctx = private
    first = adopt(ctx)
    assert first['data_state'] == 'live'
    snapshot_id = first['provenance'][0]['snapshot_id']
    damage_snapshot(ctx, snapshot_id, 'encoding')
    # A new Session observes actual damaged columns, avoiding identity-map reuse.
    with ctx.database.sessions() as db:
        snapshot = db.get(VehicleSnapshot, snapshot_id)
        with pytest.raises(VehicleRawIntegrityError):
            _vehicle_side(db, snapshot, snapshot.observed_at)
    repeated = adopt(ctx)
    assert repeated['reason'] == 'vehicle_raw_integrity_failed'
    assert_completed(ctx, repeated['query_id'])
    assert count(ctx, VehicleSnapshot) == count(ctx, VehicleVerification) == 1
    assert count(ctx, RawCapture) == count(ctx, ParserExecution) == 2
