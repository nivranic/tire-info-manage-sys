"""Explicit external-processing endpoints; ordinary knowledge search remains local."""
import asyncio
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import Field, StrictBool, model_validator
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, load_only

from .dense import capability, coverage, current_materials, ensure_hnsw, hybrid_result, mirror_cache
from .auth import session_scope
from .domain import StrictModel, digest
from .embedding_budget import budget_usage
from .embedding_gateway import (EmbeddingError, OpenAIEmbeddingAdapter, configured_embeddings,
                                model_status, safe_error, validate_receipt)
from .embedding_models import EmbeddingCompletion, EmbeddingRequest
from .embedding_service import (begin_idempotent, complete, prepare_plan, require_config, reserve_request,
                                run_view, save_vectors, validate_plan)
from .knowledge import CURRENT_WORDS, KnowledgeSearch, interpret, lexical_candidates, search_history
from .knowledge_index import refresh_index
from .service import QueryService


class PlanRequest(StrictModel):
    document_ids: list[str] = Field(min_length=1, max_length=6)

    @model_validator(mode='after')
    def unique_ids(self):
        if len(set(self.document_ids)) != len(self.document_ids) or any(not value or len(value) > 64 for value in self.document_ids):
            raise ValueError('请选择 1–6 个不同的文档')
        return self


class BuildRequest(StrictModel):
    plan_id: str = Field(min_length=1, max_length=64)
    allow_external_processing: StrictBool


class HybridRequest(StrictModel):
    search: KnowledgeSearch
    allow_external_processing: StrictBool


def external_consent(value):
    if value is not True:
        raise HTTPException(422, '需要明确允许将预览分块或查询文本发送到 OpenAI')


async def call_embedding(app, config, inputs):
    try:
        receipt = validate_receipt(await app.state.embedding_adapter.embed(config, inputs), config, len(inputs))
        from .telemetry import record_ai_usage
        record_ai_usage('openai_embeddings', receipt['usage'])
        return receipt, None
    except EmbeddingError as error:
        return None, safe_error(str(error))
    except Exception:
        return None, 'embeddings_provider_failed'


def observed_embedding(execute):
    """Observe only a reserved external attempt, through validation and commit."""
    from .telemetry import observe
    with observe('ai.embedding', component='ai') as operation:
        result = execute()
        operation.finish(result['state'])
        return result


def register_embedding_routes(app: FastAPI):
    app.state.embedding_adapter = OpenAIEmbeddingAdapter()
    # These endpoints perform synchronous SQL and lock acquisition. Run them in
    # FastAPI's worker pool; blocking on another transaction must not freeze the
    # event loop that releases request resources. The bounded HTTP coroutine owns
    # its client/loop within that worker and never shares an ambient client.

    def get_db():
        with app.state.database.sessions() as db:
            yield db

    @app.get('/v1/knowledge/vector-status')
    def status(db: Session = Depends(get_db)):
        available, reason = capability(db)
        model, scope = model_status(), None
        if model['state'] != 'configured':
            reason = reason or model['state']
            available = False
        if available:
            config = configured_embeddings()
            QueryService(db, None).lock_ingestion()
            refresh_index(db, app.state.registry)
            materials = current_materials(db, config)
            scope = coverage(materials)
            db.commit()
        return {'backend': db.get_bind().dialect.name, 'available': available, 'reason': reason,
                'model': model, 'coverage': scope, 'budget': budget_usage(db),
                'notice': '配置不表示云端连接已经验证；所配置模型须支持 dimensions 参数。'
                          '只有明确确认的建立索引或混合查询会外发；预算是 token 预留，不是金额上限。'}

    @app.post('/v1/knowledge/embedding-plans')
    def plan(payload: PlanRequest, request: Request, db: Session = Depends(get_db)):
        return prepare_plan(db, app.state.registry, payload.document_ids, request.state.session_id)

    @app.post('/v1/knowledge/embedding-runs')
    def build(payload: BuildRequest, request: Request, response: Response,
                    idempotency_key: str = Header(alias='Idempotency-Key', max_length=64), db: Session = Depends(get_db)):
        key, request_hash, existing = begin_idempotent(db, request.state.session_id, idempotency_key, 'index', payload.model_dump())
        if existing:
            value = run_view(db, existing)
            db.commit()
            response.status_code = 202 if value['state'] == 'pending' else 200
            return value
        external_consent(payload.allow_external_processing)
        config = require_config(db)
        plan, materials, missing = validate_plan(db, app.state.registry, payload.plan_id, request.state.session_id, config)
        inputs = [chunk['text'] for chunk in missing]
        row = reserve_request(db, config=config, session_id=request.state.session_id, key=key, kind='index',
            request_hash=request_hash, payload={'plan_id': plan.id, 'input_hashes': [chunk['hash'] for chunk in missing]},
            inputs=inputs, plan_id=plan.id)
        def execute():
            usage, written = None, 0
            if inputs:
                receipt, error = asyncio.run(call_embedding(app, config, inputs))
                if error:
                    return complete(db, row, error=error)
                usage = receipt['usage']
            try:
                QueryService(db, None).lock_ingestion()
                if inputs:
                    written = save_vectors(db, config, missing, receipt['vectors'])
                refresh_index(db, app.state.registry)
                now = current_materials(db, config)
                mirror_cache(db, now[2])
                ensure_hnsw(db, config)
                unique_count = len({chunk['cache_id'] for doc in materials for chunk in doc['chunks']})
                return complete(db, row, usage=usage, result={'cached_chunks': unique_count - len(missing),
                    'written_chunks': written, 'documents': len(materials), 'coverage': coverage(now),
                    'notice': '内容缓存保留历史向量；检索只关联当前正式投影，撤销记录不会因旧缓存复活。'})
            except Exception:
                db.rollback()
                return complete(db, row, usage=usage, error='embeddings_storage_failed')
        return observed_embedding(execute) if inputs else execute()

    @app.post('/v1/knowledge/hybrid-search')
    def hybrid(payload: HybridRequest, request: Request, response: Response,
                     idempotency_key: str = Header(alias='Idempotency-Key', max_length=64), db: Session = Depends(get_db)):
        key, request_hash, existing = begin_idempotent(db, request.state.session_id, idempotency_key, 'hybrid', payload.model_dump())
        if existing:
            value = run_view(db, existing)
            db.commit()
            response.status_code = 202 if value['state'] == 'pending' else 200
            return value
        if CURRENT_WORDS.search(payload.search.text):
            raise HTTPException(409, {'code': 'online_query_required', 'message': '当前信息须使用在线查询，历史混合检索不能回答'})
        external_consent(payload.allow_external_processing)
        filters, _, terms, sufficient = interpret(payload.search)
        if sufficient:
            result = search_history(db, app.state.registry, payload.search)
            result['notice'] += '结构化筛选已充分表达查询，本次未调用外部服务。'
            result['total_scope'] = 'structured_matches'
            result['external_processing'] = {'query_text_sent': False}
            result['coverage'] = None
            result['candidate_counts'] = {'fts': 0, 'dense': 0, 'merged': result['total'], 'limit': result['total']}
            db.commit()
            # Local search released the ingestion lock. Another same-key request
            # may have completed meanwhile; recheck before reserving a zero-cost
            # receipt instead of racing the unique constraint.
            key, request_hash, existing = begin_idempotent(db, request.state.session_id, idempotency_key,
                                                          'hybrid', payload.model_dump())
            if existing:
                value = run_view(db, existing)
                db.commit()
                response.status_code = 202 if value['state'] == 'pending' else 200
                return value
            row = reserve_request(db, config=None, session_id=request.state.session_id, key=key, kind='hybrid',
                request_hash=request_hash, payload=payload.search.model_dump(), inputs=[])
            return complete(db, row, result=result)
        config = require_config(db)
        refresh_index(db, app.state.registry)
        materials = current_materials(db, config, filters)
        if not materials[3]:
            raise HTTPException(409, '当前筛选范围没有完整向量索引，请先预览并建立索引；未调用外部服务')
        # Execute lexical retrieval before the paid query embedding. It is rerun
        # against the same current post-call snapshot as dense if ingestion advances.
        lexical_candidates(db, filters, terms, limit=100)
        row = reserve_request(db, config=config, session_id=request.state.session_id, key=key, kind='hybrid',
            request_hash=request_hash, payload=payload.search.model_dump(), inputs=[payload.search.text])
        def execute():
            receipt, error = asyncio.run(call_embedding(app, config, [payload.search.text]))
            if error:
                return complete(db, row, error=error)
            try:
                QueryService(db, None).lock_ingestion()
                state = refresh_index(db, app.state.registry)
                materials = current_materials(db, config, filters)
                if not materials[3]:
                    return complete(db, row, usage=receipt['usage'], error='embeddings_result_stale')
                mirror_cache(db, materials[2])
                result = hybrid_result(db, config, payload.search,
                    {'engine': 'postgresql_fts_pgvector', 'documents': state.documents, 'version': state.version},
                    materials, receipt['vectors'][0])
                return complete(db, row, result=result, usage=receipt['usage'])
            except Exception:
                db.rollback()
                return complete(db, row, usage=receipt['usage'], error='embeddings_storage_failed')
        return observed_embedding(execute)

    @app.get('/v1/knowledge/embedding-runs/{run_id}')
    def get_run(run_id: str, request: Request, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        row = db.get(EmbeddingRequest, run_id)
        if row is None or row.actor_session_id not in session_scope(db, request.state.session_id):
            raise HTTPException(404, '未找到当前账户的向量调用记录')
        return run_view(db, row)

    @app.get('/v1/knowledge/embedding-runs')
    def history(request: Request, mode: Literal['history'] = Query(...), db: Session = Depends(get_db)):
        rows = db.execute(select(EmbeddingRequest, EmbeddingCompletion).outerjoin(EmbeddingCompletion,
            EmbeddingCompletion.request_id == EmbeddingRequest.id).options(load_only(
                EmbeddingCompletion.request_id, EmbeddingCompletion.state, EmbeddingCompletion.error_code,
                EmbeddingCompletion.usage, EmbeddingCompletion.created_at))
            .where(EmbeddingRequest.actor_session_id.in_(session_scope(db, request.state.session_id)))
            .order_by(desc(EmbeddingRequest.created_at), desc(EmbeddingRequest.id)).limit(20)).all()
        return {'scope': 'actor', 'items': [run_view(db, row, completion, prefetched=True, include_result=False)
                                                     for row, completion in rows]}
