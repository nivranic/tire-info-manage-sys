"""Behavioral contract tests; all source content here is explicitly synthetic."""

from copy import deepcopy
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, func, inspect, select, text

from version_registry import EXPECTED_SCHEMA_VERSIONS, PRE_009_VERSIONS
from admin_support import register_admin
from tire_api.db import AuditEvent, ChangeEvent, Database, FactVersion, FallbackConsent, Snapshot, TireVariant, UserSession, utcnow
from tire_api.domain import LiveQueryRequest, VariantInput, parse_size
from tire_api.main import create_app
from tire_api.service import QueryService


VARIANT = {
    "brand": "Fixture Brand", "model": "Fixture Tire", "manufacturer_product_code": "FIX-001",
    "region": "US", "size": "265/40ZR20", "load_index": "104", "speed_rating": "Y",
    "xl": True, "hl": False, "oe_mark": "LUC", "acoustic_technology": "Fixture Acoustic",
    "run_flat": False, "source_variant_name": "fixture-one", "facts": {"utqg_treadwear": 300},
}
QUERY = {"query": {"size": "265/40R20", "model": "Fixture Tire"}, "fallback_policy": "ask"}


def success(body="fixture-body-v1", variants=None, **kwargs):
    return {"status": "ok", "url": "https://fixture.example/tires/product",
            "body": body, "content_type": "text/html", "etag": '"fixture-etag"',
            "parser_version": "fixture@1", "variants": deepcopy(variants if variants is not None else [VARIANT]),
            **kwargs}


class FixtureRegistry:
    def __init__(self):
        self.result = success()
        self.calls = []

    def sources(self):
        return [{"id": source_id, "name": source_id, "region": "US", "source_class": "test_fixture",
                 "status": "ready", "homepage": "https://fixture.example", "description": "test fixture only"}
                for source_id in ("fixture", "fixture-two")]

    async def fetch(self, source_id, query, cached=None, *, on_observation=None):
        self.calls.append((source_id, query, cached))
        return deepcopy(self.result)


@pytest.fixture
def setup():
    registry = FixtureRegistry()
    app = create_app("sqlite://", registry)
    with TestClient(app) as client:
        # 身份/事实治理与解析器发布等管理写已要求管理员；本夹具是套件 majority
        # 的共享基座（第57轮圆桌后统一在此注册，替代各文件自行补注册）。
        register_admin(client)
        yield client, registry, app.state.database


def live(client, payload=None, source="fixture"):
    return client.post(f"/v1/sources/{source}/live-query", json=payload or QUERY)


def grant(client, query_id, decision="allow"):
    return client.post("/v1/fallback-consents", json={"query_id": query_id, "decision": decision, "scope": "once"})


def count(database, model):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_empty_database_and_local_boundary(setup):
    client, registry, database = setup
    assert client.get("/health").json() == {"status": "ok", "mode": "local_single_user_poc", "database": "sqlite"}
    assert len(client.get("/v1/sources").json()["sources"]) == 2
    assert client.get("/v1/watchlists").json()["items"] == []
    assert count(database, Snapshot) == 0
    fresh = TestClient(client.app)
    assert "HttpOnly" in fresh.get("/health").headers.get("set-cookie", "")
    assert client.get("/health", headers={"Origin": "https://attacker.example"}).status_code == 403
    assert client.post("/v1/compare", json={"variant_ids": ["x"]}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/health", headers={"Host": "attacker.example"}).status_code == 400


def test_live_preserves_same_page_conflict_without_choosing_xl(setup):
    client, registry, database = setup
    variant = deepcopy(VARIANT)
    variant["xl"] = None
    variant["facts"]["source_field_conflicts"] = [{"field": "xl", "values": [
        {"source_field": "extraLoad", "value": False}, {"source_field": "manufMarkings", "value": "XL"}],
        "resolution": "unresolved"}]
    registry.result = success(variants=[variant])
    body = live(client).json()
    assert body["data_state"] == "live"
    assert body["variants"][0]["xl"] is None
    assert body["conflicts"][0]["scope"] == "same_source_snapshot"
    assert body["conflicts"][0]["source_id"] == "fixture"
    assert body["conflicts"][0]["snapshot_id"] == body["provenance"][0]["snapshot_id"]
    assert body["conflicts"][0]["values"][0]["value"] is False


@pytest.mark.parametrize("size,expected", [(" 265 /40 zr20 ", "265/40ZR20"), ("225/45R18", "225/45R18")])
def test_size_is_canonical_but_preserves_zr(size, expected):
    assert parse_size(size) == expected


@pytest.mark.parametrize("size", ["2654020", "265/40R20 XL 104Y", "26/40R20", "265/00R20", "265/40R99"])
def test_bad_size_rejected(size):
    with pytest.raises(ValueError):
        parse_size(size)


def test_unknown_identity_is_not_false_and_skus_do_not_merge():
    original = VariantInput.model_validate(VARIANT)
    for change in ({"oe_mark": "T0"}, {"region": "CN"}, {"manufacturer_product_code": "OTHER"},
                   {"xl": None}, {"acoustic_technology": None}, {"run_flat": True}, {"size": "265/40R20"}):
        other = VariantInput.model_validate({**VARIANT, **change})
        assert original.identity_key("source", "query", 0)[0] != other.identity_key("source", "query", 0)[0]
    unknown = VariantInput.model_validate({**VARIANT, "xl": None})
    assert unknown.xl is None
    assert unknown.identity_key("a", "q", 0)[0] != unknown.identity_key("b", "q", 0)[0]
    no_code = VariantInput.model_validate({**VARIANT, "manufacturer_product_code": None})
    assert no_code.identity_key("a", "q", 0)[0] != no_code.identity_key("a", "q", 1)[0]
    with_gtin = VariantInput.model_validate({**VARIANT, "facts": {"gtin": "00012345678905"}})
    other_gtin = VariantInput.model_validate({**VARIANT, "facts": {"gtin": "00012345678912"}})
    assert with_gtin.identity_key("a", "q", 0)[0] != other_gtin.identity_key("a", "q", 0)[0]
    with pytest.raises(ValidationError):
        VariantInput.model_validate({**VARIANT, "xl": "false"})


def test_live_persists_evidence_and_no_fixture_is_seeded(setup):
    client, registry, database = setup
    response = live(client)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["data_state"] == "live"
    assert data["variants"][0]["manufacturer_product_code"] == "FIX-001"
    assert data["snapshot_observed_at"] == data["verified_at"]
    evidence = client.get(f"/v1/evidence/{data['provenance'][0]['snapshot_id']}").json()
    assert evidence["body"] == "fixture-body-v1"
    assert len(evidence["raw_hash"]) == 64
    assert evidence["data_state"] == "local_snapshot"
    assert count(database, Snapshot) == count(database, FactVersion) == count(database, TireVariant) == 1


def test_failed_query_never_reads_facts_before_consent(setup):
    client, registry, database = setup
    live(client)
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    event.listen(database.engine, "before_cursor_execute", capture)
    try:
        registry.result = {"status": "unavailable", "reason": "network_unavailable"}
        data = live(client).json()
        assert data["data_state"] == "consent_required"
        assert data["variants"] == data["provenance"] == []
        assert data["verified_at"] is None
        never = live(client, {**QUERY, "fallback_policy": "never"}).json()
        assert never["data_state"] == "source_unavailable"
        denied = grant(client, data["query_id"], "deny")
        assert denied.status_code == 201
        assert live(client, {**QUERY, "consent_id": denied.json()["id"]}).status_code == 403
        assert not any("fact_versions" in statement.lower() or "snapshots.parsed_variants" in statement.lower()
                       for statement in statements if statement.lstrip().upper().startswith("SELECT"))
    finally:
        event.remove(database.engine, "before_cursor_execute", capture)


def test_allow_is_scoped_single_use_and_returns_explicit_snapshot(setup):
    client, registry, database = setup
    first = live(client).json()
    registry.result = {"status": "unavailable", "reason": "timeout"}
    failed = live(client).json()
    consent = grant(client, failed["query_id"]).json()
    calls = len(registry.calls)
    result = live(client, {**QUERY, "consent_id": consent["id"]}).json()
    assert result["data_state"] == "local_snapshot"
    assert result["consent_id"] == consent["id"]
    assert result["snapshot_observed_at"] == first["snapshot_observed_at"]
    assert result["snapshot_age_seconds"] >= 0
    assert len(registry.calls) == calls
    assert live(client, {**QUERY, "consent_id": consent["id"]}).status_code == 409
    assert grant(client, failed["query_id"]).status_code == 409
    with database.sessions() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "local_snapshot_read")).consent_id == consent["id"]


def test_consent_query_source_session_and_policy_cannot_be_reused(setup):
    client, registry, database = setup
    registry.result = {"status": "unavailable", "reason": "timeout"}
    failed = live(client).json()
    cid = grant(client, failed["query_id"]).json()["id"]
    assert live(client, {**QUERY, "consent_id": cid}, "fixture-two").status_code == 403
    assert live(client, {**QUERY, "query": {"size": "225/45R18"}, "consent_id": cid}).status_code == 403
    assert live(client, {**QUERY, "fallback_policy": "never", "consent_id": cid}).status_code == 403
    other = TestClient(client.app)
    assert grant(other, failed["query_id"]).status_code == 404
    assert live(other, {**QUERY, "consent_id": cid}).status_code == 403
    # Invalid requests must not consume the correct grant.
    assert live(client, {**QUERY, "consent_id": cid}).json()["reason"] == "no_matching_local_snapshot"


def test_expired_and_denied_consents_cannot_read_snapshots(setup):
    client, registry, database = setup
    registry.result = {"status": "unavailable", "reason": "timeout"}
    failed = live(client).json()
    cid = grant(client, failed["query_id"]).json()["id"]
    with database.sessions() as db:
        db.get(FallbackConsent, cid).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert live(client, {**QUERY, "consent_id": cid}).status_code == 410
    second = live(client).json()
    denied = grant(client, second["query_id"], "deny").json()
    assert grant(client, second["query_id"], "allow").status_code == 409
    assert live(client, {**QUERY, "consent_id": denied["id"]}).status_code == 403


def test_304_requires_matching_verified_body_and_keeps_observation_time(setup):
    client, registry, database = setup
    first = live(client).json()
    registry.result = {"status": "not_modified", "url": "https://fixture.example/tires/product",
                       "etag": '"fixture-etag"', "parser_version": "fixture@1"}
    second = live(client).json()
    assert second["data_state"] == "live_verified_304"
    assert second["snapshot_observed_at"] == first["snapshot_observed_at"]
    assert second["verified_at"] >= first["verified_at"]
    assert second["provenance"] == first["provenance"]
    assert count(database, Snapshot) == count(database, FactVersion) == count(database, ChangeEvent) == 1
    assert registry.calls[-1][2]["body"] == "fixture-body-v1"


@pytest.mark.parametrize("override", [
    {"url": "https://fixture.example/other"}, {"etag": '"different"'}, {"parser_version": "fixture@2"},
])
def test_invalid_304_is_never_reported_live(setup, override):
    client, registry, database = setup
    live(client)
    registry.result = {"status": "not_modified", "url": "https://fixture.example/tires/product", **override}
    result = live(client).json()
    assert result["data_state"] == "consent_required"
    assert result["reason"] == "invalid_304_without_matching_evidence"
    assert result["variants"] == []


def test_304_without_body_or_validators_fails(setup):
    client, registry, database = setup
    registry.result = {"status": "not_modified", "url": "https://fixture.example/tires/product"}
    assert live(client).json()["data_state"] == "consent_required"
    registry.result = success(etag=None)
    live(client)
    registry.result = {"status": "not_modified", "url": "https://fixture.example/tires/product"}
    assert live(client).json()["data_state"] == "consent_required"


def test_latest_transport_validator_is_independent_of_immutable_snapshot(setup):
    client, registry, database = setup
    first = live(client).json()
    registry.result = success(etag='"new-etag-same-content"')
    live(client)
    registry.result = {"status": "not_modified", "url": "https://fixture.example/tires/product",
                       "etag": '"new-etag-same-content"'}
    third = live(client).json()
    assert third["data_state"] == "live_verified_304"
    assert registry.calls[-1][2]["etag"] == '"new-etag-same-content"'
    assert third["provenance"] == first["provenance"]
    assert count(database, Snapshot) == count(database, FactVersion) == 1


def test_page_only_change_and_parser_locators_do_not_create_fact_alerts(setup):
    client, registry, database = setup
    first = live(client).json()
    vid = first["variants"][0]["id"]
    client.post("/v1/watchlists", json={"variant_id": vid})
    registry.result = success("fixture-page-layout-v2", [{**VARIANT, "facts": {**VARIANT["facts"],
                                    "evidence_spans": {"utqg_treadwear": "articles[12]"},
                                    "source_updated_at": "2026-09-01T00:00:00Z"}}])
    second = live(client).json()
    assert second["data_state"] == "live"
    assert first["provenance"][0]["snapshot_id"] != second["provenance"][0]["snapshot_id"]
    assert second["variants"][0]["facts"]["evidence_spans"]
    assert count(database, Snapshot) == 2
    assert count(database, FactVersion) == count(database, ChangeEvent) == 1
    assert len(client.get("/v1/changes").json()["items"]) == 1


def test_changed_fact_and_revert_are_append_only_revisions(setup):
    client, registry, database = setup
    first = live(client).json()
    vid = first["variants"][0]["id"]
    registry.result = success("fixture-body-v2", [{**VARIANT, "facts": {"utqg_treadwear": 320}}])
    second = live(client).json()
    assert second["variants"][0]["id"] == vid
    registry.result = success()
    live(client)
    assert count(database, Snapshot) == count(database, FactVersion) == count(database, ChangeEvent) == 3
    assert client.get(f"/v1/tire-variants/{vid}").status_code == 422
    history = client.get(f"/v1/tire-variants/{vid}?mode=history").json()
    assert [row["facts"]["utqg_treadwear"] for row in history["versions"]] == [300, 320, 300]
    assert history["data_state"] == "local_snapshot"
    with database.sessions() as db:
        snapshot = db.get(Snapshot, first["provenance"][0]["snapshot_id"])
        snapshot.body = "tampered"
        with pytest.raises(ValueError, match="只能追加"):
            db.commit()


def test_unchanged_200_deduplicates_snapshot_and_facts(setup):
    client, registry, database = setup
    first = live(client).json()
    second = live(client).json()
    assert first["provenance"] == second["provenance"]
    assert count(database, Snapshot) == count(database, FactVersion) == 1


@pytest.mark.parametrize("last_status", ["ok", "not_modified"])
def test_cached_query_reconciles_facts_changed_by_another_query(setup, last_status):
    client, registry, database = setup
    known = {**VARIANT, "facts": {**VARIANT["facts"], "product_code_type": "FIXTURE_CODE"}}
    registry.result = success(variants=[known])
    first = live(client, {"query": {"size": "265/40R20"}}).json()
    vid = first["variants"][0]["id"]
    registry.result = success("fixture-body-v2", [{**known, "facts": {**known["facts"], "utqg_treadwear": 320}}])
    second = live(client).json()
    assert second["variants"][0]["fact_version"] == 2
    registry.result = success(variants=[known]) if last_status == "ok" else {
        "status": "not_modified", "url": "https://fixture.example/tires/product", "etag": '"fixture-etag"'}
    third = live(client, {"query": {"size": "265/40R20"}}).json()
    assert third["variants"][0]["fact_version"] == 3
    assert third["variants"][0]["facts"]["utqg_treadwear"] == 300
    assert third["snapshot_observed_at"] == first["snapshot_observed_at"]
    assert third["provenance"] == first["provenance"]
    assert count(database, Snapshot) == 2
    assert count(database, FactVersion) == count(database, ChangeEvent) == 3
    history = client.get(f"/v1/tire-variants/{vid}?mode=history").json()
    assert history["fact_version"] == 3
    assert history["facts"]["utqg_treadwear"] == 300


def test_compare_watch_and_changes_are_explicit_history(setup):
    client, registry, database = setup
    vid = live(client).json()["variants"][0]["id"]
    watch = client.post("/v1/watchlists", json={"variant_id": vid}).json()
    again = client.post("/v1/watchlists", json={"variant_id": vid}).json()
    assert again["id"] == watch["id"]
    assert client.get("/v1/watchlists").json()["items"][0]["variant"]["id"] == vid
    comparison = client.post("/v1/compare", json={"variant_ids": [vid]}).json()
    assert comparison["data_state"] == "local_snapshot"
    assert comparison["variants"][0]["snapshot_id"]
    assert client.post("/v1/compare", json={"variant_ids": [vid, vid]}).status_code == 422
    other = TestClient(client.app)
    assert other.get("/v1/watchlists").json()["items"] == []
    assert other.delete(f"/v1/watchlists/{watch['id']}").status_code == 404
    assert client.delete(f"/v1/watchlists/{watch['id']}").status_code == 204
    assert client.get("/v1/changes").json()["items"] == []


def test_source_mismatch_or_bad_schema_cannot_become_a_fact(setup):
    client, registry, database = setup
    registry.result = success(variants=[{**VARIANT, "size": "225/45R18"}])
    result = live(client).json()
    assert result["data_state"] == "consent_required"
    assert result["reason"] == "source_schema_validation_failed"
    assert count(database, Snapshot) == count(database, TireVariant) == 0
    assert live(client, {"query": {"size": "garbage"}}).status_code == 422
    assert live(client, {"query": {"size": "265/40R20", "url": "http://localhost"}}).status_code == 422
    assert live(client, source="not-registered").status_code == 404


@pytest.mark.parametrize("alias,model", [("PSEV", "Pilot Sport EV"), ("PS4S", "Pilot Sport 4 S"),
                                       ("Michelin Pilot Sport EV", "Pilot Sport EV")])
def test_supported_model_aliases_are_canonical_before_fetch(setup, alias, model):
    client, registry, database = setup
    registry.result = success(variants=[{**VARIANT, "model": model}])
    result = live(client, {"query": {"size": "265/40R20", "model": alias}}).json()
    assert result["data_state"] == "live"
    assert registry.calls[-1][1]["model"] == model


def test_cross_source_conflicts_are_kept_with_both_evidence_links(setup):
    client, registry, database = setup
    known = {**VARIANT, "facts": {**VARIANT["facts"], "product_code_type": "FIXTURE_CODE"}}
    registry.result = success(variants=[known])
    original = live(client).json()
    registry.result = success("fixture-other-source", [{**known, "facts": {**known["facts"], "utqg_treadwear": 400}}])
    other = live(client, source="fixture-two").json()
    assert original["variants"][0]["id"] == other["variants"][0]["id"]
    assert other["conflicts"] == []
    historical = client.post("/v1/compare", json={"variant_ids": [other["variants"][0]["id"]]}).json()
    assert len(historical["conflicts"]) == 1
    conflict = historical["conflicts"][0]
    assert conflict["field"] == "utqg_treadwear"
    assert {row["value"] for row in conflict["values"]} == {300, 400}
    assert all(row["snapshot_id"] and row["observed_at"] for row in conflict["values"])
    assert count(database, FactVersion) == 2


def test_api_and_worker_ingestion_cannot_create_duplicate_revisions(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'concurrent.db').as_posix()}")
    database.initialize()
    gate = Barrier(2)

    class ConcurrentRegistry(FixtureRegistry):
        async def fetch(self, source_id, query, cached=None, *, on_observation=None):
            await asyncio.to_thread(gate.wait, timeout=5)
            return success()

    registry = ConcurrentRegistry()
    with database.sessions() as db:
        for actor in ("api", "worker"):
            db.add(UserSession(id=actor, expires_at=utcnow() + timedelta(hours=1)))
        db.commit()

    def execute(actor):
        with database.sessions() as db:
            return asyncio.run(QueryService(db, registry).execute(
                "fixture", LiveQueryRequest.model_validate({**QUERY, "fallback_policy": "never"}), actor))

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(execute, ("api", "worker")))
        assert all(result["data_state"] == "live" for result in results)
        assert count(database, Snapshot) == count(database, FactVersion) == count(database, ChangeEvent) == 1
    finally:
        database.close()


def test_legacy_schema_upgrade_preserves_evidence_facts_and_watchlist(tmp_path):
    url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    registry = FixtureRegistry()
    app = create_app(url, registry)
    with TestClient(app) as client:
        result = live(client).json()
        snapshot_id = result["provenance"][0]["snapshot_id"]
        client.post("/v1/watchlists", json={"variant_id": result["variants"][0]["id"]})
        evidence_before = client.get(f"/v1/evidence/{snapshot_id}").json()
        cookies = dict(client.cookies)

    # Reconstruct the prior verification schema in this test-only database.
    database = Database(url)
    with database.engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE verifications RENAME TO old_verifications")
        connection.exec_driver_sql("CREATE TABLE verifications (id VARCHAR(64) PRIMARY KEY, snapshot_id VARCHAR(64) NOT NULL, query_id VARCHAR(64) NOT NULL, source_id VARCHAR(80) NOT NULL, query_key VARCHAR(64) NOT NULL, status VARCHAR(24) NOT NULL, verified_at DATETIME NOT NULL)")
        connection.exec_driver_sql("INSERT INTO verifications SELECT id,snapshot_id,query_id,source_id,query_key,status,verified_at FROM old_verifications")
        connection.exec_driver_sql("DROP TABLE old_verifications")
        connection.execute(text("DELETE FROM tire_schema_versions WHERE version = :version"),
                           {"version": "001_verification_validators"})
        connection.execute(text("DELETE FROM tire_schema_versions WHERE version = :version"),
                           {"version": "003_parser_release_provenance"})
    database.close()

    upgraded = create_app(url, registry)
    with TestClient(upgraded, cookies=cookies) as client:
        assert client.get(f"/v1/evidence/{snapshot_id}").json() == evidence_before
        assert len(client.get("/v1/watchlists").json()["items"]) == 1
        db = upgraded.state.database
        assert count(db, FactVersion) == count(db, Snapshot) == 1
        columns = {column["name"] for column in inspect(db.engine).get_columns("verifications")}
        assert {"etag", "last_modified", "parser_identity"} <= columns
        with db.engine.connect() as connection:
            assert connection.execute(text("SELECT etag FROM verifications")).scalar() is None
            assert connection.execute(text("SELECT parser_identity FROM verifications")).scalar() is None
            assert set(connection.execute(text("SELECT version FROM tire_schema_versions")).scalars()) == set(EXPECTED_SCHEMA_VERSIONS)
        # Idempotent startup; no repeated mutation or loss of old observations.
        db.initialize()
        assert count(db, Snapshot) == 1
