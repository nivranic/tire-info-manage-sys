"""Real pgvector cosine over current filtered documents, plus reciprocal rank fusion."""
from sqlalchemy import select, text

from .domain import stable_json
from .embedding_gateway import valid_vector
from .embedding_models import EmbeddingCache
from .embedding_text import document_chunks
from .knowledge import (_filtered_statement, attach_field_resolutions, attach_identity_contracts,
                        interpret, lexical_candidates, render_ranked)

CANDIDATE_LIMIT = 100
RRF_K = 60


def capability(db):
    backend = db.get_bind().dialect.name
    if backend != 'postgresql':
        return False, 'postgresql_pgvector_required'
    available = db.execute(text("SELECT to_regtype('vector') IS NOT NULL AND to_regclass('embedding_vectors') IS NOT NULL "
                                "AND EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")).scalar()
    return bool(available), None if available else 'pgvector_extension_or_mirror_unavailable'


def current_materials(db, config, filters=None):
    from .knowledge_index import check_current_vehicle_heads, check_vehicle_document_use
    check_current_vehicle_heads(db)
    documents = list(db.scalars(_filtered_statement(filters or {})))
    check_vehicle_document_use(db, documents)
    chunks = {document.id: document_chunks(document, config) for document in documents}
    keys = {item['cache_id'] for values in chunks.values() for item in values}
    cached = {row.id: row for row in db.scalars(select(EmbeddingCache).where(
        EmbeddingCache.id.in_(keys), EmbeddingCache.model_space == config.model_space))} if keys else {}
    complete = {doc_id for doc_id, values in chunks.items() if all(item['cache_id'] in cached for item in values)}
    return documents, chunks, cached, complete


def coverage(materials):
    documents, _, _, complete = materials
    return {'eligible_documents': len(documents), 'indexed_documents': len(complete),
            'missing_documents': len(documents) - len(complete)}


def mirror_cache(db, cached):
    """Recover optional pgvector projection solely from validated immutable cache."""
    if not cached:
        return
    for row in cached.values():
        valid_vector(row.vector, row.dimensions)
    db.execute(text('INSERT INTO embedding_vectors (cache_id, model_space, dimensions, embedding) '
        'SELECT id, model_space, dimensions, CAST(CAST(vector AS text) AS vector) '
        'FROM embedding_cache WHERE id = ANY(:ids) '
        'ON CONFLICT (cache_id) DO UPDATE SET model_space = EXCLUDED.model_space, '
        'dimensions = EXCLUDED.dimensions, embedding = EXCLUDED.embedding '
        'WHERE (embedding_vectors.model_space, embedding_vectors.dimensions, embedding_vectors.embedding) '
        'IS DISTINCT FROM (EXCLUDED.model_space, EXCLUDED.dimensions, EXCLUDED.embedding)'), {'ids': list(cached)})


def ensure_hnsw(db, config):
    from fastapi import HTTPException
    from .postgres_schema import QUERIES
    from .postgres_vector_indexes import index_name, index_sql
    statement = index_sql(config.model_space, config.dimensions, if_not_exists=True)
    if db.info.get('schema_mode') == 'verify':
        name = index_name(config.model_space)
        expected = db.info.get('postgres_indexes', {}).get(name)
        declared = db.info.get('postgres_vector_indexes', {}).get(config.model_space) == config.dimensions
        query = ('SELECT * FROM (' + QUERIES['indexes'] + ') AS indexes('
            'table_name,index_name,is_unique,is_primary,is_immediate,is_valid,is_ready,is_live,definition) '
            "WHERE table_name='embedding_vectors' AND index_name=:name")
        actual = db.execute(text(query), {'name': name}).first() if declared and expected is not None else None
        if actual is None or tuple(actual) != expected:
            raise HTTPException(503, {'code': 'pgvector_index_maintenance_required',
                'message': '当前模型空间的 HNSW 索引需要拥有者依据已批准合同维护'})
        return
    db.execute(text('SELECT pg_advisory_xact_lock(821741906)'))
    db.execute(text(statement))


def cosine_candidates(db, config, materials, query_vector):
    _, chunks, _, complete = materials
    mapping = [{'document_id': doc_id, 'cache_id': item['cache_id']}
               for doc_id in complete for item in chunks[doc_id]]
    if not mapping:
        return []
    # The complete current document mapping was derived with the SAME structured
    # SQL filters as FTS. Join current projection again, materialize before cosine,
    # and scan exactly: approximate HNSW is not used to weaken filtered recall.
    statement = text('WITH eligible AS MATERIALIZED ('
        'SELECT d.id, v.embedding FROM jsonb_to_recordset(CAST(:mapping AS jsonb)) '
        'AS m(document_id text, cache_id text) '
        'JOIN knowledge_documents d ON d.id = m.document_id '
        'JOIN embedding_vectors v ON v.cache_id = m.cache_id '
        'WHERE v.model_space = :space AND v.dimensions = :dimensions), '
        'scored AS (SELECT id, MIN(embedding <=> CAST(:query_vector AS vector)) AS distance FROM eligible GROUP BY id) '
        'SELECT id, distance FROM scored ORDER BY distance, id LIMIT :limit')
    return [(row.id, float(row.distance)) for row in db.execute(statement, {
        'mapping': stable_json(mapping), 'space': config.model_space, 'dimensions': config.dimensions,
        'query_vector': stable_json(valid_vector(query_vector, config.dimensions)), 'limit': CANDIDATE_LIMIT})]


def reciprocal_rank_fusion(fts_ids, dense_ids):
    scores, provenance = {}, {}
    for name, ids in (('fts', fts_ids), ('dense', dense_ids)):
        for rank, key in enumerate(ids, start=1):
            scores[key] = scores.get(key, 0.0) + 1 / (RRF_K + rank)
            provenance.setdefault(key, {})[name + '_rank'] = rank
    return scores, provenance


def hybrid_result(db, config, payload, index, materials, query_vector):
    filters, inferred, terms, _ = interpret(payload)
    lexical = lexical_candidates(db, filters, terms, limit=CANDIDATE_LIMIT)
    dense = cosine_candidates(db, config, materials, query_vector)
    scores, ranks = reciprocal_rank_fusion([doc.id for doc, _ in lexical], [key for key, _ in dense])
    documents = {document.id: document for document in materials[0]}
    distances = dict(dense)
    methods = {key: 'hybrid' if len(ranks[key]) == 2 else 'fts' if 'fts_rank' in ranks[key] else 'dense' for key in scores}
    details = {key: {**ranks[key], 'rrf_score': score, 'cosine_distance': distances.get(key)} for key, score in scores.items()}
    ranked = render_ranked([(documents[key], -score) for key, score in scores.items()], filters, terms,
                           methods=methods, details=details, preferred_region=payload.preferred_region)
    end = payload.offset + payload.limit
    return {'mode': 'history', 'data_state': 'local_snapshot', 'text': payload.text,
        **({'preferred_region': payload.preferred_region} if payload.preferred_region else {}),
        'applied_filters': filters, 'inferred_filters': inferred,
        'items': attach_field_resolutions(db, attach_identity_contracts(db, ranked[payload.offset:end])),
        'total': len(ranked), 'total_scope': 'candidates', 'has_more': len(ranked) > end,
        'offset': payload.offset, 'limit': payload.limit,
        'external_processing': {'query_text_sent': True},
        'index': index, 'coverage': coverage(materials),
        'candidate_counts': {'fts': len(lexical), 'dense': len(dense), 'merged': len(ranked), 'limit': CANDIDATE_LIMIT},
        'stages': [
            {'name': 'structured', 'state': 'succeeded' if filters else 'not_needed', 'reason': 'FTS 与向量使用同一结构化筛选'},
            {'name': 'fts', 'state': 'succeeded', 'reason': 'PostgreSQL 全文召回，每路候选最多 100 条'},
            {'name': 'dense', 'state': 'succeeded', 'reason': '当前正式文档与内容缓存关联后，执行真实 pgvector cosine 精确扫描'},
            {'name': 'hybrid', 'state': 'succeeded', 'reason': 'RRF 融合，k=60；同一文档在两路出现时合并分数'},
            {'name': 'rerank', 'state': 'succeeded', 'reason': '按字段权威、RRF 分数与原文观察时间排序；核验时间不冒充新事实，未调用语义重排模型'},
        ],
        'notice': '历史向量检索；仅查询文本发送到 OpenAI。候选数量不是全库匹配总数；未建完整向量的文档仅可能由 FTS 返回。'
                  '向量相似度不等于事实正确或 SKU 可互换。'}
