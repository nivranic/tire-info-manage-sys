# One-shot generator for fixtures.json (run once, output reviewed; not a test).
# Basis (four-end maximal common valid prepare body, four-domain kind = tire):
#   apps/desktop/src-tauri/src/device_ai_host/tests.rs valid_prepare_json()
#   packages/api-client/tests/device-ai/device-ai-host-selftest.mts validPrepare (I区)
#   apps/api/tests/test_device_ai_dto.py base_body
# Per-end expected codes were READ from the four implementations (never guessed):
#   py  apps/api/tire_api/device_ai.py (pydantic StrictModel extra=forbid)
#   ts  packages/api-client/src/device-ai-host.ts (assertDeviceAiPrepareBody / submitStream)
#   rs  apps/desktop/src-tauri/src/device_ai_host.rs (serde deny_unknown_fields + assert_device_ai_prepare_body)
#   jv  apps/mobile/.../DeviceAiHost.java (assertPrepareBody / assertDeviceAiAnySelector / submitStream)
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[3] / ".artifacts/device-ai50/specs/decoder-fixtures-a/fixtures.json"

EF = "ef" * 32
NINE_A = "9a" * 32
NINE_9 = "99" * 32
ZERO_1 = "01" * 32
MK_AB = "ab" * 32
MK_CD = "cd" * 32
RECEIPT = "0ab9e6c8-1f2d-4a3e-9c0b-7d6e5f4a3b2c"
RECEIPT_V0 = "0ab9e6c8-1f2d-0a3e-9c0b-7d6e5f4a3b2c"
RECEIPT_HYPHENLESS = "0ab9e6c81f2d4a3e9c0b7d6e5f4a3b2c"
INTENT = "123e4567-e89b-42d3-a456-426614174000"

V = "validation_error"
I = "device_ai_host_invalid_argument"
C = "closed_fields_error"
S = "serde_deserialize_error"
A = "accept"


def tire_selector(member_key, document_id=None, snap="snap-1", variant="var-1", verif="ver-1"):
    return {
        "kind": "tire", "member_key": member_key, "document_id": document_id, "record_index": None,
        "reference": {"kind": "tire", "snapshot_id": snap, "variant_id": variant, "verification_id": verif},
    }


SEL_A = tire_selector(MK_AB)
SEL_CLOSED = tire_selector(MK_CD, "doc-2", "snap-2", "var-2", "ver-2")
SEVEN_KEYS = [format(index, "064x") for index in range(7)]


def prepare_body(**overrides):
    body = {
        "package_id": "pkg-1",
        "expected_sha256": EF,
        "expected_byte_count": 1234,
        "expected_schema": "offline-pack@2",
        "expected_owner_scope_id": NINE_A,
        "selectors": [tire_selector(MK_AB)],
        "projection_mode": "single_observation",
        "approved_closure": None,
        "expected_projection_sha256": NINE_9,
        "question_sha256": ZERO_1,
        "host_receipt_id": RECEIPT,
        "intent_id": INTENT,
    }
    body.update(overrides)
    return body


def consent_body(**overrides):
    value = {
        "expected_pack_fingerprint": "1" * 64,
        "expected_device_context_fingerprint": "2" * 64,
        "question_sha256": "3" * 64,
        "provider": "openai_responses",
        "model": "synthetic-model",
        "expected_provider_policy_fingerprint": "4" * 64,
    }
    value.update(overrides)
    return value


def case(case_id, matrix_ref, message, verdict, payload, expected):
    return {"id": case_id, "matrix_ref": matrix_ref, "message": message,
            "verdict": verdict, "payload": payload, "expected": expected}


cases = [
    # M1 — unknown fields / missing required key (closed key set).
    case("M1-prepare-unknown-top-field", "M1", "prepare_body", "reject",
         prepare_body(origin="device_history"),
         {"py": V, "ts": C, "rs": S, "jv": C}),
    case("M1-prepare-selector-unknown-field", "M1", "prepare_body", "reject",
         prepare_body(selectors=[dict(SEL_A, confidence="x")]),
         {"py": V, "ts": A, "rs": S, "jv": A}),
    case("M1-prepare-reference-unknown-field", "M1", "prepare_body", "reject",
         prepare_body(selectors=[dict(SEL_A, reference=dict(SEL_A["reference"], extra_ref="x"))]),
         {"py": V, "ts": A, "rs": S, "jv": I}),
    case("M1-prepare-missing-required-key", "M1", "prepare_body", "reject",
         {key: value for key, value in prepare_body().items() if key != "question_sha256"},
         {"py": V, "ts": C, "rs": S, "jv": C}),
    case("M1-consent-unknown-field", "M1", "provider_consent", "reject",
         consent_body(signed_at="2026-10-03T00:00:00Z"),
         {"py": V, "ts": C, "rs": S, "jv": C}),
    # M2 — illegal discriminants.
    case("M2-prepare-unknown-schema", "M2", "prepare_body", "reject",
         prepare_body(expected_schema="offline-pack@3"),
         {"py": V, "ts": I, "rs": I, "jv": I}),
    case("M2-prepare-unknown-projection-mode", "M2", "prepare_body", "reject",
         prepare_body(projection_mode="frozen_observation"),
         {"py": V, "ts": I, "rs": I, "jv": I}),
    case("M2-prepare-selector-kind-test-event", "M2", "prepare_body", "reject",
         prepare_body(selectors=[{
             "kind": "test_event", "member_key": MK_AB, "document_id": None, "record_index": None,
             "reference": {"kind": "test_event", "event_id": "evt-1", "event_revision": 1},
         }]),
         {"py": V, "ts": I, "rs": S, "jv": I}),
    # M3 — absent-never / null-carried tristate (D8 verdict: null-carried).
    case("M3-M10-nonclosure-carries-approved-closure", "M3/M10", "prepare_body", "reject",
         prepare_body(approved_closure=[SEL_CLOSED]),
         {"py": V, "ts": I, "rs": I, "jv": I}),
    case("M3-nonclosure-approved-closure-empty-array", "M3", "prepare_body", "reject",
         prepare_body(approved_closure=[]),
         {"py": V, "ts": I, "rs": I, "jv": I}),
    case("M3-nonclosure-approved-closure-null", "M3", "prepare_body", "accept",
         prepare_body(approved_closure=None),
         {"py": None, "ts": None, "rs": None, "jv": None}),
    case("M3-closure-mode-closure-absent", "M3", "prepare_body", "reject",
         {key: value for key, value in prepare_body(
             projection_mode="frozen_decision_closure").items() if key != "approved_closure"},
         {"py": V, "ts": C, "rs": I, "jv": C}),
    case("M3-closure-mode-empty-array", "M3", "prepare_body", "reject",
         prepare_body(projection_mode="frozen_decision_closure", approved_closure=[]),
         {"py": V, "ts": I, "rs": I, "jv": I}),
    case("M3-closure-mode-valid-closure", "M3", "prepare_body", "accept",
         prepare_body(projection_mode="frozen_decision_closure", approved_closure=[SEL_CLOSED]),
         {"py": None, "ts": None, "rs": None, "jv": None}),
    # M4 — include_context_ids must not appear on the prepare wire (server has no
    # such field, so a non-empty value is rejected as an unknown top-level key).
    case("M4-prepare-include-context-ids-nonempty", "M4", "prepare_body", "reject",
         prepare_body(include_context_ids=["archive-1"]),
         {"py": V, "ts": C, "rs": S, "jv": C}),
    # M6 — UUID spellings (D1: frozen text takes the strict Host set; the server
    # stays a receiving-side historical superset).
    case("M6-uuid-uppercase-accepted", "M6", "prepare_body", "accept",
         prepare_body(host_receipt_id=RECEIPT.upper()),
         {"py": None, "ts": None, "rs": None, "jv": None}),
    case("M6-uuid-hyphenless-hex-rejected", "M6", "prepare_body", "reject",
         prepare_body(host_receipt_id=RECEIPT_HYPHENLESS),
         {"py": A, "ts": I, "rs": I, "jv": I}),
    case("M6-uuid-version-zero-rejected", "M6", "prepare_body", "reject",
         prepare_body(host_receipt_id=RECEIPT_V0),
         {"py": A, "ts": I, "rs": I, "jv": I}),
    case("M6-uuid-not-a-uuid-rejected", "M6", "prepare_body", "reject",
         prepare_body(host_receipt_id="not-a-uuid"),
         {"py": V, "ts": I, "rs": I, "jv": I}),
    # M8 — hash64 negative family.
    case("M8-uppercase-expected-sha256", "M8", "prepare_body", "reject",
         prepare_body(expected_sha256="EF" * 32),
         {"py": V, "ts": I, "rs": I, "jv": I}),
    case("M8-short-member-key", "M8", "prepare_body", "reject",
         prepare_body(selectors=[tire_selector("a" * 63)]),
         {"py": V, "ts": I, "rs": I, "jv": I}),
    # M9 — SELECTOR_CAPACITY (6).
    case("M9-selector-capacity-seven", "M9", "prepare_body", "reject",
         prepare_body(selectors=[tire_selector(key) for key in SEVEN_KEYS]),
         {"py": V, "ts": I, "rs": I, "jv": I}),
    case("M9-closure-capacity-seven", "M9", "prepare_body", "reject",
         prepare_body(projection_mode="frozen_decision_closure",
                      approved_closure=[tire_selector(key) for key in SEVEN_KEYS]),
         {"py": V, "ts": I, "rs": I, "jv": I}),
    # D4 — expected_byte_count bound (1..8,388,608 inclusive, three Hosts + server).
    case("D4-byte-count-one-over-bound", "D4", "prepare_body", "reject",
         prepare_body(expected_byte_count=8388609),
         {"py": V, "ts": I, "rs": I, "jv": I}),
    case("D4-byte-count-at-bound", "D4", "prepare_body", "accept",
         prepare_body(expected_byte_count=8388608),
         {"py": None, "ts": None, "rs": None, "jv": None}),
]

by_matrix = {}
for item in cases:
    by_matrix[item["matrix_ref"]] = by_matrix.get(item["matrix_ref"], 0) + 1

payload = {
    "schema": "device-ai-decoder-fixtures@1",
    "spec_ref": "decoder-spec.md section 3 (M1-M10) + 2.6 D4/D8 + 4.3-2/4.3-3",
    "carrier_verdict": (
        "decoder-spec 4.3-3: unified closed-decoder fixtures. verdict is the frozen-text "
        "judgement (Host-strict where 2.6 D1/D7 recorded direction); expected.<end> is that "
        "end's OBSERVED runtime behaviour at its decoder layer, read from the implementations."
    ),
    "legend": {
        "expected.null": "the case is accepted (verdict=accept: all four ends accept)",
        "expected.accept": "this end's runtime decoder layer ACCEPTS even though verdict=reject (registered divergence, see notes)",
        "expected.validation_error": "py: pydantic ValidationError raised",
        "expected.device_ai_host_invalid_argument": "ts/rs/jv: Host closed fence code device_ai_host_invalid_argument",
        "expected.closed_fields_error": "ts/jv: closed key-set assertion fails as a plain programming error (message contains 'closed DTO'; jv IllegalStateException), not a Host fence code",
        "expected.serde_deserialize_error": "rs: rejected at the serde deserialization layer (deny_unknown_fields / missing required key / unknown reference enum tag), before the assert layer",
        "message": "decoder layer under test: prepare_body = DeviceAIPrepareRequest/assertDeviceAiPrepareBody; provider_consent = ProviderConsent/submitStream consent assertion",
    },
    "counts": {
        "total": len(cases),
        "accept": sum(1 for item in cases if item["verdict"] == "accept"),
        "reject": sum(1 for item in cases if item["verdict"] == "reject"),
        "by_matrix": by_matrix,
    },
    "notes": [
        "M7 (naive/zoneless timestamps) is a VIEW-layer rule: the prepare body carries no time "
        "field, so it cannot enter this prepare-body carrier; view-side negative anchors live in "
        "each end's view checks (ts selftest G24/G25, rs/jv naive-view negatives).",
        "M5 (question trim-once/codepoint bounds) belongs to the submit chain, which is not part "
        "of this prepare-body carrier; it can be added later as message:'submission' cases.",
        "M1 nested selector/reference unknown keys diverge at the ts/jv runtime assert layer: "
        "ts has no nested key-set assertion at all (TS types carry that duty at build time) and "
        "jv checks the per-kind reference key set but not the selector key set, while py "
        "(recursive extra=forbid) and rs (deny_unknown_fields on every wire struct) reject. "
        "expected.ts/expected.jv='accept' records the observed runtime behaviour; the final "
        "backstop is the server 422. Flagged for Root as a spec 2.6-unlisted divergence.",
        "M6 hyphenless/version-zero UUIDs: py accepts and canonicalizes (uuid.UUID receiving-side "
        "historical superset, decoder-spec 2.6 D1 verdict — server left as-is), the three Hosts "
        "reject with device_ai_host_invalid_argument (frozen-text strict set). expected.py="
        "'accept' locks that registered superset fact; runners assert pydantic still accepts.",
        "M3 closure-mode absent key: ts/jv fail the top-level closed key set (explicit-presence, "
        "D7 frozen principle, ts assertion is the reference implementation); rs tolerates the "
        "absence at serde (#[serde(default)]) and rejects at the assert layer; py tolerates the "
        "absence (default None) and rejects in closure_shape. All four reject, at different layers.",
        "M4 on the prepare wire degenerates to the M1 mechanism: the server DTO has no "
        "include_context_ids field (extra=forbid 422) and the Hosts reject it as an unknown "
        "top-level key; the three-Host 'must be empty' gate for local previews is a different, "
        "non-wire layer (decoder-spec section 3 M4 row).",
        "M10 (non-closure carrying approved_closure) is semantically identical to the first M3 "
        "negative, so it is carried once as matrix_ref 'M3/M10'.",
    ],
    "cases": cases,
}

OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {OUT} with {len(cases)} cases; by_matrix={by_matrix}")
