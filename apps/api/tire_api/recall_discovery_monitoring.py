"""Bounded two-pass discovery scans; only complete scans advance candidate history."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import hashlib
import time

from sqlalchemy import desc, func, select

from .db import QueryRun, RawCapture, uid, utc, utcnow
from .domain import digest
from .monitoring import LeaseLost
from .recall_models import SOURCE_ID, RecallMonitorJob, RecallMonitorRun
from .recall_discovery import RecallDiscoveryService, RecallSearchRequest, RecallSearchSnapshot, RecallSearchVerification
from .recall_discovery_monitor_models import (RecallDiscoveryJob, RecallDiscoveryRule, RecallDiscoveryRuleRevision,
    RecallDiscoveryRun, RecallDiscoveryPage, RecallDiscoveryCandidate, RecallDiscoveryNotification, DISCOVERY_BUDGET)
from .service import QueryService
from .source_settings import SourceAccessBlocked, assert_source_access

LEASE_SECONDS = 600
MAX_PAGES_PER_PASS = 20
MAX_PRODUCTS = 200
MAX_PAGE_OPERATIONS = 40
MAX_RAW_BYTES = 64 * 1024 * 1024
MAX_SECONDS = 300
SOURCE_INTERVAL = 2.1
BUDGET = DISCOVERY_BUDGET


def current_rules():
    latest = (select(RecallDiscoveryRuleRevision.rule_id,
        func.max(RecallDiscoveryRuleRevision.revision).label('revision'))
        .group_by(RecallDiscoveryRuleRevision.rule_id).subquery())
    return (select(RecallDiscoveryRule, RecallDiscoveryRuleRevision)
        .join(RecallDiscoveryRuleRevision, RecallDiscoveryRuleRevision.rule_id == RecallDiscoveryRule.id)
        .join(latest, (latest.c.rule_id == RecallDiscoveryRule.id)
              & (latest.c.revision == RecallDiscoveryRuleRevision.revision)))


def active_rules():
    return current_rules().where(RecallDiscoveryRuleRevision.enabled.is_(True),
                                 RecallDiscoveryRuleRevision.archived.is_(False))


def reschedule(db, job):
    rows = db.execute(active_rules().where(RecallDiscoveryRule.job_id == job.id)).all()
    interval = min((row.interval_seconds for _, row in rows), default=None)
    if interval is not None:
        job.next_due_at = utc(job.last_finished_at) + timedelta(seconds=interval) if job.last_finished_at else utcnow()


def source_busy_locked(db, now):
    """Shared scheduled-source exclusion; caller holds the ingestion lock."""
    for model in (RecallMonitorJob, RecallDiscoveryJob):
        if db.scalar(select(model.id).where(model.lease_until > now).limit(1)):
            return True
    for model in (RecallMonitorRun, RecallDiscoveryRun):
        finished = db.scalar(select(func.max(model.finished_at)))
        if finished and utc(finished) + timedelta(seconds=SOURCE_INTERVAL) > now:
            return True
    return False


def guard_claim(db, claim):
    job = db.get(RecallDiscoveryJob, claim['id'], populate_existing=True)
    if (job is None or job.lease_token != claim['token'] or job.lease_until is None
            or utc(job.lease_until) <= utcnow()):
        raise LeaseLost('recall_discovery_lease_lost')
    generation = claim.get('source_access_generation')
    if type(generation) is not int:
        raise SourceAccessBlocked('source_access_pin_missing')
    assert_source_access(db, SOURCE_ID, generation)
    revisions = sorted(row.id for _, row in db.execute(active_rules().where(RecallDiscoveryRule.job_id == job.id)))
    if not revisions:
        raise LeaseLost('recall_discovery_rule_disabled')
    if revisions != claim.get('rule_revision_ids'):
        raise LeaseLost('recall_discovery_rule_changed')


def claim_job(database, now=None):
    from .monitor_tasks import expire_attempts_locked, start_attempt_locked
    now = now or utcnow()
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        expire_attempts_locked(db, 'recall_discovery', now=now)
        try:
            generation = assert_source_access(db, SOURCE_ID)
        except SourceAccessBlocked:
            db.commit()
            return None
        if source_busy_locked(db, now):
            db.commit()
            return None
        job = db.scalar(select(RecallDiscoveryJob).where(
            RecallDiscoveryJob.id.in_(active_rules().with_only_columns(RecallDiscoveryRule.job_id)),
            RecallDiscoveryJob.next_due_at <= now,
            RecallDiscoveryJob.lease_until.is_(None) | (RecallDiscoveryJob.lease_until <= now))
            .order_by(RecallDiscoveryJob.next_due_at, RecallDiscoveryJob.id).limit(1))
        if job is None:
            db.commit()
            return None
        job.lease_token, job.lease_until = uid(), now + timedelta(seconds=LEASE_SECONDS)
        claim = {'id': job.id, 'token': job.lease_token, 'started_at': now, 'kind': 'recall_discovery',
            'session_id': job.session_id, 'query': dict(job.query), 'source_id': SOURCE_ID,
            'source_access_generation': generation,
            'queue_lag_seconds': max(0, (now - utc(job.next_due_at)).total_seconds())}
        claim['rule_revision_ids'] = sorted(row.id for _, row in db.execute(active_rules().where(RecallDiscoveryRule.job_id == job.id)))
        claim['attempt_id'] = start_attempt_locked(db, 'recall_discovery', claim)
        db.commit()
        return claim


class _BoundedAdapter:
    """Keep raw accounting inside the page boundary, including cached 304 bytes."""
    def __init__(self, adapter, remaining, remaining_seconds):
        self.adapter, self.remaining, self.reason = adapter, remaining, None
        self.deadline = asyncio.get_running_loop().time() + remaining_seconds
        self.raw_bytes, self.cached_snapshot_id = 0, None
        self.was_not_modified = False
        self.supports_parser_deployments = getattr(adapter, 'supports_parser_deployments', False)

    async def fetch(self, query, cached=None, *, on_observation=None, **kwargs):
        if self.remaining <= 0 or cached and len(cached.get('body', '').encode('utf-8')) > self.remaining:
            self.reason = 'discovery_raw_budget_exceeded'
            return {'status': 'unavailable', 'reason': self.reason}
        if getattr(self.adapter, 'supports_response_limits', False):
            kwargs['max_response_bytes'] = min(8 * 1024 * 1024, self.remaining)

        def received(value):
            if len(value.get('body', '').encode('utf-8')) > self.remaining:
                self.reason = 'discovery_raw_budget_exceeded'
                raise ValueError(self.reason)
            self.raw_bytes = len(value.get('body', '').encode('utf-8'))
            if on_observation:
                on_observation(value)

        try:
            # Existing parse_isolated cancellation waits for supervisor cleanup.
            async with asyncio.timeout_at(self.deadline):
                result = await self.adapter.fetch(query, cached=cached, on_observation=received, **kwargs)
        except TimeoutError:
            self.reason = 'discovery_time_budget_exceeded'
            return {'status': 'unavailable', 'reason': self.reason}
        if result.get('reason') == 'response_too_large' and self.remaining < 8 * 1024 * 1024:
            self.reason = 'discovery_raw_budget_exceeded'
        if result.get('status') == 'not_modified' and cached:
            self.was_not_modified = True
            self.raw_bytes = len(cached.get('body', '').encode('utf-8'))
            self.cached_snapshot_id = cached.get('snapshot_id')
        return result


def _record_page(database, claim, pass_number, offset, query_id, *, accepted, bounded):
    from .monitor_tasks import journal_models
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        attempt_model, _ = journal_models('recall_discovery')
        attempt = db.get(attempt_model, claim['attempt_id'])
        if (attempt is None or attempt.job_id != claim['id']
                or attempt.lease_token_hash != hashlib.sha256(claim['token'].encode()).hexdigest()):
            raise LeaseLost('recall_discovery_lease_lost')
        query = db.get(QueryRun, query_id)
        if (query is None or query.session_id != claim['session_id'] or query.source_id != SOURCE_ID
                or query.query != {'search': claim['query']['search'], 'offset': str(offset)}):
            raise ValueError('discovery_page_query_mismatch')
        fence_error = None
        if accepted:
            try:
                guard_claim(db, claim)
            except (LeaseLost, SourceAccessBlocked) as error:
                accepted, fence_error = False, error
        accepted = accepted and query.source_access_generation == claim['source_access_generation']
        verification = db.scalar(select(RecallSearchVerification).where(RecallSearchVerification.query_id == query.id))
        capture = db.scalar(select(RawCapture).where(RawCapture.query_id == query.id))
        snapshot_id = (verification.snapshot_id if accepted and verification else
            bounded.cached_snapshot_id if bounded.was_not_modified and capture is None else None)
        snapshot = db.get(RecallSearchSnapshot, snapshot_id) if snapshot_id else None
        body_bytes = capture.byte_count if capture else len(snapshot.body.encode('utf-8')) if snapshot else bounded.raw_bytes
        discovery = snapshot.discovery if accepted and snapshot and verification else None
        row = RecallDiscoveryPage(id=uid(), job_id=claim['id'], attempt_id=claim['attempt_id'],
            pass_number=pass_number, offset=offset, query_id=query.id,
            verification_id=verification.id if discovery else None, snapshot_id=snapshot.id if snapshot else None,
            total=discovery['pagination']['total'] if discovery else None,
            count=discovery['pagination']['count'] if discovery else None,
            content_fingerprint=digest(discovery) if discovery else None, raw_bytes=body_bytes)
        db.add(row)
        db.commit()
        return {'raw_bytes': body_bytes, 'discovery': discovery,
                'fence_error': fence_error,
                'parser_identity': snapshot.parser_identity if snapshot else None,
                'parser_version': snapshot.parser_version if snapshot else None}


async def execute_scan(database, claim, adapter=None, *, clock=time.monotonic, sleep=asyncio.sleep):
    from .adapters import nhtsa
    claim['parser_selection_required'] = getattr(adapter or nhtsa, 'supports_parser_deployments', False) is True
    started = clock()
    usage = {'page_operations': 0, 'raw_bytes': 0, 'elapsed_seconds': 0.0}
    identity = None
    pass_hashes = []

    def outcome(reason=None):
        usage['elapsed_seconds'] = max(0.0, clock() - started)
        return {'state': 'discovery_incomplete' if reason else 'discovery_complete', 'reason': reason,
                'usage': dict(usage)}

    for pass_number in (1, 2):
        products, expected_total = {}, None
        for page_index in range(MAX_PAGES_PER_PASS):
            elapsed = clock() - started
            wait = SOURCE_INTERVAL if usage['page_operations'] else 0
            if elapsed + wait >= MAX_SECONDS:
                return outcome('discovery_time_budget_exceeded')
            if usage['page_operations'] >= MAX_PAGE_OPERATIONS:
                return outcome('discovery_page_budget_exceeded')
            if usage['raw_bytes'] >= MAX_RAW_BYTES:
                return outcome('discovery_raw_budget_exceeded')
            if wait:
                await sleep(wait)
            with database.sessions() as db:
                QueryService(db, None).lock_ingestion()
                guard_claim(db, claim)
                db.commit()
            remaining_seconds = MAX_SECONDS - (clock() - started)
            if remaining_seconds <= 0:
                return outcome('discovery_time_budget_exceeded')
            bounded = _BoundedAdapter(adapter or nhtsa, MAX_RAW_BYTES - usage['raw_bytes'], remaining_seconds)
            offset = page_index * 10
            usage['page_operations'] += 1
            started_queries, response, failure, receipt = [], None, None, None
            try:
                with database.sessions() as db:
                    response = await RecallDiscoveryService(db, bounded,
                        ingestion_guard=lambda session: guard_claim(session, claim),
                        on_query_started=started_queries.append).execute(
                            RecallSearchRequest(query={**claim['query'], 'offset': offset}, fallback_policy='never'),
                            claim['session_id'], audience='background_monitor')
            except BaseException as error:
                failure = error
            finally:
                if started_queries:
                    assert len(started_queries) == 1
                    receipt = _record_page(database, claim, pass_number, offset, started_queries[0],
                        accepted=response is not None and response['data_state'] in {'live', 'live_verified_304'}, bounded=bounded)
                    usage['raw_bytes'] += receipt['raw_bytes']
            if failure is not None:
                raise failure
            if receipt is None:
                return outcome('discovery_page_failed')
            if receipt['fence_error'] is not None:
                raise receipt['fence_error']
            if response.get('reason') in {'source_paused', 'source_archived', 'source_access_changed', 'source_access_pin_missing'}:
                return outcome(response['reason'])
            if bounded.reason:
                return outcome(bounded.reason)
            if usage['raw_bytes'] > MAX_RAW_BYTES:
                return outcome('discovery_raw_budget_exceeded')
            if clock() - started >= MAX_SECONDS:
                return outcome('discovery_time_budget_exceeded')
            if response['data_state'] not in {'live', 'live_verified_304'} or receipt['discovery'] is None:
                return outcome('discovery_page_failed')
            current_identity = {'version': receipt['parser_version'], 'identity': receipt['parser_identity']}
            if identity is None:
                identity = current_identity
            elif current_identity != identity:
                return outcome('discovery_parser_changed')
            data = receipt['discovery']
            total = data['pagination']['total']
            if total > MAX_PRODUCTS:
                return outcome('discovery_scope_budget_exceeded')
            if expected_total is None:
                expected_total = total
            if total != expected_total or any(row['id'] in products for row in data['products']):
                return outcome('discovery_pagination_changed')
            products.update((row['id'], row) for row in data['products'])
            if not data['pagination']['has_next']:
                if len(products) != expected_total:
                    return outcome('discovery_pagination_changed')
                pass_hashes.append(digest({'total': total, 'products': sorted(products.values(), key=lambda row: row['id'])}))
                break
        else:
            return outcome('discovery_page_budget_exceeded')
    if pass_hashes[0] != pass_hashes[1]:
        return outcome('discovery_content_changed')
    return outcome()


def _scan_evidence(db, claim):
    pages = db.scalars(select(RecallDiscoveryPage).where(RecallDiscoveryPage.attempt_id == claim['attempt_id'])
        .order_by(RecallDiscoveryPage.pass_number, RecallDiscoveryPage.offset)).all()
    hashes, candidates, products_count, identity = [], {}, 0, None
    valid = len(pages) <= MAX_PAGE_OPERATIONS and sum(row.raw_bytes for row in pages) <= MAX_RAW_BYTES
    for pass_number in (1, 2):
        selected = [row for row in pages if row.pass_number == pass_number]
        products, total = {}, selected[0].total if selected else None
        complete = bool(selected) and len(selected) <= MAX_PAGES_PER_PASS and total is not None and total <= MAX_PRODUCTS
        for index, page in enumerate(selected):
            snapshot = db.get(RecallSearchSnapshot, page.snapshot_id) if page.snapshot_id else None
            verification = db.get(RecallSearchVerification, page.verification_id) if page.verification_id else None
            query = db.get(QueryRun, page.query_id) if page.query_id else None
            if (snapshot is None or verification is None or query is None or verification.query_id != page.query_id
                    or verification.snapshot_id != page.snapshot_id or query.source_access_generation != claim['source_access_generation']
                    or query.session_id != claim['session_id'] or query.source_id != SOURCE_ID
                    or query.fallback_policy != 'never' or query.state != 'live'
                    or verification.query_key != query.query_key or snapshot.query_key != query.query_key
                    or query.query != {'search': claim['query']['search'], 'offset': str(page.offset)}
                    or snapshot.query != query.query or page.content_fingerprint != digest(snapshot.discovery)
                    or snapshot.raw_hash != hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest()
                    or page.raw_bytes != len(snapshot.body.encode('utf-8'))
                    or page.total != snapshot.discovery['pagination']['total']
                    or page.count != snapshot.discovery['pagination']['count']
                    or page.offset != index * 10 or page.total != total):
                complete = False
                continue
            current = {'version': snapshot.parser_version, 'identity': snapshot.parser_identity}
            if identity is None:
                identity = current
            elif identity != current:
                complete = False
            for product in snapshot.discovery['products']:
                if product['id'] in products:
                    complete = False
                products[product['id']] = product
                for campaign in product['campaigns']:
                    item = candidates.setdefault(campaign['campaign_number'], {'campaign': campaign, 'evidence': []})
                    item['evidence'].append({'page_id': page.id, 'snapshot_id': snapshot.id,
                        'query_id': query.id, 'product_ids': [product['id']]})
        products_count = max(products_count, len(products))
        complete = complete and len(products) == total and len(selected) == max(1, ((total or 0) + 9) // 10)
        if complete:
            hashes.append(digest({'total': total, 'products': sorted(products.values(), key=lambda row: row['id'])}))
        valid = valid and complete
    return pages, hashes, candidates, products_count, bool(valid and len(hashes) == 2 and hashes[0] == hashes[1])


def _assert_current_parser(db, claim, pages):
    """Reuse each real query pin under the final adoption lock; never invent one."""
    from .parser_release_models import ParserSelection
    from .parser_releases import ParserDeploymentError, assert_selection_current
    from .parser_provenance import check_result_identity
    selections = [db.get(ParserSelection, page.query_id) for page in pages]
    if not any(selections) and not claim.get('parser_selection_required', False):
        return  # Explicit synthetic adapters have no deployment pin to verify.
    if not all(selections):
        raise ParserDeploymentError('parser_selection_mismatch', 409)
    for page, stored in zip(pages, selections, strict=True):
        selection = {'query_run_id': stored.query_run_id, 'source_id': stored.source_id,
            'bundle_id': stored.bundle_id, 'deployment_revision': stored.deployment_revision,
            'parser_version': stored.descriptor['parser_version'], 'parser_digest': stored.descriptor['parser_digest'],
            'execution_digest': stored.descriptor.get('execution_digest', stored.descriptor['parser_digest'])}
        assert_selection_current(db, selection)
        snapshot = db.get(RecallSearchSnapshot, page.snapshot_id)
        verification = db.get(RecallSearchVerification, page.verification_id)
        check_result_identity(selection, {'parser_identity': snapshot.parser_identity,
                                         'parser_version': snapshot.parser_version})
        check_result_identity(selection, {'parser_identity': verification.parser_identity,
                                         'parser_version': snapshot.parser_version})


class _FinalizationBudgetExceeded(RuntimeError):
    pass


def finish_job(database, claim, state, reason=None, now=None, *, usage=None):
    """Budget admission includes writes through the check before commit().

    The immutable Run's elapsed value ends at receipt construction, after scan
    and evidence/Parser checks. Subsequent writes are still budget checked, but
    neither their duration nor a database commit tail is retrofitted into it.
    """
    usage = usage or {}
    entered = time.monotonic()
    observed_now = now or utcnow()
    initial_elapsed = max(float(usage.get('elapsed_seconds', 0)),
                          (observed_now - utc(claim['started_at'])).total_seconds(), 0.0)

    def elapsed():
        return max(initial_elapsed + max(0.0, time.monotonic() - entered),
                   (utcnow() - utc(claim['started_at'])).total_seconds())

    try:
        return _finish_job_once(database, claim, state, reason, observed_now, usage, elapsed)
    except _FinalizationBudgetExceeded:
        # Exiting the first Session rolls back its complete Run, candidates,
        # notifications, task event and lease changes together. Pages/raw were
        # committed by separate page transactions and remain untouched.
        return _finish_job_once(database, claim, 'discovery_incomplete',
            'discovery_time_budget_exceeded', max(observed_now, utcnow()), usage, elapsed)


def _finish_job_once(database, claim, state, reason, now, usage, elapsed):
    from .monitor_tasks import finish_attempt_locked, interrupt_attempt_locked
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        job = db.get(RecallDiscoveryJob, claim['id'])
        if job is None or job.lease_token != claim['token'] or job.lease_until is None or utc(job.lease_until) <= now:
            interrupt_attempt_locked(db, claim, 'recall_discovery_lease_lost', now=now)
            db.commit()
            return False
        interrupted = state == 'lease_lost'
        if not interrupted:
            try:
                guard_claim(db, claim)
            except SourceAccessBlocked as error:
                state, reason = 'discovery_incomplete', error.code
            except LeaseLost as error:
                interrupted, state, reason = True, 'lease_lost', str(error)
        pages, hashes, candidates, products_count, valid = _scan_evidence(db, claim)
        checked_elapsed = elapsed()
        operations = max(int(usage.get('page_operations', 0)), len(pages))
        complete = state == 'discovery_complete' and reason is None and valid and checked_elapsed <= MAX_SECONDS and operations <= MAX_PAGE_OPERATIONS
        if complete:
            from .parser_releases import ParserDeploymentError
            try:
                _assert_current_parser(db, claim, pages)
            except (ParserDeploymentError, KeyError, TypeError):
                complete, state, reason = False, 'discovery_incomplete', 'discovery_parser_changed'
        if state == 'discovery_complete' and not complete:
            reason = 'discovery_time_budget_exceeded' if checked_elapsed > MAX_SECONDS else 'discovery_page_failed'
        state = 'lease_lost' if interrupted else 'discovery_complete' if complete else 'discovery_incomplete'

        def check_budget():
            if complete and elapsed() > MAX_SECONDS:
                raise _FinalizationBudgetExceeded()

        check_budget()
        previous = db.scalar(select(RecallDiscoveryRun).where(RecallDiscoveryRun.job_id == job.id,
            RecallDiscoveryRun.coverage == 'complete').order_by(desc(RecallDiscoveryRun.finished_at), desc(RecallDiscoveryRun.id)).limit(1))
        existing = set(db.scalars(select(RecallDiscoveryCandidate.campaign_number).where(RecallDiscoveryCandidate.job_id == job.id)))
        new_numbers = sorted(set(candidates) - existing) if complete else []
        check_budget()
        now = max(now, utcnow())
        run = RecallDiscoveryRun(id=uid(), job_id=job.id, attempt_id=claim['attempt_id'], lease_token=claim['token'],
            state=state, reason=reason, started_at=claim['started_at'], finished_at=now,
            previous_complete_id=previous.id if previous else None, coverage='complete' if complete else 'incomplete',
            pass_fingerprints=hashes, page_operations=operations, pages_completed=sum(row.verification_id is not None for row in pages),
            products_count=products_count, candidates_count=len(candidates), new_candidates_count=len(new_numbers) if previous else 0,
            raw_bytes=sum(row.raw_bytes for row in pages), elapsed_seconds=elapsed(), budget=dict(BUDGET))
        db.add(run)
        db.flush()
        check_budget()
        rules = db.execute(active_rules().where(RecallDiscoveryRule.job_id == job.id)).all() if complete and previous else []
        for number in new_numbers:
            check_budget()
            candidate = RecallDiscoveryCandidate(id=uid(), job_id=job.id, campaign_number=number,
                first_seen_run_id=run.id, first_seen_at=now, **candidates[number])
            db.add(candidate)
            db.flush()
            check_budget()
            for rule, revision in rules:
                check_budget()
                db.add(RecallDiscoveryNotification(session_id=rule.session_id, rule_id=rule.id,
                    rule_revision_id=revision.id, candidate_id=candidate.id))
        db.flush()
        check_budget()
        finished = (interrupt_attempt_locked(db, claim, reason, run_id=run.id, now=now) if interrupted else
                    finish_attempt_locked(db, claim, state, reason, run_id=run.id, finished_at=now))
        if not finished:
            db.rollback()
            return False
        check_budget()
        job.last_finished_at, job.lease_token, job.lease_until = now, None, None
        reschedule(db, job)
        db.flush()
        check_budget()
        db.commit()
        claim['final_result'] = {'state': state, 'reason': reason}
        return True


def interrupt_job(database, claim, reason, now=None):
    reason = reason if reason in {'recall_discovery_lease_lost', 'recall_discovery_rule_disabled',
                                  'recall_discovery_rule_changed', 'monitor_attempt_not_running'} else 'recall_discovery_lease_lost'
    return finish_job(database, claim, 'lease_lost', reason, now=now)
