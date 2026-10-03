//! device-ai exact-JSON pipeline, Rust host port (device-AI bridge round 50).
//!
//! Byte-for-byte mirror of the sealed Python reference
//! `apps/api/tire_api/device_ai_projection.py` (`parse_exact_json` /
//! `canonical_exact_json` / `exact_digest`) and `device_ai_value_encoder.py`
//! (`encode_value`), locked by the authoritative vectors in
//! `.artifacts/device-ai50/specs/e1-canonical-vectors-a.json`
//! (replayed by `tests/device_ai_e1_parity.rs`, 68/68 parity).
//!
//! Semantics frozen by those vectors and by the Python reference:
//!  - stage order: package capacity (0 bytes rejected) -> UTF-8 BOM -> strict
//!    UTF-8 -> text depth pre-scan (at most MAX_DEPTH + 1 = 33 simultaneously
//!    open brackets; brackets inside strings are skipped) -> syntax /
//!    duplicate-key (judged on the UNESCAPED text at object close, like
//!    Python's object_pairs_hook timing) / NaN-Infinity constants /
//!    number tokens -> final tree walk (AST depth <= 32 with root = 0, node
//!    budget <= 250_000 counting every AST node but not object key names,
//!    lone-surrogate strings rejected as unicode errors);
//!  - number lexemes are kept verbatim; only float tokens (containing any of
//!    `. e E`) must stay finite under binary64: `1e-5000` underflows to 0.0
//!    and keeps its token, `1e309` is rejected, and the `NaN` / `Infinity` /
//!    `-Infinity` constants are rejected as `device_ai_number_invalid`;
//!  - canonical object keys sort by codepoint (== UTF-8 byte order; the
//!    BTreeMap below relies on Rust `&str`/`String` ordering being byte
//!    order); arrays keep source order; string escaping matches Python
//!    `json.dumps(ensure_ascii=False)`: `"` and `\`, `\b \f \n \r \t`
//!    shortcuts, other control chars as lowercase `\uXXXX`, while `/`, 0x7F,
//!    U+2028/U+2029 and non-BMP characters stay raw;
//!  - digests are computed over the ORIGINAL AST, never over the encoded
//!    DeviceAIValue shape: `sha256(canonical)`, or with a namespace
//!    `sha256(ns_utf8 + b"\x00" + canonical)` (the `exact_digest` form).
//!
//! Declared deviation outside vector coverage (same stance as the TS port
//! `packages/api-client/src/device-ai-exact.ts`): the sealed Python
//! `canonical_exact_json` also accepts bounded Python `int` metadata nodes;
//! the closed Rust AST below has no bare-number node at all, so bare numbers
//! cannot enter canonical/encode and are failed closed instead of guessed
//! (encoder-spec.md section 7). Additionally, multi-fault inputs whose error
//! precedence in Python depends on dict insertion order (for example one
//! object containing both a lone-surrogate key and an over-budget sibling)
//! may report a different error code here, because a BTreeMap walks keys in
//! codepoint order; every single-fault input, including all 68 vectors, is
//! unaffected.
//!
//! Registered in `lib.rs` from round 50 P1-3 (host wiring) as a pure library
//! module with no Tauri command of its own: the DeviceAIValue wire is still
//! an unfrozen draft. `tests/device_ai_e1_parity.rs` keeps compiling this
//! file through `#[path = "../src/device_ai_exact.rs"]` so the integration
//! parity binary is independent of the lib registration.

use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fmt;

/// Conservative common bound (Android 32, desktop 64); AST depth, root = 0.
pub const DEVICE_AI_MAX_DEPTH: usize = 32;
/// Every AST node counts (containers, scalars, number lexemes); keys do not.
pub const DEVICE_AI_MAX_NODES: usize = 250_000;
/// Hard package bound; 0 bytes are rejected as a capacity failure.
pub const DEVICE_AI_MAX_PACKAGE_BYTES: usize = 8 * 1024 * 1024;
/// Same label as the Python `NumberLexeme.token_dto()` schema field.
pub const DEVICE_AI_NUMBER_TOKEN_SCHEMA: &str = "device-number-token@1";

/// Closed failure set; the message carries only the code, never source
/// content. The strings are byte-equal to the sealed Python error codes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeviceAiErrorCode {
    PackageCapacity,
    JsonBom,
    JsonUtf8,
    JsonDepth,
    JsonNodes,
    JsonDuplicateKey,
    JsonInvalid,
    JsonUnicode,
    NumberInvalid,
    NumberNonfinite,
    NumberOrTypeUnsupported,
    ValueTypeUnsupported,
    MaterialInvalid,
}

impl DeviceAiErrorCode {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::PackageCapacity => "device_ai_package_capacity",
            Self::JsonBom => "device_ai_json_bom",
            Self::JsonUtf8 => "device_ai_json_utf8",
            Self::JsonDepth => "device_ai_json_depth",
            Self::JsonNodes => "device_ai_json_nodes",
            Self::JsonDuplicateKey => "device_ai_json_duplicate_key",
            Self::JsonInvalid => "device_ai_json_invalid",
            Self::JsonUnicode => "device_ai_json_unicode",
            Self::NumberInvalid => "device_ai_number_invalid",
            Self::NumberNonfinite => "device_ai_number_nonfinite",
            Self::NumberOrTypeUnsupported => "device_ai_number_or_type_unsupported",
            Self::ValueTypeUnsupported => "device_ai_value_type_unsupported",
            Self::MaterialInvalid => "device_ai_material_invalid",
        }
    }
}

/// Closed fail-closed error; `Display` emits the Python-equal code string.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DeviceAiError {
    code: DeviceAiErrorCode,
}

impl DeviceAiError {
    #[must_use]
    pub const fn new(code: DeviceAiErrorCode) -> Self {
        Self { code }
    }

    #[must_use]
    pub const fn code(&self) -> DeviceAiErrorCode {
        self.code
    }
}

impl fmt::Display for DeviceAiError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code.as_str())
    }
}

impl std::error::Error for DeviceAiError {}

pub type DeviceAiResult<T> = Result<T, DeviceAiError>;

fn err(code: DeviceAiErrorCode) -> DeviceAiError {
    DeviceAiError::new(code)
}

/// String AST node, internally WTF-8: byte-identical to UTF-8 while valid.
///
/// Python's json accepts `\uD800`-style escapes that decode to lone
/// surrogates and only rejects them afterwards, when the finished tree is
/// walked (`_check_tree` -> `_check_string`); duplicate-key comparison also
/// sees the raw unescaped text (`object_pairs_hook`). Encoding lone
/// surrogates as their WTF-8 3-byte forms preserves both behaviours until
/// the tree walk rejects them: byte equality equals Python string equality,
/// and byte order equals codepoint order (surrogate bytes `ED A0..` sort
/// between U+D7FF and U+E000, exactly where Python would sort them).
#[derive(Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord)]
pub struct DeviceAiText {
    wtf8: Vec<u8>,
}

impl DeviceAiText {
    #[must_use]
    pub fn new(text: &str) -> Self {
        Self {
            wtf8: text.as_bytes().to_vec(),
        }
    }

    /// `None` when the text still contains unpaired surrogates (i.e. it is
    /// not real UTF-8 yet); the tree walk rejects such trees first.
    #[must_use]
    pub fn as_str(&self) -> Option<&str> {
        std::str::from_utf8(&self.wtf8).ok()
    }

    fn from_wtf8(bytes: Vec<u8>) -> Self {
        Self { wtf8: bytes }
    }
}

impl From<&str> for DeviceAiText {
    fn from(text: &str) -> Self {
        Self::new(text)
    }
}

impl From<String> for DeviceAiText {
    fn from(text: String) -> Self {
        Self {
            wtf8: text.into_bytes(),
        }
    }
}

/// Exact-AST number node: the original lexeme only, no added numeric meaning
/// (`1.2300` stays `1.2300`, `-0` keeps its sign, `1e16` is never expanded,
/// arbitrary-length integers are legal as long as they fit the package and
/// node budgets).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DeviceAiNumber {
    token: String,
}

impl DeviceAiNumber {
    /// Validates the JSON number grammar (the Python `_NUMBER` regex under
    /// `re.fullmatch` semantics) and, for float tokens (containing any of
    /// `. e E`), binary64 finiteness. Underflow such as `1e-5000` is finite
    /// and keeps its lexeme; overflow such as `1e309` is rejected.
    pub fn new(token: &str) -> DeviceAiResult<Self> {
        if !valid_number_grammar(token.as_bytes()) {
            return Err(err(DeviceAiErrorCode::NumberInvalid));
        }
        if has_float_marker(token.as_bytes()) {
            match token.parse::<f64>() {
                Ok(value) if value.is_finite() => {}
                _ => return Err(err(DeviceAiErrorCode::NumberNonfinite)),
            }
        }
        Ok(Self {
            token: token.to_owned(),
        })
    }

    #[must_use]
    pub fn token(&self) -> &str {
        &self.token
    }

    #[must_use]
    pub fn is_float(&self) -> bool {
        has_float_marker(self.token.as_bytes())
    }
}

fn has_float_marker(token: &[u8]) -> bool {
    token.iter().any(|&b| matches!(b, b'.' | b'e' | b'E'))
}

/// `-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?` as a fullmatch.
fn valid_number_grammar(token: &[u8]) -> bool {
    let mut i = 0;
    if i < token.len() && token[i] == b'-' {
        i += 1;
    }
    if i < token.len() && token[i] == b'0' {
        i += 1;
    } else if i < token.len() && token[i].is_ascii_digit() {
        while i < token.len() && token[i].is_ascii_digit() {
            i += 1;
        }
    } else {
        return false;
    }
    if i + 1 < token.len() && token[i] == b'.' && token[i + 1].is_ascii_digit() {
        i += 2;
        while i < token.len() && token[i].is_ascii_digit() {
            i += 1;
        }
    }
    if i < token.len() && (token[i] == b'e' || token[i] == b'E') {
        let mut after = i + 1;
        if after < token.len() && (token[after] == b'+' || token[after] == b'-') {
            after += 1;
        }
        if after < token.len() && token[after].is_ascii_digit() {
            i = after;
            while i < token.len() && token[i].is_ascii_digit() {
                i += 1;
            }
        }
    }
    i == token.len()
}

/// Strict exact-JSON AST, the Rust analogue of a tree produced by the sealed
/// Python `parse_exact_json`. Objects are BTreeMaps so iteration order is
/// already the codepoint (= UTF-8 byte) order used by the canonical form and
/// by the DeviceAIValue `structured` branch; arrays keep source order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DeviceAiValue {
    Null,
    Bool(bool),
    Text(DeviceAiText),
    Number(DeviceAiNumber),
    Array(Vec<DeviceAiValue>),
    Object(BTreeMap<DeviceAiText, DeviceAiValue>),
}

/// Strict bounded UTF-8 JSON AST with original integer/float lexemes.
/// Stage order and error codes match the Python `parse_exact_json`.
pub fn parse_device_ai_json(raw: &[u8], max_bytes: usize) -> DeviceAiResult<DeviceAiValue> {
    if raw.is_empty() || raw.len() > max_bytes {
        return Err(err(DeviceAiErrorCode::PackageCapacity));
    }
    if raw.starts_with(&[0xEF, 0xBB, 0xBF]) {
        return Err(err(DeviceAiErrorCode::JsonBom));
    }
    let text = std::str::from_utf8(raw).map_err(|_| err(DeviceAiErrorCode::JsonUtf8))?;
    scan_depth(text)?;
    let mut parser = Parser::new(text);
    let value = parser.parse_value()?;
    parser.skip_whitespace();
    if parser.pos != parser.text.len() {
        return Err(err(DeviceAiErrorCode::JsonInvalid));
    }
    let mut budget = 0usize;
    check_tree(&value, 0, &mut budget)?;
    Ok(value)
}

/// `parse_device_ai_json` with the sealed `MAX_PACKAGE_BYTES` bound.
pub fn parse_device_ai_package(raw: &[u8]) -> DeviceAiResult<DeviceAiValue> {
    parse_device_ai_json(raw, DEVICE_AI_MAX_PACKAGE_BYTES)
}

/// Text pre-scan (Python `_scan_depth`): brackets inside strings are skipped,
/// and at most MAX_DEPTH + 1 = 33 brackets may be open simultaneously. This
/// is only a recursion guard; 33 text levels still pass here and are judged
/// by real AST depth in the tree walk (an empty innermost container is
/// legal because it adds no deeper node).
fn scan_depth(text: &str) -> DeviceAiResult<()> {
    let mut depth: i64 = 0;
    let mut quoted = false;
    let mut escaped = false;
    for &byte in text.as_bytes() {
        if quoted {
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                quoted = false;
            }
        } else if byte == b'"' {
            quoted = true;
        } else if byte == b'[' || byte == b'{' {
            depth += 1;
            if depth > DEVICE_AI_MAX_DEPTH as i64 + 1 {
                return Err(err(DeviceAiErrorCode::JsonDepth));
            }
        } else if byte == b']' || byte == b'}' {
            depth -= 1;
        }
    }
    Ok(())
}

/// Final tree walk (Python `_check_tree`): every AST node consumes budget
/// (object key names do not), AST depth with root = 0 must stay <= 32, and
/// every string value / object key must be real UTF-8 (no lone surrogates).
fn check_tree(node: &DeviceAiValue, depth: usize, budget: &mut usize) -> DeviceAiResult<()> {
    *budget += 1;
    if depth > DEVICE_AI_MAX_DEPTH {
        return Err(err(DeviceAiErrorCode::JsonDepth));
    }
    if *budget > DEVICE_AI_MAX_NODES {
        return Err(err(DeviceAiErrorCode::JsonNodes));
    }
    match node {
        DeviceAiValue::Object(map) => {
            for (key, value) in map {
                if key.as_str().is_none() {
                    return Err(err(DeviceAiErrorCode::JsonUnicode));
                }
                check_tree(value, depth + 1, budget)?;
            }
        }
        DeviceAiValue::Array(items) => {
            for child in items {
                check_tree(child, depth + 1, budget)?;
            }
        }
        DeviceAiValue::Text(text) => {
            if text.as_str().is_none() {
                return Err(err(DeviceAiErrorCode::JsonUnicode));
            }
        }
        _ => {}
    }
    Ok(())
}

struct Parser<'a> {
    text: &'a [u8],
    pos: usize,
    number_count: usize,
}

impl<'a> Parser<'a> {
    fn new(text: &'a str) -> Self {
        Self {
            text: text.as_bytes(),
            pos: 0,
            number_count: 0,
        }
    }

    fn peek(&self) -> Option<u8> {
        self.text.get(self.pos).copied()
    }

    fn starts_with(&self, needle: &[u8]) -> bool {
        self.text[self.pos..].starts_with(needle)
    }

    fn skip_whitespace(&mut self) {
        while let Some(byte) = self.peek() {
            if matches!(byte, b' ' | b'\t' | b'\n' | b'\r') {
                self.pos += 1;
            } else {
                break;
            }
        }
    }

    fn parse_value(&mut self) -> DeviceAiResult<DeviceAiValue> {
        self.skip_whitespace();
        let first = match self.peek() {
            Some(byte) => byte,
            None => return Err(err(DeviceAiErrorCode::JsonInvalid)),
        };
        match first {
            b'"' => Ok(DeviceAiValue::Text(self.parse_string()?)),
            b'{' => self.parse_object(),
            b'[' => self.parse_array(),
            _ => {
                if self.starts_with(b"true") {
                    self.pos += 4;
                    return Ok(DeviceAiValue::Bool(true));
                }
                if self.starts_with(b"false") {
                    self.pos += 5;
                    return Ok(DeviceAiValue::Bool(false));
                }
                if self.starts_with(b"null") {
                    self.pos += 4;
                    return Ok(DeviceAiValue::Null);
                }
                // Python's parse_constant hook fires the moment the scanner
                // matches one of these, before any later syntax error, so the
                // code is device_ai_number_invalid, not device_ai_json_invalid.
                if self.starts_with(b"NaN")
                    || self.starts_with(b"Infinity")
                    || self.starts_with(b"-Infinity")
                {
                    return Err(err(DeviceAiErrorCode::NumberInvalid));
                }
                let token = self.scan_number();
                if token.is_empty() {
                    return Err(err(DeviceAiErrorCode::JsonInvalid));
                }
                self.pos += token.len();
                self.number_count += 1;
                if self.number_count > DEVICE_AI_MAX_NODES {
                    return Err(err(DeviceAiErrorCode::JsonNodes));
                }
                let lexeme = std::str::from_utf8(token).expect("number tokens are ASCII");
                Ok(DeviceAiValue::Number(DeviceAiNumber::new(lexeme)?))
            }
        }
    }

    fn parse_object(&mut self) -> DeviceAiResult<DeviceAiValue> {
        self.pos += 1; // '{'
        self.skip_whitespace();
        let mut pairs: Vec<(DeviceAiText, DeviceAiValue)> = Vec::new();
        if self.peek() == Some(b'}') {
            self.pos += 1;
            return Ok(DeviceAiValue::Object(BTreeMap::new()));
        }
        loop {
            if self.peek() != Some(b'"') {
                return Err(err(DeviceAiErrorCode::JsonInvalid));
            }
            let key = self.parse_string()?;
            self.skip_whitespace();
            if self.peek() != Some(b':') {
                return Err(err(DeviceAiErrorCode::JsonInvalid));
            }
            self.pos += 1;
            let value = self.parse_value()?;
            pairs.push((key, value));
            self.skip_whitespace();
            match self.peek() {
                Some(b'}') => {
                    self.pos += 1;
                    break;
                }
                Some(b',') => {
                    self.pos += 1;
                    self.skip_whitespace();
                }
                _ => return Err(err(DeviceAiErrorCode::JsonInvalid)),
            }
        }
        // Duplicate keys are judged on the UNESCAPED text at object close,
        // exactly like Python's object_pairs_hook timing: an unclosed object
        // with duplicate keys still fails as device_ai_json_invalid.
        let mut map = BTreeMap::new();
        for (key, value) in pairs {
            if map.contains_key(&key) {
                return Err(err(DeviceAiErrorCode::JsonDuplicateKey));
            }
            map.insert(key, value);
        }
        Ok(DeviceAiValue::Object(map))
    }

    fn parse_array(&mut self) -> DeviceAiResult<DeviceAiValue> {
        self.pos += 1; // '['
        self.skip_whitespace();
        let mut items = Vec::new();
        if self.peek() == Some(b']') {
            self.pos += 1;
            return Ok(DeviceAiValue::Array(items));
        }
        loop {
            items.push(self.parse_value()?);
            self.skip_whitespace();
            match self.peek() {
                Some(b']') => {
                    self.pos += 1;
                    break;
                }
                Some(b',') => {
                    self.pos += 1;
                    self.skip_whitespace();
                }
                _ => return Err(err(DeviceAiErrorCode::JsonInvalid)),
            }
        }
        Ok(DeviceAiValue::Array(items))
    }

    /// Scans one JSON string literal. Raw bytes are copied verbatim (the
    /// document is valid UTF-8), raw control characters are rejected, and
    /// `\uXXXX` escapes are decoded with CPython's pairing rules: a high
    /// surrogate pairs only with an immediately following `\uDC00-\uDFFF`
    /// escape; anything else stays a lone surrogate (WTF-8) and is rejected
    /// later by the tree walk.
    fn parse_string(&mut self) -> DeviceAiResult<DeviceAiText> {
        self.pos += 1; // opening quote (caller verified)
        let mut out: Vec<u8> = Vec::new();
        loop {
            let byte = match self.peek() {
                Some(byte) => byte,
                None => return Err(err(DeviceAiErrorCode::JsonInvalid)),
            };
            match byte {
                b'"' => {
                    self.pos += 1;
                    return Ok(DeviceAiText::from_wtf8(out));
                }
                b'\\' => {
                    self.pos += 1;
                    let escape = match self.peek() {
                        Some(byte) => byte,
                        None => return Err(err(DeviceAiErrorCode::JsonInvalid)),
                    };
                    self.pos += 1;
                    match escape {
                        b'"' => out.push(b'"'),
                        b'\\' => out.push(b'\\'),
                        b'/' => out.push(b'/'),
                        b'b' => out.push(0x08),
                        b'f' => out.push(0x0C),
                        b'n' => out.push(0x0A),
                        b'r' => out.push(0x0D),
                        b't' => out.push(0x09),
                        b'u' => {
                            let unit = self.hex4()?;
                            self.push_unicode_unit(&mut out, unit)?;
                        }
                        _ => return Err(err(DeviceAiErrorCode::JsonInvalid)),
                    }
                }
                byte if byte < 0x20 => return Err(err(DeviceAiErrorCode::JsonInvalid)),
                _ => {
                    out.push(byte);
                    self.pos += 1;
                }
            }
        }
    }

    fn hex4(&mut self) -> DeviceAiResult<u16> {
        if self.pos + 4 > self.text.len() {
            return Err(err(DeviceAiErrorCode::JsonInvalid));
        }
        let mut value: u16 = 0;
        for i in 0..4 {
            let byte = self.text[self.pos + i];
            let digit = match byte {
                b'0'..=b'9' => byte - b'0',
                b'a'..=b'f' => byte - b'a' + 10,
                b'A'..=b'F' => byte - b'A' + 10,
                _ => return Err(err(DeviceAiErrorCode::JsonInvalid)),
            };
            value = value * 16 + u16::from(digit);
        }
        self.pos += 4;
        Ok(value)
    }

    /// CPython pairing: a failed pair leaves the high surrogate as a lone
    /// WTF-8 code point and re-processes the second unit fresh (it may start
    /// a new pair, e.g. `"\ud800\ud834\udd1e"` -> lone D800 + U+1D11E).
    fn push_unicode_unit(&mut self, out: &mut Vec<u8>, unit: u16) -> DeviceAiResult<()> {
        match unit {
            0xD800..=0xDBFF => {
                if self.pos + 6 <= self.text.len()
                    && self.text[self.pos] == b'\\'
                    && self.text[self.pos + 1] == b'u'
                {
                    self.pos += 2;
                    let second = self.hex4()?;
                    if (0xDC00..=0xDFFF).contains(&second) {
                        let point = 0x10000u32
                            + ((u32::from(unit) - 0xD800) << 10)
                            + (u32::from(second) - 0xDC00);
                        push_wtf8_code_point(out, point);
                        return Ok(());
                    }
                    push_wtf8_code_point(out, u32::from(unit));
                    return self.push_unicode_unit(out, second);
                }
                push_wtf8_code_point(out, u32::from(unit));
                Ok(())
            }
            0xDC00..=0xDFFF => {
                push_wtf8_code_point(out, u32::from(unit));
                Ok(())
            }
            _ => {
                push_wtf8_code_point(out, u32::from(unit));
                Ok(())
            }
        }
    }

    /// Longest JSON number token at the cursor, or an empty slice. Mirrors
    /// the CPython scanner regex: `1.` or `1e` fall back to `1` and the
    /// leftover is then rejected by the container grammar as
    /// device_ai_json_invalid, exactly like Python's delimiter errors.
    fn scan_number(&self) -> &'a [u8] {
        let text = self.text;
        let mut end = self.pos;
        if end < text.len() && text[end] == b'-' {
            end += 1;
        }
        if end < text.len() && text[end] == b'0' {
            end += 1;
        } else if end < text.len() && text[end].is_ascii_digit() {
            while end < text.len() && text[end].is_ascii_digit() {
                end += 1;
            }
        } else {
            return &text[self.pos..self.pos];
        }
        if end + 1 < text.len() && text[end] == b'.' && text[end + 1].is_ascii_digit() {
            end += 2;
            while end < text.len() && text[end].is_ascii_digit() {
                end += 1;
            }
        }
        if end < text.len() && (text[end] == b'e' || text[end] == b'E') {
            let mut after = end + 1;
            if after < text.len() && (text[after] == b'+' || text[after] == b'-') {
                after += 1;
            }
            if after < text.len() && text[after].is_ascii_digit() {
                end = after;
                while end < text.len() && text[end].is_ascii_digit() {
                    end += 1;
                }
            }
        }
        &text[self.pos..end]
    }
}

/// WTF-8 encode: identical to UTF-8 for valid scalars, and defined for lone
/// surrogates (the `ED A0..ED BF` three-byte forms rejected by `from_utf8`).
fn push_wtf8_code_point(out: &mut Vec<u8>, point: u32) {
    if point < 0x80 {
        out.push(point as u8);
    } else if point < 0x800 {
        out.push(0xC0 | (point >> 6) as u8);
        out.push(0x80 | (point & 0x3F) as u8);
    } else if point < 0x10000 {
        out.push(0xE0 | (point >> 12) as u8);
        out.push(0x80 | ((point >> 6) & 0x3F) as u8);
        out.push(0x80 | (point & 0x3F) as u8);
    } else {
        out.push(0xF0 | (point >> 18) as u8);
        out.push(0x80 | ((point >> 12) & 0x3F) as u8);
        out.push(0x80 | ((point >> 6) & 0x3F) as u8);
        out.push(0x80 | (point & 0x3F) as u8);
    }
}

/// Codepoint-sorted canonical JSON text; number lexemes verbatim, arrays in
/// source order, escaping equal to Python `json.dumps(ensure_ascii=False)`.
pub fn canonical_device_ai_json(ast: &DeviceAiValue) -> DeviceAiResult<String> {
    let mut out = String::new();
    write_canonical(ast, 0, &mut out)?;
    Ok(out)
}

fn write_canonical(node: &DeviceAiValue, depth: usize, out: &mut String) -> DeviceAiResult<()> {
    if depth > DEVICE_AI_MAX_DEPTH {
        return Err(err(DeviceAiErrorCode::JsonDepth));
    }
    match node {
        DeviceAiValue::Number(number) => out.push_str(number.token()),
        DeviceAiValue::Null => out.push_str("null"),
        DeviceAiValue::Bool(true) => out.push_str("true"),
        DeviceAiValue::Bool(false) => out.push_str("false"),
        DeviceAiValue::Text(text) => push_json_string(
            text
                .as_str()
                .ok_or_else(|| err(DeviceAiErrorCode::JsonUnicode))?,
            out,
        ),
        DeviceAiValue::Array(items) => {
            out.push('[');
            for (index, child) in items.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                write_canonical(child, depth + 1, out)?;
            }
            out.push(']');
        }
        DeviceAiValue::Object(map) => {
            out.push('{');
            for (index, (key, value)) in map.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                push_json_string(
                    key.as_str()
                        .ok_or_else(|| err(DeviceAiErrorCode::JsonUnicode))?,
                    out,
                );
                out.push(':');
                write_canonical(value, depth + 1, out)?;
            }
            out.push('}');
        }
    }
    Ok(())
}

/// Python `json.dumps(ensure_ascii=False)` escape set: `"` and `\`, the
/// `\b \f \n \r \t` shortcuts, other control chars as lowercase `\uXXXX`;
/// `/`, 0x7F, U+2028/U+2029 and all non-ASCII characters stay raw.
fn push_json_string(text: &str, out: &mut String) {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    out.push('"');
    for character in text.chars() {
        match character {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            other if (other as u32) < 0x20 => {
                let value = other as u32;
                out.push_str("\\u00");
                out.push(HEX[(value >> 4) as usize] as char);
                out.push(HEX[(value & 0xF) as usize] as char);
            }
            other => out.push(other),
        }
    }
    out.push('"');
}

fn to_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0xF) as usize] as char);
    }
    out
}

/// sha256 over the canonical UTF-8 bytes of the ORIGINAL AST (never over the
/// encoded DeviceAIValue). `None` -> the bare `sha256(canonical)` form
/// (`DeviceProjection.sha256`); `Some(ns)` -> the `exact_digest` form
/// `sha256(ns_utf8 + b"\x00" + canonical)`. The namespace must be non-empty
/// and contain no NUL, exactly like the Python `exact_digest` guard.
pub fn device_ai_digest(ast: &DeviceAiValue, namespace: Option<&str>) -> DeviceAiResult<String> {
    if let Some(ns) = namespace {
        if ns.is_empty() || ns.contains('\0') {
            return Err(err(DeviceAiErrorCode::MaterialInvalid));
        }
    }
    let canonical = canonical_device_ai_json(ast)?;
    let mut hasher = Sha256::new();
    if let Some(ns) = namespace {
        hasher.update(ns.as_bytes());
        hasher.update([0u8]);
    }
    hasher.update(canonical.as_bytes());
    Ok(to_hex(&hasher.finalize()))
}

/// Encoded DeviceAIValue shape: an AST-domain tree, because the Python
/// encoder also returns only dict/list/str/bool/None nodes.
pub type DeviceAiEncoded = DeviceAiValue;

fn text_value(value: &str) -> DeviceAiValue {
    DeviceAiValue::Text(DeviceAiText::new(value))
}

fn tagged_object(entries: Vec<(&str, DeviceAiValue)>) -> DeviceAiValue {
    DeviceAiValue::Object(
        entries
            .into_iter()
            .map(|(key, value)| (DeviceAiText::new(key), value))
            .collect(),
    )
}

/// Encode one exact-AST node into the draft-b DeviceAIValue tagged shape.
/// The decision is made ONLY on the AST node type: an object that merely
/// looks like a token DTO stays the structured branch (its leaves are
/// `kind:"text"`), and a number lexeme is never flattened, stringified or
/// re-formatted. Bare numbers cannot occur in the closed Rust AST, so the
/// Python `device_ai_value_type_unsupported` branch is unreachable here by
/// construction (fail-closed, encoder-spec.md section 7).
pub fn encode_device_ai_value(ast: &DeviceAiValue) -> DeviceAiResult<DeviceAiEncoded> {
    encode_node(ast, 0)
}

fn encode_node(node: &DeviceAiValue, depth: usize) -> DeviceAiResult<DeviceAiValue> {
    if depth > DEVICE_AI_MAX_DEPTH {
        return Err(err(DeviceAiErrorCode::JsonDepth));
    }
    Ok(match node {
        DeviceAiValue::Number(number) => tagged_object(vec![
            ("kind", text_value("number")),
            (
                "value",
                tagged_object(vec![
                    ("schema", text_value(DEVICE_AI_NUMBER_TOKEN_SCHEMA)),
                    ("token", text_value(number.token())),
                ]),
            ),
        ]),
        DeviceAiValue::Null => tagged_object(vec![
            ("kind", text_value("null")),
            ("value", DeviceAiValue::Null),
        ]),
        DeviceAiValue::Bool(flag) => tagged_object(vec![
            ("kind", text_value("boolean")),
            ("value", DeviceAiValue::Bool(*flag)),
        ]),
        DeviceAiValue::Text(value) => tagged_object(vec![
            ("kind", text_value("text")),
            ("value", DeviceAiValue::Text(value.clone())),
        ]),
        DeviceAiValue::Array(items) => tagged_object(vec![
            ("kind", text_value("array")),
            (
                "items",
                DeviceAiValue::Array(
                    items
                        .iter()
                        .map(|child| encode_node(child, depth + 1))
                        .collect::<DeviceAiResult<Vec<_>>>()?,
                ),
            ),
        ]),
        DeviceAiValue::Object(map) => tagged_object(vec![
            ("kind", text_value("structured")),
            (
                "fields",
                DeviceAiValue::Array(
                    map.iter()
                        .map(|(key, value)| {
                            Ok(tagged_object(vec![
                                ("name", DeviceAiValue::Text(key.clone())),
                                ("value", encode_node(value, depth + 1)?),
                            ]))
                        })
                        .collect::<DeviceAiResult<Vec<_>>>()?,
                ),
            ),
        ]),
    })
}

impl DeviceAiValue {
    /// serde_json view of an AST subtree, for bridge interop and tests.
    /// Number lexemes are deliberately not converted to JSON numbers: the
    /// encoded DeviceAIValue keeps them as `token` strings, and a bare JSON
    /// number would smuggle a guessed lexeme (encoder-spec.md section 7).
    pub fn to_json_value(&self) -> DeviceAiResult<serde_json::Value> {
        Ok(match self {
            Self::Null => serde_json::Value::Null,
            Self::Bool(flag) => serde_json::Value::Bool(*flag),
            Self::Text(text) => serde_json::Value::String(
                text.as_str()
                    .ok_or_else(|| err(DeviceAiErrorCode::JsonUnicode))?
                    .to_owned(),
            ),
            Self::Number(_) => {
                return Err(err(DeviceAiErrorCode::NumberOrTypeUnsupported));
            }
            Self::Array(items) => serde_json::Value::Array(
                items
                    .iter()
                    .map(Self::to_json_value)
                    .collect::<DeviceAiResult<Vec<_>>>()?,
            ),
            Self::Object(map) => {
                let mut object = serde_json::Map::new();
                for (key, value) in map {
                    object.insert(
                        key.as_str()
                            .ok_or_else(|| err(DeviceAiErrorCode::JsonUnicode))?
                            .to_owned(),
                        value.to_json_value()?,
                    );
                }
                serde_json::Value::Object(object)
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn device_ai_error_codes_match_python_strings() {
        const EVERY_CODE: [(DeviceAiErrorCode, &str); 13] = [
            (DeviceAiErrorCode::PackageCapacity, "device_ai_package_capacity"),
            (DeviceAiErrorCode::JsonBom, "device_ai_json_bom"),
            (DeviceAiErrorCode::JsonUtf8, "device_ai_json_utf8"),
            (DeviceAiErrorCode::JsonDepth, "device_ai_json_depth"),
            (DeviceAiErrorCode::JsonNodes, "device_ai_json_nodes"),
            (
                DeviceAiErrorCode::JsonDuplicateKey,
                "device_ai_json_duplicate_key",
            ),
            (DeviceAiErrorCode::JsonInvalid, "device_ai_json_invalid"),
            (DeviceAiErrorCode::JsonUnicode, "device_ai_json_unicode"),
            (DeviceAiErrorCode::NumberInvalid, "device_ai_number_invalid"),
            (
                DeviceAiErrorCode::NumberNonfinite,
                "device_ai_number_nonfinite",
            ),
            (
                DeviceAiErrorCode::NumberOrTypeUnsupported,
                "device_ai_number_or_type_unsupported",
            ),
            (
                DeviceAiErrorCode::ValueTypeUnsupported,
                "device_ai_value_type_unsupported",
            ),
            (DeviceAiErrorCode::MaterialInvalid, "device_ai_material_invalid"),
        ];
        for (code, expected) in EVERY_CODE {
            assert_eq!(code.as_str(), expected);
            assert_eq!(DeviceAiError::new(code).to_string(), expected);
        }
    }

    #[test]
    fn device_ai_number_grammar_and_finiteness() {
        for accepted in [
            "0", "-0", "1", "9007199254740993", "-9007199254740993",
            "123456789012345678901234567890", "1.2300", "0.0", "-0.0", "1e5", "1E+5",
            "-1.5E-3", "5e-324", "1e-5000", "0.1000000000000000001", "1e16",
        ] {
            let number = DeviceAiNumber::new(accepted).unwrap_or_else(|e| panic!("{e}"));
            assert_eq!(number.token(), accepted);
        }
        assert!(DeviceAiNumber::new("1e-5000").unwrap().is_float());
        assert!(!DeviceAiNumber::new("9007199254740993").unwrap().is_float());
        for rejected in [
            "", "01", "1.", "+1", ".5", "1e", "1e+", "--1", "0x10", "NaN", "Infinity", "1_000",
            "- 1", "1.5e", "00",
        ] {
            assert_eq!(
                DeviceAiNumber::new(rejected).unwrap_err().code(),
                DeviceAiErrorCode::NumberInvalid,
                "token {rejected:?}"
            );
        }
        for overflow in ["1e309", "-1e400", "1e999", "1e1000000000000000000000"] {
            assert_eq!(
                DeviceAiNumber::new(overflow).unwrap_err().code(),
                DeviceAiErrorCode::NumberNonfinite,
                "token {overflow:?}"
            );
        }
        // Integer lexemes have no magnitude bound at all.
        assert!(DeviceAiNumber::new(&"9".repeat(2001)).is_ok());
    }

    #[test]
    fn device_ai_text_wtf8_semantics() {
        let valid = DeviceAiText::new("中文/ABC");
        assert_eq!(valid.as_str(), Some("中文/ABC"));
        // Lone surrogate D800 in WTF-8 is not valid UTF-8, and it sorts
        // between U+D7FF and U+E000 exactly where Python would place it.
        let lone = DeviceAiText::from_wtf8(vec![0xED, 0xA0, 0x80]);
        assert_eq!(lone.as_str(), None);
        assert!(DeviceAiText::new("\u{D7FF}") < lone);
        assert!(lone < DeviceAiText::new("\u{E000}"));
        // Equal unescaped keys compare equal, unequal surrogates do not.
        assert_eq!(lone, DeviceAiText::from_wtf8(vec![0xED, 0xA0, 0x80]));
        assert_ne!(lone, DeviceAiText::from_wtf8(vec![0xED, 0xA0, 0x81]));
    }

    #[test]
    fn device_ai_lone_surrogate_escape_is_deferred_to_the_tree_walk() {
        // A lone surrogate alone: loads succeeds, the tree walk rejects it.
        assert_eq!(
            parse_device_ai_package(br#"{"x":"\ud800"}"#)
                .unwrap_err()
                .code(),
            DeviceAiErrorCode::JsonUnicode
        );
        // A later syntax error wins first, like Python's loads ordering.
        assert_eq!(
            parse_device_ai_package(br#"{"x":"\ud800" 5}"#)
                .unwrap_err()
                .code(),
            DeviceAiErrorCode::JsonInvalid
        );
        // A duplicate key also fires before the tree walk.
        assert_eq!(
            parse_device_ai_package(br#"{"x":"\ud800","y":1,"y":2}"#)
                .unwrap_err()
                .code(),
            DeviceAiErrorCode::JsonDuplicateKey
        );
        // A paired escape is a real astral character and is accepted.
        assert!(parse_device_ai_package("{\"k\":\"😀\"}".as_bytes()).is_ok());
    }

    #[test]
    fn device_ai_canonical_escaping_matches_python_dumps() {
        let ast = parse_device_ai_package(b"{\"x\":\"a\\u0001b\\tc\\nd\"}").unwrap();
        assert_eq!(
            canonical_device_ai_json(&ast).unwrap(),
            "{\"x\":\"a\\u0001b\\tc\\nd\"}"
        );
        // Solidus stays raw, quote and backslash re-escape.
        let ast = parse_device_ai_package(br#"{"s":"\/","q":"\"","b":"\\"}"#).unwrap();
        assert_eq!(
            canonical_device_ai_json(&ast).unwrap(),
            r#"{"b":"\\","q":"\"","s":"/"}"#
        );
    }

    #[test]
    fn device_ai_digest_namespace_validation_and_known_vector() {
        let ast = parse_device_ai_package(b"42").unwrap();
        // Locked by E1 vector scalar_top_number_42.
        assert_eq!(
            device_ai_digest(&ast, None).unwrap(),
            "73475cb40a568e8da8a045ced110137e159f890ac4da883b6b17dc651b3a8049"
        );
        assert_eq!(
            device_ai_digest(&ast, Some("")).unwrap_err().code(),
            DeviceAiErrorCode::MaterialInvalid
        );
        assert_eq!(
            device_ai_digest(&ast, Some("a\0b")).unwrap_err().code(),
            DeviceAiErrorCode::MaterialInvalid
        );
    }

    #[test]
    fn device_ai_capacity_bound_uses_max_bytes() {
        assert_eq!(
            parse_device_ai_json(b"123", 2).unwrap_err().code(),
            DeviceAiErrorCode::PackageCapacity
        );
        assert!(parse_device_ai_json(b"123", 3).is_ok());
        assert_eq!(
            parse_device_ai_package(b"").unwrap_err().code(),
            DeviceAiErrorCode::PackageCapacity
        );
        assert_eq!(
            parse_device_ai_package(b"\xEF\xBB\xBF{}").unwrap_err().code(),
            DeviceAiErrorCode::JsonBom
        );
    }
}
