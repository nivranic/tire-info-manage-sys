"""Private real HTTP/Worker fixture for bounded discovery scans; synthetic sources only."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from contextlib import closing
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import tempfile
from uuid import uuid4

from fastapi import Request

from golden_acceptance import save

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'nhtsa-us-recalls'
BASELINE_CAMPAIGN = '26T008000'
NEW_CAMPAIGN = '26T009000'
LATER_CAMPAIGN = '26T010000'
MODES = {'baseline', 'new', 'duplicate', 'absent', 'reappear', 'drift', 'total_drift',
         'duplicate_product', 'page_failure', 'too_many', 'parser_change'}


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
    private = Path(tempfile.mkdtemp(prefix='tire-discovery-qa-')).resolve()
    database_path = private / 'private.sqlite'
    checkpoint = output / 'private-checkpoint.sqlite'
    app = None
    final = {'status': 'running', 'normal_database_used': False}
    counters = {'search_source_calls': 0, 'campaign_source_calls': 0,
                'external_network_attempts': 0, 'real_parser_children': 0}
    runtime = {'task': None, 'release': None, 'holding': False, 'hold_call': None,
               'mode': 'baseline', 'cycle_calls': 0, 'last_cycle': None, 'sealed': {}}
    try:
        os.environ.update(TIRE_DATABASE_URL='sqlite:///' + database_path.as_posix(),
            DATABASE_URL='sqlite:///' + database_path.as_posix(), TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0',
            TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(private / 'objects'),
            TI_PARSER_BUNDLE_ROOT=str(private / 'bundles'), TI_DISABLED_SOURCES='', TI_OBSERVABILITY_LOGS='0')
        sys.path[:0] = [str(ROOT), str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]

        def audit(event, arguments):
            if event == 'subprocess.Popen':
                counters['real_parser_children'] += 1
                raise RuntimeError('Parser children forbidden in synthetic discovery fixture')
            if event in {'socket.connect', 'socket.getaddrinfo'}:
                address = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
                if address not in {'127.0.0.1', '::1', 'localhost'}:
                    counters['external_network_attempts'] += 1
                    raise RuntimeError('External networking forbidden in synthetic discovery fixture')
            if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
                path = Path(str(arguments[0])).resolve()
                require(path.is_relative_to(private) or path == checkpoint, 'private_database_required')
        sys.addaudithook(audit)

        import uvicorn
        from fastapi.responses import JSONResponse
        from sqlalchemy import select, text
        from tire_api.adapters import nhtsa, registry
        from tire_api.db import UserSession, utcnow
        from tire_api.domain import digest
        from tire_api.main import create_app
        from tire_api.recall_discovery_monitor_models import RecallDiscoveryJob
        from tire_api.service import QueryService
        from test_recall_discovery import IDENTITY, product
        from test_recalls import RecallFixture, record
        from apps.worker import monitor as worker

        class NoTireFetch:
            SPECS = registry.SPECS
            PENDING_SOURCES = registry.PENDING_SOURCES
            supports_parser_deployments = False

            def sources(self):
                return deepcopy(registry.sources())

            async def fetch(self, *_args, **_kwargs):
                raise AssertionError('Tire source not part of discovery fixture')

        class Discovery:
            supports_parser_deployments = False

            def __init__(self):
                self.campaigns = RecallFixture()

            async def fetch(self, query, cached=None, *, on_observation=None):
                if 'search' not in query:
                    counters['campaign_source_calls'] += 1
                    row = record()
                    row['campaign_number'] = query['campaign_number']
                    self.campaigns.rows = [row]
                    return await self.campaigns.fetch(query, cached, on_observation=on_observation)
                counters['search_source_calls'] += 1
                runtime['cycle_calls'] += 1
                call = runtime['cycle_calls']
                offset, mode = int(query['offset']), runtime['mode']
                if mode == 'page_failure' and offset == 10:
                    return {'status': 'unavailable', 'reason': 'synthetic_second_page_outage'}
                products = [product(number, campaign=False) for number in range(1, 12)]
                products[-1] = product(11)
                first = products[-1]['campaigns'][0]
                first.update(campaign_number=BASELINE_CAMPAIGN, subject='合成基线公告 · 非官方验收')
                if mode != 'baseline' and mode != 'absent':
                    added = deepcopy(first)
                    added.update(campaign_number=NEW_CAMPAIGN, subject='合成新增候选 · 仅第 11 个产品')
                    products[-1]['campaigns'].append(added)
                if mode == 'duplicate':
                    products[0]['campaigns'] = [deepcopy(products[-1]['campaigns'][-1])]
                if mode == 'drift':
                    later = deepcopy(first)
                    later.update(campaign_number=LATER_CAMPAIGN, subject='不一致扫描中的合成候选')
                    products[-1]['campaigns'].append(later)
                    if call >= 3:
                        products[0]['size'] = 'LT315/65R17'
                if mode == 'total_drift' and call >= 2:
                    products.append(product(12, campaign=False))
                if mode == 'duplicate_product':
                    products[-1]['id'] = products[0]['id']
                if mode == 'too_many':
                    products.extend(product(number, campaign=False) for number in range(12, 202))
                for row in products:
                    row['recalls_count'] = len(row['campaigns'])
                rows = products[offset:offset + 10]
                discovery = {'products': deepcopy(rows), 'pagination': {'offset': offset, 'max': 10,
                    'count': len(rows), 'total': len(products), 'has_next': offset + len(rows) < len(products),
                    'has_previous': offset > 0}}
                identity = deepcopy(IDENTITY)
                if mode == 'parser_change' and call >= 3:
                    identity['deployment_revision'] = 2
                result = {'status': 'ok', 'url': nhtsa.query_url(query), 'content_type': 'application/json',
                    'parser_version': 'synthetic-discovery-monitor@1', 'parser_identity': identity,
                    'etag': None, 'last_modified': None,
                    'body': json.dumps({'synthetic_fixture_only': True, 'discovery': discovery}, ensure_ascii=False),
                    'discovery': discovery}
                if on_observation:
                    on_observation(result)
                if call == runtime['hold_call'] and runtime['release'] is not None:
                    runtime['holding'] = True
                    await asyncio.wait_for(runtime['release'].wait(), timeout=50)
                    runtime.update(holding=False, release=None, hold_call=None)
                return result

        adapter = Discovery()
        app = create_app('sqlite:///' + database_path.as_posix(), NoTireFetch())
        app.state.recall_adapter = adapter
        database = app.state.database
        database.initialize()
        owner, other = str(uuid4()), str(uuid4())
        with database.sessions() as db:
            for session_id in (owner, other):
                db.add(UserSession(id=session_id, expires_at=utcnow() + timedelta(hours=2)))
            db.commit()

        def fingerprint():
            with database.sessions() as db:
                names = ('recall_search_snapshots', 'recall_search_verifications', 'recall_discovery_runs',
                         'recall_discovery_pages', 'recall_discovery_candidates', 'monitor_task_events',
                         'recall_discovery_task_attempts', 'recall_discovery_task_events')
                return {name: {row['id']: digest(dict(row)) for row in db.execute(text('SELECT * FROM ' + name)).mappings()}
                        for name in names}

        def state():
            current = fingerprint()
            with database.sessions() as db:
                names = ('recall_discovery_jobs', 'recall_discovery_rules', 'recall_discovery_rule_revisions',
                    'recall_discovery_runs', 'recall_discovery_pages', 'recall_discovery_candidates',
                    'recall_discovery_notifications', 'recall_search_snapshots', 'recall_search_verifications',
                    'query_runs', 'raw_captures', 'recall_revisions', 'recall_events', 'recall_monitor_rules',
                    'tire_variants', 'fact_versions', 'monitor_task_attempts', 'monitor_task_events',
                    'recall_discovery_task_attempts', 'recall_discovery_task_events',
                    'fallback_consents', 'ai_requests', 'embedding_requests')
                counts = {name: db.execute(text('SELECT COUNT(*) FROM ' + name)).scalar_one() for name in names}
            return {'scope': 'synthetic_recall_discovery_monitor', 'normal_database_used': False, 'process_id': os.getpid(),
                'counts': counts, 'mode': runtime['mode'], 'holding': runtime['holding'],
                'cycle_calls': runtime['cycle_calls'],
                'worker_running': runtime['task'] is not None and not runtime['task'].done(),
                'last_cycle': runtime['last_cycle'], **counters,
                'sealed_evidence_unchanged': all(current[name].get(key) == value
                    for name, rows in runtime['sealed'].items() for key, value in rows.items())}

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

        @app.post('/fixture/seal')
        async def seal():
            require(runtime['task'] is None or runtime['task'].done(), 'seal_requires_idle_worker')
            runtime['sealed'] = fingerprint()
            return {'sealed_counts': {name: len(rows) for name, rows in runtime['sealed'].items()}}

        @app.post('/fixture/mode')
        async def set_mode(request: Request):
            body = await request.json()
            require(body.get('mode') in MODES, 'invalid_fixture_mode')
            require(runtime['task'] is None or runtime['task'].done(), 'mode_requires_idle_worker')
            runtime.update(mode=body['mode'], cycle_calls=0)
            return {'mode': runtime['mode']}

        @app.post('/fixture/start')
        async def start(request: Request):
            body = await request.json()
            require(runtime['task'] is None or runtime['task'].done(), 'worker_already_running')
            require(body.get('mode', 'baseline') in MODES, 'invalid_fixture_mode')
            require(body.get('hold_call') in {None, 1, 2, 3, 4}, 'invalid_hold_call')
            if runtime['last_cycle'] is not None:
                await asyncio.sleep(2.2)
            with database.sessions() as db:
                QueryService(db, None).lock_ingestion()
                jobs = list(db.scalars(select(RecallDiscoveryJob)))
                require(bool(jobs), 'no_discovery_rule_created')
                for job in jobs:
                    require(job.lease_token is None, 'unfinished_fixture_lease')
                    job.next_due_at = utcnow() - timedelta(seconds=1)
                db.commit()
            runtime.update(mode=body.get('mode', 'baseline'), cycle_calls=0, hold_call=body.get('hold_call'),
                release=asyncio.Event() if body.get('hold_call') else None, holding=False)

            async def cycle():
                runtime['last_cycle'] = await worker.run_recall_discovery_cycle(database, max_jobs=1, adapter=adapter)
            runtime['task'] = asyncio.create_task(cycle())
            return {'worker_started': True, 'synthetic_source': True}

        @app.post('/fixture/release')
        async def release():
            if runtime['release'] is not None:
                runtime['release'].set()
            return {'released': True}

        @app.post('/fixture/campaign-cycle')
        async def campaign_cycle():
            require(runtime['holding'], 'rival_cycle_requires_held_discovery_request')
            return await worker.run_recall_cycle(database, max_jobs=1, adapter=adapter)

        @app.post('/fixture/shutdown')
        async def shutdown():
            if runtime['release'] is not None:
                runtime['release'].set()
            if runtime['task'] is not None:
                await asyncio.wait_for(asyncio.shield(runtime['task']), timeout=25)
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
                with closing(sqlite3.connect(database_path)) as source, closing(sqlite3.connect(checkpoint)) as target:
                    source.backup(target)
                    target.commit()
                final['checkpoint_bytes'] = checkpoint.stat().st_size
            for name in ('objects', 'bundles'):
                if (private / name).exists():
                    shutil.copytree(private / name, output / (name + '-checkpoint'))
        finally:
            require(private.parent == Path(tempfile.gettempdir()).resolve()
                and private.name.startswith('tire-discovery-qa-') and not private.is_symlink(), 'unsafe_cleanup_target')
            try:
                shutil.rmtree(private)
            except BaseException as error:
                final.update(status='cleanup_failed', cleanup_error=type(error).__name__)
                raise
            finally:
                final.update(private_storage_removed=not private.exists(), **counters)
                save(output / 'fixture-final.json', final)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', required=True)
    parser.add_argument('--port', type=int, default=8003)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    serve(args.port, args.output)
