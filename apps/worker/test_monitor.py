import asyncio
import importlib.util
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select

from tire_api.db import Database, FactVersion, QueryRun, UserSession, WatchItem, utcnow
from tire_api.domain import LiveQueryRequest
from tire_api.service import QueryService
from tire_api.main import create_app
from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location("monitor", Path(__file__).with_name("monitor.py"))
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class FixtureSource:
    """Synthetic behavioral fixture, never loaded by the application."""
    offline = False

    def sources(self):
        return [{"id": "fixture"}]

    async def fetch(self, source_id, query, cached=None, *, on_observation=None):
        if self.offline:
            return {"status": "unavailable", "reason": "test_offline"}
        return {"status": "ok", "url": "https://fixture.invalid/product", "body": "synthetic-fixture",
                "content_type": "text/html", "parser_version": "fixture@1",
                "variants": [{"brand": "Fixture", "model": "Synthetic Tire", "size": "265/40R20",
                              "region": "TEST", "manufacturer_product_code": "00001", "load_index": "104",
                              "speed_rating": "Y", "facts": {"synthetic_metric": 1}}]}


def test_worker_refresh_is_online_only_and_deduplicates_watchers(monkeypatch):
    database = Database("sqlite:///:memory:")
    database.initialize()
    fixture = FixtureSource()
    monkeypatch.setattr(monitor, "registry", fixture)

    async def run():
        with database.sessions() as db:
            for session_id in ("user-a", "user-b"):
                db.add(UserSession(id=session_id, expires_at=utcnow() + timedelta(days=1)))
            db.commit()
            response = await QueryService(db, fixture).execute("fixture",
                LiveQueryRequest(query={"model": "Synthetic Tire", "size": "265/40R20"}, fallback_policy="never"), "user-a")
            variant_id = response["variants"][0]["id"]
            for session_id in ("user-a", "user-b"):
                db.add(WatchItem(session_id=session_id, variant_id=variant_id))
            db.commit()
        success = await monitor.run_cycle(database)
        assert success["jobs"] == 1
        assert success["results"][0]["state"] == "live"
        fixture.offline = True
        failure = await monitor.run_cycle(database)
        assert failure["results"][0]["state"] == "source_unavailable"
        with database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(FactVersion)) == 1
            runs = db.scalars(select(QueryRun).where(QueryRun.session_id == "monitor-worker")).all()
            assert all(run.fallback_policy == "never" for run in runs)
            assert all(run.state != "local_snapshot" for run in runs)

    try:
        asyncio.run(run())
    finally:
        database.close()


def test_scheduled_worker_persists_outcomes_and_never_uses_fallback(monkeypatch, tmp_path):
    fixture = FixtureSource()
    fixture.sources = lambda: [{"id": "fixture", "status": "ready", "supported_models": ["Synthetic Tire"]}]
    app = create_app('sqlite:///' + (tmp_path / 'worker.db').as_posix(), fixture)
    monkeypatch.setattr(monitor, 'registry', fixture)
    with TestClient(app) as client:
        for name in ('first', 'second'):
            assert client.post('/v1/alert-rules', json={'name': name, 'source_id': 'fixture',
                'query': {'model': 'Synthetic Tire'}, 'enabled': True, 'kinds': ['variant_observed']}).status_code == 201
        first = asyncio.run(monitor.run_scheduled_cycle(app.state.database, max_jobs=1))
        assert first['jobs'] == 1 and first['results'][0]['state'] == 'live'
        assert first['results'][0]['finalized']
        assert client.get('/v1/notifications').json()['total'] == 2
        assert asyncio.run(monitor.run_scheduled_cycle(app.state.database, max_jobs=1))['jobs'] == 0
        from tire_api.db import MonitorJob, MonitorRun
        with app.state.database.sessions() as db:
            job = db.scalar(select(MonitorJob))
            job.next_due_at = utcnow() - timedelta(days=1)
            db.commit()
        # Let the per-source completion gap expire; no live upstream is involved.
        from tire_api import monitoring
        actual_now = monitoring.utcnow
        monkeypatch.setattr(monitoring, 'utcnow', lambda: actual_now() + timedelta(seconds=3))
        fixture.offline = True
        result = asyncio.run(monitor.run_scheduled_cycle(app.state.database, max_jobs=1))
        assert result['results'][0]['state'] == 'source_unavailable'
        assert client.get('/v1/notifications').json()['total'] == 2
        with app.state.database.sessions() as db:
            runs = db.scalars(select(QueryRun).where(QueryRun.session_id == 'scheduled-monitor-worker')).all()
            assert len(runs) == 2 and all(run.fallback_policy == 'never' for run in runs)
            assert db.scalar(select(func.count()).select_from(MonitorRun)) == 2


def test_page_only_rules_drive_existing_worker_one_job_online_and_durable_receipts(monkeypatch, tmp_path):
    """Synthetic due/clock controls; no real four-hour wait or real upstream."""
    from tire_api.db import ChangeEvent, MonitorJob, MonitorRun
    from tire_api.monitor_task_models import MonitorTaskAttempt, MonitorTaskEvent
    from tire_api.source_page_models import SourcePageChange, SourcePageNotification
    from tire_api import monitoring
    fixture = FixtureSource()
    fixture.sources = lambda: [{'id': 'fixture', 'status': 'ready', 'supported_models': ['Synthetic Tire']}]
    fixture.body = 'synthetic-worker-page-A'
    fixture.calls = []
    original_fetch = fixture.fetch
    async def fetch(source_id, query, cached=None, *, on_observation=None):
        fixture.calls.append((source_id, dict(query)))
        result = await original_fetch(source_id, query, cached, on_observation=on_observation)
        result['body'] = fixture.body
        return result
    fixture.fetch = fetch
    app = create_app('sqlite:///' + (tmp_path / 'page-worker.sqlite').as_posix(), fixture)
    monkeypatch.setattr(monitor, 'registry', fixture)
    with TestClient(app) as client:
        for enabled in (True, False):
            response = client.post('/v1/alert-rules', json={'name': f'Synthetic page rule {enabled}',
                'source_id': 'fixture', 'query': {'model': 'Synthetic Tire'}, 'enabled': enabled,
                'kinds': ['page_changed'], 'variant_id': None, 'fields': [], 'conditions': {}})
            assert response.status_code == 201, response.text
        database = app.state.database
        first = asyncio.run(monitor.run_scheduled_cycle(database, max_jobs=1))
        assert first['jobs'] == 1 and first['results'][0]['state'] == 'live' and first['results'][0]['finalized']
        assert client.get('/v1/source-page-notifications?mode=history').json()['total'] == 0
        assert asyncio.run(monitor.run_scheduled_cycle(database, max_jobs=1))['jobs'] == 0
        assert len(fixture.calls) == 1
        with database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(MonitorJob)) == 1
            job = db.scalar(select(MonitorJob))
            job.next_due_at = utcnow() - timedelta(days=1)
            db.commit()
        actual_now = monitoring.utcnow
        monkeypatch.setattr(monitoring, 'utcnow', lambda: actual_now() + timedelta(seconds=3))
        fixture.body = 'synthetic-worker-page-B'
        second = asyncio.run(monitor.run_scheduled_cycle(database, max_jobs=1))
        assert second['jobs'] == 1 and second['results'][0]['state'] == 'live' and second['results'][0]['finalized']
        assert len(fixture.calls) == 2
        assert client.get('/v1/source-page-notifications?mode=history').json()['total'] == 1
        with database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(SourcePageChange)) == 1
            assert db.scalar(select(func.count()).select_from(SourcePageNotification)) == 1
            assert db.scalar(select(func.count()).select_from(FactVersion)) == 1
            assert db.scalar(select(func.count()).select_from(ChangeEvent)) == 1
            runs = db.scalars(select(QueryRun).where(QueryRun.session_id == 'scheduled-monitor-worker')).all()
            assert len(runs) == 2 and all(run.fallback_policy == 'never' and run.state == 'live' for run in runs)
            assert db.scalar(select(func.count()).select_from(MonitorRun)) == 2
            attempts = db.scalars(select(MonitorTaskAttempt).where(MonitorTaskAttempt.kind == 'tire')).all()
            assert len(attempts) == 2 and all(type(row.source_access_generation) is int for row in attempts)
            for attempt in attempts:
                phases = db.scalars(select(MonitorTaskEvent).where(MonitorTaskEvent.attempt_id == attempt.id)
                    .order_by(MonitorTaskEvent.sequence)).all()
                assert [row.phase for row in phases] == ['claimed', 'running', 'finished']
                assert phases[-1].state == 'succeeded' and phases[-1].query_id in {row.id for row in runs}
                assert phases[-1].run_id is not None
            job = db.scalar(select(MonitorJob))
            assert job.lease_token is None and job.lease_until is None


def test_quality_interest_uses_existing_scheduled_worker_without_creating_its_own_job(monkeypatch, tmp_path):
    """Actual worker entrypoint with synthetic due/clock controls and no network."""
    from tire_api import monitoring
    from tire_api.db import MonitorJob, MonitorRun, SourceQuarantine, Verification
    from tire_api.interest_models import InterestEvent
    from tire_api.monitor_task_models import MonitorTaskAttempt, MonitorTaskEvent
    fixture = FixtureSource()
    fixture.sources = lambda: [{'id': 'fixture', 'status': 'ready', 'supported_models': ['Synthetic Tire']}]
    fixture.reject = False
    fixture.calls = []
    original_fetch = fixture.fetch
    async def fetch(source_id, query, cached=None, *, on_observation=None):
        fixture.calls.append((source_id, dict(query)))
        result = await original_fetch(source_id, query, cached, on_observation=on_observation)
        if fixture.reject:
            result['variants'] = []
            result['body'] = 'synthetic-worker-quality-isolation'
        return result
    fixture.fetch = fetch
    app = create_app('sqlite:///' + (tmp_path / 'quality-interest-worker.sqlite').as_posix(), fixture)
    monkeypatch.setattr(monitor, 'registry', fixture)
    with TestClient(app) as client:
        database = app.state.database
        response = client.post('/v1/interests', json={'name': 'Synthetic worker quality subscription',
            'enabled': True, 'conditions': [{'kind': 'brand', 'values': ['Fixture']}],
            'metric_keys': [], 'changed_fields': [], 'source_quality_notifications': True})
        assert response.status_code == 201, response.text
        with database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(MonitorJob)) == 0
        response = client.post('/v1/alert-rules', json={'name': 'Existing polling rule', 'source_id': 'fixture',
            'query': {'model': 'Synthetic Tire'}, 'enabled': True, 'kinds': ['variant_observed']})
        assert response.status_code == 201, response.text
        first = asyncio.run(monitor.run_scheduled_cycle(database, max_jobs=1))
        assert first['jobs'] == 1 and first['results'][0]['state'] == 'live'
        assert asyncio.run(monitor.run_scheduled_cycle(database, max_jobs=1))['jobs'] == 0
        with database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(MonitorJob)) == 1
            job = db.scalar(select(MonitorJob))
            job.next_due_at = utcnow() - timedelta(days=1)
            db.commit()
        actual_now = monitoring.utcnow
        monkeypatch.setattr(monitoring, 'utcnow', lambda: actual_now() + timedelta(seconds=3))
        fixture.reject = True
        second = asyncio.run(monitor.run_scheduled_cycle(database, max_jobs=1))
        assert second['jobs'] == 1 and second['results'][0]['state'] == 'source_unavailable'
        assert second['results'][0]['finalized'] and len(fixture.calls) == 2
        rows = client.get('/v1/interest-notifications?mode=history').json()['items']
        quality = [row for row in rows if row['event']['domain'] == 'tire_source_quality']
        assert len(quality) == 1 and quality[0]['event']['after']['accepted'] is False
        with database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(SourceQuarantine)) == 1
            assert db.scalar(select(func.count()).select_from(Verification)) == 1
            assert db.scalar(select(func.count()).select_from(FactVersion)) == 1
            assert db.scalar(select(func.count()).select_from(InterestEvent).where(
                InterestEvent.domain == 'tire_source_quality')) == 1
            assert db.scalar(select(func.count()).select_from(MonitorRun)) == 2
            runs = db.scalars(select(QueryRun).where(QueryRun.session_id == 'scheduled-monitor-worker')).all()
            assert len(runs) == 2 and all(row.fallback_policy == 'never' for row in runs)
            assert {row.state for row in runs} == {'live', 'source_unavailable'}
            attempts = db.scalars(select(MonitorTaskAttempt).where(MonitorTaskAttempt.kind == 'tire')).all()
            assert len(attempts) == 2
            for attempt in attempts:
                phases = db.scalars(select(MonitorTaskEvent).where(MonitorTaskEvent.attempt_id == attempt.id)
                    .order_by(MonitorTaskEvent.sequence)).all()
                assert [row.phase for row in phases] == ['claimed', 'running', 'finished']
            job = db.scalar(select(MonitorJob))
            assert job.lease_token is None and job.lease_until is None


def test_recall_worker_runs_independent_fenced_queue_and_never_falls_back(monkeypatch, tmp_path):
    from tire_api.recall_models import RecallEvent, RecallMonitorJob, RecallMonitorRun
    from tire_api import recall_monitoring
    import json

    class RecallSource:
        offline = False

        async def fetch(self, query, cached=None, *, on_observation=None):
            if self.offline:
                return {"status": "unavailable", "reason": "synthetic_recall_outage"}
            records = [{"campaign_number": query["campaign_number"], "manufacturer": "Synthetic manufacturer",
                "report_received_date": "2023-03-02", "report_received_date_raw": "02/03/2023",
                "component": "TIRES", "summary": "Synthetic summary", "consequence": "Synthetic risk",
                "remedy": "Synthetic remedy", "make": "SYNTHETIC", "model": "SYNTHETIC", "model_year_raw": "9999"}]
            observation = {"url": "https://api.nhtsa.gov/recalls/campaignNumber?campaignNumber=" + query["campaign_number"],
                "body": json.dumps({"synthetic": records}), "content_type": "application/json", "parser_version": "fixture@1"}
            if on_observation:
                on_observation(observation)
            return {"status": "ok", **observation, "records": records}

    fixture = RecallSource()
    app = create_app('sqlite:///' + (tmp_path / 'recall-worker.db').as_posix(), FixtureSource())
    with TestClient(app) as client:
        assert client.post('/v1/recall-monitor-rules', json={'name': 'synthetic recall',
            'query': {'campaign_number': '23T001000'}, 'enabled': True, 'interval_seconds': 3600}).status_code == 201
        first = asyncio.run(monitor.run_recall_cycle(app.state.database, max_jobs=1, adapter=fixture))
        assert first['jobs'] == 1 and first['results'][0]['state'] == 'live' and first['results'][0]['finalized']
        assert client.get('/v1/recall-notifications?mode=history').json()['items'][0]['kind'] == 'first_observed'
        assert asyncio.run(monitor.run_recall_cycle(app.state.database, max_jobs=1, adapter=fixture))['jobs'] == 0
        with app.state.database.sessions() as db:
            db.scalar(select(RecallMonitorJob)).next_due_at = utcnow() - timedelta(days=1)
            db.commit()
        actual_now = recall_monitoring.utcnow
        monkeypatch.setattr(recall_monitoring, 'utcnow', lambda: actual_now() + timedelta(seconds=3))
        fixture.offline = True
        second = asyncio.run(monitor.run_recall_cycle(app.state.database, max_jobs=1, adapter=fixture))
        assert second['results'][0]['state'] == 'source_unavailable'
        with app.state.database.sessions() as db:
            runs = db.scalars(select(QueryRun).where(QueryRun.source_id == 'nhtsa-us-recalls')).all()
            assert len(runs) == 2 and all(row.fallback_policy == 'never' for row in runs)
            assert all(row.state != 'local_snapshot' for row in runs)
            assert db.scalar(select(func.count()).select_from(RecallEvent)) == 1
            assert db.scalar(select(func.count()).select_from(RecallMonitorRun)) == 2
