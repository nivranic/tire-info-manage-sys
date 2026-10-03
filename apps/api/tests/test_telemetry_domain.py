"""Real local OTel SDK over private synthetic domain/transport/provider calls."""
import asyncio
from datetime import timedelta
from io import StringIO
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import event, select

from tire_api.ai_execution import execute_response
from tire_api.ai_models import AIEvidencePack, AICompletion, AIRequest
from tire_api.adapters.transport import SafeHttpClient, SourceAccessError
from tire_api.db import Database, UserSession, uid, utcnow
from tire_api.domain import ConsentRequest, LiveQueryRequest, digest
from tire_api.embedding_api import call_embedding, observed_embedding
from tire_api.embedding_gateway import EmbeddingConfig
from tire_api.embedding_models import EmbeddingCompletion, EmbeddingRequest
from tire_api.embedding_service import complete
from tire_api.recall_discovery import RecallDiscoveryService, RecallSearchRequest
from tire_api.recall_models import RecallLiveRequest
from tire_api.recalls import RecallService
from tire_api.service import QueryService
from tire_api.telemetry import TelemetryRuntime, observe
from tire_api.vehicles import VehicleLiveRequest, VehicleService
from test_adapters import FakeResponse, FakeSession
from test_core import FixtureRegistry, QUERY
from test_embeddings import SyntheticEmbeddings
from test_recall_discovery import SearchFixture
from test_recalls import RecallFixture, CAMPAIGN
from test_vehicles import FixtureVehicleAdapter

CANARY = 'private-payload-do-not-export'


@pytest.fixture
def private_domain(tmp_path, monkeypatch):
    monkeypatch.setenv('TIRE_DATABASE_URL', 'sqlite:///' + (tmp_path / 'private.sqlite').as_posix())
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + (tmp_path / 'private.sqlite').as_posix())
    monkeypatch.setenv('TI_OBJECT_STORE_BACKEND', 'filesystem')
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    monkeypatch.setenv('TI_PARSER_BUNDLE_ROOT', str(tmp_path / 'bundles'))
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '0')
    import aiohttp
    monkeypatch.setattr(aiohttp, 'ClientSession', lambda *_a, **_k: pytest.fail('real network forbidden'))
    database = Database('sqlite:///' + (tmp_path / 'private.sqlite').as_posix())
    database.initialize()
    session = UserSession(id='synthetic-session-' + uuid4().hex, expires_at=utcnow() + timedelta(days=1))
    with database.sessions() as db:
        db.add(session)
        db.commit()
    output = StringIO()
    runtime = TelemetryRuntime('tire-test', log_output=output)
    try:
        yield database, session.id, runtime, output
    finally:
        runtime.shutdown()
        database.close()


def assert_private(runtime, output, *extra):
    exported = json.dumps(runtime.finished_spans()) + runtime.metrics() + output.getvalue()
    for forbidden in (CANARY, *extra):
        assert forbidden not in exported
    for row in runtime.finished_spans():
        assert set(row['attributes']) <= {'operation', 'component', 'outcome', 'source', 'http_status'}
    return exported


def test_query_trace_preserves_304_and_explicit_one_use_fallback(private_domain):
    database, session, runtime, output = private_domain
    registry = FixtureRegistry()
    with runtime.scope(), observe('worker.job', component='worker'):
        with database.sessions() as db:
            service = QueryService(db, registry)
            first = asyncio.run(service.execute('fixture', LiveQueryRequest(**QUERY), session))
            assert first['data_state'] == 'live' and first['variants']
            registry.result = {'status': 'not_modified', 'url': first['provenance'][0]['source_url'],
                               'parser_version': 'fixture@1', 'etag': '"fixture-etag"'}
            checked = asyncio.run(service.execute('fixture', LiveQueryRequest(**QUERY), session))
            assert checked['data_state'] == 'live_verified_304'
            registry.result = {'status': 'unavailable', 'reason': 'synthetic_outage'}
            failed = asyncio.run(service.execute('fixture', LiveQueryRequest(**QUERY), session))
            assert failed['data_state'] == 'consent_required' and not failed['variants'] and not failed['provenance']
            denied = asyncio.run(service.execute('fixture', LiveQueryRequest(**{**QUERY, 'fallback_policy': 'never'}), session))
            assert denied['data_state'] == 'source_unavailable' and not denied['variants']
            grant = service.create_consent(ConsentRequest(query_id=failed['query_id'], decision='allow', scope='once'), session)
            before = len(registry.calls)
            offline = asyncio.run(service.execute('fixture', LiveQueryRequest(**{**QUERY, 'consent_id': grant['id']}), session))
            assert offline['data_state'] == 'local_snapshot' and offline['variants']
            assert len(registry.calls) == before
            with pytest.raises(HTTPException) as expired:
                asyncio.run(service.execute('fixture', LiveQueryRequest(**{**QUERY, 'consent_id': grant['id']}), session))
            assert expired.value.status_code == 409
    rows = runtime.finished_spans()
    parent = next(row for row in rows if row['name'] == 'worker.job')
    queries = [row for row in rows if row['name'] == 'source.query']
    assert [row['attributes']['outcome'] for row in queries] == [
        'live', 'live_verified_304', 'consent_required', 'source_unavailable', 'local_snapshot', 'error']
    assert all(row['trace_id'] == parent['trace_id'] and row['parent_span_id'] == parent['span_id'] for row in queries)
    assert all(row['attributes']['source'] == 'unknown' for row in queries)
    assert any(row['name'] == 'db.ingestion_lock' and row['parent_span_id'] in {q['span_id'] for q in queries} for row in rows)
    log_rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert all(row['trace_id'] == parent['trace_id'] for row in log_rows)
    assert_private(runtime, output, session, first['query_id'], first['provenance'][0]['snapshot_id'])


@pytest.mark.parametrize('kind,source', [('vehicle', 'xiaomi-cn-vehicles'), ('recall', 'nhtsa-us-recalls'),
                                      ('discovery', 'nhtsa-us-recalls')])
def test_other_domains_keep_live_then_never_failure_without_evidence(private_domain, kind, source):
    database, session, runtime, output = private_domain
    with database.sessions() as db, runtime.scope():
        if kind == 'vehicle':
            adapter = FixtureVehicleAdapter()
            service = VehicleService(db, adapter)
            vehicle_id = adapter.candidates()[0]['id']
            run = lambda: asyncio.run(service.execute(vehicle_id, VehicleLiveRequest(fallback_policy='never'), session))
            set_offline = lambda: setattr(adapter, 'result', {'status': 'unavailable', 'reason': 'synthetic_outage'})
            values = 'fitments'
        elif kind == 'recall':
            adapter = RecallFixture()
            service = RecallService(db, adapter)
            run = lambda: asyncio.run(service.execute(RecallLiveRequest(query={'campaign_number': CAMPAIGN}, fallback_policy='never'), session))
            set_offline = lambda: setattr(adapter, 'offline', True)
            values = 'records'
        else:
            adapter = SearchFixture()
            service = RecallDiscoveryService(db, adapter)
            run = lambda: asyncio.run(service.execute(RecallSearchRequest(query={'search': CANARY}, fallback_policy='never'), session))
            set_offline = lambda: setattr(adapter, 'offline', True)
            values = 'products'
        first = run()
        assert first['data_state'] == 'live' and first[values]
        set_offline()
        failed = run()
        assert failed['data_state'] == 'source_unavailable' and not failed[values]
    rows = [row for row in runtime.finished_spans() if row['name'] == 'source.query']
    assert [row['attributes']['outcome'] for row in rows] == ['live', 'source_unavailable']
    assert all(row['attributes']['source'] == source for row in rows)
    assert_private(runtime, output, session)


def test_unknown_source_exception_preserved_and_no_runtime_is_noop(private_domain):
    database, session, runtime, output = private_domain
    with database.sessions() as db:
        service = QueryService(db, FixtureRegistry())
        with runtime.scope(), pytest.raises(HTTPException) as caught:
            asyncio.run(service.execute(CANARY, LiveQueryRequest(**QUERY), session))
        assert caught.value.status_code == 404
        assert runtime.finished_spans()[0]['attributes']['outcome'] == 'error'
        assert runtime.finished_spans()[0]['attributes']['source'] == 'unknown'
        before = runtime.finished_spans()
        assert asyncio.run(service.execute('fixture', LiveQueryRequest(**QUERY), session))['data_state'] == 'live'
        assert runtime.finished_spans() == before
    assert_private(runtime, output, session)


@pytest.mark.parametrize('status,kwargs,outcome,exception', [
    (200, {}, 'success', None), (304, {'headers': {'If-None-Match': CANARY}}, 'not_modified', None),
    (429, {}, 'error', 'upstream_http_429'), (304, {}, 'error', 'unexpected_304'),
])
def test_http_span_tracks_status_preserves_errors_and_never_exports_payload(private_domain, status, kwargs, outcome, exception):
    _, session, runtime, output = private_domain
    client = SafeHttpClient(frozenset({'www.michelinman.com'}))
    client.session = FakeSession([FakeResponse(status, chunks=[CANARY.encode()])])
    with runtime.scope(), observe('source.query', component='crawler', source='michelin-us'):
        invocation = client.get('https://www.michelinman.com/private-product?key=' + CANARY, **kwargs)
        if exception:
            with pytest.raises(SourceAccessError, match=exception):
                asyncio.run(invocation)
        else:
            result = asyncio.run(invocation)
            assert result.status == status
            if status == 200:
                assert result.body == CANARY
    rows = runtime.finished_spans()
    child, parent = rows
    assert child['name'] == 'source.http' and child['parent_span_id'] == parent['span_id']
    assert child['trace_id'] == parent['trace_id']
    assert child['attributes'] == {'operation': 'source.http', 'component': 'crawler',
                                   'source': 'michelin-us', 'outcome': outcome, 'http_status': status}
    assert_private(runtime, output, session, 'private-product', 'www.michelinman.com')


def response_request(db, session):
    pack = AIEvidencePack(id=uid(), actor_session_id=session, mode='history', data_state='local_snapshot',
        privacy_class='private', payload={'private': CANARY}, fingerprint=digest(CANARY), expires_at=utcnow() + timedelta(minutes=5))
    db.add(pack)
    db.flush()
    request = AIRequest(id=uid(), actor_session_id=session, idempotency_key=str(uuid4()), request_hash=digest(CANARY),
        pack_id=pack.id, question=CANARY, provider='openai_responses', model=CANARY, request_contract={}, reserved_tokens=20)
    db.add(request)
    db.commit()
    return request


def test_http_cancellation_is_preserved_without_error_text(private_domain):
    _, session, runtime, output = private_domain
    failure = asyncio.CancelledError(CANARY)
    class CancelledResponse:
        async def __aenter__(self):
            raise failure
        async def __aexit__(self, *_args):
            pass
    client = SafeHttpClient(frozenset({'www.michelinman.com'}))
    client.session = FakeSession([CancelledResponse()])
    with runtime.scope(), pytest.raises(asyncio.CancelledError) as caught:
        asyncio.run(client.get('https://www.michelinman.com/' + CANARY))
    assert caught.value is failure
    assert runtime.finished_spans()[0]['attributes']['outcome'] == 'cancelled'
    assert_private(runtime, output, session)


def test_unapproved_transport_host_cannot_become_a_source_label(private_domain):
    _, session, runtime, output = private_domain
    client = SafeHttpClient(frozenset({'www.michelinman.com'}))
    client.session = FakeSession([])
    with runtime.scope(), pytest.raises(SourceAccessError, match='url_not_allowed'):
        asyncio.run(client.get('https://' + CANARY + '.invalid/private'))
    assert client.session.calls == 0
    assert runtime.finished_spans()[0]['attributes']['source'] == 'unknown'
    assert_private(runtime, output, session)


@pytest.mark.parametrize('failure', [None, 'provider', 'validation', 'commit'])
def test_response_observation_covers_validation_and_commit(private_domain, failure):
    database, session, runtime, output = private_domain
    class Provider:
        async def generate(self, config, body):
            assert body == {'private': CANARY}
            if failure == 'provider':
                raise RuntimeError(CANARY)
            return {'text': CANARY, 'usage': {'input_tokens': 7, 'output_tokens': 3, 'total_tokens': 10},
                    'provider_response_id': 'synthetic_response'}
    def validate(text):
        if failure == 'validation':
            raise ValueError(CANARY)
        return {'safe_business_answer': text}
    with database.sessions() as db:
        request = response_request(db, session)
        request_id = request.id
        if failure == 'commit':
            def reject_commit(_session):
                raise RuntimeError(CANARY)
            event.listen(db, 'before_commit', reject_commit)
        with runtime.scope(), observe('worker.job', component='worker'):
            if failure == 'commit':
                with pytest.raises(RuntimeError, match=CANARY):
                    execute_response(db, SimpleNamespace(state=SimpleNamespace(ai_adapter=Provider())), request,
                                     SimpleNamespace(), {'private': CANARY}, validate)
                db.rollback()
            else:
                result = execute_response(db, SimpleNamespace(state=SimpleNamespace(ai_adapter=Provider())), request,
                                          SimpleNamespace(), {'private': CANARY}, validate)
                assert result.state == ('failed' if failure else 'completed')
                assert db.get(AICompletion, request.id) is not None
    child, parent = [row for row in runtime.finished_spans() if row['name'] in {'ai.response', 'worker.job'}]
    assert child['parent_span_id'] == parent['span_id'] and child['trace_id'] == parent['trace_id']
    assert child['attributes']['outcome'] == ('error' if failure == 'commit' else 'failed' if failure else 'completed')
    metrics = runtime.metrics()
    assert ('kind="input_tokens"' in metrics) is (failure != 'provider')
    assert 'kind="cached_tokens"' not in metrics
    assert_private(runtime, output, session, request_id)


@pytest.mark.parametrize('failure', [None, 'provider', 'invalid', 'commit'])
def test_embedding_span_real_validated_fixture_and_commit_result(private_domain, failure):
    database, session, runtime, output = private_domain
    model = SyntheticEmbeddings()
    if failure == 'provider':
        model.error = RuntimeError(CANARY)
    if failure == 'invalid':
        model.invalid = True
    config = EmbeddingConfig(CANARY, 3, 'synthetic-never-live', 100000, 20, False)
    with database.sessions() as db:
        request = EmbeddingRequest(id=uid(), actor_session_id=session, idempotency_key=str(uuid4()), kind='index',
            request_hash=digest(CANARY), model_space=config.model_space, payload={'private': CANARY}, billable=True, reserved_tokens=20)
        db.add(request)
        db.commit()
        request_id = request.id
        if failure == 'commit':
            def reject_commit(_session):
                raise RuntimeError(CANARY)
            event.listen(db, 'before_commit', reject_commit)
        def execute():
            receipt, error = asyncio.run(call_embedding(SimpleNamespace(state=SimpleNamespace(embedding_adapter=model)), config, [CANARY]))
            return complete(db, request, result={'fixture': True}, usage=receipt['usage'] if receipt else None, error=error)
        with runtime.scope(), observe('worker.job', component='worker'):
            if failure == 'commit':
                with pytest.raises(RuntimeError, match=CANARY):
                    observed_embedding(execute)
                db.rollback()
            else:
                result = observed_embedding(execute)
                assert result['state'] == ('failed' if failure else 'completed')
                assert db.get(EmbeddingCompletion, request.id) is not None
    child, parent = [row for row in runtime.finished_spans() if row['name'] in {'ai.embedding', 'worker.job'}]
    assert child['trace_id'] == parent['trace_id'] and child['parent_span_id'] == parent['span_id']
    assert child['attributes']['outcome'] == ('error' if failure == 'commit' else 'failed' if failure else 'completed')
    assert len(model.calls) == 1
    assert ('kind="input_tokens"' in runtime.metrics()) is (failure in {None, 'commit'})
    assert_private(runtime, output, session, request_id)


def test_ai_consent_rejection_never_starts_embedding_operation(private_domain):
    from tire_api.embedding_api import external_consent
    _, session, runtime, output = private_domain
    with runtime.scope(), pytest.raises(HTTPException) as caught:
        external_consent(False)
    assert caught.value.status_code == 422
    assert runtime.finished_spans() == [] and 'tire_ai_tokens' not in runtime.metrics()
    assert_private(runtime, output, session)
