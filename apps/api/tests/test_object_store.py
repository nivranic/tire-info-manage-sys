import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path

import boto3
from botocore.response import StreamingBody
from botocore.stub import Stubber
import pytest
from sqlalchemy import select

from tire_api.db import CaptureObject, EvidenceDocument, EvidenceObject, RawCapture, Snapshot
from tire_api.object_store import FileObjectStore, ObjectStoreError, S3ObjectStore, MAX_OBJECT_BYTES, configured_store
from test_core import count, setup
from test_raw_captures import BODY, QUERY, URL, configure

PDF = b'%PDF-1.7\n%\xff\xfe\x00 synthetic binary receipt, not an extracted fact\n%%EOF'
META = {'title': '合成 PDF 留存测试', 'operator': '测试署名', 'rights_basis': '此测试文件由项目生成，仅验证原始字节留存', 'source_url': 'https://example.org/synthetic.pdf'}


def upload(client, data=PDF, **metadata):
    header = base64.b64encode(json.dumps({**META, **metadata}, ensure_ascii=False).encode()).decode()
    return client.post('/v1/documents', content=data, headers={'content-type': 'application/pdf', 'x-evidence-metadata': header})


def test_file_store_atomic_dedup_and_binary_integrity(tmp_path):
    store = FileObjectStore(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as workers:
        digests = list(workers.map(store.put, [PDF] * 4))
    assert len(set(digests)) == 1 and store.get(digests[0], len(PDF)) == PDF
    assert len(list(tmp_path.rglob('*.*'))) == 0  # No temporary receiving files remain.
    path = store.path(digests[0])
    path.write_bytes(b'corrupted')
    with pytest.raises(ObjectStoreError, match='integrity'):
        store.get(digests[0], len(PDF))
    with pytest.raises(ObjectStoreError, match='integrity'):
        store.put(PDF)
    assert path.read_bytes() == b'corrupted'  # Never silently overwrite conflicting evidence.


@pytest.mark.parametrize('digest', ['../outside', 'a' * 63, 'A' * 64, '/tmp/file'])
def test_object_keys_are_not_caller_paths(tmp_path, digest):
    with pytest.raises(ObjectStoreError, match='digest'):
        FileObjectStore(tmp_path).get(digest, 1)


@pytest.mark.skipif(os.name != 'nt', reason='Windows extended path namespace regression')
def test_extended_namespace_race_keeps_containment_check(tmp_path, monkeypatch):
    store = FileObjectStore(tmp_path / 'objects')
    digest = hashlib.sha256(PDF).hexdigest()
    original = store.root / 'sha256' / digest[:2] / digest
    # Python 3.12 realpath occasionally retains //?/ while files are being created.
    monkeypatch.setattr(Path, 'resolve', lambda self: Path('//?/' + original.as_posix()))
    assert store.path(digest) == original
    outside = tmp_path / 'outside' / digest
    monkeypatch.setattr(Path, 'resolve', lambda self: Path('//?/' + outside.as_posix()))
    with pytest.raises(ObjectStoreError, match='object_path_not_allowed'):
        store.path(digest)


def test_config_does_not_discover_ambient_credentials_or_accept_http(monkeypatch, tmp_path):
    monkeypatch.setenv('TI_OBJECT_STORE_BACKEND', 's3')
    monkeypatch.delenv('TI_S3_ACCESS_KEY_ID', raising=False)
    monkeypatch.delenv('TI_S3_SECRET_ACCESS_KEY', raising=False)
    with pytest.raises(ObjectStoreError, match='credentials_required'):
        configured_store(tmp_path)
    monkeypatch.setenv('TI_S3_ACCESS_KEY_ID', 'test-only')
    monkeypatch.setenv('TI_S3_SECRET_ACCESS_KEY', 'test-only')
    monkeypatch.setenv('TI_S3_ENDPOINT_URL', 'http://127.0.0.1:9000')
    with pytest.raises(ObjectStoreError, match='requires_https'):
        configured_store(tmp_path)


def s3():
    client = boto3.client('s3', region_name='us-east-1', aws_access_key_id='test-only', aws_secret_access_key='test-only')
    return client, S3ObjectStore(client, 'tire-test-bucket')


@pytest.mark.parametrize('existing', [False, True])
def test_s3_conditional_put_and_verified_get_contract(existing):
    client, store = s3()
    digest = hashlib.sha256(PDF).hexdigest()
    read = {'Bucket': 'tire-test-bucket', 'Key': store.key(digest)}
    write = {**read, 'Body': PDF, 'IfNoneMatch': '*', 'ContentType': 'application/octet-stream',
             'ChecksumSHA256': base64.b64encode(bytes.fromhex(digest)).decode()}
    with Stubber(client) as stub:
        if existing:
            stub.add_client_error('put_object', service_error_code='PreconditionFailed', http_status_code=412, expected_params=write)
        else:
            stub.add_response('put_object', {}, write)
        stub.add_response('get_object', {'Body': StreamingBody(io.BytesIO(PDF), len(PDF))}, read)
        assert store.put(PDF) == digest
        stub.assert_no_pending_responses()


def test_s3_errors_are_sanitized_and_corruption_is_rejected():
    client, store = s3()
    digest = hashlib.sha256(PDF).hexdigest()
    with Stubber(client) as stub:
        stub.add_client_error('get_object', service_error_code='AccessDenied', service_message='private provider details', http_status_code=403)
        with pytest.raises(ObjectStoreError, match='^object_unavailable$'): store.get(digest, len(PDF))
        stub.add_response('get_object', {'Body': StreamingBody(io.BytesIO(b'wrong'), 5)})
        with pytest.raises(ObjectStoreError, match='integrity'): store.get(digest, len(PDF))


def test_pdf_roundtrip_is_opaque_immutable_deduplicated_and_download_only(setup):
    client, _, database = setup
    first = upload(client)
    assert first.status_code == 201, first.text
    one = first.json()
    assert one['accepted_as_facts'] is False and one['status'] == 'unparsed_receipt'
    assert upload(client, title='同一字节的另一收件说明').status_code == 201
    assert count(database, EvidenceObject) == 1 and count(database, EvidenceDocument) == 2
    assert count(database, Snapshot) == 0
    assert client.get('/v1/documents').status_code == 422
    listing = client.get('/v1/documents?mode=history').json()
    assert listing['total'] == 2 and all('body' not in row for row in listing['items'])
    path = f"/v1/documents/{one['id']}/content"
    assert client.get(path).status_code == 422
    response = client.get(path + '?mode=history')
    assert response.content == PDF and response.headers['x-evidence-sha256'] == hashlib.sha256(PDF).hexdigest()
    assert response.headers['content-disposition'].startswith('attachment;')
    assert response.headers['cache-control'] == 'no-store'
    with database.sessions() as db:
        row = db.get(EvidenceDocument, one['id'])
        row.title = 'overwrite'
        with pytest.raises(ValueError, match='只能追加'): db.commit()


@pytest.mark.parametrize('metadata', [{'rights_basis': ''}, {'operator': ''}, {'source_url': 'https://a:b@example.org/private'},
    {'source_url': 'https://example.org/file?token=not-real'}, {'title': 'bad\x00title'}, {'accepted_as_facts': True}])
def test_document_metadata_requires_explicit_provenance_and_rights(setup, metadata):
    client, _, database = setup
    assert upload(client, **metadata).status_code == 422
    assert count(database, EvidenceDocument) == 0


def test_pdf_size_type_and_metadata_limits(setup):
    client, _, database = setup
    assert upload(client, data=b'<script>not a PDF</script>').status_code == 422
    assert upload(client, data=b'%PDF-' + b'x' * MAX_OBJECT_BYTES).status_code == 413
    assert client.post('/v1/documents', content=PDF, headers={'content-type': 'text/html'}).status_code == 415
    assert client.post('/v1/documents', content=PDF, headers={'content-type': 'application/pdf', 'x-evidence-metadata': 'x' * 8193}).status_code == 422
    assert count(database, EvidenceObject) == 0


def test_failed_object_write_does_not_create_document_and_missing_object_is_not_served(setup, monkeypatch):
    client, _, database = setup
    row = upload(client).json()
    database.object_store.path(row['raw_hash']).unlink()
    assert client.get(f"/v1/documents/{row['id']}/content?mode=history").status_code == 503
    def fail(_): raise ObjectStoreError('object_write_failed')
    monkeypatch.setattr(database.object_store, 'put', fail)
    assert upload(client).status_code == 503
    assert count(database, EvidenceDocument) == 1


def test_capture_requires_object_write_and_verifies_object_on_read(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from tire_api.main import create_app
    configure(monkeypatch)
    app = create_app('sqlite:///' + (tmp_path / 'capture.db').as_posix())
    database = app.state.database
    with TestClient(app) as client:
        client.post(URL, json=QUERY)
        row = client.get('/v1/captures?mode=history').json()['items'][0]
        detail = client.get(row['evidence_path']).json()
        assert detail['storage_kind'] == 'object_store' and detail['body'] == BODY
        assert count(database, CaptureObject) == 1
        database.object_store.path(row['raw_hash']).write_bytes(b'corrupt')
        assert client.get(row['evidence_path']).status_code == 503
        parsed = []
        configure(monkeypatch, lambda *_: parsed.append(True))
        def fail(_): raise ObjectStoreError('object_write_failed')
        monkeypatch.setattr(database.object_store, 'put', fail)
        result = client.post(URL, json=QUERY).json()
        assert result['reason'] == 'evidence_capture_failed' and not parsed
        assert count(database, RawCapture) == 1
