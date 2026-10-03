"""DeviceAIValue AST encoder: the reference layer above the sealed projection core.

This module closes the token_dto()/as_token_dto() ambiguity break found in the
draft-b review (Top1): device_ai_projection.token_dto() maps both a real JSON
number and a source object that merely resembles {schema, token} to the same
output shape, so a downstream consumer can no longer tell the numeric role from
the structured role. The encoder below never works on DTO shapes: it walks the
exact AST produced by device_ai_projection.parse_exact_json, where a real JSON
number is a NumberLexeme node and a look-alike object stays an ordinary dict.

Encoding rules (draft-b DeviceAIValue, public-types-draft-b.ts L62-69):
  NumberLexeme              -> {"kind":"number","value":<token DTO, original lexeme>}
  None                      -> {"kind":"null","value":None}
  bool                      -> {"kind":"boolean","value":<bool>}
  str                       -> {"kind":"text","value":<str>}
  list                      -> {"kind":"array","items":[encoded children, source order]}
  dict (all keys str)       -> {"kind":"structured","fields":[{name,value} codepoint-sorted]}
  anything else (int/float) -> closed ProjectionError; bare Python numbers are not
                               exact-AST nodes and would smuggle a guessed number.

Canonical SHA is computed from the ORIGINAL AST via the projection's
canonical_exact_json / exact_digest semantics (device_ai_projection.py L157-186),
never from the encoded DTO. Structured fields sort by key codepoint, matching
canonical_exact_json (same `sorted(node)` codepoint order there); dict insertion
order is not portable across hosts and is deliberately not used.

This file is a specification-bearing reference implementation only. Draft b stays
unfrozen; no wire decoder, host integration or runtime schema is provided here,
and tire_api.device_ai_projection (sealed 97/97) is imported, never modified.
"""
from typing import Any

from .device_ai_projection import (
    MAX_DEPTH, NumberLexeme, ProjectionError, canonical_exact_json, exact_digest,
    parse_exact_json,
)
from .query_filters import MAX_CONDITIONS, TireFilter, canonical_filters
import hashlib
import json
import math

NUMBER_SCHEMA = "device-number-token@1"  # same label as NumberLexeme.token_dto (L74-75).


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ProjectionError(code)


def encode_value(node: Any) -> Any:
    """Encode one exact-AST node into the DeviceAIValue tagged shape.

    The decision is made ONLY on the AST node type. A dict whose contents equal a
    token DTO is encoded as the structured branch with text leaves; it is never
    guessed to be a number, and a NumberLexeme is never flattened back into a
    structure. Bare Python int/float inputs are rejected: parse_exact_json never
    produces them, so their presence means the value was not read from exact
    source bytes and any token derived from it would be a reconstruction.
    """
    return _encode(node, 0)


def _encode(node: Any, depth: int) -> Any:
    if depth > MAX_DEPTH:
        raise ProjectionError("device_ai_json_depth")
    if isinstance(node, NumberLexeme):
        return {"kind": "number", "value": {"schema": NUMBER_SCHEMA, "token": node.token}}
    if node is None:
        return {"kind": "null", "value": None}
    if type(node) is bool:
        return {"kind": "boolean", "value": node}
    if type(node) is str:
        return {"kind": "text", "value": node}
    if type(node) is list:
        return {"kind": "array", "items": [_encode(child, depth + 1) for child in node]}
    if type(node) is dict:
        if any(type(key) is not str for key in node):
            raise ProjectionError("device_ai_value_type_unsupported")
        fields = [{"name": key, "value": _encode(node[key], depth + 1)} for key in sorted(node)]
        return {"kind": "structured", "fields": fields}
    raise ProjectionError("device_ai_value_type_unsupported")


def encode_source_bytes(raw: bytes, *, namespace: str | None = None) -> tuple[Any, str]:
    """Parse exact source bytes, encode the value, and digest the ORIGINAL AST.

    namespace=None   -> sha256(canonical_exact_json(ast)) exactly like the frozen
                        DeviceProjection.sha256 (device_ai_projection.py L777-780);
                        no namespace prefix is prepended.
    namespace="..."  -> exact_digest(ast, namespace=...) semantics (L184-186):
                        sha256(namespace_utf8 + b"\\x00" + canonical_exact_json(ast)).
    The digest is never computed over the encoded DTO, and the encoded value is
    never reconstructed from the digest (draft-b L70-72).
    """
    ast = parse_exact_json(raw)
    encoded = encode_value(ast)
    digest = (exact_digest(ast, namespace=namespace) if namespace is not None
              else hashlib.sha256(canonical_exact_json(ast)).hexdigest())
    return encoded, digest


def encode_filters_exact_json(filters: Any) -> str:
    """Canonical tire-query-filters@1 exact JSON text (E3 reference encoder).

    Input: list (<= MAX_CONDITIONS) of TireFilter-shaped mappings. Each condition
    is validated through the existing closed server parser (query_filters.TireFilter,
    extra='forbid', normalized values, presence operators carry no value), then
    deduplicated and ordered by canonical_filters. Emission is compact JSON
    (",", ":") with fixed key order field,op,value; value is omitted for
    is_known/is_unknown; numbers are emitted as bare JSON numbers in their
    canonical lexeme form (arbitrary-precision integers; finite floats in Python
    repr form). ExactNumericToken is NOT serialized as a device-number-token@1 DTO:
    the server parser expects scalar values and the filters contract keeps its own
    namespace (draft-b L114-120).

    Round-trip equivalence (locked by tests): json.loads(text) items validated by
    TireFilter.model_validate and re-canonicalized by canonical_filters equal
    canonical_filters applied to the input list. Hosts producing this text from
    ExactNumericToken/bigint values must never JSON.stringify the token object or
    its methods; see specs/filters-exact-json-spec.md.
    """
    _require(type(filters) is list and len(filters) <= MAX_CONDITIONS, "device_ai_filters_capacity")
    try:
        validated = [TireFilter.model_validate(dict(condition)) for condition in filters]
        canonical = canonical_filters(validated)
    except (ValueError, TypeError):
        raise ProjectionError("device_ai_filters_invalid") from None
    return "[" + ",".join(_condition_text(condition) for condition in canonical) + "]"


def _condition_text(condition: dict) -> str:
    text = '{"field":' + _text_value(condition["field"]) + ',"op":' + _text_value(condition["op"])
    if "value" in condition:
        text += ',"value":' + _filter_value_text(condition["value"])
    return text + "}"


def _text_value(value: str) -> str:
    if type(value) is not str:
        raise ProjectionError("device_ai_filters_invalid")
    return json.dumps(value, ensure_ascii=False)


def _filter_value_text(value: Any) -> str:
    # bool first: bool is an int subclass and must stay true/false, not 1/0.
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is float:
        if not math.isfinite(value):
            raise ProjectionError("device_ai_filters_invalid")
        return json.dumps(value, allow_nan=False)
    if type(value) is str:
        return json.dumps(value, ensure_ascii=False)
    raise ProjectionError("device_ai_filters_invalid")
