"""Opt-in real-source capture + simulated manual edits in an isolated temporary DB.

No simulated correction is written to the application's development database.
Run: uv run --project apps/api --extra dev python scripts/curation_acceptance.py
"""
import hashlib
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tire_api.db import FactVersion, ManualFactRevision, Snapshot
from tire_api.main import create_app


def main():
    with tempfile.TemporaryDirectory(prefix="tire-curation-") as temporary:
        app = create_app(f"sqlite:///{Path(temporary, 'acceptance.db').as_posix()}")
        with TestClient(app) as client:
            live = client.post("/v1/sources/hankook-us/live-query", json={
                "query": {"model": "Ventus S1 evo3", "size": "205/45R17"}, "fallback_policy": "never"}).json()
            assert live["data_state"] == "live", live
            variant = next(row for row in live["variants"] if isinstance(row["facts"].get("utqg_treadwear"), int))
            vid = variant["id"]
            view = client.get(f"/v1/tire-variants/{vid}/fact-review", params={"source_id": "hankook-us", "mode": "history"}).json()
            raw_value = view["source_facts"]["utqg_treadwear"]
            evidence = client.get(f"/v1/evidence/{view['provenance']['snapshot_id']}").json()
            assert hashlib.sha256(evidence["body"].encode()).hexdigest() == evidence["raw_hash"]
            base = {"source_id": "hankook-us", "base_fact_id": view["base_fact_id"], "field": "utqg_treadwear",
                    "operator": "自动验收（模拟修改）", "reason": "临时数据库流程验收，不主张官网参数有误",
                    "evidence": [{"snapshot_id": evidence["id"], "locator": "UTQG - Tread Wear；仅核验流程，模拟人工值不是真实纠错"}]}
            for revision, action, value in [(1, "manual_override", raw_value + 1), (2, "manual_override", raw_value + 2),
                                            (3, "revoke", None), (4, "clear_override", None)]:
                request = {**base, "expected_revision": revision - 1, "action": action}
                if action == "manual_override":
                    request["value"] = value
                response = client.post(f"/v1/tire-variants/{vid}/fact-revisions", json=request)
                assert response.status_code == 201, response.text
                state = response.json()
                assert state["source_facts"]["utqg_treadwear"] == raw_value
                if action == "revoke":
                    assert "utqg_treadwear" not in state["effective_facts"]
                else:
                    assert state["effective_facts"]["utqg_treadwear"] == (raw_value if action == "clear_override" else value)
                ordinary = client.post("/v1/compare", json={"variant_ids": [vid]}).json()["variants"][0]
                assert ordinary["facts"]["utqg_treadwear"] == raw_value and "curation" not in ordinary
                reviewed = client.post("/v1/compare", json={"variant_ids": [vid], "include_manual": True}).json()["variants"][0]
                assert reviewed["effective_facts"] == state["effective_facts"]
            assert len(state["history"]) == 4 and all(row["valid_to"] for row in state["history"][1:])
            assert client.get(f"/v1/evidence/{evidence['id']}").json()["raw_hash"] == evidence["raw_hash"]
            with app.state.database.sessions() as db:
                assert db.scalar(select(func.count()).select_from(Snapshot)) == 1
                assert db.scalar(select(func.count()).select_from(FactVersion)) == len(live["variants"])
                assert db.scalar(select(func.count()).select_from(ManualFactRevision)) == 4
    print(json.dumps({"real_source": "hankook-us", "product_code": variant["manufacturer_product_code"],
                      "raw_hash": evidence["raw_hash"], "manual_changes": "explicit_simulation_in_temporary_database",
                      "checks": ["real_source_capture", "evidence_hash", "create_update_revoke_restore",
                                 "source_facts_unchanged", "explicit_comparison_only", "history_validity_intervals",
                                 "source_evidence_and_fact_counts_unchanged"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
