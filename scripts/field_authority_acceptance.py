"""Private real HTTP/SQLite field authority fixture with synthetic source responses.

No production data, official website, Parser child or model provider is used.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
from uuid import uuid4

from golden_acceptance import Client, save

ROOT = Path(__file__).resolve().parents[1]


def fields(resolution):
    return {row['field']: row for row in resolution['fields']}


def run_api(base, output):
    output.mkdir(parents=True, exist_ok=False)
    client = Client(base)
    report = {'status': 'running', 'scope': 'synthetic_sources_real_http_field_authority', 'checks': []}

    def check(name):
        report['checks'].append(name)
        save(output / 'api-report.json', report)

    try:
        client.call('/health')
        client.call('/fixture/entry')
        before = client.call('/fixture/state')
        assert before['scope'] == 'synthetic_field_authority' and not before['normal_database_used']
        records = before['records']
        catalog = client.call('/v1/field-policies')
        assert catalog['policy']['version'] == 'field-authority@1'
        primary = client.call('/v1/tire-variants/' + records['priority']['variant_id'] + '/field-resolution?mode=history')
        decision = fields(primary)
        assert decision['utqg_treadwear']['default_value'] == 300
        assert decision['eu_wet_grip']['default_value'] == 'B'
        assert decision['utqg_treadwear']['state'] == decision['eu_wet_grip']['state'] == 'conflict_preferred'
        assert len(decision['utqg_treadwear']['candidates']) == 2
        save(output / 'priority-resolution.json', primary)
        check('per_field_authority_keeps_both_sources_and_raw_values')

        tied = client.call('/v1/tire-variants/' + records['tie']['variant_id'] + '/field-resolution?mode=history')
        assert fields(tied)['utqg_treadwear']['state'] == 'conflict_tied'
        assert not fields(tied)['utqg_treadwear']['has_default']
        check('equal_authority_time_and_evidence_has_no_default')

        compared = client.call('/v1/compare', {'variant_ids': [records['priority']['variant_id'], records['tie']['variant_id']]})
        row = next(item for item in compared['variants'] if item['id'] == records['priority']['variant_id'])
        assert row['facts']['utqg_treadwear'] == 500
        assert fields(row['field_resolution'])['utqg_treadwear']['default_value'] == 300
        saved = client.call('/v1/saved-comparisons', {'variant_ids': compared['variant_ids'],
            'expected_fingerprint': compared['fingerprint'], 'title': 'Synthetic field-default acceptance', 'notes': 'Not a tire recommendation'}, status=201)
        saved_id = saved['id']
        detail = client.call('/v1/saved-comparisons/' + saved_id + '?mode=history')
        save(output / 'saved-comparison.json', detail)
        check('comparison_default_is_a_frozen_sidecar_without_source_fact_rewrite')

        listing = client.call('/v1/field-conflicts?mode=history&field=utqg_treadwear&source_id=fixture&limit=1')
        assert listing['total'] == 2 and len(listing['items']) == 1
        assert client.call('/v1/field-conflicts', status=422)['detail']
        assert records['namespace_mspn']['variant_id'] != records['namespace_cai']['variant_id']
        assert all(item['variant_id'] not in {records['namespace_mspn']['variant_id'], records['namespace_cai']['variant_id']}
                   for item in client.call('/v1/field-conflicts?mode=history')['items'])
        check('history_filters_preserve_competing_sources_and_namespace_boundaries')

        prior_fact_count = client.call('/fixture/state')['counts']['fact_versions']
        client.call('/fixture/metadata-phase', {})
        metadata = client.call('/v1/sources/fixture/live-query', {'query': records['priority']['query'], 'fallback_policy': 'ask'})
        assert metadata['data_state'] == 'live'
        new_snapshot = metadata['provenance'][0]['snapshot_id']
        assert new_snapshot != records['priority']['snapshots']['fixture']
        assert client.call('/fixture/state')['counts']['fact_versions'] == prior_fact_count
        current = fields(metadata['variants'][0]['field_resolution'])['utqg_treadwear']
        assert current['default_value'] == 300 and {item['source_id'] for item in current['candidates']} == {'fixture'}
        revalidated = client.call('/v1/sources/fixture/live-query', {'query': records['priority']['query'], 'fallback_policy': 'ask'})
        assert revalidated['data_state'] == 'live_verified_304' and revalidated['provenance'][0]['snapshot_id'] == new_snapshot
        assert client.call('/v1/saved-comparisons/' + saved_id + '?mode=history') == detail
        check('metadata_only_and_304_keep_old_fact_and_saved_comparison')

        after = client.call('/fixture/state')
        assert after['old_evidence_unchanged'] and after['external_network_attempts'] == after['real_parser_children'] == 0
        assert after['counts']['ai_requests'] == after['counts']['embedding_requests'] == 0
        report.update(status='passed', initial=before, final=after)
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error)[:1600])
        raise
    finally:
        save(output / 'api-report.json', report)
        client.call('/fixture/shutdown', {})


def serve(port, output):
    if port in {3000, 8000} or not 1024 <= port <= 65535:
        raise ValueError('Use an owned private loopback port')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    private_root = Path(tempfile.mkdtemp(prefix='tire-field-authority-')).resolve()
    database_path = private_root / 'private.sqlite'
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
        from sqlalchemy import text
        from tire_api.db import FactVersion, Snapshot, TireVariant, UserSession, utcnow
        from tire_api.domain import LiveQueryRequest, digest
        from tire_api.main import create_app
        from tire_api import service as service_module
        from tire_api.service import QueryService
        from test_core import FixtureRegistry, success
        from test_field_evidence import known_variant

        def audit(event, arguments):
            if event == 'subprocess.Popen':
                counters['real_parser_children'] += 1
                raise RuntimeError('No Parser subprocess is allowed in this fixture')
            if event in {'socket.connect', 'socket.getaddrinfo'}:
                target = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
                if target not in {'127.0.0.1', '::1', 'localhost'}:
                    counters['external_network_attempts'] += 1
                    raise RuntimeError('External traffic is forbidden in this fixture')
            if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
                if not Path(str(arguments[0])).resolve().is_relative_to(private_root):
                    raise RuntimeError('Database access must remain inside the owned fixture')
        sys.addaudithook(audit)

        class Registry(FixtureRegistry):
            def __init__(self):
                self.responses, self.revalidate = {}, set()
            def sources(self):
                return [{'id': key, 'name': name, 'region': 'US', 'source_class': kind,
                    'status': 'ready', 'homepage': 'https://fixture.example', 'description': 'Explicit synthetic acceptance source',
                    'supported_models': ['Fixture Priority', 'Fixture Tie', 'Fixture Namespace'], 'default_model': 'Fixture Priority'}
                    for key, name, kind in [('fixture', '合成厂商来源 A', 'manufacturer_official'),
                        ('fixture-two', '合成监管来源 B', 'regulatory'), ('fixture-peer', '合成厂商来源 C', 'manufacturer_official')]]
            async def fetch(self, source_id, query, cached=None, *, on_observation=None):
                counters['synthetic_source_calls'] += 1
                key = (source_id, digest(query))
                result = deepcopy(self.responses[key])
                if key in self.revalidate and cached:
                    result.update(status='not_modified', body=None, variants=[])
                self.revalidate.add(key)
                return result

        registry = Registry()
        app = create_app('sqlite:///' + database_path.as_posix(), registry)
        database = app.state.database
        database.initialize()
        owner = str(uuid4())
        with database.sessions() as db:
            db.add(UserSession(id=owner, expires_at=utcnow() + timedelta(hours=2)))
            db.commit()
        records = {}
        fixed_start = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
        original_clock = service_module.utcnow

        def seed(name, model, source, value, wet='A', *, day=0, namespace='MSPN'):
            query = {'model': model}
            variant = known_variant(utqg_treadwear=value, eu_wet_grip=wet, product_code_type=namespace)
            variant.update(model=model, manufacturer_product_code='SYNTH-' + model.replace(' ', '-'))
            body = json.dumps({'scope': 'synthetic_fixture', 'source': source, 'variant': variant}, ensure_ascii=False)
            registry.responses[(source, digest(query))] = success(body, [variant])
            service_module.utcnow = lambda: fixed_start + timedelta(days=day)
            with database.sessions() as db:
                result = asyncio.run(QueryService(db, registry).execute(source,
                    LiveQueryRequest.model_validate({'query': query, 'fallback_policy': 'ask'}), owner))
            if result['data_state'] != 'live':
                raise RuntimeError('synthetic_seed_not_accepted')
            record = records.setdefault(name, {'variant_id': result['variants'][0]['id'], 'query': query, 'snapshots': {}})
            if record['variant_id'] != result['variants'][0]['id']:
                raise RuntimeError('synthetic_seed_identity_mismatch')
            record['snapshots'][source] = result['provenance'][0]['snapshot_id']

        try:
            seed('priority', 'Fixture Priority', 'fixture', 300, 'A', day=0)
            seed('priority', 'Fixture Priority', 'fixture-two', 500, 'B', day=1)
            seed('tie', 'Fixture Tie', 'fixture', 300, day=2)
            seed('tie', 'Fixture Tie', 'fixture-peer', 400, day=2)
            seed('namespace_mspn', 'Fixture Namespace', 'fixture', 300, day=3)
            seed('namespace_cai', 'Fixture Namespace', 'fixture-two', 500, day=3, namespace='CAI')
        finally:
            service_module.utcnow = original_clock
        protected = (TireVariant, Snapshot, FactVersion)

        def fingerprints():
            with database.engine.connect() as connection:
                return {model.__tablename__: {str(row['id']): digest({key: str(value) for key, value in row.items()})
                    for row in connection.execute(model.__table__.select()).mappings()} for model in protected}
        before = fingerprints()

        def state():
            current = fingerprints()
            with database.sessions() as db:
                names = ('tire_variants', 'snapshots', 'fact_versions', 'verifications', 'saved_comparisons',
                         'variant_identity_bindings', 'ai_requests', 'embedding_requests')
                counts = {name: db.execute(text('SELECT COUNT(*) FROM ' + name)).scalar_one() for name in names}
            return {'scope': 'synthetic_field_authority', 'normal_database_used': False, 'records': records,
                'counts': counts, **counters, 'old_evidence_unchanged': all(current[table].get(key) == value
                    for table, rows in before.items() for key, value in rows.items())}

        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, log_level='warning'))
        @app.get('/fixture/entry')
        def entry():
            response = JSONResponse({'private_synthetic_owner_session': True})
            response.set_cookie('tire_local_session', owner, httponly=True, samesite='strict')
            return response
        @app.get('/fixture/state')
        def get_state():
            return state()
        @app.post('/fixture/metadata-phase')
        def metadata_phase():
            key = ('fixture', digest(records['priority']['query']))
            registry.responses[key]['body'] += '\n<!-- synthetic metadata-only update -->'
            registry.revalidate.discard(key)
            return {'synthetic_metadata_phase': True}
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
            if private_root.parent != Path(tempfile.gettempdir()).resolve() or not private_root.name.startswith('tire-field-authority-'):
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
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
