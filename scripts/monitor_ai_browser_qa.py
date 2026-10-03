"""Isolated synthetic monitoring/Responses UI QA; no real provider or source calls."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import func, select
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api/tests'))
from test_ai import ModelFixture
from test_core import FixtureRegistry, VARIANT, live, success
from tire_api.ai_gateway import GatewayError
from tire_api.ai_models import AICompletion, AIEvidencePack, AIRequest
from tire_api.db import AlertRule, AlertRuleRevision, ChangeEvent, NotificationDelivery
from tire_api.domain import LiveQueryRequest
from tire_api.main import create_app
from tire_api.service import QueryService


class Sources(FixtureRegistry):
    def sources(self):
        return [{**source, 'name': '合成监控验收来源 · 非真实轮胎',
                 'supported_models': ['Fixture Tire']} for source in super().sources()]


class Model(ModelFixture):
    """Fixed contract examples only; does not evaluate language or semantic quality."""
    def __init__(self):
        super().__init__()
        self.total_calls = 0
        self.draft_calls = 0
        self.fail_next = False

    async def generate(self, config, body):
        self.total_calls += 1
        await asyncio.sleep(0.25)
        if self.fail_next:
            self.fail_next = False
            raise GatewayError('ai_provider_timeout')
        schema = body['text']['format']['schema']
        if 'proposal' not in schema.get('properties', {}):
            response = await super().generate(config, body)
            answer = json.loads(response['text'])
            if answer['claims']:
                answer['claims'].append({**answer['claims'][0], 'type': 'inference',
                    'text': '合成解释：仅核对本次历史变化，不能推断实时性能或厂商发布日期。<script>window.monitorCanary=1</script>'})
            response['text'] = json.dumps(answer, ensure_ascii=False)
            return response
        self.draft_calls += 1
        unsupported = '微信' in body['input'][1]['content']
        proposal = None if unsupported else {
            'name': '合成 Acoustic 首次观察规则', 'model': 'Fixture Tire', 'size': None,
            'interval_seconds': 21600, 'kinds': ['variant_observed'], 'fields': [], 'technology': 'Acoustic',
        }
        output = {'proposal': proposal,
                  'summary': '合成草稿，只验收流程。首次观察不等于厂商新发布。<script>window.draftCanary=1</script>',
                  'unsupported_requirements': ['微信通知尚未接入，不能用站内通知替代该要求。'] if unsupported else [],
                  'clarifications': []}
        return {'text': json.dumps(output, ensure_ascii=False), 'error': None,
                'usage': {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150},
                'provider_response_id': 'synthetic-monitor-draft'}


def variant(code, technology, treadwear=300):
    row = deepcopy(VARIANT)
    row.update(manufacturer_product_code=code, acoustic_technology=technology,
               source_variant_name=code)
    row['facts'] = {'utqg_treadwear': treadwear, 'description': '合成语料，不是真实厂家声明'}
    return row


def main():
    os.environ.update({'TI_AI_ENABLED': '1', 'TI_OPENAI_MODEL': 'synthetic-monitor-fixture',
        'TI_OPENAI_API_KEY': 'synthetic-key-never-live', 'TI_AI_ALLOW_PRIVATE': '1',
        'TI_AI_DAILY_TOKEN_LIMIT': '1000000', 'TI_AI_DAILY_REQUEST_LIMIT': '100',
        'TI_EMBEDDINGS_ENABLED': '0',
        'TIRE_CORS_ORIGINS': 'http://localhost:3001,http://127.0.0.1:3001'})
    with tempfile.TemporaryDirectory(prefix='tire-monitor-ai-browser-') as directory:
        registry, model = Sources(), Model()
        app = create_app('sqlite:///' + (Path(directory) / 'qa.db').as_posix(), registry)
        app.state.ai_adapter = model
        rows = [variant('FIX-BASE', 'Acoustic'), variant('FIX-PLAIN', None)]
        with TestClient(app) as client:
            registry.result = success('monitor-ui-baseline', rows)
            assert live(client).json()['data_state'] == 'live'
            rule = client.post('/v1/alert-rules', json={'name': '合成已启用参数监控',
                'source_id': 'fixture', 'query': {'model': 'Fixture Tire'}, 'enabled': True,
                'kinds': ['facts_changed'], 'conditions': {'technology': 'Acoustic'}})
            assert rule.status_code == 201, rule.status_code
            rows[0]['facts']['utqg_treadwear'] = 420
            registry.result = success('monitor-ui-updated', rows)
            assert live(client).json()['data_state'] == 'live'
            assert client.get('/v1/notifications').json()['total'] == 1
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8001))

        @app.get('/fixture/state')
        def state():
            with app.state.database.sessions() as db:
                counts = {table.__tablename__: db.scalar(select(func.count()).select_from(table))
                          for table in (AlertRule, AlertRuleRevision, ChangeEvent, NotificationDelivery,
                                        AIEvidencePack, AIRequest, AICompletion)}
            return {'synthetic': True, 'real_openai_calls': 0, 'model_calls': model.total_calls,
                    'draft_calls': model.draft_calls, **counts}

        @app.post('/fixture/observe')
        async def observe(request: Request):
            # Add one definite match, one unknown and one marketing-only mention.
            if len(rows) == 2:
                rows.extend([variant('FIX-NEW-ACOUSTIC', 'Acoustic'), variant('FIX-NEW-UNKNOWN', None),
                             variant('FIX-NEW-MARKETING', None)])
                rows[-1]['facts']['description'] = '营销正文提到 Acoustic，SKU 技术没有确认'
            registry.result = success('monitor-ui-new-members', rows)
            with app.state.database.sessions() as db:
                result = await QueryService(db, registry).execute('fixture',
                    LiveQueryRequest(query={'model': 'Fixture Tire'}, fallback_policy='never'), request.state.session_id)
            return {'synthetic': True, 'data_state': result['data_state'], 'variants': len(result['variants'])}

        @app.post('/fixture/fail-next')
        def fail_next():
            model.fail_next = True
            return {'synthetic': True, 'next_model_call': 'ai_provider_timeout'}

        @app.post('/fixture/shutdown')
        def shutdown():
            server.should_exit = True
            return {'synthetic': True, 'shutdown_requested': True}

        print('Synthetic monitoring UI QA; isolated temporary SQLite; no real OpenAI or sources.', flush=True)
        try:
            server.run()
        finally:
            app.state.database.close()


if __name__ == '__main__':
    main()
