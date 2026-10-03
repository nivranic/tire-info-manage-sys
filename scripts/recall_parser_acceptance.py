"""Live NHTSA evidence through historical replay and A/B/A sealed code releases.

B differs from A only by a comment in a private trusted installation. Official
payloads stay unchanged; distinct-behavior upgrades and loss gates are covered
separately with synthetic fixtures. No development database or model is used.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from tire_api import parser_bundles as bundles, parser_runtime as runtime
from tire_api.db import FactVersion, RawCapture, TireVariant
from tire_api.main import create_app
from tire_api.parser_releases import register_deployed_bundle
from tire_api.recall_discovery import RecallSearchSnapshot, RecallSearchVerification
from tire_api.recall_models import RecallEvent, RecallRevision, RecallSnapshot, RecallVerification

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'nhtsa-us-recalls'
SIGNED = {'operator': '本机召回发布验收', 'reason': '真实原文、临时注释候选代码；不代表人工 Golden Set 或产品适用认证'}
FORMAL = (RecallSnapshot, RecallVerification, RecallRevision, RecallEvent,
          RecallSearchSnapshot, RecallSearchVerification, TireVariant, FactVersion, RawCapture)


def accepted(response, status=200):
    assert response.status_code == status, f'unexpected_http_{response.status_code}'
    return response.json()


def fingerprint(database):
    result = {}
    with database.sessions() as db:
        for table in FORMAL:
            rows = db.scalars(select(table)).all()
            hashes = []
            for row in rows:
                values = {column.name: getattr(row, column.name) for column in table.__table__.columns}
                hashes.append(hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False,
                    separators=(',', ':'), default=str).encode()).hexdigest())
            result[table.__tablename__] = sorted(hashes)
    return result


def verify_receipt(receipt, bundle_id, revision=None):
    assert receipt['bundle_id'] == bundle_id
    if revision is not None:
        assert receipt['deployment_revision'] == revision
    assert receipt['reaped'] and receipt['exit_code'] == 0 and receipt['pid'] > 0
    assert len(receipt['input_hash']) == 64 and len(receipt['execution_digest']) == 64


def run(output, report):
    with tempfile.TemporaryDirectory(prefix='tire-recall-parser-real-') as directory:
        root = Path(directory)
        source = root / 'trusted-install' / 'tire_api'
        installed = Path(runtime.__file__).parent
        for path in installed.rglob('*.py'):
            target = source / path.relative_to(installed)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        with patch.object(bundles, '_ROOT', source), patch.dict(os.environ, {
            'TI_PARSER_BUNDLE_ROOT': str(root / 'bundles'), 'TI_OBJECT_STORE_BACKEND': 'filesystem',
            'TI_OBJECT_STORE_ROOT': str(root / 'objects'), 'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0'}):
            app = create_app('sqlite:///' + (root / 'acceptance.db').as_posix())
            with TestClient(app) as client:
                previous_request = 0.0
                queries = {'search': {'search': 'XCELLENT ROADBREAKER', 'offset': 0},
                           'campaign': {'campaign_number': '26T008000'}}
                paths = {'search': '/v1/recalls/search', 'campaign': '/v1/recalls/live-query'}
                all_receipts, observations = [], []

                def live(kind, revision, bundle_id=None):
                    nonlocal previous_request
                    time.sleep(max(0, previous_request + 2.1 - time.monotonic()))
                    previous_request = time.monotonic()
                    response = accepted(client.post(paths[kind], json={
                        'query': queries[kind], 'fallback_policy': 'never'}))
                    report['last_source_state'] = {kind: {'state': response['data_state'], 'reason': response.get('reason')}}
                    assert response['data_state'] == 'live', 'real_source_unavailable'
                    evidence = accepted(client.get(response['provenance'][0]['evidence_path']))
                    assert hashlib.sha256(evidence['body'].encode()).hexdigest() == evidence['raw_hash']
                    identity = evidence['parser_identity']
                    assert identity['deployment_revision'] == revision
                    assert bundle_id is None or identity['bundle_id'] == bundle_id
                    execution = accepted(client.get('/v1/parser-executions/' + response['query_id'] + '?mode=history'))
                    receipt = execution['completion']['receipt']
                    verify_receipt(receipt, identity['bundle_id'], revision)
                    all_receipts.append({'kind': kind, 'query_id': response['query_id'], 'receipt': receipt})
                    observations.append({'kind': kind, 'revision': revision, 'raw_hash': evidence['raw_hash'],
                        'raw_bytes': len(evidence['body'].encode()), 'snapshot_id': evidence['id']})
                    (output / f'{revision}-{kind}-body.json').write_text(evidence['body'], encoding='utf-8')
                    records = response['products'] if kind == 'search' else response['records']
                    assert records and all(row['applicability'] == 'not_assessed' for row in records)
                    return response, identity

                report['step'] = 'real_initial_search_and_campaign'
                search, identity = live('search', 1)
                assert any(row['campaign_number'] == '26T008000' for product in search['products'] for row in product['campaigns'])
                first, _ = live('campaign', 1, identity['bundle_id'])
                first_bundle = identity['bundle_id']
                query_ids = {search['query_id'], first['query_id']}
                captures = [row for row in accepted(client.get('/v1/captures', params={
                    'mode': 'history', 'source_id': SOURCE}))['items'] if row['query_id'] in query_ids]
                assert len(captures) == 2
                report['checks'].append('real_source_both_query_shapes_with_sealed_execution_and_raw_objects')
                before = fingerprint(app.state.database)

                report['step'] = 'historical_replay_and_review'
                catalog = accepted(client.get('/v1/reparse/catalog', params={'mode': 'history', 'bundle_id': first_bundle}))
                descriptor = next(row for row in catalog['parsers'] if row['source_id'] == SOURCE)
                replayed = []
                for capture in captures:
                    replay = accepted(client.post('/v1/reparse/runs', headers={'Idempotency-Key': str(uuid4())}, json={
                        'mode': 'history', 'capture_id': capture['id'], 'bundle_id': first_bundle,
                        'parser_version': descriptor['parser_version'], 'parser_digest': descriptor['parser_digest']}), 201)
                    assert replay['state'] == 'completed' and replay['accepted_as_facts'] is False
                    assert not replay['completion']['quality_blocked']
                    assert replay['completion']['diff']['total_changed_fields'] == 0
                    verify_receipt(replay['completion']['receipt'], first_bundle)
                    reviewed = accepted(client.post('/v1/reparse/runs/' + replay['id'] + '/reviews', json={
                        'mode': 'history', 'expected_revision': 0, 'status': 'reviewed', **SIGNED}), 201)
                    assert reviewed['review_revision'] == 1
                    replayed.append(replay['id'])
                assert fingerprint(app.state.database) == before
                report['checks'].append('historical_replay_and_review_preserve_all_formal_rows')

                report['step'] = 'register_distinct_comment_only_candidate'
                with (source / 'adapters' / 'nhtsa.py').open('a', encoding='utf-8') as stream:
                    stream.write('\n# Private live acceptance candidate B: payload semantics deliberately unchanged.\n')
                with app.state.database.sessions() as db:
                    candidate = register_deployed_bundle(db, **SIGNED)
                second_bundle = candidate['id']
                assert first_bundle != second_bundle
                evaluation = accepted(client.post('/v1/parser-evaluations', headers={'Idempotency-Key': str(uuid4())}, json={
                    'mode': 'history', 'source_id': SOURCE, 'target_bundle_id': second_bundle,
                    'capture_ids': [row['id'] for row in captures], 'expected_deployment_revision': 1}), 201)
                assert evaluation['state'] == 'completed' and evaluation['can_approve']
                assert not evaluation['completion']['hard_blocks'] and not evaluation['completion']['reference_gaps']
                for sample in evaluation['completion']['results']:
                    verify_receipt(sample['candidate_receipt'], second_bundle)
                    verify_receipt(sample['control_receipt'], first_bundle)
                    assert sample['diff']['total_changed_fields'] == 0
                reviewed = accepted(client.post('/v1/parser-evaluations/' + evaluation['id'] + '/reviews', json={
                    'mode': 'history', 'expected_revision': 0, 'action': 'approve', 'acknowledged': True,
                    'completion_fingerprint': evaluation['completion']['fingerprint'], **SIGNED}), 201)
                assert reviewed['review_revision'] == 1 and fingerprint(app.state.database) == before
                report['checks'].append('two_shape_same_raw_evaluation_and_approval_do_not_adopt_history')

                def transition(action, revision, **extra):
                    return accepted(client.post(f'/v1/parser-deployments/{SOURCE}/transitions',
                        headers={'Idempotency-Key': str(uuid4())}, json={
                            'action': action, 'expected_revision': revision, **SIGNED, **extra}), 201)

                report['step'] = 'activate_candidate_then_live_verify'
                transition('activate', 1, target_bundle_id=second_bundle, evaluation_id=evaluation['id'], expected_review_revision=1)
                assert fingerprint(app.state.database) == before
                live('search', 2, second_bundle)
                live('campaign', 2, second_bundle)
                after_upgrade = fingerprint(app.state.database)
                report['step'] = 'rollback_original_then_live_verify'
                transition('rollback', 2, target_revision=1)
                assert fingerprint(app.state.database) == after_upgrade
                live('search', 3, first_bundle)
                live('campaign', 3, first_bundle)
                for run_id in replayed:
                    replay = accepted(client.get('/v1/reparse/runs/' + run_id + '?mode=history'))
                    assert replay['baseline_current'] is False
                    assert replay['parser']['bundle_id'] == first_bundle
                current = fingerprint(app.state.database)
                assert not current['tire_variants'] and not current['fact_versions']
                assert all(set(values) <= set(current[table]) for table, values in before.items())
                report['checks'].extend(['distinct_code_a_b_a_revisions_force_new_live_bodies_for_both_shapes',
                    'release_and_rollback_do_not_mutate_formal_history', 'frozen_replay_tracks_stale_latest_baseline',
                    'all_real_children_reaped_and_input_bound', 'recall_never_creates_tire_facts_or_claims_applicability'])
                report.update(status='passed', bundle_ids=[first_bundle, second_bundle],
                    evaluation_id=evaluation['id'], reparse_ids=replayed, observations=observations,
                    final_formal_counts={table: len(values) for table, values in current.items()}, model_calls=0)
                (output / 'receipts.json').write_text(json.dumps(all_receipts, ensure_ascii=False, indent=2), encoding='utf-8')
                (output / 'evaluation.json').write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    output = ROOT / '.artifacts/recall-parsers' / ('real-' + uuid4().hex)
    output.mkdir(parents=True)
    report = {'status': 'running', 'scope': 'live_nhtsa_distinct_comment_only_code_a_b_a',
              'notice': 'Candidate B is a local code-copy simulation with unchanged payload semantics.', 'checks': []}
    try:
        run(output, report)
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__)
    (output / 'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': report['status'], 'step': report.get('step'), 'checks': len(report['checks']),
                      'output_directory': str(output)}, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
