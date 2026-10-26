"""One bounded POST, with DNS enforcement in the actual HTTPS connector."""
import asyncio
import hashlib
import hmac
import re

import aiohttp

from .adapters.transport import PublicResolver, SourceAccessError
from .webhook_policy import endpoint_host


def signed_headers(target, delivery_id, number, timestamp, raw_body):
    prefix = (timestamp + '.' + delivery_id + '.' + str(number) + '.').encode('ascii')
    signature = hmac.new(target.key, prefix + raw_body, hashlib.sha256).hexdigest()
    return {'Content-Type': 'application/json', 'X-Tire-Webhook-Id': delivery_id,
        'X-Tire-Webhook-Attempt': str(number), 'X-Tire-Webhook-Timestamp': timestamp,
        'X-Tire-Webhook-Signature': 'v1=' + signature}


class WebhookTransport:
    async def send(self, target, raw_body, headers):
        try:
            if endpoint_host(target.url) != target.endpoint_host or target.key is None:
                raise ValueError()
            connector = aiohttp.TCPConnector(resolver=PublicResolver(frozenset({target.endpoint_host})),
                use_dns_cache=False, force_close=True, limit=1)
            async with aiohttp.ClientSession(connector=connector, trust_env=False, auto_decompress=False,
                    cookie_jar=aiohttp.DummyCookieJar(), timeout=aiohttp.ClientTimeout(total=8, connect=4)) as session:
                async with session.post(target.url, data=raw_body, headers=headers, allow_redirects=False) as response:
                    if response.content_length is not None and response.content_length > 65536:
                        return {'http_status': response.status, 'error_code': 'webhook_response_too_large', 'retry_after': None}
                    size = 0
                    async for part in response.content.iter_chunked(8192):
                        size += len(part)
                        if size > 65536:
                            return {'http_status': response.status, 'error_code': 'webhook_response_too_large', 'retry_after': None}
                    value = response.headers.get('Retry-After', '')
                    retry_after = min(3600, max(1, int(value))) if (response.status in (429, 503)
                        and re.fullmatch(r'[0-9]{1,10}', value)) else None
                    return {'http_status': response.status, 'error_code': None, 'retry_after': retry_after}
        except asyncio.TimeoutError:
            return {'http_status': None, 'error_code': 'webhook_timeout', 'retry_after': None}
        except (SourceAccessError, ValueError):
            return {'http_status': None, 'error_code': 'webhook_target_blocked', 'retry_after': None}
        except (aiohttp.ClientError, OSError) as error:
            cause = error
            for _ in range(5):
                if isinstance(cause, SourceAccessError):
                    return {'http_status': None, 'error_code': 'webhook_target_blocked', 'retry_after': None}
                cause = getattr(cause, '__cause__', None)
                if cause is None:
                    break
            return {'http_status': None, 'error_code': 'webhook_network_error', 'retry_after': None}
