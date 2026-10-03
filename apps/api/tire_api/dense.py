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
    documents = list(db.scalars(_filtered_statement(filters or {})))
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
    ids = list(cached)
    existing = set(db.execute(text('SELECT cache_id FROM embedding_vectors WHERE cache_id = ANY(:ids)'), {'ids': ids}).scalars())
    for key, row in cached.items():
        if key not in existing:
            vector = valid_vector(row.vector, row.dimensions)
            db.execute(text('INSERT INTO embedding_vectors (cache_id, model_space, dimensions, embedding) '
                'VALUES (:id, :space, :dimensions, CAST(:embedding AS vector)) ON CONFLICT (cache_id) DO NOTHING'),
                {'id': key, 'space': row.model_space, 'dimensions': row.dimensions, 'embedding': stable_json(vector)})


def ensure_hnsw(db, config):
    # Only validated dimensions and a digest enter DDL; no names or query text.
    dimensions = config.dimensions
    space = config.model_space
    if type(dimensions) is not int or not 1 <= dimensions <= 2000 or len(space) != 64 or any(c not in '0123456789abcdef' for c in space):
        raise ValueError('invalid vector space')
    db.execute(text('SELECT pg_advisory_xact_lock(821741906)'))
    db.execute(text(f'CREATE INDEX IF NOT EXISTS ix_embedding_hnsw_{space[:24]} ON embedding_vectors '
                    f'USING hnsw ((embedding::vector({dimensions})) vector_cosine_ops) '
                    f"WHERE model_space = '{space}' AND dimensions = {dimensions}"))


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
                           methods=methods, details=details)
    return {'mode': 'history', 'data_state': 'local_snapshot', 'text': payload.text,
        'applied_filters': filters, 'inferred_filters': inferred,
        'items': attach_field_resolutions(db, attach_identity_contracts(db, ranked[:payload.limit])),
        'total': len(ranked), 'total_scope': 'candidates', 'has_more': len(ranked) > payload.limit,
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
