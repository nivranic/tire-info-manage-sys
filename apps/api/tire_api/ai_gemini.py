"""Native Google generateContent and SSE projection onto the shared AI receipt."""
import asyncio
import re
import socket

import aiohttp

from .adapters.transport import PublicResolver, SourceAccessError
from .ai_gateway import GatewayError, MAX_RESPONSE_BYTES, safe_usage
from .ai_stream_parser import MAX_STREAM_BYTES, MAX_TEXT_BYTES, STRICT_JSON, _SSEDecoder

REFUSAL_REASONS = frozenset({'SAFETY', 'RECITATION', 'BLOCKLIST', 'PROHIBITED_CONTENT', 'SPII',
    'IMAGE_SAFETY', 'IMAGE_PROHIBITED_CONTENT', 'IMAGE_RECITATION', 'ESCALATION', 'PUP_LIMITED_DISABLED'})


def gemini_usage(value):
    if not isinstance(value, dict):
        return None
    names = ('promptTokenCount', 'candidatesTokenCount', 'thoughtsTokenCount', 'toolUsePromptTokenCount')
    counts = {name: value.get(name, 0) for name in names}
    if any(type(count) is not int or count < 0 for count in counts.values()):
        return None
    return safe_usage({'input_tokens': counts['promptTokenCount'] + counts['toolUsePromptTokenCount'],
        'output_tokens': counts['candidatesTokenCount'] + counts['thoughtsTokenCount'],
        'total_tokens': value.get('totalTokenCount')})


def _project(value):
    if not isinstance(value, dict):
        raise GatewayError('ai_response_invalid')
    identity = value.get('responseId')
    if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identity):
        identity = None
    result = {'provider_response_id': identity, 'usage': gemini_usage(value.get('usageMetadata')),
        'text': '', 'error': None, 'finish': None}
    feedback = value.get('promptFeedback', {})
    if not isinstance(feedback, dict):
        raise GatewayError('ai_response_invalid')
    if feedback.get('blockReason') not in (None, '', 'BLOCK_REASON_UNSPECIFIED'):
        return {**result, 'finish': 'blocked', 'error': 'ai_refused'}
    candidates = value.get('candidates', [])
    if not isinstance(candidates, list) or len(candidates) > 1:
        raise GatewayError('ai_response_invalid')
    if not candidates:
        return result
    candidate = candidates[0]
    if not isinstance(candidate, dict) or type(candidate.get('index', 0)) is not int or candidate.get('index', 0) != 0:
        raise GatewayError('ai_response_invalid')
    content = candidate.get('content', {})
    if not isinstance(content, dict) or content.get('role') not in (None, 'model'):
        raise GatewayError('ai_response_invalid')
    parts = content.get('parts', [])
    if not isinstance(parts, list):
        raise GatewayError('ai_response_invalid')
    texts = []
    for part in parts:
        if (not isinstance(part, dict) or set(part) - {'text', 'thought', 'thoughtSignature', 'partMetadata'}
                or type(part.get('thought', False)) is not bool):
            raise GatewayError('ai_response_invalid')
        if part.get('thought') is True:
            continue
        if 'text' not in part and isinstance(part.get('thoughtSignature'), str):
            continue
        if not isinstance(part.get('text'), str):
            raise GatewayError('ai_response_invalid')
        texts.append(part['text'])
    finish = candidate.get('finishReason')
    if finish in ('', 'FINISH_REASON_UNSPECIFIED'):
        finish = None
    if finish is not None and not isinstance(finish, str):
        raise GatewayError('ai_response_invalid')
    error = None
    if finish in ('MAX_TOKENS', 'CONTINUATION'):
        error = 'ai_response_incomplete'
    elif finish in REFUSAL_REASONS:
        error = 'ai_refused'
    elif finish not in (None, 'STOP'):
        error = 'ai_response_invalid'
    return {**result, 'text': ''.join(texts), 'finish': finish, 'error': error}


def extract_gemini_response(value):
    try:
        projected = _project(value)
    except GatewayError:
        return {'usage': None, 'provider_response_id': None, 'text': None, 'error': 'ai_response_invalid'}
    result = {key: projected[key] for key in ('usage', 'provider_response_id', 'text', 'error')}
    if projected['error']:
        return {**result, 'text': None}
    if projected['finish'] is None or not projected['text'] or len(projected['text'].encode()) > MAX_TEXT_BYTES:
        return {**result, 'text': None, 'error': 'ai_response_invalid'}
    return result


async def parse_gemini_stream(chunks, on_text):
    decoder = _SSEDecoder()
    text, response_id, usage, finish, error = '', None, None, None, None
    text_bytes = 0

    async def consume(value):
        nonlocal text, response_id, usage, finish, error, text_bytes
        projected = _project(value)
        identity = projected['provider_response_id']
        if identity is not None:
            if response_id is not None and response_id != identity:
                raise GatewayError('ai_stream_protocol_error')
            response_id = identity
        if finish is not None:
            if value.get('candidates') or projected['finish'] is not None:
                raise GatewayError('ai_stream_protocol_error')
            if 'usageMetadata' in value:
                usage = projected['usage']
            return
        piece = projected['text']
        text_bytes += len(piece.encode())
        if text_bytes > MAX_TEXT_BYTES:
            raise GatewayError('ai_response_too_large')
        text += piece
        if piece:
            await on_text(piece)
        if projected['finish'] is not None:
            finish, error, usage = projected['finish'], projected['error'], projected['usage']

    async for raw in chunks:
        for value in decoder.feed(raw):
            await consume(value)
    for value in decoder.feed(final=True):
        await consume(value)
    if decoder.buffer.strip() or decoder.data or decoder.event is not None:
        raise GatewayError('ai_stream_protocol_error')
    if finish is None:
        raise GatewayError('ai_stream_interrupted')
    if error is None and not text:
        error = 'ai_response_invalid'
    return {'usage': usage, 'provider_response_id': response_id, 'text': None if error else text, 'error': error}


class GeminiAdapter:
    async def generate(self, config, body):
        return await self._request(config, body)

    async def stream(self, config, body, on_text):
        return await self._request(config, body, on_text)

    async def _request(self, config, body, on_text=None):
        if (config.provider != 'gemini' or not isinstance(body, dict)
                or not isinstance(body.get('contents'), list) or not isinstance(body.get('systemInstruction'), dict)
                or not isinstance(body.get('generationConfig'), dict) or 'input' in body or 'messages' in body
                or not config.endpoint.endswith(':generateContent')):
            raise GatewayError('ai_configuration_invalid')
        streaming = on_text is not None
        endpoint = config.endpoint.removesuffix(':generateContent') + ':streamGenerateContent' if streaming else config.endpoint
        headers = {'x-goog-api-key': config.api_key, 'Content-Type': 'application/json',
            'Accept': 'text/event-stream' if streaming else 'application/json'}
        connector = aiohttp.TCPConnector(resolver=PublicResolver(frozenset({config.allowed_host})),
            use_dns_cache=False, family=socket.AF_UNSPEC, limit=1)
        limit = MAX_STREAM_BYTES if streaming else MAX_RESPONSE_BYTES
        try:
            async with aiohttp.ClientSession(connector=connector, trust_env=False,
                    cookie_jar=aiohttp.DummyCookieJar(), timeout=aiohttp.ClientTimeout(total=60, connect=8)) as client:
                async with client.post(endpoint, json=body, headers=headers, allow_redirects=False,
                        params={'alt': 'sse'} if streaming else None) as response:
                    if response.status != 200:
                        raise GatewayError('ai_provider_http_error')
                    if response.headers.get('Content-Type', '').split(';')[0].strip().lower() != headers['Accept']:
                        raise GatewayError('ai_response_invalid')
                    if response.content_length is not None and response.content_length > limit:
                        raise GatewayError('ai_response_too_large')
                    if streaming:
                        return await parse_gemini_stream(response.content.iter_chunked(16384), on_text)
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        if len(raw) + len(chunk) > limit:
                            raise GatewayError('ai_response_too_large')
                        raw.extend(chunk)
                    try:
                        value = STRICT_JSON.decode(raw.decode('utf-8'))
                    except GatewayError:
                        raise GatewayError('ai_response_invalid') from None
                    return extract_gemini_response(value)
        except GatewayError:
            raise
        except (TimeoutError, asyncio.TimeoutError):
            raise GatewayError('ai_provider_timeout') from None
        except (aiohttp.ClientError, SourceAccessError, OSError):
            raise GatewayError('ai_provider_network_error') from None
        except (UnicodeError, ValueError, TypeError, RecursionError):
            raise GatewayError('ai_response_invalid') from None
