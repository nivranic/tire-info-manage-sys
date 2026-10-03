"""Real Michelin filter acceptance and reusable synthetic PostgreSQL checkpoint.

Live mode uses the production allowlist/transport/sealed parser in a temporary
database. An outage is explicitly injected only after the actual source checks.
No model, credential lookup, normal database or production deployment is used.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tire_api.adapters import registry
from tire_api.ai_models import AIRequest
from tire_api.captures import checked_capture_bytes
from tire_api.db import (ChangeEvent, Database, FactVersion, FallbackConsent,
                         QueryRun, RawCapture, Snapshot, TireVariant)
from tire_api.domain import digest
from tire_api.embedding_models import EmbeddingRequest
from tire_api.main import create_app

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'michelin-us'
ENDPOINT = f'/v1/sources/{SOURCE}/live-query'
REQUEST = {'query': {'model': 'Pilot Sport EV', 'size': '265/40R20'}, 'fallback_policy': 'ask'}
FILTERS = [{'field': 'acoustic_technology', 'op': 'eq', 'value': 'Acoustic'},
           {'field': 'xl', 'op': 'eq', 'value': True}]


class ControlledRegistry:
    supports_parser_deployments = True

    def __init__(self):
        self.offline = False
        self.real_calls = 0

    @staticmethod
    def sources():
        return [item for item in registry.sources() if item['id'] == SOURCE]

    async def fetch(self, source_id, query, cached=None, *, on_observation=None, **kwargs):
        if self.offline:
            return {'status': 'unavailable', 'reason': 'explicit_filter_acceptance_outage'}
        self.real_calls += 1
        return await registry.fetch(source_id, query, cached=cached, on_observation=on_observation, **kwargs)


def accepted(response, expected=200):
    assert response.status_code == expected, f'unexpected_http_{response.status_code}'
    return response.json()


def formal_hashes(database):
    result = {}
    with database.sessions() as db:
        for model in (TireVariant, Snapshot, FactVersion, ChangeEvent):
            result[model.__tablename__] = sorted(hashlib.sha256(json.dumps({
                column.name: getattr(row, column.name) for column in model.__table__.columns
            }, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
                for row in db.scalars(select(model)))
    return result


def live_run(output, report):
    with tempfile.TemporaryDirectory(prefix='tire-query-filter-real-') as temporary:
        root = Path(temporary)
        with patch.dict(os.environ, {'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0',
                'TI_PARSER_BUNDLE_ROOT': str(root / 'bundles'), 'TI_OBJECT_STORE_BACKEND': 'filesystem',
                'TI_OBJECT_STORE_ROOT': str(root / 'objects')}):
            source = ControlledRegistry()
            app = create_app('sqlite:///' + (root / 'acceptance.db').as_posix(), source)
            try:
                with TestClient(app) as client:
                    report['step'] = 'real_filtered_query'
                    first = accepted(client.post(ENDPOINT, json={**REQUEST, 'filters': FILTERS}))
                    report['first_state'] = {'state': first['data_state'], 'reason': first['reason']}
                    assert first['data_state'] == 'live', 'real_source_query_not_live'
                    assert first['variants'] and all(row['xl'] is True and row['acoustic_technology'] == 'Acoustic'
                                                     for row in first['variants'])
                    assert '08150' in {row['manufacturer_product_code'] for row in first['variants']}, 'official_sample_changed'
                    with app.state.database.sessions() as db:
                        snapshot = db.get(Snapshot, first['provenance'][0]['snapshot_id'])
                        full_count = len(snapshot.parsed_variants)
                        assert full_count == first['selection']['source_count'] > len(first['variants'])
                        assert full_count == db.scalar(select(func.count()).select_from(TireVariant))
                        assert snapshot.query_key == digest(REQUEST['query'])
                    report['checks'].append('real_combined_sku_filter_preserves_complete_official_snapshot')
                    prior = formal_hashes(app.state.database)
                    report['step'] = 'real_zero_match_query'
                    origin = registry.SPECS[SOURCE].origin
                    state = registry._states[origin]
                    elapsed = time.monotonic() - state.get('last', 0)
                    time.sleep(max(0, state['interval'] + 0.15 - elapsed))
                    zero = accepted(client.post(ENDPOINT, json={**REQUEST, 'filters': [
                        {'field': 'manufacturer_product_code', 'op': 'eq', 'value': 'FILTER-ACCEPTANCE-NO-SUCH-CODE'}]}))
                    report['second_state'] = {'state': zero['data_state'], 'reason': zero['reason']}
                    assert zero['data_state'] in {'live', 'live_verified_304'} and not zero['variants']
                    assert zero['selection']['source_count'] == zero['selection']['excluded_count'] >= full_count
                    assert zero['selection']['matched_count'] == 0
                    after = formal_hashes(app.state.database)
                    assert all(set(values) <= set(after[key]) for key, values in prior.items())
                    report['checks'].append('real_zero_match_is_success_without_deleting_source_evidence')
                    report['observations'] = [{'state': row['data_state'], 'query_id': row['query_id'],
                        'selection': row['selection'], 'observed_at': row['snapshot_observed_at'],
                        'provenance': row['provenance'],
                        'product_codes': [v['manufacturer_product_code'] for v in row['variants']]}
                        for row in (first, zero)]
                    receipts = []
                    for row in (first, zero):
                        execution = accepted(client.get(f'/v1/parser-executions/{row["query_id"]}?mode=history'))
                        completion = execution['completion']
                        if row['data_state'] == 'live_verified_304':
                            assert completion['state'] == 'not_modified' and completion['receipt'] is None
                            assert row['provenance'] == first['provenance']
                            assert row['snapshot_observed_at'] == first['snapshot_observed_at']
                            continue
                        assert completion['state'] == 'completed'
                        receipt = completion['receipt']
                        assert receipt['exit_code'] == 0 and receipt['reaped'] and receipt['pid'] > 0
                        assert receipt['limits']['wall_seconds'] == 8 and receipt['limits']['max_concurrent'] == 2
                        receipts.append(receipt)
                    report['receipts'] = receipts
                    report['checks'].append('real_sealed_receipts_reaped_or_valid_304_without_invented_child')
                    report['step'] = 'explicit_outage_and_filter_consent'
                    source.offline = True
                    before_outage = formal_hashes(app.state.database)
                    pending = accepted(client.post(ENDPOINT, json={**REQUEST, 'filters': FILTERS}))
                    assert pending['data_state'] == 'consent_required' and not pending['variants'] and not pending['provenance']
                    assert all(pending['selection'][key] is None for key in (
                        'source_count', 'matched_count', 'excluded_count', 'undetermined_count'))
                    grant = accepted(client.post('/v1/fallback-consents', json={
                        'query_id': pending['query_id'], 'decision': 'allow'}), 201)
                    # The changed-filter request must fail before consuming the grant.
                    assert client.post(ENDPOINT, json={**REQUEST, 'filters': [], 'consent_id': grant['id']}).status_code == 403
                    local = accepted(client.post(ENDPOINT, json={**REQUEST,
                        'filters': list(reversed(FILTERS)), 'consent_id': grant['id']}))
                    assert local['data_state'] == 'local_snapshot' and local['variants']
                    assert local['snapshot_observed_at'] == zero['snapshot_observed_at']
                    assert all(row['xl'] is True and row['acoustic_technology'] == 'Acoustic' for row in local['variants'])
                    assert client.post(ENDPOINT, json={**REQUEST, 'filters': FILTERS, 'consent_id': grant['id']}).status_code == 409
                    assert formal_hashes(app.state.database) == before_outage
                    report['checks'].append('injected_outage_requires_exact_filters_and_atomic_once_consent')
                    with app.state.database.sessions() as db:
                        assert db.scalar(select(func.count()).select_from(AIRequest)) == 0
                        assert db.scalar(select(func.count()).select_from(EmbeddingRequest)) == 0
                        for capture in db.scalars(select(RawCapture)):
                            body, _storage = checked_capture_bytes(db, capture)
                            assert hashlib.sha256(body).hexdigest() == capture.raw_hash
                            (output / f'{capture.id}.raw').write_bytes(body)
                        assert all(run.query_key == digest(REQUEST['query']) and run.query == REQUEST['query']
                                   for run in db.scalars(select(QueryRun).where(QueryRun.source_id == SOURCE)))
                    report['real_source_calls'] = source.real_calls
                    report['real_model_calls'] = 0
                    report['checks'].append('acquisition_query_identity_full_raw_bytes_and_no_model_calls')
            finally:
                app.state.database.close()


def verify_query_filter_persistence(url):
    """Synthetic inputs in the caller's dedicated acceptance DB, never dev.db."""
    from query_filter_browser_qa import FilterRegistry, SOURCE as FIXTURE_SOURCE
    model = 'Filter Persistence Tire'
    source = FilterRegistry(model)
    app = create_app(url, source)
    payload = {'query': {'model': model, 'size': '265/40R20'}, 'filters': [
        {'field': 'xl', 'op': 'eq', 'value': True},
        {'field': 'utqg_treadwear', 'op': 'gte', 'value': 300}], 'fallback_policy': 'ask'}
    endpoint = f'/v1/sources/{FIXTURE_SOURCE}/live-query'
    try:
        with TestClient(app) as client:
            live = accepted(client.post(endpoint, json=payload))
            assert live['selection']['source_count'] == 6 and live['selection']['matched_count'] == 2
            source.mode = 'offline'
            pending = accepted(client.post(endpoint, json=payload))
            grant = accepted(client.post('/v1/fallback-consents', json={
                'query_id': pending['query_id'], 'decision': 'allow'}), 201)
            assert client.post(endpoint, json={**payload, 'filters': [], 'consent_id': grant['id']}).status_code == 403
            checkpoint = {'source_id': FIXTURE_SOURCE, 'query': payload['query'],
                          'live_id': live['query_id'], 'pending_id': pending['query_id'],
                          'consent_id': grant['id'], 'snapshot_id': live['provenance'][0]['snapshot_id'],
                          'filters': live['selection']['filters'],
                          'variant_ids': sorted(row['id'] for row in live['variants'])}
    finally:
        app.state.database.close()
    assert_query_filter_checkpoint(url, checkpoint)
    return checkpoint


def assert_query_filter_checkpoint(url, checkpoint):
    from tire_api.domain import LiveQueryRequest
    from tire_api.service import QueryService
    from query_filter_browser_qa import FilterRegistry
    database = Database(url)
    try:
        database.initialize()
        with database.sessions() as db:
            live = db.get(QueryRun, checkpoint['live_id'])
            pending = db.get(QueryRun, checkpoint['pending_id'])
            consent = db.get(FallbackConsent, checkpoint['consent_id'])
            assert live.selection_filters == pending.selection_filters == checkpoint['filters']
            assert live.query == pending.query == checkpoint['query']
            assert live.query_key == pending.query_key == digest(checkpoint['query'])
            assert consent.used_at is None and consent.query_id == pending.id
            snapshot = db.get(Snapshot, checkpoint['snapshot_id'])
            assert len(snapshot.parsed_variants) == 6
            service = QueryService(db, FilterRegistry(checkpoint['query']['model']))
            response = service.result(live, snapshot)
            assert sorted(row['id'] for row in response['variants']) == checkpoint['variant_ids']
            assert response['selection']['source_count'] == 6 and response['selection']['matched_count'] == 2
            # Reject changed scope before expiry/claim, without a new audit row.
            from fastapi import HTTPException
            try:
                service.consume_consent(checkpoint['source_id'], LiveQueryRequest(
                    query=checkpoint['query'], filters=[], consent_id=consent.id),
                    pending.session_id, pending.query_key)
            except HTTPException as error:
                assert error.status_code == 403
            else:
                raise AssertionError('restored_consent_scope_not_enforced')
            assert consent.used_at is None
    finally:
        database.close()


def main():
    output = ROOT / '.artifacts/query-filters' / ('real-' + uuid4().hex)
    output.mkdir(parents=True)
    report = {'status': 'running', 'checks': [], 'scope': 'live_michelin_with_explicit_outage_injection'}
    try:
        live_run(output, report)
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['error_type'] = type(error).__name__
        raise
    finally:
        (output / 'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'status': report['status'], 'checks': report['checks'],
                          'report': str(output / 'acceptance.json')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
