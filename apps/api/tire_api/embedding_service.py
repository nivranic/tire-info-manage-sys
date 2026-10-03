"""Local planning, authorization, idempotency and durable embedding budget reservations."""
from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from .db import utc, utcnow
from .dense import capability, current_materials, mirror_cache
from .domain import digest
from .embedding_budget import PENDING_WINDOW, budget_usage
from .embedding_gateway import EmbeddingError, configured_embeddings, reservation
from .embedding_models import EmbeddingCache, EmbeddingCompletion, EmbeddingPlan, EmbeddingRequest
from .embedding_text import TEXT_CONTRACT, bounded_batch, document_chunks
from .knowledge_index import refresh_index
from .knowledge_models import KnowledgeDocument
from .service import QueryService, timestamp


def require_config(db):
    available, reason = capability(db)
    if not available:
        raise HTTPException(503, {'code': reason, 'message': '本次需要 PostgreSQL 和 pgvector；未调用外部服务'})
    try:
        return configured_embeddings()
    except EmbeddingError as error:
        raise HTTPException(503, str(error)) from None


def document_material(db, documents, config):
    result, unique = [], {}
    for document in documents:
        privacy = document.payload['privacy_class']
        if privacy not in {'public', 'private'} or privacy == 'private' and not config.allow_private:
            raise HTTPException(403, '当前策略不允许向外部模型发送这些非公开文档')
        chunks = document_chunks(document, config)
        result.append({'id': document.id, 'label': document.payload['label'], 'privacy_class': privacy, 'chunks': chunks})
        unique.update({item['cache_id']: item for item in chunks})
    bounded_batch(list(unique.values()))
    cached = set(db.scalars(select(EmbeddingCache.id).where(EmbeddingCache.id.in_(unique)))) if unique else set()
    for document in result:
        for chunk in document['chunks']:
            chunk['cached'] = chunk['cache_id'] in cached
    return result, [chunk for key, chunk in unique.items() if key not in cached]


def plan_view(plan):
    return {'id': plan.id, 'model': plan.payload['model'], 'dimensions': plan.payload['dimensions'],
        'expires_at': timestamp(plan.expires_at), 'documents': [
            {**{key: document[key] for key in ('id', 'label', 'privacy_class')}, 'chunks': [
                {key: chunk[key] for key in ('text', 'hash', 'cached')} for chunk in document['chunks']]}
            for document in plan.payload['documents']],
        'pending_chunks': plan.payload['pending_chunks'], 'reserved_tokens': plan.payload['reserved_tokens']}


def prepare_plan(db, registry, ids, session_id):
    QueryService(db, None).lock_ingestion()
    config = require_config(db)
    refresh_index(db, registry)
    documents = list(db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.id.in_(ids))))
    if len(documents) != len(ids):
        raise HTTPException(409, '所选历史文档已变化或撤销，请重新检索后准备计划')
    documents.sort(key=lambda row: ids.index(row.id))
    materials, missing = document_material(db, documents, config)
    payload = {'model': config.model, 'dimensions': config.dimensions, 'text_contract': TEXT_CONTRACT,
               'documents': materials, 'pending_chunks': len(missing),
               'reserved_tokens': reservation([item['text'] for item in missing]) if missing else 0}
    plan = EmbeddingPlan(actor_session_id=session_id, model_space=config.model_space, payload=payload,
                         fingerprint=digest(payload), expires_at=utcnow() + timedelta(minutes=5))
    db.add(plan)
    db.flush()
    QueryService(db, None).audit(session_id, 'embedding_plan_prepared', plan_id=plan.id,
                               document_count=len(ids), pending_chunks=len(missing))
    db.commit()
    return plan_view(plan)


def validate_plan(db, registry, plan_id, session_id, config):
    plan = db.get(EmbeddingPlan, plan_id)
    if plan is None or plan.actor_session_id != session_id:
        raise HTTPException(404, '未找到本会话的向量建立计划')
    if (utc(plan.expires_at) <= utcnow() or digest(plan.payload) != plan.fingerprint
            or plan.model_space != config.model_space or plan.payload['text_contract'] != TEXT_CONTRACT):
        raise HTTPException(409, '计划已过期或模型配置已变化，请重新预览')
    refresh_index(db, registry)
    ids = [document['id'] for document in plan.payload['documents']]
    documents = list(db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.id.in_(ids))))
    if len(documents) != len(ids):
        raise HTTPException(409, '计划文档已变化或撤销，请重新检索')
    documents.sort(key=lambda row: ids.index(row.id))
    current, missing = document_material(db, documents, config)
    def signature(values):
        return digest([{**{key: document[key] for key in ('id', 'label', 'privacy_class')},
                        'chunks': [item['cache_id'] for item in document['chunks']]} for document in values])
    if signature(current) != signature(plan.payload['documents']):
        raise HTTPException(409, '计划内容已变化，请重新预览')
    return plan, current, missing


def begin_idempotent(db, session_id, key, kind, payload):
    try:
        key = str(UUID(key))
    except ValueError:
        raise HTTPException(422, 'Idempotency-Key 必须是 UUID') from None
    QueryService(db, None).lock_ingestion()
    request_hash = digest({'kind': kind, **payload})
    existing = db.scalar(select(EmbeddingRequest).where(EmbeddingRequest.actor_session_id == session_id,
                                                       EmbeddingRequest.idempotency_key == key))
    if existing and existing.request_hash != request_hash:
        raise HTTPException(409, '同一幂等键不能用于不同计划或查询')
    return key, request_hash, existing


def reserve_request(db, *, config, session_id, key, kind, request_hash, payload, inputs, plan_id=None):
    billable = bool(inputs)
    reserve = reservation(inputs) if billable else 0
    if billable:
        usage = budget_usage(db)
        if usage['requests'] >= config.daily_request_limit or usage['accounted_tokens'] + reserve > config.daily_token_limit:
            raise HTTPException(429, '共享 AI 当日预算不足，未调用外部服务')
        if usage['has_pending_request']:
            raise HTTPException(429, '已有外部 AI 请求尚未确认完成，请先查看调用记录')
    row = EmbeddingRequest(actor_session_id=session_id, idempotency_key=key, kind=kind,
        request_hash=request_hash, model_space=config.model_space if config else None, plan_id=plan_id,
        payload=payload, billable=billable, reserved_tokens=reserve)
    db.add(row)
    db.flush()
    QueryService(db, None).audit(session_id, 'embedding_request_started', request_id=row.id,
                               kind=kind, reserved_tokens=reserve, billable=billable)
    db.commit()
    return row


def run_view(db, row, completion=None, *, prefetched=False, include_result=True):
    if not prefetched:
        completion = db.get(EmbeddingCompletion, row.id)
    state = completion.state if completion else 'outcome_unknown' if utc(row.created_at) + PENDING_WINDOW <= utcnow() else 'pending'
    return {'id': row.id, 'kind': row.kind, 'state': state, 'reserved_tokens': row.reserved_tokens,
            'usage': completion.usage if completion else None, 'error_code': completion.error_code if completion else None,
            'result': completion.result if completion and include_result else None,
            'created_at': timestamp(row.created_at), 'completed_at': timestamp(completion.created_at) if completion else None}


def complete(db, row, result=None, usage=None, error=None):
    db.add(EmbeddingCompletion(request_id=row.id, state='failed' if error else 'completed',
                               error_code=error, usage=usage, result=result))
    QueryService(db, None).audit(row.actor_session_id, 'embedding_request_finished', request_id=row.id,
                               state='failed' if error else 'completed', error_code=error)
    db.commit()
    return run_view(db, row)


def save_vectors(db, config, chunks, vectors):
    existing = set(db.scalars(select(EmbeddingCache.id).where(EmbeddingCache.id.in_([chunk['cache_id'] for chunk in chunks]))))
    added = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        if chunk['cache_id'] not in existing:
            cache = EmbeddingCache(id=chunk['cache_id'], model_space=config.model_space,
                provider='openai_embeddings', model=config.model, dimensions=config.dimensions,
                text_contract=TEXT_CONTRACT, privacy_class=chunk['privacy_class'], text_hash=chunk['hash'], vector=vector)
            db.add(cache)
            added.append(cache)
            existing.add(cache.id)
    db.flush()
    all_cached = {row.id: row for row in db.scalars(select(EmbeddingCache).where(
        EmbeddingCache.id.in_([chunk['cache_id'] for chunk in chunks])))}
    mirror_cache(db, all_cached)
    return len(added)
