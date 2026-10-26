//! Test-only access to the tracked synthetic contract corpus. No artifact fallback.
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::path::{Component, Path};

const PROVENANCE_SHA256: &str = "278e8cacad9a8537264781e49ce381111e6ed50b17a224aa32ccdf066012172d";

fn check_relative(relative: &str) {
    assert!(!relative.is_empty(), "empty corpus path");
    assert!(
        !relative.contains(['\\', ':'])
            && relative
                .split('/')
                .all(|part| !part.is_empty() && part != "." && part != "..")
            && Path::new(relative)
                .components()
                .all(|part| matches!(part, Component::Normal(_))),
        "corpus path must stay relative: {relative}"
    );
}

fn check_bytes(raw: &[u8], entry: &Value) {
    assert_eq!(
        raw.len() as u64,
        entry["byte_count"].as_u64().expect("corpus byte_count"),
        "corpus byte count drift"
    );
    assert_eq!(
        format!("{:x}", Sha256::digest(raw)),
        entry["sha256"].as_str().expect("corpus sha256"),
        "corpus SHA-256 drift"
    );
}

pub fn read(relative: &str) -> Vec<u8> {
    check_relative(relative);
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../packages/domain-types/fixtures/device-ai-v1")
        .canonicalize()
        .expect("tracked device-AI corpus unavailable");
    let provenance_raw =
        std::fs::read(root.join("provenance.json")).expect("corpus provenance unavailable");
    assert_eq!(
        format!("{:x}", Sha256::digest(&provenance_raw)),
        PROVENANCE_SHA256,
        "corpus provenance SHA-256 drift"
    );
    let provenance: Value =
        serde_json::from_slice(&provenance_raw).expect("corpus provenance JSON");
    assert_eq!(provenance["schema"], "device-ai-test-corpus-provenance@1");
    assert_eq!(provenance["source_root"], ".artifacts/device-ai50");
    assert_eq!(provenance["synthetic_only"], true);
    let files = provenance["files"].as_array().expect("corpus files");
    assert_eq!(provenance["file_count"].as_u64(), Some(files.len() as u64));
    let entries: Vec<_> = files
        .iter()
        .filter(|entry| entry["path"].as_str() == Some(relative))
        .collect();
    assert_eq!(
        entries.len(),
        1,
        "corpus file must have exactly one provenance entry: {relative}"
    );
    assert_eq!(
        entries[0]["source_path"].as_str(),
        Some(format!(".artifacts/device-ai50/{relative}").as_str())
    );
    let path = root
        .join(relative)
        .canonicalize()
        .expect("tracked corpus file unavailable");
    assert!(path.starts_with(&root), "corpus file escaped its root");
    let raw = std::fs::read(path).expect("tracked corpus file unreadable");
    check_bytes(&raw, entries[0]);
    raw
}

#[test]
fn corpus_rejects_traversal_and_unlisted_paths() {
    for path in [
        "../provenance.json",
        "/specs/test.json",
        "specs//test.json",
        "specs/./test.json",
        "specs\\test.json",
        "C:/test.json",
        "unlisted.json",
    ] {
        assert!(
            std::panic::catch_unwind(|| read(path)).is_err(),
            "accepted unsafe or unlisted path: {path}"
        );
    }
}

#[test]
fn corpus_rejects_changed_payload_bytes() {
    let raw = b"fixture";
    let entry = serde_json::json!({"byte_count": raw.len(), "sha256": format!("{:x}", Sha256::digest(raw))});
    check_bytes(raw, &entry);
    assert!(std::panic::catch_unwind(|| check_bytes(b"fixturE", &entry)).is_err());
    assert!(std::panic::catch_unwind(|| check_bytes(b"fixture!", &entry)).is_err());
}
