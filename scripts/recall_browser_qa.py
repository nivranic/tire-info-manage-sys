"""Private synthetic recall UI acceptance; never opens the normal development DB.

Run: uv run --project apps/api --extra dev python scripts/recall_browser_qa.py
Append --self-test for in-process validation without binding a port.
The optional server uses 127.0.0.1:8001 and a dedicated HttpOnly cookie.
Synthetic HTTP-shaped JSON is parsed by the fixed in-process NHTSA parser,
then ingested through production services. This is not a subprocess, real-source,
or model acceptance test. No fixture route is registered in the production app.
"""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Literal

from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import Field, StrictBool, StrictInt
from sqlalchemy import func, select
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/worker"))
from monitor import run_recall_cycle
from tire_api.adapters import nhtsa
from tire_api.ai_models import AIRequest
from tire_api.db import FactVersion, QueryRun, RawCapture, Snapshot, TireVariant, utc, utcnow
from tire_api.domain import StrictModel
from tire_api.embedding_models import EmbeddingRequest
from tire_api.main import create_app
from tire_api.recall_discovery import RecallSearchSnapshot, RecallSearchVerification
from tire_api.recall_models import (RecallEvent, RecallMonitorJob, RecallMonitorRule, RecallMonitorRun,
    RecallNotification, RecallRevision, RecallRuleRevision, RecallSnapshot, RecallVerification)
from tire_api.service import QueryService

CANARY = '<script>window.recallCanary=1</script>'
CAMPAIGN, SECOND_CAMPAIGN = "23T001000", "26T008000"
IDENTITY = {"bundle_id": "a" * 64, "parser_digest": "b" * 64, "deployment_revision": 1}
TABLES = (TireVariant, Snapshot, FactVersion, QueryRun, RawCapture, RecallSnapshot, RecallVerification,
    RecallRevision, RecallEvent, RecallSearchSnapshot, RecallSearchVerification, RecallMonitorRule,
    RecallRuleRevision, RecallMonitorRun, RecallNotification, AIRequest, EmbeddingRequest)


class NoExternalSources:
    def sources(self):
        return [{**nhtsa.source_metadata(), "name": "NHTSA · 显式合成召回验收",
            "description": "仅隔离 UI 验收的合成传输，不是真实官方召回结论。",
            "parser_version": "synthetic-browser-recall@1"}]

    async def fetch(self, *_args, **_kwargs):
        return {"status": "unavailable", "reason": "synthetic_fixture_has_no_tire_sources"}


class Control(StrictModel):
    mode: Literal["success", "empty", "offline", "forbidden", "not_modified"] | None = None
    search_case: Literal["single", "second_page"] | None = None
    delay_next_ms: StrictInt | None = Field(default=None, ge=0, le=10000)
    increment_revision: StrictBool = False


class SyntheticRecallAdapter:
    supports_parser_deployments = False

    def __init__(self):
        self.mode = "success"
        self.search_case = "single"
        self.delay_next_ms = 0
        self.revision = 1
        self.calls = []

    def summary(self, revision):
        return f"SYNTHETIC ONLY / 合成 UI 验收，非真实风险结论。Revision {revision}. " + CANARY

    def campaign_body(self, number, revision, empty):
        row = {"NHTSACampaignNumber": number, "Manufacturer": "Synthetic Tire Manufacturer",
            "ReportReceivedDate": "02/03/2023", "Component": "TIRES", "PotentialNumberofUnitsAffected": 123,
            "Summary": self.summary(revision), "Consequence": "Synthetic consequence only. " + CANARY,
            "Remedy": "Synthetic remedy only; check the original DOT/TIN production scope.",
            "Notes": "Synthetic notes. " + CANARY, "Make": "SYNTHETIC GENERAL",
            "Model": "ALTIMAX RT43" if number == CAMPAIGN else "SYNTHETIC ROADBREAKER", "ModelYear": "9999"}
        return {"Count": 0 if empty else 1, "Message": "Results returned successfully", "results": [] if empty else [row]}

    def search_body(self, query, revision, empty, search_case):
        total = 0 if empty else 11 if search_case == "second_page" else 1
        offset = int(query["offset"])
        products = []
        for index in range(offset, min(offset + 10, total)):
            number = SECOND_CAMPAIGN if search_case == "second_page" else CAMPAIGN
            has_campaign = search_case != "second_page" or index == 10
            campaign = {"nhtsaCampaignNumber": number, "subject": "SYNTHETIC recall candidate " + CANARY,
                "reportReceivedDate": "2023-03-02T00:00:00Z", "manufacturer": "Synthetic Tire Manufacturer",
                "summary": self.summary(revision), "consequence": "Synthetic consequence " + CANARY,
                "correctiveAction": "Synthetic remedy; verify DOT/TIN and production scope.", "notes": CANARY,
                "associatedDocumentsCount": 1, "associatedProductsCount": 1,
                "associatedDocuments": [{"url": "https://static.nhtsa.gov/odi/rcl/2023/RCLRPT-23T001-0000.PDF",
                    "summary": "Synthetic fixture document reference; not fetched"}],
                "associatedProducts": [{"brand": "SYNTHETIC", "tireline": "SYNTHETIC PRODUCT", "scope": CANARY}]}
            products.append({"id": index + 1, "artemisId": 1000 + index, "brand": "SYNTHETIC GENERAL",
                "tireline": f"SYNTHETIC PRODUCT {index + 1}", "size": "215/60R16",
                "recallsCount": int(has_campaign), "safetyIssues": {"recalls": [campaign] if has_campaign else []}})
        page = {"offset": offset, "max": 10, "count": len(products), "total": total, "sort": "productName", "order": "asc",
            "currentUrl": nhtsa.query_url(query),
            "nextUrl": nhtsa.query_url({**query, "offset": str(offset + 10)}) if offset + len(products) < total else None,
            "previousUrl": nhtsa.query_url({**query, "offset": str(max(0, offset - 10))}) if offset else None}
        return {"meta": {"status": 200, "messages": [], "pagination": page}, "results": products}

    async def fetch(self, query, cached=None, *, on_observation=None):
        mode, revision, search_case, delay = self.mode, self.revision, self.search_case, self.delay_next_ms
        self.delay_next_ms = 0
        call = {"query": deepcopy(query), "mode": mode, "revision": revision, "delay_ms": delay, "completed": False}
        self.calls.append(call)
        if delay:
            await asyncio.sleep(delay / 1000)
        if mode in {"offline", "forbidden"}:
            call["completed"] = True
            return {"status": "unavailable", "reason": "synthetic_http_403" if mode == "forbidden" else "synthetic_offline"}
        observation = {"status": "ok", "url": nhtsa.query_url(query), "content_type": "application/json",
            "parser_version": "synthetic-browser-recall@1", "parser_identity": deepcopy(IDENTITY),
            "etag": f'"synthetic-{revision}-{search_case}-{mode}"', "last_modified": None}
        if mode == "not_modified":
            call["completed"] = True
            return {**observation, "status": "not_modified", "etag": cached.get("etag") if cached else None}
        envelope = (self.search_body(query, revision, mode == "empty", search_case) if "search" in query
            else self.campaign_body(query["campaign_number"], revision, mode == "empty"))
        observation["body"] = json.dumps(envelope, ensure_ascii=False, sort_keys=True)
        # The durable receipt precedes parsing, just as in the real transport path.
        if on_observation:
            on_observation(observation)
        parsed = nhtsa.parse_json(observation["body"], query)
        observation["discovery" if "search" in query else "records"] = parsed
        call["completed"] = True
        return observation


@contextmanager
def fixture_application(directory):
    import tire_api.main as api_module
    settings = {"TI_AI_ENABLED": "0", "TI_EMBEDDINGS_ENABLED": "0", "TI_DISABLED_SOURCES": "",
        "TI_OBJECT_STORE_BACKEND": "filesystem", "TI_OBJECT_STORE_ROOT": str(directory / "objects"),
        "TIRE_CORS_ORIGINS": "http://localhost:3001,http://127.0.0.1:3001"}
    previous = {name: os.environ.get(name) for name in settings}
    old_cookie = api_module.SESSION_COOKIE
    os.environ.update(settings)
    api_module.SESSION_COOKIE = "tire_recall_qa_session"
    app = None
    try:
        adapter = SyntheticRecallAdapter()
        app = create_app("sqlite:///" + (directory / "qa.db").as_posix(), NoExternalSources())
        app.state.recall_adapter = adapter
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8001))

        @app.get("/fixture/state")
        def state():
            with app.state.database.sessions() as db:
                counts = {table.__tablename__: db.scalar(select(func.count()).select_from(table)) for table in TABLES}
                runs = [{"query": row.query, "state": row.state, "fallback_policy": row.fallback_policy}
                    for row in db.scalars(select(QueryRun).order_by(QueryRun.created_at).limit(200))]
            return {"environment": "private_synthetic_recall_ui_qa", "synthetic": True,
                "mode": adapter.mode, "search_case": adapter.search_case, "revision": adapter.revision,
                "delay_next_ms": adapter.delay_next_ms, "source_calls": len(adapter.calls), "calls": adapter.calls[-100:],
                "real_source_calls": 0, "real_model_calls": 0, "model_calls": 0, "embedding_calls": 0,
                "isolated_parser_calls": 0, "parser_execution": "fixed_in_process_parser_of_synthetic_json",
                "counts": counts, "query_runs": runs, "canary": CANARY}

        @app.post("/fixture/control")
        def control(payload: Control):
            if payload.mode is not None:
                adapter.mode = payload.mode
            if payload.search_case is not None:
                adapter.search_case = payload.search_case
            if payload.delay_next_ms is not None:
                adapter.delay_next_ms = payload.delay_next_ms
            if payload.increment_revision:
                adapter.revision += 1
            return {"synthetic": True, "mode": adapter.mode, "search_case": adapter.search_case,
                "revision": adapter.revision, "delay_next_ms": adapter.delay_next_ms}

        @app.post("/fixture/run-worker-once")
        async def worker(request: Request):
            # Fixed current-session queue only. No production DB, input URL or module is accepted.
            with app.state.database.sessions() as db:
                QueryService(db, None).lock_ingestion()
                jobs = db.scalars(select(RecallMonitorJob).where(RecallMonitorJob.session_id == request.state.session_id)).all()
                for job in jobs:
                    job.next_due_at = utcnow() - timedelta(seconds=1)
                recent = db.scalar(select(func.max(RecallMonitorRun.finished_at)))
                db.commit()
            # Respect the real queue's inter-run spacing instead of modifying immutable run history.
            if recent:
                await asyncio.sleep(max(0, 2.2 - (utcnow() - utc(recent)).total_seconds()))
            result = await run_recall_cycle(app.state.database, max_jobs=1, adapter=adapter)
            return {"synthetic": True, **result}

        @app.post("/fixture/shutdown")
        def shutdown():
            server.should_exit = True
            return {"synthetic": True, "shutdown_requested": True}

        yield app, server
    finally:
        if app is not None:
            app.state.database.close()
        api_module.SESSION_COOKIE = old_cookie
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def self_test(app):
    checks = []
    with TestClient(app) as client:
        def post(path, body=None, status=200):
            response = client.post(path, json=body)
            assert response.status_code == status, (path, response.status_code, response.text)
            return response.json()

        def live(number=CAMPAIGN, **extra):
            return post("/v1/recalls/live-query", {"query": {"campaign_number": number}, **extra})

        def search(offset=0, **extra):
            return post("/v1/recalls/search", {"query": {"search": "GENERAL ALTIMAX RT43", "offset": offset}, **extra})

        def control(**values):
            return post("/fixture/control", values)

        def grant(result, decision):
            return post("/v1/fallback-consents", {"query_id": result["query_id"], "decision": decision, "scope": "once"}, 201)["id"]

        initial = client.get("/fixture/state").json()
        assert not any(initial["counts"].values())
        assert client.cookies.get("tire_recall_qa_session") and not client.cookies.get("tire_local_session")
        checks.append("private_empty_db_and_dedicated_cookie")

        found = search()
        assert found["data_state"] == "live" and found["products"][0]["campaigns"][0]["campaign_number"] == CAMPAIGN
        first = live()
        raw = client.get(first["provenance"][0]["evidence_path"]).json()
        assert CANARY in raw["body"] and first["records"][0]["report_received_date"] == "2023-03-02"
        assert hashlib.sha256(raw["body"].encode()).hexdigest() == raw["raw_hash"]
        assert nhtsa.parse_json(raw["body"], {"campaign_number": CAMPAIGN}) == first["records"]
        checks.append("search_campaign_fixed_parser_raw_hash_and_date")

        control(mode="not_modified")
        verified = live()
        assert verified["data_state"] in {"live", "live_verified_304"} and verified["provenance"] == first["provenance"]
        checks.append("304_reuses_same_evidence")
        control(mode="offline")
        failed = live()
        assert failed["data_state"] == "consent_required" and failed["records"] == []
        grant(failed, "deny")
        failed = live()
        allowed = live(consent_id=grant(failed, "allow"))
        assert allowed["data_state"] == "local_snapshot" and allowed["records"]
        failed_search = search()
        assert failed_search["products"] == []
        assert search(consent_id=grant(failed_search, "allow"))["data_state"] == "local_snapshot"
        checks.append("campaign_and_search_consent_gates")
        control(mode="forbidden")
        assert live(fallback_policy="never")["data_state"] == "source_unavailable"
        assert search(fallback_policy="never")["reason"] == "synthetic_http_403"
        checks.append("explicit_403_never_fallback")

        control(mode="empty")
        assert live()["records"] == [] and search()["pagination"]["total"] == 0
        assert len(client.get(f"/v1/recalls/{CAMPAIGN}/history?mode=history").json()["revisions"]) == 1
        checks.append("empty_keeps_prior_campaign_revision")
        control(mode="success", search_case="second_page")
        page1, page2 = search(), search(10)
        assert page1["pagination"]["has_next"] and all(not item["campaigns"] for item in page1["products"])
        assert page2["products"][0]["campaigns"][0]["campaign_number"] == SECOND_CAMPAIGN
        assert page1["provenance"][0]["snapshot_id"] != page2["provenance"][0]["snapshot_id"]
        checks.append("second_page_recall_and_separate_evidence")

        control(delay_next_ms=600)
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(live)
            for _ in range(50):
                if app.state.recall_adapter.calls[-1]["delay_ms"] == 600:
                    break
                time.sleep(.01)
            fast = live(SECOND_CAMPAIGN)
            slow = pending.result(timeout=5)
        assert fast["query"]["campaign_number"] == SECOND_CAMPAIGN and slow["query"]["campaign_number"] == CAMPAIGN
        checks.append("one_shot_delay_preserves_query_identity")

        rule = post("/v1/recall-monitor-rules", {"query": {"campaign_number": "27T002000"}, "name": "Synthetic monitor " + CANARY,
            "enabled": False, "interval_seconds": 3600}, 201)
        assert post("/fixture/run-worker-once")["jobs"] == 0
        def revise(expected, *, enabled=False, archived=False):
            return post(f'/v1/recall-monitor-rules/{rule["id"]}/revisions', {"expected_revision": expected,
                "name": rule["name"], "interval_seconds": 3600, "enabled": enabled, "archived": archived})
        rule = revise(1, enabled=True)
        assert post("/fixture/run-worker-once")["results"][0]["state"] in {"live", "live_verified_304"}
        notices = client.get("/v1/recall-notifications?mode=history").json()
        assert notices["total"] == 1 and notices["items"][0]["kind"] == "first_observed"
        control(increment_revision=True)
        assert post("/fixture/run-worker-once")["jobs"] == 1
        changed = client.get("/v1/recall-notifications?mode=history").json()["items"][0]
        assert changed["kind"] == "content_changed" and changed["changes"]["before"] != changed["changes"]["after"]
        assert CANARY in client.get('/v1/recall-evidence/' + changed['previous_snapshot_id'] + '?mode=history').json()['body']
        assert client.put(f'/v1/recall-notifications/{changed["id"]}/read', json={"read": True}).json()["read_at"]
        checks.append("real_worker_first_observed_content_change_and_read")
        rule = revise(rule["revision"], archived=True)
        assert post("/fixture/run-worker-once")["jobs"] == 0
        assert client.get("/v1/recall-monitor-rules?archived=true").json()["total"] == 1
        rule = revise(rule["revision"])
        assert not rule["enabled"] and not rule["archived"]
        with TestClient(app) as other:
            assert other.get("/v1/recall-monitor-rules").json()["total"] == 0
            assert other.get("/v1/recall-notifications?mode=history").json()["total"] == 0
        checks.append("archive_restore_and_session_isolation")
        latest = client.get("/fixture/state").json()
        counts = latest["counts"]
        assert counts["raw_captures"] > 0
        assert counts["ai_requests"] == counts["embedding_requests"] == counts["tire_variants"] == counts["fact_versions"] == counts["snapshots"] == 0
        assert latest["real_source_calls"] == latest["model_calls"] == latest["isolated_parser_calls"] == 0
        checks.append("no_models_no_external_source_no_tire_facts")
        assert post("/fixture/shutdown")["shutdown_requested"]
        return {"synthetic": True, "self_test": "passed", "checks": checks, "ports_opened": 0,
            "source_calls": latest["source_calls"], "counts": counts, "real_source_calls": 0,
            "real_model_calls": 0, "isolated_parser_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="tire-recall-browser-") as folder:
        with fixture_application(Path(folder)) as (app, server):
            if args.self_test:
                print(json.dumps(self_test(app), ensure_ascii=False), flush=True)
            else:
                print(json.dumps({"environment": "private_synthetic_recall_ui_qa", "api": "http://127.0.0.1:8001",
                    "cookie": "tire_recall_qa_session", "state": "GET /fixture/state", "control": "POST /fixture/control",
                    "worker": "POST /fixture/run-worker-once", "shutdown": "POST /fixture/shutdown",
                    "real_source_calls": 0, "real_model_calls": 0, "isolated_parser_calls": 0}, ensure_ascii=False), flush=True)
                server.run()


if __name__ == "__main__":
    main()
