"""Saved synthetic PDFs through production indexing, page retrieval and FTS APIs."""
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, event, func, select, text, update

from tire_api.db import AuditEvent, EvidenceDocument, FactVersion, Snapshot
from tire_api.document_text_models import DocumentTextChunk, DocumentTextIndex, DocumentTextPage
from tire_api.main import create_app
from test_core import FixtureRegistry
from test_document_pdf import pdf_bytes
from test_object_store import upload


@pytest.fixture
def setup():
    app = create_app('sqlite://', FixtureRegistry())
    with TestClient(app) as client:
        yield client, app.state.database


def index(client, identity):
    return client.post(f'/v1/documents/{identity}/text-index', json={'mode': 'history'})


def search(client, value, **options):
    return client.post('/v1/knowledge/document-text/search', json={'mode': 'history', 'text': value, **options})


def resolve(client, reference):
    return client.post('/v1/knowledge/document-text/resolve', json={'mode': 'history', 'reference': reference})


def document(client, pages=('pdfneedle 原始正文🛞', '第二页 原始文字'), **metadata):
    response = upload(client, pdf_bytes(pages), **metadata)
    assert response.status_code == 201, response.text
    return response.json()


def indexed_document(client, **options):
    row = document(client, **options)
    result = index(client, row['id'])
    assert result.status_code == 200, result.text
    return row, result.json()


def test_explicit_index_pages_and_receipt_preserve_raw_document_scope(setup):
    client, database = setup
    row = document(client)
    assert client.get(f"/v1/documents/{row['id']}/text").status_code == 422
    before = client.get(f"/v1/documents/{row['id']}/text?mode=history").json()
    assert before['index'] is None and before['page'] is None
    assert search(client, 'pdfneedle').json()['total'] == 0
    result = index(client, row['id'])
    assert result.status_code == 200, result.text
    value = result.json()
    assert value['index']['status'] == 'text_available' and value['index']['page_count'] == 2
    assert value['index']['parser_receipt']['reaped'] and value['document'] == row
    page = client.get(f"/v1/documents/{row['id']}/text?mode=history&page=2").json()['page']
    assert page['page'] == 2 and page['text'] == '第二页 原始文字'
    assert client.get(f"/v1/documents/{row['id']}/text?mode=history&page=3").status_code == 404
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Snapshot)) == 0
        assert db.scalar(select(func.count()).select_from(FactVersion)) == 0
        assert db.get(EvidenceDocument, row['id']).raw_hash == row['raw_hash']


def test_pdf_search_returns_page_bound_unicode_reference_and_original_restore(setup):
    client, _database = setup
    row, indexed = indexed_document(client, pages=('🛞' * 1081 + ' pdfneedle 原文',))
    response = search(client, 'pdfneedle', document_id=row['id'])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['index']['engine'] == 'sqlite_fts5' and result['total'] == 2
    item = next(item for item in result['items'] if item['reference']['start'] == 1080)
    reference = item['reference']
    assert reference['document_id'] == row['id'] and reference['raw_hash'] == row['raw_hash']
    assert reference['document_fingerprint'] == indexed['index']['document_fingerprint']
    assert reference['page'] == 1 and reference['end'] - reference['start'] == len(item['text'])
    restored = resolve(client, reference)
    assert restored.status_code == 200, restored.text
    assert restored.json()['text'] == item['text'] and restored.json()['reference'] == reference
    assert restored.json()['offset_unit'] == 'unicode_codepoints'


def test_pagination_and_document_filters_preserve_distinct_document_identity(setup):
    client, _database = setup
    first, _ = indexed_document(client, pages=tuple(f'pdfneedle page {number}' for number in range(14)))
    second, _ = indexed_document(client, title='另一份原始凭证')
    one = search(client, 'pdfneedle', document_id=first['id'], limit=12).json()
    two = search(client, 'pdfneedle', document_id=first['id'], limit=12, offset=12).json()
    assert one['total'] == two['total'] == 14 and one['has_more'] and not two['has_more']
    assert len({item['reference']['chunk_id'] for item in one['items'] + two['items']}) == 14
    assert all(item['reference']['document_id'] == first['id'] for item in one['items'] + two['items'])
    assert search(client, 'pdfneedle', document_id=second['id']).json()['total'] == 1


@pytest.mark.parametrize('pages,state', [(('', ''), 'no_extractable_text'), (('Visible', ''), 'partial_text')])
def test_no_text_and_partial_pdf_pages_are_explicit(setup, pages, state):
    client, _database = setup
    row, result = indexed_document(client, pages=pages)
    assert result['index']['status'] == state
    value = client.get(f"/v1/documents/{row['id']}/text?mode=history&page=2").json()
    assert value['page']['status'] == 'no_extractable_text' and value['page']['text'] == ''


def test_encrypted_document_keeps_original_and_explicit_state(setup):
    client, _database = setup
    row = upload(client, pdf_bytes(encrypted=True)).json()
    result = index(client, row['id'])
    assert result.status_code == 200, result.text
    assert result.json()['index']['status'] == 'encrypted'
    assert client.get(f"/v1/documents/{row['id']}/text?mode=history").json()['page'] is None
    assert search(client, 'pdfneedle', document_id=row['id']).json()['total'] == 0


def test_invalid_pdf_retains_raw_receipt_and_records_failed_extraction(setup):
    client, database = setup
    raw = b'%PDF-1.7\nsynthetic damaged document'
    row = upload(client, raw).json()
    result = index(client, row['id'])
    assert result.status_code == 422 and result.json()['detail']['code'] == 'document_pdf_invalid'
    assert client.get(f"/v1/documents/{row['id']}/content?mode=history").content == raw
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(DocumentTextIndex)) == 0
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == 'document_text_extraction_failed'))
        assert audit.detail['document_id'] == row['id'] and audit.detail['parser_receipt']['reaped']


@pytest.mark.parametrize('field,value', [
    ('document_fingerprint', '0' * 64), ('raw_hash', '0' * 64), ('extractor_version', 'unknown@1'),
    ('chunk_id', '0' * 64), ('page', 2), ('start', 1), ('end', 1),
])
def test_invalid_reference_fields_are_rejected(setup, field, value):
    client, _database = setup
    row, _ = indexed_document(client, pages=('pdfneedle original',))
    reference = search(client, 'pdfneedle', document_id=row['id']).json()['items'][0]['reference']
    reference[field] = value
    assert resolve(client, reference).status_code == 409


def test_old_reference_recovers_after_all_derived_projection_rows_are_cleared(setup):
    client, database = setup
    row, _ = indexed_document(client)
    item = search(client, 'pdfneedle', document_id=row['id']).json()['items'][0]
    with database.sessions() as db:
        db.execute(text('DELETE FROM document_text_fts'))
        for model in (DocumentTextChunk, DocumentTextPage, DocumentTextIndex):
            db.execute(delete(model).where(model.document_id == row['id']))
        db.commit()
    restored = resolve(client, item['reference'])
    assert restored.status_code == 200, restored.text
    assert restored.json()['text'] == item['text']
    assert index(client, row['id']).status_code == 200
    assert search(client, 'pdfneedle', document_id=row['id']).json()['items'][0]['reference'] == item['reference']


@pytest.mark.parametrize('corruption', ['page', 'chunk', 'fts', 'receipt'])
def test_partial_or_damaged_projection_is_visible_and_reindexable(setup, corruption):
    client, database = setup
    row, _ = indexed_document(client)
    with database.sessions() as db:
        if corruption == 'page':
            db.execute(update(DocumentTextPage).where(DocumentTextPage.document_id == row['id']).values(text='damaged'))
        elif corruption == 'chunk':
            db.execute(update(DocumentTextChunk).where(DocumentTextChunk.document_id == row['id']).values(text='damaged'))
        elif corruption == 'fts':
            db.execute(text('DELETE FROM document_text_fts'))
        else:
            record = db.get(DocumentTextIndex, row['id'])
            record.parser_receipt = {**record.parser_receipt, 'reaped': False}
        db.commit()
    assert search(client, 'pdfneedle', document_id=row['id']).status_code == 503
    assert index(client, row['id']).status_code == 200
    assert search(client, 'pdfneedle', document_id=row['id']).json()['total'] == 1


def test_original_object_damage_blocks_index_pages_search_and_reference(setup):
    client, database = setup
    row, _ = indexed_document(client)
    reference = search(client, 'pdfneedle', document_id=row['id']).json()['items'][0]['reference']
    with database.sessions() as db:
        path = db.info['object_store'].path(row['raw_hash'])
    path.write_bytes(b'synthetic corrupted bytes')
    assert index(client, row['id']).status_code == 503
    assert client.get(f"/v1/documents/{row['id']}/text?mode=history").status_code == 503
    assert search(client, 'pdfneedle', document_id=row['id']).status_code == 503
    assert resolve(client, reference).status_code == 503


def test_mid_publish_failure_rolls_back_every_projection_table(setup):
    client, database = setup
    row = document(client)

    def fail_chunk(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith('INSERT INTO document_text_chunks'):
            raise RuntimeError('synthetic projection publication failure')

    event.listen(database.engine, 'before_cursor_execute', fail_chunk)
    try:
        with pytest.raises(RuntimeError, match='synthetic projection'):
            index(client, row['id'])
    finally:
        event.remove(database.engine, 'before_cursor_execute', fail_chunk)
    with database.sessions() as db:
        for model in (DocumentTextIndex, DocumentTextPage, DocumentTextChunk):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.execute(text('SELECT count(*) FROM document_text_fts')).scalar_one() == 0
    assert index(client, row['id']).status_code == 200


def test_unexpected_storage_permission_errors_retain_their_path(setup, monkeypatch):
    client, database = setup
    row = document(client)
    with database.sessions() as db:
        store = db.info['object_store']

    def denied(*_args):
        raise PermissionError('synthetic storage permission')

    monkeypatch.setattr(store, 'get', denied)
    with pytest.raises(PermissionError, match='synthetic storage permission'):
        index(client, row['id'])


def test_concurrent_indexes_publish_one_consistent_projection(tmp_path):
    app = create_app('sqlite:///' + (tmp_path / 'concurrent.sqlite').as_posix(), FixtureRegistry())
    with TestClient(app) as client:
        row = document(client)
        with ThreadPoolExecutor(max_workers=2) as workers:
            responses = list(workers.map(lambda _: index(client, row['id']), range(2)))
        assert [response.status_code for response in responses] == [200, 200]
        with app.state.database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(DocumentTextIndex)) == 1
            assert db.scalar(select(func.count()).select_from(DocumentTextPage)) == 2
            assert db.scalar(select(func.count()).select_from(DocumentTextChunk)) == 2
        assert search(client, 'pdfneedle', document_id=row['id']).json()['total'] == 1


def test_source_material_receipt_is_rechecked_before_local_extraction(tmp_path, monkeypatch):
    import json
    import test_source_materials as materials
    from admin_support import register_admin
    path = tmp_path / 'policies.json'
    path.write_text(json.dumps({'schema': 'source-material-policies@1', 'policies': [materials.POLICY]}))
    monkeypatch.setenv('TI_SOURCE_MATERIAL_POLICIES_FILE', str(path))
    monkeypatch.setattr(materials, 'PDF', pdf_bytes())
    app = create_app('sqlite:///' + (tmp_path / 'material.sqlite').as_posix(), FixtureRegistry())
    with TestClient(app) as client:
        register_admin(client, 'synthetic-pdf-owner')
        materials.success_transport(app, monkeypatch)
        captured = client.post('/v1/source-materials/captures', json=materials.payload(client))
        assert captured.status_code == 201, captured.text
        row = captured.json()['document']
        assert index(client, row['id']).status_code == 200
        with app.state.database.sessions() as db:
            db.execute(update(EvidenceDocument).where(EvidenceDocument.id == row['id']).values(rights_basis='changed synthetic permission'))
            db.commit()
        assert index(client, row['id']).status_code == 503


def assert_document_text_checkpoint(client, checkpoint):
    response = search(client, checkpoint['text'], document_id=checkpoint['document_id'])
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['index']['engine'] == 'postgresql_fts' and value['total'] == 1
    assert value['items'][0]['reference'] == checkpoint['reference']
    page = client.get(f"/v1/documents/{checkpoint['document_id']}/text?mode=history&page=2")
    assert page.status_code == 200 and page.json()['page']['text'] == 'Second checkpoint page'
    assert page.json()['index']['page_count'] == 2
    recovered = resolve(client, checkpoint['reference'])
    assert recovered.status_code == 200 and recovered.json()['text'] == checkpoint['excerpt']


def verify_document_text_persistence(url):
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        row, _ = indexed_document(client, pages=('pdfcheckpoint grip 原文🛞', 'Second checkpoint page'))
        item = search(client, 'pdfcheckpoint grip', document_id=row['id']).json()['items'][0]
        checkpoint = {'text': 'pdfcheckpoint grip', 'document_id': row['id'], 'reference': item['reference'], 'excerpt': item['text']}
    with TestClient(create_app(url, FixtureRegistry())) as client:
        assert_document_text_checkpoint(client, checkpoint)
    return checkpoint
