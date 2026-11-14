"""Private 中国召回 subscriptions, check receipts and notification history."""
from copy import deepcopy
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .adapters.samr import SOURCE_ID, query_url
from .auth import session_scope
from .db import uid, utc, utcnow
from .domain import StrictModel, digest
from .monitoring import ReadState
from .research import DescriptionText
from .samr_notice_history import SamrNoticeChange, SamrNoticeObservation, observation_json
from .samr_monitor_models import (SamrMonitorJob, SamrMonitorRule, SamrRuleRevision,
    SamrMonitorCheck, SamrMonitorRun, SamrNotification)
from .samr_monitoring import current_rules, reschedule
from .service import QueryService, timestamp

NOTICE = '检索监控先两遍核对配置页数的列表，再检查所选公告。运行记录区分配置范围完成与来源结果完整覆盖。提醒匹配当前规则修订后观察的标题和正文变化，首次观察表示系统首次保存，具体SKU和批次适用性待核对。'


class SearchMonitorQuery(StrictModel):
    operation: Literal['search'] = 'search'
    keyword: StrictStr = Field(default='轮胎', max_length=80)
    page_limit: StrictInt = Field(default=4, ge=1, le=60)
    notice_limit: StrictInt = Field(default=60, ge=1, le=900)
    text: DescriptionText = Field(default='', max_length=120)

    @model_validator(mode='after')
    def checked_query(self):
        query_url({'operation': 'search', 'keyword': self.keyword, 'page': '1'})
        return self


class NoticeMonitorQuery(StrictModel):
    operation: Literal['notice']
    reference: StrictStr = Field(max_length=200)
    text: DescriptionText = Field(default='', max_length=120)

    @model_validator(mode='after')
    def checked_query(self):
        query_url({'operation': 'notice', 'reference': self.reference})
        return self


MonitorQuery = Annotated[SearchMonitorQuery | NoticeMonitorQuery, Field(discriminator='operation')]


class RuleSettings(StrictModel):
    name: DescriptionText = Field(min_length=1, max_length=120)
    enabled: StrictBool = False
    interval_seconds: StrictInt = Field(default=21600, ge=3600, le=604800)


class RuleCreate(RuleSettings):
    query: MonitorQuery = Field(default_factory=SearchMonitorQuery)


class RuleEdit(RuleSettings):
    expected_revision: StrictInt = Field(ge=1)
    archived: StrictBool = False


def find_rule(db, identity, scope):
    row = db.execute(current_rules().where(SamrMonitorRule.id == identity,
        SamrMonitorRule.session_id.in_(scope))).first()
    if row is None:
        raise HTTPException(404, '当前账户不存在此中国召回监控规则')
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
    checks = db.scalars(select(SamrMonitorCheck).where(SamrMonitorCheck.attempt_id == row.attempt_id)
        .order_by(SamrMonitorCheck.position)).all()
    return {'id': row.id, 'attempt_id': row.attempt_id, 'state': row.state, 'reason': row.reason,
        'started_at': timestamp(row.started_at), 'finished_at': timestamp(row.finished_at),
        'coverage': deepcopy(row.coverage),
        'selected_notices': deepcopy(row.selected_notices), 'notification_count': row.notification_count,
        'checks': [{'query_id': check.query_id, 'snapshot_id': check.snapshot_id, 'verification_id': check.verification_id,
            'query': deepcopy(check.query),
            'state': check.state, 'reason': check.reason, 'observed_at': timestamp(check.observed_at)} for check in checks]}


def rule_view(db, rule, revision, *, write_revision=None):
    job = db.get(SamrMonitorJob, rule.job_id)
    run = db.scalar(select(SamrMonitorRun).where(SamrMonitorRun.job_id == job.id)
        .order_by(desc(SamrMonitorRun.finished_at), desc(SamrMonitorRun.id)).limit(1))
    result = {'id': rule.id, 'source_id': SOURCE_ID, 'query': deepcopy(job.query), **revision_view(revision),
        'job': {'id': job.id, 'next_due_at': timestamp(job.next_due_at) if revision.enabled and not revision.archived else None,
            'lease_until': timestamp(job.lease_until), 'last_run': run_view(db, run)}, 'notice': NOTICE}
    if write_revision is not None:
        result['write_result'] = {'revision_id': write_revision.id, 'revision': write_revision.revision}
    return result


def page(items, total, offset, limit):
    return {'scope': 'session', 'data_state': 'local_snapshot', 'items': items, 'total': total, 'offset': offset, 'limit': limit}


def register_samr_monitor_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post('/v1/samr-recall-monitor-rules', status_code=201)
    def create(payload: RuleCreate, request: Request,
               idempotency_key: UUID | None = Header(None, alias='Idempotency-Key'), db: Session = Depends(get_db)):
        service = QueryService(db, None)
        service.lock_ingestion()
        session_id = request.state.session_id
        scope = session_scope(db, session_id)
        key = str(idempotency_key) if idempotency_key else None
        fingerprint = digest(payload.model_dump())
        existing = db.scalar(select(SamrMonitorRule).where(SamrMonitorRule.session_id.in_(scope),
            SamrMonitorRule.idempotency_key == key)) if key else None
        if existing:
            check_replay(existing, fingerprint)
            written = db.scalar(select(SamrRuleRevision).where(SamrRuleRevision.rule_id == existing.id,
                SamrRuleRevision.revision == 1))
            return rule_view(db, *find_rule(db, existing.id, scope), write_revision=written)
        query = payload.query.model_dump()
        job_id = digest({'source_id': SOURCE_ID, 'session_id': session_id, 'query': query})
        job = db.get(SamrMonitorJob, job_id)
        if job is None:
            job = SamrMonitorJob(id=job_id, session_id=session_id, query=query, query_key=digest(query))
            db.add(job)
            db.flush()
        rule = SamrMonitorRule(id=uid(), session_id=session_id, job_id=job.id,
            idempotency_key=key, request_hash=fingerprint)
        db.add(rule)
        db.flush()
        revision = SamrRuleRevision(rule_id=rule.id, revision=1, request_hash=fingerprint,
            **payload.model_dump(exclude={'query'}))
        db.add(revision)
        db.flush()
        reschedule(db, job)
        service.audit(session_id, 'samr_monitor_rule_created', rule_id=rule.id)
        db.commit()
        return rule_view(db, rule, revision, write_revision=revision)

    @app.get('/v1/samr-recall-monitor-rules')
    def listing(request: Request, archived: bool = False, offset: int = Query(0, ge=0),
                limit: int = Query(20, ge=1, le=50), db: Session = Depends(get_db)):
        statement = current_rules().where(SamrMonitorRule.session_id.in_(session_scope(db, request.state.session_id)),
            SamrRuleRevision.archived == archived)
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.execute(statement.order_by(desc(SamrMonitorRule.created_at), SamrMonitorRule.id)
            .offset(offset).limit(limit)).all()
        return page([rule_view(db, *row) for row in rows], total, offset, limit)

    @app.get('/v1/samr-recall-monitor-rules/{rule_id}')
    def detail(rule_id: str, request: Request, mode: Literal['history'], db: Session = Depends(get_db)):
        rule, revision = find_rule(db, rule_id, session_scope(db, request.state.session_id))
        rows = db.scalars(select(SamrRuleRevision).where(SamrRuleRevision.rule_id == rule.id)
            .order_by(desc(SamrRuleRevision.revision)).limit(51)).all()
        return {**rule_view(db, rule, revision), 'history': [revision_view(row) for row in rows[:50]], 'history_truncated': len(rows) > 50}

    @app.post('/v1/samr-recall-monitor-rules/{rule_id}/revisions')
    def revise(rule_id: str, payload: RuleEdit, request: Request,
               idempotency_key: UUID | None = Header(None, alias='Idempotency-Key'), db: Session = Depends(get_db)):
        service = QueryService(db, None)
        service.lock_ingestion()
        rule, before = find_rule(db, rule_id, session_scope(db, request.state.session_id))
        key = str(idempotency_key) if idempotency_key else None
        fingerprint = digest(payload.model_dump())
        existing = db.scalar(select(SamrRuleRevision).where(SamrRuleRevision.rule_id == rule.id,
            SamrRuleRevision.idempotency_key == key)) if key else None
        if existing:
            check_replay(existing, fingerprint)
            return rule_view(db, rule, before, write_revision=existing)
        if before.revision != payload.expected_revision:
            raise HTTPException(409, '监控规则已更新，请重新载入')
        settings = payload.model_dump(exclude={'expected_revision'})
        if settings['archived']:
            settings['enabled'] = False
        revision = SamrRuleRevision(rule_id=rule.id, revision=before.revision + 1,
            idempotency_key=key, request_hash=fingerprint, **settings)
        db.add(revision)
        db.flush()
        reschedule(db, db.get(SamrMonitorJob, rule.job_id))
        service.audit(request.state.session_id, 'samr_monitor_rule_revised', rule_id=rule.id, revision=revision.revision)
        db.commit()
        return rule_view(db, rule, revision, write_revision=revision)

    @app.get('/v1/samr-recall-monitor-rules/{rule_id}/runs')
    def runs(rule_id: str, request: Request, mode: Literal['history'], offset: int = Query(0, ge=0),
             limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
        rule, _ = find_rule(db, rule_id, session_scope(db, request.state.session_id))
        statement = select(SamrMonitorRun).where(SamrMonitorRun.job_id == rule.job_id)
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.scalars(statement.order_by(desc(SamrMonitorRun.finished_at), desc(SamrMonitorRun.id))
            .offset(offset).limit(limit)).all()
        return page([run_view(db, row) for row in rows], total, offset, limit)

    @app.get('/v1/samr-recall-notifications')
    def notifications(request: Request, mode: Literal['history'], unread: bool = False,
                      offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50), db: Session = Depends(get_db)):
        statement = (select(SamrNotification, SamrRuleRevision, SamrNoticeObservation, SamrMonitorRun.id)
            .join(SamrRuleRevision, SamrRuleRevision.id == SamrNotification.rule_revision_id)
            .join(SamrNoticeChange, SamrNoticeChange.id == SamrNotification.event_id)
            .join(SamrNoticeObservation, SamrNoticeObservation.id == SamrNoticeChange.observation_id)
            .outerjoin(SamrMonitorRun, SamrMonitorRun.attempt_id == SamrNotification.attempt_id)
            .where(SamrNotification.session_id.in_(session_scope(db, request.state.session_id))))
        if unread:
            statement = statement.where(SamrNotification.read_at.is_(None))
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.execute(statement.order_by(desc(SamrNotification.delivered_at), SamrNotification.id)
            .offset(offset).limit(limit)).all()
        snapshots = {}
        return page([{'id': item.id, 'rule_id': item.rule_id, 'rule_name': revision.name,
            'attempt_id': item.attempt_id, 'run_id': run_id, 'queued_at': timestamp(item.queued_at),
            'delivered_at': timestamp(item.delivered_at), 'observed_at': timestamp(observation.observed_at),
            'lag_seconds': max(0, (utc(item.delivered_at) - utc(observation.observed_at)).total_seconds()),
            'read_at': timestamp(item.read_at),
            'observation': observation_json(db, observation, snapshots), 'applicability': 'not_assessed'}
            for item, revision, observation, run_id in rows], total, offset, limit)

    @app.put('/v1/samr-recall-notifications/{notification_id}/read')
    def read(notification_id: str, payload: ReadState, request: Request, db: Session = Depends(get_db)):
        service = QueryService(db, None)
        service.lock_ingestion()
        row = db.scalar(select(SamrNotification).where(SamrNotification.id == notification_id,
            SamrNotification.session_id.in_(session_scope(db, request.state.session_id))))
        if row is None:
            raise HTTPException(404, '当前账户不存在此中国召回提醒')
        row.read_at = row.read_at or utcnow() if payload.read else None
        service.audit(request.state.session_id, 'samr_notification_read', notification_id=row.id, read=payload.read)
        db.commit()
        return {'id': row.id, 'read_at': timestamp(row.read_at)}
