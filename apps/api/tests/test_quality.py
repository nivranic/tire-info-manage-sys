"""Quality gates use synthetic input; official source data is tested separately."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from admin_support import register_admin
from tire_api.db import (AuditEvent, ChangeEvent, Database, FactVersion, QueryRun, Snapshot,
                         SourceQuarantine, TireVariant, UserSession, Verification, utcnow)
from tire_api.domain import LiveQueryRequest
from tire_api.main import create_app
from tire_api.quality import QUALITY_REASON, assess_quality, metrics
from tire_api.service import QueryService
from query_evidence_assertions import assert_frozen_query_evidence


ROW = {
    "brand": "Quality Fixture", "model": "Quality Test Tire", "manufacturer_product_code": "QUALITY-001",
    "region": "TEST", "size": "265/40R20", "load_index": "104", "speed_rating": "Y",
    "xl": True, "hl": False, "oe_mark": "TEST", "acoustic_technology": "Fixture foam", "run_flat": False,
    "facts": {f"field_{index}": index for index in range(8)},
}
QUERY = {"query": {"size": "265/40R20", "model": "Quality Test Tire"}, "fallback_policy": "ask"}


def result(rows=None, parser_version="quality-fixture@1", etag='"accepted"'):
    rows = deepcopy([ROW] if rows is None else rows)
    return {"status": "ok", "url": "https://fixture.example/quality", "content_type": "application/json",
            "body": json.dumps({"variants": rows}, ensure_ascii=False), "parser_version": parser_version,
            "variants": rows, "etag": etag}


def reduced(count=6, value=None):
    row = deepcopy(ROW)
    for index in range(count):
        row["facts"][f"field_{index}"] = value
    return row


class FixtureRegistry:
    def __init__(self):
        self.result = result()
        self.calls = []

    def sources(self):
        return [{"id": "quality-fixture"}, {"id": "other-region-fixture"}, {"id": "unused-fixture"}]

    async def fetch(self, source_id, query, cached=None, *, on_observation=None):
        self.calls.append((source_id, query, cached))
        return deepcopy(self.result)


@pytest.fixture
def setup():
    registry = FixtureRegistry()
    app = create_app("sqlite://", registry)
    with TestClient(app) as client:
        # 隔离复核等管理写操作需要管理员（auth.py 守卫）；首个注册用户即管理员。
        register_admin(client)
        yield client, registry, app.state.database


def live(client, payload=None, source="quality-fixture"):
    return client.post(f"/v1/sources/{source}/live-query", json=payload or QUERY)


def grant(client, query_id):
    return client.post("/v1/fallback-consents", json={"query_id": query_id, "decision": "allow", "scope": "once"})


def count(database, model):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model))


def accepted_counts(database):
    return {model.__name__: count(database, model) for model in (Snapshot, Verification, TireVariant, FactVersion, ChangeEvent)}


def health(client, source="quality-fixture"):
    return next(row for row in client.get("/v1/source-health").json()["sources"] if row["source_id"] == source)


def quarantine(client):
    return client.get("/v1/quarantines").json()["items"][0]


def test_exact_30_percent_field_boundary_has_fixed_denominator():
    below = assess_quality([ROW], [reduced(5)])
    boundary = assess_quality([ROW], [reduced(6)])
    assert below["known_fields"] == boundary["known_fields"] == 20
    assert below["field_loss_ratio"] == 0.25 and below["reason_codes"] == []
    assert boundary["field_loss_ratio"] == 0.3
    assert boundary["reason_codes"] == ["field_loss_threshold"]
    assert metrics(boundary)["lost_fields"] == 6


@pytest.mark.parametrize("empty", [None, "", "   ", [], {}, [None, ""]])
def test_empty_values_count_as_field_loss(empty):
    report = assess_quality([ROW], [reduced(6, empty)])
    assert report["lost_field_count"] == 6 and report["reason_codes"] == ["field_loss_threshold"]


def test_false_zero_and_nonempty_collections_are_known_values():
    row = deepcopy(ROW)
    row["xl"] = False
    row["facts"].update(field_0=False, field_1=0, field_2=[False], field_3=[0])
    report = assess_quality([ROW], [row])
    assert report["known_fields"] == 20 and report["lost_field_count"] == 0
    assert report["reason_codes"] == []


def test_nested_business_fields_are_recursive_and_metadata_is_excluded():
    old = deepcopy(ROW)
    old["facts"]["field_0"] = {"rating": 3, "enabled": False, "evidence": {"locator": "page.a"}}
    old["facts"]["evidence_spans"] = {str(index): "synthetic location" for index in range(100)}
    old["facts"]["source_updated_at"] = "2026-09-01"
    old["facts"]["source_field_conflicts"] = [{"field": "xl", "value": True}]
    new = deepcopy(old)
    new["facts"]["field_0"] = {"rating": None, "enabled": 0}
    for key in ("evidence_spans", "source_updated_at", "source_field_conflicts"):
        new["facts"].pop(key)
    report = assess_quality([old], [new])
    assert report["known_fields"] == 21 and report["lost_field_count"] == 1
    assert report["lost_fields"][0]["paths"] == ["facts.field_0.rating"]


def test_identity_loss_aligns_by_stable_product_key_before_identity_changes():
    row = deepcopy(ROW)
    for field in ("load_index", "speed_rating", "xl", "hl", "oe_mark", "acoustic_technology", "run_flat"):
        row[field] = None
    report = assess_quality([ROW], [row])
    assert report["aligned_rows"] == 1 and report["lost_rows"] == 0
    assert report["lost_field_count"] == 7 and report["reason_codes"] == ["field_loss_threshold"]
    assert "identity.load_index" in report["lost_fields"][0]["paths"]


def test_row_threshold_counts_original_rows_not_newly_added_rows():
    baseline = [{**deepcopy(ROW), "manufacturer_product_code": f"BASE-{index}"} for index in range(10)]
    assert assess_quality(baseline, baseline[:8])["reason_codes"] == []
    candidate = baseline[:7] + [{**deepcopy(ROW), "manufacturer_product_code": f"NEW-{index}"} for index in range(10)]
    report = assess_quality(baseline, candidate)
    assert report["candidate_rows"] == 17 and report["lost_rows"] == 3
    assert report["row_loss_ratio"] == 0.3 and report["field_loss_ratio"] == 0
    assert report["reason_codes"] == ["row_loss_threshold"]
    empty = assess_quality(baseline, [])
    assert empty["known_fields"] == 0 and empty["row_loss_ratio"] == 1
    assert empty["reason_codes"] == ["row_loss_threshold"]


@pytest.mark.parametrize("candidate", [
    [{**ROW, "manufacturer_product_code": None}],
    [ROW, {**ROW, "load_index": "105"}],
])
def test_ambiguous_product_keys_fail_closed_without_row_order_matching(candidate):
    report = assess_quality([ROW], candidate)
    assert "ambiguous_alignment" in report["reason_codes"]
    assert report["aligned_rows"] == 0 and report["ambiguous_keys"]


def test_region_is_part_of_alignment_and_new_sources_have_no_baseline():
    report = assess_quality([ROW], [{**ROW, "region": "OTHER"}])
    assert report["aligned_rows"] == 0 and report["lost_fields"] == []
    assert report["reason_codes"] == ["row_loss_threshold"]
    assert assess_quality(None, [reduced(8)])["reason_codes"] == []
    assert assess_quality([], [reduced(8)])["reason_codes"] == []


def test_quarantine_keeps_all_accepted_tables_and_evidence_times_unchanged(setup):
    client, registry, database = setup
    first = live(client).json()
    before = accepted_counts(database)
    snapshot_id = first["provenance"][0]["snapshot_id"]
    evidence = client.get(f"/v1/evidence/{snapshot_id}").json()
    registry.result = result([reduced()], parser_version="quality-fixture@2", etag='"rejected"')
    response = live(client).json()
    assert response["data_state"] == "consent_required" and response["reason"] == QUALITY_REASON
    assert response["variants"] == response["provenance"] == []
    assert response["verified_at"] is None and response["snapshot_observed_at"] is None
    assert accepted_counts(database) == before and count(database, SourceQuarantine) == 1
    assert client.get(f"/v1/evidence/{snapshot_id}").json() == evidence
    record = quarantine(client)
    assert record["previous_snapshot_id"] == snapshot_id
    assert record["metrics"]["known_fields"] == 20 and record["metrics"]["lost_fields"] == 6
    source = health(client)
    assert source["status"] == "quarantined" and source["last_reason"] == QUALITY_REASON
    assert source["last_success_at"] == first["verified_at"]
    assert (source["attempts"], source["successes"], source["failures"], source["quarantined_count"]) == (2, 1, 1, 1)


def test_never_policy_and_identity_loss_do_not_create_a_new_variant(setup):
    client, registry, database = setup
    live(client)
    row = deepcopy(ROW)
    for field in ("load_index", "speed_rating", "xl", "hl", "oe_mark", "acoustic_technology", "run_flat"):
        row[field] = None
    registry.result = result([row])
    data = live(client, {**QUERY, "fallback_policy": "never"}).json()
    assert data["data_state"] == "source_unavailable" and data["reason"] == QUALITY_REASON
    assert data["variants"] == [] and count(database, TireVariant) == 1


def test_row_disappearance_is_quarantined_before_empty_snapshot_can_replace_data(setup):
    client, registry, database = setup
    live(client)
    registry.result = result([])
    assert live(client).json()["reason"] == QUALITY_REASON
    assert count(database, Snapshot) == count(database, Verification) == 1
    assert quarantine(client)["reason_codes"] == ["row_loss_threshold"]


def test_exact_query_and_source_boundaries_have_separate_quality_baselines(setup):
    client, registry, database = setup
    live(client)
    registry.result = result([reduced(8)])
    size_only = live(client, {"query": {"size": "265/40R20"}}).json()
    assert size_only["data_state"] == "live"
    registry.result = result([{**reduced(8), "region": "OTHER"}])
    other_source = live(client, source="other-region-fixture").json()
    assert other_source["data_state"] == "live"
    assert other_source["variants"][0]["region"] == "OTHER"
    assert count(database, SourceQuarantine) == 0


def test_quarantine_metadata_is_separate_from_explicit_audited_history(setup):
    client, registry, database = setup
    live(client)
    registry.result = result([reduced()])
    live(client)
    listing = client.get("/v1/quarantines?source_id=quality-fixture&limit=1").json()
    assert listing["data_state"] == "local_snapshot" and len(listing["items"]) == 1
    record = listing["items"][0]
    assert not {"body", "candidates", "variants", "query", "session_id"} & record.keys()
    assert client.get("/v1/quarantines?source_id=unused-fixture").json()["items"] == []
    assert client.get("/v1/quarantines?limit=201").status_code == 422
    assert client.get(f"/v1/quarantines/{record['id']}").status_code == 422
    detail = client.get(record["evidence_path"]).json()
    assert detail["accepted"] is False and detail["data_state"] == "local_snapshot"
    assert detail["body"] == registry.result["body"]
    assert hashlib.sha256(detail["body"].encode()).hexdigest() == detail["raw_hash"]
    assert detail["candidates"][0]["facts"]["field_0"] is None
    assert "id" not in detail["candidates"][0]
    assert client.get(f"/v1/evidence/{record['id']}").status_code == 404
    with database.sessions() as db:
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "quarantine_history_read"))
        assert audit.detail["quarantine_id"] == record["id"]
        row = db.get(SourceQuarantine, record["id"])
        row.body = "tampered"
        with pytest.raises(ValueError, match="只能追加"):
            db.commit()


def test_authorized_fallback_can_only_return_previous_accepted_evidence(setup):
    client, registry, database = setup
    accepted = live(client).json()
    registry.result = result([reduced()])
    failed = live(client).json()
    cid = grant(client, failed["query_id"]).json()["id"]
    offline = live(client, {**QUERY, "consent_id": cid}).json()
    assert offline["data_state"] == "local_snapshot" and offline["consent_id"] == cid
    assert_frozen_query_evidence(accepted, offline, expected_state='local_snapshot')
    assert offline["verified_at"] == accepted["verified_at"]
    assert live(client, {**QUERY, "consent_id": cid}).status_code == 409
    source = health(client)
    assert source["status"] == "quarantined" and source["failures"] == 1 and source["successes"] == 1


def test_quarantined_body_and_validators_cannot_enter_304_transport_cache(setup):
    client, registry, database = setup
    first = live(client).json()
    original_body = registry.result["body"]
    registry.result = result([reduced()], etag='"rejected"')
    live(client)
    registry.result = {"status": "not_modified", "url": "https://fixture.example/quality", "etag": '"rejected"'}
    invalid = live(client).json()
    assert invalid["data_state"] == "consent_required"
    assert invalid["reason"] == "invalid_304_without_matching_evidence"
    cached = registry.calls[-1][2]
    assert cached["body"] == original_body and cached["etag"] == '"accepted"'
    assert cached["snapshot_id"] == first["provenance"][0]["snapshot_id"]
    assert count(database, Snapshot) == count(database, Verification) == 1
    registry.result["etag"] = '"accepted"'
    confirmed = live(client).json()
    assert confirmed["data_state"] == "live_verified_304"
    assert confirmed["provenance"] == first["provenance"]
    assert count(database, Verification) == 2 and count(database, SourceQuarantine) == 1


def test_valid_recovery_is_online_and_retains_quarantine_history(setup):
    client, registry, database = setup
    live(client)
    registry.result = result([reduced()])
    live(client)
    registry.result = result(parser_version="quality-fixture@recovered")
    recovered = live(client).json()
    assert recovered["data_state"] == "live" and recovered["variants"][0]["facts"] == ROW["facts"]
    source = health(client)
    assert source["status"] == "healthy" and source["last_reason"] is None
    assert source["last_success_at"] == recovered["verified_at"]
    assert (source["attempts"], source["successes"], source["failures"], source["quarantined_count"]) == (3, 2, 1, 1)
    assert count(database, SourceQuarantine) == 1 and count(database, FactVersion) == 1


def test_source_health_window_unknown_degraded_and_privacy(setup):
    client, registry, database = setup
    empty = client.get("/v1/source-health").json()
    assert empty["window"]["kind"] == "rolling_24h"
    assert {row["source_id"] for row in empty["sources"]} == {row["id"] for row in registry.sources()} | {"xiaomi-cn-vehicles"}
    assert all(row["status"] == "unknown" for row in empty["sources"])
    first = live(client).json()
    with database.sessions() as db:
        db.get(QueryRun, first["query_id"]).created_at = utcnow() - timedelta(hours=25)
        db.commit()
    assert health(client)["attempts"] == 0 and health(client)["last_success_at"] is None
    registry.result = {"status": "unavailable", "reason": "network_timeout"}
    live(client)
    source = health(client)
    assert source["status"] == "degraded" and source["last_reason"] == "network_timeout"
    assert (source["attempts"], source["successes"], source["failures"]) == (1, 0, 1)
    serialized = json.dumps(client.get("/v1/source-health").json())
    assert ROW["model"] not in serialized and "265/40R20" not in serialized
    assert "session_id" not in serialized and "query_id" not in serialized and "variants" not in serialized


def test_concurrent_rejected_observations_share_only_accepted_baseline(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'quality-concurrent.db').as_posix()}")
    database.initialize()
    registry = FixtureRegistry()
    with database.sessions() as db:
        for actor in ("baseline", "api", "worker"):
            db.add(UserSession(id=actor, expires_at=utcnow() + timedelta(hours=1)))
        db.commit()
        accepted = asyncio.run(QueryService(db, registry).execute("quality-fixture", LiveQueryRequest.model_validate(QUERY), "baseline"))
    gate = Barrier(2)
    class ConcurrentRegistry(FixtureRegistry):
        async def fetch(self, *args, **kwargs):
            await asyncio.to_thread(gate.wait, timeout=5)
            return result([reduced()])
    registry = ConcurrentRegistry()
    def execute(actor):
        with database.sessions() as db:
            return asyncio.run(QueryService(db, registry).execute("quality-fixture", LiveQueryRequest.model_validate(QUERY), actor))
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(execute, ("api", "worker")))
        assert all(row["reason"] == QUALITY_REASON for row in outcomes)
        assert count(database, SourceQuarantine) == 2
        assert all(value == 1 for value in accepted_counts(database).values())
        with database.sessions() as db:
            assert set(db.scalars(select(SourceQuarantine.previous_snapshot_id)).all()) == {accepted["provenance"][0]["snapshot_id"]}
    finally:
        database.close()


def test_existing_database_adds_quarantine_table_without_losing_evidence(tmp_path):
    url = f"sqlite:///{(tmp_path / 'existing.db').as_posix()}"
    registry = FixtureRegistry()
    original = create_app(url, registry)
    with TestClient(original) as client:
        first = live(client).json()
        evidence_path = f"/v1/evidence/{first['provenance'][0]['snapshot_id']}"
        evidence = client.get(evidence_path).json()
    database = Database(url)
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE source_quarantines")
    database.close()
    upgraded = create_app(url, registry)
    with TestClient(upgraded) as client:
        assert client.get(evidence_path).json() == evidence
        assert client.get("/v1/quarantines").json()["items"] == []
        assert count(upgraded.state.database, FactVersion) == 1
