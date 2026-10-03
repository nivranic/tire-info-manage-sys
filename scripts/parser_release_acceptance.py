"""Real official source and sealed deployment receipts in a private temporary database.

This changes only the deployment revision of the SAME trusted code. Distinct A/B/A
executable behavior is tested separately with synthetic trusted source installs.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tire_api.db import FactVersion, RawCapture, Snapshot, Verification
from tire_api.main import create_app
from tire_api.parser_release_models import ParserBundle, ParserExecution

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'hankook-us'


def accepted(response, status=200):
    assert response.status_code == status, f'Unexpected HTTP status: {response.status_code}'
    return response.json()


def main():
    output = ROOT / '.artifacts/parser-releases' / ('real-' + uuid4().hex)
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='tire-release-real-') as directory, patch.dict(os.environ, {
            'TI_PARSER_BUNDLE_ROOT': str(Path(directory) / 'bundles'), 'TI_AI_ENABLED': '0', 'TI_EMBEDDINGS_ENABLED': '0'}):
        app = create_app('sqlite:///' + (Path(directory) / 'acceptance.db').as_posix())
        with TestClient(app) as client:
            query = {'query': {'model': 'Ventus S1 evo3', 'size': '205/45R17'}, 'fallback_policy': 'never'}
            def live():
                value = accepted(client.post(f'/v1/sources/{SOURCE}/live-query', json=query))
                assert value['data_state'] == 'live', value.get('reason')
                return value
            first = live()
            capture = accepted(client.get('/v1/captures?mode=history&source_id=' + SOURCE))['items'][0]
            raw = accepted(client.get(capture['evidence_path']))
            assert hashlib.sha256(raw['body'].encode()).hexdigest() == capture['raw_hash']
            deployed = accepted(client.get(f'/v1/parser-deployments/{SOURCE}?mode=history'))
            assert deployed['revision'] == 1 and deployed['bundle_id'] == capture['parser_identity']['bundle_id']
            signed = {'operator': '本机同代码包验收', 'reason': '核对同一真实原文与同一代码包；不宣称人工 Golden Set'}
            tables = (Snapshot, Verification, FactVersion, RawCapture)
            def counts():
                with app.state.database.sessions() as db:
                    return [db.scalar(select(func.count()).select_from(table)) for table in tables]
            before = counts()
            evaluation = accepted(client.post('/v1/parser-evaluations', headers={'Idempotency-Key': str(uuid4())}, json={
                'mode': 'history', 'source_id': SOURCE, 'target_bundle_id': deployed['bundle_id'],
                'capture_ids': [capture['id']], 'expected_deployment_revision': 1}), 201)
            assert evaluation['state'] == 'completed' and not evaluation['completion']['hard_blocks']
            assert evaluation['completion']['results'][0]['diff']['total_changed_fields'] == 0
            approved = accepted(client.post('/v1/parser-evaluations/' + evaluation['id'] + '/reviews', json={
                'mode': 'history', 'expected_revision': 0, 'completion_fingerprint': evaluation['completion']['fingerprint'],
                'action': 'approve', 'acknowledged': True, **signed}), 201)
            assert approved['review_revision'] == 1 and before == counts()
            def transition(action, revision, **extra):
                return accepted(client.post(f'/v1/parser-deployments/{SOURCE}/transitions',
                    headers={'Idempotency-Key': str(uuid4())}, json={
                        'action': action, 'expected_revision': revision, **signed, **extra}), 201)
            transition('activate', 1, target_bundle_id=deployed['bundle_id'], evaluation_id=evaluation['id'], expected_review_revision=1)
            assert counts() == before
            second = live()
            transition('rollback', 2, target_revision=1)
            third = live()
            executions = [accepted(client.get('/v1/parser-executions/' + value['query_id'] + '?mode=history'))
                          for value in (first, second, third)]
            assert [item['completion']['receipt']['deployment_revision'] for item in executions] == [1, 2, 3]
            assert all(item['completion']['receipt']['bundle_id'] == deployed['bundle_id'] for item in executions)
            assert all(item['completion']['receipt']['reaped'] for item in executions)
            assert counts()[0] == 3 and counts()[-1] == 3  # revision changes require new 200 bodies
            from tire_api.adapters import xiaomi
            vehicle = accepted(client.post(f'/v1/vehicles/{xiaomi.CURRENT_ID}/live-fitments',
                                           json={'fallback_policy': 'never'}))
            assert vehicle['data_state'] == 'live' and vehicle['fitments'], vehicle.get('reason')
            vehicle_capture = accepted(client.get('/v1/captures?mode=history&source_id=' + xiaomi.SOURCE_ID))['items'][0]
            vehicle_execution = accepted(client.get('/v1/parser-executions/' + vehicle['query_id'] + '?mode=history'))
            vehicle_receipt = vehicle_execution['completion']['receipt']
            assert vehicle_receipt['bundle_id'] == vehicle_capture['parser_identity']['bundle_id']
            assert vehicle_receipt['deployment_revision'] == 1 and vehicle_receipt['reaped']
            result = {'status': 'passed', 'scope': 'real_source_same_code_deployment_revision_roundtrip',
                'source_url': capture['source_url'], 'raw_hash': capture['raw_hash'], 'raw_bytes': capture['byte_count'],
                'product_codes': sorted(row['manufacturer_product_code'] for row in third['variants']),
                'bundle_id': deployed['bundle_id'], 'evaluation_fingerprint': evaluation['completion']['fingerprint'],
                'receipts': [item['completion']['receipt'] for item in executions], 'model_calls': 0,
                'vehicle': {'source_id': xiaomi.SOURCE_ID, 'trims': len(vehicle['trims']),
                    'fitments': len(vehicle['fitments']), 'raw_hash': vehicle_capture['raw_hash'],
                    'raw_bytes': vehicle_capture['byte_count'], 'receipt': vehicle_receipt},
                'checks': ['real_online_archive_execution', 'preparser_raw_identity', 'same_raw_evaluation',
                    'approval_bound_to_fingerprint', 'evaluation_and_transition_do_not_adopt',
                    'revision_changes_force_new_body', 'append_only_rollback_revision', 'input_bound_receipts',
                    'children_reaped', 'real_vehicle_pinned_archive_receipt']}
            (output / 'acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'status': 'passed', 'checks': len(result['checks']), 'bundle_id': deployed['bundle_id'],
                              'output_directory': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
