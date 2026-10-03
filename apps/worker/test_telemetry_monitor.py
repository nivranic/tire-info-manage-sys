"""Private SQLite worker telemetry checks; never call a real source or model."""
import asyncio
from datetime import timedelta
import importlib.util
from io import StringIO
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families
import pytest
from sqlalchemy import select

from tire_api.db import MonitorJob, QueryRun, utcnow
from tire_api.main import create_app
from tire_api.monitoring import LeaseLost
from tire_api.telemetry import TelemetryRuntime


spec = importlib.util.spec_from_file_location("telemetry_test_monitor", Path(__file__).with_name("monitor.py"))
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class SyntheticSource:
    unavailable = False
    calls = 0

    def sources(self):
        return [{"id": "fixture", "status": "ready", "supported_models": ["Synthetic Tire"]}]

    async def fetch(self, source_id, query, cached=None, *, on_observation=None):
        self.calls += 1
        if self.unavailable:
            return {"status": "unavailable", "reason": "synthetic_unavailable_private_marker"}
        return {"status": "ok", "url": "https://fixture.invalid/telemetry", "body": "synthetic-private-body",
            "content_type": "text/html", "parser_version": "fixture@1", "variants": [
                {"brand": "Fixture", "model": "Synthetic Tire", "size": "265/40R20", "region": "TEST",
                 "manufacturer_product_code": "SYNTHETIC-CODE", "load_index": "104", "speed_rating": "Y",
                 "facts": {"synthetic_metric": 1}}]}


@pytest.fixture
def worker_context(tmp_path, monkeypatch):
    monkeypatch.setenv("TI_OBSERVABILITY_LOGS", "0")
    registry = SyntheticSource()
    app = create_app("sqlite:///" + (tmp_path / "worker-telemetry.db").as_posix(), registry)
    output = StringIO()
    runtime = TelemetryRuntime("tire-worker", log_output=output)
    monkeypatch.setattr(monitor, "registry", registry)
    with TestClient(app) as client:
        try:
            yield client, app.state.database, runtime, output, registry
        finally:
            runtime.shutdown()


def create_rule(client):
    response = client.post("/v1/alert-rules", json={"name": "synthetic private rule", "source_id": "fixture",
        "query": {"model": "Synthetic Tire"}, "enabled": True, "kinds": ["variant_observed"]})
    assert response.status_code == 201


def execute(runtime, awaitable):
    with runtime.scope():
        return asyncio.run(awaitable)


def worker_spans(runtime, name):
    return [row for row in runtime.finished_spans() if row["name"] == name]


def queue_samples(runtime):
    return {sample.name.rsplit("_", 1)[1]: sample.value
        for family in text_string_to_metric_families(runtime.metrics()) for sample in family.samples
        if sample.name.startswith("tire_worker_queue_lag") and sample.name.endswith(("_count", "_sum"))}


def test_idle_cycles_do_not_create_jobs_or_start_external_work(worker_context):
    _, database, runtime, _, registry = worker_context
    result = execute(runtime, monitor.run_scheduled_cycle(database, max_jobs=1))
    assert result["jobs"] == 0
    assert registry.calls == 0
    assert worker_spans(runtime, "worker.job") == []
    cycles = worker_spans(runtime, "worker.cycle")
    assert len(cycles) == 3  # Scheduled root plus campaign and discovery queues.
    assert all(row["attributes"]["outcome"] == "idle" for row in cycles)
    root = next(row for row in cycles if row["parent_span_id"] is None)
    assert all(row["trace_id"] == root["trace_id"] for row in cycles)
    assert runtime.status()["worker_presence"] == "this_process"
    assert queue_samples(runtime) == {}


@pytest.mark.parametrize("unavailable,state", [(False, "live"), (True, "source_unavailable")])
def test_scheduled_job_keeps_parentage_state_and_never_policy(worker_context, unavailable, state):
    client, database, runtime, output, registry = worker_context
    create_rule(client)
    registry.unavailable = unavailable
    result = execute(runtime, monitor.run_scheduled_cycle(database, max_jobs=1))
    assert result["jobs"] == 1 and result["results"][0]["state"] == state
    assert result["results"][0]["finalized"] is True
    job, = worker_spans(runtime, "worker.job")
    root = next(row for row in worker_spans(runtime, "worker.cycle") if row["parent_span_id"] is None)
    assert job["trace_id"] == root["trace_id"] and job["parent_span_id"] == root["span_id"]
    assert job["attributes"]["outcome"] == state
    with database.sessions() as session:
        rows = session.scalars(select(QueryRun).where(QueryRun.session_id == "scheduled-monitor-worker")).all()
        assert len(rows) == 1 and rows[0].fallback_policy == "never" and rows[0].state == state
    exported = json.dumps(runtime.finished_spans()) + output.getvalue() + runtime.metrics()
    for forbidden in ("synthetic-private-body", "SYNTHETIC-CODE", "synthetic private rule", "synthetic_unavailable_private_marker"):
        assert forbidden not in exported


@pytest.mark.parametrize("failure,expected", [(LeaseLost, "lease_lost"), (RuntimeError, "worker_error")])
def test_job_failures_keep_lease_behavior_and_hide_exception_text(worker_context, monkeypatch, failure, expected):
    client, database, runtime, output, _ = worker_context
    create_rule(client)
    async def fail(*_args, **_kwargs):
        raise failure("synthetic secret exception detail")
    monkeypatch.setattr(monitor.QueryService, "execute", fail)
    if failure is LeaseLost:
        def forbidden_finish(*_args, **_kwargs):
            raise AssertionError("A lost lease must not be finalized")
        monkeypatch.setattr(monitor, "finish_job", forbidden_finish)
    result = execute(runtime, monitor.run_scheduled_cycle(database, max_jobs=1))
    assert result["results"][0]["state"] == expected
    job, = worker_spans(runtime, "worker.job")
    assert job["attributes"]["outcome"] == expected
    assert "synthetic secret exception detail" not in json.dumps(runtime.finished_spans()) + output.getvalue()
    if failure is LeaseLost:
        assert "finalized" not in result["results"][0]


def test_expired_finalization_is_not_reported_as_a_live_job(worker_context, monkeypatch):
    client, database, runtime, _, _ = worker_context
    create_rule(client)
    monkeypatch.setattr(monitor, "finish_job", lambda *_args, **_kwargs: False)
    result = execute(runtime, monitor.run_scheduled_cycle(database, max_jobs=1))
    assert result["results"][0]["state"] == "live"
    assert result["results"][0]["finalized"] is False
    job, = worker_spans(runtime, "worker.job")
    assert job["attributes"]["outcome"] == "stale"


def test_legacy_watch_cycle_retains_job_context_and_never_policy(worker_context):
    client, database, runtime, _, _ = worker_context
    seeded = client.post("/v1/sources/fixture/live-query", json={
        "query": {"model": "Synthetic Tire", "size": "265/40R20"}, "fallback_policy": "never"})
    assert seeded.status_code == 200
    variant_id = seeded.json()["variants"][0]["id"]
    assert client.post("/v1/watchlists", json={"variant_id": variant_id}).status_code == 201
    result = execute(runtime, monitor.run_cycle(database))
    assert result["jobs"] == 1 and result["results"][0]["state"] == "live"
    job, = worker_spans(runtime, "worker.job")
    root = next(row for row in worker_spans(runtime, "worker.cycle") if row["parent_span_id"] is None)
    assert job["trace_id"] == root["trace_id"] and job["parent_span_id"] == root["span_id"]
    assert job["attributes"]["outcome"] == "live"
    assert queue_samples(runtime) == {}  # Legacy watchlists have no due time to measure.
    with database.sessions() as session:
        rows = session.scalars(select(QueryRun).where(QueryRun.session_id == "monitor-worker")).all()
        assert len(rows) == 1 and rows[0].fallback_policy == "never"


def test_recall_queue_uses_its_own_job_span_and_never_fallback(worker_context):
    client, database, runtime, _, _ = worker_context
    response = client.post("/v1/recall-monitor-rules", json={"name": "Synthetic campaign",
        "query": {"campaign_number": "23T001000"}, "enabled": True, "interval_seconds": 3600})
    assert response.status_code == 201
    class UnavailableRecall:
        async def fetch(self, query, cached=None, *, on_observation=None):
            return {"status": "unavailable", "reason": "synthetic recall unavailable"}
    result = execute(runtime, monitor.run_recall_cycle(database, max_jobs=1, adapter=UnavailableRecall()))
    assert result["jobs"] == 1 and result["results"][0]["state"] == "source_unavailable"
    job, = worker_spans(runtime, "worker.job")
    cycle, = worker_spans(runtime, "worker.cycle")
    assert job["parent_span_id"] == cycle["span_id"] and job["trace_id"] == cycle["trace_id"]
    assert job["attributes"]["source"] == "nhtsa-us-recalls"
    with database.sessions() as session:
        runs = session.scalars(select(QueryRun).where(QueryRun.source_id == "nhtsa-us-recalls")).all()
        assert len(runs) == 1 and runs[0].fallback_policy == "never"


@pytest.mark.parametrize("queue", ["tires", "recalls"])
def test_queue_delay_only_records_a_claimed_due_job(worker_context, monkeypatch, queue):
    from tire_api import monitoring, recall_monitoring
    from tire_api.recall_models import RecallMonitorJob
    client, database, runtime, _, registry = worker_context
    if queue == "tires":
        create_rule(client)
        job_type, schedule = MonitorJob, monitoring
    else:
        response = client.post("/v1/recall-monitor-rules", json={"name": "Synthetic due campaign",
            "query": {"campaign_number": "23T001000"}, "enabled": True, "interval_seconds": 3600})
        assert response.status_code == 201
        job_type, schedule = RecallMonitorJob, recall_monitoring
    now = utcnow()
    monkeypatch.setattr(schedule, "utcnow", lambda: now)
    class UnavailableRecall:
        async def fetch(self, query, cached=None, *, on_observation=None):
            return {"status": "unavailable", "reason": "synthetic due campaign unavailable"}
    def run():
        return execute(runtime, monitor.run_scheduled_cycle(database, max_jobs=1) if queue == "tires"
            else monitor.run_recall_cycle(database, max_jobs=1, adapter=UnavailableRecall()))
    with database.sessions() as session:
        session.scalar(select(job_type)).next_due_at = now + timedelta(hours=1)
        session.commit()
    assert run()["jobs"] == 0
    assert queue_samples(runtime) == {}
    with database.sessions() as session:
        job = session.scalar(select(job_type))
        job.next_due_at = now - timedelta(seconds=37)
        job.lease_token, job.lease_until = "synthetic-held-lease", now + timedelta(minutes=1)
        session.commit()
    assert run()["jobs"] == 0
    assert queue_samples(runtime) == {}
    with database.sessions() as session:
        job = session.scalar(select(job_type))
        job.lease_token, job.lease_until = None, None
        session.commit()
    assert run()["jobs"] == 1
    assert queue_samples(runtime) == {"count": 1.0, "sum": 37.0}
    assert registry.calls == (1 if queue == "tires" else 0)
    public = client.get("/v1/alert-rules" if queue == "tires" else "/v1/recall-monitor-rules?mode=history").json()
    assert "queue_lag_seconds" not in json.dumps(public)


def test_worker_cli_scope_and_shutdown_without_launching_a_service(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TIRE_DATABASE_URL", "sqlite:///" + (tmp_path / "worker-once.db").as_posix())
    monkeypatch.setattr(sys, "argv", ["monitor", "--once"])
    runtime = TelemetryRuntime("tire-worker", logs_enabled=False)
    monkeypatch.setattr(TelemetryRuntime, "from_env", classmethod(lambda cls, service_name: runtime))
    def unexpected_listener(_port):
        raise AssertionError("Default Worker CLI must not start a metrics listener")
    monkeypatch.setattr(runtime, "start_metrics_server", unexpected_listener, raising=False)
    asyncio.run(monitor.main())
    assert runtime.closed
    assert json.loads(capsys.readouterr().out)["jobs"] == 0
    assert all(row["attributes"]["outcome"] == "idle" for row in worker_spans(runtime, "worker.cycle"))


@pytest.mark.parametrize("port", ["0", "1023", "65536", "-1", "not-a-port"])
def test_worker_cli_rejects_invalid_metrics_port_before_runtime_creation(monkeypatch, port):
    monkeypatch.setattr(sys, "argv", ["monitor", "--once", "--metrics-port", port])
    def unexpected_runtime(cls, _service_name):
        raise AssertionError("Invalid CLI input must be rejected before runtime creation")
    monkeypatch.setattr(TelemetryRuntime, "from_env", classmethod(unexpected_runtime))
    with pytest.raises(SystemExit) as stopped:
        asyncio.run(monitor.main())
    assert stopped.value.code == 2


@pytest.mark.parametrize("port", [1024, 65535])
def test_worker_cli_explicit_metrics_listener_uses_runtime_and_closes(tmp_path, monkeypatch, capsys, port):
    monkeypatch.setenv("TIRE_DATABASE_URL", "sqlite:///" + (tmp_path / "worker-metrics.db").as_posix())
    monkeypatch.setattr(sys, "argv", ["monitor", "--once", "--metrics-port", str(port)])
    runtime = TelemetryRuntime("tire-worker", logs_enabled=False)
    monkeypatch.setattr(TelemetryRuntime, "from_env", classmethod(lambda cls, service_name: runtime))
    calls = []
    endpoint = {"address": "127.0.0.1", "port": port, "metrics_path": "/v1/observability/metrics"}
    def start(selected_port):
        calls.append(selected_port)
        return endpoint
    monkeypatch.setattr(runtime, "start_metrics_server", start, raising=False)
    asyncio.run(monitor.main())
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert calls == [port]
    assert output[0] == endpoint and output[1]["jobs"] == 0
    assert len(output) == 2 and runtime.closed


def test_worker_cli_metrics_start_failure_still_closes_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("TIRE_DATABASE_URL", "sqlite:///" + (tmp_path / "worker-metrics-failed.db").as_posix())
    monkeypatch.setattr(sys, "argv", ["monitor", "--once", "--metrics-port", "19091"])
    runtime = TelemetryRuntime("tire-worker", logs_enabled=False)
    monkeypatch.setattr(TelemetryRuntime, "from_env", classmethod(lambda cls, service_name: runtime))
    def start(_port):
        raise OSError("synthetic metrics listener unavailable")
    monkeypatch.setattr(runtime, "start_metrics_server", start, raising=False)
    with pytest.raises(OSError, match="synthetic metrics listener unavailable"):
        asyncio.run(monitor.main())
    assert runtime.closed and runtime.finished_spans() == []


def test_worker_cli_closes_runtime_when_a_cycle_is_cancelled(tmp_path, monkeypatch):
    monkeypatch.setenv("TIRE_DATABASE_URL", "sqlite:///" + (tmp_path / "worker-cancelled.db").as_posix())
    monkeypatch.setattr(sys, "argv", ["monitor", "--once"])
    runtime = TelemetryRuntime("tire-worker", logs_enabled=False)
    monkeypatch.setattr(TelemetryRuntime, "from_env", classmethod(lambda cls, service_name: runtime))
    async def cancel(*_args, **_kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(monitor, "run_scheduled_cycle", monitor.observed_cycle(cancel))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(monitor.main())
    assert runtime.closed
    row, = worker_spans(runtime, "worker.cycle")
    assert row["attributes"]["outcome"] == "cancelled"
