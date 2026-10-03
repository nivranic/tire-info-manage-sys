"""Owned private HTTP fixture: real Responses wire parser, synthetic provider bytes only."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
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

from golden_acceptance import save

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'michelin-us'
MODES = {'complete', 'held', 'grounding_failure', 'incomplete', 'truncated',
         'terminal_mismatch', 'uncertainty_only', 'refusal'}


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
    private = Path(tempfile.mkdtemp(prefix='tire-ai-stream-qa-')).resolve()
    database_path = private / 'private.sqlite'
    checkpoint = output / 'private-checkpoint.sqlite'
    app = None
    counters = {'source_calls': 0, 'provider_calls': 0, 'sync_provider_calls': 0,
                'wire_chunks': 0, 'external_network_attempts': 0, 'real_parser_children': 0}
    runtime = {'mode': 'complete', 'holding': False, 'release': None, 'active_provider': False,
               'wire_terminals': 0, 'sealed': None}
    final = {'status': 'running', 'normal_database_used': False, 'real_openai_calls': 0}
    try:
        os.environ.update(TIRE_DATABASE_URL='sqlite:///' + database_path.as_posix(),
            DATABASE_URL='sqlite:///' + database_path.as_posix(), TI_AI_ENABLED='1', TI_EMBEDDINGS_ENABLED='0',
            TI_OPENAI_MODEL='synthetic-stream-fixture', TI_OPENAI_API_KEY='synthetic-key-never-live',
            TI_AI_ALLOW_PRIVATE='1', TI_AI_DAILY_REQUEST_LIMIT='100', TI_AI_DAILY_TOKEN_LIMIT='10000000',
            TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(private / 'objects'),
            TI_PARSER_BUNDLE_ROOT=str(private / 'bundles'), TI_DISABLED_SOURCES='', TI_OBSERVABILITY_LOGS='0')
        sys.path[:0] = [str(ROOT), str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]

        def audit(event, arguments):
            if event == 'subprocess.Popen':
                counters['real_parser_children'] += 1
                raise RuntimeError('Parser children forbidden in synthetic AI stream fixture')
            if event in {'socket.connect', 'socket.getaddrinfo'}:
                address = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
                if address not in {'127.0.0.1', '::1', 'localhost'}:
                    counters['external_network_attempts'] += 1
                    raise RuntimeError('External networking forbidden in synthetic AI stream fixture')
            if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
                path = Path(str(arguments[0])).resolve()
                require(path.is_relative_to(private) or path == checkpoint, 'private_database_required')
        sys.addaudithook(audit)

        import uvicorn
        from fastapi.responses import JSONResponse
        from sqlalchemy import text
        from tire_api.adapters import registry as installed_registry
        from tire_api.ai_gateway import extract_response
        from tire_api.ai_stream_parser import parse_response_stream
        from tire_api.db import UserSession, utcnow
        from tire_api.domain import digest
        from tire_api.main import create_app
        from test_core import FixtureRegistry, success
        from test_field_evidence import known_variant

        class Registry(FixtureRegistry):
            SPECS = installed_registry.SPECS
            PENDING_SOURCES = installed_registry.PENDING_SOURCES
            supports_parser_deployments = False

            def sources(self):
                rows = deepcopy(installed_registry.sources())
                for row in rows:
                    if row['id'] == SOURCE:
                        row.update(name='合成 AI 流验收来源 · 非真实轮胎',
                            description='私有合成数据，仅验证内容流和证据边界',
                            supported_models=['Fixture Tire'], default_model='Fixture Tire')
                return rows

            async def fetch(self, source_id, query, cached=None, *, on_observation=None):
                require(source_id == SOURCE, 'unexpected_source')
                counters['source_calls'] += 1
                row = known_variant(utqg_treadwear=300, evidence_spans={
                    'manufacturer_product_code': '$.sku.manufacturer_product_code',
                    'facts.product_code_type': '$.sku.facts.product_code_type',
                    'facts.utqg_treadwear': '$.sku.facts.utqg_treadwear'})
                value = success(json.dumps({'synthetic_fixture_only': True, 'sku': row}, ensure_ascii=False), [row])
                if on_observation:
                    on_observation(value)
                return value

        def response_value(response_id, message_id, answer_text, status='completed'):
            return {'id': response_id, 'object': 'response', 'status': status,
                'model': 'synthetic-stream-fixture',
                'output': [{'id': message_id, 'type': 'message', 'role': 'assistant', 'status': status,
                    'content': [{'type': 'output_text', 'text': answer_text, 'annotations': []}]}],
                'usage': {'input_tokens': 500, 'output_tokens': 100, 'total_tokens': 600}}

        def output_text(body, mode):
            context = json.loads(body['input'][1]['content'])['untrusted_evidence_pack']
            fact = context['facts'][0]
            claim = {'type': 'fact', 'text': '', 'fact_ids': [fact['id']], 'evidence_ids': [fact['evidence_id']]}
            inference = {**claim, 'type': 'inference',
                'text': '合成流式推断 🛞：只验证历史证据。<script>window.aiStreamCanary=1</script>'}
            if mode == 'grounding_failure':
                inference['fact_ids'] = ['not-in-evidence-pack']
            claims = [] if mode == 'uncertainty_only' else [claim, inference]
            answer = {'claims': claims, 'uncertainty': '合成不确定性：不代表真实模型结论或当前安全适配。'}
            encoded = json.dumps(answer, ensure_ascii=False, separators=(',', ':'))
            split = len('{"claims":[') + len(json.dumps(claim, ensure_ascii=False, separators=(',', ':')))
            return encoded, split if claims else len(encoded) - 1

        class Model:
            async def generate(self, config, body):
                counters['sync_provider_calls'] += 1
                encoded, _ = output_text(body, 'complete')
                return extract_response(response_value('resp_synthetic_sync', 'msg_synthetic_sync', encoded))

            async def stream(self, config, body, on_text):
                require(not runtime['active_provider'], 'provider_calls_overlapped')
                require(body.get('stream') is True and body.get('store') is False, 'stream_contract_required')
                counters['provider_calls'] += 1
                runtime['active_provider'] = True
                mode = runtime['mode']
                response_id = 'resp_synthetic_' + str(counters['provider_calls'])
                message_id = 'msg_synthetic_' + str(counters['provider_calls'])
                encoded, split = output_text(body, mode)
                sequence = 0

                def event(kind, **payload):
                    nonlocal sequence
                    value = {'type': kind, 'sequence_number': sequence, **payload}
                    sequence += 1
                    wire = 'event: ' + kind + '\r\ndata: ' + json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\r\n\r\n'
                    return wire.encode('utf-8')

                async def frames():
                    yield event('response.created', response={'id': response_id, 'status': 'in_progress', 'output': []})
                    yield event('response.in_progress', response={'id': response_id, 'status': 'in_progress', 'output': []})
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
                        yield event('response.content_part.done', item_id=message_id, output_index=0, content_index=0,
                            part=part)
                        value = response_value(response_id, message_id, '')
                        value['output'][0]['content'] = [part]
                        yield event('response.output_item.done', output_index=0, item=value['output'][0])
                        runtime['wire_terminals'] += 1
                        yield event('response.completed', response=value)
                        return
                    yield event('response.content_part.added', item_id=message_id, output_index=0, content_index=0,
                        part={'type': 'output_text', 'text': '', 'annotations': []})
                    yield event('response.output_text.delta', item_id=message_id, output_index=0, content_index=0,
                        delta=encoded[:split], logprobs=[])
                    if mode == 'held':
                        runtime['holding'] = True
                        try:
                            await asyncio.wait_for(runtime['release'].wait(), timeout=45)
                        finally:
                            runtime['holding'] = False
                    if mode == 'truncated':
                        return
                    yield event('response.output_text.delta', item_id=message_id, output_index=0, content_index=0,
                        delta=encoded[split:], logprobs=[])
                    if mode == 'incomplete':
                        value = response_value(response_id, message_id, encoded, status='incomplete')
                        value['incomplete_details'] = {'reason': 'max_output_tokens'}
                        runtime['wire_terminals'] += 1
                        yield event('response.incomplete', response=value)
                        return
                    yield event('response.output_text.done', item_id=message_id, output_index=0, content_index=0,
                        text=encoded, logprobs=[])
                    yield event('response.content_part.done', item_id=message_id, output_index=0, content_index=0,
                        part={'type': 'output_text', 'text': encoded, 'annotations': []})
                    value = response_value(response_id, message_id, encoded)
                    yield event('response.output_item.done', output_index=0, item=value['output'][0])
                    if mode == 'terminal_mismatch':
                        value['output'][0]['content'][0]['text'] = encoded.replace('合成不确定性', '不同终态正文')
                    runtime['wire_terminals'] += 1
                    yield event('response.completed', response=value)

                async def chunks():
                    async for frame in frames():
                        offset, sizes = 0, (1, 2, 7, 17, 53)
                        while offset < len(frame):
                            size = sizes[counters['wire_chunks'] % len(sizes)]
                            chunk = frame[offset:offset + size]
                            offset += len(chunk)
                            counters['wire_chunks'] += 1
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
                db.add(UserSession(id=session_id, expires_at=utcnow() + timedelta(hours=2)))
            db.commit()

        def evidence_fingerprint(db):
            return {name: sorted(digest({key: {'bytes': bytes(value).hex()} if isinstance(value, (bytes, memoryview)) else value
                for key, value in dict(row).items()}) for row in db.execute(text('SELECT * FROM ' + name)).mappings())
                for name in ('snapshots', 'fact_versions', 'raw_captures')}

        def state():
            with database.sessions() as db:
                names = ('tire_variants', 'snapshots', 'fact_versions', 'query_runs', 'raw_captures',
                    'ai_evidence_packs', 'ai_requests', 'ai_completions', 'ai_stream_executions', 'ai_stream_events',
                    'research_reports', 'research_report_revisions', 'report_exports', 'embedding_requests')
                counts = {name: db.execute(text('SELECT COUNT(*) FROM ' + name)).scalar_one() for name in names}
                evidence = evidence_fingerprint(db)
            return {'scope': 'synthetic_ai_stream_wire', 'normal_database_used': False, 'real_openai_calls': 0,
                'process_id': os.getpid(), 'mode': runtime['mode'], 'holding': runtime['holding'],
                'active_provider': runtime['active_provider'], 'wire_terminals': runtime['wire_terminals'],
                'counts': counts, **counters,
                'sealed_evidence_unchanged': runtime['sealed'] is None or runtime['sealed'] == evidence}

        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, log_level='warning'))

        @app.get('/fixture/entry')
        def entry(actor: str = 'owner'):
            require(actor in {'owner', 'other'}, 'unknown_actor')
            result = JSONResponse({'private_synthetic_session': actor})
            result.set_cookie('tire_local_session', owner if actor == 'owner' else other, httponly=True, samesite='strict')
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

        @app.post('/fixture/seal')
        async def seal():
            with database.sessions() as db:
                runtime['sealed'] = evidence_fingerprint(db)
            return {'sealed': True}

        @app.post('/fixture/release')
        async def release():
            if runtime['release'] is not None:
                runtime['release'].set()
            return {'released': True}

        @app.post('/fixture/shutdown')
        async def shutdown():
            if runtime['release'] is not None:
                runtime['release'].set()
            server.should_exit = True
            save(output / 'fixture-before-shutdown.json', state())
            return {'shutdown_requested': True}

        save(output / 'fixture.json', {**state(), 'private_storage': str(private)})
        print(json.dumps({'ready': True, 'port': port, 'output': str(output)}), flush=True)
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
            for name in ('objects', 'bundles'):
                if (private / name).exists():
                    shutil.copytree(private / name, output / (name + '-checkpoint'))
        finally:
            require(private.parent == Path(tempfile.gettempdir()).resolve() and
                private.name.startswith('tire-ai-stream-qa-') and not private.is_symlink(), 'unsafe_cleanup_target')
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
