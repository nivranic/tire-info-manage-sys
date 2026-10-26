"""Human confirmation of exact losses; only a subsequent matching online fetch can apply it."""
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import re
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import Field, StrictBool, StrictInt, field_validator
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .auth import make_admin_guard
from .db import (AuditEvent, QueryRun, QuarantineApprovalUse, QuarantineReview,
                 RejectedObservation, Snapshot, SourceQuarantine, User, UserSession,
                 Verification, utc, utcnow)
from .domain import StrictModel, VariantInput, digest
from .quality import stable_key
from .research import DescriptionText
from .vehicle_raw import (FIRST_GENERATION_ID, SOURCE_ID, VehicleOriginalUseNotAllowed,
                          VehicleRawIntegrityError, VehicleUseNotAllowed, checked_vehicle_bytes,
                          checked_vehicle_original_bytes, checked_vehicle_parse_provenance)

APPROVAL_TTL = timedelta(hours=24)
LOSS_REASONS = {'field_loss_threshold', 'row_loss_threshold'}


def _locked_binary_actor(db: Session, request: Request) -> str:
    """Caller holds ingestion; freeze Session then User until the review commits.

    PostgreSQL needs both row locks; SQLite's BEGIN IMMEDIATE already blocks
    identity writes. Password resets hold the same ingestion/advisory lock;
    session-only login/logout/sweep and Session-before-User deletion serialize
    on these rows. Always reload: the early admin dependency may be stale.
    """
    session = db.scalar(select(UserSession).where(UserSession.id == request.state.session_id)
        .with_for_update().execution_options(populate_existing=True))
    user = (db.scalar(select(User).where(User.id == session.user_id)
        .with_for_update().execution_options(populate_existing=True))
        if session is not None and session.user_id is not None else None)
    if (session is None or utc(session.expires_at) <= utcnow()
            or user is None or not user.is_admin):
        raise HTTPException(403, {'code': 'admin_required', 'message': '此管理操作需要管理员账户登录。'})
    values = request.headers.getlist('x-tire-expected-account')
    if len(values) != 1 or re.fullmatch(r'[A-Za-z0-9_-]{1,64}', values[0]) is None:
        raise HTTPException(422, {'code': 'review_expected_account_invalid'})
    if values[0] != user.id:
        raise HTTPException(409, {'code': 'review_actor_changed'})
    return user.id


class ReviewRequest(StrictModel):
    action: Literal['approve', 'keep_quarantined']
    expected_revision: StrictInt = Field(ge=0)
    operator: DescriptionText = Field(min_length=1, max_length=80)
    reason: DescriptionText = Field(min_length=5, max_length=2000)
    confirmed_loss: StrictBool

    @field_validator('confirmed_loss')
    @classmethod
    def confirmation_required(cls, value):
        if not value:
            raise ValueError('请先核对原文、候选参数与缺失内容')
        return value


class BinaryVehicleReviewRequest(ReviewRequest):
    expected_binding_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


class BinaryParserIdentity(StrictModel):
    bundle_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    parser_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    deployment_revision: StrictInt = Field(gt=0)


class BinaryParseProvenance(StrictModel):
    contract: Literal['vehicle-pdf-parse@1']
    method: Literal['sha256_bound_reviewed_mapping']
    mapping_id: str = Field(pattern=r'^xiaomi-su7-first-generation-pdf@[1-9][0-9]{0,8}$')
    source_raw_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    bundle_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    mapping_file_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class BinaryReviewEvidence(StrictModel):
    """Review metadata only; this DTO grants no original-content endpoint."""
    body_encoding: Literal['binary']
    body: None
    raw_capture_id: str
    raw_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    byte_count: StrictInt = Field(gt=0)
    content_type: Literal['application/pdf']
    source_url: str
    parser_version: str
    parser_identity: BinaryParserIdentity
    parse_provenance: BinaryParseProvenance


class BinaryReviewState(StrictModel):
    quarantine_id: str
    scope: Literal['local_workspace']
    state: str
    revision: StrictInt
    can_approve: StrictBool
    restriction: str | None
    baseline_snapshot_id: str
    current_snapshot_id: str | None
    applied_query_id: str | None
    comparison: dict
    history: list[dict]
    history_truncated: StrictBool
    evidence_format: Literal['raw-evidence-v2']
    binding_contract: Literal['vehicle-binary@1']
    binding_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    raw_evidence: BinaryReviewEvidence


@dataclass(frozen=True)
class BinaryReviewContext:
    key: str
    blocked: str | None
    latest_id: str | None
    before: dict
    candidate: dict
    evidence: BinaryReviewEvidence
    raw: bytes


def binding(target: str, source: str, query_key: str, baseline_id: str, result: dict,
            payload: list | dict, quality: dict) -> str:
    values = {'target': target, 'source': source, 'query_key': query_key, 'baseline': baseline_id,
                   'raw_hash': hashlib.sha256(result['body'].encode('utf-8')).hexdigest(),
                   'url': result['url'], 'parser': result['parser_version'],
                   'content_type': result['content_type'], 'payload': payload, 'quality': quality}
    # Keep already-created legacy review hashes stable. New deployments cannot
    # consume them because their non-null identity adds a distinct binding.
    if result.get('parser_identity') is not None:
        values['parser_identity'] = result['parser_identity']
    return digest(values)


def binary_binding(source: str, query_key: str, baseline_id: str, result: dict,
                   payload: dict, quality: dict, *, raw: bytes) -> str:
    """Exactly fifteen keys; only already-checked online/historical capsules enter."""
    return digest({'binding_contract': 'vehicle-binary@1', 'target': 'vehicle',
        'source': source, 'query_key': query_key, 'baseline': baseline_id,
        'raw_hash': hashlib.sha256(raw).hexdigest(), 'url': result['url'],
        'parser': result['parser_version'], 'content_type': result['content_type'],
        'payload': payload, 'quality': quality, 'parser_identity': result['parser_identity'],
        'body_encoding': 'binary', 'byte_count': len(raw),
        'mapping_id': payload['parse_provenance']['mapping_id']})


def restriction(target: str, quality: dict, before: list | dict, after: list | dict) -> str | None:
    if not quality['reason_codes'] or not set(quality['reason_codes']) <= LOSS_REASONS:
        return 'identity_or_alignment_requires_repair'
    if target == 'tire':
        old = {stable_key(row): row for row in before}
        for row in after:
            previous = old.get(stable_key(row))
            if previous is not None:
                def identity(value):
                    return VariantInput.model_validate({k: v for k, v in value.items()
                        if k in VariantInput.model_fields}).identity()
                if identity(previous) != identity(row):
                    return 'identity_or_alignment_requires_repair'
    return None


def is_binary_quarantine(row) -> bool:
    from .vehicles import VehicleQuarantine
    return isinstance(row, VehicleQuarantine) and (row.body_encoding == 'binary'
        or (row.source_id == SOURCE_ID and row.vehicle_id == FIRST_GENERATION_ID))


def find_quarantine(db: Session, quarantine_id: str, *, allow_binary=False):
    from .vehicles import VehicleQuarantine
    row = db.get(SourceQuarantine, quarantine_id) or db.get(VehicleQuarantine, quarantine_id)
    if row is None:
        if db.get(RejectedObservation, quarantine_id) is not None:
            raise HTTPException(409, '解析或结构校验失败须先修复解析器，不能人工跳过')
        raise HTTPException(404, '未找到可核验的隔离记录')
    if is_binary_quarantine(row) and not allow_binary:
        raise HTTPException(409, {'code': 'binary_evidence_format_required'})
    return row


def context(db: Session, row):
    from .vehicles import VehicleService, VehicleSnapshot
    run = db.get(QueryRun, row.query_id)
    if isinstance(row, SourceQuarantine):
        target, payload = 'tire', row.candidates
        baseline = db.get(Snapshot, row.previous_snapshot_id)
        before = baseline.parsed_variants
        latest = db.scalar(select(Snapshot).join(Verification, Verification.snapshot_id == Snapshot.id)
            .where(Verification.source_id == row.source_id, Verification.query_key == run.query_key)
            .order_by(desc(Verification.verified_at)).limit(1))
    else:
        target, payload = 'vehicle', row.payload
        baseline = db.get(VehicleSnapshot, row.previous_snapshot_id)
        before = baseline.payload
        latest = VehicleService(db, None).latest(row.vehicle_id)
    key = binding(target, row.source_id, run.query_key, row.previous_snapshot_id,
        {'body': row.body, 'url': row.source_url, 'parser_version': row.parser_version,
         'content_type': row.content_type, 'parser_identity': row.parser_identity}, payload, row.quality)
    blocked = restriction(target, row.quality, before, payload)
    if hashlib.sha256(row.body.encode('utf-8')).hexdigest() != row.raw_hash:
        blocked = 'evidence_integrity_failed'
    return key, blocked, latest.id if latest else None, before, payload


def _require_binary(condition):
    if not condition:
        raise VehicleRawIntegrityError()


def _checked_vehicle_structure(payload: dict, vehicle_id: str) -> None:
    from .vehicles import WheelFitmentSpecification, validate_vehicle_structure
    _require_binary(type(payload) is dict and payload['vehicle']['id'] == vehicle_id
                    and type(payload['fitments']) is list and 1 <= len(payload['fitments']) <= 100)
    fits = [WheelFitmentSpecification.model_validate(item).model_dump() for item in payload['fitments']]
    _require_binary(len({item['id'] for item in fits}) == len(fits)
                    and fits == payload['fitments'])
    trim_ids = {item['id'] for item in payload['trims']}
    _require_binary(all(item['trim_id'] in trim_ids for item in fits))
    validate_vehicle_structure(payload, fits)


def _checked_binary_baseline(db: Session, baseline, run: QueryRun) -> None:
    from .vehicles import VehicleSnapshot, VehicleVerification, fitment_fact_hash
    from .parser_release_models import ParserSelection
    _require_binary(type(baseline) is VehicleSnapshot and baseline.source_id == run.source_id
                    and baseline.vehicle_id == run.query['vehicle_id'])
    checked_vehicle_parse_provenance(db, baseline)
    _checked_vehicle_structure(baseline.payload, baseline.vehicle_id)
    _require_binary(fitment_fact_hash(baseline.payload) == baseline.fact_hash)
    # A verification must actually belong to this source/query/vehicle. A mere
    # FK or a count of verification rows does not make a damaged baseline formal.
    verified = db.execute(select(VehicleVerification, QueryRun, ParserSelection)
        .join(QueryRun, QueryRun.id == VehicleVerification.query_id)
        .join(ParserSelection, ParserSelection.query_run_id == QueryRun.id)
        .where(VehicleVerification.snapshot_id == baseline.id,
               VehicleVerification.vehicle_id == baseline.vehicle_id,
               QueryRun.source_id == baseline.source_id, QueryRun.query_key == run.query_key)
        .execution_options(populate_existing=True)).all()
    _require_binary(any(item.query == run.query and item.query_key == digest(item.query)
        and selected.source_id == item.source_id and selected.descriptor.get('target_kind') == 'vehicle'
        and selected.descriptor.get('source_id') == item.source_id
        and selected.descriptor.get('bundle_id') == selected.bundle_id
        and selected.descriptor.get('parser_version') == baseline.parser_version
        and record.parser_identity == baseline.parser_identity == {
            'bundle_id': selected.bundle_id, 'parser_digest': selected.descriptor.get('parser_digest'),
            'deployment_revision': selected.deployment_revision}
        for record, item, selected in verified))


def checked_binary_baseline(db: Session, baseline, run: QueryRun) -> None:
    """Also used before online quality assessment, so malformed data fails closed."""
    try:
        with db.no_autoflush:
            _checked_binary_baseline(db, baseline, run)
    except VehicleRawIntegrityError:
        raise
    except Exception:
        raise VehicleRawIntegrityError() from None


def _binary_integrity_context(db: Session, row) -> BinaryReviewContext:
    """Read-only, complete original-Q and formal-baseline verification; never repair."""
    from .vehicles import VehicleQuarantine, VehicleService, VehicleSnapshot
    from .vehicle_quality import assess_vehicle_quality
    try:
        with db.no_autoflush:
            _require_binary(type(row) is VehicleQuarantine and is_binary_quarantine(row))
            row = db.get(VehicleQuarantine, row.id, populate_existing=True)
            _require_binary(row is not None)
            run = db.get(QueryRun, row.query_id, populate_existing=True)
            _require_binary(run is not None and run.source_id == row.source_id == SOURCE_ID
                and run.query == {'vehicle_id': row.vehicle_id} and run.query_key == digest(run.query))
            raw = checked_vehicle_bytes(db, row)
            provenance = checked_vehicle_parse_provenance(db, row)
            _require_binary(row.body_encoding == 'binary' and provenance is not None)
            _checked_vehicle_structure(row.payload, row.vehicle_id)
            baseline = db.get(VehicleSnapshot, row.previous_snapshot_id, populate_existing=True)
            checked_binary_baseline(db, baseline, run)
            quality = assess_vehicle_quality(baseline.payload, row.payload)
            _require_binary(quality == row.quality)
            blocked = restriction('vehicle', quality, baseline.payload, row.payload)
            latest = VehicleService(db, None).latest(row.vehicle_id)
            key = binary_binding(row.source_id, run.query_key, baseline.id,
                {'url': row.source_url, 'parser_version': row.parser_version,
                 'content_type': row.content_type, 'parser_identity': row.parser_identity},
                row.payload, quality, raw=raw)
            evidence = BinaryReviewEvidence(body_encoding='binary', body=None,
                raw_capture_id=row.raw_capture_id, raw_hash=row.raw_hash, byte_count=len(raw),
                content_type=row.content_type, source_url=row.source_url, parser_version=row.parser_version,
                parser_identity=row.parser_identity, parse_provenance=provenance)
            return BinaryReviewContext(key, blocked, latest.id if latest else None,
                                       baseline.payload, row.payload, evidence, raw)
    except VehicleRawIntegrityError:
        raise
    except Exception:
        raise VehicleRawIntegrityError() from None


def binary_context(db: Session, row) -> BinaryReviewContext:
    """Review facade: both exact originals need original and structured purposes.

    Integrity remains independent of source permission. This fixed facade is
    used by review reads/writes; the existing online consumer retains its own
    integrity entry and authorization contract, rather than borrowing a local
    review-purpose grant. Neither path changes production's pending policy.
    """
    from .vehicles import VehicleQuarantine, VehicleSnapshot
    try:
        with db.no_autoflush:
            checked = _binary_integrity_context(db, row)
            original = db.get(VehicleQuarantine, row.id, populate_existing=True)
            checked_vehicle_original_bytes(db, original, structured=True)
            baseline = db.get(VehicleSnapshot, original.previous_snapshot_id, populate_existing=True)
            checked_vehicle_original_bytes(db, baseline, structured=True)
            return checked
    except (VehicleRawIntegrityError, VehicleOriginalUseNotAllowed, VehicleUseNotAllowed):
        raise
    except Exception:
        raise VehicleRawIntegrityError() from None


def serialize(row: QuarantineReview) -> dict:
    return {'id': row.id, 'quarantine_id': row.quarantine_id, 'revision': row.revision,
            'action': row.action, 'operator': row.operator, 'reason': row.reason,
            'created_at': utc(row.created_at).isoformat(), 'expires_at': utc(row.expires_at).isoformat()}


def review_state(db: Session, row) -> dict:
    key, blocked, latest_id, before, after = context(db, row)
    return _format_review_state(db, row, key=key, blocked=blocked, latest_id=latest_id, before=before, after=after)


def _format_review_state(db: Session, row, *, key, blocked, latest_id, before, after) -> dict:
    events = db.scalars(select(QuarantineReview).where(QuarantineReview.binding_hash == key)
        .order_by(desc(QuarantineReview.revision)).limit(101)).all()
    event = events[0] if events else None
    used = db.get(QuarantineApprovalUse, event.id) if event else None
    stale = latest_id != row.previous_snapshot_id
    state = ('applied_on_online_fetch' if used else 'stale_baseline' if stale else 'restricted' if blocked else
             'pending' if event is None else 'kept_quarantined' if event.action == 'keep_quarantined' else
             'expired' if utc(event.expires_at) <= utcnow() else 'approved_waiting_online')
    return {'quarantine_id': row.id, 'scope': 'local_workspace', 'state': state,
            'revision': event.revision if event else 0, 'can_approve': not (stale or blocked or used),
            'restriction': blocked, 'baseline_snapshot_id': row.previous_snapshot_id,
            'current_snapshot_id': latest_id, 'applied_query_id': used.query_id if used else None,
            'comparison': {'before': before, 'candidate': after},
            'history': [serialize(item) for item in events[:100]], 'history_truncated': len(events) > 100}


def binary_review_state(db: Session, row, *, checked: BinaryReviewContext | None = None) -> dict:
    checked = checked if checked is not None else binary_context(db, row)
    state = _format_review_state(db, row, key=checked.key, blocked=checked.blocked,
        latest_id=checked.latest_id, before=checked.before, after=checked.candidate)
    return BinaryReviewState(**state, evidence_format='raw-evidence-v2', binding_contract='vehicle-binary@1',
                             binding_hash=checked.key, raw_evidence=checked.evidence).model_dump()


def consume_approval(db: Session, run: QueryRun, target: str, baseline, result: dict,
                     payload: list | dict, quality: dict) -> str | None:
    """Caller holds the ingestion lock; this use rolls back with accepted facts."""
    before = baseline.parsed_variants if target == 'tire' else baseline.payload
    if restriction(target, quality, before, payload):
        return None
    key = binding(target, run.source_id, run.query_key, baseline.id, result, payload, quality)
    event = db.scalar(select(QuarantineReview).where(QuarantineReview.binding_hash == key)
        .order_by(desc(QuarantineReview.revision)).limit(1))
    if (event is None or event.action != 'approve' or utc(event.expires_at) <= utcnow()
            or utc(run.created_at) <= utc(event.created_at)
            or db.get(QuarantineApprovalUse, event.id) is not None):
        return None
    db.add(QuarantineApprovalUse(review_id=event.id, query_id=run.id))
    db.add(AuditEvent(session_id=run.session_id, query_id=run.id, action='quarantine_approval_applied',
        detail={'review_id': event.id, 'quarantine_id': event.quarantine_id, 'binding_hash': key}))
    return event.id


def consume_binary_approval(db: Session, run: QueryRun, baseline, result: dict,
                            payload: dict, quality: dict, *, capture) -> str | None:
    """Caller has checked fresh capture/provenance and holds the one ingestion lock."""
    from .vehicles import VehicleQuarantine
    try:
        with db.no_autoflush:
            if restriction('vehicle', quality, baseline.payload, payload):
                return None
            checked_binary_baseline(db, baseline, run)
            raw = result['body']
            _require_binary(type(raw) is bytes and capture.query_id == run.id
                and capture.body_encoding == result['body_encoding'] == 'binary'
                and capture.raw_body == raw and capture.byte_count == len(raw)
                and capture.raw_hash == hashlib.sha256(raw).hexdigest())
            key = binary_binding(run.source_id, run.query_key, baseline.id, result, payload, quality, raw=raw)
            event = db.scalar(select(QuarantineReview).where(QuarantineReview.binding_hash == key)
                .order_by(desc(QuarantineReview.revision)).limit(1))
            if (event is None or event.action != 'approve' or utc(event.expires_at) <= utcnow()
                    or utc(run.created_at) <= utc(event.created_at)
                    or db.get(QuarantineApprovalUse, event.id) is not None):
                return None
            original = db.get(VehicleQuarantine, event.quarantine_id, populate_existing=True)
            _require_binary(original is not None)
            checked = _binary_integrity_context(db, original)
            _require_binary(checked.key == event.binding_hash == key and checked.blocked is None
                and original.previous_snapshot_id == checked.latest_id == baseline.id
                and original.raw_capture_id != capture.id and checked.raw == raw)
            db.add(QuarantineApprovalUse(review_id=event.id, query_id=run.id))
            db.add(AuditEvent(session_id=run.session_id, query_id=run.id, action='quarantine_approval_applied',
                detail={'review_id': event.id, 'quarantine_id': event.quarantine_id, 'binding_hash': key}))
            return event.id
    except VehicleRawIntegrityError:
        raise
    except Exception:
        raise VehicleRawIntegrityError() from None


def snapshot_review(db: Session, snapshot_id: str, target: str = 'tire') -> dict | None:
    from .vehicles import VehicleVerification
    verified = Verification if target == 'tire' else VehicleVerification
    event = db.scalar(select(QuarantineReview).join(QuarantineApprovalUse,
        QuarantineApprovalUse.review_id == QuarantineReview.id).join(verified,
        verified.query_id == QuarantineApprovalUse.query_id).where(verified.snapshot_id == snapshot_id))
    return serialize(event) if event else None


def register_review_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    admin_guard = make_admin_guard(get_db)

    @app.get('/v1/quarantines/{quarantine_id}/review')
    def read(quarantine_id: str, mode: Literal['history'] = Query(...),
             evidence_format: Literal['raw-evidence-v2'] | None = Query(None, alias='format'),
             db: Session = Depends(get_db)):
        row = find_quarantine(db, quarantine_id, allow_binary=evidence_format is not None)
        if is_binary_quarantine(row):
            try:
                return binary_review_state(db, row)
            except VehicleRawIntegrityError as error:
                raise HTTPException(503, {'code': error.code}) from None
            except (VehicleOriginalUseNotAllowed, VehicleUseNotAllowed) as error:
                raise HTTPException(403, {'code': error.code}) from None
        if evidence_format is not None:
            raise HTTPException(422, {'code': 'review_format_target_mismatch'})
        return review_state(db, row)

    @app.post('/v1/quarantines/{quarantine_id}/reviews', status_code=201, dependencies=[Depends(admin_guard)])
    def decide(quarantine_id: str, payload: ReviewRequest | BinaryVehicleReviewRequest, request: Request,
               mode: Literal['history'] | None = Query(None),
               evidence_format: Literal['raw-evidence-v2'] | None = Query(None, alias='format'),
               db: Session = Depends(get_db)):
        from .service import QueryService
        service = QueryService(db, None)
        service.lock_ingestion()
        actor_user_id = _locked_binary_actor(db, request) if evidence_format is not None else None
        row = find_quarantine(db, quarantine_id, allow_binary=evidence_format is not None)
        binary = is_binary_quarantine(row)
        if ((binary and (mode != 'history' or type(payload) is not BinaryVehicleReviewRequest))
                or (not binary and (evidence_format is not None or type(payload) is not ReviewRequest))):
            raise HTTPException(422, {'code': 'review_format_body_target_mismatch'})
        try:
            checked = binary_context(db, row) if binary else None
            state = binary_review_state(db, row, checked=checked) if binary else review_state(db, row)
        except VehicleRawIntegrityError as error:
            raise HTTPException(503, {'code': error.code}) from None
        except (VehicleOriginalUseNotAllowed, VehicleUseNotAllowed) as error:
            raise HTTPException(403, {'code': error.code}) from None
        if binary and payload.expected_binding_hash != checked.key:
            raise HTTPException(409, {'code': 'review_binding_changed'})
        if payload.expected_revision != state['revision']:
            raise HTTPException(409, '审批记录已更新，请重新载入并核对后提交')
        if payload.action == 'approve' and not state['can_approve']:
            raise HTTPException(409, '当前记录不可批准：基线已变更、已采纳或涉及身份/证据问题')
        if state['applied_query_id']:
            raise HTTPException(409, '此批准已随在线请求采纳；后续处理须使用事实纠错或版本管理')
        key = checked.key if binary else context(db, row)[0]
        event = QuarantineReview(quarantine_id=row.id, binding_hash=key, revision=state['revision'] + 1,
            action=payload.action, operator=payload.operator, reason=payload.reason,
            actor_session_id=request.state.session_id, expires_at=utcnow() + APPROVAL_TTL)
        db.add(event)
        db.flush()
        service.audit(request.state.session_id, 'quarantine_review_recorded', row.query_id,
                      review_id=event.id, quarantine_id=row.id, decision=payload.action,
                      **({'actor_user_id': actor_user_id} if binary else {}))
        db.commit()
        if binary:
            try:
                return binary_review_state(db, row)
            except VehicleRawIntegrityError as error:
                raise HTTPException(503, {'code': error.code}) from None
            except (VehicleOriginalUseNotAllowed, VehicleUseNotAllowed) as error:
                raise HTTPException(403, {'code': error.code}) from None
        return review_state(db, row)
