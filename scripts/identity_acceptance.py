"""Real-source identity workflow simulation in an isolated temporary database.

The two real SKUs are NOT claimed equivalent or officially corrected. ``main``
only rehearses a local correct/clear decision and never calls a model. Reusable
PostgreSQL helpers below use explicitly synthetic variants, not live source data.

Run: uv run --project apps/api --extra dev python scripts/identity_acceptance.py
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tire_api.ai_models import AIRequest
from tire_api.db import FactVersion, QueryRun, RawCapture, Snapshot, TireVariant, Verification
from tire_api.identity_models import IdentityRevision
from tire_api.identity_resolution import IdentityDecision, append_decision
from tire_api.main import create_app

ROOT = Path(__file__).resolve().parents[1]
SOURCE_TABLES = (TireVariant, FactVersion, Snapshot, Verification, RawCapture)
SIMULATION = 'simulation：仅验收本地身份流程，不主张真实 SKU 等价、参数错误或厂商更正'


def accepted(response, status=200):
    assert response.status_code == status, f'Unexpected HTTP status: {response.status_code}'
    return response.json()


def source_fingerprints(database):
    """Include every source-row field, not merely counts or displayed values."""
    result = {}
    with database.engine.connect() as connection:
        for model in SOURCE_TABLES:
            rows = connection.execute(model.__table__.select()).mappings()
            serialized = sorted(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str) for row in rows)
            result[model.__tablename__] = {'rows': len(serialized),
                'sha256': hashlib.sha256('\n'.join(serialized).encode()).hexdigest()}
    return result


def decision_payload(client, origin, target, snapshots, action='correct'):
    state = accepted(client.post(f'/v1/tire-variants/{origin}/identity-preview',
                                json={'mode': 'history', 'target_id': target}))
    codes = [state['binding'][side]['identity'].get('manufacturer_product_code')
             for side in ('source', 'target') if state['binding'][side]]
    return {'mode': 'history', 'target_id': target, 'action': action,
        'expected_revision': state['revision'], 'expected_fingerprint': state['fingerprint'],
        'operator': '自动验收 simulation', 'reason': SIMULATION, 'acknowledged': True,
        'acknowledge_unknowns': bool(state['unknown_fields']),
        'field_reasons': {row['field']: SIMULATION + '；保留该项来源差异，只演练明确选择目标'
                          for row in state['differences']},
        'evidence': [{'snapshot_id': key,
            'locator': 'simulation；规格表 Product Code: ' + ' / '.join(str(code) for code in codes)}
            for key in snapshots]}


def post_decision(client, origin, payload, key=None):
    return client.post(f'/v1/tire-variants/{origin}/identity-revisions', json=payload,
                       headers={'Idempotency-Key': key or str(uuid4())})


def read_identity(client, origin):
    return accepted(client.get(f'/v1/tire-variants/{origin}/identity-resolution?mode=history'))


def compare(client, ids, *, resolve=False):
    return accepted(client.post('/v1/compare', json={'variant_ids': ids, 'resolve_identities': resolve}))


def save_comparison(client, ids, comparison):
    return accepted(client.post('/v1/saved-comparisons', json={
        'variant_ids': ids, 'resolve_identities': True, 'include_manual': False,
        'expected_fingerprint': comparison['fingerprint'], 'title': '身份流程 simulation',
        'notes': SIMULATION}), 201)


def run_real_acceptance():
    with tempfile.TemporaryDirectory(prefix='tire-identity-real-') as directory, patch.dict(os.environ, {
            'TI_PARSER_BUNDLE_ROOT': str(Path(directory) / 'bundles'),
            'TI_OBJECT_STORE_BACKEND': 'filesystem', 'TI_OBJECT_STORE_ROOT': str(Path(directory) / 'objects'),
            'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0'}):
        database_url = 'sqlite:///' + (Path(directory) / 'acceptance.db').as_posix()
        app = create_app(database_url)
        with TestClient(app) as client:
            query = {'query': {'model': 'Ventus S1 evo3', 'size': '205/45R17'}, 'fallback_policy': 'never'}
            live = accepted(client.post('/v1/sources/hankook-us/live-query', json=query))
            assert live['data_state'] == 'live', live.get('reason')
            variants = sorted(live['variants'], key=lambda row: row['manufacturer_product_code'])
            assert len(variants) >= 2, 'The real source did not return two distinct SKUs'
            origin, target = variants[:2]
            a, b = origin['id'], target['id']
            assert a != b and origin['manufacturer_product_code'] != target['manufacturer_product_code']
            snapshots = list(dict.fromkeys(item['snapshot_id'] for item in live['provenance']))
            evidence = [accepted(client.get('/v1/evidence/' + key)) for key in snapshots]
            for item in evidence:
                assert hashlib.sha256(item['body'].encode()).hexdigest() == item['raw_hash']
            original = compare(client, [a, b])
            assert [row['id'] for row in original['variants']] == [a, b]
            before = source_fingerprints(app.state.database)
            body, correction_key = decision_payload(client, a, b, snapshots), str(uuid4())
            corrected = accepted(post_decision(client, a, body, correction_key), 201)
            assert corrected['review']['resolution']['state'] == 'redirected'
            assert read_identity(client, b)['incoming'][0]['variant_id'] == a
            replay = accepted(post_decision(client, a, body, correction_key), 201)
            assert replay['idempotent_replay'] and replay['event'] == corrected['event']
            assert post_decision(client, a, body).status_code == 409
            assert post_decision(client, a, {**body, 'reason': SIMULATION + '（不同请求）'}, correction_key).status_code == 409

            ordinary = compare(client, [a, b])
            assert [row['id'] for row in ordinary['variants']] == [a, b]
            assert [row['facts'] for row in ordinary['variants']] == [row['facts'] for row in original['variants']]
            resolved = compare(client, [a, b], resolve=True)
            assert resolved['variants'] == [original['variants'][1]], 'Resolved facts must come solely from the target SKU'
            assert resolved['identity_mappings'][0]['requested_id'] == a
            assert resolved['identity_mappings'][0]['resolved_id'] == b
            saved = save_comparison(client, [a, b], resolved)

            clear_key = str(uuid4())
            cleared = accepted(post_decision(client, a, decision_payload(client, a, None, snapshots, 'clear'), clear_key), 201)
            assert cleared['review']['resolution']['state'] == 'cleared'
            assert [(item['revision'], item['action']) for item in cleared['review']['history']] == [(2, 'clear'), (1, 'correct')]
            after_clear = compare(client, [a, b], resolve=True)
            assert [row['id'] for row in after_clear['variants']] == [a, b]
            assert [row['facts'] for row in after_clear['variants']] == [row['facts'] for row in original['variants']]
            frozen = accepted(client.get('/v1/saved-comparisons/' + saved['id'] + '?mode=history'))
            assert frozen['comparison'] == resolved
            assert frozen['current_identity_resolutions'][a]['state'] == 'cleared'
            replay_after_clear = accepted(post_decision(client, a, body, correction_key), 201)
            assert replay_after_clear['event'] == corrected['event'] and replay_after_clear['idempotent_replay']
            assert replay_after_clear['review']['resolution']['state'] == 'cleared'
            after = source_fingerprints(app.state.database)
            assert before == after
            for item in evidence:
                assert accepted(client.get('/v1/evidence/' + item['id'])) == item
            with app.state.database.sessions() as db:
                assert db.scalar(select(func.count()).select_from(IdentityRevision)) == 2
                assert db.scalar(select(func.count()).select_from(AIRequest)) == 0
                assert {row.idempotency_key for row in db.scalars(select(IdentityRevision))} == {correction_key, clear_key}
            return {'status': 'passed', 'scope': 'real_source_capture_with_explicit_simulated_local_identity_decisions',
                'simulation': SIMULATION, 'real_source': 'hankook-us', 'query': query,
                'product_codes': [origin['manufacturer_product_code'], target['manufacturer_product_code']],
                'variant_ids': [a, b], 'source_variant_count': len(variants), 'model_calls': 0,
                'evidence': [{key: item[key] for key in ('id', 'source_url', 'raw_hash')} for item in evidence],
                'source_tables_before': before, 'source_tables_after': after,
                'idempotency_keys': {'correct': correction_key, 'clear': clear_key},
                'history': cleared['review']['history'], 'original_comparison': original,
                'resolved_comparison': resolved, 'comparison_after_clear': after_clear,
                'frozen_comparison': frozen['comparison'],
                'checks': ['real_hankook_capture_without_fallback', 'distinct_real_skus_retained',
                    'source_evidence_sha256', 'explicit_simulation_correct_and_clear',
                    'uuid_replay_returns_original_event_even_after_clear', 'uuid_payload_mismatch_rejected',
                    'stale_revision_rejected', 'ordinary_comparison_preserves_both_skus',
                    'resolved_comparison_uses_target_facts_only_and_deduplicates',
                    'frozen_comparison_retains_original_target_and_current_clear_notice',
                    'append_only_history_and_request_ids_retained', 'all_source_row_hashes_unchanged',
                    'zero_model_requests']}


def assert_identity_checkpoint(database_url, checkpoint):
    """Check logical/evidence relationships after an API restart or DB restore."""
    from test_core import FixtureRegistry
    app = create_app(database_url, FixtureRegistry())
    with TestClient(app, cookies=checkpoint['cookies']) as client:
        assert source_fingerprints(app.state.database) == checkpoint['source_fingerprints']
        for variant_id, expected in checkpoint['reviews'].items():
            assert read_identity(client, variant_id) == expected
        assert compare(client, checkpoint['ids'], resolve=True) == checkpoint['resolved']
        saved = accepted(client.get('/v1/saved-comparisons/' + checkpoint['saved_id'] + '?mode=history'))
        assert saved['comparison'] == checkpoint['frozen']
        assert saved['current_identity_resolutions'][checkpoint['ids'][0]]['state'] == 'cleared'
        for item in checkpoint['evidence']:
            assert accepted(client.get('/v1/evidence/' + item['id'])) == item
        for original in checkpoint['replays']:
            response = accepted(post_decision(client, original['variant_id'], original['payload'], original['key']), 201)
            assert response['idempotent_replay'] and response['event'] == original['event']
        with app.state.database.sessions() as db:
            rows = db.scalars(select(IdentityRevision).where(IdentityRevision.variant_id.in_(checkpoint['ids']))).all()
            assert len(rows) == 3 and {row.id for row in rows} == checkpoint['event_ids']


def verify_identity_persistence(database_url):
    """Synthetic PostgreSQL CAS, UUID races, withdrawal and restart acceptance."""
    from test_core import FixtureRegistry, VARIANT, success
    registry = FixtureRegistry()
    rows = [{**deepcopy(VARIANT), 'model': 'PG Identity Simulation', 'size': '245/45R19',
             'manufacturer_product_code': 'PG-IDENTITY-' + label, 'facts': {'utqg_treadwear': value}}
            for label, value in [('A', 111), ('B', 222), ('C', 333)]]
    # The third synthetic row shares B's stable code but has an unknown HL flag.
    # This permits an explicitly acknowledged merge while retaining distinct IDs.
    rows[2].update(manufacturer_product_code=rows[1]['manufacturer_product_code'], hl=None)
    registry.result = success('synthetic PostgreSQL identity evidence; no real product claim', rows)
    app = create_app(database_url, registry)
    with TestClient(app) as client:
        live = accepted(client.post('/v1/sources/fixture/live-query', json={
            'query': {'model': 'PG Identity Simulation', 'size': '245/45R19'}, 'fallback_policy': 'never'}))
        assert live['data_state'] == 'live'
        a, b, c = [row['id'] for row in live['variants']]
        snapshots = [item['snapshot_id'] for item in live['provenance']]
        before = source_fingerprints(app.state.database)
        with app.state.database.sessions() as db:
            actor = db.get(QueryRun, live['query_id']).session_id

        def race(origin, target, same_key, action='correct'):
            payload = decision_payload(client, origin, target, snapshots, action)
            gate, shared_key = Barrier(2), str(uuid4())
            keys = [shared_key, shared_key] if same_key else [str(uuid4()), str(uuid4())]
            def submit(key):
                with app.state.database.sessions() as db:
                    gate.wait(timeout=10)
                    try:
                        return append_decision(db, origin, IdentityDecision(**payload), actor, key)
                    except HTTPException as error:
                        return {'status': error.status_code}
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(submit, keys))
            successful = [(key, result) for key, result in zip(keys, results) if 'event' in result]
            if same_key:
                assert len(successful) == 2 and successful[0][1]['event'] == successful[1][1]['event']
                assert sorted(result['idempotent_replay'] for _, result in successful) == [False, True]
            else:
                assert len(successful) == 1 and [result for result in results if 'status' in result] == [{'status': 409}]
            key, result = successful[0]
            assert result['event']['revision'] == 1
            return {'variant_id': origin, 'payload': payload, 'key': key, 'event': result['event']}

        corrected = race(a, b, same_key=False)
        initial_resolved = compare(client, [a, b], resolve=True)
        assert len(initial_resolved['variants']) == 1 and initial_resolved['variants'][0]['facts']['utqg_treadwear'] == 222
        saved = save_comparison(client, [a, b], initial_resolved)
        clear_payload = decision_payload(client, a, None, snapshots, 'clear')
        cleared = accepted(post_decision(client, a, clear_payload), 201)
        assert cleared['review']['resolution']['state'] == 'cleared'
        assert post_decision(client, a, clear_payload).status_code == 409
        assert post_decision(client, a, corrected['payload']).status_code == 409
        assert post_decision(client, a, {**corrected['payload'], 'reason': SIMULATION + '（不同请求）'}, corrected['key']).status_code == 409
        duplicate = race(c, b, same_key=True, action='merge')
        ordinary = compare(client, [a, b, c])
        assert [item['facts']['utqg_treadwear'] for item in ordinary['variants']] == [111, 222, 333]
        resolved = compare(client, [a, b, c], resolve=True)
        assert [item['id'] for item in resolved['variants']] == [a, b]
        assert [item['facts']['utqg_treadwear'] for item in resolved['variants']] == [111, 222]
        reviews = {key: read_identity(client, key) for key in (a, b, c)}
        assert [item['variant_id'] for item in reviews[b]['incoming']] == [c]
        assert reviews[b]['incoming'][0]['action'] == 'merge'
        assert [(item['revision'], item['action']) for item in reviews[a]['history']] == [(2, 'clear'), (1, 'correct')]
        assert source_fingerprints(app.state.database) == before
        checkpoint = {'cookies': dict(client.cookies), 'ids': [a, b, c], 'reviews': reviews,
            'source_fingerprints': before, 'resolved': resolved, 'saved_id': saved['id'], 'frozen': initial_resolved,
            'evidence': [accepted(client.get('/v1/evidence/' + key)) for key in snapshots],
            'event_ids': {corrected['event']['id'], cleared['event']['id'], duplicate['event']['id']},
            'replays': [corrected, duplicate]}
    assert_identity_checkpoint(database_url, checkpoint)
    return checkpoint


def main():
    output = ROOT / '.artifacts/identity' / ('real-' + uuid4().hex)
    output.mkdir(parents=True)
    try:
        result = run_real_acceptance()
    except Exception as error:
        (output / 'acceptance.json').write_text(json.dumps({'status': 'failed', 'simulation': SIMULATION,
            'error_type': type(error).__name__}, ensure_ascii=False, indent=2), encoding='utf-8')
        raise
    (output / 'acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': result['status'], 'checks': len(result['checks']),
        'product_codes': result['product_codes'], 'simulation': SIMULATION, 'output_directory': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
