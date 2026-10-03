/** Exact JSON numbers stay distinct from the native bridge's JavaScript projection. */
export const EXACT_JSON_BYTES = 8 * 1024 * 1024;
export const EXACT_NATIVE_WIRE_BYTES = 32 * 1024 * 1024;
const numericSyntax = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/;
const invalid = (): never => { throw Object.assign(new Error("精确设备 JSON 无效。"), { code: "OFFLINE_FALLBACK_INVALID" }); };
const bytes = (text: string) => new TextEncoder().encode(text).byteLength;

export class ExactJsonNumber {
  readonly kind: "integer" | "float";
  readonly integer: bigint | null;
  readonly float: number | null;
  constructor(readonly token: string) {
    if (!numericSyntax.test(token)) invalid();
    this.kind = /[.eE]/.test(token) ? "float" : "integer";
    this.integer = this.kind === "integer" ? BigInt(token) : null;
    this.float = this.kind === "float" ? Number(token) : null;
    if (this.float !== null && !Number.isFinite(this.float)) invalid();
    Object.freeze(this);
  }
  toString(): string { return this.token; }
  toJSON(): unknown {
    const raw = (JSON as unknown as { rawJSON?: (text: string) => unknown }).rawJSON;
    if (!raw) throw Object.assign(new Error("请使用精确 JSON writer。"), { code: "OFFLINE_FALLBACK_INVALID" });
    return raw(this.token);
  }
}

export type ExactJsonValue = null | boolean | string | ExactJsonNumber | ExactJsonValue[] | { [key: string]: ExactJsonValue };

export function parseExactJson(input: string | Uint8Array, maxBytes = EXACT_JSON_BYTES): ExactJsonValue {
  let text: string;
  if (typeof input === "string") text = input;
  else {
    if (!input.byteLength || input.byteLength > maxBytes || input[0] === 0xef && input[1] === 0xbb && input[2] === 0xbf) invalid();
    try { text = new TextDecoder("utf-8", { fatal: true }).decode(input); } catch { return invalid(); }
  }
  if (!text.length || bytes(text) > maxBytes || text[0] === "\ufeff") invalid();
  let position = 0;
  const whitespace = () => { while (/[\t\n\r ]/.test(text[position] || "x")) position++; };
  const string = (): string => {
    if (text[position++] !== '"') return invalid();
    const start = position - 1; let escaped = false;
    while (position < text.length) {
      const char = text[position++];
      if (!escaped && char === '"') {
        let value: unknown;
        try { value = JSON.parse(text.slice(start, position)); } catch { return invalid(); }
        if (typeof value !== "string" || /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value)) return invalid();
        return value;
      }
      escaped = !escaped && char === "\\";
    }
    return invalid();
  };
  const value = (depth: number): ExactJsonValue => {
    if (depth > 64) return invalid();
    whitespace(); const first = text[position];
    if (first === '"') return string();
    if (first === "{") {
      position++; whitespace(); const object: { [key: string]: ExactJsonValue } = {}, keys = new Set<string>();
      if (text[position] === "}") { position++; return object; }
      while (position < text.length) {
        const key = string(); if (keys.has(key)) return invalid(); keys.add(key); whitespace();
        if (text[position++] !== ":") return invalid();
        Object.defineProperty(object, key, { value: value(depth + 1), enumerable: true, writable: true, configurable: true });
        whitespace(); const next = text[position++];
        if (next === "}") return object;
        if (next !== ",") return invalid();
        whitespace();
      }
      return invalid();
    }
    if (first === "[") {
      position++; whitespace(); const array: ExactJsonValue[] = [];
      if (text[position] === "]") { position++; return array; }
      while (position < text.length) {
        array.push(value(depth + 1)); whitespace(); const next = text[position++];
        if (next === "]") return array;
        if (next !== ",") return invalid();
      }
      return invalid();
    }
    for (const [token, result] of [["true", true], ["false", false], ["null", null]] as const) {
      if (text.startsWith(token, position)) { position += token.length; return result; }
    }
    const token = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(text.slice(position));
    if (!token) return invalid(); position += token[0].length; return new ExactJsonNumber(token[0]);
  };
  const parsed = value(0); whitespace(); if (position !== text.length) return invalid(); return parsed;
}

export function stringifyExactJson(value: unknown, maxBytes = EXACT_JSON_BYTES): string {
  const active = new Set<object>();
  const encode = (node: unknown, depth: number): string => {
    if (depth > 64) return invalid();
    if (node instanceof ExactJsonNumber) return node.token;
    if (typeof node === "bigint") return node.toString();
    if (typeof node === "number") { if (!Number.isFinite(node)) return invalid(); return JSON.stringify(node); }
    if (node === null || typeof node === "boolean" || typeof node === "string") return JSON.stringify(node);
    if (!node || typeof node !== "object" || active.has(node)) return invalid();
    active.add(node);
    try {
      if (Array.isArray(node)) return "[" + node.map(child => encode(child, depth + 1)).join(",") + "]";
      if (Object.getPrototypeOf(node) !== Object.prototype && Object.getPrototypeOf(node) !== null) return invalid();
      return "{" + Object.keys(node).filter(key => (node as Record<string, unknown>)[key] !== undefined)
        .map(key => JSON.stringify(key) + ":" + encode((node as Record<string, unknown>)[key], depth + 1)).join(",") + "}";
    } finally { active.delete(node); }
  };
  const result = encode(value, 0); if (bytes(result) > maxBytes) return invalid(); return result;
}

export function projectExactJson(value: unknown): unknown {
  if (value instanceof ExactJsonNumber || typeof value === "bigint") {
    const projected = Number(value instanceof ExactJsonNumber ? value.token : value);
    return Number.isFinite(projected) ? Object.is(projected, -0) ? 0 : projected : null;
  }
  if (Array.isArray(value)) return value.map(projectExactJson);
  if (value && typeof value === "object") {
    const result: Record<string, unknown> = {};
    for (const [key, node] of Object.entries(value)) Object.defineProperty(result, key, { value: projectExactJson(node), enumerable: true, writable: true, configurable: true });
    return result;
  }
  return value;
}

export function exactSafeInteger(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number {
  if (value instanceof ExactJsonNumber) {
    if (value.integer === null || value.integer < BigInt(min) || value.integer > BigInt(max)) return invalid();
    return Number(value.integer);
  }
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < min || value > max) return invalid();
  return value;
}

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value) && !(value instanceof ExactJsonNumber);
function isV2Core(value: Record<string, unknown>): boolean {
  return record(value.intent) && value.intent.schema === "device-fallback-intent@2"
    || value.schema === "device-fallback-grant@2" || value.schema === "device-fallback-result@2" || value.schema === "offline-read-result@2" && value.package_schema === "offline-pack@2"
    || value.schema === "device-fallback-authorization@1" && value.state === "allowed" && record(value.grant) && value.grant.schema === "device-fallback-grant@2";
}
function noRecursiveTransport(value: Record<string, unknown>): void {
  if (Object.hasOwn(value, "raw_json") || record(value.intent) && Object.hasOwn(value.intent, "raw_json")
    || value.schema === "device-fallback-authorization@1" && record(value.grant) && Object.hasOwn(value.grant, "raw_json")) invalid();
  // Ordinary facts may legally have a raw_json key. No data-key blacklist here.
}

export function encodeExactDeviceFallbackWire<T extends object>(core: T): T & { raw_json: string } {
  if (!record(core) || !isV2Core(core)) return invalid(); noRecursiveTransport(core);
  const raw_json = stringifyExactJson(core), projected = projectExactJson(parseExactJson(raw_json));
  if (!record(projected)) return invalid();
  const wire = { ...projected, raw_json }; if (bytes(JSON.stringify(wire)) > EXACT_NATIVE_WIRE_BYTES) return invalid();
  return wire as T & { raw_json: string };
}

function matchesProjection(raw: unknown, mirror: unknown): boolean {
  if (raw instanceof ExactJsonNumber) return mirror === projectExactJson(raw);
  if (Array.isArray(raw)) return Array.isArray(mirror) && raw.length === mirror.length && raw.every((value, index) => matchesProjection(value, mirror[index]));
  if (record(raw)) {
    if (!record(mirror)) return false;
    const keys = Object.keys(raw); return keys.length === Object.keys(mirror).length && keys.every(key => Object.hasOwn(mirror, key) && matchesProjection(raw[key], mirror[key]));
  }
  return raw === mirror;
}
export function materializeExactMetadata(value: unknown, path: string[] = []): unknown {
  if (value instanceof ExactJsonNumber) {
    if (path.includes("payload") || path.includes("filters") && path.at(-1) === "value") return value;
    return exactSafeInteger(value);
  }
  if (Array.isArray(value)) return value.map((node, index) => materializeExactMetadata(node, [...path, String(index)]));
  if (record(value)) {
    const result: Record<string, unknown> = {};
    for (const [key, node] of Object.entries(value)) Object.defineProperty(result, key, { value: materializeExactMetadata(node, [...path, key]), enumerable: true, writable: true, configurable: true });
    return result;
  }
  return value;
}

/** Explicitly consume the transport field; all original typed core fields survive. */
export function decodeExactDeviceFallbackWire<T extends object>(input: unknown): { core: T; raw_json: string } {
  if (!record(input) || typeof input.raw_json !== "string" || bytes(JSON.stringify(input)) > EXACT_NATIVE_WIRE_BYTES) return invalid();
  const raw = parseExactJson(input.raw_json); if (!record(raw) || !isV2Core(raw)) return invalid(); noRecursiveTransport(raw);
  const mirror: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(input)) if (key !== "raw_json") Object.defineProperty(mirror, key, { value, enumerable: true });
  if (!matchesProjection(raw, mirror)) return invalid();
  return { core: materializeExactMetadata(raw) as T, raw_json: input.raw_json };
}
