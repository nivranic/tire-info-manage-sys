"""Daily aggregation read endpoints for the operations insight panel.

Read-only GROUP-BY-day projections over query_runs / rejected_observations /
ai_requests(+completions); zero-filled continuous day series; strict day bounds.
"""

from datetime import timedelta

from fastapi.testclient import TestClient
import pytest

from tire_api.ai_models import AICompletion, AIEvidencePack, AIRequest
from tire_api.db import QueryRun, RejectedObservation, UserSession, utcnow
from tire_api.domain import digest
from tire_api.main import create_app
from test_core import FixtureRegistry


class Registry(FixtureRegistry):
    def sources(self):
        return [{"id": "trends-a"}, {"id": "trends-b"}]


@pytest.fixture
def setup():
    app = create_app("sqlite://", Registry())
    with TestClient(app) as client:
        yield client, app.state.database


def seed_runs(database, rows, rejected=()):
    """rows: (source, state, created_at, reason|None); rejected: (index-of-run, observed_at)."""
    with database.sessions() as db:
        actor = UserSession(expires_at=utcnow() + timedelta(days=1))
        db.add(actor)
        db.flush()
        runs = []
        for source, state, created_at, reason in rows:
            run = QueryRun(session_id=actor.id, source_id=source, query_key="trends", query={"model": "synthetic"},
                           fallback_policy="never", state=state, reason=reason, created_at=created_at)
            db.add(run)
            runs.append(run)
        db.flush()
        for run_index, observed_at in rejected:
            db.add(RejectedObservation(query_id=runs[run_index].id, source_id=runs[run_index].source_id,
                query_key="trends", target_kind="tire", stage="parse", reason="parser_failed",
                source_url="https://fixture.example/rejected", raw_hash=digest(runs[run_index].id),
                raw_body=b"raw", content_type="text/html", parser_version="trends-fixture@1", observed_at=observed_at))
        db.commit()


def day_row(payload, source_id, date):
    entry = next(row for row in payload["sources"] if row["source_id"] == source_id)
    return next(row for row in entry["days"] if row["date"] == date.isoformat())


def test_daily_buckets_zero_fill_and_window(setup):
    client, database = setup
    today = utcnow().date()
    yesterday = today - timedelta(days=1)
    older = today - timedelta(days=3)
    out_of_window = today - timedelta(days=40)
    seed_runs(database, [
        ("trends-a", "live", utcnow(), None),
        ("trends-a", "live", utcnow(), None),
        ("trends-a", "source_unavailable", utcnow() - timedelta(days=1), "upstream_timeout"),
        ("trends-b", "local_snapshot", utcnow() - timedelta(days=3), None),
        ("trends-a", "live", utcnow() - timedelta(days=40), None),
    ], rejected=[(2, utcnow() - timedelta(days=1))])
    response = client.get("/v1/source-health/trends")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["window"] == {"kind": "daily", "days": 14,
                                 "since_date": (today - timedelta(days=13)).isoformat(),
                                 "until_date": today.isoformat()}
    assert [entry["source_id"] for entry in payload["sources"]] == ["trends-a", "trends-b", "xiaomi-cn-vehicles"]
    for entry in payload["sources"]:
        assert len(entry["days"]) == 14
        assert [row["date"] for row in entry["days"]] == sorted(row["date"] for row in entry["days"])
    assert day_row(payload, "trends-a", today) == {"date": today.isoformat(), "attempts": 2, "successes": 2,
                                                   "failures": 0, "rejected": 0}
    assert day_row(payload, "trends-a", yesterday)["attempts"] == 1
    assert day_row(payload, "trends-a", yesterday)["failures"] == 1
    assert day_row(payload, "trends-a", yesterday)["rejected"] == 1
    assert day_row(payload, "trends-a", older) == {"date": older.isoformat(), "attempts": 0, "successes": 0,
                                                   "failures": 0, "rejected": 0}
    assert day_row(payload, "trends-b", older)["attempts"] == 1
    assert day_row(payload, "trends-b", older)["successes"] == 0
    total_attempts = sum(row["attempts"] for entry in payload["sources"] for row in entry["days"])
    assert total_attempts == 4  # 40 天前的运行不落入 14 天窗口


@pytest.mark.parametrize("days,status,length", [(0, 422, None), (91, 422, None), (1, 200, 1), (90, 200, 90)])
def test_trends_days_bounds(setup, days, status, length):
    client, _ = setup
    response = client.get(f"/v1/source-health/trends?days={days}")
    assert response.status_code == status
    if status == 200:
        entry = response.json()["sources"][0]
        assert len(entry["days"]) == length


def test_ai_usage_history_daily_with_conservative_reservation(setup):
    client, database = setup
    today = utcnow().date()
    yesterday = today - timedelta(days=1)
    with database.sessions() as db:
        actor = UserSession(expires_at=utcnow() + timedelta(days=1))
        db.add(actor)
        db.flush()
        pack = AIEvidencePack(actor_session_id=actor.id, mode="history", data_state="local_snapshot",
                              privacy_class="public", payload={}, fingerprint=digest("trends-pack"),
                              expires_at=utcnow() + timedelta(hours=1))
        db.add(pack)
        db.flush()
        pending = AIRequest(actor_session_id=actor.id, idempotency_key="trends-pending", pack_id=pack.id,
                            question="q", provider="openai_responses", model="synthetic", request_hash=digest("p"),
                            request_contract={"prompt_version": "trends-fixture"}, reserved_tokens=1000, created_at=utcnow())
        db.add(pending)
        settled = AIRequest(actor_session_id=actor.id, idempotency_key="trends-settled", pack_id=pack.id,
                            question="q", provider="openai_responses", model="synthetic", request_hash=digest("s"),
                            request_contract={"prompt_version": "trends-fixture"}, reserved_tokens=500,
                            created_at=utcnow() - timedelta(days=1))
        db.add(settled)
        db.flush()
        db.add(AICompletion(request_id=settled.id, state="completed", usage={"input_tokens": 300, "output_tokens": 400,
                                                                             "total_tokens": 700}))
        db.commit()
    response = client.get("/v1/ai/usage/history")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["since_date"] == (today - timedelta(days=13)).isoformat()
    assert payload["until_date"] == today.isoformat()
    days = {row["date"]: row for row in payload["days"]}
    assert len(days) == 14
    assert days[today.isoformat()] == {"date": today.isoformat(), "requests": 1, "accounted_tokens": 1000}
    # 有 provider usage 时按实际 total_tokens 记账，而非保守预留。
    assert days[yesterday.isoformat()] == {"date": yesterday.isoformat(), "requests": 1, "accounted_tokens": 700}
    assert sum(row["requests"] for row in payload["days"]) == 2
    short = client.get("/v1/ai/usage/history?days=2").json()
    assert [row["date"] for row in short["days"]] == [yesterday.isoformat(), today.isoformat()]
    assert client.get("/v1/ai/usage/history?days=0").status_code == 422
    assert client.get("/v1/ai/usage/history?days=91").status_code == 422
