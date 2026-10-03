/**
 * device-ai internal, wire not frozen (D15 layered strategy: internal module first).
 *
 * Strict exact-JSON pipeline for the device-AI bridge, mirroring the sealed
 * Python reference apps/api/tire_api/device_ai_projection.py (parse_exact_json /
 * canonical_exact_json / exact_digest) and device_ai_value_encoder.py
 * (encode_value) byte-for-byte. Locked by the authoritative vectors in
 * .artifacts/device-ai50/specs/e1-canonical-vectors-a.json (68/68 parity).
 *
 * Semantics frozen by those vectors:
 *  - package bytes <= 8 MiB (0 bytes rejected as capacity), UTF-8 BOM rejected,
 *    invalid UTF-8 and lone surrogates rejected (closed error codes, same
 *    stage ordering as Python: capacity -> bom -> utf8 -> depth pre-scan ->
 *    syntax/duplicate-key/number -> tree depth/nodes/unicode walk);
 *  - AST depth <= 32 with root = 0 (a 33rd text bracket level is legal only
 *    for empty tail containers); text pre-scan bound is MAX_DEPTH + 1 = 33;
 *  - node budget <= 250_000 (every AST node counts, object key names do not;
 *    number tokens additionally count while parsing, as in Python);
 *  - duplicate keys are judged after unescaping, at object close time (an
 *    unclosed object with duplicate keys fails as json_invalid, like Python's
 *    object_pairs_hook timing);
 *  - number lexemes are kept verbatim; only float tokens (containing . e E)
 *    must stay finite under binary64 (1e-5000 keeps its token, 1e309 and
 *    NaN/Infinity are rejected);
 *  - canonical object keys sort by codepoint (== UTF-8 byte order), never by
 *    UTF-16 code-unit order and never by Object.keys enumeration order;
 *    arrays keep source order; string escaping matches json.dumps(
 *    ensure_ascii=False) == ECMAScript JSON.stringify (\/ stays /, 0x7F and
 *    U+2028/U+2029 stay raw, control chars as lowercase \uXXXX, non-BMP raw).
 *
 * Differences from the legacy offline-fallback module exact-json.ts are
 * intentional; that file stays the permissive channel and must not change.
 * This module is deliberately NOT exported from index.ts: the DeviceAIValue
 * wire is still a draft. Declared deviation outside vector coverage:
 * canonical_exact_json also accepts bounded Python int nodes (metadata
 * channel); this module rejects bare JS numbers in canonical/encode because
 * the exact-AST domain never contains them and JS cannot distinguish 5 from
 * 5.0 — fail closed instead of guessing a lexeme (encoder-spec.md section 7).
 */

export const DEVICE_AI_MAX_DEPTH = 32;
export const DEVICE_AI_MAX_NODES = 250_000;
export const DEVICE_AI_MAX_PACKAGE_BYTES = 8 * 1024 * 1024;
export const DEVICE_AI_NUMBER_TOKEN_SCHEMA = "device-number-token@1";

export type DeviceAiErrorCode =
  | "device_ai_package_capacity"
  | "device_ai_json_bom"
  | "device_ai_json_utf8"
  | "device_ai_json_depth"
  | "device_ai_json_nodes"
  | "device_ai_json_duplicate_key"
  | "device_ai_json_invalid"
  | "device_ai_json_unicode"
  | "device_ai_number_invalid"
  | "device_ai_number_nonfinite"
  | "device_ai_number_or_type_unsupported"
  | "device_ai_value_type_unsupported"
  | "device_ai_material_invalid";

/** Closed failure; the message carries only the code, never source content. */
export class DeviceAiProjectionError extends Error {
  constructor(readonly code: DeviceAiErrorCode) { super(code); this.name = "DeviceAiProjectionError"; }
}
const fail = (code: DeviceAiErrorCode): never => { throw new DeviceAiProjectionError(code); };

const NUMERIC_SYNTAX = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/;
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u;

/** Exact-AST number node: original lexeme only, no added numeric meaning. */
export class DeviceAiJsonNumber {
  readonly isFloat: boolean;
  constructor(readonly token: string) {
    if (typeof token !== "string" || !NUMERIC_SYNTAX.test(token)) fail("device_ai_number_invalid");
    this.isFloat = /[.eE]/.test(token);
    if (this.isFloat && !Number.isFinite(Number(token))) fail("device_ai_number_nonfinite");
    Object.freeze(this);
  }
  tokenDto(): { schema: string; token: string } { return { schema: DEVICE_AI_NUMBER_TOKEN_SCHEMA, token: this.token }; }
  toString(): string { return this.token; }
}

export type DeviceAiJsonAst = null | boolean | string | DeviceAiJsonNumber | DeviceAiJsonAst[] | { [key: string]: DeviceAiJsonAst };

const isPlainAstObject = (node: unknown): node is { [key: string]: DeviceAiJsonAst } =>
  !!node && typeof node === "object" && !Array.isArray(node) && !(node instanceof DeviceAiJsonNumber)
  && (Object.getPrototypeOf(node) === Object.prototype || Object.getPrototypeOf(node) === null);

const checkString = (value: string): void => { if (LONE_SURROGATE.test(value)) fail("device_ai_json_unicode"); };

/**
 * Codepoint order (== UTF-8 byte order). Same semantics as device-criteria.ts
 * compareCodepoints; kept inline so this unfrozen internal module stays
 * self-contained and importable under node --experimental-transform-types.
 */
const compareCodepoints = (a: string, b: string): number => {
  const first = Array.from(a, c => c.codePointAt(0)!), second = Array.from(b, c => c.codePointAt(0)!);
  for (let i = 0; i < Math.min(first.length, second.length); i++) if (first[i] !== second[i]) return first[i] - second[i];
  return first.length - second.length;
};

/** Text pre-scan: at most MAX_DEPTH + 1 simultaneously open brackets (Python _scan_depth). */
function scanDepth(text: string): void {
  let depth = 0, quoted = false, escaped = false;
  for (const char of text) {
    if (quoted) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') quoted = false;
    } else if (char === '"') quoted = true;
    else if (char === "[" || char === "{") {
      depth++;
      if (depth > DEVICE_AI_MAX_DEPTH + 1) fail("device_ai_json_depth");
    } else if (char === "]" || char === "}") depth--;
  }
}

/** Tree walk: node budget, AST depth (root = 0) and lone-surrogate strings (Python _check_tree). */
function checkTree(root: DeviceAiJsonAst): void {
  let budget = 0;
  const walk = (node: DeviceAiJsonAst, depth: number): void => {
    budget++;
    if (depth > DEVICE_AI_MAX_DEPTH) fail("device_ai_json_depth");
    if (budget > DEVICE_AI_MAX_NODES) fail("device_ai_json_nodes");
    if (Array.isArray(node)) { for (const child of node) walk(child, depth + 1); return; }
    if (isPlainAstObject(node)) {
      for (const key of Object.keys(node)) { checkString(key); walk(node[key], depth + 1); }
      return;
    }
    if (typeof node === "string") checkString(node);
  };
  walk(root, 0);
}

/**
 * Strict bounded UTF-8 JSON AST with original integer/float lexemes.
 * A string input is processed as its own UTF-8 byte encoding (so "\ufeff..."
 * fails as a BOM exactly like the equivalent bytes would).
 */
export function parseDeviceAiJson(input: string | Uint8Array, maxBytes: number = DEVICE_AI_MAX_PACKAGE_BYTES): DeviceAiJsonAst {
  const raw = typeof input === "string" ? new TextEncoder().encode(input) : input;
  if (!(raw.byteLength > 0 && raw.byteLength <= maxBytes)) fail("device_ai_package_capacity");
  if (raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf) fail("device_ai_json_bom");
  let text: string;
  try { text = new TextDecoder("utf-8", { fatal: true }).decode(raw); } catch { return fail("device_ai_json_utf8"); }
  scanDepth(text);
  let position = 0, numberCount = 0;
  const invalid = (): never => fail("device_ai_json_invalid");
  const whitespace = (): void => {
    while (position < text.length) {
      const char = text[position];
      if (char === " " || char === "\t" || char === "\n" || char === "\r") position++; else break;
    }
  };
  const string = (): string => {
    if (text[position++] !== '"') invalid();
    const start = position - 1; let escaped = false;
    while (position < text.length) {
      const char = text[position++];
      if (!escaped && char === '"') {
        // JSON.parse on the exact literal slice validates the escape set and the
        // raw-control-character ban with the same strictness as Python's json.
        let value: unknown;
        try { value = JSON.parse(text.slice(start, position)); } catch { return invalid(); }
        return value as string;
      }
      escaped = !escaped && char === "\\";
    }
    return invalid(); // unterminated string
  };
  const number = (token: string): DeviceAiJsonNumber => {
    numberCount++;
    if (numberCount > DEVICE_AI_MAX_NODES) fail("device_ai_json_nodes");
    return new DeviceAiJsonNumber(token);
  };
  /** Longest JSON number token at `position`, or "" (hand-rolled to avoid O(n^2) slicing). */
  const scanNumber = (): string => {
    const digits = (from: number): number => { let end = from; while (text[end] >= "0" && text[end] <= "9") end++; return end; };
    let end = position;
    if (text[end] === "-") end++;
    if (text[end] === "0") end++;
    else if (text[end] >= "1" && text[end] <= "9") end = digits(end);
    else return "";
    if (text[end] === ".") { end++; const stop = digits(end); if (stop === end) return ""; end = stop; }
    if (text[end] === "e" || text[end] === "E") {
      end++;
      if (text[end] === "+" || text[end] === "-") end++;
      const stop = digits(end); if (stop === end) return ""; end = stop;
    }
    return text.slice(position, end);
  };
  const value = (): DeviceAiJsonAst => {
    whitespace();
    const first = text[position];
    if (first === '"') return string();
    if (first === "{") {
      position++; whitespace();
      if (text[position] === "}") { position++; return {}; }
      const pairs: [string, DeviceAiJsonAst][] = [];
      for (;;) {
        const key = string();
        whitespace();
        if (text[position++] !== ":") invalid();
        const child = value(); // depth itself is enforced later by checkTree
        pairs.push([key, child]);
        whitespace();
        const next = text[position++];
        if (next === "}") break;
        if (next !== ",") invalid();
        whitespace();
        if (position >= text.length) invalid();
      }
      // Duplicate keys are judged after unescaping at object close, matching
      // Python's object_pairs_hook timing (unclosed => json_invalid wins).
      const object: { [key: string]: DeviceAiJsonAst } = {};
      for (const [key, child] of pairs) {
        if (Object.hasOwn(object, key)) fail("device_ai_json_duplicate_key");
        Object.defineProperty(object, key, { value: child, enumerable: true, writable: true, configurable: true });
      }
      return object;
    }
    if (first === "[") {
      position++; whitespace();
      const array: DeviceAiJsonAst[] = [];
      if (text[position] === "]") { position++; return array; }
      for (;;) {
        array.push(value());
        whitespace();
        const next = text[position++];
        if (next === "]") break;
        if (next !== ",") invalid();
        whitespace();
        if (position >= text.length) invalid();
      }
      return array;
    }
    if (text.startsWith("true", position)) { position += 4; return true; }
    if (text.startsWith("false", position)) { position += 5; return false; }
    if (text.startsWith("null", position)) { position += 4; return null; }
    // JSON allows these three constants through the scanner; Python's
    // parse_constant hook rejects them with device_ai_number_invalid.
    if (text.startsWith("NaN", position) || text.startsWith("Infinity", position) || text.startsWith("-Infinity", position))
      fail("device_ai_number_invalid");
    const token = scanNumber();
    if (!token) invalid();
    position += token.length;
    return number(token);
  };
  const parsed = value();
  whitespace();
  if (position !== text.length) invalid();
  checkTree(parsed);
  return parsed;
}

/** Codepoint-sorted canonical JSON text; lexemes verbatim, arrays in source order. */
export function canonicalDeviceAiJson(ast: DeviceAiJsonAst): string {
  const encode = (node: unknown, depth: number): string => {
    if (depth > DEVICE_AI_MAX_DEPTH) fail("device_ai_json_depth");
    if (node instanceof DeviceAiJsonNumber) return node.token;
    if (node === null) return "null";
    if (typeof node === "boolean") return node ? "true" : "false";
    if (typeof node === "string") { checkString(node); return JSON.stringify(node); }
    if (Array.isArray(node)) return "[" + node.map(child => encode(child, depth + 1)).join(",") + "]";
    if (isPlainAstObject(node)) {
      const keys = Object.keys(node).sort(compareCodepoints);
      return "{" + keys.map(key => encode(key, depth + 1) + ":" + encode(node[key], depth + 1)).join(",") + "}";
    }
    return fail("device_ai_number_or_type_unsupported");
  };
  return encode(ast, 0);
}

const toHex = (bytes: Uint8Array): string => {
  let out = "";
  for (const byte of bytes) out += byte.toString(16).padStart(2, "0");
  return out;
};

/**
 * sha256 over the canonical UTF-8 bytes of the ORIGINAL AST (never the encoded
 * DTO). No namespace => bare digest (DeviceProjection.sha256 form); with a
 * namespace => exact_digest form sha256(ns_utf8 + b"\x00" + canonical).
 * Implemented on the Web Crypto API (globalThis.crypto.subtle), matching the
 * project's existing async digest convention; no synchronous implementation
 * exists in packages/ to reuse.
 */
export async function deviceAiDigest(ast: DeviceAiJsonAst, namespace?: string): Promise<string> {
  if (namespace !== undefined && (typeof namespace !== "string" || !namespace || namespace.includes("\0")))
    fail("device_ai_material_invalid");
  const encoder = new TextEncoder();
  const canonical = encoder.encode(canonicalDeviceAiJson(ast));
  const bytes = namespace === undefined ? canonical
    : (() => { const head = encoder.encode(namespace), all = new Uint8Array(head.length + 1 + canonical.length); all.set(head, 0); all[head.length] = 0; all.set(canonical, head.length + 1); return all; })();
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return toHex(new Uint8Array(digest));
}

export interface DeviceAiValueField { name: string; value: DeviceAiValue }
export type DeviceAiValue =
  | { kind: "number"; value: { schema: "device-number-token@1"; token: string } }
  | { kind: "null"; value: null }
  | { kind: "boolean"; value: boolean }
  | { kind: "text"; value: string }
  | { kind: "array"; items: DeviceAiValue[] }
  | { kind: "structured"; fields: DeviceAiValueField[] };

/**
 * Encode one exact-AST node into the draft-b DeviceAIValue tagged shape.
 * The decision is made ONLY on the AST node type: a dict that merely looks
 * like a token DTO stays the structured branch, and bare JS numbers (never
 * produced by parseDeviceAiJson) are rejected instead of guessed.
 */
export function encodeDeviceAiValue(ast: DeviceAiJsonAst): DeviceAiValue {
  const encode = (node: unknown, depth: number): DeviceAiValue => {
    if (depth > DEVICE_AI_MAX_DEPTH) fail("device_ai_json_depth");
    if (node instanceof DeviceAiJsonNumber) return { kind: "number", value: { schema: DEVICE_AI_NUMBER_TOKEN_SCHEMA, token: node.token } };
    if (node === null) return { kind: "null", value: null };
    if (typeof node === "boolean") return { kind: "boolean", value: node };
    if (typeof node === "string") return { kind: "text", value: node };
    if (Array.isArray(node)) return { kind: "array", items: node.map(child => encode(child, depth + 1)) };
    if (isPlainAstObject(node)) {
      const fields = Object.keys(node).sort(compareCodepoints)
        .map(name => ({ name, value: encode(node[name], depth + 1) }));
      return { kind: "structured", fields };
    }
    return fail("device_ai_value_type_unsupported");
  };
  return encode(ast, 0);
}
