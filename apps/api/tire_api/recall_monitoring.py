"""Session-owned campaign monitoring with append-only rules and fenced leases."""
from datetime import timedelta
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import Field, StrictBool, StrictInt
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .db import utc, utcnow, uid
from .domain import StrictModel, digest
from .monitoring import LeaseLost, ReadState
from .recall_models import (SOURCE_ID, RecallEvent, RecallMonitorJob, RecallMonitorRule, RecallMonitorRun,
                            RecallNotification, RecallQuery, RecallRevision, RecallRuleRevision)
from .research import DescriptionText
from .service import QueryService, timestamp
from .source_settings import SourceAccessBlocked, assert_source_access

LEASE_SECONDS = 600


class RecallRuleSettings(StrictModel):
    name: DescriptionText = Field(min_length=1, max_length=120)
    enabled: StrictBool = False
    interval_seconds: StrictInt = Field(default=21600, ge=3600, le=604800)


class RecallRuleCreate(RecallRuleSettings):
    query: RecallQuery


class RecallRuleEdit(RecallRuleSettings):
    expected_revision: StrictInt = Field(ge=1)
    archived: StrictBool = False


def current_rules():
    latest = (select(RecallRuleRevision.rule_id, func.max(RecallRuleRevision.revision).label("revision"))
              .group_by(RecallRuleRevision.rule_id).subquery())
    return (select(RecallMonitorRule, RecallRuleRevision)
        .join(RecallRuleRevision, RecallRuleRevision.rule_id == RecallMonitorRule.id)
        .join(latest, (latest.c.rule_id == RecallMonitorRule.id) & (latest.c.revision == RecallRuleRevision.revision)))


def active_rules():
    return current_rules().where(RecallRuleRevision.enabled.is_(True), RecallRuleRevision.archived.is_(False))


def record_notifications(db: Session, revision: RecallRevision, event: RecallEvent) -> None:
    rules = db.execute(active_rules().join(RecallMonitorJob, RecallMonitorRule.job_id == RecallMonitorJob.id)
                       .where(RecallMonitorJob.campaign_number == revision.campaign_number)).all()
    for rule, settings in rules:
        if db.scalar(select(RecallNotification.id).where(RecallNotification.rule_id == rule.id,
                                                       RecallNotification.event_id == event.id)):
            continue
        db.add(RecallNotification(session_id=rule.session_id, rule_id=rule.id,
                                 rule_revision_id=settings.id, event_id=event.id))


def reschedule(db: Session, job: RecallMonitorJob) -> None:
    rows = db.execute(active_rules().where(RecallMonitorRule.job_id == job.id)).all()
    interval = min((row.interval_seconds for _, row in rows), default=None)
    if interval is not None:
        job.next_due_at = utc(job.last_finished_at) + timedelta(seconds=interval) if job.last_finished_at else utcnow()


def guard_claim(db: Session, claim: dict) -> None:
    job = db.get(RecallMonitorJob, claim["id"], populate_existing=True)
    if (job is None or job.lease_token != claim["token"] or job.lease_until is None
            or utc(job.lease_until) <= utcnow()):
        raise LeaseLost("recall_monitor_lease_lost")
    generation = claim.get('source_access_generation')
    if type(generation) is not int:
        raise SourceAccessBlocked('source_access_pin_missing')
    assert_source_access(db, SOURCE_ID, generation)
    revisions = sorted(row.id for _, row in db.execute(active_rules().where(RecallMonitorRule.job_id == job.id)))
    if not revisions:
        raise LeaseLost("recall_monitor_rule_disabled")
    if revisions != claim.get('rule_revision_ids'):
        raise LeaseLost('recall_monitor_rule_changed')


def claim_job(database, now=None):
    from .monitor_tasks import expire_attempts_locked, start_attempt_locked
    from .recall_discovery_monitoring import source_busy_locked
    now = now or utcnow()
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        expire_attempts_locked(db, 'recall', now=now)
        try:
            generation = assert_source_access(db, SOURCE_ID)
        except SourceAccessBlocked:
            db.commit()
            return None
        # One source request at a time across processes, including distinct sessions.
        if source_busy_locked(db, now):
            db.commit()
            return None
        eligible = active_rules().with_only_columns(RecallMonitorRule.job_id)
        job = db.scalar(select(RecallMonitorJob).where(RecallMonitorJob.id.in_(eligible),
            RecallMonitorJob.next_due_at <= now,
            RecallMonitorJob.lease_until.is_(None) | (RecallMonitorJob.lease_until <= now))
            .order_by(RecallMonitorJob.next_due_at, RecallMonitorJob.id).limit(1))
        if job is None:
            db.commit()
            return None
        job.lease_token = uid()
        job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        claim = {"id": job.id, "token": job.lease_token, "started_at": now,
                 "source_access_generation": generation,
                 "source_id": SOURCE_ID, "query": {"campaign_number": job.campaign_number}, "session_id": job.session_id,
                 "queue_lag_seconds": max(0, (now - utc(job.next_due_at)).total_seconds())}
        claim['rule_revision_ids'] = sorted(row.id for _, row in db.execute(active_rules().where(RecallMonitorRule.job_id == job.id)))
        claim['attempt_id'] = start_attempt_locked(db, 'recall', claim)
        db.commit()
        return claim


def finish_job(database, claim, state, reason=None, now=None, *, query_id=None):
    from .monitor_tasks import finish_attempt_locked, interrupt_attempt_locked
    now = now or utcnow()
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        job = db.get(RecallMonitorJob, claim["id"])
        if (job is None or job.lease_token != claim["token"] or job.lease_until is None
                or utc(job.lease_until) <= now):
            interrupt_attempt_locked(db, claim, 'recall_monitor_lease_lost', now=now)
            db.commit()
            return False
        run = RecallMonitorRun(id=uid(), job_id=job.id, lease_token=claim["token"], state=state, reason=reason,
                               started_at=claim["started_at"], finished_at=now)
        db.add(run)
        db.flush()
        terminal = (interrupt_attempt_locked(db, claim, reason, now=now, run_id=run.id) if state == 'lease_lost' else
                    finish_attempt_locked(db, claim, state, reason, query_id=query_id, finished_at=now, run_id=run.id))
        if claim.get('attempt_id') and not terminal:
            db.rollback()
            return False
        job.last_finished_at, job.lease_token, job.lease_until = now, None, None
        reschedule(db, job)
        db.commit()
        return True


def interrupt_job(database, claim, reason, now=None):
    reason = reason if reason in {'recall_monitor_lease_lost', 'recall_monitor_rule_disabled',
                                  'recall_monitor_rule_changed', 'monitor_attempt_not_running'} else 'recall_monitor_lease_lost'
    return finish_job(database, claim, 'lease_lost', reason, now=now)


def revision_view(row):
    return {"revision": row.revision, "name": row.name, "enabled": row.enabled, "archived": row.archived,
            "interval_seconds": row.interval_seconds, "created_at": timestamp(row.created_at)}


def rule_view(db, rule, row):
    job = db.get(RecallMonitorJob, rule.job_id)
    last = db.scalar(select(RecallMonitorRun).where(RecallMonitorRun.job_id == job.id)
                     .order_by(desc(RecallMonitorRun.finished_at)).limit(1))
    return {"id": rule.id, "source_id": SOURCE_ID, "query": {"campaign_number": job.campaign_number},
        **revision_view(row), "job": {"id": job.id,
        "next_due_at": timestamp(job.next_due_at) if row.enabled and not row.archived else None,
        "lease_until": timestamp(job.lease_until), "last_run": {
            "state": last.state, "reason": last.reason, "finished_at": timestamp(last.finished_at)} if last else None}}


def find_rule(db, rule_id, session_id, expected=None):
    result = db.execute(current_rules().where(RecallMonitorRule.id == rule_id,
                                             RecallMonitorRule.session_id == session_id)).first()
    if result is None:
        raise HTTPException(404, "当前会话不存在此召回规则")
    if expected is not None and result[1].revision != expected:
        raise HTTPException(409, "召回规则已更新，请重新载入")
    return result


def register_recall_monitoring_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post("/v1/recall-monitor-rules", status_code=201)
    def create(payload: RecallRuleCreate, request: Request, db: Session = Depends(get_db)):
        service = QueryService(db, None)
        service.lock_ingestion()
        session_id = request.state.session_id
        job_id = digest({"source_id": SOURCE_ID, "session_id": session_id, "query": payload.query.canonical()})
        job = db.get(RecallMonitorJob, job_id)
        if job is None:
            job = RecallMonitorJob(id=job_id, session_id=session_id, campaign_number=payload.query.campaign_number)
            db.add(job)
            db.flush()
        rule = RecallMonitorRule(id=uid(), session_id=session_id, job_id=job.id)
        db.add(rule)
        db.flush()
        row = RecallRuleRevision(rule_id=rule.id, revision=1, **payload.model_dump(exclude={"query"}))
        db.add(row)
        db.flush()
        reschedule(db, job)
        service.audit(session_id, "recall_monitor_rule_created", rule_id=rule.id)
        db.commit()
        return rule_view(db, rule, row)

    @app.get("/v1/recall-monitor-rules")
    def listing(request: Request, archived: bool = False, offset: int = Query(0, ge=0),
                limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
        statement = current_rules().where(RecallMonitorRule.session_id == request.state.session_id,
                                          RecallRuleRevision.archived == archived)
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.execute(statement.order_by(desc(RecallMonitorRule.created_at), RecallMonitorRule.id)
                          .offset(offset).limit(limit)).all()
        return {"scope": "session", "data_state": "local_snapshot", "items": [rule_view(db, *row) for row in rows],
                "total": total, "offset": offset, "limit": limit}

    @app.get("/v1/recall-monitor-rules/{rule_id}")
    def detail(rule_id: str, request: Request, mode: Literal["history"] = Query(...), db: Session = Depends(get_db)):
        rule, row = find_rule(db, rule_id, request.state.session_id)
        history = db.scalars(select(RecallRuleRevision).where(RecallRuleRevision.rule_id == rule.id)
                             .order_by(desc(RecallRuleRevision.revision)).limit(51)).all()
        return {**rule_view(db, rule, row), "history": [revision_view(item) for item in history[:50]],
                "history_truncated": len(history) > 50}

    @app.post("/v1/recall-monitor-rules/{rule_id}/revisions")
    def revise(rule_id: str, payload: RecallRuleEdit, request: Request, db: Session = Depends(get_db)):
        service = QueryService(db, None)
        service.lock_ingestion()
        rule, before = find_rule(db, rule_id, request.state.session_id, payload.expected_revision)
        settings = payload.model_dump(exclude={"expected_revision"})
        if settings["archived"]:
            settings["enabled"] = False
        if all(getattr(before, key) == value for key, value in settings.items()):
            return rule_view(db, rule, before)
        row = RecallRuleRevision(rule_id=rule.id, revision=before.revision + 1, **settings)
        db.add(row)
        db.flush()
        job = db.get(RecallMonitorJob, rule.job_id)
        # The claim pins rule revisions. Keep its source reservation until the
        # old request returns or expires; clearing it here would permit overlap.
        reschedule(db, job)
        service.audit(request.state.session_id, "recall_monitor_rule_revised", rule_id=rule.id, revision=row.revision)
        db.commit()
        return rule_view(db, rule, row)

    @app.get("/v1/recall-notifications")
    def notifications(request: Request, mode: Literal["history"] = Query(...), unread: bool = False,
                      offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
        statement = (select(RecallNotification, RecallRuleRevision, RecallEvent, RecallRevision)
            .join(RecallRuleRevision, RecallRuleRevision.id == RecallNotification.rule_revision_id)
            .join(RecallEvent, RecallEvent.id == RecallNotification.event_id)
            .join(RecallRevision, RecallRevision.id == RecallEvent.revision_id)
            .where(RecallNotification.session_id == request.state.session_id))
        if unread:
            statement = statement.where(RecallNotification.read_at.is_(None))
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.execute(statement.order_by(desc(RecallNotification.delivered_at), RecallNotification.id)
                          .offset(offset).limit(limit)).all()
        items = [{"id": item.id, "rule_id": item.rule_id, "rule_name": rule.name, "kind": event.kind,
            "campaign_number": revision.campaign_number, "source_id": SOURCE_ID, "snapshot_id": revision.snapshot_id,
            "previous_snapshot_id": revision.previous_snapshot_id, "revision": revision.revision,
            "observed_at": timestamp(event.observed_at), "delivered_at": timestamp(item.delivered_at),
            "read_at": timestamp(item.read_at), "changes": event.changes} for item, rule, event, revision in rows]
        return {"scope": "session", "data_state": "local_snapshot", "items": items,
                "total": total, "offset": offset, "limit": limit}

    @app.put("/v1/recall-notifications/{notification_id}/read")
    def mark(notification_id: str, payload: ReadState, request: Request, db: Session = Depends(get_db)):
        service = QueryService(db, None)
        service.lock_ingestion()
        row = db.get(RecallNotification, notification_id)
        if row is None or row.session_id != request.state.session_id:
            raise HTTPException(404, "当前会话不存在此召回提醒")
        row.read_at = utcnow() if payload.read else None
        service.audit(request.state.session_id, "recall_notification_read_changed", notification_id=row.id, read=payload.read)
        db.commit()
        return {"id": row.id, "read_at": timestamp(row.read_at)}
