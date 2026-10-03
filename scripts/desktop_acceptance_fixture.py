"""Private real FastAPI fixture for native desktop acceptance; never normal data.

Source data is synthetic, with no real parser receipt or upstream/model traffic.
Uses the production cookie name so the real Rust secure-session bridge is tested.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
from unittest.mock import patch

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from sqlalchemy import func, select
import uvicorn

from query_filter_browser_qa import COUNTS, FilterRegistry, formal_fingerprint
from tire_api.db import EvidenceDocument, UserSession, WatchItem
from tire_api.main import create_app


@contextmanager
def fixture(directory: Path, port: int):
    registry = FilterRegistry(model='Pilot Sport EV')
    observations = []
    slow = {'started': 0, 'disconnected': 0, 'completed': 0}
    with patch.dict(os.environ, {
        'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0',
        'TI_OBJECT_STORE_BACKEND': 'filesystem',
        'TI_OBJECT_STORE_ROOT': str(directory / 'objects'),
        'TI_PARSER_BUNDLE_ROOT': str(directory / 'bundles'),
    }):
        app = create_app('sqlite:///' + (directory / 'qa.db').as_posix(), registry)

        async def native_probe(scope, receive, send):
            # Observe the actual ASGI socket before BaseHTTPMiddleware. Its request
            # wrapper can consume disconnect events, so Request.is_disconnected()
            # inside a FastAPI route is not reliable evidence for this probe.
            if scope['type'] != 'http' or scope['path'] != '/v1/desktop-qa/slow':
                return await app(scope, receive, send)
            slow['started'] += 1
            try:
                async with asyncio.timeout(10):
                    while True:
                        message = await receive()
                        if message['type'] == 'http.disconnect':
                            slow['disconnected'] += 1
                            return
            except TimeoutError:
                slow['completed'] += 1
                await send({'type': 'http.response.start', 'status': 200,
                            'headers': [(b'content-type', b'application/json')]})
                await send({'type': 'http.response.body', 'body': b'{"completed":true}'})

        server = uvicorn.Server(uvicorn.Config(native_probe, host='127.0.0.1', port=port, access_log=False))

        @app.middleware('http')
        async def observe(request: Request, call_next):
            # Record header presence, never cookie/header values or payloads.
            if not request.url.path.startswith('/fixture/'):
                observations.append({'method': request.method, 'path': request.url.path,
                    'cookie_present': bool(request.headers.get('cookie')),
                    'origin_present': bool(request.headers.get('origin')),
                    'idempotency_present': bool(request.headers.get('idempotency-key')),
                    'metadata_present': bool(request.headers.get('x-evidence-metadata'))})
            return await call_next(request)

        @app.get('/v1/desktop-qa/redirect')
        def redirect():
            return RedirectResponse(f'http://127.0.0.1:{port}/v1/desktop-qa/redirect-target', status_code=302)

        @app.get('/v1/desktop-qa/redirect-target')
        def redirected():
            return {'redirect_followed': True}

        @app.get('/fixture/state')
        def state():
            with app.state.database.sessions() as db:
                counts = {model.__tablename__: db.scalar(select(func.count()).select_from(model))
                          for model in (*COUNTS, UserSession, WatchItem, EvidenceDocument)}
            return {'synthetic_source': True, 'real_source_calls': 0, 'real_model_calls': 0,
                    'parser_execution': 'synthetic_output_no_subprocess_receipt',
                    'counts': counts, 'source_calls': len(registry.calls),
                    'requests': observations, 'slow': slow,
                    'formal_fingerprint': formal_fingerprint(app.state.database)}

        @app.post('/fixture/shutdown')
        def shutdown():
            server.should_exit = True
            return {'shutdown_requested': True}

        try:
            yield app, server
        finally:
            app.state.database.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8002)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / '.artifacts' / 'desktop'
    directory = args.directory.resolve()
    if not directory.is_relative_to(root.resolve()) or directory == root.resolve():
        parser.error('Use a new child directory of .artifacts/desktop.')
    if not 1024 <= args.port <= 65535 or args.port in {3000, 8000}:
        parser.error('Use an unprivileged isolated port, never the normal service port.')
    directory.mkdir(parents=True, exist_ok=False)
    with fixture(directory, args.port) as (app, server):
        if args.self_test:
            with TestClient(app) as client:
                health = client.get('/health')
                assert health.status_code == 200 and 'tire_local_session' in client.cookies
                result = client.post('/v1/sources/filter-fixture/live-query', json={
                    'query': {'model': 'Pilot Sport EV', 'size': '265/40R20'}, 'fallback_policy': 'ask'})
                assert result.status_code == 200 and len(result.json()['variants']) == 6
                assert client.get('/v1/desktop-qa/redirect', follow_redirects=False).status_code == 302
                state = client.get('/fixture/state').json()
                assert state['counts']['ai_requests'] == state['counts']['embedding_requests'] == 0
                print(json.dumps({'status': 'passed', 'checks': 4, 'scope': 'fixture_only'}, ensure_ascii=False))
        else:
            print('Private native acceptance API; synthetic source; models disabled.', flush=True)
            server.run()


if __name__ == '__main__':
    main()
