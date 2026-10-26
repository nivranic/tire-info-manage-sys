"""Private actual-S2 knowledge/embedding gates; no production rights or PG claim.

Run only through the managed runner. SQLite exercises durable inputs and ledger
boundaries; a controlled query adapter never stands for live semantic ranking.
"""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select, update

from test_vehicle_binary_consumers import allowed_local
from test_vehicle_binary_ingestion import adopt, assert_completed, damage_snapshot, private
from test_vehicle_pdf_runtime import reviewed_pdf
from tire_api import dense, embedding_api, embedding_service, knowledge_index, vehicle_raw
from tire_api.db import AuditEvent
from tire_api.domain import digest
from tire_api.embedding_budget import budget_usage
from tire_api.embedding_gateway import EmbeddingConfig, EmbeddingError, reservation
from tire_api.embedding_models import EmbeddingCache, EmbeddingCompletion, EmbeddingPlan, EmbeddingRequest
from tire_api.embedding_text import TEXT_CONTRACT, document_chunks
from tire_api.knowledge import KnowledgeSearch
from tire_api.knowledge_models import KnowledgeDocument, KnowledgeIndexState
from tire_api.service import QueryService
from tire_api.vehicles import VehicleVerification


QUERY = 'Compare the archived configuration evidence.'
ZERO = {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}
STATE_MODELS = (KnowledgeDocument, KnowledgeIndexState, EmbeddingPlan, EmbeddingRequest,
                EmbeddingCompletion, EmbeddingCache, AuditEvent)


class ForbidEmbedding:
    def __init__(self):
        self.calls = []

    async def embed(self, _config, inputs):
        self.calls.append(list(inputs))
        raise AssertionError('a forbidden embedding Provider was called')


@pytest.fixture
def knowledge_ctx(private, monkeypatch):
    accepted = adopt(private)
    assert accepted['data_state'] == 'live'
    assert_completed(private, accepted['query_id'])
    private.snapshot_id = accepted['provenance'][0]['snapshot_id']
    private.config = EmbeddingConfig('private-r92-fixture', 3, 'synthetic-unused',
                                    daily_token_limit=1000000, daily_request_limit=100, allow_private=True)
    private.provider = ForbidEmbedding()
    private.app.state.embedding_adapter = private.provider
    # Capability is deliberately isolated from these SQLite source/input tests.
    monkeypatch.setattr(embedding_service, 'require_config', lambda _db: private.config)
    monkeypatch.setattr(embedding_api, 'require_config', lambda _db: private.config)
    effects = {'mirror': 0, 'save_vectors': 0}
    def forbid_mirror(*_args, **_kwargs):
        effects['mirror'] += 1
        raise AssertionError('these source/input tests must not touch the PG mirror')
    def forbid_save(*_args, **_kwargs):
        effects['save_vectors'] += 1
        raise AssertionError('forbidden document vectors must not be written')
    monkeypatch.setattr(embedding_api, 'mirror_cache', forbid_mirror)
    monkeypatch.setattr(embedding_service, 'mirror_cache', forbid_mirror)
    monkeypatch.setattr(embedding_api, 'save_vectors', forbid_save)
    yield private
    assert private.provider.calls == [] and effects == {'mirror': 0, 'save_vectors': 0}


@contextmanager
def local_only(monkeypatch):
    original = vehicle_raw._vehicle_consumer_rights
    with monkeypatch.context() as scoped:
        scoped.setattr(vehicle_raw, '_vehicle_consumer_rights', lambda capsule:
            {**original(capsule), 'structured_fact_use': 'allowed'})
        yield


def state(ctx):
    with ctx.database.sessions() as db:
        counts = tuple(db.scalar(select(func.count()).select_from(model)) for model in STATE_MODELS)
        index = db.get(KnowledgeIndexState, 'accepted')
        documents = sorted((row.id, row.kind, row.source_id, digest(row.payload), row.tokens)
                           for row in db.scalars(select(KnowledgeDocument)))
        plans = sorted((row.id, row.fingerprint) for row in db.scalars(select(EmbeddingPlan)))
        return counts, index.signature if index else None, documents, plans


def post(ctx, path, body, key=None):
    return ctx.client.post(path, json=body, headers={'Idempotency-Key': key or str(uuid4())})


def search_body(text=QUERY, filters=None):
    return KnowledgeSearch(mode='history', text=text, filters=filters or {}).model_dump()


def build_body(plan_id):
    return {'plan_id': plan_id, 'allow_external_processing': True}


def hybrid_body(text=QUERY, filters=None):
    return {'search': search_body(text, filters), 'allow_external_processing': True}


def index_documents(ctx):
    with ctx.database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        knowledge_index.refresh_index(db, ctx.app.state.registry)
        ids = list(db.scalars(select(KnowledgeDocument.id).order_by(KnowledgeDocument.id)))
        db.commit()
    assert ids
    return ids


def make_plan(ctx):
    ids = index_documents(ctx)
    response = post(ctx, '/v1/knowledge/embedding-plans', {'document_ids': ids})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['pending_chunks'] > 0
    return value['id']


def cache_documents(ctx):
    with ctx.database.sessions() as db:
        documents = list(db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.id)))
        for document in documents:
            for chunk in document_chunks(document, ctx.config):
                if db.get(EmbeddingCache, chunk['cache_id']) is None:
                    db.add(EmbeddingCache(id=chunk['cache_id'], model_space=ctx.config.model_space,
                        provider='openai_embeddings', model=ctx.config.model, dimensions=ctx.config.dimensions,
                        text_contract=TEXT_CONTRACT, privacy_class=chunk['privacy_class'],
                        text_hash=chunk['hash'], vector=[1.0, 0.0, 0.0]))
        db.commit()


def archive_index(ctx, plan_id, *, cached=False):
    with ctx.database.sessions() as db:
        plan = db.get(EmbeddingPlan, plan_id)
        unique = {chunk['cache_id']: chunk for doc in plan.payload['documents'] for chunk in doc['chunks']}
        chunks = [] if cached else list(unique.values())
        inputs = [chunk['text'] for chunk in chunks]
        row = EmbeddingRequest(actor_session_id=ctx.session_id, idempotency_key=str(uuid4()), kind='index',
            request_hash=digest({'kind': 'index', **build_body(plan_id)}), model_space=ctx.config.model_space,
            plan_id=plan_id, payload={'plan_id': plan_id, 'input_hashes': [chunk['hash'] for chunk in chunks]},
            billable=bool(inputs), reserved_tokens=reservation(inputs) if inputs else 0)
        db.add(row)
        db.commit()
        return SimpleNamespace(id=row.id, inputs=inputs, plan_id=plan_id)


def archive_query(ctx):
    payload = search_body()
    with ctx.database.sessions() as db:
        row = EmbeddingRequest(actor_session_id=ctx.session_id, idempotency_key=str(uuid4()), kind='hybrid',
            request_hash=digest({'kind': 'hybrid', 'search': payload, 'allow_external_processing': True}),
            model_space=ctx.config.model_space, payload=payload, billable=True, reserved_tokens=reservation([QUERY]))
        db.add(row)
        db.commit()
        return SimpleNamespace(id=row.id, inputs=[QUERY])


def dispatch(ctx, archived, *, inputs=None, config=None):
    return asyncio.run(embedding_api.dispatch_embedding(ctx.app, config or ctx.config,
        archived.inputs if inputs is None else inputs, request_id=archived.id, session_id=ctx.session_id))


def assert_local(result, code):
    receipt, error, local_refusal = result
    assert receipt is None and error == code and local_refusal is True


def assert_http(response, status, code):
    assert response.status_code == status and response.json()['detail'] == {'code': code}


@pytest.mark.parametrize('warm', [False, True], ids=['cold', 'warm'])
def test_pending_current_head_blocks_every_entry_before_filters_config_and_writes(knowledge_ctx, monkeypatch, warm):
    ctx = knowledge_ctx
    if warm:
        with local_only(monkeypatch):
            make_plan(ctx)
    before = state(ctx)
    for filters in ({'kind': 'vehicle'}, {'kind': 'tire'}):
        response = post(ctx, '/v1/knowledge/search', search_body('', filters))
        assert_http(response, 403, 'vehicle_structured_fact_use_not_allowed')
    assert_http(ctx.client.get('/v1/knowledge/vector-status'), 403, 'vehicle_structured_fact_use_not_allowed')
    assert_http(post(ctx, '/v1/knowledge/embedding-plans', {'document_ids': ['0' * 64]}),
                403, 'vehicle_structured_fact_use_not_allowed')
    assert_http(post(ctx, '/v1/knowledge/embedding-runs', build_body('0' * 32)),
                403, 'vehicle_structured_fact_use_not_allowed')
    for body in (hybrid_body(), hybrid_body('', {'kind': 'tire'})):
        assert_http(post(ctx, '/v1/knowledge/hybrid-search', body), 403, 'vehicle_structured_fact_use_not_allowed')
    with ctx.database.sessions() as db:
        with pytest.raises(HTTPException) as error:
            dense.current_materials(db, ctx.config, {'kind': 'tire'})
        assert error.value.status_code == 403 and error.value.detail == {'code': 'vehicle_structured_fact_use_not_allowed'}
    assert state(ctx) == before and ctx.provider.calls == []


@pytest.mark.parametrize('damage', ['identity', 'vehicle'], ids=['exact-parser-identity', 'exact-formal-vehicle'])
def test_exact_current_verification_is_checked_before_warm_or_tire_only_use(knowledge_ctx, allowed_local, damage):
    ctx = knowledge_ctx
    index_documents(ctx)
    with ctx.database.sessions() as db:
        row = db.scalar(select(VehicleVerification).where(VehicleVerification.snapshot_id == ctx.snapshot_id))
        values = ({'parser_identity': {**row.parser_identity, 'parser_digest': '0' * 64}} if damage == 'identity'
                  else {'vehicle_id': 'private-wrong-formal-vehicle'})
        db.execute(update(VehicleVerification).where(VehicleVerification.id == row.id).values(**values))
        db.commit()
    before = state(ctx)
    response = post(ctx, '/v1/knowledge/search', search_body('', {'kind': 'tire'}))
    assert_http(response, 409, 'vehicle_raw_integrity_failed')
    assert state(ctx) == before and ctx.provider.calls == []


@pytest.mark.parametrize('changed', ['markers', 'values', 'empty-plan', 'frozen-chunk'])
def test_projection_and_durable_plan_cannot_launder_binary_material(knowledge_ctx, allowed_local, changed):
    ctx = knowledge_ctx
    archived = archive_index(ctx, make_plan(ctx))
    with ctx.database.sessions() as db:
        if changed in {'empty-plan', 'frozen-chunk'}:
            plan = db.get(EmbeddingPlan, archived.plan_id)
            payload = deepcopy(plan.payload)
            if changed == 'empty-plan':
                payload['documents'] = []
            else:
                # Its own recomputed fingerprint cannot attest substituted text.
                payload['documents'][0]['chunks'][0]['text'] = 'substituted frozen chunk'
            db.execute(update(EmbeddingPlan).where(EmbeddingPlan.id == plan.id).values(
                payload=payload, fingerprint=digest(payload)))
        else:
            document = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.kind == 'vehicle'))
            payload = deepcopy(document.payload)
            values = {}
            if changed == 'markers':
                payload.update(kind='tire', source_id='private-unrelated', reference={'kind': 'tire', 'variant_id': 'private'})
                values = {'kind': 'tire', 'source_id': 'private-unrelated'}
            else:
                payload['_values']['vehicle']['model'] = 'substituted semantic material'
            db.execute(update(KnowledgeDocument).where(KnowledgeDocument.id == document.id).values(payload=payload, **values))
        db.commit()
    before = state(ctx)
    assert_local(dispatch(ctx, archived), 'vehicle_evidence_binding_failed')
    assert state(ctx) == before and ctx.provider.calls == []


@pytest.mark.parametrize('cached', [False, True], ids=['missing', 'all-cached'])
def test_local_preview_and_cache_never_grant_build_reserve_or_old_dispatch(knowledge_ctx, allowed_local, cached):
    ctx = knowledge_ctx
    plan_id = make_plan(ctx)
    if cached:
        cache_documents(ctx)
    before = state(ctx)
    assert_http(post(ctx, '/v1/knowledge/embedding-runs', build_body(plan_id)), 403, 'vehicle_provider_use_not_allowed')
    with ctx.database.sessions() as db:
        plan = db.get(EmbeddingPlan, plan_id)
        chunks = {chunk['cache_id']: chunk for doc in plan.payload['documents'] for chunk in doc['chunks']}
        inputs = [] if cached else [chunk['text'] for chunk in chunks.values()]
        with pytest.raises(HTTPException) as error:
            embedding_service.reserve_request(db, config=ctx.config, session_id=ctx.session_id, key=str(uuid4()),
                kind='index', request_hash=digest({'kind': 'index', **build_body(plan_id)}),
                payload={'plan_id': plan_id, 'input_hashes': [digest(value) for value in inputs]},
                inputs=inputs, plan_id=plan_id)
        assert error.value.status_code == 403 and error.value.detail == {'code': 'vehicle_provider_use_not_allowed'}
    assert state(ctx) == before
    archived = archive_index(ctx, plan_id, cached=cached)
    assert_local(dispatch(ctx, archived), 'vehicle_provider_use_not_allowed')
    assert ctx.provider.calls == []


@pytest.mark.parametrize('changed', ['text', 'missing-hashes', 'empty-hashes', 'plan-id', 'false-consent', 'config'])
def test_actual_index_inputs_require_the_complete_durable_authorization(knowledge_ctx, allowed_local, changed):
    ctx = knowledge_ctx
    archived = archive_index(ctx, make_plan(ctx))
    inputs, config = archived.inputs, ctx.config
    if changed == 'text':
        inputs = ['unrelated replacement text']
    elif changed == 'config':
        config = EmbeddingConfig('different-private-model', 3, 'synthetic-unused', allow_private=True)
    else:
        with ctx.database.sessions() as db:
            row = db.get(EmbeddingRequest, archived.id)
            payload = deepcopy(row.payload)
            values = {}
            if changed == 'missing-hashes':
                payload.pop('input_hashes')
            elif changed == 'empty-hashes':
                payload['input_hashes'] = []
            elif changed == 'plan-id':
                payload['plan_id'] = 'missing-private-plan'
            else:
                values['request_hash'] = digest({'kind': 'index', 'plan_id': row.plan_id,
                                                 'allow_external_processing': False})
            db.execute(update(EmbeddingRequest).where(EmbeddingRequest.id == row.id).values(payload=payload, **values))
            db.commit()
    before = state(ctx)
    assert_local(dispatch(ctx, archived, inputs=inputs, config=config), 'vehicle_evidence_binding_failed')
    assert state(ctx) == before and ctx.provider.calls == []


@pytest.mark.parametrize('damage', ['object', 'encoding'], ids=['same-length-original', 'encoding-downgrade'])
def test_old_reservation_rechecks_raw_at_the_actual_embedding_point(knowledge_ctx, allowed_local, damage):
    ctx = knowledge_ctx
    archived = archive_index(ctx, make_plan(ctx))
    damage_snapshot(ctx, ctx.snapshot_id, damage)
    before = state(ctx)
    assert_local(dispatch(ctx, archived), 'vehicle_raw_integrity_failed')
    assert state(ctx) == before and ctx.provider.calls == []


def test_hybrid_sends_only_durable_query_after_reader_closes_and_preserves_caller_dirty(knowledge_ctx, allowed_local, monkeypatch):
    ctx = knowledge_ctx
    index_documents(ctx)
    cache_documents(ctx)
    archived = archive_query(ctx)
    sessions, flushes = [], []
    factory = ctx.database.sessions
    def readers(*args, **kwargs):
        reader = factory(*args, **kwargs)
        event.listen(reader, 'before_flush', lambda *_args: flushes.append(True))
        sessions.append(reader)
        return reader
    monkeypatch.setattr(ctx.database, 'sessions', readers)
    class QueryOnly:
        calls = []
        async def embed(self, config, inputs):
            self.calls.append(list(inputs))
            assert sessions and all(not reader.in_transaction() for reader in sessions)
            assert config.model_space == ctx.config.model_space
            raise EmbeddingError('embeddings_response_invalid')
    adapter = QueryOnly()
    ctx.app.state.embedding_adapter = adapter
    with factory() as caller:
        pending = AuditEvent(session_id=ctx.session_id, action='private_r92_unflushed', detail={})
        caller.add(pending)
        receipt, error, local_refusal = dispatch(ctx, archived)
        assert pending in caller.new and caller.is_active
    assert receipt is None and error == 'embeddings_response_invalid' and local_refusal is False
    assert adapter.calls == [[QUERY]] and flushes == []
    assert all(not reader.in_transaction() for reader in sessions)
    with factory() as db:
        capsule = vehicle_raw.checked_vehicle_consumer_capsule(db, ctx.snapshot_id)
        with pytest.raises(vehicle_raw.VehicleUseNotAllowed):
            vehicle_raw.require_vehicle_consumer_use(capsule, 'provider')


@pytest.mark.parametrize('changed', ['document-text', 'two-inputs', 'other-query', 'false-consent', 'noncanonical-shape'])
def test_hybrid_query_permission_cannot_authorize_different_actual_inputs(knowledge_ctx, allowed_local, changed):
    ctx = knowledge_ctx
    index_documents(ctx)
    cache_documents(ctx)
    archived = archive_query(ctx)
    inputs = [QUERY]
    if changed == 'document-text':
        with ctx.database.sessions() as db:
            document = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.kind == 'vehicle'))
            inputs = [document_chunks(document, ctx.config)[0]['text']]
    elif changed == 'two-inputs':
        inputs = [QUERY, 'a second text must not be sent']
    elif changed == 'other-query':
        inputs = ['a different query must not be sent']
    else:
        with ctx.database.sessions() as db:
            row = db.get(EmbeddingRequest, archived.id)
            payload = deepcopy(row.payload)
            if changed == 'noncanonical-shape':
                payload.pop('limit')
            body = {'search': payload, 'allow_external_processing': changed != 'false-consent'}
            db.execute(update(EmbeddingRequest).where(EmbeddingRequest.id == row.id).values(
                payload=payload, request_hash=digest({'kind': 'hybrid', **body})))
            db.commit()
    assert_local(dispatch(ctx, archived, inputs=inputs), 'vehicle_evidence_binding_failed')
    assert ctx.provider.calls == []


def test_structured_hybrid_with_binary_material_is_local_only(knowledge_ctx, allowed_local, monkeypatch):
    ctx = knowledge_ctx
    index_documents(ctx)
    fresh, calls = embedding_api.check_embedding_dispatch, []
    def checked(*args, **kwargs):
        calls.append(True)
        return fresh(*args, **kwargs)
    monkeypatch.setattr(embedding_api, 'check_embedding_dispatch', checked)
    response = post(ctx, '/v1/knowledge/hybrid-search', hybrid_body('', {'kind': 'vehicle'}))
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['state'] == 'completed' and value['reserved_tokens'] == 0 and value['usage'] is None
    assert value['result']['external_processing'] == {'query_text_sent': False}
    assert calls == [True] and ctx.provider.calls == []
    with ctx.database.sessions() as db:
        assert budget_usage(db)['requests'] == 0
        capsule = vehicle_raw.checked_vehicle_consumer_capsule(db, ctx.snapshot_id)
        with pytest.raises(vehicle_raw.VehicleUseNotAllowed):
            vehicle_raw.require_vehicle_consumer_use(capsule, 'provider')


def test_actual_local_predispatch_refusal_releases_tokens_and_replay_never_dispatches(knowledge_ctx, allowed_local, monkeypatch):
    ctx = knowledge_ctx
    index_documents(ctx)
    cache_documents(ctx)
    actual, dispatches = embedding_api.reserve_request, []
    fresh = embedding_service.check_embedding_dispatch
    def reserve(*args, **kwargs):
        row = actual(*args, **kwargs)
        monkeypatch.setattr(vehicle_raw, '_vehicle_consumer_rights', lambda _capsule: {'structured_fact_use': 'pending_review'})
        return row
    def checked(*args, **kwargs):
        dispatches.append(True)
        return fresh(*args, **kwargs)
    monkeypatch.setattr(embedding_api, 'reserve_request', reserve)
    monkeypatch.setattr(embedding_api, 'check_embedding_dispatch', checked)
    key = str(uuid4())
    response = post(ctx, '/v1/knowledge/hybrid-search', hybrid_body(), key)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['state'] == 'failed' and value['error_code'] == 'vehicle_structured_fact_use_not_allowed'
    assert value['usage'] == ZERO and value['result'] is None and value['reserved_tokens'] > 0
    with ctx.database.sessions() as db:
        usage = budget_usage(db)
        assert usage['requests'] == 1 and usage['accounted_tokens'] == 0 and usage['has_pending_request'] is False
        assert db.scalar(select(func.count()).select_from(EmbeddingCompletion)) == 1
    replay = post(ctx, '/v1/knowledge/hybrid-search', hybrid_body(), key)
    assert replay.status_code == 200 and replay.json() == value
    assert dispatches == [True] and ctx.provider.calls == []


@pytest.mark.parametrize('after', ['provider-same-code', 'receipt-then-policy-change'])
def test_dispatched_error_or_postcall_local_refusal_never_invents_zero_usage(knowledge_ctx, allowed_local, monkeypatch, after):
    ctx = knowledge_ctx
    index_documents(ctx)
    cache_documents(ctx)
    class Dispatched:
        calls = []
        async def embed(self, config, inputs):
            self.calls.append(list(inputs))
            if after == 'provider-same-code':
                raise EmbeddingError('vehicle_structured_fact_use_not_allowed')
            monkeypatch.setattr(vehicle_raw, '_vehicle_consumer_rights', lambda _capsule: {'structured_fact_use': 'pending_review'})
            return {'vectors': [[1.0, 0.0, 0.0]],
                    'usage': {'input_tokens': 7, 'output_tokens': 0, 'total_tokens': 7}}
    adapter = Dispatched()
    ctx.app.state.embedding_adapter = adapter
    response = post(ctx, '/v1/knowledge/hybrid-search', hybrid_body())
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['state'] == 'failed' and adapter.calls == [[QUERY]]
    if after == 'provider-same-code':
        assert value['usage'] is None
    else:
        assert value['error_code'] == 'vehicle_structured_fact_use_not_allowed'
        assert value['usage'] == {'input_tokens': 7, 'output_tokens': 0, 'total_tokens': 7}
    with ctx.database.sessions() as db:
        usage = budget_usage(db)
        assert usage['requests'] == 1 and usage['has_pending_request'] is False
        assert usage['accounted_tokens'] == (value['reserved_tokens'] if after == 'provider-same-code' else 7)


def test_local_refusal_completion_failure_keeps_durable_pending_and_reservation(knowledge_ctx, allowed_local, monkeypatch):
    ctx = knowledge_ctx
    index_documents(ctx)
    cache_documents(ctx)
    actual = embedding_api.reserve_request
    def reserve(*args, **kwargs):
        row = actual(*args, **kwargs)
        monkeypatch.setattr(vehicle_raw, '_vehicle_consumer_rights', lambda _capsule: {'structured_fact_use': 'pending_review'})
        return row
    def cannot_complete(*_args, **_kwargs):
        raise RuntimeError('private_r92_completion_unavailable')
    monkeypatch.setattr(embedding_api, 'reserve_request', reserve)
    monkeypatch.setattr(embedding_api, 'complete', cannot_complete)
    with pytest.raises(RuntimeError, match='private_r92_completion_unavailable'):
        post(ctx, '/v1/knowledge/hybrid-search', hybrid_body())
    with ctx.database.sessions() as db:
        row = db.scalar(select(EmbeddingRequest))
        assert row is not None and row.reserved_tokens > 0
        assert db.get(EmbeddingCompletion, row.id) is None
        usage = budget_usage(db)
        assert usage['has_pending_request'] is True and usage['requests'] == 1
        assert usage['accounted_tokens'] == row.reserved_tokens
    assert ctx.provider.calls == []
