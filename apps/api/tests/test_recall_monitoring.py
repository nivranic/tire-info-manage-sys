import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from test_recalls import CAMPAIGN, count, live, recall_setup
from tire_api.db import utcnow
from tire_api.monitoring import LeaseLost
from tire_api.recall_models import (RecallEvent, RecallLiveRequest, RecallMonitorJob, RecallMonitorRun,
                                   RecallNotification, RecallRevision, RecallSnapshot)
from tire_api.recall_monitoring import claim_job, finish_job, guard_claim
from tire_api.recalls import RecallService


def create_rule(client, **extra):
    response = client.post("/v1/recall-monitor-rules", json={"name": "Synthetic campaign monitoring",
        "query": {"campaign_number": CAMPAIGN}, "enabled": True, "interval_seconds": 3600, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def notifications(client):
    response = client.get("/v1/recall-notifications?mode=history")
    assert response.status_code == 200, response.text
    return response.json()


def test_notifications_first_observed_content_changed_and_empty_do_not_resolve(recall_setup):
    client, adapter, database, _ = recall_setup
    rule = create_rule(client)
    assert notifications(client)["total"] == 0
    live(client)
    notice = notifications(client)["items"][0]
    assert notice["kind"] == "first_observed" and notice["revision"] == 1
    assert notice["rule_id"] == rule["id"] and notice["previous_snapshot_id"] is None
    live(client)
    assert notifications(client)["total"] == 1
    adapter.rows[0]["remedy"] = "Changed synthetic measure"
    live(client)
    second = notifications(client)["items"][0]
    assert second["kind"] == "content_changed" and second["changes"]["before"] != second["changes"]["after"]
    adapter.rows = []
    live(client)
    adapter.offline = True
    live(client, fallback_policy="never")
    assert notifications(client)["total"] == count(database, RecallEvent) == 2
    assert client.put(f'/v1/recall-notifications/{notice["id"]}/read', json={"read": True}).json()["read_at"]
    assert client.get("/v1/recall-notifications?mode=history&unread=true").json()["total"] == 1


def test_rules_and_notifications_are_session_private_and_revisions_compare_and_swap(recall_setup):
    client, _, _, app = recall_setup
    rule = create_rule(client)
    live(client)
    notice = notifications(client)["items"][0]
    edit = {"expected_revision": 1, "name": "renamed", "enabled": True, "archived": True, "interval_seconds": 7200}
    with TestClient(app) as other:
        assert other.get("/v1/recall-monitor-rules").json()["total"] == 0
        assert notifications(other)["total"] == 0
        assert other.get(f'/v1/recall-monitor-rules/{rule["id"]}?mode=history').status_code == 404
        assert other.post(f'/v1/recall-monitor-rules/{rule["id"]}/revisions', json=edit).status_code == 404
        assert other.put(f'/v1/recall-notifications/{notice["id"]}/read', json={"read": True}).status_code == 404
    result = client.post(f'/v1/recall-monitor-rules/{rule["id"]}/revisions', json=edit)
    assert result.status_code == 200 and result.json()["revision"] == 2
    assert result.json()["enabled"] is False and result.json()["archived"] is True
    assert client.post(f'/v1/recall-monitor-rules/{rule["id"]}/revisions', json=edit).status_code == 409
    assert client.get("/v1/recall-monitor-rules").json()["total"] == 0
    detail = client.get(f'/v1/recall-monitor-rules/{rule["id"]}?mode=history').json()
    assert [row["revision"] for row in detail["history"]] == [2, 1]
    assert client.post("/v1/recall-monitor-rules", json={"name": "bad", "query": {"campaign_number": CAMPAIGN},
                       "interval_seconds": 3599}).status_code == 422
    assert client.get("/v1/recall-notifications").status_code == 422


def test_recall_source_cannot_enter_tire_monitor_rule(recall_setup):
    client, _, _, app = recall_setup
    app.state.registry.sources = lambda: [{"id": "nhtsa-us-recalls", "status": "ready",
        "target_kind": "recall", "supported_models": ["Synthetic"]}]
    response = client.post("/v1/alert-rules", json={"name": "wrong domain", "source_id": "nhtsa-us-recalls",
        "query": {"model": "Synthetic"}})
    assert response.status_code == 422


def test_only_one_worker_claims_and_expired_tokens_cannot_write_or_finish(recall_setup):
    client, adapter, database, _ = recall_setup
    rule = create_rule(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim_job(database), range(2)))
    assert sum(value is not None for value in claims) == 1
    stale = next(value for value in claims if value is not None)
    with database.sessions() as db:
        db.get(RecallMonitorJob, stale["id"]).lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    fresh = claim_job(database)
    assert fresh and fresh["token"] != stale["token"]
    async def attempt():
        with database.sessions() as db:
            await RecallService(db, adapter, ingestion_guard=lambda session: guard_claim(session, stale)).execute(
                RecallLiveRequest(query={"campaign_number": CAMPAIGN}, fallback_policy="never"), stale["session_id"])
    with pytest.raises(LeaseLost):
        asyncio.run(attempt())
    assert count(database, RecallSnapshot) == count(database, RecallNotification) == 0
    assert not finish_job(database, stale, "live")
    assert finish_job(database, fresh, "source_unavailable", "synthetic_outage")
    assert not finish_job(database, fresh, "source_unavailable", "synthetic_outage")
    assert count(database, RecallMonitorRun) == 1
    result = client.get(f'/v1/recall-monitor-rules/{rule["id"]}?mode=history').json()
    assert result["job"]["last_run"]["state"] == "source_unavailable"


def test_revision_during_transport_revokes_ingestion_lease(recall_setup):
    client, adapter, database, _ = recall_setup
    rule = create_rule(client)
    claim = claim_job(database)
    response = client.post(f'/v1/recall-monitor-rules/{rule["id"]}/revisions', json={"expected_revision": 1,
        "name": "disabled", "enabled": False, "archived": False, "interval_seconds": 3600})
    assert response.status_code == 200
    with database.sessions() as db, pytest.raises(LeaseLost):
        guard_claim(db, claim)
    assert claim_job(database) is None
    assert count(database, RecallRevision) == 0


def test_lease_expiring_during_ingestion_rolls_back_flushed_evidence(recall_setup):
    client, adapter, database, _ = recall_setup
    create_rule(client)
    claim = claim_job(database)
    checks = []
    def guard(db):
        checks.append(True)
        if len(checks) == 2:
            raise LeaseLost("synthetic_deadline_elapsed_before_commit")
        guard_claim(db, claim)
    async def run():
        with database.sessions() as db:
            await RecallService(db, adapter, ingestion_guard=guard).execute(
                RecallLiveRequest(query=claim["query"], fallback_policy="never"), claim["session_id"])
    with pytest.raises(LeaseLost):
        asyncio.run(run())
    assert len(checks) == 2
    assert count(database, RecallSnapshot) == count(database, RecallEvent) == count(database, RecallNotification) == 0
