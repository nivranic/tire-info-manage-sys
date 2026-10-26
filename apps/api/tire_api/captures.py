"""Durable pre-parser receipt journal and separate rejected-response evidence."""
from copy import deepcopy
import hashlib
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from sqlalchemy import desc, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, load_only
from sqlalchemy.pool import NullPool, QueuePool

from .db import AuditEvent, CaptureObject, EvidenceObject, QueryRun, RawCapture, RejectedObservation, SourceQuarantine, uid, utc


class CaptureWriteError(Exception):
    """A source must not parse or accept a response without the required receipt."""


def parser_failure_reason(code: Any) -> str:
    """Only fixed Parser error codes may enter public or retained failure metadata."""
    from .parser_bundles import ERROR_CODES
    codes = ERROR_CODES | {
        'parser_schema_changed', 'parser_failed', 'parser_timeout', 'parser_cancelled',
        'parser_crashed', 'parser_cleanup_failed', 'parser_isolation_unavailable',
        'parser_protocol_invalid', 'parser_code_mismatch', 'parser_version_mismatch',
        'parser_input_invalid', 'parser_input_too_large', 'parser_output_too_large',
        'parser_stderr_too_large', 'parser_source_not_allowed',
        'parser_selection_invalid', 'parser_selection_mismatch',
        'vehicle_pdf_invalid', 'vehicle_pdf_revision_unreviewed',
    }
    return code if type(code) is str and code in codes else 'parser_failed'


def checked_capture_bytes(db: Session, row: RawCapture) -> tuple[bytes, str]:
    """An existing object reference is authoritative; never fall back to the DB copy."""
    if row.body_encoding == 'binary':
        raise HTTPException(409, {'code': 'binary_evidence_format_required'})
    from .object_store import ObjectStoreError
    reference = db.get(CaptureObject, row.id)
    try:
        if type(row.byte_count) is not int or not 1 <= row.byte_count <= 8 * 1024 * 1024:
            raise ValueError('invalid size')
        if reference is not None:
            obj = db.get(EvidenceObject, reference.raw_hash)
            if (reference.raw_hash != row.raw_hash or obj is None or obj.raw_hash != row.raw_hash
                    or obj.byte_count != row.byte_count):
                raise ValueError('object mapping mismatch')
            body = db.info['object_store'].get(reference.raw_hash, row.byte_count)
        else:
            body = row.raw_body
        if (not isinstance(body, bytes) or len(body) != row.byte_count
                or hashlib.sha256(body).hexdigest() != row.raw_hash):
            raise ValueError('capture integrity mismatch')
        body.decode('utf-8', errors='strict')
    except (ObjectStoreError, KeyError, OSError, ValueError, TypeError):
        raise HTTPException(503, '原文对象缺失或完整性校验失败，未返回内容') from None
    return body, 'object_store' if reference is not None else 'database_legacy'


def checked_text_raw_metadata(db: Session, row) -> tuple[dict, str | None]:
    """Explicit non-vehicle V2 text adapter; never bypass a retained object."""
    try:
        if (type(row) not in (RawCapture, RejectedObservation, SourceQuarantine)
                or getattr(row, 'body_encoding', 'utf-8') != 'utf-8'
                or row.content_type not in {'text/html', 'application/json', 'text/javascript',
                                             'application/javascript', 'text/plain'}):
            raise ValueError('invalid text evidence')
        storage_kind, capture_id = None, None
        if type(row) is RawCapture:
            raw, storage_kind = checked_capture_bytes(db, row)
            capture_id = row.id
        else:
            if type(row) is SourceQuarantine:
                if type(row.body) is not str:
                    raise ValueError('invalid text body')
                raw = row.body.encode('utf-8', errors='strict')
            else:
                raw = row.raw_body
            capture = db.scalar(select(RawCapture).where(RawCapture.query_id == row.query_id))
            if capture is not None:
                if (capture.body_encoding != 'utf-8'
                        or any(getattr(capture, key) != getattr(row, key) for key in
                               ('source_id', 'query_key', 'source_url', 'raw_hash', 'content_type',
                                'parser_version', 'parser_identity'))
                        or type(row) is RejectedObservation and capture.target_kind != row.target_kind):
                    raise ValueError('text capture mismatch')
                captured, _ = checked_capture_bytes(db, capture)
                if captured != raw:
                    raise ValueError('text capture bytes mismatch')
                capture_id = capture.id
        if (type(raw) is not bytes or not 1 <= len(raw) <= 8 * 1024 * 1024
                or hashlib.sha256(raw).hexdigest() != row.raw_hash):
            raise ValueError('text integrity mismatch')
        text = raw.decode('utf-8', errors='strict')
        return ({'evidence_format': 'raw-evidence-v2', 'body_encoding': 'utf-8', 'body': text,
                 'raw_capture_id': capture_id, 'raw_hash': row.raw_hash, 'byte_count': len(raw),
                 'content_type': row.content_type, 'content_path': None,
                 'parse_method': None, 'mapping_id': None}, storage_kind)
    except Exception:
        raise HTTPException(503, {'code': 'vehicle_raw_integrity_failed'}) from None


def validated_observation(observation: Any, *, source_id: str | None = None,
                          query: dict | None = None) -> dict | None:
    if not isinstance(observation, dict):
        return None
    body, url = observation.get("body"), observation.get("url")
    parser, mime = observation.get("parser_version"), observation.get("content_type")
    encoding = observation.get('body_encoding', 'utf-8')
    if encoding == 'binary':
        from .vehicle_raw import FIRST_GENERATION_ID, MAX_BYTES, PDF_URL, SOURCE_ID
        from .parser_provenance import parser_identity
        identity = parser_identity(observation.get('parser_identity'))
        if (source_id != SOURCE_ID or type(query) is not dict or query != {'vehicle_id': FIRST_GENERATION_ID}
                or type(body) is not bytes or not 1 <= len(body) <= MAX_BYTES or not body.startswith(b'%PDF-')
                or url != PDF_URL or mime != 'application/pdf'
                or type(parser) is not str or not 1 <= len(parser) <= 100
                or any(ord(character) < 32 for character in parser)
                or identity is None or type(observation.get('parser_identity')) is not dict
                or observation['parser_identity'] != identity):
            return None
        return {'source_url': url, 'raw_body': body, 'raw_hash': hashlib.sha256(body).hexdigest(),
                'content_type': mime, 'parser_version': parser, 'parser_identity': identity,
                'body_encoding': 'binary'}
    if encoding != 'utf-8':
        return None
    if (not isinstance(body, str) or not body or not isinstance(url, str) or len(url) > 8192
            or not isinstance(parser, str) or not 1 <= len(parser) <= 100
            or not isinstance(mime, str) or mime not in {"text/html", "application/json", "text/javascript", "application/javascript", "text/plain"}):
        return None
    if any(ord(character) < 32 for character in url + parser):
        return None
    try:
        parsed = urlsplit(url)
        from .adapters.nhtsa import permitted_url
        if (parsed.scheme != "https" or not parsed.hostname or parsed.port not in (None, 443)
                or parsed.username or parsed.password or parsed.query and not permitted_url(url)
                or parsed.fragment or "\\" in url):
            return None
        raw = body.encode("utf-8", errors="strict")
    except (ValueError, UnicodeError):
        return None
    if len(raw) > 8 * 1024 * 1024:
        return None
    from .parser_provenance import parser_identity
    identity = observation.get('parser_identity')
    # Builtin DB-free probes have no deployment; only complete identities persist.
    identity = parser_identity(identity)
    return {"source_url": url, "raw_body": raw, "raw_hash": hashlib.sha256(raw).hexdigest(),
            "content_type": mime, "parser_version": parser, "parser_identity": identity}


def capture_target(run: QueryRun) -> str:
    if run.source_id == 'nhtsa-us-recalls' and set(run.query) in ({'campaign_number'}, {'search', 'offset'}):
        return 'recall'
    return 'vehicle' if 'vehicle_id' in run.query else 'tire'


def _binary_journal_bind(db: Session):
    """Only the project's known independent checkout pools support binary journals.

    Reject shared/unknown pools before opening a journal: closing a Session on
    a shared DBAPI connection could roll back the caller's transaction.
    """
    bind = db.get_bind()
    if not isinstance(bind, Engine) or type(bind.pool) not in (QueuePool, NullPool):
        raise CaptureWriteError('evidence_capture_failed')
    if bind.dialect.name == 'sqlite' and (bind.url.database in (None, '', ':memory:')
            or bind.url.query.get('mode') == 'memory' or bind.url.query.get('cache') == 'shared'):
        raise CaptureWriteError('evidence_capture_failed')
    return bind


def _binary_original_run(journal, query_id, source_id, query_key, query, session_id):
    original = journal.get(QueryRun, query_id)
    if (original is None or original.source_id != source_id or original.query_key != query_key
            or original.query != query or original.session_id != session_id):
        raise CaptureWriteError('evidence_capture_failed')
    return original


def before_parse_recorder(db: Session, run: QueryRun) -> Callable[[dict], None]:
    """Caller has committed QueryRun and closed its transaction before network I/O.

    A separate transaction protects the receipt from later parse/ingestion rollback.
    The callback is synchronous and must finish before the adapter invokes a parser.
    No accepted snapshots, cached parameters or validators are read.
    """
    context = {"query_id": run.id, "source_id": run.source_id, "query_key": run.query_key,
               "target_kind": capture_target(run)}
    trusted_query = deepcopy(run.query)
    expected_url = None
    if context['target_kind'] == 'recall':
        from .adapters.nhtsa import query_url
        expected_url = query_url(run.query)
    session_id, bind = run.session_id, db.get_bind()
    store = db.info.get('object_store')

    def record(observation: dict) -> None:
        values = validated_observation(observation, source_id=context['source_id'], query=trusted_query)
        if values is None or expected_url and (values['source_url'] != expected_url or values['content_type'] != 'application/json'):
            raise CaptureWriteError("evidence_capture_failed")
        try:
            binary = values.get('body_encoding') == 'binary'
            if binary and db.in_transaction():
                raise CaptureWriteError('evidence_capture_failed')
            journal_bind = _binary_journal_bind(db) if binary else bind
            with Session(journal_bind, expire_on_commit=False, info={'object_store': store}) as journal:
                if binary:
                    from .vehicle_raw import checked_vehicle_capture, checked_vehicle_capture_pin
                    original = _binary_original_run(journal, context['query_id'], context['source_id'],
                                                    context['query_key'], trusted_query, session_id)
                    checked_vehicle_capture_pin(journal, original, parser_version=values['parser_version'],
                                                parser_identity=values['parser_identity'])
                    if journal.scalar(select(RawCapture.id).where(RawCapture.query_id == original.id)) is not None:
                        raise CaptureWriteError('evidence_capture_failed')
                from .documents import record_object
                digest = record_object(journal, values['raw_body'], store)
                row = RawCapture(id=uid(), **context, **values, byte_count=len(values["raw_body"]))
                journal.add(row)
                journal.flush()
                journal.add(CaptureObject(capture_id=row.id, raw_hash=digest))
                if binary:
                    journal.flush()
                    checked_vehicle_capture(journal, original, observation)
                journal.add(AuditEvent(session_id=session_id, query_id=context["query_id"],
                    action="raw_response_received", detail={"capture_id": row.id, "raw_hash": row.raw_hash,
                                                            "target_kind": row.target_kind}))
                journal.commit()
        except Exception:
            # Never expose SQL arguments or connection strings in an API response.
            raise CaptureWriteError("evidence_capture_failed") from None

    return record


def retain_rejected_response(db: Session, run: QueryRun, observation: Any,
                             stage: Literal["parser", "schema"]) -> str | None:
    """No snapshots, parameters, validators or latest accepted records are read here."""
    values = validated_observation(observation, source_id=run.source_id, query=run.query)
    if values is None:
        return None
    if values.get('body_encoding') == 'binary':
        try:
            from .vehicle_raw import checked_vehicle_capture
            with Session(_binary_journal_bind(db), expire_on_commit=False,
                         info={'object_store': db.info.get('object_store')}) as journal:
                original = _binary_original_run(journal, run.id, run.source_id, run.query_key,
                                                run.query, run.session_id)
                checked_vehicle_capture(journal, original, observation)
        except Exception:
            # No new capture or object is created to rescue a failed observation.
            return None
    target = capture_target(run)
    if target == 'recall':
        from .adapters.nhtsa import query_url
        if values['source_url'] != query_url(run.query) or values['content_type'] != 'application/json':
            return None
    if stage == 'parser':
        reason = (parser_failure_reason(observation['parser_error']) if 'parser_error' in observation
                  else 'parser_schema_changed')
    else:
        reason = 'vehicle_source_schema_changed' if target == 'vehicle' else 'source_schema_validation_failed'
    row = RejectedObservation(id=uid(), query_id=run.id, source_id=run.source_id, query_key=run.query_key,
                              target_kind=target, stage=stage, reason=reason, **values)
    db.add(row)
    db.add(AuditEvent(session_id=run.session_id, query_id=run.id, action="rejected_response_retained",
                      detail={"observation_id": row.id, "stage": stage, "target_kind": target, "raw_hash": row.raw_hash}))
    return row.id


def register_capture_routes(app: FastAPI) -> None:
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    def metadata(row: RawCapture, state: str, reason: str | None, query: dict) -> dict:
        return {"id": row.id, "query_id": row.query_id, "source_id": row.source_id,
                "target_kind": row.target_kind, "source_url": row.source_url, "raw_hash": row.raw_hash,
                "byte_count": row.byte_count, "content_type": row.content_type,
                "parser_version": row.parser_version, "observed_at": utc(row.observed_at).isoformat(),
                "parser_identity": row.parser_identity,
                "query_state": state, "query_reason": reason, "query": query,
                "processing_unconfirmed": state == "pending",
                "evidence_path": f"/v1/captures/{row.id}?mode=history"}

    @app.get("/v1/captures")
    def captures(mode: Literal["history"] = Query(...), source_id: str | None = Query(None, max_length=80),
                 pending_only: bool = False, limit: int = Query(50, ge=1, le=200),
                 offset: int = Query(0, ge=0, le=100000),
                 db: Session = Depends(get_db)) -> dict:
        columns = [getattr(RawCapture, column.name) for column in RawCapture.__table__.columns
                   if column.name not in {"raw_body", "query_key"}]
        statement = (select(RawCapture, QueryRun.state, QueryRun.reason, QueryRun.query)
                     .join(QueryRun, QueryRun.id == RawCapture.query_id)
                     .options(load_only(*columns)).order_by(desc(RawCapture.observed_at), desc(RawCapture.id)))
        if source_id:
            statement = statement.where(RawCapture.source_id == source_id)
        if pending_only:
            statement = statement.where(QueryRun.state == "pending")
        total = db.scalar(select(func.count()).select_from(statement.with_only_columns(RawCapture.id).order_by(None).subquery()))
        return {"data_state": "local_snapshot", "items": [metadata(row, state, reason, query)
                for row, state, reason, query in db.execute(statement.offset(offset).limit(limit))],
                "total": total, "offset": offset, "limit": limit}

    @app.get("/v1/captures/{capture_id}")
    def capture(capture_id: str, request: Request, mode: Literal["history"] = Query(...),
                evidence_format: Literal['raw-evidence-v2'] | None = Query(None, alias='format'),
                db: Session = Depends(get_db)) -> dict:
        result = db.execute(select(RawCapture, QueryRun.state, QueryRun.reason, QueryRun.query)
                            .join(QueryRun, QueryRun.id == RawCapture.query_id)
                            .where(RawCapture.id == capture_id)).first()
        if result is None:
            raise HTTPException(404, "未找到原文接收记录")
        row, state, reason, query = result
        from .vehicle_raw import vehicle_raw_requires_v2
        requires_v2 = vehicle_raw_requires_v2(db, row)
        if evidence_format is None:
            if requires_v2:
                raise HTTPException(409, {'code': 'binary_evidence_format_required'})
            raw_body, storage_kind = checked_capture_bytes(db, row)
            fields = {'body': raw_body.decode('utf-8')}
        elif requires_v2 or row.target_kind == 'vehicle':
            from .vehicle_raw import (VehicleOriginalUseNotAllowed, VehicleRawIntegrityError,
                                      VehicleUseNotAllowed, checked_vehicle_v2_metadata)
            try:
                fields = checked_vehicle_v2_metadata(db, row)
                storage_kind = 'object_store' if db.get(CaptureObject, row.id) else 'database_legacy'
            except VehicleRawIntegrityError:
                raise HTTPException(503, {'code': 'vehicle_raw_integrity_failed'}) from None
            except (VehicleOriginalUseNotAllowed, VehicleUseNotAllowed) as error:
                raise HTTPException(403, {'code': error.code}) from None
        else:
            fields, storage_kind = checked_text_raw_metadata(db, row)
        response = {**metadata(row, state, reason, query), "data_state": "local_snapshot",
                    **fields, "receipt_only": True, "storage_kind": storage_kind}
        db.add(AuditEvent(session_id=request.state.session_id, query_id=row.query_id,
                          action="raw_capture_history_read", detail={"capture_id": row.id}))
        db.commit()
        return response

    @app.get('/v1/captures/{capture_id}/content')
    def capture_content(capture_id: str, request: Request, mode: Literal['history'] = Query(...),
                        evidence_format: Literal['raw-evidence-v2'] | None = Query(None, alias='format'),
                        db: Session = Depends(get_db)) -> Response:
        row = db.scalar(select(RawCapture).join(QueryRun, QueryRun.id == RawCapture.query_id)
                        .where(RawCapture.id == capture_id))
        if row is None:
            raise HTTPException(404, '未找到原文接收记录')
        from .vehicle_raw import (VehicleOriginalUseNotAllowed, VehicleRawIntegrityError,
                                  checked_vehicle_original_bytes, vehicle_raw_requires_v2)
        if not vehicle_raw_requires_v2(db, row):
            raise HTTPException(409, {'code': 'raw_evidence_content_unavailable'})
        try:
            raw = checked_vehicle_original_bytes(db, row)
        except VehicleRawIntegrityError:
            raise HTTPException(503, {'code': 'vehicle_raw_integrity_failed'}) from None
        except VehicleOriginalUseNotAllowed as error:
            raise HTTPException(403, {'code': error.code}) from None
        db.add(AuditEvent(session_id=request.state.session_id, query_id=row.query_id,
                          action='raw_capture_downloaded', detail={'capture_id': row.id}))
        db.commit()
        return Response(raw, media_type='application/pdf', headers={
            'Content-Disposition': 'attachment; filename="vehicle-evidence.pdf"',
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "sandbox; default-src 'none'", 'X-Evidence-SHA256': row.raw_hash})
