"""Isolated synthetic source for the ordinary-query filter browser acceptance.

The real API, persistence, quality gate and consent gate run unchanged. Source
transport and parser output are synthetic, with no simulated execution receipt.
Never opens the normal database; binds loopback 8001 with a separate cookie.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import func, select
import uvicorn

from tire_api.ai_models import AIRequest
from tire_api.db import (ChangeEvent, FactVersion, FallbackConsent, QueryRun,
                         RawCapture, Snapshot, TireVariant, Verification)
from tire_api.embedding_models import EmbeddingRequest
from tire_api.main import create_app

SOURCE = 'filter-fixture'
MODEL = 'Fixture Tire'
CANARY = '<script>window.filterCanary=1</script>'
QUERY = {'query': {'model': MODEL, 'size': '265/40R20'}, 'fallback_policy': 'ask'}
ENDPOINT = f'/v1/sources/{SOURCE}/live-query'
COUNTS = (TireVariant, Snapshot, FactVersion, QueryRun, RawCapture,
          Verification, ChangeEvent, FallbackConsent, AIRequest, EmbeddingRequest)


class ModeRequest(BaseModel):
    mode: str


def fixture_rows(model=MODEL):
    rows = []
    for index, (xl, flat, foam, wear, oe) in enumerate((
        (True, False, True, 300, 'LUC'), (True, True, False, 280, 'AO'),
        (False, False, None, 340, None), (None, None, None, None, None),
        (None, False, False, 300, 'MO1'), (True, None, True, 400, '*'),
    ), 1):
        facts = {'utqg_treadwear': wear, 'utqg_traction': 'AA', 'utqg_temperature': 'A',
                 'eu_fuel_class': 'B', 'eu_wet_grip': 'A', 'eu_external_noise_db': 69 + index,
                 'eu_noise_class': 'B', 'season': 'summer', 'acoustic_foam': foam,
                 'technology_features': ['Acoustic'] if foam else [],
                 'gtin': f'000000000{index:04d}', 'fixture_notice': 'SYNTHETIC ONLY ' + CANARY}
        if index == 5:
            facts['source_field_conflicts'] = [{'field': 'xl', 'resolution': 'unresolved',
                'values': [{'source_field': 'extraLoad', 'value': False},
                           {'source_field': 'manufMarkings', 'value': 'XL'}]}]
        rows.append({'brand': 'SYNTHETIC Brand', 'model': model,
            'manufacturer_product_code': f'00{index:03d}', 'region': 'US',
            'size': '265/40ZR20' if index in (1, 6) else '265/40R20',
            'load_index': '104', 'speed_rating': 'Y', 'xl': xl, 'hl': False,
            'oe_mark': oe, 'acoustic_technology': 'Acoustic' if foam else None,
            'run_flat': flat, 'source_variant_name': f'SYNTHETIC {index} ' + CANARY,
            'facts': facts})
    return rows


class FilterRegistry:
    def __init__(self, model=MODEL):
        self.model = model
        self.mode = 'online'
        self.calls = []

    def sources(self):
        return [{'id': SOURCE, 'name': '合成组合筛选验收来源', 'region': 'US',
                 'source_class': 'test_fixture', 'status': 'ready',
                 'homepage': 'https://fixture.example', 'description': '仅独立验收，非真实厂商数据。',
                 'supported_models': [self.model], 'default_model': self.model,
                 'target_kind': 'tire'}]

    async def fetch(self, source_id, query, cached=None, *, on_observation=None):
        assert source_id == SOURCE and query.get('model') == self.model
        mode = self.mode
        self.calls.append({'source_id': source_id, 'query': deepcopy(query), 'mode': mode})
        if mode == 'offline':
            return {'status': 'unavailable', 'reason': 'synthetic_filter_outage'}
        if mode == 'slow':
            await asyncio.sleep(2)
        url = 'https://fixture.example/filter-query'
        if mode == 'not_modified' and cached:
            return {'status': 'not_modified', 'url': url, 'parser_version': 'filter-fixture@1',
                    'etag': '"filter-fixture-v1"'}
        rows = fixture_rows(self.model)
        if mode == 'quality_loss':
            rows = rows[:1]
        result = {'status': 'ok', 'url': url, 'content_type': 'application/json',
                  'body': json.dumps({'synthetic': True, 'rows': rows}, ensure_ascii=False),
                  'parser_version': 'filter-fixture@1', 'etag': '"filter-fixture-v1"', 'variants': rows}
        if on_observation:
            on_observation(result)
        return result


def formal_fingerprint(database):
    result = {}
    with database.sessions() as db:
        for model in (TireVariant, Snapshot, FactVersion, ChangeEvent):
            rows = [{column.name: getattr(row, column.name) for column in model.__table__.columns}
                    for row in db.scalars(select(model))]
            result[model.__tablename__] = hashlib.sha256(json.dumps(
                sorted(rows, key=lambda value: str(value.get('id'))),
                sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()
    return result


@contextmanager
def fixture_application(directory):
    import tire_api.main as api_module
    registry = FilterRegistry()
    with patch.dict(os.environ, {'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0',
            'TI_OBJECT_STORE_BACKEND': 'filesystem', 'TI_OBJECT_STORE_ROOT': str(directory / 'objects'),
            'TI_PARSER_BUNDLE_ROOT': str(directory / 'bundles'),
            'TIRE_CORS_ORIGINS': 'http://localhost:3001,http://127.0.0.1:3001'}), \
            patch.object(api_module, 'SESSION_COOKIE', 'tire_filter_qa_session'):
        app = create_app('sqlite:///' + (directory / 'qa.db').as_posix(), registry)
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8001))

        @app.get('/fixture/state')
        def state():
            with app.state.database.sessions() as db:
                counts = {model.__tablename__: db.scalar(select(func.count()).select_from(model)) for model in COUNTS}
            return {'synthetic': True, 'real_source_calls': 0, 'real_model_calls': 0,
                    'parser_execution': 'synthetic_output_no_subprocess_receipt',
                    'mode': registry.mode, 'calls': registry.calls, 'counts': counts,
                    'formal_fingerprint': formal_fingerprint(app.state.database)}

        @app.post('/fixture/mode')
        def set_mode(payload: ModeRequest):
            from fastapi import HTTPException
            if payload.mode not in {'online', 'offline', 'not_modified', 'quality_loss', 'slow'}:
                raise HTTPException(422, 'Unsupported fixture mode')
            registry.mode = payload.mode
            return {'synthetic': True, 'mode': registry.mode}

        @app.post('/fixture/shutdown')
        def shutdown():
            server.should_exit = True
            return {'shutdown_requested': True}

        try:
            yield app, registry, server
        finally:
            app.state.database.close()


def self_test(app, registry):
    checks = []
    with TestClient(app) as client:
        def mode(value):
            response = client.post('/fixture/mode', json={'mode': value})
            assert response.status_code == 200 and response.json()['mode'] == value

        assert client.get('/v1/tire-query-filters').status_code == 200
        filters = [{'field': 'xl', 'op': 'eq', 'value': True},
                   {'field': 'utqg_treadwear', 'op': 'gte', 'value': 300}]
        live = client.post(ENDPOINT, json={**QUERY, 'filters': filters}).json()
        assert live['data_state'] == 'live', live
        assert {row['manufacturer_product_code'] for row in live['variants']} == {'00001', '00006'}
        assert live['selection']['source_count'] == 6 and live['selection']['matched_count'] == 2
        checks.append('combined_filters_match_two_of_six_full_source_records')
        with app.state.database.sessions() as db:
            assert len(db.get(Snapshot, live['provenance'][0]['snapshot_id']).parsed_variants) == 6
            assert db.scalar(select(func.count()).select_from(TireVariant)) == 6
        before = formal_fingerprint(app.state.database)
        mode('not_modified')
        no = client.post(ENDPOINT, json={**QUERY, 'filters': [
            {'field': 'manufacturer_product_code', 'op': 'eq', 'value': 'ABSENT'}]}).json()
        assert no['data_state'] == 'live_verified_304' and not no['variants']
        assert no['selection']['source_count'] == 6 and no['selection']['excluded_count'] == 6
        checks.append('zero_match_keeps_revalidation_and_full_snapshot')
        mode('offline')
        pending = client.post(ENDPOINT, json={**QUERY, 'filters': filters}).json()
        assert pending['data_state'] == 'consent_required' and not pending['variants']
        assert all(pending['selection'][key] is None for key in (
            'source_count', 'matched_count', 'excluded_count', 'undetermined_count'))
        grant = client.post('/v1/fallback-consents', json={'query_id': pending['query_id'], 'decision': 'allow'})
        assert grant.status_code == 201
        consent = grant.json()['id']
        assert client.post(ENDPOINT, json={**QUERY, 'filters': [], 'consent_id': consent}).status_code == 403
        accepted = client.post(ENDPOINT, json={**QUERY, 'filters': list(reversed(filters)), 'consent_id': consent})
        assert accepted.status_code == 200 and accepted.json()['data_state'] == 'local_snapshot'
        assert accepted.json()['selection']['matched_count'] == 2
        assert client.post(ENDPOINT, json={**QUERY, 'filters': filters, 'consent_id': consent}).status_code == 409
        checks.append('frozen_filter_consent_cannot_expand_reorder_allowed_once_only')
        assert formal_fingerprint(app.state.database) == before
        checks.append('projection_does_not_rewrite_source_facts_or_model_state')
        mode('quality_loss')
        lost = client.post(ENDPOINT, json={**QUERY, 'filters': [
            {'field': 'manufacturer_product_code', 'op': 'eq', 'value': '00001'}]}).json()
        assert lost['reason'] == 'source_quality_quarantined' and not lost['variants']
        assert formal_fingerprint(app.state.database) == before
        checks.append('source_member_loss_is_not_hidden_by_matching_projection')
        final = client.get('/fixture/state').json()
        assert final['counts']['ai_requests'] == final['counts']['embedding_requests'] == 0
        return {'checks': checks, 'final': final, 'scope': 'synthetic_transport_and_parser_output_real_business_routes'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='tire-filter-browser-') as temporary:
        with fixture_application(Path(temporary)) as (app, registry, server):
            if args.self_test:
                print(json.dumps(self_test(app, registry), ensure_ascii=False), flush=True)
            else:
                print('Synthetic filter fixture; empty private database; no source or model network.', flush=True)
                server.run()


if __name__ == '__main__':
    main()
