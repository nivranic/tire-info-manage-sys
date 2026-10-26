"""Bounded identity-encoded PDF acquisition, independent of parser transports."""
import asyncio
from datetime import datetime, timezone
import hashlib
import threading
import time
from urllib.parse import urljoin, urlsplit

import aiohttp
from yarl import URL

from .adapters.robots import RobotsPolicy
from .adapters.transport import PublicResolver, SourceAccessError, USER_AGENT
from .material_source_policy import checked_url
from .object_store import MAX_OBJECT_BYTES

TOTAL_SECONDS = 20


class MaterialTransportError(Exception):
    pass


def robots_failure_diagnostic(error):
    """Only this exact bounded observation may enter a failure audit."""
    if (type(error) is not MaterialTransportError or len(error.args) != 1
            or type(error.args[0]) is not str or error.args[0] != 'source_material_robots_unavailable'):
        return None
    fields = vars(error)
    if (len(fields) != 2 or any(type(key) is not str for key in fields)
            or set(fields) != {'phase', 'http_status'}):
        return None
    phase, status = fields['phase'], fields['http_status']
    if (type(phase) is not str or phase != 'robots_http_status' or type(status) is not int
            or not 100 <= status <= 599 or status in (200, 404, 410)):
        return None
    return {'phase': phase, 'http_status': status}


def now():
    return datetime.now(timezone.utc).isoformat()


def header_values(headers, name):
    return headers.getall(name, []) if hasattr(headers, 'getall') else [headers[name]] if name in headers else []


def has_content_type(response, expected):
    values = header_values(response.headers, 'Content-Type')
    return len(values) == 1 and values[0].split(';')[0].strip().lower() == expected


class MaterialSourceTransport:
    def __init__(self):
        self._lock = threading.Lock()
        self._active = 0
        self._hosts = set()
        self._last = {}
        self._interval = {}

    async def fetch(self, policy):
        with self._lock:
            if self._active >= 2:
                raise MaterialTransportError('source_material_busy')
            self._active += 1
        claimed = set()
        try:
            async with asyncio.timeout(TOTAL_SECONDS):
                return await self._fetch(policy, claimed)
        except MaterialTransportError:
            raise
        except TimeoutError:
            raise MaterialTransportError('source_material_timeout') from None
        except SourceAccessError:
            raise MaterialTransportError('source_material_address_blocked') from None
        except (aiohttp.ClientError, OSError, ValueError, UnicodeError):
            raise MaterialTransportError('source_material_network_failed') from None
        finally:
            with self._lock:
                self._active -= 1
                self._hosts.difference_update(claimed)

    async def _pace(self, host, claimed):
        with self._lock:
            interval = max(2.0, self._interval.get(host, 2.0))
            delay = self._last.get(host, -float('inf')) + interval - time.monotonic()
            if host not in claimed:
                if host in self._hosts or delay > 0:
                    raise MaterialTransportError('source_material_rate_limited')
                self._hosts.add(host)
                claimed.add(host)
        # Only sequencing within this same capture may wait, under the total deadline.
        if delay > 0:
            await asyncio.sleep(delay)
        with self._lock:
            self._last[host] = time.monotonic()

    async def _body(self, response, limit):
        # CIMultiDict.get returns only the first header: a second gzip/br value
        # must never be hidden by an initial identity value.
        encodings = header_values(response.headers, 'Content-Encoding')
        if len(encodings) > 1 or any(value.strip().lower() not in ('', 'identity') for value in encodings):
            raise MaterialTransportError('source_material_encoding_rejected')
        length = response.content_length
        if length is not None and (type(length) is not int or length < 0 or length > limit):
            raise MaterialTransportError('source_material_too_large')
        body = bytearray()
        async for chunk in response.content.iter_chunked(65536):
            if len(body) + len(chunk) > limit:
                raise MaterialTransportError('source_material_too_large')
            body.extend(chunk)
        if length is not None and length != len(body):
            raise MaterialTransportError('source_material_incomplete_body')
        return bytes(body)

    async def _robots(self, session, target, claimed):
        parsed = urlsplit(target)
        host = parsed.hostname
        robots_url = f'https://{parsed.netloc}/robots.txt'
        await self._pace(host, claimed)
        async with session.get(URL(robots_url, encoded=True), allow_redirects=False,
                headers={'Accept': 'text/plain'}) as response:
            status = response.status
            if status in (404, 410):
                body, rules = b'', RobotsPolicy('', USER_AGENT)
            elif status == 200:
                if not has_content_type(response, 'text/plain'):
                    raise MaterialTransportError('source_material_robots_invalid')
                body = await self._body(response, 64 * 1024)
                rules = RobotsPolicy(body.decode('utf-8', errors='strict'), USER_AGENT)
            else:
                error = MaterialTransportError('source_material_robots_unavailable')
                error.phase, error.http_status = 'robots_http_status', status
                raise error
        if not rules.can_fetch(target):
            raise MaterialTransportError('source_material_robots_disallowed')
        interval = max(2.0, rules.minimum_interval)
        with self._lock:
            self._interval[host] = interval
        entry = {'url': robots_url, 'status': status, 'raw_hash': hashlib.sha256(body).hexdigest() if status == 200 else None,
            'byte_count': len(body), 'allowed': True, 'minimum_interval': interval, 'target_url': target}
        return entry, body

    async def _fetch(self, policy, claimed):
        started = now()
        allowed = {checked_url(policy['download_url']), *[checked_url(url) for url in policy['redirect_urls']]}
        hosts = frozenset(urlsplit(url).hostname for url in allowed)
        connector = aiohttp.TCPConnector(resolver=PublicResolver(hosts), use_dns_cache=False, limit=2,
            family=0)
        async with aiohttp.ClientSession(connector=connector, trust_env=False, auto_decompress=False,
                timeout=aiohttp.ClientTimeout(total=TOTAL_SECONDS, connect=4, sock_read=8),
                headers={'User-Agent': USER_AGENT, 'Accept': 'application/pdf', 'Accept-Encoding': 'identity'},
                cookie_jar=aiohttp.DummyCookieJar()) as session:
            # aiohttp 3.x retries idempotent methods after a disconnected pooled
            # connection by default. One reservation authorizes one attempt only.
            session._retry_connection = False
            target = policy['download_url']
            visited, redirects, robots, robot_objects = set(), [], [], []
            for hop in range(4):
                if target not in allowed or target in visited:
                    raise MaterialTransportError('source_material_redirect_rejected')
                visited.add(target)
                checked_url(target)
                entry, robot_body = await self._robots(session, target, claimed)
                robots.append(entry)
                if robot_body:
                    robot_objects.append({'raw_hash': entry['raw_hash'], 'body': robot_body})
                await self._pace(urlsplit(target).hostname, claimed)
                async with session.get(URL(target, encoded=True), allow_redirects=False) as response:
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get('Location')
                        if not location or hop == 3 or any(ord(c) <= 32 for c in location):
                            raise MaterialTransportError('source_material_redirect_rejected')
                        next_url = urljoin(target, location)
                        checked_url(next_url)
                        if next_url not in allowed or next_url in visited:
                            raise MaterialTransportError('source_material_redirect_rejected')
                        redirects.append({'from_url': target, 'to_url': next_url, 'status': response.status})
                        target = next_url
                        continue
                    if response.status != 200:
                        raise MaterialTransportError('source_material_http_rejected')
                    if not has_content_type(response, 'application/pdf'):
                        raise MaterialTransportError('source_material_content_type_rejected')
                    body = await self._body(response, MAX_OBJECT_BYTES)
                    if not body.startswith(b'%PDF-'):
                        raise MaterialTransportError('source_material_pdf_marker_missing')
                    return {'body': body, 'initial_url': policy['download_url'], 'final_url': target,
                        'redirects': redirects, 'robots': robots, 'robot_objects': robot_objects,
                        'started_at': started, 'completed_at': now()}
        raise MaterialTransportError('source_material_redirect_rejected')
