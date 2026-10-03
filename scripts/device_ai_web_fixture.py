"""Owned private fixture for the round50 device-AI web host QA.

Real tire_api app on an isolated temporary SQLite DB + filesystem object store
(TI_* env isolation, audit hook forbids subprocess/external network/normal
databases). Seeds one actor-owned OfflinePack built from the sealed producer
sample (.artifacts/device-ai50/projection-vectors-a/inputs/nonempty-pack.json,
owner_scope_id replaced byte-for-byte with the session-derived digest). The
synthetic provider streams an uncertainty-only grounded answer (device packs
render no fact text in this wave); OpenAI is never contacted.

Run: uv run --project apps/api --extra dev python scripts/device_ai_web_fixture.py \
        --serve --port 8003 --output <artifacts dir>
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import closing
from datetime import timedelta
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

from fastapi import Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from golden_acceptance import save  # noqa: E402

SAMPLES = ROOT / '.artifacts/device-ai50/projection-vectors-a/inputs'
MODES = {'complete', 'held', 'provider_error', 'refusal'}


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
    private = Path(tempfile.mkdtemp(prefix='tire-device-ai-web-qa-')).resolve()
    database_path = private / 'private.sqlite'
    checkpoint = output / 'private-checkpoint.sqlite'
    app = None
    counters = {'provider_calls': 0, 'external_network_attempts': 0, 'real_parser_children': 0}
    runtime = {'mode': 'complete', 'release': None, 'holding': False, 'active_provider': False}
    final = {'status': 'running', 'normal_database_used': False, 'real_openai_calls': 0}
    try:
        os.environ.update(TIRE_DATABASE_URL='sqlite:///' + database_path.as_posix(),
            DATABASE_URL='sqlite:///' + database_path.as_posix(), TI_AI_ENABLED='1', TI_EMBEDDINGS_ENABLED='0',
            TI_OPENAI_MODEL='synthetic-device-ai-fixture', TI_OPENAI_API_KEY='synthetic-key-never-live',
            TI_AI_ALLOW_PRIVATE='1', TI_AI_DAILY_REQUEST_LIMIT='100', TI_AI_DAILY_TOKEN_LIMIT='10000000',
            TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(private / 'objects'),
            TI_PARSER_BUNDLE_ROOT=str(private / 'bundles'), TI_DISABLED_SOURCES='', TI_OBSERVABILITY_LOGS='0',
            # The QA web dev server proxies /api/* here with the browser Origin
            # header preserved; the app middleware rejects unknown origins with
            # 403 (不允许此请求来源), so the QA origin must be allow-listed.
            TIRE_CORS_ORIGINS='http://127.0.0.1:3003,http://localhost:3003')
        sys.path[:0] = [str(ROOT), str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]

        # Pre-warm the uname cache BEFORE the audit hook: on Windows,
        # platform.machine()/uname() may lazily shell out to `cmd /c ver`
        # (subprocess) on first call (e.g. from sqlalchemy's import-time
        # platform probe). That fallback is environment-dependent flakiness,
        # not a parser child — populating the cache first keeps the audit
        # fence focused on real subprocess spawns.
        import platform as _platform
        _platform.uname()

        def audit(event, arguments):
            if event == 'subprocess.Popen':
                counters['real_parser_children'] += 1
                raise RuntimeError('Parser children forbidden in device-AI web fixture')
            if event in {'socket.connect', 'socket.getaddrinfo'}:
                address = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
                if address not in {'127.0.0.1', '::1', 'localhost'}:
                    counters['external_network_attempts'] += 1
                    raise RuntimeError('External networking forbidden in device-AI web fixture')
            if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
                path = Path(str(arguments[0])).resolve()
                require(path.is_relative_to(private) or path == checkpoint, 'private_database_required')
        sys.addaudithook(audit)

        import uvicorn
        from sqlalchemy import text
        from tire_api.ai_gateway import extract_response
        from tire_api.ai_stream_parser import parse_response_stream
        from tire_api.db import EvidenceObject, TireVariant, UserSession, utcnow
        from tire_api.main import create_app
        from tire_api.offline_models import OfflinePack, OfflinePackPlan
        from test_core import FixtureRegistry

        class Registry(FixtureRegistry):
            supports_parser_deployments = False

            def sources(self):
                return []  # Device-AI prepare/submit never touch source adapters.

        def seeded_pack(owner_session: str):
            """Session-owned copy of the sealed producer sample (byte-level
            owner_scope replacement keeps every number lexeme identical)."""
            original = (SAMPLES / 'nonempty-pack.json').read_bytes()
            descriptor = json.loads((SAMPLES / 'nonempty-descriptor.json').read_text(encoding='utf-8'))
            scope = hashlib.sha256(json.dumps({'namespace': 'offline-owner-scope@1', 'session': owner_session},
                                              separators=(',', ':')).encode('utf-8')).hexdigest()
            sample_scope = descriptor['owner_scope_id'].encode('ascii')
            require(len(sample_scope) == 64 and original.count(sample_scope) == 1, 'owner_scope_single_occurrence')
            raw = original.replace(sample_scope, scope.encode('ascii'))
            sha = hashlib.sha256(raw).hexdigest()
            require(len(raw) == len(original), 'byte_length_preserved')
            descriptor.update(sha256=sha, byte_count=len(raw), owner_scope_id=scope)
            return raw, descriptor

        def response_value(response_id, message_id, answer_text):
            return {'id': response_id, 'object': 'response', 'status': 'completed',
                'model': 'synthetic-device-ai-fixture',
                'output': [{'id': message_id, 'type': 'message', 'role': 'assistant', 'status': 'completed',
                    'content': [{'type': 'output_text', 'text': answer_text, 'annotations': []}]}],
                'usage': {'input_tokens': 400, 'output_tokens': 60, 'total_tokens': 460}}

        class Model:
            async def generate(self, config, body):
                counters['provider_calls'] += 1
                encoded = json.dumps({'claims': [], 'uncertainty': '合成说明：设备历史投影本波不渲染事实文本。'},
                                     ensure_ascii=False, separators=(',', ':'))
                return extract_response(response_value('resp_synthetic_sync', 'msg_synthetic_sync', encoded))

            async def stream(self, config, body, on_text):
                require(not runtime['active_provider'], 'provider_calls_overlapped')
                counters['provider_calls'] += 1
                runtime['active_provider'] = True
                mode = runtime['mode']
                response_id = 'resp_synthetic_' + str(counters['provider_calls'])
                message_id = 'msg_synthetic_' + str(counters['provider_calls'])
                answer = json.dumps({'claims': [], 'uncertainty': '合成不确定性：设备历史观察只有回执与候选，'
                    '不构成实时参数或安全适配结论。<script>window.deviceAiCanary=1</script>'},
                    ensure_ascii=False, separators=(',', ':'))
                if mode == 'provider_error':
                    from tire_api.ai_gateway import GatewayError
                    runtime['active_provider'] = False
                    raise GatewayError('ai_provider_timeout')
                sequence = 0

                def event(kind, **payload):
                    nonlocal sequence
                    value = {'type': kind, 'sequence_number': sequence, **payload}
                    sequence += 1
                    wire = 'event: ' + kind + '\r\ndata: ' + json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\r\n\r\n'
                    return wire.encode('utf-8')

                async def frames():
                    yield event('response.created', response={'id': response_id, 'status': 'in_progress', 'output': []})
                    yield event('response.output_item.added', output_index=0,
                        item={'id': message_id, 'type': 'message', 'role': 'assistant', 'status': 'in_progress', 'content': []})
                    if mode == 'refusal':
                        refusal = 'PRIVATE REFUSAL MUST NOT BE DISPLAYED'
                        yield event('response.content_part.added', item_id=message_id, output_index=0, content_index=0,
                            part={'type': 'refusal', 'refusal': ''})
                        yield event('response.refusal.delta', item_id=message_id, output_index=0, content_index=0,
                            delta=refusal)
                        yield event('response.refusal.done', item_id=message_id, output_index=0, content_index=0,
                            refusal=refusal)
                        part = {'type': 'refusal', 'refusal': refusal}
                        value = response_value(response_id, message_id, '')
                        value['output'][0]['content'] = [part]
                        yield event('response.output_item.done', output_index=0, item=value['output'][0])
                        yield event('response.completed', response=value)
                        return
                    yield event('response.content_part.added', item_id=message_id, output_index=0, content_index=0,
                        part={'type': 'output_text', 'text': '', 'annotations': []})
                    yield event('response.output_text.delta', item_id=message_id, output_index=0, content_index=0,
                        delta=answer[:len(answer) // 2], logprobs=[])
                    if mode == 'held':
                        runtime['holding'] = True
                        try:
                            await asyncio.wait_for(runtime['release'].wait(), timeout=60)
                        finally:
                            runtime['holding'] = False
                    yield event('response.output_text.delta', item_id=message_id, output_index=0, content_index=0,
                        delta=answer[len(answer) // 2:], logprobs=[])
                    yield event('response.output_text.done', item_id=message_id, output_index=0, content_index=0,
                        text=answer, logprobs=[])
                    yield event('response.content_part.done', item_id=message_id, output_index=0, content_index=0,
                        part={'type': 'output_text', 'text': answer, 'annotations': []})
                    yield event('response.output_item.done', output_index=0,
                        item=response_value(response_id, message_id, answer)['output'][0])
                    yield event('response.completed', response=response_value(response_id, message_id, answer))

                async def chunks():
                    async for frame in frames():
                        offset = 0
                        while offset < len(frame):
                            chunk = frame[offset:offset + 23]
                            offset += len(chunk)
                            yield chunk
                            await asyncio.sleep(0)
                try:
                    return await parse_response_stream(chunks(), on_text)
                finally:
                    runtime['active_provider'] = False

        app = create_app('sqlite:///' + database_path.as_posix(), Registry())
        app.state.ai_adapter = Model()
        database = app.state.database
        database.initialize()
        owner, other = str(uuid4()), str(uuid4())
        with database.sessions() as db:
            for session_id in (owner, other):
                db.add(UserSession(id=session_id, expires_at=utcnow() + timedelta(hours=3)))
            db.commit()

        raw, descriptor = seeded_pack(owner)
        envelope = json.loads(raw)
        tire_member = next(member for member in envelope['members'] if member['reference']['kind'] == 'tire')
        variant_id = tire_member['reference']['variant_id']
        frozen_identity = tire_member['payload']['identity_contract']
        identity = frozen_identity['current_identity']
        with database.sessions() as db:
            store = database.object_store
            assert store.put(raw) == descriptor['sha256']
            db.add(EvidenceObject(raw_hash=descriptor['sha256'], byte_count=len(raw)))
            db.add(TireVariant(id=variant_id, identity_key=descriptor['sha256'], identity=dict(identity),
                               identity_status=frozen_identity['identity_status']))
            db.flush()
            from tire_api.identity_contract import _new_binding
            db.add(_new_binding(variant_id=variant_id, key=frozen_identity['current_key'], identity=identity,
                status=frozen_identity['identity_status'], origin='fixture_binding', proof={'fixture': True}))
            now = utcnow()
            db.add(OfflinePackPlan(id=descriptor['plan_id'], package_id=descriptor['id'],
                actor_session_id=owner, fingerprint=descriptor['plan_fingerprint'], preview={},
                content_hash=descriptor['sha256'], byte_count=len(raw),
                created_at=now, expires_at=now + timedelta(minutes=30)))
            db.flush()
            db.add(OfflinePack(id=descriptor['id'], plan_id=descriptor['plan_id'], actor_session_id=owner,
                idempotency_key=str(uuid4()), request_hash='a' * 64, content_hash=descriptor['sha256'],
                byte_count=len(raw), descriptor=descriptor))
            db.commit()

        def state():
            with database.sessions() as db:
                counts = {name: db.execute(text('SELECT COUNT(*) FROM ' + name)).scalar_one() for name in (
                    'local_sessions', 'offline_pack_plans', 'offline_packs', 'device_ai_preparations', 'device_ai_consent_claims',
                    'ai_evidence_packs', 'ai_requests', 'ai_completions', 'ai_stream_executions', 'ai_stream_events')}
                owner_row = db.execute(text('SELECT actor_session_id FROM offline_packs LIMIT 1')).first()
            return {'scope': 'synthetic_device_ai_web_wire', 'normal_database_used': False, 'real_openai_calls': 0,
                'process_id': os.getpid(), 'mode': runtime['mode'], 'holding': runtime['holding'],
                'active_provider': runtime['active_provider'], 'counts': counts,
                'package': {'id': descriptor['id'], 'sha256': descriptor['sha256'], 'byte_count': descriptor['byte_count'],
                            'owner_scope_id': descriptor['owner_scope_id'], 'schema': 'offline-pack@2',
                            'plan_fingerprint': descriptor['plan_fingerprint']},
                'owner_session': owner, 'pack_actor': owner_row[0] if owner_row else None,
                **counters}

        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, log_level='warning'))

        @app.get('/fixture/entry')
        def entry(request: Request, actor: str = 'owner'):
            # Callers must establish any middleware session first (e.g. GET
            # /fixture/state): on a cookie-less first request the session
            # middleware appends its own Set-Cookie AFTER this route's, the
            # last header would win, and the actor cookie would be dropped.
            require(actor in {'owner', 'other'}, 'unknown_actor')
            require(request.cookies.get('tire_local_session') is not None, 'establish_a_session_first')
            result = JSONResponse({'private_synthetic_session': actor, 'package': descriptor['id']})
            result.set_cookie('tire_local_session', owner if actor == 'owner' else other,
                              httponly=True, samesite='strict')
            return result

        @app.get('/fixture/state')
        def get_state():
            return state()

        @app.post('/fixture/config')
        async def configure(request: Request):
            body = await request.json()
            require(body.get('mode') in MODES and not runtime['active_provider'], 'invalid_mode_or_active_provider')
            runtime.update(mode=body['mode'], release=asyncio.Event() if body['mode'] == 'held' else None)
            return {'mode': runtime['mode']}

        @app.post('/fixture/release')
        def release():
            if runtime['release'] is not None:
                runtime['release'].set()
            return {'released': True}

        @app.post('/fixture/shutdown')
        def shutdown():
            if runtime['release'] is not None:
                runtime['release'].set()
            server.should_exit = True
            save(output / 'fixture-before-shutdown.json', state())
            return {'shutdown_requested': True}

        save(output / 'fixture.json', state())
        print(json.dumps({'ready': True, 'port': port, 'output': str(output), 'package': descriptor['id']}), flush=True)
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
            if (private / 'objects').exists():
                shutil.copytree(private / 'objects', output / 'objects-checkpoint')
        finally:
            require(private.parent == Path(tempfile.gettempdir()).resolve() and
                private.name.startswith('tire-device-ai-web-qa-') and not private.is_symlink(), 'unsafe_cleanup_target')
            try:
                shutil.rmtree(private)
            finally:
                final.update(private_storage_removed=not private.exists(), **counters)
                save(output / 'fixture-final.json', final)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', required=True)
    parser.add_argument('--port', type=int, default=8003)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    serve(arguments.port, arguments.output)
