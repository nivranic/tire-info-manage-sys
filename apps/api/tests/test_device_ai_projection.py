"""Pure tests over frozen producer49 download bytes, never its database/services.

The fixture manifests pin exact historical producer bytes. Mutated descendants
are rejection/scope counterexamples, not claims of newly authorized evidence.
No test imports main/db/adapters, invokes a parser/model, changes env or keys.
"""
import ast
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from tire_api import device_ai_projection as projection
from tire_api.device_ai_projection import (
    FrozenPackBinding, MAX_DEPTH, MAX_NODES, MAX_PACKAGE_BYTES, NumberLexeme,
    ProjectionError, canonical_exact_json, exact_digest, parse_exact_json,
    project_offline_pack,
)


ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / ".artifacts/query-fallback49/producer-v2-samples-a"
PINNED = {
    "legacy": "0d3f27af8747b9fc390d7dbb685e8ea34fab1fbe27ef7331bc9b1a704a7ced00",
    "nonempty": "5d5250cbd24e38d5c610ee75429ce3915b295d4e4f74dd47ede0e11bf318e862",
    "empty": "644a5b288c0c35f728da086d9e15a02fb0547b98489a0700ad245e4d22024574",
}
MODES = {"tire": "single_observation", "vehicle": "complete_observation",
         "recall": "complete_formal_observation", "recall_search": "candidate_page_context",
         "test_event": "complete_event_context"}


def sample(name="nonempty"):
    raw = (SAMPLES / f"{name}-pack.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PINNED[name]
    descriptor = json.loads((SAMPLES / f"{name}-descriptor.json").read_bytes())
    metadata = json.loads(raw)
    assert descriptor["sha256"] == PINNED[name] and descriptor["byte_count"] == len(raw)
    binding = FrozenPackBinding(descriptor["id"], descriptor["owner_scope_id"], descriptor["sha256"],
                                descriptor["byte_count"], metadata["schema"])
    return raw, binding, metadata


def selector_for(envelope, kind, *, index=0):
    member = [row for row in envelope["members"] if row["reference"]["kind"] == kind][index]
    document = next(row for row in envelope["documents"] if row["member_key"] == member["key"])
    return {"kind": kind, "member_key": member["key"], "document_id": document["id"],
            "record_index": document["record_index"], "reference": deepcopy(member["reference"])}


def counterexample(envelope, binding):
    """Independent encoding of a changed producer-shaped rejection fixture."""
    raw = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return raw, replace(binding, sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw))


def selected_member(envelope, kind="tire"):
    return next(row for row in envelope["members"] if row["reference"]["kind"] == kind)


def expect_error(code, call):
    with pytest.raises(ProjectionError) as error:
        call()
    assert error.value.code == code


@pytest.mark.parametrize("name", ["legacy", "nonempty", "empty"])
def test_original_producer_number_spellings_remain_in_ast(name):
    raw, _binding, _metadata = sample(name)
    envelope = parse_exact_json(raw)
    tire = selected_member(envelope)
    facts = tire["payload"]["variant"]["facts"]
    assert facts["reference_int"].token == "9007199254740993"
    assert facts["reference_float"].token == "1.0"
    assert facts["reference_tiny"].token == "5e-324"
    canonical = canonical_exact_json(envelope)
    assert b'"reference_float":1.0' in canonical
    assert b'"reference_int":9007199254740993' in canonical
    assert b'"reference_tiny":5e-324' in canonical


@pytest.mark.parametrize("name", ["legacy", "nonempty", "empty"])
def test_single_observation_uses_proven_candidates_not_variant_facts(name):
    raw, binding, envelope = sample(name)
    result = project_offline_pack(raw, binding, [selector_for(envelope, "tire")])
    dto = result.as_token_dto()
    assert dto["privacy_class"] == "private" and result.member_count == 1
    material = dto["observations"][0]["material"]
    assert material["scope"] == "device_single_observation"
    assert b"reference_int" not in result.canonical_bytes  # No proven FIELD_SPECS candidate.
    assert b"reference_float" not in result.canonical_bytes
    assert "variant" not in material and "facts" not in material
    assert "related_candidates" not in material["frozen_identity_contract"]
    source = dto["observations"][0]["source"]
    for field in material["fields"]:
        assert set(field) == {"field", "label", "unit", "candidates"}
        for candidate in field["candidates"]:
            assert candidate["verification_id"] == source["verification_id"]
            assert candidate["observed_at"] == source["observed_at"]
            assert candidate["verified_at"] == source["verified_at"]
    treadwear = next(row for row in material["fields"] if row["field"] == "utqg_treadwear")
    assert treadwear["candidates"][0]["value"] == {"schema": "device-number-token@1", "token": "300"}
    assert hashlib.sha256(result.canonical_bytes).hexdigest() == result.sha256
    assert dto["archive"]["sha256"] == PINNED[name]
    assert b'"member_reasons"' not in result.canonical_bytes and b'"contexts"' not in result.canonical_bytes


@pytest.mark.parametrize("kind", ["vehicle", "recall", "recall_search"])
def test_producer_domains_preserve_complete_parent_observation(kind):
    raw, binding, envelope = sample()
    if kind == "recall":
        nonempty_index = next(index for index, row in enumerate(
            [item for item in envelope["members"] if item["reference"]["kind"] == "recall"])
            if row["payload"]["records"])
        selector = selector_for(envelope, kind, index=nonempty_index)
    else:
        selector = selector_for(envelope, kind)
    result = project_offline_pack(raw, binding, [selector], mode=MODES[kind])
    material = parse_exact_json(result.canonical_bytes)["observations"][0]["material"]
    original = next(row for row in parse_exact_json(raw)["members"] if row["key"] == selector["member_key"])["payload"]
    assert canonical_exact_json(material) == canonical_exact_json(original)
    assert result.as_token_dto()["observations"][0]["selector"]["record_index"] == selector["record_index"]
    if kind == "recall":
        assert len(material["records"]) == 2  # Clicking record zero does not amputate parent boundary.
        assert material["boundary"]["applicability"] == "not_assessed"
    elif kind == "recall_search":
        assert material["boundary"]["formal_campaign_revision"] is False
        assert material["boundary"]["complete_query_result"] is False


def test_producer_empty_candidate_page_is_not_a_formal_recall():
    raw, binding, envelope = sample("empty")
    result = project_offline_pack(raw, binding, [selector_for(envelope, "recall_search")], mode="candidate_page_context")
    material = result.as_token_dto()["observations"][0]["material"]
    assert material["empty_observation"] is True and material["discovery"]["products"] == []
    assert material["query"]["search"] == "SYNTHETIC EMPTY"
    assert material["boundary"]["applicability"] == "not_assessed"
    assert "recall_revision_id" not in material


def test_producer_empty_formal_observation_remains_empty_history():
    raw, binding, envelope = sample()
    empty = next(row for row in envelope["members"] if row["reference"]["kind"] == "recall" and not row["payload"]["records"])
    selector = {"kind": "recall", "member_key": empty["key"], "document_id": None,
                "record_index": None, "reference": empty["reference"]}
    result = project_offline_pack(raw, binding, [selector], mode="complete_formal_observation")
    material = result.as_token_dto()["observations"][0]["material"]
    assert material["evidence"]["observation_kind"] == "empty"
    assert material["records"] == [] and material["boundary"]["applicability"] == "not_assessed"


@pytest.mark.parametrize("name", ["legacy", "nonempty", "empty"])
def test_actual_test_event_is_restricted_without_any_policy_override(name):
    raw, binding, envelope = sample(name)
    expect_error("device_ai_selected_restricted", lambda: project_offline_pack(
        raw, binding, [selector_for(envelope, "test_event")], mode="complete_event_context"))
    # Merely relabelling manual material cannot downgrade its policy.
    test_member = selected_member(envelope, "test_event")
    test_member["privacy_class"] = "public"
    for document in envelope["documents"]:
        if document["member_key"] == test_member["key"]:
            document["privacy_class"] = "public"
    changed, changed_binding = counterexample(envelope, binding)
    expect_error("device_ai_selected_restricted", lambda: project_offline_pack(
        changed, changed_binding, [selector_for(envelope, "test_event")], mode="complete_event_context"))


def test_frozen_decision_is_an_explicit_distinct_mode():
    raw, binding, envelope = sample()
    result = project_offline_pack(raw, binding, [selector_for(envelope, "tire")], mode="frozen_decision_closure")
    material = result.as_token_dto()["observations"][0]["material"]
    assert material["scope"] == "device_frozen_decision_closure"
    assert any("default_candidate_ids" in field for field in material["fields"])
    assert any("dimensions" in candidate for field in material["fields"] for candidate in field["candidates"])


def test_closure_acknowledgement_is_checked_even_without_expansion():
    raw, binding, envelope = sample()
    selector = selector_for(envelope, "tire")
    wrong = selector_for(envelope, "vehicle")
    expect_error("device_ai_closure_consent_required", lambda: project_offline_pack(
        raw, binding, [selector], mode="frozen_decision_closure", approved_closure=[wrong]))


def test_selected_document_privacy_cannot_disagree_with_member():
    _raw, binding, envelope = sample()
    selector = selector_for(envelope, "tire")
    next(row for row in envelope["documents"] if row["id"] == selector["document_id"])["privacy_class"] = "restricted"
    raw, binding = counterexample(envelope, binding)
    expect_error("device_ai_document_mismatch", lambda: project_offline_pack(raw, binding, [selector]))


@pytest.mark.parametrize("path", ["parser_identity", "current_identity", "candidate_extra", "search_evidence"])
def test_untyped_metadata_cannot_smuggle_personal_or_formal_evidence_context(path):
    _raw, binding, envelope = sample()
    kind = "recall_search" if path == "search_evidence" else "tire"
    selector = selector_for(envelope, kind)
    member = selected_member(envelope, kind)
    if path == "parser_identity":
        member["source"]["parser_identity"] = {"personal_name": "private-canary"}
    elif path == "current_identity":
        member["payload"]["identity_contract"]["current_identity"]["personal_name"] = "private-canary"
    elif path == "candidate_extra":
        member["payload"]["field_resolution"]["fields"][0]["candidates"][0]["personal_name"] = "private-canary"
    else:
        member["payload"]["evidence"]["evidence_type"] = "recall"
    raw, binding = counterexample(envelope, binding)
    with pytest.raises(ProjectionError):
        project_offline_pack(raw, binding, [selector], mode=MODES[kind])


def add_alternate_receipt(envelope):
    """Producer-shaped scope counterexample: same observation, distinct fixed receipt."""
    first = selected_member(envelope)
    alternate = deepcopy(first)
    alternate["reference"]["verification_id"] = "11111111-1111-4111-8111-111111111111"
    alternate["source"]["verification_id"] = alternate["reference"]["verification_id"]
    alternate["key"] = hashlib.sha256(json.dumps(alternate["reference"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    for field in first["payload"]["field_resolution"]["fields"]:
        extra = deepcopy(field["candidates"][0])
        extra["id"] = hashlib.sha256((extra["id"] + ":alternate-receipt").encode()).hexdigest()
        extra["verification_id"] = alternate["reference"]["verification_id"]
        field["candidates"].append(extra)
    alternate["payload"]["field_resolution"] = deepcopy(first["payload"]["field_resolution"])
    envelope["members"].append(alternate)
    return alternate


def test_single_excludes_another_receipt_and_closure_requires_explicit_scope():
    _raw, binding, envelope = sample()
    selector = selector_for(envelope, "tire")
    alternate = add_alternate_receipt(envelope)
    changed, changed_binding = counterexample(envelope, binding)
    result = project_offline_pack(changed, changed_binding, [selector])
    assert alternate["reference"]["verification_id"].encode() not in result.canonical_bytes
    expect_error("device_ai_closure_consent_required", lambda: project_offline_pack(
        changed, changed_binding, [selector], mode="frozen_decision_closure"))
    extra_selector = {"kind": "tire", "member_key": alternate["key"], "document_id": None,
                      "record_index": None, "reference": alternate["reference"]}
    # Full decisions here exceed the existing 44KB AI limit: never truncate to fit.
    expect_error("device_ai_projection_capacity", lambda: project_offline_pack(
        changed, changed_binding, [selector], mode="frozen_decision_closure", approved_closure=[selector, extra_selector]))


def test_absent_candidate_receipt_can_link_only_when_frozen_proof_is_unique():
    _raw, binding, envelope = sample()
    selector = selector_for(envelope, "tire")
    candidate = selected_member(envelope)["payload"]["field_resolution"]["fields"][0]["candidates"][0]
    candidate.pop("verification_id")
    changed, changed_binding = counterexample(envelope, binding)
    result = project_offline_pack(changed, changed_binding, [selector])
    assert result.member_count == 1  # Source/raw/time matches the sole archived receipt.
    add_alternate_receipt(envelope)
    changed, changed_binding = counterexample(envelope, binding)
    expect_error("device_ai_candidate_receipt_ambiguous_or_missing", lambda: project_offline_pack(changed, changed_binding, [selector]))


@pytest.mark.parametrize("attribute,value", [("raw_hash", "0" * 64), ("source_id", "not-the-original-source"),
                                           ("verified_at", "2000-01-01T00:00:00Z"), ("snapshot_id", "missing-snapshot")])
def test_mismatched_candidate_provenance_never_repairs_from_variant_facts(attribute, value):
    _raw, binding, envelope = sample()
    selector = selector_for(envelope, "tire")
    first = selected_member(envelope)["payload"]["field_resolution"]["fields"][0]
    first["candidates"][0][attribute] = value
    changed, changed_binding = counterexample(envelope, binding)
    with pytest.raises(ProjectionError):
        project_offline_pack(changed, changed_binding, [selector])


@pytest.mark.parametrize("fields", [("source_id",), ("source_url",), ("parser_version",),
                                    ("source_id", "source_url", "parser_version")])
def test_matching_null_formal_source_fields_are_not_a_proof(fields):
    _raw, binding, envelope = sample()
    selector = selector_for(envelope, "tire")
    member = selected_member(envelope)
    for name in fields:
        member["source"][name] = None
        for field in member["payload"]["field_resolution"]["fields"]:
            for candidate in field["candidates"]:
                candidate[name] = None
    raw, binding = counterexample(envelope, binding)
    expect_error("device_ai_source_proof_missing", lambda: project_offline_pack(raw, binding, [selector]))


@pytest.mark.parametrize("schema", [{"schema": "unapproved", "garage_id": "unselected-personal-context"},
                                    "unapproved-identity@99", False, 1])
def test_snapshot_identity_schema_cannot_smuggle_unselected_context(schema):
    _raw, binding, envelope = sample()
    selector = selector_for(envelope, "tire")
    selected_member(envelope)["payload"]["snapshot_identity_contract"] = schema
    raw, binding = counterexample(envelope, binding)
    expect_error("device_ai_snapshot_identity_unsupported", lambda: project_offline_pack(raw, binding, [selector]))


@pytest.mark.parametrize("field,value", [
    ("current_key", {"garage_id": "private"}), ("current_key", ["private"]),
    ("state", {"garage_id": "private"}), ("state", ["current"]), ("state", "future-unapproved"),
    ("identity_status", {"garage_id": "private"}), ("identity_status", ["complete"]),
    ("origin", {"garage_id": "private"}), ("tracking_state", ["current"]),
    ("reason_codes", [{"garage_id": "private"}]), ("related_candidates", [{"garage_id": "private"}]),
    ("unknown_private_field", "private"),
])
def test_entire_frozen_identity_contract_is_closed_and_typed(field, value):
    _raw, binding, envelope = sample()
    selector = selector_for(envelope, "tire")
    selected_member(envelope)["payload"]["identity_contract"][field] = value
    raw, binding = counterexample(envelope, binding)
    with pytest.raises(ProjectionError):
        project_offline_pack(raw, binding, [selector])


@pytest.mark.parametrize("field,value", [
    ("brand", {"garage_id": "private"}), ("brand", ["private"]),
    ("model", {"garage_id": "private"}), ("region", ["private"]),
    ("manufacturer_product_code", {"garage_id": "private"}),
    ("product_code_type", ["MSPN"]), ("size", {"garage_id": "private"}),
    ("load_index", ["104"]), ("speed_rating", ["Y"]), ("xl", "true"), ("hl", 1),
    ("oe_mark", {"garage_id": "private"}), ("acoustic_technology", ["private"]),
    ("run_flat", {"garage_id": "private"}), ("gtin", {"garage_id": "private"}),
    ("eprel_id", ["private"]), ("technology_features", [{"feature": {"enabled": True}}]),
    ("unknown_dimension", "private"),
])
def test_frozen_identity_dimensions_never_stringify_unknown_objects_or_lists(field, value):
    _raw, binding, envelope = sample()
    selector = selector_for(envelope, "tire")
    selected_member(envelope)["payload"]["identity_contract"]["current_identity"][field] = value
    raw, binding = counterexample(envelope, binding)
    with pytest.raises(ProjectionError):
        project_offline_pack(raw, binding, [selector])


@pytest.mark.parametrize("state", ["legacy_unbound", "legacy_needs_review"])
def test_legacy_contract_preserves_null_limitations_without_filling_identity(state):
    _raw, binding, envelope = sample()
    selector = selector_for(envelope, "tire")
    identity = selected_member(envelope)["payload"]["identity_contract"]
    identity.update(state=state, current_key=None, current_identity=None, identity_status=None,
                    tracking_state="identity_review_required")
    raw, binding = counterexample(envelope, binding)
    result = project_offline_pack(raw, binding, [selector])
    frozen = result.as_token_dto()["observations"][0]["material"]["frozen_identity_contract"]
    assert frozen["state"] == state and frozen["current_key"] is None and frozen["current_identity"] is None


@pytest.mark.parametrize("raw,code", [
    (b'{"x":1,"x":2}', "device_ai_json_duplicate_key"),
    (b'{"x":1,"\\u0078":2}', "device_ai_json_duplicate_key"),
    (b'\xef\xbb\xbf{}', "device_ai_json_bom"),
    (b'{"x":"\xff"}', "device_ai_json_utf8"),
    (b'{"x":"\\ud800"}', "device_ai_json_unicode"),
    (b'{"x":1e309}', "device_ai_number_nonfinite"),
    (b'{"x":-1e309}', "device_ai_number_nonfinite"),
    (b'{"x":NaN}', "device_ai_number_invalid"),
    (b'{"x":Infinity}', "device_ai_number_invalid"),
    (b'{} {}', "device_ai_json_invalid"),
    (b'{"x":01}', "device_ai_json_invalid"),
])
def test_strict_original_byte_parser(raw, code):
    expect_error(code, lambda: parse_exact_json(raw))


def test_large_integer_is_not_misclassified_as_nonfinite_float():
    literal = "9" * 1000  # >309 digits, never converted through float/int digit limit.
    value = parse_exact_json(("{\"value\":" + literal + "}").encode())
    assert value["value"].token == literal
    assert canonical_exact_json(value) == ("{\"value\":" + literal + "}").encode()
    assert NumberLexeme("1e-5000").token == "1e-5000"  # Source binary64 underflow is finite.


def test_depth_nodes_and_package_size_have_hard_bounds():
    assert parse_exact_json(b"[" * MAX_DEPTH + b"0" + b"]" * MAX_DEPTH)
    expect_error("device_ai_json_depth", lambda: parse_exact_json(b"[" * (MAX_DEPTH + 1) + b"0" + b"]" * (MAX_DEPTH + 1)))
    expect_error("device_ai_json_nodes", lambda: parse_exact_json(b"[" + b"0," * MAX_NODES + b"0]"))
    expect_error("device_ai_package_capacity", lambda: parse_exact_json(b" " * (MAX_PACKAGE_BYTES + 1)))
    expect_error("device_ai_package_capacity", lambda: parse_exact_json(b""))


def test_codepoint_order_number_lexemes_and_digest_have_literal_vectors():
    value = parse_exact_json('{"𐀀":9007199254740993,"s":"中文/\\u0001","n":1.00,"":-0}'.encode())
    expected = '{"n":1.00,"s":"中文/\\u0001","":-0,"𐀀":9007199254740993}'.encode()
    assert canonical_exact_json(value) == expected
    assert exact_digest(value, namespace="literal-vector@1") == hashlib.sha256(b"literal-vector@1\x00" + expected).hexdigest()
    assert projection.token_dto(value)["n"] == {"schema": "device-number-token@1", "token": "1.00"}
    expect_error("device_ai_number_or_type_unsupported", lambda: canonical_exact_json({"value": 0.1}))


@pytest.mark.parametrize("binding_change", ["sha256", "owner_scope_id", "package_id", "byte_count", "schema"])
def test_original_archive_binding_mismatch_is_closed(binding_change):
    raw, binding, envelope = sample()
    values = {"sha256": "0" * 64, "owner_scope_id": "0" * 64, "package_id": "wrong-package",
              "byte_count": binding.byte_count + 1, "schema": "offline-pack@1"}
    expect_error("device_ai_package_binding_mismatch", lambda: project_offline_pack(
        raw, replace(binding, **{binding_change: values[binding_change]}), [selector_for(envelope, "tire")]))


@pytest.mark.parametrize("change", ["extra_field", "wrong_receipt", "wrong_document", "record_without_document", "context_kind", "unknown_kind"])
def test_exact_selector_is_closed_and_cannot_choose_personal_context(change):
    raw, binding, envelope = sample()
    selector = selector_for(envelope, "tire")
    if change == "extra_field":
        selector["allow_external_processing"] = True
    elif change == "wrong_receipt":
        selector["reference"]["verification_id"] = "wrong-receipt"
    elif change == "wrong_document":
        selector["document_id"] = selector_for(envelope, "vehicle")["document_id"]
    elif change == "record_without_document":
        selector.update(document_id=None, record_index=0)
    elif change == "context_kind":
        selector["kind"] = "garage"
        selector["reference"] = {"kind": "garage", "vehicle_id": "private"}
    else:
        selector["reference"]["kind"] = "change_event"
    with pytest.raises(ProjectionError):
        project_offline_pack(raw, binding, [selector])


def test_capacity_rejects_whole_projection_and_input_bytes_are_unchanged():
    raw, binding, envelope = sample()
    before = hashlib.sha256(raw).hexdigest()
    expect_error("device_ai_projection_capacity", lambda: project_offline_pack(
        raw, binding, [selector_for(envelope, "tire")], max_projection_bytes=1))
    assert hashlib.sha256(raw).hexdigest() == before
    assert (SAMPLES / "nonempty-pack.json").read_bytes() == raw


@pytest.mark.parametrize("kind", ["recall", "recall_search"])
def test_domain_parent_receipt_and_candidate_formality_are_not_client_relabelled(kind):
    _raw, binding, envelope = sample()
    selector = selector_for(envelope, kind)
    member = selected_member(envelope, kind)
    if kind == "recall":
        member["payload"]["evidence"]["verification_id"] = "other-receipt"
    else:
        member["payload"]["boundary"]["formal_campaign_revision"] = True
    raw, binding = counterexample(envelope, binding)
    with pytest.raises(ProjectionError):
        project_offline_pack(raw, binding, [selector], mode=MODES[kind])


def test_selected_raw_or_secret_key_is_rejected_and_unselected_reasons_are_not_exported():
    _raw, binding, envelope = sample()
    selector = selector_for(envelope, "tire")
    member = selected_member(envelope)
    member["member_reasons"] = [{"selector": "garage", "object_id": "private-personal-canary"}]
    envelope["contexts"] = [{"private_canary": "private-personal-canary"}]
    raw, binding = counterexample(envelope, binding)
    result = project_offline_pack(raw, binding, [selector])
    assert b"private-personal-canary" not in result.canonical_bytes
    field = member["payload"]["field_resolution"]["fields"][0]
    field["candidates"][0]["value"] = {"api_key": "rejected-material-canary"}
    raw, binding = counterexample(envelope, binding)
    expect_error("device_ai_excluded_material", lambda: project_offline_pack(raw, binding, [selector]))


def test_module_imports_only_pure_standard_library_and_source_text_is_not_executed():
    module_tree = ast.parse(Path(projection.__file__).read_text(encoding="utf-8"))
    allowed = {"copy", "dataclasses", "datetime", "hashlib", "json", "math", "re", "typing"}
    for node in ast.walk(module_tree):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module in allowed
    text = 'Source text: import socket; network, permission and Provider are data.'
    assert parse_exact_json(json.dumps({"text": text}).encode())["text"] == text
    assert "public DTO/routes/ledger/migration/idempotency/SSE" in projection.UNIMPLEMENTED_INTEGRATION
