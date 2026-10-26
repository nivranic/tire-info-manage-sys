import type {
  BinaryQuarantineReviewRequestV2, BinaryQuarantineReviewStateV2,
} from "@tire/domain-types";
import type { RawEvidenceContextFence } from "./raw-evidence-v2";

type Obj = Record<string, unknown>;
type Send = <T>(path: string, init?: RequestInit, format?: "json" | "blob" | "response") => Promise<T>;
const METHOD = "sha256_bound_reviewed_mapping";
const MAX_BYTES = 8 * 1024 * 1024;
const provenanceKeys = ["contract", "method", "mapping_id", "source_raw_hash", "bundle_id", "mapping_file_sha256"];
const requestKeys = ["action", "expected_revision", "operator", "reason", "confirmed_loss", "expected_binding_hash"];
const stateKeys = ["quarantine_id", "scope", "state", "revision", "can_approve", "restriction", "baseline_snapshot_id", "current_snapshot_id", "applied_query_id", "comparison", "history", "history_truncated", "evidence_format", "binding_contract", "binding_hash", "raw_evidence"];
const evidenceKeys = ["body_encoding", "body", "raw_capture_id", "raw_hash", "byte_count", "content_type", "source_url", "parser_version", "parser_identity", "parse_provenance"];
const states = ["pending", "restricted", "stale_baseline", "kept_quarantined", "expired", "approved_waiting_online", "applied_on_online_fetch"];

export class QuarantineReviewContractError extends Error {
  constructor(public readonly code = "quarantine_review_contract_invalid") {
    super("隔离审批请求或响应不符合完整合同，请重新读取并核对。");
    this.name = "QuarantineReviewContractError";
  }
}
export class QuarantineReviewContextError extends Error {
  readonly code = "quarantine_review_context_changed";
  constructor() { super("隔离审批的上下文已变化，请重新读取并核对。"); this.name = "QuarantineReviewContextError"; }
}
function check(condition: unknown, code?: string): asserts condition {
  if (!condition) throw new QuarantineReviewContractError(code);
}
const object = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v)
  && (Object.getPrototypeOf(v) === Object.prototype || Object.getPrototypeOf(v) === null);
const shape = (v: unknown, required: readonly string[], optional: readonly string[] = []): v is Obj => object(v)
  && required.every(key => Object.hasOwn(v, key))
  && Reflect.ownKeys(v).every(key => typeof key === "string" && (required.includes(key) || optional.includes(key)));
const exact = (v: unknown, fields: readonly string[]): v is Obj => shape(v, fields) && Reflect.ownKeys(v).length === fields.length;
const integer = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const id = (v: unknown): v is string => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const mapping = (v: unknown): v is string => typeof v === "string" && /^xiaomi-su7-first-generation-pdf@[1-9][0-9]{0,8}$/.test(v);
const one = (v: unknown, options: readonly string[]): v is string => typeof v === "string" && options.includes(v);
function unicode(value: string): boolean {
  for (let i = 0; i < value.length; i++) {
    const c = value.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) { const next = value.charCodeAt(++i); if (!(next >= 0xdc00 && next <= 0xdfff)) return false; }
    else if (c >= 0xdc00 && c <= 0xdfff) return false;
  }
  return true;
}
const string = (v: unknown, min = 0, max = 8192): v is string => typeof v === "string" && unicode(v)
  && Array.from(v).length >= min && Array.from(v).length <= max;
// DescriptionText preserves whitespace and CR/LF/TAB; its limits count Unicode code points.
const description = (v: unknown, min: number, max: number) => string(v, min, max) && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(v);
const text = (v: unknown, max = 8192): v is string => string(v, 1, max) && !!v.trim() && !v.includes("\0");
const nullableString = (v: unknown) => v === null || string(v);
const nullableId = (v: unknown) => v === null || id(v);
const list = (v: unknown, accept: (item: unknown) => boolean, min = 0, max = 10000): v is unknown[] => Array.isArray(v)
  && v.length >= min && v.length <= max && v.every(accept);
const strings = (v: unknown) => list(v, item => string(item));
const timestamp = (v: unknown): v is string => typeof v === "string"
  && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|\+00:00)$/.test(v) && Number.isFinite(Date.parse(v));
function laterTimestamp(end: string, start: string): boolean {
  const endSecond = Date.parse(`${end.slice(0, 19)}Z`), startSecond = Date.parse(`${start.slice(0, 19)}Z`);
  if (endSecond !== startSecond) return endSecond > startSecond;
  const endFraction = /\.(\d+)/.exec(end)?.[1] ?? "", startFraction = /\.(\d+)/.exec(start)?.[1] ?? "";
  const width = Math.max(endFraction.length, startFraction.length);
  return endFraction.padEnd(width, "0") > startFraction.padEnd(width, "0");
}
function provenance(v: unknown): v is Obj {
  return exact(v, provenanceKeys) && v.contract === "vehicle-pdf-parse@1" && v.method === METHOD && mapping(v.mapping_id)
    && hash(v.source_raw_hash) && hash(v.bundle_id) && hash(v.mapping_file_sha256);
}
function parser(v: unknown): v is Obj {
  return exact(v, ["bundle_id", "parser_digest", "deployment_revision"]) && hash(v.bundle_id) && hash(v.parser_digest) && integer(v.deployment_revision, 1);
}
function axle(v: unknown): v is Obj {
  return exact(v, ["size", "load_index", "speed_rating", "oe_mark", "manufacturer_product_code", "matched_tire_variant_id"])
    && text(v.size, 24) && ["load_index", "speed_rating", "oe_mark", "manufacturer_product_code", "matched_tire_variant_id"].every(key => nullableString(v[key]));
}
function fitment(v: unknown): v is Obj {
  return exact(v, ["id", "trim_id", "trim_name", "wheel_option_name", "wheel_diameter_inches", "availability", "front", "rear", "staggered", "source_tire_description", "constraints", "source_description", "evidence_locator"])
    && id(v.id) && text(v.trim_id, 120) && text(v.trim_name) && text(v.wheel_option_name) && integer(v.wheel_diameter_inches, 10, 30)
    && one(v.availability, ["standard", "optional", "unavailable"]) && axle(v.front) && axle(v.rear)
    && typeof v.staggered === "boolean" && v.staggered === (v.front.size !== v.rear.size)
    && (v.front.size as string).endsWith(`R${v.wheel_diameter_inches}`) && (v.rear.size as string).endsWith(`R${v.wheel_diameter_inches}`)
    && nullableString(v.source_tire_description) && strings(v.constraints) && text(v.source_description) && text(v.evidence_locator);
}
function vehicle(v: unknown): boolean {
  return shape(v, ["id", "manufacturer", "model", "generation", "model_year", "region", "source_vehicle_id"], ["source_version"])
    && v.id === "xiaomi-su7-first-generation" && exact(v.manufacturer, ["id", "name"]) && text(v.manufacturer.id, 80) && text(v.manufacturer.name, 160)
    && text(v.model, 160) && text(v.generation, 80) && (v.model_year === null || integer(v.model_year, 1900, 2100)) && text(v.region, 80) && text(v.source_vehicle_id, 80)
    && (!Object.hasOwn(v, "source_version") || v.source_version === null || string(v.source_version) || typeof v.source_version === "number" && Number.isFinite(v.source_version));
}
function trim(v: unknown): v is Obj {
  return exact(v, ["id", "name", "source_trim_id", "model_year", "wheel_option_ids"]) && text(v.id, 120) && text(v.name, 160) && text(v.source_trim_id, 80)
    && (v.model_year === null || integer(v.model_year, 1900, 2100)) && list(v.wheel_option_ids, id, 1, 100)
    && new Set(v.wheel_option_ids).size === v.wheel_option_ids.length;
}
function documents(v: unknown): boolean {
  return list(v, item => exact(item, ["url", "title", "status"]) && text(item.url) && (item.title === null || text(item.title)) && item.status === "official_source_link", 0, 100);
}
function coverage(v: unknown): boolean {
  return exact(v, ["axle_sizes", "wheel_options", "trim_mapping", "model_year", "exact_tire_sku", "oe_mark", "notice"])
    && ["axle_sizes", "wheel_options", "trim_mapping", "model_year", "exact_tire_sku", "oe_mark"].every(key => typeof v[key] === "boolean") && text(v.notice);
}
function payload(v: unknown): v is Obj {
  if (!shape(v, ["vehicle", "trims", "fitments", "parse_method", "mapping_id", "parse_provenance"], ["footnotes", "documents", "coverage"])
    || !vehicle(v.vehicle) || !list(v.trims, trim, 1, 12) || !list(v.fitments, fitment, 1, 100)
    || v.parse_method !== METHOD || !mapping(v.mapping_id) || !provenance(v.parse_provenance)
    || v.parse_provenance.mapping_id !== v.mapping_id
    || Object.hasOwn(v, "footnotes") && !strings(v.footnotes) || Object.hasOwn(v, "documents") && !documents(v.documents)
    || Object.hasOwn(v, "coverage") && !coverage(v.coverage)) return false;
  const trims = v.trims as Obj[], fits = v.fitments as Obj[];
  if (new Set(trims.map(item => item.id)).size !== trims.length || new Set(fits.map(item => item.id)).size !== fits.length) return false;
  return fits.every(item => trims.some(row => row.id === item.trim_id && row.name === item.trim_name)) && trims.every(row => {
    const expected = fits.filter(item => item.trim_id === row.id).map(item => item.id), actual = row.wheel_option_ids as string[];
    return expected.length === actual.length && actual.every(key => expected.includes(key));
  });
}
function historyEvent(v: unknown): v is Obj {
  return exact(v, ["id", "quarantine_id", "revision", "action", "operator", "reason", "created_at", "expires_at"])
    && id(v.id) && id(v.quarantine_id) && integer(v.revision, 1) && one(v.action, ["approve", "keep_quarantined"])
    && description(v.operator, 1, 80) && description(v.reason, 5, 2000) && timestamp(v.created_at) && timestamp(v.expires_at)
    && laterTimestamp(v.expires_at, v.created_at);
}

/** Schema and internal relationships only; original bytes and source permission remain separate gates. */
export function assertBinaryQuarantineReviewStateV2(value: unknown, requestedId: string): asserts value is BinaryQuarantineReviewStateV2 {
  check(id(requestedId) && exact(value, stateKeys));
  check(value.quarantine_id === requestedId && value.scope === "local_workspace" && one(value.state, states) && integer(value.revision)
    && typeof value.can_approve === "boolean" && (value.restriction === null || value.restriction === "identity_or_alignment_requires_repair")
    && id(value.baseline_snapshot_id) && nullableId(value.current_snapshot_id) && nullableId(value.applied_query_id)
    && value.evidence_format === "raw-evidence-v2" && value.binding_contract === "vehicle-binary@1" && hash(value.binding_hash));
  check(exact(value.comparison, ["before", "candidate"]) && payload(value.comparison.before) && payload(value.comparison.candidate));
  const raw = value.raw_evidence, candidate = value.comparison.candidate;
  check(exact(raw, evidenceKeys) && raw.body_encoding === "binary" && raw.body === null && id(raw.raw_capture_id) && hash(raw.raw_hash)
    && integer(raw.byte_count, 1, MAX_BYTES) && raw.content_type === "application/pdf" && text(raw.source_url) && text(raw.parser_version, 100)
    && parser(raw.parser_identity) && provenance(raw.parse_provenance));
  const rawProvenance = raw.parse_provenance;
  check(rawProvenance.source_raw_hash === raw.raw_hash && rawProvenance.bundle_id === raw.parser_identity.bundle_id
    && provenanceKeys.every(key => (candidate.parse_provenance as Obj)[key] === rawProvenance[key]));
  check(list(value.history, historyEvent, 0, 100) && typeof value.history_truncated === "boolean");
  const history = value.history as Obj[];
  check(new Set(history.map(item => item.id)).size === history.length
    && history.every((item, i) => i === 0 || Number(history[i - 1].revision) > Number(item.revision))
    && (value.revision === 0 ? history.length === 0 : history.length > 0 && history[0].revision === value.revision)
    && (!value.history_truncated || history.length === 100));
  const applied = value.applied_query_id !== null, stale = value.current_snapshot_id !== value.baseline_snapshot_id,
    restricted = value.restriction !== null;
  check(value.can_approve === !(applied || stale || restricted));
  // Preserve the server's precedence; expiry is server time, never the caller's clock.
  if (applied) check(value.state === "applied_on_online_fetch" && history.length > 0 && history[0].action === "approve");
  else if (stale) check(value.state === "stale_baseline");
  else if (restricted) check(value.state === "restricted");
  else if (history.length === 0) check(value.state === "pending");
  else if (history[0].action === "keep_quarantined") check(value.state === "kept_quarantined");
  else check(value.state === "expired" || value.state === "approved_waiting_online");
}

type Context = { check(): void; stage<T>(operation: () => Promise<T>): Promise<T> };
function context(fence: RawEvidenceContextFence, signal: AbortSignal | undefined, authority: () => number): Context {
  check(fence && typeof fence.assertCurrent === "function", "quarantine_review_context_required");
  const assertCurrent = fence.assertCurrent.bind(fence), epoch = authority();
  const current = () => {
    if (signal?.aborted) throw new DOMException("请求已取消", "AbortError");
    check(assertCurrent() === undefined, "quarantine_review_context_required");
    if (authority() !== epoch) throw new QuarantineReviewContextError();
    if (signal?.aborted) throw new DOMException("请求已取消", "AbortError");
  };
  current();
  return { check: current, async stage<T>(operation: () => Promise<T>): Promise<T> {
    current();
    let result: T;
    try { result = await operation(); } catch (cause) { current(); throw cause; }
    current(); return result;
  } };
}
function requestBody(value: unknown): string {
  check(exact(value, requestKeys) && one(value.action, ["approve", "keep_quarantined"]) && integer(value.expected_revision)
    && description(value.operator, 1, 80) && description(value.reason, 5, 2000) && value.confirmed_loss === true && hash(value.expected_binding_hash));
  return JSON.stringify({ action: value.action, expected_revision: value.expected_revision, operator: value.operator,
    reason: value.reason, confirmed_loss: true, expected_binding_hash: value.expected_binding_hash });
}
/** Shares the normal request/error pipeline; never retries a possibly committed write. */
export function createQuarantineReviewV2Api(send: Send, authority: () => number) {
  async function exchange(idValue: string, suffix: "review" | "reviews", init: RequestInit, ctx: Context, expectedStatus: 200 | 201): Promise<BinaryQuarantineReviewStateV2> {
    check(id(idValue)); ctx.check();
    const response = await ctx.stage(() => send<Response>(`/v1/quarantines/${encodeURIComponent(idValue)}/${suffix}?mode=history&format=raw-evidence-v2`, init, "response"));
    ctx.check(); check(response instanceof Response && response.status === expectedStatus);
    const value: unknown = await ctx.stage(() => response.json());
    ctx.check(); assertBinaryQuarantineReviewStateV2(value, idValue); ctx.check();
    return value;
  }
  return {
    quarantineReviewV2: async (idValue: string, fence: RawEvidenceContextFence, signal?: AbortSignal): Promise<BinaryQuarantineReviewStateV2> => {
      const ctx = context(fence, signal, authority);
      return exchange(idValue, "review", { signal }, ctx, 200);
    },
    reviewQuarantineV2: async (idValue: string, value: BinaryQuarantineReviewRequestV2, expectedAccountId: string, fence: RawEvidenceContextFence, signal?: AbortSignal): Promise<BinaryQuarantineReviewStateV2> => {
      const ctx = context(fence, signal, authority);
      check(id(expectedAccountId));
      const body = requestBody(value); ctx.check();
      return exchange(idValue, "reviews", { method: "POST", headers: { "X-Tire-Expected-Account": expectedAccountId }, body, signal }, ctx, 201);
    },
  };
}
