"""Private HTTP source-management acceptance using explicitly synthetic sources.

The fixture uses the real API, SQLAlchemy and filesystem capture store. Every
source response is synthetic; external sockets, Parser children and other SQLite
paths are rejected. It is never a proof of a manufacturer or model connection.
"""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import time
from uuid import uuid4

from fastapi import Request

from golden_acceptance import Client, save

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'michelin-us'
QUERY = {'query': {'model': 'Fixture Tire', 'size': '265/40R20'}, 'fallback_policy': 'ask'}
SIGNED = {'operator': 'Synthetic Source QA', 'reason': 'Automated synthetic source-control check; not a human source approval'}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def run_api(base, output):
    output.mkdir(parents=True, exist_ok=False)
    client = Client(base)
    report = {'status': 'running', 'scope': 'synthetic_sources_real_http_source_management', 'checks': []}
    owned_fixture = False

    def check(name):
        report['checks'].append(name)
        save(output / 'api-report.json', report)

    def proposal(action, source=SOURCE, **extra):
        intent = {'action': action, **extra}
        preview = client.call(f'/v1/source-settings/{source}/preview', intent)
        require(preview['can_submit'], 'Preview must permit intended fixture operation')
        return {**intent, **SIGNED, 'expected_revision': preview['revision'],
                'expected_fingerprint': preview['fingerprint']}

    def change(action, source=SOURCE, **extra):
        return client.call(f'/v1/source-settings/{source}/revisions', proposal(action, source, **extra),
                           key=str(uuid4()), status=201)

    def blocked(value):
        require(value['data_state'] == 'source_unavailable', 'Management block must not offer local fallback')
        require(not value.get('variants') and not value.get('provenance') and not value.get('consent_id'),
                'Blocked request exposed facts or consent')
        require(value['reason'] in {'source_paused', 'source_archived', 'source_access_changed', 'source_access_pin_missing'},
                'Blocked request lost management reason')

    try:
        client.call('/health')
        client.call('/fixture/entry')
        before = client.call('/fixture/state')
        require(before['scope'] == 'synthetic_source_settings' and not before['normal_database_used'], 'Wrong fixture')
        owned_fixture = True
        report['initial'] = before
        catalog = client.call('/v1/source-settings')
        require(catalog['total'] == 11, 'Complete management catalog missing')
        by_id = {item['source_id']: item for item in catalog['items']}
        require(by_id['xiaomi-cn-vehicles']['target_kind'] == 'vehicle', 'Wrong vehicle management key')
        require(not by_id['eprel']['can_fetch'], 'Unconfigured EPREL became ready')
        require(all(item['management']['revision'] == 0 for item in by_id.values()), 'Read created settings')
        old_catalog = client.call('/v1/sources')['sources']
        require('xiaomi-cn-vehicles' not in {item['id'] for item in old_catalog}, 'Vehicle entered tire catalog')
        check('read_only_complete_catalog_and_existing_domain_membership')

        payload, key = proposal('edit_notes', notes='合成验收备注 🛞\n仅本机'), str(uuid4())
        first = client.call(f'/v1/source-settings/{SOURCE}/revisions', payload, key=key, status=201)
        repeated = client.call(f'/v1/source-settings/{SOURCE}/revisions', payload, key=key, status=201)
        require(repeated['replayed'] and repeated['event'] == first['event'], 'UUID replay changed event')
        require(first['source']['management']['access_generation'] == 0, 'Notes invalidated access')
        mismatch = client.call(f'/v1/source-settings/{SOURCE}/revisions', {**payload, 'reason': 'Different request payload'}, key=key, status=409)
        require(mismatch['detail']['code'] == 'idempotency_payload_mismatch', 'Mismatch not rejected')
        client.call(f'/v1/source-settings/{SOURCE}/preview', {'action': 'pause', 'url': 'https://forbidden.example/'}, status=422)
        check('utf8_notes_uuid_replay_and_forbidden_capability_mutation')

        client.call('/fixture/mode', {'mode': 'offline'})
        failed = client.call(f'/v1/sources/{SOURCE}/live-query', QUERY)
        require(failed['data_state'] == 'consent_required', 'Fixture offline failure lost ask policy')
        grant = client.call('/v1/fallback-consents', {'query_id': failed['query_id'], 'decision': 'allow', 'scope': 'once'}, status=201)
        consent_query = {**QUERY, 'consent_id': grant['id']}
        paused = change('pause')
        calls = client.call('/fixture/state')['synthetic_source_calls']
        blocked(client.call(f'/v1/sources/{SOURCE}/live-query', QUERY))
        blocked(client.call(f'/v1/sources/{SOURCE}/live-query', consent_query))
        require(client.call('/fixture/state')['synthetic_source_calls'] == calls, 'Pause still fetched')
        require(not client.call('/fixture/state')['used_consents'], 'Blocked consent was consumed')
        other = Client(base)
        other.call('/health')
        require(other.call(f'/v1/source-settings/{SOURCE}')['management']['state'] == 'paused', 'State was session local')
        history = client.call('/v1/compare', {'variant_ids': [before['variant_id']]})
        require(history['variants'][0]['id'] == before['variant_id'], 'Pause erased historical comparison')
        check('pause_blocks_new_and_previously_authorized_queries_but_preserves_history')

        enabled = change('enable')
        require(enabled['source']['management']['access_generation'] > paused['event']['access_generation'], 'Enable did not advance generation')
        blocked(client.call(f'/v1/sources/{SOURCE}/live-query', consent_query))
        fresh_failure = client.call(f'/v1/sources/{SOURCE}/live-query', QUERY)
        fresh_grant = client.call('/v1/fallback-consents', {'query_id': fresh_failure['query_id'], 'decision': 'allow', 'scope': 'once'}, status=201)
        local = client.call(f'/v1/sources/{SOURCE}/live-query', {**QUERY, 'consent_id': fresh_grant['id']})
        require(local['data_state'] == 'local_snapshot' and len(local['variants']) == 1, 'New explicit consent stopped working')
        check('pause_resume_invalidates_old_generation_without_removing_new_explicit_fallback')

        archived = change('archive')
        require(archived['source']['effective_status'] == 'archived', 'Archive not projected')
        blocked(client.call(f'/v1/sources/{SOURCE}/live-query', QUERY))
        restored = change('restore')
        require(restored['source']['management']['state'] == 'paused' and not restored['source']['can_fetch'], 'Restore silently enabled collection')
        change('pause', source='eprel')
        pending = change('enable', source='eprel')
        require(not pending['source']['can_fetch'] and pending['source']['registered_status'] == 'configuration_required', 'Enable overrode capability')
        check('archive_restore_and_pending_capability_remain_distinct')

        change('enable')
        client.call('/fixture/mode', {'mode': 'live'})
        query_client = Client(base)
        query_client.call('/health')
        query_client.call('/fixture/entry')
        for action, note in [('pause', None), ('edit_notes', '备注更新不打断正在核验的请求')]:
            if action == 'edit_notes':
                change('enable')
            counts_before = client.call('/fixture/state')['counts']
            client.call('/fixture/hold', {})
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(query_client.call, f'/v1/sources/{SOURCE}/live-query', QUERY)
                try:
                    deadline = time.monotonic() + 15
                    while not client.call('/fixture/state')['holding']:
                        require(time.monotonic() < deadline, 'Synthetic response never entered hold')
                        time.sleep(0.05)
                    change(action, **({'notes': note} if note is not None else {}))
                finally:
                    client.call('/fixture/release', {})
                result = future.result(timeout=20)
            after = client.call('/fixture/state')['counts']
            require(after['raw_captures'] == counts_before['raw_captures'] + 1, 'Received raw not retained')
            if action == 'pause':
                blocked(result)
                for table in ('snapshots', 'fact_versions', 'verifications', 'change_events'):
                    require(after[table] == counts_before[table], 'In-flight response was adopted after pause: ' + table)
            else:
                require(result['data_state'] == 'live', 'Notes-only update rejected admitted response')
                require(after['fact_versions'] == counts_before['fact_versions'] + 1, 'Valid admitted response was not adopted')
        check('in_flight_pause_keeps_raw_without_adoption_and_notes_do_not_cancel')

        after = client.call('/fixture/state')
        require(after['old_evidence_unchanged'], 'Initial immutable evidence changed')
        require(after['external_network_attempts'] == after['real_parser_children'] == 0, 'Fixture crossed execution scope')
        require(after['counts']['ai_requests'] == after['counts']['embedding_requests'] == 0, 'Model ledger unexpectedly changed')
        report.update(status='passed', final=after)
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error)[:1800])
        raise
    finally:
        save(output / 'api-report.json', report)
        if owned_fixture:
            try:
                client.call('/fixture/release', {})
            finally:
                client.call('/fixture/shutdown', {})


def serve(port, output):
    if port in {3000, 8000} or not 1024 <= port <= 65535:
        raise ValueError('Use an owned private loopback port')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    private_root = Path(tempfile.mkdtemp(prefix='tire-source-settings-')).resolve()
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
        from tire_api.adapters import registry as installed_registry
        from tire_api.db import UserSession, utcnow
        from tire_api.domain import LiveQueryRequest, digest
        from tire_api.main import create_app
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
            SPECS = installed_registry.SPECS
            PENDING_SOURCES = installed_registry.PENDING_SOURCES
            supports_parser_deployments = False

            def __init__(self):
                self.mode, self.sequence, self.holding, self.release = 'live', 0, False, None

            def sources(self):
                rows = deepcopy(installed_registry.sources())
                for row in rows:
                    if row['id'] == SOURCE:
                        row.update(name='合成轮胎来源 · 管理验收', description='明确合成样本，仅本机私有验收',
                                   supported_models=['Fixture Tire'], default_model='Fixture Tire')
                return rows

            async def fetch(self, source_id, query, cached=None, *, on_observation=None):
                require(source_id == SOURCE, 'Unexpected fixture source')
                counters['synthetic_source_calls'] += 1
                if self.mode == 'offline':
                    return {'status': 'unavailable', 'reason': 'explicit_synthetic_offline'}
                row = known_variant(utqg_treadwear=300 + self.sequence,
                    evidence_spans={'manufacturer_product_code': '$.sku.manufacturer_product_code',
                                    'facts.product_code_type': '$.sku.facts.product_code_type',
                                    'facts.utqg_treadwear': '$.sku.facts.utqg_treadwear'})
                result = success(json.dumps({'synthetic': True, 'sequence': self.sequence, 'sku': row}, ensure_ascii=False), [row])
                if on_observation:
                    on_observation({key: result.get(key) for key in ('url', 'body', 'content_type', 'parser_version', 'parser_identity')})
                if self.release is not None:
                    event = self.release
                    self.holding = True
                    await asyncio.wait_for(event.wait(), timeout=30)
                    self.holding, self.release = False, None
                return result

        registry = Registry()
        app = create_app('sqlite:///' + database_path.as_posix(), registry)
        database = app.state.database
        database.initialize()
        owner = str(uuid4())
        with database.sessions() as db:
            db.add(UserSession(id=owner, expires_at=utcnow() + timedelta(hours=2)))
            db.commit()
            seeded = asyncio.run(QueryService(db, registry).execute(SOURCE, LiveQueryRequest.model_validate(QUERY), owner))
            require(seeded['data_state'] == 'live', 'Synthetic seed failed')
        variant_id = seeded['variants'][0]['id']

        def fingerprints():
            result = {}
            with database.sessions() as db:
                for table in ('tire_variants', 'snapshots', 'fact_versions'):
                    result[table] = {row['id']: digest(dict(row)) for row in db.execute(text('SELECT * FROM ' + table)).mappings()}
            return result
        before = fingerprints()

        def state():
            current = fingerprints()
            with database.sessions() as db:
                names = ('tire_variants', 'snapshots', 'fact_versions', 'verifications', 'change_events', 'raw_captures',
                         'source_setting_revisions', 'fallback_consents', 'ai_requests', 'embedding_requests')
                counts = {name: db.execute(text('SELECT COUNT(*) FROM ' + name)).scalar_one() for name in names}
                used = db.execute(text('SELECT COUNT(*) FROM fallback_consents WHERE used_at IS NOT NULL')).scalar_one()
            return {'scope': 'synthetic_source_settings', 'normal_database_used': False, 'source_id': SOURCE,
                'query': QUERY, 'variant_id': variant_id, 'snapshot_id': seeded['provenance'][0]['snapshot_id'],
                'counts': counts, 'holding': registry.holding, 'used_consents': used, **counters,
                'old_evidence_unchanged': all(current[table].get(key) == value
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

        @app.post('/fixture/mode')
        async def mode(request: Request):
            body = await request.json()
            require(body.get('mode') in {'live', 'offline'}, 'Invalid fixture mode')
            registry.mode = body['mode']
            return {'synthetic_mode': registry.mode}

        @app.post('/fixture/hold')
        async def hold():
            require(registry.release is None, 'A synthetic request is already held')
            registry.sequence += 1
            registry.release = asyncio.Event()
            return {'next_synthetic_response_held': True}

        @app.post('/fixture/release')
        async def release():
            if registry.release is not None:
                registry.release.set()
            return {'synthetic_response_released': True}

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
            if private_root.parent != Path(tempfile.gettempdir()).resolve() or not private_root.name.startswith('tire-source-settings-'):
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
