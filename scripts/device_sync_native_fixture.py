"""Private real FastAPI history producer for native sync QA; synthetic evidence only."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


def run(output: Path, port: int):
    root = Path(__file__).resolve().parents[1]
    output = output.resolve()
    if not output.is_relative_to(root / '.artifacts/device-sync') or port in {3000, 8000} or not 1024 <= port <= 65535:
        raise ValueError('Use an isolated artifact child and local QA port')
    output.mkdir(parents=True, exist_ok=False)
    private = Path(tempfile.mkdtemp(prefix='ti-sync48-')).resolve()
    counters = {'external_network_attempts': 0, 'parser_children': 0, 'provider_calls': 0}
    os.environ.update(TIRE_DATABASE_URL='sqlite:///' + (private / 'import.sqlite').as_posix(),
        DATABASE_URL='sqlite:///' + (private / 'import.sqlite').as_posix(),
        TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_ENABLED='0',
        TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(private / 'objects'),
        TI_PARSER_BUNDLE_ROOT=str(private / 'bundles'), TI_DISABLED_SOURCES='')
    sys.path[:0] = [str(root / 'apps/api'), str(root / 'apps/api/tests')]

    def audit(event, args):
        if event == 'subprocess.Popen':
            counters['parser_children'] += 1
            raise RuntimeError('Parser children forbidden')
        if event in {'socket.connect', 'socket.getaddrinfo'}:
            address = args[1][0] if event == 'socket.connect' and isinstance(args[1], tuple) else args[0]
            if address not in {'127.0.0.1', '::1', 'localhost'}:
                counters['external_network_attempts'] += 1
                raise RuntimeError('External network forbidden')
        if event == 'sqlite3.connect' and str(args[0]) != ':memory:':
            target = Path(str(args[0])).resolve()
            if not target.is_relative_to(private):
                raise RuntimeError('Only private databases allowed')

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
    from test_core import FixtureRegistry, live
    from test_garage import PROFILE
    from test_offline_packs import seed_domains, plan, confirm, download

    def forbidden(*args, **kwargs):
        counters['provider_calls'] += 1
        raise RuntimeError('Real source/model/parser forbidden')

    SafeHttpClient._request = forbidden
    OpenAIResponsesAdapter.generate = OpenAIResponsesAdapter.stream = forbidden
    OpenAIEmbeddingAdapter.embed = forbidden
    parser_runtime._run_sync = forbidden
    registry = FixtureRegistry()
    app = create_app('sqlite:///' + (private / 'private.sqlite').as_posix(), registry)
    database = app.state.database
    owner = None
    mode = 'normal'
    requests = []
    pending = set()
    evidence_tables = ('snapshots', 'fact_versions', 'tire_variants', 'verifications',
        'recall_snapshots', 'recall_revisions', 'recall_verifications', 'vehicle_snapshots',
        'vehicle_verifications', 'test_events', 'test_event_revisions')

    def fingerprint():
        with database.sessions() as db:
            names = set(inspect(database.engine).get_table_names())
            return {name: sorted(digest({k: {'bytes': bytes(v).hex()} if isinstance(v, (bytes, memoryview)) else v
                for k, v in dict(row).items()}) for row in db.execute(text('SELECT * FROM ' + name)).mappings())
                for name in evidence_tables if name in names}

    @app.middleware('http')
    async def bind_entry(request, call_next):
        if request.url.path == '/v1/offline-qa/entry' and owner:
            request.scope['headers'] = [(k, v) for k, v in request.scope['headers'] if k.lower() != b'cookie'] + [
                (b'cookie', ('tire_local_session=' + owner).encode('ascii'))]
        return await call_next(request)

    with TestClient(app) as client:
        tire = live(client).json()['variants'][0]
        refs, origin = seed_domains(client, database)
        response = client.post('/v1/garage', json={**PROFILE, 'nickname': '同步前合成私人车库',
            'rear': {'size': tire['size'], 'current_variant_id': tire['id']}})
        response.raise_for_status()
        garage_id = response.json()['id']
        client.post('/v1/watchlists', json={'variant_id': tire['id']}).raise_for_status()
        prepared = plan(client, {'garage': {'include': True}, 'watchlist': {'include': True},
            'recent': {'include': False}, 'references': refs})
        descriptor = confirm(client, prepared).json()
        raw, envelope = download(client, descriptor)
        owner = client.cookies.get('tire_local_session')
        assert owner and prepared['can_confirm'] and len(envelope['members']) == 5
        sealed = fingerprint()
    for filename, value in [('base-descriptor.json', descriptor), ('base-plan.json', prepared)]:
        (output / filename).write_text(stable_json(value), encoding='utf-8')
    (output / 'base-pack.json').write_bytes(raw)
    (output / 'private-path.json').write_text(json.dumps({'directory': str(private)}), encoding='utf-8')

    def state():
        with database.sessions() as db:
            counts = {name: db.execute(text('SELECT COUNT(*) FROM ' + name)).scalar_one() for name in
                ('offline_pack_plans', 'offline_packs', 'evidence_objects', 'ai_requests', 'embedding_requests')}
        return {'schema': 'native-sync48-real-api-fixture@1', 'process_id': os.getpid(), 'port': port,
            'normal_database_used': False, 'real_source_model_calls': 0, 'synthetic_source_calls': len(registry.calls),
            'mode': mode, 'pending': len(pending), 'requests': requests, 'counts': counts, **counters,
            'sealed_evidence_unchanged': fingerprint() == sealed, 'base_sha256': hashlib.sha256(raw).hexdigest()}

    def persist():
        (output / 'state.json').write_text(json.dumps(state(), ensure_ascii=False, indent=2), encoding='utf-8')

    @app.get('/v1/offline-qa/entry')
    def entry():
        response = JSONResponse({'fixture_only': True, 'normal_database_used': False})
        response.set_cookie('tire_local_session', owner, httponly=True, samesite='strict')
        return response

    @app.get('/fixture/state')
    def fixture_state():
        persist()
        return state()

    @app.post('/fixture/control')
    async def control(value: dict):
        nonlocal mode
        assert set(value) <= {'mode', 'nickname'}
        if 'mode' in value:
            assert value['mode'] in {'normal', 'hang_prepare', 'hang_confirm', 'hang_download'}
            mode = value['mode']
        if 'nickname' in value:
            assert isinstance(value['nickname'], str) and 0 < len(value['nickname']) <= 80
            with TestClient(app) as editor:
                editor.cookies.set('tire_local_session', owner)
                before = editor.get('/v1/garage/' + garage_id, params={'mode': 'history'})
                before.raise_for_status()
                saved = before.json()
                saved['profile']['nickname'] = value['nickname']
                changed = editor.put('/v1/garage/' + garage_id, json={
                    'expected_revision': saved['revision'], 'profile': saved['profile']})
                changed.raise_for_status()
        persist()
        return {'mode': mode}

    @app.post('/fixture/shutdown')
    def shutdown():
        server.should_exit = True
        return {'shutdown_requested': True}

    async def transport(scope, receive, send):
        if scope['type'] != 'http':
            return await app(scope, receive, send)
        path = scope['path']
        headers = dict(scope.get('headers', []))
        marker = headers.get(b'x-tire-offline-sync') == b'1'
        item = None
        if path.startswith('/v1/offline'):
            item = {'path': path, 'method': scope['method'], 'sync_marker': marker,
                'cookie_present': bool(headers.get(b'cookie')), 'owner_header_present': bool(headers.get(b'x-tire-offline-expected-owner')),
                'idempotency_key': headers.get(b'idempotency-key', b'').decode('ascii') or None}
            requests.append(item)
        hold = marker and ((mode == 'hang_prepare' and path.endswith('updates:prepare')) or
            (mode == 'hang_confirm' and path == '/v1/offline-packs') or
            (mode == 'hang_download' and path.endswith('/download')))
        buffered = []
        async def recorded(message):
            if item is not None and message['type'] == 'http.response.start':
                item['status'] = message['status']
            if hold:
                buffered.append(message)
            else:
                await send(message)
        await app(scope, receive, recorded)
        if hold:
            identity = id(buffered)
            pending.add(identity)
            if item is not None:
                item['response_held_after_real_endpoint'] = True
            persist()
            try:
                while mode != 'normal':
                    await asyncio.sleep(0.1)
                for message in buffered:
                    await send(message)
            finally:
                pending.discard(identity)
                persist()
        persist()

    server = uvicorn.Server(uvicorn.Config(transport, host='127.0.0.1', port=port, access_log=False, log_level='warning'))
    persist()
    print('Private real FastAPI native sync fixture ready; synthetic only.', flush=True)
    try:
        server.run()
    finally:
        persist()
        database.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8049)
    options = parser.parse_args()
    run(options.output, options.port)
