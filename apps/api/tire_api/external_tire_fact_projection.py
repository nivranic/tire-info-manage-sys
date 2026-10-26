"""Bounded, pure projection of one observation under one G1a policy.

This module does not authenticate a policy, owner, observation, or current head.
The v1 value limits are engineering acceptance limits, not regulatory findings.
There is deliberately no reader, clock, route, provider, or permission fallback.
"""

from dataclasses import dataclass
from decimal import Decimal
import json
import math
import re
from types import MappingProxyType

from .external_fact_policy import evaluate_applicability


SCHEMA = "external-tire-fact-projection@1"
MAX_JSON_BYTES = 64 * 1024
MAX_DEPTH = 4
MAX_NODES = 256
REASON_CODES = frozenset({
    "projected", "input_invalid", "identity_invalid", "fact_value_invalid",
    "projection_capacity", "policy_invalid", "policy_not_applicable",
    "required_fields_not_covered", "no_permitted_facts",
})
_IDENTITY_KEYS = (
    "brand", "model", "region", "manufacturer_product_code", "product_code_type",
    "size", "load_index", "speed_rating", "xl", "hl", "run_flat", "oe_mark",
    "acoustic_technology", "gtin", "technology_features", "eprel_id",
)
_FACT_KEYS = frozenset({
    "utqg_treadwear", "utqg_traction", "utqg_temperature", "eu_fuel_class",
    "eu_wet_grip", "eu_external_noise_db", "eu_noise_class", "weight_kg",
    "tread_depth",
})
_REQUIRED_FIELDS = (
    "evidence.source_id", "evidence.snapshot_id", "evidence.raw_hash",
    "evidence.parser_version", "identity.variant_id", "identity.identity_status",
    "identity.identity_contract_version",
    *("identity." + key for key in _IDENTITY_KEYS),
)
_SOURCE_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}")
_HASH = re.compile(r"[0-9a-f]{64}")
_SIZE = re.compile(r"([0-9]{3})/([0-9]{2})(ZR|R)([0-9]{2}(?:\.5)?)")
_LOAD = re.compile(r"[0-9]{2,3}(?:/[0-9]{2,3})?")
_GTIN = re.compile(r"(?:[0-9]{8}|[0-9]{12}|[0-9]{13}|[0-9]{14})")
_EPREL = re.compile(r"[1-9][0-9]{0,19}")
_SPEEDS = frozenset({
    "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "B", "C", "D",
    "E", "F", "G", "J", "K", "L", "M", "N", "P", "Q", "R", "S", "T",
    "U", "H", "V", "W", "Y", "(Y)", "ZR",
})
_ENUMS = {
    "utqg_traction": frozenset({"AA", "A", "B", "C"}),
    "utqg_temperature": frozenset({"A", "B", "C"}),
    "eu_fuel_class": frozenset("ABCDEFG"),
    "eu_wet_grip": frozenset("ABCDEFG"),
    "eu_noise_class": frozenset({"A", "B", "C"}),
}


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    status: str
    reason: str
    item: MappingProxyType | None = None

    def to_dict(self) -> dict:
        """Return a detached JSON-shaped result envelope, with no mutable aliases."""
        return {"status": self.status, "reason": self.reason, "item": _thaw(self.item)}


class _ProjectionError(ValueError):
    def __init__(self, reason):
        self.reason = reason


def _fail(reason):
    raise _ProjectionError(reason)


def _bounded_copy(value):
    """Copy exact JSON builtins before any semantic checks or serialization.

    Root depth is zero. Nodes count JSON values, including containers; member
    names contribute to the byte budget but are not separate JSON value nodes.
    Only active ancestors are cycle markers, so repeated noncyclic input values
    are copied independently. No method of a user-defined subclass is invoked.
    """
    active = set()
    nodes = 0
    text_bytes = 0

    def text_size(item):
        nonlocal text_bytes
        if len(item) > MAX_JSON_BYTES:
            _fail("projection_capacity")
        try:
            text_bytes += len(item.encode("utf-8", errors="strict"))
        except UnicodeError:
            _fail("input_invalid")
        if text_bytes > MAX_JSON_BYTES:
            _fail("projection_capacity")

    def visit(item, depth):
        nonlocal nodes
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            _fail("projection_capacity")
        kind = type(item)
        if kind is str:
            text_size(item)
            return item
        if item is None or kind is bool or kind is float:
            return item
        if kind is int:
            # Bound enormous integers before any decimal conversion. Semantic
            # checks below reject out-of-range fact integers before JSON dumps.
            if item.bit_length() > MAX_JSON_BYTES * 4:
                _fail("projection_capacity")
            return item
        if kind is not dict and kind is not list:
            _fail("input_invalid")
        if len(item) > MAX_NODES:
            _fail("projection_capacity")
        marker = id(item)
        if marker in active:
            _fail("input_invalid")
        active.add(marker)
        if kind is dict:
            copied = {}
            for key, child in item.items():
                if type(key) is not str:
                    _fail("input_invalid")
                text_size(key)
                copied[key] = visit(child, depth + 1)
        else:
            copied = [visit(child, depth + 1) for child in item]
        active.remove(marker)
        return copied

    return visit(value, 0)


def _closed(value, keys, reason):
    if type(value) is not dict or value.keys() != keys:
        _fail(reason)


def _text(value, maximum, reason, *, empty=False):
    if (type(value) is not str or not (0 if empty else 1) <= len(value) <= maximum
            or value != value.strip() or (value and not value.isprintable())):
        _fail(reason)
    return value


def _pattern(value, pattern, reason):
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(reason)
    return value


def _observation(value):
    _closed(value, {"source_id", "snapshot_id", "raw_hash", "parser_version"}, "input_invalid")
    _pattern(value["source_id"], _SOURCE_ID, "input_invalid")
    _pattern(value["snapshot_id"], _IDENTIFIER, "input_invalid")
    _pattern(value["raw_hash"], _HASH, "input_invalid")
    _text(value["parser_version"], 100, "input_invalid")
    return value


def _identity(value):
    reason = "identity_invalid"
    _closed(value, {"variant_id", "contract_version", "status", "values"}, reason)
    _pattern(value["variant_id"], _IDENTIFIER, reason)
    if (type(value["contract_version"]) is not str
            or value["contract_version"] != "variant-identity@2"
            or type(value["status"]) is not str
            or value["status"] not in {"complete", "source_scoped"}):
        _fail(reason)
    values = value["values"]
    required = set(_IDENTITY_KEYS[:13])
    if (type(values) is not dict or not required.issubset(values)
            or not values.keys() <= set(_IDENTITY_KEYS)):
        _fail(reason)
    normalized = {key: values.get(key) for key in _IDENTITY_KEYS}
    for key, maximum in (("brand", 120), ("model", 200), ("region", 40)):
        _text(normalized[key], maximum, reason)
    for key in ("manufacturer_product_code", "product_code_type"):
        if normalized[key] is not None:
            _text(normalized[key], 100, reason)
    size = normalized["size"]
    _pattern(size, _SIZE, reason)
    width, aspect, _, rim = _SIZE.fullmatch(size).groups()
    if not (100 <= int(width) <= 455 and 20 <= int(aspect) <= 95
            and 10 <= Decimal(rim) <= 30):
        _fail(reason)
    if normalized["load_index"] is not None:
        _pattern(normalized["load_index"], _LOAD, reason)
    if normalized["speed_rating"] is not None and (
        type(normalized["speed_rating"]) is not str or normalized["speed_rating"] not in _SPEEDS
    ):
        _fail(reason)
    for key in ("xl", "hl", "run_flat"):
        if normalized[key] is not None and type(normalized[key]) is not bool:
            _fail(reason)
    for key in ("oe_mark", "acoustic_technology"):
        if normalized[key] is not None:
            _text(normalized[key], 100, reason, empty=True)
    gtin = normalized["gtin"]
    if gtin is not None:
        _pattern(gtin, _GTIN, reason)
        total = sum(int(digit) * (3 if index % 2 == 0 else 1)
                    for index, digit in enumerate(reversed(gtin[:-1])))
        if (10 - total % 10) % 10 != int(gtin[-1]):
            _fail(reason)
    features = normalized["technology_features"]
    if features is not None:
        if type(features) is not list or len(features) > 32:
            _fail(reason)
        for feature in features:
            _text(feature, 100, reason)
        if len(features) != len(set(features)):
            _fail(reason)
        normalized["technology_features"] = sorted(features)
    if normalized["eprel_id"] is not None:
        _pattern(normalized["eprel_id"], _EPREL, reason)
    if value["status"] == "complete" and any(normalized[key] is None for key in _IDENTITY_KEYS[:13]):
        _fail(reason)
    return {"variant_id": value["variant_id"], "contract_version": value["contract_version"],
            "status": value["status"], "values": normalized}


def _number(value, minimum, maximum, places, *, positive=False):
    if (type(value) not in (int, float) or (type(value) is float and not math.isfinite(value))
            or value < minimum or value > maximum or (positive and value == 0)):
        _fail("fact_value_invalid")
    if Decimal(str(value)).as_tuple().exponent < -places:
        _fail("fact_value_invalid")


def _facts(value):
    if type(value) is not dict or not value.keys() <= _FACT_KEYS:
        _fail("fact_value_invalid")
    for key, fact in value.items():
        if fact is None:
            continue
        if key in _ENUMS:
            if type(fact) is not str or fact not in _ENUMS[key]:
                _fail("fact_value_invalid")
        elif key in {"utqg_treadwear", "eu_external_noise_db"}:
            maximum = 5000 if key == "utqg_treadwear" else 200
            if type(fact) is not int or not 0 <= fact <= maximum:
                _fail("fact_value_invalid")
        elif key == "weight_kg":
            _number(fact, 0, 200, 3, positive=True)
        else:
            _closed(fact, {"value", "unit"}, "fact_value_invalid")
            unit = fact["unit"]
            if type(unit) is not str or unit not in {"mm", "1/32 in", "in"}:
                _fail("fact_value_invalid")
            maximum, places = {"mm": (100, 3), "1/32 in": (128, 3), "in": (4, 4)}[unit]
            _number(fact["value"], 0, maximum, places)
    return value


def _conflicts(value):
    if (type(value) is not list or len(value) > 9
            or any(type(key) is not str or key not in _FACT_KEYS for key in value)
            or len(value) != len(set(value))):
        _fail("fact_value_invalid")
    return sorted(value)


def _check_json_size(value):
    # Only detached, validated ordinary containers reach the serializer.
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_JSON_BYTES:
        _fail("projection_capacity")


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if type(value) is list:
        return tuple(_freeze(child) for child in value)
    return value


def _thaw(value):
    if type(value) is MappingProxyType:
        return {key: _thaw(child) for key, child in value.items()}
    if type(value) is tuple:
        return [_thaw(child) for child in value]
    return value


def project_observation(policy, payload, *, now) -> ProjectionResult:
    """Project one already-selected observation; no authenticity is implied.

    All input values are checked before permission-based omission. A policy
    must cover every output identity key, including optional keys filled null.
    Each fact uses that same policy; explicit permitted null counts as provided.
    """
    try:
        copied = _bounded_copy(payload)
        _closed(copied, {"observation", "identity", "facts", "conflicted_fields"}, "input_invalid")
        observation = _observation(copied["observation"])
        identity = _identity(copied["identity"])
        facts = _facts(copied["facts"])
        conflicts = _conflicts(copied["conflicted_fields"])
        _check_json_size(copied)
        required = evaluate_applicability(policy, observation, list(_REQUIRED_FIELDS), now=now)
        if required.status == "invalid":
            return ProjectionResult("invalid", "policy_invalid")
        if required.status != "applicable":
            reason = ("required_fields_not_covered" if required.reason == "fields_not_covered"
                      else "policy_not_applicable")
            return ProjectionResult("not_applicable", reason)
        permitted_facts = {}
        permitted_conflicts = []
        for key in sorted(set(facts) | set(conflicts)):
            decision = evaluate_applicability(policy, observation, ["facts." + key], now=now)
            if decision.status == "invalid":
                return ProjectionResult("invalid", "policy_invalid")
            if decision.status != "applicable":
                continue
            if key in conflicts:
                permitted_conflicts.append(key)
            else:
                permitted_facts[key] = facts[key]
        if not permitted_facts and not permitted_conflicts:
            return ProjectionResult("not_applicable", "no_permitted_facts")
        item = {
            "schema": SCHEMA, "data_state": "local_snapshot", "source_refresh_performed": False,
            "observation": observation, "identity": identity, "facts": permitted_facts,
            "conflicted_fields": permitted_conflicts,
        }
        _check_json_size(item)
        return ProjectionResult("projected", "projected", _freeze(item))
    except _ProjectionError as error:
        return ProjectionResult("invalid", error.reason)
