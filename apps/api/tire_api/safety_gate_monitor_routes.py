"""Private Safety Gate subscriptions, check receipts and notification history."""
from copy import deepcopy
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import Field, StrictBool, StrictInt
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .adapters.safety_gate import SOURCE_ID
from .auth import session_scope
from .db import uid, utcnow
from .domain import StrictModel, digest
from .monitoring import ReadState
from .research import DescriptionText
from .safety_gate_alerts import AlertChange, AlertObservation, observation_json
from .safety_gate_monitor_models import (SafetyGateMonitorJob, SafetyGateMonitorRule, SafetyGateRuleRevision,
    SafetyGateMonitorCheck, SafetyGateMonitorRun, SafetyGateNotification)
from .safety_gate_monitoring import current_rules, reschedule
from .service import QueryService, timestamp

NOTICE = '按官方索引检查最近所选数量的英文周报。提醒匹配当前规则修订后观察的变化前后字段，首次观察表示系统首次保存，具体轮胎适用性待核对。'


class MonitorQuery(StrictModel):
    report_limit: StrictInt = Field(default=4, ge=1, le=12)
    text: DescriptionText = Field(default='tyre', max_length=120)


class RuleSettings(StrictModel):
    name: DescriptionText = Field(min_length=1, max_length=120)
    enabled: StrictBool = False
    interval_seconds: StrictInt = Field(default=21600, ge=3600, le=604800)


class RuleCreate(RuleSettings):
    query: MonitorQuery = Field(default_factory=MonitorQuery)


class RuleEdit(RuleSettings):
    expected_revision: StrictInt = Field(ge=1)
    archived: StrictBool = False


def find_rule(db, identity, scope):
    row = db.execute(current_rules().where(SafetyGateMonitorRule.id == identity,
        SafetyGateMonitorRule.session_id.in_(scope))).first()
    if row is None:
        raise HTTPException(404, '当前账户不存在此Safety Gate监控规则')
    return row


def check_replay(row, fingerprint):
    if row.request_hash != fingerprint:
        raise HTTPException(409, '同一请求标识已绑定不同的监控内容')


def revision_view(row):
    return {'revision': row.revision, 'name': row.name, 'enabled': row.enabled, 'archived': row.archived,
        'interval_seconds': row.interval_seconds, 'created_at': timestamp(row.created_at)}


def run_view(db, row):
    if row is None:
        return None
    checks = db.scalars(select(SafetyGateMonitorCheck).where(SafetyGateMonitorCheck.attempt_id == row.attempt_id)
        .order_by(SafetyGateMonitorCheck.position)).all()
    return {'id': row.id, 'attempt_id': row.attempt_id, 'state': row.state, 'reason': row.reason,
        'started_at': timestamp(row.started_at), 'finished_at': timestamp(row.finished_at),
        'coverage': 'complete' if row.state == 'safety_gate_complete' else 'incomplete',
        'selected_reports': deepcopy(row.selected_reports), 'notification_count': row.notification_count,
        'checks': [{'query_id': check.query_id, 'snapshot_id': check.snapshot_id, 'query': deepcopy(check.query),
            'state': check.state, 'reason': check.reason, 'observed_at': timestamp(check.observed_at)} for check in checks]}


def rule_view(db, rule, revision, *, write_revision=None):
    job = db.get(SafetyGateMonitorJob, rule.job_id)
    run = db.scalar(select(SafetyGateMonitorRun).where(SafetyGateMonitorRun.job_id == job.id)
        .order_by(desc(SafetyGateMonitorRun.finished_at), desc(SafetyGateMonitorRun.id)).limit(1))
    result = {'id': rule.id, 'source_id': SOURCE_ID, 'query': deepcopy(job.query), **revision_view(revision),
        'job': {'id': job.id, 'next_due_at': timestamp(job.next_due_at) if revision.enabled and not revision.archived else None,
            'lease_until': timestamp(job.lease_until), 'last_run': run_view(db, run)}, 'notice': NOTICE}
    if write_revision is not None:
        result['write_result'] = {'revision_id': write_revision.id, 'revision': write_revision.revision}
    return result


def page(items, total, offset, limit):
    return {'scope': 'session', 'data_state': 'local_snapshot', 'items': items, 'total': total, 'offset': offset, 'limit': limit}


def register_safety_gate_monitor_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post('/v1/safety-gate-monitor-rules', status_code=201)
    def create(payload: RuleCreate, request: Request,
               idempotency_key: UUID | None = Header(None, alias='Idempotency-Key'), db: Session = Depends(get_db)):
        service = QueryService(db, None)
        service.lock_ingestion()
        session_id = request.state.session_id
        scope = session_scope(db, session_id)
        key = str(idempotency_key) if idempotency_key else None
        fingerprint = digest(payload.model_dump())
        existing = db.scalar(select(SafetyGateMonitorRule).where(SafetyGateMonitorRule.session_id.in_(scope),
            SafetyGateMonitorRule.idempotency_key == key)) if key else None
        if existing:
            check_replay(existing, fingerprint)
            written = db.scalar(select(SafetyGateRuleRevision).where(SafetyGateRuleRevision.rule_id == existing.id,
                SafetyGateRuleRevision.revision == 1))
            return rule_view(db, *find_rule(db, existing.id, scope), write_revision=written)
        query = payload.query.model_dump()
        job_id = digest({'source_id': SOURCE_ID, 'session_id': session_id, 'query': query})
        job = db.get(SafetyGateMonitorJob, job_id)
        if job is None:
            job = SafetyGateMonitorJob(id=job_id, session_id=session_id, query=query, query_key=digest(query))
            db.add(job)
            db.flush()
        rule = SafetyGateMonitorRule(id=uid(), session_id=session_id, job_id=job.id,
            idempotency_key=key, request_hash=fingerprint)
        db.add(rule)
        db.flush()
        revision = SafetyGateRuleRevision(rule_id=rule.id, revision=1, request_hash=fingerprint,
            **payload.model_dump(exclude={'query'}))
        db.add(revision)
        db.flush()
        reschedule(db, job)
        service.audit(session_id, 'safety_gate_monitor_rule_created', rule_id=rule.id)
        db.commit()
        return rule_view(db, rule, revision, write_revision=revision)

    @app.get('/v1/safety-gate-monitor-rules')
    def listing(request: Request, archived: bool = False, offset: int = Query(0, ge=0),
                limit: int = Query(20, ge=1, le=50), db: Session = Depends(get_db)):
        statement = current_rules().where(SafetyGateMonitorRule.session_id.in_(session_scope(db, request.state.session_id)),
            SafetyGateRuleRevision.archived == archived)
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.execute(statement.order_by(desc(SafetyGateMonitorRule.created_at), SafetyGateMonitorRule.id)
            .offset(offset).limit(limit)).all()
        return page([rule_view(db, *row) for row in rows], total, offset, limit)

    @app.get('/v1/safety-gate-monitor-rules/{rule_id}')
    def detail(rule_id: str, request: Request, mode: Literal['history'], db: Session = Depends(get_db)):
        rule, revision = find_rule(db, rule_id, session_scope(db, request.state.session_id))
        rows = db.scalars(select(SafetyGateRuleRevision).where(SafetyGateRuleRevision.rule_id == rule.id)
            .order_by(desc(SafetyGateRuleRevision.revision)).limit(51)).all()
        return {**rule_view(db, rule, revision), 'history': [revision_view(row) for row in rows[:50]], 'history_truncated': len(rows) > 50}

    @app.post('/v1/safety-gate-monitor-rules/{rule_id}/revisions')
    def revise(rule_id: str, payload: RuleEdit, request: Request,
               idempotency_key: UUID | None = Header(None, alias='Idempotency-Key'), db: Session = Depends(get_db)):
        service = QueryService(db, None)
        service.lock_ingestion()
        rule, before = find_rule(db, rule_id, session_scope(db, request.state.session_id))
        key = str(idempotency_key) if idempotency_key else None
        fingerprint = digest(payload.model_dump())
        existing = db.scalar(select(SafetyGateRuleRevision).where(SafetyGateRuleRevision.rule_id == rule.id,
            SafetyGateRuleRevision.idempotency_key == key)) if key else None
        if existing:
            check_replay(existing, fingerprint)
            return rule_view(db, rule, before, write_revision=existing)
        if before.revision != payload.expected_revision:
            raise HTTPException(409, '监控规则已更新，请重新载入')
        settings = payload.model_dump(exclude={'expected_revision'})
        if settings['archived']:
            settings['enabled'] = False
        revision = SafetyGateRuleRevision(rule_id=rule.id, revision=before.revision + 1,
            idempotency_key=key, request_hash=fingerprint, **settings)
        db.add(revision)
        db.flush()
        reschedule(db, db.get(SafetyGateMonitorJob, rule.job_id))
        service.audit(request.state.session_id, 'safety_gate_monitor_rule_revised', rule_id=rule.id, revision=revision.revision)
        db.commit()
        return rule_view(db, rule, revision, write_revision=revision)

    @app.get('/v1/safety-gate-monitor-rules/{rule_id}/runs')
    def runs(rule_id: str, request: Request, mode: Literal['history'], offset: int = Query(0, ge=0),
             limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
        rule, _ = find_rule(db, rule_id, session_scope(db, request.state.session_id))
        statement = select(SafetyGateMonitorRun).where(SafetyGateMonitorRun.job_id == rule.job_id)
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.scalars(statement.order_by(desc(SafetyGateMonitorRun.finished_at), desc(SafetyGateMonitorRun.id))
            .offset(offset).limit(limit)).all()
        return page([run_view(db, row) for row in rows], total, offset, limit)

    @app.get('/v1/safety-gate-notifications')
    def notifications(request: Request, mode: Literal['history'], unread: bool = False,
                      offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50), db: Session = Depends(get_db)):
        statement = (select(SafetyGateNotification, SafetyGateRuleRevision, AlertObservation)
            .join(SafetyGateRuleRevision, SafetyGateRuleRevision.id == SafetyGateNotification.rule_revision_id)
            .join(AlertChange, AlertChange.id == SafetyGateNotification.event_id)
            .join(AlertObservation, AlertObservation.id == AlertChange.observation_id)
            .where(SafetyGateNotification.session_id.in_(session_scope(db, request.state.session_id))))
        if unread:
            statement = statement.where(SafetyGateNotification.read_at.is_(None))
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.execute(statement.order_by(desc(SafetyGateNotification.delivered_at), SafetyGateNotification.id)
            .offset(offset).limit(limit)).all()
        snapshots = {}
        return page([{'id': item.id, 'rule_id': item.rule_id, 'rule_name': revision.name, 'run_id': item.run_id,
            'delivered_at': timestamp(item.delivered_at), 'read_at': timestamp(item.read_at),
            'observation': observation_json(db, observation, snapshots), 'applicability': 'not_assessed'}
            for item, revision, observation in rows], total, offset, limit)

    @app.put('/v1/safety-gate-notifications/{notification_id}/read')
    def read(notification_id: str, payload: ReadState, request: Request, db: Session = Depends(get_db)):
        service = QueryService(db, None)
        service.lock_ingestion()
        row = db.scalar(select(SafetyGateNotification).where(SafetyGateNotification.id == notification_id,
            SafetyGateNotification.session_id.in_(session_scope(db, request.state.session_id))))
        if row is None:
            raise HTTPException(404, '当前账户不存在此Safety Gate提醒')
        row.read_at = row.read_at or utcnow() if payload.read else None
        service.audit(request.state.session_id, 'safety_gate_notification_read', notification_id=row.id, read=payload.read)
        db.commit()
        return {'id': row.id, 'read_at': timestamp(row.read_at)}
