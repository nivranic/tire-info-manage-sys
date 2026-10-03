"""Synthetic browser-only knowledge search QA on an isolated DB, loopback 8001."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
import uvicorn

from ai_acceptance import BrowserSources, BrowserModel
from test_core import live, success, VARIANT
from test_test_events import create, PAYLOAD
from tire_api.main import create_app


def main():
    os.environ.update({'TI_AI_ENABLED': '1', 'TI_OPENAI_MODEL': 'synthetic-knowledge-fixture',
        'TI_OPENAI_API_KEY': 'synthetic-key-never-live', 'TI_AI_ALLOW_PRIVATE': '1',
        'TI_AI_DAILY_REQUEST_LIMIT': '100', 'TI_AI_DAILY_TOKEN_LIMIT': '1000000',
        'TIRE_CORS_ORIGINS': 'http://localhost:3001,http://127.0.0.1:3001'})
    with tempfile.TemporaryDirectory(prefix='tire-knowledge-browser-') as directory:
        registry = BrowserSources()
        app = create_app('sqlite:///' + (Path(directory) / 'qa.db').as_posix(), registry)
        app.state.ai_adapter = BrowserModel()
        with TestClient(app) as client:
            one = deepcopy(VARIANT)
            one['facts']['technology_features'] = ['静音泡棉', 'Acoustic']
            two = deepcopy(VARIANT)
            two.update(manufacturer_product_code='FIX-002', acoustic_technology=None, source_variant_name='fixture-two')
            registry.result = success(variants=[one, two])
            assert live(client).json()['data_state'] == 'live'
            alternate = deepcopy(one)
            alternate['facts']['utqg_treadwear'] = 340
            registry.result = success(body='synthetic-source-two', variants=[alternate])
            assert live(client, source='fixture-two').json()['data_state'] == 'live'
            event = deepcopy(PAYLOAD)
            event['event']['title'] = '合成湿地测试 <script>window.knowledgeCanary=1</script>'
            event['event']['conditions'] += ' 静音评测；仅为全文检索验收。'
            create(client, event)
        print('Synthetic knowledge QA only; isolated temporary DB; no real model calls.', flush=True)
        uvicorn.run(app, host='127.0.0.1', port=8001)


if __name__ == '__main__':
    main()
