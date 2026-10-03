"""Opt-in real-source API acceptance plus an explicitly injected network failure.

Uses a temporary database, never seeds the application's development database.
Run with: uv run --project apps/api --extra dev python scripts/acceptance.py
"""

import argparse
from copy import deepcopy
import hashlib
import json
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from tire_api.adapters import registry, xiaomi
from tire_api.main import create_app
from tire_api.vehicles import register_vehicle_routes


class ControlledSource:
    offline = False

    def __init__(self):
        self.inject_parser_loss_for = None
        self.last_accepted_responses = {}

    @staticmethod
    def sources():
        return registry.sources()

    async def fetch(self, source_id, query, cached=None, *, on_observation=None):
        if self.offline:
            return {"status": "unavailable", "reason": "acceptance_injected_network_failure"}
        if self.inject_parser_loss_for == source_id:
            # Deliberately simulate a broken parser over a previously downloaded
            # real body. This is not represented as an actual upstream failure.
            result = deepcopy(self.last_accepted_responses[source_id])
            result["parser_version"] += "+acceptance-injected-field-loss"
            if on_observation is not None:
                on_observation(result)
            for row in result["variants"]:
                row["facts"] = {}
                for field in ("load_index", "speed_rating", "xl", "hl", "oe_mark", "acoustic_technology", "run_flat"):
                    row[field] = None
            return result
        result = await registry.fetch(source_id, query, cached, on_observation=on_observation)
        if result["status"] == "ok":
            self.last_accepted_responses[source_id] = deepcopy(result)
        return result


class ControlledVehicleSource:
    offline = False
    candidates = staticmethod(xiaomi.candidates)

    async def fetch(self, vehicle_id, *, on_observation=None):
        if self.offline:
            return {"status": "unavailable", "reason": "acceptance_injected_network_failure"}
        return await xiaomi.fetch(vehicle_id, on_observation=on_observation)


def extended_acceptance(client, tire_source, vehicle_source, report):
    """Exercise the real regional/OEM API paths before injecting explicit outages."""
    tire_source.offline = False
    endpoint = "/v1/sources/michelin-cn/live-query"
    request = {"query": {"model": "PSEV", "size": "265/40R20"}, "fallback_policy": "ask"}
    live = client.post(endpoint, json=request).json()
    assert live["data_state"] == "live", live
    assert live["variants"] and all(row["region"] == "CN" for row in live["variants"])
    cn_codes = {row["manufacturer_product_code"] for row in live["variants"]}
    assert cn_codes.isdisjoint(report["product_codes"]), "区域产品编号样本变化，需人工核对"
    report["cn_product_codes"] = sorted(cn_codes)
    report["checks"].append("real_cn_query_preserves_regional_identity")
    # Respect the production adapter's current per-origin robots budget.
    origin = registry.SPECS["michelin-cn"].origin
    time.sleep(max(2.1, registry._states[origin]["interval"] + 0.1))
    revalidated = client.post(endpoint, json=request).json()
    assert revalidated["data_state"] in {"live", "live_verified_304"}, revalidated
    report["cn_revalidation_state"] = revalidated["data_state"]
    if revalidated["data_state"] == "live_verified_304":
        assert revalidated["snapshot_observed_at"] == live["snapshot_observed_at"]
        assert revalidated["provenance"][0]["raw_hash"] == live["provenance"][0]["raw_hash"]
        report["checks"].append("real_304_preserves_original_observation")
    else:
        # The upstream may stop returning validators; never manufacture a 304.
        report["checks"].append("conditional_request_returned_real_200")

    tire_source.inject_parser_loss_for = "michelin-cn"
    quarantined = client.post(endpoint, json=request).json()
    assert quarantined["data_state"] == "consent_required" and quarantined["reason"] == "source_quality_quarantined"
    assert not quarantined["variants"] and not quarantined["provenance"]
    entries = client.get("/v1/quarantines", params={"source_id": "michelin-cn"}).json()["items"]
    assert len(entries) == 1
    quarantine_evidence = client.get(f"/v1/quarantines/{entries[0]['id']}", params={"mode": "history"}).json()
    assert quarantine_evidence["data_state"] == "local_snapshot"
    assert hashlib.sha256(quarantine_evidence["body"].encode()).hexdigest() == quarantine_evidence["raw_hash"]
    grant = client.post("/v1/fallback-consents", json={"query_id": quarantined["query_id"], "decision": "allow"})
    assert grant.status_code == 201
    previous = client.post(endpoint, json={**request, "consent_id": grant.json()["id"]}).json()
    assert previous["data_state"] == "local_snapshot"
    assert previous["variants"] == revalidated["variants"]
    assert previous["snapshot_observed_at"] == revalidated["snapshot_observed_at"]
    tire_source.inject_parser_loss_for = None
    time.sleep(max(2.1, registry._states[origin]["interval"] + 0.1))
    recovered = client.post(endpoint, json=request).json()
    assert recovered["data_state"] in {"live", "live_verified_304"}
    assert {row["id"] for row in recovered["variants"]} == {row["id"] for row in live["variants"]}
    report["parser_loss"] = "explicit_fault_injection_over_real_cn_body"
    report["checks"].extend(["injected_parser_loss_quarantined_without_local_answer",
                             "authorized_fallback_excludes_quarantined_candidate", "real_source_recovers_after_quarantine"])

    vehicle_endpoint = f"/v1/vehicles/{xiaomi.CURRENT_ID}/live-fitments"
    vehicle_request = {"fallback_policy": "ask"}
    vehicle = client.post(vehicle_endpoint, json=vehicle_request).json()
    assert vehicle["data_state"] == "live", vehicle
    assert vehicle["vehicle"]["id"] == xiaomi.CURRENT_ID
    assert vehicle["trims"] and vehicle["fitments"]
    psev_20 = [row for row in vehicle["fitments"] if row["wheel_diameter_inches"] == 20
               and row["availability"] != "unavailable" and "EV" in (row["source_tire_description"] or "")]
    assert psev_20, "官方20英寸PSEV配置样本变化：需重新人工核对"
    assert all(row["front"]["size"] == "245/40R20" and row["rear"]["size"] == "265/40R20" for row in psev_20)
    assert all(row[axle]["matched_tire_variant_id"] is None for row in vehicle["fitments"] for axle in ("front", "rear"))
    vehicle_evidence = client.get(f"/v1/vehicle-evidence/{vehicle['provenance'][0]['snapshot_id']}").json()
    assert hashlib.sha256(vehicle_evidence["body"].encode()).hexdigest() == vehicle_evidence["raw_hash"]
    report["vehicle"] = {"id": xiaomi.CURRENT_ID, "trims": len(vehicle["trims"]),
                         "fitments": len(vehicle["fitments"]), "evidence_hash": vehicle_evidence["raw_hash"]}
    report["checks"].extend(["real_current_su7_axles_and_raw_evidence", "vehicle_size_does_not_infer_exact_tire_sku"])
    first = client.post(f"/v1/vehicles/{xiaomi.FIRST_GENERATION_ID}/live-fitments",
                        json={"fallback_policy": "never"}).json()
    assert first["data_state"] == "source_unavailable" and first["fitments"] == []
    report["checks"].append("first_generation_cannot_borrow_current_generation")

    vehicle_source.offline = True
    tire_source.offline = True
    pending = client.post(vehicle_endpoint, json=vehicle_request).json()
    assert pending["data_state"] == "consent_required" and not pending["fitments"] and not pending["provenance"]
    consent = client.post("/v1/fallback-consents", json={"query_id": pending["query_id"], "decision": "allow"})
    assert consent.status_code == 201
    consent_id = consent.json()["id"]
    assert client.post(endpoint, json={**request, "consent_id": consent_id}).status_code == 403
    assert client.post(f"/v1/vehicles/{xiaomi.FIRST_GENERATION_ID}/live-fitments",
                       json={**vehicle_request, "consent_id": consent_id}).status_code == 403
    approved = {**vehicle_request, "consent_id": consent_id}
    local = client.post(vehicle_endpoint, json=approved).json()
    assert local["data_state"] == "local_snapshot" and local["snapshot_observed_at"] == vehicle["snapshot_observed_at"]
    assert local["provenance"][0]["raw_hash"] == vehicle_evidence["raw_hash"]
    assert local["fitments"] == vehicle["fitments"]
    assert client.post(vehicle_endpoint, json=approved).status_code == 409
    report["checks"].extend(["vehicle_consent_cannot_cross_tire_or_generation", "authorized_vehicle_fallback_is_immutable_and_single_use"])


def main():
    parser = argparse.ArgumentParser(description="真实官网 API 验收；故障注入只作用于临时数据库")
    parser.add_argument("--extended", action="store_true", help="同时验证中国区条件请求、小米当前车型与跨域授权隔离")
    args = parser.parse_args()
    report = {"source": "michelin-us", "live_source": True, "outage": "fault_injected", "checks": []}
    source = ControlledSource()
    vehicle_source = ControlledVehicleSource()
    endpoint = "/v1/sources/michelin-us/live-query"
    request = {"query": {"model": "PSEV", "size": "265/40R20"}, "fallback_policy": "ask"}
    with tempfile.TemporaryDirectory(prefix="tire-acceptance-") as temporary:
        application = create_app(f"sqlite:///{Path(temporary, 'acceptance.db').as_posix()}", source)
        register_vehicle_routes(application, vehicle_source)
        with TestClient(application) as client:
            response = client.post(endpoint, json=request)
            assert response.status_code == 200, response.text
            live = response.json()
            assert live["data_state"] == "live", live
            assert len(live["variants"]) >= 2, "官方目录变更：请人工重新核对验收样本"
            codes = {variant["manufacturer_product_code"] for variant in live["variants"]}
            assert "08150" in codes, "官方样本MSPN变更：请重新核对，不要伪造结果"
            ids = [variant["id"] for variant in live["variants"]]
            assert len(ids) == len(set(ids))
            report["product_codes"] = sorted(codes)
            report["checks"].append("real_live_query_and_separate_skus")
            snapshot_id = live["provenance"][0]["snapshot_id"]
            evidence = client.get(f"/v1/evidence/{snapshot_id}").json()
            assert hashlib.sha256(evidence["body"].encode()).hexdigest() == evidence["raw_hash"]
            report["checks"].append("raw_evidence_hash")
            watch = client.post("/v1/watchlists", json={"variant_id": ids[0]})
            assert watch.status_code == 201
            assert len(client.get("/v1/watchlists").json()["items"]) == 1
            compare = client.post("/v1/compare", json={"variant_ids": ids[:2]}).json()
            assert compare["data_state"] == "local_snapshot" and len(compare["variants"]) == 2
            report["checks"].append("watch_and_explicit_historical_compare")

            source.offline = True
            pending = client.post(endpoint, json=request).json()
            assert pending["data_state"] == "consent_required" and pending["variants"] == []
            report["checks"].append("outage_without_answer_returns_no_local_parameters")
            deny = client.post("/v1/fallback-consents", json={"query_id": pending["query_id"], "decision": "deny", "scope": "once"})
            assert deny.status_code == 201
            denied = client.post(endpoint, json={**request, "consent_id": deny.json()["id"]})
            assert denied.status_code == 403
            report["checks"].append("denied_consent_cannot_read_snapshot")

            pending = client.post(endpoint, json=request).json()
            consent = client.post("/v1/fallback-consents", json={"query_id": pending["query_id"], "decision": "allow", "scope": "once"})
            assert consent.status_code == 201
            approved_request = {**request, "consent_id": consent.json()["id"]}
            local = client.post(endpoint, json=approved_request).json()
            assert local["data_state"] == "local_snapshot" and local["consent_id"]
            assert local["provenance"][0]["raw_hash"] == evidence["raw_hash"]
            assert local["snapshot_observed_at"] == live["snapshot_observed_at"]
            assert len(local["variants"]) == len(live["variants"])
            assert client.post(endpoint, json=approved_request).status_code == 409
            never = client.post(endpoint, json={**request, "fallback_policy": "never"}).json()
            assert never["data_state"] == "source_unavailable" and never["variants"] == []
            report["checks"].extend(["authorized_snapshot_preserves_original_evidence", "consent_single_use", "never_policy_no_local_parameters"])
            if args.extended:
                extended_acceptance(client, source, vehicle_source, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
