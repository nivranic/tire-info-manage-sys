"""R77 private runtime fixture. Synthetic R69 catalogs and controlled Provider only."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]


def serve(port, web_port, output):
    output = output.resolve()
    assert output.is_relative_to((ROOT / '.artifacts').resolve()) and not output.exists()
    assert port != web_port and all(1024 <= value <= 65535 and value not in (3000, 8000) for value in (port, web_port))
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    output.mkdir(parents=True)
    storage = output / 's'
    storage.mkdir()
    db_file = storage / 'p.db'
    db_url = 'sqlite:///' + db_file.as_posix()
    for name in list(os.environ):
        if (name.startswith(('TI_', 'TIRE_', 'OPENAI_', 'ANTHROPIC_', 'AZURE_OPENAI_'))
                or name == 'DATABASE_URL' or name.lower().endswith('_proxy')):
            del os.environ[name]
    os.environ.update(TIRE_DATABASE_URL=db_url, DATABASE_URL=db_url,
        TI_AI_ENABLED='1', TI_AI_PROVIDER='openai_responses', TI_OPENAI_MODEL='synthetic-r77-controlled',
        TI_OPENAI_API_KEY=secrets.token_urlsafe(18), TI_AI_ALLOW_PRIVATE='1',
        TI_AI_DAILY_TOKEN_LIMIT='1000000', TI_AI_DAILY_REQUEST_LIMIT='50',
        TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_ENABLED='0',
        TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(storage / 'o'),
        TI_PARSER_BUNDLE_ROOT=str(storage / 'b'),
        TIRE_CORS_ORIGINS=f'http://127.0.0.1:{web_port}')
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
    paths = [path for directory in ('apps/api/tire_api', 'apps/web/components',
        'packages/api-client/src', 'packages/domain-types/src') for path in (ROOT / directory).rglob('*')
        if path.is_file() and path.suffix in ('.py', '.ts', '.tsx', '.css')]
    paths += [ROOT / 'apps/api/tests/candidate_ai_support.py',
        ROOT / 'apps/api/tests/fixtures/candidate_ai/SYNTHETIC-LICENSE.txt', Path(__file__)]
    def source_hashes():
        return [{'path': path.relative_to(ROOT).as_posix(), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(paths)]
    before = source_hashes()
    counts = {'external_network_attempts': 0, 'child_process_attempts': 0, 'normal_database_attempts': 0,
        'listener_binds': 0, 'internal_socketpair_connections': 0}
    pair_state, original_pair = threading.local(), socket.socketpair
    def guarded_pair(*args, **kwargs):
        assert getattr(pair_state, 'current', None) is None
        pair_state.current = {'listener': None, 'connected': False}
        try:
            return original_pair(*args, **kwargs)
        finally:
            pair_state.current = None
    def audit(event, arguments):
        pair = getattr(pair_state, 'current', None)
        if event == 'socket.bind':
            address = arguments[1]
            if pair is not None and pair['listener'] is None and address in (('127.0.0.1', 0), ('::1', 0)):
                pair['listener'] = arguments[0]
                return
            if address == ('127.0.0.1', port) and counts['listener_binds'] == 0:
                counts['listener_binds'] += 1
                return
            counts['external_network_attempts'] += 1
            raise RuntimeError('r77_private_listener_only')
        if event == 'socket.connect':
            if pair is not None and pair['listener'] is not None and not pair['connected']:
                expected = pair['listener'].getsockname()
                if arguments[1] == expected and expected[0] in ('127.0.0.1', '::1') and expected[1] != 0:
                    pair['connected'] = True
                    counts['internal_socketpair_connections'] += 1
                    return
            counts['external_network_attempts'] += 1
            raise RuntimeError('r77_external_network_forbidden')
        if event in ('socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr', 'socket.getnameinfo', 'socket.sendto', 'socket.sendmsg'):
            counts['external_network_attempts'] += 1
            raise RuntimeError('r77_external_network_forbidden')
        if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn'):
            counts['child_process_attempts'] += 1
            raise RuntimeError('r77_child_process_forbidden')
        if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
            if not Path(str(arguments[0])).resolve().is_relative_to(storage):
                counts['normal_database_attempts'] += 1
                raise RuntimeError('r77_private_database_required')
    if sys.platform == 'win32':
        socket.socketpair = guarded_pair
        def native_win32_ver(release='', version='', csd='', ptype=''):
            native = sys.getwindowsversion()
            return str(native.major), f'{native.major}.{native.minor}.{native.build}', native.service_pack, ptype
        platform.win32_ver = native_win32_ver
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.addaudithook(audit)
    import uvicorn
    from fastapi import Request
    from fastapi.testclient import TestClient
    from tire_api import main
    from candidate_ai_support import NoNetworkRegistry, seed_candidate_ai, grant_payload
    assert main.app.state.database.engine.url.get_backend_name() == 'sqlite'
    assert Path(main.app.state.database.engine.url.database).resolve() == db_file.resolve()
    app = main.create_app(db_url, NoNetworkRegistry())
    original_lifespan = app.router.lifespan_context
    state = {'synthetic_only': True, 'normal_database_used': False, 'provider_mode': 'controlled_adapter'}
    case, client = None, None
    class SelectionAdapter:
        def __init__(self):
            self.calls = []
        async def generate(self, config, body):
            payload = json.loads(body['input'][1]['content'])['untrusted_evidence_pack']
            first = payload['candidates'][0]
            result = {'decision': 'choose', 'selections': [{'variant_id': first['variant_id'],
                'reason_ids': [first['reasons'][0]['id']]}], 'uncertainty_codes': []}
            self.calls.append({'body_hash': hashlib.sha256(json.dumps(body, sort_keys=True,
                ensure_ascii=False, separators=(',', ':')).encode()).hexdigest(),
                'variant_id': first['variant_id'], 'purpose': payload['purpose']})
            return {'text': json.dumps(result), 'error': None,
                'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
                'provider_response_id': 'r77-controlled'}
    adapter = SelectionAdapter()
    @asynccontextmanager
    async def lifespan(application):
        nonlocal case, client
        async with original_lifespan(application):
            client = TestClient(application, backend_options={'loop_factory': asyncio.SelectorEventLoop})
            try:
                case = seed_candidate_ai(client)
                app.state.ai_adapter = adapter
                state.update(selection=case.selection, variants=case.variants, preference=case.preference)
                declaration = grant_payload({'id': '0' * 64})
                state['synthetic_rights_declaration'] = {key: value for key, value in declaration.items()
                    if key not in ('dependency_id', 'expected_revision', 'action')}
                record = {'schema': 'r77-private-runtime@1', 'synthetic_only': True,
                    'sources_before': before, 'normal_database_used': False,
                    'credential_values_not_recorded': True}
                (output / 'started.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
                print(json.dumps({'ready': True, 'port': port}), flush=True)
                yield
            finally:
                client.close()
        after = source_hashes()
        (output / 'stopped.json').write_text(json.dumps({'schema': 'r77-private-runtime-stop@1',
            'shutdown_complete': True, 'sources_before': before, 'sources_after': after,
            'sources_stable': before == after, 'guard_counts': counts, 'controlled_provider_calls': adapter.calls,
            'real_provider_calls': 0, 'normal_database_used': False}, indent=2), encoding='utf-8')
    app.router.lifespan_context = lifespan
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, loop='asyncio',
        log_level='warning', access_log=False))
    @app.post('/fixture/session')
    def fixture_session(request: Request):
        # Test-only account binding; no credential or cookie value leaves memory.
        # This route is absent from the product factory and does not test login.
        from tire_api.db import UserSession
        with app.state.database.sessions() as db:
            row = db.get(UserSession, request.state.session_id)
            row.user_id = case.user['id']
            db.commit()
        return {'authenticated': True, 'synthetic_only': True, 'login_acceptance': False}
    @app.get('/fixture/state')
    def fixture_state():
        return {**state, 'provider_calls': len(adapter.calls), 'guard_counts': counts}
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
