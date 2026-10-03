"""Private recall research fixture; source records and model output are explicitly synthetic."""
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
CAMPAIGN = '23T001000'
SOURCE_MODES = {'baseline', 'compact', 'same_content_new_raw', 'changed', 'empty', 'offline', 'not_modified', 'held'}
MODEL_MODES = {'facts', 'held', 'unsafe_inference', 'unsafe_uncertainty', 'cross_record', 'empty_claims'}


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
    private = Path(tempfile.mkdtemp(prefix='tire-recall-knowledge-qa-')).resolve()
    database_path = private / 'private.sqlite'
    checkpoint = output / 'private-checkpoint.sqlite'
    app = None
    counters = {'tire_source_calls': 0, 'recall_source_calls': 0, 'provider_calls': 0,
                'sync_provider_calls': 0, 'external_network_attempts': 0, 'real_parser_children': 0,
                'wire_text_deltas': 0, 'wire_terminals': 0}
    runtime = {'source_mode': 'baseline', 'model_mode': 'facts', 'holding_source': False,
        'holding_model': False, 'source_release': None, 'model_release': None, 'active_model': False,
        'sealed': None}
    final = {'status': 'running', 'normal_database_used': False, 'real_openai_calls': 0}
    try:
        os.environ.update(TIRE_DATABASE_URL='sqlite:///' + database_path.as_posix(),
            DATABASE_URL='sqlite:///' + database_path.as_posix(), TI_AI_ENABLED='1', TI_EMBEDDINGS_ENABLED='0',
            TI_OPENAI_MODEL='synthetic-recall-research', TI_OPENAI_API_KEY='synthetic-key-never-live',
            TI_AI_ALLOW_PRIVATE='1', TI_AI_DAILY_REQUEST_LIMIT='100', TI_AI_DAILY_TOKEN_LIMIT='10000000',
            TI_OBJECT_STORE_BACKEND='filesystem', TI_OBJECT_STORE_ROOT=str(private / 'objects'),
            TI_PARSER_BUNDLE_ROOT=str(private / 'bundles'), TI_DISABLED_SOURCES='', TI_OBSERVABILITY_LOGS='0')
        sys.path[:0] = [str(ROOT), str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]

        def audit(event, arguments):
            if event == 'subprocess.Popen':
                counters['real_parser_children'] += 1
                raise RuntimeError('Parser children forbidden in private recall research fixture')
            if event in {'socket.connect', 'socket.getaddrinfo'}:
                address = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
                if address not in {'127.0.0.1', '::1', 'localhost'}:
                    counters['external_network_attempts'] += 1
                    raise RuntimeError('External networking forbidden in private recall research fixture')
            if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
                path = Path(str(arguments[0])).resolve()
                require(path.is_relative_to(private) or path == checkpoint, 'private_database_required')
        sys.addaudithook(audit)

        import uvicorn
        from fastapi.responses import JSONResponse
        from sqlalchemy import text
        from tire_api.adapters import registry as installed_registry
        from tire_api.ai_stream_parser import parse_response_stream
        from tire_api.db import UserSession, utcnow
        from tire_api.domain import digest
        from tire_api.main import create_app
        from tire_api.recalls import campaign_url
        from test_core import FixtureRegistry, success
        from test_field_evidence import known_variant
        from test_recalls import IDENTITY, record

        class Registry(FixtureRegistry):
            SPECS = installed_registry.SPECS
            PENDING_SOURCES = installed_registry.PENDING_SOURCES
            supports_parser_deployments = False

            def sources(self):
                rows = deepcopy(installed_registry.sources())
                for row in rows:
                    if row['id'] == 'michelin-us':
                        row.update(name='合成轮胎来源 · 召回研究混合包验收', supported_models=['Fixture Tire'],
                                   default_model='Fixture Tire')
                return rows

            async def fetch(self, source_id, query, cached=None, *, on_observation=None):
                require(source_id == 'michelin-us', 'unexpected_tire_source')
                counters['tire_source_calls'] += 1
                row = known_variant(utqg_treadwear=300, evidence_spans={
                    'manufacturer_product_code': '$.sku.manufacturer_product_code',
                    'facts.product_code_type': '$.sku.facts.product_code_type',
                    'facts.utqg_treadwear': '$.sku.facts.utqg_treadwear'})
                value = success(json.dumps({'synthetic_fixture_only': True, 'sku': row}, ensure_ascii=False), [row])
                if on_observation:
                    on_observation(value)
                return value

        class Recalls:
            supports_parser_deployments = False

            async def fetch(self, query, cached=None, *, on_observation=None):
                counters['recall_source_calls'] += 1
                mode = runtime['source_mode']
                if mode == 'offline':
                    return {'status': 'unavailable', 'reason': 'synthetic_recall_outage'}
                identity = deepcopy(IDENTITY)
                common = {'url': campaign_url(query['campaign_number']), 'content_type': 'application/json',
                    'parser_version': 'synthetic-recall-research@1', 'parser_identity': identity,
                    'etag': '"synthetic-research-v1"', 'last_modified': None}
                if mode == 'not_modified':
                    require(cached is not None, '304_requires_existing_transport_cache')
                    return {**common, 'status': 'not_modified'}
                rows = []
                if mode != 'empty':
                    first = record('SYNTHETIC ALPHA')
                    first.update(campaign_number=query['campaign_number'], make='SYNTHETIC PAIR A',
                        summary=('合成公告原文 A，不能推断实物安全。<script>window.recallKnowledgeCanary=1</script>'
                                 + '这段合成原文用于窄屏换行验收，具体实物适用性仍未评估。' * 22),
                        remedy='合成措施：按监管公告核对批次。')
                    second = record('SYNTHETIC BETA')
                    second.update(campaign_number=query['campaign_number'], make='SYNTHETIC PAIR B',
                        summary='合成公告原文 B，保留单独产品记录。', remedy='合成措施 B，非真实轮胎建议。')
                    if mode == 'compact':
                        first['summary'] = '合成短公告 A，适用性未评估。<script>window.recallKnowledgeCanary=1</script>'
                    if mode == 'changed':
                        first['summary'] = '合成公告新修订 A；旧报告内容必须保持。'
                    rows = [first, second, deepcopy(first)]
                nonce = 1 if mode == 'same_content_new_raw' else 0
                value = {**common, 'status': 'ok', 'records': rows,
                    'body': json.dumps({'synthetic_fixture_only': True, 'raw_nonce': nonce, 'records': rows}, ensure_ascii=False)}
                if on_observation:
                    on_observation(value)
                if mode == 'held':
                    runtime['holding_source'] = True
                    try:
                        await asyncio.wait_for(runtime['source_release'].wait(), timeout=45)
                    finally:
                        runtime['holding_source'] = False
                return value

        def model_output(body, mode):
            pack = json.loads(body['input'][1]['content'])['untrusted_evidence_pack']
            require(body['store'] is False and body['background'] is False and body['tools'] == [],
                    'provider_retention_or_tools_changed')
            if pack.get('purpose') == 'recall_research':
                require(body['text']['format']['name'] == 'recall_evidence_answer' and
                        body['text']['format']['strict'] is True and bool(pack.get('recall_policy')),
                        'recall_provider_contract_missing')
            facts = pack['facts']
            require(bool(facts), 'fixture_requires_canonical_facts')
            claims = [{'type': 'fact', 'text': '', 'fact_ids': [fact['id']], 'evidence_ids': [fact['evidence_id']]}
                      for fact in facts[:4]]
            uncertainty = '' if pack.get('purpose') == 'recall_research' else '合成模型，仅用于协议验收。'
            if mode == 'unsafe_inference':
                claims = [{**claims[0], 'type': 'inference', 'text': 'UNSAFE MODEL TEXT: 这条实物轮胎安全且无需召回。'}]
            elif mode == 'unsafe_uncertainty':
                uncertainty = 'UNSAFE MODEL UNCERTAINTY: 空公告表示已经解除召回，可继续使用。'
            elif mode == 'empty_claims':
                claims = []
            elif mode == 'cross_record':
                different = {}
                for fact in facts:
                    if fact.get('domain') == 'recall' and fact.get('record_key'):
                        different.setdefault(fact['record_key'], fact)
                require(len(different) >= 2, 'cross_record_fixture_requires_multiple_scopes')
                chosen = list(different.values())[:2]
                claims = [{'type': 'fact', 'text': '', 'fact_ids': [fact['id'] for fact in chosen],
                           'evidence_ids': list(dict.fromkeys(fact['evidence_id'] for fact in chosen))}]
            value = ({'uncertainty': uncertainty, 'claims': claims} if mode == 'unsafe_uncertainty'
                     else {'claims': claims, 'uncertainty': uncertainty})
            return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

        class Model:
            async def generate(self, config, body):
                counters['sync_provider_calls'] += 1
                return {'text': model_output(body, runtime['model_mode']), 'error': None,
                    'usage': {'input_tokens': 500, 'output_tokens': 100, 'total_tokens': 600},
                    'provider_response_id': 'resp_synthetic_recall_sync'}

            async def stream(self, config, body, on_text):
                require(not runtime['active_model'], 'fixture_provider_overlap')
                counters['provider_calls'] += 1
                runtime['active_model'] = True
                response_id = 'resp_synthetic_recall_' + str(counters['provider_calls'])
                message_id = 'msg_synthetic_recall_' + str(counters['provider_calls'])
                mode = runtime['model_mode']
                encoded = model_output(body, mode)
                sequence = 0

                def wire(kind, **payload):
                    nonlocal sequence
                    value = {'type': kind, 'sequence_number': sequence, **payload}
                    sequence += 1
                    return ('event: ' + kind + '\r\ndata: ' + json.dumps(value, ensure_ascii=False) + '\r\n\r\n').encode()

                async def frames():
                    yield wire('response.created', response={'id': response_id, 'status': 'in_progress', 'output': []})
                    yield wire('response.output_item.added', output_index=0,
                        item={'id': message_id, 'type': 'message', 'role': 'assistant', 'status': 'in_progress', 'content': []})
                    yield wire('response.content_part.added', item_id=message_id, output_index=0, content_index=0,
                        part={'type': 'output_text', 'text': '', 'annotations': []})
                    stop = len(encoded)
                    if mode == 'held':
                        first = json.loads(encoded)['claims'][0]
                        stop = len('{"claims":[' + json.dumps(first, ensure_ascii=False, separators=(',', ':')))
                    for offset in range(0, stop, 31):
                        counters['wire_text_deltas'] += 1
                        yield wire('response.output_text.delta', item_id=message_id, output_index=0,
                            content_index=0, delta=encoded[offset:min(offset + 31, stop)])
                    if mode == 'held':
                        runtime['holding_model'] = True
                        try:
                            await asyncio.wait_for(runtime['model_release'].wait(), timeout=45)
                        finally:
                            runtime['holding_model'] = False
                        for offset in range(stop, len(encoded), 31):
                            counters['wire_text_deltas'] += 1
                            yield wire('response.output_text.delta', item_id=message_id, output_index=0,
                                content_index=0, delta=encoded[offset:offset + 31])
                    yield wire('response.output_text.done', item_id=message_id, output_index=0, content_index=0, text=encoded)
                    part = {'type': 'output_text', 'text': encoded, 'annotations': []}
                    yield wire('response.content_part.done', item_id=message_id, output_index=0, content_index=0, part=part)
                    item = {'id': message_id, 'type': 'message', 'role': 'assistant', 'status': 'completed', 'content': [part]}
                    yield wire('response.output_item.done', output_index=0, item=item)
                    counters['wire_terminals'] += 1
                    yield wire('response.completed', response={'id': response_id, 'status': 'completed', 'output': [item],
                        'usage': {'input_tokens': 500, 'output_tokens': 100, 'total_tokens': 600}})

                async def chunks():
                    async for frame in frames():
                        for offset in range(0, len(frame), 19):
                            yield frame[offset:offset + 19]
                            await asyncio.sleep(0)
                try:
                    return await parse_response_stream(chunks(), on_text)
                finally:
                    runtime['active_model'] = False

        app = create_app('sqlite:///' + database_path.as_posix(), Registry())
        app.state.recall_adapter = Recalls()
        app.state.ai_adapter = Model()
        database = app.state.database
        database.initialize()
        owner, other = str(uuid4()), str(uuid4())
        with database.sessions() as db:
            for session_id in (owner, other):
                db.add(UserSession(id=session_id, expires_at=utcnow() + timedelta(hours=2)))
            db.commit()

        def fingerprints(db):
            return {name: sorted(digest({key: {'bytes': bytes(value).hex()} if isinstance(value, (bytes, memoryview)) else value
                for key, value in dict(row).items()}) for row in db.execute(text('SELECT * FROM ' + name)).mappings())
                for name in ('recall_snapshots', 'recall_revisions', 'recall_verifications')}

        def state():
            with database.sessions() as db:
                names = ('tire_variants', 'fact_versions', 'snapshots', 'raw_captures', 'query_runs',
                    'recall_snapshots', 'recall_revisions', 'recall_verifications', 'recall_events',
                    'recall_search_snapshots', 'recall_discovery_candidates', 'fallback_consents',
                    'knowledge_documents', 'ai_evidence_packs', 'ai_requests', 'ai_completions',
                    'ai_stream_executions', 'ai_stream_events', 'research_reports', 'research_report_revisions',
                    'report_exports', 'embedding_requests')
                counts = {name: db.execute(text('SELECT COUNT(*) FROM ' + name)).scalar_one() for name in names}
                current = fingerprints(db)
            unchanged = runtime['sealed'] is None or all(set(rows) <= set(current[name]) for name, rows in runtime['sealed'].items())
            return {'scope': 'synthetic_recall_knowledge_research', 'normal_database_used': False,
                'real_openai_calls': 0, 'process_id': os.getpid(), 'source_mode': runtime['source_mode'],
                'model_mode': runtime['model_mode'], 'holding_source': runtime['holding_source'],
                'holding_model': runtime['holding_model'], 'active_model': runtime['active_model'],
                'counts': counts, 'sealed_evidence_unchanged': unchanged, **counters}

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
            require(not runtime['active_model'] and not runtime['holding_source'], 'configure_requires_idle')
            require(set(body) <= {'source_mode', 'model_mode'}, 'invalid_fixture_config')
            if 'source_mode' in body:
                require(body['source_mode'] in SOURCE_MODES, 'invalid_source_mode')
                runtime.update(source_mode=body['source_mode'],
                    source_release=asyncio.Event() if body['source_mode'] == 'held' else None)
            if 'model_mode' in body:
                require(body['model_mode'] in MODEL_MODES, 'invalid_model_mode')
                runtime.update(model_mode=body['model_mode'],
                    model_release=asyncio.Event() if body['model_mode'] == 'held' else None)
            return {'source_mode': runtime['source_mode'], 'model_mode': runtime['model_mode']}

        @app.post('/fixture/release')
        async def release():
            for name in ('source_release', 'model_release'):
                if runtime[name] is not None:
                    runtime[name].set()
            return {'released': True}

        @app.post('/fixture/seal')
        async def seal():
            with database.sessions() as db:
                runtime['sealed'] = fingerprints(db)
            return {'sealed': True}

        @app.post('/fixture/shutdown')
        async def shutdown():
            await release()
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
                private.name.startswith('tire-recall-knowledge-qa-') and not private.is_symlink(), 'unsafe_cleanup_target')
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
    args = parser.parse_args()
    serve(args.port, args.output)
