"""Private recall lifecycle fixture: synthetic HTTP, real sealed subprocess parsers.

Run with ``uv run --project apps/api --extra dev python
scripts/recall_reparse_browser_qa.py``; add --self-test for local API acceptance.
The optional server binds only 127.0.0.1:8001, uses a dedicated cookie, and stores
all DB, object and parser archive data in one temporary directory. It never opens
data/dev.db. No real source or model is called; no production route is added.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/tests"))
from test_parser_bundles import trusted_copy
from tire_api.adapters import nhtsa
from tire_api.adapters.robots import RobotsPolicy
from tire_api.adapters.transport import FetchResult
from tire_api.ai_models import AIRequest
from tire_api.captures import before_parse_recorder
from tire_api.db import FactVersion, QueryRun, RawCapture, Snapshot, TireVariant, uid
from tire_api.domain import digest
from tire_api.embedding_models import EmbeddingRequest
from tire_api.main import create_app
from tire_api.parser_release_models import (ParserBundle, ParserDeploymentRevision,
    ParserEvaluation, ParserEvaluationCompletion, ParserEvaluationReview, ParserExecution, ParserSelection)
from tire_api.parser_releases import register_deployed_bundle
from tire_api.recall_discovery import RecallSearchSnapshot, RecallSearchVerification
from tire_api.recall_models import (RecallEvent, RecallMonitorRule, RecallNotification,
    RecallRevision, RecallSnapshot, RecallVerification)
from tire_api.reparse_models import ReparseRun, ReparseCompletion, ReparseReview

SOURCE = nhtsa.SOURCE_ID
CAMPAIGN = "23T001000"
CANARY = '<script>window.recallReleaseCanary=1</script>'
TABLES = (TireVariant, Snapshot, FactVersion, QueryRun, RawCapture,
    RecallSnapshot, RecallVerification, RecallRevision, RecallEvent,
    RecallSearchSnapshot, RecallSearchVerification, RecallMonitorRule, RecallNotification,
    AIRequest, EmbeddingRequest, ParserBundle, ParserDeploymentRevision,
    ParserEvaluation, ParserEvaluationCompletion, ParserEvaluationReview,
    ParserExecution, ParserSelection, ReparseRun, ReparseCompletion, ReparseReview)
FACT_TABLES = (TireVariant, Snapshot, FactVersion, RecallSnapshot, RecallVerification,
    RecallRevision, RecallEvent, RecallSearchSnapshot, RecallSearchVerification,
    RecallMonitorRule, RecallNotification, AIRequest, EmbeddingRequest)


def campaign_body():
    return {"Count": 1, "Message": "Results returned successfully", "results": [{
        "NHTSACampaignNumber": CAMPAIGN, "Manufacturer": "SYNTHETIC ONLY Manufacturer",
        "ReportReceivedDate": "02/03/2023", "Component": "TIRES", "PotentialNumberofUnitsAffected": 123,
        "Summary": "SYNTHETIC ONLY / 合成生命周期验收，非真实公告结论。" + CANARY,
        "Consequence": "Synthetic consequence only.", "Remedy": "Synthetic remedy; DOT/TIN applicability not assessed.",
        "Notes": "Synthetic notes. " + CANARY, "Make": "SYNTHETIC", "Model": "DEMO", "ModelYear": "9999"}]}


def search_body():
    query = {"search": "SYNTHETIC DEMO", "offset": "0"}
    campaign = {"nhtsaCampaignNumber": CAMPAIGN, "subject": "SYNTHETIC ONLY recall",
        "reportReceivedDate": "2023-03-02T00:00:00Z", "manufacturer": "SYNTHETIC ONLY Manufacturer",
        "summary": "Synthetic search summary. " + CANARY, "consequence": "Synthetic consequence only.",
        "correctiveAction": "Synthetic remedy; no exact SKU applicability.", "notes": "Synthetic notes.",
        "associatedDocumentsCount": 2,
        "associatedDocuments": [{"url": f"https://static.nhtsa.gov/odi/rcl/2023/SYNTHETIC-ONLY-{index}.pdf",
            "summary": f"Synthetic attachment {index}; never fetched"} for index in (1, 2)],
        "associatedProductsCount": 2,
        "associatedProducts": [{"type": "Tire", "productMake": "SYNTHETIC",
            "productModel": f"DEMO {index}"} for index in (1, 2)]}
    products = [{"id": 1, "artemisId": 1001, "brand": "SYNTHETIC", "tireline": "DEMO",
        "size": "215/60R16", "recallsCount": 1, "safetyIssues": {"recalls": [campaign]}}]
    return {"meta": {"status": 200, "messages": [], "pagination": {"offset": 0, "max": 10,
        "count": 1, "total": 1, "sort": "productName", "order": "asc",
        "currentUrl": nhtsa.query_url(query), "nextUrl": None, "previousUrl": None}}, "results": products}


class SyntheticTransport:
    calls = 0

    def __init__(self, *_args):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def get(self, url, **_kwargs):
        # Only the two exact fixed queries seeded below are allowed. No network.
        bodies = {nhtsa.query_url({"campaign_number": CAMPAIGN}): campaign_body(),
            nhtsa.query_url({"search": "SYNTHETIC DEMO", "offset": "0"}): search_body()}
        if url not in bodies:
            raise AssertionError("fixture accepts only its two fixed synthetic queries")
        type(self).calls += 1
        return FetchResult(200, url, json.dumps(bodies[url], ensure_ascii=False), "application/json", None, None)


class NoOtherSources:
    def sources(self):
        return [{**nhtsa.source_metadata(), "name": "NHTSA · 合成生命周期验收",
            "description": "隔离环境的合成原文与真实封存 Parser 执行；非真实官网验收。"}]

    async def fetch(self, *_args, **_kwargs):
        return {"status": "unavailable", "reason": "synthetic_fixture_has_no_other_sources"}


async def synthetic_policy(*_args):
    return RobotsPolicy("", "TireEvidenceResearch")


def mark_candidate(source: Path, *, loss=False):
    """Mutate only the temporary trusted install, then seal its actual bytes."""
    path = source / "adapters/nhtsa.py"
    text = '''
_synthetic_previous_parse = parse_json
def parse_json(body, query):
    value = _synthetic_previous_parse(body, query)
    if isinstance(value, list):
        for row in value:
            row['summary'] = None if SYNTHETIC_LOSS else row['summary'] + ' / synthetic parser B'
    else:
        for product in value['products']:
            for campaign in product['campaigns']:
                if SYNTHETIC_LOSS:
                    campaign['documents'] = campaign['documents'][:-1]
                else:
                    campaign['summary'] += ' / synthetic parser B'
    return value
'''.replace("SYNTHETIC_LOSS", "True" if loss else "False")
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def evidence_fingerprint(database):
    # Hash full persisted rows, including observed/verified times and validators.
    with database.sessions() as db:
        values = {table.__tablename__: sorted([
            {column.name: str(getattr(row, column.name)) for column in table.__table__.columns}
            for row in db.scalars(select(table))], key=lambda value: json.dumps(value, sort_keys=True))
            for table in FACT_TABLES}
    return digest(values)


@contextmanager
def fixture_application(directory: Path):
    import tire_api.main as api_module
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(api_module, "SESSION_COOKIE", "tire_recall_release_qa_session")
        for name, value in {"TI_AI_ENABLED": "0", "TI_EMBEDDINGS_ENABLED": "0", "TI_DISABLED_SOURCES": "",
            "TI_OBJECT_STORE_BACKEND": "filesystem", "TI_OBJECT_STORE_ROOT": str(directory / "objects"),
            "TIRE_CORS_ORIGINS": "http://localhost:3001,http://127.0.0.1:3001"}.items():
            patcher.setenv(name, value)
        patcher.setattr(nhtsa, "SafeHttpClient", SyntheticTransport)
        patcher.setattr(nhtsa, "_policy", synthetic_policy)
        patcher.setattr(nhtsa, "_state", {"last": -float("inf"), "failures": 0, "until": 0, "busy": False, "interval": 2.0})
        SyntheticTransport.calls = 0
        source = trusted_copy(directory, patcher)
        pristine_parser = (source / "adapters/nhtsa.py").read_text(encoding="utf-8")
        app = create_app("sqlite:///" + (directory / "qa.db").as_posix(), NoOtherSources())
        captures = {}
        try:
            with TestClient(app) as client:
                for label, path, query in (("campaign", "/v1/recalls/live-query", {"campaign_number": CAMPAIGN}),
                    ("search", "/v1/recalls/search", {"search": "SYNTHETIC DEMO", "offset": 0})):
                    nhtsa._state.update(last=-float("inf"), failures=0, until=0)
                    response = client.post(path, json={"query": query, "fallback_policy": "never"})
                    assert response.status_code == 200 and response.json()["data_state"] == "live", response.text
                    execution = client.get(f'/v1/parser-executions/{response.json()["query_id"]}?mode=history').json()
                    receipt = execution["completion"]["receipt"]
                    assert execution["completion"]["state"] == "completed" and receipt["reaped"] and receipt["exit_code"] == 0
                    assert type(receipt["pid"]) is int and receipt["pid"] > 0 and len(receipt["input_hash"]) == 64
                    with app.state.database.sessions() as db:
                        captures[label] = db.scalar(select(RawCapture.id).where(RawCapture.query_id == response.json()["query_id"]))
                with app.state.database.sessions() as db:
                    first = db.scalar(select(ParserDeploymentRevision).where(ParserDeploymentRevision.source_id == SOURCE)).bundle_id
                    original = db.get(RawCapture, captures["campaign"])
                    original_run = db.get(QueryRun, original.query_id)
                    gap_run = QueryRun(id=uid(), session_id=original_run.session_id, source_id=SOURCE,
                        query_key=original_run.query_key, query=deepcopy(original_run.query), fallback_policy="never",
                        state="source_unavailable", reason="synthetic_receipt_only_no_accepted_snapshot")
                    db.add(gap_run)
                    db.commit()
                    # Durable production capture writer, intentionally no ingestion.
                    before_parse_recorder(db, gap_run)({"body": original.raw_body.decode("utf-8"),
                        "url": original.source_url, "content_type": original.content_type,
                        "parser_version": original.parser_version, "parser_identity": original.parser_identity})
                    captures["reference_gap"] = db.scalar(select(RawCapture.id).where(RawCapture.query_id == gap_run.id))
                    db.commit()
                    mark_candidate(source)
                    second = register_deployed_bundle(db, "合成候选 B " + CANARY,
                        "只改变临时可信安装的公告文本解析，非官网变更")["id"]
                    (source / "adapters/nhtsa.py").write_text(pristine_parser, encoding="utf-8")
                    mark_candidate(source, loss=True)
                    loss = register_deployed_bundle(db, "合成缺失包 C",
                        "临时代码删去公告安全字段或附件，验证不可批准门禁")["id"]
            baseline = evidence_fingerprint(app.state.database)
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8001))

            @app.get("/fixture/state")
            def state():
                with app.state.database.sessions() as db:
                    counts = {table.__tablename__: db.scalar(select(func.count()).select_from(table)) for table in TABLES}
                return {"environment": "private_synthetic_recall_release_qa", "synthetic": True,
                    "parser_execution": "real_sealed_subprocess", "bundle_ids": {"a": first, "b": second, "loss": loss},
                    "capture_ids": captures, "source_calls": SyntheticTransport.calls,
                    "real_source_calls": 0, "real_model_calls": 0, "counts": counts,
                    "historical_evidence_unchanged": baseline == evidence_fingerprint(app.state.database), "canary": CANARY}

            @app.post("/fixture/shutdown")
            def shutdown():
                server.should_exit = True
                return {"synthetic": True, "shutdown_requested": True}

            yield app, server
        finally:
            app.state.database.close()


def self_test(app):
    checks = []
    with TestClient(app) as client:
        def post(path, payload, *, status=201, key=None):
            response = client.post(path, json=payload, headers={"Idempotency-Key": key or str(uuid4())})
            assert response.status_code == status, (path, response.status_code, response.text)
            return response.json()

        def state():
            return client.get("/fixture/state").json()

        initial = state()
        assert client.cookies.get("tire_recall_release_qa_session") and not client.cookies.get("tire_local_session")
        assert initial["counts"]["parser_executions"] == 2 and initial["source_calls"] == 2
        assert initial["counts"]["tire_variants"] == initial["counts"]["ai_requests"] == initial["counts"]["embedding_requests"] == 0
        checks.append("private_db_cookie_real_subprocess_seed_no_external_calls")
        bundles, captures = initial["bundle_ids"], initial["capture_ids"]
        catalog = client.get(f'/v1/reparse/catalog?mode=history&bundle_id={bundles["b"]}').json()
        descriptor = next(row for row in catalog["parsers"] if row["source_id"] == SOURCE)
        assert descriptor["target_kind"] == "recall"
        runs = []
        for label in ("campaign", "search"):
            key = str(uuid4())
            payload = {"mode": "history", "capture_id": captures[label], "bundle_id": bundles["b"],
                "parser_version": descriptor["parser_version"], "parser_digest": descriptor["parser_digest"]}
            run = post("/v1/reparse/runs", payload, key=key)
            assert post("/v1/reparse/runs", payload, key=key)["id"] == run["id"]
            assert run["state"] == "completed" and run["accepted_as_facts"] is False
            assert run["completion"]["receipt"]["reaped"] and run["completion"]["receipt"]["exit_code"] == 0
            assert run["completion"]["receipt"]["bundle_id"] == bundles["b"]
            assert run["completion"]["receipt"]["pid"] > 0 and len(run["completion"]["receipt"]["input_hash"]) == 64
            candidate = run["completion"]["candidate"]
            rows = candidate if label == "campaign" else candidate["products"]
            assert all(row["applicability"] == "not_assessed" for row in rows)
            assert CANARY in json.dumps(candidate, ensure_ascii=False)
            runs.append(run)
        checks.append("campaign_and_search_reparse_shapes_real_receipts_idempotency")
        review_payload = {"mode": "history", "expected_revision": 0, "status": "reviewed",
            "operator": "合成审阅 " + CANARY, "reason": "只核对历史候选，不批准事实"}
        reviewed = post(f'/v1/reparse/runs/{runs[0]["id"]}/reviews', review_payload)
        assert reviewed["review_revision"] == 1
        assert post(f'/v1/reparse/runs/{runs[0]["id"]}/reviews', review_payload, status=409)["detail"]["code"] == "reparse_review_revision_conflict"
        checks.append("signed_reparse_review_stale_revision_rejected")

        def evaluate(bundle, labels):
            return post("/v1/parser-evaluations", {"mode": "history", "source_id": SOURCE,
                "target_bundle_id": bundles[bundle], "capture_ids": [captures[label] for label in labels],
                "expected_deployment_revision": 1})

        valid = evaluate("b", ("campaign", "search", "reference_gap"))
        assert valid["state"] == "completed" and valid["can_approve"]
        assert valid["completion"]["reference_gaps"] == [captures["reference_gap"]]
        refs = {row["capture_id"]: row["reference_kind"] for row in valid["completion"]["results"]}
        assert refs[captures["campaign"]] == refs[captures["search"]] == "accepted_same_raw"
        assert refs[captures["reference_gap"]] == "control_same_raw"
        for row in valid["completion"]["results"]:
            for kind, bundle in (("candidate", "b"), ("control", "a")):
                receipt = row[kind + "_receipt"]
                assert receipt["reaped"] and receipt["exit_code"] == 0 and receipt["bundle_id"] == bundles[bundle]
                assert receipt["pid"] > 0 and len(receipt["input_hash"]) == 64
        checks.append("same_raw_formal_reference_and_explicit_control_reference_gap")
        bad = evaluate("loss", ("campaign", "search"))
        assert not bad["can_approve"]
        assert {row["code"] for row in bad["completion"]["hard_blocks"]} & {"recall_member_loss", "recall_safety_field_loss"}
        signed = {"operator": "合成发布验收", "reason": "只用于隔离环境生命周期核对"}

        def approve(value, *, gap=False, status=201, revision=0):
            return post(f'/v1/parser-evaluations/{value["id"]}/reviews', {"mode": "history",
                "expected_revision": revision, "completion_fingerprint": value["completion"]["fingerprint"],
                "action": "approve", "acknowledged": True, "acknowledge_reference_gaps": gap, **signed}, status=status)

        approve(bad, status=409)
        approve(valid, status=422)
        valid = approve(valid, gap=True)
        approve(valid, gap=True, status=409)
        assert valid["review_revision"] == 1
        checks.append("loss_hardblock_gap_acknowledgement_and_stale_approval_gates")
        activated = post(f"/v1/parser-deployments/{SOURCE}/transitions", {"action": "activate",
            "expected_revision": 1, "target_bundle_id": bundles["b"], "evaluation_id": valid["id"],
            "expected_review_revision": 1, **signed})
        assert activated["revision"] == 2 and activated["bundle_id"] == bundles["b"]
        post(f"/v1/parser-deployments/{SOURCE}/transitions", {"action": "pause", "expected_revision": 1, **signed}, status=409)
        rolled = post(f"/v1/parser-deployments/{SOURCE}/transitions", {"action": "rollback", "expected_revision": 2,
            "target_revision": 1, **signed})
        assert rolled["revision"] == 3 and rolled["bundle_id"] == bundles["a"]
        checks.append("signed_activate_and_rollback_append_revisions_a_b_a")
        final = state()
        assert final["source_calls"] == initial["source_calls"] and final["historical_evidence_unchanged"]
        assert final["real_source_calls"] == final["real_model_calls"] == 0
        checks.append("history_never_refetches_or_rewrites_facts_verification_notifications")
        return {"synthetic": True, "parser_execution": "real_sealed_subprocess", "checks": checks,
            "real_source_calls": 0, "real_model_calls": 0, "state": final}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="tire-recall-release-qa-") as temporary:
        with fixture_application(Path(temporary)) as (app, server):
            if args.self_test:
                print(json.dumps(self_test(app), ensure_ascii=False), flush=True)
            else:
                print(json.dumps({"environment": "private_synthetic_recall_release_qa",
                    "database": "temporary SQLite", "parser_execution": "real_sealed_subprocess",
                    "real_source_calls": 0, "real_model_calls": 0}), flush=True)
                server.run()


if __name__ == "__main__":
    main()
