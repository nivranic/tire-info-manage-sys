"""Real ASGI/SQLite telemetry integration; every input is synthetic and private."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import json
from types import SimpleNamespace

from fastapi import Body
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families
import pytest
from sqlalchemy import func, select

from tire_api.db import AuditEvent, UserSession
from tire_api.main import RequestTelemetryMiddleware, create_app
from tire_api.telemetry import TelemetryRuntime, observe


class NoSourceRegistry:
    def sources(self):
        return []

    async def fetch(self, *_args, **_kwargs):
        raise AssertionError("Telemetry tests must not request any source")


def build_app(tmp_path, monkeypatch, *, enabled=True):
    output = StringIO()
    runtime = TelemetryRuntime("tire-api", enabled=enabled, log_output=output)
    monkeypatch.setattr(TelemetryRuntime, "from_env", classmethod(lambda cls, service_name: runtime))
    app = create_app("sqlite:///" + (tmp_path / "telemetry-api.db").as_posix(), NoSourceRegistry())
    return app, runtime, output


def count(database, model):
    with database.sessions() as session:
        return session.scalar(select(func.count()).select_from(model))


def register_test_routes(app, runtime):
    @app.post("/telemetry-test-sync/{record_id}")
    def sync_route(record_id: str, payload: dict = Body(...)):
        # FastAPI runs this in a worker thread. The child must retain its API parent.
        with observe("source.query", component="crawler", source="michelin-us") as span:
            span.finish("live")
        return {"accepted": True}

    @app.get("/telemetry-test-error")
    def failing_route():
        raise RuntimeError("synthetic-exception-text-must-not-be-exported")

    runtime.set_routes(route.path for route in app.routes if hasattr(route, "path"))


def test_diagnostics_are_sessionless_database_free_and_do_not_observe_themselves(tmp_path, monkeypatch):
    app, runtime, _ = build_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        assert count(app.state.database, UserSession) == 0
        assert count(app.state.database, AuditEvent) == 0
        before = runtime.metrics()
        with monkeypatch.context() as guard:
            def forbidden_session(*_args, **_kwargs):
                raise AssertionError("Diagnostics touched the business database")
            guard.setattr(app.state.database, "sessions", forbidden_session)
            for path in ("/v1/observability", "/v1/observability/metrics", "/v1/observability/"):
                response = client.get(path)
                assert response.status_code == 200
                assert "set-cookie" not in response.headers
                assert response.headers["cache-control"] == "no-store"
                assert response.headers["x-content-type-options"] == "nosniff"
            status = client.get("/v1/observability").json()
            assert status["scope"] == "current_process_only"
            assert status["service_name"] == "tire-api"
            assert status["worker_presence"] == "not_observed_here"
            assert status["recent_spans"] == []
        assert runtime.metrics() == before
        assert runtime.finished_spans() == []
        assert count(app.state.database, UserSession) == count(app.state.database, AuditEvent) == 0
    assert runtime.closed


@pytest.mark.parametrize("headers,client_address,expected", [
    ({"Origin": "https://untrusted.invalid"}, ("testclient", 50000), 403),
    ({"Sec-Fetch-Site": "cross-site"}, ("testclient", 50000), 403),
    ({"Host": "untrusted.invalid"}, ("testclient", 50000), 400),
    ({}, ("198.51.100.22", 50000), 403),
])
def test_diagnostics_retain_local_origin_host_and_client_boundaries(tmp_path, monkeypatch, headers, client_address, expected):
    app, runtime, output = build_app(tmp_path, monkeypatch)
    with TestClient(app, client=client_address) as client:
        for path in ("/v1/observability", "/v1/observability/metrics"):
            response = client.get(path, headers=headers)
            assert response.status_code == expected
            assert "set-cookie" not in response.headers
        assert count(app.state.database, UserSession) == count(app.state.database, AuditEvent) == 0
        assert runtime.finished_spans() == []
        assert output.getvalue() == ""


def test_http_templates_statuses_thread_parentage_and_sensitive_inputs(tmp_path, monkeypatch):
    app, runtime, output = build_app(tmp_path, monkeypatch)
    register_test_routes(app, runtime)
    incoming_trace = "0123456789abcdef0123456789abcdef"
    incoming_parent = "0123456789abcdef"
    markers = ["synthetic-path-secret", "synthetic-query-secret", "synthetic-body-secret", "synthetic-header-secret", "synthetic-cookie-secret", "synthetic-exception-text-must-not-be-exported"]
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/telemetry-test-sync/" + markers[0] + "?q=" + markers[1],
            json={"note": markers[2]}, headers={"X-Test-Private": markers[3], "Cookie": "tire_local_session=" + markers[4],
                "traceparent": f"00-{incoming_trace}-{incoming_parent}-01", "baggage": "private=" + markers[3]})
        assert response.status_code == 200
        assert client.post("/telemetry-test-sync/another-private-id", json=[]).status_code == 422
        assert client.get("/not-a-route/synthetic-unmatched-secret?q=another-query-secret").status_code == 404
        assert client.get("/telemetry-test-error").status_code == 500
        rows = runtime.finished_spans()
        parents = [row for row in rows if row["name"] == "api.request"]
        assert len(parents) == 4
        child = next(row for row in rows if row["name"] == "source.query")
        parent = next(row for row in parents if row["attributes"]["http_status"] == 200)
        assert child["parent_span_id"] == parent["span_id"]
        assert child["trace_id"] == parent["trace_id"] != incoming_trace
        assert parent["parent_span_id"] is None
        by_status = {row["attributes"]["http_status"]: row["attributes"] for row in parents}
        assert by_status[200]["route"] == by_status[422]["route"] == "/telemetry-test-sync/{record_id}"
        assert by_status[404]["route"] == "unknown"
        assert [by_status[code]["outcome"] for code in (200, 422, 404, 500)] == ["success", "rejected", "rejected", "error"]
        before = len(rows)
        metric_text = client.get("/v1/observability/metrics").text
        families = list(text_string_to_metric_families(metric_text))
        assert any(any(sample.labels.get("operation") == "api.request" for sample in family.samples) for family in families)
        assert len(runtime.finished_spans()) == before
        exported = json.dumps(rows) + output.getvalue() + metric_text
        for marker in markers + ["synthetic-unmatched-secret", "another-private-id", "another-query-secret", incoming_trace, incoming_parent]:
            assert marker not in exported
        assert len({row["trace_id"] for row in parents}) == len(parents)


def test_parallel_requests_keep_distinct_roots_and_thread_children(tmp_path, monkeypatch):
    app, runtime, _ = build_app(tmp_path, monkeypatch)
    register_test_routes(app, runtime)
    with TestClient(app) as client:
        def send(index):
            return client.post(f"/telemetry-test-sync/private-{index}", json={"private": index}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(send, range(2))) == [200, 200]
        rows = runtime.finished_spans()
        parents = {row["trace_id"]: row for row in rows if row["name"] == "api.request"}
        children = [row for row in rows if row["name"] == "source.query"]
        assert len(parents) == len(children) == 2
        assert all(child["parent_span_id"] == parents[child["trace_id"]]["span_id"] for child in children)


def test_disabled_runtime_keeps_api_behavior_and_cleans_up(tmp_path, monkeypatch):
    app, runtime, output = build_app(tmp_path, monkeypatch, enabled=False)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert count(app.state.database, UserSession) == 1
        assert client.get("/v1/observability").json()["enabled"] is False
        assert list(text_string_to_metric_families(client.get("/v1/observability/metrics").text)) == []
        assert runtime.finished_spans() == []
    assert runtime.closed
    assert output.getvalue() == ""


def test_runtime_closes_when_database_initialization_fails(tmp_path, monkeypatch):
    app, runtime, _ = build_app(tmp_path, monkeypatch)
    def fail_initialize():
        raise RuntimeError("synthetic private startup failure")
    monkeypatch.setattr(app.state.database, "initialize", fail_initialize)
    with pytest.raises(RuntimeError, match="synthetic private startup failure"):
        with TestClient(app):
            pytest.fail("Failed startup must not enter the application")
    assert runtime.closed


def test_asgi_cancellation_is_observed_without_changing_cancellation():
    runtime = TelemetryRuntime("tire-api", logs_enabled=False)
    runtime.set_routes(["/synthetic-cancel/{id}"])
    async def cancelled(scope, receive, send):
        raise asyncio.CancelledError()
    async def unused(*args):
        raise AssertionError("Synthetic app does not use request content")
    async def run():
        scope = {"type": "http", "path": "/synthetic-cancel/private", "route": SimpleNamespace(path="/synthetic-cancel/{id}")}
        with pytest.raises(asyncio.CancelledError):
            await RequestTelemetryMiddleware(cancelled, runtime)(scope, unused, unused)
    try:
        asyncio.run(run())
        row, = runtime.finished_spans()
        assert row["attributes"]["outcome"] == "cancelled"
        assert row["attributes"]["http_status"] == 499
        assert row["status"] == "ERROR"
    finally:
        runtime.shutdown()
