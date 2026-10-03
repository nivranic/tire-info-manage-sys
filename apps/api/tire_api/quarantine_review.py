"""Human confirmation of exact losses; only a subsequent matching online fetch can apply it."""
from datetime import timedelta
import hashlib
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import Field, StrictBool, StrictInt, field_validator
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .db import (AuditEvent, QueryRun, QuarantineApprovalUse, QuarantineReview,
                 RejectedObservation, Snapshot, SourceQuarantine, Verification, utc, utcnow)
from .domain import StrictModel, VariantInput, digest
from .quality import stable_key
from .research import DescriptionText

APPROVAL_TTL = timedelta(hours=24)
LOSS_REASONS = {'field_loss_threshold', 'row_loss_threshold'}


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


def find_quarantine(db: Session, quarantine_id: str):
    from .vehicles import VehicleQuarantine
    row = db.get(SourceQuarantine, quarantine_id) or db.get(VehicleQuarantine, quarantine_id)
    if row is None:
        if db.get(RejectedObservation, quarantine_id) is not None:
            raise HTTPException(409, '解析或结构校验失败须先修复解析器，不能人工跳过')
        raise HTTPException(404, '未找到可核验的隔离记录')
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


def serialize(row: QuarantineReview) -> dict:
    return {'id': row.id, 'quarantine_id': row.quarantine_id, 'revision': row.revision,
            'action': row.action, 'operator': row.operator, 'reason': row.reason,
            'created_at': utc(row.created_at).isoformat(), 'expires_at': utc(row.expires_at).isoformat()}


def review_state(db: Session, row) -> dict:
    key, blocked, latest_id, before, after = context(db, row)
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

    @app.get('/v1/quarantines/{quarantine_id}/review')
    def read(quarantine_id: str, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        return review_state(db, find_quarantine(db, quarantine_id))

    @app.post('/v1/quarantines/{quarantine_id}/reviews', status_code=201)
    def decide(quarantine_id: str, payload: ReviewRequest, request: Request, db: Session = Depends(get_db)):
        from .auth import require_admin
        require_admin(request, db)
        from .service import QueryService
        service = QueryService(db, None)
        service.lock_ingestion()
        row = find_quarantine(db, quarantine_id)
        state = review_state(db, row)
        if payload.expected_revision != state['revision']:
            raise HTTPException(409, '审批记录已更新，请重新载入并核对后提交')
        if payload.action == 'approve' and not state['can_approve']:
            raise HTTPException(409, '当前记录不可批准：基线已变更、已采纳或涉及身份/证据问题')
        if state['applied_query_id']:
            raise HTTPException(409, '此批准已随在线请求采纳；后续处理须使用事实纠错或版本管理')
        key, *_ = context(db, row)
        event = QuarantineReview(quarantine_id=row.id, binding_hash=key, revision=state['revision'] + 1,
            action=payload.action, operator=payload.operator, reason=payload.reason,
            actor_session_id=request.state.session_id, expires_at=utcnow() + APPROVAL_TTL)
        db.add(event)
        db.flush()
        service.audit(request.state.session_id, 'quarantine_review_recorded', row.query_id,
                      review_id=event.id, quarantine_id=row.id, decision=payload.action)
        db.commit()
        return review_state(db, row)
