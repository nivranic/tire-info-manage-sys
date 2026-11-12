"""Production hybrid routes with original bindings and fixed vector SQL fixtures."""
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, text

from admin_support import register_admin
from tire_api import dense, embedding_api, original_text_retrieval
from tire_api.db import Snapshot, utcnow
from tire_api.domain import digest
from tire_api.embedding_models import EmbeddingRequest
from tire_api.knowledge import KnowledgeSearch
from test_document_text import indexed_document, search as pdf_search
from test_text_embeddings import authorize, build, plan, selection, setup


CATALOG = [
    {'id': 'fixture', 'region': 'US', 'source_class': 'manufacturer_official'},
    {'id': 'fixture-cn', 'region': 'CN', 'source_class': 'manufacturer_official'},
    {'id': 'fixture-media', 'region': 'US', 'source_class': 'professional_media'},
]


def fixed_cosine(_db, _config, materials, vector):
    result = [(key, 1 - sum(a * b for a, b in zip(materials['cached'][cache_id].vector, vector, strict=True)))
              for key, cache_id in materials['cache_ids'].items()]
    return sorted(result, key=lambda row: (row[1], row[0]))[:100]


@pytest.fixture
def retrieval(setup, monkeypatch):
    client, database, provider = setup
    register_admin(client)
    monkeypatch.setattr(client.app.state.registry, 'sources', lambda: CATALOG)
    monkeypatch.setattr(dense, 'cosine_candidates', lambda *_: [])
    monkeypatch.setattr(original_text_retrieval, 'cosine_candidates', fixed_cosine)
    monkeypatch.setattr(embedding_api, 'mirror_cache', lambda *_: None)
    yield client, database, provider


def html(retrieval, *, body='acoustic quiettopic original 🛞', source='fixture', query=None, at=None, index=True):
    client, database, _provider = retrieval
    selected = selection(client, database, '<p>' + body + '</p>', source=source, query=query or str(uuid4()), at=at)
    if index:
        index_selection(client, selected)
    return selected


def index_selection(client, selected, **permission):
    response = authorize(client, selected, **permission)
    assert response.status_code == 200, response.text
    prepared = plan(client, selected)
    assert prepared.status_code == 200, prepared.text
    response = build(client, prepared.json()['id'])
    assert response.status_code == 200 and response.json()['state'] == 'completed', response.text


def ask(client, question='quiettopic', *, filters=None, preferred_region=None, key=None, consent=True,
        offset=0, limit=12):
    search = {'mode': 'history', 'text': question, 'filters': filters or {}, 'offset': offset, 'limit': limit}
    if preferred_region is not None:
        search['preferred_region'] = preferred_region
    return client.post('/v1/knowledge/hybrid-search', headers={'Idempotency-Key': key or str(uuid4())},
        json={'search': search, 'allow_external_processing': consent})


def completed(response):
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['state'] == 'completed', value
    return value['result']['original_text']


def test_body_only_hybrid_uses_original_contract_one_query_call_and_frozen_history(retrieval):
    client, database, provider = retrieval
    selected = html(retrieval)
    key = str(uuid4())
    response = ask(client, key=key)
    result = completed(response)
    item, = result['items']
    assert item['reference'] == selected['reference'] and item['match']['method'] == 'hybrid'
    assert item['text'].endswith('🛞') and item['match']['fts_rank'] == item['match']['dense_rank'] == 1
    assert result['text_contract'] == 'original-text-semantic@1'
    assert result['coverage'] == {'eligible_chunks': 1, 'indexed_chunks': 1, 'missing_chunks': 0}
    assert provider.calls[-1][2] == ['quiettopic'] and len(provider.calls) == 2
    assert ask(client, key=key).json() == response.json() and len(provider.calls) == 2
    assert ask(client, question='other question', key=key).status_code == 409
    run_id = response.json()['id']
    assert client.get(f'/v1/knowledge/embedding-runs/{run_id}?mode=history').json() == response.json()
    with database.sessions() as db:
        assert db.scalar(select(func.count()).select_from(EmbeddingRequest)) == 2


def test_semantic_only_candidate_and_unindexed_lexical_candidate_keep_distinct_methods(retrieval):
    indexed = html(retrieval, body='acoustic semantic material')
    local = html(retrieval, body='acoustic quiettopic local only', index=False)
    result = completed(ask(retrieval[0]))
    by_id = {item['reference']['chunk_id']: item for item in result['items']}
    assert by_id[indexed['reference']['chunk_id']]['match']['method'] == 'dense'
    assert by_id[indexed['reference']['chunk_id']]['match']['matched_terms'] == []
    assert by_id[local['reference']['chunk_id']]['match']['method'] == 'fts'
    assert result['coverage'] == {'eligible_chunks': 2, 'indexed_chunks': 1, 'missing_chunks': 1}


@pytest.mark.parametrize('filters', [
    {'brand': 'Fixture'}, {'model': 'Fixture'}, {'size': '245/40R20'}, {'product_code': 'X'},
    {'variant_id': 'X'}, {'technology': 'Acoustic'}, {'field': 'utqg_treadwear'},
    {'kind': 'vehicle'}, {'kind': 'test_event'}, {'kind': 'recall'}, {'campaign_number': '24T000001'},
])
def test_entity_filters_do_not_admit_unassociated_page_text(retrieval, filters):
    client, _database, provider = retrieval
    html(retrieval)
    before = len(provider.calls)
    response = ask(client, filters=filters)
    assert response.status_code == 409, response.text
    assert len(provider.calls) == before


def test_source_and_region_hard_filters_apply_to_dense_and_fts_before_candidates(retrieval):
    client, _database, provider = retrieval
    us = html(retrieval)
    cn = html(retrieval, source='fixture-cn')
    for filters, expected in [({'source_id': 'fixture'}, us), ({'region': 'CN'}, cn), ({'kind': 'tire', 'region': 'US'}, us)]:
        result = completed(ask(client, filters=filters))
        assert [item['reference'] for item in result['items']] == [expected['reference']]
        assert result['candidate_counts']['fts'] == result['candidate_counts']['dense'] == 1
    before = len(provider.calls)
    assert ask(client, filters={'source_id': 'fixture', 'region': 'CN'}).status_code == 409
    assert len(provider.calls) == before


def test_source_category_and_region_preference_are_explicit_ranking_dimensions(retrieval):
    client, _database, _provider = retrieval
    html(retrieval, source='fixture-media')
    us = html(retrieval)
    cn = html(retrieval, source='fixture-cn')
    result = completed(ask(client, preferred_region='CN'))
    assert [item['reference'] for item in result['items'][:2]] == [cn['reference'], us['reference']]
    assert [item['match']['authority_tier'] for item in result['items']] == [1, 1, 2]
    assert [item['match']['region_match'] for item in result['items']] == ['exact', 'different', 'different']
    assert all(item['match']['variant_match'] == 'page_scope' for item in result['items'])


@pytest.mark.parametrize('collection', ['structured', 'original_text'])
def test_hybrid_pages_slice_global_rankings_and_freeze_each_receipt(retrieval, collection):
    from test_core import VARIANT
    from test_knowledge import seed as seed_structured

    client, database, provider = retrieval
    html(retrieval, source='fixture-media')
    html(retrieval, source='fixture')
    html(retrieval, source='fixture-cn')
    document, _ = indexed_document(client, pages=('acoustic quiettopic PDF page',))
    pdf = pdf_search(client, 'quiettopic', document_id=document['id']).json()['items'][0]
    index_selection(client, {'kind': 'document_text', 'reference': pdf['reference']})
    rows = [{**VARIANT, 'id': str(uuid4()), 'manufacturer_product_code': f'PAGE-{index}',
             'facts': {'description': 'quiettopic page candidate'}} for index in range(3)]
    seed_structured(database, rows, query='hybrid-pages')
    complete_response = ask(client, preferred_region='CN', limit=30)
    assert complete_response.status_code == 200, complete_response.text
    full = complete_response.json()['result']
    expected = full if collection == 'structured' else full['original_text']
    total = 3 if collection == 'structured' else 4
    assert expected['total'] == total

    pages = {}
    for offset in (2, 0, total, 2000):
        key = str(uuid4())
        response = ask(client, preferred_region='CN', offset=offset, limit=2, key=key)
        assert response.status_code == 200, response.text
        value = response.json()
        result = value['result'] if collection == 'structured' else value['result']['original_text']
        assert result['items'] == expected['items'][offset:offset + 2]
        assert result['offset'] == offset and result['limit'] == 2
        assert result['total'] == total and result['has_more'] is (offset + 2 < total)
        before = len(provider.calls)
        assert ask(client, preferred_region='CN', offset=offset, limit=2, key=key).json() == value
        assert len(provider.calls) == before
        assert ask(client, preferred_region='CN', offset=offset, limit=1, key=key).status_code == 409
        assert client.get(f"/v1/knowledge/embedding-runs/{value['id']}?mode=history").json() == value
        pages[offset] = result['items']
    assert pages[0] + pages[2] + pages[total] + pages[2000] == expected['items']


def test_equal_fusion_scores_use_observation_time(retrieval, monkeypatch):
    client, _database, _provider = retrieval
    old = html(retrieval, at=utcnow() - timedelta(days=5))
    new = html(retrieval, at=utcnow() - timedelta(days=1))
    ids = [old['reference']['chunk_id'], new['reference']['chunk_id']]
    monkeypatch.setattr(original_text_retrieval, 'lexical_candidates', lambda *_: ids)
    monkeypatch.setattr(original_text_retrieval, 'cosine_candidates', lambda *_: [(ids[1], 0.0), (ids[0], 0.0)])
    result = completed(ask(client))
    assert result['items'][0]['reference'] == new['reference']
    assert result['items'][0]['match']['rrf_score'] == result['items'][1]['match']['rrf_score']
    assert result['items'][0]['match']['freshness']['time_basis'] == 'observed_at'


def test_no_consent_current_language_or_missing_vectors_causes_no_query_dispatch(retrieval):
    client, _database, provider = retrieval
    html(retrieval, index=False)
    assert ask(client).status_code == 409 and not provider.calls
    assert ask(client, question='最新 quiettopic').status_code == 409
    assert ask(client, consent=False).status_code == 422 and not provider.calls


@pytest.mark.parametrize('change', ['revoke', 'expire', 'private', 'endpoint', 'latest_head'])
def test_ineligible_vector_cache_is_excluded_before_query_dispatch(retrieval, monkeypatch, change):
    client, database, provider = retrieval
    selected = html(retrieval, query='head-scope')
    if change == 'revoke':
        assert authorize(client, selected, expected_revision=1, action='revoke').status_code == 200
    elif change == 'expire':
        assert authorize(client, selected, expected_revision=1,
            expires_at=(utcnow() + timedelta(minutes=1)).isoformat()).status_code == 200
        from tire_api import text_embeddings
        now = utcnow()
        monkeypatch.setattr(text_embeddings, 'utcnow', lambda: now + timedelta(minutes=2))
    elif change == 'private':
        assert authorize(client, selected, expected_revision=1, privacy_class='private').status_code == 200
    elif change == 'endpoint':
        monkeypatch.setenv('TI_EMBEDDINGS_BASE_URL', 'https://fixture.invalid/other/v1')
    else:
        html(retrieval, body='acoustic new head', query='head-scope', index=False)
    before = len(provider.calls)
    assert ask(client).status_code == 409
    assert len(provider.calls) == before


@pytest.mark.parametrize('change', ['original', 'cache'])
def test_corrupt_original_or_cache_refuses_before_query_dispatch(retrieval, change):
    client, database, provider = retrieval
    selected = html(retrieval)
    with database.sessions() as db:
        if change == 'original':
            db.execute(text('UPDATE snapshots SET body = :body WHERE id = :id'),
                {'body': 'corrupted original', 'id': selected['reference']['snapshot_id']})
        else:
            db.execute(text("UPDATE embedding_cache SET vector = '[0,0,0]'"))
        db.commit()
    before = len(provider.calls)
    response = ask(client)
    assert response.status_code == 409 and response.json()['detail']['code'].startswith('text_embedding_')
    assert len(provider.calls) == before


def test_final_dispatch_checks_revocation_and_records_zero_actual_usage(retrieval, monkeypatch):
    client, _database, provider = retrieval
    selected = html(retrieval)
    check = embedding_api.check_embedding_dispatch
    def revoke(*args, **kwargs):
        assert authorize(client, selected, expected_revision=1, action='revoke').status_code == 200
        return check(*args, **kwargs)
    monkeypatch.setattr(embedding_api, 'check_embedding_dispatch', revoke)
    value = ask(client).json()
    assert value['state'] == 'failed' and value['error_code'] == 'text_embedding_use_not_allowed'
    assert value['usage']['total_tokens'] == 0 and len(provider.calls) == 1


def test_revocation_during_query_keeps_actual_usage_and_refuses_stale_result(retrieval):
    client, _database, provider = retrieval
    selected = html(retrieval)
    embed = provider.embed
    async def revoke(config, inputs):
        receipt = await embed(config, inputs)
        assert authorize(client, selected, expected_revision=1, action='revoke').status_code == 200
        return receipt
    provider.embed = revoke
    value = ask(client).json()
    assert value['state'] == 'failed' and value['error_code'] == 'embeddings_result_stale'
    assert value['usage']['total_tokens'] == 10 and value['result'] is None and len(provider.calls) == 2


def test_pdf_dense_result_recovers_original_page_and_preserves_unknown_publication(retrieval):
    client, _database, provider = retrieval
    document, _ = indexed_document(client, pages=('acoustic first original 🛞', 'acoustic second original'))
    rows = pdf_search(client, 'acoustic', document_id=document['id']).json()['items']
    for item in rows:
        index_selection(client, {'kind': 'document_text', 'reference': item['reference']})
    result = completed(ask(client, question='semantic question', preferred_region='CN'))
    assert len(result['items']) == 2 and len(provider.calls) == 3
    assert {item['reference']['page'] for item in result['items']} == {1, 2}
    assert all(item['match']['method'] == 'dense' and item['match']['region_match'] == 'unknown'
        and item['match']['authority_tier'] is None and item['match']['freshness'] == {
            'time_basis': 'publication_unknown', 'observed_at': None} for item in result['items'])


def test_legacy_search_serialization_preserves_request_fingerprints():
    previous = {'mode': 'history', 'text': 'legacy question', 'filters': {
        'kind': None, 'campaign_number': None, 'brand': None, 'model': None, 'size': None, 'region': None,
        'product_code': None, 'source_id': None, 'variant_id': None, 'technology': None, 'field': None},
        'limit': 12, 'offset': 0}
    value = KnowledgeSearch.model_validate(previous)
    assert value.model_dump() == previous
    assert digest(value.model_dump()) == digest(previous)
    assert KnowledgeSearch.model_validate({**previous, 'preferred_region': None}).model_dump() == previous
    assert value.model_copy(update={'preferred_region': 'CN'}).model_dump()['preferred_region'] == 'CN'


def test_private_vector_can_be_retrieved_when_current_processing_policy_allows_it(retrieval, monkeypatch):
    client, database, provider = retrieval
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '1')
    selected = selection(client, database)
    index_selection(client, selected, privacy_class='private')
    result = completed(ask(client, question='semantic question'))
    assert result['items'][0]['reference'] == selected['reference'] and len(provider.calls) == 2
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '0')
    assert ask(client, question='semantic question').status_code == 409 and len(provider.calls) == 2


def test_lost_html_projection_is_rebuilt_from_current_authorized_original(retrieval):
    from sqlalchemy import delete
    from tire_api.source_text_models import SourceTextChunk, SourceTextIndex
    client, database, _provider = retrieval
    selected = html(retrieval)
    with database.sessions() as db:
        db.execute(text('DELETE FROM source_text_fts'))
        db.execute(delete(SourceTextChunk))
        db.execute(delete(SourceTextIndex))
        db.commit()
    result = completed(ask(client))
    assert result['items'][0]['reference'] == selected['reference']


@pytest.mark.parametrize('value', [' ', 'C\nN', 'X' * 41])
def test_region_preference_is_validated_before_dispatch(retrieval, value):
    assert ask(retrieval[0], preferred_region=value).status_code == 422
    assert not retrieval[2].calls


def verify_original_text_hybrid(url, *, authenticate):
    """Called by the isolated verifier with actual PostgreSQL FTS and cosine."""
    from tire_api.main import create_app
    from tire_api.embedding_gateway import configured_embeddings
    from test_core import FixtureRegistry
    from test_embeddings import SyntheticEmbeddings, settings
    with pytest.MonkeyPatch.context() as monkeypatch:
        settings(monkeypatch)
        registry = FixtureRegistry()
        registry.sources = lambda: CATALOG
        app = create_app(url, registry)
        provider = SyntheticEmbeddings()
        app.state.embedding_adapter = provider
        with TestClient(app) as client:
            authenticate(client)
            fixture = client, app.state.database, provider
            us = html(fixture, body='acoustic quiettopic US original')
            cn = html(fixture, body='acoustic quiettopic CN original', source='fixture-cn')
            with app.state.database.sessions() as db:
                materials = original_text_retrieval.current_originals(db, configured_embeddings(), registry, {'source_id': 'fixture-cn'})
                cache_id = materials['cache_ids'][cn['reference']['chunk_id']]
                db.execute(text('UPDATE embedding_vectors SET embedding = CAST(:vector AS vector) WHERE cache_id = :id'),
                    {'vector': '[0,1,0]', 'id': cache_id})
                distance = db.execute(text('SELECT embedding <=> CAST(:vector AS vector) FROM embedding_vectors WHERE cache_id = :id'),
                    {'vector': '[1,0,0]', 'id': cache_id}).scalar_one()
                assert float(distance) == 1.0
                db.commit()
            response = ask(client, filters={'source_id': 'fixture-cn'}, preferred_region='CN')
            result = completed(response)
            assert result['items'][0]['reference'] == cn['reference']
            assert result['items'][0]['match']['method'] == 'hybrid'
            assert result['items'][0]['match']['cosine_distance'] == 0
            ranked = completed(ask(client, preferred_region='CN', limit=30))
            assert ranked['items'][0]['reference'] == cn['reference']
            assert len(provider.calls) == 4 and all(call[2] == ['quiettopic'] for call in provider.calls[-2:])
            with app.state.database.sessions() as db:
                materials = original_text_retrieval.current_originals(db, configured_embeddings(), registry, {'source_id': 'fixture'})
                scores = original_text_retrieval.cosine_candidates(db, configured_embeddings(), materials, [1, 0, 0])
                assert (us['reference']['chunk_id'], 0.0) in scores
                assert cn['reference']['chunk_id'] not in dict(scores)
            page_response = ask(client, preferred_region='CN', offset=1, limit=1)
            page = completed(page_response)
            assert page['items'] == ranked['items'][1:2]
            assert page['offset'] == page['limit'] == 1
            assert page['total'] == ranked['total'] and page['has_more'] is (ranked['total'] > 2)
            empty_response = ask(client, preferred_region='CN', offset=2000, limit=1)
            empty = completed(empty_response)
            assert not empty['items'] and not empty['has_more'] and empty['total'] == ranked['total']
            checkpoint = {'run_id': response.json()['id'], 'originals': result, 'us': us, 'cn': cn,
                          'pages': [page_response.json(), empty_response.json()]}
        app.state.database.close()
    return {'checks': ['original_bound_postgresql_fts_and_cosine', 'derived_mirror_recovery_from_content_cache', 'hard_source_scope_before_vector_limit',
        'region_preference_with_real_fusion', 'only_query_text_dispatched',
        'global_original_fusion_ranking_paginated_with_empty_page'], 'checkpoint': checkpoint}


def assert_original_text_hybrid_checkpoint(url, checkpoint, *, authenticate):
    from tire_api.main import create_app
    from tire_api.embedding_gateway import configured_embeddings
    from test_core import FixtureRegistry
    from test_embeddings import SyntheticEmbeddings, settings
    with pytest.MonkeyPatch.context() as monkeypatch:
        settings(monkeypatch)
        registry = FixtureRegistry()
        registry.sources = lambda: CATALOG
        app = create_app(url, registry)
        provider = SyntheticEmbeddings()
        app.state.embedding_adapter = provider
        with TestClient(app) as client:
            authenticate(client)
            response = client.get(f"/v1/knowledge/embedding-runs/{checkpoint['run_id']}?mode=history")
            assert response.status_code == 200 and response.json()['result']['original_text'] == checkpoint['originals']
            for saved in checkpoint.get('pages', []):
                response = client.get(f"/v1/knowledge/embedding-runs/{saved['id']}?mode=history")
                assert response.status_code == 200 and response.json() == saved
            with app.state.database.sessions() as db:
                config = configured_embeddings()
                materials = original_text_retrieval.current_originals(db, config, registry, {'source_id': 'fixture-cn'})
                result = original_text_retrieval.hybrid_result(db, config,
                    KnowledgeSearch(mode='history', text='quiettopic', filters={'source_id': 'fixture-cn'}, preferred_region='CN'),
                    materials, [1, 0, 0])
                assert result['items'][0]['reference'] == checkpoint['cn']['reference']
                assert result['items'][0]['match']['cosine_distance'] == 0
            assert not provider.calls
        app.state.database.close()
