"""Durable scheduled rules; optional legacy single-process watch refresh.

Scheduled claims use database leases and fenced ingestion. No external delivery.
"""

import argparse
import asyncio
import json
import os
from datetime import timedelta
from functools import wraps
from pathlib import Path

from sqlalchemy import desc, select

from tire_api.adapters import registry
from tire_api.db import Database, FactVersion, TireVariant, UserSession, WatchItem, uid, utcnow
from tire_api.domain import LiveQueryRequest
from tire_api.service import QueryService
from tire_api.monitoring import LeaseLost, claim_job, finish_job, guard_claim
from tire_api.source_settings import SourceAccessBlocked
from tire_api.telemetry import TelemetryRuntime, observe


def observed_cycle(function):
    """Use the caller's process runtime; importing a worker never starts one."""
    @wraps(function)
    async def measured(*args, **kwargs):
        with observe("worker.cycle", component="worker") as span:
            result = await function(*args, **kwargs)
            rows = result["results"]
            outcome = "completed" if rows else "idle"
            for state in ("worker_error", "lease_lost", "source_unavailable", "discovery_incomplete", "local_snapshot", "consent_required"):
                if any(row["state"] == state for row in rows):
                    outcome = 'source_unavailable' if state == 'discovery_incomplete' else state
                    break
            else:
                if any(row.get("finalized") is False for row in rows):
                    outcome = "stale"
            span.finish(outcome)
            return result
    return measured


def begin_attempt(database, claim, guard):
    """Record entry to the service, not an inferred HTTP/Parser stage."""
    from tire_api.monitor_tasks import mark_running_locked
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        guard(db, claim)
        if not mark_running_locked(db, claim):
            raise LeaseLost('monitor_attempt_not_running')
        db.commit()


def interrupt_attempt(database, claim, error):
    from tire_api.monitor_tasks import interrupt_attempt_locked
    allowed = {'monitor_lease_lost', 'recall_monitor_lease_lost',
               'recall_monitor_rule_disabled', 'monitor_attempt_not_running',
               'recall_monitor_rule_changed', 'recall_discovery_lease_lost',
               'recall_discovery_rule_disabled', 'recall_discovery_rule_changed'}
    reason = str(error) if str(error) in allowed else 'monitor_lease_lost'
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        interrupt_attempt_locked(db, claim, reason)
        db.commit()


@observed_cycle
async def run_scheduled_cycle(database: Database, *, max_jobs: int = 100) -> dict:
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        if db.get(UserSession, "scheduled-monitor-worker") is None:
            db.add(UserSession(id="scheduled-monitor-worker", expires_at=utcnow() + timedelta(days=365)))
        db.commit()
    results = []
    for index in range(max_jobs):
        if index:
            await asyncio.sleep(2.1)
        claim = claim_job(database)
        if claim is None:
            break
        with observe("worker.job", component="worker", source=claim["source_id"]) as span:
            if "queue_lag_seconds" in claim:
                span.finish("unknown", queue_lag_seconds=claim["queue_lag_seconds"])
            query_id = None
            try:
                begin_attempt(database, claim, guard_claim)
                with database.sessions() as db:
                    response = await QueryService(db, registry, ingestion_guard=lambda session: guard_claim(session, claim)).execute(
                        claim["source_id"], LiveQueryRequest(query=claim["query"], fallback_policy="never"),
                        "scheduled-monitor-worker", audience='background_monitor')
                state, reason = response["data_state"], response.get("reason")
                query_id = response.get('query_id')
            except LeaseLost as error:
                interrupt_attempt(database, claim, error)
                span.finish("lease_lost")
                results.append({"job_id": claim["id"], "state": "lease_lost"})
                continue
            except SourceAccessBlocked as error:
                state, reason = 'source_unavailable', error.code
            except Exception:
                state, reason = "worker_error", "monitor_execution_failed"
            finalized = finish_job(database, claim, state, reason[:100] if reason else None, query_id=query_id)
            span.finish(state if finalized else "stale")
            results.append({"job_id": claim["id"], "state": state, "reason": reason, "finalized": finalized})
    recalls = await run_recall_cycle(database, max_jobs=max_jobs)
    discovery = await run_recall_discovery_cycle(database, max_jobs=max_jobs)
    return {"checked_at": utcnow().isoformat(), "jobs": len(results) + recalls["jobs"] + discovery['jobs'],
            "results": results + recalls["results"] + discovery['results']}


@observed_cycle
async def run_recall_cycle(database: Database, *, max_jobs: int = 100, adapter=None) -> dict:
    """Independent campaign queue; never reads fallback answers or sends messages."""
    from tire_api.adapters import nhtsa
    from tire_api.recall_models import RecallLiveRequest
    from tire_api.recalls import RecallService
    from tire_api.recall_monitoring import (claim_job as claim_recall, finish_job as finish_recall,
                                           guard_claim as guard_recall, interrupt_job as interrupt_recall)
    results = []
    for index in range(max_jobs):
        if index:
            await asyncio.sleep(2.1)
        claim = claim_recall(database)
        if claim is None:
            break
        with observe("worker.job", component="worker", source=claim["source_id"]) as span:
            if "queue_lag_seconds" in claim:
                span.finish("unknown", queue_lag_seconds=claim["queue_lag_seconds"])
            query_id = None
            try:
                begin_attempt(database, claim, guard_recall)
                with database.sessions() as db:
                    response = await RecallService(db, adapter or nhtsa,
                        ingestion_guard=lambda session: guard_recall(session, claim)).execute(
                            RecallLiveRequest(query=claim["query"], fallback_policy="never"), claim["session_id"],
                            audience='background_monitor')
                state, reason = response["data_state"], response.get("reason")
                query_id = response.get('query_id')
            except LeaseLost as error:
                interrupt_recall(database, claim, str(error))
                span.finish("lease_lost")
                results.append({"job_id": claim["id"], "source": claim["source_id"], "state": "lease_lost"})
                continue
            except SourceAccessBlocked as error:
                state, reason = 'source_unavailable', error.code
            except Exception:
                state, reason = "worker_error", "recall_monitor_execution_failed"
            finalized = finish_recall(database, claim, state, reason[:100] if reason else None, query_id=query_id)
            span.finish(state if finalized else "stale")
            results.append({"job_id": claim["id"], "source": claim["source_id"],
                            "state": state, "reason": reason, "finalized": finalized})
    return {"checked_at": utcnow().isoformat(), "jobs": len(results), "results": results}


@observed_cycle
async def run_recall_discovery_cycle(database: Database, *, max_jobs: int = 100, adapter=None) -> dict:
    from tire_api import recall_discovery_monitoring as queue
    results = []
    for index in range(max_jobs):
        if index:
            await asyncio.sleep(queue.SOURCE_INTERVAL)
        claim = queue.claim_job(database)
        if claim is None:
            break
        with observe('worker.job', component='worker', source=claim['source_id']) as span:
            usage = None
            try:
                begin_attempt(database, claim, queue.guard_claim)
                response = await queue.execute_scan(database, claim, adapter)
                state, reason, usage = response['state'], response['reason'], response['usage']
            except LeaseLost as error:
                queue.interrupt_job(database, claim, str(error))
                span.finish('lease_lost')
                results.append({'job_id': claim['id'], 'source': claim['source_id'], 'kind': 'recall_discovery', 'state': 'lease_lost'})
                continue
            except SourceAccessBlocked as error:
                state, reason = 'discovery_incomplete', error.code
            except Exception:
                state, reason = 'discovery_incomplete', 'recall_discovery_execution_failed'
            finalized = queue.finish_job(database, claim, state, reason, usage=usage)
            if finalized:
                state, reason = claim['final_result']['state'], claim['final_result']['reason']
            span.finish('completed' if finalized and state == 'discovery_complete' else 'source_unavailable' if finalized else 'stale')
            results.append({'job_id': claim['id'], 'source': claim['source_id'], 'kind': 'recall_discovery',
                            'state': state, 'reason': reason, 'finalized': finalized})
    return {'checked_at': utcnow().isoformat(), 'jobs': len(results), 'results': results}


@observed_cycle
async def run_cycle(database: Database) -> dict:
    jobs: dict[tuple[str, str, str], None] = {}
    with database.sessions() as db:
        variant_ids = db.scalars(select(WatchItem.variant_id).distinct()).all()
        for variant_id in variant_ids:
            variant = db.get(TireVariant, variant_id)
            fact = db.scalar(select(FactVersion).where(FactVersion.variant_id == variant_id)
                             .order_by(desc(FactVersion.observed_at)).limit(1))
            if variant is not None and fact is not None:
                jobs[(fact.source_id, variant.identity["model"], variant.identity["size"])] = None
        # Reuse a bounded worker identity rather than creating a user session each cycle.
        worker = db.get(UserSession, "monitor-worker")
        if worker is None:
            worker = UserSession(id="monitor-worker", expires_at=utcnow() + timedelta(days=365))
            db.add(worker)
            db.commit()
    results = []
    for index, (source, model, size) in enumerate(jobs):
        if index:
            await asyncio.sleep(2.1)
        with observe("worker.job", component="worker", source=source) as span:
            with database.sessions() as db:
                response = await QueryService(db, registry).execute(source,
                    LiveQueryRequest(query={"model": model, "size": size}, fallback_policy="never"),
                    "monitor-worker", audience='background_monitor')
                span.finish(response["data_state"])
                results.append({"source": source, "state": response["data_state"], "reason": response.get("reason")})
    recalls = await run_recall_cycle(database)
    discovery = await run_recall_discovery_cycle(database)
    return {"checked_at": utcnow().isoformat(), "jobs": len(jobs) + recalls["jobs"] + discovery['jobs'],
            "results": results + recalls["results"] + discovery['results']}


async def main() -> None:
    parser = argparse.ArgumentParser(description="轮胎监控规则 Worker（持久租约）")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--legacy-watchlists", action="store_true", help="旧关注列表单实例刷新；不代替监控规则")
    parser.add_argument("--interval", type=int, default=None, help="检查周期秒数；规则模式默认 60，旧关注模式默认 21600")
    parser.add_argument("--metrics-port", type=int, default=None, help="显式开启本机指标读取端口（1024–65535）；默认不监听")
    args = parser.parse_args()
    interval = args.interval if args.interval is not None else 21600 if args.legacy_watchlists else 60
    if interval < (300 if args.legacy_watchlists else 10):
        parser.error("interval is below the supported polling minimum")
    if args.metrics_port is not None and not 1024 <= args.metrics_port <= 65535:
        parser.error("metrics-port must be between 1024 and 65535")
    root = Path(__file__).resolve().parents[2]
    url = os.getenv("TIRE_DATABASE_URL") or os.getenv("DATABASE_URL") or f"sqlite:///{(root / 'data/dev.db').as_posix()}"
    database = Database(url)
    telemetry = TelemetryRuntime.from_env("tire-worker")
    try:
        database.initialize()
        if args.metrics_port is not None:
            endpoint = telemetry.start_metrics_server(args.metrics_port)
            print(json.dumps(endpoint, ensure_ascii=False), flush=True)
        with telemetry.scope():
            while True:
                cycle = await run_cycle(database) if args.legacy_watchlists else await run_scheduled_cycle(database)
                print(json.dumps(cycle, ensure_ascii=False), flush=True)
                if args.once:
                    break
                await asyncio.sleep(interval)
    finally:
        try:
            database.close()
        finally:
            telemetry.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
