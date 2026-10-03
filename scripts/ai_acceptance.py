"""Isolated browser QA only: synthetic sources AND synthetic OpenAI output, no cloud calls.

Run with uv run --project apps/api --extra dev python scripts/ai_acceptance.py.
The process owns a temporary SQLite DB and only listens on loopback port 8001.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

from fastapi.testclient import TestClient
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api/tests'))
from test_ai import ModelFixture
from test_core import FixtureRegistry, live
from test_test_events import create
from tire_api.ai_gateway import GatewayError
from tire_api.main import create_app


class BrowserSources(FixtureRegistry):
    def sources(self):
        return [{**source, 'name': '合成验收来源 · 非真实轮胎', 'supported_models': ['Fixture Tire']}
                for source in super().sources()]


class BrowserModel(ModelFixture):
    async def generate(self, config, body):
        await asyncio.sleep(1)
        data = json.loads(body['input'][1]['content'])
        if '调用失败' in data['question']:
            raise GatewayError('ai_provider_timeout')
        result = await super().generate(config, body)
        output = json.loads(result['text'])
        if '引用失败' in data['question']:
            output['claims'][0]['fact_ids'] = ['invented']
        else:
            output['claims'].append({**output['claims'][0], 'type': 'inference',
                'text': '合成推断，仅验证界面，不是真实 AI 分析。<script>window.aiCanary=1</script>'})
        result['text'] = json.dumps(output)
        return result


def main():
    os.environ.update({'TI_AI_ENABLED': '1', 'TI_OPENAI_MODEL': 'synthetic-browser-fixture',
        'TI_OPENAI_API_KEY': 'synthetic-key-never-live', 'TI_AI_ALLOW_PRIVATE': '1',
        'TI_AI_DAILY_REQUEST_LIMIT': '100', 'TI_AI_DAILY_TOKEN_LIMIT': '1000000',
        'TIRE_CORS_ORIGINS': 'http://localhost:3001,http://127.0.0.1:3001'})
    with tempfile.TemporaryDirectory(prefix='tire-ai-browser-') as directory:
        registry = BrowserSources()
        app = create_app('sqlite:///' + (Path(directory) / 'qa.db').as_posix(), registry)
        app.state.ai_adapter = BrowserModel()
        with TestClient(app) as client:
            assert live(client).status_code == 200
            create(client)

        @app.post('/fixture/outage')
        async def outage():
            registry.result = {'status': 'unavailable', 'reason': 'synthetic_outage'}
            return {'synthetic': True}

        print('Synthetic browser QA only; independent temporary DB; OpenAI never contacted.', flush=True)
        uvicorn.run(app, host='127.0.0.1', port=8001)


if __name__ == '__main__':
    main()
