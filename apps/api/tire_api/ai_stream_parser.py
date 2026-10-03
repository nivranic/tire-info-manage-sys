"""Bounded Responses SSE decoding and complete, grounded JSON draft projection."""
import codecs
import json
import re
from types import SimpleNamespace

from .ai_gateway import GatewayError, extract_response, safe_usage

MAX_STREAM_BYTES = 4 * 1024 * 1024
MAX_FRAME_BYTES = 512 * 1024
MAX_STREAM_EVENTS = 16384
MAX_TEXT_BYTES = 64000


def _fail(code='ai_stream_protocol_error'):
    raise GatewayError(code)


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            _fail()
        value[key] = item
    return value


def _constant(_value):
    _fail()


STRICT_JSON = json.JSONDecoder(object_pairs_hook=_pairs, parse_constant=_constant)


class _SSEDecoder:
    def __init__(self):
        self.decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self.buffer = ''
        self.data = []
        self.event = None
        self.total = self.frame_size = self.events = 0

    def feed(self, raw=b'', *, final=False):
        if not isinstance(raw, bytes):
            _fail()
        self.total += len(raw)
        if self.total > MAX_STREAM_BYTES:
            _fail('ai_response_too_large')
        try:
            self.buffer += self.decoder.decode(raw, final=final)
        except UnicodeError:
            _fail()
        output = []
        while match := re.search(r'[\r\n]', self.buffer):
            at = match.start()
            if self.buffer[at] == '\r' and at + 1 == len(self.buffer) and not final:
                break
            skip = 2 if self.buffer[at:at + 2] == '\r\n' else 1
            line, self.buffer = self.buffer[:at], self.buffer[at + skip:]
            self.frame_size += len(line.encode('utf-8')) + skip
            if self.frame_size > MAX_FRAME_BYTES:
                _fail('ai_response_too_large')
            if not line:
                if self.data:
                    try:
                        value = STRICT_JSON.decode('\n'.join(self.data))
                    except (ValueError, RecursionError):
                        _fail()
                    if not isinstance(value, dict) or self.event is not None and self.event != value.get('type'):
                        _fail()
                    self.events += 1
                    if self.events > MAX_STREAM_EVENTS:
                        _fail('ai_response_too_large')
                    output.append(value)
                self.data, self.event, self.frame_size = [], None, 0
            elif not line.startswith(':'):
                field, _, value = line.partition(':')
                value = value[1:] if value.startswith(' ') else value
                if field == 'data':
                    self.data.append(value)
                elif field == 'event':
                    if self.event is not None:
                        _fail()
                    self.event = value
                # SSE id/retry are transport hints, never execution or billing instructions.
        if self.frame_size + len(self.buffer.encode('utf-8')) > MAX_FRAME_BYTES:
            _fail('ai_response_too_large')
        return output


class _ResponseDecoder:
    def __init__(self):
        self.sequence = -1
        self.response_id = None
        self.items = {}
        self.finished_items = set()
        self.parts = {}
        self.text = ''
        self.refused = False

    def _part(self, event):
        output, content = event.get('output_index'), event.get('content_index')
        if type(output) is not int or type(content) is not int or output < 0 or content < 0:
            _fail()
        key = (output, content)
        item = self.items.get(output)
        if not item or item[0] != event.get('item_id') or item[1] != 'message':
            _fail()
        return key

    def _validate_item(self, index, item):
        if type(index) is not int or not isinstance(item, dict) or self.items.get(index) != (item.get('id'), item.get('type')):
            _fail()
        if item['type'] == 'reasoning':
            return  # Identity only; reasoning bodies are neither projected nor persisted.
        if item.get('role') != 'assistant' or item.get('status') != 'completed' or not isinstance(item.get('content'), list):
            _fail()
        parts = {content: part for (output, content), part in self.parts.items() if output == index}
        if set(parts) != set(range(len(item['content']))):
            _fail()
        for content, value in enumerate(item['content']):
            part = parts[content]
            if (not part['done'] or not isinstance(value, dict) or value.get('type') != part['type']
                    or value.get('refusal' if part['type'] == 'refusal' else 'text') != part['text']):
                _fail()

    def consume(self, event):
        sequence, kind = event.get('sequence_number'), event.get('type')
        if type(sequence) is not int or sequence <= self.sequence or not isinstance(kind, str):
            _fail()
        self.sequence = sequence
        if kind == 'response.created':
            value = event.get('response')
            if self.response_id is not None or not isinstance(value, dict):
                _fail()
            response_id = value.get('id')
            if not isinstance(response_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', response_id):
                _fail()
            self.response_id = response_id
            return None, None
        if self.response_id is None:
            _fail()
        if kind == 'response.in_progress':
            if not isinstance(event.get('response'), dict) or event['response'].get('id') != self.response_id:
                _fail()
        elif kind == 'response.output_item.added':
            index, item = event.get('output_index'), event.get('item')
            if type(index) is not int or index < 0 or index in self.items or not isinstance(item, dict):
                _fail()
            item_id, item_type = item.get('id'), item.get('type')
            if not isinstance(item_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', item_id):
                _fail()
            if any(value[0] == item_id for value in self.items.values()):
                _fail()
            if item_type not in {'message', 'reasoning'} or item_type == 'message' and item.get('role') != 'assistant':
                _fail()
            if item_type == 'message' and any(value[1] == 'message' for value in self.items.values()):
                _fail()  # One structured JSON answer, never interleaved messages.
            self.items[index] = (item_id, item_type)
        elif kind == 'response.content_part.added':
            key, part = self._part(event), event.get('part')
            if key in self.parts or not isinstance(part, dict) or part.get('type') not in {'output_text', 'refusal'}:
                _fail()
            if part['type'] == 'output_text' and (self.parts or part.get('text', '') != ''):
                _fail()
            self.parts[key] = {'type': part['type'], 'text': '', 'done': False}
            self.refused |= part['type'] == 'refusal'
        elif kind in {'response.output_text.delta', 'response.output_text.done', 'response.refusal.delta', 'response.refusal.done'}:
            key = self._part(event)
            part = self.parts.get(key)
            refusal = kind.startswith('response.refusal.')
            if not part or part['type'] != ('refusal' if refusal else 'output_text') or part['done']:
                _fail()
            if kind.endswith('.delta'):
                delta = event.get('delta')
                if not isinstance(delta, str):
                    _fail()
                part['text'] += delta
                try:
                    size = len(part['text'].encode('utf-8'))
                except UnicodeError:
                    _fail()
                if size > MAX_TEXT_BYTES:
                    _fail('ai_response_too_large')
                if not refusal:
                    self.text += delta
                    return delta, None
            else:
                if event.get('refusal' if refusal else 'text') != part['text']:
                    _fail()
                part['done'] = True
        elif kind == 'response.content_part.done':
            part = self.parts.get(self._part(event))
            value = event.get('part')
            if not part or not part['done'] or not isinstance(value, dict) or value.get('type') != part['type']:
                _fail()
            if value.get('refusal' if part['type'] == 'refusal' else 'text') != part['text']:
                _fail()
        elif kind == 'response.output_item.done':
            item, index = event.get('item'), event.get('output_index')
            self._validate_item(index, item)
            if index in self.finished_items:
                _fail()
            self.finished_items.add(index)
        elif kind.startswith('response.reasoning'):
            pass  # No reasoning trace, summary, logprob or raw event leaves this decoder.
        elif kind in {'response.completed', 'response.failed', 'response.incomplete'}:
            value = event.get('response')
            status = kind.removeprefix('response.')
            if not isinstance(value, dict) or value.get('id') != self.response_id or value.get('status') != status:
                _fail()
            if status != 'completed':
                return None, {'text': None, 'error': 'ai_provider_failed' if status == 'failed' else 'ai_response_incomplete',
                              'usage': safe_usage(value.get('usage')), 'provider_response_id': self.response_id}
            output = value.get('output')
            if not isinstance(output, list) or set(self.items) != set(range(len(output))):
                _fail()
            for index, item in enumerate(output):
                self._validate_item(index, item)
            receipt = extract_response(value)
            if self.refused or receipt['error'] == 'ai_refused':
                return None, {**receipt, 'text': None, 'error': 'ai_refused'}
            if receipt['error']:
                return None, receipt
            if not self.parts or any(not part['done'] for part in self.parts.values()) or receipt['text'] != self.text:
                _fail()
            return None, receipt
        elif kind == 'error':
            return None, {'text': None, 'error': 'ai_provider_failed', 'usage': None, 'provider_response_id': self.response_id}
        else:
            _fail()
        return None, None


async def parse_response_stream(chunks, on_text):
    """Production parser, also callable with private synthetic byte iterators."""
    sse, response = _SSEDecoder(), _ResponseDecoder()
    async for chunk in chunks:
        for event in sse.feed(chunk):
            delta, receipt = response.consume(event)
            if delta is not None:
                await on_text(delta)
            if receipt is not None:
                return receipt
    for event in sse.feed(final=True):
        delta, receipt = response.consume(event)
        if delta is not None:
            await on_text(delta)
        if receipt is not None:
            return receipt
    _fail('ai_stream_interrupted')


class StructuredDraftProjector:
    """Only complete claim objects/string values are provisionally projected."""
    def __init__(self, pack):
        self.pack = SimpleNamespace(payload=pack['payload'], data_state=pack['data_state'])
        self.text = ''
        self.position = 0
        self.state = 'start'
        self.keys = set()
        self.key = None
        self.claims = []

    def _value(self):
        try:
            value, end = STRICT_JSON.raw_decode(self.text, self.position)
        except json.JSONDecodeError:
            return None
        except (GatewayError, ValueError, RecursionError):
            _fail('ai_grounding_validation_failed')
        self.position = end
        return (value,)

    def feed(self, delta):
        from .ai_analysis import grounded_answer
        if not isinstance(delta, str):
            _fail('ai_grounding_validation_failed')
        self.text += delta
        try:
            size = len(self.text.encode('utf-8'))
        except UnicodeError:
            _fail('ai_grounding_validation_failed')
        if size > MAX_TEXT_BYTES:
            _fail('ai_response_too_large')
        output = []
        while True:
            while self.position < len(self.text) and self.text[self.position] in ' \t\r\n':
                self.position += 1
            if self.position == len(self.text):
                return output
            char = self.text[self.position]
            state = self.state
            if state == 'start':
                if char != '{': _fail('ai_grounding_validation_failed')
                self.position += 1
                self.state = 'key_first'
            elif state in {'key_first', 'key_next'}:
                if char == '}' and state == 'key_first':
                    self.position += 1
                    self.state = 'done'
                    continue
                if char != '"': _fail('ai_grounding_validation_failed')
                parsed = self._value()
                if parsed is None: return output
                self.key = parsed[0]
                if self.key not in {'claims', 'uncertainty'} or self.key in self.keys:
                    _fail('ai_grounding_validation_failed')
                self.keys.add(self.key)
                self.state = 'colon'
            elif state == 'colon':
                if char != ':': _fail('ai_grounding_validation_failed')
                self.position += 1
                self.state = 'value'
            elif state == 'value':
                if self.key == 'claims':
                    if char != '[': _fail('ai_grounding_validation_failed')
                    self.position += 1
                    self.state = 'claim_first'
                else:
                    if char != '"': _fail('ai_grounding_validation_failed')
                    parsed = self._value()
                    if parsed is None: return output
                    if len(parsed[0]) > 2000: _fail('ai_grounding_validation_failed')
                    try:
                        from .ai_recall_contract import validate_recall_uncertainty
                        validate_recall_uncertainty(parsed[0], self.pack.payload)
                    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
                        _fail('ai_grounding_validation_failed')
                    output.append({'type': 'uncertainty_draft', 'payload': {'text': parsed[0]}})
                    self.state = 'after_value'
            elif state in {'claim_first', 'claim_next'}:
                if char == ']' and state == 'claim_first':
                    self.position += 1
                    self.state = 'after_value'
                    continue
                if char != '{' or len(self.claims) >= 12: _fail('ai_grounding_validation_failed')
                parsed = self._value()
                if parsed is None: return output
                try:
                    claim = grounded_answer(json.dumps({'claims': [parsed[0]], 'uncertainty': ''}), self.pack)['claims'][0]
                except (ValueError, TypeError, KeyError, RecursionError):
                    _fail('ai_grounding_validation_failed')
                output.append({'type': 'claim_draft', 'payload': {'index': len(self.claims), 'claim': claim}})
                self.claims.append(claim)
                self.state = 'after_claim'
            elif state == 'after_claim':
                if char not in ',]': _fail('ai_grounding_validation_failed')
                self.position += 1
                self.state = 'claim_next' if char == ',' else 'after_value'
            elif state == 'after_value':
                if char not in ',}': _fail('ai_grounding_validation_failed')
                self.position += 1
                self.state = 'key_next' if char == ',' else 'done'
            else:
                _fail('ai_grounding_validation_failed')

    def finish(self):
        from .ai_analysis import grounded_answer
        if self.state != 'done' or self.keys != {'claims', 'uncertainty'}:
            _fail('ai_grounding_validation_failed')
        try:
            STRICT_JSON.decode(self.text)
            answer = grounded_answer(self.text, self.pack)
        except (ValueError, TypeError, KeyError, RecursionError):
            _fail('ai_grounding_validation_failed')
        if answer['claims'] != self.claims:
            _fail('ai_grounding_validation_failed')
        return answer
