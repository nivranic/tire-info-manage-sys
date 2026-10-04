"""Synthetic model output tests are contract evidence, not live OpenAI acceptance."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from tire_api.ai_analysis import grounded_answer
from tire_api.ai_evidence import PreparePack
from tire_api.ai_gateway import (GatewayError, OpenAIConfig, OpenAIResponsesAdapter,
                                configured_model, extract_response, request_body, safe_usage)
from tire_api.ai_models import AICompletion, AIEvidencePack, AIRequest
from tire_api.db import FactVersion, Snapshot, utcnow
from tire_api.main import create_app
from test_core import FixtureRegistry, QUERY, live


class ModelFixture:
    def __init__(self):
        self.calls = []
        self.mutation = None
        self.failure = None

    async def generate(self, config, body):
        self.calls.append((config, body))
        if self.failure:
            raise self.failure
        context = json.loads(body['input'][1]['content'])['untrusted_evidence_pack']
        fact = context['facts'][0]
        output = {'claims': [{'type': 'fact', 'text': '', 'fact_ids': [fact['id']],
                              'evidence_ids': [fact['evidence_id']]}], 'uncertainty': 'Synthetic model fixture, not live AI.'}
        if self.mutation:
            self.mutation(output)
        return {'text': json.dumps(output), 'error': None, 'usage': {'input_tokens': 500, 'output_tokens': 100, 'total_tokens': 600},
                'provider_response_id': 'resp_synthetic'}


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('TI_AI_ENABLED', '1')
    monkeypatch.setenv('TI_OPENAI_MODEL', 'synthetic-model')
    monkeypatch.setenv('TI_OPENAI_API_KEY', 'synthetic-key-never-live')
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '1')  # The synthetic registry has no official-source authority.
    monkeypatch.setenv('TI_AI_DAILY_TOKEN_LIMIT', '100000')
    monkeypatch.setenv('TI_AI_DAILY_REQUEST_LIMIT', '20')
    registry = FixtureRegistry()
    app = create_app('sqlite://', registry)
    model = ModelFixture()
    app.state.ai_adapter = model
    with TestClient(app) as client:
        from admin_support import register_admin
        register_admin(client)  # lifecycle-events 等全局写端点已加管理守卫
        yield client, registry, model, app.state.database


def count(database, model):
    with database.sessions() as db:
        return db.scalar(select(func.count()).select_from(model))


def historical_pack(client):
    result = live(client).json()
    response = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [
        {'kind': 'tire', 'snapshot_id': result['provenance'][0]['snapshot_id'], 'variant_id': result['variants'][0]['id']} ]})
    assert response.status_code == 200, response.text
    return response.json()['pack']


def analyze(client, pack, key=None, question='解释所选历史参数', **changes):
    return client.post('/v1/ai/analyses', headers={'Idempotency-Key': key or str(uuid4())}, json={
        'pack_id': pack['id'], 'question': question, 'allow_external_processing': True, **changes})


def test_grounded_fact_rendering_idempotency_audit_and_no_fact_mutation(setup):
    client, _, model, database = setup
    pack = historical_pack(client)
    baseline = (count(database, Snapshot), count(database, FactVersion))
    key = str(uuid4())
    response = analyze(client, pack, key)
    assert response.status_code == 200, response.text
    run = response.json()
    assert run['state'] == 'completed'
    assert run['answer']['claims'][0]['text'] == pack['facts'][0]['text']
    assert run['answer']['source_state'] == 'snapshot'
    assert run['usage']['total_tokens'] == 600
    assert analyze(client, pack, key).json()['id'] == run['id']
    assert len(model.calls) == 1
    assert analyze(client, pack, key, question='另一个不同的问题').status_code == 409
    assert len(model.calls) == 1
    assert (count(database, Snapshot), count(database, FactVersion)) == baseline
    with database.sessions() as db:
        row = db.get(AICompletion, run['id'])
        row.state = 'overwrite'
        with pytest.raises(ValueError): db.commit()
    body = model.calls[0][1]
    assert body['store'] is False and body['tools'] == [] and body['stream'] is False
    assert 'synthetic-key-never-live' not in json.dumps(body)
    assert client.get('/v1/ai/status').json()['budget']['accounted_tokens'] == 600
    assert client.get('/v1/ai/analyses?mode=history').json()['items'][0]['answer'] is None


@pytest.mark.parametrize('mutation', ['unknown_fact', 'unknown_evidence', 'free_fact', 'source_state', 'empty'])
def test_bad_model_answers_are_rejected_without_raw_output(setup, mutation):
    client, _, model, database = setup
    pack = historical_pack(client)
    def change(output):
        if mutation == 'unknown_fact': output['claims'][0]['fact_ids'] = ['not_in_pack']
        if mutation == 'unknown_evidence': output['claims'][0]['evidence_ids'] = ['invented_source']
        if mutation == 'free_fact': output['claims'][0]['text'] = 'Invented tire fact, not allowed'
        if mutation == 'source_state': output['source_state'] = 'live'
        if mutation == 'empty': output.update(claims=[], uncertainty='')
    model.mutation = change
    result = analyze(client, pack).json()
    assert result['state'] == 'failed' and result['answer'] is None
    assert result['error_code'] == 'ai_grounding_validation_failed'
    assert count(database, AICompletion) == 1


def test_provider_failure_does_not_fetch_or_change_data_scope_and_sanitizes_errors(setup):
    client, registry, model, database = setup
    pack = historical_pack(client)
    calls = len(registry.calls)
    model.failure = GatewayError('secret-canary-must-not-escape')
    result = analyze(client, pack).json()
    assert result['error_code'] == 'ai_provider_failed' and result['answer'] is None
    assert 'secret-canary' not in json.dumps(result)
    assert len(registry.calls) == calls and count(database, AIEvidencePack) == 1
    assert client.get('/v1/ai/status').json()['budget']['accounted_tokens'] == result['reserved_tokens']


def test_explicit_external_consent_configuration_privacy_and_budget_fail_before_call(setup, monkeypatch):
    client, _, model, database = setup
    pack = historical_pack(client)
    assert analyze(client, pack, allow_external_processing=False).status_code == 422
    monkeypatch.setenv('TI_AI_ENABLED', '0')
    assert analyze(client, pack).status_code == 503
    monkeypatch.setenv('TI_AI_ENABLED', '1')
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '0')
    assert analyze(client, pack).status_code == 403
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '1')
    monkeypatch.setenv('TI_AI_DAILY_TOKEN_LIMIT', '1000')
    assert analyze(client, pack).status_code == 429
    assert not model.calls and count(database, AIRequest) == 0


def test_current_question_cannot_silently_use_explicit_history_and_expired_pack_is_rejected(setup, monkeypatch):
    client, _, model, database = setup
    pack = historical_pack(client)
    assert analyze(client, pack, question='现在这条轮胎还有没有静音技术？').status_code == 409
    from tire_api import ai_analysis
    monkeypatch.setattr(ai_analysis, 'utcnow', lambda: utcnow() + timedelta(hours=1))
    assert analyze(client, pack).status_code == 409
    assert not model.calls


def test_current_evidence_obeys_live_failure_and_one_use_data_consent(setup):
    client, registry, model, database = setup
    original = live(client).json()
    registry.result = {'status': 'unavailable', 'reason': 'synthetic_outage'}
    request = {'mode': 'current', 'source_id': 'fixture', 'query': QUERY['query'],
               'variant_ids': [original['variants'][0]['id']]}
    failed = client.post('/v1/ai/evidence-packs', json=request).json()
    assert failed['pack'] is None and failed['query_result']['variants'] == []
    assert count(database, AIEvidencePack) == 0 and not model.calls
    consent = client.post('/v1/fallback-consents', json={'query_id': failed['query_result']['query_id'], 'decision': 'allow', 'scope': 'once'}).json()
    response = client.post('/v1/ai/evidence-packs', json={**request, 'consent_id': consent['id']})
    assert response.status_code == 200, response.text
    pack = response.json()['pack']
    assert pack['data_state'] == 'local_snapshot' and pack['consent_id'] == consent['id']
    assert analyze(client, pack, question='现在有什么证据？').json()['answer']['source_state'] == 'snapshot'
    assert client.post('/v1/ai/evidence-packs', json={**request, 'consent_id': consent['id']}).status_code == 409


def test_pack_and_analysis_are_session_bound(setup):
    client, _, _, _ = setup
    pack = historical_pack(client)
    run = analyze(client, pack).json()
    client.cookies.clear()
    assert client.get(f'/v1/ai/evidence-packs/{pack["id"]}?mode=history').status_code == 404
    assert client.get(f'/v1/ai/analyses/{run["id"]}?mode=history').status_code == 404
    assert analyze(client, pack).status_code == 404
    assert client.get('/v1/ai/analyses?mode=history').json()['items'] == []


def test_model_configuration_is_explicit_and_does_not_use_ambient_key(monkeypatch):
    monkeypatch.setenv('TI_AI_ENABLED', '1')
    monkeypatch.setenv('TI_OPENAI_MODEL', 'synthetic-model')
    monkeypatch.delenv('TI_OPENAI_API_KEY', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'ambient-key-not-authorized')
    with pytest.raises(GatewayError, match='ai_configuration_required'): configured_model()
    monkeypatch.setenv('TI_OPENAI_API_KEY', 'private-canary')
    config = configured_model()
    assert 'private-canary' not in repr(config)
    body, reservation = request_body(config, '历史参数', {'facts': []})
    assert body['text']['format']['strict'] is True and reservation > config.max_output_tokens


def response(text='{}', **changes):
    return {'id': 'resp_fixture', 'status': 'completed', 'usage': {'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30},
            'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': text}]}], **changes}


def test_native_response_incomplete_refusal_and_usage_handling():
    assert extract_response(response())['text'] == '{}'
    assert extract_response(response(status='incomplete'))['error'] == 'ai_response_incomplete'
    refused = response()
    refused['output'][0]['content'] = [{'type': 'refusal', 'refusal': 'not exposed'}]
    assert extract_response(refused)['error'] == 'ai_refused'
    assert extract_response(response(output=[{'type': 'function_call'}]))['error'] == 'ai_response_invalid'
    assert safe_usage({'input_tokens': True, 'output_tokens': 2, 'total_tokens': 3}) is None
    assert safe_usage({'input_tokens': 1, 'output_tokens': 2, 'total_tokens': 4}) is None


def test_cross_test_inferences_rejected_but_separate_fact_quotes_allowed(setup):
    from test_test_events import create
    client, _, _, database = setup
    one, two = create(client), create(client)
    result = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [
        {'kind': 'test_event', 'event_id': e['id'], 'event_revision': 1} for e in (one, two)]})
    assert result.status_code == 200, result.text
    pack = result.json()['pack']
    ids = [next(f['id'] for f in pack['facts'] if f['evidence_id'] == e['id']) for e in pack['evidence']]
    value = {'claims': [{'type': 'inference', 'text': 'Rank both events together', 'fact_ids': ids,
                         'evidence_ids': [e['id'] for e in pack['evidence']]}], 'uncertainty': ''}
    with database.sessions() as db:
        saved = db.get(AIEvidencePack, pack['id'])
        with pytest.raises(ValueError, match='cross_event'): grounded_answer(json.dumps(value), saved)


def test_history_rejects_unaccepted_or_wrong_identity_references(setup):
    client, _, _, _ = setup
    row = live(client).json()
    assert client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [
        {'kind': 'tire', 'snapshot_id': row['provenance'][0]['snapshot_id'], 'variant_id': 'not-in-snapshot'}]}).status_code == 404
    with pytest.raises(ValidationError):
        PreparePack.model_validate({'mode': 'history', 'references': [{'kind': 'document', 'snapshot_id': 'fake'}]})


def test_live_and_304_packs_preserve_actual_verification_state(setup):
    client, registry, model, _ = setup
    payload = {'mode': 'current', 'source_id': 'fixture', 'query': QUERY['query']}
    first = client.post('/v1/ai/evidence-packs', json=payload).json()['pack']
    assert first['data_state'] == 'live' and first['evidence'][0]['verified_at']
    registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product'}
    second = client.post('/v1/ai/evidence-packs', json=payload).json()['pack']
    assert second['data_state'] == 'live_verified_304'
    assert second['evidence'][0]['snapshot_id'] == first['evidence'][0]['snapshot_id']
    assert not model.calls and len(registry.calls) == 2


def test_withdrawal_and_changed_test_event_block_frozen_pack(setup):
    from test_lifecycle import request_for
    from test_test_events import create, PAYLOAD
    client, _, model, _ = setup
    pack = historical_pack(client)
    result = live(client).json()
    assert client.post(f'/v1/tire-variants/{result["variants"][0]["id"]}/lifecycle-events', json=request_for(result)).status_code == 201
    assert analyze(client, pack).status_code == 409
    event = create(client)
    pack = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [
        {'kind': 'test_event', 'event_id': event['id'], 'event_revision': 1}]}).json()['pack']
    changed = deepcopy(PAYLOAD)
    changed['event']['conditions'] += ' Revised fixture conditions.'
    assert client.put(f'/v1/test-events/{event["id"]}', json={**changed, 'expected_revision': 1}).status_code == 200
    assert analyze(client, pack).status_code == 409
    assert not model.calls


def test_unknown_completion_keeps_reservation_and_does_not_retry(setup, monkeypatch):
    from tire_api import ai_analysis
    from tire_api.domain import digest
    client, _, model, database = setup
    pack = historical_pack(client)
    key = str(uuid4())
    payload = {'pack_id': pack['id'], 'question': '解释所选历史参数', 'allow_external_processing': True}
    with database.sessions() as db:
        saved = db.get(AIEvidencePack, pack['id'])
        row = AIRequest(actor_session_id=saved.actor_session_id, idempotency_key=key, pack_id=pack['id'],
            question=payload['question'], request_hash=digest(payload), provider='openai_responses', model='synthetic-model',
            reserved_tokens=4500, request_contract={'prompt_version': 'fixture'})
        db.add(row); db.commit()
    assert analyze(client, pack, key).status_code == 202
    assert analyze(client, pack).status_code == 429
    monkeypatch.setattr(ai_analysis, 'utcnow', lambda: utcnow() + timedelta(seconds=130))
    result = analyze(client, pack, key).json()
    assert result['state'] == 'outcome_unknown' and result['usage'] is None
    assert client.get('/v1/ai/status').json()['budget']['accounted_tokens'] == 4500
    assert not model.calls and count(database, AICompletion) == 0


def verify_ai_persistence(url):
    """Shared SQLite/PostgreSQL concurrency/restart acceptance. Only synthetic providers."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    registry = FixtureRegistry()
    app = create_app(url, registry)
    entered, release = Event(), Event()
    class SlowFixture(ModelFixture):
        async def generate(self, config, body):
            entered.set()
            assert await asyncio.to_thread(release.wait, 10)
            return await super().generate(config, body)
    model = SlowFixture(); app.state.ai_adapter = model
    with TestClient(app) as client:
        pack = historical_pack(client)
        key = str(uuid4())
        with ThreadPoolExecutor(2) as pool:
            future = pool.submit(analyze, client, pack, key)
            try:
                assert entered.wait(10)
                duplicate = analyze(client, pack, key)
                assert duplicate.status_code == 202 and duplicate.json()['state'] == 'pending'
            finally:
                release.set()
            first = future.result(timeout=15)
        assert first.status_code == 200 and first.json()['state'] == 'completed'
        assert len(model.calls) == 1
        cookies = dict(client.cookies)
        run = first.json()
    restart = create_app(url, registry)
    model2 = ModelFixture(); restart.state.ai_adapter = model2
    with TestClient(restart) as client:
        client.cookies.update(cookies)
        assert analyze(client, pack, key).json() == run
        assert client.get(f'/v1/ai/analyses/{run["id"]}?mode=history').json()['pack']['fingerprint'] == pack['fingerprint']
        assert not model2.calls


def test_file_database_concurrency_restart(setup, tmp_path):
    verify_ai_persistence('sqlite:///' + (tmp_path / 'ai.db').as_posix())


@pytest.mark.parametrize('bad', [None, [], {'text': '{}', 'usage': {'total_tokens': -1}}, {'error': 'secret-canary', 'usage': None}])
def test_malformed_adapter_receipts_fail_closed(setup, bad):
    client, _, model, database = setup
    pack = historical_pack(client)
    async def invalid(*args): return bad
    model.generate = invalid
    result = analyze(client, pack).json()
    assert result['state'] == 'failed' and result['answer'] is None and result['usage'] is None
    assert 'secret-canary' not in json.dumps(result)
    assert count(database, AICompletion) == 1


@pytest.mark.parametrize('case', ['valid', 'redirect', 'mime', 'length', 'stream_size', 'timeout', 'invalid_json'])
def test_native_http_transport_contract_and_limits(monkeypatch, case):
    from tire_api import ai_gateway as gateway
    captured = {}
    class Context:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
    class Content:
        async def iter_chunked(self, size):
            if case == 'timeout': raise TimeoutError()
            yield b'x' * (gateway.MAX_RESPONSE_BYTES + 1) if case == 'stream_size' else b'not-json' if case == 'invalid_json' else json.dumps(response()).encode()
    class Response(Context):
        status = 302 if case == 'redirect' else 200
        headers = {'Content-Type': 'text/html' if case == 'mime' else 'application/json; charset=utf-8'}
        content_length = gateway.MAX_RESPONSE_BYTES + 1 if case == 'length' else None
        content = Content()
    class Client(Context):
        def __init__(self, **kwargs): captured['client'] = kwargs
        def post(self, endpoint, **kwargs):
            captured['endpoint'], captured['request'] = endpoint, kwargs
            return Response()
    monkeypatch.setattr(gateway.aiohttp, 'ClientSession', Client)
    monkeypatch.setattr(gateway.aiohttp, 'TCPConnector', lambda **kwargs: captured.setdefault('connector', kwargs))
    async def invoke(): return await OpenAIResponsesAdapter().generate(OpenAIConfig(model='fixture', api_key='private-canary'), {'store': False})
    if case == 'valid': assert asyncio.run(invoke())['text'] == '{}'
    else:
        code = {'redirect': 'ai_provider_http_error', 'mime': 'ai_response_invalid', 'length': 'ai_response_too_large',
                'stream_size': 'ai_response_too_large', 'timeout': 'ai_provider_timeout', 'invalid_json': 'ai_response_invalid'}[case]
        with pytest.raises(GatewayError, match=code): asyncio.run(invoke())
    assert captured['endpoint'] == 'https://api.openai.com/v1/responses'
    assert captured['request']['allow_redirects'] is False
    assert captured['request']['headers']['Authorization'] == 'Bearer private-canary'
    assert captured['client']['trust_env'] is False and captured['client']['timeout'].total == 60
    assert captured['connector']['use_dns_cache'] is False


def test_history_pack_keeps_unselected_conflict_boundary_without_external_values(setup, monkeypatch):
    from test_core import VARIANT, success
    client, registry, model, _ = setup
    known = deepcopy(VARIANT)
    known['facts']['product_code_type'] = 'MSPN'
    registry.result = success(variants=[known])
    base = live(client).json()
    other = deepcopy(known)
    other['facts']['utqg_treadwear'] = 999321
    other['facts']['private_canary'] = 'unselected-secret-content'
    registry.result = success(body='unselected-private-source', variants=[other])
    assert live(client, source='fixture-two').status_code == 200
    original_sources = registry.sources
    registry.sources = lambda: [{**row, 'source_class': 'manufacturer_official' if row['id'] == 'fixture' else 'unclassified'} for row in original_sources()]
    result = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [
        {'kind': 'tire', 'snapshot_id': base['provenance'][0]['snapshot_id'], 'variant_id': base['variants'][0]['id']}]})
    pack = result.json()['pack']
    assert pack['privacy_class'] == 'private'
    assert any(item['scope'] == 'unselected_formal_evidence' for item in pack['conflicts'])
    assert '999321' not in json.dumps(pack) and 'unselected-secret-content' not in json.dumps(pack)
    assert 'fixture-two' not in json.dumps(pack)
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '0')
    assert analyze(client, pack).status_code == 403 and not model.calls
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '1')
    run = analyze(client, pack).json()
    assert run['answer']['conflicts'] == pack['conflicts']
    assert '999321' not in json.dumps(model.calls[0][1])


@pytest.mark.parametrize('field', ['technology_features', 'gtin', 'eprel_id'])
def test_additional_identity_fields_keep_separate_variants_not_false_conflicts(setup, field):
    from test_core import VARIANT, success
    client, registry, _, _ = setup
    selected = deepcopy(VARIANT)
    selected['facts'][field] = ['Selected'] if field == 'technology_features' else '10000001'
    registry.result = success(variants=[selected])
    first = live(client).json()
    other = deepcopy(selected)
    other['facts'][field] = ['UNSELECTED_CONFLICT_999321'] if field == 'technology_features' else '999321'
    registry.result = success(body='private-outside-field', variants=[other])
    second = live(client, source='fixture-two').json()
    assert first['variants'][0]['id'] != second['variants'][0]['id']
    result = client.post('/v1/knowledge/search', json={'mode': 'history', 'filters': {'model': 'Fixture Tire'}}).json()
    assert {item['reference']['variant_id'] for item in result['items']} == {first['variants'][0]['id'], second['variants'][0]['id']}
    assert all(not item['conflicts'] for item in result['items'])
    pack = client.post('/v1/ai/evidence-packs', json={'mode': 'history', 'references': [
        {'kind': 'tire', 'snapshot_id': first['provenance'][0]['snapshot_id'], 'variant_id': first['variants'][0]['id']}]}).json()['pack']
    assert pack['conflicts'] == []
    assert '999321' not in json.dumps(pack)
