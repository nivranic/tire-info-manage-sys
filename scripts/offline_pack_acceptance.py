"""Private four-domain offline-pack fixture and HTTP checks; never normal data."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def require(value, code):
    if not value:
        raise AssertionError(code)


def run(port, output, check_only):
    require(1024 <= port <= 65535 and port not in {3000, 8000}, 'private_port_required')
    output = output.resolve()
    require(output.is_relative_to((ROOT / '.artifacts').resolve()), 'artifact_directory_required')
    output.mkdir(parents=True, exist_ok=False)
    private = Path(tempfile.mkdtemp(prefix='tire-offline-qa-')).resolve()
    checkpoint = output / 'private-checkpoint.sqlite'
    counters = {'external_network_attempts': 0, 'real_parser_children': 0, 'provider_calls': 0}
    result = {'status': 'running', 'normal_database_used': False, 'scope': 'synthetic_offline_four_domains'}
    os.environ.update(TIRE_DATABASE_URL='sqlite:///' + (private / 'import-guard.sqlite').as_posix(),
        DATABASE_URL='sqlite:///' + (private / 'import-guard.sqlite').as_posix(),
        TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_ENABLED='0',
        TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(private / 'objects'),
        TI_PARSER_BUNDLE_ROOT=str(private / 'bundles'), TI_DISABLED_SOURCES='',
        TIRE_CORS_ORIGINS='http://127.0.0.1:3003')
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]

    def audit(event, args):
        if event == 'subprocess.Popen':
            counters['real_parser_children'] += 1
            raise RuntimeError('Parser children forbidden in offline fixture')
        if event in {'socket.connect', 'socket.getaddrinfo'}:
            address = args[1][0] if event == 'socket.connect' and isinstance(args[1], tuple) else args[0]
            if address not in {'127.0.0.1', '::1', 'localhost'}:
                counters['external_network_attempts'] += 1
                raise RuntimeError('External network forbidden in offline fixture')
        if event == 'sqlite3.connect' and str(args[0]) != ':memory:':
            target = Path(str(args[0])).resolve()
            require(target.is_relative_to(private) or target == checkpoint, 'private_database_required')

    sys.addaudithook(audit)
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from sqlalchemy import inspect, text
    import uvicorn
    from tire_api.adapters.transport import SafeHttpClient
    from tire_api.ai_gateway import OpenAIResponsesAdapter
    from tire_api.embedding_gateway import OpenAIEmbeddingAdapter
    from tire_api import parser_runtime
    from tire_api.main import create_app
    from tire_api.domain import digest, stable_json
    from tire_api.db import uid
    from test_core import FixtureRegistry, live
    from test_garage import PROFILE
    from test_offline_packs import seed_domains, plan, confirm, download

    def forbidden(*args, **kwargs):
        counters['provider_calls'] += 1
        raise RuntimeError('Real source/model/parser forbidden in offline fixture')

    SafeHttpClient._request = forbidden
    OpenAIResponsesAdapter.generate = OpenAIResponsesAdapter.stream = forbidden
    OpenAIEmbeddingAdapter.embed = forbidden
    parser_runtime._run_sync = forbidden
    registry = FixtureRegistry()
    database_path = private / 'private.sqlite'
    app = create_app('sqlite:///' + database_path.as_posix(), registry)
    database = app.state.database
    entry_owner = {'value': None}

    @app.middleware('http')
    async def synthetic_entry_cookie(request, call_next):
        if request.url.path in {'/fixture/entry', '/v1/offline-qa/entry'} and entry_owner['value']:
            # Bind fixture entry before production session middleware, so its
            # first anonymous session cannot overwrite the intentional seed cookie.
            request.scope['headers'] = [(k, v) for k, v in request.scope['headers'] if k.lower() != b'cookie'] + [
                (b'cookie', ('tire_local_session=' + entry_owner['value']).encode('ascii'))]
        return await call_next(request)
    evidence_tables = ('snapshots', 'fact_versions', 'tire_variants', 'verifications',
        'recall_snapshots', 'recall_revisions', 'recall_verifications', 'vehicle_snapshots',
        'vehicle_verifications', 'test_events', 'test_event_revisions')

    def evidence_fingerprint():
        with database.sessions() as db:
            names = set(inspect(database.engine).get_table_names())
            return {name: sorted(digest({k: {'bytes': bytes(v).hex()} if isinstance(v, (bytes, memoryview)) else v
                for k, v in dict(row).items()}) for row in db.execute(text('SELECT * FROM ' + name)).mappings())
                for name in evidence_tables if name in names}

    try:
        with TestClient(app) as client:
            tire = live(client).json()['variants'][0]
            refs, origin = seed_domains(client, database)
            garage = client.post('/v1/garage', json={**PROFILE,
                'nickname': '合成车库 · 离线私人预览',
                'rear': {'size': tire['size'], 'current_variant_id': tire['id']}})
            garage.raise_for_status()
            client.post('/v1/watchlists', json={'variant_id': tire['id']}).raise_for_status()
            prepared = plan(client, {'garage': {'include': True}, 'watchlist': {'include': True},
                'recent': {'include': False}, 'references': refs})
            require(prepared['can_confirm'], 'complete_scope_must_be_confirmable')
            confirmation_key = uid()
            descriptor = confirm(client, prepared, confirmation_key).json()
            raw, envelope = download(client, descriptor)
            require(len(envelope['members']) == 5 and len(envelope['contexts']) == 2 and len(envelope['documents']) == 9,
                'four_domain_fixture_contract')
            owner = client.cookies.get('tire_local_session')
            require(owner is not None, 'private_cookie_required')
            entry_owner['value'] = owner
            for name, value in [('valid-descriptor', descriptor), ('valid-plan', prepared)]:
                (output / (name + '.json')).write_text(stable_json(value), encoding='utf-8')
            (output / 'valid-envelope.json').write_bytes(raw)
            sealed = evidence_fingerprint()
            checks = 0
            require(client.get('/v1/offline-packs/' + descriptor['id'] + '?mode=history').json() == descriptor, 'owned_descriptor'); checks += 1
            other = TestClient(app)
            require(other.get(descriptor['download_path']).status_code == 404, 'cross_owner_denied'); checks += 1
            replay = confirm(client, prepared, confirmation_key)
            require(replay.status_code == 201 and replay.json() == descriptor, 'idempotent_confirmation'); checks += 1
            require(confirm(client, prepared, expected_fingerprint='0' * 64).status_code == 409, 'fingerprint_denied'); checks += 1
            require(confirm(client, prepared, allow_device_storage=False).status_code == 422, 'explicit_storage_consent'); checks += 1
            require(all(x not in raw for x in (b'raw canary', b'FULL PDF', b'actor_session_id', b'Fixture reviewer')), 'raw_secret_exclusion'); checks += 1
            require(evidence_fingerprint() == sealed, 'source_evidence_unchanged'); checks += 1
            require(len(registry.calls) == 1, 'export_does_not_refresh_source'); checks += 1
            result.update(http_checks=checks, fixture_sha256=hashlib.sha256(raw).hexdigest(),
                fixture_byte_count=len(raw), counts=prepared['counts'], revision_origin_pinned=True)

        def state():
            with database.sessions() as db:
                names = set(inspect(database.engine).get_table_names())
                counts = {name: db.execute(text('SELECT COUNT(*) FROM ' + name)).scalar_one() for name in
                    ('offline_pack_plans', 'offline_packs', 'knowledge_documents', 'ai_evidence_packs', 'ai_requests',
                    'embedding_requests', 'fallback_consents') if name in names}
            return {**result, **counters, 'process_id': os.getpid(), 'counts': counts,
                'sealed_evidence_unchanged': evidence_fingerprint() == sealed,
                'synthetic_source_calls': len(registry.calls), 'real_openai_calls': 0}

        @app.get('/fixture/entry')
        def entry():
            response = JSONResponse({'scope': 'synthetic_offline_four_domains', 'normal_database_used': False})
            response.set_cookie('tire_local_session', owner, httponly=True, samesite='strict')
            return response

        @app.get('/v1/offline-qa/entry')
        def native_entry():
            # Fixture-only route inside the production bridge's existing v1 authority.
            # The native bridge consumes this synthetic HttpOnly cookie; no renderer secret.
            return entry()

        @app.get('/fixture/state')
        def fixture_state():
            return state()

        @app.get('/fixture/references')
        def references():
            return {'scope': 'synthetic_offline_four_domains', 'references': refs,
                'fixture_package_id': descriptor['id'], 'revision_origin': origin}

        result['status'] = 'passed' if check_only else 'ready'
        (output / 'fixture-ready.json').write_text(json.dumps(state(), ensure_ascii=False, indent=2), encoding='utf-8')
        if check_only:
            print(json.dumps(state(), ensure_ascii=False))
        else:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', port))
            print('Private offline fixture ready; synthetic only; models/parsers forbidden.', flush=True)
            uvicorn.run(app, host='127.0.0.1', port=port, access_log=False, log_level='warning')
            result['status'] = 'stopped'
    except BaseException as error:
        result.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        result.update(counters)
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        if database_path.exists():
            with sqlite3.connect(database_path) as source, sqlite3.connect(checkpoint) as target:
                source.backup(target)
        database.engine.dispose()
        # Retain the uniquely named private workspace and checkpoint for independent review.
        # Neither is a normal workspace database or a device credential store.
        (output / 'private-path.json').write_text(json.dumps({'directory': str(private)}), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8003)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    run(args.port, args.output, args.check_only)
