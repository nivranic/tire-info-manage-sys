"""Fixed official sources, per-origin robots policy and bounded online fetches."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import os
import re
import time
from dataclasses import dataclass, fields
from functools import partial
from typing import Callable
from urllib.parse import urlsplit

import aiohttp

from .michelin import parse_michelin_html
from .michelin_regions import MICHELIN_REGIONS
from . import hankook, toyo, pirelli
from .robots import RobotsPolicy
from .transport import SafeHttpClient, SourceAccessError, USER_AGENT
from ..captures import CaptureWriteError, parser_failure_reason
from ..parser_runtime import ParserRunError, current_parser, parse_isolated

supports_parser_deployments = True


def pin_parser_selection(source_id: str, target_kind: str, selection: dict | None,
                         *, builtin_descriptor: dict | None = None) -> tuple[dict, dict, dict]:
    """Freeze a trusted selection before networking; never select again in flight."""
    try:
        if selection is None:
            descriptor = deepcopy(builtin_descriptor if builtin_descriptor is not None else current_parser(source_id))
            manifest, revision = None, None
        else:
            from ..parser_bundles import BundleError, bundle_descriptor
            frozen = deepcopy(selection)
            if (not isinstance(frozen, dict) or frozen.get('source_id') != source_id
                    or not isinstance(frozen.get('query_run_id'), str) or not 1 <= len(frozen['query_run_id']) <= 64
                    or type(frozen.get('deployment_revision')) is not int or frozen['deployment_revision'] < 1
                    or not isinstance(frozen.get('bundle_id'), str) or not 1 <= len(frozen['bundle_id']) <= 128
                    or not isinstance(frozen.get('bundle_manifest'), dict)):
                raise ParserRunError('parser_selection_invalid')
            manifest, revision = frozen['bundle_manifest'], frozen['deployment_revision']
            try:
                descriptor = bundle_descriptor(manifest, source_id)
            except BundleError as exc:
                raise ParserRunError(exc.code) from None
            if any(frozen.get(key) != descriptor.get(key) for key in ('source_id', 'bundle_id', 'parser_version', 'parser_digest')):
                raise ParserRunError('parser_selection_mismatch')
        if (descriptor.get('source_id') != source_id or descriptor.get('target_kind') != target_kind
                or not isinstance(descriptor.get('parser_version'), str) or not 1 <= len(descriptor['parser_version']) <= 100
                or not isinstance(descriptor.get('parser_digest'), str)
                or re.fullmatch(r'[0-9a-f]{64}', descriptor['parser_digest']) is None):
            raise ParserRunError('parser_selection_invalid')
        public = {'parser_version': descriptor['parser_version'], 'parser_identity': {
            'bundle_id': descriptor.get('bundle_id'), 'parser_digest': descriptor['parser_digest'],
            'deployment_revision': revision}}
        options = {'bundle_manifest': manifest, 'deployment_revision': revision} if selection is not None else {}
        return descriptor, public, options
    except ParserRunError:
        raise
    except Exception:
        raise ParserRunError('parser_selection_invalid') from None


@dataclass(frozen=True)
class SourceSpec:
    id: str
    name: str
    region: str
    origin: str
    model_urls: dict[str, str]
    parser_version: str
    parser: Callable[[str, dict], list[dict]]
    description: str
    source_class: str = "manufacturer_official"
    content_types: tuple[str, ...] = ("text/html",)
    status: str = "ready"
    product_page_urls: dict[str, str] | None = None
    requires_size: bool = False

    @property
    def host(self) -> str:
        return urlsplit(self.origin).hostname or ""

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "region": self.region,
                "source_class": self.source_class, "status": self.status,
                "homepage": self.origin, "description": self.description,
                "supported_models": list(self.model_urls),
                "default_model": next(iter(self.model_urls), None),
                "parser_version": self.parser_version,
                "requires_size": self.requires_size,
                "product_page_urls": self.product_page_urls or self.model_urls}


SPECS: dict[str, SourceSpec] = {
    "michelin-us": SourceSpec(
        id="michelin-us", name="米其林 · 美国官网", region="US", origin="https://www.michelinman.com",
        model_urls={"Pilot Sport EV": "https://www.michelinman.com/auto/tires/michelin-pilot-sport-ev",
                    "Pilot Sport 4 S": "https://www.michelinman.com/auto/tires/michelin-pilot-sport-4-s"},
        parser_version="michelin-us-astro@2.0.0", parser=parse_michelin_html,
        description="PSEV / PS4S 官方产品页 · MSPN、OE 与技术标记；每次查询在线验证。",
    ),
}


def register_source(config: dict, parser: Callable[[str, dict], list[dict]]) -> None:
    allowed = {item.name for item in fields(SourceSpec)} - {"parser"}
    spec = SourceSpec(**{key: value for key, value in config.items() if key in allowed}, parser=parser)
    SPECS[spec.id] = spec


for region_source_id, region_config in MICHELIN_REGIONS.items():
    register_source({**region_config, "id": region_source_id},
                    partial(parse_michelin_html, region=region_config["region"]))

for brand_adapter in (toyo, hankook, pirelli):
    register_source(brand_adapter.SOURCE_CONFIG, brand_adapter.parse_html)

PENDING_SOURCES = [
    {"id": "eprel", "name": "EPREL · 欧盟标签", "region": "EU", "source_class": "regulatory",
     "status": "configuration_required", "homepage": "https://eprel.ec.europa.eu/",
     "supported_models": [], "description": "待申请 API Key 并完成 API 适配与条款核验，当前不提供查询。"},
    {"id": "michelin-cn", "name": "米其林 · 中国官网", "region": "CN", "source_class": "manufacturer_official",
     "status": "not_implemented", "homepage": "https://www.michelin.com.cn/",
     "supported_models": [], "description": "正在专项核验中国规格与 OE，不能用美国版本代替。"},
]

_states: dict[str, dict] = {}
_robots: dict[str, tuple[float, RobotsPolicy]] = {}
_robots_requests: dict[str, float] = {}


def sources() -> list[dict]:
    from .nhtsa import source_metadata
    disabled = {value.strip() for value in os.getenv("TI_DISABLED_SOURCES", "").split(",")}
    values = [spec.public() for spec in SPECS.values()]
    values.extend(dict(value) for value in PENDING_SOURCES if value["id"] not in SPECS)
    values.append(source_metadata())
    for value in values:
        if value["id"] in disabled:
            value["status"] = "disabled"
    return values


def model_key(value: str) -> str:
    model = re.sub(r"\s+", " ", value.strip().casefold())
    model = re.sub(r"^michelin\s+", "", model)
    return {"psev": "pilot sport ev", "ps4s": "pilot sport 4 s"}.get(model, model)


def query_url(query: dict, source_id: str = "michelin-us") -> str:
    spec = SPECS.get(source_id)
    if spec is None:
        raise SourceAccessError("source_not_found")
    # Size-only callers use the source's advertised default. The UI is explicit.
    model = model_key(str(query.get("model") or next(iter(spec.model_urls), "")))
    selected = next(((name, url) for name, url in spec.model_urls.items() if model_key(name) == model), None)
    if selected is None:
        raise SourceAccessError("unsupported_model")
    if source_id == pirelli.SOURCE_CONFIG['id']:
        try:
            return pirelli.build_query_url({**query, 'model': selected[0]})
        except ValueError as exc:
            code = str(exc)
            raise SourceAccessError(code if code in {'source_size_required', 'unsupported_model', 'invalid_size'}
                                    else 'invalid_size') from None
    return selected[1]


def permitted_path(url: str, source_id: str = "michelin-us") -> bool:
    spec = SPECS.get(source_id)
    if spec is None:
        return False
    if source_id == pirelli.SOURCE_CONFIG['id']:
        return pirelli.permitted_path(url)
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname == spec.host and not parsed.query
            and not parsed.fragment and parsed.port in (None, 443)
            and parsed.username is None and parsed.password is None
            and parsed.path.rstrip("/") in {urlsplit(value).path.rstrip("/") for value in spec.model_urls.values()})


async def _robots_policy(client: SafeHttpClient, spec: SourceSpec) -> RobotsPolicy:
    cached = _robots.get(spec.origin)
    if cached is not None and time.monotonic() - cached[0] < 3600:
        return cached[1]
    now = time.monotonic()
    interval = max(2.0, _states.get(spec.origin, {}).get("interval", 2.0))
    if now - _robots_requests.get(spec.origin, -float("inf")) < interval:
        raise SourceAccessError("source_rate_limited")
    robots_url = f"{spec.origin.rstrip('/')}/robots.txt"
    # Record actual requests, including failures. A local cooldown rejection must
    # neither send another robots request nor extend the next allowed attempt.
    _robots_requests[spec.origin] = now
    result = await client.get(robots_url, allowed_types=("text/plain",), max_bytes=128 * 1024,
                              can_follow=lambda target: target.rstrip("/") == robots_url,
                              allowed_statuses=(200, 404, 410))
    # Absent robots is distinct from unreachable robots: 403/429/5xx fail closed.
    policy = RobotsPolicy(result.body if result.status == 200 else "", USER_AGENT)
    _robots[spec.origin] = (time.monotonic(), policy)
    return policy


async def fetch(source_id: str, query: dict, cached: dict | None = None,
                *, on_observation: Callable[[dict], None] | None = None,
                parser_selection: dict | None = None) -> dict:
    source = next((item for item in sources() if item["id"] == source_id), None)
    if source is None:
        return {"status": "unavailable", "reason": "source_not_found"}
    if source["status"] != "ready":
        return {"status": "unavailable", "reason": source["status"]}
    if source_id not in SPECS:
        return {"status": "unavailable", "reason": "unsupported_query_type"}
    spec = SPECS[source_id]
    try:
        descriptor, parser_metadata, parser_options = pin_parser_selection(source_id, 'tire', parser_selection)
    except ParserRunError as exc:
        reason = parser_failure_reason(exc.code)
        return {'status': 'unavailable', 'reason': reason, 'parser_error': reason, 'parser_receipt': exc.receipt}
    query_target = None
    if source_id == pirelli.SOURCE_CONFIG['id']:
        try:
            query_target = query_url(query, source_id)
        except SourceAccessError as exc:
            return {'status': 'unavailable', 'reason': str(exc), **parser_metadata}
    state = _states.setdefault(spec.origin, {"last": -float("inf"), "failures": 0, "until": 0,
                                             "busy": False, "interval": 2.0})
    now = time.monotonic()
    if now < state["until"]:
        return {"status": "unavailable", "reason": "circuit_open", **parser_metadata}
    if state["busy"] or now - state["last"] < state["interval"]:
        return {"status": "unavailable", "reason": "source_rate_limited", **parser_metadata}
    state["busy"] = True
    observation = None
    parser_failure = None
    try:
        url = query_target if query_target is not None else query_url(query, source_id)
        validators = {}
        if (cached and cached.get("url") == url and cached.get("body")
                and cached.get("parser_version") == descriptor['parser_version']
                and parser_metadata['parser_identity']['bundle_id'] is not None
                and parser_metadata['parser_identity']['deployment_revision'] is not None
                and isinstance(cached.get('parser_identity'), dict)
                and type(cached['parser_identity'].get('deployment_revision')) is int
                and cached.get('parser_identity') == parser_metadata['parser_identity']):
            if cached.get("etag"):
                validators["If-None-Match"] = cached["etag"]
            elif cached.get("last_modified"):
                validators["If-Modified-Since"] = cached["last_modified"]
        async with asyncio.timeout(12):
            async with SafeHttpClient(frozenset({spec.host})) as client:
                robots = await _robots_policy(client, spec)
                if not robots.can_fetch(url):
                    raise SourceAccessError("robots_disallowed")
                state["interval"] = max(2.0, robots.minimum_interval)
                if now - state["last"] < state["interval"]:
                    raise SourceAccessError("source_rate_limited")
                for attempt in range(2):
                    state["last"] = time.monotonic()
                    try:
                        result = await client.get(url, headers=validators, allowed_types=spec.content_types,
                            can_follow=lambda target: permitted_path(target, source_id) and robots.can_fetch(target))
                        break
                    except SourceAccessError as exc:
                        if (str(exc) not in {"upstream_http_502", "upstream_http_503", "upstream_http_504"}
                                or attempt or state["interval"] > 3):
                            raise
                        await asyncio.sleep(state["interval"])
                if result.status == 304:
                    if not cached or not validators or cached.get("url") != result.url:
                        raise SourceAccessError("unexpected_304")
                    state.update(failures=0, until=0)
                    return {"status": "not_modified", "url": result.url, **parser_metadata,
                            "etag": result.etag, "last_modified": result.last_modified}
                observation = {"url": result.url, "body": result.body, "content_type": result.content_type,
                               **deepcopy(parser_metadata)}
                if on_observation is not None:
                    on_observation(observation)
                parsed = await parse_isolated(source_id, result.body, query, descriptor['parser_version'],
                                              descriptor['parser_digest'], **parser_options)
                variants = parsed['payload']
                state.update(failures=0, until=0)
                return {"status": "ok", "url": result.url, "body": result.body,
                        "content_type": result.content_type, "etag": result.etag,
                        "last_modified": result.last_modified, **parser_metadata,
                        "variants": variants, "parser_receipt": parsed['receipt']}
    except CaptureWriteError:
        return {"status": "unavailable", "reason": "evidence_capture_failed", **parser_metadata}
    except ParserRunError as exc:
        reason = parser_failure_reason(exc.code)
        parser_failure = exc
    except TimeoutError:
        reason = "upstream_timeout"
    except SourceAccessError as exc:
        reason = str(exc)
    except (aiohttp.ClientError, OSError):
        reason = "upstream_network_error"
    except (ValueError, TypeError, KeyError, RecursionError):
        reason = "parser_schema_changed"
    except Exception:
        reason = "parser_schema_changed" if observation is not None else "source_fetch_failed"
    finally:
        state["busy"] = False
    if reason not in {"unsupported_model", "source_size_required", "invalid_size", "robots_disallowed", "source_rate_limited"}:
        state["failures"] += 1
        if state["failures"] >= 3:
            state["until"] = time.monotonic() + 60
    if observation is not None:
        if parser_failure is not None:
            observation = {**observation, 'parser_error': reason}
        return {"status": "unavailable", "reason": reason if parser_failure else "parser_schema_changed",
                "rejected_observation": observation,
                **parser_metadata,
                **({'parser_error': reason, 'parser_receipt': parser_failure.receipt} if parser_failure else {})}
    return {"status": "unavailable", "reason": reason, **parser_metadata}

