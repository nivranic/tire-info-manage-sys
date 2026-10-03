//! device-ai Host wiring for the native stack (round 50, P1-3 host step 3;
//! selector wire extended to the four open prepare domains in round 50
//! P1-4c — tire / vehicle / recall / recall_search with the five-value
//! projection_mode Literal and the frozen_decision_closure approved_closure
//! gates, mirroring the TS SDK 1:1).
//!
//! Rust counterpart of the sealed TS SDK `packages/api-client/src/device-ai-host.ts`
//! (round 50, P1-3 host step 2); semantics are kept 1:1 where the two runtimes
//! allow it, and every intentional deviation is flagged in a comment and in the
//! round report. Four concerns, none of them a Provider call and none of them a
//! new wire (roundtable D15: the wire is an unfrozen draft, so nothing here is
//! exported to `packages/domain-types`):
//!
//!  1. [`DeviceAiHostClient`] — metadata-only prepare + lookup/read against the
//!     implemented server routes, and the device branch of the existing stream
//!     entry. Request bodies match the closed server DTOs in
//!     `apps/api/tire_api/device_ai.py` (`DeviceAIPrepareRequest` /
//!     `DeviceSubmission` / `ProviderConsent`) and `ai_analysis.py`
//!     (`AnalysisRequest`) verbatim; the frozen field-name lists live in the
//!     `DEVICE_AI_*_FIELDS` constants and the serialization shape is locked by
//!     unit tests. Transport reuses the existing [`crate::bridge::Bridge`]
//!     (session cookies, bootstrap, timeouts, response bounds, cancellation
//!     registry); a second HTTP stack is deliberately NOT built. HTTP error
//!     bodies pass through with status + closed `detail.code` (the ApiError
//!     404/409/422 mapping of the TS pipeline).
//!  2. Fingerprint helpers — `question_sha256` (bare sha256 of trim-once
//!     UTF-8), `selection_sha256` / `device_context_fingerprint` /
//!     `local_preview_fingerprint` per `.artifacts/device-ai50/specs/
//!     fingerprint-spec.md` sections 2/3/4, plus [`compute_local_preview`]
//!     which reuses the exact-JSON module `crate::device_ai_exact`
//!     (68/68 E1 parity). The three new namespaces are proposals pending Root
//!     approval and are centralized as constants.
//!  3. [`DeviceAiJournal`] — AES-256-GCM encrypted append-only journal with
//!     the five fences (owner / generation / SHA chain / monotonic clock /
//!     session). AES-GCM comes from the existing `aes-gcm` dependency (same
//!     primitive as `offline::crypto`), and the key is loaded from the OS
//!     secure store through the same keyring conventions (`OsJournalKeyStore`,
//!     service `org.taiji.tireintelligence.desktop.deviceai.v1`). The AAD is
//!     `canonical(["device-ai-journal@1", owner])`, binding the owner
//!     cryptographically under the explicit header fence.
//!  4. [`resolve_unknown_outcome`] — N18 lookup-first recovery after a
//!     disconnect or crash. Read-only; it never resubmits on its own.
//!
//! Rust-side closed-code extension: the TS SDK throws free-form `Error` for
//! malformed server views ("响应格式不完整"); IPC here only carries closed
//! `&'static str` codes, so those failures map to the new closed code
//! `device_ai_host_response_invalid`.

use crate::bridge::Bridge;
use crate::device_ai_exact::{
    canonical_device_ai_json, device_ai_digest, parse_device_ai_package, DeviceAiNumber,
    DeviceAiText, DeviceAiValue,
};
use crate::security::{ApiRequest, NativeResult};
use aes_gcm::{
    aead::{Aead, KeyInit, Payload},
    Aes256Gcm, Nonce,
};
use base64::{engine::general_purpose::STANDARD, Engine};
use rand_core::{OsRng, RngCore};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use uuid::Uuid;
use zeroize::Zeroizing;

// ---------------------------------------------------------------------------
// Namespaces, schemas and closed server DTO field lists (TS parity).
// ---------------------------------------------------------------------------

pub const DEVICE_AI_SELECTION_NAMESPACE: &str = "device-ai-selection@1";
pub const DEVICE_AI_CONTEXT_NAMESPACE: &str = "device-ai-context@1";
pub const DEVICE_AI_LOCAL_PREVIEW_NAMESPACE: &str = "device-ai-local-preview@1";
pub const DEVICE_AI_JOURNAL_SCHEMA: &str = "device-ai-journal@1";
pub const DEVICE_AI_JOURNAL_ENTRY_SCHEMA: &str = "device-ai-journal-entry@1";
pub const DEVICE_AI_PROJECTION_POLICY_VERSION: &str = "device-ai-projection@1";
pub const DEVICE_AI_NUMBER_TOKEN_SCHEMA: &str = "device-number-token@1";

/// `Number.isSafeInteger` bound shared with the TS SDK (`metaInt`).
pub const DEVICE_AI_SAFE_INTEGER: u64 = 9_007_199_254_740_991;

/// Closed server DTO field lists (apps/api/tire_api/device_ai.py and
/// ai_analysis.py, verbatim; server models are extra=forbid).
pub const DEVICE_AI_PREPARE_REQUEST_FIELDS: [&str; 12] = [
    "package_id",
    "expected_sha256",
    "expected_byte_count",
    "expected_schema",
    "expected_owner_scope_id",
    "selectors",
    "projection_mode",
    "approved_closure",
    "expected_projection_sha256",
    "question_sha256",
    "host_receipt_id",
    "intent_id",
];
pub const DEVICE_AI_SUBMISSION_FIELDS: [&str; 4] = [
    "prepare_id",
    "host_receipt_id",
    "device_context_fingerprint",
    "provider_consent",
];
pub const DEVICE_AI_PROVIDER_CONSENT_FIELDS: [&str; 6] = [
    "expected_pack_fingerprint",
    "expected_device_context_fingerprint",
    "question_sha256",
    "provider",
    "model",
    "expected_provider_policy_fingerprint",
];
pub const DEVICE_AI_ANALYSIS_REQUEST_FIELDS: [&str; 4] = [
    "pack_id",
    "question",
    "allow_external_processing",
    "device_submission",
];

// ---------------------------------------------------------------------------
// Closed host failure codes (byte-equal to the TS DeviceAiHostErrorCode set,
// plus the Rust-only device_ai_host_response_invalid extension).
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeviceAiHostErrorCode {
    InvalidArgument,
    PackageMismatch,
    PreviewUnsupported,
    JournalOwnerMismatch,
    JournalGenerationMismatch,
    JournalSessionMismatch,
    JournalChainBroken,
    JournalEntryTampered,
    JournalClockRegression,
    JournalCorrupt,
    ResponseInvalid,
}

impl DeviceAiHostErrorCode {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::InvalidArgument => "device_ai_host_invalid_argument",
            Self::PackageMismatch => "device_ai_host_package_mismatch",
            Self::PreviewUnsupported => "device_ai_host_preview_unsupported",
            Self::JournalOwnerMismatch => "device_ai_host_journal_owner_mismatch",
            Self::JournalGenerationMismatch => "device_ai_host_journal_generation_mismatch",
            Self::JournalSessionMismatch => "device_ai_host_journal_session_mismatch",
            Self::JournalChainBroken => "device_ai_host_journal_chain_broken",
            Self::JournalEntryTampered => "device_ai_host_journal_entry_tampered",
            Self::JournalClockRegression => "device_ai_host_journal_clock_regression",
            Self::JournalCorrupt => "device_ai_host_journal_corrupt",
            Self::ResponseInvalid => "device_ai_host_response_invalid",
        }
    }
}

impl std::fmt::Display for DeviceAiHostErrorCode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

fn host_err(code: DeviceAiHostErrorCode) -> DeviceAiHostErrorCode {
    code
}

// ---------------------------------------------------------------------------
// Small validators (TS parity; length bounds count Unicode codepoints, which
// matches the pydantic server bounds — JS .length would count UTF-16 units).
// ---------------------------------------------------------------------------

fn is_hash64(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

fn is_plain_string(value: &str, max: usize) -> bool {
    !value.is_empty()
        && value.chars().count() <= max
        && !value.contains(['\r', '\n', '\0'])
}

fn is_safe_positive_int(value: u64) -> bool {
    (1..=DEVICE_AI_SAFE_INTEGER).contains(&value)
}

fn is_package_schema(value: &str) -> bool {
    matches!(value, "offline-pack@1" | "offline-pack@2")
}

/// ECMAScript `String.prototype.trim` whitespace set (used only around UUID
/// normalization, mirroring the TS `value.trim()`); deliberately distinct from
/// the Python whitespace set pinned for questions below.
fn is_js_trim_whitespace(character: char) -> bool {
    matches!(
        character,
        '\u{09}' | '\u{0a}'
            | '\u{0b}'
            | '\u{0c}'
            | '\u{0d}'
            | '\u{20}'
            | '\u{a0}'
            | '\u{feff}'
            | '\u{1680}'
            | '\u{2000}'..='\u{200a}'
            | '\u{2028}'
            | '\u{2029}'
            | '\u{202f}'
            | '\u{205f}'
            | '\u{3000}'
    )
}

fn js_trim(text: &str) -> &str {
    text.trim_matches(is_js_trim_whitespace)
}

/// Canonical lowercase UUID normalization mirroring the TS `canonicalDeviceAiUuid`
/// (accepts uppercase and braced spellings; the canonical form must be a
/// hyphenated lowercase UUID with version 1-8 and RFC 4122 variant, exactly the
/// TS `UUID_CANONICAL` set). The server `canonical_uuid` additionally accepts
/// other version/variant nibbles; the Host is stricter, like the TS SDK.
pub fn canonical_device_ai_uuid(value: &str) -> Result<String, DeviceAiHostErrorCode> {
    let invalid = Err(host_err(DeviceAiHostErrorCode::InvalidArgument));
    if value.is_empty() || value.chars().count() > 68 {
        return invalid;
    }
    let mut text = js_trim(value).to_ascii_lowercase();
    if text.starts_with('{') && text.ends_with('}') {
        text = text[1..text.len() - 1].to_owned();
    }
    let bytes = text.as_bytes();
    if bytes.len() != 36 {
        return invalid;
    }
    for position in [8, 13, 18, 23] {
        if bytes[position] != b'-' {
            return invalid;
        }
    }
    for (index, byte) in bytes.iter().enumerate() {
        if matches!(index, 8 | 13 | 18 | 23) {
            continue;
        }
        if !byte.is_ascii_hexdigit() {
            return invalid;
        }
    }
    // version nibble 1-8, variant nibble 8/9/a/b (already lowercased).
    if !(b'1'..=b'8').contains(&bytes[14]) || !matches!(bytes[19], b'8' | b'9' | b'a' | b'b') {
        return invalid;
    }
    Ok(text)
}

// ---------------------------------------------------------------------------
// question: trim-once + codepoint counting + bare UTF-8 sha256 (spec section 5).
// ---------------------------------------------------------------------------

/// Python `str.strip()` whitespace set, pinned explicitly (roundtable D3); JS
/// `String.prototype.trim` differs (it strips U+FEFF but not U+001C..U+001F or
/// U+0085).
fn is_python_whitespace(character: char) -> bool {
    matches!(
        character,
        '\t' | '\n'
            | '\u{0b}'
            | '\u{0c}'
            | '\r'
            | ' '
            | '\u{1c}'..='\u{1f}'
            | '\u{85}'
            | '\u{a0}'
            | '\u{1680}'
            | '\u{2000}'..='\u{200a}'
            | '\u{2028}'
            | '\u{2029}'
            | '\u{202f}'
            | '\u{205f}'
            | '\u{3000}'
    )
}

/// Exactly one trim pass over the pinned whitespace set (no double trim).
pub fn trim_once_question(text: &str) -> &str {
    text.trim_matches(is_python_whitespace)
}

/// Unicode codepoint count (Python `len()`), never UTF-16 code units.
pub fn question_codepoints(text: &str) -> usize {
    text.chars().count()
}

/// The single normalization point before any digest or submit body.
pub fn normalize_question(text: &str) -> Result<&str, DeviceAiHostErrorCode> {
    let trimmed = trim_once_question(text);
    let count = question_codepoints(trimmed);
    if count < 2 || count > 2000 {
        return Err(host_err(DeviceAiHostErrorCode::InvalidArgument));
    }
    Ok(trimmed)
}

/// Bare sha256(UTF-8 bytes): no namespace, no JSON quoting, no NFKC (spec 5).
pub fn question_sha256(normalized_question: &str) -> String {
    sha256_hex(normalized_question.as_bytes())
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut out = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(out, "{byte:02x}");
    }
    out
}

// ---------------------------------------------------------------------------
// AST builder helpers over the exact-JSON module.
// ---------------------------------------------------------------------------

fn text_node(text: &str) -> DeviceAiValue {
    DeviceAiValue::Text(DeviceAiText::new(text))
}

fn object_node(entries: Vec<(&str, DeviceAiValue)>) -> DeviceAiValue {
    DeviceAiValue::Object(
        entries
            .into_iter()
            .map(|(key, value)| (DeviceAiText::new(key), value))
            .collect(),
    )
}

fn array_node(items: Vec<DeviceAiValue>) -> DeviceAiValue {
    DeviceAiValue::Array(items)
}

/// Bounded metadata integer as an exact number lexeme (TS `metaInt`).
fn meta_int(value: i64) -> Result<DeviceAiNumber, DeviceAiHostErrorCode> {
    if value.unsigned_abs() > DEVICE_AI_SAFE_INTEGER as u64 {
        return Err(host_err(DeviceAiHostErrorCode::InvalidArgument));
    }
    DeviceAiNumber::new(&value.to_string())
        .map_err(|_| host_err(DeviceAiHostErrorCode::InvalidArgument))
}

fn meta_int_node(value: i64) -> Result<DeviceAiValue, DeviceAiHostErrorCode> {
    Ok(DeviceAiValue::Number(meta_int(value)?))
}

/// Plain serde JSON -> exact AST for journal/fingerprint material (the TS
/// `toJournalAst`): integers become lexemes under the safe-integer bound,
/// floats and other non-JSON shapes fail closed.
fn json_to_ast(value: &Value) -> Option<DeviceAiValue> {
    match value {
        Value::Null => Some(DeviceAiValue::Null),
        Value::Bool(flag) => Some(DeviceAiValue::Bool(*flag)),
        Value::String(text) => Some(DeviceAiValue::Text(DeviceAiText::new(text))),
        Value::Number(number) => {
            if let Some(unsigned) = number.as_u64() {
                if unsigned > DEVICE_AI_SAFE_INTEGER {
                    return None;
                }
                DeviceAiNumber::new(&unsigned.to_string()).ok().map(DeviceAiValue::Number)
            } else if let Some(signed) = number.as_i64() {
                if signed.unsigned_abs() > DEVICE_AI_SAFE_INTEGER as u64 {
                    return None;
                }
                DeviceAiNumber::new(&signed.to_string()).ok().map(DeviceAiValue::Number)
            } else {
                None
            }
        }
        Value::Array(items) => items
            .iter()
            .map(json_to_ast)
            .collect::<Option<Vec<_>>>()
            .map(array_node),
        Value::Object(map) => {
            let mut out = BTreeMap::new();
            for (key, item) in map {
                out.insert(DeviceAiText::new(key), json_to_ast(item)?);
            }
            Some(DeviceAiValue::Object(out))
        }
    }
}

// ---------------------------------------------------------------------------
// selector wire shape (server DeviceSelector). Round 50 P1-4c: the four open
// prepare domains — tire / vehicle / recall / recall_search (device_ai.py
// L121). test_event stays OUT of this set (N27 closed domain), so a
// test_event selector fails deserialization here exactly the way the server
// Literal 422s it; the projection core rejects it as well (double fence).
// ---------------------------------------------------------------------------

/// Per-domain archived reference union, keyed by `kind` (server DeviceReference
/// discriminated union, verbatim key sets: tire carries variant_id; recall
/// carries the explicitly nullable recall_revision_id; vehicle / recall_search
/// are snapshot+verification only).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", deny_unknown_fields)]
pub enum DeviceAiReferenceWire {
    #[serde(rename = "tire")]
    Tire {
        snapshot_id: String,
        variant_id: String,
        verification_id: String,
    },
    #[serde(rename = "vehicle")]
    Vehicle {
        snapshot_id: String,
        verification_id: String,
    },
    #[serde(rename = "recall")]
    Recall {
        snapshot_id: String,
        #[serde(default)]
        recall_revision_id: Option<String>,
        verification_id: String,
    },
    #[serde(rename = "recall_search")]
    RecallSearch {
        snapshot_id: String,
        verification_id: String,
    },
}

impl DeviceAiReferenceWire {
    #[must_use]
    pub const fn kind(&self) -> &'static str {
        match self {
            Self::Tire { .. } => "tire",
            Self::Vehicle { .. } => "vehicle",
            Self::Recall { .. } => "recall",
            Self::RecallSearch { .. } => "recall_search",
        }
    }

    fn ids(&self) -> Vec<&str> {
        match self {
            Self::Tire {
                snapshot_id,
                variant_id,
                verification_id,
            } => vec![
                snapshot_id.as_str(),
                variant_id.as_str(),
                verification_id.as_str(),
            ],
            Self::Vehicle {
                snapshot_id,
                verification_id,
            }
            | Self::RecallSearch {
                snapshot_id,
                verification_id,
            } => vec![snapshot_id.as_str(), verification_id.as_str()],
            Self::Recall {
                snapshot_id,
                recall_revision_id,
                verification_id,
            } => {
                // Server: recall_revision_id is str|None, 1..64 when present.
                let mut ids = vec![snapshot_id.as_str(), verification_id.as_str()];
                if let Some(revision) = recall_revision_id {
                    ids.push(revision.as_str());
                }
                ids
            }
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DeviceAiSelectorWire {
    pub kind: String,
    pub member_key: String,
    #[serde(default)]
    pub document_id: Option<String>,
    #[serde(default)]
    pub record_index: Option<i64>,
    pub reference: DeviceAiReferenceWire,
}

/// Server `DeviceSelector` Literal, record_index bound included (StrictInt
/// 0..=3999 in device_ai.py L124).
pub const DEVICE_AI_SELECTOR_MAX_RECORD_INDEX: i64 = 3999;

pub fn assert_device_ai_selector(selector: &DeviceAiSelectorWire) -> Result<(), DeviceAiHostErrorCode> {
    let invalid = || host_err(DeviceAiHostErrorCode::InvalidArgument);
    // Four open domains only — test_event and anything else fail here (N27).
    if !matches!(
        selector.kind.as_str(),
        "tire" | "vehicle" | "recall" | "recall_search"
    ) {
        return Err(invalid());
    }
    if selector.kind != selector.reference.kind() {
        return Err(invalid()); // 'selector kind 与引用 kind 必须一致'
    }
    if !is_hash64(&selector.member_key) {
        return Err(invalid());
    }
    if let Some(document_id) = &selector.document_id {
        // TS compares JS string length; codepoint counting matches the server.
        if !is_plain_string(document_id, 200) {
            return Err(invalid());
        }
    }
    if selector
        .record_index
        .is_some_and(|index| !(0..=DEVICE_AI_SELECTOR_MAX_RECORD_INDEX).contains(&index))
    {
        return Err(invalid());
    }
    // '缺少 document_id 时不能携带 record_index' (model_validator).
    if selector.document_id.is_none() && selector.record_index.is_some() {
        return Err(invalid());
    }
    // tire/vehicle are whole-observation domains: record_index stays null
    // ('{kind} selector 不携带 record_index（投影核恒要求 None）').
    if matches!(selector.kind.as_str(), "tire" | "vehicle") && selector.record_index.is_some() {
        return Err(invalid());
    }
    if selector.reference.ids().iter().any(|id| !is_plain_string(id, 64)) {
        return Err(invalid());
    }
    Ok(())
}

/// Selector as canonical AST input (fingerprint-spec section 2 item shape);
/// the reference key set follows the domain exactly, like the TS
/// `Object.entries(selector.reference)` over the declared interface.
pub fn selector_ast(selector: &DeviceAiSelectorWire) -> Result<DeviceAiValue, DeviceAiHostErrorCode> {
    assert_device_ai_selector(selector)?;
    let reference = match &selector.reference {
        DeviceAiReferenceWire::Tire {
            snapshot_id,
            variant_id,
            verification_id,
        } => object_node(vec![
            ("kind", text_node("tire")),
            ("snapshot_id", text_node(snapshot_id)),
            ("variant_id", text_node(variant_id)),
            ("verification_id", text_node(verification_id)),
        ]),
        DeviceAiReferenceWire::Vehicle {
            snapshot_id,
            verification_id,
        } => object_node(vec![
            ("kind", text_node("vehicle")),
            ("snapshot_id", text_node(snapshot_id)),
            ("verification_id", text_node(verification_id)),
        ]),
        DeviceAiReferenceWire::Recall {
            snapshot_id,
            recall_revision_id,
            verification_id,
        } => object_node(vec![
            ("kind", text_node("recall")),
            ("snapshot_id", text_node(snapshot_id)),
            (
                "recall_revision_id",
                recall_revision_id
                    .as_deref()
                    .map(text_node)
                    .unwrap_or(DeviceAiValue::Null),
            ),
            ("verification_id", text_node(verification_id)),
        ]),
        DeviceAiReferenceWire::RecallSearch {
            snapshot_id,
            verification_id,
        } => object_node(vec![
            ("kind", text_node("recall_search")),
            ("snapshot_id", text_node(snapshot_id)),
            ("verification_id", text_node(verification_id)),
        ]),
    };
    let record_index = match selector.record_index {
        None => DeviceAiValue::Null,
        Some(index) => meta_int_node(index)?,
    };
    Ok(object_node(vec![
        (
            "document_id",
            selector
                .document_id
                .as_deref()
                .map(text_node)
                .unwrap_or(DeviceAiValue::Null),
        ),
        ("kind", text_node(&selector.kind)),
        ("member_key", text_node(&selector.member_key)),
        ("record_index", record_index),
        ("reference", reference),
    ]))
}

fn by_member_key(a: &DeviceAiSelectorWire, b: &DeviceAiSelectorWire) -> std::cmp::Ordering {
    a.member_key.cmp(&b.member_key)
}

/// fingerprint-spec section 2: member_key-ascending resolved closure digest.
/// REQUESTED selectors are capped at 6 (server DTO); the RESOLVED closure may
/// grow past that after frozen_decision_closure dependency expansion (the pack
/// member bound is 200), so only the non-empty/uniqueness fences apply (TS
/// parity).
pub fn selection_sha256(resolved: &[DeviceAiSelectorWire]) -> Result<String, DeviceAiHostErrorCode> {
    if resolved.is_empty() || resolved.len() > 200 {
        return Err(host_err(DeviceAiHostErrorCode::InvalidArgument));
    }
    let mut sorted = resolved.to_vec();
    sorted.sort_by(by_member_key);
    let mut seen = std::collections::BTreeSet::new();
    for item in &sorted {
        assert_device_ai_selector(item)?;
        if !seen.insert(item.member_key.as_str()) {
            return Err(host_err(DeviceAiHostErrorCode::InvalidArgument));
        }
    }
    let items = sorted
        .iter()
        .map(selector_ast)
        .collect::<Result<Vec<_>, _>>()?;
    device_ai_digest(&array_node(items), Some(DEVICE_AI_SELECTION_NAMESPACE))
        .map_err(|_| host_err(DeviceAiHostErrorCode::InvalidArgument))
}

// ---------------------------------------------------------------------------
// device_context_fingerprint (spec section 3). The SERVER value is
// authoritative; this helper exists so a decoder can independently verify it
// once the inputs are exposed.
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct DeviceAiReceiptSourceInput {
    pub selector: DeviceAiSelectorWire,
    pub selection_reason: String,
    /// Receipt source canonical AST; archived numbers must enter as lexemes.
    pub source: DeviceAiValue,
}

#[derive(Debug, Clone)]
pub struct DeviceAiContextIdentityInput {
    pub package_id: String,
    pub package_schema: String,
    pub package_sha256: String,
    pub projection_mode: String,
    pub projection_sha256: String,
    pub selection_sha256: String,
    pub receipt_sources: Vec<DeviceAiReceiptSourceInput>,
    pub device_citations: Vec<DeviceAiValue>,
    pub domain_boundaries: Vec<DeviceAiValue>,
}

pub fn device_context_fingerprint(input: &DeviceAiContextIdentityInput) -> Result<String, DeviceAiHostErrorCode> {
    let invalid = || host_err(DeviceAiHostErrorCode::InvalidArgument);
    if !is_hash64(&input.package_sha256)
        || !is_hash64(&input.projection_sha256)
        || !is_hash64(&input.selection_sha256)
    {
        return Err(invalid());
    }
    // Spec section 3: sort by the node's canonical bytes, but keep the ORIGINAL
    // AST nodes (a serde round-trip would destroy number lexemes).
    let canonical_bytes_order = |nodes: &[DeviceAiValue]| -> Result<Vec<DeviceAiValue>, DeviceAiHostErrorCode> {
        let mut keyed: Vec<(String, &DeviceAiValue)> = Vec::with_capacity(nodes.len());
        for node in nodes {
            let text = canonical_device_ai_json(node).map_err(|_| invalid())?;
            keyed.push((text, node));
        }
        keyed.sort_by(|a, b| a.0.cmp(&b.0));
        Ok(keyed.into_iter().map(|(_, node)| node.clone()).collect())
    };
    let mut receipt_sources = input.receipt_sources.clone();
    receipt_sources.sort_by(|a, b| by_member_key(&a.selector, &b.selector));
    let receipt_items = receipt_sources
        .iter()
        .map(|item| {
            Ok(object_node(vec![
                ("selection_reason", text_node(&item.selection_reason)),
                ("selector", selector_ast(&item.selector)?),
                ("source", item.source.clone()),
            ]))
        })
        .collect::<Result<Vec<_>, DeviceAiHostErrorCode>>()?;
    let ast = object_node(vec![
        (
            "device_citations",
            array_node(canonical_bytes_order(&input.device_citations)?),
        ),
        (
            "domain_boundaries",
            array_node(canonical_bytes_order(&input.domain_boundaries)?),
        ),
        ("numeric_encoding", text_node(DEVICE_AI_NUMBER_TOKEN_SCHEMA)),
        ("package_id", text_node(&input.package_id)),
        ("package_schema", text_node(&input.package_schema)),
        ("package_sha256", text_node(&input.package_sha256)),
        ("projection_mode", text_node(&input.projection_mode)),
        ("projection_sha256", text_node(&input.projection_sha256)),
        ("receipt_sources", array_node(receipt_items)),
        ("schema", text_node("device-ai-context@1")),
        ("selection_sha256", text_node(&input.selection_sha256)),
    ]);
    device_ai_digest(&ast, Some(DEVICE_AI_CONTEXT_NAMESPACE))
        .map_err(|_| host_err(DeviceAiHostErrorCode::InvalidArgument))
}

// ---------------------------------------------------------------------------
// local_preview_fingerprint (spec section 4): frozen intent + origin +
// selection closure + projection digest. `state` and the nullable
// `projection_sha256` stay in the input: blocked and ready are different
// authorization objects and must never share a fingerprint.
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DeviceAiOriginBindingWire {
    pub expected_profile_id: String,
    pub expected_owner_epoch: u64,
    pub slot_id: String,
    pub expected_generation: u64,
    pub package_id: String,
    pub expected_sha256: String,
    pub expected_byte_count: u64,
    pub owner_scope_id: String,
    pub package_schema: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeviceAiPreviewState {
    Ready,
    Blocked,
}

impl DeviceAiPreviewState {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Ready => "ready",
            Self::Blocked => "blocked",
        }
    }
}

pub struct DeviceAiLocalPreviewInput<'a> {
    pub question_sha256_value: &'a str,
    pub include_context_ids: &'a [String],
    pub projection_mode: &'a str,
    pub query_context: Option<&'a DeviceAiValue>,
    pub origin: &'a DeviceAiOriginBindingWire,
    /// Requested selectors, REQUEST ORDER preserved (order is user input).
    pub selected: &'a [DeviceAiSelectorWire],
    /// Resolved closure, member_key ascending (same array as selection_sha256).
    pub resolved_closure: &'a [DeviceAiSelectorWire],
    pub state: DeviceAiPreviewState,
    pub projection_sha256_value: Option<&'a str>,
}

fn assert_origin(origin: &DeviceAiOriginBindingWire) -> Result<(), DeviceAiHostErrorCode> {
    let invalid = || host_err(DeviceAiHostErrorCode::InvalidArgument);
    if !is_hash64(&origin.expected_sha256)
        || !is_hash64(&origin.owner_scope_id)
        || !is_safe_positive_int(origin.expected_byte_count)
        || !is_safe_positive_int(origin.expected_owner_epoch)
        || !is_safe_positive_int(origin.expected_generation)
        || !is_plain_string(&origin.package_id, 64)
        || !is_plain_string(&origin.slot_id, 64)
        || !is_plain_string(&origin.expected_profile_id, 64)
        || !is_package_schema(&origin.package_schema)
    {
        return Err(invalid());
    }
    Ok(())
}

pub fn local_preview_fingerprint(input: &DeviceAiLocalPreviewInput<'_>) -> Result<String, DeviceAiHostErrorCode> {
    let invalid = || host_err(DeviceAiHostErrorCode::InvalidArgument);
    if !is_hash64(input.question_sha256_value) {
        return Err(invalid());
    }
    // M4 (decoder-spec section 3): include_context_ids must stay EMPTY until
    // the frozen wire opens the archive-id intent channel; a non-empty list
    // fails closed before entering the fingerprint AST.
    if !input.include_context_ids.is_empty() {
        return Err(invalid());
    }
    if input.state == DeviceAiPreviewState::Blocked && input.projection_sha256_value.is_some() {
        return Err(invalid());
    }
    if input.state == DeviceAiPreviewState::Ready
        && input
            .projection_sha256_value
            .is_some_and(|value| !is_hash64(value))
    {
        return Err(invalid());
    }
    if input.selected.is_empty() {
        return Err(invalid());
    }
    let origin = input.origin;
    assert_origin(origin)?;
    let mut closure = input.resolved_closure.to_vec();
    closure.sort_by(by_member_key);
    let closure_items = closure
        .iter()
        .map(selector_ast)
        .collect::<Result<Vec<_>, _>>()?;
    let selected_items = input
        .selected
        .iter()
        .map(selector_ast)
        .collect::<Result<Vec<_>, _>>()?;
    let include_ids = input
        .include_context_ids
        .iter()
        .map(|id| text_node(id))
        .collect::<Vec<_>>();
    let ast = object_node(vec![
        (
            "intent",
            object_node(vec![
                ("include_context_ids", array_node(include_ids)),
                ("policy_version", text_node(DEVICE_AI_PROJECTION_POLICY_VERSION)),
                ("purpose", text_node("device_history_analysis")),
                ("question_sha256", text_node(input.question_sha256_value)),
            ]),
        ),
        (
            "origin",
            object_node(vec![
                ("expected_byte_count", meta_int_node(origin.expected_byte_count as i64)?),
                ("expected_generation", meta_int_node(origin.expected_generation as i64)?),
                ("expected_owner_epoch", meta_int_node(origin.expected_owner_epoch as i64)?),
                ("expected_profile_id", text_node(&origin.expected_profile_id)),
                ("expected_sha256", text_node(&origin.expected_sha256)),
                ("owner_scope_id", text_node(&origin.owner_scope_id)),
                ("package_id", text_node(&origin.package_id)),
                ("package_schema", text_node(&origin.package_schema)),
                ("slot_id", text_node(&origin.slot_id)),
            ]),
        ),
        ("projection_mode", text_node(input.projection_mode)),
        (
            "projection_sha256",
            input
                .projection_sha256_value
                .map(text_node)
                .unwrap_or(DeviceAiValue::Null),
        ),
        (
            "query_context",
            input
                .query_context
                .cloned()
                .unwrap_or(DeviceAiValue::Null),
        ),
        ("resolved_closure", array_node(closure_items)),
        ("selected", array_node(selected_items)),
        ("state", text_node(input.state.as_str())),
    ]);
    device_ai_digest(&ast, Some(DEVICE_AI_LOCAL_PREVIEW_NAMESPACE))
        .map_err(|_| host_err(DeviceAiHostErrorCode::InvalidArgument))
}

// ---------------------------------------------------------------------------
// compute_local_preview — local recomputation from the ORIGINAL package bytes,
// for showing "the fingerprints about to leave this device" BEFORE any export
// consent. Server-independent; makes no attestation claim (B01).
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeviceAiPreviewRequest {
    pub question: String,
    pub selectors: Vec<DeviceAiSelectorWire>,
    pub origin: DeviceAiOriginBindingWire,
    #[serde(default)]
    pub include_context_ids: Vec<String>,
    /// None -> "single_observation".
    #[serde(default)]
    pub projection_mode: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct DeviceAiLocalPreviewSummary {
    pub question_sha256: String,
    pub selection_sha256: String,
    pub local_preview_fingerprint: String,
    pub package_sha256: String,
    pub package_byte_count: u64,
    pub package_schema: String,
    /// Member keys located in the original envelope for each requested selector.
    pub located_member_keys: Vec<String>,
    /// Projection digest is NOT recomputed here: fingerprint-spec section 1
    /// requires a full parser+canonical+closure re-implementation with aligned
    /// vectors before any equivalence claim. The preview fingerprint is
    /// computed with state="ready" and projection_sha256=null.
    pub projection_binding: &'static str,
    pub notices: Vec<&'static str>,
}

fn ast_equals(a: &DeviceAiValue, b: &DeviceAiValue) -> bool {
    match (canonical_device_ai_json(a), canonical_device_ai_json(b)) {
        (Ok(left), Ok(right)) => left == right,
        _ => false,
    }
}

fn object_field<'a>(node: &'a DeviceAiValue, key: &str) -> Option<&'a DeviceAiValue> {
    match node {
        DeviceAiValue::Object(map) => map.get(&DeviceAiText::new(key)),
        _ => None,
    }
}

fn field_str<'a>(node: &'a DeviceAiValue, key: &str) -> Option<&'a str> {
    object_field(node, key).and_then(|value| match value {
        DeviceAiValue::Text(text) => text.as_str(),
        _ => None,
    })
}

pub fn compute_local_preview(
    package_bytes: &[u8],
    request: &DeviceAiPreviewRequest,
) -> Result<DeviceAiLocalPreviewSummary, DeviceAiHostErrorCode> {
    let invalid = || host_err(DeviceAiHostErrorCode::InvalidArgument);
    let mismatch = || host_err(DeviceAiHostErrorCode::PackageMismatch);
    let unsupported = || host_err(DeviceAiHostErrorCode::PreviewUnsupported);
    if package_bytes.is_empty() {
        return Err(invalid());
    }
    let origin = &request.origin;
    if !is_hash64(&origin.expected_sha256) || !is_safe_positive_int(origin.expected_byte_count) {
        return Err(invalid());
    }
    if origin.expected_byte_count != package_bytes.len() as u64 {
        return Err(mismatch());
    }
    match request.projection_mode.as_deref() {
        None | Some("single_observation") => {}
        // frozen_decision_closure needs the full closure re-computation (phase B).
        Some(_) => return Err(unsupported()),
    }
    if request.selectors.len() != 1 {
        // Phase A: exactly one tire selector (proposal complete_branch_contract).
        return Err(unsupported());
    }
    for selector in &request.selectors {
        assert_device_ai_selector(selector)?;
        // Four-domain selectors are valid on the prepare wire, but the Rust
        // local preview re-computation is still Phase A tire-only; the TS SDK
        // carries the full projection port (20/20 vector parity).
        if selector.kind != "tire" {
            return Err(unsupported());
        }
    }
    let package_sha = sha256_hex(package_bytes);
    if package_sha != origin.expected_sha256 {
        return Err(mismatch());
    }

    let envelope = parse_device_ai_package(package_bytes)
        .map_err(|_| host_err(DeviceAiHostErrorCode::InvalidArgument))?;
    let schema = field_str(&envelope, "schema").unwrap_or_default();
    if !is_package_schema(schema) {
        return Err(invalid());
    }
    if field_str(&envelope, "package_id") != Some(origin.package_id.as_str())
        || field_str(&envelope, "owner_scope_id") != Some(origin.owner_scope_id.as_str())
    {
        return Err(mismatch());
    }
    let members = match object_field(&envelope, "members") {
        Some(DeviceAiValue::Array(items)) => items,
        _ => return Err(invalid()),
    };

    let mut located = Vec::new();
    for selector in &request.selectors {
        let expected = selector_ast(selector)?;
        let found = members.iter().any(|member| {
            let entry_reference = match object_field(member, "reference") {
                Some(reference) => reference,
                None => return false,
            };
            field_str(member, "member_key") == Some(selector.member_key.as_str())
                && ast_equals(entry_reference, object_field(&expected, "reference").unwrap_or(&DeviceAiValue::Null))
        });
        if !found {
            return Err(mismatch());
        }
        located.push(selector.member_key.clone());
    }

    let normalized = normalize_question(&request.question)?;
    let question_hash = question_sha256(normalized);
    // single_observation: resolved closure == requested selection (no
    // dependency expansion in phase A); selection_sha256 therefore binds
    // exactly what the server recomputes for the same selectors.
    let selection_hash = selection_sha256(&request.selectors)?;
    let preview_fingerprint = local_preview_fingerprint(&DeviceAiLocalPreviewInput {
        question_sha256_value: &question_hash,
        include_context_ids: &request.include_context_ids,
        projection_mode: "single_observation",
        query_context: None,
        origin,
        selected: &request.selectors,
        resolved_closure: &request.selectors,
        state: DeviceAiPreviewState::Ready,
        projection_sha256_value: None,
    })?;
    Ok(DeviceAiLocalPreviewSummary {
        question_sha256: question_hash,
        selection_sha256: selection_hash,
        local_preview_fingerprint: preview_fingerprint,
        package_sha256: package_sha,
        package_byte_count: package_bytes.len() as u64,
        package_schema: schema.to_owned(),
        located_member_keys: located,
        projection_binding: "not_recomputed",
        notices: vec![
            "本预览为本地重算：question_sha256 / selection_sha256 / local_preview_fingerprint 均不依赖服务端。",
            "projection_sha256 未在本机重算（需投影核完整复刻并通过向量对拍）；服务端 prepare 会以 expected_projection_sha256 复核为准。",
            "device_context_fingerprint 由服务端从自有投影权威计算（fingerprint-spec 第 3 节），Host 只读取/转发。",
        ],
    })
}

// ---------------------------------------------------------------------------
// Encrypted append-only journal with five fences.
//
// Storage layout (one opaque byte blob, Host-owned store):
//   { "schema": "device-ai-journal@1", "owner": <str>, "generation": <int>,
//     "iv_hex": <24 hex chars>, "ciphertext_base64": <str> }
// ciphertext = AES-GCM-256(canonical({entries:[...]}), aad = compact_json(
//   ["device-ai-journal@1", owner]) ). The AAD pins the owner, so a blob
//   copied across owners fails to decrypt outright (cryptographic owner fence
//   below the explicit one). Wire bytes (header field order, AAD bytes,
//   canonical plaintext) are identical to the TS SDK journal, and the key is
//   Host-injected: this module never derives or persists a key itself.
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case", tag = "type", deny_unknown_fields)]
pub enum DeviceAiJournalEvent {
    PreviewShown {
        intent_id: String,
        local_preview_fingerprint: String,
        question_sha256: String,
        package_sha256: String,
    },
    DecisionMade {
        intent_id: String,
        decision: DeviceAiJournalDecision,
        local_preview_fingerprint: String,
    },
    PrepareCreated {
        intent_id: String,
        prepare_id: String,
        idempotency_key: String,
        projection_sha256: String,
        device_context_fingerprint: String,
    },
    ClaimSubmitted {
        intent_id: String,
        prepare_id: String,
        analysis_key: String,
        question_sha256: String,
    },
    OutcomeObserved {
        intent_id: String,
        analysis_key: String,
        request_id: String,
        state: String,
    },
    FailureObserved {
        intent_id: Option<String>,
        stage: String,
        code: String,
    },
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum DeviceAiJournalDecision {
    Allow,
    Deny,
}

// ---------------------------------------------------------------------------
// Closed event validation for the IPC append entry point. The TS SDK journal
// accepts any structurally shaped event (TS is structural); the IPC boundary
// here only carries closed codes, so the six panel-written event shapes get
// explicit field validation before anything is sealed into the ledger. The
// wire itself is already closed by the serde tag/deny_unknown_fields enums
// above; this adds the value-level bounds (hash64 fingerprints, canonical
// UUIDs where recovery lookup depends on them, closed stage/state sets).
// ---------------------------------------------------------------------------

/// failure_observed stages exactly as the panels write them
/// (apps/web/components/device-ai-values.ts deviceAiFailureLabels).
pub const DEVICE_AI_JOURNAL_FAILURE_STAGES: [&str; 8] = [
    "local_preview",
    "decision",
    "prepare",
    "submit",
    "outcome",
    "recovery",
    "provider",
    "source",
];

/// outcome_observed states, verbatim from the AI stream execution Literal
/// (`is_ai_stream_execution` below; server ai-streams@1).
pub const DEVICE_AI_JOURNAL_OUTCOME_STATES: [&str; 5] = [
    "accepted",
    "running",
    "completed",
    "failed",
    "outcome_unknown",
];

/// Closed validation of one journal event as it crosses the IPC boundary.
/// Invalid input never reaches the encrypted ledger.
pub fn assert_device_ai_journal_event(
    event: &DeviceAiJournalEvent,
) -> Result<(), DeviceAiHostErrorCode> {
    let invalid = || host_err(DeviceAiHostErrorCode::InvalidArgument);
    match event {
        DeviceAiJournalEvent::PreviewShown {
            intent_id,
            local_preview_fingerprint,
            question_sha256,
            package_sha256,
        } => {
            if !is_plain_string(intent_id, 64)
                || !is_hash64(local_preview_fingerprint)
                || !is_hash64(question_sha256)
                || !is_hash64(package_sha256)
            {
                return Err(invalid());
            }
        }
        DeviceAiJournalEvent::DecisionMade {
            intent_id,
            decision: _,
            local_preview_fingerprint,
        } => {
            if !is_plain_string(intent_id, 64) || !is_hash64(local_preview_fingerprint) {
                return Err(invalid());
            }
        }
        DeviceAiJournalEvent::PrepareCreated {
            intent_id,
            prepare_id,
            idempotency_key,
            projection_sha256,
            device_context_fingerprint,
        } => {
            if !is_plain_string(intent_id, 64)
                || !is_plain_string(prepare_id, 64)
                // Recovery lookup and server replay both key on the UUID form.
                || canonical_device_ai_uuid(idempotency_key).is_err()
                || !is_hash64(projection_sha256)
                || !is_hash64(device_context_fingerprint)
            {
                return Err(invalid());
            }
        }
        DeviceAiJournalEvent::ClaimSubmitted {
            intent_id,
            prepare_id,
            analysis_key,
            question_sha256,
        } => {
            if !is_plain_string(intent_id, 64)
                || !is_plain_string(prepare_id, 64)
                // resolve_unknown_outcome canonicalizes this key for lookup;
                // a non-UUID key could never be recovered, so refuse it here.
                || canonical_device_ai_uuid(analysis_key).is_err()
                || !is_hash64(question_sha256)
            {
                return Err(invalid());
            }
        }
        DeviceAiJournalEvent::OutcomeObserved {
            intent_id,
            analysis_key,
            request_id,
            state,
        } => {
            // The panels write `intent_id: intentId ?? ""` (empty is valid).
            if !intent_id.is_empty() && !is_plain_string(intent_id, 64) {
                return Err(invalid());
            }
            if canonical_device_ai_uuid(analysis_key).is_err()
                || !is_plain_string(request_id, 80)
                || !DEVICE_AI_JOURNAL_OUTCOME_STATES.contains(&state.as_str())
            {
                return Err(invalid());
            }
        }
        DeviceAiJournalEvent::FailureObserved {
            intent_id,
            stage,
            code,
        } => {
            if intent_id.as_deref().is_some_and(|id| !is_plain_string(id, 64))
                || !DEVICE_AI_JOURNAL_FAILURE_STAGES.contains(&stage.as_str())
                // Passthrough failure codes stay bounded (same 100-char bound
                // as extract_api_error's closed detail.code check).
                || !is_plain_string(code, 100)
            {
                return Err(invalid());
            }
        }
    }
    Ok(())
}

pub trait DeviceAiJournalStore: Send + Sync {
    /// Load the whole encrypted blob, or `None` when the journal does not exist.
    fn load(&self) -> NativeResult<Option<Vec<u8>>>;
    /// Persist the whole encrypted blob atomically (Host store's own CAS).
    fn save(&self, blob: &[u8]) -> NativeResult<()>;
}

/// Journal operations fail either through a store/OS failure (closed native
/// code) or through one of the five fence codes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeviceAiJournalError {
    Store(&'static str),
    Fence(DeviceAiHostErrorCode),
}

pub struct DeviceAiJournalOptions {
    /// Fence 1: profile/device ownership identity (free-form Host identifier).
    pub owner: String,
    /// Fence 2: journal generation; a rebuild bumps it and voids older blobs.
    pub generation: u64,
    /// Fence 5: the current session; entries from other sessions never replay.
    pub session_id: String,
    /// AES-GCM-256 key, injected by the Host (never derived or stored here).
    pub key: Zeroizing<[u8; 32]>,
    pub store: Arc<dyn DeviceAiJournalStore>,
    /// Fence 4: injected monotonic clock (nanoseconds; must be >= 1).
    pub monotonic_now: Box<dyn Fn() -> u64 + Send + Sync>,
    /// Wall clock for audit display only; never used in fence decisions.
    pub wall_now: Option<Box<dyn Fn() -> String + Send + Sync>>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct DeviceAiJournalFenceViolation {
    pub code: &'static str,
    pub sequence: Option<u64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct DeviceAiJournalCrossSessionEntry {
    pub sequence: u64,
    pub session_id: String,
}

/// Full five-fence report (audit view; never fails on fence violations).
#[derive(Debug, Clone, Serialize)]
pub struct DeviceAiJournalVerification {
    pub ok: bool,
    pub length: usize,
    /// Fence violations over owner/generation/SHA chain/clock (never session).
    pub violations: Vec<DeviceAiJournalFenceViolation>,
    /// Entries whose session differs from the journal's current session.
    pub cross_session_entries: Vec<DeviceAiJournalCrossSessionEntry>,
}

#[derive(Serialize, Deserialize)]
struct JournalBlobWire {
    schema: String,
    owner: String,
    generation: u64,
    iv_hex: String,
    ciphertext_base64: String,
}

pub const GENESIS_HASH: &str = "0000000000000000000000000000000000000000000000000000000000000000";

fn journal_aad(owner: &str) -> Vec<u8> {
    serde_json::to_vec(&json!([DEVICE_AI_JOURNAL_SCHEMA, owner]))
        .expect("serializing two JSON strings cannot fail")
}

fn v_str<'a>(value: &'a Value, key: &str) -> Option<&'a str> {
    value.get(key).and_then(Value::as_str)
}

fn v_u64(value: &Value, key: &str) -> Option<u64> {
    value.get(key).and_then(Value::as_u64)
}

/// Entry hash input: the entry WITHOUT entry_sha256, canonicalized over the
/// nine hash-input fields (TS `entryHashAst`); built from the raw stored JSON
/// so tampered shapes fail closed.
fn entry_hash_input_ast(entry: &Value) -> Option<DeviceAiValue> {
    const KEYS: [&str; 9] = [
        "clock",
        "event",
        "generation",
        "owner",
        "prev_sha256",
        "schema",
        "sequence",
        "session_id",
        "wall_clock",
    ];
    let mut out = BTreeMap::new();
    for key in KEYS {
        let value = entry.get(key)?;
        out.insert(DeviceAiText::new(key), json_to_ast(value)?);
    }
    Some(DeviceAiValue::Object(out))
}

fn entry_sha256(entry: &Value) -> Option<String> {
    let ast = entry_hash_input_ast(entry)?;
    let canonical = canonical_device_ai_json(&ast).ok()?;
    Some(sha256_hex(canonical.as_bytes()))
}

pub struct DeviceAiJournal {
    options: DeviceAiJournalOptions,
}

impl DeviceAiJournal {
    pub fn new(options: DeviceAiJournalOptions) -> Result<Self, DeviceAiHostErrorCode> {
        let invalid = || host_err(DeviceAiHostErrorCode::InvalidArgument);
        if !is_plain_string(&options.owner, 128)
            || !is_safe_positive_int(options.generation)
            || !is_plain_string(&options.session_id, 128)
        {
            return Err(invalid());
        }
        Ok(Self { options })
    }

    /// Fence context exposure (read-only) for recovery flows and self-tests.
    pub fn owner(&self) -> &str {
        &self.options.owner
    }
    pub fn generation(&self) -> u64 {
        self.options.generation
    }
    pub fn session_id(&self) -> &str {
        &self.options.session_id
    }

    fn cipher(&self) -> Aes256Gcm {
        Aes256Gcm::new_from_slice(&*self.options.key).expect("journal key is 32 bytes")
    }

    fn seal(&self, entries: &[Value]) -> Result<Vec<u8>, DeviceAiJournalError> {
        let store_failure =
            || DeviceAiJournalError::Store("DEVICE_AI_JOURNAL_KEY_UNAVAILABLE");
        let mut nonce = [0_u8; 12];
        OsRng
            .try_fill_bytes(&mut nonce)
            .map_err(|_| store_failure())?;
        let entry_asts = entries
            .iter()
            .map(json_to_ast)
            .collect::<Option<Vec<_>>>()
            .ok_or(DeviceAiJournalError::Fence(
                DeviceAiHostErrorCode::JournalCorrupt,
            ))?;
        let plaintext_ast = object_node(vec![(
            "entries",
            array_node(entry_asts),
        )]);
        let plaintext = canonical_device_ai_json(&plaintext_ast)
            .map_err(|_| DeviceAiJournalError::Fence(DeviceAiHostErrorCode::JournalCorrupt))?
            .into_bytes();
        let ciphertext = self
            .cipher()
            .encrypt(
                Nonce::from_slice(&nonce),
                Payload {
                    msg: &plaintext,
                    aad: &journal_aad(&self.options.owner),
                },
            )
            .map_err(|_| DeviceAiJournalError::Store("DEVICE_AI_JOURNAL_SEAL_FAILED"))?;
        let blob = JournalBlobWire {
            schema: DEVICE_AI_JOURNAL_SCHEMA.to_owned(),
            owner: self.options.owner.clone(),
            generation: self.options.generation,
            iv_hex: nonce.iter().map(|byte| format!("{byte:02x}")).collect(),
            ciphertext_base64: STANDARD.encode(&ciphertext),
        };
        serde_json::to_vec(&blob).map_err(|_| DeviceAiJournalError::Store("DEVICE_AI_JOURNAL_SEAL_FAILED"))
    }

    fn unseal(&self, blob: &[u8]) -> Result<Vec<Value>, DeviceAiJournalError> {
        let corrupt = || DeviceAiJournalError::Fence(DeviceAiHostErrorCode::JournalCorrupt);
        let wire: JournalBlobWire = serde_json::from_slice(blob).map_err(|_| corrupt())?;
        if wire.schema != DEVICE_AI_JOURNAL_SCHEMA
            || !is_plain_string(&wire.owner, 128)
            || !is_safe_positive_int(wire.generation)
            || wire.iv_hex.len() != 24
            || !wire.iv_hex.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
            || wire.ciphertext_base64.is_empty()
        {
            return Err(corrupt());
        }
        // Fence 1 (owner) — explicit header check; the AAD below is the
        // cryptographic layer of the same fence: a blob saved under another
        // owner simply fails to decrypt here.
        if wire.owner != self.options.owner {
            return Err(DeviceAiJournalError::Fence(
                DeviceAiHostErrorCode::JournalOwnerMismatch,
            ));
        }
        // Fence 2 (generation) — a rebuilt journal (generation+1) voids old blobs.
        if wire.generation != self.options.generation {
            return Err(DeviceAiJournalError::Fence(
                DeviceAiHostErrorCode::JournalGenerationMismatch,
            ));
        }
        let ciphertext = STANDARD
            .decode(&wire.ciphertext_base64)
            .map_err(|_| corrupt())?;
        let mut nonce = [0_u8; 12];
        for (index, pair) in wire.iv_hex.as_bytes().chunks(2).enumerate() {
            let high = (pair[0] as char).to_digit(16).unwrap_or(0) as u8;
            let low = (pair[1] as char).to_digit(16).unwrap_or(0) as u8;
            nonce[index] = (high << 4) | low;
        }
        let plaintext = self
            .cipher()
            .decrypt(
                Nonce::from_slice(&nonce),
                Payload {
                    msg: &ciphertext,
                    aad: &journal_aad(&self.options.owner),
                },
            )
            .map_err(|_| corrupt())?;
        let parsed: Value = serde_json::from_slice(&plaintext).map_err(|_| corrupt())?;
        match parsed.get("entries") {
            Some(Value::Array(entries)) => Ok(entries.clone()),
            _ => Err(corrupt()),
        }
    }

    /// Structural verification (fences 1/2/4/5 + chain shape of fence 3) over
    /// a decrypted entry list; the per-entry hash re-computation lives in
    /// `verify_integrity_of` so every entry is hashed exactly once.
    fn structure_check(&self, entries: &[Value]) -> DeviceAiJournalVerification {
        let mut violations = Vec::new();
        let mut cross_session = Vec::new();
        let mut previous_hash = GENESIS_HASH;
        let mut previous_clock: Option<u64> = None; // None == TS Number.NEGATIVE_INFINITY
        for (index, entry) in entries.iter().enumerate() {
            let sequence = index as u64 + 1;
            let shape_ok = entry.is_object()
                && v_str(entry, "schema") == Some(DEVICE_AI_JOURNAL_ENTRY_SCHEMA)
                && v_u64(entry, "sequence").is_some()
                && v_str(entry, "entry_sha256").is_some_and(is_hash64)
                && v_str(entry, "prev_sha256").is_some_and(is_hash64);
            if !shape_ok {
                violations.push(DeviceAiJournalFenceViolation {
                    code: DeviceAiHostErrorCode::JournalCorrupt.as_str(),
                    sequence: Some(sequence),
                });
                continue;
            }
            let broken = |violations: &mut Vec<DeviceAiJournalFenceViolation>| {
                violations.push(DeviceAiJournalFenceViolation {
                    code: DeviceAiHostErrorCode::JournalChainBroken.as_str(),
                    sequence: Some(sequence),
                });
            };
            // Fence 3 (SHA): chain continuity + sequence numbering (hash
            // re-computation happens in verify_integrity_of).
            if v_u64(entry, "sequence") != Some(sequence) {
                broken(&mut violations);
            }
            if v_str(entry, "prev_sha256") != Some(previous_hash) {
                broken(&mut violations);
            }
            // Fence 1/2 apply per entry as well (defense in depth under the
            // header).
            if v_str(entry, "owner") != Some(self.options.owner.as_str()) {
                violations.push(DeviceAiJournalFenceViolation {
                    code: DeviceAiHostErrorCode::JournalOwnerMismatch.as_str(),
                    sequence: Some(sequence),
                });
            }
            if v_u64(entry, "generation") != Some(self.options.generation) {
                violations.push(DeviceAiJournalFenceViolation {
                    code: DeviceAiHostErrorCode::JournalGenerationMismatch.as_str(),
                    sequence: Some(sequence),
                });
            }
            // Fence 4 (clock): strictly increasing monotonic timestamps, no
            // replay of an older entry after a newer one, no clock rollback.
            // A missing/non-integer clock counts as non-finite, like the TS
            // Number.isFinite gate.
            let clock = v_u64(entry, "clock");
            let clock_ok = match (clock, previous_clock) {
                (Some(current), Some(previous)) => current > previous,
                (Some(_), None) => true,
                (None, _) => false,
            };
            if !clock_ok {
                violations.push(DeviceAiJournalFenceViolation {
                    code: DeviceAiHostErrorCode::JournalClockRegression.as_str(),
                    sequence: Some(sequence),
                });
            }
            // Fence 5 (session): recorded, but never fails readAll — recovery
            // reads the ledger; cross-session authorization is blocked at
            // consumption.
            if v_str(entry, "session_id") != Some(self.options.session_id.as_str()) {
                cross_session.push(DeviceAiJournalCrossSessionEntry {
                    sequence,
                    session_id: v_str(entry, "session_id").unwrap_or_default().to_owned(),
                });
            }
            previous_hash = v_str(entry, "entry_sha256").unwrap_or_default();
            previous_clock = clock.or(previous_clock);
        }
        let ok = violations.is_empty();
        DeviceAiJournalVerification {
            ok,
            length: entries.len(),
            violations,
            cross_session_entries: cross_session,
        }
    }

    pub fn append(&self, event: DeviceAiJournalEvent) -> Result<Value, DeviceAiJournalError> {
        let blob = self.options.store.load().map_err(DeviceAiJournalError::Store)?;
        let entries = match blob {
            Some(blob) => self.unseal(&blob)?,
            None => Vec::new(),
        };
        let structural = self.structure_check(&entries);
        if !structural.ok {
            return Err(DeviceAiJournalError::Fence(
                structural.violations[0]
                    .code
                    .parse_fence()
                    .unwrap_or(DeviceAiHostErrorCode::JournalCorrupt),
            ));
        }
        let clock = (self.options.monotonic_now)();
        if !is_safe_positive_int(clock) {
            return Err(DeviceAiJournalError::Fence(
                DeviceAiHostErrorCode::InvalidArgument,
            ));
        }
        // Fence 4 at write time: the new entry must strictly advance the clock.
        if let Some(tail_clock) = entries.last().and_then(|tail| v_u64(tail, "clock")) {
            if clock <= tail_clock {
                return Err(DeviceAiJournalError::Fence(
                    DeviceAiHostErrorCode::JournalClockRegression,
                ));
            }
        }
        let wall_clock = match &self.options.wall_now {
            Some(wall_now) => wall_now(),
            None => chrono_wall_now(),
        };
        let draft = json!({
            "schema": DEVICE_AI_JOURNAL_ENTRY_SCHEMA,
            "sequence": entries.len() as u64 + 1,
            "owner": self.options.owner,          // fence 1 stamped at write time
            "generation": self.options.generation, // fence 2 stamped at write time
            "session_id": self.options.session_id, // fence 5 stamped at write time
            "clock": clock,
            "wall_clock": wall_clock,
            "event": serde_json::to_value(&event)
                .map_err(|_| DeviceAiJournalError::Store("DEVICE_AI_JOURNAL_SEAL_FAILED"))?,
            "prev_sha256": entries
                .last()
                .and_then(|tail| v_str(tail, "entry_sha256"))
                .unwrap_or(GENESIS_HASH),
        });
        let digest = entry_sha256(&draft).ok_or(DeviceAiJournalError::Fence(
            DeviceAiHostErrorCode::InvalidArgument,
        ))?;
        let mut entry = draft;
        entry
            .as_object_mut()
            .expect("draft is an object")
            .insert("entry_sha256".to_owned(), Value::String(digest));
        let mut all = entries;
        all.push(entry.clone());
        let blob = self.seal(&all)?;
        self.options.store.save(&blob).map_err(DeviceAiJournalError::Store)?;
        Ok(entry)
    }

    /// Decrypt + full verification. Fence violations throw their closed code.
    pub fn read_all(&self) -> Result<Vec<Value>, DeviceAiJournalError> {
        let blob = self
            .options
            .store
            .load()
            .map_err(DeviceAiJournalError::Store)?;
        let blob = match blob {
            Some(blob) => blob,
            None => return Ok(Vec::new()),
        };
        let entries = self.unseal(&blob)?;
        let verification = self.verify_integrity_of(&entries);
        if !verification.ok {
            return Err(DeviceAiJournalError::Fence(
                verification.violations[0]
                    .code
                    .parse_fence()
                    .unwrap_or(DeviceAiHostErrorCode::JournalCorrupt),
            ));
        }
        Ok(entries)
    }

    /// Full five-fence report; never fails on fence violations (audit view).
    pub fn verify_integrity(&self) -> Result<DeviceAiJournalVerification, DeviceAiJournalError> {
        let blob = self
            .options
            .store
            .load()
            .map_err(DeviceAiJournalError::Store)?;
        let Some(blob) = blob else {
            return Ok(DeviceAiJournalVerification {
                ok: true,
                length: 0,
                violations: Vec::new(),
                cross_session_entries: Vec::new(),
            });
        };
        match self.unseal(&blob) {
            Ok(entries) => Ok(self.verify_integrity_of(&entries)),
            // owner/generation/corrupt fences surface from unseal itself.
            Err(DeviceAiJournalError::Fence(code)) => Ok(DeviceAiJournalVerification {
                ok: false,
                length: 0,
                violations: vec![DeviceAiJournalFenceViolation {
                    code: code.as_str(),
                    sequence: None,
                }],
                cross_session_entries: Vec::new(),
            }),
            Err(error) => Err(error),
        }
    }

    fn verify_integrity_of(&self, entries: &[Value]) -> DeviceAiJournalVerification {
        let mut verification = self.structure_check(entries);
        // Fence 3 (SHA): full per-entry hash re-computation over the canonical
        // form. Entries whose hash input cannot even be canonicalized count as
        // corrupt (fail-closed; the TS SDK would host-fail on the same input).
        for (index, entry) in entries.iter().enumerate() {
            if !entry.is_object() || !v_str(entry, "entry_sha256").is_some_and(is_hash64) {
                continue;
            }
            match entry_sha256(entry) {
                Some(digest) => {
                    if digest != v_str(entry, "entry_sha256").unwrap_or_default() {
                        verification.violations.push(DeviceAiJournalFenceViolation {
                            code: DeviceAiHostErrorCode::JournalEntryTampered.as_str(),
                            sequence: Some(index as u64 + 1),
                        });
                    }
                }
                None => verification.violations.push(DeviceAiJournalFenceViolation {
                    code: DeviceAiHostErrorCode::JournalCorrupt.as_str(),
                    sequence: Some(index as u64 + 1),
                }),
            }
        }
        verification.ok = verification.violations.is_empty();
        verification
    }

    /// Fence 5 hard gate: every entry must belong to the current session.
    /// Used before consuming any authorization-bearing entry (submit paths);
    /// pure recovery reads use read_all and handle cross-session explicitly.
    pub fn assert_same_session(&self, entries: &[Value]) -> Result<(), DeviceAiJournalError> {
        for entry in entries {
            if v_str(entry, "session_id") != Some(self.options.session_id.as_str()) {
                return Err(DeviceAiJournalError::Fence(
                    DeviceAiHostErrorCode::JournalSessionMismatch,
                ));
            }
        }
        Ok(())
    }
}

fn chrono_wall_now() -> String {
    format!(
        "{}",
        chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.3fZ")
    )
}

trait FenceCode {
    fn parse_fence(&self) -> Option<DeviceAiHostErrorCode>;
}

impl FenceCode for &str {
    fn parse_fence(&self) -> Option<DeviceAiHostErrorCode> {
        Some(match *self {
            "device_ai_host_journal_owner_mismatch" => DeviceAiHostErrorCode::JournalOwnerMismatch,
            "device_ai_host_journal_generation_mismatch" => {
                DeviceAiHostErrorCode::JournalGenerationMismatch
            }
            "device_ai_host_journal_session_mismatch" => DeviceAiHostErrorCode::JournalSessionMismatch,
            "device_ai_host_journal_chain_broken" => DeviceAiHostErrorCode::JournalChainBroken,
            "device_ai_host_journal_entry_tampered" => DeviceAiHostErrorCode::JournalEntryTampered,
            "device_ai_host_journal_clock_regression" => DeviceAiHostErrorCode::JournalClockRegression,
            "device_ai_host_journal_corrupt" => DeviceAiHostErrorCode::JournalCorrupt,
            _ => return None,
        })
    }
}

// ---------------------------------------------------------------------------
// Host client — prepare/lookup/read + stream submit + attempt lookup.
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeviceAiPrepareBody {
    pub package_id: String,
    pub expected_sha256: String,
    pub expected_byte_count: u64,
    pub expected_schema: String,
    pub expected_owner_scope_id: String,
    pub selectors: Vec<DeviceAiSelectorWire>,
    pub projection_mode: String,
    #[serde(default)]
    pub approved_closure: Option<Vec<DeviceAiSelectorWire>>,
    pub expected_projection_sha256: String,
    pub question_sha256: String,
    pub host_receipt_id: String,
    pub intent_id: String,
}

/// Server `DeviceAIPrepareRequest.projection_mode` Literal, verbatim (five
/// values; test_event's complete_event_context stays out — N27 closed set).
pub const DEVICE_AI_PREPARE_PROJECTION_MODES: [&str; 5] = [
    "single_observation",
    "frozen_decision_closure",
    "complete_observation",
    "complete_formal_observation",
    "candidate_page_context",
];

#[derive(Debug, Clone, PartialEq)]
pub struct DeviceAiApiError {
    pub status: u16,
    pub code: Option<String>,
    pub message: Option<String>,
    pub run_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum DeviceAiClientError {
    /// Transport/session failures with the existing closed native codes
    /// (API_TIMEOUT, API_UNAVAILABLE, SESSION_CHANGED, ...).
    Native(&'static str),
    /// Host-side closed validation failures (argument checks, response shape).
    Host(DeviceAiHostErrorCode),
    /// Server rejection passthrough (404/409/422/... with detail.code).
    Api(DeviceAiApiError),
}

impl DeviceAiClientError {
    /// Map onto the IPC error convention: closed `&'static str` codes.
    /// Server HTTP rejections do NOT map here (they carry dynamic passthrough
    /// payloads and are surfaced as a `rejected` result envelope instead).
    pub fn into_ipc_error(self) -> Option<&'static str> {
        match self {
            Self::Native(code) => Some(code),
            Self::Host(code) => Some(code.as_str()),
            Self::Api(_) => None,
        }
    }

    pub fn api_status(&self) -> Option<u16> {
        match self {
            Self::Api(error) => Some(error.status),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeviceAiProviderConsentBody {
    pub expected_pack_fingerprint: String,
    pub expected_device_context_fingerprint: String,
    pub question_sha256: String,
    pub provider: String,
    pub model: String,
    pub expected_provider_policy_fingerprint: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeviceAiSubmissionBody {
    pub prepare_id: String,
    pub host_receipt_id: String,
    pub device_context_fingerprint: String,
    pub provider_consent: DeviceAiProviderConsentBody,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeviceAiStreamSubmission {
    pub pack_id: String,
    /// Raw question text; normalized (trim-once) exactly once before dispatch.
    pub question: String,
    pub prepare_id: String,
    pub host_receipt_id: String,
    pub device_context_fingerprint: String,
    pub provider_consent: DeviceAiProviderConsentBody,
}

#[derive(Debug, Clone, Serialize)]
pub struct DeviceAiEndpointSuccess {
    pub status: u16,
    pub value: Value,
}

fn assert_consent(consent: &DeviceAiProviderConsentBody) -> Result<(), DeviceAiHostErrorCode> {
    let invalid = || host_err(DeviceAiHostErrorCode::InvalidArgument);
    if !is_hash64(&consent.expected_pack_fingerprint)
        || !is_hash64(&consent.expected_device_context_fingerprint)
        || !is_hash64(&consent.question_sha256)
        || !is_hash64(&consent.expected_provider_policy_fingerprint)
        || !is_plain_string(&consent.provider, 32)
        || !is_plain_string(&consent.model, 120)
    {
        return Err(invalid());
    }
    Ok(())
}

pub fn assert_device_ai_prepare_body(body: &DeviceAiPrepareBody) -> Result<(), DeviceAiHostErrorCode> {
    let invalid = || host_err(DeviceAiHostErrorCode::InvalidArgument);
    if !is_plain_string(&body.package_id, 64)
        || !is_hash64(&body.expected_sha256)
        || !is_hash64(&body.expected_owner_scope_id)
        || !is_hash64(&body.expected_projection_sha256)
        || !is_hash64(&body.question_sha256)
        || !is_safe_positive_int(body.expected_byte_count)
        || !is_package_schema(&body.expected_schema)
        || !DEVICE_AI_PREPARE_PROJECTION_MODES.contains(&body.projection_mode.as_str())
    {
        return Err(invalid());
    }
    if body.selectors.is_empty() || body.selectors.len() > 6 {
        return Err(invalid());
    }
    for selector in &body.selectors {
        assert_device_ai_selector(selector)?;
    }
    let mut seen = std::collections::BTreeSet::new();
    if body.selectors.iter().any(|item| !seen.insert(item.member_key.as_str())) {
        return Err(invalid());
    }
    match body.projection_mode.as_str() {
        // frozen_decision_closure: approved_closure is a REQUIRED, exact,
        // 1..SELECTOR_CAPACITY list of valid four-domain selectors with
        // unique member_keys ('必须显式提供 approved_closure（精确相等清单）').
        "frozen_decision_closure" => {
            let Some(closure) = body.approved_closure.as_ref() else {
                return Err(invalid());
            };
            if closure.is_empty() || closure.len() > 6 {
                return Err(invalid());
            }
            let mut closure_seen = std::collections::BTreeSet::new();
            for selector in closure {
                assert_device_ai_selector(selector)?;
                if !closure_seen.insert(selector.member_key.as_str()) {
                    return Err(invalid());
                }
            }
        }
        // Every other mode: approved_closure must be null ('仅
        // frozen_decision_closure 模式允许 approved_closure').
        _ => {
            if body.approved_closure.is_some() {
                return Err(invalid());
            }
        }
    }
    canonical_device_ai_uuid(&body.host_receipt_id)?;
    canonical_device_ai_uuid(&body.intent_id)?;
    Ok(())
}

/// Prepare body as dispatched: exactly the closed server field set, with both
/// UUIDs canonicalized lowercase.
pub fn canonicalize_prepare_body(body: &DeviceAiPrepareBody) -> Result<Value, DeviceAiHostErrorCode> {
    assert_device_ai_prepare_body(body)?;
    let mut wire = serde_json::to_value(body)
        .map_err(|_| host_err(DeviceAiHostErrorCode::InvalidArgument))?;
    let object = wire
        .as_object_mut()
        .ok_or_else(|| host_err(DeviceAiHostErrorCode::InvalidArgument))?;
    object.insert(
        "host_receipt_id".to_owned(),
        Value::String(canonical_device_ai_uuid(&body.host_receipt_id)?),
    );
    object.insert(
        "intent_id".to_owned(),
        Value::String(canonical_device_ai_uuid(&body.intent_id)?),
    );
    Ok(wire)
}

/// AnalysisRequest body for the closed device branch: exactly the four server
/// fields, question normalized (trim-once) exactly once, and the literal
/// `allow_external_processing: true` of the device branch.
pub fn build_analysis_request_body(
    submission: &DeviceAiStreamSubmission,
) -> Result<Value, DeviceAiHostErrorCode> {
    let invalid = || host_err(DeviceAiHostErrorCode::InvalidArgument);
    if !is_plain_string(&submission.pack_id, 64) || !is_plain_string(&submission.prepare_id, 64) {
        return Err(invalid());
    }
    let question = normalize_question(&submission.question)?;
    let consent = &submission.provider_consent;
    assert_consent(consent)?;
    if !is_hash64(&submission.device_context_fingerprint) {
        return Err(invalid());
    }
    let device_submission = json!({
        "prepare_id": submission.prepare_id,
        "host_receipt_id": canonical_device_ai_uuid(&submission.host_receipt_id)?,
        "device_context_fingerprint": submission.device_context_fingerprint,
        "provider_consent": serde_json::to_value(consent)
            .map_err(|_| host_err(DeviceAiHostErrorCode::InvalidArgument))?,
    });
    Ok(json!({
        "pack_id": submission.pack_id,
        "question": question,
        "allow_external_processing": true,
        "device_submission": device_submission,
    }))
}

pub struct DeviceAiHostClient {
    bridge: Arc<Bridge>,
}

/// Server error `detail` passthrough (the TS ApiError mapping): string detail,
/// 422 validation arrays, and closed `{code, message, run_id}` objects.
fn extract_api_error(status: u16, body: &Value) -> DeviceAiApiError {
    let detail = body.get("detail");
    let mut message = format!("请求失败（HTTP {status}）");
    let mut code = None;
    let mut run_id = None;
    match detail {
        Some(Value::String(text)) => message = text.clone(),
        Some(Value::Array(items)) => {
            let messages: Vec<String> = items
                .iter()
                .take(3)
                .filter_map(|item| {
                    item.get("msg")
                        .and_then(Value::as_str)
                        .map(|msg| msg.strip_prefix("Value error, ").unwrap_or(msg).to_owned())
                })
                .collect();
            if !messages.is_empty() {
                message = messages.join("；");
            }
        }
        Some(detail @ Value::Object(_)) => {
            if let Some(text) = detail.get("message").and_then(Value::as_str) {
                message = text.to_owned();
            }
            if let Some(text) = detail.get("code").and_then(Value::as_str) {
                let bounded = !text.is_empty()
                    && text.len() <= 100
                    && text
                        .chars()
                        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '@' | '.' | '-'));
                if bounded {
                    code = Some(text.to_owned());
                }
            }
            if let Some(text) = detail.get("run_id").and_then(Value::as_str) {
                let bounded = !text.is_empty()
                    && text.len() <= 64
                    && text
                        .chars()
                        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-');
                if bounded {
                    run_id = Some(text.to_owned());
                }
            }
        }
        _ => {}
    }
    DeviceAiApiError {
        status,
        code,
        message: Some(message),
        run_id,
    }
}

/// AI stream detail validation, mirroring `isAIStreamDetail` from the sealed
/// TS pipeline (`packages/api-client/src/index.ts`).
fn is_ai_timestamp(value: &Value) -> bool {
    value
        .as_str()
        .is_some_and(|text| chrono::DateTime::parse_from_rfc3339(text).is_ok())
}

fn bounded_cursor(value: &Value) -> bool {
    value
        .as_str()
        .is_some_and(|text| {
            !text.is_empty()
                && text.chars().count() <= 512
                && !text.contains(['\r', '\n', '\0'])
        })
}

fn string_or_null(value: &Value) -> bool {
    value.is_null() || value.is_string()
}

fn is_ai_claim(value: &Value) -> bool {
    let Some(object) = value.as_object() else {
        return false;
    };
    let claim_type = object.get("type").and_then(Value::as_str).unwrap_or_default();
    if !matches!(claim_type, "fact" | "inference") {
        return false;
    }
    let Some(text) = object.get("text").and_then(Value::as_str) else {
        return false;
    };
    if text.trim().is_empty() {
        return false;
    }
    if claim_type == "inference" && text.chars().count() > 2000 {
        return false;
    }
    let references = |items: Option<&Value>, max: usize| {
        items
            .and_then(Value::as_array)
            .is_some_and(|list| {
                list.len() <= max
                    && list
                        .iter()
                        .all(|item| item.as_str().is_some_and(|s| !s.is_empty()))
            })
    };
    if !references(object.get("fact_ids"), 24) || !references(object.get("evidence_ids"), 6) {
        return false;
    }
    serde_json::to_vec(value).is_ok_and(|bytes| bytes.len() <= 65536)
}

fn is_ai_draft(value: &Value) -> bool {
    value
        .get("index")
        .and_then(Value::as_u64)
        .is_some_and(|index| index < 12)
        && value.get("claim").is_some_and(is_ai_claim)
}

fn is_ai_stream_execution(value: &Value) -> bool {
    let Some(object) = value.as_object() else {
        return false;
    };
    let state = object.get("state").and_then(Value::as_str).unwrap_or_default();
    if !matches!(
        state,
        "accepted" | "running" | "completed" | "failed" | "outcome_unknown"
    ) {
        return false;
    }
    let terminal = matches!(state, "completed" | "failed" | "outcome_unknown");
    object.get("terminal").and_then(Value::as_bool) == Some(terminal)
        && is_ai_timestamp(object.get("deadline_at").unwrap_or(&Value::Null))
        && string_or_null(object.get("last_event_at").unwrap_or(&Value::Null))
        && object.get("projection_only").and_then(Value::as_bool).is_some()
}

fn is_ai_stream_detail(value: &Value, request_id: Option<&str>) -> bool {
    let Some(object) = value.as_object() else {
        return false;
    };
    if object.get("schema").and_then(Value::as_str) != Some("ai-streams@1")
        || object.get("scope").and_then(Value::as_str) != Some("session")
        || !object.get("execution").is_some_and(is_ai_stream_execution)
        || !bounded_cursor(object.get("cursor").unwrap_or(&Value::Null))
        || !is_ai_timestamp(object.get("server_time").unwrap_or(&Value::Null))
    {
        return false;
    }
    let Some(analysis) = object.get("analysis").and_then(Value::as_object) else {
        return false;
    };
    let analysis_id = analysis.get("id").and_then(Value::as_str).unwrap_or_default();
    if analysis_id.is_empty() {
        return false;
    }
    if let Some(expected) = request_id {
        if analysis_id != expected {
            return false;
        }
    }
    if !analysis.get("pack_id").and_then(Value::as_str).is_some()
        || !analysis.get("question").and_then(Value::as_str).is_some()
    {
        return false;
    }
    let drafts_ok = object
        .get("draft_claims")
        .and_then(Value::as_array)
        .is_some_and(|claims| claims.len() <= 12 && claims.iter().all(is_ai_draft));
    if !drafts_ok {
        return false;
    }
    if let Some(uncertainty) = object.get("draft_uncertainty") {
        let ok = uncertainty.is_null()
            || uncertainty
                .as_str()
                .is_some_and(|text| text.chars().count() <= 2000);
        if !ok {
            return false;
        }
    } else {
        return false;
    }
    let execution_state = object
        .get("execution")
        .and_then(|execution| execution.get("state"))
        .and_then(Value::as_str)
        .unwrap_or_default();
    let analysis_state = analysis.get("state").and_then(Value::as_str);
    let expected_analysis_state = match execution_state {
        "accepted" | "running" => "pending",
        other => other,
    };
    if analysis_state != Some(expected_analysis_state) {
        return false;
    }
    let terminal = matches!(execution_state, "completed" | "failed" | "outcome_unknown");
    let draft_count = object
        .get("draft_claims")
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or(0);
    let has_drafts = draft_count > 0
        || object
            .get("draft_uncertainty")
            .is_some_and(|value| !value.is_null());
    if terminal && has_drafts {
        return false;
    }
    if execution_state != "completed" {
        return analysis.get("answer").map(Value::is_null).unwrap_or(false);
    }
    let Some(answer) = analysis.get("answer").and_then(Value::as_object) else {
        return false;
    };
    answer
        .get("claims")
        .and_then(Value::as_array)
        .is_some_and(|claims| claims.len() <= 12 && claims.iter().all(is_ai_claim))
        && answer.get("uncertainty").and_then(Value::as_str).is_some()
        && answer.get("notice").and_then(Value::as_str).is_some()
}

fn checked_prepare_view(value: Value) -> Result<Value, DeviceAiHostErrorCode> {
    let invalid = || host_err(DeviceAiHostErrorCode::ResponseInvalid);
    let Some(object) = value.as_object() else {
        return Err(invalid());
    };
    let id_ok = object
        .get("id")
        .and_then(Value::as_str)
        .is_some_and(|id| is_plain_string(id, 64));
    let pack_id_ok = object
        .get("pack_id")
        .and_then(Value::as_str)
        .is_some_and(|id| is_plain_string(id, 64));
    let hash_ok = [
        "projection_sha256",
        "device_context_fingerprint",
        "question_sha256",
        "selection_sha256",
    ]
    .iter()
    .all(|key| object.get(*key).and_then(Value::as_str).is_some_and(is_hash64));
    let flags_ok = object.get("replayed").and_then(Value::as_bool).is_some()
        && object.get("expired").and_then(Value::as_bool).is_some();
    let expires_ok = is_ai_timestamp(object.get("expires_at").unwrap_or(&Value::Null));
    if id_ok && pack_id_ok && hash_ok && flags_ok && expires_ok {
        Ok(value)
    } else {
        Err(invalid())
    }
}

fn checked_stream_detail(value: Value) -> Result<Value, DeviceAiHostErrorCode> {
    if is_ai_stream_detail(&value, None) {
        Ok(value)
    } else {
        Err(host_err(DeviceAiHostErrorCode::ResponseInvalid))
    }
}

impl DeviceAiHostClient {
    pub(crate) fn new(bridge: Arc<Bridge>) -> Self {
        Self { bridge }
    }

    async fn dispatch(
        &self,
        method: &'static str,
        path: String,
        idempotency_key: Option<String>,
        body: Option<Vec<u8>>,
    ) -> Result<DeviceAiEndpointSuccess, DeviceAiClientError> {
        let mut headers = std::collections::BTreeMap::new();
        if body.is_some() {
            headers.insert("content-type".to_owned(), "application/json".to_owned());
        }
        if let Some(key) = &idempotency_key {
            headers.insert("idempotency-key".to_owned(), key.clone());
        }
        let request = ApiRequest {
            id: Uuid::new_v4().to_string(),
            path,
            method: method.to_owned(),
            headers,
            body_base64: body.map(|bytes| STANDARD.encode(bytes)),
        };
        let response = self
            .bridge
            .request(request)
            .await
            .map_err(DeviceAiClientError::Native)?;
        let bytes = STANDARD
            .decode(&response.body_base64)
            .map_err(|_| DeviceAiClientError::Host(DeviceAiHostErrorCode::ResponseInvalid))?;
        let value: Value = serde_json::from_slice(&bytes)
            .map_err(|_| DeviceAiClientError::Host(DeviceAiHostErrorCode::ResponseInvalid))?;
        if (200..=299).contains(&response.status) {
            Ok(DeviceAiEndpointSuccess {
                status: response.status,
                value,
            })
        } else {
            Err(DeviceAiClientError::Api(extract_api_error(
                response.status, &value,
            )))
        }
    }

    /// POST /v1/ai/device-evidence-packs — metadata-only prepare.
    /// `key` is the Idempotency-Key UUID (same key + same body replays the
    /// original result; same key + different body is a server 409, surfaced
    /// as an Api passthrough). Body is closed-asserted before dispatch.
    pub async fn prepare(
        &self,
        body: &DeviceAiPrepareBody,
        key: &str,
    ) -> Result<DeviceAiEndpointSuccess, DeviceAiClientError> {
        let wire = canonicalize_prepare_body(body).map_err(DeviceAiClientError::Host)?;
        let idempotency_key =
            canonical_device_ai_uuid(key).map_err(DeviceAiClientError::Host)?;
        let bytes = serde_json::to_vec(&wire)
            .map_err(|_| DeviceAiClientError::Host(DeviceAiHostErrorCode::InvalidArgument))?;
        let success = self
            .dispatch(
                "POST",
                "/v1/ai/device-evidence-packs".to_owned(),
                Some(idempotency_key),
                Some(bytes),
            )
            .await?;
        let view = checked_prepare_view(success.value).map_err(DeviceAiClientError::Host)?;
        Ok(DeviceAiEndpointSuccess {
            status: success.status,
            value: view,
        })
    }

    /// GET /v1/ai/device-evidence-packs/lookup — read-only recovery by key.
    pub async fn lookup_prepare(
        &self,
        key: &str,
    ) -> Result<DeviceAiEndpointSuccess, DeviceAiClientError> {
        let idempotency_key =
            canonical_device_ai_uuid(key).map_err(DeviceAiClientError::Host)?;
        let path = format!(
            "/v1/ai/device-evidence-packs/lookup?mode=history&idempotency_key={idempotency_key}"
        );
        let success = self.dispatch("GET", path, None, None).await?;
        let view = checked_prepare_view(success.value).map_err(DeviceAiClientError::Host)?;
        Ok(DeviceAiEndpointSuccess {
            status: success.status,
            value: view,
        })
    }

    /// GET /v1/ai/device-evidence-packs/{prepare_id} — owned immutable read.
    pub async fn read_prepare(
        &self,
        prepare_id: &str,
    ) -> Result<DeviceAiEndpointSuccess, DeviceAiClientError> {
        // Fail-closed id charset: the existing path validator rejects encoded
        // separators, so ids containing them are refused before the network.
        if !is_plain_string(prepare_id, 64)
            || prepare_id
                .chars()
                .any(|c| matches!(c, '/' | '?' | '#' | '%' | '\\' | '&'))
        {
            return Err(DeviceAiClientError::Host(
                DeviceAiHostErrorCode::InvalidArgument,
            ));
        }
        let path = format!("/v1/ai/device-evidence-packs/{prepare_id}?mode=history");
        let success = self.dispatch("GET", path, None, None).await?;
        let view = checked_prepare_view(success.value).map_err(DeviceAiClientError::Host)?;
        Ok(DeviceAiEndpointSuccess {
            status: success.status,
            value: view,
        })
    }

    /// POST /v1/ai/analysis-streams with the closed device branch: the
    /// existing AnalysisRequest plus device_submission. The question is
    /// normalized (trim-once, codepoint-counted) exactly once here so the
    /// server's triple binding digest(trim_once(question)) ==
    /// preparation.question_sha256 == consent.question_sha256 can hold.
    /// allow_external_processing is the literal true of the device branch.
    pub async fn submit_stream(
        &self,
        submission: &DeviceAiStreamSubmission,
        key: &str,
    ) -> Result<DeviceAiEndpointSuccess, DeviceAiClientError> {
        let body = build_analysis_request_body(submission).map_err(DeviceAiClientError::Host)?;
        let idempotency_key =
            canonical_device_ai_uuid(key).map_err(DeviceAiClientError::Host)?;
        let bytes = serde_json::to_vec(&body)
            .map_err(|_| DeviceAiClientError::Host(DeviceAiHostErrorCode::InvalidArgument))?;
        let success = self
            .dispatch(
                "POST",
                "/v1/ai/analysis-streams".to_owned(),
                Some(idempotency_key),
                Some(bytes),
            )
            .await?;
        let detail = checked_stream_detail(success.value).map_err(DeviceAiClientError::Host)?;
        if detail.get("replayed").and_then(Value::as_bool).is_none() {
            return Err(DeviceAiClientError::Host(
                DeviceAiHostErrorCode::ResponseInvalid,
            ));
        }
        Ok(DeviceAiEndpointSuccess {
            status: success.status,
            value: detail,
        })
    }

    /// GET /v1/ai/analysis-streams/lookup — read-only attempt recovery by the
    /// frozen analysis key. Never starts or cancels anything (N18).
    pub async fn lookup_attempt(
        &self,
        key: &str,
    ) -> Result<DeviceAiEndpointSuccess, DeviceAiClientError> {
        let idempotency_key =
            canonical_device_ai_uuid(key).map_err(DeviceAiClientError::Host)?;
        let path =
            format!("/v1/ai/analysis-streams/lookup?mode=history&idempotency_key={idempotency_key}");
        let success = self.dispatch("GET", path, None, None).await?;
        let detail = checked_stream_detail(success.value).map_err(DeviceAiClientError::Host)?;
        Ok(DeviceAiEndpointSuccess {
            status: success.status,
            value: detail,
        })
    }
}

// ---------------------------------------------------------------------------
// N18: unknown-outcome resolution. Lookup first, never resubmit on its own.
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum DeviceAiUnknownOutcomeResolution {
    Resolved {
        detail: Value,
    },
    NotSubmitted,
    UnknownLocalClaim {
        analysis_key: String,
        resubmission: &'static str,
    },
    CrossSessionReplayBlocked,
    JournalIntegrityFailed {
        violations: Vec<DeviceAiJournalFenceViolation>,
    },
}

/// After a disconnect or crash: read-only lookup with the SAME idempotency key
/// first. A hit returns the existing attempt reference and NOTHING is ever
/// resubmitted automatically. On a miss, only the absence of a local
/// claim_submitted entry makes a fresh user decision legitimate; a recorded
/// claim allows exactly one recovery path — same key, same body, explicit user
/// decision — and a cross-session claim is never replayed (fence 5).
/// Transport failures propagate untouched: the caller retries later and the
/// state stays genuinely unknown.
pub async fn resolve_unknown_outcome(
    client: &DeviceAiHostClient,
    journal: Option<&DeviceAiJournal>,
    analysis_key: &str,
    intent_id: Option<&str>,
) -> Result<DeviceAiUnknownOutcomeResolution, DeviceAiClientError> {
    let key = canonical_device_ai_uuid(analysis_key).map_err(DeviceAiClientError::Host)?;
    let detail = match client.lookup_attempt(&key).await {
        Ok(success) => Some(success.value),
        Err(DeviceAiClientError::Api(error)) if error.status == 404 => None,
        Err(other) => return Err(other),
    };
    if let Some(detail) = detail {
        return Ok(DeviceAiUnknownOutcomeResolution::Resolved { detail });
    }
    let Some(journal) = journal else {
        return Ok(DeviceAiUnknownOutcomeResolution::NotSubmitted);
    };
    let journal_failure = |error: DeviceAiJournalError| match error {
        DeviceAiJournalError::Store(code) => DeviceAiClientError::Native(code),
        DeviceAiJournalError::Fence(code) => DeviceAiClientError::Host(code),
    };
    let verification = journal.verify_integrity().map_err(journal_failure)?;
    if !verification.ok {
        return Ok(DeviceAiUnknownOutcomeResolution::JournalIntegrityFailed {
            violations: verification.violations,
        });
    }
    let entries = journal.read_all().map_err(journal_failure)?;
    let claims: Vec<&Value> = entries
        .iter()
        .filter(|entry| {
            let event = entry.get("event");
            event
                .and_then(|event| event.get("type"))
                .and_then(Value::as_str)
                    == Some("claim_submitted")
                && event
                    .and_then(|event| event.get("analysis_key"))
                    .and_then(Value::as_str)
                    == Some(key.as_str())
                && intent_id.is_none_or(|expected| {
                    event
                        .and_then(|event| event.get("intent_id"))
                        .and_then(Value::as_str)
                        == Some(expected)
                })
        })
        .collect();
    if claims.is_empty() {
        return Ok(DeviceAiUnknownOutcomeResolution::NotSubmitted);
    }
    // Fence 5: a claim recorded under a different session never replays here.
    let cross_session = claims.iter().any(|entry| {
        v_str(entry, "session_id") != Some(journal.session_id())
    });
    if cross_session {
        return Ok(DeviceAiUnknownOutcomeResolution::CrossSessionReplayBlocked);
    }
    Ok(DeviceAiUnknownOutcomeResolution::UnknownLocalClaim {
        analysis_key: key,
        resubmission: "same_key_same_body_user_decision_only",
    })
}

// ---------------------------------------------------------------------------
// Native host store: OS keyring key + app-data blob file (existing offline
// conventions: keyring service per feature, hashed account sub-directory,
// atomic replace on save).
// ---------------------------------------------------------------------------

pub const DEVICE_AI_JOURNAL_MAX_BYTES: usize = 4 * 1024 * 1024;

/// Append-only encrypted journal blob stored as one file under
/// `<app-data>/device-ai-v1/<sha256(store_account)>/journal.bin`, persisted by
/// write-temp + fsync + rename.
pub struct FileJournalStore {
    path: PathBuf,
    limit: usize,
}

impl FileJournalStore {
    pub fn open(app_data: &Path, account: &str) -> Self {
        let root = app_data
            .join("device-ai-v1")
            .join(sha256_hex(account.as_bytes()));
        Self {
            path: root.join("journal.bin"),
            limit: DEVICE_AI_JOURNAL_MAX_BYTES,
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

impl DeviceAiJournalStore for FileJournalStore {
    fn load(&self) -> NativeResult<Option<Vec<u8>>> {
        let failure = || "DEVICE_AI_JOURNAL_STORE_FAILED";
        let Ok(metadata) = std::fs::metadata(&self.path) else {
            return Ok(None);
        };
        if metadata.len() as usize > self.limit {
            return Err("DEVICE_AI_JOURNAL_TOO_LARGE");
        }
        let blob = std::fs::read(&self.path).map_err(|_| failure())?;
        if blob.len() > self.limit {
            return Err("DEVICE_AI_JOURNAL_TOO_LARGE");
        }
        Ok(Some(blob))
    }

    fn save(&self, blob: &[u8]) -> NativeResult<()> {
        let failure = || "DEVICE_AI_JOURNAL_STORE_FAILED";
        if blob.len() > self.limit {
            return Err("DEVICE_AI_JOURNAL_TOO_LARGE");
        }
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent).map_err(|_| failure())?;
            let metadata = std::fs::symlink_metadata(parent).map_err(|_| failure())?;
            if metadata.file_type().is_symlink() {
                return Err(failure());
            }
        }
        let temporary = self.path.with_extension("tmp");
        {
            use std::io::Write as _;
            let mut file = std::fs::File::create(&temporary).map_err(|_| failure())?;
            file.write_all(blob).map_err(|_| failure())?;
            file.sync_all().map_err(|_| failure())?;
        }
        std::fs::rename(&temporary, &self.path).map_err(|_| failure())
    }
}

/// Journal AES-GCM-256 key held in the OS secure store, following the
/// `offline::crypto::OsKeyStore` keyring conventions with a device-ai
/// specific service (`org.taiji.tireintelligence.desktop.deviceai.v1`).
#[cfg(any(target_os = "windows", target_os = "macos"))]
pub struct OsJournalKeyStore(keyring::Entry);

#[cfg(any(target_os = "windows", target_os = "macos"))]
impl OsJournalKeyStore {
    pub fn open(account: &str) -> NativeResult<Self> {
        keyring::Entry::new("org.taiji.tireintelligence.desktop.deviceai.v1", account)
            .map(Self)
            .map_err(|_| "DEVICE_AI_JOURNAL_KEY_UNAVAILABLE")
    }

    /// Load the existing 32-byte key, or mint and persist a fresh one.
    pub fn load_or_create(&self) -> NativeResult<Zeroizing<[u8; 32]>> {
        match self.0.get_secret() {
            Ok(bytes) => {
                if bytes.len() != 32 {
                    return Err("DEVICE_AI_JOURNAL_KEY_INVALID");
                }
                let mut key = Zeroizing::new([0_u8; 32]);
                key.copy_from_slice(&bytes);
                Ok(key)
            }
            Err(keyring::Error::NoEntry) => {
                let mut key = Zeroizing::new([0_u8; 32]);
                OsRng
                    .try_fill_bytes(key.as_mut())
                    .map_err(|_| "DEVICE_AI_JOURNAL_KEY_UNAVAILABLE")?;
                self.0
                    .set_secret(key.as_ref())
                    .map_err(|_| "DEVICE_AI_JOURNAL_KEY_UNAVAILABLE")?;
                Ok(key)
            }
            Err(_) => Err("DEVICE_AI_JOURNAL_KEY_UNAVAILABLE"),
        }
    }
}

/// Monotonic clock for the journal: UNIX-epoch nanoseconds with an in-process
/// never-decreasing guard. Cross-restart monotonicity relies on the wall clock
/// not regressing; any violation surfaces as the fence-4
/// `device_ai_host_journal_clock_regression` failure (fail-closed, no silent
/// corruption) — the honest bound without a persisted clock sequence.
#[derive(Debug, Default)]
pub struct WallNanoClock {
    last: AtomicU64,
}

impl WallNanoClock {
    pub const fn new() -> Self {
        Self {
            last: AtomicU64::new(0),
        }
    }

    pub fn now(&self) -> u64 {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|elapsed| elapsed.as_nanos() as u64)
            .unwrap_or(0);
        let previous = self.last.fetch_max(nanos.max(1), Ordering::SeqCst);
        nanos.max(previous.saturating_add(1)).max(1)
    }
}

/// Open the native journal for the current installation account. `owner` is
/// the Host identity (the existing per-installation store account), and the
/// key lives in the OS secure store; generation 1 is the initial journal
/// build (a future rebuild bumps it and fence 2 voids older blobs).
#[cfg(any(target_os = "windows", target_os = "macos"))]
pub fn open_native_journal(
    app_data: &Path,
    account: &str,
    owner: &str,
    generation: u64,
    session_id: &str,
) -> NativeResult<DeviceAiJournal> {
    let key = OsJournalKeyStore::open(account)?.load_or_create()?;
    let store = Arc::new(FileJournalStore::open(app_data, account));
    let clock = Arc::new(WallNanoClock::new());
    DeviceAiJournal::new(DeviceAiJournalOptions {
        owner: owner.to_owned(),
        generation,
        session_id: session_id.to_owned(),
        key,
        store,
        monotonic_now: Box::new(move || clock.now()),
        wall_now: None,
    })
    .map_err(|_| "DEVICE_AI_JOURNAL_STORE_FAILED")
}

#[cfg(not(any(target_os = "windows", target_os = "macos")))]
pub fn open_native_journal(
    _app_data: &Path,
    _account: &str,
    _owner: &str,
    _generation: u64,
    _session_id: &str,
) -> NativeResult<DeviceAiJournal> {
    Err("DEVICE_AI_UNSUPPORTED_PLATFORM")
}

#[cfg(test)]
mod tests;
