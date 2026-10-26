"""Private R75 HTTP/React fixture. Synthetic seeds, no production database or providers."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def serve(port, web_port, output):
    output = output.resolve()
    assert output.is_relative_to((ROOT / '.artifacts').resolve())
    assert 1024 <= port <= 65535 and port not in {3000, 8000}
    assert 1024 <= web_port <= 65535 and web_port not in {3000, 8000, port}
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    output.mkdir(parents=True, exist_ok=False)
    storage = ROOT / '.artifacts' / ('r75-web-' + uuid4().hex[:12])
    storage.mkdir()
    database_path = storage / 'p.sqlite'
    private_url = 'sqlite:///' + database_path.as_posix()
    for name in list(os.environ):
        if (name.startswith(('TI_', 'TIRE_', 'OPENAI_', 'ANTHROPIC_', 'AZURE_OPENAI_'))
                or name == 'DATABASE_URL' or name.lower().endswith('_proxy')):
            del os.environ[name]
    os.environ.update(TIRE_DATABASE_URL=private_url, DATABASE_URL=private_url,
        TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_ENABLED='0',
        TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(storage / 'o'),
        TI_PARSER_BUNDLE_ROOT=str(storage / 'b'),
        TIRE_CORS_ORIGINS=f'http://127.0.0.1:{web_port},http://localhost:{web_port}')
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
    names = [str(path.relative_to(ROOT)).replace('\\', '/') for directory in
             ['apps/api/tire_api', 'packages/domain-types/src',
              'packages/api-client/src', 'apps/web/components']
             for path in (ROOT / directory).rglob('*') if path.is_file()
             and path.suffix in {'.py', '.ts', '.tsx', '.css'}]
    names += ['scripts/test_candidate_web_fixture.py'] + ['apps/api/tests/' + name + '.py' for name in
        ['candidate_interpretation_support', 'test_fitment_relations', 'test_test_sku_links',
         'test_test_events', 'test_test_preference_routes', 'test_research', 'admin_support']]
    source_hashes = lambda: {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                             for name in sorted(names)}
    sources_before = source_hashes()
    platform.uname()
    counts = {'external_network_attempts': 0, 'child_process_attempts': 0,
              'normal_database_attempts': 0}

    def audit(event, arguments):
        if event == 'subprocess.Popen':
            counts['child_process_attempts'] += 1
            raise RuntimeError('R75 private fixture forbids child processes')
        if event in {'socket.connect', 'socket.getaddrinfo'}:
            address = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
            if address not in {'127.0.0.1', '::1', 'localhost'}:
                counts['external_network_attempts'] += 1
                raise RuntimeError('R75 private fixture forbids external networking')
        if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
            if not Path(str(arguments[0])).resolve().is_relative_to(storage):
                counts['normal_database_attempts'] += 1
                raise RuntimeError('R75 GUID private database required')
    sys.addaudithook(audit)
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    import uvicorn
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from tire_api import main
    from tire_api.db import AuditEvent
    from tire_api.test_events import TireTestRevision
    from tire_api.test_sku_link_models import TestSkuLinkRevision
    from test_fitment_relations import NoNetworkRegistry
    from admin_support import register_admin
    from candidate_interpretation_support import seed_candidate_scenario, request_body

    assert main.app.state.database.engine.url.get_backend_name() == 'sqlite'
    assert Path(main.app.state.database.engine.url.database).resolve() == database_path.resolve()
    app = main.create_app(private_url, NoNetworkRegistry())
    original_lifespan = app.router.lifespan_context
    state = {'synthetic_only': True, 'normal_database_used': False, 'provider_calls': 0}
    case = None

    @asynccontextmanager
    async def lifespan(application):
        nonlocal case
        async with original_lifespan(application):
            client = TestClient(application, backend_options={'loop_factory': asyncio.SelectorEventLoop})
            try:
                register_admin(client)
                session = client.cookies['tire_local_session']
                case = seed_candidate_scenario(client, application.state.database, session)
                state.update(event_id=case.event['id'], event=case.event,
                    request=request_body(case), links=case.links,
                    variants=[selected['variant_id'] for selected in case.selections],
                    selections=case.selections,
                    weights=case.preference['weights'])
                if getattr(case, 'reviewer', None):
                    case.reviewer_session = case.reviewer.cookies['tire_local_session']
                    case.reviewer.close()
            finally:
                client.close()
            (output / 'started.json').write_text(json.dumps({
                'schema': 'r75-private-runtime@1', 'synthetic_only': True,
                'private_storage': storage.relative_to(ROOT).as_posix(),
                'sources_before': sources_before,
                'private_database_confirmed_before_imported_app_use': True,
                'credential_values_not_recorded': True,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'ready': True, 'port': port, 'event_id': state['event_id']}), flush=True)
            yield
        (output / 'stopped.json').write_text(json.dumps({
            'shutdown_complete': True, 'guard_counts': counts,
            'sources_before': sources_before, 'sources_after': source_hashes(),
            'sources_stable': sources_before == source_hashes(),
        }, indent=2), encoding='utf-8')

    app.router.lifespan_context = lifespan
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
                                         loop='asyncio', log_level='warning', access_log=False))

    @app.get('/fixture/state')
    def fixture_state():
        with app.state.database.sessions() as db:
            business_counts = {model.__tablename__: db.scalar(select(func.count()).select_from(model))
                               for model in [AuditEvent, TireTestRevision, TestSkuLinkRevision]}
        return {**state, 'counts': business_counts, 'guard_counts': dict(counts)}

    @app.post('/fixture/link-state')
    def fixture_link_state(payload: dict):
        # Private harness route, never registered in the production app factory.
        from test_test_sku_links import decision, operation, post
        action = payload.get('action')
        if action not in {'revoke', 'restore', 'review'} or type(payload.get('index')) is not int or payload['index'] not in {0, 1}:
            raise HTTPException(422, 'Invalid synthetic fixture operation')
        # Keep existing private actor credentials confined to helper-owned client cookies.
        from fastapi.testclient import TestClient
        client = TestClient(app, backend_options={'loop_factory': asyncio.SelectorEventLoop})
        client.cookies.set('tire_local_session', case.reviewer_session)
        try:
            index = payload['index']
            proposal = operation(case.proposals[index], case.links[index]['id'], action)
            request = decision(client, proposal)
            response = post(client, request)
            if response.status_code != 201:
                raise HTTPException(response.status_code, 'Synthetic fixture action rejected')
            result = response.json()
            case.links[index] = result['link']
            state['links'] = case.links
            state['request'] = request_body(case)
            return {'changed': True, 'action': action, 'link_id': result['link']['id']}
        finally:
            client.close()

    @app.post('/fixture/shutdown')
    def shutdown():
        server.should_exit = True
        return {'stopping': True}

    server.run()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--web-port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    serve(args.port, args.web_port, args.output)
