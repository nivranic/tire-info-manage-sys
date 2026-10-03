"""Real public-source evidence to three frozen report formats; zero model calls."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import tempfile
from uuid import uuid4

from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import func, select

from tire_api.ai_models import AIRequest
from tire_api.db import EvidenceDocument, RawCapture, Snapshot
from tire_api.knowledge_models import KnowledgeDocument
from tire_api.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def accepted(response, expected=200):
    assert response.status_code == expected, response.status_code
    return response.json()


def main():
    output = ROOT / '.artifacts' / 'reports' / ('real-' + uuid4().hex)
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='tire-report-real-') as directory:
        app = create_app('sqlite:///' + (Path(directory) / 'acceptance.db').as_posix())
        with TestClient(app) as client:
            live = accepted(client.post('/v1/sources/hankook-us/live-query', json={
                'query': {'model': 'Ventus S1 evo3', 'size': '205/45R17'}, 'fallback_policy': 'never'}))
            assert live['data_state'] == 'live' and live['variants'], live.get('reason')
            pack = accepted(client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [
                {'kind': 'tire', 'snapshot_id': row['snapshot_id'], 'variant_id': row['id']}
                for row in live['variants']]}))['pack']
            tables = (Snapshot, RawCapture, EvidenceDocument, KnowledgeDocument, AIRequest)
            with app.state.database.sessions() as db:
                before = [db.scalar(select(func.count()).select_from(table)) for table in tables]
            payload = {'mode': 'history', 'pack_id': pack['id'],
                'title': '韩泰 Ventus S1 evo3 · 205/45R17 来源证据报告',
                'notes': '来自本次真实官网采集的历史副本；无模型分析，不构成选胎或安全适配结论。'}
            headers = {'Idempotency-Key': str(uuid4())}
            report = accepted(client.post('/v1/reports', json=payload, headers=headers), 201)
            assert accepted(client.post('/v1/reports', json=payload, headers=headers), 201)['id'] == report['id']
            assert report['body']['data_state'] == 'local_snapshot' and report['body']['analysis'] is None
            downloads = {}
            for format_name, suffix in [('markdown', 'md'), ('html', 'html'), ('pdf', 'pdf')]:
                receipt = accepted(client.post('/v1/reports/' + report['id'] + '/exports',
                                               json={'revision': 1, 'format': format_name}), 201)
                file = client.get(receipt['content_url'])
                assert file.status_code == 200 and len(file.content) == receipt['byte_count']
                assert hashlib.sha256(file.content).hexdigest() == receipt['sha256'] == file.headers['x-report-sha256']
                assert 'attachment;' in file.headers['content-disposition'] and file.headers['cache-control'] == 'no-store'
                (output / ('hankook-evidence.' + suffix)).write_bytes(file.content)
                downloads[format_name] = {'sha256': receipt['sha256'], 'byte_count': receipt['byte_count']}
                if format_name == 'pdf':
                    reader = PdfReader(BytesIO(file.content))
                    extracted = ''.join(page.extract_text() for page in reader.pages)
                    assert all(row['manufacturer_product_code'] in extracted for row in live['variants'])
                    assert '韩泰' in extracted and '历史' in extracted
                    downloads[format_name]['pages'] = len(reader.pages)
                else:
                    text = file.content.decode('utf-8')
                    assert all(row['manufacturer_product_code'] in text for row in live['variants'])
                    if format_name == 'html':
                        assert '<script' not in text.lower()
            with app.state.database.sessions() as db:
                assert before == [db.scalar(select(func.count()).select_from(table)) for table in tables]
            result = {'status': 'passed', 'source': live['provenance'][0]['source_url'],
                'product_codes': [row['manufacturer_product_code'] for row in live['variants']],
                'pack_fingerprint': pack['fingerprint'], 'body_hash': report['body_hash'], 'downloads': downloads,
                'model_calls': 0, 'checks': ['real_online_source', 'exact_selected_pack', 'historical_report_without_ai',
                    'idempotent_report_save', 'three_verified_downloads', 'pdf_chinese_and_sku_text',
                    'no_source_model_or_knowledge_side_effect']}
            (output / 'acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({**result, 'output_directory': str(output)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
