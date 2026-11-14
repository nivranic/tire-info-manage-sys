"""Chinese recall scans, renewable leases and immediate evidence-bound notifications."""
import asyncio
from copy import deepcopy
from datetime import timedelta

from sqlalchemy import func, select

from .adapters import samr as source
from .db import QueryRun, uid, utc, utcnow
from .monitoring import LeaseLost
from .samr_recalls import SamrRecallRequest, SamrRecallService, SamrRecallSnapshot, SamrRecallVerification, checked_snapshot
from .samr_notice_history import SamrNoticeChange, SamrNoticeObservation, SamrNoticeRevision, observation_json
from .samr_monitor_models import (SamrMonitorJob, SamrMonitorRule, SamrRuleRevision, SamrMonitorCheck,
    SamrMonitorRun, SamrNotification)
from .service import QueryService
from .source_settings import SourceAccessBlocked, assert_source_access

LEASE_SECONDS = 600
MAX_SECONDS = 21600
SOURCE_INTERVAL = 2.1
SUCCESS_STATES = {'live', 'live_verified_304'}


class ScanChanged(ValueError):
    pass


def current_rules():
    latest = (select(SamrRuleRevision.rule_id, func.max(SamrRuleRevision.revision).label('revision'))
        .group_by(SamrRuleRevision.rule_id).subquery())
    return (select(SamrMonitorRule, SamrRuleRevision)
        .join(SamrRuleRevision, SamrRuleRevision.rule_id == SamrMonitorRule.id)
        .join(latest, (latest.c.rule_id == SamrMonitorRule.id) & (latest.c.revision == SamrRuleRevision.revision)))


def active_rules():
    return current_rules().where(SamrRuleRevision.enabled.is_(True), SamrRuleRevision.archived.is_(False))


def reschedule(db, job):
    rows = db.execute(active_rules().where(SamrMonitorRule.job_id == job.id)).all()
    interval = min((revision.interval_seconds for _, revision in rows), default=None)
    if interval is not None:
        job.next_due_at = utc(job.last_finished_at) + timedelta(seconds=interval) if job.last_finished_at else utcnow()


def guard_claim(db, claim):
    job = db.get(SamrMonitorJob, claim['id'], populate_existing=True)
    if (job is None or job.lease_token != claim['token'] or job.lease_until is None or utc(job.lease_until) <= utcnow()
            or job.session_id != claim['session_id'] or job.query != claim['query'] or job.query_key != source_query_key(claim['query'])):
        raise LeaseLost('samr_monitor_lease_lost')
    generation = claim.get('source_access_generation')
    if type(generation) is not int:
        raise SourceAccessBlocked('source_access_pin_missing')
    assert_source_access(db, source.SOURCE_ID, generation)
    revisions = sorted(row.id for _, row in db.execute(active_rules().where(SamrMonitorRule.job_id == job.id)))
    if not revisions:
        raise LeaseLost('samr_monitor_rule_disabled')
    if revisions != claim['rule_revision_ids']:
        raise LeaseLost('samr_monitor_rule_changed')


def source_query_key(query):
    from .domain import digest
    return digest(query)


def claim_job(database, now=None):
    from .monitor_tasks import expire_attempts_locked, start_attempt_locked
    now = now or utcnow()
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        expire_attempts_locked(db, 'samr', now=now)
        try:
            generation = assert_source_access(db, source.SOURCE_ID)
        except SourceAccessBlocked:
            db.commit()
            return None
        busy = db.scalar(select(SamrMonitorJob.id).where(SamrMonitorJob.lease_until > now).limit(1))
        last = db.scalar(select(func.max(SamrMonitorRun.finished_at)))
        if busy or last and utc(last) + timedelta(seconds=SOURCE_INTERVAL) > now:
            db.commit()
            return None
        eligible = active_rules().with_only_columns(SamrMonitorRule.job_id)
        job = db.scalar(select(SamrMonitorJob).where(SamrMonitorJob.id.in_(eligible), SamrMonitorJob.next_due_at <= now,
            SamrMonitorJob.lease_until.is_(None) | (SamrMonitorJob.lease_until <= now))
            .order_by(SamrMonitorJob.next_due_at, SamrMonitorJob.id).limit(1))
        if job is None:
            db.commit()
            return None
        job.lease_token, job.lease_until = uid(), now + timedelta(seconds=LEASE_SECONDS)
        claim = {'id': job.id, 'token': job.lease_token, 'started_at': now, 'session_id': job.session_id,
            'query': deepcopy(job.query), 'source_id': source.SOURCE_ID, 'source_access_generation': generation,
            'queue_lag_seconds': max(0, (now - utc(job.next_due_at)).total_seconds()),
            'rule_revision_ids': sorted(row.id for _, row in db.execute(active_rules().where(SamrMonitorRule.job_id == job.id)))}
        claim['attempt_id'] = start_attempt_locked(db, 'samr', claim)
        db.commit()
        return claim


def deliver_notifications(db, claim, article_id):
    rules = db.execute(active_rules().where(SamrMonitorRule.job_id == claim['id'])).all()
    term = claim['query']['text'].casefold()
    snapshots = {}
    for rule, revision in rules:
        sent = select(SamrNotification.id).where(SamrNotification.rule_id == rule.id,
            SamrNotification.event_id == SamrNoticeChange.id).exists()
        events = db.execute(select(SamrNoticeChange, SamrNoticeObservation).join(SamrNoticeObservation,
            SamrNoticeObservation.id == SamrNoticeChange.observation_id).where(SamrNoticeChange.article_id == article_id,
            SamrNoticeChange.observed_at >= revision.created_at, ~sent)
            .order_by(SamrNoticeObservation.sequence)).all()
        for change, observation in events:
            versions = db.scalars(select(SamrNoticeRevision).where(SamrNoticeRevision.id.in_(
                [change.before_revision_id, change.after_revision_id]))).all()
            if term and not any(term in version.notice[field].casefold() for version in versions for field in ('title', 'text')):
                continue
            observation_json(db, observation, snapshots)
            now = utcnow()
            db.add(SamrNotification(id=uid(), session_id=rule.session_id, rule_id=rule.id,
                rule_revision_id=revision.id, event_id=change.id, attempt_id=claim['attempt_id'], queued_at=now, delivered_at=now))


async def check_query(database, claim, adapter, query, position):
    from .monitor_tasks import _safe_reason
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        guard_claim(db, claim)
        db.get(SamrMonitorJob, claim['id']).lease_until = utcnow() + timedelta(seconds=LEASE_SECONDS)
        db.commit()
        result = await SamrRecallService(db, adapter, ingestion_guard=lambda session: guard_claim(session, claim)).execute(
            SamrRecallRequest(query=query, fallback_policy='never'), claim['session_id'], audience='background_monitor')
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        guard_claim(db, claim)
        run = db.get(QueryRun, result['query_id'])
        if run is None or run.session_id != claim['session_id'] or run.source_id != source.SOURCE_ID or run.query != query:
            raise ValueError('samr_monitor_query_binding_invalid')
        verification = db.scalar(select(SamrRecallVerification).where(SamrRecallVerification.query_id == run.id))
        snapshot = None
        if result['data_state'] in SUCCESS_STATES:
            snapshot = checked_snapshot(db.get(SamrRecallSnapshot, verification.snapshot_id)) if verification else None
            if snapshot is None or snapshot.query != query or snapshot.document != result['document']:
                raise ValueError('samr_monitor_evidence_binding_invalid')
        db.add(SamrMonitorCheck(attempt_id=claim['attempt_id'], position=position, query_id=run.id,
            snapshot_id=snapshot.id if snapshot else None, verification_id=verification.id if verification else None,
            query=deepcopy(query), state=result['data_state'], reason=_safe_reason(result.get('reason'))))
        if snapshot is not None and query['operation'] == 'notice':
            deliver_notifications(db, claim, snapshot.document['notice']['article_id'])
        db.commit()
    return result


def search_query(query, page):
    return {'operation': 'search', 'keyword': query['keyword'], 'page': str(page)}


def selected_notices(query, documents):
    first = documents[0]
    notices = []
    seen = set()
    for page, document in enumerate(documents, 1):
        if (document['page'] != page or document['declared_total'] != first['declared_total']
                or document['source_navigation_pages'] != first['source_navigation_pages']):
            raise ScanChanged('samr_monitor_pagination_changed')
        for item in document['notices']:
            if item['article_id'] in seen:
                raise ScanChanged('samr_monitor_pagination_changed')
            seen.add(item['article_id'])
            notices.append(item)
    return notices[:query['notice_limit']], len(notices)


async def execute_scan(database, claim, adapter=None):
    adapter = adapter or source
    async with asyncio.timeout(MAX_SECONDS):
        query = claim['query']
        if query['operation'] == 'notice':
            result = await check_query(database, claim, adapter, {'operation': 'notice', 'reference': query['reference']}, 0)
            return ('samr_complete', None) if result['data_state'] in SUCCESS_STATES else ('source_unavailable', result.get('reason'))
        documents = []
        position = 0
        for pass_number in range(2):
            current = []
            page, pages = 1, 1
            while page <= pages:
                if position:
                    await asyncio.sleep(SOURCE_INTERVAL)
                result = await check_query(database, claim, adapter, search_query(query, page), position)
                position += 1
                if result['data_state'] not in SUCCESS_STATES:
                    return 'source_unavailable', result.get('reason')
                current.append(result['document'])
                pages = max(1, min(query['page_limit'], current[0]['source_navigation_pages']))
                page += 1
            selected_notices(query, current)
            if pass_number == 0:
                documents = current
            elif current != documents:
                raise ScanChanged('samr_monitor_listing_changed')
        selected, _ = selected_notices(query, documents)
        for item in selected:
            await asyncio.sleep(SOURCE_INTERVAL)
            result = await check_query(database, claim, adapter, {'operation': 'notice', 'reference': item['reference']}, position)
            position += 1
            if result['data_state'] not in SUCCESS_STATES:
                return 'source_unavailable', result.get('reason')
        return 'samr_complete', None


def scan_coverage(db, claim, checks):
    query = claim['query']
    accepted = {row.position: checked_snapshot(db.get(SamrRecallSnapshot, row.snapshot_id)) for row in checks
        if row.snapshot_id is not None and row.state in SUCCESS_STATES}
    coverage = {'status': 'incomplete', 'listing_consistency': 'not_applicable' if query['operation'] == 'notice' else 'unconfirmed',
        'declared_total': None, 'source_navigation_page_limit': source.NAVIGATION_PAGE_LIMIT,
        'expected_pages': 0, 'accepted_search_checks': sum(row.query['operation'] == 'search' and row.snapshot_id is not None for row in checks),
        'selected_notice_count': 1 if query['operation'] == 'notice' else 0,
        'checked_notice_count': sum(row.query['operation'] == 'notice' and row.snapshot_id is not None for row in checks),
        'source_results_fully_covered': False}
    selected = []
    expected = [{'operation': 'notice', 'reference': query['reference']}] if query['operation'] == 'notice' else []
    if query['operation'] == 'search':
        if 0 not in accepted:
            return selected, coverage, False
        first = accepted[0].document
        pages = max(1, min(query['page_limit'], first['source_navigation_pages']))
        coverage.update(declared_total=first['declared_total'], expected_pages=pages,
            source_navigation_pages=first['source_navigation_pages'])
        if any(position not in accepted for position in range(pages * 2)):
            return selected, coverage, False
        documents = [accepted[position].document for position in range(pages)]
        try:
            selected, discovered = selected_notices(query, documents)
        except ScanChanged:
            return [], coverage, False
        confirmed = documents == [accepted[position].document for position in range(pages, pages * 2)]
        coverage.update(listing_consistency='two_pass_equal' if confirmed else 'changed', selected_notice_count=len(selected),
            discovered_notice_count=discovered)
        if not confirmed:
            return selected, coverage, False
        expected = [search_query(query, page) for _ in range(2) for page in range(1, pages + 1)]
        expected += [{'operation': 'notice', 'reference': item['reference']} for item in selected]
        coverage['source_results_fully_covered'] = len(selected) == discovered == first['declared_total']
    complete = len(checks) == len(expected) and all(row.position == position and row.query == expected[position]
        and position in accepted and accepted[position].query == row.query for position, row in enumerate(checks))
    coverage['status'] = 'complete' if complete else 'incomplete'
    coverage['source_results_fully_covered'] = complete and coverage['source_results_fully_covered']
    return selected, coverage, complete


def finish_job(database, claim, state, reason=None, now=None):
    from .monitor_tasks import _safe_reason, finish_attempt_locked, interrupt_attempt_locked
    now = now or utcnow()
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        job = db.get(SamrMonitorJob, claim['id'])
        if job is None or job.lease_token != claim['token'] or job.lease_until is None or utc(job.lease_until) <= now:
            interrupt_attempt_locked(db, claim, 'samr_monitor_lease_lost', now=now)
            db.commit()
            return False
        try:
            guard_claim(db, claim)
        except LeaseLost as error:
            state, reason = 'lease_lost', str(error)
        except SourceAccessBlocked as error:
            state, reason = 'source_unavailable', error.code
        checks = db.scalars(select(SamrMonitorCheck).where(SamrMonitorCheck.attempt_id == claim['attempt_id'])
            .order_by(SamrMonitorCheck.position)).all()
        selected, coverage, complete = scan_coverage(db, claim, checks)
        if state == 'samr_complete' and not complete:
            state, reason = 'samr_incomplete', 'samr_monitor_incomplete'
        reason = _safe_reason(reason)
        count = db.scalar(select(func.count()).select_from(SamrNotification).where(SamrNotification.attempt_id == claim['attempt_id']))
        run = SamrMonitorRun(id=uid(), job_id=job.id, attempt_id=claim['attempt_id'], lease_token=claim['token'],
            state=state, reason=reason, started_at=claim['started_at'], finished_at=now,
            selected_notices=deepcopy(selected), coverage=coverage, notification_count=count)
        db.add(run)
        db.flush()
        terminal = (interrupt_attempt_locked(db, claim, reason, now=now, run_id=run.id) if state == 'lease_lost' else
            finish_attempt_locked(db, claim, state, reason, finished_at=now, run_id=run.id,
                query_id=checks[-1].query_id if checks else None))
        if not terminal:
            db.rollback()
            return False
        job.last_finished_at, job.lease_token, job.lease_until = now, None, None
        if state != 'lease_lost' or reason != 'worker_cancelled':
            reschedule(db, job)
        QueryService(db, None).audit(claim['session_id'], 'samr_monitor_finished', run_id=run.id,
            attempt_id=claim['attempt_id'], state=state, notifications=count)
        db.commit()
        claim['final_result'] = {'state': state, 'reason': reason}
        return True
