"""anthropic (Messages API native) provider adapter tests (ADR-2026-055)."""
import asyncio
import json

import pytest

from tire_api import ai_recall_contract
from tire_api.ai_gateway import (AnthropicAdapter, GatewayError, configured_adapter, configured_model,
                                 extract_anthropic_response, model_status, parse_anthropic_stream,
                                 request_body, safe_anthropic_usage)
from tire_api.embedding_gateway import configured_embeddings

ALL_ENV = ('TI_AI_ENABLED', 'TI_AI_PROVIDER', 'TI_OPENAI_MODEL', 'TI_OPENAI_API_KEY',
           'TI_CHAT_MODEL', 'TI_CHAT_API_KEY', 'TI_CHAT_BASE_URL',
           'TI_ANTHROPIC_MODEL', 'TI_ANTHROPIC_API_KEY', 'TI_ANTHROPIC_BASE_URL',
           'TI_ANTHROPIC_AUTH_HEADER', 'TI_AI_MAX_OUTPUT_TOKENS')


def anthropic_env(monkeypatch, **override):
    for name in ALL_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('TI_AI_ENABLED', '1')
    monkeypatch.setenv('TI_AI_PROVIDER', 'anthropic')
    monkeypatch.setenv('TI_ANTHROPIC_MODEL', 'claude-sonnet-4-5')
    monkeypatch.setenv('TI_ANTHROPIC_API_KEY', 'sk-ant-test')
    for name, value in override.items():
        monkeypatch.setenv(name, value)


def expect_error(call, code):
    with pytest.raises(GatewayError) as caught:
        call()
    assert str(caught.value) == code


def test_anthropic_config_default_and_custom_base(monkeypatch):
    anthropic_env(monkeypatch)
    config = configured_model()
    assert config.provider == 'anthropic'
    assert config.endpoint == 'https://api.anthropic.com/v1/messages'
    assert config.allowed_host == 'api.anthropic.com' and config.auth_style == 'x-api-key'
    assert isinstance(configured_adapter(), AnthropicAdapter)
    status = model_status()
    assert status['provider'] == 'anthropic' and status['endpoint_host'] == 'api.anthropic.com'
    anthropic_env(monkeypatch, TI_ANTHROPIC_BASE_URL='https://relay.example.com/anthropic')
    relay = configured_model()
    assert relay.endpoint == 'https://relay.example.com/anthropic/v1/messages'
    assert relay.allowed_host == 'relay.example.com'
    anthropic_env(monkeypatch, TI_ANTHROPIC_BASE_URL='http://127.0.0.1:8082')
    local = configured_model()
    assert local.endpoint == 'http://127.0.0.1:8082/v1/messages'
    anthropic_env(monkeypatch, TI_ANTHROPIC_AUTH_HEADER='bearer')
    assert configured_model().auth_style == 'bearer'


def test_anthropic_config_rejects_missing_or_unsafe_values(monkeypatch):
    for missing in ('TI_ANTHROPIC_MODEL', 'TI_ANTHROPIC_API_KEY'):
        anthropic_env(monkeypatch)
        monkeypatch.delenv(missing, raising=False)
        expect_error(configured_model, 'ai_configuration_required')
    for bad_base in ('http://api.anthropic.com', 'https://relay.example.com?q=1', 'not-a-url'):
        anthropic_env(monkeypatch, TI_ANTHROPIC_BASE_URL=bad_base)
        expect_error(configured_model, 'ai_configuration_invalid')
    anthropic_env(monkeypatch, TI_ANTHROPIC_MODEL='has space')
    expect_error(configured_model, 'ai_configuration_invalid')
    anthropic_env(monkeypatch, TI_ANTHROPIC_AUTH_HEADER='query')
    expect_error(configured_model, 'ai_configuration_invalid')


def test_anthropic_request_body_shape_and_shared_contract(monkeypatch):
    anthropic_env(monkeypatch)
    config = configured_model()
    body, reserve = request_body(config, '问', {'facts': []})
    assert set(body) == {'model', 'max_tokens', 'stream', 'system', 'messages'}
    assert body['max_tokens'] == 1500 and body['stream'] is False  # max_tokens mandatory (D-2).
    from tire_api.ai_gateway import OUTPUT_SCHEMA, SYSTEM_PROMPT
    from tire_api.domain import stable_json
    assert body['system'] == SYSTEM_PROMPT + '\n\n输出必须是严格的 JSON 文本，并逐字遵循下面的 JSON Schema；' \
        'uncertainty 是单个字符串，不是数组：\n' + stable_json(OUTPUT_SCHEMA)  # schema rides in system (ADR-2026-055)
    assert body['messages'] == [{'role': 'user', 'content': body['messages'][0]['content']}]
    assert len(body['messages']) == 1
    assert json.loads(body['messages'][0]['content'])['question'] == '问'
    streamed, streamed_reserve = request_body(config, '问', {'facts': []}, stream=True)
    assert streamed['stream'] is True and streamed_reserve == reserve
    monkeypatch.setattr(ai_recall_contract, 'contains_recall', lambda evidence: True)
    monkeypatch.setattr(ai_recall_contract, 'validate_recall_payload', lambda evidence: None)
    recall_body, _ = request_body(config, '问', {'recall_policy': {}})
    assert recall_body['system'].startswith(ai_recall_contract.RECALL_SYSTEM_PROMPT)
    assert stable_json(ai_recall_contract.RECALL_OUTPUT_SCHEMA) in recall_body['system']
    big = {'facts': [{'domain': 'tire', 'field_code': 'c', 'text': 'x' * 20000} for _ in range(4)]}
    expect_error(lambda: request_body(config, '问', big), 'ai_evidence_too_large')


def test_safe_anthropic_usage_and_extract_response():
    assert safe_anthropic_usage({'input_tokens': 3, 'output_tokens': 4}) == \
        {'input_tokens': 3, 'output_tokens': 4, 'total_tokens': 7}
    assert safe_anthropic_usage({'input_tokens': 3}) is None
    assert safe_anthropic_usage('x') is None

    def value(**over):
        base = {'id': 'msg_01', 'type': 'message', 'role': 'assistant',
                'content': [{'type': 'text', 'text': '{"claims":[]}'}],
                'stop_reason': 'end_turn', 'usage': {'input_tokens': 2, 'output_tokens': 5}}
        base.update(over)
        return base

    receipt = extract_anthropic_response(value())
    assert receipt == {'usage': {'input_tokens': 2, 'output_tokens': 5, 'total_tokens': 7},
                       'provider_response_id': 'msg_01', 'text': '{"claims":[]}', 'error': None}
    assert extract_anthropic_response(value(stop_reason='max_tokens'))['error'] == 'ai_response_incomplete'
    assert extract_anthropic_response(value(stop_reason='refusal'))['error'] == 'ai_refused'
    assert extract_anthropic_response(value(stop_reason='stop_sequence'))['error'] == 'ai_response_invalid'
    assert extract_anthropic_response(value(stop_reason='tool_use'))['error'] == 'ai_response_invalid'
    assert extract_anthropic_response(value(stop_reason=None))['error'] == 'ai_response_invalid'
    assert extract_anthropic_response(value(type='error'))['error'] == 'ai_response_invalid'
    thinking = extract_anthropic_response(value(content=[{'type': 'thinking', 'thinking': 'x'},
                                                         {'type': 'redacted_thinking', 'data': 'y'},
                                                         {'type': 'text', 'text': '答案'}]))
    assert thinking['text'] == '答案'
    assert extract_anthropic_response(value(content=[{'type': 'tool_use', 'id': 't'}]))['error'] == 'ai_response_invalid'
    assert extract_anthropic_response(value(content=[{'type': 'text', 'text': ''}]))['error'] == 'ai_response_invalid'
    assert extract_anthropic_response(value(content=[{'type': 'text', 'text': 'x' * 64001}]))['error'] == 'ai_response_invalid'
    assert extract_anthropic_response(value(content=[]))['error'] == 'ai_response_invalid'
    assert extract_anthropic_response(value(id='bad id!'))['provider_response_id'] is None
    assert extract_anthropic_response(value(usage={'input_tokens': 2}))['usage'] is None


def anthropic_sse(*events):
    return ''.join(f'event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
                   for name, payload in events).encode('utf-8')


def run_raw(*payloads):
    async def drive():
        seen = []

        async def hook(delta):
            seen.append(delta)

        async def gen():
            for item in payloads:
                yield item
        receipt = await parse_anthropic_stream(gen(), hook)
        return receipt, seen
    return asyncio.run(drive())


def test_parse_anthropic_stream_happy_path_with_utf8_split():
    text = '{"claims":[]}ück'
    first, second = text[:6], text[6:]
    payload = anthropic_sse(
        ('message_start', {'type': 'message_start', 'message': {'id': 'msg_02', 'usage': {'input_tokens': 11}}}),
        ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': first}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': second}}),
        ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
        ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': 4}}),
        ('message_stop', {'type': 'message_stop'}))
    cut = payload.index('ü'.encode('utf-8')) + 1
    receipt, seen = run_raw(payload[:cut], payload[cut:])
    assert receipt == {'usage': {'input_tokens': 11, 'output_tokens': 4, 'total_tokens': 15},
                       'provider_response_id': 'msg_02', 'text': text, 'error': None}
    assert seen == [first, second]


def test_parse_anthropic_stream_ping_thinking_and_stop_mapping():
    payload = anthropic_sse(
        ('ping', {'type': 'ping'}),
        ('message_start', {'type': 'message_start', 'message': {'id': 'msg_03', 'usage': {'input_tokens': 5}}}),
        ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': ''}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': '秘密'}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'signature_delta', 'signature': 'sig'}}),
        ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
        ('content_block_start', {'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'text', 'text': ''}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': '答案'}}),
        ('content_block_stop', {'type': 'content_block_stop', 'index': 1}),
        ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': 2}}),
        ('message_stop', {'type': 'message_stop'}))
    receipt, seen = run_raw(payload)
    assert receipt['text'] == '答案' and receipt['error'] is None and seen == ['答案']
    truncated = anthropic_sse(
        ('message_start', {'type': 'message_start', 'message': {'id': 'msg_04', 'usage': {'input_tokens': 5}}}),
        ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'x'}}),
        ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
        ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'max_tokens'}}),
        ('message_stop', {'type': 'message_stop'}))
    assert run_raw(truncated)[0]['error'] == 'ai_response_incomplete'
    refused = anthropic_sse(
        ('message_start', {'type': 'message_start', 'message': {'id': 'msg_05', 'usage': {'input_tokens': 5}}}),
        ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'refusal'}}),
        ('message_stop', {'type': 'message_stop'}))
    assert run_raw(refused)[0]['error'] == 'ai_refused'


def test_parse_anthropic_stream_protocol_errors():
    def expect_stream_error(payload, code):
        with pytest.raises(GatewayError) as caught:
            run_raw(payload)
        assert str(caught.value) == code

    start = ('message_start', {'type': 'message_start', 'message': {'id': 'msg_06', 'usage': {'input_tokens': 3}}})
    delta_before_start = anthropic_sse(
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'x'}}))
    with pytest.raises(GatewayError):
        run_raw(delta_before_start)
    no_terminal = anthropic_sse(
        start,
        ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'x'}}),
        ('content_block_stop', {'type': 'content_block_stop', 'index': 0}))
    expect_stream_error(no_terminal, 'ai_stream_interrupted')
    unterminated_block = anthropic_sse(
        start,
        ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}}),
        ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}}),
        ('message_stop', {'type': 'message_stop'}))
    with pytest.raises(GatewayError):
        run_raw(unterminated_block)
    bad_event_name = anthropic_sse(('content_block_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}}))
    with pytest.raises(GatewayError):  # _SSEDecoder requires event name == data.type
        run_raw(bad_event_name)
    unknown = anthropic_sse(start, ('mystery_event', {'type': 'mystery_event'}))
    with pytest.raises(GatewayError):
        run_raw(unknown)
    text_on_thinking = anthropic_sse(
        start,
        ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': ''}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'x'}}))
    with pytest.raises(GatewayError):
        run_raw(text_on_thinking)
    huge = anthropic_sse(
        start,
        ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'x' * 70000}}))
    with pytest.raises(GatewayError) as caught:
        run_raw(huge)
    assert str(caught.value) == 'ai_response_too_large'


def test_adapter_guards_and_cross_protocol_defense(monkeypatch):
    anthropic_env(monkeypatch)
    adapter, config = AnthropicAdapter(), configured_model()
    chat_style = {'model': 'm', 'max_tokens': 5, 'stream': True, 'messages': [{'role': 'system', 'content': 's'},
                                                                              {'role': 'user', 'content': 'u'}]}
    with pytest.raises(GatewayError):  # missing top-level system
        asyncio.run(adapter.stream(config, chat_style, lambda delta: asyncio.sleep(0)))
    body, _ = request_body(config, '问', {'facts': []})
    with pytest.raises(GatewayError):  # stream flag mismatch for stream()
        asyncio.run(adapter.stream(config, body, lambda delta: asyncio.sleep(0)))
    streamed, _ = request_body(config, '问', {'facts': []}, stream=True)
    with pytest.raises(GatewayError):  # stream flag mismatch for generate()
        asyncio.run(adapter.generate(config, streamed))


def test_status_error_paths_and_embeddings_untouched(monkeypatch):
    anthropic_env(monkeypatch, TI_AI_ENABLED='0')
    assert model_status() == {'provider': 'anthropic', 'state': 'ai_disabled', 'model': None,
                              'connection_verified': False}
    anthropic_env(monkeypatch, TI_AI_PROVIDER='anthropic-x')
    assert model_status()['provider'] == 'openai_responses'
    for name in ('TI_EMBEDDINGS_ENABLED', 'TI_EMBEDDINGS_BASE_URL', 'TI_OPENAI_EMBEDDING_MODEL',
                 'TI_OPENAI_API_KEY', 'TI_OPENAI_EMBEDDING_DIMENSIONS'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '1')
    monkeypatch.setenv('TI_OPENAI_EMBEDDING_MODEL', 'embedding-test')
    monkeypatch.setenv('TI_OPENAI_API_KEY', 'k')
    monkeypatch.setenv('TI_OPENAI_EMBEDDING_DIMENSIONS', '64')
    assert configured_embeddings().endpoint == 'https://api.openai.com/v1/embeddings'  # no anthropic embeddings
