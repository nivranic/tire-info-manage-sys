"""Real source facts; simulated saved research/preferences only in a temporary DB."""
import json
import hashlib
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
from tire_api.main import create_app


def main():
    with tempfile.TemporaryDirectory(prefix='tire-research-acceptance-') as directory:
        app = create_app('sqlite:///' + (Path(directory) / 'research.db').as_posix())
        with TestClient(app) as client:
            live = client.post('/v1/sources/hankook-us/live-query', json={
                'query': {'model': 'Ventus S1 evo3', 'size': '205/45R17'}, 'fallback_policy': 'never'}).json()
            assert live['data_state'] == 'live' and len(live['variants']) >= 2, live.get('reason')
            variant_ids = [row['id'] for row in live['variants'][:2]]
            compared = client.post('/v1/compare', json={'variant_ids': variant_ids}).json()
            assert compared['variants'] and len(compared['fingerprint']) == 64
            response = client.post('/v1/saved-comparisons', json={
                'variant_ids': variant_ids, 'expected_fingerprint': compared['fingerprint'],
                'title': '自动验收保存记录，不代表用户研究结论', 'notes': '真实来源参数，临时库模拟保存'} )
            assert response.status_code == 201
            saved = response.json()
            path = '/v1/saved-comparisons/' + saved['id']
            assert client.put(path, json={'expected_revision': 1, 'title': '模拟编辑后的记录', 'notes': '不改变固定事实'}).status_code == 200
            for revision, action in [(2, 'archive'), (3, 'restore')]:
                assert client.post(path + '/state', json={'expected_revision': revision, 'action': action}).status_code == 200
            detail = client.get(path + '?mode=history').json()
            assert detail['comparison'] == compared and len(detail['history']) == 4
            weights = {'dry': 20, 'wet': 25, 'quiet': 20, 'comfort': 10, 'wear': 15, 'energy': 5, 'appearance': 5}
            assert client.put('/v1/driving-preferences', json={'expected_revision': 0, 'weights': weights}).status_code == 200
            assert client.post('/v1/compare', json={'variant_ids': variant_ids}).json() == compared
            cleared = client.post('/v1/driving-preferences/clear', json={'expected_revision': 1}).json()
            assert cleared['weights'] is None and cleared['history'][1]['weights'] == weights
            evidence = client.get('/v1/evidence/' + compared['provenance'][0]['snapshot_id']).json()
            assert evidence['raw_hash'] == compared['provenance'][0]['raw_hash']
            assert hashlib.sha256(evidence['body'].encode()).hexdigest() == live['provenance'][0]['raw_hash']
            print(json.dumps({'status': 'passed', 'scope': 'Real Hankook facts; simulated saved comparison and weights in a temporary DB',
                'product_codes': [row['manufacturer_product_code'] for row in compared['variants']],
                'raw_hash': evidence['raw_hash'], 'fingerprint': compared['fingerprint'],
                'checks': ['real_source_two_sku_query', 'frozen_comparison_and_evidence',
                           'metadata_archive_restore_history', 'preferences_do_not_change_comparison',
                           'clear_preferences_preserves_history', 'original_evidence_unchanged']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
