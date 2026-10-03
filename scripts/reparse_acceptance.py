"""Real public-source capture -> isolated historical parser -> non-publishing review."""
import hashlib
import json
from pathlib import Path
import tempfile
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tire_api.db import (ChangeEvent, FactVersion, QueryRun, RawCapture, Snapshot, Verification)
from tire_api.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def accepted(response, status=200):
    assert response.status_code == status, f'Unexpected HTTP status: {response.status_code}'
    return response.json()


def main():
    output = ROOT / '.artifacts/reparse' / ('real-' + uuid4().hex)
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='tire-reparse-real-') as directory:
        app = create_app('sqlite:///' + (Path(directory) / 'acceptance.db').as_posix())
        with TestClient(app) as client:
            live = accepted(client.post('/v1/sources/hankook-us/live-query', json={
                'query': {'model': 'Ventus S1 evo3', 'size': '205/45R17'}, 'fallback_policy': 'never'}))
            assert live['data_state'] == 'live' and len(live['variants']) == 2, live.get('reason')
            captures = accepted(client.get('/v1/captures?mode=history&source_id=hankook-us'))['items']
            capture = next(row for row in captures if row['query_id'] == live['query_id'])
            raw = accepted(client.get(capture['evidence_path']))
            assert hashlib.sha256(raw['body'].encode()).hexdigest() == capture['raw_hash']
            catalog = accepted(client.get('/v1/reparse/catalog?mode=history'))
            parser = next(row for row in catalog['parsers'] if row['source_id'] == 'hankook-us')
            tables = (Snapshot, Verification, FactVersion, ChangeEvent, RawCapture, QueryRun)
            with app.state.database.sessions() as db:
                before = [db.scalar(select(func.count()).select_from(table)) for table in tables]
            health_before = accepted(client.get('/v1/source-health'))
            payload = {'mode': 'history', 'capture_id': capture['id'],
                'parser_version': parser['parser_version'], 'parser_digest': parser['parser_digest']}
            headers = {'Idempotency-Key': str(uuid4())}
            run = accepted(client.post('/v1/reparse/runs', json=payload, headers=headers), 201)
            assert run['state'] == 'completed' and run['accepted_as_facts'] is False, run.get('completion')
            assert run['data_state'] == 'local_snapshot' and run['input']['raw_hash'] == capture['raw_hash']
            assert accepted(client.post('/v1/reparse/runs', json=payload, headers=headers), 201)['id'] == run['id']
            codes = sorted(row['manufacturer_product_code'] for row in run['completion']['candidate'])
            assert codes == sorted(row['manufacturer_product_code'] for row in live['variants'])
            assert run['completion']['diff']['total_changed_fields'] == 0
            assert not run['completion']['quality']['reason_codes']
            reviewed = accepted(client.post('/v1/reparse/runs/' + run['id'] + '/reviews', json={
                'mode': 'history', 'expected_revision': 0, 'status': 'reviewed',
                'operator': 'Local acceptance', 'reason': '核对官网原文与固定 Parser 的历史输出；不批准新事实。'}), 201)
            assert reviewed['review_revision'] == 1 and reviewed['accepted_as_facts'] is False
            assert reviewed['completion']['fingerprint'] == run['completion']['fingerprint']
            with app.state.database.sessions() as db:
                assert before == [db.scalar(select(func.count()).select_from(table)) for table in tables]
            health_after = accepted(client.get('/v1/source-health'))
            assert health_before['sources'] == health_after['sources']
            result = {'status': 'passed', 'source': capture['source_url'], 'raw_hash': capture['raw_hash'],
                'raw_bytes': capture['byte_count'], 'product_codes': codes, 'parser': run['parser'],
                'receipt': run['completion']['receipt'], 'completion_fingerprint': run['completion']['fingerprint'],
                'model_calls': 0, 'checks': ['real_online_source_with_isolated_parser', 'durable_verified_raw_object',
                    'historical_isolated_reparse', 'same_uuid_reuses_frozen_run', 'exact_sku_output_matches',
                    'frozen_quality_and_diff', 'append_only_historical_review',
                    'no_facts_verification_query_or_source_health_change']}
            (output / 'acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({**result, 'output_directory': str(output)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
