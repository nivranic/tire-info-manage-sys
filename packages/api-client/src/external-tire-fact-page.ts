import type { ExternalTireFactPage, ExternalTireFactPageRequest } from "@tire/domain-types";
import { isExternalTireFactResult } from "./external-tire-facts";

export const EXTERNAL_TIRE_FACT_PAGE_MAX_BYTES = 1_327_104;
const MAX_DEPTH = 6, MAX_NODES = 5472, ITEM_MAX_BYTES = 65_536;
const ROUTE = "/external/v1/tire-facts";
type Obj = Record<string, unknown>;
type Cursor = {
  schema: "external-tire-facts-cursor@1"; key_id: string; owner: string; route: string;
  source_id: string; query_id: string; verification_id: string; limit: number;
  issued: number; expires: number; window: string; context: string; after: string;
};
function ensure(v: unknown): asserts v { if (!v) throw new Error("external_tire_fact_page_contract_invalid"); }
const object = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
const full = (pattern: RegExp, v: unknown): v is string => typeof v === "string" && pattern.exec(v)?.[0] === v;
const id = (v: unknown, maximum = 64): v is string => full(new RegExp(`^[A-Za-z0-9_-]{1,${maximum}}$`), v);
const hex = (v: unknown): v is string => full(/^[a-f0-9]{64}$/, v);
function closed(v: unknown, keys: string[]): asserts v is Obj {
  ensure(object(v) && Object.keys(v).length === keys.length && keys.every(key => Object.hasOwn(v, key)));
}
function unicode(v: string) { return ![...v].some(c => { const cp = c.codePointAt(0)!; return cp >= 0xd800 && cp <= 0xdfff; }); }
/** Detached JSON values only: no getters, sparse arrays, symbols or toJSON calls. */
function bounded(input: unknown): unknown {
  let nodes = 0;
  const ancestors = new Set<object>();
  function visit(v: unknown, depth: number): unknown {
    ensure(depth <= MAX_DEPTH && ++nodes <= MAX_NODES);
    if (typeof v === "string") { ensure(v.length <= EXTERNAL_TIRE_FACT_PAGE_MAX_BYTES && unicode(v)); return v; }
    if (v === null || typeof v === "boolean") return v;
    if (typeof v === "number") { ensure(Number.isFinite(v)); return v; }
    ensure(typeof v === "object" && v !== null);
    const array = Array.isArray(v), prototype = Object.getPrototypeOf(v);
    ensure(array ? prototype === Array.prototype : prototype === Object.prototype || prototype === null);
    ensure(!ancestors.has(v)); ancestors.add(v);
    const descriptors = Object.getOwnPropertyDescriptors(v), keys = Object.keys(v);
    ensure(keys.length <= MAX_NODES && Object.getOwnPropertySymbols(v).length === 0
      && Object.getOwnPropertyNames(v).length === keys.length + (array ? 1 : 0));
    let result: unknown;
    if (array) {
      ensure(keys.length === v.length && keys.every((key, index) => key === String(index)));
      result = keys.map(key => { ensure("value" in descriptors[key]); return visit(descriptors[key].value, depth + 1); });
    } else {
      const copy = Object.create(null) as Obj;
      for (const key of keys) {
        ensure(key.length <= EXTERNAL_TIRE_FACT_PAGE_MAX_BYTES && unicode(key) && "value" in descriptors[key]);
        copy[key] = visit(descriptors[key].value, depth + 1);
      }
      result = copy;
    }
    ancestors.delete(v);
    return result;
  }
  const result = visit(input, 0);
  ensure(new TextEncoder().encode(JSON.stringify(result)).byteLength <= EXTERNAL_TIRE_FACT_PAGE_MAX_BYTES);
  return result;
}
function decodeBase64(value: string): Uint8Array {
  const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4));
  ensure(btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "") === value);
  return Uint8Array.from(binary, c => c.charCodeAt(0));
}
/** Shape and canonical encoding only. The SDK cannot authenticate the server HMAC. */
function cursor(value: unknown): Cursor {
  ensure(full(/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/, value) && value.length <= 2048);
  const [body, signature] = value.split(".");
  const raw = decodeBase64(body); ensure(raw.byteLength <= 1500 && decodeBase64(signature).byteLength === 32);
  const text = new TextDecoder("utf-8", { fatal: true }).decode(raw), v: unknown = JSON.parse(text);
  const keys = ["schema", "key_id", "owner", "route", "source_id", "query_id", "verification_id", "limit", "issued", "expires", "window", "context", "after"];
  closed(v, keys);
  ensure(v.schema === "external-tire-facts-cursor@1" && full(/^[a-f0-9]{32}$/, v.key_id)
    && hex(v.owner) && v.route === ROUTE && id(v.source_id, 80) && id(v.query_id) && id(v.verification_id)
    && typeof v.limit === "number" && Number.isInteger(v.limit) && v.limit >= 1 && v.limit <= 20
    && typeof v.issued === "number" && Number.isSafeInteger(v.issued) && v.issued >= 0
    && typeof v.expires === "number" && Number.isSafeInteger(v.expires) && v.expires >= 0
    && v.expires > v.issued && v.expires - v.issued <= 900 && hex(v.window) && hex(v.context) && id(v.after));
  // Canonical re-encoding also rejects duplicate JSON keys, alternate escapes and nested values.
  ensure(JSON.stringify(Object.fromEntries(Object.keys(v).sort().map(key => [key, v[key]]))) === text);
  return v as unknown as Cursor;
}
function binds(c: Cursor, request: ExternalTireFactPageRequest) {
  return c.source_id === request.source_id && c.query_id === request.query_id && c.verification_id === request.verification_id
    && c.limit === (request.limit ?? 20);
}
export function isExternalTireFactPageRequest(value: unknown, keyId?: string): value is ExternalTireFactPageRequest {
  try {
    ensure(object(value) && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null));
    const required = ["source_id", "query_id", "verification_id"], keys = Object.keys(value);
    ensure(required.every(key => Object.hasOwn(value, key)) && keys.every(key => required.includes(key) || ["limit", "cursor", "signal"].includes(key))
      && Object.getOwnPropertySymbols(value).length === 0 && Object.getOwnPropertyNames(value).length === keys.length
      && keys.every(key => "value" in Object.getOwnPropertyDescriptor(value, key)!));
    ensure(id(value.source_id, 80) && id(value.query_id) && id(value.verification_id));
    ensure(value.limit === undefined || typeof value.limit === "number");
    const limit = value.limit ?? 20;
    ensure(typeof limit === "number" && Number.isInteger(limit) && limit >= 1 && limit <= 20);
    ensure(value.signal === undefined || (typeof AbortSignal !== "undefined" && value.signal instanceof AbortSignal));
    if (value.cursor !== undefined) {
      const before = cursor(value.cursor);
      ensure(binds(before, value as unknown as ExternalTireFactPageRequest) && (keyId === undefined || before.key_id === keyId));
    }
    return true;
  } catch { return false; }
}
export function isExternalTireFactPage(value: unknown): value is ExternalTireFactPage {
  try {
    const v = bounded(value); closed(v, ["schema", "items", "next_cursor", "limit", "data_state", "source_refresh_performed"]);
    ensure(v.schema === "external-tire-fact-page@1" && v.data_state === "local_snapshot" && v.source_refresh_performed === false
      && typeof v.limit === "number" && Number.isInteger(v.limit) && v.limit >= 1 && v.limit <= 20
      && Array.isArray(v.items) && v.items.length >= 1 && v.items.length <= v.limit);
    let previous = "", observation = "";
    for (const item of v.items) {
      ensure(new TextEncoder().encode(JSON.stringify(item)).byteLength <= ITEM_MAX_BYTES
        && isExternalTireFactResult({ status: "projected", reason: "projected", item }));
      ensure(previous < item.identity.variant_id); previous = item.identity.variant_id;
      const current = JSON.stringify([item.observation.source_id, item.observation.snapshot_id, item.observation.raw_hash, item.observation.parser_version]);
      ensure(observation === "" || observation === current); observation = current;
    }
    if (v.next_cursor !== null) {
      ensure(v.items.length === v.limit);
      const next = cursor(v.next_cursor);
      ensure(next.limit === v.limit && next.source_id === v.items[0].observation.source_id && next.after === previous);
    }
    return true;
  } catch { return false; }
}
/** Correlation checks against the pre-await request snapshot; no HMAC/ownership claim. */
export function tireFactPageMatchesRequest(value: ExternalTireFactPage, request: ExternalTireFactPageRequest, keyId: string): boolean {
  try {
    ensure(value.limit === (request.limit ?? 20) && value.items.every(item => item.observation.source_id === request.source_id));
    const before = request.cursor === undefined ? undefined : cursor(request.cursor);
    if (before) ensure(before.key_id === keyId && binds(before, request) && value.items[0].identity.variant_id > before.after);
    if (value.next_cursor !== null) {
      const next = cursor(value.next_cursor); ensure(next.key_id === keyId && binds(next, request));
      if (before) for (const field of ["owner", "issued", "expires", "window", "context"] as const) ensure(next[field] === before[field]);
    }
    return true;
  } catch { return false; }
}
