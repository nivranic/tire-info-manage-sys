"""Real NHTSA search -> campaign evidence, plus separately labeled PG simulation.

The live path uses the production adapter, transport and isolated parser. A
network failure is a failed acceptance, never substituted by a recorded fixture.
Reusable PostgreSQL helpers use only synthetic data and never contact NHTSA.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Barrier
import time
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tire_api.db import FactVersion, FallbackConsent, RawCapture, TireVariant, utcnow
from tire_api.domain import digest
from tire_api.main import create_app
from tire_api.parser_release_models import ParserExecution
from tire_api.recall_discovery import RecallSearchSnapshot
from tire_api.recall_models import (RecallEvent, RecallLiveRequest, RecallMonitorJob,
                                   RecallNotification, RecallRevision, RecallSnapshot)
from tire_api.recalls import RecallService

ROOT = Path(__file__).resolve().parents[1]


def accepted(response, expected=200):
    assert response.status_code == expected, f"Unexpected HTTP status: {response.status_code}"
    return response.json()


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def evidence_check(client, provenance):
    evidence = accepted(client.get(provenance["evidence_path"]))
    assert evidence["data_state"] == "local_snapshot"
    assert hashlib.sha256(evidence["body"].encode("utf-8")).hexdigest() == provenance["raw_hash"] == evidence["raw_hash"]
    assert evidence["parser_identity"] == provenance["parser_identity"]
    return evidence


def run_real_acceptance(output: Path, report: dict):
    with tempfile.TemporaryDirectory(prefix="tire-recall-real-") as directory, patch.dict(os.environ, {
        "TI_PARSER_BUNDLE_ROOT": str(Path(directory) / "bundles"), "TI_OBJECT_STORE_BACKEND": "filesystem",
        "TI_OBJECT_STORE_ROOT": str(Path(directory) / "objects"), "TI_AI_ENABLED": "0", "TI_EMBEDDINGS_ENABLED": "0"}):
        app = create_app("sqlite:///" + (Path(directory) / "acceptance.db").as_posix())
        with TestClient(app) as client:
            report["step"] = "real_name_discovery"
            found = accepted(client.post("/v1/recalls/search", json={"query": {
                "search": "XCELLENT ROADBREAKER", "offset": 0}, "fallback_policy": "never"}))
            (output / "real-discovery-response.json").write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
            report["real_source_states"]["discovery"] = {"state": found["data_state"], "reason": found.get("reason")}
            assert found["data_state"] == "live", "real_discovery_unavailable"
            assert found["products"] and all(row["applicability"] == "not_assessed" for row in found["products"])
            candidates = [item for row in found["products"] for item in row["campaigns"]]
            candidate = next((item for item in candidates if item["campaign_number"] == "26T008000"), None)
            assert candidate is not None, "expected_campaign_not_in_current_discovery_page"
            discovery_evidence = evidence_check(client, found["provenance"][0])
            (output / "real-discovery-body.json").write_text(discovery_evidence["body"], encoding="utf-8")
            with app.state.database.sessions() as db:
                assert count(db, RecallSnapshot) == count(db, RecallRevision) == count(db, TireVariant) == count(db, FactVersion) == 0
            report["checks"].append("real_discovery_remains_candidates_without_campaign_or_tire_adoption")
            # Respect the production adapter's source gap; do not reset its clock.
            time.sleep(2.1)
            report["step"] = "real_explicit_campaign_verification"
            campaign = accepted(client.post("/v1/recalls/live-query", json={
                "query": {"campaign_number": candidate["campaign_number"]}, "fallback_policy": "never"}))
            (output / "real-campaign-response.json").write_text(json.dumps(campaign, ensure_ascii=False, indent=2), encoding="utf-8")
            report["real_source_states"]["campaign"] = {"state": campaign["data_state"], "reason": campaign.get("reason")}
            assert campaign["data_state"] == "live" and campaign["records"], "real_campaign_unavailable"
            assert all(row["campaign_number"] == "26T008000" and row["applicability"] == "not_assessed" for row in campaign["records"])
            raw = evidence_check(client, campaign["provenance"][0])
            (output / "real-campaign-body.json").write_text(raw["body"], encoding="utf-8")
            original_rows = json.loads(raw["body"])["results"]
            from datetime import datetime
            expected_dates = {datetime.strptime(row["ReportReceivedDate"], "%d/%m/%Y").date().isoformat() for row in original_rows}
            assert {row["report_received_date"] for row in campaign["records"]} == expected_dates
            assert {row["report_received_date_raw"] for row in campaign["records"]} == {row["ReportReceivedDate"] for row in original_rows}
            assert candidate["report_received_at"][:10] in expected_dates
            report["checks"].extend(["real_explicit_campaign_with_complete_product_records",
                "raw_body_hash_and_parser_identity", "campaign_dd_mm_date_cross_checked_with_discovery_iso_date"])
            report["step"] = "real_parser_receipts_and_raw_objects"
            receipts = []
            with app.state.database.sessions() as db:
                for response in (found, campaign):
                    execution = db.get(ParserExecution, response["query_id"])
                    assert execution and execution.state == "completed" and execution.receipt["reaped"] is True
                    assert execution.receipt["exit_code"] == 0 and execution.receipt["pid"] > 0
                    receipts.append({"query_id": response["query_id"], "state": execution.state, "receipt": execution.receipt})
                captures = db.scalars(select(RawCapture).order_by(RawCapture.observed_at)).all()
                assert len(captures) == 2 and all(row.target_kind == "recall" for row in captures)
                capture_ids = [row.id for row in captures]
                assert count(db, TireVariant) == count(db, FactVersion) == 0
            for identifier in capture_ids:
                capture = accepted(client.get(f"/v1/captures/{identifier}?mode=history"))
                assert hashlib.sha256(capture["body"].encode("utf-8")).hexdigest() == capture["raw_hash"]
            (output / "real-parser-receipts.json").write_text(json.dumps(receipts, ensure_ascii=False, indent=2), encoding="utf-8")
            report["checks"].extend(["actual_isolated_children_completed_and_reaped", "preparser_raw_objects_hash_verified"])
            report["real"] = {"search": found["query"], "pagination": found["pagination"], "campaign_number": "26T008000",
                "product_count": len(campaign["records"]), "source_dates": sorted(expected_dates),
                "discovery_provenance": found["provenance"], "campaign_provenance": campaign["provenance"],
                "model_calls": 0, "applicability": "not_assessed"}
            report["status"] = "passed"


def verify_recall_persistence(url: str) -> dict:
    """Synthetic PostgreSQL behavior; caller guarantees an isolated test database."""
    sys.path.insert(0, str(ROOT / "apps/api/tests"))
    from test_recalls import CAMPAIGN, NoTireSource, RecallFixture
    from test_recall_discovery import SearchFixture
    from tire_api.recall_monitoring import claim_job, finish_job, guard_claim
    from tire_api.monitoring import LeaseLost
    fixture, discovery = RecallFixture(), SearchFixture()

    class CompositeFixture:
        async def fetch(self, query, **kwargs):
            return await (discovery if "search" in query else fixture).fetch(query, **kwargs)

    app = create_app(url, NoTireSource())
    app.state.recall_adapter = CompositeFixture()
    with TestClient(app) as client:
        rule = accepted(client.post("/v1/recall-monitor-rules", json={"name": "PG synthetic recall",
            "query": {"campaign_number": CAMPAIGN}, "enabled": True, "interval_seconds": 3600}), 201)
        payload = {"query": {"campaign_number": CAMPAIGN}, "fallback_policy": "never"}
        first = accepted(client.post("/v1/recalls/live-query", json=payload))
        assert first["data_state"] == "live" and first["revision"] == 1
        accepted(client.post("/v1/recalls/live-query", json=payload))
        fixture.rows[0]["remedy"] = "PG SYNTHETIC changed remedy, not an official announcement"
        changed = accepted(client.post("/v1/recalls/live-query", json=payload))
        assert changed["revision"] == 2
        saved_rows = deepcopy(fixture.rows)
        fixture.rows = []
        empty = accepted(client.post("/v1/recalls/live-query", json=payload))
        assert empty["data_state"] == "live" and empty["records"] == []
        with app.state.database.sessions() as db:
            assert count(db, RecallRevision) == count(db, RecallEvent) == count(db, RecallNotification) == 2
        fixture.rows = saved_rows
        latest = accepted(client.post("/v1/recalls/live-query", json=payload))
        assert latest["revision"] == 2
        search = accepted(client.post("/v1/recalls/search", json={"query": {"search": "SYNTHETIC DEMO", "offset": 0},
            "fallback_policy": "never"}))
        assert search["data_state"] == "live" and search["products"][0]["applicability"] == "not_assessed"
        evidence_check(client, search["provenance"][0])
        with app.state.database.sessions() as db:
            assert count(db, RecallRevision) == 2 and count(db, RecallSearchSnapshot) == 1

        fixture.offline = True
        failed = accepted(client.post("/v1/recalls/live-query", json={**payload, "fallback_policy": "ask"}))
        consent = accepted(client.post("/v1/fallback-consents", json={"query_id": failed["query_id"],
            "decision": "allow", "scope": "once"}), 201)
        with app.state.database.sessions() as db:
            actor = db.get(FallbackConsent, consent["id"]).session_id
        barrier = Barrier(2)
        def consume(_):
            with app.state.database.sessions() as db:
                barrier.wait(timeout=10)
                try:
                    result = asyncio.run(RecallService(db, fixture).execute(RecallLiveRequest(
                        query={"campaign_number": CAMPAIGN}, fallback_policy="ask", consent_id=consent["id"]), actor))
                    assert result["data_state"] == "local_snapshot"
                    return 200
                except HTTPException as error:
                    return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(consume, range(2))) == [200, 409]

        barrier = Barrier(2)
        def revise(index):
            barrier.wait(timeout=10)
            return client.post(f'/v1/recall-monitor-rules/{rule["id"]}/revisions', json={
                "expected_revision": 1, "name": f"PG concurrent synthetic revision {index}",
                "enabled": True, "archived": False, "interval_seconds": 3600}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(revise, range(2))) == [200, 409]
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: claim_job(app.state.database), range(2)))
        assert sum(row is not None for row in claims) == 1
        stale = next(row for row in claims if row)
        with app.state.database.sessions() as db:
            db.get(RecallMonitorJob, stale["id"]).lease_until = utcnow() - timedelta(seconds=1)
            db.commit()
        fresh = claim_job(app.state.database)
        assert fresh and fresh["token"] != stale["token"]
        with app.state.database.sessions() as db:
            try:
                guard_claim(db, stale)
            except LeaseLost:
                pass
            else:
                raise AssertionError("stale_recall_lease_was_accepted")
        assert not finish_job(app.state.database, stale, "live")
        assert finish_job(app.state.database, fresh, "source_unavailable", "pg_synthetic_outage")
        assert not finish_job(app.state.database, fresh, "live")
        notices = accepted(client.get("/v1/recall-notifications?mode=history"))
        assert notices["total"] == 2
        accepted(client.put(f'/v1/recall-notifications/{notices["items"][0]["id"]}/read', json={"read": True}))
        history = accepted(client.get(f"/v1/recalls/{CAMPAIGN}/history?mode=history"))
        rule_after = accepted(client.get(f'/v1/recall-monitor-rules/{rule["id"]}?mode=history'))
        notices = accepted(client.get("/v1/recall-notifications?mode=history"))
        captures = accepted(client.get("/v1/captures?mode=history&source_id=nhtsa-us-recalls"))["items"]
        checkpoint = {"data": "synthetic only", "cookies": dict(client.cookies), "campaign_number": CAMPAIGN,
            "rule_id": rule["id"], "rule": rule_after, "history": history, "notifications": notices,
            "search": search, "captures": [{"id": row["id"], "raw_hash": row["raw_hash"]} for row in captures],
            "checks": ["complete_campaign_revisions_and_first_observed_notifications", "empty_is_not_recall_resolution",
                "discovery_page_has_no_campaign_side_effect", "concurrent_single_use_recall_consent",
                "concurrent_recall_rule_revision_cas", "concurrent_lease_claim_and_stale_token_fencing"]}
    assert_recall_checkpoint(url, checkpoint)
    return checkpoint


def assert_recall_checkpoint(url: str, checkpoint: dict):
    """Exercise history, evidence/object links and private state after restart/restore."""
    app = create_app(url)
    with TestClient(app) as client:
        assert accepted(client.get("/v1/recall-monitor-rules"))["total"] == 0
        assert accepted(client.get("/v1/recall-notifications?mode=history"))["total"] == 0
        assert client.get(f'/v1/recall-monitor-rules/{checkpoint["rule_id"]}?mode=history').status_code == 404
        client.cookies.update(checkpoint["cookies"])
        rule = accepted(client.get(f'/v1/recall-monitor-rules/{checkpoint["rule_id"]}?mode=history'))
        assert rule == checkpoint["rule"]
        notices = accepted(client.get("/v1/recall-notifications?mode=history"))
        assert notices == checkpoint["notifications"]
        history = accepted(client.get(f'/v1/recalls/{checkpoint["campaign_number"]}/history?mode=history'))
        assert history["records"] == checkpoint["history"]["records"]
        assert history["revisions"] == checkpoint["history"]["revisions"]
        for revision in history["revisions"]:
            evidence = accepted(client.get(f'/v1/recall-evidence/{revision["snapshot_id"]}?mode=history'))
            assert hashlib.sha256(evidence["body"].encode()).hexdigest() == evidence["raw_hash"]
        search = accepted(client.get("/v1/recalls/search-history", params={"mode": "history", "search": "SYNTHETIC DEMO", "offset": 0}))
        assert search["products"] == checkpoint["search"]["products"]
        assert search["pagination"] == checkpoint["search"]["pagination"]
        evidence_check(client, search["provenance"][0])
        for row in checkpoint["captures"]:
            evidence = accepted(client.get(f'/v1/captures/{row["id"]}?mode=history'))
            assert hashlib.sha256(evidence["body"].encode()).hexdigest() == row["raw_hash"] == evidence["raw_hash"]


def main():
    output = ROOT / ".artifacts/recalls" / ("real-" + uuid4().hex)
    output.mkdir(parents=True)
    report = {"status": "running", "data": "live official NHTSA; no simulated transport", "checks": [], "real_source_states": {}}
    try:
        run_real_acceptance(output, report)
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__)
    (output / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**report, "output_directory": str(output)}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
