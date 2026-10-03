"""Private UI acceptance: synthetic HTTP transport, real archived A/B/C parsers."""
import json
import os
from pathlib import Path
import sys
import tempfile

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api/tests'))
from test_brand_adapters import hankook_body, hankook_card, hankook_fields
from test_parser_bundles import trusted_copy, mark_parser
from tire_api.adapters import registry
from tire_api.adapters.robots import RobotsPolicy
from tire_api.adapters.transport import FetchResult
from tire_api.db import ChangeEvent, FactVersion, QueryRun, RawCapture, Snapshot, Verification
from tire_api.main import create_app
from tire_api.parser_releases import register_deployed_bundle
from tire_api.parser_release_models import (ParserBundle, ParserDeploymentRevision, ParserEvaluation,
    ParserEvaluationCompletion, ParserEvaluationReview, ParserExecution, ParserSelection)
from tire_api.reparse_models import ReparseRun, ReparseCompletion, ReparseReview


class Transport:
    body = ''
    calls = 0
    def __init__(self, *_): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    async def get(self, url, **_):
        type(self).calls += 1
        return FetchResult(200, url, self.body, 'text/html', None, None)


async def robots(*_):
    return RobotsPolicy('', 'TireEvidenceResearch')


def main():
    import tire_api.main as api_module
    api_module.SESSION_COOKIE = 'tire_parser_release_qa_session'
    os.environ.update({'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0', 'TI_DISABLED_SOURCES': '',
        'TIRE_CORS_ORIGINS': 'http://localhost:3001,http://127.0.0.1:3001'})
    registry.SafeHttpClient, registry._robots_policy = Transport, robots
    with tempfile.TemporaryDirectory(prefix='tire-parser-release-ui-') as directory, pytest.MonkeyPatch.context() as patcher:
        root = Path(directory)
        source = trusted_copy(root, patcher)
        app = create_app('sqlite:///' + (root / 'qa.db').as_posix())
        query = {'query': {'model': 'Ventus S1 evo3', 'size': '265/40R20'}, 'fallback_policy': 'never'}
        one = hankook_card(hankook_fields(**{'Material Code': '9990001', 'UTQG - Tread Wear': '300'}))
        two = hankook_card(hankook_fields(**{'Material Code': '9990002', 'UTQG - Tread Wear': '340'}))
        marker = '<script>window.parserReleaseCanary=1</script>'
        captures = {}
        with TestClient(app) as client:
            for label, body, expected in [
                ('valid', marker + hankook_body([('Ventus S1 evo3', [one, two])]), 'live'),
                ('loss', marker + hankook_body([('Ventus S1 evo3', [one])]), 'source_unavailable'),
                ('invalid', '<html>合成结构变化。' + marker + '</html>', 'source_unavailable'),
            ]:
                registry._states.clear(); Transport.body = body
                response = client.post('/v1/sources/hankook-us/live-query', json=query)
                assert response.status_code == 200 and response.json()['data_state'] == expected, response.text
                with app.state.database.sessions() as db:
                    captures[label] = db.scalar(select(RawCapture.id).where(RawCapture.query_id == response.json()['query_id']))
            with app.state.database.sessions() as db:
                first = db.scalar(select(ParserDeploymentRevision)).bundle_id
                mark_parser(source, 222)
                second = register_deployed_bundle(db, '合成包B <script>window.parserReleaseCanary=2</script>', '只改临时测试代码的数值，不是官网变化')['id']
                with (source / 'adapters/hankook.py').open('a', encoding='utf-8') as stream:
                    stream.write('\n_previous = parse_html\ndef parse_html(body, query):\n    return _previous(body, query)[:1]\n')
                third = register_deployed_bundle(db, '合成包C', '临时代码显式删去一半记录，验证发布质量门')['id']
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8001))

        @app.get('/fixture/state')
        def state():
            tables = (Snapshot, Verification, FactVersion, ChangeEvent, RawCapture, QueryRun, ParserBundle,
                ParserDeploymentRevision, ParserEvaluation, ParserEvaluationCompletion, ParserEvaluationReview,
                ParserSelection, ParserExecution, ReparseRun, ReparseCompletion, ReparseReview)
            with app.state.database.sessions() as db:
                counts = {table.__tablename__: db.scalar(select(func.count()).select_from(table)) for table in tables}
            return {'environment': 'synthetic transport and archived code changes, real isolated parsers',
                'bundle_ids': {'a': first, 'b': second, 'loss': third}, 'capture_ids': captures,
                'source_calls': Transport.calls, 'real_source_calls': 0, 'real_model_calls': 0, **counts}

        @app.post('/fixture/shutdown')
        def shutdown():
            server.should_exit = True
            return {'shutdown_requested': True}

        print(json.dumps({'environment': 'private_parser_release_ui_qa', 'real_network_calls': 0}), flush=True)
        try:
            server.run()
        finally:
            app.state.database.close()


if __name__ == '__main__':
    main()
