//! E1 canonical-vector replay for the Rust device-ai exact pipeline.
//!
//! Reads the authoritative vectors from
//! `.artifacts/device-ai50/specs/e1-canonical-vectors-a.json` at runtime and
//! locks 68/68 parity (47 accept + 21 reject) with the sealed Python
//! reference: accepted vectors must reproduce canonical bytes, both sha256
//! forms and the encoded DeviceAIValue shape byte-for-byte (the 250000-node
//! vector binds via sha256 only, per its `sha256_only_size` binding);
//! rejected vectors must fail closed with the listed error codes; and the
//! cross-vector invariants must hold after replay.
//!
//! The module under test lives at `src/device_ai_exact.rs` and is compiled
//! here through `#[path]` because it is deliberately not yet registered in
//! `lib.rs` (the DeviceAIValue wire is still an unfrozen draft).

#[path = "../src/device_ai_exact.rs"]
mod device_ai_exact;

use device_ai_exact::{
    canonical_device_ai_json, device_ai_digest, encode_device_ai_value, parse_device_ai_package,
};

const VECTORS_PATH: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../.artifacts/device-ai50/specs/e1-canonical-vectors-a.json"
);

fn hex_digit(byte: u8) -> u8 {
    match byte {
        b'0'..=b'9' => byte - b'0',
        b'a'..=b'f' => byte - b'a' + 10,
        b'A'..=b'F' => byte - b'A' + 10,
        _ => panic!("invalid hex digit {}", byte),
    }
}

fn hex_decode(text: &str) -> Vec<u8> {
    let bytes = text.as_bytes();
    assert_eq!(bytes.len() % 2, 0, "hex text must have even length");
    (0..bytes.len() / 2)
        .map(|i| (hex_digit(bytes[2 * i]) << 4) | hex_digit(bytes[2 * i + 1]))
        .collect()
}

/// literal/bytes vectors are expanded from their utf8_hex; template vectors
/// from (prefix + repeat * count + suffix), all UTF-8 encoded, exactly like
/// the file's replay_instructions.
fn vector_input_bytes(input: &serde_json::Value) -> Vec<u8> {
    match input["form"].as_str().expect("input form") {
        "literal" | "bytes" => hex_decode(input["utf8_hex"].as_str().expect("utf8_hex")),
        "template" => {
            let mut text = String::from(input["prefix"].as_str().expect("prefix"));
            let repeat = input["repeat"].as_str().expect("repeat");
            for _ in 0..input["count"].as_u64().expect("count") {
                text.push_str(repeat);
            }
            text.push_str(input["suffix"].as_str().expect("suffix"));
            text.into_bytes()
        }
        other => panic!("unknown input form: {other}"),
    }
}

struct AcceptedOutcome {
    canonical: Option<String>,
    sha256: String,
    encoded_text: Option<String>,
}

#[test]
fn device_ai_e1_parity_replays_all_68_vectors() {
    let raw = std::fs::read_to_string(VECTORS_PATH)
        .unwrap_or_else(|e| panic!("read E1 vector file {}: {e}", VECTORS_PATH));
    let doc: serde_json::Value =
        serde_json::from_str(&raw).unwrap_or_else(|e| panic!("parse E1 vector file: {e}"));
    let vectors = doc["vectors"].as_array().expect("vectors array");
    let counts = &doc["counts"];
    assert_eq!(
        vectors.len() as u64,
        counts["total"].as_u64().expect("total count"),
        "vector total must match the file's own counts"
    );
    let namespace = doc["constants"]["namespaced_sha256_namespace"]
        .as_str()
        .expect("namespace constant");

    let mut accepted_count = 0usize;
    let mut rejected_count = 0usize;
    let mut outcomes: std::collections::HashMap<String, AcceptedOutcome> =
        std::collections::HashMap::new();

    for vector in vectors {
        let id = vector["id"].as_str().expect("vector id");
        let bytes = vector_input_bytes(&vector["input"]);
        assert_eq!(
            bytes.len() as u64,
            vector["input_byte_count"].as_u64().expect("input_byte_count"),
            "[{id}] expanded input size"
        );

        if vector["state"].as_str() == Some("accepted") {
            accepted_count += 1;
            let ast = parse_device_ai_package(&bytes)
                .unwrap_or_else(|e| panic!("[{id}] expected accept, got {e}"));

            let size_bound = vector["output_binding"].as_str() == Some("sha256_only_size");
            assert_eq!(
                vector.get("canonical").is_some(),
                !size_bound,
                "[{id}] canonical presence must follow the output binding"
            );
            assert_eq!(
                vector.get("encoded").is_some(),
                !size_bound,
                "[{id}] encoded presence must follow the output binding"
            );

            let mut canonical = None;
            if !size_bound {
                let text = canonical_device_ai_json(&ast)
                    .unwrap_or_else(|e| panic!("[{id}] canonical: {e}"));
                assert_eq!(
                    text,
                    vector["canonical"]["text"].as_str().expect("canonical text"),
                    "[{id}] canonical text"
                );
                assert_eq!(
                    text.as_bytes(),
                    &hex_decode(vector["canonical"]["utf8_hex"].as_str().expect("canonical hex"))[..],
                    "[{id}] canonical bytes"
                );
                canonical = Some(text);
            }

            let mut encoded_text = None;
            if !size_bound {
                let encoded = encode_device_ai_value(&ast)
                    .unwrap_or_else(|e| panic!("[{id}] encode: {e}"));
                let json = encoded
                    .to_json_value()
                    .unwrap_or_else(|e| panic!("[{id}] encoded json: {e}"));
                assert_eq!(json, vector["encoded"], "[{id}] encoded shape");
                // The encoded tree is number-free, so serde_json's compact
                // output (BTreeMap key order, the json.dumps escape set)
                // matches the file's encoded_canonical_text byte-for-byte.
                let serialized = serde_json::to_string(&json).expect("serialize encoded");
                assert_eq!(
                    serialized,
                    vector["encoded_canonical_text"]
                        .as_str()
                        .expect("encoded canonical text"),
                    "[{id}] encoded canonical text"
                );
                encoded_text = Some(serialized);
            }

            // Both output bindings carry the two digest forms over the
            // ORIGINAL AST; the encoded value never participates.
            let sha256 = device_ai_digest(&ast, None)
                .unwrap_or_else(|e| panic!("[{id}] bare digest: {e}"));
            assert_eq!(
                sha256,
                vector["sha256"].as_str().expect("sha256"),
                "[{id}] sha256"
            );
            let namespaced = device_ai_digest(&ast, Some(namespace))
                .unwrap_or_else(|e| panic!("[{id}] namespaced digest: {e}"));
            assert_eq!(
                namespaced,
                vector["sha256_namespaced"].as_str().expect("sha256_namespaced"),
                "[{id}] sha256_namespaced (namespace {namespace})"
            );

            outcomes.insert(
                id.to_string(),
                AcceptedOutcome {
                    canonical,
                    sha256,
                    encoded_text,
                },
            );
        } else {
            rejected_count += 1;
            let errors = vector["errors"].as_array().expect("errors array");
            assert_eq!(errors.len(), 1, "[{id}] expected exactly one error code");
            let expected = errors[0].as_str().expect("error code");
            match parse_device_ai_package(&bytes) {
                Ok(_) => panic!("[{id}] expected rejection {expected}"),
                Err(e) => assert_eq!(e.code().as_str(), expected, "[{id}] error code"),
            }
        }
    }

    assert_eq!(
        accepted_count as u64,
        counts["accepted"].as_u64().expect("accepted count"),
        "accepted count"
    );
    assert_eq!(
        rejected_count as u64,
        counts["rejected"].as_u64().expect("rejected count"),
        "rejected count"
    );
    assert_eq!(accepted_count, 47, "47 accepted vectors");
    assert_eq!(rejected_count, 21, "21 rejected vectors");
    assert_eq!(accepted_count + rejected_count, 68, "68 total vectors");

    // Cross-vector invariants must hold after replay.
    let invariants = &doc["cross_vector_invariants"];
    for pair in invariants["canonical_must_match"].as_array().expect("canonical_must_match") {
        let first = pair[0].as_str().expect("first id");
        let second = pair[1].as_str().expect("second id");
        assert_ne!(
            outcomes[first].canonical, None,
            "canonical missing for {first}"
        );
        assert_eq!(
            outcomes[first].canonical, outcomes[second].canonical,
            "canonical_must_match {first} == {second}"
        );
    }
    for pair in invariants["encoded_must_differ"].as_array().expect("encoded_must_differ") {
        let first = pair[0].as_str().expect("first id");
        let second = pair[1].as_str().expect("second id");
        assert_ne!(
            outcomes[first].encoded_text, outcomes[second].encoded_text,
            "encoded_must_differ {first} != {second}"
        );
    }
    for pair in invariants["sha256_must_differ"].as_array().expect("sha256_must_differ") {
        let first = pair[0].as_str().expect("first id");
        let second = pair[1].as_str().expect("second id");
        assert_ne!(
            outcomes[first].sha256, outcomes[second].sha256,
            "sha256_must_differ {first} != {second}"
        );
    }
}
