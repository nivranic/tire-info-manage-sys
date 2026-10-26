"""Build only the new synthetic capacity corpus, using standard-library rules.

This generator never imports a product parser, canonicalizer or projector.
Existing device-ai-v1 files are read-only authority inputs, not output targets.
The new corpus's hand-reviewed closure-fingerprints.json and fingerprint spec
are immutable authoring inputs. They are verified, never regenerated, and make
this script reproducible from the managed checkout without ignored evidence.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "packages/domain-types/fixtures/device-ai-capacity-v1"
OLD = ROOT / "packages/domain-types/fixtures/device-ai-v1/projection-vectors-a"
N = 8_388_608


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    # All newly authored closure material contains strings, bool/null and small
    # metadata integers only. Source numeric lexemes in formal projections are
    # inherited as bytes below, not decoded or reserialized by this function.
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def write(name, value):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else (
        json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2,
                   allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


def read_old(name, expected_sha):
    raw = (OLD / name).read_bytes()
    assert sha(raw) == expected_sha, name
    return raw


def read_authority(name, expected_sha):
    path = OUT / name
    if not path.is_file():
        raise ValueError(f"Missing immutable managed authority input: {name}")
    raw = path.read_bytes()
    if sha(raw) != expected_sha:
        raise ValueError(f"Immutable managed authority SHA drift: {name}")
    return raw


def build():
    # Verify both hand-reviewed authority inputs before writing any derivative.
    # Never reconstruct them from the product or from ignored .artifacts data.
    read_authority("closure-fingerprints.json", "393a1839d5c3919b50dc837d3e5eedd7c5187a864b31d7d7c70520c33f9cf9b2")
    spec = read_authority("specs/fingerprint-spec.md", "d2b7524d0e86101885f08442d139ef0128481dba3992d396a46ef7af2e497345")
    OUT.mkdir(parents=True, exist_ok=True)
    boundary = []

    def recipe(identifier, prefix, size, expected_text=None, error=None):
        count = size - len(prefix)
        assert count >= 0
        raw = prefix + b" " * count
        expectation = {"state": "rejected", "error_code": error} if error else {
            "state": "accepted", "canonical_text": expected_text,
            "canonical_utf8_hex": expected_text.encode("utf-8").hex(),
            "canonical_sha256": sha(expected_text.encode("utf-8"))}
        boundary.append({"id": identifier, "input": {"form": "repeat_hex",
            "prefix_hex": prefix.hex(), "repeat_hex": "20", "repeat_count": count,
            "suffix_hex": ""}, "input_byte_count": len(raw),
            "input_sha256": sha(raw), "expected": expectation})

    for delta, label in [(-1, "n-minus-1"), (0, "n"), (1, "n-plus-1")]:
        recipe("ascii-" + label, b"0", N + delta, "0",
               "device_ai_package_capacity" if delta == 1 else None)
    for delta, label in [(0, "n"), (1, "n-plus-1")]:
        recipe("nonbmp-" + label, '{"t":"😀"}'.encode("utf-8"), N + delta,
               '{"t":"😀"}', "device_ai_package_capacity" if delta else None)
    for prefix, label, error in [(b"\xef\xbb\xbf0", "bom", "device_ai_json_bom"),
                                 (b'"\xff"', "invalid-utf8", "device_ai_json_utf8")]:
        recipe(label + "-n", prefix, N, error=error)
        recipe(label + "-n-plus-1", prefix, N + 1, error="device_ai_package_capacity")
    boundary.append({"id": "empty", "input": {"form": "repeat_hex", "prefix_hex": "",
        "repeat_hex": "20", "repeat_count": 0, "suffix_hex": ""},
        "input_byte_count": 0, "input_sha256": sha(b""),
        "expected": {"state": "rejected", "error_code": "device_ai_package_capacity"}})
    write("boundary-recipes.json", {"schema": "device-ai-capacity-recipes@1",
                                  "max_package_bytes": N, "cases": boundary})

    base = read_old("inputs/nonempty-pack.json", "5d5250cbd24e38d5c610ee75429ce3915b295d4e4f74dd47ede0e11bf318e862")
    descriptor = read_old("inputs/nonempty-descriptor.json", "9a647693195d96daa5a73237f108973dea4b43dce2b35eb94096ea404972629d")
    projection_input = read_old("domain/nonempty-tire-single/input.json", "d2f1f1ad761c6f100ada487c2abb83e4996c57f3751305df1320766e4763faf4")
    projection = read_old("domain/nonempty-tire-single/projection.canonical.json", "e6c42637f571dfb6695ec470a9c80d77d7ab42a879eeec1d7354ca0a2b5144e8")
    write("base-pack.json", base)
    write("base-descriptor.json", descriptor)
    write("projection-input.json", projection_input)
    write("projections/formal-base.canonical.json", projection)
    formal_cases = []
    for target, label in [(len(base), "base"), (N - 1, "n-minus-1"), (N, "n"), (N + 1, "n-plus-1")]:
        padding = target - len(base)
        raw = base + b" " * padding
        digest = sha(raw)
        expected = {"state": "rejected", "error_code": "device_ai_metadata_number_invalid"}
        if target <= N:
            # Exact inherited literal, precisely one fixed-length archive SHA
            # substitution. No product execution and no numeric decoding.
            needle = b'"sha256":"' + sha(base).encode("ascii") + b'"'
            assert projection.count(needle) == 1
            derived = projection.replace(needle, b'"sha256":"' + digest.encode("ascii") + b'"')
            name = "projections/formal-" + label + ".canonical.json"
            write(name, derived)
            expected = {"state": "accepted", "projection_file": name,
                        "projection_byte_count": len(derived), "projection_sha256": sha(derived)}
        formal_cases.append({"id": "formal-" + label, "padding_spaces": padding,
            "input_byte_count": len(raw), "input_sha256": digest,
            "parser_expected": {"state": "accepted"} if target <= N else {
                "state": "rejected", "error_code": "device_ai_package_capacity"},
            "expected": expected})
    write("formal-package.json", {"schema": "device-ai-formal-capacity@1",
        "base_pack": "base-pack.json", "base_descriptor": "base-descriptor.json",
        "projection_input": "projection-input.json", "cases": formal_cases})

    envelope = json.loads(base)
    original_tire = next(m for m in envelope["members"] if m["reference"]["kind"] == "tire")
    original_doc = next(d for d in envelope["documents"] if d["member_key"] == original_tire["key"])
    vehicle = next(m for m in envelope["members"] if m["reference"]["kind"] == "vehicle")
    vehicle_docs = [d for d in envelope["documents"] if d["member_key"] == vehicle["key"]]
    members, documents = [], []
    for letter, digit in [("a", "1"), ("b", "2"), ("d", "4")]:
        m = deepcopy(original_tire)
        m["key"] = digit * 64
        m["reference"]["snapshot_id"] = "capacity-snapshot-" + letter
        m["reference"]["verification_id"] = "capacity-verification-" + letter
        m["source"].update(verification_id=m["reference"]["verification_id"],
            raw_hash=sha(("synthetic-source-" + letter).encode("ascii")),
            source_id="capacity-source-" + letter,
            source_url="https://example.org/device-ai-capacity/" + letter)
        m["payload"]["variant"]["snapshot_id"] = m["reference"]["snapshot_id"]
        m["payload"]["variant"]["facts"] = {"synthetic_excluded_value": "not projected"}
        field = deepcopy(m["payload"]["field_resolution"]["fields"][0])
        candidate = field["candidates"][0]
        for name in ("snapshot_id", "variant_id", "verification_id"):
            candidate[name] = m["reference"][name]
        for name in ("source_id", "source_url", "raw_hash", "parser_version", "observed_at", "verified_at"):
            candidate[name] = m["source"][name]
        candidate.update(id=sha(("synthetic-candidate-" + letter).encode("ascii")),
                         value="Synthetic acoustic " + letter.upper())
        field.update(default_value=candidate["value"], default_candidate_ids=[candidate["id"]])
        m["payload"]["field_resolution"]["fields"] = [field]
        d = deepcopy(original_doc)
        d.update(id="capacity-document-" + letter, member_key=m["key"],
                 text="Synthetic capacity source " + letter.upper())
        d["facets"]["source_id"] = m["source"]["source_id"]
        members.append(m)
        documents.append(d)
    a, b, isolated = members
    a_field = a["payload"]["field_resolution"]["fields"][0]
    b_candidate = deepcopy(b["payload"]["field_resolution"]["fields"][0]["candidates"][0])
    a_field["candidates"].append(b_candidate)
    a_field.update(default_candidate_ids=[b_candidate["id"]], default_value=b_candidate["value"], state="conflict")
    envelope.update(package_id="capacity-synthetic-multimember", members=members + [vehicle],
                    documents=documents + vehicle_docs, contexts=[], omissions=[])
    pack = canonical(envelope)
    write("closure-pack.json", pack)

    def selector(member, document=None):
        return {"kind": member["reference"]["kind"], "member_key": member["key"],
                "document_id": document, "record_index": None, "reference": deepcopy(member["reference"])}

    sa, sb, sd = selector(a, documents[0]["id"]), selector(b), selector(isolated)
    sb_doc = selector(b, documents[1]["id"])
    binding = {"package_id": envelope["package_id"], "owner_scope_id": envelope["owner_scope_id"],
               "schema": envelope["schema"], "sha256": sha(pack), "byte_count": len(pack)}
    cases = []

    def expected_projection(selectors, mode):
        # Authority rule: A's two complete candidates prove A and B. B is a
        # self-dependency. D and vehicle are not reachable. Material is the
        # explicit field + closed five-key identity contract, not variant.facts.
        requested = {s["member_key"]: s for s in selectors}
        resolved = deepcopy(requested)
        if mode == "frozen_decision_closure":
            resolved.setdefault(b["key"], deepcopy(sb))
        observations = []
        for m in [a, b]:
            if m["key"] not in resolved:
                continue
            payload = m["payload"]
            fields = deepcopy(payload["field_resolution"]["fields"])
            if mode == "single_observation":
                allowed = {"id", "field", "source_field", "present", "value", "evidence_locator",
                    "evidence_valid", "missing_evidence", "snapshot_id", "variant_id", "verification_id",
                    "source_id", "source_url", "raw_hash", "parser_version", "observed_at", "verified_at"}
                fields = [{"field": f["field"], "label": f["label"], "unit": f["unit"],
                    "candidates": [{k: v for k, v in c.items() if k in allowed} for c in f["candidates"]
                                   if c["verification_id"] == m["reference"]["verification_id"]]} for f in fields]
            material = {"frozen_identity_contract": {k: deepcopy(payload["identity_contract"][k])
                for k in ["schema", "state", "current_key", "current_identity", "identity_status"]},
                "snapshot_identity_contract": payload["snapshot_identity_contract"],
                "field_policy": deepcopy(payload["field_resolution"]["policy"]), "fields": fields,
                "scope": "device_single_observation" if mode == "single_observation" else "device_frozen_decision_closure"}
            observations.append({"selector": resolved[m["key"]],
                "selection_reason": "requested" if m["key"] in requested else "decision_dependency",
                "source": deepcopy(m["source"]), "material": material})
        result = {"schema": "device-ai-projection@1", "data_state": "local_snapshot",
            "source_refresh_performed": False, "privacy_class": "private", "projection_mode": mode,
            "archive": {"package_id": binding["package_id"], "package_schema": binding["schema"], "sha256": binding["sha256"]},
            "observations": observations}
        return canonical(result), [o["selector"] for o in observations]

    def positive(identifier, selectors, approved, mode="frozen_decision_closure"):
        raw, resolved = expected_projection(selectors, mode)
        path = "projections/" + identifier + ".canonical.json"
        write(path, raw)
        cases.append({"id": identifier, "selectors": selectors, "approved_closure": approved, "mode": mode,
            "expected": {"state": "accepted", "projection_file": path, "projection_sha256": sha(raw),
                "projection_byte_count": len(raw), "resolved_closure": resolved}})

    positive("closure-a-to-b", [sa], [sa, sb])
    positive("closure-approved-reversed", [sa], [sb, sa])
    positive("selected-a-b", [sa, sb_doc], [sa, sb_doc])
    positive("selected-b-a", [sb_doc, sa], [sb_doc, sa])
    positive("single-a-isolated", [sa], None, "single_observation")

    def negative(identifier, selectors, approved, code, **extra):
        cases.append({"id": identifier, "selectors": selectors, "approved_closure": approved,
            "mode": "frozen_decision_closure", "expected": {"state": "rejected", "error_code": code}, **extra})

    negative("approval-absent", [sa], None, "device_ai_closure_consent_required")
    negative("approval-missing-b", [sa], [sa], "device_ai_closure_consent_required")
    negative("approval-duplicate-a", [sa], [sa, sa], "device_ai_closure_consent_required")
    negative("approval-superset-d", [sa], [sa, sb, sd], "device_ai_closure_consent_required")
    negative("approval-wrong-document", [sa], [sa, sb_doc], "device_ai_closure_consent_required")
    wrong_index = {**sb, "record_index": 0}
    negative("approval-wrong-index", [sa], [sa, wrong_index], "device_ai_selector_mismatch")
    wrong_reference = deepcopy(sb)
    wrong_reference["reference"]["verification_id"] = "wrong-receipt"
    negative("approval-wrong-reference", [sa], [sa, wrong_reference], "device_ai_receipt_mismatch")
    negative("selected-duplicate", [sa, sa], [sa, sb], "device_ai_selector_ambiguous")
    negative("selected-wrong-document", [{**sa, "document_id": documents[1]["id"]}], [sa, sb], "device_ai_document_mismatch")
    negative("selected-non-tire", [selector(vehicle)], None, "device_ai_projection_mode_unsupported")
    for label, code in [("cross-variant", "device_ai_decision_dependency_mismatch"),
                        ("restricted-dependency", "device_ai_selected_restricted")]:
        changed = deepcopy(envelope)
        cb = changed["members"][1]
        approved_b = deepcopy(sb)
        if label == "cross-variant":
            alternate = "capacity-different-variant"
            cb["reference"]["variant_id"] = alternate
            cb["payload"]["variant"]["id"] = alternate
            cb["payload"]["field_resolution"]["variant_id"] = alternate
            cb["payload"]["field_resolution"]["fields"][0]["candidates"][0]["variant_id"] = alternate
            changed["members"][0]["payload"]["field_resolution"]["fields"][0]["candidates"][1]["variant_id"] = alternate
            approved_b["reference"]["variant_id"] = alternate
        else:
            cb["privacy_class"] = "restricted"
            changed["documents"][1]["privacy_class"] = "restricted"
        changed_raw = canonical(changed)
        name = "closure-" + label + ".json"
        write(name, changed_raw)
        negative(label, [sa], [sa, approved_b], code, package_file=name,
            binding={**binding, "sha256": sha(changed_raw), "byte_count": len(changed_raw)})
    write("closure-package.json", {"schema": "device-ai-full-closure@1", "package_file": "closure-pack.json",
        "binding": binding, "dependency_edges": [[a["key"], a["key"]], [a["key"], b["key"]], [b["key"], b["key"]]],
        "unselected_member_keys": [isolated["key"], vehicle["key"]], "cases": cases})

    write("authority.json", {"schema": "device-ai-capacity-authority@1", "synthetic_only": True,
        "formal_source_root": "packages/domain-types/fixtures/device-ai-v1/projection-vectors-a",
        "formal_projection_source": "domain/nonempty-tire-single/projection.canonical.json",
        "formal_projection_source_sha256": sha(projection),
        "formal_projection_derivation": "Replace exactly one archive.sha256 literal with each actual padded raw package SHA; preserve every other byte.",
        "closure_derivation": "Explicit standard-library structural selection in generate_device_ai_capacity_fixtures.py; no product imports. A has A/B candidates, B only B; D/vehicle are unreachable. Five identity keys plus policy/fields/scope; observations sorted by member_key. See README.md.",
        "fingerprint_spec_source": ".artifacts/device-ai50/specs/fingerprint-spec.md",
        "fingerprint_spec_sha256": sha(spec), "fingerprint_spec_sections": ["0", "2", "3", "4"],
        "product_executed_to_generate_expected": False})
    write(".gitattributes", b"* -text\n")
    write("README.md", """# Device AI capacity / closure synthetic corpus v1

All material is synthetic. The 8 MiB limit applies to the complete unencrypted UTF-8 package body, including JSON whitespace and the envelope. Recipes expand real N-1/N/N+1 bytes; they never substitute a smaller decoder limit. Every loader pins manifest.json itself and validates every bound file plus each expanded size/SHA. Missing, corrupt, unbound and escaping paths fail closed.

Formal base-pack.json, descriptor, projection-input.json and the base canonical projection are exact read-only copies from device-ai-v1/projection-vectors-a (authority.json pins their lineage). projection-input.json supplies the original binding, selectors and mode. Padding appends ASCII JSON spaces after the original complete producer-shaped body. This is a synthetic descendant, not a claim that the producer emitted an 8 MiB body. Raw SHA changes; the full projection also changes because archive.sha256 binds the raw body. Derived canonical literals replace exactly that one 64-hex SHA in the inherited canonical literal, leaving all business observations and numeric lexemes byte-identical. N+1 parser fails capacity, while the projector's earlier binding metadata gate fails device_ai_metadata_number_invalid.

closure-pack.json is a newly authored producer-shaped synthetic descendant, not an original producer download. Three distinguishable tire receipts A/B/D share a variant; each has a unique snapshot, verification ID, source URL/ID/raw hash. Their single acoustic field has only string values. A contains proven A and B candidates and chooses B as default; B contains only its own candidate. Thus A expands to exactly A/B; D and an archived vehicle are unreachable. Source proofs remain complete. All requested selectors include the document ID and explicit null record_index; dependency B canonically has document_id and record_index null. Approved closure must equal those complete selectors exactly. Tests cover absent/missing/duplicate/superset consent, wrong document/index/receipt, duplicate selection, cross-variant dependency, non-tire and restricted dependency.

The independently authored closure projection rule is explicit: observations sort by member_key; preserve complete selector, requested/decision_dependency reason and source. Material copies only identity {schema,state,current_key,current_identity,identity_status}, snapshot_identity_contract, field policy, complete frozen fields and mode scope. variant/facts, lifecycle, member reasons and contexts are excluded. The single-observation case retains only A's own candidate with the closed provenance key set shown in the generator, without decisions. All newly projected values are strings/bools/null, so stdlib sort_keys/compact JSON exactly follows the spec without float conversion. Expected projections are generated from these stated structural rules, never from a product implementation.

closure-fingerprints.json preserves selected request order, sorts resolved selectors by member_key, and tests canonical UTF-8 byte ordering of currently supported recall boundary notices U+E000/U+10000. Canonical literal, UTF-8 hex, size and namespaced SHA are independently auditable. specs/fingerprint-spec.md is the exact authority source copied with its source SHA in authority.json; sections 0/2/3/4 govern these literals. Its historical pending-implementation labels are retained as source provenance, not current status. ADR-2026-063 governs the current acceptance boundary: native parser/helper parity is distinct from Python/TS full projection coverage; native full multi-member preview remains unsupported. Each formal case separates parser_expected from full-projector expected so the N+1 capacity error is not confused with the earlier projector metadata error.

The generator uses only Python standard library and writes only this new corpus. Original 127 device-ai-v1 files, provenance/pins/expected and sealed Python projection/encoder are untouched. No real professional materials, licensing, Provider, network, normal database, device or full V1 gate is accepted by these fixtures.
""".encode("utf-8"))
    entries = []
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            raw = path.read_bytes()
            entries.append({"path": path.relative_to(OUT).as_posix(), "byte_count": len(raw), "sha256": sha(raw)})
    manifest = write("manifest.json", {"schema": "device-ai-capacity-corpus@1", "synthetic_only": True,
                                   "max_package_bytes": N, "files": entries})
    print(json.dumps({"manifest_sha256": sha(manifest), "files": len(entries), "boundary_cases": len(boundary),
                      "formal_cases": len(formal_cases), "closure_cases": len(cases)}))


if __name__ == "__main__":
    build()
