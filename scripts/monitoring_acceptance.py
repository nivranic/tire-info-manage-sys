"""Real online scheduler evidence; simulated local rules in a temporary database."""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tire_api.ai_models import AIRequest
from tire_api.main import create_app


def main():
    spec = importlib.util.spec_from_file_location('acceptance_monitor', Path(__file__).resolve().parents[1] / 'apps/worker/monitor.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    with tempfile.TemporaryDirectory(prefix='tire-monitoring-acceptance-') as directory:
        app = create_app('sqlite:///' + (Path(directory) / 'monitor.db').as_posix())
        with TestClient(app) as client:
            response = client.post('/v1/alert-rules', json={'name': '真实来源调度验收，模拟用户规则',
                'source_id': 'hankook-us', 'query': {'model': 'Ventus S1 evo3', 'size': '205/45R17'},
                'enabled': True, 'kinds': ['variant_observed', 'facts_changed']})
            assert response.status_code == 201, response.status_code
            rule = response.json()
            cycle = asyncio.run(worker.run_scheduled_cycle(app.state.database, max_jobs=1))
            assert cycle['jobs'] == 1 and cycle['results'][0]['state'] == 'live' and cycle['results'][0]['finalized'], cycle
            notices = client.get('/v1/notifications').json()['items']
            assert len(notices) >= 2 and all(item['kind'] == 'variant_observed' and item['previous_snapshot_id'] is None for item in notices)
            hashes = set()
            for notice in notices:
                evidence = client.get('/v1/evidence/' + notice['snapshot_id']).json()
                assert hashlib.sha256(evidence['body'].encode()).hexdigest() == evidence['raw_hash']
                hashes.add(evidence['raw_hash'])
            prepared = client.post('/v1/ai/evidence-packs', json={'mode': 'history',
                'references': [{'kind': 'change_event', 'change_id': notices[0]['change_id']}]})
            assert prepared.status_code == 200, prepared.status_code
            pack = prepared.json()['pack']
            assert pack['data_state'] == 'local_snapshot' and pack['privacy_class'] == 'public'
            assert pack['evidence'][0]['change_id'] == notices[0]['change_id']
            assert pack['evidence'][0]['raw_hash'] in hashes and not pack['evidence'][0]['previous_snapshot_id']
            assert any('不代表产品刚发布' in fact['text'] for fact in pack['facts'])
            with app.state.database.sessions() as db:
                assert db.scalar(select(func.count()).select_from(AIRequest)) == 0
            assert asyncio.run(worker.run_scheduled_cycle(app.state.database, max_jobs=1))['jobs'] == 0
            assert client.get('/v1/notifications').json()['total'] == len(notices)
            assert client.put('/v1/notifications/' + notices[0]['id'] + '/read', json={'read': True}).status_code == 200
            assert client.get('/v1/notifications?unread=true').json()['total'] == len(notices) - 1
            path = '/v1/alert-rules/' + rule['id']
            assert client.post(path + '/state', json={'expected_revision': 1, 'action': 'archive'}).status_code == 200
            restored = client.post(path + '/state', json={'expected_revision': 2, 'action': 'restore'}).json()
            assert restored['enabled'] is False and restored['revision'] == 3
            assert client.get('/v1/notifications').json()['total'] == len(notices)
            print(json.dumps({'status': 'passed', 'scope': 'Real Hankook online response; synthetic personal rules in temporary DB',
                'product_codes': [notice['identity']['manufacturer_product_code'] for notice in notices], 'raw_hashes': sorted(hashes),
                'change_pack_fingerprint': pack['fingerprint'], 'model_calls': 0,
                'checks': ['real_scheduled_online_query', 'first_observation_not_release_claim', 'cited_evidence_hashes',
                           'frozen_change_to_ai_evidence_no_model', 'not_due_no_extra_fetch_or_alert', 'persistent_read_receipt',
                           'archive_restore_preserves_alerts_and_stays_paused']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
