"""Synthetic binary admission/journaling only; no S2, PDF child or online fetch.

The R86 private fixture supplies a real local bundle and original Parser pin.
Every body below is synthetic and deliberately outside the reviewed PDF hash.
"""
from copy import deepcopy
import hashlib
import inspect
import json

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, func, select

from tire_api import captures
from tire_api.db import (AuditEvent, CaptureObject, Database, EvidenceObject, FactVersion,
                         QueryRun, RawCapture, RejectedObservation, Snapshot, UserSession, Verification)
from tire_api.main import create_app
from tire_api.object_store import ObjectStoreError
from tire_api.parser_release_models import ParserBundle, ParserDeploymentRevision, ParserSelection
from tire_api.vehicle_raw import vehicle_raw_metadata
from tire_api.vehicles import VehicleSnapshot, VehicleVerification
from test_vehicle_raw import (CURRENT, JSON_URL, SOURCE, URL, VEHICLE, capture,
                              digest, new_run, private)

PDF = b'%PDF-1.7\n%synthetic-r87-unknown-\x80\n%%EOF\n'
ASCII_PDF = b'%PDF-1.7\nsynthetic ASCII unknown revision\n%%EOF\n'
TEXT = '{"history":"原 UTF-8 字节保持"}'
IDENTITY = {'bundle_id': '1' * 64, 'parser_digest': '2' * 64, 'deployment_revision': 1}
OLD_KEYS = {'source_url', 'raw_body', 'raw_hash', 'content_type', 'parser_version', 'parser_identity'}
BODY_TABLES = (RawCapture, CaptureObject, EvidenceObject, RejectedObservation, AuditEvent)
FACT_TABLES = (Snapshot, FactVersion, Verification, VehicleSnapshot, VehicleVerification)


def binary_observation(body=PDF, *, identity=None, parser='r87-synthetic@1'):
    return {'body': body, 'body_encoding': 'binary', 'url': URL,
        'content_type': 'application/pdf', 'parser_version': parser,
        'parser_identity': deepcopy(IDENTITY if identity is None else identity)}


def trusted(observation):
    return captures.validated_observation(observation, source_id=SOURCE, query={'vehicle_id': VEHICLE})


def counts(database, models=BODY_TABLES):
    with database.sessions() as db:
        return {model.__tablename__: db.scalar(select(func.count()).select_from(model)) for model in models}


def prepared(private, *, vehicle=VEHICLE, source=SOURCE, query=None, pinned=True):
    database = private.database
    with database.sessions() as db:
        run = new_run(db, vehicle=vehicle, source=source, query=query, pinned=pinned)
        selected = db.get(ParserSelection, run.id)
        identity = {'bundle_id': selected.bundle_id, 'parser_digest': selected.descriptor['parser_digest'],
                    'deployment_revision': selected.deployment_revision} if selected else deepcopy(IDENTITY)
        observed = binary_observation(identity=identity,
            parser=selected.descriptor['parser_version'] if selected else 'r87-synthetic@1')
        db.commit()
        return run.id, observed


def journal(private, run_id, observed):
    with private.database.sessions() as db:
        run = db.get(QueryRun, run_id)
        db.commit()
        captures.before_parse_recorder(db, run)(observed)


def assert_capture_failure(call):
    with pytest.raises(captures.CaptureWriteError) as error:
        call()
    assert str(error.value) == 'evidence_capture_failed'


def test_trusted_context_is_keyword_only_and_single_argument_never_authorizes_binary():
    signature = inspect.signature(captures.validated_observation)
    assert signature.parameters['source_id'].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters['query'].kind is inspect.Parameter.KEYWORD_ONLY
    observed = binary_observation()
    observed['source_id'], observed['query'] = SOURCE, {'vehicle_id': VEHICLE}
    assert captures.validated_observation(observed) is None
    assert captures.validated_observation(observed, source_id=SOURCE) is None
    assert captures.validated_observation(observed, query={'vehicle_id': VEHICLE}) is None
    assert captures.validated_observation(observed, source_id='other-source', query={'vehicle_id': VEHICLE}) is None


@pytest.mark.parametrize('body', [PDF, ASCII_PDF, b'%PDF-' + b'x' * (8 * 1024 * 1024 - 5)], ids=['synthetic-binary-pdf', 'synthetic-ascii-pdf', 'synthetic-max-8mib-pdf'])
def test_unknown_pdf_revision_is_admitted_by_actual_bytes_without_claiming_parse_success(body):
    observed = binary_observation(body)
    before = deepcopy(observed)
    actual = trusted(observed)
    assert set(actual) == OLD_KEYS | {'body_encoding'}
    assert actual == {'source_url': URL, 'raw_body': body,
        'raw_hash': hashlib.sha256(body).hexdigest(), 'content_type': 'application/pdf',
        'parser_version': 'r87-synthetic@1', 'parser_identity': IDENTITY, 'body_encoding': 'binary'}
    assert observed == before


@pytest.mark.parametrize('mutation', [
    'missing-encoding', 'wrong-encoding', 'string', 'bytearray', 'memoryview', 'empty',
    'too-large', 'signature', 'url-host', 'url-query', 'url-fragment', 'mime',
    'parser-empty', 'parser-control', 'identity-extra', 'identity-missing',
])
def test_binary_admission_rejects_invalid_shapes_and_untrusted_metadata(mutation):
    observed = binary_observation()
    if mutation == 'missing-encoding':
        observed.pop('body_encoding')
    elif mutation == 'wrong-encoding':
        observed['body_encoding'] = 'base64'
    elif mutation == 'string':
        observed['body'] = '%PDF-1.7 text is not raw bytes'
    elif mutation == 'bytearray':
        observed['body'] = bytearray(PDF)
    elif mutation == 'memoryview':
        observed['body'] = memoryview(PDF)
    elif mutation == 'empty':
        observed['body'] = b''
    elif mutation == 'too-large':
        observed['body'] = b'%PDF-' + b'x' * (8 * 1024 * 1024 - 4)
    elif mutation == 'signature':
        observed['body'] = b'not a PDF'
    elif mutation == 'url-host':
        observed['url'] = 'https://other.invalid/parameters.pdf'
    elif mutation == 'url-query':
        observed['url'] = URL + '?alternate=1'
    elif mutation == 'url-fragment':
        observed['url'] = URL + '#page=3'
    elif mutation == 'mime':
        observed['content_type'] = 'application/octet-stream'
    elif mutation == 'parser-empty':
        observed['parser_version'] = ''
    elif mutation == 'parser-control':
        observed['parser_version'] = 'r87\nparser'
    elif mutation == 'identity-extra':
        observed['parser_identity']['untrusted'] = True
    else:
        observed['parser_identity'] = None
    assert trusted(observed) is None


@pytest.mark.parametrize('query', [None, {}, {'vehicle_id': CURRENT}, {'vehicle_id': VEHICLE, 'extra': True}, {'vehicle_id': 1}])
def test_binary_admission_requires_exact_first_generation_query(query):
    assert captures.validated_observation(binary_observation(), source_id=SOURCE, query=query) is None


@pytest.mark.parametrize('encoding', [None, 'utf-8'])
def test_single_argument_utf8_keeps_original_keys_bytes_hash_and_identity_behavior(encoding):
    observed = {'body': TEXT, 'url': JSON_URL, 'content_type': 'application/json',
                'parser_version': 'r87-legacy@1', 'parser_identity': None}
    if encoding is not None:
        observed['body_encoding'] = encoding
    actual = captures.validated_observation(observed)
    assert set(actual) == OLD_KEYS
    assert actual['raw_body'] == TEXT.encode('utf-8', errors='strict')
    assert actual['raw_hash'] == hashlib.sha256(TEXT.encode('utf-8')).hexdigest()
    assert actual['parser_identity'] is None
    for body in ('', '\ud800', b'bytes are not legacy text'):
        assert captures.validated_observation({**observed, 'body': body}) is None
    assert captures.validated_observation({**observed, 'body_encoding': 'unknown'}) is None
    assert captures.validated_observation({**observed, 'content_type': 'application/pdf'}) is None
    assert captures.validated_observation({**observed, 'url': JSON_URL + '?not-allowed=1'}) is None


@pytest.mark.parametrize('failure', ['source', 'query-extra', 'query-key', 'missing-pin',
    'identity', 'identity-extra', 'parser-version', 'mime', 'signature', 'too-large'])
def test_pre_admission_and_original_pin_fail_before_object_put_with_no_evidence_writes(private, monkeypatch, failure):
    source = 'other-source' if failure == 'source' else SOURCE
    query = {'vehicle_id': VEHICLE, 'extra': True} if failure == 'query-extra' else None
    run_id, observed = prepared(private, source=source, query=query, pinned=failure != 'missing-pin')
    if failure == 'query-key':
        with private.database.sessions() as db:
            db.get(QueryRun, run_id).query_key = '0' * 64
            db.commit()
    elif failure == 'identity':
        observed['parser_identity']['bundle_id'] = 'f' * 64
    elif failure == 'identity-extra':
        observed['parser_identity']['caller'] = True
    elif failure == 'parser-version':
        observed['parser_version'] = 'forged@1'
    elif failure == 'mime':
        observed['content_type'] = 'text/html'
    elif failure == 'signature':
        observed['body'] = b'not a PDF'
    elif failure == 'too-large':
        observed['body'] = b'%PDF-' + b'x' * (8 * 1024 * 1024 - 4)
    before, puts = counts(private.database), []

    def forbidden_put(body):
        puts.append(True)
        raise AssertionError('pre-admission failure must precede persistence')

    monkeypatch.setattr(private.database.object_store, 'put', forbidden_put)
    reached_parser = []

    def caller():
        journal(private, run_id, observed)
        reached_parser.append(True)  # Synthetic ordering marker, no Parser call.

    assert_capture_failure(caller)
    assert puts == reached_parser == []
    assert counts(private.database) == before


@pytest.mark.parametrize('body', [PDF, ASCII_PDF])
def test_successful_journal_commits_objects_capture_and_audit_before_caller_rollback(private, body):
    run_id, observed = prepared(private)
    observed['body'] = body
    with private.database.sessions() as caller:
        run = caller.get(QueryRun, run_id)
        caller.commit()
        record = captures.before_parse_recorder(caller, run)
        record(observed)
        # A separate session is the stand-in for a parser seeing the receipt.
        with private.database.sessions() as db:
            cap = db.scalar(select(RawCapture).where(RawCapture.query_id == run_id))
            assert cap.raw_body == body and cap.body_encoding == 'binary'
            assert cap.raw_hash == hashlib.sha256(body).hexdigest() and cap.byte_count == len(body)
            reference = db.get(CaptureObject, cap.id)
            assert reference.raw_hash == cap.raw_hash
            assert db.get(EvidenceObject, cap.raw_hash).byte_count == len(body)
            assert private.database.object_store.get(cap.raw_hash, len(body)) == body
            assert db.get(QueryRun, run_id).state == 'pending'
            assert db.scalar(select(AuditEvent).where(AuditEvent.action == 'raw_response_received')) is not None
            assert vehicle_raw_metadata(db, cap)['parse_method'] is None
        run.reason = 'synthetic downstream failure'
        caller.flush()
        caller.rollback()
    assert counts(private.database)[RawCapture.__tablename__] == 1
    assert all(value == 0 for value in counts(private.database, FACT_TABLES).values())
    with private.database.sessions() as db:
        assert db.get(QueryRun, run_id).reason is None


def test_binary_recording_refuses_an_uncommitted_caller_without_rolling_back_its_marker(private, monkeypatch):
    run_id, observed = prepared(private)
    puts = []

    def forbidden_put(body):
        puts.append(True)
        raise AssertionError('caller transaction must be rejected before object persistence')

    monkeypatch.setattr(private.database.object_store, 'put', forbidden_put)
    with private.database.sessions() as db:
        run = db.get(QueryRun, run_id)
        run.reason = 'r87-pending-caller-marker'
        db.flush()
        assert db.in_transaction()
        assert_capture_failure(lambda: captures.before_parse_recorder(db, run)(observed))
        assert puts == [] and db.in_transaction() and run.reason == 'r87-pending-caller-marker'
        assert db.scalar(select(func.count()).select_from(RawCapture)) == 0
        db.commit()
    with private.database.sessions() as db:
        assert db.get(QueryRun, run_id).reason == 'r87-pending-caller-marker'


def test_static_pool_binary_journal_fails_before_checkout_without_closing_caller_transaction(private, monkeypatch):
    from sqlalchemy.pool import StaticPool

    memory = Database('sqlite:///:memory:')
    try:
        memory.initialize()
        assert type(memory.engine.pool) is StaticPool
        # Copy only trusted registry/session rows into the private memory DB.
        # This is a fixture, not a journal or a product migration harness.
        with private.database.sessions() as source, memory.sessions() as target:
            for model in (UserSession, ParserBundle, ParserDeploymentRevision):
                rows = [dict(row) for row in source.execute(select(model.__table__)).mappings()]
                target.execute(model.__table__.insert(), rows)
            target.commit()
        with memory.sessions() as db:
            run = new_run(db)
            selected = db.get(ParserSelection, run.id)
            observed = binary_observation(identity={'bundle_id': selected.bundle_id,
                'parser_digest': selected.descriptor['parser_digest'], 'deployment_revision': selected.deployment_revision},
                parser=selected.descriptor['parser_version'])
            capture(db, run, PDF, observed=observed)
            db.commit()
            puts, checkouts = [], []

            def forbidden_put(body):
                puts.append(True)
                raise AssertionError('shared pool must fail before object persistence')

            def checkout(*args):
                checkouts.append(True)

            monkeypatch.setattr(memory.object_store, 'put', forbidden_put)
            event.listen(memory.engine, 'checkout', checkout)
            try:
                # Prove the pool gate itself, without an active caller
                # transaction allowing the separate transaction gate to win.
                assert not db.in_transaction()
                assert_capture_failure(lambda: captures.before_parse_recorder(db, run)(observed))
                assert captures.retain_rejected_response(db, run, observed, 'parser') is None
                assert not db.in_transaction() and puts == checkouts == []
                run.reason = 'r87-shared-pool-pending-marker'
                db.flush()
                # The marker setup may check out the caller's own connection.
                checkouts.clear()
                assert_capture_failure(lambda: captures.before_parse_recorder(db, run)(observed))
                assert captures.retain_rejected_response(db, run, observed, 'parser') is None
            finally:
                event.remove(memory.engine, 'checkout', checkout)
            assert puts == checkouts == []
            assert db.in_transaction() and db.connection().connection.driver_connection.in_transaction
            assert run.reason == 'r87-shared-pool-pending-marker'
            assert db.scalar(select(QueryRun.reason).where(QueryRun.id == run.id)) == run.reason
            assert db.scalar(select(func.count()).select_from(RejectedObservation)) == 0
            db.commit()
        with memory.sessions() as db:
            assert db.scalar(select(QueryRun.reason)) == 'r87-shared-pool-pending-marker'
    finally:
        memory.close()


@pytest.mark.parametrize('failure', ['object-put', 'capture-insert', 'reference-insert'])
def test_capture_failures_are_fixed_and_do_not_claim_zero_orphan_objects(private, monkeypatch, failure):
    run_id, observed = prepared(private)
    store, puts = private.database.object_store, []
    original_put = store.put

    def tracked_put(body):
        puts.append(True)
        if failure == 'object-put':
            raise ObjectStoreError('synthetic private storage diagnostic must not escape')
        return original_put(body)

    def fail_sql(_connection, _cursor, sql, *_args):
        target = 'raw_captures' if failure == 'capture-insert' else 'capture_objects'
        if failure != 'object-put' and sql.startswith('INSERT INTO ' + target):
            raise RuntimeError('synthetic private database diagnostic must not escape')

    monkeypatch.setattr(store, 'put', tracked_put)
    event.listen(private.database.engine, 'before_cursor_execute', fail_sql)
    marker = []
    try:
        def caller():
            journal(private, run_id, observed)
            marker.append(True)
        assert_capture_failure(caller)
    finally:
        event.remove(private.database.engine, 'before_cursor_execute', fail_sql)
    assert puts == [True] and marker == []
    assert all(value == 0 for value in counts(private.database).values())
    if failure != 'object-put':
        # Valid admission can leave an unreferenced immutable file after DB
        # rollback. This test does not invoke any automatic cleanup procedure.
        assert store.path(hashlib.sha256(PDF).hexdigest()).is_file()


@pytest.mark.parametrize('stage,code', [('parser', 'vehicle_pdf_revision_unreviewed'), ('parser', 'vehicle_pdf_invalid'), ('schema', 'vehicle_source_schema_changed')])
def test_unknown_pdf_rejection_uses_the_same_durable_capture_and_authoritative_object(private, stage, code):
    run_id, observed = prepared(private)
    journal(private, run_id, observed)
    observed['parser_error'] = code
    with private.database.sessions() as db:
        run = db.get(QueryRun, run_id)
        cap = db.scalar(select(RawCapture).where(RawCapture.query_id == run_id))
        rejection_id = captures.retain_rejected_response(db, run, observed, stage)
        assert rejection_id is not None
        db.commit()
        row = db.get(RejectedObservation, rejection_id)
        assert row.reason == code and row.raw_body == cap.raw_body == PDF
        assert row.raw_hash == cap.raw_hash == hashlib.sha256(PDF).hexdigest()
        metadata = vehicle_raw_metadata(db, row)
        assert metadata['raw_capture_id'] == cap.id and metadata['parse_method'] is metadata['mapping_id'] is None
    assert all(value == 0 for value in counts(private.database, FACT_TABLES).values())


@pytest.mark.parametrize('failure', ['missing-capture', 'uncommitted-capture', 'wrong-body', 'missing-object', 'invalid-signature'])
def test_binary_rejection_cannot_retain_uncommitted_or_inconsistent_originals(private, failure):
    run_id, observed = prepared(private)
    if failure not in ('missing-capture', 'uncommitted-capture'):
        journal(private, run_id, observed)
    with private.database.sessions() as db:
        run = db.get(QueryRun, run_id)
        if failure == 'uncommitted-capture':
            run.reason = 'r87-uncommitted-capture-marker'
            capture(db, run, PDF, observed=observed)
        elif failure == 'wrong-body':
            observed['body'] = PDF[:-1] + b'X'
        elif failure == 'missing-object':
            private.database.object_store.path(hashlib.sha256(PDF).hexdigest()).unlink()
        elif failure == 'invalid-signature':
            observed['body'] = b'not a PDF'
        before = db.scalar(select(func.count()).select_from(RejectedObservation))
        assert captures.retain_rejected_response(db, run, observed, 'parser') is None
        assert db.scalar(select(func.count()).select_from(RejectedObservation)) == before == 0
        if failure == 'uncommitted-capture':
            assert db.in_transaction() and db.connection().connection.driver_connection.in_transaction
            assert db.get(QueryRun, run_id).reason == 'r87-uncommitted-capture-marker'
            assert db.scalar(select(func.count()).select_from(RawCapture)) == 1
        db.rollback()
    assert counts(private.database)[RejectedObservation.__tablename__] == 0


@pytest.mark.parametrize('code', ['vehicle_pdf_invalid', 'vehicle_pdf_revision_unreviewed'])
def test_pdf_failure_codes_are_explicit_safe_literals(code):
    assert captures.parser_failure_reason(code) == code


@pytest.mark.parametrize('value', ['unlisted_synthetic_private_diagnostic', {'code': 'vehicle_pdf_invalid'}, None, 42])
def test_unlisted_parser_diagnostics_are_not_retained_as_failure_text(private, value):
    assert captures.parser_failure_reason(value) == 'parser_failed'
    run_id, observed = prepared(private)
    journal(private, run_id, observed)
    observed['parser_error'] = value
    with private.database.sessions() as db:
        row_id = captures.retain_rejected_response(db, db.get(QueryRun, run_id), observed, 'parser')
        db.commit()
        row = db.get(RejectedObservation, row_id)
        assert row.reason == 'parser_failed'
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == 'rejected_response_retained'))
        assert 'unlisted_synthetic_private_diagnostic' not in json.dumps(audit.detail)


@pytest.mark.parametrize('body', [PDF, ASCII_PDF])
def test_binary_capture_and_rejected_history_fail_closed_409_without_legacy_decode(private, body):
    run_id, observed = prepared(private)
    observed['body'] = body
    journal(private, run_id, observed)
    with private.database.sessions() as db:
        run = db.get(QueryRun, run_id)
        observed['parser_error'] = 'vehicle_pdf_revision_unreviewed'
        rejected_id = captures.retain_rejected_response(db, run, observed, 'parser')
        db.commit()
        cap = db.scalar(select(RawCapture).where(RawCapture.query_id == run_id))
        cap_id = cap.id
        with pytest.raises(HTTPException) as error:
            captures.checked_capture_bytes(db, cap)
        assert error.value.status_code == 409
        assert error.value.detail == {'code': 'binary_evidence_format_required'}
    app = create_app(str(private.database.engine.url))
    with TestClient(app, raise_server_exceptions=False) as client:
        for url in ('/v1/captures/' + cap_id, '/v1/quarantines/' + rejected_id):
            response = client.get(url + '?mode=history')
            assert response.status_code == 409
            assert response.json() == {'detail': {'code': 'binary_evidence_format_required'}}
            assert '%PDF-' not in response.text and 'content_path' not in response.text


def test_original_utf8_capture_and_rejected_history_remain_text_200(private):
    with private.database.sessions() as db:
        run = new_run(db, vehicle=CURRENT)
        db.commit()
        observed = {'body': TEXT, 'url': JSON_URL, 'content_type': 'application/json',
                    'parser_version': 'r87-legacy@1', 'parser_identity': None}
        captures.before_parse_recorder(db, run)(observed)
        row_id = captures.retain_rejected_response(db, run, observed, 'parser')
        db.commit()
        cap = db.scalar(select(RawCapture).where(RawCapture.query_id == run.id))
        cap_id = cap.id
        assert captures.checked_capture_bytes(db, cap) == (TEXT.encode('utf-8'), 'object_store')
    app = create_app(str(private.database.engine.url))
    with TestClient(app) as client:
        capture_response = client.get('/v1/captures/' + cap_id + '?mode=history')
        rejected_response = client.get('/v1/quarantines/' + row_id + '?mode=history')
        assert capture_response.status_code == rejected_response.status_code == 200
        assert capture_response.json()['body'] == rejected_response.json()['body'] == TEXT
        assert capture_response.json()['receipt_only'] is True
        assert rejected_response.json()['accepted'] is False

