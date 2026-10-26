//! Actual 8 MiB parser inputs and current pure fingerprint helpers, without starting a host.
//! Native full closure projection remains unsupported and is covered by the existing host tests.
#[path = "support/device_ai_capacity_corpus.rs"]
mod corpus;

use serde_json::Value;
use tire_desktop_lib::device_ai_exact::{
    canonical_device_ai_json, device_ai_digest, parse_device_ai_package, DeviceAiValue,
    DEVICE_AI_MAX_PACKAGE_BYTES,
};
use tire_desktop_lib::device_ai_host::{
    device_context_fingerprint, local_preview_fingerprint, selection_sha256,
    DeviceAiContextIdentityInput, DeviceAiLocalPreviewInput, DeviceAiOriginBindingWire,
    DeviceAiPreviewState, DeviceAiReceiptSourceInput, DeviceAiSelectorWire,
};

fn fingerprints() -> Value {
    corpus::document(
        "closure-fingerprints.json",
        "device-ai-closure-fingerprints@1",
    )
}

fn text<'a>(node: &'a Value, key: &str) -> &'a str {
    node[key]
        .as_str()
        .unwrap_or_else(|| panic!("expected fixture text {key}"))
}

fn exact(node: &Value) -> DeviceAiValue {
    // Input adapter only; the current context fields contain no archived numeric tokens.
    parse_device_ai_package(&serde_json::to_vec(node).expect("fixture input JSON"))
        .expect("fixture exact AST input")
}

fn selectors(node: &Value) -> Vec<DeviceAiSelectorWire> {
    serde_json::from_value(node.clone()).expect("fixture selectors")
}

fn assert_literal(expected: &Value, namespace: &str) {
    let canonical = text(expected, "canonical_text").as_bytes();
    assert_eq!(
        canonical.len() as u64,
        expected["byte_count"].as_u64().expect("literal byte count")
    );
    assert_eq!(
        canonical,
        corpus::hex_decode(text(expected, "canonical_utf8_hex"))
    );
    let mut preimage = namespace.as_bytes().to_vec();
    preimage.push(0);
    preimage.extend_from_slice(canonical);
    // sha2 only: expected is never regenerated with a product canonicalizer/fingerprint helper.
    assert_eq!(corpus::sha256(&preimage), text(expected, "sha256"));
}

#[test]
fn boundary_recipes_replay_actual_default_capacity_bytes() {
    let doc = corpus::document("boundary-recipes.json", "device-ai-capacity-recipes@1");
    assert_eq!(
        doc["max_package_bytes"].as_u64(),
        Some(DEVICE_AI_MAX_PACKAGE_BYTES as u64)
    );
    let cases = doc["cases"].as_array().expect("boundary cases");
    assert_eq!(cases.len(), 10);
    for vector in cases {
        let raw = corpus::expand_boundary(vector);
        let expected = &vector["expected"];
        let result = parse_device_ai_package(&raw);
        if expected["state"] == "rejected" {
            assert_eq!(
                result.unwrap_err().code().as_str(),
                text(expected, "error_code"),
                "{}",
                vector["id"]
            );
        } else {
            let ast = result.unwrap_or_else(|error| panic!("{}: {error}", vector["id"]));
            let canonical = canonical_device_ai_json(&ast).expect("canonical accepted AST");
            assert_eq!(canonical, text(expected, "canonical_text"));
            assert_eq!(
                canonical.as_bytes(),
                corpus::hex_decode(text(expected, "canonical_utf8_hex"))
            );
            assert_eq!(
                device_ai_digest(&ast, None).unwrap(),
                text(expected, "canonical_sha256")
            );
        }
    }
}

#[test]
fn formal_packages_keep_ast_at_actual_capacity_boundary() {
    let doc = corpus::document("formal-package.json", "device-ai-formal-capacity@1");
    let base = parse_device_ai_package(&corpus::read(text(&doc, "base_pack")))
        .expect("base package parser");
    let canonical = canonical_device_ai_json(&base).unwrap();
    let cases = doc["cases"].as_array().expect("formal cases");
    assert_eq!(cases.len(), 4);
    for vector in cases {
        let raw = corpus::expand_formal(&doc, vector);
        // Full projector metadata errors live under expected; this target calls only the parser.
        let expected = &vector["parser_expected"];
        let result = parse_device_ai_package(&raw);
        if expected["state"] == "rejected" {
            assert_eq!(
                result.unwrap_err().code().as_str(),
                text(expected, "error_code")
            );
        } else {
            assert_eq!(
                canonical_device_ai_json(&result.expect("accepted formal package")).unwrap(),
                canonical
            );
        }
    }
}

#[test]
fn selection_digest_sorts_resolved_closure() {
    let doc = fingerprints();
    let expected = &doc["selection_expected"];
    assert_literal(expected, "device-ai-selection@1");
    let original = selectors(&doc["selection_input"]);
    let mut reversed = original.clone();
    reversed.reverse();
    assert_eq!(
        selection_sha256(&original).unwrap(),
        text(expected, "sha256")
    );
    assert_eq!(
        selection_sha256(&reversed).unwrap(),
        text(expected, "sha256")
    );
}

#[test]
fn preview_digest_sorts_closure_but_binds_requested_order() {
    let doc = fingerprints();
    let cases = doc["preview_cases"].as_array().expect("preview cases");
    assert_eq!(cases.len(), 3);
    let mut outcomes = std::collections::BTreeMap::new();
    for vector in cases {
        let node = &vector["input"];
        let expected = &vector["expected"];
        assert_literal(expected, "device-ai-local-preview@1");
        let origin: DeviceAiOriginBindingWire =
            serde_json::from_value(node["origin"].clone()).unwrap();
        let selected = selectors(&node["selected"]);
        let closure = selectors(&node["resolved_closure"]);
        let context = (!node["query_context"].is_null()).then(|| exact(&node["query_context"]));
        let include_ids: Vec<String> =
            serde_json::from_value(node["include_context_ids"].clone()).unwrap();
        let state = match text(node, "state") {
            "ready" => DeviceAiPreviewState::Ready,
            "blocked" => DeviceAiPreviewState::Blocked,
            _ => panic!("unknown fixture state"),
        };
        let actual = local_preview_fingerprint(&DeviceAiLocalPreviewInput {
            question_sha256_value: text(node, "question_sha256"),
            include_context_ids: &include_ids,
            projection_mode: text(node, "projection_mode"),
            query_context: context.as_ref(),
            origin: &origin,
            selected: &selected,
            resolved_closure: &closure,
            state,
            projection_sha256_value: node["projection_sha256"].as_str(),
        })
        .unwrap();
        assert_eq!(actual, text(expected, "sha256"), "{}", vector["id"]);
        outcomes.insert(text(vector, "id").to_owned(), actual);
    }
    assert_eq!(
        outcomes["closure-ascending"],
        outcomes["closure-descending"]
    );
    assert_ne!(
        outcomes["closure-ascending"],
        outcomes["selected-order-change"]
    );
}

#[test]
fn context_digest_uses_utf8_order_for_current_recall_boundaries() {
    let doc = fingerprints();
    let cases = doc["context_cases"].as_array().expect("context cases");
    assert_eq!(cases.len(), 1);
    for vector in cases {
        let node = &vector["input"];
        let expected = &vector["expected"];
        assert_literal(expected, "device-ai-context@1");
        let receipt_sources = node["receipt_sources"]
            .as_array()
            .unwrap()
            .iter()
            .map(|source| DeviceAiReceiptSourceInput {
                selector: serde_json::from_value(source["selector"].clone()).unwrap(),
                selection_reason: text(source, "selection_reason").to_owned(),
                source: exact(&source["source"]),
            })
            .collect();
        let actual = device_context_fingerprint(&DeviceAiContextIdentityInput {
            package_id: text(node, "package_id").to_owned(),
            package_schema: text(node, "package_schema").to_owned(),
            package_sha256: text(node, "package_sha256").to_owned(),
            projection_mode: text(node, "projection_mode").to_owned(),
            projection_sha256: text(node, "projection_sha256").to_owned(),
            selection_sha256: text(node, "selection_sha256").to_owned(),
            receipt_sources,
            device_citations: node["device_citations"]
                .as_array()
                .unwrap()
                .iter()
                .map(exact)
                .collect(),
            domain_boundaries: node["domain_boundaries"]
                .as_array()
                .unwrap()
                .iter()
                .map(exact)
                .collect(),
        })
        .unwrap();
        assert_eq!(actual, text(expected, "sha256"));
    }
}

#[test]
fn integrity_rejects_missing_changed_and_unbounded_inputs() {
    let raw = corpus::read("boundary-recipes.json");
    let sha256 = corpus::sha256(&raw);
    let mut changed = raw.clone();
    changed[0] ^= 1;
    assert!(
        std::panic::catch_unwind(|| corpus::verify_bytes(&changed, raw.len() as u64, &sha256))
            .is_err()
    );
    changed.push(b' ');
    assert!(
        std::panic::catch_unwind(|| corpus::verify_bytes(&changed, raw.len() as u64, &sha256))
            .is_err()
    );
    assert!(std::panic::catch_unwind(|| corpus::verify_manifest(&raw)).is_err());
    assert!(std::panic::catch_unwind(|| corpus::read("missing.json")).is_err());
    assert!(std::panic::catch_unwind(|| corpus::read("../manifest.json")).is_err());
    let doc = corpus::document("boundary-recipes.json", "device-ai-capacity-recipes@1");
    let mut vector = doc["cases"][0].clone();
    vector["input_sha256"] = Value::String("0".repeat(64));
    assert!(std::panic::catch_unwind(|| corpus::expand_boundary(&vector)).is_err());
    vector["input"]["repeat_count"] = Value::from(u64::MAX);
    assert!(std::panic::catch_unwind(|| corpus::expand_boundary(&vector)).is_err());
}

struct IsolatedCorpus {
    root: std::path::PathBuf,
}

impl IsolatedCorpus {
    fn new() -> Self {
        let source = corpus::root_path();
        let manifest = corpus::verify_all(&source);
        let root =
            std::env::temp_dir().join(format!("r73-capacity-corpus-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&root).expect("isolated corpus root");
        std::fs::copy(source.join("manifest.json"), root.join("manifest.json")).unwrap();
        for entry in manifest["files"].as_array().unwrap() {
            let relative = text(entry, "path");
            let target = root.join(relative);
            std::fs::create_dir_all(target.parent().unwrap()).unwrap();
            std::fs::copy(source.join(relative), target).unwrap();
        }
        Self { root }
    }
}

impl Drop for IsolatedCorpus {
    fn drop(&mut self) {
        // Only this newly created UUID root is removed; no fixture path enters the deletion target.
        assert!(self.root.starts_with(std::env::temp_dir()));
        std::fs::remove_dir_all(&self.root).expect("remove isolated corpus");
    }
}

#[test]
fn read_rejects_missing_projection_before_returning_unrelated_recipe() {
    let isolated = IsolatedCorpus::new();
    assert!(!corpus::read_from_root(&isolated.root, "boundary-recipes.json").is_empty());
    std::fs::remove_file(isolated.root.join("projections/formal-n.canonical.json")).unwrap();
    assert!(std::panic::catch_unwind(|| corpus::read_from_root(
        &isolated.root,
        "boundary-recipes.json"
    ))
    .is_err());
}

#[test]
fn read_rejects_same_size_projection_corruption_before_returning_unrelated_recipe() {
    let isolated = IsolatedCorpus::new();
    assert!(!corpus::read_from_root(&isolated.root, "boundary-recipes.json").is_empty());
    let projection = isolated.root.join("projections/formal-n.canonical.json");
    let mut changed = std::fs::read(&projection).unwrap();
    let original_size = changed.len();
    changed[0] ^= 1;
    std::fs::write(&projection, &changed).unwrap();
    assert_eq!(
        std::fs::metadata(&projection).unwrap().len(),
        original_size as u64
    );
    assert!(std::panic::catch_unwind(|| corpus::read_from_root(
        &isolated.root,
        "boundary-recipes.json"
    ))
    .is_err());
}
