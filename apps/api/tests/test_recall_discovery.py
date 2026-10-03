"""Single-page search uses synthetic fixtures and isolated databases only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from tire_api.adapters import nhtsa
from tire_api.db import FallbackConsent, QueryRun, RawCapture, RejectedObservation, TireVariant, utcnow
from tire_api.db import UserSession
from tire_api.main import create_app
from tire_api.recall_discovery import RecallDiscoveryService, RecallSearchRequest, RecallSearchSnapshot, RecallSearchVerification
from tire_api.recall_models import RecallRevision, RecallSnapshot

IDENTITY = {"bundle_id": "a" * 64, "parser_digest": "b" * 64, "deployment_revision": 1}


def product(identifier=1, campaign=True):
    campaigns = [{"campaign_number": "26T008000", "subject": "Synthetic recall", "report_received_at": "2026-02-11T19:47:18Z",
        "summary": "Synthetic TIN restriction", "consequence": "Synthetic consequence", "remedy": "Synthetic remedy",
        "manufacturer": "Synthetic maker", "notes": None, "documents": [],
        "associated_products": [{"type": "Tire", "productMake": "SYNTHETIC", "productModel": "DEMO"}]}] if campaign else []
    return {"id": identifier, "artemis_id": 1000 + identifier, "brand": "SYNTHETIC", "tireline": "DEMO",
            "size": "LT305/65R17", "recalls_count": len(campaigns), "campaigns": campaigns,
            "applicability": "not_assessed"}


class SearchFixture:
    def __init__(self):
        self.products = [product()]
        self.offline = False
        self.not_modified = False
        self.identity = deepcopy(IDENTITY)
        self.calls = []
        self.mutate = None
        self.after_observation_error = False

    async def fetch(self, query, cached=None, *, on_observation=None):
        self.calls.append({"query": deepcopy(query), "cached": deepcopy(cached)})
        if self.offline:
            return {"status": "unavailable", "reason": "synthetic_outage"}
        offset = int(query["offset"])
        rows = self.products[offset:offset + 10]
        discovery = {"products": deepcopy(rows), "pagination": {"offset": offset, "max": 10, "count": len(rows),
            "total": len(self.products), "has_next": offset + len(rows) < len(self.products), "has_previous": offset > 0}}
        result = {"status": "not_modified" if self.not_modified else "ok", "url": nhtsa.query_url(query),
            "content_type": "application/json", "parser_version": "synthetic-search@1", "parser_identity": deepcopy(self.identity),
            "etag": '"synthetic-search"', "last_modified": None}
        if not self.not_modified:
            result.update(body=json.dumps({"synthetic_search": discovery}), discovery=discovery)
        if self.mutate:
            self.mutate(result)
        if not self.not_modified and on_observation:
            on_observation(result)
        if self.after_observation_error:
            raise ValueError("synthetic parser failure after receipt")
        return result


class NoTireSource:
    def sources(self):
        return [{"id": "synthetic", "status": "ready", "supported_models": ["Synthetic"]}]

    async def fetch(self, *_args, **_kwargs):
        return {"status": "unavailable", "reason": "synthetic_outage"}


@pytest.fixture
def setup(tmp_path):
    app = create_app("sqlite:///" + (tmp_path / "search.db").as_posix(), NoTireSource())
    adapter = SearchFixture()
    app.state.recall_adapter = adapter
    with TestClient(app) as client:
        yield client, adapter, app.state.database, app


def search(client, *, term="SYNTHETIC DEMO", offset=0, **extra):
    return client.post("/v1/recalls/search", json={"query": {"search": term, "offset": offset}, **extra})


def grant(client, query_id, decision="allow"):
    response = client.post("/v1/fallback-consents", json={"query_id": query_id, "decision": decision, "scope": "once"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def count(database, model):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_live_search_preserves_page_evidence_without_adopting_recall_or_sku(setup):
    client, adapter, database, _ = setup
    response = search(client, term="  SYNTHETIC   DEMO  ")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["data_state"] == "live" and data["query"] == {"search": "SYNTHETIC DEMO", "offset": "0"}
    assert data["products"][0]["applicability"] == "not_assessed"
    assert data["pagination"] == {"offset": 0, "max": 10, "count": 1, "total": 1, "has_next": False, "has_previous": False}
    evidence = client.get(data["provenance"][0]["evidence_path"]).json()
    assert evidence["data_state"] == "local_snapshot" and "synthetic_search" in evidence["body"]
    assert client.get("/v1/recall-search-evidence/" + evidence["id"]).status_code == 422
    assert count(database, RecallSearchSnapshot) == count(database, RecallSearchVerification) == 1
    assert count(database, RecallRevision) == count(database, RecallSnapshot) == count(database, TireVariant) == 0
    with database.sessions() as db:
        capture = db.scalar(select(RawCapture))
        assert capture.target_kind == "recall" and capture.source_id == "nhtsa-us-recalls"


def test_late_304_cannot_replace_a_newer_page_from_another_session(setup):
    client, adapter, database, _ = setup
    first = search(client).json()
    original_fetch = adapter.fetch
    other = SearchFixture()
    other.products[0]['tireline'] = 'CHANGED PRODUCT'
    with database.sessions() as db:
        db.add(UserSession(id='other-search-session', expires_at=utcnow() + timedelta(hours=1)))
        db.commit()

    async def overlap(query, cached=None, *, on_observation=None):
        with database.sessions() as db:
            updated = await RecallDiscoveryService(db, other).execute(
                RecallSearchRequest(query={'search': query['search'], 'offset': int(query['offset'])}), 'other-search-session')
            assert updated['data_state'] == 'live'
        adapter.not_modified = True
        return await original_fetch(query, cached=cached, on_observation=on_observation)

    adapter.fetch = overlap
    late = search(client, fallback_policy='never').json()
    assert late['data_state'] == 'source_unavailable' and late['reason'] == 'recall_search_cache_head_changed'
    assert late['products'] == [] and late['provenance'] == []
    history = client.get('/v1/recalls/search-history', params={'search':'SYNTHETIC DEMO', 'mode':'history'}).json()
    assert history['products'][0]['tireline'] == 'CHANGED PRODUCT'
    assert history['provenance'] != first['provenance']
    assert count(database, RecallSearchSnapshot) == count(database, RecallSearchVerification) == 2


@pytest.mark.parametrize("query", [{"search": "  "}, {"search": "x", "offset": 1}, {"search": "x", "offset": True},
    {"search": "x", "offset": "10"}, {"search": "x", "offset": 10010}, {"search": "x", "campaign_number": "26T008000"}])
def test_invalid_query_never_fetches(setup, query):
    client, adapter, _, _ = setup
    assert client.post("/v1/recalls/search", json={"query": query}).status_code == 422
    assert adapter.calls == []


def test_pages_are_explicit_and_empty_does_not_mean_safe(setup):
    client, adapter, database, _ = setup
    adapter.products = [product(i, campaign=i == 11) for i in range(1, 12)]
    first = search(client).json()
    assert first["pagination"]["has_next"] and all(not item["campaigns"] for item in first["products"])
    second = search(client, offset=10).json()
    assert second["pagination"]["has_previous"] and second["products"][0]["campaigns"]
    assert second["provenance"][0]["snapshot_id"] != first["provenance"][0]["snapshot_id"]
    adapter.products = []
    empty = search(client).json()
    assert empty["data_state"] == "live" and empty["reason"] == "no_results" and empty["pagination"]["total"] == 0
    adapter.offline = True
    failed = search(client, fallback_policy="never").json()
    assert failed["data_state"] == "source_unavailable" and failed["pagination"] is None and failed["reason"] != "no_results"
    assert count(database, RecallRevision) == 0


def test_failure_does_not_read_parsed_history_before_atomic_consent(setup):
    client, adapter, database, _ = setup
    assert search(client).json()["data_state"] == "live"
    adapter.offline = True
    statements = []
    def track(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())
    event.listen(database.engine, "before_cursor_execute", track)
    try:
        failed = search(client).json()
        assert failed["data_state"] == "consent_required" and failed["products"] == []
        assert not any("recall_search_snapshots.discovery" in sql for sql in statements)
        token = grant(client, failed["query_id"])
        statements.clear()
        local = search(client, consent_id=token).json()
        assert local["data_state"] == "local_snapshot" and local["products"]
        claimed = next(i for i, sql in enumerate(statements) if sql.startswith("update fallback_consents"))
        read = next(i for i, sql in enumerate(statements) if "recall_search_snapshots.discovery" in sql)
        assert claimed < read
        assert search(client, consent_id=token).status_code == 409
        assert len(adapter.calls) == 2
    finally:
        event.remove(database.engine, "before_cursor_execute", track)


def test_consent_is_bound_to_query_page_session_policy_and_domain(setup):
    client, adapter, _, app = setup
    adapter.offline = True
    failed = search(client).json()
    token = grant(client, failed["query_id"])
    assert search(client, term="OTHER", consent_id=token).status_code == 403
    assert search(client, offset=10, consent_id=token).status_code == 403
    assert search(client, fallback_policy="never", consent_id=token).status_code == 403
    with TestClient(app) as other:
        assert search(other, consent_id=token).status_code == 403
    campaign = client.post("/v1/recalls/live-query", json={"query": {"campaign_number": "26T008000"}}).json()
    campaign_token = grant(client, campaign["query_id"])
    assert search(client, consent_id=campaign_token).status_code == 403
    assert client.post("/v1/recalls/live-query", json={"query": {"campaign_number": "26T008000"}, "consent_id": token}).status_code == 403
    assert search(client, consent_id=token).status_code == 200


def test_denied_and_expired_consent_never_read_snapshot(setup):
    client, adapter, database, _ = setup
    search(client)
    adapter.offline = True
    denied = grant(client, search(client).json()["query_id"], "deny")
    assert search(client, consent_id=denied).status_code == 403
    expired = grant(client, search(client).json()["query_id"])
    with database.sessions() as db:
        db.get(FallbackConsent, expired).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert search(client, consent_id=expired).status_code == 410


def test_explicit_history_requires_mode_and_exact_page(setup):
    client, adapter, _, _ = setup
    live = search(client).json()
    assert client.get("/v1/recalls/search-history?search=SYNTHETIC%20DEMO").status_code == 422
    historical = client.get("/v1/recalls/search-history?mode=history&search=SYNTHETIC%20DEMO").json()
    assert historical["data_state"] == "local_snapshot" and historical["provenance"] == live["provenance"]
    missing = client.get("/v1/recalls/search-history?mode=history&search=SYNTHETIC%20DEMO&offset=10").json()
    assert missing["products"] == [] and missing["reason"] == "no_matching_recall_search_snapshot"
    assert len(adapter.calls) == 1


def test_raw_capture_survives_parse_failure_and_schema_rejection(setup):
    client, adapter, database, _ = setup
    adapter.after_observation_error = True
    assert search(client).json()["data_state"] == "consent_required"
    assert count(database, RawCapture) == 1 and count(database, RecallSearchSnapshot) == 0
    adapter.after_observation_error = False
    adapter.mutate = lambda result: result["discovery"]["pagination"].update(total=9)
    assert search(client).json()["reason"] == "recall_search_schema_changed"
    assert count(database, RawCapture) == 2 and count(database, RejectedObservation) == 1


def test_valid_304_deduplicates_but_changed_parser_identity_fails_without_history_read(setup):
    client, adapter, database, _ = setup
    initial = search(client).json()
    adapter.not_modified = True
    reused = search(client).json()
    assert reused["data_state"] == "live_verified_304" and reused["provenance"] == initial["provenance"]
    with database.sessions() as db:
        assert db.get(QueryRun, reused["query_id"]).state == "live"
    assert count(database, RecallSearchSnapshot) == 1 and count(database, RecallSearchVerification) == 2
    adapter.identity = {**IDENTITY, "deployment_revision": 2}
    assert search(client).json()["data_state"] == "consent_required"
    assert count(database, RecallSearchVerification) == 2


@pytest.mark.parametrize("mutation", [
    lambda row: row.pop("parser_identity"),
    lambda row: row.pop("parser_version"),
    lambda row: row.update(etag='"different-validator"'),
    lambda row: row.update(body="tampered 304 body"),
])
def test_invalid_304_never_reads_parsed_candidates(setup, mutation):
    client, adapter, database, _ = setup
    search(client)
    adapter.not_modified = True
    adapter.mutate = mutation
    statements = []
    def track(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())
    event.listen(database.engine, "before_cursor_execute", track)
    try:
        failed = search(client).json()
        assert failed["data_state"] == "consent_required" and failed["products"] == []
        assert not any("recall_search_snapshots.discovery" in sql for sql in statements)
        assert count(database, RecallSearchVerification) == 1
    finally:
        event.remove(database.engine, "before_cursor_execute", track)


def test_source_text_is_preserved_and_external_document_rejected(setup):
    client, adapter, database, _ = setup
    campaign = adapter.products[0]["campaigns"][0]
    campaign["summary"] = "  Official source whitespace.  "
    campaign["documents"] = [{"url": "https://static.nhtsa.gov/odi/rcl/2021/RCLRPT-21T001-4277.PDF", "title": " Official PDF "}]
    data = search(client).json()
    assert data["products"][0]["campaigns"][0]["summary"] == "  Official source whitespace.  "
    assert data["products"][0]["campaigns"][0]["documents"][0]["title"] == " Official PDF "
    campaign["documents"][0]["url"] = "https://example.org/forged.pdf"
    assert search(client).json()["data_state"] == "consent_required"
    assert count(database, RecallSearchSnapshot) == 1


def test_concurrent_fallback_consumption_is_once(setup):
    client, adapter, database, _ = setup
    search(client)
    adapter.offline = True
    token = grant(client, search(client).json()["query_id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _n: search(client, consent_id=token), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert count(database, RecallSearchSnapshot) == 1


def test_parallel_duplicate_queries_share_immutable_snapshot(setup):
    client, adapter, database, _ = setup
    search(client)  # Establish the local session before the concurrent requests.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _n: search(client).json(), range(2)))
    assert all(result["data_state"] == "live" for result in results)
    assert len({row["provenance"][0]["snapshot_id"] for row in results}) == 1
    assert count(database, RecallSearchSnapshot) == 1 and count(database, RecallSearchVerification) == 3
    assert count(database, RecallRevision) == 0
    with database.sessions() as db:
        snapshot = db.scalar(select(RecallSearchSnapshot))
        snapshot.body = "changed"
        with pytest.raises(ValueError, match="只能追加"):
            db.commit()
