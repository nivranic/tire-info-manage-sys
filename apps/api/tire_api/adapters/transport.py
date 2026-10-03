"""Bounded HTTPS transport with DNS validation in the actual connector.

The approved hostname remains the TLS SNI/certificate name. Only public addresses
returned by this resolver reach the socket; there is no second unchecked lookup.
Environment proxies are intentionally not inherited by the crawler.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver

USER_AGENT = "TireEvidenceResearch/0.1 (deterministic specification query)"
MAX_BODY_BYTES = 8 * 1024 * 1024

# Static attribution only; never export a request URL, query, or unknown host.
_TELEMETRY_SOURCES = {
    'www.michelinman.com': 'michelin-us', 'www.michelin.com.cn': 'michelin-cn',
    'www.michelin.co.uk': 'michelin-uk', 'www.michelin.fr': 'michelin-fr',
    'www.michelin.de': 'michelin-de', 'www.toyotires.com': 'toyo-us',
    'www.hankooktire.com': 'hankook-us', 'www.pirelli.com': 'pirelli-us',
    'website-api.xiaomiev.com': 'xiaomi-su7', 'www.xiaomiev.com': 'xiaomi-su7',
    'api.nhtsa.gov': 'nhtsa',
}


class SourceAccessError(Exception):
    """Safe error codes only, never request headers or credentials."""


def validate_url(url: str, allowed_hosts: frozenset[str]) -> str:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in allowed_hosts
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or "\\" in url
        ):
            raise SourceAccessError("url_not_allowed")
        return parsed.hostname
    except ValueError as exc:
        raise SourceAccessError("url_not_allowed") from exc


def validate_public_ip(address: str) -> None:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise SourceAccessError("invalid_dns_address") from exc
    # Also reject IPv4-in-IPv6, transition/tunnel addresses and scoped addresses.
    if (
        not ip.is_global or ip.is_multicast or ip.is_unspecified
        or "%" in address
        or isinstance(ip, ipaddress.IPv6Address)
        and (ip.ipv4_mapped is not None or ip.sixtofour is not None or ip.teredo is not None)
    ):
        raise SourceAccessError("non_public_address")


class PublicResolver(AbstractResolver):
    def __init__(self, hosts: frozenset[str]) -> None:
        self.hosts = hosts

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        if host not in self.hosts:
            raise SourceAccessError("host_not_allowed")
        records = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=family, type=socket.SOCK_STREAM
        )
        if not records:
            raise SourceAccessError("dns_empty")
        result = []
        seen = set()
        for af, _, proto, _, sockaddr in records:
            address = sockaddr[0]
            validate_public_ip(address)
            if (af, address) in seen:
                continue
            seen.add((af, address))
            result.append({"hostname": host, "host": address, "port": port,
                           "family": af, "proto": proto, "flags": socket.AI_NUMERICHOST})
        return result

    async def close(self) -> None:
        pass


@dataclass(frozen=True)
class FetchResult:
    status: int
    url: str
    body: str
    content_type: str
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class BinaryFetchResult:
    status: int
    url: str
    body: bytes
    content_type: str
    etag: str | None
    last_modified: str | None


class SafeHttpClient:
    def __init__(self, hosts: frozenset[str]) -> None:
        self.hosts = hosts
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(
            resolver=PublicResolver(self.hosts), use_dns_cache=False, limit=2,
            family=socket.AF_UNSPEC,
        )
        self.session = aiohttp.ClientSession(
            connector=connector, trust_env=False,
            timeout=aiohttp.ClientTimeout(total=8, connect=4),
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.8"},
            cookie_jar=aiohttp.DummyCookieJar(),
        )
        return self

    async def __aexit__(self, *_):
        if self.session:
            await self.session.close()

    async def get(self, url: str, **kwargs) -> FetchResult:
        return await self._request("GET", url, **kwargs)

    async def get_bytes(self, url: str, **kwargs) -> BinaryFetchResult:
        return await self._request("GET", url, binary=True, **kwargs)

    async def post(self, url: str, *, json_body, **kwargs) -> FetchResult:
        """Only for fixed, reviewed read-only catalog APIs, never user URLs."""
        return await self._request("POST", url, json_body=json_body, **kwargs)

    async def _request(self, method: str, url: str, *, headers: dict | None = None, json_body=None,
                  allowed_types: tuple[str, ...] = ("text/html",),
                  max_bytes: int = MAX_BODY_BYTES, can_follow=None,
                  allowed_statuses: tuple[int, ...] = (200,), binary: bool = False) -> FetchResult | BinaryFetchResult:
        from ..telemetry import observe
        try:
            host = urlsplit(url).hostname
        except ValueError:
            host = None
        source = _TELEMETRY_SOURCES.get(host, 'unknown') if host in self.hosts else 'unknown'
        with observe('source.http', component='crawler', source=source) as operation:
            return await self._request_observed(method, url, headers=headers, json_body=json_body,
                allowed_types=allowed_types, max_bytes=max_bytes, can_follow=can_follow,
                allowed_statuses=allowed_statuses, binary=binary, operation=operation)

    async def _request_observed(self, method: str, url: str, *, headers: dict | None, json_body,
                  allowed_types: tuple[str, ...], max_bytes: int, can_follow,
                  allowed_statuses: tuple[int, ...], binary: bool, operation) -> FetchResult | BinaryFetchResult:
        if not self.session:
            raise RuntimeError("client_not_open")
        conditional_headers = headers or {}
        result_type = BinaryFetchResult if binary else FetchResult
        empty_body = b"" if binary else ""
        for hop in range(4):
            validate_url(url, self.hosts)
            request = (self.session.get(url, headers=conditional_headers, allow_redirects=False)
                       if method == "GET" else self.session.post(url, json=json_body,
                                                               headers=conditional_headers, allow_redirects=False))
            async with request as response:
                operation.finish('not_modified' if response.status == 304 else 'success', http_status=response.status)
                if response.status in (301, 302, 303, 307, 308):
                    if method != "GET":
                        raise SourceAccessError("post_redirect_not_allowed")
                    location = response.headers.get("Location")
                    if not location or hop == 3:
                        raise SourceAccessError("redirect_limit")
                    next_url = urljoin(url, location)
                    validate_url(next_url, self.hosts)
                    if can_follow is not None and not can_follow(next_url):
                        raise SourceAccessError("redirect_not_allowed")
                    # Validators belong to a resource, not a different redirect target.
                    conditional_headers = {}
                    url = next_url
                    continue
                if response.status == 304:
                    if not conditional_headers:
                        raise SourceAccessError("unexpected_304")
                    return result_type(304, str(response.url), empty_body, "",
                                       response.headers.get("ETag"), response.headers.get("Last-Modified"))
                if response.status not in allowed_statuses:
                    raise SourceAccessError(f"upstream_http_{response.status}")
                if response.status != 200:
                    # Explicit exceptions are for absent robots.txt (404/410), not
                    # product pages. Do not parse or retain arbitrary error bodies.
                    return result_type(response.status, str(response.url), empty_body, "", None, None)
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type not in allowed_types:
                    raise SourceAccessError("unsupported_content_type")
                if response.content_length is not None and response.content_length > max_bytes:
                    raise SourceAccessError("response_too_large")
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise SourceAccessError("response_too_large")
                try:
                    text = bytes(body) if binary else body.decode(response.charset or "utf-8", errors="strict")
                except (UnicodeError, LookupError) as exc:
                    raise SourceAccessError("unsupported_encoding") from exc
                return result_type(response.status, str(response.url), text, content_type,
                                   response.headers.get("ETag"), response.headers.get("Last-Modified"))
        raise SourceAccessError("redirect_limit")
