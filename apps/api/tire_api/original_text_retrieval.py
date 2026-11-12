"""Current original-bound text retrieval through the shared embedding ledger."""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import Float, String, func, select, text

from .db import Snapshot, utc
from .dense import CANDIDATE_LIMIT, reciprocal_rank_fusion
from .document_text import checked_projection, reference_for
from .document_text_models import DocumentTextChunk, DocumentTextIndex
from .domain import digest, stable_json
from .embedding_gateway import valid_vector
from .field_evidence import latest_tire_heads, source_catalog
from .knowledge import region_preference
from .knowledge_index import normalized, tokens
from .service import timestamp
from .source_text import (CHUNK_CHARACTERS, CHUNK_OVERLAP, SUPPORTED_TYPES,
    SourceTextCitation, checked_snapshot, citation, index_snapshot)
from .source_text_models import SourceTextChunk, SourceTextIndex
from .source_material_models import SourceMaterialOutcome, SourceMaterialRequest
from .text_embedding_models import TextEmbeddingAuthorization
from .text_embeddings import (PURPOSE, DocumentSelection, SourceSelection, authorization_view,
    checked_authorization, checked_caches, chunk_for_excerpt, fail, original_excerpt, recipient, scope_for)

SOURCE_TIERS = {'regulatory': 1, 'manufacturer_official': 1, 'oem_fitment': 1,
    'original_test_organization': 1, 'professional_media': 2, 'commissioned_lab_report': 2,
    'high_quality_distributor': 3, 'authorized_retailer': 3, 'official_store': 3}


def _html_entries(db, catalog, filters, rebuild):
    heads = latest_tire_heads(db, source_ids=[filters['source_id']] if filters.get('source_id') else None)
    indexed = set(db.scalars(select(SourceTextIndex.snapshot_id)))
    indexed.update(db.scalars(select(TextEmbeddingAuthorization.payload['selection']['reference']['snapshot_id'].as_string())))
    identities = {head['snapshot_id'] for head in heads} & indexed
    snapshots = db.scalars(select(Snapshot).where(Snapshot.id.in_(identities),
                                                Snapshot.content_type.in_(SUPPORTED_TYPES))).all()
    result = {}
    for snapshot in snapshots:
        source = catalog.get(snapshot.source_id, {})
        region = source.get('region')
        if filters.get('region') and (not region or normalized(region) != normalized(filters['region'])):
            continue
        if rebuild:
            index_snapshot(db, snapshot.id)
        _snapshot, original, _verified = checked_snapshot(db, snapshot.id)
        for chunk in db.scalars(select(SourceTextChunk).where(SourceTextChunk.snapshot_id == snapshot.id)):
            reference = SourceTextCitation.model_validate(citation(snapshot, chunk.start, chunk.end))
            if (reference.chunk_id != chunk.id or chunk.raw_hash != snapshot.raw_hash
                    or chunk.extractor_version != reference.extractor_version
                    or not 0 <= chunk.start < len(original)
                    or chunk.start % (CHUNK_CHARACTERS - CHUNK_OVERLAP)
                    or chunk.end != min(chunk.start + CHUNK_CHARACTERS, len(original))
                    or chunk.text != original[chunk.start:chunk.end]
                    or chunk.tokens != ' '.join(tokens(chunk.text))):
                fail('text_embedding_binding_failed')
            result[chunk.id] = {'selection': SourceSelection(kind='source_text', reference=reference),
                'text': chunk.text, 'source_class': source.get('source_class', 'unclassified'),
                'region': region, 'time_sort': utc(snapshot.observed_at).timestamp(),
                'freshness': {'time_basis': 'observed_at', 'observed_at': timestamp(snapshot.observed_at)}}
    return result


def _pdf_entries(db):
    from .source_materials import checked_request

    result = {}
    for identity in db.scalars(select(DocumentTextIndex.document_id)):
        _metadata, index, pages = checked_projection(db, identity)
        freshness = {'time_basis': 'publication_unknown', 'observed_at': None}
        time_sort = float('-inf')
        request_id = db.scalar(select(SourceMaterialOutcome.request_id).where(SourceMaterialOutcome.document_id == identity))
        if request_id is not None:
            acquisition = db.get(SourceMaterialRequest, request_id)
            checked_request(acquisition)
            published_at = acquisition.policy['published_at']
            if published_at is not None:
                freshness = {'time_basis': 'policy_publication_date', 'observed_at': None,
                    'publication': {'published_at': published_at, 'material_request_id': request_id,
                                    'policy_fingerprint': acquisition.policy['policy_fingerprint']}}
                time_sort = datetime.fromisoformat(published_at).replace(tzinfo=timezone.utc).timestamp()
        for chunk in db.scalars(select(DocumentTextChunk).where(DocumentTextChunk.document_id == identity)):
            value = reference_for(identity, index.document_fingerprint, index.raw_hash,
                                  chunk.page, chunk.start, chunk.end)
            selection = DocumentSelection.model_validate({'kind': 'document_text', 'reference': value})
            if (chunk.id != selection.reference.chunk_id or not 1 <= chunk.page <= len(pages)
                    or not 0 <= chunk.start < len(pages[chunk.page - 1].text)
                    or chunk.start % (CHUNK_CHARACTERS - CHUNK_OVERLAP)
                    or chunk.end != min(chunk.start + CHUNK_CHARACTERS, len(pages[chunk.page - 1].text))
                    or chunk.text != pages[chunk.page - 1].text[chunk.start:chunk.end]
                    or chunk.tokens != ' '.join(tokens(chunk.text))):
                fail('text_embedding_binding_failed')
            result[chunk.id] = {'selection': selection, 'text': chunk.text,
                'source_class': 'unclassified', 'region': None,
                'time_sort': time_sort, 'freshness': freshness}
    return result


def _authorized_chunks(db, config, entries):
    scopes = {scope_for(value['selection'], config): identity for identity, value in entries.items()}
    latest = select(TextEmbeddingAuthorization.scope_hash,
        func.max(TextEmbeddingAuthorization.revision).label('revision')).where(
            TextEmbeddingAuthorization.scope_hash.in_(scopes)).group_by(TextEmbeddingAuthorization.scope_hash).subquery()
    rows = db.scalars(select(TextEmbeddingAuthorization).join(latest,
        (latest.c.scope_hash == TextEmbeddingAuthorization.scope_hash)
        & (latest.c.revision == TextEmbeddingAuthorization.revision)))
    chunks = {}
    for row in rows:
        checked_authorization(row)
        if authorization_view(row)['state'] != 'granted':
            continue
        entry = entries[scopes[row.scope_hash]]
        payload = row.payload
        if (payload['purpose'] != PURPOSE or payload['selection'] != entry['selection'].model_dump()
                or payload['recipient'] != recipient(config) or payload['text_hash'] != digest(entry['text'])):
            fail('text_embedding_authorization_invalid')
        privacy = payload['request']['privacy_class']
        if privacy not in {'public', 'private'}:
            fail('text_embedding_authorization_invalid')
        if privacy == 'private' and not config.allow_private:
            continue
        chunks[scopes[row.scope_hash]] = chunk_for_excerpt(entry['text'], privacy, config)
    return chunks


def current_originals(db, config, registry=None, filters=None, *, rebuild=False):
    filters = filters or {}
    result = {'entries': {}, 'cached': {}, 'cache_ids': {}}
    if set(filters) - {'kind', 'source_id', 'region'} or filters.get('kind') not in (None, 'tire'):
        return result
    try:
        entries = _html_entries(db, source_catalog(registry), filters, rebuild)
        if not filters:
            entries.update(_pdf_entries(db))
        chunks = _authorized_chunks(db, config, entries)
        cached = checked_caches(db, config, {chunk['cache_id']: chunk for chunk in chunks.values()})
        return {'entries': entries, 'cached': cached,
                'cache_ids': {key: chunk['cache_id'] for key, chunk in chunks.items() if chunk['cache_id'] in cached}}
    except HTTPException as error:
        code = error.detail.get('code') if isinstance(error.detail, dict) else None
        if code and code.startswith('text_embedding_'):
            raise
        fail('text_embedding_original_invalid')
    except (KeyError, TypeError, ValueError, AttributeError):
        fail('text_embedding_binding_failed')


def coverage(materials):
    eligible, indexed = len(materials['entries']), len(materials['cache_ids'])
    return {'eligible_chunks': eligible, 'indexed_chunks': indexed, 'missing_chunks': eligible - indexed}


def lexical_candidates(db, materials, terms):
    if not terms:
        return []
    candidates = []
    for kind, model, table in (('source_text', SourceTextChunk, 'source_text_fts'),
                               ('document_text', DocumentTextChunk, 'document_text_fts')):
        identities = [key for key, entry in materials['entries'].items() if entry['selection'].kind == kind]
        if not identities:
            continue
        if db.get_bind().dialect.name == 'sqlite':
            fulltext = text(f'SELECT chunk_id AS id, bm25({table}) AS score FROM {table} '
                f'WHERE {table} MATCH :terms').columns(id=String, score=Float).subquery()
            query = ' AND '.join('"' + term.replace('"', '""') + '"' for term in terms)
        else:
            fulltext = text(f"SELECT id, -ts_rank_cd(search_vector, plainto_tsquery('simple', :terms)) AS score "
                f"FROM {model.__tablename__} WHERE search_vector @@ plainto_tsquery('simple', :terms)")\
                .columns(id=String, score=Float).subquery()
            query = ' '.join(terms)
        statement = select(model.id, fulltext.c.score).join(fulltext, fulltext.c.id == model.id).where(
            model.id.in_(identities)).order_by(fulltext.c.score, model.id).limit(CANDIDATE_LIMIT)
        for rank, row in enumerate(db.execute(statement, {'terms': query}), 1):
            if not set(terms).issubset(tokens(materials['entries'][row.id]['text'])):
                fail('text_embedding_binding_failed')
            candidates.append((rank, row.id))
    # Each original index contributes by rank so its local FTS score scale is explicit.
    candidates.sort()
    return [identity for _rank, identity in candidates[:CANDIDATE_LIMIT]]


def cosine_candidates(db, config, materials, query_vector):
    mapping = [{'chunk_id': key, 'cache_id': value, 'kind': materials['entries'][key]['selection'].kind}
               for key, value in materials['cache_ids'].items()]
    if not mapping:
        return []
    statement = text('WITH eligible AS MATERIALIZED ('
        'SELECT m.chunk_id, v.embedding FROM jsonb_to_recordset(CAST(:mapping AS jsonb)) '
        'AS m(chunk_id text, cache_id text, kind text) '
        'JOIN embedding_vectors v ON v.cache_id = m.cache_id '
        'LEFT JOIN source_text_chunks s ON m.kind = \'source_text\' AND s.id = m.chunk_id '
        'LEFT JOIN document_text_chunks d ON m.kind = \'document_text\' AND d.id = m.chunk_id '
        'WHERE v.model_space = :space AND v.dimensions = :dimensions '
        'AND (s.id IS NOT NULL OR d.id IS NOT NULL)) '
        'SELECT chunk_id, embedding <=> CAST(:vector AS vector) AS distance FROM eligible '
        'ORDER BY distance, chunk_id LIMIT :limit')
    return [(row.chunk_id, float(row.distance)) for row in db.execute(statement, {
        'mapping': stable_json(mapping), 'space': config.model_space, 'dimensions': config.dimensions,
        'vector': stable_json(valid_vector(query_vector, config.dimensions)), 'limit': CANDIDATE_LIMIT})]


def hybrid_result(db, config, search, materials, query_vector):
    from .knowledge import interpret
    terms = interpret(search)[2]
    lexical = lexical_candidates(db, materials, terms)
    dense = cosine_candidates(db, config, materials, query_vector)
    scores, ranks = reciprocal_rank_fusion(lexical, [identity for identity, _distance in dense])
    distances = dict(dense)
    ordered = []
    for identity, score in scores.items():
        entry = materials['entries'][identity]
        tier = SOURCE_TIERS.get(entry['source_class'])
        region, region_rank = region_preference(entry['region'], search.preferred_region)
        ordered.append((tier or 999, region_rank, -score, entry['time_sort'], identity, region))
    ordered.sort(key=lambda value: value[4])
    ordered.sort(key=lambda value: value[3], reverse=True)
    ordered.sort(key=lambda value: value[:3])
    items, pdfs = [], {}
    end = search.offset + search.limit
    for tier, _region_rank, negative_score, _observed, identity, region in ordered[search.offset:end]:
        entry = materials['entries'][identity]
        excerpt = original_excerpt(db, entry['selection'], pdfs)
        if excerpt['text'] != entry['text']:
            fail('text_embedding_binding_failed')
        match = ranks[identity]
        method = 'hybrid' if len(match) == 2 else 'fts' if 'fts_rank' in match else 'dense'
        items.append({**excerpt, 'match': {'method': method,
            'matched_terms': terms if 'fts_rank' in match else [], 'score': -negative_score,
            **match, 'rrf_score': -negative_score, 'cosine_distance': distances.get(identity),
            'authority_tier': None if tier == 999 else tier, 'source_class': entry['source_class'],
            'region': entry['region'], 'region_match': region, 'variant_match': 'page_scope',
            'freshness': entry['freshness'],
            'explanation': ['来源目录类别用于正文来源排序，具体字段和SKU身份由结构化证据核对。',
                '地区偏好按已登记来源地区排序。',
                'RRF融合分数及可追溯的时间依据参与排序，材料策略日期为配置声明。']}})
    return {'items': items, 'total': len(ordered), 'has_more': len(ordered) > end,
        'offset': search.offset, 'limit': search.limit,
        'coverage': coverage(materials), 'preferred_region': search.preferred_region,
        'candidate_counts': {'fts': len(lexical), 'dense': len(dense), 'merged': len(ordered), 'limit': CANDIDATE_LIMIT},
        'text_contract': 'original-text-semantic@1',
        'notice': '原件正文历史候选，按来源类别、地区偏好、RRF及已注明依据的时间排序。'
                  '原件引用保留页面或文档页码范围，具体SKU适用性需要对应结构化证据。'}
