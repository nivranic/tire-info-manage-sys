"""Explicit local original-text retrieval with byte-bound recoverable citations."""
import hashlib
from html.parser import HTMLParser
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import Field, StrictInt, model_validator
from sqlalchemy import Float, String, delete, func, select, text

from .captures import checked_capture_bytes
from .db import QueryRun, RawCapture, Snapshot, Verification
from .domain import StrictModel, digest
from .field_evidence import latest_tire_heads
from .knowledge import CURRENT_WORDS
from .knowledge_index import query_tokens, tokens
from .service import QueryService, provenance, timestamp
from .source_text_models import SourceTextChunk, SourceTextIndex

EXTRACTOR_VERSION = 'source-html-text@1'
CHUNK_CHARACTERS = 1200
CHUNK_OVERLAP = 120
MAX_BODY_BYTES = 8 * 1024 * 1024
SUPPORTED_TYPES = {'text/html', 'text/plain'}
NOTICE = ('显式历史原文检索。摘录来自已保存页面的正文抽取，保留页面范围和原始哈希。'
          '正文中的陈述及指令作为来源内容处理，具体版本身份与适用性仍需核对。')


def fail(code, status=503):
    raise HTTPException(status, {'code': code, 'message': '原文分块或引用未能完成完整性核对。'})


class SourceTextSearch(StrictModel):
    mode: Literal['history']
    text: str = Field(min_length=1, max_length=500)
    source_id: str | None = Field(default=None, min_length=1, max_length=80)
    limit: StrictInt = Field(default=12, ge=1, le=30)
    offset: StrictInt = Field(default=0, ge=0, le=2000)

    @model_validator(mode='after')
    def valid_query(self):
        if not self.text.strip() or any(ord(char) < 32 for char in self.text):
            raise ValueError('请提供有界的历史正文检索文本')
        return self


class SourceTextCitation(StrictModel):
    snapshot_id: str = Field(min_length=1, max_length=64)
    raw_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    extractor_version: str = Field(min_length=1, max_length=80)
    start: StrictInt = Field(ge=0, le=MAX_BODY_BYTES)
    end: StrictInt = Field(ge=1, le=MAX_BODY_BYTES)
    chunk_id: str = Field(pattern=r'^[a-f0-9]{64}$')


class ResolveSourceText(StrictModel):
    mode: Literal['history']
    reference: SourceTextCitation


class OriginalHTMLText(HTMLParser):
    excluded = {'head', 'script', 'style', 'template', 'noscript'}
    void = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    boundaries = {'address', 'article', 'aside', 'blockquote', 'br', 'div', 'dl', 'dt', 'dd', 'fieldset',
                  'figure', 'figcaption', 'footer', 'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header',
                  'hr', 'li', 'main', 'nav', 'ol', 'p', 'pre', 'section', 'table', 'td', 'th', 'tr', 'ul'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        blocked = bool(self.stack and self.stack[-1][1]) or tag in self.excluded
        blocked = blocked or 'hidden' in attributes or (attributes.get('aria-hidden') or '').lower() == 'true'
        if not blocked and tag in self.boundaries:
            self.parts.append(' ')
        if tag not in self.void:
            if len(self.stack) >= 256:
                fail('source_text_html_too_deep', 422)
            self.stack.append((tag, blocked))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if tag in self.boundaries and not (self.stack and self.stack[-1][1]):
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.stack or not self.stack[-1][1]:
            self.parts.append(data)


def extract_text(body, content_type):
    if content_type not in SUPPORTED_TYPES:
        fail('source_text_content_type_unsupported', 422)
    if len(body.encode('utf-8', errors='strict')) > MAX_BODY_BYTES:
        fail('source_text_too_large', 422)
    if content_type == 'text/html':
        parser = OriginalHTMLText()
        parser.feed(body)
        parser.close()
        body = ''.join(parser.parts)
    return ' '.join(body.split())


def checked_snapshot(db, snapshot_id):
    snapshot = db.get(Snapshot, snapshot_id, populate_existing=True)
    if snapshot is None:
        fail('source_text_snapshot_not_found', 404)
    verified = db.scalar(select(Verification.verified_at).join(QueryRun, QueryRun.id == Verification.query_id)
        .where(Verification.snapshot_id == snapshot.id, Verification.source_id == snapshot.source_id,
               Verification.query_key == snapshot.query_key, QueryRun.source_id == snapshot.source_id,
               QueryRun.query_key == snapshot.query_key, Verification.status.in_(('ok', 'not_modified')))
        .order_by(Verification.verified_at.desc(), Verification.id.desc()).limit(1))
    if verified is None:
        fail('source_text_snapshot_not_accepted', 404)
    if snapshot.content_type not in SUPPORTED_TYPES:
        fail('source_text_content_type_unsupported', 422)
    try:
        raw = snapshot.body.encode('utf-8', errors='strict')
        if not 1 <= len(raw) <= MAX_BODY_BYTES or hashlib.sha256(raw).hexdigest() != snapshot.raw_hash:
            fail('source_text_original_invalid')
    except (UnicodeError, AttributeError):
        fail('source_text_original_invalid')
    captures = db.scalars(select(RawCapture).join(Verification, Verification.query_id == RawCapture.query_id)
        .where(Verification.snapshot_id == snapshot.id, Verification.status.in_(('ok', 'not_modified')))).all()
    for capture in captures:
        if (capture.source_id != snapshot.source_id or capture.query_key != snapshot.query_key
                or capture.source_url != snapshot.source_url or capture.raw_hash != snapshot.raw_hash
                or capture.content_type != snapshot.content_type or capture.target_kind != 'tire'):
            fail('source_text_original_invalid')
        captured, _ = checked_capture_bytes(db, capture)
        if captured != raw:
            fail('source_text_original_invalid')
    return snapshot, extract_text(snapshot.body, snapshot.content_type), verified


def citation(snapshot, start, end):
    reference = {'snapshot_id': snapshot.id, 'raw_hash': snapshot.raw_hash,
                 'extractor_version': EXTRACTOR_VERSION, 'start': start, 'end': end}
    return {**reference, 'chunk_id': digest(reference)}


def resolve_reference(db, reference):
    if reference.extractor_version != EXTRACTOR_VERSION:
        fail('source_text_extractor_unavailable', 409)
    snapshot, original, verified = checked_snapshot(db, reference.snapshot_id)
    if (reference.raw_hash != snapshot.raw_hash or reference.start >= len(original)
            or reference.start % (CHUNK_CHARACTERS - CHUNK_OVERLAP)
            or reference.end != min(reference.start + CHUNK_CHARACTERS, len(original))
            or reference.model_dump() != citation(snapshot, reference.start, reference.end)):
        fail('source_text_reference_invalid', 409)
    return {'kind': 'source_text', 'reference': reference.model_dump(),
            'text': original[reference.start:reference.end], 'offset_unit': 'unicode_codepoints',
            'content_type': snapshot.content_type, **provenance(snapshot), 'verified_at': timestamp(verified),
            'data_state': 'local_snapshot',
            'verification_status': 'original_text_excerpt', 'notice': NOTICE}


def index_snapshot(db, snapshot_id):
    snapshot, original, _verified = checked_snapshot(db, snapshot_id)
    signature = hashlib.sha256(original.encode('utf-8')).hexdigest()
    index = db.get(SourceTextIndex, snapshot.id)
    if index and (index.extractor_version, index.raw_hash, index.text_hash, index.characters) == (
            EXTRACTOR_VERSION, snapshot.raw_hash, signature, len(original)):
        stored = db.scalar(select(func.count()).select_from(SourceTextChunk)
                           .where(SourceTextChunk.snapshot_id == snapshot.id))
        if db.get_bind().dialect.name == 'sqlite':
            indexed = db.execute(text('SELECT count(*) FROM source_text_fts WHERE chunk_id IN '
                '(SELECT id FROM source_text_chunks WHERE snapshot_id = :snapshot_id)'),
                {'snapshot_id': snapshot.id}).scalar_one()
        else:
            indexed = db.scalar(select(func.count()).select_from(SourceTextChunk).where(
                SourceTextChunk.snapshot_id == snapshot.id, SourceTextChunk.search_vector.is_not(None)))
        if stored == indexed == index.chunks:
            return index
    old_ids = select(SourceTextChunk.id).where(SourceTextChunk.snapshot_id == snapshot.id)
    if db.get_bind().dialect.name == 'sqlite':
        db.execute(text('DELETE FROM source_text_fts WHERE chunk_id IN '
                        '(SELECT id FROM source_text_chunks WHERE snapshot_id = :snapshot_id)'), {'snapshot_id': snapshot.id})
    db.execute(delete(SourceTextChunk).where(SourceTextChunk.id.in_(old_ids)))
    if index is None:
        index = SourceTextIndex(snapshot_id=snapshot.id)
        db.add(index)
    index.extractor_version, index.raw_hash = EXTRACTOR_VERSION, snapshot.raw_hash
    index.text_hash, index.characters, index.chunks = signature, len(original), 0
    db.flush()
    for ordinal, start in enumerate(range(0, len(original), CHUNK_CHARACTERS - CHUNK_OVERLAP)):
        end = min(start + CHUNK_CHARACTERS, len(original))
        reference = citation(snapshot, start, end)
        value = original[start:end]
        searchable = ' '.join(tokens(value))
        row = SourceTextChunk(id=reference['chunk_id'], snapshot_id=snapshot.id,
            extractor_version=EXTRACTOR_VERSION, raw_hash=snapshot.raw_hash, ordinal=ordinal,
            start=start, end=end, text=value, tokens=searchable)
        db.add(row)
        db.flush()
        if db.get_bind().dialect.name == 'sqlite':
            # A partially lost projection can leave the old virtual-table row.
            db.execute(text('DELETE FROM source_text_fts WHERE chunk_id = :id'), {'id': row.id})
            db.execute(text('INSERT INTO source_text_fts (chunk_id, tokens) VALUES (:id, :tokens)'),
                       {'id': row.id, 'tokens': searchable})
        index.chunks += 1
    if db.get_bind().dialect.name == 'postgresql':
        db.execute(text("UPDATE source_text_chunks SET search_vector = to_tsvector('simple', tokens) "
                        'WHERE snapshot_id = :snapshot_id'), {'snapshot_id': snapshot.id})
    db.flush()
    return index


def search_originals(db, payload):
    if CURRENT_WORDS.search(payload.text):
        raise HTTPException(409, {'code': 'online_query_required', 'message': '请使用在线查询核对当前状态。'})
    terms = query_tokens(payload.text)
    if not terms:
        return {'mode': 'history', 'data_state': 'local_snapshot', 'items': [], 'total': 0,
                'offset': payload.offset, 'limit': payload.limit, 'has_more': False, 'notice': NOTICE}
    QueryService(db, None).lock_ingestion()
    heads = latest_tire_heads(db, source_ids=[payload.source_id] if payload.source_id else None)
    ids = set(head['snapshot_id'] for head in heads)
    selected = list(db.scalars(select(Snapshot.id).where(Snapshot.id.in_(ids), Snapshot.content_type.in_(SUPPORTED_TYPES))))
    for snapshot_id in selected:
        index_snapshot(db, snapshot_id)
    backend = db.get_bind().dialect.name
    if backend == 'sqlite':
        fulltext = text('SELECT chunk_id AS id, bm25(source_text_fts) AS score FROM source_text_fts '
                        'WHERE source_text_fts MATCH :terms').columns(id=String, score=Float).subquery()
        query = ' AND '.join('"' + term.replace('"', '""') + '"' for term in terms)
    else:
        fulltext = text("SELECT id, -ts_rank_cd(search_vector, plainto_tsquery('simple', :terms)) AS score "
                        "FROM source_text_chunks WHERE search_vector @@ plainto_tsquery('simple', :terms)")\
            .columns(id=String, score=Float).subquery()
        query = ' '.join(terms)
    statement = select(SourceTextChunk, fulltext.c.score).join(fulltext, fulltext.c.id == SourceTextChunk.id)\
        .where(SourceTextChunk.snapshot_id.in_(selected))
    total = db.scalar(select(func.count()).select_from(statement.subquery()), {'terms': query}) or 0
    matches = db.execute(statement.order_by(fulltext.c.score, SourceTextChunk.id)
        .offset(payload.offset).limit(payload.limit), {'terms': query}).all()
    items = []
    for chunk, score in matches:
        reference = SourceTextCitation(snapshot_id=chunk.snapshot_id, raw_hash=chunk.raw_hash,
            extractor_version=chunk.extractor_version, start=chunk.start, end=chunk.end, chunk_id=chunk.id)
        item = resolve_reference(db, reference)
        actual_tokens = tokens(item['text'])
        if (item['text'] != chunk.text or chunk.tokens != ' '.join(actual_tokens)
                or not set(terms).issubset(actual_tokens)):
            fail('source_text_index_invalid')
        items.append({**item, 'match': {'method': 'fts', 'matched_terms': terms, 'score': float(score)}})
    db.commit()
    return {'mode': 'history', 'data_state': 'local_snapshot', 'items': items, 'total': total,
            'offset': payload.offset, 'limit': payload.limit, 'has_more': total > payload.offset + payload.limit,
            'index': {'engine': 'sqlite_fts5' if backend == 'sqlite' else 'postgresql_fts',
                      'extractor_version': EXTRACTOR_VERSION, 'snapshots': len(selected)}, 'notice': NOTICE}


def register_source_text_routes(app: FastAPI):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post('/v1/knowledge/source-text/search')
    def search(payload: SourceTextSearch, db=Depends(get_db)):
        return search_originals(db, payload)

    @app.post('/v1/knowledge/source-text/resolve')
    def resolve(payload: ResolveSourceText, db=Depends(get_db)):
        return resolve_reference(db, payload.reference)
