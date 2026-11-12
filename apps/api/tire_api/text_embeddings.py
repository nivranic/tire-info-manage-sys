"""Original-bound excerpt permissions and plans for the shared embedding ledger."""
import asyncio
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request
from pydantic import AwareDatetime, Field, StrictBool, StrictInt, field_validator, model_validator
from sqlalchemy import desc, select

from .auth import current_user, make_admin_guard
from .db import utc, utcnow
from .document_text import (DocumentTextReference, extract_original, resolve_extracted_reference)
from .domain import StrictModel, digest
from .embedding_gateway import configured_embeddings, EmbeddingError, reservation, valid_vector
from .embedding_models import EmbeddingCache, EmbeddingPlan
from .embedding_text import bounded_batch
from .material_source_policy import plain
from .parser_runtime import ParserRunError
from .service import QueryService
from .source_text import SourceTextCitation, resolve_reference
from .text_embedding_models import TextEmbeddingAuthorization

TEXT_CONTRACT = 'original-text-semantic@1'
PURPOSE = 'original_text_embedding@1'
LOCAL_ERRORS = frozenset({'text_embedding_original_invalid', 'text_embedding_authorization_invalid',
    'text_embedding_use_not_allowed', 'text_embedding_binding_failed'})


def fail(code, status=409):
    raise HTTPException(status, {'code': code, 'message': '正文原件、用途许可或向量计划需要重新核对。'})


class SourceSelection(StrictModel):
    kind: Literal['source_text']
    reference: SourceTextCitation


class DocumentSelection(StrictModel):
    kind: Literal['document_text']
    reference: DocumentTextReference


TextSelection = Annotated[SourceSelection | DocumentSelection, Field(discriminator='kind')]


class PreviewRequest(StrictModel):
    selection: TextSelection


class AuthorizationRequest(PreviewRequest):
    expected_revision: StrictInt = Field(ge=0)
    scope_hash: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    action: Literal['grant', 'revoke']
    rights_basis: str = Field(min_length=1, max_length=1000)
    privacy_class: Literal['public', 'private']
    expires_at: AwareDatetime | None = None
    acknowledged: StrictBool

    _basis = field_validator('rights_basis')(plain)

    @model_validator(mode='after')
    def valid_permission(self):
        if not self.acknowledged:
            raise ValueError('需要确认本次用途许可声明')
        if self.action == 'grant' and self.expires_at is not None and self.expires_at <= utcnow():
            raise ValueError('用途许可到期时间须晚于当前时间')
        return self


class TextPlanRequest(StrictModel):
    selections: list[TextSelection] = Field(min_length=1, max_length=32)

    @model_validator(mode='after')
    def unique_references(self):
        if len({digest(item.model_dump()) for item in self.selections}) != len(self.selections):
            raise ValueError('请选择不同的正文引用')
        return self


def recipient(config):
    return {'provider': 'openai_embeddings', 'endpoint': config.endpoint, 'allowed_host': config.allowed_host}


def scope_for(selection, config):
    return digest({'purpose': PURPOSE, 'selection': selection.model_dump(), 'recipient': recipient(config)})


def original_excerpt(db, selection, pdfs):
    try:
        if selection.kind == 'source_text':
            return resolve_reference(db, selection.reference)
        identity = selection.reference.document_id
        if identity not in pdfs:
            pdfs[identity] = asyncio.run(extract_original(db, identity, release_transaction=False))
        extracted, _receipt, metadata, fingerprint = pdfs[identity]
        return resolve_extracted_reference(selection.reference, extracted, metadata, fingerprint)
    except (HTTPException, ParserRunError):
        fail('text_embedding_original_invalid')


def authorization_head(db, scope):
    row = db.scalar(select(TextEmbeddingAuthorization).where(TextEmbeddingAuthorization.scope_hash == scope)
        .order_by(desc(TextEmbeddingAuthorization.revision)).limit(1).execution_options(populate_existing=True))
    return checked_authorization(row)


def checked_authorization(row):
    if row is not None:
        value = {'scope_hash': row.scope_hash, 'revision': row.revision,
                 'actor_user_id': row.actor_user_id, 'payload': row.payload}
        if digest(value) != row.fingerprint:
            fail('text_embedding_authorization_invalid')
    return row


def authorization_view(row):
    if row is None:
        return {'state': 'missing', 'revision': 0, 'revision_id': None}
    try:
        request = row.payload['request']
        expiration = request['expires_at']
        expired = expiration is not None and utc(datetime.fromisoformat(expiration)) <= utcnow()
        state = {'grant': 'granted', 'revoke': 'revoked'}[request['action']]
        if state == 'granted' and expired:
            state = 'expired'
        return {'state': state, 'revision': row.revision, 'revision_id': row.id}
    except (KeyError, ValueError, TypeError):
        fail('text_embedding_authorization_invalid')


def chunk_for_excerpt(value, privacy, config):
    text_hash = digest(value)
    return {'text': value, 'hash': text_hash, 'privacy_class': privacy, 'text_contract': TEXT_CONTRACT,
        'cache_id': digest({'provider': 'openai_embeddings', 'model_space': config.model_space,
            'recipient': recipient(config),
            'model': config.model, 'dimensions': config.dimensions, 'text_contract': TEXT_CONTRACT,
            'privacy_class': privacy, 'text_hash': text_hash})}


def material(db, selection, config, pdfs):
    excerpt = original_excerpt(db, selection, pdfs)
    scope = scope_for(selection, config)
    authorization = authorization_head(db, scope)
    if authorization_view(authorization)['state'] != 'granted':
        fail('text_embedding_use_not_allowed', 403)
    try:
        payload = authorization.payload
        if (payload['purpose'] != PURPOSE or payload['selection'] != selection.model_dump()
                or payload['recipient'] != recipient(config) or payload['text_hash'] != digest(excerpt['text'])):
            fail('text_embedding_authorization_invalid')
        privacy = payload['request']['privacy_class']
        if privacy not in {'public', 'private'} or privacy == 'private' and not config.allow_private:
            fail('text_embedding_use_not_allowed', 403)
    except (KeyError, TypeError):
        fail('text_embedding_authorization_invalid')
    chunk = chunk_for_excerpt(excerpt['text'], privacy, config)
    label = excerpt['document']['title'] if selection.kind == 'document_text' else excerpt['source_id']
    return {'id': selection.reference.chunk_id, 'label': label, 'privacy_class': privacy,
        'selection': selection.model_dump(), 'authorization_id': authorization.id, 'chunks': [chunk]}


def checked_caches(db, config, unique):
    cached = {row.id: row for row in db.scalars(select(EmbeddingCache).where(EmbeddingCache.id.in_(unique)))}
    for key, row in cached.items():
        chunk = unique[key]
        if (row.model_space != config.model_space or row.provider != 'openai_embeddings'
                or row.model != config.model or row.dimensions != config.dimensions
                or row.text_contract != TEXT_CONTRACT or row.text_hash != chunk['hash']
                or row.privacy_class != chunk['privacy_class']):
            fail('text_embedding_binding_failed')
        try:
            valid_vector(row.vector, config.dimensions)
        except EmbeddingError:
            fail('text_embedding_binding_failed')
    return cached


def text_materials(db, selections, config):
    pdfs = {}
    documents = [material(db, selection, config, pdfs) for selection in selections]
    unique = {chunk['cache_id']: chunk for doc in documents for chunk in doc['chunks']}
    bounded_batch(list(unique.values()))
    cached = checked_caches(db, config, unique)
    for doc in documents:
        for chunk in doc['chunks']:
            row = cached.get(chunk['cache_id'])
            chunk['cached'] = row is not None
    return documents, [chunk for key, chunk in unique.items() if key not in cached]


def material_signature(documents):
    return digest([{**doc, 'chunks': [{key: value for key, value in chunk.items() if key != 'cached'}
        for chunk in doc['chunks']]} for doc in documents])


def checked_plan_materials(db, plan, config):
    try:
        payload = plan.payload
        if (digest(payload) != plan.fingerprint or plan.model_space != config.model_space
                or payload['model'] != config.model or payload['dimensions'] != config.dimensions
                or payload['text_contract'] != TEXT_CONTRACT or utc(plan.expires_at) <= utcnow()):
            fail('text_embedding_binding_failed')
        selections = TextPlanRequest.model_validate({'selections': [doc['selection'] for doc in payload['documents']]}).selections
        current, missing = text_materials(db, selections, config)
        if material_signature(current) != material_signature(payload['documents']):
            fail('text_embedding_binding_failed')
        return current, missing
    except (KeyError, ValueError, TypeError, AttributeError):
        fail('text_embedding_binding_failed')


def prepare_plan(db, selections, session_id):
    from .embedding_service import plan_view, require_config
    QueryService(db, None).lock_ingestion()
    config = require_config(db)
    documents, missing = text_materials(db, selections, config)
    payload = {'model': config.model, 'dimensions': config.dimensions, 'text_contract': TEXT_CONTRACT,
        'documents': documents, 'pending_chunks': len(missing),
        'reserved_tokens': reservation([chunk['text'] for chunk in missing]) if missing else 0}
    plan = EmbeddingPlan(actor_session_id=session_id, model_space=config.model_space, payload=payload,
        fingerprint=digest(payload), expires_at=utcnow() + timedelta(minutes=5))
    db.add(plan)
    db.flush()
    QueryService(db, None).audit(session_id, 'text_embedding_plan_prepared', plan_id=plan.id,
        excerpt_count=len(documents), pending_chunks=len(missing))
    db.commit()
    return {**plan_view(plan), 'text_contract': TEXT_CONTRACT,
        'selections': [{'selection': doc['selection'], 'authorization_id': doc['authorization_id']} for doc in documents]}


def register_text_embedding_routes(app):
    def get_db():
        with app.state.database.sessions() as db:
            yield db

    admin_guard = make_admin_guard(get_db)

    def configured():
        try:
            return configured_embeddings()
        except EmbeddingError as error:
            raise HTTPException(503, str(error)) from None

    @app.post('/v1/knowledge/text-embedding-authorizations/preview')
    def preview(payload: PreviewRequest, db=Depends(get_db)):
        config = configured()
        excerpt = original_excerpt(db, payload.selection, {})
        scope = scope_for(payload.selection, config)
        return {'purpose': PURPOSE, 'selection': payload.selection.model_dump(), 'text': excerpt['text'],
            'text_hash': digest(excerpt['text']), 'recipient': recipient(config), 'scope_hash': scope,
            'authorization': authorization_view(authorization_head(db, scope)),
            'notice': '用途依据由管理员声明并记录。建立向量时仍需单次确认外部处理。'}

    @app.post('/v1/knowledge/text-embedding-authorizations', dependencies=[Depends(admin_guard)])
    def authorize(payload: AuthorizationRequest, request: Request, db=Depends(get_db)):
        QueryService(db, None).lock_ingestion()
        scope = payload.scope_hash if payload.action == 'revoke' else None
        config = None
        if scope is None:
            config = configured()
            scope = scope_for(payload.selection, config)
        if payload.scope_hash is not None and payload.scope_hash != scope:
            fail('text_embedding_binding_failed')
        previous = authorization_head(db, scope)
        if payload.expected_revision != (previous.revision if previous else 0):
            fail('text_embedding_binding_failed')
        if payload.action == 'revoke':
            if previous is None:
                fail('text_embedding_use_not_allowed', 404)
            if previous.payload['selection'] != payload.selection.model_dump():
                fail('text_embedding_binding_failed')
            text_hash = previous.payload['text_hash']
            receiving = previous.payload['recipient']
        else:
            text_hash = digest(original_excerpt(db, payload.selection, {})['text'])
            receiving = recipient(config)
        owner = current_user(db, request.state.session_id)
        value = {'purpose': PURPOSE, 'selection': payload.selection.model_dump(),
            'text_hash': text_hash, 'recipient': receiving, 'request': payload.model_dump(mode='json')}
        binding = {'scope_hash': scope, 'revision': payload.expected_revision + 1,
                   'actor_user_id': owner.id, 'payload': value}
        row = TextEmbeddingAuthorization(**binding, fingerprint=digest(binding))
        db.add(row)
        db.flush()
        QueryService(db, None).audit(request.state.session_id, 'text_embedding_authorization_added',
            authorization_id=row.id, revision=row.revision, authorization_action=payload.action)
        db.commit()
        return {'purpose': PURPOSE, 'scope_hash': scope, 'authorization': authorization_view(row)}

    @app.post('/v1/knowledge/text-embedding-plans')
    def plan(payload: TextPlanRequest, request: Request, db=Depends(get_db)):
        return prepare_plan(db, payload.selections, request.state.session_id)
