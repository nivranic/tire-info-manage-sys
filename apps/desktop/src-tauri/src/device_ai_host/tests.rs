//! device-ai host wiring tests: TS SDK selftest parity (sections B-H of
//! `.artifacts/device-ai50/host-sdk-selftest/device-ai-host-selftest.mts`),
//! cross-checked against the Python-reference digests in
//! `host-expected-fingerprints.json`, plus the closed serialization shapes of
//! the four server DTOs and the HTTP layer over the existing bridge (real
//! loopback server, same convention as `bridge/tests.rs`).

use super::*;
use crate::security::LaunchConfig;
use crate::session::{SessionStore, COOKIE_NAME};
use std::sync::Mutex as StdMutex;

const EXPECTED_PATH: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../.artifacts/device-ai50/host-sdk-selftest/host-expected-fingerprints.json"
);
const TEST_COOKIE: &str = "acd95df4-f31d-4275-8b9e-098a90cbb223";

// Shared mini inputs (lockstep with the TS selftest and
// gen-expected-fingerprints.py).
fn mk_a() -> String {
    "ab".repeat(32)
}
fn mk_b() -> String {
    "cd".repeat(32)
}
fn sel_a() -> DeviceAiSelectorWire {
    DeviceAiSelectorWire {
        kind: "tire".into(),
        member_key: mk_a(),
        document_id: None,
        record_index: None,
        reference: DeviceAiReferenceWire::Tire {
            snapshot_id: "snap-1".into(),
            variant_id: "var-1".into(),
            verification_id: "ver-1".into(),
        },
    }
}
fn sel_b() -> DeviceAiSelectorWire {
    DeviceAiSelectorWire {
        kind: "tire".into(),
        member_key: mk_b(),
        document_id: Some("doc-2".into()),
        record_index: None,
        reference: DeviceAiReferenceWire::Tire {
            snapshot_id: "snap-2".into(),
            variant_id: "var-2".into(),
            verification_id: "ver-2".into(),
        },
    }
}
fn sel_vehicle() -> DeviceAiSelectorWire {
    DeviceAiSelectorWire {
        kind: "vehicle".into(),
        member_key: "12".repeat(32),
        document_id: None,
        record_index: None,
        reference: DeviceAiReferenceWire::Vehicle {
            snapshot_id: "vsnap-1".into(),
            verification_id: "vver-1".into(),
        },
    }
}
fn sel_recall() -> DeviceAiSelectorWire {
    DeviceAiSelectorWire {
        kind: "recall".into(),
        member_key: "0f".repeat(32),
        document_id: Some("rdoc-1".into()),
        record_index: Some(3),
        reference: DeviceAiReferenceWire::Recall {
            snapshot_id: "rsnap-1".into(),
            recall_revision_id: Some("rrev-1".into()),
            verification_id: "rver-1".into(),
        },
    }
}
fn sel_recall_search() -> DeviceAiSelectorWire {
    DeviceAiSelectorWire {
        kind: "recall_search".into(),
        member_key: "ee".repeat(32),
        document_id: None,
        record_index: None,
        reference: DeviceAiReferenceWire::RecallSearch {
            snapshot_id: "ssnap-1".into(),
            verification_id: "sver-1".into(),
        },
    }
}
fn origin_fixture() -> DeviceAiOriginBindingWire {
    DeviceAiOriginBindingWire {
        expected_profile_id: "11111111-2222-4333-8444-555555555555".into(),
        expected_owner_epoch: 1,
        slot_id: "slot-1".into(),
        expected_generation: 2,
        package_id: "pkg-1".into(),
        expected_sha256: "ef".repeat(32),
        expected_byte_count: 1234,
        owner_scope_id: "9a".repeat(32),
        package_schema: "offline-pack@2".into(),
    }
}
const QUESTION: &str = "P225 这条轮胎的历史参数如何解析？";
const SOURCE_JSON: &str = r#"{"source_id":"src-1","observed_at":"2026-01-01T00:00:00Z","verified_at":null,"verification_id":"ver-1","load_index_9007199254740993":9007199254740993,"pressure":0.1000000000000000001,"negative_zero":-0}"#;

fn expected_fingerprints() -> Value {
    let raw = std::fs::read_to_string(EXPECTED_PATH)
        .unwrap_or_else(|error| panic!("read expected fingerprints {EXPECTED_PATH}: {error}"));
    serde_json::from_str(&raw).expect("parse expected fingerprints")
}

fn sorted_keys(value: &Value) -> Vec<String> {
    let mut keys: Vec<String> = value.as_object().expect("object").keys().cloned().collect();
    keys.sort();
    keys
}

// ---------------------------------------------------------------------------
// B. question trim-once + bare sha256 parity (Python reference digests).
// ---------------------------------------------------------------------------

#[test]
fn question_trim_once_codepoints_and_sha256_parity() {
    assert_eq!(trim_once_question("  历史问题  "), "历史问题");
    // U+3000 and U+000B are Python whitespace; U+001C is too (beyond JS trim).
    assert_eq!(trim_once_question("　历史问题\u{0b}"), "历史问题");
    assert_eq!(trim_once_question("\u{1c}问题\u{1c}"), "问题");
    // Internal whitespace preserved; one pass strips the whole runs.
    assert_eq!(trim_once_question("问题  内容"), "问题  内容");
    assert_eq!(trim_once_question("   问题   内容   "), "问题   内容");
    // U+FEFF is NOT Python whitespace (a naive trim-everything would strip it).
    assert_eq!(trim_once_question("\u{feff}问题"), "\u{feff}问题");

    assert_eq!(normalize_question("ab").unwrap(), "ab");
    assert!(normalize_question("a").is_err());
    let wide = "𐀀".repeat(2000); // 2000 codepoints, 4000 UTF-16 units
    assert_eq!(normalize_question(&wide).unwrap(), wide.as_str());
    assert!(normalize_question(&"𐀀".repeat(2001)).is_err());
    assert!(normalize_question(&"𐀀𐀀".repeat(1001)).is_err());

    let expected = expected_fingerprints();
    for (text, digest) in expected["question_sha256"].as_object().expect("map") {
        assert_eq!(&question_sha256(text), digest.as_str().unwrap(), "{text:?}");
    }
    // No NFKC, no JSON quoting wrapper.
    assert_ne!(question_sha256("ﬃ 轮胎历史"), question_sha256("ffi 轮胎历史"));
    assert_ne!(question_sha256("text"), question_sha256("\"text\""));
}

#[test]
fn canonical_uuid_accepts_braced_uppercase_and_rejects_noncanonical() {
    assert_eq!(
        canonical_device_ai_uuid("9999AAAA-BBBB-4CCC-8DDD-5555EEE66666").unwrap(),
        "9999aaaa-bbbb-4ccc-8ddd-5555eee66666"
    );
    assert_eq!(
        canonical_device_ai_uuid("{9999aaaa-bbbb-4ccc-8ddd-5555eee66666}").unwrap(),
        "9999aaaa-bbbb-4ccc-8ddd-5555eee66666"
    );
    for bad in [
        "",                                     // empty
        "9999aaaa-bbbb-4ccc-8ddd-5555eee6666",  // short
        "9999aaaa0bbbb0cccc0dddd055555eee66666", // simple form (no hyphens)
        "9999aaaa-bbbb-0ccc-8ddd-5555eee66666", // version nibble 0
        "9999aaaa-bbbb-4ccc-cddd-5555eee66666", // variant nibble c
        "9999aaaa bbbb 4ccc 8ddd 5555eee66666", // separators
    ] {
        assert!(canonical_device_ai_uuid(bad).is_err(), "{bad}");
    }
}

// ---------------------------------------------------------------------------
// C. fingerprint parity (Python reference).
// ---------------------------------------------------------------------------

#[test]
fn fingerprint_parity_vs_python_reference() {
    let expected = expected_fingerprints();
    let selection = selection_sha256(&[sel_b(), sel_a()]).unwrap();
    assert_eq!(
        selection,
        expected["selection_sha256"].as_str().unwrap(),
        "selection_sha256 unordered == Python"
    );
    assert_eq!(
        selection_sha256(&[sel_a(), sel_b()]).unwrap(),
        selection,
        "request order must not matter"
    );
    assert_eq!(
        selection_sha256(&[sel_a(), sel_a()]).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );

    // device_context_fingerprint: numeric lexemes preserved through the AST.
    let source = parse_device_ai_package(SOURCE_JSON.as_bytes()).unwrap();
    let context_hash = device_context_fingerprint(&DeviceAiContextIdentityInput {
        package_id: "pkg-1".into(),
        package_schema: "offline-pack@2".into(),
        package_sha256: "ef".repeat(32),
        projection_mode: "single_observation".into(),
        projection_sha256: "99".repeat(32),
        selection_sha256: "01".repeat(32),
        receipt_sources: vec![DeviceAiReceiptSourceInput {
            selector: sel_a(),
            selection_reason: "requested".into(),
            source,
        }],
        device_citations: Vec::new(),
        domain_boundaries: Vec::new(),
    })
    .unwrap();
    assert_eq!(
        context_hash,
        expected["device_context_fingerprint"].as_str().unwrap(),
        "device_context_fingerprint == Python (lexemes 9007199254740993 / 0.1000000000000000001 / -0)"
    );

    let origin = origin_fixture();
    let preview_hash = local_preview_fingerprint(&DeviceAiLocalPreviewInput {
        question_sha256_value: &question_sha256(QUESTION),
        include_context_ids: &[],
        projection_mode: "single_observation",
        query_context: None,
        origin: &origin,
        selected: &[sel_b()],
        resolved_closure: &[sel_a()],
        state: DeviceAiPreviewState::Ready,
        projection_sha256_value: None,
    })
    .unwrap();
    assert_eq!(
        preview_hash,
        expected["local_preview_fingerprint"].as_str().unwrap(),
        "local_preview_fingerprint == Python"
    );
    let blocked = local_preview_fingerprint(&DeviceAiLocalPreviewInput {
        question_sha256_value: &question_sha256(QUESTION),
        include_context_ids: &[],
        projection_mode: "single_observation",
        query_context: None,
        origin: &origin,
        selected: &[sel_b()],
        resolved_closure: &[sel_a()],
        state: DeviceAiPreviewState::Blocked,
        projection_sha256_value: None,
    })
    .unwrap();
    assert_ne!(blocked, preview_hash, "blocked vs ready must differ");
    // blocked + projection digest is an invalid authorization object.
    assert!(local_preview_fingerprint(&DeviceAiLocalPreviewInput {
        question_sha256_value: &question_sha256(QUESTION),
        include_context_ids: &[],
        projection_mode: "single_observation",
        query_context: None,
        origin: &origin,
        selected: &[sel_b()],
        resolved_closure: &[sel_a()],
        state: DeviceAiPreviewState::Blocked,
        projection_sha256_value: Some("99".repeat(32).as_str()),
    })
    .is_err());
    // M4 (decoder-spec section 3): include_context_ids must stay EMPTY until
    // the frozen wire opens the archive-id intent channel; a non-empty list
    // fails closed before entering the fingerprint AST.
    assert_eq!(
        local_preview_fingerprint(&DeviceAiLocalPreviewInput {
            question_sha256_value: &question_sha256(QUESTION),
            include_context_ids: &["archive-1".to_owned()],
            projection_mode: "single_observation",
            query_context: None,
            origin: &origin,
            selected: &[sel_b()],
            resolved_closure: &[sel_a()],
            state: DeviceAiPreviewState::Ready,
            projection_sha256_value: None,
        })
        .unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );
}

// ---------------------------------------------------------------------------
// E. compute_local_preview over a mini envelope.
// ---------------------------------------------------------------------------

#[test]
fn compute_local_preview_mini_envelope() {
    let envelope = json!({
        "schema": "offline-pack@2", "package_id": "pkg-1", "owner_scope_id": "9a".repeat(32),
        "members": [
            { "member_key": mk_a(), "reference": { "kind": "tire", "snapshot_id": "snap-1", "variant_id": "var-1", "verification_id": "ver-1" } },
            { "member_key": mk_b(), "reference": { "kind": "tire", "snapshot_id": "snap-2", "variant_id": "var-2", "verification_id": "ver-2" } },
        ],
    });
    let bytes = serde_json::to_vec(&envelope).unwrap();
    let mut origin = origin_fixture();
    origin.expected_byte_count = bytes.len() as u64;
    origin.expected_sha256 = sha256_hex(&bytes);

    let summary = compute_local_preview(
        &bytes,
        &DeviceAiPreviewRequest {
            question: format!("  {QUESTION}  "),
            selectors: vec![sel_a()],
            origin: origin.clone(),
            include_context_ids: Vec::new(),
            projection_mode: None,
        },
    )
    .unwrap();
    let expected = expected_fingerprints();
    assert_eq!(summary.located_member_keys, vec![mk_a()]);
    assert_eq!(summary.package_byte_count as usize, bytes.len());
    assert_eq!(summary.package_schema, "offline-pack@2");
    assert_eq!(
        summary.question_sha256,
        expected["question_sha256"][QUESTION].as_str().unwrap(),
        "trim-once inside compute_local_preview"
    );
    assert_eq!(summary.selection_sha256, selection_sha256(&[sel_a()]).unwrap());
    assert_eq!(
        summary.local_preview_fingerprint,
        local_preview_fingerprint(&DeviceAiLocalPreviewInput {
            question_sha256_value: &question_sha256(QUESTION),
            include_context_ids: &[],
            projection_mode: "single_observation",
            query_context: None,
            origin: &origin,
            selected: &[sel_a()],
            resolved_closure: &[sel_a()],
            state: DeviceAiPreviewState::Ready,
            projection_sha256_value: None,
        })
        .unwrap()
    );
    assert_eq!(summary.projection_binding, "not_recomputed");
    assert_eq!(summary.notices.len(), 3);

    let mut wrong_sha = origin.clone();
    wrong_sha.expected_sha256 = "ff".repeat(32);
    assert_eq!(
        compute_local_preview(&bytes, &DeviceAiPreviewRequest {
            question: QUESTION.into(),
            selectors: vec![sel_a()],
            origin: wrong_sha,
            include_context_ids: Vec::new(),
            projection_mode: None,
        })
        .unwrap_err(),
        DeviceAiHostErrorCode::PackageMismatch
    );
    let mut wrong_count = origin.clone();
    wrong_count.expected_byte_count += 1;
    assert_eq!(
        compute_local_preview(&bytes, &DeviceAiPreviewRequest {
            question: QUESTION.into(),
            selectors: vec![sel_a()],
            origin: wrong_count,
            include_context_ids: Vec::new(),
            projection_mode: None,
        })
        .unwrap_err(),
        DeviceAiHostErrorCode::PackageMismatch
    );
    let mut unknown_member = sel_a();
    unknown_member.member_key = "ee".repeat(32);
    assert_eq!(
        compute_local_preview(&bytes, &DeviceAiPreviewRequest {
            question: QUESTION.into(),
            selectors: vec![unknown_member],
            origin: origin.clone(),
            include_context_ids: Vec::new(),
            projection_mode: None,
        })
        .unwrap_err(),
        DeviceAiHostErrorCode::PackageMismatch
    );
    let mut wrong_reference = sel_a();
    wrong_reference.reference = DeviceAiReferenceWire::Tire {
        snapshot_id: "snap-1".into(),
        variant_id: "var-1".into(),
        verification_id: "ver-9".into(),
    };
    assert_eq!(
        compute_local_preview(&bytes, &DeviceAiPreviewRequest {
            question: QUESTION.into(),
            selectors: vec![wrong_reference],
            origin: origin.clone(),
            include_context_ids: Vec::new(),
            projection_mode: None,
        })
        .unwrap_err(),
        DeviceAiHostErrorCode::PackageMismatch
    );
    assert_eq!(
        compute_local_preview(&bytes, &DeviceAiPreviewRequest {
            question: QUESTION.into(),
            selectors: vec![sel_a(), sel_b()],
            origin: origin.clone(),
            include_context_ids: Vec::new(),
            projection_mode: None,
        })
        .unwrap_err(),
        DeviceAiHostErrorCode::PreviewUnsupported
    );
    assert_eq!(
        compute_local_preview(&bytes, &DeviceAiPreviewRequest {
            question: QUESTION.into(),
            selectors: vec![sel_a()],
            origin,
            include_context_ids: Vec::new(),
            projection_mode: Some("frozen_decision_closure".into()),
        })
        .unwrap_err(),
        DeviceAiHostErrorCode::PreviewUnsupported
    );
}

// ---------------------------------------------------------------------------
// A/G4/G14-16. Closed serialization shapes against the frozen server lists.
// ---------------------------------------------------------------------------

fn valid_prepare_json() -> Value {
    json!({
        "package_id": "pkg-1", "expected_sha256": "ef".repeat(32), "expected_byte_count": 1234,
        "expected_schema": "offline-pack@2", "expected_owner_scope_id": "9a".repeat(32),
        "selectors": [sel_a()], "projection_mode": "single_observation", "approved_closure": null,
        "expected_projection_sha256": "99".repeat(32), "question_sha256": "01".repeat(32),
        "host_receipt_id": "11111111-2222-4333-8444-555555555555",
        "intent_id": "22222222-3333-4444-8555-666666666666",
    })
}

#[test]
fn closed_dto_serialization_shapes_match_server_field_lists() {
    let body: DeviceAiPrepareBody =
        serde_json::from_value(valid_prepare_json()).expect("valid prepare body parses");
    assert_device_ai_prepare_body(&body).unwrap();
    let canonical = canonicalize_prepare_body(&body).unwrap();
    let mut expected: Vec<&str> = DEVICE_AI_PREPARE_REQUEST_FIELDS.to_vec();
    expected.sort_unstable();
    assert_eq!(sorted_keys(&canonical), expected, "prepare body closed field set");
    // extra field rejected (server extra=forbid would 422)
    let mut extra = valid_prepare_json();
    extra["local_preview_fingerprint"] = json!("x".repeat(64));
    assert!(serde_json::from_value::<DeviceAiPrepareBody>(extra).is_err());
    // missing required field rejected
    let mut missing = valid_prepare_json();
    missing
        .as_object_mut()
        .unwrap()
        .remove("question_sha256");
    assert!(serde_json::from_value::<DeviceAiPrepareBody>(missing).is_err());
    // closure shape gate
    let mut closure = valid_prepare_json();
    closure["projection_mode"] = json!("frozen_decision_closure");
    let closure_body: DeviceAiPrepareBody = serde_json::from_value(closure).unwrap();
    assert_eq!(
        assert_device_ai_prepare_body(&closure_body).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );
    // M8 (decoder-spec section 3): hash64 negative family — uppercase and
    // wrong-length spellings fail the closed-body assertion like the server 422.
    let mut upper: DeviceAiPrepareBody = serde_json::from_value(valid_prepare_json()).unwrap();
    upper.expected_sha256 = "EF".repeat(32);
    assert_eq!(
        assert_device_ai_prepare_body(&upper).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );
    let mut short: DeviceAiPrepareBody = serde_json::from_value(valid_prepare_json()).unwrap();
    short.selectors[0].member_key = "a".repeat(63);
    assert_eq!(
        assert_device_ai_prepare_body(&short).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );

    let submission = DeviceAiStreamSubmission {
        pack_id: "pack-1".into(),
        question: format!("　{QUESTION}　"),
        prepare_id: "prep-1".into(),
        host_receipt_id: "11111111-2222-4333-8444-555555555555".into(),
        device_context_fingerprint: "03".repeat(32),
        provider_consent: DeviceAiProviderConsentBody {
            expected_pack_fingerprint: "aa".repeat(32),
            expected_device_context_fingerprint: "03".repeat(32),
            question_sha256: question_sha256(QUESTION),
            provider: "openai_responses".into(),
            model: "m-1".into(),
            expected_provider_policy_fingerprint: "05".repeat(32),
        },
    };
    let body = build_analysis_request_body(&submission).unwrap();
    let mut expected: Vec<&str> = DEVICE_AI_ANALYSIS_REQUEST_FIELDS.to_vec();
    expected.sort_unstable();
    assert_eq!(sorted_keys(&body), expected, "AnalysisRequest closed field set");
    let mut expected: Vec<&str> = DEVICE_AI_SUBMISSION_FIELDS.to_vec();
    expected.sort_unstable();
    assert_eq!(
        sorted_keys(&body["device_submission"]),
        expected,
        "device_submission closed field set"
    );
    let mut expected: Vec<&str> = DEVICE_AI_PROVIDER_CONSENT_FIELDS.to_vec();
    expected.sort_unstable();
    assert_eq!(
        sorted_keys(&body["device_submission"]["provider_consent"]),
        expected,
        "provider_consent closed field set"
    );
    assert_eq!(body["allow_external_processing"], json!(true));
    assert_eq!(body["question"], json!(QUESTION), "question normalized exactly once");
    assert_eq!(
        body["device_submission"]["host_receipt_id"],
        json!("11111111-2222-4333-8444-555555555555")
    );
    // closed struct: unknown consent keys are refused at deserialization
    let mut bad = serde_json::to_value(&submission).unwrap();
    bad["provider_consent"]["extra"] = json!(1);
    assert!(serde_json::from_value::<DeviceAiStreamSubmission>(bad).is_err());
}

// ---------------------------------------------------------------------------
// P1-4c: four-domain selector wire + prepare mode/closure gates, mirroring the
// server DeviceSelector/DeviceAIPrepareRequest validator semantics verbatim
// (domain key set / record_index rules / test_event rejection).
// ---------------------------------------------------------------------------

fn selector_json(selector: &DeviceAiSelectorWire) -> Value {
    serde_json::to_value(selector).expect("selector serializes")
}

#[test]
fn selector_four_domain_wire_shapes_and_validator_semantics() {
    // Per-domain reference key sets on the wire (server discriminated union).
    let expected_reference_keys = |selector: &Value| -> Vec<String> {
        let mut keys: Vec<String> = selector["reference"]
            .as_object()
            .expect("reference object")
            .keys()
            .cloned()
            .collect();
        keys.sort();
        keys
    };
    let tire = selector_json(&sel_a());
    assert_eq!(
        expected_reference_keys(&tire),
        vec!["kind", "snapshot_id", "variant_id", "verification_id"]
    );
    let vehicle = selector_json(&sel_vehicle());
    assert_eq!(
        expected_reference_keys(&vehicle),
        vec!["kind", "snapshot_id", "verification_id"]
    );
    let recall = selector_json(&sel_recall());
    assert_eq!(
        expected_reference_keys(&recall),
        vec!["kind", "recall_revision_id", "snapshot_id", "verification_id"]
    );
    assert_eq!(recall["reference"]["recall_revision_id"], json!("rrev-1"));
    let recall_search = selector_json(&sel_recall_search());
    assert_eq!(
        expected_reference_keys(&recall_search),
        vec!["kind", "snapshot_id", "verification_id"]
    );

    // All four domains pass the closed selector check (round trip included).
    for selector in [sel_a(), sel_vehicle(), sel_recall(), sel_recall_search()] {
        assert_device_ai_selector(&selector).unwrap();
        let wire: DeviceAiSelectorWire =
            serde_json::from_value(selector_json(&selector)).unwrap();
        assert_eq!(wire, selector);
    }

    // recall_revision_id is explicitly nullable: null and ABSENT both mean
    // None, and the serialized wire always carries the key (TS parity).
    let mut null_revision = selector_json(&sel_recall());
    null_revision["reference"]["recall_revision_id"] = Value::Null;
    let parsed: DeviceAiSelectorWire = serde_json::from_value(null_revision.clone()).unwrap();
    assert!(matches!(
        &parsed.reference,
        DeviceAiReferenceWire::Recall {
            recall_revision_id: None,
            ..
        }
    ));
    assert_device_ai_selector(&parsed).unwrap();
    let mut absent_revision = null_revision.clone();
    absent_revision
        ["reference"]
        .as_object_mut()
        .unwrap()
        .remove("recall_revision_id");
    let parsed_absent: DeviceAiSelectorWire =
        serde_json::from_value(absent_revision).unwrap();
    assert_eq!(parsed, parsed_absent);
    assert_eq!(
        selector_json(&parsed)["reference"]["recall_revision_id"],
        json!(null)
    );

    // test_event is a closed domain: kind rejected by the assert AND an
    // unknown reference tag refused at deserialization (server Literal 422).
    let mut test_event = selector_json(&sel_vehicle());
    test_event["kind"] = json!("test_event");
    let parsed_event: DeviceAiSelectorWire = serde_json::from_value(test_event.clone()).unwrap();
    assert_eq!(
        assert_device_ai_selector(&parsed_event).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );
    test_event["reference"] = json!({
        "kind": "test_event", "event_id": "ev-1", "event_revision": 1
    });
    assert!(
        serde_json::from_value::<DeviceAiSelectorWire>(test_event).is_err(),
        "test_event reference kind must fail deserialization like the server DTO"
    );

    // selector kind must equal the reference kind ('selector kind 与引用 kind 必须一致').
    let mut mismatched = selector_json(&sel_vehicle());
    mismatched["kind"] = json!("tire");
    let parsed_mismatch: DeviceAiSelectorWire = serde_json::from_value(mismatched).unwrap();
    assert_eq!(
        assert_device_ai_selector(&parsed_mismatch).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );

    // vehicle is a whole-observation domain: record_index must stay null even
    // with a document_id ('vehicle selector 不携带 record_index').
    let mut indexed_vehicle = sel_vehicle();
    indexed_vehicle.document_id = Some("vdoc-1".into());
    indexed_vehicle.record_index = Some(0);
    assert_eq!(
        assert_device_ai_selector(&indexed_vehicle).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );
    // ...and so is tire.
    let mut indexed_tire = sel_a();
    indexed_tire.document_id = Some("doc-9".into());
    indexed_tire.record_index = Some(0);
    assert_eq!(
        assert_device_ai_selector(&indexed_tire).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );

    // record_index without document_id is rejected ('缺少 document_id 时不能携带 record_index').
    let mut orphan_index = sel_recall();
    orphan_index.document_id = None;
    assert_eq!(
        assert_device_ai_selector(&orphan_index).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );
    // record_index bound 0..=3999 (server StrictInt bound).
    let mut over = sel_recall();
    over.record_index = Some(4000);
    assert_eq!(
        assert_device_ai_selector(&over).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );
    let mut at_bound = sel_recall();
    at_bound.record_index = Some(3999);
    assert_device_ai_selector(&at_bound).unwrap();

    // Closed key sets: unknown selector/reference keys are refused (extra=forbid).
    let mut extra_selector_key = selector_json(&sel_vehicle());
    extra_selector_key["extra"] = json!(1);
    assert!(serde_json::from_value::<DeviceAiSelectorWire>(extra_selector_key).is_err());
    let mut extra_reference_key = selector_json(&sel_vehicle());
    extra_reference_key["reference"]["variant_id"] = json!("v-1");
    assert!(
        serde_json::from_value::<DeviceAiSelectorWire>(extra_reference_key).is_err(),
        "vehicle reference must not accept the tire-only variant_id key"
    );
    let mut missing_id = selector_json(&sel_vehicle());
    missing_id["reference"].as_object_mut().unwrap().remove("verification_id");
    assert!(serde_json::from_value::<DeviceAiSelectorWire>(missing_id).is_err());

    // selection_sha256 binds a mixed four-domain closure member_key-ascending.
    let mixed = selection_sha256(&[sel_recall_search(), sel_a(), sel_recall(), sel_vehicle()])
        .unwrap();
    assert_eq!(
        selection_sha256(&[sel_vehicle(), sel_recall(), sel_a(), sel_recall_search()]).unwrap(),
        mixed,
        "member_key ordering, not request order"
    );
}

#[test]
fn prepare_body_four_domain_modes_and_closure_gates() {
    let mut body: DeviceAiPrepareBody = serde_json::from_value(valid_prepare_json()).unwrap();

    // Per-domain converter modes of the projection core are valid prepare
    // modes; each domain's single selector passes with approved_closure null.
    for (selector, mode) in [
        (&sel_vehicle(), "complete_observation"),
        (&sel_recall(), "complete_formal_observation"),
        (&sel_recall_search(), "candidate_page_context"),
    ] {
        body.selectors = vec![selector.clone()];
        body.projection_mode = mode.into();
        body.approved_closure = None;
        assert_device_ai_prepare_body(&body).unwrap();
        let canonical = canonicalize_prepare_body(&body).unwrap();
        assert_eq!(canonical["projection_mode"], json!(mode));
        // Wire selector keeps the domain key set closed end to end.
        assert_eq!(
            canonical["selectors"][0]["reference"]
                .as_object()
                .unwrap()
                .len(),
            if mode == "complete_formal_observation" { 4 } else { 3 },
            "recall reference carries the nullable recall_revision_id key"
        );
    }

    // complete_event_context is preview-capable on the TS port but is NOT on
    // the prepare Literal — fail closed here instead of a server 422.
    body.selectors = vec![sel_vehicle()];
    body.projection_mode = "complete_event_context".into();
    assert_eq!(
        assert_device_ai_prepare_body(&body).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );

    // frozen_decision_closure: required exact closure of valid selectors.
    body.selectors = vec![sel_a()];
    body.projection_mode = "frozen_decision_closure".into();
    body.approved_closure = Some(vec![sel_a(), sel_b()]);
    assert_device_ai_prepare_body(&body).unwrap();
    let canonical = canonicalize_prepare_body(&body).unwrap();
    assert_eq!(
        sorted_keys(&canonical["approved_closure"][0]),
        vec!["document_id", "kind", "member_key", "record_index", "reference"]
    );

    // Empty closure (server: 必须显式提供) and >SELECTOR_CAPACITY(6) closure.
    body.approved_closure = Some(Vec::new());
    assert_eq!(
        assert_device_ai_prepare_body(&body).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );
    let mut seven = vec![sel_a(), sel_b(), sel_vehicle(), sel_recall(), sel_recall_search()];
    seven.push({
        let mut sixth = sel_recall();
        sixth.member_key = "dd".repeat(32);
        sixth
    });
    seven.push({
        let mut seventh = sel_recall();
        seventh.member_key = "cc".repeat(32);
        seventh
    });
    assert_eq!(seven.len(), 7);
    body.approved_closure = Some(seven);
    assert_eq!(
        assert_device_ai_prepare_body(&body).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );

    // Duplicate member_key inside the closure ('selector 不能重复指向同一成员').
    body.approved_closure = Some(vec![sel_a(), sel_a()]);
    assert_eq!(
        assert_device_ai_prepare_body(&body).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );

    // Closure entries obey the same closed selector semantics (test_event).
    let mut event = sel_vehicle();
    event.kind = "test_event".into();
    body.approved_closure = Some(vec![event]);
    assert_eq!(
        assert_device_ai_prepare_body(&body).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );

    // Non-frozen modes refuse approved_closure entirely.
    body.projection_mode = "single_observation".into();
    body.approved_closure = Some(vec![sel_a()]);
    assert_eq!(
        assert_device_ai_prepare_body(&body).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument
    );
    body.approved_closure = None;
    assert_device_ai_prepare_body(&body).unwrap();

    // A four-domain selection (unique member_keys) is a valid single request.
    body.selectors = vec![sel_a(), sel_vehicle(), sel_recall(), sel_recall_search()];
    assert_device_ai_prepare_body(&body).unwrap();
    body.selectors.push(sel_b());
    assert_device_ai_prepare_body(&body).unwrap();
    body.selectors.push({
        let mut sixth = sel_recall();
        sixth.member_key = "dd".repeat(32);
        sixth
    });
    assert_device_ai_prepare_body(&body).unwrap();
    body.selectors.push({
        let mut seventh = sel_recall();
        seventh.member_key = "cc".repeat(32);
        seventh
    });
    assert_eq!(
        assert_device_ai_prepare_body(&body).unwrap_err(),
        DeviceAiHostErrorCode::InvalidArgument,
        "SELECTOR_CAPACITY = 6"
    );
}

// ---------------------------------------------------------------------------
// F. journal append / verify / tamper / five fences.
// ---------------------------------------------------------------------------

struct MemoryJournalStore {
    blob: StdMutex<Option<Vec<u8>>>,
}

impl DeviceAiJournalStore for MemoryJournalStore {
    fn load(&self) -> NativeResult<Option<Vec<u8>>> {
        Ok(self
            .blob
            .lock()
            .map_err(|_| "DEVICE_AI_JOURNAL_STORE_FAILED")?
            .clone())
    }
    fn save(&self, blob: &[u8]) -> NativeResult<()> {
        *self
            .blob
            .lock()
            .map_err(|_| "DEVICE_AI_JOURNAL_STORE_FAILED")? = Some(blob.to_vec());
        Ok(())
    }
}

struct TestClock(StdMutex<u64>);
impl TestClock {
    fn advance(&self) {
        *self.0.lock().unwrap() += 10;
    }
    fn set(&self, value: u64) {
        *self.0.lock().unwrap() = value;
    }
}

fn journal_fixture(
    owner: &str,
    generation: u64,
    session: &str,
    key: [u8; 32],
    store: &Arc<MemoryJournalStore>,
    clock: &Arc<TestClock>,
) -> DeviceAiJournal {
    let store = Arc::clone(store) as Arc<dyn DeviceAiJournalStore>;
    let clock = Arc::clone(clock);
    DeviceAiJournal::new(DeviceAiJournalOptions {
        owner: owner.into(),
        generation,
        session_id: session.into(),
        key: Zeroizing::new(key),
        store,
        monotonic_now: Box::new(move || *clock.0.lock().unwrap()),
        wall_now: Some(Box::new(|| "2026-10-02T00:00:00.000Z".into())),
    })
    .unwrap()
}

/// Test-only unseal mirroring the TS selftest helpers (same AAD and wire).
fn unseal_for_test(blob: &[u8], key: &[u8; 32]) -> (Value, Vec<Value>) {
    let wire: Value = serde_json::from_slice(blob).unwrap();
    let owner = wire["owner"].as_str().unwrap();
    let iv_hex = wire["iv_hex"].as_str().unwrap();
    let mut nonce = [0_u8; 12];
    for (index, pair) in iv_hex.as_bytes().chunks(2).enumerate() {
        nonce[index] = ((pair[0] as char).to_digit(16).unwrap() << 4) as u8
            | (pair[1] as char).to_digit(16).unwrap() as u8;
    }
    let ciphertext = STANDARD.decode(wire["ciphertext_base64"].as_str().unwrap()).unwrap();
    let cipher = Aes256Gcm::new_from_slice(key).unwrap();
    let plaintext = cipher
        .decrypt(
            Nonce::from_slice(&nonce),
            Payload {
                msg: &ciphertext,
                aad: &journal_aad(owner),
            },
        )
        .unwrap();
    let parsed: Value = serde_json::from_slice(&plaintext).unwrap();
    (wire, parsed["entries"].as_array().unwrap().clone())
}

fn reseal_for_test(wire: &Value, entries: &[Value], key: &[u8; 32]) -> Vec<u8> {
    let owner = wire["owner"].as_str().unwrap();
    let mut nonce = [0_u8; 12];
    OsRng.fill_bytes(&mut nonce);
    let cipher = Aes256Gcm::new_from_slice(key).unwrap();
    let plaintext = serde_json::to_vec(&json!({ "entries": entries })).unwrap();
    let ciphertext = cipher
        .encrypt(
            Nonce::from_slice(&nonce),
            Payload {
                msg: &plaintext,
                aad: &journal_aad(owner),
            },
        )
        .unwrap();
    serde_json::to_vec(&json!({
        "schema": wire["schema"], "owner": wire["owner"], "generation": wire["generation"],
        "iv_hex": nonce.iter().map(|byte| format!("{byte:02x}")).collect::<String>(),
        "ciphertext_base64": STANDARD.encode(&ciphertext),
    }))
    .unwrap()
}

fn stored_blob(store: &MemoryJournalStore) -> Vec<u8> {
    store.blob.lock().unwrap().clone().expect("journal saved")
}

fn save_blob(store: &MemoryJournalStore, blob: &[u8]) {
    *store.blob.lock().unwrap() = Some(blob.to_vec());
}

#[test]
fn journal_five_fences_and_tamper_detection() {
    let key = [7_u8; 32];
    let other_key = [9_u8; 32];
    let store = Arc::new(MemoryJournalStore {
        blob: StdMutex::new(None),
    });
    let clock = Arc::new(TestClock(StdMutex::new(0)));
    let journal = journal_fixture("profile-1", 1, "session-1", key, &store, &clock);

    let empty = journal.verify_integrity().unwrap();
    assert!(empty.ok && empty.length == 0);

    clock.advance();
    let e1 = journal
        .append(DeviceAiJournalEvent::PreviewShown {
            intent_id: "i-1".into(),
            local_preview_fingerprint: "aa".repeat(32),
            question_sha256: "bb".repeat(32),
            package_sha256: "cc".repeat(32),
        })
        .unwrap();
    clock.advance();
    let e2 = journal
        .append(DeviceAiJournalEvent::DecisionMade {
            intent_id: "i-1".into(),
            decision: DeviceAiJournalDecision::Allow,
            local_preview_fingerprint: "aa".repeat(32),
        })
        .unwrap();
    clock.advance();
    let e3 = journal
        .append(DeviceAiJournalEvent::ClaimSubmitted {
            intent_id: "i-1".into(),
            prepare_id: "prep-1".into(),
            analysis_key: "11111111-2222-4333-8444-555555555555".into(),
            question_sha256: "bb".repeat(32),
        })
        .unwrap();
    assert_eq!(
        (
            e1["sequence"].as_u64(),
            e2["sequence"].as_u64(),
            e3["sequence"].as_u64()
        ),
        (Some(1), Some(2), Some(3))
    );
    assert_eq!(e1["prev_sha256"].as_str().unwrap(), GENESIS_HASH);
    assert_eq!(
        e2["prev_sha256"].as_str().unwrap(),
        e1["entry_sha256"].as_str().unwrap()
    );
    assert_eq!(
        e3["prev_sha256"].as_str().unwrap(),
        e2["entry_sha256"].as_str().unwrap()
    );
    assert_eq!(e3["owner"], json!("profile-1"));
    assert_eq!(e3["generation"], json!(1));
    assert_eq!(e3["session_id"], json!("session-1"));
    assert_eq!((e1["clock"].as_u64(), e2["clock"].as_u64(), e3["clock"].as_u64()), (Some(10), Some(20), Some(30)));

    let read_back = journal.read_all().unwrap();
    assert_eq!(read_back.len(), 3);
    let verified = journal.verify_integrity().unwrap();
    assert!(verified.ok && verified.length == 3 && verified.cross_session_entries.is_empty());

    // Fence 3 — tamper with entry content (entry_sha256 kept stale).
    {
        let (wire, mut entries) = unseal_for_test(&stored_blob(&store), &key);
        entries[1]["event"]["decision"] = json!("deny");
        save_blob(&store, &reseal_for_test(&wire, &entries, &key));
        let tampered = journal.verify_integrity().unwrap();
        assert!(!tampered.ok);
        assert!(tampered.violations.iter().any(|violation| {
            violation.code == "device_ai_host_journal_entry_tampered"
                && violation.sequence == Some(2)
        }));
        assert_eq!(
            journal.read_all().unwrap_err(),
            DeviceAiJournalError::Fence(DeviceAiHostErrorCode::JournalEntryTampered)
        );
        entries[1]["event"]["decision"] = json!("allow");
        save_blob(&store, &reseal_for_test(&wire, &entries, &key));
        assert!(journal.verify_integrity().unwrap().ok);
    }

    // Fence 3 — break the chain link.
    {
        let (wire, mut entries) = unseal_for_test(&stored_blob(&store), &key);
        entries[2]["prev_sha256"] = json!("ee".repeat(32));
        save_blob(&store, &reseal_for_test(&wire, &entries, &key));
        let broken = journal.verify_integrity().unwrap();
        assert!(broken.violations.iter().any(|violation| {
            violation.code == "device_ai_host_journal_chain_broken" && violation.sequence == Some(3)
        }));
        entries[2]["prev_sha256"] = entries[1]["entry_sha256"].clone();
        save_blob(&store, &reseal_for_test(&wire, &entries, &key));
    }

    // Fence 4 — clock regression at write time, then recovery.
    clock.set(5);
    assert_eq!(
        journal
            .append(DeviceAiJournalEvent::FailureObserved {
                intent_id: Some("i-1".into()),
                stage: "submit".into(),
                code: "api_network_unavailable".into(),
            })
            .unwrap_err(),
        DeviceAiJournalError::Fence(DeviceAiHostErrorCode::JournalClockRegression)
    );
    clock.advance(); // 15 -> still below tail clock 30? set explicitly below.
    clock.set(40);
    let e4 = journal
        .append(DeviceAiJournalEvent::FailureObserved {
            intent_id: Some("i-1".into()),
            stage: "submit".into(),
            code: "api_network_unavailable".into(),
        })
        .unwrap();
    assert_eq!(e4["sequence"].as_u64(), Some(4));

    // Fence 4 — reordered entries (older clock appended after newer).
    {
        let (wire, entries) = unseal_for_test(&stored_blob(&store), &key);
        let mut reordered = entries.clone();
        let last = reordered.pop().unwrap();
        reordered.insert(0, last); // sequence 4 (clock 40) before sequence 1
        save_blob(&store, &reseal_for_test(&wire, &reordered, &key));
        let check = journal.verify_integrity().unwrap();
        assert!(check.violations.iter().any(|violation| {
            violation.code == "device_ai_host_journal_clock_regression"
        }));
        save_blob(&store, &reseal_for_test(&wire, &entries, &key));
    }

    // Fence 1 — wrong owner (explicit header check + AAD below it).
    let wrong_owner = journal_fixture("profile-2", 1, "session-1", key, &store, &clock);
    let owner_check = wrong_owner.verify_integrity().unwrap();
    assert!(!owner_check.ok);
    assert_eq!(
        owner_check.violations[0].code,
        "device_ai_host_journal_owner_mismatch"
    );
    assert_eq!(
        wrong_owner.read_all().unwrap_err(),
        DeviceAiJournalError::Fence(DeviceAiHostErrorCode::JournalOwnerMismatch)
    );

    // Fence 2 — stale generation after a rebuild.
    let stale = journal_fixture("profile-1", 2, "session-1", key, &store, &clock);
    let generation_check = stale.verify_integrity().unwrap();
    assert!(!generation_check.ok);
    assert_eq!(
        generation_check.violations[0].code,
        "device_ai_host_journal_generation_mismatch"
    );

    // Wrong key: AES-GCM AAD/authentication failure => corrupt.
    let wrong_key = journal_fixture("profile-1", 1, "session-1", other_key, &store, &clock);
    let key_check = wrong_key.verify_integrity().unwrap();
    assert!(!key_check.ok);
    assert_eq!(key_check.violations[0].code, "device_ai_host_journal_corrupt");

    // Corrupt wire header shape (bad iv_hex) => corrupt without touching AES.
    {
        let (mut wire, entries) = unseal_for_test(&stored_blob(&store), &key);
        // Re-seal the ORIGINAL ciphertext but damage the header only.
        let raw = stored_blob(&store);
        let mut damaged: Value = serde_json::from_slice(&raw).unwrap();
        damaged["iv_hex"] = json!("zz");
        let _ = (&mut wire, &entries); // silence unused in this block
        save_blob(&store, serde_json::to_vec(&damaged).unwrap().as_slice());
        let corrupt = journal.verify_integrity().unwrap();
        assert_eq!(corrupt.violations[0].code, "device_ai_host_journal_corrupt");
        // restore
        let (wire, entries) = unseal_for_test(&raw, &key);
        save_blob(&store, &reseal_for_test(&wire, &entries, &key));
    }

    // Fence 5 — session binding: recovery read allowed, hard gate refuses.
    let next_session = journal_fixture("profile-1", 1, "session-2", key, &store, &clock);
    let cross = next_session.verify_integrity().unwrap();
    assert!(cross.ok, "recovery read allowed across sessions");
    assert_eq!(cross.cross_session_entries.len(), 4);
    let fresh = next_session.read_all().unwrap();
    assert_eq!(
        next_session.assert_same_session(&fresh).unwrap_err(),
        DeviceAiJournalError::Fence(DeviceAiHostErrorCode::JournalSessionMismatch)
    );
    clock.set(50);
    let appended = next_session
        .append(DeviceAiJournalEvent::FailureObserved {
            intent_id: None,
            stage: "recover".into(),
            code: "none".into(),
        })
        .unwrap();
    assert_eq!(appended["session_id"], json!("session-2"));
}

// ---------------------------------------------------------------------------
// G/H. Host client over the existing bridge (real loopback server, the same
// convention as bridge/tests.rs) + N18 lookup-first resolution.
// ---------------------------------------------------------------------------

struct MemorySessionStore {
    value: StdMutex<Option<String>>,
}
impl SessionStore for MemorySessionStore {
    fn load(&self) -> NativeResult<Option<String>> {
        Ok(self.value.lock().unwrap().clone())
    }
    fn save(&self, value: Option<&str>) -> NativeResult<()> {
        *self.value.lock().unwrap() = value.map(str::to_owned);
        Ok(())
    }
    fn delete(&self) -> NativeResult<()> {
        *self.value.lock().unwrap() = None;
        Ok(())
    }
}

#[derive(Clone)]
struct Incoming {
    target: String,
    headers: std::collections::BTreeMap<String, String>,
    body: Vec<u8>,
}

struct Server {
    port: u16,
    received: Arc<StdMutex<Vec<Incoming>>>,
    task: tokio::task::JoinHandle<()>,
}

impl Drop for Server {
    fn drop(&mut self) {
        self.task.abort();
    }
}

impl Server {
    async fn start(
        handler: impl Fn(&Incoming) -> (u16, Vec<(String, String)>, Vec<u8>) + Send + Sync + 'static,
    ) -> Self {
        // Tests bind only their own ephemeral loopback listener; no real API or
        // OS store is touched.
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let received = Arc::new(StdMutex::new(Vec::new()));
        let received_clone = received.clone();
        let handler = Arc::new(handler);
        let task = tokio::spawn(async move {
            loop {
                let Ok((stream, _)) = listener.accept().await else {
                    break;
                };
                let received = received_clone.clone();
                let handler = handler.clone();
                tokio::spawn(async move {
                    let _ = serve(stream, received, handler).await;
                });
            }
        });
        Self {
            port,
            received,
            task,
        }
    }

    fn bridge(&self) -> Bridge {
        Bridge::new(
            LaunchConfig {
                port: self.port,
                namespace: "test-deviceai".into(),
            },
            Arc::new(MemorySessionStore {
                value: StdMutex::new(Some(TEST_COOKIE.into())),
            }),
        )
        .unwrap()
    }
}

async fn serve(
    mut stream: tokio::net::TcpStream,
    received: Arc<StdMutex<Vec<Incoming>>>,
    handler: Arc<impl Fn(&Incoming) -> (u16, Vec<(String, String)>, Vec<u8>)>,
) -> std::io::Result<()> {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let mut data = Vec::new();
    let end = loop {
        let mut chunk = [0_u8; 8192];
        let count = stream.read(&mut chunk).await?;
        if count == 0 {
            return Ok(());
        }
        data.extend_from_slice(&chunk[..count]);
        if let Some(index) = data.windows(4).position(|bytes| bytes == b"\r\n\r\n") {
            break index + 4;
        }
        assert!(data.len() < 65536);
    };
    let text = String::from_utf8_lossy(&data[..end]).to_string();
    let mut lines = text.split("\r\n");
    let target = lines
        .next()
        .unwrap()
        .split_whitespace()
        .nth(1)
        .unwrap()
        .to_owned();
    let headers: std::collections::BTreeMap<String, String> = lines
        .filter_map(|line| {
            line.split_once(':')
                .map(|(key, value)| (key.to_ascii_lowercase(), value.trim().to_owned()))
        })
        .collect();
    let length = headers
        .get("content-length")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(0);
    while data.len() - end < length {
        let mut chunk = [0_u8; 8192];
        let count = stream.read(&mut chunk).await?;
        if count == 0 {
            return Ok(());
        }
        data.extend_from_slice(&chunk[..count]);
    }
    let incoming = Incoming {
        target,
        headers,
        body: data[end..end + length].to_vec(),
    };
    received.lock().unwrap().push(incoming.clone());
    let (status, headers, body) = handler(&incoming);
    let mut response = format!("HTTP/1.1 {status} Test\r\nConnection: close\r\n");
    for (key, value) in headers {
        response.push_str(&format!("{key}: {value}\r\n"));
    }
    response.push_str(&format!("Content-Length: {}\r\n\r\n", body.len()));
    stream.write_all(response.as_bytes()).await?;
    stream.write_all(&body).await?;
    Ok(())
}

fn health_reply() -> (u16, Vec<(String, String)>, Vec<u8>) {
    (
        200,
        vec![(
            "Set-Cookie".into(),
            format!(
                "{COOKIE_NAME}={TEST_COOKIE}; HttpOnly; Path=/; SameSite=strict; Max-Age=1209600"
            ),
        )],
        b"{}".to_vec(),
    )
}

fn json_reply(status: u16, body: Value) -> (u16, Vec<(String, String)>, Vec<u8>) {
    (
        status,
        vec![("Content-Type".into(), "application/json".into())],
        serde_json::to_vec(&body).unwrap(),
    )
}

fn prepare_view_fixture(canonical_key: &str) -> Value {
    json!({
        "id": "prep-1", "created_at": "2026-10-02T12:00:00Z", "expires_at": "2026-10-02T12:30:00Z",
        "expired": false, "idempotency_key": canonical_key,
        "host_receipt_id": "11111111-2222-4333-8444-555555555555",
        "intent_id": "22222222-3333-4444-8555-666666666666",
        "pack_id": "pack-1", "offline_pack_id": "pkg-1", "question_sha256": "01".repeat(32),
        "selection_sha256": "02".repeat(32), "projection_sha256": "99".repeat(32),
        "projection_byte_count": 1000, "device_context_fingerprint": "03".repeat(32),
        "request_hash": "04".repeat(32), "contract": {}, "pack": {}, "replayed": false,
        "provider_preview": { "model": { "provider": "openai_responses" } },
    })
}

fn stream_detail_fixture() -> Value {
    json!({
        "schema": "ai-streams@1", "scope": "session",
        "execution": { "state": "accepted", "terminal": false, "deadline_at": "2026-10-02T12:30:00Z",
                       "last_event_at": null, "projection_only": false },
        "cursor": "cursor-1", "server_time": "2026-10-02T12:00:00Z",
        "analysis": {
            "id": "req-1", "pack_id": "pack-1", "question": "问题", "provider": "openai_responses",
            "model": "m-1", "created_at": "2026-10-02T12:00:00Z", "completed_at": null,
            "state": "pending", "reserved_tokens": 100, "usage": null, "error_code": null,
            "answer": null,
        },
        "draft_claims": [], "draft_uncertainty": null, "replayed": false,
    })
}

fn prepare_body_fixture() -> DeviceAiPrepareBody {
    serde_json::from_value(valid_prepare_json()).unwrap()
}

const KEY_UPPER: &str = "9999AAAA-BBBB-4CCC-8DDD-5555EEE66666";
const KEY_CANONICAL: &str = "9999aaaa-bbbb-4ccc-8ddd-5555eee66666";

#[tokio::test]
async fn client_prepare_paths_bodies_and_error_passthrough() {
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        assert_eq!(incoming.target, "/v1/ai/device-evidence-packs");
        assert_eq!(
            incoming.headers.get("cookie").unwrap(),
            &format!("{COOKIE_NAME}={TEST_COOKIE}")
        );
        assert_eq!(
            incoming.headers.get("idempotency-key").map(String::as_str),
            Some(KEY_CANONICAL),
            "Idempotency-Key canonicalized lowercase"
        );
        let body: Value = serde_json::from_slice(&incoming.body).unwrap();
        let mut expected: Vec<&str> = DEVICE_AI_PREPARE_REQUEST_FIELDS.to_vec();
        expected.sort_unstable();
        let mut keys = body.as_object().unwrap().keys().map(String::to_owned).collect::<Vec<_>>();
        keys.sort();
        assert_eq!(keys, expected, "prepare body closed field set on the wire");
        assert_eq!(body["host_receipt_id"], json!("11111111-2222-4333-8444-555555555555"));
        json_reply(201, prepare_view_fixture(KEY_CANONICAL))
    })
    .await;
    let client = DeviceAiHostClient::new(Arc::new(server.bridge()));
    let success = client
        .prepare(&prepare_body_fixture(), KEY_UPPER)
        .await
        .unwrap();
    assert_eq!(success.status, 201);
    assert_eq!(success.value["id"], json!("prep-1"));
    assert_eq!(success.value["replayed"], json!(false));

    // Invalid arguments never reach the network.
    let offline = Server::start(|_| panic!("invalid arguments must not reach the network")).await;
    let offline_client = DeviceAiHostClient::new(Arc::new(offline.bridge()));
    let mut bad = prepare_body_fixture();
    bad.question_sha256 = "XYZ".into();
    assert_eq!(
        offline_client.prepare(&bad, KEY_UPPER).await.unwrap_err(),
        DeviceAiClientError::Host(DeviceAiHostErrorCode::InvalidArgument)
    );
    assert!(offline_client.prepare(&prepare_body_fixture(), "not-a-uuid").await.is_err());
    assert!(offline.received.lock().unwrap().is_empty());
}

#[tokio::test]
async fn client_prepare_replay_missing_preview_and_malformed_view() {
    // Replay branch: 200 with replayed=true and provider_preview omitted.
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        let mut view = prepare_view_fixture(KEY_CANONICAL);
        view["replayed"] = json!(true);
        view.as_object_mut().unwrap().remove("provider_preview");
        json_reply(200, view)
    })
    .await;
    let client = DeviceAiHostClient::new(Arc::new(server.bridge()));
    let replayed = client
        .prepare(&prepare_body_fixture(), KEY_CANONICAL)
        .await
        .unwrap();
    assert_eq!(replayed.status, 200);
    assert_eq!(replayed.value["replayed"], json!(true));
    assert!(replayed.value.get("provider_preview").is_none());

    // Malformed view (expires_at not a date) fails with the closed code.
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        let mut view = prepare_view_fixture(KEY_CANONICAL);
        view["expires_at"] = json!("not-a-date");
        json_reply(200, view)
    })
    .await;
    let client = DeviceAiHostClient::new(Arc::new(server.bridge()));
    assert_eq!(
        client
            .prepare(&prepare_body_fixture(), KEY_CANONICAL)
            .await
            .unwrap_err(),
        DeviceAiClientError::Host(DeviceAiHostErrorCode::ResponseInvalid)
    );

    // M7 (decoder-spec section 3): a naive timestamp (no timezone offset) is
    // rejected exactly like an unparsable one — the RFC 3339 offset is
    // mandatory (chrono parse_from_rfc3339), unlike a plain Date.parse.
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        let mut view = prepare_view_fixture(KEY_CANONICAL);
        view["expires_at"] = json!("2026-10-02T12:30:00");
        json_reply(200, view)
    })
    .await;
    let client = DeviceAiHostClient::new(Arc::new(server.bridge()));
    assert_eq!(
        client
            .prepare(&prepare_body_fixture(), KEY_CANONICAL)
            .await
            .unwrap_err(),
        DeviceAiClientError::Host(DeviceAiHostErrorCode::ResponseInvalid)
    );

    // 409 closed-code passthrough (Api error with detail.code).
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        json_reply(
            409,
            json!({"detail": {"code": "device_ai_prepare_conflict", "message": "已绑定既有准备记录"}}),
        )
    })
    .await;
    let client = DeviceAiHostClient::new(Arc::new(server.bridge()));
    match client.prepare(&prepare_body_fixture(), KEY_CANONICAL).await {
        Err(DeviceAiClientError::Api(error)) => {
            assert_eq!(error.status, 409);
            assert_eq!(error.code.as_deref(), Some("device_ai_prepare_conflict"));
            assert_eq!(error.message.as_deref(), Some("已绑定既有准备记录"));
        }
        other => panic!("expected Api passthrough, got {other:?}"),
    }
}

#[tokio::test]
async fn client_lookup_read_and_attempt_paths() {
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        if incoming.target.starts_with("/v1/ai/device-evidence-packs/lookup") {
            assert_eq!(
                incoming.target,
                format!("/v1/ai/device-evidence-packs/lookup?mode=history&idempotency_key={KEY_CANONICAL}")
            );
            return json_reply(200, prepare_view_fixture(KEY_CANONICAL));
        }
        if incoming.target.starts_with("/v1/ai/device-evidence-packs/") {
            assert_eq!(incoming.target, "/v1/ai/device-evidence-packs/prep-1?mode=history");
            return json_reply(200, prepare_view_fixture(KEY_CANONICAL));
        }
        assert_eq!(
            incoming.target,
            format!("/v1/ai/analysis-streams/lookup?mode=history&idempotency_key={KEY_CANONICAL}")
        );
        json_reply(200, stream_detail_fixture())
    })
    .await;
    let client = DeviceAiHostClient::new(Arc::new(server.bridge()));
    let lookup = client.lookup_prepare(KEY_UPPER).await.unwrap();
    assert_eq!(lookup.value["id"], json!("prep-1"));
    let read = client.read_prepare("prep-1").await.unwrap();
    assert_eq!(read.value["pack_id"], json!("pack-1"));
    let attempt = client.lookup_attempt(KEY_UPPER).await.unwrap();
    assert_eq!(attempt.value["analysis"]["id"], json!("req-1"));
    // Ids that could smuggle path separators are refused before the network.
    assert_eq!(
        client.read_prepare("a/b?c").await.unwrap_err(),
        DeviceAiClientError::Host(DeviceAiHostErrorCode::InvalidArgument)
    );
    assert_eq!(server.received.lock().unwrap().len(), 4);
}

#[tokio::test]
async fn client_submit_stream_body_and_acceptance_checks() {
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        assert_eq!(incoming.target, "/v1/ai/analysis-streams");
        assert_eq!(
            incoming.headers.get("idempotency-key").map(String::as_str),
            Some(KEY_CANONICAL)
        );
        let body: Value = serde_json::from_slice(&incoming.body).unwrap();
        let mut expected: Vec<&str> = DEVICE_AI_ANALYSIS_REQUEST_FIELDS.to_vec();
        expected.sort_unstable();
        let mut keys = body.as_object().unwrap().keys().map(String::to_owned).collect::<Vec<_>>();
        keys.sort();
        assert_eq!(keys, expected);
        let submission = &body["device_submission"];
        let mut expected: Vec<&str> = DEVICE_AI_SUBMISSION_FIELDS.to_vec();
        expected.sort_unstable();
        let mut keys = submission.as_object().unwrap().keys().map(String::to_owned).collect::<Vec<_>>();
        keys.sort();
        assert_eq!(keys, expected);
        assert_eq!(body["allow_external_processing"], json!(true));
        assert_eq!(body["question"], json!(QUESTION), "trim-once exactly once");
        assert_eq!(submission["prepare_id"], json!("prep-1"));
        assert_eq!(
            submission["host_receipt_id"],
            json!("11111111-2222-4333-8444-555555555555")
        );
        assert_eq!(
            submission["device_context_fingerprint"],
            json!("03".repeat(32))
        );
        let mut expected: Vec<&str> = DEVICE_AI_PROVIDER_CONSENT_FIELDS.to_vec();
        expected.sort_unstable();
        let mut keys = submission["provider_consent"].as_object().unwrap().keys().map(String::to_owned).collect::<Vec<_>>();
        keys.sort();
        assert_eq!(keys, expected);
        json_reply(202, stream_detail_fixture())
    })
    .await;
    let client = DeviceAiHostClient::new(Arc::new(server.bridge()));
    let submission = DeviceAiStreamSubmission {
        pack_id: "pack-1".into(),
        question: format!("　{QUESTION}　"), // U+3000 both ends
        prepare_id: "prep-1".into(),
        host_receipt_id: "11111111-2222-4333-8444-555555555555".into(),
        device_context_fingerprint: "03".repeat(32),
        provider_consent: DeviceAiProviderConsentBody {
            expected_pack_fingerprint: "aa".repeat(32),
            expected_device_context_fingerprint: "03".repeat(32),
            question_sha256: question_sha256(QUESTION),
            provider: "openai_responses".into(),
            model: "m-1".into(),
            expected_provider_policy_fingerprint: "05".repeat(32),
        },
    };
    let acceptance = client.submit_stream(&submission, KEY_UPPER).await.unwrap();
    assert_eq!(acceptance.status, 202);
    assert_eq!(acceptance.value["replayed"], json!(false));

    // Acceptance without the replayed flag is rejected.
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        let mut detail = stream_detail_fixture();
        detail
            .as_object_mut()
            .unwrap()
            .remove("replayed");
        json_reply(202, detail)
    })
    .await;
    let client = DeviceAiHostClient::new(Arc::new(server.bridge()));
    assert_eq!(
        client.submit_stream(&submission, KEY_CANONICAL).await.unwrap_err(),
        DeviceAiClientError::Host(DeviceAiHostErrorCode::ResponseInvalid)
    );

    // 409 closed-code passthrough on consent mismatch.
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        json_reply(409, json!({"detail": {"code": "device_ai_consent_mismatch", "message": "六元组不一致"}}))
    })
    .await;
    let client = DeviceAiHostClient::new(Arc::new(server.bridge()));
    match client.submit_stream(&submission, KEY_CANONICAL).await {
        Err(DeviceAiClientError::Api(error)) => {
            assert_eq!(error.status, 409);
            assert_eq!(error.code.as_deref(), Some("device_ai_consent_mismatch"));
        }
        other => panic!("expected Api passthrough, got {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// H. resolveUnknownOutcome (N18): lookup first, never resubmit.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn resolve_unknown_outcome_is_lookup_first_and_never_resubmits() {
    let analysis_key = "12345678-1234-4234-8345-123456789abc";
    // Hit: exactly one lookup, zero submits (the handler panics on POST).
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        if incoming.target.starts_with("/v1/ai/analysis-streams/lookup") {
            return json_reply(200, stream_detail_fixture());
        }
        panic!("resolveUnknownOutcome must never resubmit");
    })
    .await;
    let client = DeviceAiHostClient::new(Arc::new(server.bridge()));
    let resolved = resolve_unknown_outcome(&client, None, &analysis_key.to_uppercase(), None)
        .await
        .unwrap();
    match resolved {
        DeviceAiUnknownOutcomeResolution::Resolved { detail } => {
            assert_eq!(detail["analysis"]["id"], json!("req-1"));
        }
        other => panic!("expected resolved, got {other:?}"),
    }
    assert_eq!(server.received.lock().unwrap().len(), 2);

    // Miss: 404 passthrough drives the recovery matrix.
    let server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        json_reply(404, json!({"detail": "未找到本会话的 AI 流式分析"}))
    })
    .await;
    let client = DeviceAiHostClient::new(Arc::new(server.bridge()));
    assert!(matches!(
        resolve_unknown_outcome(&client, None, analysis_key, None).await.unwrap(),
        DeviceAiUnknownOutcomeResolution::NotSubmitted
    ));

    let key = [3_u8; 32];
    let store = Arc::new(MemoryJournalStore {
        blob: StdMutex::new(None),
    });
    let clock = Arc::new(TestClock(StdMutex::new(0)));
    let journal = journal_fixture("profile-1", 1, "session-1", key, &store, &clock);
    assert!(matches!(
        resolve_unknown_outcome(&client, Some(&journal), analysis_key, None)
            .await
            .unwrap(),
        DeviceAiUnknownOutcomeResolution::NotSubmitted
    ));

    clock.advance();
    journal
        .append(DeviceAiJournalEvent::ClaimSubmitted {
            intent_id: "intent-1".into(),
            prepare_id: "prep-1".into(),
            analysis_key: analysis_key.into(),
            question_sha256: "bb".repeat(32),
        })
        .unwrap();
    match resolve_unknown_outcome(&client, Some(&journal), analysis_key, Some("intent-1"))
        .await
        .unwrap()
    {
        DeviceAiUnknownOutcomeResolution::UnknownLocalClaim {
            analysis_key: key,
            resubmission,
        } => {
            assert_eq!(key, analysis_key);
            assert_eq!(resubmission, "same_key_same_body_user_decision_only");
        }
        other => panic!("expected unknown_local_claim, got {other:?}"),
    }
    assert!(matches!(
        resolve_unknown_outcome(&client, Some(&journal), analysis_key, Some("intent-other"))
            .await
            .unwrap(),
        DeviceAiUnknownOutcomeResolution::NotSubmitted
    ));

    // Fence 5: a claim recorded under a different session never replays.
    let next_session = journal_fixture("profile-1", 1, "session-2", key, &store, &clock);
    assert!(matches!(
        resolve_unknown_outcome(&client, Some(&next_session), analysis_key, Some("intent-1"))
            .await
            .unwrap(),
        DeviceAiUnknownOutcomeResolution::CrossSessionReplayBlocked
    ));

    // Tampered journal: integrity failure surfaces, still zero submits.
    let (wire, mut entries) = unseal_for_test(&stored_blob(&store), &key);
    entries[0]["event"]["analysis_key"] = json!("forged");
    save_blob(&store, &reseal_for_test(&wire, &entries, &key));
    match resolve_unknown_outcome(&client, Some(&journal), analysis_key, None)
        .await
        .unwrap()
    {
        DeviceAiUnknownOutcomeResolution::JournalIntegrityFailed { violations } => {
            assert!(!violations.is_empty());
        }
        other => panic!("expected journal_integrity_failed, got {other:?}"),
    }
    let requests = server.received.lock().unwrap();
    assert!(
        requests.iter().all(|incoming| incoming.target == "/health"
            || incoming.target.starts_with("/v1/ai/analysis-streams/lookup")),
        "no POST /v1/ai/analysis-streams ever happened"
    );
}

#[test]
fn wall_nano_clock_never_decreases_within_process() {
    let clock = WallNanoClock::new();
    let first = clock.now();
    let second = clock.now();
    assert!(second > first, "strictly increasing within the process");
    assert!(first >= 1);
}

#[test]
fn file_journal_store_round_trip_and_bounds() {
    let directory = std::env::temp_dir().join(format!("device-ai-journal-test-{}", Uuid::new_v4()));
    let store = FileJournalStore::open(&directory, "account-1");
    assert!(store.load().unwrap().is_none());
    store.save(b"blob-bytes").unwrap();
    assert_eq!(store.load().unwrap().as_deref(), Some(b"blob-bytes".as_ref()));
    assert!(store.path().starts_with(&directory));
    assert!(store.save(&vec![0_u8; DEVICE_AI_JOURNAL_MAX_BYTES + 1]).is_err());
    let _ = std::fs::remove_dir_all(&directory);
}

#[test]
#[cfg(any(target_os = "windows", target_os = "macos"))]
#[ignore = "Opt in only: creates and removes one fresh application-owned OS credential"]
fn os_journal_key_store_round_trip_own_temporary_entry() {
    assert_eq!(
        std::env::var("TI_DESKTOP_TEST_OS_STORE").as_deref(),
        Ok("1"),
        "explicit OS-store test opt-in is required"
    );
    let account = format!("deviceai-test-{}", Uuid::new_v4());
    let store = super::OsJournalKeyStore::open(&account).unwrap();
    struct Cleanup(super::OsJournalKeyStore);
    impl Drop for Cleanup {
        fn drop(&mut self) {
            let _ = self.0 .0.delete_credential();
        }
    }
    let key = store.load_or_create().unwrap();
    assert_eq!(key.as_ref().len(), 32);
    // Second load returns the SAME persisted key (no re-mint).
    assert_eq!(*store.load_or_create().unwrap(), *key);
    let _cleanup = Cleanup(store);
}

// ---------------------------------------------------------------------------
// I. IPC command layer shapes (device_ai_journal_append /
//    device_ai_resolve_unknown in lib.rs): the closed event wire, the
//    command-shaped append -> read_all visibility under the five fences, and
//    the resolve wire kinds (TS DeviceAiUnknownOutcomeResolution parity).
// ---------------------------------------------------------------------------

/// The exact IPC entry path of device_ai_journal_append: serde wire
/// deserialization (closed tag + deny_unknown_fields) then the value-level
/// closed validation, before anything reaches the ledger.
fn command_event(wire: Value) -> Result<DeviceAiJournalEvent, String> {
    serde_json::from_value::<DeviceAiJournalEvent>(wire)
        .map_err(|error| error.to_string())
        .and_then(|event| {
            assert_device_ai_journal_event(&event)
                .map_err(|code| code.as_str().to_owned())
                .map(|()| event)
        })
}

const INTENT_ID: &str = "11111111-2222-4333-8444-555555555555";
const ANALYSIS_KEY: &str = "12345678-1234-4234-8345-123456789abc";

/// The six events exactly as the desktop panel orchestration writes them.
fn panel_flow_wires() -> Vec<Value> {
    vec![
        json!({
            "type": "preview_shown", "intent_id": INTENT_ID,
            "local_preview_fingerprint": "ab".repeat(32),
            "question_sha256": "cd".repeat(32), "package_sha256": "ef".repeat(32),
        }),
        json!({
            "type": "decision_made", "intent_id": INTENT_ID, "decision": "allow",
            "local_preview_fingerprint": "ab".repeat(32),
        }),
        json!({
            "type": "prepare_created", "intent_id": INTENT_ID, "prepare_id": "prep-1",
            "idempotency_key": "22345678-1234-4333-8444-555555555555",
            "projection_sha256": "0f".repeat(32), "device_context_fingerprint": "9a".repeat(32),
        }),
        json!({
            "type": "claim_submitted", "intent_id": INTENT_ID, "prepare_id": "prep-1",
            "analysis_key": ANALYSIS_KEY, "question_sha256": "cd".repeat(32),
        }),
        json!({
            "type": "outcome_observed", "intent_id": INTENT_ID, "analysis_key": ANALYSIS_KEY,
            "request_id": "req-1", "state": "completed",
        }),
        json!({
            "type": "failure_observed", "intent_id": null, "stage": "submit",
            "code": "ai_provider_timeout",
        }),
    ]
}

#[test]
fn ipc_journal_append_wire_is_closed() {
    for wire in panel_flow_wires() {
        assert!(command_event(wire).is_ok(), "panel-written event must pass");
    }
    // Empty intent_id is the documented outcome_observed form (intentId ?? "").
    assert!(command_event(json!({
        "type": "outcome_observed", "intent_id": "", "analysis_key": ANALYSIS_KEY,
        "request_id": "req-1", "state": "outcome_unknown",
    }))
    .is_ok());

    // Unknown event type and unknown fields never deserialize (closed tag +
    // deny_unknown_fields), and the decision Literal is closed as well.
    assert!(command_event(json!({"type": "consent_granted"})).is_err());
    assert!(command_event(json!({
        "type": "decision_made", "intent_id": INTENT_ID, "decision": "allow",
        "local_preview_fingerprint": "ab".repeat(32), "extra": 1,
    }))
    .is_err());
    assert!(command_event(json!({
        "type": "decision_made", "intent_id": INTENT_ID, "decision": "maybe",
        "local_preview_fingerprint": "ab".repeat(32),
    }))
    .is_err());

    // Value-level closed validation (assert_device_ai_journal_event).
    let rejects = vec![
        // fingerprint / hash shape fences
        json!({"type": "preview_shown", "intent_id": INTENT_ID,
            "local_preview_fingerprint": "not-a-hash", "question_sha256": "cd".repeat(32),
            "package_sha256": "ef".repeat(32)}),
        json!({"type": "decision_made", "intent_id": INTENT_ID, "decision": "deny",
            "local_preview_fingerprint": "ab".repeat(31)}),
        json!({"type": "prepare_created", "intent_id": INTENT_ID, "prepare_id": "prep-1",
            "idempotency_key": "22345678-1234-4333-8444-555555555555",
            "projection_sha256": "zz".repeat(32), "device_context_fingerprint": "9a".repeat(32)}),
        json!({"type": "claim_submitted", "intent_id": INTENT_ID, "prepare_id": "prep-1",
            "analysis_key": ANALYSIS_KEY, "question_sha256": ""}),
        // recovery depends on the UUID form of both keys
        json!({"type": "claim_submitted", "intent_id": INTENT_ID, "prepare_id": "prep-1",
            "analysis_key": "not-a-uuid", "question_sha256": "cd".repeat(32)}),
        json!({"type": "prepare_created", "intent_id": INTENT_ID, "prepare_id": "prep-1",
            "idempotency_key": "not-a-uuid", "projection_sha256": "0f".repeat(32),
            "device_context_fingerprint": "9a".repeat(32)}),
        json!({"type": "outcome_observed", "intent_id": INTENT_ID, "analysis_key": "not-a-uuid",
            "request_id": "req-1", "state": "completed"}),
        // closed stage / state sets
        json!({"type": "failure_observed", "intent_id": null, "stage": "network", "code": "x"}),
        json!({"type": "outcome_observed", "intent_id": INTENT_ID, "analysis_key": ANALYSIS_KEY,
            "request_id": "req-1", "state": "pending"}),
        // bounded passthrough code, no control characters in ids
        json!({"type": "failure_observed", "intent_id": null, "stage": "submit", "code": ""}),
        json!({"type": "failure_observed", "intent_id": null, "stage": "submit",
            "code": "c".repeat(101)}),
        json!({"type": "failure_observed", "intent_id": Some("bad\nid".to_owned()), "stage": "submit",
            "code": "API_TIMEOUT"}),
    ];
    for wire in rejects {
        let error = command_event(wire).expect_err("closed validation must reject");
        assert_eq!(error, "device_ai_host_invalid_argument");
    }
}

#[test]
fn ipc_journal_append_then_read_all_keeps_five_fences() {
    let key = [5_u8; 32];
    let store = Arc::new(MemoryJournalStore {
        blob: StdMutex::new(None),
    });
    let clock = Arc::new(TestClock(StdMutex::new(0)));
    let journal = journal_fixture("profile-1", 1, "session-1", key, &store, &clock);

    // The full panel flow through the command-shaped entry path: every event
    // crosses the closed wire + validation, then append.
    for wire in panel_flow_wires() {
        let event = command_event(wire).expect("panel event passes the closed wire");
        clock.advance();
        journal.append(event).unwrap();
    }
    let entries = journal.read_all().unwrap();
    assert_eq!(entries.len(), 6);
    for (index, entry) in entries.iter().enumerate() {
        assert_eq!(v_u64(entry, "sequence"), Some(index as u64 + 1));
        assert_eq!(v_str(entry, "owner"), Some("profile-1"));
        assert_eq!(v_u64(entry, "generation"), Some(1));
        assert_eq!(v_str(entry, "session_id"), Some("session-1"));
        assert!(v_str(entry, "entry_sha256").is_some_and(is_hash64));
    }
    assert_eq!(v_str(&entries[2], "prev_sha256"), v_str(&entries[1], "entry_sha256"));

    // Full five-fence report over the read_journal shape: ok, no violations,
    // no cross-session entries, and the hard session gate passes.
    let verification = journal.verify_integrity().unwrap();
    assert!(verification.ok, "{verification:?}");
    assert_eq!(verification.length, 6);
    assert!(verification.violations.is_empty());
    assert!(verification.cross_session_entries.is_empty());
    journal.assert_same_session(&entries).unwrap();

    // read_all keeps failing closed after a tamper (the command surfaces the
    // fence code instead of returning tampered content).
    let (wire, mut stored) = unseal_for_test(&stored_blob(&store), &key);
    stored[3]["event"]["question_sha256"] = json!("forged");
    save_blob(&store, &reseal_for_test(&wire, &stored, &key));
    match journal.read_all() {
        Err(DeviceAiJournalError::Fence(code)) => {
            assert_eq!(code, DeviceAiHostErrorCode::JournalEntryTampered);
        }
        other => panic!("expected tamper fence, got {other:?}"),
    }
}

#[tokio::test]
async fn ipc_resolve_unknown_four_branches_and_wire_kinds() {
    // Lookup-first, four recovery branches (+ integrity), zero submits: the
    // handler panics on any POST /v1/ai/analysis-streams.
    let miss_server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        json_reply(404, json!({"detail": "未找到本会话的 AI 流式分析"}))
    })
    .await;
    let miss_client = DeviceAiHostClient::new(Arc::new(miss_server.bridge()));

    let key = [6_u8; 32];
    let store = Arc::new(MemoryJournalStore {
        blob: StdMutex::new(None),
    });
    let clock = Arc::new(TestClock(StdMutex::new(0)));
    let journal = journal_fixture("profile-1", 1, "session-1", key, &store, &clock);

    // Branch 1: no local claim at all -> not_submitted.
    let resolution = resolve_unknown_outcome(&miss_client, Some(&journal), ANALYSIS_KEY, None)
        .await
        .unwrap();
    assert!(matches!(
        resolution,
        DeviceAiUnknownOutcomeResolution::NotSubmitted
    ));
    assert_eq!(
        serde_json::to_value(&resolution).unwrap()["kind"],
        json!("not_submitted")
    );

    // Command-shaped claim append, exactly as device_ai_journal_append does.
    let claim_wire = json!({
        "type": "claim_submitted", "intent_id": INTENT_ID, "prepare_id": "prep-1",
        "analysis_key": ANALYSIS_KEY, "question_sha256": "cd".repeat(32),
    });
    clock.advance();
    journal
        .append(command_event(claim_wire).expect("claim passes the closed wire"))
        .unwrap();

    // Branch 2: same-session local claim, server miss -> unknown_local_claim
    // with the frozen same-key resubmission policy.
    let resolution = resolve_unknown_outcome(&miss_client, Some(&journal), ANALYSIS_KEY, Some(INTENT_ID))
        .await
        .unwrap();
    match &resolution {
        DeviceAiUnknownOutcomeResolution::UnknownLocalClaim {
            analysis_key,
            resubmission,
        } => {
            assert_eq!(analysis_key, ANALYSIS_KEY);
            assert_eq!(*resubmission, "same_key_same_body_user_decision_only");
        }
        other => panic!("expected unknown_local_claim, got {other:?}"),
    }
    let wire = serde_json::to_value(&resolution).unwrap();
    assert_eq!(wire["kind"], json!("unknown_local_claim"));
    assert_eq!(wire["analysis_key"], json!(ANALYSIS_KEY));
    assert_eq!(
        wire["resubmission"],
        json!("same_key_same_body_user_decision_only")
    );

    // Branch 3: the claim belongs to another session -> replay blocked (fence 5).
    let other_session = journal_fixture("profile-1", 1, "session-2", key, &store, &clock);
    let resolution =
        resolve_unknown_outcome(&miss_client, Some(&other_session), ANALYSIS_KEY, Some(INTENT_ID))
            .await
            .unwrap();
    assert!(matches!(
        resolution,
        DeviceAiUnknownOutcomeResolution::CrossSessionReplayBlocked
    ));
    assert_eq!(
        serde_json::to_value(&resolution).unwrap()["kind"],
        json!("cross_session_replay_blocked")
    );

    // Branch 4: server hit -> resolved, existing detail reference only.
    let hit_server = Server::start(move |incoming| {
        if incoming.target == "/health" {
            return health_reply();
        }
        if incoming.target.starts_with("/v1/ai/analysis-streams/lookup") {
            return json_reply(200, stream_detail_fixture());
        }
        panic!("resolve must never resubmit");
    })
    .await;
    let hit_client = DeviceAiHostClient::new(Arc::new(hit_server.bridge()));
    let resolution = resolve_unknown_outcome(&hit_client, Some(&journal), ANALYSIS_KEY, None)
        .await
        .unwrap();
    match &resolution {
        DeviceAiUnknownOutcomeResolution::Resolved { detail } => {
            assert_eq!(detail["analysis"]["id"], json!("req-1"));
        }
        other => panic!("expected resolved, got {other:?}"),
    }
    let wire = serde_json::to_value(&resolution).unwrap();
    assert_eq!(wire["kind"], json!("resolved"));
    assert_eq!(wire["detail"]["analysis"]["id"], json!("req-1"));

    // Integrity failure branch: tampered ledger stops recovery, still no submits.
    let (blob_wire, mut stored) = unseal_for_test(&stored_blob(&store), &key);
    stored[0]["event"]["analysis_key"] = json!("forged");
    save_blob(&store, &reseal_for_test(&blob_wire, &stored, &key));
    let resolution = resolve_unknown_outcome(&miss_client, Some(&journal), ANALYSIS_KEY, None)
        .await
        .unwrap();
    match &resolution {
        DeviceAiUnknownOutcomeResolution::JournalIntegrityFailed { violations } => {
            assert!(!violations.is_empty());
        }
        other => panic!("expected journal_integrity_failed, got {other:?}"),
    }
    let wire = serde_json::to_value(&resolution).unwrap();
    assert_eq!(wire["kind"], json!("journal_integrity_failed"));
    assert!(!wire["violations"].as_array().unwrap().is_empty());

    // Neither server ever saw a submit: only /health and lookups.
    for (server, label) in [(&miss_server, "miss"), (&hit_server, "hit")] {
        let requests = server.received.lock().unwrap();
        assert!(
            requests.iter().all(|incoming| incoming.target == "/health"
                || incoming.target.starts_with("/v1/ai/analysis-streams/lookup")),
            "{label} server must never receive a submit"
        );
    }
}
