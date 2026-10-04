"""openai_chat (Chat Completions compatible) provider adapter tests (ADR-2026-054)."""
import asyncio
import json

import pytest

from tire_api import ai_recall_contract
from tire_api.ai_gateway import (ChatCompletionsAdapter, GatewayError, OpenAIResponsesAdapter,
                                 configured_adapter, configured_model, extract_chat_response,
                                 model_status, parse_chat_stream, request_body, safe_chat_usage,
                                 validated_public_base_url)
from tire_api.embedding_gateway import configured_embeddings
from tire_api.domain import digest

ALL_ENV = ('TI_AI_ENABLED', 'TI_AI_PROVIDER', 'TI_OPENAI_MODEL', 'TI_OPENAI_API_KEY',
           'TI_CHAT_MODEL', 'TI_CHAT_API_KEY', 'TI_CHAT_BASE_URL', 'TI_CHAT_RESPONSE_FORMAT',
           'TI_CHAT_TOKENS_PARAM', 'TI_CHAT_STREAM_USAGE', 'TI_AI_MAX_OUTPUT_TOKENS',
           'TI_EMBEDDINGS_ENABLED', 'TI_EMBEDDINGS_BASE_URL')


def chat_env(monkeypatch, **override):
    for name in ALL_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('TI_AI_ENABLED', '1')
    monkeypatch.setenv('TI_AI_PROVIDER', 'openai_chat')
    monkeypatch.setenv('TI_CHAT_MODEL', 'glm-4.6')
    monkeypatch.setenv('TI_CHAT_API_KEY', 'test-chat-key')
    monkeypatch.setenv('TI_CHAT_BASE_URL', 'https://open.bigmodel.cn/api/paas/v4')
    for name, value in override.items():
        monkeypatch.setenv(name, value)


def responses_env(monkeypatch):
    for name in ALL_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('TI_AI_ENABLED', '1')
    monkeypatch.setenv('TI_OPENAI_MODEL', 'gpt-test')
    monkeypatch.setenv('TI_OPENAI_API_KEY', 'test-key')


def expect_error(call, code):
    with pytest.raises(GatewayError) as caught:
        call()
    assert str(caught.value) == code


def test_default_provider_stays_responses_with_identical_wire(monkeypatch):
    responses_env(monkeypatch)
    config = configured_model()
    assert config.provider == 'openai_responses' and config.endpoint == 'https://api.openai.com/v1/responses'
    assert isinstance(configured_adapter(), OpenAIResponsesAdapter)
    body, reserve = request_body(config, '问题', {'facts': []})
    assert set(body) == {'model', 'store', 'stream', 'background', 'max_output_tokens', 'tools', 'input', 'text'}
    assert body['store'] is False and body['stream'] is False and body['background'] is False
    assert model_status()['provider'] == 'openai_responses' and 'endpoint_host' not in model_status()
    chat_env(monkeypatch)
    chat_body, chat_reserve = request_body(configured_model(), '问题', {'facts': []})
    assert chat_reserve == reserve  # D-D: one shared budget across protocols.


def test_chat_config_resolution_and_endpoint(monkeypatch):
    chat_env(monkeypatch)
    config = configured_model()
    assert config.provider == 'openai_chat'
    assert config.endpoint == 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
    assert config.allowed_host == 'open.bigmodel.cn'
    assert config.response_format == 'json_object' and config.tokens_param == 'max_tokens'
    assert config.stream_usage is True
    status = model_status()
    assert status['provider'] == 'openai_chat' and status['endpoint_host'] == 'open.bigmodel.cn'
    assert status['model'] == 'glm-4.6' and status['state'] == 'configured'
    assert isinstance(configured_adapter(), ChatCompletionsAdapter)
    chat_env(monkeypatch, TI_CHAT_BASE_URL='https://api.deepseek.com/')
    assert configured_model().endpoint == 'https://api.deepseek.com/chat/completions'
    chat_env(monkeypatch, TI_CHAT_BASE_URL='http://127.0.0.1:8000/v1')
    local = configured_model()
    assert local.endpoint == 'http://127.0.0.1:8000/v1/chat/completions' and local.allowed_host == '127.0.0.1'


def test_chat_config_rejects_missing_or_unsafe_values(monkeypatch):
    for missing in ('TI_CHAT_MODEL', 'TI_CHAT_API_KEY', 'TI_CHAT_BASE_URL'):
        chat_env(monkeypatch)
        monkeypatch.delenv(missing, raising=False)
        expect_error(configured_model, 'ai_configuration_required')
    for bad_base in ('http://api.example.com', 'https://api.example.com?q=1', 'https://api.example.com#f',
                     'https://user:pw@api.example.com', 'ftp://api.example.com',
                     'not-a-url'):
        chat_env(monkeypatch, TI_CHAT_BASE_URL=bad_base)
        expect_error(configured_model, 'ai_configuration_invalid')
    chat_env(monkeypatch, TI_CHAT_MODEL='has space')
    expect_error(configured_model, 'ai_configuration_invalid')
    chat_env(monkeypatch, TI_AI_PROVIDER='openai_whisper')
    expect_error(configured_model, 'ai_configuration_invalid')
    expect_error(configured_adapter, 'ai_configuration_invalid')
    chat_env(monkeypatch)
    monkeypatch.setenv('TI_CHAT_RESPONSE_FORMAT', 'yaml')
    expect_error(configured_model, 'ai_configuration_invalid')
    chat_env(monkeypatch, TI_CHAT_TOKENS_PARAM='tokens')
    expect_error(configured_model, 'ai_configuration_invalid')


def test_validated_public_base_url_direct_rules():
    assert validated_public_base_url('https://a.example/v4//') == 'https://a.example/v4'
    assert validated_public_base_url('http://localhost:11434') == 'http://localhost:11434'
    assert validated_public_base_url('http://[::1]:9000') == 'http://[::1]:9000'
    expect_error(lambda: validated_public_base_url(''), 'ai_configuration_required')
    expect_error(lambda: validated_public_base_url('http://api.example.com'), 'ai_configuration_invalid')


def test_resolver_loopback_exception_matches_config_layer_promise(monkeypatch):
    """G5-2（第61轮圆桌）：配置层允许的 loopback base URL 在传输层同样放行（AI 适配器例外）；
    来源抓取默认形态仍拒绝环回解析。"""
    from tire_api.adapters.transport import PublicResolver, SourceAccessError

    async def scenario():
        allowed = PublicResolver(frozenset({'localhost'}), allow_loopback=True)
        records = await allowed.resolve('localhost', 11434)
        assert records[0]['host'] == 'localhost'
        blocked = PublicResolver(frozenset({'localhost'}))
        try:
            await blocked.resolve('localhost', 11434)
        except SourceAccessError as error:
            assert str(error) == 'non_public_address'
        else:
            raise AssertionError('默认 resolver 不应放行环回地址')
        outside = PublicResolver(frozenset({'api.openai.com'}), allow_loopback=True)
        try:
            await outside.resolve('localhost', 11434)
        except SourceAccessError as error:
            assert str(error) == 'host_not_allowed'
        else:
            raise AssertionError('白名单外主机必须拒绝')

    asyncio.run(scenario())


def test_chat_request_body_shapes_and_knobs(monkeypatch):
    chat_env(monkeypatch)
    config = configured_model()
    body, _ = request_body(config, '问', {'facts': []})
    assert set(body) == {'model', 'stream', 'max_tokens', 'messages', 'response_format'}
    assert body['response_format'] == {'type': 'json_object'} and body['stream'] is False
    assert body['messages'][0]['role'] == 'system' and body['messages'][1]['role'] == 'user'
    assert json.loads(body['messages'][1]['content'])['question'] == '问'
    streamed, _ = request_body(config, '问', {'facts': []}, stream=True)
    assert streamed['stream'] is True and streamed['stream_options'] == {'include_usage': True}
    chat_env(monkeypatch, TI_CHAT_RESPONSE_FORMAT='json_schema')
    schema_body, _ = request_body(configured_model(), '问', {'facts': []})
    assert schema_body['response_format']['type'] == 'json_schema'
    assert schema_body['response_format']['json_schema']['name'] == 'tire_evidence_answer'
    assert schema_body['response_format']['json_schema']['strict'] is True
    assert 'stream_options' not in schema_body
    chat_env(monkeypatch, TI_CHAT_RESPONSE_FORMAT='none', TI_CHAT_TOKENS_PARAM='max_completion_tokens')
    plain_body, _ = request_body(configured_model(), '问', {'facts': []})
    assert 'response_format' not in plain_body and plain_body['max_completion_tokens'] == 1500
    chat_env(monkeypatch, TI_CHAT_STREAM_USAGE='0')
    no_usage, _ = request_body(configured_model(), '问', {'facts': []}, stream=True)
    assert 'stream_options' not in no_usage


def test_chat_request_body_reuses_recall_branch(monkeypatch):
    chat_env(monkeypatch)
    monkeypatch.setattr(ai_recall_contract, 'contains_recall', lambda evidence: True)
    monkeypatch.setattr(ai_recall_contract, 'validate_recall_payload', lambda evidence: None)
    body, _ = request_body(configured_model(), '问', {'recall_policy': {}})
    assert body['messages'][0]['content'] == ai_recall_contract.RECALL_SYSTEM_PROMPT
    monkeypatch.setattr(ai_recall_contract, 'validate_recall_payload',
                        lambda evidence: (_ for _ in ()).throw(ValueError))
    expect_error(lambda: request_body(configured_model(), '问', {'recall_policy': {}}), 'ai_grounding_validation_failed')


def test_chat_request_body_shared_size_gate(monkeypatch):
    big = {'facts': [{'domain': 'tire', 'field_code': 'c', 'text': 'x' * 20000} for _ in range(4)]}
    responses_env(monkeypatch)
    expect_error(lambda: request_body(configured_model(), '问', big), 'ai_evidence_too_large')
    chat_env(monkeypatch)
    expect_error(lambda: request_body(configured_model(), '问', big), 'ai_evidence_too_large')


def test_safe_chat_usage_and_extract_chat_response():
    assert safe_chat_usage({'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7}) == \
        {'input_tokens': 3, 'output_tokens': 4, 'total_tokens': 7}
    assert safe_chat_usage({'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 8}) is None
    assert safe_chat_usage('x') is None

    def value(**choice):
        message = choice.pop('message', {'role': 'assistant', 'content': '{"claims":[]}'})
        return {'id': 'chatcmpl-1', 'object': 'chat.completion',
                'choices': [{'index': 0, 'finish_reason': choice.pop('finish_reason', 'stop'),
                             'message': message}], **choice}

    receipt = extract_chat_response(value(usage={'prompt_tokens': 1, 'completion_tokens': 2, 'total_tokens': 3}))
    assert receipt == {'usage': {'input_tokens': 1, 'output_tokens': 2, 'total_tokens': 3},
                       'provider_response_id': 'chatcmpl-1', 'text': '{"claims":[]}', 'error': None}
    assert extract_chat_response(value(finish_reason='length'))['error'] == 'ai_response_incomplete'
    assert extract_chat_response(value(finish_reason='content_filter'))['error'] == 'ai_refused'
    assert extract_chat_response(value(message={'role': 'assistant', 'content': None, 'refusal': 'no'}))['error'] == 'ai_refused'
    assert extract_chat_response(value(message={'role': 'assistant', 'content': 'x', 'tool_calls': []}))['error'] == 'ai_response_invalid'
    assert extract_chat_response(value(message={'role': 'user', 'content': 'x'}))['error'] == 'ai_response_invalid'
    assert extract_chat_response(value(finish_reason=None))['error'] == 'ai_response_invalid'
    assert extract_chat_response(value(message={'role': 'assistant', 'content': ''}))['error'] == 'ai_response_invalid'
    assert extract_chat_response(value(message={'role': 'assistant', 'content': 'x' * 64001}))['error'] == 'ai_response_invalid'
    assert extract_chat_response(value(usage={'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 5}))['usage'] is None
    duplicated = value()
    duplicated['choices'].append(duplicated['choices'][0])
    assert extract_chat_response(duplicated)['error'] == 'ai_response_invalid'
    bad_object = value()
    bad_object['object'] = 'chat.completion.chunk'
    assert extract_chat_response(bad_object)['error'] == 'ai_response_invalid'
    bad_id = value()
    bad_id['id'] = 'bad id!'
    assert extract_chat_response(bad_id)['provider_response_id'] is None


def sse(*events):
    return ('\n'.join(f'data: {event}' for event in events) + '\ndata: [DONE]\n\n').encode('utf-8')


def chunk(delta=None, finish=None, chunk_id='chatcmpl-9', usage=None):
    choice = {'index': 0, 'delta': delta if delta is not None else {}, 'finish_reason': finish}
    value = {'id': chunk_id, 'object': 'chat.completion.chunk', 'choices': [choice]}
    if usage is not None:
        value['usage'] = usage
        value['choices'] = []
    return json.dumps(value, ensure_ascii=False)


def run_raw(*payloads):
    """Drive parse_chat_stream over raw byte chunks; returns (receipt, collected deltas)."""
    async def drive():
        seen = []

        async def hook(delta):
            seen.append(delta)

        async def gen():
            for item in payloads:
                yield item
        receipt = await parse_chat_stream(gen(), hook)
        return receipt, seen
    return asyncio.run(drive())


def test_parse_chat_stream_happy_path_with_split_utf8():
    text = '{"claims":[]}ück'
    first, second = text[:6], text[6:]
    payload = sse(chunk(delta={'role': 'assistant'}),
                  chunk(delta={'content': first}),
                  chunk(delta={'content': second}),
                  chunk(delta={}, finish='stop'),
                  chunk(usage={'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}))
    cut = payload.index('ü'.encode('utf-8')) + 1  # split inside the two-byte sequence
    receipt, seen = run_raw(payload[:cut], payload[cut:])
    assert receipt == {'usage': {'input_tokens': 2, 'output_tokens': 3, 'total_tokens': 5},
                       'provider_response_id': 'chatcmpl-9', 'text': text, 'error': None}
    assert seen == [first, second]


def test_parse_chat_stream_refusal_and_finish_mapping():
    refusal = sse(chunk(delta={'role': 'assistant'}), chunk(delta={'refusal': 'not allowed'}),
                  chunk(delta={}, finish='stop'))
    assert run_raw(refusal)[0]['error'] == 'ai_refused'
    length = sse(chunk(delta={'content': '部分'}), chunk(delta={}, finish='length'))
    assert run_raw(length)[0]['error'] == 'ai_response_incomplete'
    filtered = sse(chunk(delta={'content': 'x'}), chunk(delta={}, finish='content_filter'))
    assert run_raw(filtered)[0]['error'] == 'ai_refused'
    empty = sse(chunk(delta={'role': 'assistant'}), chunk(delta={}, finish='stop'))
    assert run_raw(empty)[0]['error'] == 'ai_response_invalid'


def test_parse_chat_stream_protocol_errors():
    def expect_stream_error(payload, code):
        with pytest.raises(GatewayError) as caught:
            run_raw(payload)
        assert str(caught.value) == code
    expect_stream_error(b'event: ping\ndata: {}\n\n', 'ai_stream_protocol_error')
    expect_stream_error(b'data: {not json}\n\n', 'ai_stream_protocol_error')
    no_done = ('data: ' + chunk(delta={'content': 'x'}, finish='stop') + '\n\n').encode('utf-8')
    expect_stream_error(no_done, 'ai_stream_interrupted')
    double_finish = sse(chunk(delta={}, finish='stop'), chunk(delta={}, finish='stop'))
    with pytest.raises(GatewayError):
        run_raw(double_finish)
    content_after_finish = sse(chunk(delta={}, finish='stop'), chunk(delta={'content': 'x'}))
    with pytest.raises(GatewayError):
        run_raw(content_after_finish)
    non_string = sse(chunk(delta={'content': 5}))
    with pytest.raises(GatewayError):
        run_raw(non_string)
    huge_line = ('data: ' + chunk(delta={'content': 'x' * 600000}) + '\n\n').encode('utf-8')
    expect_stream_error(huge_line, 'ai_response_too_large')
    trailing = sse(chunk(delta={}, finish='stop')) + b'data: {"id":"chatcmpl-9"}\n'
    with pytest.raises(GatewayError):
        run_raw(trailing)


def test_adapter_guards_reject_cross_protocol_bodies(monkeypatch):
    responses_env(monkeypatch)
    responses_body, _ = request_body(configured_model(), '问', {'facts': []}, stream=True)
    chat_env(monkeypatch)
    adapter = ChatCompletionsAdapter()
    config = configured_model()
    with pytest.raises(GatewayError):
        asyncio.run(adapter.stream(config, responses_body, lambda delta: asyncio.sleep(0)))
    chat_body, _ = request_body(config, '问', {'facts': []})
    with pytest.raises(GatewayError):
        asyncio.run(adapter.stream(config, chat_body, lambda delta: asyncio.sleep(0)))
    with pytest.raises(GatewayError):
        asyncio.run(adapter.generate(config, {**chat_body, 'stream': True}))


def test_model_status_reflects_provider_and_disabled_state(monkeypatch):
    chat_env(monkeypatch, TI_AI_ENABLED='0')
    status = model_status()
    assert status == {'provider': 'openai_chat', 'state': 'ai_disabled', 'model': None,
                      'connection_verified': False}
    chat_env(monkeypatch, TI_AI_PROVIDER='openai_bogus')
    assert model_status()['provider'] == 'openai_responses'  # sanitized echo on error paths


def test_embeddings_base_url_scopes_model_space(monkeypatch):
    for name in ('TI_EMBEDDINGS_ENABLED', 'TI_EMBEDDINGS_BASE_URL', 'TI_OPENAI_EMBEDDING_MODEL',
                 'TI_OPENAI_API_KEY', 'TI_OPENAI_EMBEDDING_DIMENSIONS'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('TI_EMBEDDINGS_ENABLED', '1')
    monkeypatch.setenv('TI_OPENAI_EMBEDDING_MODEL', 'embedding-test')
    monkeypatch.setenv('TI_OPENAI_API_KEY', 'k')
    monkeypatch.setenv('TI_OPENAI_EMBEDDING_DIMENSIONS', '64')
    default = configured_embeddings()
    assert default.endpoint == 'https://api.openai.com/v1/embeddings'
    assert default.model_space == digest({'provider': 'openai_embeddings', 'model': 'embedding-test',
                                           'dimensions': 64})  # unchanged default space
    monkeypatch.setenv('TI_EMBEDDINGS_BASE_URL', 'https://open.bigmodel.cn/api/paas/v4')
    custom = configured_embeddings()
    assert custom.endpoint == 'https://open.bigmodel.cn/api/paas/v4/embeddings'
    assert custom.allowed_host == 'open.bigmodel.cn'
    assert custom.model_space != default.model_space
    monkeypatch.setenv('TI_EMBEDDINGS_BASE_URL', 'http://api.example.com')
    with pytest.raises(Exception) as caught:
        configured_embeddings()
    assert 'embeddings_configuration_invalid' in str(caught.value) or str(caught.value) == 'embeddings_configuration_invalid'
