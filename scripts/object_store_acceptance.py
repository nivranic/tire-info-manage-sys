"""Real source receipt in a temporary filesystem store; synthetic PDF upload only."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
from tire_api.main import create_app


def main():
    with tempfile.TemporaryDirectory(prefix='tire-object-acceptance-') as directory:
        url = 'sqlite:///' + (Path(directory) / 'evidence.db').as_posix()
        with TestClient(create_app(url)) as client:
            live = client.post('/v1/sources/hankook-us/live-query', json={
                'query': {'model': 'Ventus S1 evo3', 'size': '205/45R17'}, 'fallback_policy': 'never'}).json()
            assert live['data_state'] == 'live', live.get('reason')
            capture = client.get('/v1/captures?mode=history').json()['items'][0]
            detail = client.get(capture['evidence_path']).json()
            assert detail['storage_kind'] == 'object_store'
            assert hashlib.sha256(detail['body'].encode()).hexdigest() == detail['raw_hash'] == live['provenance'][0]['raw_hash']
            pdf = b'%PDF-1.7\n%\xff\xfe Synthetic receipt, no tire claims\n%%EOF'
            metadata = {'title': '自动验收二进制文件，不是官方资料', 'operator': '自动化验收',
                        'rights_basis': '项目生成的合成字节，仅用于收件和下载测试', 'source_url': ''}
            response = client.post('/v1/documents', content=pdf, headers={'content-type': 'application/pdf',
                'x-evidence-metadata': base64.b64encode(json.dumps(metadata, ensure_ascii=False).encode()).decode()})
            assert response.status_code == 201
            document = response.json()
            assert document['accepted_as_facts'] is False
            content_url = '/v1/documents/' + document['id'] + '/content?mode=history'
            assert client.get(content_url).content == pdf
        with TestClient(create_app(url)) as restarted:
            assert restarted.get(content_url).content == pdf
            assert restarted.get(capture['evidence_path']).json()['body'] == detail['body']
            print(json.dumps({'status': 'passed', 'scope': 'Real Hankook text receipt, synthetic PDF, isolated local object store',
                'source_hash': detail['raw_hash'], 'source_bytes': capture['byte_count'], 'pdf_hash': document['raw_hash'],
                'checks': ['real_online_source', 'pre_parser_receipt_object_reference', 'object_and_snapshot_hash_agree',
                           'binary_pdf_exact_roundtrip', 'document_not_promoted_to_facts', 'restart_preserves_object_reads']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
