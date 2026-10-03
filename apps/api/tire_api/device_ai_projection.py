"""Pure projection of authenticated, immutable offline bytes; no AI authorization.

The caller must obtain an actor-owned OfflinePack and enforce current visibility,
rights, lifecycle and consent before using the result. Expected hashes and local
device metadata are not proof of ownership or physical installation. This module
does not import a database, adapter, provider, router or host implementation.

Numbers retain their archived spelling. Floating tokens still have the original
package's finite binary64 semantics; retaining a lexeme does not add precision.
The Python interfaces below are internal and do not freeze a public wire schema.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence


MAX_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 32  # Conservative common bound: Android 32, desktop 64.
MAX_NODES = 250_000
MAX_PROJECTION_BYTES = 44_000
MAX_SAFE_INTEGER = 9_007_199_254_740_991
POLICY_VERSION = "device-ai-projection@1"
SUPPORTED_KINDS = frozenset({"tire", "vehicle", "recall", "recall_search", "test_event"})
UNIMPLEMENTED_INTEGRATION = (
    "actor ownership/current visibility/rights/revocation gates",
    "host selection preview/once consent/provider consent",
    "public DTO/routes/ledger/migration/idempotency/SSE",
    "device citation generation/reopen CAS",
    "personal context projection and cross-package selection",
    "restricted test-event AI use (blocked under current policy)",
)
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FORBIDDEN = frozenset({
    "body", "raw", "raw_body", "raw_content", "html", "full_text", "full_html",
    "full_document", "image_base64", "pdf_base64", "session_cookie", "actor_session_id",
    "session_id", "cookie", "cookies", "authorization", "api_key", "provider_key",
    "access_token", "refresh_token", "body_base64",
})


class ProjectionError(ValueError):
    """Closed failure; no source body or secret is embedded in the message."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _require(condition: bool, code: str = "device_ai_material_invalid") -> None:
    if not condition:
        raise ProjectionError(code)


@dataclass(frozen=True, slots=True)
class NumberLexeme:
    token: str

    def __post_init__(self) -> None:
        _require(isinstance(self.token, str) and bool(_NUMBER.fullmatch(self.token)),
                 "device_ai_number_invalid")
        if self.is_float:
            _require(math.isfinite(float(self.token)), "device_ai_number_nonfinite")

    @property
    def is_float(self) -> bool:
        return any(char in self.token for char in ".eE")

    def token_dto(self) -> dict[str, str]:
        return {"schema": "device-number-token@1", "token": self.token}


def _scan_depth(text: str) -> None:
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            _require(depth <= MAX_DEPTH + 1, "device_ai_json_depth")
        elif char in "]}":
            depth -= 1


def _check_tree(value: Any, depth: int, budget: list[int]) -> None:
    budget[0] += 1
    _require(depth <= MAX_DEPTH, "device_ai_json_depth")
    _require(budget[0] <= MAX_NODES, "device_ai_json_nodes")
    if isinstance(value, dict):
        for key, child in value.items():
            _check_string(key)
            _check_tree(child, depth + 1, budget)
    elif isinstance(value, list):
        for child in value:
            _check_tree(child, depth + 1, budget)
    elif isinstance(value, str):
        _check_string(value)


def _check_string(value: str) -> None:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise ProjectionError("device_ai_json_unicode") from None


def parse_exact_json(raw: bytes) -> Any:
    """Strict bounded UTF-8 JSON AST with original integer/float tokens."""
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_PACKAGE_BYTES,
             "device_ai_package_capacity")
    _require(not raw.startswith(b"\xef\xbb\xbf"), "device_ai_json_bom")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise ProjectionError("device_ai_json_utf8") from None
    _scan_depth(text)
    number_count = 0

    def number(token: str) -> NumberLexeme:
        nonlocal number_count
        number_count += 1
        _require(number_count <= MAX_NODES, "device_ai_json_nodes")
        return NumberLexeme(token)

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            _require(key not in result, "device_ai_json_duplicate_key")
            result[key] = value
        return result

    def constant(_token: str) -> None:
        raise ProjectionError("device_ai_number_invalid")

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_int=number,
                           parse_float=number, parse_constant=constant)
    except (json.JSONDecodeError, RecursionError, OverflowError):
        raise ProjectionError("device_ai_json_invalid") from None
    _check_tree(value, 0, [0])
    return value


def canonical_exact_json(value: Any) -> bytes:
    """Codepoint-sorted JSON; no float conversion or number normalization."""
    def encode(node: Any, depth: int) -> str:
        _require(depth <= MAX_DEPTH, "device_ai_json_depth")
        if isinstance(node, NumberLexeme):
            return node.token
        if node is None:
            return "null"
        if type(node) is bool:
            return "true" if node else "false"
        if type(node) is int:
            _require(abs(node) <= MAX_SAFE_INTEGER, "device_ai_metadata_number_invalid")
            return str(node)
        if isinstance(node, str):
            _check_string(node)
            return json.dumps(node, ensure_ascii=False)
        if isinstance(node, list):
            return "[" + ",".join(encode(child, depth + 1) for child in node) + "]"
        if isinstance(node, dict):
            _require(all(type(key) is str for key in node), "device_ai_json_invalid")
            return "{" + ",".join(encode(key, depth + 1) + ":" + encode(node[key], depth + 1)
                                    for key in sorted(node)) + "}"
        raise ProjectionError("device_ai_number_or_type_unsupported")

    return encode(value, 0).encode("utf-8")


def exact_digest(value: Any, *, namespace: str) -> str:
    _require(type(namespace) is str and bool(namespace) and "\x00" not in namespace)
    return hashlib.sha256(namespace.encode("utf-8") + b"\x00" + canonical_exact_json(value)).hexdigest()


def token_dto(value: Any) -> Any:
    """Fresh projection for ordinary JSON transport; business numbers are tagged."""
    if isinstance(value, NumberLexeme):
        return value.token_dto()
    if isinstance(value, dict):
        return {key: token_dto(child) for key, child in value.items()}
    if isinstance(value, list):
        return [token_dto(child) for child in value]
    return value


def _shape(value: Any, required: set[str], optional: set[str] = frozenset()) -> dict:
    _require(type(value) is dict and required <= value.keys() and value.keys() <= required | optional)
    return value


def _text(value: Any, *, nullable: bool = False, maximum: int = 100_000) -> Any:
    _require(nullable and value is None or type(value) is str and len(value) <= maximum
             and "\x00" not in value)
    return value


def _id(value: Any) -> str:
    _text(value, maximum=200)
    _require(bool(value))
    return value


def _hash(value: Any) -> str:
    _require(type(value) is str and bool(_HASH.fullmatch(value)))
    return value


def _meta_int(value: Any, maximum: int = MAX_SAFE_INTEGER, minimum: int = 0) -> int:
    if isinstance(value, NumberLexeme):
        _require(not value.is_float and len(value.token) <= 17, "device_ai_metadata_number_invalid")
        value = int(value.token)
    _require(type(value) is int and minimum <= value <= maximum, "device_ai_metadata_number_invalid")
    return value


def _time(value: Any, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    _text(value, maximum=80)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _require(parsed.tzinfo is not None)
    except ValueError:
        raise ProjectionError("device_ai_material_invalid") from None


def _no_excluded_material(value: Any) -> None:
    if isinstance(value, dict):
        _require(not any(key.lower() in _FORBIDDEN for key in value), "device_ai_excluded_material")
        for child in value.values():
            _no_excluded_material(child)
    elif isinstance(value, list):
        for child in value:
            _no_excluded_material(child)
    elif isinstance(value, str):
        _text(value)


def _reference(value: Any, schema: str) -> dict:
    _require(type(value) is dict and value.get("kind") in SUPPORTED_KINDS,
             "device_ai_domain_unsupported")
    kind = value["kind"]
    fields = {"tire": {"kind", "snapshot_id", "variant_id", "verification_id"},
              "vehicle": {"kind", "snapshot_id", "verification_id"},
              "recall": {"kind", "snapshot_id", "recall_revision_id", "verification_id"},
              "recall_search": {"kind", "snapshot_id", "verification_id"},
              "test_event": {"kind", "event_id", "event_revision"}}[kind]
    _shape(value, fields)
    _require(kind != "recall_search" or schema == "offline-pack@2", "device_ai_domain_unsupported")
    result = dict(value)
    for key, item in value.items():
        if key == "event_revision":
            result[key] = _meta_int(item, maximum=2_147_483_647, minimum=1)
        elif key == "recall_revision_id" and item is None:
            continue
        else:
            _id(item)
    return result


def _source(value: Any, reference: dict) -> dict:
    names = {"source_id", "source_url", "raw_hash", "parser_version", "parser_identity",
             "observed_at", "verified_at", "verification_id"}
    _shape(value, names)
    _time(value["observed_at"])
    _time(value["verified_at"], nullable=True)
    for key in ("source_id", "source_url", "parser_version", "verification_id"):
        _text(value[key], nullable=True)
    _require(type(value["source_url"]) is str and bool(value["source_url"].strip()),
             "device_ai_source_proof_missing")
    if value["parser_identity"] is not None:
        identity = _shape(value["parser_identity"], {"bundle_id", "parser_digest", "deployment_revision"})
        _id(identity["bundle_id"])
        _hash(identity["parser_digest"])
        _meta_int(identity["deployment_revision"])
    if value["raw_hash"] is not None:
        _hash(value["raw_hash"])
    if reference["kind"] == "test_event":
        _require(value["verification_id"] is None and value["verified_at"] is None,
                 "device_ai_receipt_mismatch")
    else:
        _require(all(type(value[key]) is str and bool(value[key].strip())
                     for key in ("source_id", "parser_version")), "device_ai_source_proof_missing")
        _require(value["verification_id"] == reference["verification_id"]
                 and value["verified_at"] is not None and value["raw_hash"] is not None,
                 "device_ai_receipt_mismatch")
    _no_excluded_material(value)
    return value


@dataclass(frozen=True, slots=True)
class FrozenPackBinding:
    package_id: str
    owner_scope_id: str
    sha256: str
    byte_count: int
    schema: str


@dataclass(frozen=True, slots=True)
class DeviceProjection:
    canonical_bytes: bytes
    sha256: str
    token_dto_bytes: bytes
    member_count: int

    def as_token_dto(self) -> dict:
        return json.loads(self.token_dto_bytes)


def _load(raw: bytes, expected: FrozenPackBinding) -> tuple[dict, dict, dict]:
    _id(expected.package_id)
    _hash(expected.owner_scope_id)
    _hash(expected.sha256)
    _meta_int(expected.byte_count, maximum=MAX_PACKAGE_BYTES, minimum=1)
    _require(type(raw) is bytes and len(raw) == expected.byte_count
             and hashlib.sha256(raw).hexdigest() == expected.sha256, "device_ai_package_binding_mismatch")
    envelope = parse_exact_json(raw)
    _shape(envelope, {"schema", "package_id", "created_at", "plan_fingerprint", "owner_scope_id",
                      "privacy_class", "data_state", "source_refresh_performed", "base_pack_id",
                      "scope", "contracts", "contexts", "members", "documents", "omissions"})
    _require(expected.schema in {"offline-pack@1", "offline-pack@2"}
             and envelope["schema"] == expected.schema
             and envelope["package_id"] == expected.package_id
             and envelope["owner_scope_id"] == expected.owner_scope_id,
             "device_ai_package_binding_mismatch")
    _require(envelope["data_state"] == "local_snapshot" and envelope["source_refresh_performed"] is False
             and envelope["privacy_class"] in {"private", "restricted"})
    _time(envelope["created_at"])
    _hash(envelope["plan_fingerprint"])
    _shape(envelope["contracts"], {"offline_policy", "field_policy", "recall_policy"})
    _require(envelope["contracts"]["offline_policy"] == "offline-policy@1")
    members = {}
    _require(type(envelope["members"]) is list and len(envelope["members"]) <= 200)
    for member in envelope["members"]:
        _shape(member, {"key", "reference", "member_reasons", "privacy_class", "raw_included", "source", "payload"})
        key = _hash(member["key"])
        _require(key not in members, "device_ai_member_ambiguous")
        reference = _reference(member["reference"], expected.schema)
        _source(member["source"], reference)
        _require(member["privacy_class"] in {"public", "private", "restricted"}
                 and member["raw_included"] is False and type(member["payload"]) is dict)
        members[key] = member
    documents = {}
    _require(type(envelope["documents"]) is list and len(envelope["documents"]) <= 4000)
    for document in envelope["documents"]:
        _shape(document, {"id", "category", "kind", "member_key", "context_id", "record_index",
                          "title", "text", "facets", "membership", "privacy_class", "observed_at", "verified_at"})
        identifier = _id(document["id"])
        _require(identifier not in documents, "device_ai_document_ambiguous")
        documents[identifier] = document
    return envelope, members, documents


def _select(selector: Any, schema: str, members: dict, documents: dict) -> tuple[dict, dict]:
    _shape(selector, {"kind", "member_key", "document_id", "record_index", "reference"})
    reference = _reference(selector["reference"], schema)
    _require(selector["kind"] == reference["kind"], "device_ai_selector_mismatch")
    key = _hash(selector["member_key"])
    _require(key in members, "device_ai_member_missing")
    member = members[key]
    _require(canonical_exact_json(reference) == canonical_exact_json(_reference(member["reference"], schema)),
             "device_ai_receipt_mismatch")
    record = selector["record_index"]
    if record is not None:
        record = _meta_int(record, maximum=3999)
    document_id = selector["document_id"]
    if document_id is not None:
        _id(document_id)
        _require(document_id in documents, "device_ai_document_missing")
        document = documents[document_id]
        _require(document["category"] == "evidence" and document["context_id"] is None
                 and document["member_key"] == key and document["kind"] == reference["kind"]
                 and document["privacy_class"] == member["privacy_class"]
                 and (None if document["record_index"] is None else _meta_int(document["record_index"], 3999)) == record,
                 "device_ai_document_mismatch")
        for name in ("observed_at", "verified_at"):
            _require(document[name] == member["source"][name], "device_ai_receipt_mismatch")
    else:
        _require(record is None, "device_ai_selector_mismatch")
    _require(reference["kind"] not in {"tire", "vehicle"} or record is None, "device_ai_selector_mismatch")
    resolved = {"kind": reference["kind"], "member_key": key, "document_id": document_id,
                "record_index": record, "reference": reference}
    return resolved, member


def _candidate_origin(candidate: dict, members: dict) -> str:
    required = {"snapshot_id", "variant_id", "source_id", "source_url", "raw_hash", "parser_version",
                "observed_at", "verified_at", "field", "present", "value", "id", "missing_evidence"}
    optional = {"source_field", "source_name", "source_class", "source_region", "fact_version_id",
                "published_at", "evidence_locator", "identity_match", "region_match", "evidence_valid",
                "source_conflicted", "equivalence_event_id", "curation_field", "sku_specific",
                "eligible", "exclusion_reasons", "authority", "dimensions", "verification_id"}
    _require(type(candidate) is dict and required <= candidate.keys() and candidate.keys() <= required | optional,
             "device_ai_candidate_proof_missing")
    # field_evidence.add marks source fields eligible for future curation here;
    # a non-null marker is not a curated/personal value or authorization.
    _text(candidate.get("curation_field"), nullable=True, maximum=200)
    _require(type(candidate["present"]) is bool and type(candidate["missing_evidence"]) is list)
    matches = []
    for key, member in members.items():
        ref, source = member["reference"], member["source"]
        if ref["kind"] != "tire" or ref["snapshot_id"] != candidate["snapshot_id"] or ref["variant_id"] != candidate["variant_id"]:
            continue
        if "verification_id" in candidate and candidate["verification_id"] != ref["verification_id"]:
            continue
        if all(candidate[name] == source[name] for name in
               ("source_id", "source_url", "raw_hash", "parser_version", "observed_at", "verified_at")):
            matches.append(key)
    _require(len(matches) == 1, "device_ai_candidate_receipt_ambiguous_or_missing")
    return matches[0]


def _resolution(member: dict) -> dict:
    payload = member["payload"]
    _shape(payload, {"variant", "identity_contract", "snapshot_identity_contract", "field_resolution", "lifecycle"})
    # This is an archived schema label, never an arbitrary context object. None
    # retains the producer's explicit legacy unknown; it grants no identity use.
    _require(payload["snapshot_identity_contract"] is None
             or type(payload["snapshot_identity_contract"]) is str
             and payload["snapshot_identity_contract"] == "variant-identity@2",
             "device_ai_snapshot_identity_unsupported")
    variant, ref = payload["variant"], member["reference"]
    _require(type(variant) is dict and variant.get("id") == ref["variant_id"]
             and variant.get("snapshot_id") == ref["snapshot_id"], "device_ai_variant_mismatch")
    resolution = payload["field_resolution"]
    _shape(resolution, {"policy", "variant_id", "scope", "data_state", "fields", "notice", "fingerprint"})
    _require(resolution["variant_id"] == ref["variant_id"] and resolution["scope"] == "offline_pack"
             and resolution["data_state"] == "local_snapshot" and type(resolution["fields"]) is list)
    _hash(resolution["fingerprint"])
    _shape(resolution["policy"], {"version", "digest"})
    _require(resolution["policy"]["version"] == "field-authority@1", "device_ai_domain_unsupported")
    _hash(resolution["policy"]["digest"])
    return resolution


def _frozen_identity(member: dict) -> dict:
    identity = member["payload"]["identity_contract"]
    required = {"schema", "state", "current_key", "current_identity", "identity_status"}
    _shape(identity, required | {"origin", "reason_codes", "related_candidates", "tracking_state", "notice"})
    _require(identity["schema"] == "variant-identity@2", "device_ai_domain_unsupported")
    _require(type(identity["state"]) is str
             and identity["state"] in {"current", "legacy_unbound", "legacy_needs_review"},
             "device_ai_identity_context_invalid")
    _text(identity["origin"], nullable=True, maximum=200)
    _text(identity["notice"])
    _require(type(identity["reason_codes"]) is list and all(type(code) is str for code in identity["reason_codes"]),
             "device_ai_identity_context_invalid")
    _require(type(identity["related_candidates"]) is list, "device_ai_identity_context_invalid")
    for related in identity["related_candidates"]:
        _shape(related, {"variant_id", "relationship", "product_code_type"})
        _id(related["variant_id"])
        _require(type(related["relationship"]) is str
                 and related["relationship"] in {"unconfirmed_legacy", "unconfirmed_current"},
                 "device_ai_identity_context_invalid")
        _text(related["product_code_type"], nullable=True, maximum=100)
    if identity["state"] == "current":
        _hash(identity["current_key"])
        _require(type(identity["identity_status"]) is str
                 and identity["identity_status"] in {"complete", "source_scoped"}
                 and identity["tracking_state"] == "current", "device_ai_identity_context_invalid")
    else:
        # contract_metadata emits nulls when no current binding exists. Keep this
        # historical limitation; never fill them from variant or candidates.
        _require(identity["current_key"] is None and identity["current_identity"] is None
                 and identity["identity_status"] is None and identity["tracking_state"] == "identity_review_required",
                 "device_ai_identity_context_invalid")
    # Related candidates are not part of the selected observation or its facts.
    if identity["current_identity"] is not None:
        dimensions = identity["current_identity"]
        names = {"brand", "model", "region", "size", "manufacturer_product_code", "product_code_type",
                 "load_index", "speed_rating", "xl", "hl", "oe_mark", "acoustic_technology", "run_flat"}
        _shape(dimensions, names, {"gtin", "eprel_id", "technology_features"})
        limits = {"brand": 120, "model": 200, "region": 40, "size": 24,
                  "manufacturer_product_code": 100, "product_code_type": 100,
                  "load_index": 12, "speed_rating": 12, "oe_mark": 100, "acoustic_technology": 100}
        for name, maximum in limits.items():
            value = dimensions[name]
            _text(value, nullable=name not in {"brand", "model", "region", "size"}, maximum=maximum)
            if name in {"brand", "model", "region", "size"}:
                _require(bool(value), "device_ai_identity_context_invalid")
        for name in ("xl", "hl", "run_flat"):
            _require(dimensions[name] is None or type(dimensions[name]) is bool,
                     "device_ai_identity_context_invalid")
        if dimensions["manufacturer_product_code"] is not None:
            _require(bool(dimensions["manufacturer_product_code"]) and dimensions["manufacturer_product_code"].isprintable(),
                     "device_ai_identity_context_invalid")
        if dimensions["product_code_type"] is not None:
            namespace = dimensions["product_code_type"]
            _require(bool(namespace) and namespace == namespace.strip() and namespace.isprintable(),
                     "device_ai_identity_context_invalid")
        if dimensions["load_index"] is not None:
            _require(bool(re.fullmatch(r"\d{2,3}(?:/\d{2,3})?", dimensions["load_index"])),
                     "device_ai_identity_context_invalid")
        if dimensions["speed_rating"] is not None:
            _require(dimensions["speed_rating"] in {"A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8",
                                                   "B", "C", "D", "E", "F", "G", "J", "K", "L", "M", "N", "P",
                                                   "Q", "R", "S", "T", "U", "H", "V", "W", "Y", "(Y)", "ZR"},
                     "device_ai_identity_context_invalid")
        _require(bool(re.fullmatch(r"\d{3}/\d{2}(?:ZR|R)\d{2}(?:\.5)?", dimensions["size"])),
                 "device_ai_identity_context_invalid")
        # legacy_identity imports these optional dimensions from arbitrary JSON
        # facts. Only the source-observed scalar IDs / string feature-list subset
        # has a closed projection here. Rich JSON identities remain unsupported;
        # do not stringify objects or pretend to have a feature-object schema.
        for name in ("gtin", "eprel_id"):
            if name in dimensions:
                value = dimensions[name]
                _require(value is None or type(value) is str or isinstance(value, NumberLexeme) and not value.is_float,
                         "device_ai_identity_dimension_unsupported")
        if "technology_features" in dimensions:
            features = dimensions["technology_features"]
            _require(type(features) is list and all(type(feature) is str for feature in features),
                     "device_ai_identity_dimension_unsupported")
    else:
        _require(identity["state"] != "current", "device_ai_identity_context_invalid")
    projected = {key: deepcopy(identity[key]) for key in required}
    _no_excluded_material(projected)
    return projected


def _tire(member: dict, members: dict, mode: str) -> dict:
    resolution = _resolution(member)
    fields, seen = [], set()
    for field in resolution["fields"]:
        _shape(field, {"field", "label", "unit", "category", "identity_bound", "source_scope_only",
                       "state", "has_default", "default_value", "default_candidate_ids", "candidates", "reasons"})
        _require(type(field["candidates"]) is list and bool(field["candidates"]))
        _id(field["field"])
        _text(field["label"])
        _text(field["unit"], nullable=True)
        _require(field["field"] not in seen, "device_ai_field_ambiguous")
        seen.add(field["field"])
        candidates = []
        for candidate in field["candidates"]:
            _require(type(candidate) is dict and candidate.get("field") == field["field"])
            ref = member["reference"]
            if mode == "single_observation" and (candidate.get("snapshot_id") != ref["snapshot_id"]
                                                  or candidate.get("variant_id") != ref["variant_id"]
                                                  or "verification_id" in candidate and candidate["verification_id"] != ref["verification_id"]):
                continue
            origin_key = _candidate_origin(candidate, members)
            if mode == "single_observation" and origin_key != member["key"]:
                continue
            if mode == "single_observation":
                allowed = {"id", "field", "source_field", "present", "value", "evidence_locator",
                           "evidence_valid", "missing_evidence", "snapshot_id", "variant_id", "verification_id",
                           "source_id", "source_url", "raw_hash", "parser_version", "observed_at", "verified_at"}
                candidates.append({key: deepcopy(value) for key, value in candidate.items() if key in allowed})
            else:
                candidates.append(deepcopy(candidate))
        _require(bool(candidates), "device_ai_selected_field_proof_missing")
        if mode == "single_observation":
            fields.append({"field": field["field"], "label": field["label"], "unit": field["unit"], "candidates": candidates})
        else:
            _require(type(field.get("default_candidate_ids")) is list
                     and set(field["default_candidate_ids"]) <= {candidate["id"] for candidate in candidates},
                     "device_ai_decision_dependency_missing")
            fields.append(deepcopy(field))
    result = {"frozen_identity_contract": _frozen_identity(member),
              "snapshot_identity_contract": member["payload"]["snapshot_identity_contract"],
              "field_policy": deepcopy(resolution["policy"]), "fields": fields,
              "scope": "device_single_observation" if mode == "single_observation" else "device_frozen_decision_closure"}
    # payload.variant.facts may contain canonical/merged data; never copy it.
    _no_excluded_material(result)
    return result


def _vehicle(member: dict) -> dict:
    payload = member["payload"]
    _shape(payload, {"vehicle", "trims", "fitments", "footnotes", "fact_hash", "fact_version", "excluded_document_count"})
    _hash(payload["fact_hash"])
    _meta_int(payload["fact_version"], minimum=1)
    _meta_int(payload["excluded_document_count"])
    _require(type(payload["vehicle"]) is dict and all(type(payload[key]) is list for key in ("trims", "fitments", "footnotes")))
    _id(payload["vehicle"].get("id"))
    trim_ids = [_id(trim.get("id")) for trim in payload["trims"] if type(trim) is dict]
    _require(len(trim_ids) == len(payload["trims"]) and len(set(trim_ids)) == len(trim_ids))
    fitment_ids = []
    for fitment in payload["fitments"]:
        _require(type(fitment) is dict and fitment.get("trim_id") in trim_ids
                 and type(fitment.get("front")) is dict and type(fitment.get("rear")) is dict)
        fitment_ids.append(_id(fitment.get("id")))
        for axle in ("front", "rear"):
            _id(fitment[axle].get("size"))
    _require(len(set(fitment_ids)) == len(fitment_ids))
    _no_excluded_material(payload)
    return deepcopy(payload)


def _receipt_evidence(evidence: dict, member: dict) -> None:
    _require(type(evidence) is dict)
    ref, source = member["reference"], member["source"]
    _require(evidence.get("snapshot_id") == ref["snapshot_id"]
             and evidence.get("verification_id") == ref["verification_id"], "device_ai_receipt_mismatch")
    for key in ("observed_at", "verified_at"):
        _require(evidence.get(key) == source[key], "device_ai_receipt_mismatch")


def _recall(member: dict) -> dict:
    payload = member["payload"]
    _shape(payload, {"evidence", "records", "facts", "policy", "boundary"})
    evidence, records, boundary = payload["evidence"], payload["records"], payload["boundary"]
    _receipt_evidence(evidence, member)
    _require(evidence.get("evidence_type") == "recall" and evidence.get("applicability") == "not_assessed"
             and evidence.get("recall_revision_id") == member["reference"]["recall_revision_id"])
    _require(type(records) is list and len(records) <= 1000 and _meta_int(evidence.get("record_count"), 1000) == len(records))
    _require(evidence.get("observation_kind") == ("records" if records else "empty"))
    _require(hashlib.sha256(canonical_exact_json(records)).hexdigest() == evidence.get("records_hash"),
             "device_ai_recall_records_mismatch")
    _shape(boundary, {"policy", "mode", "applicability", "notice"})
    _require(boundary["policy"] == "recall-fact-selection@1" and boundary["mode"] == "announcement_facts_only"
             and boundary["applicability"] == "not_assessed")
    _shape(payload["policy"], {"version", "digest"})
    _require(payload["policy"]["version"] == boundary["policy"])
    _hash(payload["policy"]["digest"])
    scopes = evidence.get("record_scopes")
    _require(type(scopes) is list and len(scopes) == len(records))
    record_by_key, occurrences = {}, {}
    for index, (record, scope) in enumerate(zip(records, scopes)):
        _shape(record, {"campaign_number", "manufacturer", "report_received_date", "report_received_date_raw",
                        "component", "potential_units", "summary", "consequence", "remedy", "notes",
                        "make", "model", "model_year_raw", "applicability"})
        _require(record.get("campaign_number") == evidence.get("campaign_number")
                 and record.get("applicability") == "not_assessed")
        digest = hashlib.sha256(canonical_exact_json(record)).hexdigest()
        occurrences[digest] = occurrences.get(digest, 0) + 1
        _shape(scope, {"index", "occurrence", "record_hash", "record_key"})
        _require(_meta_int(scope["index"], 999) == index and _meta_int(scope["occurrence"], 1000, 1) == occurrences[digest]
                 and scope["record_hash"] == digest and scope["record_key"] == f"{digest}:{occurrences[digest]}",
                 "device_ai_recall_records_mismatch")
        record_by_key[scope["record_key"]] = record
    _require(type(payload["facts"]) is list)
    for fact in payload["facts"]:
        _shape(fact, {"domain", "field", "field_code", "value", "scope", "record_key", "text"})
        _require(fact["domain"] == "recall" and type(fact["field_code"]) is str and fact["field_code"].startswith("recall."))
        name = fact["field_code"].removeprefix("recall.")
        if fact["scope"] == "record":
            _require(fact["record_key"] in record_by_key and name in record_by_key[fact["record_key"]])
            expected = record_by_key[fact["record_key"]][name]
        else:
            _require(fact["scope"] == "observation" and fact["record_key"] is None
                     and name in {"campaign_number", "record_count", "observation_kind", "applicability"})
            expected = evidence[name]
        _require(canonical_exact_json(fact["value"]) == canonical_exact_json(expected), "device_ai_recall_fact_mismatch")
    _no_excluded_material(payload)
    return deepcopy(payload)


def _recall_search(member: dict) -> dict:
    payload = member["payload"]
    _shape(payload, {"query", "discovery", "discovery_hash", "notices", "evidence", "empty_observation", "boundary"})
    _shape(payload["evidence"], {"snapshot_id", "query_id", "verification_id", "data_state", "observed_at", "verified_at"})
    _receipt_evidence(payload["evidence"], member)
    _require(payload["evidence"].get("data_state") == "local_snapshot")
    _shape(payload["query"], {"search", "offset"})
    _id(payload["query"]["search"])
    offset = payload["query"]["offset"]
    _require(type(offset) is str and bool(re.fullmatch(r"0|[1-9][0-9]{0,4}", offset)) and int(offset) <= 10000)
    discovery = _shape(payload["discovery"], {"products", "pagination"})
    products = discovery["products"]
    _require(type(products) is list and len(products) <= 10 and payload["empty_observation"] is (not products))
    page = _shape(discovery["pagination"], {"count", "max", "offset", "total", "has_next", "has_previous"})
    _require(_meta_int(page["count"], 10) == len(products) and _meta_int(page["max"], 10) == 10
             and _meta_int(page["offset"], 10000) == int(offset))
    _meta_int(page["total"])
    _require(type(page["has_next"]) is bool and type(page["has_previous"]) is bool)
    boundary = _shape(payload["boundary"], {"kind", "formal_campaign_revision", "applicability", "complete_query_result"})
    _require(boundary == {"kind": "recall_search_candidate_page", "formal_campaign_revision": False,
                          "applicability": "not_assessed", "complete_query_result": False})
    _require(hashlib.sha256(canonical_exact_json(discovery)).hexdigest() == payload["discovery_hash"],
             "device_ai_search_page_mismatch")
    _require(type(payload["notices"]) is list and all(type(notice) is str for notice in payload["notices"]))
    for product in products:
        _require(type(product) is dict and product.get("applicability") == "not_assessed")
    _no_excluded_material(payload)
    return deepcopy(payload)


def _test_event(member: dict) -> dict:
    payload = member["payload"]
    _shape(payload, {"metadata", "event"})
    metadata, event, ref = payload["metadata"], payload["event"], member["reference"]
    _require(type(metadata) is dict and type(event) is dict
             and metadata.get("id") == ref["event_id"]
             and _meta_int(metadata.get("revision"), 2_147_483_647, 1) == _meta_int(ref["event_revision"], 2_147_483_647, 1)
             and metadata.get("record_kind") == "manual_transcription"
             and metadata.get("verification_status") == "unverified" and metadata.get("verified_at") is None)
    _require(type(event.get("participants")) is list and type(event.get("metrics")) is list
             and type(event.get("measurements")) is list)
    _no_excluded_material(payload)
    return deepcopy(payload)


def project_offline_pack(raw: bytes, expected: FrozenPackBinding, selectors: Sequence[Mapping[str, Any]], *,
                         mode: str = "single_observation", approved_closure: Sequence[Mapping[str, Any]] | None = None,
                         max_projection_bytes: int = MAX_PROJECTION_BYTES) -> DeviceProjection:
    """Project selected original observations, never warehouse/current content.

    Closure expansion must be explicitly supplied as exact approved selectors.
    This equality check is a scope gate, not evidence that a human consented.
    Current rights and Provider permission must be enforced by the future caller.
    """
    _require(mode in {"single_observation", "frozen_decision_closure", "complete_observation",
                      "complete_formal_observation", "candidate_page_context", "complete_event_context"},
             "device_ai_projection_mode_unsupported")
    _require(type(selectors) in {list, tuple} and 0 < len(selectors) <= 6, "device_ai_selector_capacity")
    _meta_int(max_projection_bytes, MAX_PROJECTION_BYTES, 1)
    envelope, members, documents = _load(raw, expected)
    selected = [_select(selector, expected.schema, members, documents) for selector in selectors]
    requested = {item[0]["member_key"]: item[0] for item in selected}
    _require(len(requested) == len(selected), "device_ai_selector_ambiguous")
    resolved = dict(requested)
    if mode == "frozen_decision_closure":
        queue = list(resolved)
        for key in queue:
            member = members[key]
            _require(member["reference"]["kind"] == "tire", "device_ai_projection_mode_unsupported")
            for field in _resolution(member)["fields"]:
                _require(type(field) is dict and type(field.get("candidates")) is list)
                for candidate in field["candidates"]:
                    dependency = _candidate_origin(candidate, members)
                    _require(members[dependency]["reference"]["variant_id"] == member["reference"]["variant_id"],
                             "device_ai_decision_dependency_mismatch")
                    if dependency not in resolved:
                        reference = _reference(members[dependency]["reference"], expected.schema)
                        resolved[dependency] = {"kind": "tire", "member_key": dependency, "document_id": None,
                                                "record_index": None, "reference": reference}
                        queue.append(dependency)
        if resolved.keys() != requested.keys() or approved_closure is not None:
            _require(type(approved_closure) in {list, tuple} and len(approved_closure) == len(resolved),
                     "device_ai_closure_consent_required")
            approved = [_select(selector, expected.schema, members, documents)[0] for selector in approved_closure]
            _require({canonical_exact_json(item) for item in approved} == {canonical_exact_json(item) for item in resolved.values()},
                     "device_ai_closure_consent_required")
    else:
        _require(approved_closure is None, "device_ai_projection_mode_unsupported")
    observations = []
    converters = {"vehicle": ("complete_observation", _vehicle), "recall": ("complete_formal_observation", _recall),
                  "recall_search": ("candidate_page_context", _recall_search), "test_event": ("complete_event_context", _test_event)}
    for key in sorted(resolved):
        member = members[key]
        kind = member["reference"]["kind"]
        # Test events always originate as restricted manual material; labels cannot downgrade them.
        _require(member["privacy_class"] != "restricted" and kind != "test_event", "device_ai_selected_restricted")
        if kind == "tire":
            _require(mode in {"single_observation", "frozen_decision_closure"}, "device_ai_projection_mode_unsupported")
            material = _tire(member, members, mode)
        else:
            required_mode, converter = converters[kind]
            _require(mode == required_mode, "device_ai_projection_mode_unsupported")
            material = converter(member)
        focus = resolved[key]["record_index"]
        if focus is not None:
            records = member["payload"].get("records") if kind == "recall" else member["payload"]["discovery"]["products"]
            _require(focus < len(records), "device_ai_record_mismatch")
        observations.append({"selector": resolved[key], "selection_reason": "requested" if key in requested else "decision_dependency",
                             "source": deepcopy(member["source"]), "material": material})
    result = {"schema": POLICY_VERSION, "data_state": "local_snapshot", "source_refresh_performed": False,
              "privacy_class": "private", "projection_mode": mode,
              "archive": {"package_id": expected.package_id, "package_schema": expected.schema, "sha256": expected.sha256},
              "observations": observations}
    canonical = canonical_exact_json(result)
    _require(len(canonical) <= max_projection_bytes, "device_ai_projection_capacity")
    dto = json.dumps(token_dto(result), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return DeviceProjection(canonical, hashlib.sha256(canonical).hexdigest(), dto, len(observations))
