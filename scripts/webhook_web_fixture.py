"""R78 private HTTP fixture: synthetic notifications, controlled receiver only."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import sys
import threading
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def serve(port, web_port, output):
    output = output.resolve()
    assert output.is_relative_to((ROOT / '.artifacts').resolve()) and not output.exists()
    assert output.name.startswith('r78-')
    assert port != web_port and all(1024 <= p <= 65535 and p not in (3000, 8000) for p in (port, web_port))
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    output.mkdir(parents=True)
    storage = ROOT / '.artifacts' / ('r78-ws-' + uuid4().hex[:16])
    storage.mkdir()
    db_file = storage / 'p.db'
    db_url = 'sqlite:///' + db_file.as_posix()
    for name in list(os.environ):
        if (name.startswith(('TI_', 'TIRE_', 'OPENAI_', 'ANTHROPIC_', 'AZURE_OPENAI_'))
                or name == 'DATABASE_URL' or name.lower().endswith('_proxy')):
            del os.environ[name]
    targets = storage / 'targets.json'
    targets.write_text(json.dumps({'schema': 'webhook-targets@1', 'targets': [
        {'id': 'synthetic-receiver', 'title': '合成受控接收端',
         'url': 'https://receiver.example.com/tire-events', 'signing_key_env': 'TI_WEBHOOK_SIGNING_FIXTURE'},
        {'id': 'synthetic-missing-key', 'title': '未配置密钥的合成目标',
         'url': 'https://missing.example.com/tire-events', 'signing_key_env': 'TI_WEBHOOK_SIGNING_MISSING'},
    ]}), encoding='utf-8')
    os.environ.update(TIRE_DATABASE_URL=db_url, DATABASE_URL=db_url,
        TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_ENABLED='0',
        TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(storage / 'o'),
        TI_PARSER_BUNDLE_ROOT=str(storage / 'b'), TI_WEBHOOK_TARGETS_FILE=str(targets),
        TI_WEBHOOK_SIGNING_FIXTURE=secrets.token_hex(32),
        TIRE_CORS_ORIGINS=f'http://127.0.0.1:{web_port}')
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
    counts = {'external_network_attempts': 0, 'child_process_attempts': 0,
              'normal_database_attempts': 0, 'listener_binds': 0,
              'internal_socketpair_connections': 0}
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
            raise RuntimeError('r78_private_listener_only')
        if event == 'socket.connect':
            if pair is not None and pair['listener'] is not None and not pair['connected']:
                expected = pair['listener'].getsockname()
                if arguments[1] == expected and expected[0] in ('127.0.0.1', '::1') and expected[1] != 0:
                    pair['connected'] = True
                    counts['internal_socketpair_connections'] += 1
                    return
            counts['external_network_attempts'] += 1
            raise RuntimeError('r78_external_network_forbidden')
        if event in ('socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr',
                     'socket.getnameinfo', 'socket.sendto', 'socket.sendmsg'):
            counts['external_network_attempts'] += 1
            raise RuntimeError('r78_external_network_forbidden')
        if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn'):
            counts['child_process_attempts'] += 1
            raise RuntimeError('r78_child_process_forbidden')
        if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
            if not Path(str(arguments[0])).resolve().is_relative_to(storage):
                counts['normal_database_attempts'] += 1
                raise RuntimeError('r78_private_database_required')
    if sys.platform == 'win32':
        socket.socketpair = guarded_pair
    sys.addaudithook(audit)
    if sys.platform == 'win32':
        def native_win32_ver(release='', version='', csd='', ptype=''):
            native = sys.getwindowsversion()
            return str(native.major), f'{native.major}.{native.minor}.{native.build}', native.service_pack, ptype
        platform.win32_ver = native_win32_ver
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    def source_hashes():
        paths = set()
        for directory in ('apps/api/tire_api', 'apps/worker', 'apps/web/components',
                          'packages/api-client/src', 'packages/domain-types/src'):
            paths.update(p for p in (ROOT / directory).rglob('*')
                         if p.is_file() and p.suffix in ('.py', '.ts', '.tsx', '.css'))
        paths.update({Path(__file__), ROOT / 'apps/api/tests/test_core.py',
                      ROOT / 'apps/api/tests/admin_support.py',
                      ROOT / 'apps/api/tests/test_monitoring.py',
                      ROOT / 'apps/api/tests/test_interest_events.py'})
        return [{'path': p.relative_to(ROOT).as_posix(), 'bytes': p.stat().st_size,
                 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(paths)]
    before = source_hashes()
    import uvicorn
    from fastapi import Request
    from fastapi.testclient import TestClient
    from tire_api import main
    from tire_api.db import UserSession
    from admin_support import register_admin
    from test_core import FixtureRegistry, live
    from test_monitoring import create, changed
    from test_interest_events import watch
    assert main.app.state.database.engine.url.get_backend_name() == 'sqlite'
    assert Path(main.app.state.database.engine.url.database).resolve() == db_file.resolve()
    registry = FixtureRegistry()
    app = main.create_app(db_url, registry)
    original_lifespan = app.router.lifespan_context
    client, owner = None, None
    state = {'synthetic_only': True, 'normal_database_used': False,
             'real_provider_calls': 0, 'real_webhook_receivers': 0,
             'controlled_receiver_calls': 0, 'signature_checks': 0, 'emissions': 0}

    class ControlledReceiver:
        def __init__(self, status):
            self.status = status

        async def send(self, target, raw_body, headers):
            # Independent receiver-side check of production-generated bytes.
            stamp = headers['X-Tire-Webhook-Timestamp']
            identifier = headers['X-Tire-Webhook-Id']
            number = headers['X-Tire-Webhook-Attempt']
            prefix = f'{stamp}.{identifier}.{number}.'.encode('ascii')
            key = bytes.fromhex(os.environ[target.signing_key_env])
            expected = 'v1=' + hmac.new(key, prefix + raw_body, hashlib.sha256).hexdigest()
            body = json.loads(raw_body)
            assert hmac.compare_digest(expected, headers['X-Tire-Webhook-Signature'])
            assert body['delivery_id'] == identifier and body['data_scope'] == 'notification_reference_only'
            assert raw_body == json.dumps(body, sort_keys=True, ensure_ascii=False,
                separators=(',', ':')).encode('utf-8')
            state['signature_checks'] += 1
            state['controlled_receiver_calls'] += 1
            return {'http_status': self.status, 'error_code': None, 'retry_after': None}

    @asynccontextmanager
    async def lifespan(application):
        nonlocal client, owner
        async with original_lifespan(application):
            client = TestClient(application, backend_options={'loop_factory': asyncio.SelectorEventLoop})
            try:
                owner = register_admin(client, username='synthetic_owner')['user']
                assert live(client).status_code == 200
                assert create(client).status_code == 201
                watch(client)
                (output / 'started.json').write_text(json.dumps({
                    'schema': 'r78-private-runtime@1', 'synthetic_only': True,
                    'sources_before': before, 'normal_database_used': False,
                    'credential_values_not_recorded': True}, indent=2), encoding='utf-8')
                print(json.dumps({'ready': True, 'port': port}), flush=True)
                yield
            finally:
                client.close()
        after = source_hashes()
        (output / 'stopped.json').write_text(json.dumps({
            'schema': 'r78-private-runtime-stop@1', 'shutdown_complete': True,
            'sources_before': before, 'sources_after': after,
            'sources_stable': before == after, 'guard_counts': counts,
            **state}, indent=2), encoding='utf-8')
    app.router.lifespan_context = lifespan
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
        loop='asyncio', log_level='warning', access_log=False))

    @app.post('/fixture/session')
    def fixture_session(request: Request):
        with app.state.database.sessions() as db:
            row = db.get(UserSession, request.state.session_id)
            row.user_id = owner['id']
            db.commit()
        return {'authenticated': True, 'synthetic_only': True, 'login_acceptance': False}

    @app.post('/fixture/emit')
    def emit():
        state['emissions'] += 1
        changed(registry, 400 + state['emissions'])
        response = live(client)
        assert response.status_code == 200
        return {'emissions': state['emissions'], 'synthetic_only': True}

    @app.get('/fixture/state')
    def fixture_state():
        return {**state, 'guard_counts': counts}

    @app.post('/fixture/dispatch')
    async def dispatch(status: int = 400):
        assert status in (204, 400, 503)
        from tire_api.webhook_delivery import run_webhook_cycle
        return await run_webhook_cycle(app.state.database, max_jobs=1,
            adapter=ControlledReceiver(status))

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
