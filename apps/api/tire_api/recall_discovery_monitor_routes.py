"""Session-private discovery subscriptions and read-only bounded scan evidence."""
from copy import deepcopy
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import Field, StrictBool, StrictInt, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .db import uid, utcnow
from .domain import StrictModel, digest
from .monitoring import ReadState
from .recall_discovery import RecallSearchQuery
from .recall_discovery_monitor_models import (DISCOVERY_BUDGET, RecallDiscoveryJob, RecallDiscoveryRule,
    RecallDiscoveryRuleRevision, RecallDiscoveryRun, RecallDiscoveryPage, RecallDiscoveryCandidate,
    RecallDiscoveryNotification)
from .recall_discovery_monitoring import current_rules, reschedule
from .recall_models import SOURCE_ID
from .research import DescriptionText
from .service import QueryService, timestamp

NOTICE = ('名称检索仅发现召回候选，不确认具体 SKU 或 DOT/TIN 适用性；两次有界遍历一致'
          '不代表上游原子快照。首次完整扫描建立基线，不发送提醒；不完整扫描不推进基线。')


class DiscoveryQuery(StrictModel):
    search: str = Field(min_length=1, max_length=120)

    @field_validator('search')
    @classmethod
    def clean_search(cls, value):
        return RecallSearchQuery(search=value).search


class DiscoveryRuleSettings(StrictModel):
    name: DescriptionText = Field(min_length=1, max_length=120)
    enabled: StrictBool = False
    interval_seconds: StrictInt = Field(default=21600, ge=3600, le=604800)


class DiscoveryRuleCreate(DiscoveryRuleSettings):
    query: DiscoveryQuery


class DiscoveryRuleEdit(DiscoveryRuleSettings):
    expected_revision: StrictInt = Field(ge=1)
    archived: StrictBool = False


def _key(value):
    if value is None:
        return None
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, {'code': 'invalid_idempotency_key', 'message': '请求标识必须是 UUID'}) from None


def _check_replay(row, fingerprint):
    if row.request_hash != fingerprint:
        raise HTTPException(409, {'code': 'idempotency_payload_mismatch', 'message': '同一请求标识已绑定不同内容'})


def find_rule(db, rule_id, session_id):
    row = db.execute(current_rules().where(RecallDiscoveryRule.id == rule_id,
        RecallDiscoveryRule.session_id == session_id)).first()
    if row is None:
        raise HTTPException(404, '当前会话不存在此名称发现订阅')
    return row


def find_job(db, job_id, session_id):
    job = db.scalar(select(RecallDiscoveryJob).where(RecallDiscoveryJob.id == job_id,
                                                   RecallDiscoveryJob.session_id == session_id))
    if job is None:
        raise HTTPException(404, '当前会话不存在此名称发现任务')
    return job


def revision_view(row):
    return {'revision': row.revision, 'name': row.name, 'enabled': row.enabled, 'archived': row.archived,
            'interval_seconds': row.interval_seconds, 'created_at': timestamp(row.created_at)}


def run_view(row):
    if row is None:
        return None
    complete = row.coverage == 'complete'
    return {'id': row.id, 'job_id': row.job_id, 'attempt_id': row.attempt_id,
        'state': row.state, 'reason': row.reason, 'started_at': timestamp(row.started_at),
        'finished_at': timestamp(row.finished_at), 'previous_complete_id': row.previous_complete_id,
        'coverage': {'status': row.coverage, 'passes_required': 2,
            'passes_completed': len(row.pass_fingerprints), 'pass_fingerprints': deepcopy(row.pass_fingerprints),
            **{key: getattr(row, key) for key in ('page_operations', 'pages_completed', 'products_count',
                'candidates_count', 'new_candidates_count', 'raw_bytes', 'elapsed_seconds')},
            'budget': deepcopy(row.budget), 'baseline_advanced': complete,
            'is_initial_baseline': complete and row.previous_complete_id is None}}


def rule_view(db, rule, revision, *, write_revision=None, replayed=False):
    job = db.get(RecallDiscoveryJob, rule.job_id)
    runs = select(RecallDiscoveryRun).where(RecallDiscoveryRun.job_id == job.id).order_by(
        desc(RecallDiscoveryRun.finished_at), desc(RecallDiscoveryRun.id))
    result = {**revision_view(revision), 'id': rule.id, 'source_id': SOURCE_ID, 'query': deepcopy(job.query),
        'job': {'id': job.id, 'next_due_at': timestamp(job.next_due_at), 'lease_until': timestamp(job.lease_until),
                'last_run': run_view(db.scalar(runs.limit(1)))},
        'baseline': run_view(db.scalar(runs.where(RecallDiscoveryRun.coverage == 'complete').limit(1))),
        'budget': deepcopy(DISCOVERY_BUDGET), 'notice': NOTICE}
    if write_revision is not None:
        result['write_result'] = {'revision_id': write_revision.id, 'revision': write_revision.revision,
                                  'replayed': replayed}
    return result


def candidate_view(row):
    return {'id': row.id, 'campaign_number': row.campaign_number, 'first_seen_run_id': row.first_seen_run_id,
        'first_seen_at': timestamp(row.first_seen_at), 'campaign': deepcopy(row.campaign),
        'evidence': deepcopy(row.evidence), 'applicability': 'not_assessed'}


def page_view(row):
    return {**{key: getattr(row, key) for key in ('id', 'attempt_id', 'pass_number', 'offset', 'query_id',
            'verification_id', 'snapshot_id', 'total', 'count', 'content_fingerprint', 'raw_bytes')},
            'observed_at': timestamp(row.observed_at)}


def _list(items, total, offset, limit):
    return {'scope': 'session', 'items': items, 'total': total, 'offset': offset, 'limit': limit}


def scan_list(db, job_id, session_id, offset, limit):
    find_job(db, job_id, session_id)
    statement = select(RecallDiscoveryRun).where(RecallDiscoveryRun.job_id == job_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(statement.order_by(desc(RecallDiscoveryRun.finished_at), desc(RecallDiscoveryRun.id))
                      .offset(offset).limit(limit)).all()
    return _list([run_view(row) for row in rows], total, offset, limit)


def scan_detail(db, run_id, session_id, offset, limit):
    run = db.scalar(select(RecallDiscoveryRun).join(RecallDiscoveryJob,
        RecallDiscoveryJob.id == RecallDiscoveryRun.job_id).where(RecallDiscoveryRun.id == run_id,
                                                                 RecallDiscoveryJob.session_id == session_id))
    if run is None:
        raise HTTPException(404, '当前会话不存在此名称发现扫描')
    job = find_job(db, run.job_id, session_id)
    statement = select(RecallDiscoveryPage).where(RecallDiscoveryPage.attempt_id == run.attempt_id,
                                                 RecallDiscoveryPage.job_id == job.id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    pages = db.scalars(statement.order_by(RecallDiscoveryPage.pass_number, RecallDiscoveryPage.offset)
                       .offset(offset).limit(limit)).all()
    candidate_statement = select(RecallDiscoveryCandidate).where(RecallDiscoveryCandidate.first_seen_run_id == run.id,
                                                                  RecallDiscoveryCandidate.job_id == job.id)
    candidate_total = db.scalar(select(func.count()).select_from(candidate_statement.subquery())) or 0
    candidates = db.scalars(candidate_statement.order_by(RecallDiscoveryCandidate.campaign_number).limit(100)).all()
    return {**run_view(run), 'scope': 'session', 'source_id': SOURCE_ID, 'query': deepcopy(job.query),
        'pages': [page_view(row) for row in pages], 'pages_total': total, 'page_offset': offset, 'page_limit': limit,
        'candidates': [candidate_view(row) for row in candidates], 'candidates_total': candidate_total,
        'candidates_truncated': candidate_total > len(candidates), 'notice': NOTICE}


def register_recall_discovery_monitor_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post('/v1/recall-discovery-rules', status_code=201)
    def create(payload: DiscoveryRuleCreate, request: Request,
               idempotency_key: str | None = Header(None, alias='Idempotency-Key', max_length=64),
               db: Session = Depends(get_db)):
        key, fingerprint = _key(idempotency_key), digest(payload.model_dump())
        session_id = request.state.session_id
        service = QueryService(db, None)
        service.lock_ingestion()
        existing = db.scalar(select(RecallDiscoveryRule).where(RecallDiscoveryRule.session_id == session_id,
            RecallDiscoveryRule.idempotency_key == key)) if key else None
        if existing:
            _check_replay(existing, fingerprint)
            rule, current = find_rule(db, existing.id, session_id)
            written = db.scalar(select(RecallDiscoveryRuleRevision).where(RecallDiscoveryRuleRevision.rule_id == rule.id,
                                                                         RecallDiscoveryRuleRevision.revision == 1))
            return rule_view(db, rule, current, write_revision=written, replayed=True)
        query = payload.query.model_dump()
        query_key = digest(query)
        job = db.scalar(select(RecallDiscoveryJob).where(RecallDiscoveryJob.session_id == session_id,
                                                         RecallDiscoveryJob.query_key == query_key))
        if job is None:
            job = RecallDiscoveryJob(id=uid(), session_id=session_id, source_id=SOURCE_ID, query=query, query_key=query_key)
            db.add(job)
            db.flush()
        rule = RecallDiscoveryRule(session_id=session_id, job_id=job.id, idempotency_key=key, request_hash=fingerprint)
        db.add(rule)
        db.flush()
        revision = RecallDiscoveryRuleRevision(rule_id=rule.id, revision=1, archived=False,
                                               **payload.model_dump(exclude={'query'}))
        db.add(revision)
        db.flush()
        # Retain any in-flight source reservation until its Worker returns.
        reschedule(db, job)
        service.audit(session_id, 'recall_discovery_rule_created', rule_id=rule.id, revision=1)
        db.commit()
        return rule_view(db, rule, revision, write_revision=revision)

    @app.get('/v1/recall-discovery-rules')
    def listing(request: Request, archived: bool = False, offset: int = Query(0, ge=0, le=100000),
                limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
        from .auth import session_scope
        statement = current_rules().where(RecallDiscoveryRule.session_id.in_(session_scope(db, request.state.session_id)),
                                          RecallDiscoveryRuleRevision.archived == archived)
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.execute(statement.order_by(desc(RecallDiscoveryRule.created_at), RecallDiscoveryRule.id)
                          .offset(offset).limit(limit)).all()
        return _list([rule_view(db, *row) for row in rows], total, offset, limit)

    @app.get('/v1/recall-discovery-rules/{rule_id}')
    def detail(rule_id: str, request: Request, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        rule, revision = find_rule(db, rule_id, request.state.session_id)
        rows = db.scalars(select(RecallDiscoveryRuleRevision).where(RecallDiscoveryRuleRevision.rule_id == rule.id)
                          .order_by(desc(RecallDiscoveryRuleRevision.revision)).limit(51)).all()
        return {**rule_view(db, rule, revision), 'history': [revision_view(row) for row in rows[:50]],
                'history_truncated': len(rows) > 50}

    @app.post('/v1/recall-discovery-rules/{rule_id}/revisions', status_code=201)
    def revise(rule_id: str, payload: DiscoveryRuleEdit, request: Request,
               idempotency_key: str | None = Header(None, alias='Idempotency-Key', max_length=64),
               db: Session = Depends(get_db)):
        key, fingerprint = _key(idempotency_key), digest(payload.model_dump())
        service = QueryService(db, None)
        service.lock_ingestion()
        rule, current = find_rule(db, rule_id, request.state.session_id)
        written = db.scalar(select(RecallDiscoveryRuleRevision).where(RecallDiscoveryRuleRevision.rule_id == rule.id,
            RecallDiscoveryRuleRevision.idempotency_key == key)) if key else None
        if written:
            _check_replay(written, fingerprint)
            return rule_view(db, rule, current, write_revision=written, replayed=True)
        if current.revision != payload.expected_revision:
            raise HTTPException(409, {'code': 'rule_revision_conflict', 'message': '订阅已更新，请读取最新修订后重试'})
        settings = payload.model_dump(exclude={'expected_revision'})
        if settings['archived']:
            settings['enabled'] = False
        revision = RecallDiscoveryRuleRevision(rule_id=rule.id, revision=current.revision + 1,
            idempotency_key=key, request_hash=fingerprint, **settings)
        db.add(revision)
        db.flush()
        reschedule(db, db.get(RecallDiscoveryJob, rule.job_id))
        service.audit(request.state.session_id, 'recall_discovery_rule_revised', rule_id=rule.id, revision=revision.revision)
        db.commit()
        return rule_view(db, rule, revision, write_revision=revision)

    @app.get('/v1/recall-discovery-runs')
    def runs(request: Request, job_id: str = Query(..., max_length=64), mode: Literal['history'] = Query(...),
             offset: int = Query(0, ge=0, le=100000), limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
        return scan_list(db, job_id, request.state.session_id, offset, limit)

    @app.get('/v1/recall-discovery-jobs/{job_id}/scans')
    def scans(job_id: str, request: Request, mode: Literal['history'] = Query(...),
              offset: int = Query(0, ge=0, le=100000), limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
        return scan_list(db, job_id, request.state.session_id, offset, limit)

    @app.get('/v1/recall-discovery-runs/{run_id}')
    def run_detail(run_id: str, request: Request, mode: Literal['history'] = Query(...),
                   page_offset: int = Query(0, ge=0, le=100000), page_limit: int = Query(20, ge=1, le=100),
                   db: Session = Depends(get_db)):
        return scan_detail(db, run_id, request.state.session_id, page_offset, page_limit)

    @app.get('/v1/recall-discovery-scans/{run_id}')
    def scan(run_id: str, request: Request, mode: Literal['history'] = Query(...),
             offset: int = Query(0, ge=0, le=100000), limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
        return scan_detail(db, run_id, request.state.session_id, offset, limit)

    @app.get('/v1/recall-discovery-notifications')
    def notifications(request: Request, unread_only: bool = False, offset: int = Query(0, ge=0, le=100000),
                      limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
        from .auth import session_scope
        scope = session_scope(db, request.state.session_id)
        statement = (select(RecallDiscoveryNotification, RecallDiscoveryRuleRevision,
                            RecallDiscoveryCandidate, RecallDiscoveryJob)
            .join(RecallDiscoveryRuleRevision, RecallDiscoveryRuleRevision.id == RecallDiscoveryNotification.rule_revision_id)
            .join(RecallDiscoveryCandidate, RecallDiscoveryCandidate.id == RecallDiscoveryNotification.candidate_id)
            .join(RecallDiscoveryJob, RecallDiscoveryJob.id == RecallDiscoveryCandidate.job_id)
            .where(RecallDiscoveryNotification.session_id.in_(scope),
                   RecallDiscoveryJob.session_id.in_(scope)))
        if unread_only:
            statement = statement.where(RecallDiscoveryNotification.read_at.is_(None))
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.execute(statement.order_by(desc(RecallDiscoveryNotification.delivered_at), RecallDiscoveryNotification.id)
                          .offset(offset).limit(limit)).all()
        items = [{'id': row.id, 'rule_id': row.rule_id, 'rule_name': revision.name, 'rule_revision': revision.revision,
            'job_id': job.id, 'query': deepcopy(job.query), 'candidate': candidate_view(candidate),
            'delivered_at': timestamp(row.delivered_at), 'read_at': timestamp(row.read_at),
            'kind': 'candidate_first_observed'} for row, revision, candidate, job in rows]
        return _list(items, total, offset, limit)

    @app.post('/v1/recall-discovery-notifications/{notification_id}/read')
    def mark(notification_id: str, payload: ReadState, request: Request, db: Session = Depends(get_db)):
        service = QueryService(db, None)
        service.lock_ingestion()
        row = db.scalar(select(RecallDiscoveryNotification).where(RecallDiscoveryNotification.id == notification_id,
            RecallDiscoveryNotification.session_id == request.state.session_id))
        if row is None:
            raise HTTPException(404, '当前会话不存在此候选提醒')
        row.read_at = utcnow() if payload.read else None
        service.audit(request.state.session_id, 'recall_discovery_notification_read_changed', notification_id=row.id, read=payload.read)
        db.commit()
        return {'id': row.id, 'read_at': timestamp(row.read_at)}
