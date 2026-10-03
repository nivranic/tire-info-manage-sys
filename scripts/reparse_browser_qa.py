"""Synthetic transport and actual deployed parsers, isolated from the normal database."""
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
from test_brand_adapters import hankook_body, hankook_card, hankook_fields
from tire_api.adapters import registry
from tire_api.adapters.robots import RobotsPolicy
from tire_api.adapters.transport import FetchResult
from tire_api.db import (ChangeEvent, FactVersion, QueryRun, RawCapture, RejectedObservation,
                         Snapshot, SourceQuarantine, Verification)
from tire_api.main import create_app


class Transport:
    body = ''
    calls = 0

    def __init__(self, *_):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def get(self, url, **_):
        type(self).calls += 1
        return FetchResult(200, url, self.body, 'text/html', None, None)


async def robots(*_):
    return RobotsPolicy('', 'TireEvidenceResearch')


def main():
    # Browser cookies ignore TCP ports. Keep this temporary QA session separate
    # from the normal localhost:3000 application's HttpOnly session cookie.
    import tire_api.main as api_module
    api_module.SESSION_COOKIE = 'tire_reparse_qa_session'
    os.environ.update({'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0', 'TI_DISABLED_SOURCES': '',
        'TIRE_CORS_ORIGINS': 'http://localhost:3001,http://127.0.0.1:3001'})
    registry.SafeHttpClient = Transport
    registry._robots_policy = robots
    with tempfile.TemporaryDirectory(prefix='tire-reparse-browser-') as directory:
        app = create_app('sqlite:///' + (Path(directory) / 'qa.db').as_posix())
        query = {'query': {'model': 'Ventus S1 evo3', 'size': '265/40R20'}, 'fallback_policy': 'never'}
        one = hankook_card(hankook_fields(**{'Material Code': '9990001', 'UTQG - Tread Wear': '300'}))
        two = hankook_card(hankook_fields(**{'Material Code': '9990002', 'UTQG - Tread Wear': '340'}))
        marker = '<script>window.reparseCanary=1</script>'
        with TestClient(app) as client:
            for body, expected in [
                (marker + hankook_body([('Ventus S1 evo3', [one, two])]), 'live'),
                (marker + hankook_body([('Ventus S1 evo3', [one])]), 'source_unavailable'),
                ('<html>合成来源结构变化，无法解析。' + marker + '</html>', 'source_unavailable'),
            ]:
                registry._states.clear()
                Transport.body = body
                response = client.post('/v1/sources/hankook-us/live-query', json=query)
                assert response.status_code == 200, response.status_code
                assert response.json()['data_state'] == expected, response.json().get('reason')
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8001))

        @app.get('/fixture/state')
        def fixture_state():
            from tire_api.reparse_models import ReparseRun, ReparseCompletion, ReparseReview
            tables = (Snapshot, Verification, FactVersion, ChangeEvent, RawCapture,
                      SourceQuarantine, RejectedObservation, QueryRun,
                      ReparseRun, ReparseCompletion, ReparseReview)
            with app.state.database.sessions() as db:
                counts = {table.__tablename__: db.scalar(select(func.count()).select_from(table)) for table in tables}
            return {'synthetic_transport': True, 'real_source_calls': 0, 'source_calls': Transport.calls,
                    'real_model_calls': 0, **counts}

        @app.post('/fixture/shutdown')
        def shutdown():
            server.should_exit = True
            return {'synthetic': True, 'shutdown_requested': True}

        print(json.dumps({'environment': 'synthetic transport + actual isolated parser',
                          'database': 'temporary SQLite', 'real_network_calls': 0}), flush=True)
        try:
            server.run()
        finally:
            app.state.database.close()


if __name__ == '__main__':
    main()
