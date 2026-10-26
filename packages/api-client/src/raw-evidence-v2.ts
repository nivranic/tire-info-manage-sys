import type {
  VehicleEvidenceV2, RawCaptureEvidenceV2, QuarantineEvidenceV2,
} from "@tire/domain-types";

type ObjectValue = Record<string, unknown>;
type Metadata = VehicleEvidenceV2 | RawCaptureEvidenceV2 | QuarantineEvidenceV2;
type Endpoint = "vehicle-evidence" | "captures" | "quarantines";
type Send = <T>(path: string, init?: RequestInit, format?: "json" | "blob" | "response") => Promise<T>;
const MAX_BYTES = 8 * 1024 * 1024;
const METHOD = "sha256_bound_reviewed_mapping";
const rawKeys = ["evidence_format", "body_encoding", "body", "raw_capture_id", "raw_hash", "byte_count", "content_type", "content_path", "parse_method", "mapping_id"];
const vehicleKeys = ["id", "vehicle_id", "snapshot_id", "source_id", "source_url", "source_page", "parser_version", "parser_identity", "observed_at", "evidence_path", "quality_review", "verified_at", "data_state", "documents"];
const captureKeys = ["id", "query_id", "source_id", "target_kind", "source_url", "parser_version", "observed_at", "parser_identity", "query_state", "query_reason", "query", "processing_unconfirmed", "evidence_path", "data_state", "receipt_only", "storage_kind"];
const quarantineKeys = ["id", "query_id", "source_id", "source_url", "parser_version", "observed_at", "previous_snapshot_id", "status", "kind", "target_kind", "reason_codes", "metrics", "evidence_path", "data_state", "accepted", "candidates", "quality"];

export class RawEvidenceContractError extends Error {
  constructor(public readonly code = "raw_evidence_contract_invalid") {
    super("原件响应未通过完整性或合同校验，未返回可用内容。");
    this.name = "RawEvidenceContractError";
  }
}
export class RawEvidenceContextError extends Error {
  readonly code = "raw_evidence_context_changed";
  constructor() { super("读取原件的上下文已变化，请重新读取。"); this.name = "RawEvidenceContextError"; }
}
/** The caller captures its account/component authority before calling the SDK. Must throw synchronously when stale. */
export interface RawEvidenceContextFence { assertCurrent(): void }
export interface VerifiedRawEvidenceContent<T extends Metadata> { blob: Blob; metadata: T }

function requireContract(condition: unknown, code?: string): asserts condition {
  if (!condition) throw new RawEvidenceContractError(code);
}
const object = (v: unknown): v is ObjectValue => !!v && typeof v === "object" && !Array.isArray(v);
const shape = (v: unknown, required: readonly string[], optional: readonly string[] = []): v is ObjectValue =>
  object(v) && required.every(k => Object.hasOwn(v, k)) && Object.keys(v).every(k => required.includes(k) || optional.includes(k));
const exact = (v: unknown, keys: readonly string[]): v is ObjectValue => shape(v, keys) && Object.keys(v).length === keys.length;
function unicode(v: string): boolean {
  for (let i = 0; i < v.length; i++) {
    const c = v.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) { const next = v.charCodeAt(++i); if (!(next >= 0xdc00 && next <= 0xdfff)) return false; }
    else if (c >= 0xdc00 && c <= 0xdfff) return false;
  }
  return true;
}
const text = (v: unknown, max = 8192): v is string => typeof v === "string" && v.length > 0 && v.length <= max && unicode(v) && !/[\u0000-\u001f\u007f]/.test(v);
const id = (v: unknown): v is string => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const integer = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const number = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const ratio = (v: unknown) => number(v) && v >= 0 && v <= 1;
const hash = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const mapping = (v: unknown): v is string => typeof v === "string" && /^xiaomi-su7-first-generation-pdf@[1-9][0-9]{0,8}$/.test(v);
const one = (v: unknown, values: readonly string[]): v is string => typeof v === "string" && values.includes(v);
const nullableText = (v: unknown) => v === null || text(v);
const nullableId = (v: unknown) => v === null || id(v);
const time = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|\+00:00)$/.test(v) && Number.isFinite(Date.parse(v));
const nullableTime = (v: unknown) => v === null || time(v);
const list = (v: unknown, accept: (item: unknown) => boolean, max = 10000): v is unknown[] => Array.isArray(v) && v.length <= max && v.every(accept);
const strings = (v: unknown) => list(v, item => typeof item === "string" && unicode(item), 10000);
function json(v: unknown, depth = 0): boolean {
  if (depth > 30) return false;
  if (v === null || typeof v === "boolean" || number(v)) return true;
  if (typeof v === "string") return unicode(v);
  if (Array.isArray(v)) return v.length <= 10000 && v.every(item => json(item, depth + 1));
  return object(v) && Object.keys(v).length <= 10000 && Object.entries(v).every(([key, item]) => unicode(key) && json(item, depth + 1));
}
const jsonObject = (v: unknown) => object(v) && json(v);
function parser(v: unknown): boolean {
  return v === null || exact(v, ["bundle_id", "parser_digest", "deployment_revision"]) && hash(v.bundle_id) && hash(v.parser_digest) && integer(v.deployment_revision, 1);
}
function review(v: unknown): boolean {
  return v === null || exact(v, ["id", "quarantine_id", "revision", "action", "operator", "reason", "created_at", "expires_at"])
    && id(v.id) && id(v.quarantine_id) && integer(v.revision, 1) && one(v.action, ["approve", "keep_quarantined"])
    && text(v.operator) && text(v.reason) && time(v.created_at) && time(v.expires_at);
}
function documents(v: unknown): boolean {
  return list(v, item => exact(item, ["url", "title", "status"]) && text(item.url) && nullableText(item.title) && item.status === "official_source_link", 100);
}
const metricKeys = ["baseline_rows", "candidate_rows", "aligned_rows", "lost_rows", "row_loss_ratio", "known_fields", "lost_fields", "field_loss_ratio"];
function metrics(v: unknown): boolean {
  return exact(v, metricKeys) && metricKeys.every(k => k.endsWith("ratio") ? ratio(v[k]) : integer(v[k]));
}
function quality(v: unknown, depth = 0): boolean {
  if (depth > 8 || !shape(v, ["baseline_rows", "candidate_rows", "aligned_rows", "lost_rows", "row_loss_ratio", "known_fields", "field_loss_ratio", "ruleset", "threshold", "lost_field_count", "reason_codes", "lost_fields", "lost_row_keys", "ambiguous_keys"], ["groups", "namespace_reference_alignments"])) return false;
  return ["baseline_rows", "candidate_rows", "aligned_rows", "lost_rows", "known_fields", "lost_field_count"].every(k => integer(v[k]))
    && ["row_loss_ratio", "field_loss_ratio", "threshold"].every(k => ratio(v[k]))
    && text(v.ruleset) && strings(v.reason_codes) && strings(v.lost_row_keys) && strings(v.ambiguous_keys)
    && list(v.lost_fields, item => exact(item, ["row_key", "paths"]) && text(item.row_key) && strings(item.paths))
    && (!Object.hasOwn(v, "groups") || object(v.groups) && Object.values(v.groups).every(item => quality(item, depth + 1)))
    && (!Object.hasOwn(v, "namespace_reference_alignments") || list(v.namespace_reference_alignments, item => exact(item, ["baseline_key", "candidate_key", "entity_equivalence"])
      && text(item.baseline_key) && text(item.candidate_key) && item.entity_equivalence === false));
}
function axle(v: unknown): boolean {
  return exact(v, ["size", "load_index", "speed_rating", "oe_mark", "manufacturer_product_code", "matched_tire_variant_id"])
    && text(v.size, 24) && ["load_index", "speed_rating", "oe_mark", "manufacturer_product_code", "matched_tire_variant_id"].every(k => nullableText(v[k]));
}
function fitment(v: unknown): boolean {
  return exact(v, ["id", "trim_id", "trim_name", "wheel_option_name", "wheel_diameter_inches", "availability", "front", "rear", "staggered", "source_tire_description", "constraints", "source_description", "evidence_locator"])
    && id(v.id) && text(v.trim_id, 120) && text(v.trim_name) && text(v.wheel_option_name)
    && integer(v.wheel_diameter_inches, 10, 30) && one(v.availability, ["standard", "optional", "unavailable"])
    && axle(v.front) && axle(v.rear) && typeof v.staggered === "boolean" && nullableText(v.source_tire_description)
    && strings(v.constraints) && typeof v.source_description === "string" && unicode(v.source_description) && text(v.evidence_locator);
}
function vehicleDescription(v: unknown): boolean {
  return shape(v, ["id", "manufacturer", "model", "generation", "model_year", "region", "source_vehicle_id"], ["source_version"])
    && text(v.id, 80) && exact(v.manufacturer, ["id", "name"]) && text(v.manufacturer.id, 80) && text(v.manufacturer.name, 160)
    && text(v.model, 160) && text(v.generation, 80) && (v.model_year === null || integer(v.model_year, 1900, 2100))
    && text(v.region, 80) && text(v.source_vehicle_id, 80)
    && (!Object.hasOwn(v, "source_version") || v.source_version === null || typeof v.source_version === "string" && unicode(v.source_version) || number(v.source_version));
}
function provenance(v: unknown): boolean {
  return exact(v, ["contract", "method", "mapping_id", "source_raw_hash", "bundle_id", "mapping_file_sha256"])
    && v.contract === "vehicle-pdf-parse@1" && v.method === METHOD && mapping(v.mapping_id) && hash(v.source_raw_hash) && hash(v.bundle_id) && hash(v.mapping_file_sha256);
}
function coverage(v: unknown): boolean {
  return exact(v, ["axle_sizes", "wheel_options", "trim_mapping", "model_year", "exact_tire_sku", "oe_mark", "notice"])
    && ["axle_sizes", "wheel_options", "trim_mapping", "model_year", "exact_tire_sku", "oe_mark"].every(k => typeof v[k] === "boolean") && text(v.notice);
}
function vehiclePayload(v: unknown): boolean {
  if (!shape(v, ["vehicle", "trims", "fitments"], ["footnotes", "documents", "coverage", "parse_method", "mapping_id", "parse_provenance"])) return false;
  return vehicleDescription(v.vehicle)
    && list(v.trims, item => exact(item, ["id", "name", "source_trim_id", "model_year", "wheel_option_ids"])
      && text(item.id, 120) && text(item.name, 160) && text(item.source_trim_id, 80)
      && (item.model_year === null || integer(item.model_year, 1900, 2100)) && strings(item.wheel_option_ids), 12)
    && list(v.fitments, fitment, 100)
    && (!Object.hasOwn(v, "footnotes") || strings(v.footnotes)) && (!Object.hasOwn(v, "documents") || documents(v.documents))
    && (!Object.hasOwn(v, "coverage") || coverage(v.coverage))
    && (!Object.hasOwn(v, "parse_method") || v.parse_method === METHOD) && (!Object.hasOwn(v, "mapping_id") || mapping(v.mapping_id))
    && (!Object.hasOwn(v, "parse_provenance") || provenance(v.parse_provenance));
}
function tireCandidate(v: unknown): boolean {
  return exact(v, ["brand", "model", "manufacturer_product_code", "region", "size", "load_index", "speed_rating", "xl", "hl", "oe_mark", "acoustic_technology", "run_flat", "source_variant_name", "facts"])
    && text(v.brand, 120) && text(v.model, 200) && text(v.region, 40) && text(v.size, 24)
    && ["manufacturer_product_code", "load_index", "speed_rating", "oe_mark", "acoustic_technology", "source_variant_name"].every(k => nullableText(v[k]))
    && ["xl", "hl", "run_flat"].every(k => v[k] === null || typeof v[k] === "boolean") && jsonObject(v.facts);
}
function endpointPath(endpoint: Endpoint, requestedId: string): string {
  requireContract(id(requestedId));
  return `/v1/${endpoint}/${encodeURIComponent(requestedId)}`;
}
function raw(v: ObjectValue, endpoint: Endpoint, requestedId: string, parsed: boolean): void {
  requireContract(v.evidence_format === "raw-evidence-v2" && v.id === requestedId && id(v.id)
    && hash(v.raw_hash) && integer(v.byte_count, 1, MAX_BYTES));
  if (v.body_encoding === "utf-8") {
    requireContract(typeof v.body === "string" && unicode(v.body) && new TextEncoder().encode(v.body).byteLength === v.byte_count
      && nullableId(v.raw_capture_id) && one(v.content_type, ["text/html", "application/json", "text/javascript", "application/javascript", "text/plain"])
      && v.content_path === null && v.parse_method === null && v.mapping_id === null);
  } else {
    requireContract(v.body_encoding === "binary" && v.body === null && id(v.raw_capture_id) && v.content_type === "application/pdf"
      && v.content_path === `${endpointPath(endpoint, requestedId)}/content?mode=history` && v.source_id === "xiaomi-cn-vehicles");
    requireContract(parsed ? v.parse_method === METHOD && mapping(v.mapping_id) : v.parse_method === null && v.mapping_id === null);
  }
}
/** Synchronous schema assertion only; SDK methods separately verify the actual UTF-8 or PDF SHA-256 bytes. */
export function assertVehicleEvidenceV2(value: unknown, requestedId: string): asserts value is VehicleEvidenceV2 {
  requireContract(exact(value, [...rawKeys, ...vehicleKeys]));
  raw(value, "vehicle-evidence", requestedId, true);
  requireContract(value.snapshot_id === requestedId && text(value.vehicle_id, 80) && text(value.source_id, 80) && text(value.source_url)
    && text(value.source_page) && text(value.parser_version, 100) && parser(value.parser_identity) && time(value.observed_at)
    && value.evidence_path === endpointPath("vehicle-evidence", requestedId) && review(value.quality_review)
    && nullableTime(value.verified_at) && value.data_state === "local_snapshot" && documents(value.documents));
  requireContract(value.body_encoding === "binary" ? value.vehicle_id === "xiaomi-su7-first-generation" && value.parser_identity !== null : value.content_type === "application/json");
}
/** Synchronous schema assertion only; SDK methods separately verify the actual UTF-8 or PDF SHA-256 bytes. */
export function assertRawCaptureEvidenceV2(value: unknown, requestedId: string): asserts value is RawCaptureEvidenceV2 {
  requireContract(exact(value, [...rawKeys, ...captureKeys]));
  raw(value, "captures", requestedId, false);
  requireContract(value.raw_capture_id === requestedId && id(value.query_id) && text(value.source_id, 80) && one(value.target_kind, ["tire", "vehicle", "recall"])
    && text(value.source_url) && text(value.parser_version, 100) && time(value.observed_at) && parser(value.parser_identity)
    && text(value.query_state, 80) && nullableText(value.query_reason) && jsonObject(value.query)
    && typeof value.processing_unconfirmed === "boolean" && value.processing_unconfirmed === (value.query_state === "pending")
    && value.evidence_path === `${endpointPath("captures", requestedId)}?mode=history` && value.data_state === "local_snapshot"
    && value.receipt_only === true && one(value.storage_kind, ["object_store", "database_legacy"]));
  if (value.body_encoding === "binary") requireContract(value.parser_identity !== null && value.target_kind === "vehicle" && object(value.query) && value.query.vehicle_id === "xiaomi-su7-first-generation");
  if (value.target_kind === "vehicle" && value.body_encoding === "utf-8") requireContract(value.content_type === "application/json");
}
/** Synchronous schema assertion only; SDK methods separately verify the actual UTF-8 or PDF SHA-256 bytes. */
export function assertQuarantineEvidenceV2(value: unknown, requestedId: string): asserts value is QuarantineEvidenceV2 {
  requireContract(object(value));
  const rejected = value.kind === "response_rejected";
  const vehicle = value.kind === "field_loss" && value.target_kind === "vehicle";
  requireContract(exact(value, [...rawKeys, ...quarantineKeys, ...(rejected ? ["stage"] : vehicle ? ["vehicle_id", "vehicle_payload"] : [])]));
  raw(value, "quarantines", requestedId, vehicle);
  requireContract(id(value.query_id) && text(value.source_id, 80) && text(value.source_url) && text(value.parser_version, 100) && time(value.observed_at)
    && nullableId(value.previous_snapshot_id) && value.status === "quarantined" && one(value.target_kind, ["tire", "vehicle", "recall"])
    && strings(value.reason_codes) && value.evidence_path === `${endpointPath("quarantines", requestedId)}?mode=history`
    && value.data_state === "local_snapshot" && value.accepted === false);
  if (rejected) {
    requireContract(one(value.stage, ["parser", "schema"]) && value.previous_snapshot_id === null && value.metrics === null
      && Array.isArray(value.candidates) && value.candidates.length === 0 && value.quality === null);
    if (value.body_encoding === "binary") requireContract(value.target_kind === "vehicle");
  } else {
    requireContract(value.kind === "field_loss" && metrics(value.metrics) && quality(value.quality));
    if (vehicle) {
      requireContract(text(value.vehicle_id, 80) && list(value.candidates, fitment, 100) && vehiclePayload(value.vehicle_payload));
      const payload = value.vehicle_payload as ObjectValue;
      requireContract(object(payload.vehicle) && payload.vehicle.id === value.vehicle_id);
      if (value.body_encoding === "binary") {
        requireContract(value.vehicle_id === "xiaomi-su7-first-generation" && payload.parse_method === value.parse_method && payload.mapping_id === value.mapping_id
          && object(payload.parse_provenance) && payload.parse_provenance.method === value.parse_method
          && payload.parse_provenance.mapping_id === value.mapping_id && payload.parse_provenance.source_raw_hash === value.raw_hash);
      }
    } else requireContract(value.target_kind === "tire" && value.body_encoding === "utf-8" && list(value.candidates, tireCandidate));
  }
  if (value.target_kind === "vehicle" && value.body_encoding === "utf-8") requireContract(value.content_type === "application/json");
}

type Context = { check(): void; stage<T>(operation: () => Promise<T>): Promise<T> };
function context(fence: RawEvidenceContextFence, signal: AbortSignal | undefined, authority: () => number): Context {
  requireContract(fence && typeof fence.assertCurrent === "function", "raw_evidence_context_required");
  const assertCurrent = fence.assertCurrent.bind(fence), epoch = authority();
  const check = () => {
    if (signal?.aborted) throw new DOMException("请求已取消", "AbortError");
    requireContract(assertCurrent() === undefined, "raw_evidence_context_required");
    if (authority() !== epoch) throw new RawEvidenceContextError();
    if (signal?.aborted) throw new DOMException("请求已取消", "AbortError");
  };
  check();
  return { check, async stage<T>(operation: () => Promise<T>): Promise<T> {
    check();
    let result: T;
    try { result = await operation(); } catch (cause) { check(); throw cause; }
    check(); return result;
  } };
}
async function digest(bytes: ArrayBuffer, ctx: Context): Promise<string> {
  ctx.check();
  const subtle = globalThis.crypto?.subtle;
  requireContract(subtle && typeof subtle.digest === "function", "raw_evidence_crypto_unavailable");
  const result = await ctx.stage(() => subtle.digest("SHA-256", bytes));
  ctx.check();
  return Array.from(new Uint8Array(result), b => b.toString(16).padStart(2, "0")).join("");
}

/** Uses the existing request pipeline; the host transport is never invoked with a server-supplied path. */
export function createRawEvidenceV2Api(send: Send, authority: () => number) {
  async function metadata<T extends Metadata>(endpoint: Endpoint, requestedId: string, ctx: Context, signal: AbortSignal | undefined, decode: (value: unknown, requestedId: string) => asserts value is T): Promise<T> {
    ctx.check();
    const path = endpointPath(endpoint, requestedId);
    const value = await ctx.stage(() => send<unknown>(`${path}?format=raw-evidence-v2&mode=history`, { signal }));
    ctx.check(); decode(value, requestedId);
    if (value.body_encoding === "utf-8") {
      requireContract(typeof value.body === "string");
      const bytes = new TextEncoder().encode(value.body);
      const actual = await digest(bytes.buffer as ArrayBuffer, ctx);
      ctx.check(); requireContract(actual === value.raw_hash);
    }
    ctx.check();
    return Object.freeze(value);
  }
  async function readMetadata<T extends Metadata>(endpoint: Endpoint, requestedId: string, fence: RawEvidenceContextFence, signal: AbortSignal | undefined, decode: (value: unknown, requestedId: string) => asserts value is T): Promise<T> {
    const ctx = context(fence, signal, authority);
    const value = await metadata(endpoint, requestedId, ctx, signal, decode);
    ctx.check(); return value;
  }
  async function content<T extends Metadata>(endpoint: Endpoint, requestedId: string, fence: RawEvidenceContextFence, signal: AbortSignal | undefined, decode: (value: unknown, requestedId: string) => asserts value is T): Promise<VerifiedRawEvidenceContent<T>> {
    const ctx = context(fence, signal, authority);
    const value = await metadata(endpoint, requestedId, ctx, signal, decode);
    ctx.check(); requireContract(value.body_encoding === "binary", "raw_evidence_content_unavailable");
    const blob = await ctx.stage(() => send<Blob>(`${endpointPath(endpoint, requestedId)}/content?mode=history`, { signal }, "blob"));
    ctx.check();
    requireContract(blob instanceof Blob && blob.type === "application/pdf" && integer(blob.size, 1, MAX_BYTES) && blob.size === value.byte_count);
    const bytes = await ctx.stage(() => blob.arrayBuffer());
    ctx.check(); requireContract(bytes.byteLength === value.byte_count);
    const prefix = new Uint8Array(bytes, 0, Math.min(5, bytes.byteLength));
    requireContract(prefix.length === 5 && [37, 80, 68, 70, 45].every((b, i) => prefix[i] === b));
    const actual = await digest(bytes, ctx);
    ctx.check(); requireContract(actual === value.raw_hash);
    ctx.check(); return { blob, metadata: value };
  }
  return {
    vehicleEvidenceV2: (id: string, fence: RawEvidenceContextFence, signal?: AbortSignal) => readMetadata("vehicle-evidence", id, fence, signal, assertVehicleEvidenceV2),
    captureEvidenceV2: (id: string, fence: RawEvidenceContextFence, signal?: AbortSignal) => readMetadata("captures", id, fence, signal, assertRawCaptureEvidenceV2),
    quarantineEvidenceV2: (id: string, fence: RawEvidenceContextFence, signal?: AbortSignal) => readMetadata("quarantines", id, fence, signal, assertQuarantineEvidenceV2),
    vehicleEvidenceContent: (id: string, fence: RawEvidenceContextFence, signal?: AbortSignal) => content("vehicle-evidence", id, fence, signal, assertVehicleEvidenceV2),
    captureEvidenceContent: (id: string, fence: RawEvidenceContextFence, signal?: AbortSignal) => content("captures", id, fence, signal, assertRawCaptureEvidenceV2),
    quarantineEvidenceContent: (id: string, fence: RawEvidenceContextFence, signal?: AbortSignal) => content("quarantines", id, fence, signal, assertQuarantineEvidenceV2),
  };
}
