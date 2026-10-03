"""Private synthetic identity UI acceptance; never uses the normal development DB.

Run: uv run --project apps/api --extra dev python scripts/identity_browser_qa.py
Check without opening a port: append --self-test.
The server binds only to 127.0.0.1:8001. All source results are explicitly
synthetic FixtureRegistry data accepted by the real QueryService ingestion path.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import func, select
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api/tests'))
from test_core import FixtureRegistry, VARIANT, success
from tire_api.ai_models import AIRequest
from tire_api.db import (ChangeEvent, FactVersion, QueryRun, RawCapture, Snapshot,
                         TireVariant, Verification, WatchItem)
from tire_api.domain import LiveQueryRequest
from tire_api.embedding_models import EmbeddingRequest
from tire_api.identity_models import IdentityRevision
from tire_api.identity_resolution import IdentityDecision, append_decision, preview
from tire_api.main import create_app
from tire_api.service import QueryService

CANARY = '<script>window.identityCanary=1</script>'
OPERATOR = '合成身份审核者 ' + CANARY
QUERY = {'query': {'model': 'Fixture Tire', 'size': '265/40R20'}, 'fallback_policy': 'never'}
TABLES = (TireVariant, Snapshot, RawCapture, Verification, FactVersion, ChangeEvent,
          QueryRun, WatchItem, IdentityRevision, AIRequest, EmbeddingRequest)


def variant(code, treadwear, *, hl=False):
    row = deepcopy(VARIANT)
    row.update(manufacturer_product_code=code, source_variant_name=code, hl=hl)
    row['facts'] = {'utqg_treadwear': treadwear,
                    'description': '仅合成身份验收，不是真实轮胎资料。' + CANARY}
    return row


class Sources(FixtureRegistry):
    def __init__(self):
        super().__init__()
        self.primary = [variant('FIX-A', 100), variant('FIX-B', 200), variant('FIX-C', 300),
                        variant('FIX-MERGE', 400, hl=None)]
        self.secondary = [variant('FIX-MERGE', 400, hl=None)]
        self.target_updates = 0

    def sources(self):
        return [{**source, 'name': '合成身份验收来源 ' + source['id'],
                 'description': '仅隔离浏览器验收，不代表真实厂商数据。',
                 'parser_version': 'fixture@1', 'supported_models': ['Fixture Tire']}
                for source in super().sources()]

    async def fetch(self, source_id, query, cached=None, *, on_observation=None):
        self.calls.append((source_id, deepcopy(query), cached))
        rows = self.primary if source_id == 'fixture' else self.secondary
        body = ('<html><body><h1>合成身份验收：' + source_id + '</h1>' + CANARY
                + '<pre>' + json.dumps(rows, ensure_ascii=False, sort_keys=True) + '</pre></body></html>')
        return success(body, rows, url='https://fixture.example/' + source_id + '/identity',
                       etag='"synthetic-identity-' + str(self.target_updates) + '"')


@contextmanager
def fixture_application(directory):
    """Keep DB, evidence objects, cookie and process settings private to this run."""
    import tire_api.main as api_module

    settings = {'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0', 'TI_DISABLED_SOURCES': '',
                'TI_OBJECT_STORE_BACKEND': 'filesystem',
                'TI_OBJECT_STORE_ROOT': str(directory / 'objects'),
                'TIRE_CORS_ORIGINS': 'http://localhost:3001,http://127.0.0.1:3001'}
    previous = {name: os.environ.get(name) for name in settings}
    previous_cookie = api_module.SESSION_COOKIE
    os.environ.update(settings)
    api_module.SESSION_COOKIE = 'tire_identity_qa_session'
    app = None
    try:
        registry = Sources()
        app = create_app('sqlite:///' + (directory / 'qa.db').as_posix(), registry)
        variants, snapshots = {}, {}
        with TestClient(app) as client:
            for source_id, labels in [('fixture', ['a', 'b', 'c', 'x']), ('fixture-two', ['y'])]:
                response = client.post('/v1/sources/' + source_id + '/live-query', json=QUERY)
                assert response.status_code == 200, response.text
                data = response.json()
                assert data['data_state'] == 'live', data['data_state']
                assert len(data['variants']) == len(labels)
                variants.update({label: row['id'] for label, row in zip(labels, data['variants'])})
                snapshots[source_id] = data['provenance'][0]['snapshot_id']
        assert len(set(variants.values())) == 5
        initial_snapshots = dict(snapshots)
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8001))

        @app.get('/fixture/state')
        def state():
            with app.state.database.sessions() as db:
                counts = {table.__tablename__: db.scalar(select(func.count()).select_from(table))
                          for table in TABLES}
            return {'environment': 'private_synthetic_identity_ui_qa', 'synthetic': True,
                    'variant_ids': variants, 'snapshot_ids': snapshots,
                    'initial_snapshot_ids': initial_snapshots,
                    'source_calls': len(registry.calls),
                    'source_calls_by_id': {source['id']: sum(call[0] == source['id'] for call in registry.calls)
                                           for source in registry.sources()},
                    'real_source_calls': 0, 'real_model_calls': 0,
                    'model_calls': 0, 'embedding_calls': 0, 'target_updates': registry.target_updates,
                    'suggested_operator': OPERATOR, 'counts': counts, **counts}

        @app.post('/fixture/bootstrap-client')
        def bootstrap_client(request: Request):
            # Session identity comes only from the regular HttpOnly-cookie middleware.
            # Existing accepted facts are read normally; this adds only WatchItems.
            with app.state.database.sessions() as db:
                service = QueryService(db, registry)
                service.lock_ingestion()
                added = 0
                for variant_id in variants.values():
                    service.historical_variant(variant_id)
                    exists = db.scalar(select(WatchItem.id).where(
                        WatchItem.session_id == request.state.session_id, WatchItem.variant_id == variant_id))
                    if not exists:
                        db.add(WatchItem(session_id=request.state.session_id, variant_id=variant_id))
                        service.audit(request.state.session_id, 'watch_added', variant_id=variant_id)
                        added += 1
                db.commit()
            return {'synthetic': True, 'added': added, 'variant_ids': variants}

        @app.post('/fixture/update-target-facts')
        async def update_target_facts(request: Request):
            # Fixed B fact change; no URL, code, identity or DB selection is accepted.
            registry.target_updates += 1
            registry.primary[1]['facts']['utqg_treadwear'] = 200 + 50 * registry.target_updates
            with app.state.database.sessions() as db:
                data = await QueryService(db, registry).execute(
                    'fixture', LiveQueryRequest(**QUERY), request.state.session_id)
            if data['data_state'] == 'live':
                snapshots['fixture'] = data['provenance'][0]['snapshot_id']
            return {'synthetic': True, 'data_state': data['data_state'],
                    'target_id': variants['b'], 'snapshot_id': snapshots['fixture'],
                    'treadwear': registry.primary[1]['facts']['utqg_treadwear']}

        @app.post('/fixture/competing-correction')
        def competing_correction(request: Request):
            # Simulates another reviewer while the browser holds an A -> B preview.
            with app.state.database.sessions() as db:
                QueryService(db, registry).lock_ingestion()
                current = preview(db, variants['a'], variants['c'])
                payload = IdentityDecision(mode='history', action='correct', target_id=variants['c'],
                    expected_revision=current['revision'], expected_fingerprint=current['fingerprint'],
                    operator=OPERATOR, reason='仅合成竞争审核，用于验证浏览器旧预览不能覆盖新修订。',
                    acknowledged=True, acknowledge_unknowns=bool(current['unknown_fields']),
                    field_reasons={row['field']: '已人工核对合成原文中的该项差异。'
                                   for row in current['differences']},
                    evidence=[{'snapshot_id': snapshots['fixture'], 'locator': '合成原文 FIX-A 与 FIX-C 所在行'}])
                result = append_decision(db, variants['a'], payload, request.state.session_id, str(uuid4()))
            return {'synthetic': True, **result}

        @app.post('/fixture/shutdown')
        def shutdown():
            server.should_exit = True
            return {'synthetic': True, 'shutdown_requested': True}

        yield app, server
    finally:
        if app is not None:
            app.state.database.close()
        api_module.SESSION_COOKIE = previous_cookie
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def self_test(app):
    """Exercise fixture wiring and real identity gates without binding any port."""
    with TestClient(app) as client:
        state = client.get('/fixture/state').json()
        ids, snapshots = state['variant_ids'], state['snapshot_ids']
        assert state['tire_variants'] == 5 and state['source_calls'] == 2
        assert client.cookies.get('tire_identity_qa_session')
        assert not client.cookies.get('tire_local_session')
        assert client.post('/fixture/bootstrap-client').json()['added'] == 5
        assert client.post('/fixture/bootstrap-client').json()['added'] == 0
        assert len(client.get('/v1/watchlists').json()['items']) == 5
        with TestClient(app) as other:
            assert other.get('/v1/watchlists').json()['items'] == []

        def decision(origin, target, action, evidence):
            response = client.post('/v1/tire-variants/' + origin + '/identity-preview',
                                   json={'mode': 'history', 'target_id': target})
            assert response.status_code == 200, response.text
            current = response.json()
            return {'mode': 'history', 'action': action, 'target_id': target,
                    'expected_revision': current['revision'], 'expected_fingerprint': current['fingerprint'],
                    'operator': OPERATOR, 'reason': '合成浏览器 fixture 自检，不是真实身份结论。',
                    'acknowledged': True, 'acknowledge_unknowns': bool(current['unknown_fields']),
                    'field_reasons': {row['field']: '已人工核对合成原文中的该项差异。' for row in current['differences']},
                    'evidence': [{'snapshot_id': value, 'locator': '合成精确代码所在行'} for value in evidence]}

        def submit(origin, body):
            return client.post('/v1/tire-variants/' + origin + '/identity-revisions', json=body,
                               headers={'Idempotency-Key': str(uuid4())})

        pending = decision(ids['a'], ids['b'], 'correct', [snapshots['fixture']])
        assert client.post('/fixture/competing-correction').status_code == 200
        assert submit(ids['a'], pending).status_code == 409
        corrected = submit(ids['a'], decision(ids['a'], ids['b'], 'correct', [snapshots['fixture']]))
        assert corrected.status_code == 201, corrected.text
        assert CANARY in corrected.json()['event']['operator']
        assert client.post('/fixture/update-target-facts').json()['data_state'] == 'live'
        review = client.get('/v1/tire-variants/' + ids['a'] + '/identity-resolution?mode=history').json()
        assert review['resolution']['state'] == 'needs_review'
        merged = submit(ids['x'], decision(ids['x'], ids['y'], 'merge', list(snapshots.values())))
        assert merged.status_code == 201, merged.text
        raw = client.get('/v1/evidence/' + snapshots['fixture']).json()
        assert CANARY in raw['body']
        latest = client.get('/fixture/state').json()
        assert latest['ai_requests'] == latest['embedding_requests'] == 0
        assert latest['identity_revisions'] == 3 and latest['tire_variants'] == 5
        assert client.post('/fixture/shutdown').json()['shutdown_requested']
        return {'synthetic': True, 'self_test': 'passed', 'ports_opened': 0,
                'source_calls': latest['source_calls'], 'identity_revisions': latest['identity_revisions'],
                'real_source_calls': 0, 'real_model_calls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true', help='Validate in-process with a temporary DB; no listener')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='tire-identity-browser-') as directory:
        with fixture_application(Path(directory)) as (app, server):
            if args.self_test:
                print(json.dumps(self_test(app), ensure_ascii=False), flush=True)
            else:
                print(json.dumps({'environment': 'private_synthetic_identity_ui_qa',
                    'api': 'http://127.0.0.1:8001', 'real_source_calls': 0, 'real_model_calls': 0,
                    'bootstrap': 'POST /fixture/bootstrap-client', 'state': 'GET /fixture/state',
                    'shutdown': 'POST /fixture/shutdown'}, ensure_ascii=False), flush=True)
                server.run()


if __name__ == '__main__':
    main()
