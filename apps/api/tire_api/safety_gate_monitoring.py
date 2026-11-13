"""Rolling official weekly checks with shared leases and evidence-bound notifications."""
import asyncio
from copy import deepcopy
from datetime import timedelta

from sqlalchemy import func, select

from .adapters import safety_gate as source
from .db import QueryRun, uid, utc, utcnow
from .monitoring import LeaseLost
from .safety_gate import SafetyGateRequest, SafetyGateService, SafetyGateSnapshot, SafetyGateVerification, checked_snapshot
from .safety_gate_alerts import AlertChange, AlertObservation, AlertRevision, observation_json
from .safety_gate_monitor_models import (SafetyGateMonitorJob, SafetyGateMonitorRule, SafetyGateRuleRevision,
    SafetyGateMonitorCheck, SafetyGateMonitorRun, SafetyGateNotification)
from .service import QueryService
from .source_settings import SourceAccessBlocked, assert_source_access

LEASE_SECONDS = 600
MAX_SECONDS = 300
SOURCE_INTERVAL = 2.1
SUCCESS_STATES = {'live', 'live_verified_304'}


def current_rules():
    latest = (select(SafetyGateRuleRevision.rule_id, func.max(SafetyGateRuleRevision.revision).label('revision'))
        .group_by(SafetyGateRuleRevision.rule_id).subquery())
    return (select(SafetyGateMonitorRule, SafetyGateRuleRevision)
        .join(SafetyGateRuleRevision, SafetyGateRuleRevision.rule_id == SafetyGateMonitorRule.id)
        .join(latest, (latest.c.rule_id == SafetyGateMonitorRule.id)
              & (latest.c.revision == SafetyGateRuleRevision.revision)))


def active_rules():
    return current_rules().where(SafetyGateRuleRevision.enabled.is_(True), SafetyGateRuleRevision.archived.is_(False))


def reschedule(db, job):
    rows = db.execute(active_rules().where(SafetyGateMonitorRule.job_id == job.id)).all()
    interval = min((revision.interval_seconds for _, revision in rows), default=None)
    if interval is not None:
        job.next_due_at = utc(job.last_finished_at) + timedelta(seconds=interval) if job.last_finished_at else utcnow()


def guard_claim(db, claim):
    job = db.get(SafetyGateMonitorJob, claim['id'], populate_existing=True)
    if (job is None or job.lease_token != claim['token'] or job.lease_until is None or utc(job.lease_until) <= utcnow()):
        raise LeaseLost('safety_gate_monitor_lease_lost')
    generation = claim.get('source_access_generation')
    if type(generation) is not int:
        raise SourceAccessBlocked('source_access_pin_missing')
    assert_source_access(db, source.SOURCE_ID, generation)
    revisions = sorted(row.id for _, row in db.execute(active_rules().where(SafetyGateMonitorRule.job_id == job.id)))
    if not revisions:
        raise LeaseLost('safety_gate_monitor_rule_disabled')
    if revisions != claim['rule_revision_ids']:
        raise LeaseLost('safety_gate_monitor_rule_changed')


def claim_job(database, now=None):
    from .monitor_tasks import expire_attempts_locked, start_attempt_locked
    now = now or utcnow()
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        expire_attempts_locked(db, 'safety_gate', now=now)
        try:
            generation = assert_source_access(db, source.SOURCE_ID)
        except SourceAccessBlocked:
            db.commit()
            return None
        busy = db.scalar(select(SafetyGateMonitorJob.id).where(SafetyGateMonitorJob.lease_until > now).limit(1))
        last = db.scalar(select(func.max(SafetyGateMonitorRun.finished_at)))
        if busy or last and utc(last) + timedelta(seconds=SOURCE_INTERVAL) > now:
            db.commit()
            return None
        eligible = active_rules().with_only_columns(SafetyGateMonitorRule.job_id)
        job = db.scalar(select(SafetyGateMonitorJob).where(SafetyGateMonitorJob.id.in_(eligible),
            SafetyGateMonitorJob.next_due_at <= now,
            SafetyGateMonitorJob.lease_until.is_(None) | (SafetyGateMonitorJob.lease_until <= now))
            .order_by(SafetyGateMonitorJob.next_due_at, SafetyGateMonitorJob.id).limit(1))
        if job is None:
            db.commit()
            return None
        job.lease_token, job.lease_until = uid(), now + timedelta(seconds=LEASE_SECONDS)
        claim = {'id': job.id, 'token': job.lease_token, 'started_at': now, 'session_id': job.session_id,
            'query': deepcopy(job.query), 'source_id': source.SOURCE_ID, 'source_access_generation': generation,
            'queue_lag_seconds': max(0, (now - utc(job.next_due_at)).total_seconds()),
            'rule_revision_ids': sorted(row.id for _, row in db.execute(active_rules().where(SafetyGateMonitorRule.job_id == job.id)))}
        claim['attempt_id'] = start_attempt_locked(db, 'safety_gate', claim)
        db.commit()
        return claim


async def check_query(database, claim, adapter, query, position):
    from .monitor_tasks import _safe_reason
    with database.sessions() as db:
        result = await SafetyGateService(db, adapter, ingestion_guard=lambda session: guard_claim(session, claim)).execute(
            SafetyGateRequest(query=query, fallback_policy='never'), claim['session_id'])
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        guard_claim(db, claim)
        run = db.get(QueryRun, result['query_id'])
        if run is None or run.session_id != claim['session_id'] or run.source_id != source.SOURCE_ID or run.query != query:
            raise ValueError('safety_gate_monitor_query_binding_invalid')
        verification = db.scalar(select(SafetyGateVerification).where(SafetyGateVerification.query_id == run.id))
        snapshot_id = None
        if result['data_state'] in SUCCESS_STATES:
            snapshot = checked_snapshot(db.get(SafetyGateSnapshot, verification.snapshot_id)) if verification else None
            if snapshot is None or snapshot.query != query or snapshot.document != result['document']:
                raise ValueError('safety_gate_monitor_evidence_binding_invalid')
            snapshot_id = snapshot.id
        db.add(SafetyGateMonitorCheck(attempt_id=claim['attempt_id'], position=position, query_id=run.id,
            snapshot_id=snapshot_id, query=deepcopy(query), state=result['data_state'], reason=_safe_reason(result.get('reason'))))
        db.commit()
    return result


async def execute_scan(database, claim, adapter=None):
    adapter = adapter or source
    async with asyncio.timeout(MAX_SECONDS):
        catalog = await check_query(database, claim, adapter, {'operation': 'reports'}, 0)
        if catalog['data_state'] not in SUCCESS_STATES:
            return 'source_unavailable', catalog.get('reason')
        reports = selected_reports(catalog['document'], claim['query']['report_limit'])
        for position, row in enumerate(reports, 1):
            await asyncio.sleep(SOURCE_INTERVAL)
            result = await check_query(database, claim, adapter, {
                'operation': 'report', 'report_id': row['report_id'], 'reference': row['reference']}, position)
            if result['data_state'] not in SUCCESS_STATES:
                return 'source_unavailable', result.get('reason')
        return 'safety_gate_complete', None


def selected_reports(document, limit):
    return sorted(document['reports'],
        key=lambda row: (row['published_date'], row['reference'], row['report_id']), reverse=True)[:limit]


def deliver_notifications(db, claim, run):
    accepted = db.scalars(select(SafetyGateMonitorCheck).where(SafetyGateMonitorCheck.attempt_id == claim['attempt_id'],
        SafetyGateMonitorCheck.position > 0, SafetyGateMonitorCheck.snapshot_id.is_not(None))).all()
    report_ids = [row.query['report_id'] for row in accepted]
    rules = db.execute(active_rules().where(SafetyGateMonitorRule.job_id == claim['id'])).all()
    term = claim['query']['text'].casefold()
    count, snapshots = 0, {}
    for rule, revision in rules:
        sent = select(SafetyGateNotification.id).where(SafetyGateNotification.rule_id == rule.id,
            SafetyGateNotification.event_id == AlertChange.id).exists()
        events = db.execute(select(AlertChange, AlertObservation).join(AlertObservation,
            AlertObservation.id == AlertChange.observation_id).where(AlertObservation.report_id.in_(report_ids),
                AlertChange.observed_at >= revision.created_at, ~sent).order_by(AlertChange.observed_at, AlertChange.id)).all()
        for change, observation in events:
            versions = db.scalars(select(AlertRevision).where(AlertRevision.id.in_(
                change.before_revision_ids + change.after_revision_ids))).all()
            if term and not any(term in str(value or '').casefold() for version in versions for value in version.alert['fields'].values()):
                continue
            observation_json(db, observation, snapshots)
            db.add(SafetyGateNotification(id=uid(), session_id=rule.session_id, rule_id=rule.id,
                rule_revision_id=revision.id, event_id=change.id, run_id=run.id))
            count += 1
    return count


def finish_job(database, claim, state, reason=None, now=None):
    from .monitor_tasks import _safe_reason, finish_attempt_locked, interrupt_attempt_locked
    now = now or utcnow()
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        job = db.get(SafetyGateMonitorJob, claim['id'])
        if job is None or job.lease_token != claim['token'] or job.lease_until is None or utc(job.lease_until) <= now:
            interrupt_attempt_locked(db, claim, 'safety_gate_monitor_lease_lost', now=now)
            db.commit()
            return False
        admitted = False
        try:
            guard_claim(db, claim)
            admitted = state != 'lease_lost'
        except LeaseLost as error:
            state, reason = 'lease_lost', str(error)
        except SourceAccessBlocked as error:
            state, reason = 'source_unavailable', error.code
        checks = db.scalars(select(SafetyGateMonitorCheck).where(SafetyGateMonitorCheck.attempt_id == claim['attempt_id'])
            .order_by(SafetyGateMonitorCheck.position)).all()
        reports = []
        catalog_accepted = bool(checks and checks[0].position == 0 and checks[0].snapshot_id
            and checks[0].query == {'operation': 'reports'} and checks[0].state in SUCCESS_STATES)
        if catalog_accepted:
            catalog = checked_snapshot(db.get(SafetyGateSnapshot, checks[0].snapshot_id))
            reports = selected_reports(catalog.document, claim['query']['report_limit'])
        expected_queries = [{'operation': 'reports'}] + [
            {'operation': 'report', 'report_id': row['report_id'], 'reference': row['reference']} for row in reports]
        complete = catalog_accepted and len(checks) == len(expected_queries) and all(
            check.position == position and check.query == expected_queries[position]
            and check.snapshot_id is not None and check.state in SUCCESS_STATES for position, check in enumerate(checks))
        if state == 'safety_gate_complete' and not complete:
            state, reason = 'source_unavailable', 'safety_gate_monitor_incomplete'
        reason = _safe_reason(reason)
        run = SafetyGateMonitorRun(id=uid(), job_id=job.id, attempt_id=claim['attempt_id'], lease_token=claim['token'],
            state=state, reason=reason, started_at=claim['started_at'], finished_at=now,
            selected_reports=deepcopy(reports))
        db.add(run)
        # Flush the run only after computing its immutable delivery count.
        if admitted:
            with db.no_autoflush:
                run.notification_count = deliver_notifications(db, claim, run)
        db.flush()
        terminal = (interrupt_attempt_locked(db, claim, reason, now=now, run_id=run.id) if state == 'lease_lost' else
            finish_attempt_locked(db, claim, state, reason, finished_at=now, run_id=run.id,
                query_id=checks[-1].query_id if checks else None))
        if not terminal:
            db.rollback()
            return False
        job.last_finished_at, job.lease_token, job.lease_until = now, None, None
        reschedule(db, job)
        QueryService(db, None).audit(claim['session_id'], 'safety_gate_monitor_finished',
            run_id=run.id, attempt_id=claim['attempt_id'], state=state, notifications=run.notification_count)
        db.commit()
        claim['final_result'] = {'state': state, 'reason': reason}
        return True
