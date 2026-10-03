"""Synthetic report UI/export acceptance on a temporary database and loopback API."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile

from fastapi.testclient import TestClient
from sqlalchemy import func, select
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api/tests'))
from test_ai import ModelFixture
from test_core import FixtureRegistry, VARIANT, live, success
from test_test_events import create as create_event, PAYLOAD
from tire_api.ai_models import AICompletion, AIEvidencePack, AIRequest
from tire_api.db import EvidenceDocument, Snapshot
from tire_api.main import create_app


class Sources(FixtureRegistry):
    def sources(self):
        return [{**source, 'name': '合成报告验收来源 · 非真实产品',
                 'supported_models': ['Fixture Tire']} for source in super().sources()]


class Model(ModelFixture):
    async def generate(self, config, body):
        await asyncio.sleep(0.25)
        receipt = await super().generate(config, body)
        output = json.loads(receipt['text'])
        output['claims'].append({**output['claims'][0], 'type': 'inference',
            'text': '合成推断：仅验证导出排版与引用，不是真实选胎建议。<script>window.reportCanary=1</script>'})
        output['uncertainty'] = '合成模型仅演示协议，无法证明实际性能；不同测试事件不能直接排名。'
        receipt['text'] = json.dumps(output, ensure_ascii=False)
        return receipt


def main():
    os.environ.update({'TI_AI_ENABLED': '1', 'TI_OPENAI_MODEL': 'synthetic-report-fixture',
        'TI_OPENAI_API_KEY': 'synthetic-key-never-live', 'TI_AI_ALLOW_PRIVATE': '1',
        'TI_AI_DAILY_TOKEN_LIMIT': '1000000', 'TI_AI_DAILY_REQUEST_LIMIT': '100',
        'TI_EMBEDDINGS_ENABLED': '0',
        'TIRE_CORS_ORIGINS': 'http://localhost:3001,http://127.0.0.1:3001'})
    with tempfile.TemporaryDirectory(prefix='tire-report-browser-') as directory:
        registry, model = Sources(), Model()
        app = create_app('sqlite:///' + (Path(directory) / 'qa.db').as_posix(), registry)
        app.state.ai_adapter = model
        one, two = deepcopy(VARIANT), deepcopy(VARIANT)
        one.update(manufacturer_product_code='FIX-REPORT-001', acoustic_technology='Acoustic')
        two.update(manufacturer_product_code='FIX-REPORT-002', acoustic_technology=None)
        one['facts'].update(eu_wet_grip='A', description='中文引文 <script>window.reportCanary=1</script> & [伪链接](javascript:alert(1))')
        two['facts'].update(utqg_treadwear=340, description='独立 SKU；没有确认静音技术，未知不能写成不支持。')
        registry.result = success('DO_NOT_EXPORT_RAW_BODY', [one, two])
        with TestClient(app) as client:
            assert live(client).json()['data_state'] == 'live'
            event = deepcopy(PAYLOAD)
            event['event']['title'] = '合成湿地测试报告引用'
            create_event(client, event)
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8001))

        @app.get('/fixture/state')
        def fixture_state():
            from tire_api.report_models import ResearchReport, ResearchReportRevision, ReportExport
            with app.state.database.sessions() as db:
                counts = {table.__tablename__: db.scalar(select(func.count()).select_from(table))
                          for table in (Snapshot, EvidenceDocument, AIEvidencePack, AIRequest, AICompletion,
                                        ResearchReport, ResearchReportRevision, ReportExport)}
            return {'synthetic': True, 'real_openai_calls': 0, 'model_calls': len(model.calls),
                    'source_calls': len(registry.calls), **counts}

        @app.post('/fixture/shutdown')
        def shutdown():
            server.should_exit = True
            return {'synthetic': True, 'shutdown_requested': True}

        print('Synthetic reports QA; isolated temporary SQLite; no real OpenAI/source calls.', flush=True)
        try:
            server.run()
        finally:
            app.state.database.close()


if __name__ == '__main__':
    main()
