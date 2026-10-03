"""Official Xiaomi vehicle configuration JSON; never infer OE SKU from another market.

The public page /xiaomi/car-config invokes this read-only POST with [{}]. No
account, vehicle identifier, phone number or authentication is sent.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
import re
import time
from typing import Callable
from urllib.parse import urlsplit

import aiohttp

from ..domain import digest, parse_size
from ..captures import CaptureWriteError, parser_failure_reason
from ..parser_runtime import ParserRunError, current_parser, parse_isolated
from .robots import RobotsPolicy
from .transport import SafeHttpClient, SourceAccessError, USER_AGENT

SOURCE_ID = "xiaomi-cn-vehicles"
SOURCE_PAGE = "https://www.xiaomiev.com/xiaomi/car-config"
HOST = "website-api.xiaomiev.com"
API_URL = f"https://{HOST}/mtop/guidemarketing/product/pc/paramComparison"
PARSER_VERSION = "xiaomi-param-comparison@1.0.1"
supports_parser_deployments = True
CURRENT_ID = "xiaomi-su7-current"
FIRST_GENERATION_ID = "xiaomi-su7-first-generation"
CURRENT_SOURCE_ID = 500023067
_last_fetch = -float("inf")
_busy = False
_robots: dict[str, tuple[float, RobotsPolicy]] = {}
_robots_requests: dict[str, float] = {}
_AXLE_SIZE = re.compile(r"(?P<axle>[前后])(?:轮(?:胎)?)?\s*\d{3}/\d{2}\s*(?:ZR|R)\d{2}(?:\.5)?")


def candidates() -> list[dict]:
    """Source catalog metadata only. This function contains no tire specifications."""
    return [
        {"id": CURRENT_ID, "manufacturer": "小米汽车", "model": "SU7", "generation": "新一代",
         "model_year": None, "region": "CN", "status": "ready", "source_id": SOURCE_ID,
         "source_page": SOURCE_PAGE,
         "description": "官方当前参数配置表；明确区分版本、轮毂选项和前后轴。年款未由该表独立声明。"},
        {"id": FIRST_GENERATION_ID, "manufacturer": "小米汽车", "model": "SU7", "generation": "首代",
         "model_year": None, "region": "CN", "status": "requires_source_verification", "source_id": SOURCE_ID,
         "source_page": SOURCE_PAGE,
         "description": "首代官方配置来源尚待恢复核验，不借用新一代配置或美国轮胎 SKU。"},
    ]


def _pdf_reference(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.hostname != "s1.xiaomiev.com" or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.query or parsed.fragment or "\\" in value):
        return None
    if not parsed.path.startswith("/remote-config/theme/") or not parsed.path.lower().endswith(".pdf"):
        return None
    return value


def parse_config(body: str, vehicle_id: str = CURRENT_ID) -> dict:
    if vehicle_id != CURRENT_ID:
        raise SourceAccessError("vehicle_generation_not_verified")
    document = json.loads(body)
    if document.get("code") != 0:
        raise SourceAccessError("vehicle_source_response_error")
    tables = document.get("data", {}).get("paramComparisonTableVOList")
    if not isinstance(tables, list):
        raise SourceAccessError("vehicle_source_schema_changed")
    matches = [(index, value) for index, value in enumerate(tables)
               if isinstance(value, dict) and value.get("carItemId") == CURRENT_SOURCE_ID]
    if len(matches) != 1:
        raise SourceAccessError("vehicle_generation_not_found")
    table_index, table = matches[0]
    if table.get("brandCode") != "xiaomi" or "新一代SU7" not in re.sub(r"\s+", "", table.get("pdfFileName", "")):
        raise SourceAccessError("vehicle_generation_identity_changed")
    trims = []
    trim_map = {}
    for row in table.get("carSsuDataList", []):
        source_id = row.get("carSsuId")
        name = row.get("pcCarVersionName")
        if not isinstance(source_id, int) or not isinstance(name, str) or not name.startswith("SU7") or source_id in trim_map:
            raise SourceAccessError("vehicle_trim_identity_invalid")
        trim = {"id": f"{vehicle_id}-{source_id}", "name": name, "source_trim_id": str(source_id),
                "model_year": None, "wheel_option_ids": []}
        trim_map[source_id] = trim
        trims.append(trim)
    if not trims or len(trims) > 12:
        raise SourceAccessError("vehicle_trim_schema_changed")
    fitments = []
    footnotes = []
    seen = set()
    groups = table.get("groups", [])
    for group_index, group in enumerate(groups):
        if group.get("groupName") != "轮毂/轮胎":
            continue
        footnotes.extend(group.get("footnote") or [])
        for column_index, column in enumerate(group.get("paramComparisonCols", [])):
            trim = trim_map.get(column.get("carSsuId"))
            if trim is None or column.get("carItemId") != CURRENT_SOURCE_ID:
                raise SourceAccessError("vehicle_trim_column_mismatch")
            for row_index, row in enumerate(column.get("paramComparisonCells", [])):
                name = row.get("paramName", "")
                description = row.get("paramDesc", "").replace("\\n", "\n")
                wheel_match = re.search(r"(\d{2})英寸.*轮毂", name)
                front = re.search(r"前(?:轮(?:胎)?)?\s*(\d{3}/\d{2}\s*(?:ZR|R)\d{2}(?:\.5)?)", description)
                rear = re.search(r"后(?:轮(?:胎)?)?\s*(\d{3}/\d{2}\s*(?:ZR|R)\d{2}(?:\.5)?)", description)
                if not wheel_match or not front or not rear:
                    raise SourceAccessError("vehicle_axle_mapping_ambiguous")
                front_size, rear_size = parse_size(front.group(1)), parse_size(rear.group(1))
                rim = int(wheel_match.group(1))
                if not front_size.endswith(f"R{rim}") or not rear_size.endswith(f"R{rim}"):
                    raise SourceAccessError("vehicle_wheel_diameter_mismatch")
                availability = {"●": "standard", "○": "optional", "-": "unavailable"}.get(str(row.get("paramValue", "")).strip())
                if availability is None:
                    raise SourceAccessError("vehicle_option_availability_unknown")
                option_id = digest({"trim_id": trim["id"], "wheel_name": name})[:24]
                if option_id in seen:
                    raise SourceAccessError("vehicle_duplicate_wheel_option")
                seen.add(option_id)
                other_lines = []
                axle_constraints = []
                for original_line in description.splitlines():
                    line = original_line.strip()
                    if not line:
                        continue
                    if _AXLE_SIZE.search(line):
                        # Remove only the parsed dimensions. Conditions attached to
                        # that same line remain facts, including their axle scope.
                        remainder = _AXLE_SIZE.sub("", line).strip(" \t,，;；:：/、")
                        if remainder:
                            axle_constraints.append(_AXLE_SIZE.sub(lambda match: f"{match['axle']}轴", line))
                    else:
                        other_lines.append(line)
                source_tire = next((line for line in other_lines if "轮胎" in line), None)
                constraints = axle_constraints + [line for line in other_lines if line != source_tire]
                locator = (f"data.paramComparisonTableVOList[{table_index}].groups[{group_index}]"
                           f".paramComparisonCols[{column_index}].paramComparisonCells[{row_index}]")
                axle_metadata = {"load_index": None, "speed_rating": None, "oe_mark": None,
                                 "manufacturer_product_code": None, "matched_tire_variant_id": None}
                fitments.append({"id": option_id, "trim_id": trim["id"], "trim_name": trim["name"],
                                 "wheel_option_name": name, "wheel_diameter_inches": rim,
                                 "availability": availability,
                                 "front": {"size": front_size, **axle_metadata},
                                 "rear": {"size": rear_size, **axle_metadata},
                                 "staggered": front_size != rear_size,
                                 "source_tire_description": source_tire, "constraints": constraints,
                                 "source_description": description, "evidence_locator": locator})
                trim["wheel_option_ids"].append(option_id)
    if not fitments or any(not trim["wheel_option_ids"] for trim in trims) or len(fitments) > 100:
        raise SourceAccessError("vehicle_fitments_missing")
    return {
        "vehicle": {"id": vehicle_id, "manufacturer": {"id": "xiaomi", "name": "小米汽车"},
                    "model": "SU7", "generation": "新一代", "model_year": None, "region": "CN",
                    "source_vehicle_id": str(CURRENT_SOURCE_ID), "source_version": table.get("version")},
        "trims": trims, "fitments": fitments, "footnotes": footnotes,
        "documents": [{"url": url, "title": table.get("pdfFileName"), "status": "official_source_link"}]
                     if (url := _pdf_reference(table.get("pdfConfigDownloadUrl"))) else [],
        "coverage": {"axle_sizes": True, "wheel_options": True, "trim_mapping": True,
                     "model_year": False, "exact_tire_sku": False, "oe_mark": False,
                     "notice": "官方车型表证明配置关系，不证明具体轮胎 SKU、载重/速度或 OE 胎侧标记。"},
    }


async def fetch(vehicle_id: str, *, on_observation: Callable[[dict], None] | None = None,
                parser_selection: dict | None = None) -> dict:
    global _last_fetch, _busy, _robots
    if vehicle_id != CURRENT_ID:
        return {"status": "unavailable", "reason": "vehicle_generation_not_verified"}
    if SOURCE_ID in os.getenv("TI_DISABLED_SOURCES", "").split(","):
        return {"status": "unavailable", "reason": "source_disabled"}
    from .registry import pin_parser_selection
    try:
        descriptor, parser_metadata, parser_options = pin_parser_selection(SOURCE_ID, 'vehicle', parser_selection,
            builtin_descriptor=current_parser(SOURCE_ID) if parser_selection is None else None)
    except ParserRunError as exc:
        reason = parser_failure_reason(exc.code)
        return {'status': 'unavailable', 'reason': reason, 'parser_error': reason, 'parser_receipt': exc.receipt}
    except Exception:
        return {'status': 'unavailable', 'reason': 'parser_selection_invalid', 'parser_error': 'parser_selection_invalid'}
    now = time.monotonic()
    minimum_interval = max([2, *(entry[1].minimum_interval for entry in _robots.values()
                                  if now - entry[0] <= 3600)])
    if _busy or now - _last_fetch < minimum_interval:
        return {"status": "unavailable", "reason": "source_rate_limited", **parser_metadata}
    _busy = True
    observation = None
    fallback_failure_reason = None
    transport_cancelled = False

    async def transport_request(call, *args, **kwargs):
        nonlocal fallback_failure_reason, transport_cancelled
        try:
            return await call(*args, **kwargs)
        except TimeoutError:
            fallback_failure_reason = 'upstream_timeout'
            raise
        except (aiohttp.ClientError, OSError):
            fallback_failure_reason = 'upstream_network_error'
            raise
        except asyncio.CancelledError:
            # asyncio.timeout converts cancellation on leaving its context.
            # Only a cancellation inside an actual HTTP await can qualify.
            transport_cancelled = True
            raise

    try:
        async with asyncio.timeout(15):
            async with SafeHttpClient(frozenset({HOST, "www.xiaomiev.com"})) as client:
                for hostname, target in (("www.xiaomiev.com", SOURCE_PAGE), (HOST, API_URL)):
                    cached_policy = _robots.get(hostname)
                    if cached_policy is None or time.monotonic() - cached_policy[0] > 3600:
                        # Failed robots requests have their own per-host budget. A
                        # local retry rejection never extends either request clock.
                        now = time.monotonic()
                        if now - _robots_requests.get(hostname, -float("inf")) < 2:
                            raise SourceAccessError("source_rate_limited")
                        robots_url = f"https://{hostname}/robots.txt"
                        _robots_requests[hostname] = now
                        robots = await transport_request(client.get, robots_url, allowed_types=("text/plain",),
                                                  allowed_statuses=(200, 404, 410), max_bytes=128 * 1024,
                                                  can_follow=lambda url, expected=robots_url: url == expected)
                        policy = RobotsPolicy(robots.body if robots.status == 200 else "", USER_AGENT)
                        cached_policy = (time.monotonic(), policy)
                        _robots[hostname] = cached_policy
                    if not cached_policy[1].can_fetch(target):
                        raise SourceAccessError("robots_disallowed")
                    if time.monotonic() - _last_fetch < cached_policy[1].minimum_interval:
                        raise SourceAccessError("source_rate_limited")
                # Rejected attempts do not move the upstream request clock. Count
                # actual POST attempts, including those that later fail in transit.
                _last_fetch = time.monotonic()
                result = await transport_request(client.post, API_URL, json_body=[{}], allowed_types=("application/json",),
                                           max_bytes=2 * 1024 * 1024)
        observation = {"url": result.url, "body": result.body,
                       "content_type": result.content_type, **deepcopy(parser_metadata)}
        if on_observation is not None:
            on_observation(observation)
        parsed = await parse_isolated(SOURCE_ID, result.body, {'vehicle_id': vehicle_id}, descriptor['parser_version'],
                                      descriptor['parser_digest'], **parser_options)
        payload = parsed['payload']
        return {"status": "ok", "url": result.url, "body": result.body,
                "content_type": result.content_type, **parser_metadata,
                "payload": payload, "parser_receipt": parsed['receipt']}
    except CaptureWriteError:
        return {"status": "unavailable", "reason": "evidence_capture_failed", **parser_metadata}
    except ParserRunError as exc:
        reason = parser_failure_reason(exc.code)
        rejected = {**observation, 'parser_error': reason} if observation is not None else None
        return {"status": "unavailable", "reason": reason, "rejected_observation": rejected,
                "parser_error": reason, "parser_receipt": exc.receipt, **parser_metadata}
    except SourceAccessError as exc:
        reason = str(exc)
    except TimeoutError:
        if transport_cancelled:
            fallback_failure_reason = 'upstream_timeout'
        reason = "vehicle_network_unavailable"
    except (aiohttp.ClientError, OSError):
        reason = "vehicle_network_unavailable"
    except (ValueError, KeyError, TypeError, AttributeError):
        reason = "vehicle_source_schema_changed"
    except Exception:
        reason = "vehicle_source_schema_changed" if observation is not None else "vehicle_source_fetch_failed"
    finally:
        _busy = False
    if observation is not None:
        return {"status": "unavailable", "reason": "vehicle_source_schema_changed", "rejected_observation": observation,
                **parser_metadata}
    return {"status": "unavailable", "reason": reason, **parser_metadata,
            **({'fallback_failure_reason': fallback_failure_reason} if fallback_failure_reason else {})}
