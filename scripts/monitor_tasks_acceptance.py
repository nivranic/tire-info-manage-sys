"""Private real HTTP/SSE/Worker fixture; all tire/recall observations are synthetic."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
from uuid import uuid4

from fastapi import Request

from golden_acceptance import save

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'michelin-us'


def require(value, code):
    if not value:
        raise AssertionError(code)


def serve(port, output):
    require(1024 <= port <= 65535 and port not in {3000, 8000}, 'private_port_required')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    output = output.resolve()
    require(output.is_relative_to((ROOT / '.artifacts').resolve()), 'workspace_artifact_required')
    output.mkdir(parents=True, exist_ok=False)
    private = Path(tempfile.mkdtemp(prefix='tire-task-qa-')).resolve()
    database_path = private / 'private.sqlite'
    app = None
    final = {'status': 'running', 'normal_database_used': False}
    counters = {'tire_source_calls': 0, 'recall_source_calls': 0,
                'external_network_attempts': 0, 'real_parser_children': 0}
    runtime = {'task': None, 'holding': False, 'release': None, 'hold_kind': None,
               'mode': 'live', 'sequence': 0, 'last_cycle': None}
    try:
        os.environ.update(TIRE_DATABASE_URL='sqlite:///' + database_path.as_posix(),
            DATABASE_URL='sqlite:///' + database_path.as_posix(), TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0',
            TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(private / 'objects'),
            TI_PARSER_BUNDLE_ROOT=str(private / 'bundles'), TI_DISABLED_SOURCES='',
            TI_OBSERVABILITY_LOGS='0')
        sys.path[:0] = [str(ROOT), str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
        import uvicorn
        from fastapi.responses import JSONResponse
        from sqlalchemy import select, text
        from tire_api.adapters import nhtsa, registry as installed_registry
        from tire_api.db import MonitorJob, MonitorRun, UserSession, uid, utcnow
        from tire_api.domain import LiveQueryRequest, digest
        from tire_api.main import create_app
        from tire_api.monitoring import RuleCreate, create_rule
        from tire_api.recall_models import RecallMonitorJob, RecallMonitorRule, RecallRuleRevision
        from tire_api.service import QueryService
        from test_core import FixtureRegistry, success
        from test_field_evidence import known_variant
        from test_recalls import CAMPAIGN, RecallFixture
        from apps.worker import monitor as worker

        def audit(event, arguments):
            if event == 'subprocess.Popen':
                counters['real_parser_children'] += 1
                raise RuntimeError('Parser children forbidden in task fixture')
            if event in {'socket.connect', 'socket.getaddrinfo'}:
                address = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
                if address not in {'127.0.0.1', '::1', 'localhost'}:
                    counters['external_network_attempts'] += 1
                    raise RuntimeError('External networking forbidden in task fixture')
            if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
                require(Path(str(arguments[0])).resolve().is_relative_to(private), 'private_database_required')
        sys.addaudithook(audit)

        async def held(kind):
            if runtime['hold_kind'] == kind and runtime['release'] is not None:
                runtime['holding'] = True
                await asyncio.wait_for(runtime['release'].wait(), timeout=50)
                runtime['holding'], runtime['release'], runtime['hold_kind'] = False, None, None

        class Registry(FixtureRegistry):
            SPECS = installed_registry.SPECS
            PENDING_SOURCES = installed_registry.PENDING_SOURCES
            supports_parser_deployments = False

            def sources(self):
                rows = deepcopy(installed_registry.sources())
                for row in rows:
                    if row['id'] == SOURCE:
                        row.update(name='合成轮胎来源 · 任务验收', description='私有合成任务，不代表官网验收',
                            supported_models=['Fixture Tire'], default_model='Fixture Tire')
                return rows

            async def fetch(self, source_id, query, cached=None, *, on_observation=None):
                require(source_id == SOURCE, 'unexpected_synthetic_tire_source')
                counters['tire_source_calls'] += 1
                if runtime['mode'] == 'offline':
                    await held('tire')
                    return {'status': 'unavailable', 'reason': 'synthetic_outage'}
                row = known_variant(utqg_treadwear=300 + runtime['sequence'], evidence_spans={
                    'manufacturer_product_code': '$.sku.manufacturer_product_code',
                    'facts.product_code_type': '$.sku.facts.product_code_type',
                    'facts.utqg_treadwear': '$.sku.facts.utqg_treadwear'})
                value = success(json.dumps({'synthetic': True, 'sku': row}), [row])
                if on_observation:
                    on_observation(value)
                await held('tire')
                return value

        class Recalls(RecallFixture):
            async def fetch(self, query, cached=None, *, on_observation=None):
                counters['recall_source_calls'] += 1
                self.offline = runtime['mode'] == 'offline'
                value = await super().fetch(query, cached, on_observation=on_observation)
                await held('recall')
                return value

        registry, recalls = Registry(), Recalls()
        app = create_app('sqlite:///' + database_path.as_posix(), registry)
        app.state.recall_adapter = recalls
        worker.registry = registry
        # Worker uses the same production orchestration with an explicit fixture transport.
        nhtsa.fetch = recalls.fetch
        nhtsa.supports_parser_deployments = False
        database = app.state.database
        database.initialize()
        owner, other = str(uuid4()), str(uuid4())
        with database.sessions() as db:
            for session_id in (owner, other):
                db.add(UserSession(id=session_id, expires_at=utcnow() + timedelta(hours=2)))
            db.commit()
            seeded = asyncio.run(QueryService(db, registry).execute(SOURCE,
                LiveQueryRequest(query={'model': 'Fixture Tire', 'size': '265/40R20'}, fallback_policy='never'), owner))
            require(seeded['data_state'] == 'live', 'synthetic_seed_failed')
            QueryService(db, None).lock_ingestion()
            tire_rule = create_rule(db, registry, RuleCreate(name='合成轮胎持续核验', enabled=True,
                source_id=SOURCE, query={'model': 'Fixture Tire', 'size': '265/40R20'},
                interval_seconds=14400, kinds=['facts_changed'], fields=['utqg_treadwear']), owner)
            tire_job_id = tire_rule['job']['id']
            db.commit()
            QueryService(db, None).lock_ingestion()
            recall_job_id = digest({'source_id': 'nhtsa-us-recalls', 'session_id': owner,
                                   'query': {'campaign_number': CAMPAIGN}})
            db.add(RecallMonitorJob(id=recall_job_id, session_id=owner, campaign_number=CAMPAIGN))
            db.flush()
            recall_rule = RecallMonitorRule(id=uid(), session_id=owner, job_id=recall_job_id)
            db.add(recall_rule)
            db.flush()
            db.add(RecallRuleRevision(rule_id=recall_rule.id, revision=1, name='合成召回公告持续核验',
                enabled=True, archived=False, interval_seconds=3600))
            for index in (2, 1):
                started = utcnow() - timedelta(days=index)
                db.add(MonitorRun(job_id=tire_job_id, lease_token=uid(), state='source_unavailable',
                    reason='synthetic_legacy_outage', started_at=started, finished_at=started + timedelta(seconds=2)))
            db.commit()
            recall_rule_id = recall_rule.id

        def fingerprint():
            with database.sessions() as db:
                return {table: {row['id']: digest(dict(row)) for row in db.execute(text('SELECT * FROM ' + table)).mappings()}
                        for table in ('tire_variants', 'snapshots', 'fact_versions', 'monitor_runs')}
        original = fingerprint()

        def state():
            current = fingerprint()
            with database.sessions() as db:
                names = ('tire_variants', 'snapshots', 'fact_versions', 'raw_captures', 'monitor_runs',
                    'recall_monitor_runs', 'monitor_task_attempts', 'monitor_task_events',
                    'fallback_consents', 'ai_requests', 'embedding_requests')
                counts = {name: db.execute(text('SELECT COUNT(*) FROM ' + name)).scalar_one() for name in names}
            return {'scope': 'synthetic_monitor_tasks', 'normal_database_used': False,
                'tire_job_id': tire_job_id, 'recall_job_id': recall_job_id,
                'tire_rule_id': tire_rule['id'], 'recall_rule_id': recall_rule_id,
                'counts': counts, 'holding': runtime['holding'], 'hold_kind': runtime['hold_kind'],
                'worker_running': runtime['task'] is not None and not runtime['task'].done(),
                'last_cycle': runtime['last_cycle'], **counters,
                'old_evidence_unchanged': all(current[table].get(key) == value
                    for table, rows in original.items() for key, value in rows.items())}

        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, log_level='warning'))

        @app.get('/fixture/entry')
        def entry(actor: str = 'owner'):
            require(actor in {'owner', 'other'}, 'unknown_fixture_actor')
            response = JSONResponse({'private_synthetic_session': actor})
            response.set_cookie('tire_local_session', owner if actor == 'owner' else other, httponly=True, samesite='strict')
            return response

        @app.get('/fixture/state')
        def get_state():
            return state()

        @app.post('/fixture/start')
        async def start(request: Request):
            body = await request.json()
            require(runtime['task'] is None or runtime['task'].done(), 'worker_already_running')
            require(body.get('hold_kind') in {'tire', 'recall', None}, 'invalid_hold_kind')
            require(body.get('mode', 'live') in {'live', 'offline'}, 'invalid_synthetic_mode')
            # Respect the production source gap before making the synthetic jobs due again.
            if runtime['last_cycle'] is not None:
                await asyncio.sleep(2.2)
            with database.sessions() as db:
                QueryService(db, None).lock_ingestion()
                for model in (MonitorJob, RecallMonitorJob):
                    for job in db.scalars(select(model)):
                        require(job.lease_token is None, 'unfinished_fixture_lease')
                        job.next_due_at = utcnow() - timedelta(seconds=1)
                db.commit()
            runtime.update(mode=body.get('mode', 'live'), hold_kind=body.get('hold_kind'),
                release=asyncio.Event() if body.get('hold_kind') else None,
                holding=False, sequence=runtime['sequence'] + 1)

            async def cycle():
                runtime['last_cycle'] = await worker.run_scheduled_cycle(database, max_jobs=1)
            runtime['task'] = asyncio.create_task(cycle())
            return {'worker_started': True, 'synthetic_sources': True}

        @app.post('/fixture/release')
        async def release():
            if runtime['release'] is not None:
                runtime['release'].set()
            return {'released': True}

        @app.post('/fixture/shutdown')
        async def shutdown():
            if runtime['release'] is not None:
                runtime['release'].set()
            if runtime['task'] is not None:
                await asyncio.wait_for(asyncio.shield(runtime['task']), timeout=15)
            save(output / 'fixture-before-shutdown.json', state())
            server.should_exit = True
            return {'shutdown_requested': True}

        save(output / 'fixture.json', state())
        print(json.dumps({'ready': True, 'port': port, 'output': str(output)}), flush=True)
        server.run()
        final.update(status='stopped', state=state())
    except BaseException as error:
        final.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        if app is not None:
            app.state.database.close()
            app.state.telemetry.shutdown()
        try:
            if database_path.exists():
                shutil.copy2(database_path, output / 'private-checkpoint.sqlite')
                final['checkpoint_bytes'] = (output / 'private-checkpoint.sqlite').stat().st_size
            for name in ('objects', 'bundles'):
                if (private / name).exists():
                    shutil.copytree(private / name, output / (name + '-checkpoint'))
        finally:
            require(private.parent == Path(tempfile.gettempdir()).resolve()
                and private.name.startswith('tire-task-qa-') and not private.is_symlink(), 'unsafe_cleanup_target')
            shutil.rmtree(private)
            final.update(private_storage_removed=not private.exists(), **counters)
            save(output / 'fixture-final.json', final)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', required=True)
    parser.add_argument('--port', type=int, default=8003)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    serve(args.port, args.output)
