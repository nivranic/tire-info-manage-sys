"""Native OpenAI Embeddings transport with a fixed public endpoint and strict output."""
import asyncio
from dataclasses import dataclass, field
import json
import math
import os
import re
import socket
import struct

import aiohttp

from .adapters.transport import PublicResolver, SourceAccessError
from .domain import digest

ENDPOINT = 'https://api.openai.com/v1/embeddings'
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
SAFE_ERRORS = {'embeddings_disabled', 'embeddings_configuration_required', 'embeddings_configuration_invalid',
               'embeddings_http_error', 'embeddings_response_invalid', 'embeddings_response_too_large',
               'embeddings_timeout', 'embeddings_network_error', 'embeddings_provider_failed',
               'embeddings_result_stale', 'embeddings_storage_failed'}


class EmbeddingError(Exception):
    pass


def safe_error(value):
    return value if isinstance(value, str) and value in SAFE_ERRORS else 'embeddings_provider_failed'


def setting(name, default, minimum, maximum):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise EmbeddingError('embeddings_configuration_invalid') from None
    if not minimum <= value <= maximum:
        raise EmbeddingError('embeddings_configuration_invalid')
    return value


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str
    dimensions: int
    api_key: str = field(repr=False)
    daily_token_limit: int = 100000
    daily_request_limit: int = 20
    allow_private: bool = False

    @property
    def model_space(self):
        return digest({'provider': 'openai_embeddings', 'model': self.model, 'dimensions': self.dimensions})


def configured_embeddings():
    if os.getenv('TI_EMBEDDINGS_ENABLED', '0') != '1':
        raise EmbeddingError('embeddings_disabled')
    model = os.getenv('TI_OPENAI_EMBEDDING_MODEL', '')
    key = os.getenv('TI_OPENAI_API_KEY', '')
    if not model or not key or not os.getenv('TI_OPENAI_EMBEDDING_DIMENSIONS'):
        raise EmbeddingError('embeddings_configuration_required')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,119}', model) or any(c.isspace() for c in key):
        raise EmbeddingError('embeddings_configuration_invalid')
    return EmbeddingConfig(model, setting('TI_OPENAI_EMBEDDING_DIMENSIONS', 0, 1, 2000), key,
        setting('TI_AI_DAILY_TOKEN_LIMIT', 100000, 1000, 10000000),
        setting('TI_AI_DAILY_REQUEST_LIMIT', 20, 1, 1000), os.getenv('TI_AI_ALLOW_PRIVATE', '0') == '1')


def model_status():
    try:
        config = configured_embeddings()
    except EmbeddingError as error:
        return {'state': str(error), 'model': None, 'dimensions': None}
    return {'state': 'configured', 'model': config.model, 'dimensions': config.dimensions}


def valid_vector(value, dimensions):
    if not isinstance(value, list) or len(value) != dimensions:
        raise EmbeddingError('embeddings_response_invalid')
    if any(type(number) not in (float, int) or abs(number) > 1e20 or not math.isfinite(number) for number in value):
        raise EmbeddingError('embeddings_response_invalid')
    # pgvector stores float32. Validate those actual representable values rather
    # than accepting a Python-only nonzero vector which becomes zero on write.
    vector = [struct.unpack('f', struct.pack('f', float(number)))[0] for number in value]
    norm_squared = math.fsum(number * number for number in vector)
    if not 1e-30 <= norm_squared <= 1e30:
        raise EmbeddingError('embeddings_response_invalid')
    return vector


def valid_usage(value):
    if not isinstance(value, dict):
        return None
    prompt, total = value.get('prompt_tokens'), value.get('total_tokens')
    if type(prompt) is not int or type(total) is not int or prompt != total or not 0 <= total <= 100000000:
        return None
    return {'input_tokens': prompt, 'output_tokens': 0, 'total_tokens': total}


def extract_embeddings(value, config, count):
    if not isinstance(value, dict) or value.get('model') != config.model or value.get('object') != 'list':
        raise EmbeddingError('embeddings_response_invalid')
    data, usage = value.get('data'), valid_usage(value.get('usage'))
    if not isinstance(data, list) or len(data) != count or usage is None:
        raise EmbeddingError('embeddings_response_invalid')
    found = {}
    for item in data:
        if not isinstance(item, dict) or item.get('object') != 'embedding' or type(item.get('index')) is not int:
            raise EmbeddingError('embeddings_response_invalid')
        index = item['index']
        if index not in range(count) or index in found:
            raise EmbeddingError('embeddings_response_invalid')
        found[index] = valid_vector(item.get('embedding'), config.dimensions)
    return {'vectors': [found[index] for index in range(count)], 'usage': usage}


def validate_receipt(receipt, config, count):
    from .ai_gateway import safe_usage
    if not isinstance(receipt, dict) or not isinstance(receipt.get('vectors'), list) or len(receipt['vectors']) != count:
        raise EmbeddingError('embeddings_response_invalid')
    usage = safe_usage(receipt.get('usage'))
    if usage is None or usage['output_tokens'] != 0:
        raise EmbeddingError('embeddings_response_invalid')
    return {'vectors': [valid_vector(item, config.dimensions) for item in receipt['vectors']], 'usage': usage}


def reservation(inputs):
    return sum(len(value.encode('utf-8')) for value in inputs) + 1024 + 64 * len(inputs)


class OpenAIEmbeddingAdapter:
    async def embed(self, config, inputs):
        if (not isinstance(inputs, list) or not 1 <= len(inputs) <= 32
                or any(not isinstance(value, str) or not value or len(value.encode('utf-8')) > 6000 for value in inputs)
                or sum(len(value.encode('utf-8')) for value in inputs) > 100000):
            raise EmbeddingError('embeddings_configuration_invalid')
        body = {'model': config.model, 'input': inputs, 'encoding_format': 'float', 'dimensions': config.dimensions}
        connector = aiohttp.TCPConnector(resolver=PublicResolver(frozenset({'api.openai.com'})),
                                         use_dns_cache=False, family=socket.AF_UNSPEC, limit=1)
        try:
            async with aiohttp.ClientSession(connector=connector, trust_env=False,
                    cookie_jar=aiohttp.DummyCookieJar(), timeout=aiohttp.ClientTimeout(total=60, connect=8)) as client:
                async with client.post(ENDPOINT, json=body, allow_redirects=False,
                        headers={'Authorization': 'Bearer ' + config.api_key, 'Content-Type': 'application/json'}) as response:
                    if response.status != 200:
                        raise EmbeddingError('embeddings_http_error')
                    if response.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                        raise EmbeddingError('embeddings_response_invalid')
                    if response.content_length is not None and response.content_length > MAX_RESPONSE_BYTES:
                        raise EmbeddingError('embeddings_response_too_large')
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise EmbeddingError('embeddings_response_too_large')
                        raw.extend(chunk)
                    return extract_embeddings(json.loads(raw.decode('utf-8')), config, len(inputs))
        except EmbeddingError:
            raise
        except (TimeoutError, asyncio.TimeoutError):
            raise EmbeddingError('embeddings_timeout') from None
        except (aiohttp.ClientError, SourceAccessError, OSError):
            raise EmbeddingError('embeddings_network_error') from None
        except (UnicodeError, ValueError, TypeError, RecursionError):
            raise EmbeddingError('embeddings_response_invalid') from None
