"""Persistent monitor receipts and bounded, read-only reconnectable event streams.

All writer helpers require the existing ingestion lock and never commit. Reader
sessions are short lived; neither a page request nor a stream drives the Worker.
"""
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
import time
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, case, desc, exists, func, literal, or_, select, union_all

from .db import AlertRule, MonitorJob, MonitorRun, uid, utc, utcnow
from .monitor_task_models import (MonitorTaskAttempt, MonitorTaskEvent,
                                 RecallDiscoveryTaskAttempt, RecallDiscoveryTaskEvent)
from .recall_models import RecallMonitorJob, RecallMonitorRule, RecallMonitorRun, SOURCE_ID
from .recall_discovery_monitor_models import RecallDiscoveryJob, RecallDiscoveryRule, RecallDiscoveryRun
from .service import timestamp

SCHEMA = 'monitor-tasks@1'
MAX_SEQUENCE = 9007199254740991
STREAM_SECONDS = 25.0
HEARTBEAT_SECONDS = 10.0
POLL_SECONDS = 1.0
MAX_STREAM_EVENTS = 500
Kind = Literal['tire', 'recall', 'recall_discovery']
TaskState = Literal['never_run', 'running', 'succeeded', 'failed', 'blocked', 'interrupted', 'result_unknown']
BLOCKED_REASONS = {'source_paused', 'source_archived', 'source_access_changed', 'source_access_pin_missing'}
SAFE_REASONS = BLOCKED_REASONS | {
    'lease_expired', 'lease_lost', 'monitor_lease_lost', 'recall_monitor_lease_lost',
    'monitor_rule_disabled', 'recall_monitor_rule_disabled', 'monitor_execution_failed',
    'recall_monitor_execution_failed', 'task_execution_failed', 'source_unavailable',
    'source_timeout', 'upstream_timeout', 'disabled', 'configuration_required',
    'parser_unavailable', 'parser_failed', 'parser_timeout', 'parser_identity_changed',
    'quality_quarantined', 'identity_contract_changed', 'worker_cancelled',
    'monitor_attempt_not_running',
    'discovery_incomplete', 'discovery_scope_budget_exceeded', 'discovery_page_budget_exceeded',
    'discovery_raw_budget_exceeded', 'discovery_time_budget_exceeded', 'discovery_page_failed',
    'discovery_pagination_changed', 'discovery_content_changed', 'discovery_parser_changed',
    'recall_discovery_execution_failed', 'recall_discovery_lease_lost', 'recall_discovery_rule_disabled',
    'recall_monitor_rule_changed', 'recall_discovery_rule_changed',
}
RESULT_STATES = {'live', 'live_verified_304', 'source_unavailable', 'worker_error',
                 'lease_lost', 'consent_required', 'local_snapshot', 'discovery_complete', 'discovery_incomplete'}


def _safe_reason(value):
    if value is None:
        return None
    return value if isinstance(value, str) and value in SAFE_REASONS else 'task_execution_failed'


def _result_state(value):
    return value if isinstance(value, str) and value in RESULT_STATES else 'worker_error'


def _models(kind):
    if kind == 'tire':
        return MonitorJob, MonitorRun
    if kind == 'recall':
        return RecallMonitorJob, RecallMonitorRun
    if kind == 'recall_discovery':
        return RecallDiscoveryJob, RecallDiscoveryRun
    raise ValueError('invalid_monitor_task_kind')


def journal_models(kind):
    """Select additive journals while sharing every lifecycle and cursor helper."""
    if kind in {'tire', 'recall'}:
        return MonitorTaskAttempt, MonitorTaskEvent
    if kind == 'recall_discovery':
        return RecallDiscoveryTaskAttempt, RecallDiscoveryTaskEvent
    raise ValueError('invalid_monitor_task_kind')


def _token_hash(token):
    if not isinstance(token, str) or not token or len(token) > 64:
        raise ValueError('invalid_monitor_task_lease')
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _latest_event(db, kind, job_id):
    _, event_model = journal_models(kind)
    return db.scalar(select(event_model).where(event_model.kind == kind,
        event_model.job_id == job_id).order_by(desc(event_model.sequence)).limit(1))


def _attempt_event(db, attempt):
    _, event_model = journal_models(attempt.kind)
    return db.scalar(select(event_model).where(event_model.attempt_id == attempt.id)
        .order_by(desc(event_model.sequence)).limit(1))


def _append_event(db, attempt, phase, state, *, result_state=None, reason=None,
                  query_id=None, run_id=None, now=None):
    last = _latest_event(db, attempt.kind, attempt.job_id)
    sequence = last.sequence + 1 if last else 1
    if sequence > MAX_SEQUENCE:
        raise ValueError('monitor_task_sequence_exhausted')
    _, event_model = journal_models(attempt.kind)
    row = event_model(id=uid(), attempt_id=attempt.id, kind=attempt.kind,
        job_id=attempt.job_id, sequence=sequence, phase=phase, state=state,
        result_state=result_state, reason=_safe_reason(reason), query_id=query_id,
        run_id=run_id, created_at=now or utcnow())
    db.add(row)
    db.flush()
    return row


def _claim_attempt(db, claim):
    attempt_id = claim.get('attempt_id')
    if not isinstance(attempt_id, str):
        return None
    attempt_model, _ = journal_models(claim.get('kind'))
    row = db.get(attempt_model, attempt_id)
    if (row is None or row.kind != claim.get('kind') or row.job_id != claim.get('id')
            or row.lease_token_hash != _token_hash(claim.get('token'))):
        return None
    return row


def _lease_valid(job, attempt, now):
    return bool(job is not None and job.lease_token and job.lease_until
        and utc(job.lease_until) > utc(now) and _token_hash(job.lease_token) == attempt.lease_token_hash)


def start_attempt_locked(db, kind, claim):
    """Called after assigning the lease, before the claim transaction commits."""
    job_model, _ = _models(kind)
    attempt_model, _ = journal_models(kind)
    claim['kind'] = kind
    now = claim['started_at']
    if type(claim.get('source_access_generation')) is not int or claim['source_access_generation'] < 0:
        raise ValueError('invalid_monitor_task_generation')
    job = db.get(job_model, claim['id'])
    token_hash = _token_hash(claim['token'])
    if (job is None or job.lease_token != claim['token'] or job.lease_until is None
            or utc(job.lease_until) <= utc(now)):
        raise ValueError('monitor_task_claim_not_owned')
    previous = db.scalar(select(attempt_model).where(attempt_model.kind == kind,
        attempt_model.job_id == job.id, attempt_model.lease_token_hash == token_hash))
    if previous:
        return previous.id
    attempt = attempt_model(id=uid(), kind=kind, job_id=job.id,
        source_id=claim['source_id'], query=deepcopy(claim['query']), lease_token_hash=token_hash,
        source_access_generation=claim.get('source_access_generation'), started_at=now)
    db.add(attempt)
    db.flush()
    _append_event(db, attempt, 'claimed', 'running', now=now)
    return attempt.id


def mark_running_locked(db, claim, *, now=None):
    now = now or utcnow()
    attempt = _claim_attempt(db, claim)
    if attempt is None:
        return False
    job_model, _ = _models(attempt.kind)
    job = db.get(job_model, attempt.job_id, populate_existing=True)
    last = _attempt_event(db, attempt)
    if not last or last.phase != 'claimed' or not _lease_valid(job, attempt, now):
        return False
    _append_event(db, attempt, 'running', 'running', now=now)
    return True


def finish_attempt_locked(db, claim, state, reason=None, *, query_id=None, run_id=None, finished_at=None):
    now = finished_at or utcnow()
    attempt = _claim_attempt(db, claim)
    if attempt is None:
        return False
    last = _attempt_event(db, attempt)
    if not last or last.phase == 'finished':
        return False
    job_model, run_model = _models(attempt.kind)
    job = db.get(job_model, attempt.job_id)
    # The caller may already have cleared the lease in this same transaction.
    # A matching immutable run is therefore also an explicit fencing receipt.
    receipt = db.get(run_model, run_id) if run_id else None
    matched_receipt = bool(receipt and receipt.job_id == attempt.job_id
        and _token_hash(receipt.lease_token) == attempt.lease_token_hash
        and receipt.state == state and receipt.reason == reason)
    if not matched_receipt and not _lease_valid(job, attempt, now):
        return False
    if run_id and not matched_receipt:
        raise ValueError('monitor_task_run_mismatch')
    result = _result_state(state)
    outcome = ('blocked' if reason in BLOCKED_REASONS else
               'succeeded' if result in {'live', 'live_verified_304', 'discovery_complete'} else 'failed')
    _append_event(db, attempt, 'finished', outcome, result_state=result, reason=reason,
        query_id=query_id, run_id=run_id, now=now)
    return True


def interrupt_attempt_locked(db, claim, reason, *, now=None, run_id=None):
    attempt = _claim_attempt(db, claim)
    if attempt is None:
        return False
    last = _attempt_event(db, attempt)
    if not last or last.phase == 'finished':
        return False
    if run_id:
        _, run_model = _models(attempt.kind)
        receipt = db.get(run_model, run_id)
        if (receipt is None or receipt.job_id != attempt.job_id
                or _token_hash(receipt.lease_token) != attempt.lease_token_hash):
            raise ValueError('monitor_task_run_mismatch')
    _append_event(db, attempt, 'finished', 'interrupted', result_state='lease_lost', reason=reason,
                  run_id=run_id, now=now)
    return True


def expire_attempts_locked(db, kind, *, now=None):
    """Run before eligibility filters, so paused sources cannot strand attempts."""
    now = now or utcnow()
    job_model, _ = _models(kind)
    attempt_model, event_model = journal_models(kind)
    finished = select(event_model.attempt_id).where(event_model.phase == 'finished')
    attempts = db.scalars(select(attempt_model).where(attempt_model.kind == kind,
        ~attempt_model.id.in_(finished)).order_by(attempt_model.started_at)).all()
    count = 0
    for attempt in attempts:
        job = db.get(job_model, attempt.job_id, populate_existing=True)
        if not _lease_valid(job, attempt, now):
            reason = ('lease_expired' if job and job.lease_until and utc(job.lease_until) <= utc(now)
                      else 'lease_lost')
            _append_event(db, attempt, 'finished', 'interrupted', result_state='lease_lost', reason=reason, now=now)
            count += 1
    return count


def _cursor(kind, job_id, row=None):
    value = [1, kind, job_id, row.sequence if row else 0, row.id if row else None]
    return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')


def _reset():
    raise HTTPException(409, {'code': 'task_cursor_reset_required',
                             'message': '执行事件游标已失效，请重新读取任务详情。'})


def _anchor(db, kind, job_id, cursor):
    _, event_model = journal_models(kind)
    if cursor is None:
        return 0
    try:
        if not isinstance(cursor, str) or not cursor or len(cursor) > 512:
            _reset()
        value = json.loads(base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True))
        if (not isinstance(value, list) or len(value) != 5 or type(value[0]) is not int
                or value[:3] != [1, kind, job_id]
                or type(value[3]) is not int or not 0 <= value[3] <= MAX_SEQUENCE):
            _reset()
        sequence, event_id = value[3:]
        if sequence == 0:
            if event_id is not None:
                _reset()
            return 0
        if not isinstance(event_id, str) or len(event_id) > 64:
            _reset()
        row = db.scalar(select(event_model.id).where(event_model.kind == kind,
            event_model.job_id == job_id, event_model.sequence == sequence,
            event_model.id == event_id))
        if row is None:
            _reset()
        return sequence
    except (ValueError, TypeError, UnicodeError):
        _reset()


def _visible_job(db, kind, job_id, scope):
    job_model, _ = _models(kind)
    statement = select(job_model).where(job_model.id == job_id)
    if kind in {'recall', 'recall_discovery'}:
        rule_model = RecallMonitorRule if kind == 'recall' else RecallDiscoveryRule
        statement = statement.where(job_model.session_id.in_(scope),
            exists(select(rule_model.id).where(rule_model.job_id == job_model.id,
                                               rule_model.session_id.in_(scope))))
    else:
        statement = statement.where(exists(select(AlertRule.id).where(AlertRule.job_id == job_model.id)))
    job = db.scalar(statement)
    if job is None:
        raise HTTPException(404, '未找到可读取的监控任务')
    return job


def _event_view(row):
    return {'id': row.id, 'sequence': row.sequence, 'cursor': _cursor(row.kind, row.job_id, row),
        'attempt_id': row.attempt_id, 'phase': row.phase, 'state': row.state,
        'result_state': row.result_state, 'reason': _safe_reason(row.reason), 'query_id': row.query_id,
        'run_id': row.run_id, 'created_at': timestamp(row.created_at)}


def _attempt_view(db, row):
    last = _attempt_event(db, row)
    return {'id': row.id, 'started_at': timestamp(row.started_at),
        'finished_at': timestamp(last.created_at) if last and last.phase == 'finished' else None,
        'last_event_at': timestamp(last.created_at) if last else None,
        'phase': last.phase if last else 'claimed', 'state': last.state if last else 'running',
        'terminal': bool(last and last.phase == 'finished'), 'result_state': last.result_state if last else None,
        'reason': _safe_reason(last.reason) if last else None, 'query_id': last.query_id if last else None,
        'source_access_generation': row.source_access_generation}


def _rules(db, kind, job_id, scope):
    if kind == 'tire':
        from .monitoring import current_rules
        statement = current_rules(db, job_id)
        rule_model = AlertRule
    elif kind == 'recall':
        from .recall_monitoring import current_rules
        statement = current_rules().where(RecallMonitorRule.job_id == job_id,
                                          RecallMonitorRule.session_id.in_(scope))
        rule_model = RecallMonitorRule
    else:
        from .recall_discovery_monitoring import current_rules
        statement = current_rules().where(RecallDiscoveryRule.job_id == job_id,
                                          RecallDiscoveryRule.session_id.in_(scope))
        rule_model = RecallDiscoveryRule
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.execute(statement.order_by(rule_model.id).limit(50)).all()
    return ([{'id': rule.id, 'name': revision.name, 'revision': revision.revision,
              'enabled': revision.enabled, 'archived': revision.archived} for rule, revision in rows], total)


def _legacy_view(row):
    return {'id': row.id, 'state': _result_state(row.state), 'reason': _safe_reason(row.reason),
        'started_at': timestamp(row.started_at), 'finished_at': timestamp(row.finished_at), 'legacy': True}


def task_view(db, kind, job, scope, *, now=None):
    now = now or utcnow()
    rules, total = _rules(db, kind, job.id, scope)
    attempt_model, event_model = journal_models(kind)
    event = _latest_event(db, kind, job.id)
    attempt = db.get(attempt_model, event.attempt_id) if event else None
    attempt_view = _attempt_view(db, attempt) if attempt else None
    _, run_model = _models(kind)
    last_run = db.scalar(select(run_model).where(run_model.job_id == job.id)
                         .order_by(desc(run_model.finished_at), desc(run_model.id)).limit(1))
    linked = bool(last_run and db.scalar(select(event_model.id).where(
        event_model.kind == kind, event_model.job_id == job.id,
        event_model.run_id == last_run.id).limit(1)))
    legacy = _legacy_view(last_run) if last_run and not linked else None
    state, terminal = 'never_run', False
    if attempt_view:
        state, terminal = attempt_view['state'], attempt_view['terminal']
        if not terminal and not _lease_valid(job, attempt, now):
            state = 'result_unknown'
    elif job.lease_token:
        state = 'result_unknown'
    elif legacy:
        state, terminal = ('succeeded' if legacy['state'] in {'live', 'live_verified_304', 'discovery_complete'} else 'failed'), True
    return {'kind': kind, 'job_id': job.id, 'scope': 'local_workspace' if kind == 'tire' else 'session',
        'source_id': job.source_id if kind == 'tire' else SOURCE_ID,
        'query': {'campaign_number': job.campaign_number} if kind == 'recall' else deepcopy(job.query),
        'rules': rules, 'rule_count': total, 'rules_truncated': total > len(rules),
        'next_due_at': timestamp(job.next_due_at), 'lease_until': timestamp(job.lease_until),
        'state': state, 'terminal': terminal, 'phase': event.phase if event else None,
        'last_event_at': timestamp(event.created_at) if event else None,
        'last_attempt': attempt_view, 'last_run': legacy}


def _state_expression(db, kind, job_model, run_model, now):
    attempt_model, event_model = journal_models(kind)
    last_state = select(event_model.state).where(event_model.kind == kind,
        event_model.job_id == job_model.id).order_by(desc(event_model.sequence)).limit(1).scalar_subquery()
    last_result = select(run_model.state).where(run_model.job_id == job_model.id).order_by(
        desc(run_model.finished_at), desc(run_model.id)).limit(1).scalar_subquery()
    last_lease_hash = select(attempt_model.lease_token_hash).join(event_model,
        event_model.attempt_id == attempt_model.id).where(event_model.kind == kind,
        event_model.job_id == job_model.id).order_by(desc(event_model.sequence)).limit(1).scalar_subquery()
    if db.get_bind().dialect.name == 'postgresql':
        # sha256(bytea) is a PostgreSQL built-in; no pgcrypto extension is needed.
        current_lease_hash = func.encode(func.sha256(func.convert_to(job_model.lease_token, 'UTF8')), 'hex')
    else:
        current_lease_hash = func.tire_monitor_lease_hash(job_model.lease_token)
    return case((and_(last_state == 'running', or_(job_model.lease_token.is_(None),
        job_model.lease_until.is_(None), job_model.lease_until <= now,
        current_lease_hash != last_lease_hash)), 'result_unknown'),
        (last_state.is_not(None), last_state), (job_model.lease_token.is_not(None), 'result_unknown'),
        (last_result.in_(['live', 'live_verified_304', 'discovery_complete']), 'succeeded'),
        (last_result.is_not(None), 'failed'), else_='never_run')


def task_list(db, scope, *, kind=None, source_id=None, rule_id=None, state=None, offset=0, limit=20):
    now = utcnow()
    statements = []
    for lane in ([kind] if kind else ['tire', 'recall', 'recall_discovery']):
        job_model, run_model = _models(lane)
        rule_model = {'tire': AlertRule, 'recall': RecallMonitorRule, 'recall_discovery': RecallDiscoveryRule}[lane]
        rule_clause = select(rule_model.id).where(rule_model.job_id == job_model.id)
        if rule_id:
            rule_clause = rule_clause.where(rule_model.id == rule_id)
        if lane != 'tire':
            rule_clause = rule_clause.where(rule_model.session_id.in_(scope))
        statement = select(literal(lane).label('kind'), job_model.id.label('job_id')).where(exists(rule_clause))
        if lane != 'tire':
            statement = statement.where(job_model.session_id.in_(scope))
            if source_id and source_id != SOURCE_ID:
                statement = statement.where(literal(False))
        elif source_id:
            statement = statement.where(job_model.source_id == source_id)
        if state:
            statement = statement.where(_state_expression(db, lane, job_model, run_model, now) == state)
        statements.append(statement)
    candidates = union_all(*statements).subquery()
    total = db.scalar(select(func.count()).select_from(candidates)) or 0
    rows = db.execute(select(candidates).order_by(candidates.c.kind, candidates.c.job_id).offset(offset).limit(limit)).all()
    items = [task_view(db, lane, _visible_job(db, lane, job_id, scope), scope, now=now)
             for lane, job_id in rows]
    return {'schema': SCHEMA, 'items': items, 'total': total, 'offset': offset, 'limit': limit,
            'server_time': timestamp(now)}


def task_detail(db, kind, job_id, scope, *, attempt_offset=0, attempt_limit=20,
                legacy_offset=0, legacy_limit=20):
    job = _visible_job(db, kind, job_id, scope)
    attempt_model, event_model = journal_models(kind)
    # Capture the stream watermark BEFORE reading projections. The client may
    # see newer projection data, but replay from this anchor cannot miss events.
    cursor = _cursor(kind, job_id, _latest_event(db, kind, job_id))
    statement = select(attempt_model).where(attempt_model.kind == kind,
                                            attempt_model.job_id == job_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(statement.order_by(desc(attempt_model.started_at), desc(attempt_model.id))
                      .offset(attempt_offset).limit(attempt_limit)).all()
    _, run_model = _models(kind)
    linked = exists(select(event_model.id).where(event_model.kind == kind,
        event_model.job_id == job_id, event_model.run_id == run_model.id))
    legacy_statement = select(run_model).where(run_model.job_id == job_id, ~linked)
    legacy_total = db.scalar(select(func.count()).select_from(legacy_statement.subquery())) or 0
    legacy_rows = db.scalars(legacy_statement.order_by(desc(run_model.finished_at), desc(run_model.id))
                            .offset(legacy_offset).limit(legacy_limit)).all()
    return {'schema': SCHEMA, 'task': task_view(db, kind, job, scope),
        'attempts': [_attempt_view(db, row) for row in rows], 'attempts_total': total,
        'attempt_offset': attempt_offset, 'attempt_limit': attempt_limit, 'cursor': cursor,
        'legacy_runs': [_legacy_view(row) for row in legacy_rows], 'legacy_runs_total': legacy_total,
        'legacy_offset': legacy_offset, 'legacy_limit': legacy_limit,
        'server_time': timestamp(utcnow())}


def event_page(db, kind, job_id, scope, *, cursor=None, limit=50):
    _, event_model = journal_models(kind)
    _visible_job(db, kind, job_id, scope)
    sequence = _anchor(db, kind, job_id, cursor)
    latest = _latest_event(db, kind, job_id)
    upper = latest.sequence if latest else 0
    rows = db.scalars(select(event_model).where(event_model.kind == kind,
        event_model.job_id == job_id, event_model.sequence > sequence,
        event_model.sequence <= upper).order_by(event_model.sequence).limit(limit + 1)).all()
    selected = rows[:limit]
    return {'schema': SCHEMA, 'kind': kind, 'job_id': job_id, 'items': [_event_view(row) for row in selected],
        'next_cursor': _cursor(kind, job_id, selected[-1]) if selected else cursor or _cursor(kind, job_id),
        'latest_cursor': _cursor(kind, job_id, latest), 'has_more': len(rows) > limit,
        'server_time': timestamp(utcnow())}


def _frame(event, data, cursor=None):
    return (f'id: {cursor}\n' if cursor else '') + f'event: {event}\ndata: ' + json.dumps(
        data, ensure_ascii=False, separators=(',', ':')) + '\n\n'


async def stream_events(database, request, kind, job_id, scope, cursor):
    started = heartbeat = time.monotonic()
    delivered = 0
    while time.monotonic() - started < STREAM_SECONDS and delivered < MAX_STREAM_EVENTS:
        if await request.is_disconnected():
            return

        def read_page():
            with database.sessions() as db:
                return event_page(db, kind, job_id, scope, cursor=cursor, limit=100)

        try:
            page = await asyncio.to_thread(read_page)
        except HTTPException as error:
            if error.status_code in (404, 409):
                yield _frame('reset', {'code': 'task_cursor_reset_required', 'server_time': timestamp(utcnow())})
                return
            raise
        for row in page['items']:
            cursor = row['cursor']
            delivered += 1
            yield _frame('task_event', row, cursor)
            if delivered >= MAX_STREAM_EVENTS:
                break
        if time.monotonic() - heartbeat >= HEARTBEAT_SECONDS:
            yield _frame('heartbeat', {'cursor': cursor, 'server_time': timestamp(utcnow())})
            heartbeat = time.monotonic()
        if not page['has_more']:
            await asyncio.sleep(min(POLL_SECONDS, max(0, STREAM_SECONDS - (time.monotonic() - started))))
    yield _frame('stream_end', {'cursor': cursor, 'server_time': timestamp(utcnow()), 'reason': 'window_complete'})


def register_monitor_task_routes(app: FastAPI):
    @app.get('/v1/monitor-tasks')
    def listing(request: Request, kind: Kind | None = None,
                source_id: str | None = Query(None, max_length=80), rule_id: str | None = Query(None, max_length=64),
                state: TaskState | None = None, offset: int = Query(0, ge=0, le=100000),
                limit: int = Query(20, ge=1, le=50)):
        with app.state.database.sessions() as db:
            from .auth import session_scope
            return task_list(db, session_scope(db, request.state.session_id), kind=kind, source_id=source_id,
                             rule_id=rule_id, state=state, offset=offset, limit=limit)

    @app.get('/v1/monitor-tasks/{kind}/{job_id}')
    def detail(kind: Kind, job_id: str, request: Request,
               attempt_offset: int = Query(0, ge=0, le=100000), attempt_limit: int = Query(20, ge=1, le=100),
               legacy_offset: int = Query(0, ge=0, le=100000), legacy_limit: int = Query(20, ge=1, le=100)):
        with app.state.database.sessions() as db:
            from .auth import session_scope
            return task_detail(db, kind, job_id, session_scope(db, request.state.session_id),
                attempt_offset=attempt_offset, attempt_limit=attempt_limit,
                legacy_offset=legacy_offset, legacy_limit=legacy_limit)

    @app.get('/v1/monitor-tasks/{kind}/{job_id}/events')
    def events(kind: Kind, job_id: str, request: Request, cursor: str | None = Query(None, max_length=512),
               limit: int = Query(50, ge=1, le=100)):
        with app.state.database.sessions() as db:
            from .auth import session_scope
            return event_page(db, kind, job_id, session_scope(db, request.state.session_id), cursor=cursor, limit=limit)

    @app.get('/v1/monitor-tasks/{kind}/{job_id}/events/stream')
    def stream(kind: Kind, job_id: str, request: Request, cursor: str | None = Query(None, max_length=512),
               last_event_id: str | None = Header(None, alias='Last-Event-ID', max_length=512)):
        with app.state.database.sessions() as db:
            from .auth import session_scope
            scope = session_scope(db, request.state.session_id)
            _visible_job(db, kind, job_id, scope)
            if cursor is not None and last_event_id is not None and cursor != last_event_id:
                _reset()
            cursor = last_event_id or cursor
            event_page(db, kind, job_id, scope, cursor=cursor, limit=1)
            cursor = cursor or _cursor(kind, job_id)
        return StreamingResponse(stream_events(app.state.database, request, kind, job_id,
            scope, cursor), media_type='text/event-stream', headers={
                'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no', 'X-Content-Type-Options': 'nosniff'})
