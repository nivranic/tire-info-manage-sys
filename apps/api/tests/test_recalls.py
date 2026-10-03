"""Recall evidence/consent behavior with clearly synthetic transport fixtures."""
from copy import deepcopy
from datetime import timedelta
import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, func, select

from tire_api.db import FactVersion, FallbackConsent, QueryRun, RawCapture, TireVariant, utcnow
from tire_api.main import create_app
from tire_api.recall_models import RecallEvent, RecallRevision, RecallSnapshot, RecallVerification
from tire_api.recalls import campaign_url

CAMPAIGN = "23T001000"
IDENTITY = {"bundle_id": "a" * 64, "parser_digest": "b" * 64, "deployment_revision": 1}


def record(model="SYNTHETIC A"):
    return {"campaign_number": CAMPAIGN, "manufacturer": "Synthetic manufacturer", "report_received_date": "2023-03-02",
        "report_received_date_raw": "02/03/2023", "component": "TIRES", "potential_units": 123,
        "summary": "Synthetic summary", "consequence": "Synthetic consequence", "remedy": "Synthetic remedy",
        "notes": None, "make": "SYNTHETIC", "model": model, "model_year_raw": "9999", "applicability": "not_assessed"}


class RecallFixture:
    def __init__(self):
        self.rows = [record()]
        self.offline = False
        self.not_modified = False
        self.calls = []
        self.identity = deepcopy(IDENTITY)

    async def fetch(self, query, cached=None, *, on_observation=None):
        self.calls.append({"query": deepcopy(query), "cached": deepcopy(cached)})
        if self.offline:
            return {"status": "unavailable", "reason": "synthetic_outage"}
        result = {"status": "not_modified" if self.not_modified else "ok", "url": campaign_url(query["campaign_number"]),
                  "content_type": "application/json", "parser_version": "synthetic-recall@1",
                  "parser_identity": deepcopy(self.identity), "etag": '"fixture-v1"', "last_modified": None}
        if not self.not_modified:
            result.update(body=json.dumps({"synthetic": self.rows}), records=deepcopy(self.rows))
            if on_observation:
                on_observation(result)
        return result


class NoTireSource:
    def sources(self):
        return [{"id": "synthetic", "status": "ready", "supported_models": ["Synthetic"]}]

    async def fetch(self, *_args, **_kwargs):
        return {"status": "unavailable", "reason": "synthetic_outage"}


@pytest.fixture
def recall_setup(tmp_path):
    app = create_app("sqlite:///" + (tmp_path / "recalls.db").as_posix(), NoTireSource())
    adapter = RecallFixture()
    app.state.recall_adapter = adapter
    with TestClient(app) as client:
        yield client, adapter, app.state.database, app


def live(client, **extra):
    return client.post("/v1/recalls/live-query", json={"query": {"campaign_number": CAMPAIGN}, **extra})


def count(database, model):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model))


def grant(client, query_id):
    response = client.post("/v1/fallback-consents", json={"query_id": query_id, "decision": "allow", "scope": "once"})
    assert response.status_code == 201
    return response.json()["id"]


def test_recall_live_evidence_is_separate_and_preserves_raw_date(recall_setup):
    client, adapter, database, _ = recall_setup
    response = client.post("/v1/recalls/live-query", json={"query": {"campaign_number": "23t001000"}})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["data_state"] == "live" and data["revision"] == 1
    assert data["records"][0]["report_received_date"] == "2023-03-02"
    assert data["records"][0]["report_received_date_raw"] == "02/03/2023"
    assert data["records"][0]["model_year_raw"] == "9999"
    assert data["records"][0]["applicability"] == "not_assessed"
    assert data["provenance"][0]["parser_identity"] == IDENTITY
    evidence = client.get(data["provenance"][0]["evidence_path"]).json()
    assert evidence["data_state"] == "local_snapshot" and "synthetic" in evidence["body"]
    assert client.get("/v1/recall-evidence/" + evidence["id"]).status_code == 422
    assert count(database, RecallRevision) == count(database, RawCapture) == 1
    assert count(database, TireVariant) == count(database, FactVersion) == 0


@pytest.mark.parametrize("query", [{"campaign_number": "23V001000"}, {"campaign_number": "２３T001000"},
    {"campaign_number": "23T001000", "model": "x"}, {"model": "ALTIMAX RT43"}])
def test_invalid_campaign_queries_do_not_fetch(recall_setup, query):
    client, adapter, _, _ = recall_setup
    assert client.post("/v1/recalls/live-query", json={"query": query}).status_code == 422
    assert not adapter.calls


def test_complete_records_are_order_invariant_and_empty_never_resolves(recall_setup):
    client, adapter, database, _ = recall_setup
    adapter.rows = [record("A"), record("B")]
    assert live(client).json()["revision"] == 1
    adapter.rows.reverse()
    assert live(client).json()["revision"] == 1
    adapter.rows = []
    empty = live(client).json()
    assert empty["data_state"] == "live" and empty["reason"] == "no_results" and empty["records"] == []
    assert count(database, RecallRevision) == count(database, RecallEvent) == 1
    adapter.rows = [record("A"), record("B")]
    assert live(client).json()["revision"] == 1
    adapter.rows[1]["remedy"] = "Updated synthetic remedy"
    assert live(client).json()["revision"] == 2
    history = client.get(f"/v1/recalls/{CAMPAIGN}/history?mode=history").json()
    assert [item["kind"] for item in history["revisions"]] == ["content_changed", "first_observed"]
    assert history["revisions"][1]["records"] != history["revisions"][0]["records"]
    assert count(database, RecallEvent) == 2


def test_failure_never_selects_stored_records_until_atomic_one_use_consent(recall_setup):
    client, adapter, database, _ = recall_setup
    assert live(client).json()["data_state"] == "live"
    adapter.offline = True
    statements = []
    def track(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())
    event.listen(database.engine, "before_cursor_execute", track)
    try:
        failed = live(client).json()
        assert failed["data_state"] == "consent_required" and failed["records"] == []
        assert not any("recall_snapshots.records" in sql or "from recall_revisions" in sql for sql in statements)
        token = grant(client, failed["query_id"])
        statements.clear()
        result = live(client, consent_id=token).json()
        assert result["data_state"] == "local_snapshot" and result["records"]
        claim = next(i for i, sql in enumerate(statements) if sql.startswith("update fallback_consents"))
        read = next(i for i, sql in enumerate(statements) if "recall_snapshots.records" in sql)
        assert claim < read
        assert live(client, consent_id=token).status_code == 409
        assert len(adapter.calls) == 2
    finally:
        event.remove(database.engine, "before_cursor_execute", track)


def test_consent_cannot_cross_session_campaign_domain_or_never(recall_setup):
    client, adapter, _, app = recall_setup
    adapter.offline = True
    token = grant(client, live(client).json()["query_id"])
    assert live(client, consent_id=token, fallback_policy="never").status_code == 403
    assert client.post("/v1/recalls/live-query", json={"query": {"campaign_number": "23T002000"}, "consent_id": token}).status_code == 403
    with TestClient(app) as other:
        assert live(other, consent_id=token).status_code == 403
    tire_run = client.post("/v1/sources/synthetic/live-query", json={"query": {"model": "Synthetic"}}).json()
    tire_token = grant(client, tire_run["query_id"])
    assert live(client, consent_id=tire_token).status_code == 403


def test_expired_consent_does_not_read_history(recall_setup):
    client, adapter, database, _ = recall_setup
    adapter.offline = True
    token = grant(client, live(client).json()["query_id"])
    with database.sessions() as db:
        db.get(FallbackConsent, token).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert live(client, consent_id=token).status_code == 410


def test_304_requires_same_parser_identity_and_preserves_snapshot(recall_setup):
    client, adapter, database, _ = recall_setup
    first = live(client).json()
    adapter.not_modified = True
    again = live(client).json()
    assert again["data_state"] == "live_verified_304", again
    assert again["provenance"][0]["snapshot_id"] == first["provenance"][0]["snapshot_id"]
    assert count(database, RecallSnapshot) == count(database, RecallEvent) == 1
    assert count(database, RecallVerification) == 2
    adapter.identity["deployment_revision"] = 2
    assert live(client).json()["data_state"] == "consent_required"
    assert count(database, RecallVerification) == 2


def test_invalid_result_preserves_raw_but_writes_no_formal_evidence(recall_setup):
    client, adapter, database, _ = recall_setup
    adapter.rows[0]["applicability"] = "safe"
    assert live(client).json()["data_state"] == "consent_required"
    assert count(database, RawCapture) == 1
    assert count(database, RecallSnapshot) == count(database, RecallRevision) == 0


def test_recall_evidence_is_append_only(recall_setup):
    client, _, database, _ = recall_setup
    live(client)
    with database.sessions() as db:
        row = db.scalar(select(RecallSnapshot))
        row.records = []
        with pytest.raises(ValueError, match="只能追加"):
            db.commit()


@pytest.mark.parametrize("adapter_status", ["ok", "live"])
def test_deployed_parser_without_execution_receipt_never_adopts(recall_setup, monkeypatch, tmp_path, adapter_status):
    """Even trusted adapter output must carry the child execution receipt."""
    from tire_api.parser_provenance import parser_identity
    from tire_api.parser_release_models import ParserExecution
    client, _, database, app = recall_setup
    monkeypatch.setenv("TI_PARSER_BUNDLE_ROOT", str(tmp_path / "parser-bundles"))

    class MissingReceipt:
        supports_parser_deployments = True

        async def fetch(self, query, cached=None, *, on_observation, parser_selection):
            observation = {"url": campaign_url(CAMPAIGN), "body": json.dumps({"synthetic": [record()]}),
                "content_type": "application/json", "parser_version": parser_selection["parser_version"],
                "parser_identity": parser_identity(parser_selection)}
            on_observation(observation)
            return {"status": adapter_status, **observation, "records": [record()]}

    app.state.recall_adapter = MissingReceipt()
    result = live(client, fallback_policy="never").json()
    assert result["data_state"] == "source_unavailable", result
    assert result["reason"] in {"parser_receipt_mismatch", "parser_receipt_invalid", "recall_source_unavailable"}
    assert count(database, RawCapture) == 1 and count(database, RecallSnapshot) == 0
    with database.sessions() as db:
        assert db.scalar(select(ParserExecution)).state == ("failed" if adapter_status == "ok" else "not_started")


def test_two_sessions_reject_late_304_after_newer_campaign_adoption(recall_setup):
    import asyncio
    from tire_api.db import UserSession, uid
    from tire_api.recall_models import RecallLiveRequest
    from tire_api.recalls import RecallService
    client, adapter, database, _ = recall_setup
    first = live(client).json()
    with database.sessions() as db:
        first_session = db.get(QueryRun, first["query_id"]).session_id
        second_session = uid()
        db.add(UserSession(id=second_session, expires_at=utcnow() + timedelta(days=1)))
        db.commit()

    async def concurrent_queries():
        fetched, release = asyncio.Event(), asyncio.Event()
        class Delayed304:
            async def fetch(self, query, cached=None, *, on_observation=None):
                assert cached["snapshot_id"] == first["provenance"][0]["snapshot_id"]
                fetched.set()
                await release.wait()
                return {"status": "not_modified", "url": cached["url"], "parser_version": cached["parser_version"],
                        "parser_identity": cached["parser_identity"], "etag": cached["etag"]}
        request = RecallLiveRequest(query={"campaign_number": CAMPAIGN}, fallback_policy="never")
        async def late():
            with database.sessions() as db:
                return await RecallService(db, Delayed304()).execute(request, first_session)
        pending = asyncio.create_task(late())
        await fetched.wait()
        adapter.rows[0]["remedy"] = "Newer synthetic B remedy"
        with database.sessions() as db:
            newer = await RecallService(db, adapter).execute(request, second_session)
        assert newer["revision"] == 2 and newer["data_state"] == "live"
        release.set()
        stale = await pending
        assert stale["data_state"] == "source_unavailable" and stale["reason"] == "recall_cache_head_changed"
        assert stale["records"] == stale["provenance"] == []
    asyncio.run(concurrent_queries())
    history = client.get(f"/v1/recalls/{CAMPAIGN}/history?mode=history").json()
    assert history["revision"] == 2 and history["records"][0]["remedy"] == "Newer synthetic B remedy"
    assert count(database, RecallVerification) == count(database, RecallRevision) == count(database, RecallEvent) == 2
