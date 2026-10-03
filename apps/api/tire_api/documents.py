"""Opaque user-authorized PDF receipts; never parsed or promoted to tire facts."""
import base64
import binascii
import json
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import Field, ValidationError, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .db import EvidenceDocument, EvidenceObject
from .domain import StrictModel
from .object_store import MAX_OBJECT_BYTES, ObjectStoreError
from .research import DescriptionText
from .service import QueryService, timestamp


def record_object(db: Session, data: bytes, store=None) -> str:
    store = store or db.info['object_store']
    digest = store.put(data)
    register_object(db, digest, len(data))
    return digest


def register_object(db: Session, digest: str, size: int) -> None:
    if db.get_bind().dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    db.execute(insert(EvidenceObject).values(raw_hash=digest, byte_count=size)
               .on_conflict_do_nothing(index_elements=['raw_hash']))
    saved = db.get(EvidenceObject, digest)
    if saved is None or saved.byte_count != size:
        raise ObjectStoreError('object_metadata_conflict')


class DocumentMetadata(StrictModel):
    title: DescriptionText = Field(min_length=1, max_length=160)
    source_url: str = Field(default='', max_length=2048)
    operator: DescriptionText = Field(min_length=1, max_length=80)
    rights_basis: DescriptionText = Field(min_length=1, max_length=500)

    @field_validator('source_url')
    @classmethod
    def public_reference(cls, value):
        if not value:
            return value
        try:
            parsed = urlsplit(value)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment or parsed.port not in (None, 443)
                    or '\\' in value or any(ord(c) < 32 for c in value)):
                raise ValueError('invalid')
        except ValueError:
            raise ValueError('来源引用只接受不含凭据、查询参数和片段的 HTTPS 地址') from None
        return value


def document_metadata(row: EvidenceDocument, size: int) -> dict:
    return {'id': row.id, 'raw_hash': row.raw_hash, 'byte_count': size, 'title': row.title,
            'source_url': row.source_url, 'operator': row.operator, 'rights_basis': row.rights_basis,
            'content_type': row.content_type, 'created_at': timestamp(row.created_at),
            'status': 'unparsed_receipt', 'accepted_as_facts': False}


def register_document_routes(app: FastAPI) -> None:
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.post('/v1/documents', status_code=201)
    async def upload(request: Request, db: Session = Depends(get_db)) -> dict:
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/pdf':
            raise HTTPException(415, '目前仅接收 PDF 原始文档')
        metadata_header = request.headers.get('x-evidence-metadata', '')
        if not metadata_header or len(metadata_header) > 8192:
            raise HTTPException(422, '请提供有界的文档说明与保存授权依据')
        try:
            payload = DocumentMetadata.model_validate(json.loads(base64.b64decode(metadata_header, validate=True).decode('utf-8')))
        except (ValueError, UnicodeError, binascii.Error, ValidationError):
            raise HTTPException(422, '文档说明、署名或保存授权依据无效') from None
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_OBJECT_BYTES:
                raise HTTPException(413, '原始文档不得超过 8 MiB')
            body.extend(chunk)
        if not body.startswith(b'%PDF-'):
            raise HTTPException(422, '文件没有 PDF 标识；原文未保存')
        service = QueryService(db, None)
        # Storage publication can precede DB commit; failures can leave unreferenced
        # objects, never a committed document whose put has not finished.
        try:
            digest = await run_in_threadpool(db.info['object_store'].put, bytes(body))
            service.lock_ingestion()
            register_object(db, digest, len(body))
        except ObjectStoreError:
            raise HTTPException(503, '原文存储未完成，未创建文档记录') from None
        row = EvidenceDocument(raw_hash=digest, content_type='application/pdf',
                               actor_session_id=request.state.session_id, **payload.model_dump())
        db.add(row)
        db.flush()
        service.audit(request.state.session_id, 'evidence_document_received', document_id=row.id, raw_hash=digest)
        db.commit()
        return document_metadata(row, len(body))

    @app.get('/v1/documents')
    def listing(mode: Literal['history'] = Query(...), offset: int = Query(0, ge=0), db: Session = Depends(get_db)) -> dict:
        rows = db.execute(select(EvidenceDocument, EvidenceObject.byte_count)
            .join(EvidenceObject, EvidenceObject.raw_hash == EvidenceDocument.raw_hash)
            .order_by(desc(EvidenceDocument.created_at), desc(EvidenceDocument.id)).offset(offset).limit(50)).all()
        return {'scope': 'local_workspace', 'storage_backend': db.info['object_store'].backend,
                'items': [document_metadata(row, size) for row, size in rows],
                'total': db.scalar(select(func.count()).select_from(EvidenceDocument)) or 0, 'offset': offset,
                'notice': '用户声明有权保存的原始文档；未解析、未核验，不作为轮胎或车型事实。'}

    @app.get('/v1/documents/{document_id}/content')
    def content(document_id: str, request: Request, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)) -> Response:
        row = db.get(EvidenceDocument, document_id)
        if row is None:
            raise HTTPException(404, '未找到原始文档')
        blob = db.get(EvidenceObject, row.raw_hash)
        if blob is None:
            raise HTTPException(503, '原文元信息缺失，未返回内容')
        try:
            data = db.info['object_store'].get(row.raw_hash, blob.byte_count)
        except ObjectStoreError:
            raise HTTPException(503, '原文缺失或完整性校验失败，未返回内容') from None
        QueryService(db, None).audit(request.state.session_id, 'evidence_document_downloaded', document_id=row.id, raw_hash=row.raw_hash)
        db.commit()
        return Response(data, media_type='application/pdf', headers={
            'Content-Disposition': f'attachment; filename="evidence-{row.raw_hash}.pdf"',
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "sandbox; default-src 'none'", 'X-Evidence-SHA256': row.raw_hash})
