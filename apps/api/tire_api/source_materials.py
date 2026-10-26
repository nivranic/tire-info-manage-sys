"""Licensed fixed-source acquisition; transport evidence never authenticates content."""
import asyncio
from copy import deepcopy
import hashlib
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from pydantic import ConfigDict, Field, StrictBool, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .auth import current_user, make_admin_guard
from .db import EvidenceDocument, EvidenceObject, UserSession, uid, utc, utcnow
from .documents import document_metadata, register_object
from .domain import StrictModel, digest
from .material_source_policy import canonical_policy, plain
from .material_source_transport import MaterialTransportError, robots_failure_diagnostic
from .object_store import ObjectStoreError
from .service import QueryService, timestamp
from .source_material_models import SourceMaterialOutcome, SourceMaterialRequest, SourceMaterialStop

NOTICE = ('按可信本地许可配置从固定 HTTPS 地址取得原字节；许可与引用页关系是操作者声明。'
          '传输记录不认证出版来源、内容真伪或精确 SKU，不开放 AI、Provider 或导出用途。')
FAILURE_CODES = frozenset('source_material_' + suffix for suffix in (
    'busy', 'timeout', 'address_blocked', 'network_failed', 'rate_limited', 'encoding_rejected',
    'too_large', 'incomplete_body', 'robots_invalid', 'robots_unavailable', 'robots_disallowed',
    'redirect_rejected', 'http_rejected', 'content_type_rejected', 'pdf_marker_missing',
    'authorization_changed', 'policy_changed', 'storage_failed', 'cancelled', 'capture_failed'))


def fail(code, status=409):
    raise HTTPException(status, {'code': code, 'message': '来源材料操作未完成；请检查状态与固定来源策略。'})


class MaterialPreview(StrictModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=False)
    policy_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$')
    expected_policy_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')


class MaterialCapture(MaterialPreview):
    idempotency_key: str = Field(min_length=36, max_length=36)
    operator: str = Field(min_length=1, max_length=80)
    rights_confirmed: StrictBool

    _operator = field_validator('operator')(plain)

    @field_validator('idempotency_key')
    @classmethod
    def valid_uuid(cls, value):
        if str(UUID(value)) != value:
            raise ValueError('请提供固定规范 UUID')
        return value

    @field_validator('rights_confirmed')
    @classmethod
    def confirmed(cls, value):
        if value is not True:
            raise ValueError('请确认声明的保存与工作区权利')
        return value


class MaterialStop(StrictModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=False)
    expected_request_id: str = Field(min_length=36, max_length=36)
    operator: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=500)

    _operator = field_validator('operator')(plain)

    @field_validator('expected_request_id')
    @classmethod
    def valid_request_id(cls, value):
        return MaterialCapture.valid_uuid(value)

    @field_validator('reason')
    @classmethod
    def single_paragraph(cls, value):
        plain(value)
        if any(separator in value for separator in ('\x85', '\u2028', '\u2029')):
            raise ValueError('请提供单段停止说明')
        return value


def request_fingerprint(row):
    return digest({key: getattr(row, key) for key in ('id', 'actor_user_id', 'actor_session_id',
        'idempotency_key', 'operator', 'payload', 'request_hash', 'policy')} | {'created_at': timestamp(row.created_at)})


def outcome_fingerprint(row):
    return digest({key: getattr(row, key) for key in ('request_id', 'state', 'failure_code', 'document_id', 'receipt')}
        | {'created_at': timestamp(row.created_at)})


def stop_fingerprint(row):
    return digest({key: getattr(row, key) for key in ('request_id', 'request_fingerprint', 'actor_user_id',
        'actor_session_id', 'payload', 'payload_hash', 'operator', 'reason')}
        | {'stopped_at': timestamp(row.stopped_at)})


def checked_stop(db, row, stop):
    try:
        if (stop.request_id != row.id or stop.request_fingerprint != row.fingerprint
                or stop.actor_user_id != row.actor_user_id
                or str(UUID(stop.actor_session_id)) != stop.actor_session_id
                or db.get(UserSession, stop.actor_session_id) is None
                or MaterialStop.model_validate(stop.payload).model_dump() != stop.payload
                or stop.payload != {'expected_request_id': row.id, 'operator': stop.operator, 'reason': stop.reason}
                or digest(stop.payload) != stop.payload_hash or stop_fingerprint(stop) != stop.fingerprint
                or utc(stop.stopped_at) < utc(row.created_at) or utc(stop.stopped_at) > utcnow()):
            raise ValueError('stop mismatch')
    except (KeyError, TypeError, ValueError, AttributeError):
        fail('source_material_integrity_failed', 503)
    return {'schema': 'source-material-stop@1', 'request_id': row.id, 'idempotency_key': row.idempotency_key,
        'operator': stop.operator, 'reason': stop.reason, 'stopped_at': timestamp(stop.stopped_at)}


def checked_request(row):
    try:
        raw_policy = {key: value for key, value in row.policy.items() if key != 'policy_fingerprint'}
        if (canonical_policy(raw_policy) != row.policy or digest(row.payload) != row.request_hash
                or row.payload['policy_id'] != row.policy['policy_id']
                or row.payload['expected_policy_fingerprint'] != row.policy['policy_fingerprint']
                or row.payload['idempotency_key'] != row.idempotency_key or row.payload['operator'] != row.operator
                or MaterialCapture.model_validate(row.payload).model_dump() != row.payload
                or request_fingerprint(row) != row.fingerprint):
            raise ValueError('request mismatch')
    except Exception:
        fail('source_material_integrity_failed', 503)


def material_row(db, model, key):
    # JSON/DateTime result processors run before checked_request/checked_stop
    # receive a row. Only malformed persisted values become integrity errors;
    # DBAPI, permission guards and other execution failures retain their path.
    try:
        return db.get(model, key)
    except (ValueError, TypeError):
        fail('source_material_integrity_failed', 503)


def request_for_owner(db, actor_id, idempotency_key):
    try:
        return db.scalar(select(SourceMaterialRequest).where(SourceMaterialRequest.actor_user_id == actor_id,
            SourceMaterialRequest.idempotency_key == idempotency_key))
    except (ValueError, TypeError):
        fail('source_material_integrity_failed', 503)


def checked_view(db, row):
    checked_request(row)
    outcome = material_row(db, SourceMaterialOutcome, row.id)
    stop = material_row(db, SourceMaterialStop, row.id)
    if stop is not None and outcome is not None:
        fail('source_material_integrity_failed', 503)
    stopped = checked_stop(db, row, stop) if stop is not None else None
    document = receipt = None
    if outcome is not None:
        try:
            if outcome.fingerprint != outcome_fingerprint(outcome):
                raise ValueError('outcome mismatch')
            if outcome.state == 'succeeded':
                receipt = deepcopy(outcome.receipt)
                fingerprint = receipt.pop('fingerprint')
                if fingerprint != digest(receipt):
                    raise ValueError('receipt mismatch')
                receipt['fingerprint'] = fingerprint
                doc = db.get(EvidenceDocument, outcome.document_id)
                obj = db.get(EvidenceObject, doc.raw_hash) if doc else None
                if doc is None or obj is None:
                    raise ValueError('document missing')
                document = document_metadata(doc, obj.byte_count)
                if (receipt['request_id'] != row.id or receipt['policy_fingerprint'] != row.policy['policy_fingerprint']
                        or receipt['document_id'] != doc.id or receipt['raw_hash'] != doc.raw_hash
                        or receipt['byte_count'] != obj.byte_count
                        or receipt['document_metadata_hash'] != digest({**document, 'actor_session_id': doc.actor_session_id})
                        or doc.actor_session_id != row.actor_session_id or doc.source_url != row.policy['source_reference_url']
                        or doc.title != row.policy['title'] or doc.operator != row.operator
                        or doc.rights_basis != row.policy['rights']['basis'] or doc.content_type != 'application/pdf'
                        or outcome.failure_code is not None):
                    raise ValueError('mapping mismatch')
                db.info['object_store'].get(doc.raw_hash, obj.byte_count)
                checked_transport(db, row.policy, receipt)
            elif (outcome.state != 'failed' or outcome.document_id is not None or outcome.receipt is not None
                    or outcome.failure_code not in FAILURE_CODES):
                raise ValueError('invalid failure')
        except (ObjectStoreError, KeyError, TypeError, ValueError, AttributeError):
            fail('source_material_integrity_failed', 503)
    return {'request_id': row.id, 'idempotency_key': row.idempotency_key,
        'state': outcome.state if outcome else 'stopped_unconfirmed' if stopped else 'processing_unconfirmed', 'policy': deepcopy(row.policy),
        'policy_fingerprint': row.policy['policy_fingerprint'], 'operator': row.operator,
        'requested_at': timestamp(row.created_at), 'completed_at': timestamp(outcome.created_at) if outcome else None,
        'failure_code': outcome.failure_code if outcome else None, 'document': document, 'receipt': receipt,
        'stop': stopped, 'notice': NOTICE}


def checked_transport(db, policy, receipt):
    from urllib.parse import urlsplit
    from datetime import datetime
    from .adapters.robots import RobotsPolicy
    from .adapters.transport import USER_AGENT
    if (receipt['schema'] != 'source-material-receipt@1' or receipt['source_reference_url'] != policy['source_reference_url']
            or receipt['initial_url'] != policy['download_url'] or receipt['content_type'] != 'application/pdf'
            or receipt['content_encoding'] != 'identity' or receipt['transport_verification'] != 'https_transport_observed'
            or receipt['content_authenticity'] != 'unverified' or receipt['source_reference_relation'] != 'operator_configured'):
        raise ValueError('transport semantics mismatch')
    started, ended = (datetime.fromisoformat(receipt[key]) for key in ('started_at', 'completed_at'))
    if started.tzinfo is None or ended.tzinfo is None or ended < started:
        raise ValueError('transport dates invalid')
    targets = [policy['download_url']]
    if len(receipt['redirects']) > 3:
        raise ValueError('redirect limit')
    for redirect in receipt['redirects']:
        if (redirect['from_url'] != targets[-1] or redirect['to_url'] not in policy['redirect_urls']
                or redirect['to_url'] in targets or redirect['status'] not in (301, 302, 303, 307, 308)):
            raise ValueError('redirect mismatch')
        targets.append(redirect['to_url'])
    if receipt['final_url'] != targets[-1] or len(receipt['robots']) != len(targets):
        raise ValueError('robots chain mismatch')
    for target, robot in zip(targets, receipt['robots'], strict=True):
        parsed = urlsplit(target)
        if (robot['target_url'] != target or robot['url'] != f'https://{parsed.netloc}/robots.txt'
                or robot['allowed'] is not True):
            raise ValueError('robots target mismatch')
        if robot['status'] == 200:
            if type(robot['byte_count']) is not int or not 0 <= robot['byte_count'] <= 64 * 1024:
                raise ValueError('robots size invalid')
            if robot['byte_count'] == 0:
                if robot['raw_hash'] != hashlib.sha256(b'').hexdigest():
                    raise ValueError('empty robots hash mismatch')
                body = b''
            else:
                blob = db.get(EvidenceObject, robot['raw_hash'])
                if blob is None or blob.byte_count != robot['byte_count']:
                    raise ValueError('robots mapping missing')
                body = db.info['object_store'].get(blob.raw_hash, blob.byte_count)
            rules = RobotsPolicy(body.decode('utf-8', errors='strict'), USER_AGENT)
            if not rules.can_fetch(target) or robot['minimum_interval'] != max(2.0, rules.minimum_interval):
                raise ValueError('robots decision mismatch')
        elif (robot['status'] not in (404, 410) or robot['raw_hash'] is not None or robot['byte_count'] != 0
                or robot['minimum_interval'] != 2.0):
            raise ValueError('robots absence mismatch')


def refreshed_request(db, request_id, fingerprint, actor_id):
    # A row detached by close() is not refreshed by expire_all(). Reacquire it
    # under the write lock and compare the immutable identity pinned before I/O.
    row = material_row(db, SourceMaterialRequest, request_id)
    if row is None:
        fail('source_material_integrity_failed', 503)
    checked_request(row)
    if row.fingerprint != fingerprint or row.actor_user_id != actor_id:
        fail('source_material_integrity_failed', 503)
    return row


def finalize_failure(db, request_id, fingerprint, actor_id, code, error=None):
    db.rollback()
    QueryService(db, None).lock_ingestion()
    db.expire_all()
    row = refreshed_request(db, request_id, fingerprint, actor_id)
    # Failure recording preserves its existing role-withdrawal contract. It
    # still validates the frozen request and the same adoption arbitration.
    value = checked_view(db, row)
    if value['state'] != 'processing_unconfirmed':
        db.commit()
        return row
    if db.get(SourceMaterialOutcome, row.id) is None:
        outcome = SourceMaterialOutcome(request_id=row.id, state='failed', failure_code=code,
            document_id=None, receipt=None, created_at=utcnow())
        outcome.fingerprint = outcome_fingerprint(outcome)
        db.add(outcome)
        diagnostic = robots_failure_diagnostic(error) if code == 'source_material_robots_unavailable' else None
        if diagnostic is not None:
            QueryService(db, None).audit(row.actor_session_id, 'source_material_failed',
                request_id=row.id, failure_code=code, **diagnostic)
        db.commit()
    return row


def register_source_material_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db
    admin_guard = make_admin_guard(get_db)

    def owner(db, request):
        user = current_user(db, request.state.session_id)
        if user is None:
            fail('source_material_login_required', 403)
        return user

    def selected(payload):
        policy = app.state.material_policies.get(payload.policy_id)
        if policy is None:
            fail('source_material_policy_not_found', 404)
        if policy['policy_fingerprint'] != payload.expected_policy_fingerprint:
            fail('source_material_policy_changed')
        return policy

    @app.get('/v1/source-materials/policies')
    def policies():
        return {'scope': 'local_workspace', 'items': app.state.material_policies.items(), 'notice': NOTICE}

    @app.post('/v1/source-materials/preview', dependencies=[Depends(admin_guard)])
    def preview(payload: MaterialPreview):
        return {'policy': selected(payload), 'can_capture': True, 'blockers': [], 'notice': NOTICE}

    @app.post('/v1/source-materials/requests/{idempotency_key}/stop', dependencies=[Depends(admin_guard)])
    def stop(payload: MaterialStop, request: Request,
             idempotency_key: str = Path(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
             db: Session = Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        db.expire_all()
        actor = owner(db, request)
        if not actor.is_admin:
            fail('admin_required', 403)
        row = request_for_owner(db, actor.id, idempotency_key)
        if row is None:
            fail('source_material_request_not_found', 404)
        checked_request(row)
        if row.id != payload.expected_request_id:
            fail('source_material_stop_request_mismatch')
        value = checked_view(db, row)
        data = payload.model_dump()
        if value['state'] in ('succeeded', 'failed'):
            db.commit()
            return {'request': value, 'effect': 'already_terminal'}
        if value['state'] == 'stopped_unconfirmed':
            if db.get(SourceMaterialStop, row.id).payload != data:
                fail('source_material_stop_conflict')
            db.commit()
            return {'request': value, 'effect': 'already_stopped'}
        stopped = SourceMaterialStop(request_id=row.id, request_fingerprint=row.fingerprint,
            actor_user_id=actor.id, actor_session_id=request.state.session_id, payload=data, payload_hash=digest(data),
            operator=payload.operator, reason=payload.reason, stopped_at=utcnow())
        stopped.fingerprint = stop_fingerprint(stopped)
        try:
            db.add(stopped)
            QueryService(db, None).audit(request.state.session_id, 'source_material_stopped', request_id=row.id,
                operator=payload.operator, reason=payload.reason)
            db.commit()
        except Exception:
            db.rollback()
            fail('source_material_stop_commit_unconfirmed', 503)
        return {'request': checked_view(db, row), 'effect': 'stopped'}

    @app.post('/v1/source-materials/captures', status_code=201, dependencies=[Depends(admin_guard)])
    async def capture(payload: MaterialCapture, request: Request, db: Session = Depends(get_db)):
        data = payload.model_dump()
        QueryService(db, None).lock_ingestion()
        db.expire_all()
        actor = owner(db, request)
        if not actor.is_admin:
            fail('admin_required', 403)
        actor_id, session_id = actor.id, request.state.session_id
        row = request_for_owner(db, actor_id, payload.idempotency_key)
        if row is not None:
            checked_request(row)
            if row.request_hash != digest(data):
                fail('source_material_idempotency_mismatch')
            value = checked_view(db, row)
            db.commit()
            return {**value, 'replayed': True}
        row = SourceMaterialRequest(id=uid(), actor_user_id=actor_id, actor_session_id=session_id,
            idempotency_key=payload.idempotency_key, operator=payload.operator, payload=data,
            request_hash=digest(data), policy=selected(payload), created_at=utcnow())
        row.fingerprint = request_fingerprint(row)
        db.add(row)
        QueryService(db, None).audit(session_id, 'source_material_requested', request_id=row.id)
        db.commit()
        request_id, fingerprint = row.id, row.fingerprint
        # No transaction or ingestion lock spans network or object publication.
        db.close()
        try:
            obtained = await app.state.material_transport.fetch(deepcopy(row.policy))
            body = obtained['body']
            if not isinstance(body, bytes) or not body.startswith(b'%PDF-'):
                raise MaterialTransportError('source_material_pdf_marker_missing')
            store = db.info['object_store']
            from starlette.concurrency import run_in_threadpool
            raw_hash = await run_in_threadpool(store.put, body)
            robot_objects = []
            for robot in obtained['robot_objects']:
                robot_hash = await run_in_threadpool(store.put, robot['body'])
                if robot_hash != robot['raw_hash']:
                    raise ObjectStoreError('object_integrity_failed')
                robot_objects.append((robot_hash, len(robot['body'])))
            QueryService(db, None).lock_ingestion()
            # Re-read the current session and stable original requester role.
            db.expire_all()
            row = refreshed_request(db, request_id, fingerprint, actor_id)
            current = current_user(db, session_id)
            if current is None or current.id != actor_id or not current.is_admin:
                raise MaterialTransportError('source_material_authorization_changed')
            value = checked_view(db, row)
            if value['state'] != 'processing_unconfirmed':
                db.commit()
                return {**value, 'replayed': False}
            if selected(payload) != row.policy:
                raise MaterialTransportError('source_material_policy_changed')
            register_object(db, raw_hash, len(body))
            for robot_hash, size in robot_objects:
                register_object(db, robot_hash, size)
            doc = EvidenceDocument(raw_hash=raw_hash, title=row.policy['title'], source_url=row.policy['source_reference_url'],
                operator=row.operator, rights_basis=row.policy['rights']['basis'], content_type='application/pdf',
                actor_session_id=row.actor_session_id)
            db.add(doc)
            db.flush()
            metadata = document_metadata(doc, len(body))
            receipt = {key: deepcopy(obtained[key]) for key in ('initial_url', 'final_url', 'redirects', 'robots', 'started_at', 'completed_at')}
            receipt.update(schema='source-material-receipt@1', request_id=row.id,
                policy_fingerprint=row.policy['policy_fingerprint'], source_reference_url=row.policy['source_reference_url'],
                raw_hash=raw_hash, byte_count=len(body), content_type='application/pdf', content_encoding='identity',
                document_id=doc.id, document_metadata_hash=digest({**metadata, 'actor_session_id': doc.actor_session_id}),
                transport_verification='https_transport_observed', content_authenticity='unverified',
                source_reference_relation='operator_configured')
            receipt['fingerprint'] = digest(receipt)
            outcome = SourceMaterialOutcome(request_id=row.id, state='succeeded', failure_code=None,
                document_id=doc.id, receipt=receipt, created_at=utcnow())
            outcome.fingerprint = outcome_fingerprint(outcome)
            db.add(outcome)
            QueryService(db, None).audit(session_id, 'source_material_received', request_id=row.id, document_id=doc.id)
            db.commit()
        except asyncio.CancelledError:
            try:
                finalize_failure(db, request_id, fingerprint, actor_id, 'source_material_cancelled')
            except Exception:
                pass
            raise
        except (MaterialTransportError, ObjectStoreError) as exc:
            code = str(exc) if isinstance(exc, MaterialTransportError) and str(exc) in FAILURE_CODES else (
                'source_material_storage_failed' if isinstance(exc, ObjectStoreError) else 'source_material_capture_failed')
            try:
                row = finalize_failure(db, request_id, fingerprint, actor_id, code, exc)
            except HTTPException:
                db.rollback()
                raise
            except Exception:
                fail('source_material_commit_unconfirmed', 503)
        except HTTPException as exc:
            db.rollback()
            if isinstance(exc.detail, dict) and exc.detail.get('code') == 'source_material_integrity_failed':
                raise
            fail('source_material_commit_unconfirmed', 503)
        except Exception:
            db.rollback()
            # A terminal commit may have succeeded despite a lost acknowledgement.
            # Leave the durable reservation for lookup, never repeat acquisition.
            fail('source_material_commit_unconfirmed', 503)
        return {**checked_view(db, row), 'replayed': False}

    @app.get('/v1/source-materials/requests')
    def requests(request: Request, mode: Literal['history'] = Query(...), offset: int = Query(0, ge=0),
                 db: Session = Depends(get_db)):
        actor = owner(db, request)
        where = SourceMaterialRequest.actor_user_id == actor.id
        try:
            rows = db.scalars(select(SourceMaterialRequest).where(where).order_by(desc(SourceMaterialRequest.created_at),
                desc(SourceMaterialRequest.id)).offset(offset).limit(50)).all()
        except (ValueError, TypeError):
            fail('source_material_integrity_failed', 503)
        return {'scope': 'current_user', 'items': [checked_view(db, row) for row in rows], 'offset': offset,
            'total': db.scalar(select(func.count()).select_from(SourceMaterialRequest).where(where)) or 0, 'notice': NOTICE}

    @app.get('/v1/source-materials/requests/{idempotency_key}')
    def lookup(idempotency_key: str, request: Request, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        actor = owner(db, request)
        row = request_for_owner(db, actor.id, idempotency_key)
        if row is None:
            fail('source_material_request_not_found', 404)
        return checked_view(db, row)

    @app.get('/v1/source-materials/documents/{document_id}')
    def document_receipt(document_id: str, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        outcome = db.scalar(select(SourceMaterialOutcome).where(SourceMaterialOutcome.document_id == document_id))
        if outcome is None:
            fail('source_material_receipt_not_found', 404)
        row = db.get(SourceMaterialRequest, outcome.request_id)
        if row is None:
            fail('source_material_integrity_failed', 503)
        return checked_view(db, row)
