"""Isolated HTTP/UI fixture. Uses production routes and a synthetic model only."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
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
    # Keep content-addressed hardlink targets below Windows path-length limits.
    storage = ROOT / '.artifacts' / ('r70-web-' + uuid4().hex)
    storage.mkdir()
    database_path = storage / 'synthetic.sqlite'
    for name in list(os.environ):
        if name.startswith('TI_') or name in {'TIRE_DATABASE_URL', 'DATABASE_URL', 'TIRE_CORS_ORIGINS'}:
            del os.environ[name]
    os.environ.update(
        TIRE_DATABASE_URL='sqlite:///' + database_path.as_posix(),
        TI_AI_ENABLED='1', TI_AI_PROVIDER='openai_responses',
        TI_OPENAI_MODEL='synthetic-offline-only', TI_OPENAI_API_KEY='synthetic-no-network',
        TI_AI_ALLOW_PRIVATE='1', TI_AI_DAILY_REQUEST_LIMIT='40', TI_AI_DAILY_TOKEN_LIMIT='1000000',
        TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_LOGS='0',
        TI_OBJECT_STORE_ROOT=str(storage / 'objects'), TI_OBJECT_STORE_BACKEND='filesystem',
        TI_PARSER_BUNDLE_ROOT=str(storage / 'bundles'),
        TIRE_CORS_ORIGINS=f'http://127.0.0.1:{web_port},http://localhost:{web_port}',
    )
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
    platform.uname()
    counters = {'external_network_attempts': 0, 'parser_children': 0,
                'actual_provider_attempts': 0, 'normal_database_attempts': 0, 'synthetic_model_calls': 0}

    def audit(event, arguments):
        if event == 'subprocess.Popen':
            counters['parser_children'] += 1
            raise RuntimeError('Children forbidden in isolated test AI QA')
        if event in {'socket.connect', 'socket.getaddrinfo'}:
            address = arguments[1][0] if event == 'socket.connect' and isinstance(arguments[1], tuple) else arguments[0]
            if address not in {'127.0.0.1', '::1', 'localhost'}:
                counters['external_network_attempts'] += 1
                raise RuntimeError('External networking forbidden in isolated test AI QA')
        if event == 'sqlite3.connect' and str(arguments[0]) != ':memory:':
            if not Path(str(arguments[0])).resolve().is_relative_to(storage):
                counters['normal_database_attempts'] += 1
                raise RuntimeError('private_database_required')
    sys.addaudithook(audit)

    import uvicorn
    from fastapi import Query
    from tire_api.db import UserSession, uid, utcnow
    from tire_api.domain import LiveQueryRequest
    from tire_api.main import create_app
    from tire_api.service import QueryService
    from tire_api.test_events import EventPayload, TireTestEvent, append
    from test_core import FixtureRegistry, QUERY
    from test_test_events import PAYLOAD

    registry = FixtureRegistry()
    app = create_app('sqlite:///' + database_path.as_posix(), registry)
    state = {'synthetic_only': True, 'normal_database_used': False, 'model_mode': 'valid'}

    class SyntheticModel:
        def answer(self, body):
            counters['synthetic_model_calls'] += 1
            context = json.loads(body['input'][1]['content'])['untrusted_evidence_pack']
            fact = next((item for item in context['facts'] if item['field'].startswith('本场成绩')), context['facts'][0])
            claim = {'type': 'fact', 'text': '', 'fact_ids': [fact['id']], 'evidence_ids': [fact['evidence_id']]}
            value = {'claims': [claim], 'uncertainty': ''}
            if state['model_mode'] == 'inference':
                value['claims'][0].update(type='inference', text='Synthetic forbidden SKU recommendation')
            elif state['model_mode'] == 'uncertainty':
                value['uncertainty'] = 'Synthetic forbidden recommendation in uncertainty'
            return json.dumps(value, ensure_ascii=False)

        async def generate(self, _config, body):
            return {'text': self.answer(body), 'error': None,
                    'usage': {'input_tokens': 500, 'output_tokens': 100, 'total_tokens': 600},
                    'provider_response_id': 'synthetic_sync'}

        async def stream(self, _config, body, on_text):
            text = self.answer(body)
            for start in range(0, len(text), 25):
                await on_text(text[start:start + 25])
                await asyncio.sleep(0.025)
            return {'text': text, 'error': None,
                    'usage': {'input_tokens': 500, 'output_tokens': 100, 'total_tokens': 600},
                    'provider_response_id': 'synthetic_stream'}

    app.state.ai_adapter = SyntheticModel()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            with application.state.database.sessions() as db:
                owner = UserSession(id=uid(), expires_at=utcnow() + timedelta(hours=2))
                db.add(owner)
                db.commit()
                owner_id = owner.id
                seeded = await QueryService(db, registry).execute(
                    'fixture', LiveQueryRequest.model_validate(QUERY), owner_id)
                if seeded['data_state'] != 'live':
                    raise RuntimeError('Synthetic source seed rejected')
                state.update(tire_snapshot_id=seeded['provenance'][0]['snapshot_id'],
                             variant_id=seeded['variants'][0]['id'])
                item = TireTestEvent(id=uid())
                db.add(item)
                db.flush()
                data = EventPayload.model_validate(deepcopy(PAYLOAD['event'])).model_dump(mode='json')
                recorded = append(db, item.id, data, 'create', 'active', 'Synthetic fixture',
                                  'Isolated HTTP and browser QA', owner_id, 1)
                state.update(event_id=recorded['id'], event_revision=recorded['revision'])
            (output / 'started.json').write_text(json.dumps({
                'schema': 'test-ai-private-runtime@1', 'state': state,
                'private_storage': storage.relative_to(ROOT).as_posix(),
                'counters': counters, 'normal_database_touched': False,
                'provider': 'synthetic fixture adapter; not live model acceptance',
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            yield
        (output / 'stopped.json').write_text(json.dumps({
            'state': state, 'counters': counters, 'shutdown_complete': True,
        }, ensure_ascii=False, indent=2), encoding='utf-8')

    app.router.lifespan_context = lifespan
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning', access_log=False))

    @app.get('/fixture/state')
    def fixture_state():
        return {**state, 'counters': dict(counters)}

    @app.post('/fixture/model')
    def set_model(mode: str = Query(pattern='^(valid|inference|uncertainty)$')):
        state['model_mode'] = mode
        return {'mode': mode}

    @app.post('/fixture/shutdown')
    def shutdown():
        server.should_exit = True
        return {'shutdown_requested': True}

    server.run()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--web-port', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    serve(args.port, args.web_port, args.output)
