"""Private synthetic discovery monitoring; no live source or Parser process."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import func, select

from tire_api import recall_discovery_monitoring as queue, recall_monitoring
from tire_api.db import QueryRun, RawCapture, uid, utc, utcnow
from tire_api.domain import digest
from tire_api.main import SESSION_COOKIE
from tire_api.monitoring import LeaseLost
from tire_api.monitor_tasks import journal_models
from tire_api.recall_discovery import RecallDiscoveryService, RecallSearchRequest
from tire_api.recall_discovery_monitor_models import (RecallDiscoveryJob, RecallDiscoveryRule,
    RecallDiscoveryRuleRevision, RecallDiscoveryRun, RecallDiscoveryPage, RecallDiscoveryCandidate,
    RecallDiscoveryNotification, DISCOVERY_BUDGET)
from tire_api.recall_models import (RecallRevision, RecallSnapshot, RecallMonitorJob, RecallMonitorRun,
    RecallRuleRevision)
from test_recall_discovery import product
from test_source_access import access_app, mutate_source


spec = importlib.util.spec_from_file_location('discovery_execution_worker',
    Path(__file__).resolve().parents[3] / 'apps/worker/monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


async def no_sleep(_seconds):
    pass


def seed(env, *, search='SYNTHETIC DEMO', enabled=True):
    client, app, _ = env
    client.get('/health')
    session_id = client.cookies.get(SESSION_COOKIE)
    query = {'search': search}
    job_id = digest({'session_id': session_id, 'query': query})
    with app.state.database.sessions() as db:
        job = db.get(RecallDiscoveryJob, job_id)
        if job is None:
            job = RecallDiscoveryJob(id=job_id, session_id=session_id, query=query, query_key=digest(query))
            db.add(job)
            db.flush()
        rule = RecallDiscoveryRule(id=uid(), session_id=session_id, job_id=job.id)
        db.add(rule)
        db.flush()
        db.add(RecallDiscoveryRuleRevision(id=uid(), rule_id=rule.id, revision=1,
            name='Synthetic discovery rule', enabled=enabled, archived=False, interval_seconds=3600))
        db.commit()
        return job.id, rule.id


def due_claim(env, job_id):
    database = env[1].state.database
    with database.sessions() as db:
        job = db.get(RecallDiscoveryJob, job_id)
        now = max(utcnow(), utc(job.last_finished_at) + timedelta(seconds=3) if job.last_finished_at else utcnow())
        job.next_due_at = now - timedelta(seconds=1)
        db.commit()
    claim = queue.claim_job(database, now=now)
    assert claim is not None
    monitor.begin_attempt(database, claim, queue.guard_claim)
    return claim


def scan(env, job_id, **kwargs):
    database = env[1].state.database
    claim = due_claim(env, job_id)
    result = asyncio.run(queue.execute_scan(database, claim, env[2]['search'], sleep=no_sleep, **kwargs))
    assert queue.finish_job(database, claim, result['state'], result['reason'],
        now=claim['started_at'] + timedelta(seconds=1), usage=result['usage'])
    with database.sessions() as db:
        run = db.scalar(select(RecallDiscoveryRun).where(RecallDiscoveryRun.attempt_id == claim['attempt_id']))
    return claim, result, run


def count(database, model):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_scheduled_discovery_rejects_lost_claim_before_fetch(access_app):
    client, app, adapters = access_app
    client.get('/health')
    owner = client.cookies.get(SESSION_COOKIE)

    def lost(_db):
        raise LeaseLost('recall_discovery_lease_lost')

    with app.state.database.sessions() as db:
        with pytest.raises(LeaseLost, match='recall_discovery_lease_lost'):
            asyncio.run(RecallDiscoveryService(db, adapters['search'], ingestion_guard=lost).execute(
                RecallSearchRequest(query={'search': 'SYNTHETIC DEMO'}, fallback_policy='never'), owner))
    assert adapters['search'].calls == []


def test_complete_two_pass_baseline_then_seen_ever_notifies_once(access_app):
    job_id, _ = seed(access_app)
    seed(access_app)  # Same query/session shares one job but two independent rules.
    adapter = access_app[2]['search']
    adapter.products = [product(index, campaign=index == 11) for index in range(1, 12)]
    database = access_app[1].state.database
    _, result, baseline = scan(access_app, job_id)
    assert result['state'] == 'discovery_complete' and baseline.coverage == 'complete'
    assert baseline.products_count == 11 and baseline.candidates_count == 1 and baseline.new_candidates_count == 0
    assert baseline.page_operations == baseline.pages_completed == 4 and baseline.budget == DISCOVERY_BUDGET
    assert len(baseline.pass_fingerprints) == 2 and len(set(baseline.pass_fingerprints)) == 1
    assert count(database, RecallDiscoveryCandidate) == 1 and count(database, RecallDiscoveryNotification) == 0
    new = deepcopy(adapter.products[-1]['campaigns'][0])
    new['campaign_number'] = '26T009000'
    adapter.products[-1]['campaigns'].append(new)
    adapter.products[-1]['recalls_count'] = 2
    _, _, second = scan(access_app, job_id)
    assert second.previous_complete_id == baseline.id and second.new_candidates_count == 1
    assert count(database, RecallDiscoveryCandidate) == count(database, RecallDiscoveryNotification) == 2
    with database.sessions() as db:
        candidate = db.scalar(select(RecallDiscoveryCandidate).where(RecallDiscoveryCandidate.campaign_number == '26T009000'))
        assert len(candidate.evidence) == 2
        receipts = [db.get(RecallDiscoveryPage, row['page_id']) for row in candidate.evidence]
        assert {(row.pass_number, row.offset) for row in receipts} == {(1, 10), (2, 10)}
        assert all(db.get(QueryRun, row.query_id).fallback_policy == 'never' for row in receipts)
    scan(access_app, job_id)
    adapter.products[-1]['campaigns'] = []
    adapter.products[-1]['recalls_count'] = 0
    scan(access_app, job_id)
    adapter.products[-1]['campaigns'] = [new]
    adapter.products[-1]['recalls_count'] = 1
    scan(access_app, job_id)
    assert count(database, RecallDiscoveryNotification) == 2
    assert count(database, RecallSnapshot) == count(database, RecallRevision) == 0


@pytest.mark.parametrize('mutation,reason', [
    ('scope', 'discovery_scope_budget_exceeded'), ('duplicate', 'discovery_pagination_changed'),
    ('content', 'discovery_content_changed'), ('total', 'discovery_pagination_changed'),
    ('failed', 'discovery_page_failed'), ('parser', 'discovery_parser_changed')])
def test_incomplete_scan_never_advances_baseline_or_seen(access_app, monkeypatch, mutation, reason):
    job_id, _ = seed(access_app)
    adapter = access_app[2]['search']
    adapter.products = [product(index, campaign=index == 11) for index in range(1, 12)]
    _, _, baseline = scan(access_app, job_id)
    before_calls = len(adapter.calls)
    fetch = adapter.fetch

    async def changed(query, *args, **kwargs):
        index = len(adapter.calls) - before_calls
        if mutation == 'scope':
            adapter.products = [product(i, False) for i in range(1, 202)]
        if mutation == 'duplicate' and index == 1:
            adapter.products[-1]['id'] = adapter.products[0]['id']
        if mutation == 'content' and index == 2:
            adapter.products[-1]['campaigns'][0]['remedy'] = 'Synthetic different second pass content'
        if mutation == 'total' and index == 1:
            adapter.products.append(product(12, False))
        if mutation == 'failed' and index == 1:
            adapter.offline = True
        if mutation == 'parser' and index == 1:
            adapter.identity['parser_digest'] = 'c' * 64
        return await fetch(query, *args, **kwargs)

    monkeypatch.setattr(adapter, 'fetch', changed)
    _, result, failed = scan(access_app, job_id)
    assert result['reason'] == reason and failed.coverage == 'incomplete'
    assert failed.previous_complete_id == baseline.id and failed.new_candidates_count == 0
    database = access_app[1].state.database
    assert count(database, RecallDiscoveryCandidate) == 1 and count(database, RecallDiscoveryNotification) == 0
    with database.sessions() as db:
        _, event_model = journal_models('recall_discovery')
        terminal = db.scalar(select(event_model).where(event_model.run_id == failed.id))
        assert terminal.state == 'failed'


@pytest.mark.parametrize('mutation,expected', [('pause', 'source_access_changed'), ('aba', 'source_access_changed'), ('notes', None)])
def test_discovery_source_management_fence(access_app, monkeypatch, mutation, expected):
    job_id, _ = seed(access_app)
    adapter = access_app[2]['search']
    fetch = adapter.fetch
    mutated = False

    async def change(*args, **kwargs):
        nonlocal mutated
        response = await fetch(*args, **kwargs)
        if not mutated:
            mutated = True
            mutate_source(access_app, 'search', mutation)
        return response

    monkeypatch.setattr(adapter, 'fetch', change)
    _, result, run = scan(access_app, job_id)
    assert result['reason'] == expected
    assert run.coverage == ('complete' if expected is None else 'incomplete')
    if expected:
        assert count(access_app[1].state.database, RecallDiscoveryCandidate) == 0
        assert count(access_app[1].state.database, RawCapture) == 1
        with access_app[1].state.database.sessions() as db:
            page, = db.scalars(select(RecallDiscoveryPage)).all()
            capture, = db.scalars(select(RawCapture)).all()
            assert page.query_id == capture.query_id and page.verification_id is None
            assert page.raw_bytes == run.raw_bytes == capture.byte_count and run.pages_completed == 0


def test_304_reuse_counts_the_full_page_raw_size(access_app):
    job_id, _ = seed(access_app)
    _, _, first = scan(access_app, job_id)
    access_app[2]['search'].not_modified = True
    _, _, second = scan(access_app, job_id)
    assert second.coverage == 'complete' and second.raw_bytes == first.raw_bytes
    assert second.page_operations == 2 and second.new_candidates_count == 0
    assert count(access_app[1].state.database, RawCapture) == 2  # Two baseline passes only.


def test_time_budget_records_pages_without_candidate_commit(access_app, monkeypatch):
    job_id, _ = seed(access_app)
    ticks = [0.0]
    fetch = access_app[2]['search'].fetch

    async def slow(*args, **kwargs):
        result = await fetch(*args, **kwargs)
        ticks[0] = 301.0
        return result

    monkeypatch.setattr(access_app[2]['search'], 'fetch', slow)
    _, result, run = scan(access_app, job_id, clock=lambda: ticks[0])
    assert result['reason'] == 'discovery_time_budget_exceeded' and run.coverage == 'incomplete'
    assert run.pages_completed == 1 and count(access_app[1].state.database, RecallDiscoveryCandidate) == 0


def test_raw_budget_is_cumulative_including_304(access_app, monkeypatch):
    job_id, _ = seed(access_app)
    _, _, baseline = scan(access_app, job_id)
    access_app[2]['search'].not_modified = True
    monkeypatch.setattr(queue, 'MAX_RAW_BYTES', baseline.raw_bytes // 2 + 1)
    _, result, run = scan(access_app, job_id)
    assert result['reason'] == 'discovery_raw_budget_exceeded' and run.coverage == 'incomplete'
    assert run.raw_bytes <= queue.MAX_RAW_BYTES and run.page_operations == 2
    assert count(access_app[1].state.database, RecallDiscoveryNotification) == 0


@pytest.mark.parametrize('products,operations', [(0, 2), (200, 40)])
def test_empty_and_maximum_supported_scope_are_fully_scanned(access_app, products, operations):
    job_id, _ = seed(access_app)
    access_app[2]['search'].products = [product(index, index == products) for index in range(1, products + 1)]
    _, _, run = scan(access_app, job_id)
    assert run.coverage == 'complete' and run.page_operations == run.pages_completed == operations
    assert run.products_count == products
    assert run.pass_fingerprints[0] == run.pass_fingerprints[1]
    assert len(access_app[2]['search'].calls) == operations


def test_page_timeout_keeps_exact_query_raw_receipt(access_app, monkeypatch):
    job_id, _ = seed(access_app)
    adapter = access_app[2]['search']
    fetch = adapter.fetch

    async def receive_then_wait(*args, **kwargs):
        await fetch(*args, **kwargs)
        await asyncio.sleep(1)

    monkeypatch.setattr(adapter, 'fetch', receive_then_wait)
    monkeypatch.setattr(queue, 'MAX_SECONDS', 0.1)
    _, result, run = scan(access_app, job_id)
    assert result['reason'] == 'discovery_time_budget_exceeded'
    assert run.coverage == 'incomplete' and run.page_operations == 1 and run.pages_completed == 0
    with access_app[1].state.database.sessions() as db:
        page, = db.scalars(select(RecallDiscoveryPage)).all()
        capture, = db.scalars(select(RawCapture)).all()
        assert page.query_id == capture.query_id and page.verification_id is None
        assert page.raw_bytes == run.raw_bytes == capture.byte_count


def test_cached_200_then_aba_receipt_counts_new_raw_not_old_snapshot(access_app, monkeypatch):
    job_id, _ = seed(access_app)
    _, _, baseline = scan(access_app, job_id)
    adapter = access_app[2]['search']
    adapter.products[0]['campaigns'][0]['summary'] = 'Synthetic new larger body ' * 20
    fetch = adapter.fetch

    async def change_after_raw(*args, **kwargs):
        result = await fetch(*args, **kwargs)
        mutate_source(access_app, 'search', 'aba')
        return result

    monkeypatch.setattr(adapter, 'fetch', change_after_raw)
    claim, result, run = scan(access_app, job_id)
    assert result['reason'] == 'source_access_changed' and run.coverage == 'incomplete'
    with access_app[1].state.database.sessions() as db:
        page, = db.scalars(select(RecallDiscoveryPage).where(RecallDiscoveryPage.attempt_id == claim['attempt_id'])).all()
        capture = db.scalar(select(RawCapture).where(RawCapture.query_id == page.query_id))
        assert page.snapshot_id is None and page.verification_id is None
        assert page.raw_bytes == capture.byte_count == run.raw_bytes
        assert page.raw_bytes != baseline.raw_bytes // 2
        assert run.pages_completed == 0 and run.page_operations == 1


@pytest.mark.parametrize('old_kind', ['recall', 'discovery'])
def test_revision_during_held_fetch_keeps_cross_queue_reservation_until_return(access_app, monkeypatch, old_kind):
    job_id, rule_id = seed(access_app)
    client, app, adapters = access_app
    created = client.post('/v1/recall-monitor-rules', json={'name': 'Synthetic held campaign',
        'query': {'campaign_number': '23T001000'}, 'enabled': True}).json()
    database = app.state.database
    held, release = asyncio.Event(), asyncio.Event()
    adapter = adapters['recall' if old_kind == 'recall' else 'search']
    fetch = adapter.fetch

    async def wait(*args, **kwargs):
        held.set()
        await release.wait()
        return await fetch(*args, **kwargs)

    monkeypatch.setattr(adapter, 'fetch', wait)

    async def run():
        task = asyncio.create_task(monitor.run_recall_cycle(database, max_jobs=1, adapter=adapter) if old_kind == 'recall'
            else monitor.run_recall_discovery_cycle(database, max_jobs=1, adapter=adapter))
        await asyncio.wait_for(held.wait(), timeout=3)
        if old_kind == 'recall':
            edited = client.post('/v1/recall-monitor-rules/' + created['id'] + '/revisions',
                json={'expected_revision': 1, 'name': 'Synthetic changed campaign rule', 'enabled': True})
            assert edited.status_code == 200
        else:
            with database.sessions() as db:
                db.add(RecallDiscoveryRuleRevision(id=uid(), rule_id=rule_id, revision=2,
                    name='Synthetic changed search rule', enabled=True, archived=False, interval_seconds=3600))
                db.commit()
        other_queue = queue if old_kind == 'recall' else recall_monitoring
        assert other_queue.claim_job(database) is None
        release.set()
        result = await asyncio.wait_for(task, timeout=3)
        assert result['results'][0]['state'] == 'lease_lost'
        assert other_queue.claim_job(database) is None  # Real completion starts the shared cooldown.
        assert other_queue.claim_job(database, now=utcnow() + timedelta(seconds=3)) is not None

    asyncio.run(run())
    with database.sessions() as db:
        run_model = RecallMonitorRun if old_kind == 'recall' else RecallDiscoveryRun
        interrupted = db.scalar(select(run_model))
        assert interrupted.state == 'lease_lost'
        _, event_model = journal_models('recall' if old_kind == 'recall' else 'recall_discovery')
        event = db.scalar(select(event_model).where(event_model.run_id == interrupted.id))
        assert event.state == 'interrupted'
        if old_kind == 'discovery':
            page, = db.scalars(select(RecallDiscoveryPage)).all()
            capture, = db.scalars(select(RawCapture)).all()
            assert page.query_id == capture.query_id and page.verification_id is None
            assert interrupted.page_operations == 1 and interrupted.pages_completed == 0
            assert interrupted.raw_bytes == page.raw_bytes == capture.byte_count
    assert count(database, RecallDiscoveryCandidate) == count(database, RecallDiscoveryNotification) == 0


@pytest.mark.parametrize('transition', ['unchanged', 'pause', 'aba'])
def test_final_commit_rechecks_persisted_parser_selection(access_app, monkeypatch, transition):
    """Synthetic DB pins bind real fixture queries; no bundle sealing or child."""
    from tire_api.parser_release_models import ParserBundle, ParserDeploymentRevision, ParserSelection
    job_id, _ = seed(access_app)
    database = access_app[1].state.database
    descriptor = {'parser_version': 'synthetic-search@1', 'parser_digest': 'b' * 64}
    with database.sessions() as db:
        db.add(ParserBundle(id='a' * 64, manifest={'synthetic': True}, descriptors={},
            operator='Synthetic tester', reason='Private persisted selection fence only', origin='synthetic-test'))
        db.flush()
        original = ParserDeploymentRevision(id=uid(), source_id='nhtsa-us-recalls', revision=1,
            state='active', bundle_id='a' * 64, descriptor=descriptor, action='bootstrap',
            actor_session_id='synthetic-test', idempotency_key=uid(), request_hash='d' * 64,
            operator='Synthetic tester', reason='Private persisted selection fence only')
        db.add(original)
        db.commit()

    service_type = queue.RecallDiscoveryService

    class PinnedFixtureService(service_type):
        def __init__(self, db, adapter, *, ingestion_guard=None, on_query_started=None):
            def started(query_id):
                db.add(ParserSelection(query_run_id=query_id, source_id='nhtsa-us-recalls',
                    deployment_id=original.id, bundle_id=original.bundle_id, deployment_revision=1,
                    descriptor=descriptor))
                db.commit()
                if on_query_started:
                    on_query_started(query_id)
            super().__init__(db, adapter, ingestion_guard=ingestion_guard, on_query_started=started)

    monkeypatch.setattr(queue, 'RecallDiscoveryService', PinnedFixtureService)
    claim = due_claim(access_app, job_id)
    result = asyncio.run(queue.execute_scan(database, claim, access_app[2]['search'], sleep=no_sleep))
    assert result['state'] == 'discovery_complete'
    assert count(database, ParserSelection) == 2
    if transition != 'unchanged':
        with database.sessions() as db:
            for revision, state in ([(2, 'paused')] if transition == 'pause' else [(2, 'paused'), (3, 'active')]):
                db.add(ParserDeploymentRevision(id=uid(), source_id=original.source_id, revision=revision,
                    state=state, bundle_id=original.bundle_id, descriptor=descriptor,
                    action='pause' if state == 'paused' else 'rollback', actor_session_id='synthetic-test',
                    idempotency_key=uid(), request_hash='d' * 64, operator='Synthetic tester',
                    reason='Synthetic change after last page and before final commit'))
            db.commit()
    assert queue.finish_job(database, claim, result['state'], result['reason'], usage=result['usage'])
    with database.sessions() as db:
        run = db.scalar(select(RecallDiscoveryRun).where(RecallDiscoveryRun.attempt_id == claim['attempt_id']))
        assert run.coverage == ('complete' if transition == 'unchanged' else 'incomplete')
        assert run.reason == (None if transition == 'unchanged' else 'discovery_parser_changed')
        assert run.pages_completed == 2 and len(run.pass_fingerprints) == 2
    assert count(database, RecallDiscoveryCandidate) == (1 if transition == 'unchanged' else 0)
    assert count(database, RecallDiscoveryNotification) == 0


@pytest.mark.parametrize('slow_stage', ['candidate', 'notification', 'terminal'])
def test_finalization_deadline_rolls_back_complete_writes_before_incomplete_receipt(access_app, monkeypatch, slow_stage):
    from sqlalchemy.orm import Session
    job_id, _ = seed(access_app)
    database = access_app[1].state.database
    _, _, baseline = scan(access_app, job_id)
    extra = deepcopy(access_app[2]['search'].products[0]['campaigns'][0])
    extra['campaign_number'] = '26T009000'
    access_app[2]['search'].products[0]['campaigns'].append(extra)
    access_app[2]['search'].products[0]['recalls_count'] = 2
    claim = due_claim(access_app, job_id)
    result = asyncio.run(queue.execute_scan(database, claim, access_app[2]['search'], sleep=no_sleep))
    assert result['state'] == 'discovery_complete'
    before_pages, before_raw = count(database, RecallDiscoveryPage), count(database, RawCapture)
    _, event_model = journal_models('recall_discovery')
    watched = {'candidate': RecallDiscoveryCandidate, 'notification': RecallDiscoveryNotification,
               'terminal': event_model}[slow_stage]
    now = [claim['started_at'] + timedelta(seconds=1)]
    delayed = []
    original_flush = Session.flush

    def flush_then_advance(session, *args, **kwargs):
        crosses = not delayed and any(isinstance(row, watched) and (
            slow_stage != 'terminal' or row.phase == 'finished') for row in session.new)
        answer = original_flush(session, *args, **kwargs)
        if crosses:
            delayed.append(True)
            now[0] = claim['started_at'] + timedelta(seconds=301)
        return answer

    monkeypatch.setattr(queue, 'utcnow', lambda: now[0])
    monkeypatch.setattr(Session, 'flush', flush_then_advance)
    assert queue.finish_job(database, claim, result['state'], result['reason'], usage=result['usage'])
    assert delayed == [True]
    with database.sessions() as db:
        run, = db.scalars(select(RecallDiscoveryRun).where(RecallDiscoveryRun.attempt_id == claim['attempt_id'])).all()
        assert run.coverage == 'incomplete' and run.reason == 'discovery_time_budget_exceeded'
        assert run.previous_complete_id == baseline.id and run.new_candidates_count == 0
        assert run.elapsed_seconds >= 301
        assert set(db.scalars(select(RecallDiscoveryCandidate.campaign_number))) == {'26T008000'}
        assert db.scalar(select(func.count()).select_from(RecallDiscoveryNotification)) == 0
        terminal, = db.scalars(select(event_model).where(event_model.attempt_id == claim['attempt_id'],
                                                       event_model.phase == 'finished')).all()
        assert terminal.state == 'failed' and terminal.run_id == run.id
        assert db.get(RecallDiscoveryJob, job_id).lease_token is None
    assert count(database, RecallDiscoveryPage) == before_pages and count(database, RawCapture) == before_raw
