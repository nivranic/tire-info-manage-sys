"""Real official-source evidence through local historical search; no cloud model calls.

An isolated temporary database is populated by the normal Hankook live adapter.
Search success proves retrieval mechanics, not semantic recall or an AI answer.
"""
from pathlib import Path
import json
import tempfile

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tire_api.ai_models import AIRequest
from tire_api.db import RawCapture, Snapshot
from tire_api.main import create_app


def search(client, **payload):
    response = client.post('/v1/knowledge/search', json={'mode': 'history', **payload})
    assert response.status_code == 200, response.status_code
    return response.json()


def main():
    with tempfile.TemporaryDirectory(prefix='tire-knowledge-real-') as directory:
        url = 'sqlite:///' + (Path(directory) / 'acceptance.db').as_posix()
        app = create_app(url)
        with TestClient(app) as client:
            response = client.post('/v1/sources/hankook-us/live-query', json={
                'query': {'model': 'Ventus S1 evo3', 'size': '205/45R17'}, 'fallback_policy': 'never'})
            assert response.status_code == 200
            live = response.json()
            assert live['data_state'] == 'live' and live['variants'], live.get('reason')
            ids = {v['id'] for v in live['variants']}
            with app.state.database.sessions() as db:
                before = [db.scalar(select(func.count()).select_from(t)) for t in (RawCapture, Snapshot, AIRequest)]
            exact = search(client, filters={'source_id': 'hankook-us', 'size': '205/45R17', 'model': 'Ventus S1 evo3'})
            assert {r['reference']['variant_id'] for r in exact['items']} == ids
            assert exact['data_state'] == 'local_snapshot'
            words = search(client, text='Ventus', filters={'source_id': 'hankook-us'})
            assert {r['reference']['variant_id'] for r in words['items']} == ids
            assert any(s['state'] == 'succeeded' and 'fts' in s['name'].lower() for s in words['stages'])
            prepared = client.post('/v1/ai/evidence-packs', json={'mode': 'history',
                'references': [row['reference'] for row in exact['items']]})
            assert prepared.status_code == 200
            pack = prepared.json()['pack']
            assert pack['data_state'] == 'local_snapshot' and pack['privacy_class'] == 'public'
            with app.state.database.sessions() as db:
                assert [db.scalar(select(func.count()).select_from(t)) for t in (RawCapture, Snapshot, AIRequest)] == before
            reference = words['items'][0]['reference']
        with TestClient(create_app(url)) as client:
            restored = search(client, text='Ventus', filters={'source_id': 'hankook-us'})
            assert reference in [row['reference'] for row in restored['items']]
        print(json.dumps({'status': 'passed', 'source': live['provenance'][0]['source_url'],
            'engine': exact['index']['engine'], 'variants': len(ids), 'pack_fingerprint': pack['fingerprint'],
            'scope': 'real online source then explicit historical retrieval in temporary SQLite; zero model calls',
            'checks': ['exact_identity', 'actual_full_text_search', 'historical_state', 'precise_reference_to_pack',
                       'no_capture_snapshot_or_model_side_effect', 'restart_search']}))


if __name__ == '__main__':
    main()
