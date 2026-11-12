"""Native Gemini protocol and synthetic application checks."""
import asyncio
from copy import deepcopy
import importlib
from io import StringIO
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from tire_api.ai_gateway import (GatewayError, OUTPUT_SCHEMA, configured_adapter, configured_model,
                                 model_status, outbound_measurement, request_body)
from tire_api.ai_execution import _vehicle_dispatch_input
from tire_api.main import create_app
from test_ai import analyze, historical_pack
from test_ai_stream_api import accept, until
from test_core import FixtureRegistry
from candidate_ai_support import (configured_environment, grant_payload, ok, prepare,
                                  seed_candidate_ai, submit_payload)
from test_ai_pricing import case as pricing_case, plan, post_price, PRICE, workload
from test_telemetry import samples
from test_vehicle_binary_dispatch import (archive_device_pack, archive_pack, archive_reservation,
    assert_denied_completion, ForbidProvider, run_stream, run_sync)


def module():
    return importlib.import_module('tire_api.ai_gemini')


def configure(monkeypatch):
    monkeypatch.setenv('TI_AI_ENABLED', '1')
    monkeypatch.setenv('TI_AI_PROVIDER', 'gemini')
    monkeypatch.setenv('TI_GEMINI_MODEL', 'gemini-synthetic-fixture')
    monkeypatch.setenv('TI_GEMINI_API_KEY', 'synthetic-gemini-never-live')
    monkeypatch.setenv('TI_AI_ALLOW_PRIVATE', '1')
    monkeypatch.setenv('TI_AI_DAILY_TOKEN_LIMIT', '100000')
    monkeypatch.setenv('TI_AI_DAILY_REQUEST_LIMIT', '20')


def response_value(text='{"claims":[],"uncertainty":"fixture"}', finish='STOP'):
    return {'responseId': 'gemini_fixture_1', 'candidates': [{'index': 0,
        'content': {'role': 'model', 'parts': [{'text': text}]}, 'finishReason': finish}],
        'usageMetadata': {'promptTokenCount': 10, 'candidatesTokenCount': 3,
            'thoughtsTokenCount': 2, 'totalTokenCount': 15}}


def sse(*values):
    return ''.join('data: ' + json.dumps(value, ensure_ascii=False) + '\n\n' for value in values).encode()


def parse(*chunks):
    async def drive():
        seen = []

        async def on_text(value):
            seen.append(value)

        async def source():
            for chunk in chunks:
                yield chunk
        receipt = await module().parse_gemini_stream(source(), on_text)
        return receipt, seen
    return asyncio.run(drive())


def transport(monkeypatch, content_factory, *, status=200, content_type='application/json', length=None, error=None):
    calls = []
    state = {'sessions_closed': 0}

    class Response:
        def __init__(self, raw):
            self.status, self.headers = status, {'Content-Type': content_type}
            self.content_length = length
            self.content = SimpleNamespace(iter_chunked=self.chunks)
            self.raw = raw

        async def chunks(self, size):
            for offset in range(0, len(self.raw), size):
                yield self.raw[offset:offset + size]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class Session:
        def __init__(self, **kwargs):
            state['session_options'] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            state['sessions_closed'] += 1

        def post(self, url, **kwargs):
            calls.append({'url': url, **kwargs})
            if error:
                raise error
            return Response(content_factory(url, kwargs['json']))

    def connector(**kwargs):
        state['connector_options'] = kwargs
        return object()

    monkeypatch.setattr(module().aiohttp, 'TCPConnector', connector)
    monkeypatch.setattr(module().aiohttp, 'ClientSession', Session)
    return calls, state


def test_config_factory_status_and_independent_key(monkeypatch):
    configure(monkeypatch)
    config = configured_model()
    assert config.provider == 'gemini' and config.model == 'gemini-synthetic-fixture'
    assert config.endpoint == 'https://generativelanguage.googleapis.com/v1beta/models/gemini-synthetic-fixture:generateContent'
    assert config.allowed_host == 'generativelanguage.googleapis.com'
    assert isinstance(configured_adapter(), module().GeminiAdapter)
    assert model_status()['endpoint_host'] == config.allowed_host
    assert config.api_key not in repr(config) and config.api_key not in json.dumps(model_status())
    monkeypatch.delenv('TI_GEMINI_API_KEY')
    monkeypatch.setenv('GEMINI_API_KEY', 'ambient-never-use')
    monkeypatch.setenv('TI_OPENAI_API_KEY', 'other-provider-never-use')
    with pytest.raises(GatewayError, match='ai_configuration_required'):
        configured_model()


@pytest.mark.parametrize('name,value', [('TI_GEMINI_MODEL', ''), ('TI_GEMINI_API_KEY', ''),
    ('TI_GEMINI_MODEL', 'models/model'), ('TI_GEMINI_MODEL', '../model'),
    ('TI_GEMINI_MODEL', 'model:generateContent'), ('TI_GEMINI_MODEL', 'model?q=1'),
    ('TI_GEMINI_API_KEY', 'key\nvalue')])
def test_unsafe_or_missing_configuration_rejected(monkeypatch, name, value):
    configure(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(GatewayError):
        configured_model()


def test_request_body_schema_and_shared_accounting(monkeypatch):
    configure(monkeypatch)
    config = configured_model()
    evidence = {'facts': []}
    body, reserve = request_body(config, '历史问题', evidence)
    assert set(body) == {'systemInstruction', 'contents', 'generationConfig'}
    assert body['generationConfig'] == {'candidateCount': 1, 'maxOutputTokens': config.max_output_tokens,
        'responseMimeType': 'application/json', 'responseJsonSchema': OUTPUT_SCHEMA}
    assert json.loads(body['contents'][0]['parts'][0]['text']) == {
        'question': '历史问题', 'untrusted_evidence_pack': evidence}
    assert _vehicle_dispatch_input(body) == json.loads(body['contents'][0]['parts'][0]['text'])
    _, expected = outbound_measurement('历史问题', evidence, max_output_tokens=config.max_output_tokens)
    assert reserve == expected
    assert request_body(config, '历史问题', evidence, stream=True) == (body, reserve)
    schema = {'type': 'object', 'properties': {'decision': {'type': 'string'}}, 'required': ['decision']}
    custom, _ = request_body(config, '历史问题', evidence, output_schema=schema, system_prompt='custom')
    assert custom['generationConfig']['responseJsonSchema'] == schema
    assert custom['systemInstruction']['parts'] == [{'text': 'custom'}]


@pytest.mark.parametrize('mutation', ['two_users', 'two_parts', 'non_text', 'bad_json'])
def test_native_dispatch_envelope_rejects_ambiguous_input(monkeypatch, mutation):
    configure(monkeypatch)
    body, _ = request_body(configured_model(), '历史问题', {'facts': []})
    if mutation == 'two_users':
        body['contents'].append(deepcopy(body['contents'][0]))
    elif mutation == 'two_parts':
        body['contents'][0]['parts'].append({'text': '{}'})
    elif mutation == 'non_text':
        body['contents'][0]['parts'][0] = {'inlineData': {'data': 'AA=='}}
    else:
        body['contents'][0]['parts'][0]['text'] = '{'
    assert _vehicle_dispatch_input(body) is None


def test_response_usage_counts_reasoning_without_exposing_it():
    value = response_value()
    value['candidates'][0]['content']['parts'].insert(0, {'thought': True, 'text': 'PRIVATE_THOUGHT', 'thoughtSignature': 'PRIVATE_SIGNATURE'})
    result = module().extract_gemini_response(value)
    assert result['error'] is None and result['text'] == '{"claims":[],"uncertainty":"fixture"}'
    assert result['usage'] == {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}
    assert 'PRIVATE' not in json.dumps(result)
    value['usageMetadata']['totalTokenCount'] = 99
    assert module().extract_gemini_response(value)['usage'] is None


@pytest.mark.parametrize('reason,error', [('MAX_TOKENS', 'ai_response_incomplete'),
    ('CONTINUATION', 'ai_response_incomplete'), ('SAFETY', 'ai_refused'), ('RECITATION', 'ai_refused'),
    ('BLOCKLIST', 'ai_refused'), ('UNEXPECTED_TOOL_CALL', 'ai_response_invalid'),
    ('OTHER', 'ai_response_invalid'), ('', 'ai_response_invalid')])
def test_finish_reason_mapping(reason, error):
    assert module().extract_gemini_response(response_value(finish=reason))['error'] == error


@pytest.mark.parametrize('mutation', ['multiple', 'index', 'role', 'function', 'empty', 'invalid_part'])
def test_invalid_response_is_rejected(mutation):
    value = response_value()
    candidate = value['candidates'][0]
    if mutation == 'multiple':
        value['candidates'].append(deepcopy(candidate))
    elif mutation == 'index':
        candidate['index'] = True
    elif mutation == 'role':
        candidate['content']['role'] = 'user'
    elif mutation == 'function':
        candidate['content']['parts'] = [{'functionCall': {'name': 'bad'}}]
    elif mutation == 'empty':
        candidate['content']['parts'] = []
    else:
        candidate['content']['parts'] = ['bad']
    assert module().extract_gemini_response(value)['error'] == 'ai_response_invalid'


def test_prompt_block_is_a_refusal():
    value = {'promptFeedback': {'blockReason': 'SAFETY'}}
    assert module().extract_gemini_response(value)['error'] == 'ai_refused'
    assert parse(sse(value))[0]['error'] == 'ai_refused'


def test_stream_split_utf8_finish_usage_and_reasoning():
    thought = response_value('PRIVATE_THOUGHT', finish='')
    thought['candidates'][0]['content']['parts'][0]['thought'] = True
    first, last = response_value('中', finish=''), response_value('文')
    raw = sse(thought, first, last)
    cut = raw.index('中'.encode()) + 1
    result, seen = parse(raw[:cut], raw[cut:])
    assert result['error'] is None and result['text'] == '中文' and seen == ['中', '文']
    assert result['usage'] == {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}
    missing_usage = response_value('final')
    missing_usage.pop('usageMetadata')
    assert parse(sse(first, missing_usage))[0]['usage'] is None


@pytest.mark.parametrize('case', ['no_finish', 'after_finish', 'changed_id', 'duplicate_json',
    'invalid_utf8', 'trailing_partial', 'oversized_text'])
def test_stream_rejects_incomplete_or_corrupt_protocol(case):
    first, last = response_value('first', finish=''), response_value('last')
    if case == 'no_finish':
        raw = sse(first)
    elif case == 'after_finish':
        raw = sse(last, first)
    elif case == 'changed_id':
        last['responseId'] = 'another_response'
        raw = sse(first, last)
    elif case == 'duplicate_json':
        raw = b'data: {"candidates":[],"candidates":[]}\n\n'
    elif case == 'invalid_utf8':
        raw = b'data: \xff\n\n'
    elif case == 'trailing_partial':
        raw = sse(last) + b'data: {'
    else:
        raw = sse(response_value('x' * 64001))
    with pytest.raises(GatewayError):
        parse(raw)


@pytest.mark.parametrize('streamed', [False, True])
def test_native_http_transport_headers_and_cleanup(monkeypatch, streamed):
    configure(monkeypatch)
    config = configured_model()
    value = response_value()
    raw = sse(value) if streamed else json.dumps(value).encode()
    calls, state = transport(monkeypatch, lambda *_: raw,
        content_type='text/event-stream' if streamed else 'application/json')
    adapter = configured_adapter()
    body, _ = request_body(config, '历史问题', {'facts': []}, stream=streamed)
    if streamed:
        result = asyncio.run(adapter.stream(config, body, lambda _: asyncio.sleep(0)))
    else:
        result = asyncio.run(adapter.generate(config, body))
    assert result['error'] is None and len(calls) == 1
    sent = calls[0]
    assert sent['headers']['x-goog-api-key'] == config.api_key
    assert 'Authorization' not in sent['headers'] and config.api_key not in sent['url']
    assert sent['allow_redirects'] is False
    if streamed:
        assert sent['url'].endswith(':streamGenerateContent') and sent['params'] == {'alt': 'sse'}
    assert state['session_options']['trust_env'] is False and state['sessions_closed'] == 1


@pytest.mark.parametrize('case,code', [('status', 'ai_provider_http_error'), ('mime', 'ai_response_invalid'),
    ('length', 'ai_response_too_large'), ('duplicate_json', 'ai_response_invalid'),
    ('timeout', 'ai_provider_timeout'), ('connection', 'ai_provider_network_error')])
def test_native_http_failures_are_sanitized(monkeypatch, case, code):
    configure(monkeypatch)
    options = {'status': 403} if case == 'status' else {'content_type': 'text/html'} if case == 'mime' else {}
    if case == 'length':
        options['length'] = 512 * 1024 + 1
    if case == 'timeout':
        options['error'] = TimeoutError('PRIVATE_FAILURE')
    if case == 'connection':
        options['error'] = module().aiohttp.ClientConnectionError('PRIVATE_FAILURE')
    raw = b'{"x":1,"x":2}' if case == 'duplicate_json' else json.dumps(response_value()).encode()
    transport(monkeypatch, lambda *_: raw, **options)
    config = configured_model()
    body, _ = request_body(config, '历史问题', {'facts': []})
    with pytest.raises(GatewayError, match=code):
        asyncio.run(configured_adapter().generate(config, body))


@pytest.mark.parametrize('streamed', [False, True])
def test_application_entry_points_grounding_usage_and_replay(monkeypatch, tmp_path, streamed):
    configure(monkeypatch)

    def answer(_url, body):
        evidence = json.loads(body['contents'][0]['parts'][0]['text'])['untrusted_evidence_pack']
        fact = evidence['facts'][0]
        output = {'claims': [{'type': 'fact', 'text': '', 'fact_ids': [fact['id']],
            'evidence_ids': [fact['evidence_id']]}], 'uncertainty': 'synthetic Gemini transport'}
        value = response_value(json.dumps(output))
        return sse(value) if streamed else json.dumps(value).encode()

    calls, _ = transport(monkeypatch, answer, content_type='text/event-stream' if streamed else 'application/json')
    app = create_app('sqlite:///' + (tmp_path / 'gemini.db').as_posix(), FixtureRegistry())
    with TestClient(app) as client:
        assert client.get('/v1/ai/status').json()['model']['provider'] == 'gemini'
        pack = historical_pack(client)
        key = str(uuid4())
        if streamed:
            started = accept(client, pack, key)
            assert started.status_code == 202
            done = until(client, started.json()['analysis']['id'], lambda item: item['execution']['terminal'])
            row = done['analysis']
            assert accept(client, pack, key).status_code == 200
        else:
            response = analyze(client, pack, key)
            assert response.status_code == 200
            row = response.json()
            assert analyze(client, pack, key).json() == row
        assert row['state'] == 'completed' and row['provider'] == 'gemini'
        assert row['answer']['claims'][0]['text'] == pack['facts'][0]['text']
        assert row['usage'] == {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}
        assert len(calls) == 1
        assert client.get('/v1/ai/status').json()['budget']['accounted_tokens'] == 15


def test_native_candidate_authorization_dispatch_and_revocation(monkeypatch, tmp_path):
    url = configured_environment(monkeypatch, tmp_path / 'candidate')
    configure(monkeypatch)
    output = {'decision': 'abstain', 'selections': [], 'uncertainty_codes': []}
    calls, _ = transport(monkeypatch, lambda *_: json.dumps(response_value(json.dumps(output))).encode())
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        case = seed_candidate_ai(client)
        app.state.ai_adapter = configured_adapter()
        first = prepare(case)
        assert first['sendable'] is False and calls == []
        path = '/v1/ai/candidate-preparations/' + first['preparation_id'] + '/authorizations'
        for dependency in first['dependencies']:
            grant = {**grant_payload(dependency), 'provider': 'gemini'}
            assert ok(client.post(path, json=grant))['provider'] == 'gemini'
        ready = prepare(case)
        assert ready['sendable'] is True
        key = str(uuid4())
        result = ok(client.post('/v1/ai/candidate-recommendations', json=submit_payload(ready),
            headers={'Idempotency-Key': key}))
        assert result['state'] == 'completed' and result['preparation']['provider']['provider'] == 'gemini'
        assert len(calls) == 1 and 'contents' in calls[0]['json']
        replay = ok(client.post('/v1/ai/candidate-recommendations', json=submit_payload(ready),
            headers={'Idempotency-Key': key}))
        assert replay['id'] == result['id'] and len(calls) == 1
        dependency = ready['dependencies'][0]
        revoke = {**grant_payload(dependency, revision=1, action='revoke'), 'provider': 'gemini'}
        path = '/v1/ai/candidate-preparations/' + ready['preparation_id'] + '/authorizations'
        assert ok(client.post(path, json=revoke))['provider'] == 'gemini'
        assert prepare(case)['sendable'] is False and len(calls) == 1


def test_native_price_creation_planning_and_replay(pricing_case):
    _app, admin, _reader, _anonymous, _user = pricing_case
    key = str(uuid4())
    value = {**PRICE, 'provider': 'gemini'}
    created = ok(post_price(admin, value, key))
    assert created['provider'] == 'gemini'
    assert ok(post_price(admin, value, key)) == created
    result = ok(plan(admin, workload(created['id'])))
    assert result['items'][0]['price_version']['provider'] == 'gemini'
    assert result['items'][0]['exact_total'] == '5'


def test_native_usage_keeps_the_explicit_telemetry_provider():
    from tire_api.telemetry import TelemetryRuntime, record_ai_usage
    runtime = TelemetryRuntime(log_output=StringIO())
    try:
        with runtime.scope():
            record_ai_usage('gemini', {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15})
        tokens = samples(runtime, 'tire_ai_tokens_total')
        assert len(tokens) == 3 and {sample.labels['provider'] for sample in tokens} == {'gemini'}
        assert {sample.labels['kind']: sample.value for sample in tokens} == {
            'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}
    finally:
        runtime.shutdown()


@pytest.fixture
def gemini_vehicle_ctx(monkeypatch, tmp_path):
    """Synthetic capsule boundary; no historical PDF or binary-ingestion claim."""
    from admin_support import register_admin
    from sqlalchemy import select
    from test_fitment_relations import seed_vehicle
    from tire_api import vehicle_raw
    from tire_api.ai_gateway import OpenAIConfig
    from tire_api.service import timestamp
    from tire_api.vehicles import VehicleSnapshot, VehicleVerification, vehicle_provenance

    url = configured_environment(monkeypatch, tmp_path / 'vehicle')
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        register_admin(client)
        session_id = client.cookies['tire_local_session']
        snapshot_id = seed_vehicle(app.state.database, session_id)
        with app.state.database.sessions() as db:
            snapshot = db.get(VehicleSnapshot, snapshot_id)
            verification = db.scalar(select(VehicleVerification).where(VehicleVerification.snapshot_id == snapshot_id))
            capsule = {'snapshot_id': snapshot_id, 'payload': deepcopy(snapshot.payload),
                'provenance': vehicle_provenance(snapshot), 'verification_id': verification.id,
                'verified_at': timestamp(verification.verified_at), 'observed_at': timestamp(snapshot.observed_at),
                **{key: getattr(snapshot, key) for key in ('fact_hash', 'source_id', 'raw_hash', 'parser_version', 'parser_identity')}}
        monkeypatch.setattr(vehicle_raw, 'checked_vehicle_consumer_capsule',
            lambda *_args, **_kwargs: deepcopy(capsule))
        config = OpenAIConfig(model='synthetic-gemini-vehicle', api_key='synthetic-never-live',
            provider='gemini', allow_private=True)
        provider = ForbidProvider()
        app.state.ai_adapter = provider
        yield SimpleNamespace(client=client, app=app, database=app.state.database, session_id=session_id,
            snapshot_id=snapshot_id, config=config, provider=provider)


@pytest.mark.parametrize('device', [False, True])
@pytest.mark.parametrize('streamed', [False, True])
@pytest.mark.parametrize('tampered', [False, True])
def test_native_vehicle_final_dispatch_checks_rights_and_frozen_body(gemini_vehicle_ctx, device, streamed, tampered):
    ctx = gemini_vehicle_ctx
    pack_id = archive_device_pack(ctx) if device else archive_pack(ctx)
    reserved = archive_reservation(ctx, pack_id, stream=streamed)
    assert _vehicle_dispatch_input(reserved.body) is not None
    if tampered:
        reserved.body['contents'][0]['parts'][0]['text'] = '{}'
    completion = run_stream(ctx, reserved) if streamed else run_sync(ctx, reserved)
    assert_denied_completion(ctx, completion,
        'vehicle_evidence_binding_failed' if tampered else 'vehicle_provider_use_not_allowed')
