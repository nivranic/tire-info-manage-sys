"""Local PDF page indexing and original-bound citation recovery."""
import hashlib
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import Field, StrictInt, model_validator
from sqlalchemy import Float, String, delete, func, select, text

from .db import EvidenceDocument, EvidenceObject, utcnow
from .document_pdf import (MAX_PAGE_CHARACTERS, MAX_PAGES, MAX_TEXT_CHARACTERS,
                           PARSER_VERSION, SOURCE_ID, extractor_version)
from .document_text_models import DocumentTextChunk, DocumentTextIndex, DocumentTextPage
from .documents import DocumentMetadata, document_metadata
from .domain import StrictModel, digest
from .knowledge import CURRENT_WORDS
from .knowledge_index import query_tokens, tokens
from .object_store import ObjectStoreError
from .parser_runtime import ParserRunError, current_parser, input_hash, parse_isolated
from .service import QueryService, timestamp
from .source_text import CHUNK_CHARACTERS, CHUNK_OVERLAP

NOTICE = ('显式历史PDF正文。页码与摘录来自保存原件的文字层抽取，正文作为来源内容处理。'
          '无可抽取文字的页面需核对空白或扫描情况。具体SKU、事实核验及外部用途按各自证据与许可处理。')


def fail(code, status=503):
    raise HTTPException(status, {'code': code, 'message': 'PDF正文或引用未能完成核对，可核查原件并重新建立正文索引。'})


class HistoryMode(StrictModel):
    mode: Literal['history']


class PDFPage(StrictModel):
    page: StrictInt = Field(ge=1, le=MAX_PAGES)
    text: str = Field(max_length=MAX_PAGE_CHARACTERS)
    text_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    status: Literal['text', 'no_extractable_text']


class PDFExtraction(StrictModel):
    document_id: str = Field(min_length=1, max_length=64)
    extractor_version: str = Field(min_length=1, max_length=100)
    status: Literal['text_available', 'partial_text', 'no_extractable_text', 'encrypted']
    page_count: StrictInt | None = Field(ge=1, le=MAX_PAGES)
    characters: StrictInt = Field(ge=0, le=MAX_TEXT_CHARACTERS)
    pages: list[PDFPage] = Field(max_length=MAX_PAGES)

    @model_validator(mode='after')
    def coherent_pages(self):
        if self.extractor_version != extractor_version():
            raise ValueError('extractor version mismatch')
        if self.status == 'encrypted':
            if self.page_count is not None or self.pages or self.characters:
                raise ValueError('encrypted PDF has text')
            return self
        if self.page_count != len(self.pages) or not self.pages:
            raise ValueError('page count mismatch')
        for number, page in enumerate(self.pages, 1):
            if (page.page != number or page.text != ' '.join(page.text.split())
                    or page.text_hash != hashlib.sha256(page.text.encode('utf-8')).hexdigest()
                    or page.status != ('text' if page.text else 'no_extractable_text')):
                raise ValueError('page text mismatch')
        count = sum(bool(page.text) for page in self.pages)
        state = 'text_available' if count == self.page_count else 'partial_text' if count else 'no_extractable_text'
        if self.status != state or self.characters != sum(len(page.text) for page in self.pages):
            raise ValueError('document text mismatch')
        return self


class DocumentTextSearch(HistoryMode):
    text: str = Field(min_length=1, max_length=500)
    document_id: str | None = Field(default=None, min_length=1, max_length=64)
    limit: StrictInt = Field(default=12, ge=1, le=30)
    offset: StrictInt = Field(default=0, ge=0, le=2000)

    @model_validator(mode='after')
    def useful_query(self):
        if not self.text.strip() or any(ord(character) < 32 for character in self.text):
            raise ValueError('请提供有界的历史PDF检索文本')
        return self


class DocumentTextReference(StrictModel):
    document_id: str = Field(min_length=1, max_length=64)
    document_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    raw_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    extractor_version: str = Field(min_length=1, max_length=100)
    page: StrictInt = Field(ge=1, le=MAX_PAGES)
    start: StrictInt = Field(ge=0, le=MAX_PAGE_CHARACTERS)
    end: StrictInt = Field(ge=1, le=MAX_PAGE_CHARACTERS)
    chunk_id: str = Field(pattern=r'^[a-f0-9]{64}$')


class ResolveDocumentText(HistoryMode):
    reference: DocumentTextReference


def checked_document(db, document_id):
    row = db.get(EvidenceDocument, document_id, populate_existing=True)
    if row is None:
        fail('document_text_not_found', 404)
    obj = db.get(EvidenceObject, row.raw_hash, populate_existing=True)
    if obj is None or row.content_type != 'application/pdf':
        fail('document_text_original_invalid')
    try:
        DocumentMetadata.model_validate({name: getattr(row, name) for name in ('title', 'source_url', 'operator', 'rights_basis')})
    except (ValueError, TypeError):
        fail('document_text_original_invalid')
    try:
        raw = db.info['object_store'].get(row.raw_hash, obj.byte_count)
    except ObjectStoreError:
        fail('document_text_original_invalid')
    from .source_material_models import SourceMaterialOutcome, SourceMaterialRequest
    from .source_materials import checked_view
    outcome = db.scalar(select(SourceMaterialOutcome).where(SourceMaterialOutcome.document_id == row.id))
    if outcome is not None:
        acquisition = db.get(SourceMaterialRequest, outcome.request_id)
        if acquisition is None or checked_view(db, acquisition)['state'] != 'succeeded':
            fail('document_text_material_invalid')
    metadata = document_metadata(row, obj.byte_count)
    fingerprint = digest({**metadata, 'actor_session_id': row.actor_session_id})
    return row, raw, metadata, fingerprint


async def extract_original(db, document_id, *, release_transaction=True):
    _row, raw, _metadata, fingerprint = checked_document(db, document_id)
    descriptor = current_parser(SOURCE_ID)
    if release_transaction:
        db.rollback()
    result = await parse_isolated(SOURCE_ID, raw, {'document_id': document_id},
        descriptor['parser_version'], descriptor['parser_digest'])
    try:
        extracted = PDFExtraction.model_validate(result['payload'])
        if extracted.document_id != document_id:
            raise ValueError('document mismatch')
    except (ValueError, TypeError, UnicodeError):
        fail('document_text_parser_output_invalid')
    _row, current, metadata, current_fingerprint = checked_document(db, document_id)
    if current != raw or current_fingerprint != fingerprint:
        fail('document_text_original_changed', 409)
    return extracted, result['receipt'], metadata, fingerprint


def reference_for(document_id, fingerprint, raw_hash, page, start, end):
    value = {'document_id': document_id, 'document_fingerprint': fingerprint, 'raw_hash': raw_hash,
             'extractor_version': extractor_version(), 'page': page, 'start': start, 'end': end}
    return {**value, 'chunk_id': digest(value)}


def index_view(index):
    return {'status': index.status, 'page_count': index.page_count, 'characters': index.characters,
        'chunks': index.chunks, 'raw_hash': index.raw_hash, 'document_fingerprint': index.document_fingerprint,
        'extractor_version': index.extractor_version, 'indexed_at': timestamp(index.indexed_at),
        'parser_receipt': index.parser_receipt}


def checked_projection(db, document_id):
    _row, raw, metadata, fingerprint = checked_document(db, document_id)
    index = db.get(DocumentTextIndex, document_id, populate_existing=True)
    if index is None:
        return metadata, None, []
    pages = list(db.scalars(select(DocumentTextPage).where(DocumentTextPage.document_id == document_id)
                           .order_by(DocumentTextPage.page)))
    try:
        value = PDFExtraction.model_validate({'document_id': document_id, 'extractor_version': index.extractor_version,
            'status': index.status, 'page_count': index.page_count, 'characters': index.characters,
            'pages': [{'page': page.page, 'text': page.text, 'text_hash': page.text_hash, 'status': page.status} for page in pages]})
        expected_chunks = sum(len(range(0, len(page.text), CHUNK_CHARACTERS - CHUNK_OVERLAP)) for page in pages)
        receipt = index.parser_receipt
        if (not isinstance(receipt, dict) or receipt.get('source_id') != SOURCE_ID
                or receipt.get('parser_version') != PARSER_VERSION or receipt.get('reaped') is not True
                or receipt.get('exit_code') != 0
                or receipt.get('input_hash') != input_hash({**receipt, 'query': {'document_id': document_id}}, raw)):
            raise ValueError('parser receipt mismatch')
        stored_chunks = db.scalar(select(func.count()).select_from(DocumentTextChunk)
                                  .where(DocumentTextChunk.document_id == document_id))
        if db.get_bind().dialect.name == 'sqlite':
            indexed_chunks = db.execute(text('SELECT count(*) FROM document_text_fts WHERE chunk_id IN '
                '(SELECT id FROM document_text_chunks WHERE document_id = :document_id)'), {'document_id': document_id}).scalar_one()
        else:
            indexed_chunks = db.scalar(select(func.count()).select_from(DocumentTextChunk).where(
                DocumentTextChunk.document_id == document_id, DocumentTextChunk.search_vector.is_not(None)))
        if (index.document_fingerprint != fingerprint or index.raw_hash != metadata['raw_hash']
                or index.text_hash != digest(value.model_dump())
                or not index.chunks == expected_chunks == stored_chunks == indexed_chunks):
            raise ValueError('projection binding mismatch')
    except (ValueError, TypeError, KeyError, UnicodeError):
        fail('document_text_index_invalid')
    return metadata, index, pages


def write_projection(db, extracted, receipt, metadata, fingerprint):
    document_id = extracted.document_id
    if db.get_bind().dialect.name == 'sqlite':
        db.execute(text('DELETE FROM document_text_fts WHERE chunk_id IN '
            '(SELECT id FROM document_text_chunks WHERE document_id = :document_id)'), {'document_id': document_id})
    db.execute(delete(DocumentTextChunk).where(DocumentTextChunk.document_id == document_id))
    db.execute(delete(DocumentTextPage).where(DocumentTextPage.document_id == document_id))
    index = db.get(DocumentTextIndex, document_id)
    if index is None:
        index = DocumentTextIndex(document_id=document_id)
        db.add(index)
    index.document_fingerprint, index.raw_hash = fingerprint, metadata['raw_hash']
    index.extractor_version, index.text_hash = extracted.extractor_version, digest(extracted.model_dump())
    index.status, index.page_count = extracted.status, extracted.page_count
    index.characters, index.chunks = extracted.characters, 0
    index.parser_receipt, index.indexed_at = receipt, utcnow()
    db.flush()
    for page in extracted.pages:
        db.add(DocumentTextPage(document_id=document_id, **page.model_dump()))
        db.flush()
        for start in range(0, len(page.text), CHUNK_CHARACTERS - CHUNK_OVERLAP):
            end = min(start + CHUNK_CHARACTERS, len(page.text))
            reference = reference_for(document_id, fingerprint, index.raw_hash, page.page, start, end)
            value = page.text[start:end]
            searchable = ' '.join(tokens(value))
            db.add(DocumentTextChunk(id=reference['chunk_id'], document_id=document_id, page=page.page,
                start=start, end=end, text=value, tokens=searchable))
            if db.get_bind().dialect.name == 'sqlite':
                db.execute(text('DELETE FROM document_text_fts WHERE chunk_id = :id'), {'id': reference['chunk_id']})
                db.execute(text('INSERT INTO document_text_fts (chunk_id, tokens) VALUES (:id, :tokens)'),
                           {'id': reference['chunk_id'], 'tokens': searchable})
            index.chunks += 1
    db.flush()
    if db.get_bind().dialect.name == 'postgresql':
        db.execute(text("UPDATE document_text_chunks SET search_vector = to_tsvector('simple', tokens) "
                        'WHERE document_id = :document_id'), {'document_id': document_id})
    return index


def render_excerpt(metadata, reference, value):
    return {'kind': 'document_text', 'reference': reference, 'text': value, 'offset_unit': 'unicode_codepoints',
        'document': metadata, 'data_state': 'local_snapshot', 'verification_status': 'original_text_excerpt', 'notice': NOTICE}


def resolve_extracted_reference(reference, extracted, metadata, fingerprint):
    if reference.extractor_version != extractor_version():
        fail('document_text_extractor_unavailable', 409)
    if reference.page > len(extracted.pages):
        fail('document_text_reference_invalid', 409)
    original = extracted.pages[reference.page - 1].text
    if (reference.start >= len(original) or reference.start % (CHUNK_CHARACTERS - CHUNK_OVERLAP)
            or reference.end != min(reference.start + CHUNK_CHARACTERS, len(original))
            or reference.model_dump() != reference_for(reference.document_id, fingerprint, metadata['raw_hash'],
                                                      reference.page, reference.start, reference.end)):
        fail('document_text_reference_invalid', 409)
    return render_excerpt(metadata, reference.model_dump(), original[reference.start:reference.end])


def begin_read(db):
    if db.get_bind().dialect.name == 'sqlite':
        db.connection().exec_driver_sql('BEGIN')
    elif db.get_bind().dialect.name == 'postgresql':
        db.connection().exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')


def search_documents(db, payload):
    if CURRENT_WORDS.search(payload.text):
        raise HTTPException(409, {'code': 'online_query_required', 'message': '请使用在线查询核对当前状态。'})
    begin_read(db)
    terms = query_tokens(payload.text)
    identities = list(db.scalars(select(DocumentTextIndex.document_id).where(
        DocumentTextIndex.document_id == payload.document_id) if payload.document_id else select(DocumentTextIndex.document_id)))
    projections = {identity: checked_projection(db, identity) for identity in identities}
    if db.get_bind().dialect.name == 'sqlite':
        fulltext = text('SELECT chunk_id AS id, bm25(document_text_fts) AS score FROM document_text_fts '
                        'WHERE document_text_fts MATCH :terms').columns(id=String, score=Float).subquery()
        query = ' AND '.join('"' + term.replace('"', '""') + '"' for term in terms)
    else:
        fulltext = text("SELECT id, -ts_rank_cd(search_vector, plainto_tsquery('simple', :terms)) AS score "
                        "FROM document_text_chunks WHERE search_vector @@ plainto_tsquery('simple', :terms)")\
            .columns(id=String, score=Float).subquery()
        query = ' '.join(terms)
    statement = select(DocumentTextChunk, fulltext.c.score).join(fulltext, fulltext.c.id == DocumentTextChunk.id)\
        .where(DocumentTextChunk.document_id.in_(identities))
    total = db.scalar(select(func.count()).select_from(statement.subquery()), {'terms': query}) if terms else 0
    matches = db.execute(statement.order_by(fulltext.c.score, DocumentTextChunk.id).offset(payload.offset)
        .limit(payload.limit), {'terms': query}).all() if terms else []
    items = []
    for chunk, score in matches:
        metadata, index, pages = projections[chunk.document_id]
        if index is None or not 1 <= chunk.page <= len(pages):
            fail('document_text_index_invalid')
        original = pages[chunk.page - 1].text
        reference = reference_for(chunk.document_id, index.document_fingerprint, index.raw_hash,
                                  chunk.page, chunk.start, chunk.end)
        if (chunk.start % (CHUNK_CHARACTERS - CHUNK_OVERLAP) or chunk.start >= len(original)
                or chunk.end != min(chunk.start + CHUNK_CHARACTERS, len(original))
                or chunk.id != reference['chunk_id'] or chunk.text != original[chunk.start:chunk.end]
                or chunk.tokens != ' '.join(tokens(chunk.text)) or not set(terms).issubset(tokens(chunk.text))):
            fail('document_text_index_invalid')
        items.append({**render_excerpt(metadata, reference, chunk.text),
                      'match': {'method': 'fts', 'matched_terms': terms, 'score': float(score)}})
    return {'mode': 'history', 'data_state': 'local_snapshot', 'items': items, 'total': total or 0,
        'offset': payload.offset, 'limit': payload.limit, 'has_more': (total or 0) > payload.offset + payload.limit,
        'index': {'engine': 'sqlite_fts5' if db.get_bind().dialect.name == 'sqlite' else 'postgresql_fts',
                  'extractor_version': extractor_version(), 'documents': len(identities)}, 'notice': NOTICE}


def register_document_text_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    async def extract(db, document_id, session_id):
        try:
            return await extract_original(db, document_id)
        except ParserRunError as error:
            db.rollback()
            QueryService(db, None).audit(session_id, 'document_text_extraction_failed',
                document_id=document_id, error_code=error.code, parser_receipt=error.receipt)
            db.commit()
            fail(error.code, 422 if error.code.startswith('document_pdf_') else 503)

    @app.post('/v1/documents/{document_id}/text-index')
    async def index(document_id: str, payload: HistoryMode, request: Request, db=Depends(get_db)):
        extracted, receipt, metadata, fingerprint = await extract(db, document_id, request.state.session_id)
        service = QueryService(db, None)
        service.lock_ingestion()
        _row, _raw, current, current_fingerprint = checked_document(db, document_id)
        if current != metadata or current_fingerprint != fingerprint:
            fail('document_text_original_changed', 409)
        projection = write_projection(db, extracted, receipt, metadata, fingerprint)
        service.audit(request.state.session_id, 'document_text_indexed', document_id=document_id,
                      raw_hash=projection.raw_hash, extractor_version=projection.extractor_version)
        db.commit()
        return {'mode': 'history', 'document': metadata, 'index': index_view(projection), 'page': None, 'notice': NOTICE}

    @app.get('/v1/documents/{document_id}/text')
    def pages(document_id: str, mode: Literal['history'] = Query(...),
              page: int = Query(1, ge=1, le=MAX_PAGES), db=Depends(get_db)):
        begin_read(db)
        metadata, projection, values = checked_projection(db, document_id)
        if projection and projection.page_count and page > projection.page_count:
            fail('document_text_page_not_found', 404)
        value = values[page - 1] if values else None
        return {'mode': 'history', 'document': metadata, 'index': index_view(projection) if projection else None,
            'page': {'page': value.page, 'text': value.text, 'text_hash': value.text_hash, 'status': value.status} if value else None,
            'notice': NOTICE}

    @app.post('/v1/knowledge/document-text/search')
    def search(payload: DocumentTextSearch, db=Depends(get_db)):
        return search_documents(db, payload)

    @app.post('/v1/knowledge/document-text/resolve')
    async def resolve(payload: ResolveDocumentText, request: Request, db=Depends(get_db)):
        reference = payload.reference
        if reference.extractor_version != extractor_version():
            fail('document_text_extractor_unavailable', 409)
        _row, _raw, metadata, fingerprint = checked_document(db, reference.document_id)
        if reference.raw_hash != metadata['raw_hash'] or reference.document_fingerprint != fingerprint:
            fail('document_text_reference_invalid', 409)
        extracted, _receipt, metadata, fingerprint = await extract(db, reference.document_id, request.state.session_id)
        return resolve_extracted_reference(reference, extracted, metadata, fingerprint)
