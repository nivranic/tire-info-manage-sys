"""Managed-only V2 HTTP coverage: actual private S2 child plus synthetic negatives.

No online capture, production permission, SDK runtime, UI/Native or PG claim.
The extra quarantine/rejected rows are explicit private response fixtures; the
separate quality case below creates a real quality rejection through ingestion.
"""
from copy import deepcopy
from datetime import timedelta
import hashlib

import pytest
from sqlalchemy import func, select, update

from test_vehicle_binary_ingestion import adopt, assert_completed, private, private_mapping_revision
from test_vehicle_pdf_runtime import reviewed_pdf
from tire_api import vehicle_raw
from tire_api.db import (AuditEvent, CaptureObject, QueryRun, RawCapture,
                         RejectedObservation, Snapshot, SourceQuarantine, UserSession, uid, utcnow)
from tire_api.documents import record_object
from tire_api.domain import digest
from tire_api.parser_release_models import ParserExecution, ParserSelection
from tire_api.quality import assess_quality
from tire_api.vehicle_quality import assess_vehicle_quality
from tire_api.vehicles import (VehicleManufacturer, VehicleModel, VehicleQuarantine,
                               VehicleSnapshot, fitment_fact_hash)


V2 = {'evidence_format', 'body_encoding', 'body', 'raw_capture_id', 'raw_hash', 'byte_count',
      'content_type', 'content_path', 'parse_method', 'mapping_id'}
VEHICLE = V2 | {'id', 'vehicle_id', 'snapshot_id', 'source_id', 'source_url', 'source_page',
    'parser_version', 'parser_identity', 'observed_at', 'evidence_path', 'quality_review',
    'verified_at', 'data_state', 'documents'}
CAPTURE = V2 | {'id', 'query_id', 'source_id', 'target_kind', 'source_url', 'parser_version',
    'observed_at', 'parser_identity', 'query_state', 'query_reason', 'query',
    'processing_unconfirmed', 'evidence_path', 'data_state', 'receipt_only', 'storage_kind'}
QUARANTINE = V2 | {'id', 'query_id', 'source_id', 'source_url', 'parser_version', 'observed_at',
    'previous_snapshot_id', 'status', 'kind', 'target_kind', 'reason_codes', 'metrics',
    'evidence_path', 'data_state', 'accepted', 'candidates', 'quality'}
PARAMS = {'format': 'raw-evidence-v2', 'mode': 'history'}
UNKNOWN = b'%PDF-1.7\n%synthetic-unparsed-r93-\x80\n%%EOF\n'
TEXT = '{"history":"原 UTF-8 字节，不规范化"}'
DOWNLOAD_ACTIONS = {'vehicle_evidence_downloaded', 'raw_capture_downloaded', 'quarantine_evidence_downloaded'}


def grant(monkeypatch, *, original=True, structured=True):
    base = vehicle_raw._vehicle_original_policy
    def policy(binding):
        return {**base(binding), 'local_original_read': 'allowed' if original else 'pending_review',
                'structured_fact_use': 'allowed' if structured else 'pending_review'}
    monkeypatch.setattr(vehicle_raw, '_vehicle_original_policy', policy)


def rejected_row(db, capture):
    row = RejectedObservation(id=uid(), query_id=capture.query_id, source_id=capture.source_id,
        query_key=capture.query_key, target_kind=capture.target_kind, stage='parser',
        reason='vehicle_pdf_revision_unreviewed', source_url=capture.source_url,
        raw_hash=capture.raw_hash, raw_body=capture.raw_body, body_encoding=capture.body_encoding,
        content_type=capture.content_type, parser_version=capture.parser_version,
        parser_identity=deepcopy(capture.parser_identity))
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def evidence(private):
    first = adopt(private)
    assert first['data_state'] == 'live'
    private.snapshot_id = first['provenance'][0]['snapshot_id']
    private.capture_id = assert_completed(private, first['query_id'])
    private.pdf = private.adapter.load()
    with private.database.sessions() as db:
        snapshot = db.get(VehicleSnapshot, private.snapshot_id)
        capture = db.get(RawCapture, private.capture_id)
        quarantine = VehicleQuarantine(id=uid(), query_id=capture.query_id, vehicle_id=snapshot.vehicle_id,
            source_id=snapshot.source_id, previous_snapshot_id=snapshot.id, source_url=snapshot.source_url,
            raw_hash=snapshot.raw_hash, body=None, body_encoding='binary', raw_capture_id=capture.id,
            content_type=snapshot.content_type, parser_version=snapshot.parser_version,
            parser_identity=deepcopy(snapshot.parser_identity), payload=deepcopy(snapshot.payload),
            quality=assess_vehicle_quality(snapshot.payload, snapshot.payload))
        db.add(quarantine)
        run = QueryRun(id=uid(), session_id=private.session_id, source_id=capture.source_id,
            query={'vehicle_id': vehicle_raw.FIRST_GENERATION_ID}, query_key=capture.query_key,
            fallback_policy='never')
        db.add(run)
        db.flush()
        selected = db.get(ParserSelection, capture.query_id)
        db.add(ParserSelection(query_run_id=run.id, source_id=selected.source_id,
            deployment_id=selected.deployment_id, bundle_id=selected.bundle_id,
            deployment_revision=selected.deployment_revision, descriptor=deepcopy(selected.descriptor)))
        unknown = RawCapture(id=uid(), query_id=run.id, source_id=capture.source_id,
            query_key=run.query_key, target_kind='vehicle', source_url=vehicle_raw.PDF_URL,
            raw_hash=hashlib.sha256(UNKNOWN).hexdigest(), raw_body=UNKNOWN, byte_count=len(UNKNOWN),
            body_encoding='binary', content_type='application/pdf', parser_version=capture.parser_version,
            parser_identity=deepcopy(capture.parser_identity))
        db.add(unknown)
        db.flush()
        db.add(CaptureObject(capture_id=unknown.id, raw_hash=record_object(db, UNKNOWN)))
        rejected = rejected_row(db, unknown)
        db.commit()
        private.quarantine_id, private.unknown_id, private.rejected_id = quarantine.id, unknown.id, rejected.id
        private.unknown_query = run.id
    private.paths = {
        'snapshot': f'/v1/vehicle-evidence/{private.snapshot_id}',
        'capture': f'/v1/captures/{private.capture_id}',
        'quarantine': f'/v1/quarantines/{private.quarantine_id}',
        'unknown': f'/v1/captures/{private.unknown_id}',
        'rejected': f'/v1/quarantines/{private.rejected_id}',
    }
    return private


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json() == {'detail': {'code': code}}


def read(ctx, path):
    return ctx.client.get(path, params=PARAMS)


def download(ctx, path, **kwargs):
    return ctx.client.get(path + '/content', params={'mode': 'history'}, **kwargs)


def test_actual_s2_v2_envelopes_content_headers_full_bytes_and_audit(evidence, monkeypatch):
    ctx = evidence
    grant(monkeypatch)
    for kind, path in ctx.paths.items():
        response = read(ctx, path)
        assert response.status_code == 200, response.text
        body = response.json()
        expected = (VEHICLE if kind == 'snapshot' else CAPTURE if kind in ('capture', 'unknown')
                    else QUARANTINE | ({'vehicle_id', 'vehicle_payload'} if kind == 'quarantine' else {'stage'}))
        assert set(body) == expected
        raw = UNKNOWN if kind in ('unknown', 'rejected') else ctx.pdf
        assert body['evidence_format'] == 'raw-evidence-v2' and body['body_encoding'] == 'binary'
        assert body['body'] is None and body['byte_count'] == len(raw)
        assert body['raw_hash'] == hashlib.sha256(raw).hexdigest()
        assert body['content_type'] == 'application/pdf' and body['data_state'] == 'local_snapshot'
        assert body['content_path'] == path + '/content?mode=history'
        if kind in ('snapshot', 'quarantine'):
            assert body['parse_method'] == 'sha256_bound_reviewed_mapping'
            assert body['mapping_id'] == 'xiaomi-su7-first-generation-pdf@1'
        else:
            assert body['parse_method'] is None and body['mapping_id'] is None
        if kind in ('quarantine', 'rejected'):
            assert body['accepted'] is False and body['status'] == 'quarantined'
        if kind == 'rejected':
            assert body['candidates'] == [] and body['quality'] is None and body['metrics'] is None
            assert body['stage'] == 'parser'
        if kind in ('capture', 'unknown'):
            assert body['receipt_only'] is True and body['storage_kind'] == 'object_store'
        result = download(ctx, path, headers={'Range': 'bytes=0-4', 'If-Range': 'synthetic'})
        assert result.status_code == 200 and result.content == raw
        assert result.headers['content-type'] == 'application/pdf'
        assert result.headers['content-length'] == str(len(raw))
        assert result.headers['content-disposition'] == 'attachment; filename="vehicle-evidence.pdf"'
        assert result.headers['cache-control'] == 'no-store'
        assert result.headers['x-content-type-options'] == 'nosniff'
        assert result.headers['content-security-policy'] == "sandbox; default-src 'none'"
        assert result.headers['x-evidence-sha256'] == body['raw_hash']
        assert 'content-range' not in result.headers and 'accept-ranges' not in result.headers
    with ctx.database.sessions() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action.in_(DOWNLOAD_ACTIONS))))
        assert len(events) == 5 and all(row.session_id == ctx.session_id for row in events)
        assert {row.action for row in events} == DOWNLOAD_ACTIONS


def test_pending_policy_and_two_purposes_never_grant_each_other(evidence, monkeypatch):
    ctx = evidence
    for path in ctx.paths.values():
        assert_error(read(ctx, path), 403, 'vehicle_original_read_not_allowed')
        assert_error(download(ctx, path), 403, 'vehicle_original_read_not_allowed')
    with ctx.database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action.in_(DOWNLOAD_ACTIONS))) == 0
    grant(monkeypatch, original=True, structured=False)
    for kind, path in ctx.paths.items():
        if kind in ('snapshot', 'quarantine'):
            assert_error(read(ctx, path), 403, 'vehicle_structured_fact_use_not_allowed')
        else:
            assert read(ctx, path).status_code == 200
        assert download(ctx, path).status_code == 200
    grant(monkeypatch, original=False, structured=True)
    for path in ctx.paths.values():
        assert_error(read(ctx, path), 403, 'vehicle_original_read_not_allowed')
        assert_error(download(ctx, path), 403, 'vehicle_original_read_not_allowed')


def test_unparsed_capture_and_rejected_original_need_no_accepted_capsule(evidence, monkeypatch):
    ctx = evidence
    grant(monkeypatch, structured=False)
    def forbidden(*_args, **_kwargs):
        raise AssertionError('raw history must not ask for an accepted consumer capsule')
    monkeypatch.setattr(vehicle_raw, 'checked_vehicle_consumer_capsule', forbidden)
    with ctx.database.sessions() as db:
        assert db.get(ParserExecution, ctx.unknown_query) is None
        assert db.scalar(select(func.count()).select_from(VehicleSnapshot).where(
            VehicleSnapshot.raw_capture_id == ctx.unknown_id)) == 0
    for kind in ('unknown', 'rejected'):
        body = read(ctx, ctx.paths[kind]).json()
        assert body['raw_capture_id'] == ctx.unknown_id
        assert body['parse_method'] is None and body['mapping_id'] is None
        assert download(ctx, ctx.paths[kind]).content == UNKNOWN


def test_real_quality_quarantine_preserves_original_mapping_and_unaccepted_state(private, monkeypatch):
    first = adopt(private)
    assert first['data_state'] == 'live'
    private_mapping_revision(private, reduce=True)
    failed = adopt(private)
    assert failed['reason'] == 'source_quality_quarantined'
    capture_id = assert_completed(private, failed['query_id'])
    with private.database.sessions() as db:
        row = db.scalar(select(VehicleQuarantine))
        assert row.raw_capture_id == capture_id
        path = f'/v1/quarantines/{row.id}'
        assert db.scalar(select(func.count()).select_from(VehicleSnapshot)) == 1
    grant(monkeypatch)
    result = read(private, path)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body['accepted'] is False and body['mapping_id'].endswith('@2')
    assert body['previous_snapshot_id'] == first['provenance'][0]['snapshot_id']
    assert download(private, path).content == private.adapter.load()


def text_rows(ctx):
    raw = TEXT.encode('utf-8')
    with ctx.database.sessions() as db:
        captures = []
        for index, mime in enumerate(('text/html', 'application/json', 'text/javascript',
                                      'application/javascript', 'text/plain')):
            query = {'synthetic_text': index}
            run = QueryRun(id=uid(), session_id=ctx.session_id, source_id='synthetic-text',
                query=query, query_key=digest(query), fallback_policy='never')
            db.add(run)
            db.flush()
            cap = RawCapture(id=uid(), query_id=run.id, source_id=run.source_id, query_key=run.query_key,
                target_kind='recall' if index == 1 else 'tire', source_url='https://example.test/history',
                raw_hash=hashlib.sha256(raw).hexdigest(), raw_body=raw, byte_count=len(raw),
                body_encoding='utf-8', content_type=mime, parser_version='synthetic-text@1', parser_identity=None)
            db.add(cap)
            db.flush()
            captures.append(cap)
        first = captures[0]
        rejected = rejected_row(db, first)
        baseline = Snapshot(id=uid(), source_id=first.source_id, query_key=first.query_key,
            source_url=first.source_url, raw_hash=first.raw_hash, body=TEXT, content_type=first.content_type,
            parser_version=first.parser_version, parser_identity=None, parsed_variants=[])
        db.add(baseline)
        db.flush()
        quarantine = SourceQuarantine(id=uid(), query_id=first.query_id, source_id=first.source_id,
            query_key=first.query_key, previous_snapshot_id=baseline.id, source_url=first.source_url,
            raw_hash=first.raw_hash, body=TEXT, content_type=first.content_type,
            parser_version=first.parser_version, parser_identity=None, candidates=[], quality=assess_quality([], []))
        db.add(quarantine)
        if db.get(VehicleManufacturer, 'xiaomi') is None:
            db.add(VehicleManufacturer(id='xiaomi', name='Synthetic text directory'))
            db.flush()
        if db.get(VehicleModel, vehicle_raw.CURRENT_ID) is None:
            db.add(VehicleModel(id=vehicle_raw.CURRENT_ID, manufacturer_id='xiaomi', name='Synthetic current',
                generation='synthetic', region='CN', source_vehicle_id='synthetic-current'))
            db.flush()
        payload = {'vehicle': {'id': vehicle_raw.CURRENT_ID}, 'trims': [], 'fitments': [],
                   'footnotes': [], 'documents': []}
        legacy = VehicleSnapshot(id=uid(), vehicle_id=vehicle_raw.CURRENT_ID, source_id=vehicle_raw.SOURCE_ID,
            source_url=vehicle_raw.JSON_URL, raw_hash=hashlib.sha256(raw).hexdigest(), body=TEXT,
            body_encoding='utf-8', raw_capture_id=None, content_type='application/json',
            parser_version='synthetic-current@1', parser_identity=None, payload=payload,
            fact_hash=fitment_fact_hash(payload), fact_version=1)
        db.add(legacy)
        db.commit()
        return {'vehicle': f'/v1/vehicle-evidence/{legacy.id}',
                'captures': [f'/v1/captures/{cap.id}' for cap in captures],
                'capture_id': first.id, 'quarantine_id': quarantine.id, 'rejected_id': rejected.id,
                'quarantine': f'/v1/quarantines/{quarantine.id}',
                'rejected': f'/v1/quarantines/{rejected.id}'}


def test_legacy_vehicle_and_all_nonvehicle_text_mimes_keep_old_envelopes(private):
    rows = text_rows(private)
    paths = [rows['vehicle'], *rows['captures'], rows['quarantine'], rows['rejected']]
    for path in paths:
        legacy = private.client.get(path, params={} if path == rows['vehicle'] else {'mode': 'history'})
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()['body'] == TEXT and not (set(legacy.json()) & {'evidence_format', 'body_encoding'})
        result = read(private, path)
        assert result.status_code == 200, result.text
        body = result.json()
        expected = (VEHICLE if path == rows['vehicle'] else CAPTURE if path in rows['captures']
                    else QUARANTINE | ({'stage'} if path == rows['rejected'] else set()))
        assert set(body) == expected
        assert body['body_encoding'] == 'utf-8' and body['body'] == TEXT
        assert body['raw_hash'] == hashlib.sha256(TEXT.encode('utf-8')).hexdigest()
        assert body['byte_count'] == len(TEXT.encode('utf-8'))
        assert body['content_path'] is None and body['parse_method'] is None and body['mapping_id'] is None
        if path == rows['vehicle']:
            assert body['raw_capture_id'] is None
        elif path in (rows['quarantine'], rows['rejected']):
            assert body['raw_capture_id'] == rows['capture_id']
        assert_error(download(private, path), 409, 'raw_evidence_content_unavailable')


@pytest.mark.parametrize('damage', ['missing', 'same-length'])
def test_binary_authoritative_object_damage_is_503_before_pending_permission(evidence, damage):
    ctx = evidence
    path = ctx.database.object_store.path(hashlib.sha256(ctx.pdf).hexdigest())
    if damage == 'missing':
        path.unlink()
    else:
        path.write_bytes(ctx.pdf[:-1] + bytes([ctx.pdf[-1] ^ 1]))
    for kind in ('snapshot', 'capture', 'quarantine'):
        assert_error(read(ctx, ctx.paths[kind]), 503, 'vehicle_raw_integrity_failed')
        assert_error(download(ctx, ctx.paths[kind]), 503, 'vehicle_raw_integrity_failed')


@pytest.mark.parametrize('kind', ['snapshot', 'capture', 'quarantine', 'rejected'])
def test_fixed_first_generation_identity_cannot_be_downgraded_to_utf8(evidence, kind):
    ctx = evidence
    text = b'{"synthetic":"legal UTF8 columns cannot grant first-generation rights"}'
    raw_hash = hashlib.sha256(text).hexdigest()
    with ctx.database.sessions() as db:
        model = VehicleSnapshot if kind == 'snapshot' else VehicleQuarantine if kind == 'quarantine' else (
            RawCapture if kind == 'capture' else RejectedObservation)
        row_id = getattr(ctx, kind + '_id')
        row = db.get(model, row_id)
        capture_id = row.raw_capture_id if kind in ('snapshot', 'quarantine') else (
            row.id if kind == 'capture' else ctx.unknown_id)
        capture = db.get(RawCapture, capture_id)
        saved = record_object(db, text)
        db.flush()
        # Deliberate low-level private corruption; production ORM history stays immutable.
        values = {'body_encoding': 'utf-8', 'content_type': 'application/json',
                  'source_url': vehicle_raw.JSON_URL, 'raw_hash': raw_hash}
        db.execute(CaptureObject.__table__.update().where(CaptureObject.capture_id == capture.id).values(raw_hash=saved))
        db.execute(RawCapture.__table__.update().where(RawCapture.id == capture.id).values(
            **values, raw_body=text, byte_count=len(text)))
        if kind in ('snapshot', 'quarantine'):
            db.execute(model.__table__.update().where(model.id == row_id).values(**values, body=text.decode('utf-8')))
        elif kind == 'rejected':
            db.execute(model.__table__.update().where(model.id == row_id).values(**values, raw_body=text))
        db.commit()  # All current SQLite CHECK constraints still hold.
    path = ctx.paths[kind]
    assert_error(ctx.client.get(path, params={'mode': 'history'}), 409, 'binary_evidence_format_required')
    assert_error(read(ctx, path), 503, 'vehicle_raw_integrity_failed')
    assert_error(download(ctx, path), 503, 'vehicle_raw_integrity_failed')


@pytest.mark.parametrize('damage', ['mime', 'utf8', 'hash', 'object'])
def test_nonvehicle_v2_text_integrity_and_existing_object_are_authoritative(private, damage):
    rows = text_rows(private)
    with private.database.sessions() as db:
        cap = db.get(RawCapture, rows['capture_id'])
        if damage == 'mime':
            values = {'content_type': 'image/png'}
        elif damage == 'utf8':
            values = {'raw_body': b'\xff', 'byte_count': 1, 'raw_hash': hashlib.sha256(b'\xff').hexdigest()}
        elif damage == 'hash':
            values = {'raw_hash': '0' * 64}
        else:
            saved = record_object(db, cap.raw_body)
            db.add(CaptureObject(capture_id=cap.id, raw_hash=saved))
        if damage != 'object':
            # Match existing adversarial fixtures without changing append-only protection.
            db.execute(RawCapture.__table__.update().where(RawCapture.id == cap.id).values(**values))
        db.commit()
    if damage == 'object':
        private.database.object_store.path(saved).unlink()
    for path in (rows['captures'][0], rows['quarantine'], rows['rejected']):
        assert_error(read(private, path), 503, 'vehicle_raw_integrity_failed')


def test_explicit_format_history_unknown_ids_and_text_content_negotiation(private):
    for base in ('/v1/vehicle-evidence/', '/v1/captures/', '/v1/quarantines/'):
        path = base + 'unknown-r93'
        for params in ({'format': 'unknown', 'mode': 'history'}, {'format': 'raw-evidence-v2'},
                       {'format': 'raw-evidence-v2', 'mode': 'current'}):
            assert private.client.get(path, params=params).status_code == 422
        for params in ({}, {'mode': 'current'}, {'mode': 'history', 'format': 'unknown'}):
            assert private.client.get(path + '/content', params=params).status_code == 422
        assert read(private, path).status_code == 404
        assert download(private, path).status_code == 404


def test_history_keeps_workspace_scope_and_audits_current_reader(evidence, monkeypatch):
    ctx = evidence
    grant(monkeypatch)
    other = uid()
    with ctx.database.sessions() as db:
        db.add(UserSession(id=other, expires_at=utcnow() + timedelta(days=1)))
        db.flush()
        db.execute(update(QueryRun).values(session_id=other))
        db.commit()
    assert read(ctx, ctx.paths['capture']).status_code == 200
    assert download(ctx, ctx.paths['capture']).status_code == 200
    with ctx.database.sessions() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == 'raw_capture_downloaded')))
        assert len(events) == 1 and events[0].session_id == ctx.session_id and events[0].session_id != other


def test_trusted_policy_scope_version_expiry_and_external_use_flags_fail_closed(evidence, monkeypatch):
    ctx = evidence
    base = vehicle_raw._vehicle_original_policy
    mutations = ({'scope': {}}, {'policy_version': 'unreviewed'}, {'expires_at': '2099-01-01'},
                 {'provider_use': True}, {'export_or_redistribution': True}, {'extra': 'unreviewed'})
    for mutation in mutations:
        def policy(binding):
            return {**base(binding), 'local_original_read': 'allowed', 'structured_fact_use': 'allowed', **mutation}
        monkeypatch.setattr(vehicle_raw, '_vehicle_original_policy', policy)
        assert_error(read(ctx, ctx.paths['capture']), 403, 'vehicle_original_read_not_allowed')
        assert_error(download(ctx, ctx.paths['capture']), 403, 'vehicle_original_read_not_allowed')
