//! Separate synthetic capacity corpus. Never falls back to historical artifacts.
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::path::{Component, Path, PathBuf};

const MANIFEST_SHA256: &str = "c1d454ce4875a9d9c6e77fc8dd9f59ae4ae147ca0ca030af553e83bae14525d1";
pub const MAX_PACKAGE_BYTES: usize = 8_388_608;

fn check_relative(relative: &str) {
    assert!(
        !relative.is_empty()
            && !relative.contains(['\\', ':'])
            && relative
                .split('/')
                .all(|part| !part.is_empty() && part != "." && part != "..")
            && Path::new(relative)
                .components()
                .all(|part| matches!(part, Component::Normal(_))),
        "capacity corpus path must stay relative"
    );
}

pub fn sha256(raw: &[u8]) -> String {
    format!("{:x}", Sha256::digest(raw))
}

pub fn verify_bytes(raw: &[u8], expected_size: u64, expected_sha256: &str) {
    assert_eq!(raw.len() as u64, expected_size, "capacity bytes size drift");
    assert_eq!(sha256(raw), expected_sha256, "capacity bytes SHA-256 drift");
}

pub fn verify_manifest(raw: &[u8]) -> Value {
    assert_eq!(
        sha256(raw),
        MANIFEST_SHA256,
        "capacity manifest SHA-256 drift"
    );
    let manifest: Value = serde_json::from_slice(raw).expect("capacity manifest JSON");
    assert_eq!(manifest["schema"], "device-ai-capacity-corpus@1");
    assert_eq!(manifest["synthetic_only"], true);
    assert_eq!(
        manifest["max_package_bytes"].as_u64(),
        Some(MAX_PACKAGE_BYTES as u64)
    );
    manifest
}

pub fn read(relative: &str) -> Vec<u8> {
    read_from_root(&root_path(), relative)
}

pub fn root_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../packages/domain-types/fixtures/device-ai-capacity-v1")
        .canonicalize()
        .expect("tracked capacity corpus unavailable")
}

fn read_contained(root: &Path, relative: &str) -> Vec<u8> {
    check_relative(relative);
    let path = root
        .join(relative)
        .canonicalize()
        .expect("tracked capacity file unavailable");
    assert!(path.starts_with(root), "capacity path escaped root");
    std::fs::read(path).expect("capacity fixture unreadable")
}

/// Check all bindings before returning any fixture, including files no native DUT consumes.
pub fn verify_all(directory: &Path) -> Value {
    let root = directory
        .canonicalize()
        .expect("capacity corpus root unavailable");
    let manifest = verify_manifest(&read_contained(&root, "manifest.json"));
    let files = manifest["files"].as_array().expect("capacity files");
    assert_eq!(files.len(), 22, "capacity corpus file count drift");
    let mut seen = BTreeSet::new();
    for entry in files {
        let relative = entry["path"].as_str().expect("fixture path");
        assert!(seen.insert(relative), "duplicate capacity corpus entry");
        verify_bytes(
            &read_contained(&root, relative),
            entry["byte_count"].as_u64().expect("fixture byte count"),
            entry["sha256"].as_str().expect("fixture SHA-256"),
        );
    }
    manifest
}

/// Root injection is test-only, so isolated corruption never touches the tracked corpus.
pub fn read_from_root(directory: &Path, relative: &str) -> Vec<u8> {
    check_relative(relative);
    let root = directory
        .canonicalize()
        .expect("capacity corpus root unavailable");
    let manifest = verify_all(&root);
    let entries: Vec<_> = manifest["files"]
        .as_array()
        .expect("capacity files")
        .iter()
        .filter(|entry| entry["path"].as_str() == Some(relative))
        .collect();
    assert_eq!(
        entries.len(),
        1,
        "capacity file needs exactly one manifest entry"
    );
    let raw = read_contained(&root, relative);
    verify_bytes(
        &raw,
        entries[0]["byte_count"]
            .as_u64()
            .expect("fixture byte count"),
        entries[0]["sha256"].as_str().expect("fixture SHA-256"),
    );
    raw
}

pub fn document(relative: &str, schema: &str) -> Value {
    let doc: Value = serde_json::from_slice(&read(relative)).expect("capacity fixture JSON");
    assert_eq!(doc["schema"].as_str(), Some(schema));
    doc
}

pub fn hex_decode(text: &str) -> Vec<u8> {
    assert_eq!(text.len() % 2, 0, "hex input length");
    text.as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            let digit = |byte| match byte {
                b'0'..=b'9' => byte - b'0',
                b'a'..=b'f' => byte - b'a' + 10,
                b'A'..=b'F' => byte - b'A' + 10,
                _ => panic!("invalid hex input"),
            };
            (digit(pair[0]) << 4) | digit(pair[1])
        })
        .collect()
}

pub fn expand_boundary(vector: &Value) -> Vec<u8> {
    let input = &vector["input"];
    assert_eq!(input["form"], "repeat_hex");
    let prefix = hex_decode(input["prefix_hex"].as_str().expect("prefix hex"));
    let repeat = hex_decode(input["repeat_hex"].as_str().expect("repeat hex"));
    let suffix = hex_decode(input["suffix_hex"].as_str().expect("suffix hex"));
    let count = input["repeat_count"]
        .as_u64()
        .expect("nonnegative repeat count");
    assert!(
        count <= (MAX_PACKAGE_BYTES + 1) as u64 && !repeat.is_empty(),
        "unbounded capacity recipe"
    );
    let size = (count as usize)
        .checked_mul(repeat.len())
        .and_then(|n| n.checked_add(prefix.len()))
        .and_then(|n| n.checked_add(suffix.len()))
        .expect("recipe size overflow");
    assert!(size <= MAX_PACKAGE_BYTES + 1, "recipe exceeds test bound");
    let mut raw = Vec::with_capacity(size);
    raw.extend_from_slice(&prefix);
    for _ in 0..count {
        raw.extend_from_slice(&repeat);
    }
    raw.extend_from_slice(&suffix);
    verify_bytes(
        &raw,
        vector["input_byte_count"].as_u64().expect("input bytes"),
        vector["input_sha256"].as_str().expect("input SHA-256"),
    );
    raw
}

pub fn expand_formal(doc: &Value, vector: &Value) -> Vec<u8> {
    let mut raw = read(doc["base_pack"].as_str().expect("base pack path"));
    let padding = vector["padding_spaces"]
        .as_u64()
        .expect("nonnegative padding");
    assert!(
        padding <= (MAX_PACKAGE_BYTES + 1) as u64,
        "unbounded formal padding"
    );
    let size = raw
        .len()
        .checked_add(padding as usize)
        .expect("formal size overflow");
    assert!(size <= MAX_PACKAGE_BYTES + 1, "formal exceeds test bound");
    raw.resize(size, b' ');
    verify_bytes(
        &raw,
        vector["input_byte_count"]
            .as_u64()
            .expect("formal input bytes"),
        vector["input_sha256"]
            .as_str()
            .expect("formal input SHA-256"),
    );
    raw
}
