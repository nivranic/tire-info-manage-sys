"""Synthetic wire fragments and grounded drafts; no credentials or network."""
import asyncio
import json

import pytest

from tire_api.ai_gateway import GatewayError


TEXT = '{"claims":[{"type":"fact","text":"","fact_ids":["f1"],"evidence_ids":["e1"]}],"uncertainty":"仍需核对"}'
PACK = {'payload': {'facts': [{'id': 'f1', 'evidence_id': 'e1', 'text': '宽度 245 mm'}],
                    'evidence': [{'id': 'e1'}], 'conflicts': [], 'source_state': 'snapshot'},
        'data_state': 'history'}


def response(text=TEXT, status='completed'):
    return {'id': 'resp_synthetic', 'status': status,
            'usage': {'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30},
            'output': [{'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': text}]}]}


def events(text=TEXT):
    return [
        {'type': 'response.created', 'sequence_number': 0, 'response': {'id': 'resp_synthetic', 'status': 'in_progress'}},
        {'type': 'response.output_item.added', 'sequence_number': 1, 'output_index': 0,
         'item': {'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'status': 'in_progress', 'content': []}},
        {'type': 'response.content_part.added', 'sequence_number': 2, 'output_index': 0, 'content_index': 0,
         'item_id': 'msg_1', 'part': {'type': 'output_text', 'text': ''}},
        {'type': 'response.output_text.delta', 'sequence_number': 3, 'output_index': 0, 'content_index': 0,
         'item_id': 'msg_1', 'delta': text},
        {'type': 'response.output_text.done', 'sequence_number': 4, 'output_index': 0, 'content_index': 0,
         'item_id': 'msg_1', 'text': text},
        {'type': 'response.completed', 'sequence_number': 5, 'response': response(text)},
    ]


def wire(items, newline='\r\n'):
    return ''.join(f'event: {item["type"]}{newline}data: {json.dumps(item, ensure_ascii=False)}{newline}{newline}'
                   for item in items).encode()


def parse(raw, width=7):
    from tire_api.ai_stream_parser import parse_response_stream
    received = []

    async def chunks():
        for at in range(0, len(raw), width):
            yield raw[at:at + width]

    async def on_text(text):
        received.append(text)

    return asyncio.run(parse_response_stream(chunks(), on_text)), received


def test_real_wire_parser_handles_split_utf8_crlf_and_returns_only_final_receipt():
    receipt, received = parse(b': keepalive\r\n\r\n' + wire(events()), width=1)
    assert ''.join(received) == TEXT
    assert receipt == {'text': TEXT, 'error': None, 'usage': {'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30},
                       'provider_response_id': 'resp_synthetic'}


@pytest.mark.parametrize('mutation', ['sequence', 'item', 'final_text', 'final_id', 'tool', 'duplicate_key'])
def test_wire_identity_order_terminal_and_tool_corruption_is_rejected(mutation):
    items = events()
    if mutation == 'sequence': items[3]['sequence_number'] = 2
    if mutation == 'item': items[3]['item_id'] = 'other_item'
    if mutation == 'final_text': items[-1]['response'] = response('{}')
    if mutation == 'final_id': items[-1]['response']['id'] = 'resp_other'
    if mutation == 'tool': items[1]['item']['type'] = 'function_call'
    raw = wire(items)
    if mutation == 'duplicate_key': raw = raw.replace(b'"sequence_number": 3', b'"sequence_number": 3, "sequence_number": 4')
    with pytest.raises(GatewayError):
        parse(raw)


def test_clean_eof_without_terminal_is_unknown_not_completed():
    with pytest.raises(GatewayError, match='ai_stream_interrupted'):
        parse(wire(events()[:-1]))


@pytest.mark.parametrize('mutation', ['final_item_id', 'final_index', 'done_content', 'done_status', 'done_role'])
def test_terminal_and_item_done_preserve_actual_message_identity_and_content(mutation):
    items = events()
    if mutation == 'final_item_id':
        items[-1]['response']['output'][0]['id'] = 'msg_replaced'
    elif mutation == 'final_index':
        items[-1]['response']['output'].insert(0, {'id': 'unseen_reasoning', 'type': 'reasoning'})
    else:
        item = response()['output'][0]
        if mutation == 'done_content': item['content'][0]['text'] = '{}'
        if mutation == 'done_status': item['status'] = 'in_progress'
        if mutation == 'done_role': item['role'] = 'user'
        items.insert(-1, {'type': 'response.output_item.done', 'sequence_number': 5, 'output_index': 0, 'item': item})
        items[-1]['sequence_number'] = 6
    with pytest.raises(GatewayError, match='ai_stream_protocol_error'):
        parse(wire(items))


@pytest.mark.parametrize('status,code', [('incomplete', 'ai_response_incomplete'), ('failed', 'ai_provider_failed')])
def test_terminal_failures_keep_safe_usage_and_discard_unfinished_text(status, code):
    items = events()
    items[-1] = {'type': f'response.{status}', 'sequence_number': 5, 'response': response(status=status)}
    receipt, _ = parse(wire(items))
    assert receipt['error'] == code and receipt['text'] is None and receipt['usage']['total_tokens'] == 30


def test_claim_drafts_arrive_only_at_complete_object_and_render_facts_from_pack():
    from tire_api.ai_stream_parser import StructuredDraftProjector
    projector = StructuredDraftProjector(PACK)
    split = TEXT.index('],"uncertainty"')
    assert projector.feed(TEXT[:split - 1]) == []
    first = projector.feed(TEXT[split - 1:split])
    assert first == [{'type': 'claim_draft', 'payload': {'index': 0, 'claim': {
        'type': 'fact', 'text': '宽度 245 mm', 'fact_ids': ['f1'], 'evidence_ids': ['e1']}}}]
    assert projector.feed(TEXT[split:]) == [{'type': 'uncertainty_draft', 'payload': {'text': '仍需核对'}}]
    assert projector.finish()['claims'][0]['text'] == '宽度 245 mm'


def test_uncertainty_only_answer_streams_after_complete_escaped_string():
    from tire_api.ai_stream_parser import StructuredDraftProjector
    projector = StructuredDraftProjector(PACK)
    assert projector.feed('{"claims":[],"uncertainty":"缺少\\"') == []
    assert projector.feed('当前\\"证据"') == [{'type': 'uncertainty_draft', 'payload': {'text': '缺少"当前"证据'}}]
    assert projector.feed('}') == []
    assert projector.finish()['claims'] == []


@pytest.mark.parametrize('text', [
    TEXT.replace('"text":""', '"text":"invented fact"'),
    TEXT.replace('"f1"', '"unknown"'),
    TEXT.replace('"e1"', '"other"'),
    TEXT.replace('"type":"fact"', '"type":"fact","type":"inference"'),
    '{"claims":[],"claims":[],"uncertainty":"x"}',
    '{"claims":[],"uncertainty":"x","internal_log":"secret"}',
])
def test_invalid_claim_or_structure_never_becomes_final_answer(text):
    from tire_api.ai_stream_parser import StructuredDraftProjector
    projector = StructuredDraftProjector(PACK)
    with pytest.raises((GatewayError, ValueError)):
        projector.feed(text)
        projector.finish()


def test_projection_limits_do_not_expose_oversized_or_raw_provider_content():
    from tire_api.ai_stream_parser import StructuredDraftProjector
    projector = StructuredDraftProjector(PACK)
    with pytest.raises(GatewayError):
        projector.feed('{"claims":[],"uncertainty":"' + 'x' * 65537)


def test_sse_multiline_data_bare_cr_and_reasoning_are_not_exposed():
    items = events()
    items.insert(1, {'type': 'response.output_item.added', 'sequence_number': 1, 'output_index': 0,
                     'item': {'id': 'reason_1', 'type': 'reasoning', 'summary': []}})
    items.insert(2, {'type': 'response.reasoning_summary_text.delta', 'sequence_number': 2,
                     'item_id': 'reason_1', 'output_index': 0, 'summary_index': 0, 'delta': 'PRIVATE REASONING'})
    for index, event in enumerate(items):
        event['sequence_number'] = index
        if index >= 3 and 'output_index' in event:
            event['output_index'] = 1
    items[-1]['response']['output'].insert(0, {'id': 'reason_1', 'type': 'reasoning', 'summary': [{'text': 'PRIVATE REASONING'}]})
    raw = ''.join(''.join('data: ' + line + '\r' for line in json.dumps(item, ensure_ascii=False, indent=2).splitlines()) + '\r'
                  for item in items).encode()
    receipt, received = parse(raw, width=3)
    assert receipt['text'] == TEXT and ''.join(received) == TEXT
    assert 'PRIVATE' not in json.dumps(receipt)


def test_complete_refusal_never_projects_raw_refusal():
    items = events()
    items[2]['part'] = {'type': 'refusal', 'refusal': ''}
    items[3]['type'], items[3]['delta'] = 'response.refusal.delta', 'PRIVATE REFUSAL'
    items[4]['type'] = 'response.refusal.done'
    items[4].pop('text')
    items[4]['refusal'] = 'PRIVATE REFUSAL'
    items[-1]['response']['output'][0]['content'] = [{'type': 'refusal', 'refusal': 'PRIVATE REFUSAL'}]
    receipt, received = parse(wire(items))
    assert received == [] and receipt['error'] == 'ai_refused' and receipt['text'] is None
    assert 'PRIVATE' not in json.dumps(receipt)


@pytest.mark.parametrize('case', ['frame', 'total', 'events', 'utf8', 'event_type', 'boolean_sequence'])
def test_wire_resource_and_protocol_limits_fail_closed(monkeypatch, case):
    from tire_api import ai_stream_parser as parser
    raw = wire(events())
    if case == 'frame': monkeypatch.setattr(parser, 'MAX_FRAME_BYTES', 80)
    if case == 'total': monkeypatch.setattr(parser, 'MAX_STREAM_BYTES', 80)
    if case == 'events': monkeypatch.setattr(parser, 'MAX_STREAM_EVENTS', 2)
    if case == 'utf8': raw = b'data: \xff\n\n'
    if case == 'event_type': raw = raw.replace(b'event: response.created', b'event: response.failed', 1)
    if case == 'boolean_sequence': raw = raw.replace(b'"sequence_number": 3', b'"sequence_number": true', 1)
    with pytest.raises(GatewayError):
        parse(raw)


@pytest.mark.parametrize('case', ['valid', 'redirect', 'mime', 'length', 'timeout'])
def test_native_stream_transport_enforces_fixed_endpoint_headers_and_timeouts(monkeypatch, case):
    from tire_api import ai_gateway as gateway
    from tire_api.ai_stream_parser import MAX_STREAM_BYTES
    captured = {}

    class Context:
        async def __aenter__(self): return self
        async def __aexit__(self, *_):
            captured['closed'] = captured.get('closed', 0) + 1

    class Content:
        async def iter_chunked(self, _size):
            if case == 'timeout': raise TimeoutError()
            yield wire(events())

    class Response(Context):
        status = 302 if case == 'redirect' else 200
        headers = {'Content-Type': 'application/json' if case == 'mime' else 'text/event-stream; charset=utf-8'}
        content_length = MAX_STREAM_BYTES + 1 if case == 'length' else None
        content = Content()

    class Client(Context):
        def __init__(self, **kwargs): captured['client'] = kwargs
        def post(self, endpoint, **kwargs):
            captured['endpoint'], captured['request'] = endpoint, kwargs
            return Response()

    monkeypatch.setattr(gateway.aiohttp, 'ClientSession', Client)
    monkeypatch.setattr(gateway.aiohttp, 'TCPConnector', lambda **kwargs: captured.setdefault('connector', kwargs))

    async def invoke():
        async def on_text(_text): pass
        return await gateway.OpenAIResponsesAdapter().stream(gateway.OpenAIConfig('fixture', 'synthetic-key'),
            {'stream': True, 'store': False, 'background': False, 'tools': []}, on_text)

    if case == 'valid':
        assert asyncio.run(invoke())['text'] == TEXT
    else:
        with pytest.raises(GatewayError): asyncio.run(invoke())
    assert captured['endpoint'] == 'https://api.openai.com/v1/responses'
    assert captured['request']['allow_redirects'] is False
    assert captured['request']['headers']['Accept'] == 'text/event-stream'
    assert captured['client']['trust_env'] is False and captured['client']['timeout'].total == 60
    assert captured['client']['timeout'].connect == 8 and captured['connector']['use_dns_cache'] is False
    assert captured['closed'] == 2
