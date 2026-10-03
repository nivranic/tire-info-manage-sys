"""Owned migration fixture: real local HTTP/SQLite with explicitly synthetic v1 history.

All source observations are in-process synthetic transport. This does not claim
official-source, real-model, independent human truth or real Parser acceptance.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import tempfile
from uuid import uuid4

from golden_acceptance import Client, save

ROOT = Path(__file__).resolve().parents[1]
SIGNED = {'operator': 'Synthetic identity migration QA', 'reason': 'Automated private migration check; not human Golden approval'}


def request_payload(preview):
    return {**SIGNED, 'mode': 'history', 'schema': preview['schema'], 'expected_revision': preview['revision'],
            'expected_preview_fingerprint': preview['preview_fingerprint'], 'acknowledged': True}


def run_api(base, output):
    output.mkdir(parents=True, exist_ok=False)
    client = Client(base)
    report = {'status': 'running', 'scope': 'synthetic_v1_history_real_http_sqlite', 'checks': []}
    def checked(name):
        report['checks'].append(name)
        save(output / 'api-report.json', report)
    try:
        client.call('/health')
        client.call('/fixture/entry')
        initial = client.call('/fixture/state')
        assert not initial['normal_database_used'] and initial['real_parser_children'] == 0
        preview = client.call('/v1/identity-contract/migration-preview?mode=history')
        assert preview['summary']['eligible'] == 1 and preview['summary']['needs_review'] == 2
        assert preview['summary']['watch_risk_count'] == 1
        assert client.call('/fixture/state')['legacy_unchanged']
        checked('readonly_preview_classifies_eligible_unknown_mixed_and_watch_risk')
        payload = request_payload(preview)
        key = str(uuid4())
        application = client.post('/v1/identity-contract/migration-applications', payload, key=key)
        replay = client.post('/v1/identity-contract/migration-applications', payload, key=key)
        assert application['id'] == replay['id'] and replay['idempotent_replay']
        client.post('/v1/identity-contract/migration-applications', {**payload, 'reason': 'different payload'}, key=key, status=409)
        client.post('/v1/identity-contract/migration-applications', payload, status=409)
        checked('one_application_fixed_uuid_replay_payload_conflict_and_stale_fence')
        checks = []
        for name in ('eligible', 'unknown', 'mixed'):
            item = initial['records'][name]
            response = client.post('/v1/sources/fixture/live-query', {'query': item['query'], 'fallback_policy': 'never'}, status=200)
            assert response['data_state'] == 'live', response
            current, = response['variants']
            assert (current['id'] == item['variant_id']) == (name == 'eligible')
            assert current['identity_contract']['state'] == 'current'
            again = client.post('/v1/sources/fixture/live-query', {'query': item['query'], 'fallback_policy': 'never'}, status=200)
            assert again['data_state'] == 'live_verified_304' and again['variants'][0]['id'] == current['id'], again
            checks.append({'kind': name, 'old_id': item['variant_id'], 'current_id': current['id'], 'reused_id': name == 'eligible'})
        report['observations'] = checks
        checked('legacy_cache_forces_200_then_v2_304_preserves_proven_ids_and_separates_unresolved')
        final = client.call('/fixture/state')
        assert final['legacy_unchanged'] and final['watch_variant_unchanged']
        assert final['counts']['variant_identity_migration_applications'] == 1
        assert final['counts']['ai_requests'] == final['counts']['embedding_requests'] == 0
        assert final['external_network_attempts'] == final['real_parser_children'] == 0
        report['final'] = final
        checked('immutable_history_and_old_watch_preserved_no_model_or_network')
        report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error)[:2500])
        raise
    finally:
        save(output / 'api-report.json', report)
        client.call('/fixture/shutdown', {})


def serve(port, output):
    if port in {3000, 8000} or not 1024 <= port <= 65535:
        raise ValueError('Use a private unoccupied fixture port')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    private_root = Path(tempfile.mkdtemp(prefix='tire-identity-contract-')).resolve()
    database_path = private_root / 'private.db'
    app = None
    final = {'status': 'running', 'normal_database_used': False}
    counters = {'synthetic_source_calls': 0, 'external_network_attempts': 0, 'real_parser_children': 0}
    try:
        os.environ.update(TIRE_DATABASE_URL='sqlite:///' + database_path.as_posix(),
            DATABASE_URL='sqlite:///' + database_path.as_posix(), TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0',
            TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(private_root / 'objects'),
            TI_PARSER_BUNDLE_ROOT=str(private_root / 'bundles'))
        sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
        import uvicorn
        from fastapi.responses import JSONResponse
        from sqlalchemy import select, text
        from tire_api.db import FactVersion, Snapshot, TireVariant, WatchItem
        from tire_api.domain import digest
        from tire_api.main import create_app
        from test_core import FixtureRegistry, success
        from test_identity_migration import seed_legacy

        def audit(event, arguments):
            if event == 'subprocess.Popen':
                counters['real_parser_children'] += 1
                raise RuntimeError('Parser execution is outside this synthetic HTTP fixture')
            if event in {'socket.connect', 'socket.getaddrinfo'}:
                target = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
                if target not in {'127.0.0.1', '::1', 'localhost'}:
                    counters['external_network_attempts'] += 1
                    raise RuntimeError('External traffic is forbidden in this fixture')
            if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
                if not Path(str(arguments[0])).resolve().is_relative_to(private_root):
                    raise RuntimeError('SQLite access must stay in the owned fixture directory')
        sys.addaudithook(audit)

        class Registry(FixtureRegistry):
            def __init__(self):
                super().__init__()
                self.observations = {}
                self.calls = []
            async def fetch(self, source_id, query, cached=None, *, on_observation=None):
                counters['synthetic_source_calls'] += 1
                self.calls.append({'query_key': digest(query), 'cached': bool(cached)})
                observation = deepcopy(self.observations[digest(query)])
                if cached:
                    return {'status': 'not_modified', 'url': observation['url'], 'etag': observation['etag'],
                            'parser_version': observation['parser_version']}
                if on_observation is not None:
                    on_observation(observation)
                return observation

        registry = Registry()
        app = create_app(os.environ['TIRE_DATABASE_URL'], registry)
        database = app.state.database
        database.initialize()
        records = {}
        with database.sessions() as db:
            records['eligible'] = seed_legacy(db, product_code='ELIGIBLE-001', query={'model': 'Fixture Tire'})
            owner = records['eligible']['session_id']
            records['unknown'] = seed_legacy(db, namespace=None, product_code='UNKNOWN-001', watch=True,
                session_id=owner, query={'model': 'Fixture Tire', 'size': '265/40R20'})
            records['mixed'] = seed_legacy(db, namespace='MSPN', extra_namespaces=(None,), product_code='MIXED-001',
                session_id=owner, query={'model': 'Fixture Tire', 'size': '265/40ZR20'})
            for name, row in records.items():
                variant = deepcopy(row['variant'])
                variant['facts']['product_code_type'] = 'CAI' if name == 'eligible' else 'MSPN'
                body = db.get(Snapshot, row['snapshot_id']).body if name == 'eligible' else 'synthetic-v2-' + name
                registry.observations[row['query_key']] = success(body, [variant])

        protected = (TireVariant, Snapshot, FactVersion, WatchItem)
        def fingerprints():
            with database.engine.connect() as connection:
                return {model.__tablename__: {str(row['id']): digest({key: str(value) for key, value in row.items()})
                    for row in connection.execute(model.__table__.select()).mappings()} for model in protected}
        before = fingerprints()
        public_records = {name: {key: row[key] for key in ('variant_id', 'snapshot_id', 'fact_id', 'query', 'query_key')}
                          for name, row in records.items()}
        def state():
            current = fingerprints()
            with database.sessions() as db:
                names = ('tire_variants', 'snapshots', 'fact_versions', 'watch_items', 'variant_identity_bindings',
                         'variant_identity_migration_applications', 'ai_requests', 'embedding_requests')
                counts = {name: db.execute(text('SELECT COUNT(*) FROM ' + name)).scalar_one() for name in names}
                watch = db.get(WatchItem, records['unknown']['watch_id'])
                return {'scope': 'synthetic_v1_history_real_http_sqlite', 'normal_database_used': False,
                    'records': public_records, 'counts': counts, **counters, 'source_requests': registry.calls,
                    'legacy_unchanged': all(current[table].get(key) == value for table, rows in before.items() for key, value in rows.items()),
                    'watch_variant_unchanged': watch.variant_id == records['unknown']['variant_id']}

        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, log_level='warning'))
        @app.get('/fixture/entry')
        def entry():
            response = JSONResponse({'private_synthetic_owner_session': True})
            response.set_cookie('tire_local_session', owner, httponly=True, samesite='strict')
            return response
        @app.get('/fixture/state')
        def get_state():
            return state()
        @app.post('/fixture/shutdown')
        def shutdown():
            save(output / 'fixture-before-shutdown.json', state())
            server.should_exit = True
            return {'shutdown_requested': True}
        save(output / 'fixture.json', state())
        print(json.dumps({'ready': True, 'base_url': f'http://127.0.0.1:{port}', 'output': str(output)}), flush=True)
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
            for folder in ('objects', 'bundles'):
                if (private_root / folder).exists():
                    shutil.copytree(private_root / folder, output / (folder + '-checkpoint'))
        finally:
            if private_root.parent != Path(tempfile.gettempdir()).resolve() or not private_root.name.startswith('tire-identity-contract-'):
                raise RuntimeError('Unexpected cleanup path')
            shutil.rmtree(private_root)
            final.update(private_storage_removed=not private_root.exists(), **counters)
            save(output / 'fixture-final.json', final)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--serve', action='store_true')
    modes.add_argument('--check-api', action='store_true')
    parser.add_argument('--port', type=int, default=8003)
    parser.add_argument('--base', default='http://127.0.0.1:8003')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    serve(args.port, args.output) if args.serve else run_api(args.base, args.output)


if __name__ == '__main__':
    main()
