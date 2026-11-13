import type { ExternalSafetyGatePage, ExternalSafetyGateRequest } from "@tire/domain-types";

export const EXTERNAL_SAFETY_GATE_MAX_BYTES = 2 * 1024 * 1024;
const BASE = "https://ec.europa.eu/safety-gate-alerts";
const facts = new Set(["category", "product", "brand", "name", "model_number", "batch_number", "barcode", "risk_type", "danger", "measures", "recall_url", "description", "notifying_country", "country_of_origin", "type", "level", "online_trader", "company_recall_code", "production_dates"]);
type Obj = Record<string, unknown>;
function ensure(value: unknown): asserts value { if (!value) throw new Error("external_safety_gate_contract_invalid"); }
const full = (pattern: RegExp, v: unknown): v is string => typeof v === "string" && pattern.exec(v)?.[0] === v;
const id = (v: unknown) => full(/^[A-Za-z0-9_-]{1,64}$/, v);
const hash = (v: unknown) => full(/^[a-f0-9]{64}$/, v);
const reportId = (v: unknown) => full(/^[1-9][0-9]{0,11}$/, v);
const pageLimit = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 1 && v <= 20;
const object = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
function closed(v: unknown, keys: string[]): asserts v is Obj {
  ensure(object(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k)));
}
function scalar(v: unknown, max: number): v is string {
  return typeof v === "string" && [...v].length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(v)
    && ![...v].some(c => { const n = c.codePointAt(0)!; return n >= 0xd800 && n <= 0xdfff; });
}
function date(v: unknown) {
  return full(/^\d{4}-\d\d-\d\d$/, v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v;
}
function time(v: unknown): bigint {
  ensure(typeof v === "string");
  const m = /^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(v);
  ensure(m && m[0] === v); const ms = Date.parse(m[1] + "Z");
  ensure(Number.isFinite(ms) && new Date(ms).toISOString().slice(0, 19) === m[1]);
  return BigInt(ms) * 1000n + BigInt((m[2] || "").padEnd(6, "0"));
}
function plain(v: unknown): asserts v is Obj {
  ensure(object(v) && [Object.prototype, null].includes(Object.getPrototypeOf(v)));
  const keys = Reflect.ownKeys(v);
  ensure(keys.length <= 1000 && keys.every(k => typeof k === "string" && Object.getOwnPropertyDescriptor(v, k)?.enumerable
    && "value" in Object.getOwnPropertyDescriptor(v, k)!));
}
function bounded(value: unknown) {
  let count = 0;
  const pending = [{ value, depth: 0 }], seen = new Set<object>();
  while (pending.length) {
    const { value: v, depth } = pending.pop()!;
    ensure(++count <= 4096 && depth <= 6);
    if (typeof v === "string") { ensure(scalar(v, EXTERNAL_SAFETY_GATE_MAX_BYTES)); continue; }
    if (v === null || typeof v === "boolean" || typeof v === "number" && Number.isFinite(v)) continue;
    ensure(v !== null && typeof v === "object" && !seen.has(v)); seen.add(v);
    if (Array.isArray(v)) {
      ensure(Object.getPrototypeOf(v) === Array.prototype && v.length <= 1000
        && Reflect.ownKeys(v).length === v.length + 1 && Object.keys(v).every((k, i) => k === String(i)));
      for (let i = 0; i < v.length; i++) { const d = Object.getOwnPropertyDescriptor(v, String(i)); ensure(d && "value" in d); pending.push({ value: d.value, depth: depth + 1 }); }
    } else {
      plain(v);
      for (const k of Object.keys(v)) pending.push({ value: Object.getOwnPropertyDescriptor(v, k)!.value, depth: depth + 1 });
    }
  }
  ensure(new TextEncoder().encode(JSON.stringify(value)).byteLength <= EXTERNAL_SAFETY_GATE_MAX_BYTES);
}
function canonical(v: unknown): unknown {
  return object(v) ? Object.fromEntries(Object.keys(v).sort().map(k => [k, canonical(v[k])])) : v;
}
function decodePart(value: string) {
  const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4));
  ensure(btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "") === value);
  return Uint8Array.from(binary, c => c.charCodeAt(0));
}
/** Only the server can authenticate the HMAC; this checks transport shape/binding. */
function cursor(value: unknown) {
  ensure(full(/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/, value) && value.length <= 2048);
  const [raw, signature] = value.split("."); ensure(decodePart(signature).length === 32);
  const text = new TextDecoder("utf-8", { fatal: true }).decode(decodePart(raw)), v: unknown = JSON.parse(text);
  closed(v, ["schema", "key_id", "owner", "route", "limit", "filters", "expires", "context", "after"]);
  closed(v.filters, ["report_id", "query_id", "mode"]); closed(v.context, ["window", "count"]);
  ensure(v.schema === "external-cursor@1" && full(/^[a-f0-9]{32}$/, v.key_id) && hash(v.owner)
    && v.route === "safety-gate-report-alerts" && pageLimit(v.limit)
    && reportId(v.filters.report_id) && id(v.filters.query_id) && v.filters.mode === "history"
    && typeof v.expires === "number" && Number.isSafeInteger(v.expires) && v.expires > 0
    && hash(v.context.window) && typeof v.context.count === "number" && Number.isInteger(v.context.count)
    && v.context.count >= 1 && v.context.count <= 1000 && typeof v.after === "number" && Number.isInteger(v.after)
    && v.after > 0 && v.after < v.context.count && v.after % v.limit === 0
    && JSON.stringify(canonical(v)) === text);
  return { key: v.key_id as string, owner: v.owner as string, report: v.filters.report_id as string, query: v.filters.query_id as string,
    limit: v.limit, expires: v.expires, window: v.context.window as string, count: v.context.count, after: v.after };
}
export function isExternalSafetyGateRequest(value: unknown, keyId: string): value is ExternalSafetyGateRequest {
  try {
    plain(value); const required = ["report_id", "query_id", "mode"];
    ensure(required.every(k => Object.hasOwn(value, k)) && Object.keys(value).every(k => [...required, "limit", "cursor", "signal"].includes(k)));
    ensure(reportId(value.report_id) && id(value.query_id) && value.mode === "history" && pageLimit(value.limit === undefined ? 20 : value.limit));
    ensure(value.signal === undefined || typeof AbortSignal !== "undefined" && value.signal instanceof AbortSignal);
    if (value.cursor !== undefined) { const c = cursor(value.cursor); ensure(c.key === keyId && c.report === value.report_id && c.query === value.query_id && c.limit === (value.limit ?? 20)); }
    return true;
  } catch { return false; }
}
export function isExternalSafetyGatePage(value: unknown): value is ExternalSafetyGatePage {
  try {
    bounded(value); closed(value, ["schema", "data_state", "source_refresh_performed", "query_id", "report", "observation", "items", "limit", "next_cursor"]);
    ensure(value.schema === "external-safety-gate-alert-page@1" && value.data_state === "local_snapshot"
      && value.source_refresh_performed === false && id(value.query_id) && pageLimit(value.limit));
    closed(value.report, ["report_id", "reference", "published_date"]);
    ensure(reportId(value.report.report_id) && full(/^Report-\d{4}-[0-9]{1,3}$/, value.report.reference)
      && +value.report.reference.split("-").at(-1)! >= 1 && +value.report.reference.split("-").at(-1)! <= 53 && date(value.report.published_date));
    closed(value.observation, ["source_id", "snapshot_id", "raw_hash", "parser_version", "source_url", "observed_at", "verified_at"]);
    const o = value.observation;
    ensure(o.source_id === "eu-safety-gate" && id(o.snapshot_id) && hash(o.raw_hash) && scalar(o.parser_version, 100) && o.parser_version.length > 0
      && o.source_url === `${BASE}/api/download/weeklyReport/detail/xml/${value.report.report_id}?language=en&search=WEB_REPORT%7C:%7C${value.report.report_id},`
      && time(o.observed_at) <= time(o.verified_at));
    ensure(Array.isArray(value.items) && value.items.length <= value.limit);
    const ids = new Set(), cases = new Set(); let shape: string | undefined;
    for (const item of value.items) {
      closed(item, ["alert_id", "case_number", "published_date", "source_url", "applicability", "facts"]);
      ensure(full(/^-?[1-9][0-9]{0,11}$/, item.alert_id) && scalar(item.case_number, 80) && item.case_number.length > 0
        && date(item.published_date) && item.source_url === `${BASE}/screen/webReport/alertDetail/${item.alert_id}` && item.applicability === "not_assessed"
        && !ids.has(item.alert_id) && !cases.has(item.case_number)); ids.add(item.alert_id); cases.add(item.case_number);
      plain(item.facts); const projectedFacts = item.facts, keys = Object.keys(projectedFacts).sort();
      ensure(keys.every(k => facts.has(k) && (projectedFacts[k] === null || scalar(projectedFacts[k], 60000))));
      const current = JSON.stringify(keys); ensure(shape === undefined || shape === current); shape = current;
    }
    if (value.next_cursor !== null) {
      const c = cursor(value.next_cursor); ensure(value.items.length === value.limit && c.report === value.report.report_id && c.query === value.query_id && c.limit === value.limit);
    }
    return true;
  } catch { return false; }
}
export function safetyGatePageMatchesRequest(value: ExternalSafetyGatePage, request: ExternalSafetyGateRequest, keyId: string) {
  try {
    ensure(value.query_id === request.query_id && value.report.report_id === request.report_id && value.limit === (request.limit ?? 20));
    const previous = request.cursor === undefined ? null : cursor(request.cursor);
    const next = value.next_cursor === null ? null : cursor(value.next_cursor);
    if (previous) ensure(value.items.length === Math.min(value.limit, previous.count - previous.after)
      && (next !== null) === (previous.after + value.items.length < previous.count));
    if (next) ensure(next.key === keyId && next.after === (previous?.after ?? 0) + value.items.length
      && (!previous || next.window === previous.window && next.count === previous.count && next.expires === previous.expires && next.owner === previous.owner));
    return true;
  } catch { return false; }
}
