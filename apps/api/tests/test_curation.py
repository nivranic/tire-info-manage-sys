"""Synthetic review actions; source values and original evidence never get rewritten."""
from copy import deepcopy
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tire_api.curation import RevisionRequest, append_revision
from tire_api.db import AuditEvent, FactVersion, ManualFactRevision, Snapshot, UserSession
from tire_api.main import create_app
from query_evidence_assertions import assert_frozen_query_evidence
from test_core import FixtureRegistry, QUERY, VARIANT, count, grant, live, setup, success


def prepare(client):
    result = live(client).json()
    variant_id = result["variants"][0]["id"]
    url = f"/v1/tire-variants/{variant_id}/fact-review"
    view = client.get(url, params={"source_id": "fixture", "mode": "history"}).json()
    payload = {"source_id": "fixture", "base_fact_id": view["base_fact_id"], "expected_revision": 0,
               "field": "utqg_treadwear", "action": "manual_override", "value": 420,
               "operator": "测试核验员", "reason": "合成原文用于测试纠错流程",
               "evidence": [{"snapshot_id": result["provenance"][0]["snapshot_id"], "locator": "fixture test evidence"}]}
    return variant_id, result, view, payload


def edit(client, variant_id, payload):
    return client.post(f"/v1/tire-variants/{variant_id}/fact-revisions", json=payload)


def test_append_update_revoke_and_restore_preserve_source_and_history(setup):
    client, registry, database = setup
    variant_id, live_data, initial, payload = prepare(client)
    assert initial["revision"] == 0 and initial["source_facts"] == initial["effective_facts"]
    assert client.get(f"/v1/tire-variants/{variant_id}/fact-review", params={"source_id": "fixture"}).status_code == 422
    first = edit(client, variant_id, payload)
    assert first.status_code == 201
    assert first.json()["effective_facts"]["utqg_treadwear"] == 420
    updated = edit(client, variant_id, {**payload, "expected_revision": 1, "value": 440}).json()
    assert updated["history"][0]["before"] == {"present": True, "value": 420}
    assert updated["history"][1]["valid_to"] == updated["history"][0]["valid_from"]
    revoked_request = {key: value for key, value in payload.items() if key != "value"}
    revoked = edit(client, variant_id, {**revoked_request, "expected_revision": 2, "action": "revoke"}).json()
    assert "utqg_treadwear" not in revoked["effective_facts"]
    assert revoked["source_facts"]["utqg_treadwear"] == 300
    assert revoked["fields"]["utqg_treadwear"]["status"] == "revoked"
    restored = edit(client, variant_id, {**revoked_request, "expected_revision": 3, "action": "clear_override"}).json()
    assert restored["effective_facts"]["utqg_treadwear"] == 300
    assert len(restored["history"]) == 4
    assert all(row["operator"] and row["reason"] and row["evidence"][0]["raw_hash"] for row in restored["history"])
    assert restored["history"][0]["valid_to"] is None
    assert count(database, Snapshot) == 1 and count(database, FactVersion) == 1
    assert_frozen_query_evidence(live_data, live(client).json(), expected_state='live', reverified=True)
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "manual_fact_revision")) == 4
        row = db.scalar(select(ManualFactRevision))
        row.reason = "cannot rewrite"
        with pytest.raises(ValueError, match="只能追加"):
            db.commit()
        db.rollback()
        db.delete(db.get(ManualFactRevision, row.id))
        with pytest.raises(ValueError, match="只能追加"):
            db.commit()


def test_manual_values_only_in_explicit_review_and_opt_in_compare(setup):
    client, registry, database = setup
    variant_id, accepted, _, payload = prepare(client)
    assert edit(client, variant_id, payload).status_code == 201
    ordinary = client.post("/v1/compare", json={"variant_ids": [variant_id]}).json()["variants"][0]
    assert ordinary["facts"]["utqg_treadwear"] == 300 and "effective_facts" not in ordinary
    reviewed = client.post("/v1/compare", json={"variant_ids": [variant_id], "include_manual": True}).json()["variants"][0]
    assert reviewed["facts"]["utqg_treadwear"] == 300
    assert reviewed["effective_facts"]["utqg_treadwear"] == 420
    assert reviewed["curation"]["fields"]["utqg_treadwear"]["status"] == "manual_override"
    registry.result = {"status": "unavailable", "reason": "fixture_outage"}
    pending = live(client).json()
    assert not pending["variants"]
    consent = grant(client, pending["query_id"]).json()
    local = live(client, {**QUERY, "consent_id": consent["id"]}).json()
    assert_frozen_query_evidence(accepted, local, expected_state='local_snapshot')
    assert local["snapshot_observed_at"] == accepted["snapshot_observed_at"]


def test_source_update_invalidates_overlay_and_stale_editor(setup):
    client, registry, database = setup
    variant_id, _, _, payload = prepare(client)
    first = edit(client, variant_id, payload).json()
    changed = deepcopy(VARIANT)
    changed["facts"]["utqg_treadwear"] = 320
    registry.result = success("fixture-source-v2", variants=[changed])
    assert live(client).json()["variants"][0]["facts"]["utqg_treadwear"] == 320
    current = client.get(f"/v1/tire-variants/{variant_id}/fact-review", params={"source_id": "fixture", "mode": "history"}).json()
    assert current["effective_facts"]["utqg_treadwear"] == 320
    assert current["fields"]["utqg_treadwear"]["status"] == "needs_review"
    assert current["history"][0]["valid_to"] is not None
    assert edit(client, variant_id, {**payload, "expected_revision": 1}).status_code == 409
    refreshed = {**payload, "expected_revision": 1, "base_fact_id": current["base_fact_id"]}
    second = edit(client, variant_id, refreshed)
    assert second.status_code == 201 and second.json()["effective_facts"]["utqg_treadwear"] == 420
    assert second.json()["history"][0]["before"]["value"] == 320
    assert first["base_fact_id"] != current["base_fact_id"]


@pytest.mark.parametrize("change", [
    {"field": "load_index"}, {"field": "gtin"}, {"field": "technology_features"},
    {"field": "source_markings"}, {"field": "evidence_spans"}, {"field": "acoustic_foam"},
    {"value": True}, {"value": "420"}, {"value": -1}, {"value": 10 ** 1000},
    {"reason": ""}, {"operator": ""}, {"evidence": []},
    {"action": "revoke"}, {"expected_revision": True}, {"operator_session_id": "injected"},
])
def test_invalid_edit_does_not_create_revisions(setup, change):
    client, _, database = setup
    variant_id, _, _, payload = prepare(client)
    assert edit(client, variant_id, {**payload, **change}).status_code == 422
    assert count(database, ManualFactRevision) == 0


@pytest.mark.parametrize("field,value", [("utqg_treadwear", 0), ("utqg_treadwear", None),
                                        ("for_sale", False), ("tread_depth", {"value": 7.5, "unit": "mm"})])
def test_unknown_false_zero_and_measurements_keep_their_semantics(setup, field, value):
    client, _, _ = setup
    variant_id, _, _, payload = prepare(client)
    response = edit(client, variant_id, {**payload, "field": field, "value": value})
    assert response.status_code == 201
    assert response.json()["effective_facts"][field] == value
    assert response.json()["history"][0]["after"]["present"] is True


def test_source_scope_and_snapshot_requirement(setup):
    client, registry, database = setup
    registry.result['variants'][0]['facts']['product_code_type'] = 'MSPN'
    variant_id, _, _, payload = prepare(client)
    assert edit(client, variant_id, payload).status_code == 201
    other = live(client, source="fixture-two").json()["variants"][0]
    assert other["id"] == variant_id  # This synthetic identity is complete.
    other_review = client.get(f"/v1/tire-variants/{variant_id}/fact-review", params={"source_id": "fixture-two", "mode": "history"}).json()
    assert other_review["revision"] == 0 and other_review["effective_facts"]["utqg_treadwear"] == 300
    assert edit(client, variant_id, {**payload, "source_id": "fixture-two"}).status_code == 409
    registry.result = success("fixture-broken", variants=[])
    assert live(client).json()["reason"] == "source_quality_quarantined"
    quarantined_id = client.get("/v1/quarantines").json()["items"][0]["id"]
    invalid = {**payload, "expected_revision": 1, "value": 440,
               "evidence": [{"snapshot_id": quarantined_id, "locator": "quarantine must not pass"}]}
    assert edit(client, variant_id, invalid).status_code == 422
    assert count(database, ManualFactRevision) == 1


def test_concurrent_edit_one_wins_without_losing_history(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'curation.db').as_posix()}", FixtureRegistry())
    with TestClient(app) as client:
        variant_id, _, _, payload = prepare(client)
        with app.state.database.sessions() as db:
            session_id = db.scalar(select(UserSession.id))
        barrier = Barrier(2)

        def write(value):
            with app.state.database.sessions() as db:
                barrier.wait()
                try:
                    return append_revision(db, variant_id, RevisionRequest(**{**payload, "value": value}), session_id)["revision"]
                except HTTPException as error:
                    return error.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, [420, 440]))
        assert sorted(results) == [1, 409]
        assert count(app.state.database, ManualFactRevision) == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_input_returns_bounded_validation_error_not_500(setup, value):
    client, _, database = setup
    variant_id, _, _, payload = prepare(client)
    response = client.post(f"/v1/tire-variants/{variant_id}/fact-revisions",
                           content=json.dumps({**payload, "value": value}), headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert "input" not in response.json()["detail"][0]
    assert count(database, ManualFactRevision) == 0
