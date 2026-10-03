"""Native embedding protocol tests and synthetic-provider REAL-pgvector acceptance.

Fixture vectors are fixed test data, never fallback production embeddings. They
prove persistence/filtering/cosine/RRF mechanics, not live semantic quality.
"""
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
from types import SimpleNamespace
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, text

from tire_api.db import VariantLifecycleEvent, utcnow
from tire_api.domain import digest
from tire_api.dense import reciprocal_rank_fusion
from tire_api.embedding_gateway import (EmbeddingConfig, EmbeddingError, OpenAIEmbeddingAdapter,
    configured_embeddings, extract_embeddings, valid_vector, valid_usage)
from tire_api.embedding_models import EmbeddingCache, EmbeddingCompletion, EmbeddingPlan, EmbeddingRequest
from tire_api.embedding_service import reserve_request
from tire_api.embedding_text import bounded_batch, chunk_text, document_chunks
from tire_api.main import create_app
from test_core import VARIANT, FixtureRegistry, live, success
from test_knowledge import Sources, search, seed


class SyntheticEmbeddings:
    """Explicit, fixed orthogonal fixtures; no semantic-model claim."""
    def __init__(self):
        self.calls = []
        self.error = None
        self.invalid = False

    async def embed(self, config, inputs):
        self.calls.append((config.model, config.dimensions, list(inputs)))
        if self.error:
            raise self.error
        if self.invalid:
            return {'vectors': [[0] * config.dimensions for _ in inputs], 'usage': None}
        vectors = []
        for value in inputs:
            vector = [0.0] * config.dimensions
            vector[1 if 'fixturebeta' in value and config.dimensions > 1 else 0] = 1.0
            vectors.append(vector)
        return {'vectors': vectors, 'usage': {'input_tokens': 10 * len(inputs), 'output_tokens': 0, 'total_tokens': 10 * len(inputs)}}


def settings(monkeypatch):
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '1')
    monkeypatch.setenv('TI_OPENAI_EMBEDDING_MODEL', 'synthetic-embedding-fixture')
    monkeypatch.setenv('TI_OPENAI_EMBEDDING_DIMENSIONS', '3')
    monkeypatch.setenv('TI_OPENAI_API_KEY', 'synthetic-never-live')
    monkeypatch.setenv('TI_AI_DAILY_TOKEN_LIMIT', '1000000')
    monkeypatch.setenv('TI_AI_DAILY_REQUEST_LIMIT', '100')
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '0')


def test_sqlite_rejects_before_paid_call_and_structured_query_needs_no_model(monkeypatch):
    settings(monkeypatch)
    app = create_app('sqlite://', Sources())
    model = SyntheticEmbeddings()
    app.state.embedding_adapter = model
    with TestClient(app) as client:
        live(client)
        item = search(client, filters={'kind': 'tire'}).json()['items'][0]
        status = client.get('/v1/knowledge/vector-status').json()
        assert status['available'] is False and status['reason'] == 'postgresql_pgvector_required'
        assert client.post('/v1/knowledge/embedding-plans', json={'document_ids': [item['id']]}).status_code == 503
        response = hybrid(client, 'Fixture Tire')
        assert response.status_code == 503 and not model.calls
        response = hybrid(client, '', {'product_code': 'FIX-001'})
        assert response.status_code == 200 and response.json()['state'] == 'completed'
        assert response.json()['reserved_tokens'] == 0 and response.json()['usage'] is None
        assert response.json()['result']['items'][0]['match']['method'] == 'structured'
        assert response.json()['result']['external_processing']['query_text_sent'] is False
        assert client.get('/v1/ai/status').json()['budget']['requests'] == 0
        assert not model.calls


def test_embedding_config_has_no_ambient_key_or_responses_model_dependency(monkeypatch):
    settings(monkeypatch)
    monkeypatch.delenv('TI_OPENAI_MODEL', raising=False)
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    assert configured_embeddings().dimensions == 3
    assert 'synthetic-never-live' not in repr(configured_embeddings())
    monkeypatch.delenv('TI_OPENAI_API_KEY')
    monkeypatch.setenv('OPENAI_API_KEY', 'ambient-never-use')
    with pytest.raises(EmbeddingError, match='embeddings_configuration_required'):
        configured_embeddings()


def native_response():
    return {'object': 'list', 'model': 'fixture-model', 'data': [
        {'object': 'embedding', 'index': 1, 'embedding': [0, 1, 0]},
        {'object': 'embedding', 'index': 0, 'embedding': [1, 0, 0]}],
        'usage': {'prompt_tokens': 12, 'total_tokens': 12}}


@pytest.mark.parametrize('bad', ['model', 'count', 'duplicate', 'index_bool', 'index_range', 'dimension',
                                    'nan', 'infinity', 'zero', 'underflow', 'giant_integer', 'huge_norm',
                                    'numeric_bool', 'usage', 'negative_usage'])
def test_native_embedding_response_fails_closed(bad):
    config = EmbeddingConfig('fixture-model', 3, 'secret-test')
    value = native_response()
    assert extract_embeddings(value, config, 2)['vectors'] == [[1, 0, 0], [0, 1, 0]]
    if bad == 'model': value['model'] = 'different'
    elif bad == 'count': value['data'].pop()
    elif bad == 'duplicate': value['data'][0]['index'] = 0
    elif bad == 'index_bool': value['data'][0]['index'] = True
    elif bad == 'index_range': value['data'][0]['index'] = 2
    elif bad == 'dimension': value['data'][0]['embedding'] = [1, 0]
    elif bad == 'nan': value['data'][0]['embedding'][0] = float('nan')
    elif bad == 'infinity': value['data'][0]['embedding'][0] = float('inf')
    elif bad == 'zero': value['data'][0]['embedding'] = [0, 0, 0]
    elif bad == 'underflow': value['data'][0]['embedding'] = [1e-300, 0, 0]
    elif bad == 'giant_integer': value['data'][0]['embedding'][0] = 10 ** 1000
    elif bad == 'huge_norm': value['data'][0]['embedding'] = [1e20, 0, 0]
    elif bad == 'numeric_bool': value['data'][0]['embedding'][0] = True
    elif bad == 'usage': value['usage']['total_tokens'] = 13
    else: value['usage'] = {'prompt_tokens': -1, 'total_tokens': -1}
    with pytest.raises(EmbeddingError, match='embeddings_response_invalid'):
        extract_embeddings(value, config, 2)


@pytest.mark.parametrize('case', ['ok', 'redirect', 'mime', 'large_header', 'large_stream', 'timeout', 'invalid_json'])
def test_native_http_contract_no_redirects_retries_or_ambient_proxy(monkeypatch, case):
    from tire_api import embedding_gateway as gateway
    observed = {'calls': 0}
    class Content:
        async def iter_chunked(self, _size):
            if case == 'timeout': raise TimeoutError()
            yield b'x' * (gateway.MAX_RESPONSE_BYTES + 1) if case == 'large_stream' else b'not-json' if case == 'invalid_json' else json.dumps(native_response()).encode()
    class Response:
        status = 302 if case == 'redirect' else 200
        headers = {'Content-Type': 'text/html' if case == 'mime' else 'application/json'}
        content_length = gateway.MAX_RESPONSE_BYTES + 1 if case == 'large_header' else None
        content = Content()
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
    class Client:
        def __init__(self, **kwargs): observed['client'] = kwargs
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        def post(self, url, **kwargs):
            observed['calls'] += 1
            observed['url'], observed['post'] = url, kwargs
            return Response()
    monkeypatch.setattr(gateway.aiohttp, 'TCPConnector', lambda **kwargs: observed.setdefault('connector', kwargs))
    monkeypatch.setattr(gateway.aiohttp, 'ClientSession', Client)
    config = EmbeddingConfig('fixture-model', 3, 'synthetic-auth-only')
    if case == 'ok':
        assert asyncio.run(OpenAIEmbeddingAdapter().embed(config, ['one', 'two']))['usage']['total_tokens'] == 12
    else:
        with pytest.raises(EmbeddingError):
            asyncio.run(OpenAIEmbeddingAdapter().embed(config, ['one', 'two']))
    assert observed['calls'] == 1 and observed['url'] == 'https://api.openai.com/v1/embeddings'
    assert observed['client']['trust_env'] is False and observed['post']['allow_redirects'] is False
    assert observed['connector']['resolver'].hosts == frozenset({'api.openai.com'})
    assert observed['connector']['use_dns_cache'] is False
    assert observed['post']['json'] == {'model': 'fixture-model', 'input': ['one', 'two'], 'encoding_format': 'float', 'dimensions': 3}
    assert observed['post']['headers']['Authorization'] == 'Bearer synthetic-auth-only'


def test_semantic_content_cache_survives_observation_metadata_but_isolates_model_privacy_dimensions():
    config = EmbeddingConfig('fixture-model', 3, 'secret')
    document = SimpleNamespace(payload={'kind': 'tire', 'label': 'Fixture Tire', 'privacy_class': 'public',
        '_values': {'size': '265/40R20', 'utqg_treadwear': 300, 'source_updated_at': '2026-01-01',
                    'source_url': 'https://must-not-send.example', 'id': 'not-semantic', 'operator': 'private-operator'}})
    before = document_chunks(document, config)
    document.payload['_values'].update(source_updated_at='2026-02-01', id='new-snapshot', operator='another')
    after = document_chunks(document, config)
    assert before == after
    assert not any(value in before[0]['text'] for value in ('2026-01-01', 'https://', 'private-operator', 'not-semantic'))
    assert before[0]['cache_id'] != document_chunks(document, EmbeddingConfig('other-model', 3, 'secret'))[0]['cache_id']
    assert before[0]['cache_id'] != document_chunks(document, EmbeddingConfig('fixture-model', 4, 'secret'))[0]['cache_id']
    document.payload['privacy_class'] = 'private'
    assert before[0]['cache_id'] != document_chunks(document, config)[0]['cache_id']
    document.payload['privacy_class'] = 'public'
    document.payload['_values']['utqg_treadwear'] = 340
    assert before[0]['cache_id'] != document_chunks(document, config)[0]['cache_id']
    source = '中🙂word' * 1500
    chunks = chunk_text(source)
    assert ''.join(chunks) == source and all(len(chunk.encode('utf-8')) <= 6000 for chunk in chunks)
    from fastapi import HTTPException
    with pytest.raises(HTTPException): bounded_batch([{'text': 'x'}] * 33)
    with pytest.raises(HTTPException): bounded_batch([{'text': 'x' * 6000}] * 17)


def test_rrf_scores_union_and_duplicates_are_document_scoped():
    scores, ranks = reciprocal_rank_fusion(['a', 'b'], ['b', 'c'])
    assert set(scores) == {'a', 'b', 'c'} and scores['b'] == 1 / 62 + 1 / 61
    assert ranks['b'] == {'fts_rank': 2, 'dense_rank': 1}


def test_shared_pending_budget_immutable_ledger_unknown_replay_and_session_boundary(monkeypatch):
    from tire_api.ai_models import AIRequest, AIEvidencePack
    from tire_api.embedding_api import HybridRequest
    from tire_api.embedding_budget import budget_usage
    from tire_api.knowledge import KnowledgeSearch
    from tire_api.service import QueryService
    from test_ai import analyze, historical_pack, ModelFixture
    settings(monkeypatch)
    monkeypatch.setenv('TI_AI_ENABLED', '1')
    monkeypatch.setenv('TI_OPENAI_MODEL', 'synthetic-response-fixture')
    app = create_app('sqlite://', Sources())
    model = ModelFixture()
    app.state.ai_adapter = model
    with TestClient(app) as client:
        pack = historical_pack(client)
        with app.state.database.sessions() as db:
            actor = db.get(AIEvidencePack, pack['id']).actor_session_id
            query = HybridRequest(search=KnowledgeSearch(mode='history', text='ledger question'), allow_external_processing=True)
            key = str(uuid4())
            row = EmbeddingRequest(actor_session_id=actor, idempotency_key=key, kind='hybrid',
                request_hash=digest({'kind': 'hybrid', **query.model_dump()}), model_space='synthetic-space',
                payload={}, billable=True, reserved_tokens=4500)
            db.add(row)
            db.commit()
            run_id = row.id
        assert analyze(client, pack).status_code == 429 and not model.calls
        assert hybrid(client, 'ledger question', key=key).status_code == 202
        assert client.get('/v1/ai/status').json()['budget']['accounted_tokens'] == 4500
        other = TestClient(app)
        assert other.get(f'/v1/knowledge/embedding-runs/{run_id}?mode=history').status_code == 404
        assert other.get('/v1/knowledge/embedding-runs?mode=history').json()['items'] == []
        from tire_api import embedding_service
        monkeypatch.setattr(embedding_service, 'utcnow', lambda: utcnow() + timedelta(seconds=130))
        assert hybrid(client, 'ledger question', key=key).json()['state'] == 'outcome_unknown'
        with app.state.database.sessions() as db:
            saved = db.get(EmbeddingRequest, run_id)
            saved.reserved_tokens = 0
            with pytest.raises(ValueError): db.commit()


def test_responses_pending_blocks_embedding_reservation_and_completed_usage_reconciles(monkeypatch):
    from tire_api.ai_models import AIRequest, AICompletion, AIEvidencePack
    from tire_api.embedding_budget import budget_usage
    from tire_api.service import QueryService
    from fastapi import HTTPException
    from test_ai import historical_pack
    settings(monkeypatch)
    app = create_app('sqlite://', Sources())
    with TestClient(app) as client:
        pack = historical_pack(client)
        with app.state.database.sessions() as db:
            actor = db.get(AIEvidencePack, pack['id']).actor_session_id
            ai = AIRequest(actor_session_id=actor, idempotency_key=str(uuid4()), request_hash=digest('fixture'),
                pack_id=pack['id'], question='Synthetic pending', provider='fixture', model='fixture',
                request_contract={}, reserved_tokens=3000)
            db.add(ai)
            db.commit()
            QueryService(db, None).lock_ingestion()
            with pytest.raises(HTTPException) as error:
                reserve_request(db, config=configured_embeddings(), session_id=actor, key=str(uuid4()), kind='index',
                    request_hash=digest('embedding'), payload={}, inputs=['Synthetic document'])
            assert error.value.status_code == 429
            db.rollback()
            db.add(AICompletion(request_id=ai.id, state='completed', usage={'input_tokens': 25, 'output_tokens': 5, 'total_tokens': 30}))
            db.commit()
            QueryService(db, None).lock_ingestion()
            row = reserve_request(db, config=configured_embeddings(), session_id=actor, key=str(uuid4()), kind='hybrid',
                    request_hash=digest('embedding'), payload={}, inputs=['Synthetic question'])
            assert budget_usage(db)['accounted_tokens'] == 30 + row.reserved_tokens
            assert budget_usage(db)['requests'] == 2 and budget_usage(db)['has_pending_request']


def test_concurrent_free_structured_queries_share_one_receipt(tmp_path):
    app = create_app('sqlite:///' + (tmp_path / 'structured-idempotency.db').as_posix(), Sources())
    model = SyntheticEmbeddings()
    app.state.embedding_adapter = model
    with TestClient(app) as client:
        live(client)
        barrier = Barrier(4)
        key = str(uuid4())
        def query(_):
            barrier.wait(timeout=10)
            return hybrid(client, '', {'kind': 'tire'}, key)
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(query, range(4)))
        assert all(value.status_code in {200, 202} for value in values)
        assert len({value.json()['id'] for value in values}) == 1 and not model.calls
        with app.state.database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(EmbeddingRequest)) == 1


def hybrid(client, value, filters=None, key=None, consent=True):
    return client.post('/v1/knowledge/hybrid-search', headers={'Idempotency-Key': key or str(uuid4())},
        json={'search': {'mode': 'history', 'text': value, 'filters': filters or {}}, 'allow_external_processing': consent})


def build(client, plan, key=None, consent=True):
    return client.post('/v1/knowledge/embedding-runs', headers={'Idempotency-Key': key or str(uuid4())},
        json={'plan_id': plan['id'], 'allow_external_processing': consent})


def create_plan(client, documents):
    response = client.post('/v1/knowledge/embedding-plans', json={'document_ids': [item['id'] for item in documents]})
    assert response.status_code == 200, response.text
    return response.json()


def verify_embedding_persistence(url):
    """Use only an isolated PostgreSQL DB with vector installed. Provider is synthetic.

    The runner supplies a non-superuser owner URL privately; never print or return
    that URL, credentials, session cookies, question histories, or keys.
    """
    checks = []
    with pytest.MonkeyPatch.context() as monkeypatch:
        settings(monkeypatch)
        registry = Sources()
        app = create_app(url, registry)
        model = SyntheticEmbeddings()
        app.state.embedding_adapter = model
        with TestClient(app) as client:
            status = client.get('/v1/knowledge/vector-status').json()
            assert status['available'] and status['backend'] == 'postgresql', status
            alpha_id, beta_id, missing_id = str(uuid4()), str(uuid4()), str(uuid4())
            alpha = {**VARIANT, 'id': alpha_id, 'model': 'fixturealpha', 'facts': {'description': '湿地制动 fixturealpha'}}
            beta = {**VARIANT, 'id': beta_id, 'model': 'fixturebeta', 'manufacturer_product_code': 'BETA',
                    'facts': {'description': '日常通勤 fixturebeta'}}
            missing = {**VARIANT, 'id': missing_id, 'model': 'fixturemissing', 'manufacturer_product_code': 'MISSING',
                       'facts': {'description': '湿地制动 fixturemissing'}}
            alpha_snapshot, actor_id = seed(app.state.database, [alpha, beta, missing], query='embedding-acceptance')
            results = search(client, filters={'kind': 'tire'}).json()['items']
            documents = [row for row in results if row['reference']['variant_id'] in {alpha_id, beta_id}]
            assert len(documents) == 2
            plan = create_plan(client, documents)
            assert plan['pending_chunks'] == 2 and plan['reserved_tokens'] > 0 and not model.calls
            assert build(client, plan, consent=False).status_code == 422
            other = TestClient(app)
            assert build(other, plan).status_code == 404
            from tire_api import embedding_service
            with pytest.MonkeyPatch.context() as clock:
                clock.setattr(embedding_service, 'utcnow', lambda: utcnow() + timedelta(minutes=6))
                assert build(client, plan).status_code == 409
            assert not model.calls
            key = str(uuid4())
            run = build(client, plan, key).json()
            assert run['state'] == 'completed' and run['result']['written_chunks'] == 2, run
            assert len(model.calls) == 1 and build(client, plan, key).json() == run
            assert len(model.calls) == 1
            checks.append('explicit_plan_and_idempotent_pgvector_build')
            # The same paid query key racing while the provider is live is only
            # observed, never submitted again. Reservation exists before egress.
            entered, release = Event(), Event()
            class SlowEmbeddings(SyntheticEmbeddings):
                async def embed(self, config, inputs):
                    entered.set()
                    assert await asyncio.to_thread(release.wait, 10)
                    return await super().embed(config, inputs)
            slow = SlowEmbeddings()
            slow.calls = model.calls
            app.state.embedding_adapter = slow
            concurrent_key = str(uuid4())
            with ThreadPoolExecutor(max_workers=2) as pool:
                running = pool.submit(hybrid, client, 'concurrent fixture query', None, concurrent_key)
                try:
                    assert entered.wait(10)
                    duplicate = hybrid(client, 'concurrent fixture query', key=concurrent_key)
                    assert duplicate.status_code == 202 and duplicate.json()['state'] == 'pending'
                    assert hybrid(client, 'parallel different query').status_code == 429
                    pending_budget = client.get('/v1/ai/status').json()['budget']
                    assert pending_budget['has_pending_request'] and pending_budget['requests'] == 2
                finally:
                    release.set()
                concurrent_result = running.result(timeout=15).json()
            assert concurrent_result['state'] == 'completed' and len(model.calls) == 2, concurrent_result
            app.state.embedding_adapter = model
            checks.append('concurrent_paid_idempotency_and_pre_egress_budget_reservation')
            query_key = str(uuid4())
            found = hybrid(client, '湿地制动', key=query_key).json()
            assert found['state'] == 'completed', found
            result = found['result']
            assert result['total_scope'] == 'candidates' and result['coverage']['missing_documents'] >= 1
            assert result['external_processing']['query_text_sent'] is True
            assert result['items'][0]['reference']['variant_id'] == alpha_id
            assert result['items'][0]['match']['method'] == 'hybrid'
            assert any(item['reference']['variant_id'] == missing_id and item['match']['method'] == 'fts' for item in result['items'])
            assert result['candidate_counts']['dense'] >= 2 and result['candidate_counts']['fts'] >= 2
            assert model.calls[-1][2] == ['湿地制动']  # No candidate document text leaves the machine.
            assert hybrid(client, '湿地制动', key=query_key).json() == found and len(model.calls) == 3
            assert hybrid(client, 'other query', key=query_key).status_code == 409
            checks.append('real_cosine_rrf_partial_coverage_and_query_only_egress')
            filtered = hybrid(client, '湿地制动', {'variant_id': beta_id}).json()
            assert filtered['state'] == 'completed', filtered
            assert {item['reference']['variant_id'] for item in filtered['result']['items']} == {beta_id}
            assert filtered['result']['items'][0]['match']['method'] == 'dense'
            assert hybrid(client, '湿地制动', {'region': 'CN'}).status_code == 409
            checks.append('identical_hard_filters_before_fts_and_dense')
            cached = create_plan(client, documents)
            calls = len(model.calls)
            assert cached['pending_chunks'] == 0
            assert build(client, cached).json()['result']['written_chunks'] == 0 and len(model.calls) == calls
            # Source re-observation and a 304 never change semantic cache keys.
            seed(app.state.database, None, query='embedding-acceptance', snapshot=alpha_snapshot,
                 at=utcnow() + timedelta(seconds=1))
            assert create_plan(client, documents)['pending_chunks'] == 0
            seed(app.state.database, [alpha, beta, missing], query='embedding-acceptance', at=utcnow() + timedelta(seconds=2))
            newer = search(client, filters={'variant_id': alpha_id}).json()['items']
            assert newer[0]['id'] != next(d['id'] for d in documents if d['reference']['variant_id'] == alpha_id)
            assert create_plan(client, newer)['pending_chunks'] == 0
            checks.append('content_addressing_reuses_304_and_equal_facts_new_snapshot')
            # Changing model or dimensions creates an independent space.
            monkeypatch.setenv('TI_OPENAI_EMBEDDING_DIMENSIONS', '4')
            assert create_plan(client, newer)['pending_chunks'] == 1
            assert hybrid(client, '湿地制动', {'variant_id': alpha_id}).status_code == 409
            monkeypatch.setenv('TI_OPENAI_EMBEDDING_DIMENSIONS', '3')
            monkeypatch.setenv('TI_OPENAI_EMBEDDING_MODEL', 'other-synthetic-model')
            assert create_plan(client, newer)['pending_chunks'] == 1
            monkeypatch.setenv('TI_OPENAI_EMBEDDING_MODEL', 'synthetic-embedding-fixture')
            checks.append('model_and_dimension_spaces_are_disjoint')
            # Source privacy metadata changes cannot reuse public vectors.
            private_id = str(uuid4())
            seed(app.state.database, [{**alpha, 'id': private_id}], source='unknown-private-source', query='private')
            private = search(client, filters={'variant_id': private_id}).json()['items']
            assert client.post('/v1/knowledge/embedding-plans', json={'document_ids': [private[0]['id']]}).status_code == 403
            monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '1')
            assert create_plan(client, private)['pending_chunks'] == 1
            monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '0')
            checks.append('private_policy_and_cache_privacy_isolation')
            # In-flight plan must be rejected if the current entity is withdrawn.
            pending_plan = create_plan(client, newer)
            with app.state.database.sessions() as db:
                db.add(VariantLifecycleEvent(variant_id=alpha_id, revision=1, action='revoke', before_state='active',
                    after_state='revoked', operator_session_id=actor_id, operator='Synthetic', reason='test withdrawal', evidence=[]))
                db.commit()
            assert build(client, pending_plan).status_code == 409
            response = hybrid(client, '湿地制动').json()
            assert response['state'] == 'completed', response
            assert alpha_id not in {item['reference'].get('variant_id') for item in response['result']['items']}
            with app.state.database.sessions() as db:
                assert db.scalar(select(func.count()).select_from(EmbeddingCache)) == 2
            checks.append('withdrawn_document_cannot_reappear_from_old_vectors')
            # A real content change produces a new cache entry; only the latest
            # formal document can join it. The old vector remains historical.
            changed_beta = {**beta, 'facts': {'description': '日常通勤 fixturebeta changedfacts'}}
            changed_snapshot, _ = seed(app.state.database, [alpha, changed_beta, missing],
                                      query='embedding-acceptance', at=utcnow() + timedelta(seconds=3))
            beta_documents = search(client, filters={'variant_id': beta_id}).json()['items']
            changed_plan = create_plan(client, beta_documents)
            assert changed_plan['pending_chunks'] == 1
            changed_run = build(client, changed_plan).json()
            assert changed_run['state'] == 'completed' and changed_run['result']['written_chunks'] == 1, changed_run
            changed_search = hybrid(client, 'changedfacts', {'variant_id': beta_id}).json()
            assert changed_search['state'] == 'completed', changed_search
            assert {item['reference']['snapshot_id'] for item in changed_search['result']['items']} == {changed_snapshot}
            with app.state.database.sessions() as db:
                assert db.scalar(select(func.count()).select_from(EmbeddingCache)) == 3
            checks.append('changed_fact_incremental_embedding_and_old_cache_exclusion')
            model.error = EmbeddingError('secret-error-must-not-escape')
            failure_key = str(uuid4())
            failed = hybrid(client, 'provider failure fixture', key=failure_key).json()
            assert failed['state'] == 'failed' and failed['error_code'] == 'embeddings_provider_failed' and failed['result'] is None
            count_before = len(model.calls)
            assert hybrid(client, 'provider failure fixture', key=failure_key).json() == failed and len(model.calls) == count_before
            assert 'secret-error' not in json.dumps(failed)
            model.error = None
            checks.append('provider_failure_durable_and_never_claims_hybrid_success')
            budget = client.get('/v1/ai/status').json()['budget']
            assert budget['requests'] == len(model.calls) and budget['accounted_tokens'] >= failed['reserved_tokens']
            monkeypatch.setenv('TI_AI_DAILY_REQUEST_LIMIT', str(budget['requests']))
            assert hybrid(client, 'budget exhausted fixture').status_code == 429
            monkeypatch.setenv('TI_AI_DAILY_REQUEST_LIMIT', '100')
            checks.append('shared_responses_embedding_budget')
            cookies = dict(client.cookies)
        # Restart: replay does not call a provider and saved vector space survives.
        restart = create_app(url, registry)
        restarted_model = SyntheticEmbeddings()
        restart.state.embedding_adapter = restarted_model
        with TestClient(restart) as client:
            client.cookies.update(cookies)
            assert build(client, plan, key).json() == run
            assert hybrid(client, '湿地制动', key=query_key).json() == found
            assert not restarted_model.calls
            with restart.state.database.sessions() as db:
                assert db.execute(text('SELECT count(*) FROM embedding_vectors')).scalar() == 3
                assert db.execute(text("SELECT count(*) FROM pg_indexes WHERE tablename = 'embedding_vectors' AND indexdef LIKE '%USING hnsw%'")).scalar() >= 1
        checks.append('restart_idempotency_vector_mirror_and_hnsw_persist')
    return {'provider': 'synthetic_fixed_vectors_not_live_semantic_acceptance', 'checks': checks,
            'passed': len(checks), 'business_tables': ['embedding_cache', 'embedding_plans', 'embedding_requests', 'embedding_completions']}
