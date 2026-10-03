/**
 * device-ai internal, wire not frozen (roundtable D15 layered strategy).
 *
 * Host-side port of the server projection core (apps/api/tire_api/
 * device_ai_projection.py). Round 50 P1-4b extends the phase-A tire
 * single_observation slice to the full accepted surface of the sealed
 * vectors: mode="frozen_decision_closure" (candidate dependency expansion
 * over _candidate_origin + the approved-closure consent gate, core L728-749)
 * and the vehicle / recall / recall_search converters ("complete_observation"
 * / "complete_formal_observation" / "candidate_page_context"). test_event
 * stays rejection-only (device_ai_selected_restricted), exactly like the
 * server: the restricted check runs before converter dispatch.
 *
 * WHY THIS EXISTS: the server prepare route requires expected_projection_sha256
 * to equal its own recomputation (device_ai_routes.py), while the preview SDK
 * (./device-ai-host.ts) deliberately never claimed projection equivalence.
 * This port computes that digest LOCALLY so the Web host can dispatch prepare
 * without a prior server round-trip. Equivalence is not claimed abstractly:
 * the port is locked against ALL 20 sealed domain vectors in
 * .artifacts/device-ai50/projection-vectors-a (17 accepted: byte-equal
 * canonical text, sha256 AND token-DTO text; 3 rejected: equal error codes)
 * by .artifacts/device-ai50/projection-parity-ts/run-projection-parity.mts;
 * the server still re-verifies on every prepare, so any divergence surfaces
 * as a closed 409 device_ai_projection_mismatch, never as a silent mismatch.
 *
 * The exact-JSON primitives (parse/canonical/digest, number lexemes) come from
 * ./device-ai-exact.ts (locked by the E1 68/68 parity vectors). Validation
 * mirrors the Python _load/_select/_candidate_origin/_resolution/
 * _frozen_identity/_tire/_vehicle/_recall/_recall_search acceptance path;
 * rejection ordering is not guaranteed to be identical, only the fail-closed
 * direction. Declared deviation on pathological inputs: Python == semantics
 * between a NumberLexeme and a bool/str are always False, which === on the
 * AST reproduces except when two lexeme objects with the same token are
 * compared for identity (receipt/reference fields); there this port fails
 * closed instead of matching. Deliberately NOT exported from index.ts.
 */
import {
  DeviceAiJsonNumber,
  canonicalDeviceAiJson,
  deviceAiDigest,
  parseDeviceAiJson,
  type DeviceAiErrorCode,
  type DeviceAiJsonAst,
} from "./device-ai-exact";
import type { DeviceAiSelectorWire, DeviceAiTireSelectorWire } from "./device-ai-host";

export const DEVICE_AI_PROJECTION_POLICY_VERSION = "device-ai-projection@1";
export const DEVICE_AI_MAX_PROJECTION_BYTES = 44_000;
export const DEVICE_AI_MAX_PACKAGE_BYTES_PORT = 8 * 1024 * 1024;
export const DEVICE_AI_MAX_META_INTEGER = 9_007_199_254_740_991;
export const DEVICE_AI_SELECTION_NAMESPACE = "device-ai-selection@1";

/** The six projection modes of the Python core gate (L718-720). */
export type DeviceAiProjectionMode =
  | "single_observation"
  | "frozen_decision_closure"
  | "complete_observation"
  | "complete_formal_observation"
  | "candidate_page_context"
  | "complete_event_context";

const PROJECTION_MODES: ReadonlySet<string> = new Set([
  "single_observation", "frozen_decision_closure", "complete_observation",
  "complete_formal_observation", "candidate_page_context", "complete_event_context",
]);
/** Per-kind required mode for the non-tire converters (core L753-754). */
const CONVERTER_MODES: Readonly<Record<string, string>> = {
  vehicle: "complete_observation",
  recall: "complete_formal_observation",
  recall_search: "candidate_page_context",
  test_event: "complete_event_context",
};

export type DeviceAiProjectionPortCode =
  | DeviceAiErrorCode
  | "device_ai_package_binding_mismatch"
  | "device_ai_member_ambiguous"
  | "device_ai_member_missing"
  | "device_ai_document_ambiguous"
  | "device_ai_document_missing"
  | "device_ai_document_mismatch"
  | "device_ai_selector_mismatch"
  | "device_ai_selector_capacity"
  | "device_ai_selector_ambiguous"
  | "device_ai_receipt_mismatch"
  | "device_ai_source_proof_missing"
  | "device_ai_domain_unsupported"
  | "device_ai_projection_mode_unsupported"
  | "device_ai_projection_capacity"
  | "device_ai_variant_mismatch"
  | "device_ai_field_ambiguous"
  | "device_ai_selected_field_proof_missing"
  | "device_ai_candidate_proof_missing"
  | "device_ai_candidate_receipt_ambiguous_or_missing"
  | "device_ai_snapshot_identity_unsupported"
  | "device_ai_identity_context_invalid"
  | "device_ai_identity_dimension_unsupported"
  | "device_ai_excluded_material"
  | "device_ai_metadata_number_invalid"
  | "device_ai_selected_restricted"
  | "device_ai_decision_dependency_mismatch"
  | "device_ai_decision_dependency_missing"
  | "device_ai_closure_consent_required"
  | "device_ai_record_mismatch"
  | "device_ai_recall_records_mismatch"
  | "device_ai_recall_fact_mismatch"
  | "device_ai_search_page_mismatch";

export class DeviceAiProjectionPortError extends Error {
  constructor(readonly code: DeviceAiProjectionPortCode) { super(code); this.name = "DeviceAiProjectionPortError"; }
}
function reject(code: DeviceAiProjectionPortCode): never { throw new DeviceAiProjectionPortError(code); }

const HASH64 = /^[0-9a-f]{64}$/;
const REFERENCE_KINDS = new Set(["tire", "vehicle", "recall", "recall_search", "test_event"]);
const FORBIDDEN_KEYS = new Set([
  "body", "raw", "raw_body", "raw_content", "html", "full_text", "full_html",
  "full_document", "image_base64", "pdf_base64", "session_cookie", "actor_session_id",
  "session_id", "cookie", "cookies", "authorization", "api_key", "provider_key",
  "access_token", "refresh_token", "body_base64",
]);

type AstRecord = { [key: string]: DeviceAiJsonAst };
const isRecord = (value: unknown): value is AstRecord =>
  !!value && typeof value === "object" && !Array.isArray(value) && !(value instanceof DeviceAiJsonNumber);

/**
 * Bounded metadata integer as it exists in the Python result tree: _meta_int
 * returns a plain int, so canonical_exact_json renders its decimal text
 * (identical to the lexeme token) while token_dto emits it BARE — unlike
 * payload numbers, which become {"schema":"device-number-token@1",...}.
 * Canonical behavior is inherited unchanged (instanceof DeviceAiJsonNumber);
 * only the token-DTO walk below distinguishes the marker.
 */
class DeviceAiMetaInt extends DeviceAiJsonNumber {}

/** Deep copy that keeps number lexemes as lexemes (structuredClone would not). */
function cloneAst<T extends DeviceAiJsonAst>(node: T): T {
  if (node instanceof DeviceAiJsonNumber) return new DeviceAiJsonNumber(node.token) as T;
  if (Array.isArray(node)) return node.map(cloneAst) as T;
  if (isRecord(node)) {
    const out: AstRecord = {};
    for (const [key, value] of Object.entries(node)) out[key] = cloneAst(value);
    return out as T;
  }
  return node;
}

function shape(value: unknown, required: readonly string[], optional: readonly string[] = []): AstRecord {
  if (!isRecord(value)) reject("device_ai_material_invalid");
  const allowed = new Set([...required, ...optional]);
  for (const key of required) if (!Object.hasOwn(value, key)) reject("device_ai_material_invalid");
  for (const key of Object.keys(value)) if (!allowed.has(key)) reject("device_ai_material_invalid");
  return value;
}
function text(value: unknown, nullable = false, maximum = 100_000): void {
  if (nullable && value === null) return;
  if (typeof value !== "string" || value.length > maximum || value.includes("\0")) reject("device_ai_material_invalid");
}
function identifier(value: unknown): void { text(value, false, 200); if (!(value as string).length) reject("device_ai_material_invalid"); }
function hash64(value: unknown): void { if (typeof value !== "string" || !HASH64.test(value)) reject("device_ai_material_invalid"); }
function metaInt(value: unknown, maximum = DEVICE_AI_MAX_META_INTEGER, minimum = 0): number {
  if (value instanceof DeviceAiJsonNumber) {
    if (value.isFloat || value.token.length > 17) reject("device_ai_metadata_number_invalid");
    const parsed = Number(value.token);
    if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) reject("device_ai_metadata_number_invalid");
    return parsed;
  }
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum || value > maximum) reject("device_ai_metadata_number_invalid");
  return value;
}
function timeString(value: unknown, nullable = false): void {
  if (nullable && value === null) return;
  if (typeof value !== "string" || value.length > 80 || value.includes("\0")) reject("device_ai_material_invalid");
  // Python datetime.fromisoformat with tzinfo required: a date, a time and an
  // explicit zone (Z or ±HH:MM). Producer receipts always carry one.
  if (!/^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[Zz]|[+-]\d{2}:\d{2})$/.test(value)) reject("device_ai_material_invalid");
}
function noExcludedMaterial(value: DeviceAiJsonAst): void {
  if (isRecord(value)) {
    for (const [key, child] of Object.entries(value)) {
      if (FORBIDDEN_KEYS.has(key.toLowerCase())) reject("device_ai_excluded_material");
      noExcludedMaterial(child);
    }
  } else if (Array.isArray(value)) for (const child of value) noExcludedMaterial(child);
  else if (typeof value === "string") text(value);
}

/** Python _reference: closed per-kind key sets; returns the validated copy. */
function reference(value: unknown, schema: string): AstRecord {
  if (!isRecord(value) || typeof value.kind !== "string" || !REFERENCE_KINDS.has(value.kind)) reject("device_ai_domain_unsupported");
  const kind = value.kind;
  const fields: Record<string, readonly string[]> = {
    tire: ["kind", "snapshot_id", "variant_id", "verification_id"],
    vehicle: ["kind", "snapshot_id", "verification_id"],
    recall: ["kind", "snapshot_id", "recall_revision_id", "verification_id"],
    recall_search: ["kind", "snapshot_id", "verification_id"],
    test_event: ["kind", "event_id", "event_revision"],
  };
  shape(value, fields[kind]);
  if (kind === "recall_search" && schema !== "offline-pack@2") reject("device_ai_domain_unsupported");
  const out: AstRecord = { ...value };
  for (const [key, item] of Object.entries(value)) {
    if (key === "event_revision") out[key] = new DeviceAiMetaInt(String(metaInt(item, 2_147_483_647, 1)));
    else if (key === "recall_revision_id" && item === null) continue;
    else identifier(item);
  }
  return out;
}

/** Python _source: receipt proof and parser identity checks. */
function source(value: unknown, ref: AstRecord): AstRecord {
  const row = shape(value, ["source_id", "source_url", "raw_hash", "parser_version", "parser_identity", "observed_at", "verified_at", "verification_id"]);
  timeString(row.observed_at);
  timeString(row.verified_at, true);
  for (const key of ["source_id", "source_url", "parser_version", "verification_id"]) text(row[key], true);
  if (typeof row.source_url !== "string" || !row.source_url.trim()) reject("device_ai_source_proof_missing");
  if (row.parser_identity !== null) {
    const identity = shape(row.parser_identity, ["bundle_id", "parser_digest", "deployment_revision"]);
    identifier(identity.bundle_id); hash64(identity.parser_digest); metaInt(identity.deployment_revision);
  }
  if (row.raw_hash !== null) hash64(row.raw_hash);
  if (ref.kind === "test_event") {
    if (row.verification_id !== null || row.verified_at !== null) reject("device_ai_receipt_mismatch");
  } else {
    for (const key of ["source_id", "parser_version"]) if (typeof row[key] !== "string" || !(row[key] as string).trim()) reject("device_ai_source_proof_missing");
    if (row.verification_id !== ref.verification_id || row.verified_at === null || row.raw_hash === null) reject("device_ai_receipt_mismatch");
  }
  noExcludedMaterial(row);
  return row;
}

export interface DeviceAiProjectionBinding {
  package_id: string;
  owner_scope_id: string;
  sha256: string;
  byte_count: number;
  schema: "offline-pack@1" | "offline-pack@2";
}

/** One resolved observation, member_key ascending (fingerprint-spec 2/3 inputs). */
export interface DeviceAiProjectionObservationSummary {
  member_key: string;
  kind: string;
  selection_reason: "requested" | "decision_dependency";
  /** Resolved selector, wire form (validated copy of what entered the projection). */
  selector: DeviceAiSelectorWire;
  /** Resolved selector canonical AST (the exact node inside the projection). */
  selectorAst: DeviceAiJsonAst;
  /** Receipt source canonical AST (member.source, numbers as lexemes). */
  sourceAst: DeviceAiJsonAst;
}

export interface DeviceAiProjectionPortResult {
  canonicalText: string;
  sha256: string;
  byteCount: number;
  memberCount: number;
  /** selection_sha256 over the resolved selector closure (server namespace). */
  selectionSha256: string;
  /** Token-DTO transport text (Python token_dto_bytes form; never hashed). */
  tokenDtoText: string;
  /** Resolved closure observations, member_key ascending. */
  observations: DeviceAiProjectionObservationSummary[];
}

const ENVELOPE_KEYS = ["schema", "package_id", "created_at", "plan_fingerprint", "owner_scope_id",
  "privacy_class", "data_state", "source_refresh_performed", "base_pack_id",
  "scope", "contracts", "contexts", "members", "documents", "omissions"] as const;

interface LoadedPack { envelope: AstRecord; members: Map<string, AstRecord>; documents: Map<string, AstRecord> }

async function sha256Bytes(bytes: Uint8Array): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes.slice().buffer as ArrayBuffer);
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}
const sha256Text = (text: string): Promise<string> => sha256Bytes(new TextEncoder().encode(text));

async function loadPack(bytes: Uint8Array, binding: DeviceAiProjectionBinding): Promise<LoadedPack> {
  identifier(binding.package_id); hash64(binding.owner_scope_id); hash64(binding.sha256);
  metaInt(binding.byte_count, DEVICE_AI_MAX_PACKAGE_BYTES_PORT, 1);
  if (!(bytes instanceof Uint8Array) || bytes.byteLength !== binding.byte_count) reject("device_ai_package_binding_mismatch");
  if (await sha256Bytes(bytes) !== binding.sha256) reject("device_ai_package_binding_mismatch");
  const envelope = parseDeviceAiJson(bytes);
  const record: AstRecord = shape(envelope, ENVELOPE_KEYS);
  if (binding.schema !== "offline-pack@1" && binding.schema !== "offline-pack@2") reject("device_ai_package_binding_mismatch");
  if (record.schema !== binding.schema || record.package_id !== binding.package_id
    || record.owner_scope_id !== binding.owner_scope_id) reject("device_ai_package_binding_mismatch");
  if (record.data_state !== "local_snapshot" || record.source_refresh_performed !== false
    || (record.privacy_class !== "private" && record.privacy_class !== "restricted")) reject("device_ai_material_invalid");
  timeString(record.created_at);
  hash64(record.plan_fingerprint);
  const contracts = shape(record.contracts, ["offline_policy", "field_policy", "recall_policy"]);
  if (contracts.offline_policy !== "offline-policy@1") reject("device_ai_material_invalid");
  const members = new Map<string, AstRecord>();
  if (!Array.isArray(record.members) || record.members.length > 200) reject("device_ai_material_invalid");
  const memberList: DeviceAiJsonAst[] = record.members;
  for (const item of memberList) {
    const member = shape(item, ["key", "reference", "member_reasons", "privacy_class", "raw_included", "source", "payload"]);
    hash64(member.key);
    if (members.has(member.key as string)) reject("device_ai_member_ambiguous");
    const ref = reference(member.reference, binding.schema);
    source(member.source, ref);
    if ((member.privacy_class !== "public" && member.privacy_class !== "private" && member.privacy_class !== "restricted")
      || member.raw_included !== false || !isRecord(member.payload)) reject("device_ai_material_invalid");
    members.set(member.key as string, member);
  }
  const documents = new Map<string, AstRecord>();
  if (!Array.isArray(record.documents) || record.documents.length > 4000) reject("device_ai_material_invalid");
  const documentList: DeviceAiJsonAst[] = record.documents;
  for (const item of documentList) {
    const document = shape(item, ["id", "category", "kind", "member_key", "context_id", "record_index",
      "title", "text", "facets", "membership", "privacy_class", "observed_at", "verified_at"]);
    identifier(document.id);
    if (documents.has(document.id as string)) reject("device_ai_document_ambiguous");
    documents.set(document.id as string, document);
  }
  return { envelope: record, members, documents };
}

interface SelectedEntry { resolved: AstRecord; member: AstRecord }

function selectEntry(selector: DeviceAiSelectorWire, schema: string, members: Map<string, AstRecord>, documents: Map<string, AstRecord>): SelectedEntry {
  const row = shape(selector, ["kind", "member_key", "document_id", "record_index", "reference"]);
  const ref = reference(row.reference, schema);
  if (row.kind !== ref.kind) reject("device_ai_selector_mismatch");
  hash64(row.member_key);
  const key = row.member_key as string;
  const member = members.get(key);
  if (!member) reject("device_ai_member_missing");
  if (canonicalDeviceAiJson(ref) !== canonicalDeviceAiJson(reference(member.reference, schema))) reject("device_ai_receipt_mismatch");
  let record: number | null = null;
  if (row.record_index !== null) record = metaInt(row.record_index, 3999);
  const documentId = row.document_id;
  if (documentId !== null) {
    identifier(documentId);
    const document = documents.get(documentId as string);
    if (!document) reject("device_ai_document_missing");
    if (document.category !== "evidence" || document.context_id !== null
      || document.member_key !== key || document.kind !== ref.kind
      || document.privacy_class !== member.privacy_class
      || (document.record_index === null ? null : metaInt(document.record_index, 3999)) !== record) reject("device_ai_document_mismatch");
    const memberSource = member.source as AstRecord;
    for (const name of ["observed_at", "verified_at"]) if (document[name] !== memberSource[name]) reject("device_ai_receipt_mismatch");
  } else if (record !== null) reject("device_ai_selector_mismatch");
  if ((ref.kind === "tire" || ref.kind === "vehicle") && record !== null) reject("device_ai_selector_mismatch");
  const resolved: AstRecord = { kind: ref.kind, member_key: key, document_id: documentId,
    record_index: record === null ? null : new DeviceAiMetaInt(String(record)), reference: ref };
  return { resolved, member };
}

const CANDIDATE_REQUIRED = ["snapshot_id", "variant_id", "source_id", "source_url", "raw_hash", "parser_version",
  "observed_at", "verified_at", "field", "present", "value", "id", "missing_evidence"] as const;
const CANDIDATE_OPTIONAL = new Set(["source_field", "source_name", "source_class", "source_region", "fact_version_id",
  "published_at", "evidence_locator", "identity_match", "region_match", "evidence_valid",
  "source_conflicted", "equivalence_event_id", "curation_field", "sku_specific",
  "eligible", "exclusion_reasons", "authority", "dimensions", "verification_id"]);

/** Python _candidate_origin: the receipt must name exactly one pack member. */
function candidateOrigin(candidate: AstRecord, members: Map<string, AstRecord>): string {
  shape(candidate, CANDIDATE_REQUIRED, [...CANDIDATE_OPTIONAL]);
  text(candidate.curation_field, true, 200);
  if (typeof candidate.present !== "boolean" || !Array.isArray(candidate.missing_evidence)) reject("device_ai_candidate_proof_missing");
  const matches: string[] = [];
  for (const [key, member] of members) {
    const ref = isRecord(member.reference) ? member.reference : null;
    const src = isRecord(member.source) ? member.source : null;
    if (!ref || !src || ref.kind !== "tire" || ref.snapshot_id !== candidate.snapshot_id || ref.variant_id !== candidate.variant_id) continue;
    if (Object.hasOwn(candidate, "verification_id") && candidate.verification_id !== ref.verification_id) continue;
    let all = true;
    for (const name of ["source_id", "source_url", "raw_hash", "parser_version", "observed_at", "verified_at"]) {
      if (candidate[name] !== src[name]) { all = false; break; }
    }
    if (all) matches.push(key);
  }
  if (matches.length !== 1) reject("device_ai_candidate_receipt_ambiguous_or_missing");
  return matches[0];
}

function tireResolution(member: AstRecord): AstRecord {
  const payload = shape(member.payload, ["variant", "identity_contract", "snapshot_identity_contract", "field_resolution", "lifecycle"]);
  const snapshotContract = payload.snapshot_identity_contract;
  if (snapshotContract !== null && (typeof snapshotContract !== "string" || snapshotContract !== "variant-identity@2")) reject("device_ai_snapshot_identity_unsupported");
  const variant = payload.variant;
  const ref = member.reference as AstRecord;
  if (!isRecord(variant) || variant.id !== ref.variant_id || variant.snapshot_id !== ref.snapshot_id) reject("device_ai_variant_mismatch");
  const resolutionRow = shape(payload.field_resolution, ["policy", "variant_id", "scope", "data_state", "fields", "notice", "fingerprint"]);
  if (resolutionRow.variant_id !== ref.variant_id || resolutionRow.scope !== "offline_pack"
    || resolutionRow.data_state !== "local_snapshot" || !Array.isArray(resolutionRow.fields)) reject("device_ai_material_invalid");
  hash64(resolutionRow.fingerprint);
  const policy = shape(resolutionRow.policy, ["version", "digest"]);
  if (policy.version !== "field-authority@1") reject("device_ai_domain_unsupported");
  hash64(policy.digest);
  return resolutionRow;
}

const SPEED_RATINGS = new Set(["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8",
  "B", "C", "D", "E", "F", "G", "J", "K", "L", "M", "N", "P",
  "Q", "R", "S", "T", "U", "H", "V", "W", "Y", "(Y)", "ZR"]);

function frozenIdentity(member: AstRecord): AstRecord {
  const payload = shape(member.payload, ["variant", "identity_contract", "snapshot_identity_contract", "field_resolution", "lifecycle"]);
  const identity = shape(payload.identity_contract,
    ["schema", "state", "current_key", "current_identity", "identity_status"],
    ["origin", "reason_codes", "related_candidates", "tracking_state", "notice"]);
  if (identity.schema !== "variant-identity@2") reject("device_ai_domain_unsupported");
  if (typeof identity.state !== "string" || !["current", "legacy_unbound", "legacy_needs_review"].includes(identity.state)) reject("device_ai_identity_context_invalid");
  text(identity.origin, true, 200);
  text(identity.notice);
  if (!Array.isArray(identity.reason_codes) || identity.reason_codes.some(code => typeof code !== "string")) reject("device_ai_identity_context_invalid");
  if (!Array.isArray(identity.related_candidates)) reject("device_ai_identity_context_invalid");
  const relatedList: DeviceAiJsonAst[] = identity.related_candidates;
  for (const relatedItem of relatedList) {
    if (!isRecord(relatedItem)) reject("device_ai_identity_context_invalid");
    const related: AstRecord = relatedItem;
    shape(related, ["variant_id", "relationship", "product_code_type"]);
    identifier(related.variant_id);
    if (typeof related.relationship !== "string" || !["unconfirmed_legacy", "unconfirmed_current"].includes(related.relationship)) reject("device_ai_identity_context_invalid");
    text(related.product_code_type, true, 100);
  }
  if (identity.state === "current") {
    hash64(identity.current_key);
    if (typeof identity.identity_status !== "string" || !["complete", "source_scoped"].includes(identity.identity_status)
      || identity.tracking_state !== "current") reject("device_ai_identity_context_invalid");
  } else if (identity.current_key !== null || identity.current_identity !== null
    || identity.identity_status !== null || identity.tracking_state !== "identity_review_required") {
    reject("device_ai_identity_context_invalid");
  }
  if (identity.current_identity !== null) {
    const dimensions = shape(identity.current_identity,
      ["brand", "model", "region", "size", "manufacturer_product_code", "product_code_type",
        "load_index", "speed_rating", "xl", "hl", "oe_mark", "acoustic_technology", "run_flat"],
      ["gtin", "eprel_id", "technology_features"]);
    const limits: Record<string, number> = { brand: 120, model: 200, region: 40, size: 24,
      manufacturer_product_code: 100, product_code_type: 100,
      load_index: 12, speed_rating: 12, oe_mark: 100, acoustic_technology: 100 };
    for (const [name, maximum] of Object.entries(limits)) {
      const mustBePresent = name === "brand" || name === "model" || name === "region" || name === "size";
      text(dimensions[name], !mustBePresent, maximum);
      if (mustBePresent && !dimensions[name]) reject("device_ai_identity_context_invalid");
    }
    for (const name of ["xl", "hl", "run_flat"]) {
      if (dimensions[name] !== null && typeof dimensions[name] !== "boolean") reject("device_ai_identity_context_invalid");
    }
    if (dimensions.manufacturer_product_code !== null) {
      const code = dimensions.manufacturer_product_code as string;
      if (!code || /[\x00-\x1f\x7f]/.test(code)) reject("device_ai_identity_context_invalid");
    }
    if (dimensions.product_code_type !== null) {
      const namespace = dimensions.product_code_type as string;
      if (!namespace || namespace !== namespace.trim() || /[\x00-\x1f\x7f]/.test(namespace)) reject("device_ai_identity_context_invalid");
    }
    if (dimensions.load_index !== null && !/^\d{2,3}(?:\/\d{2,3})?$/.test(dimensions.load_index as string)) reject("device_ai_identity_context_invalid");
    if (dimensions.speed_rating !== null && !SPEED_RATINGS.has(dimensions.speed_rating as string)) reject("device_ai_identity_context_invalid");
    if (!/^\d{3}\/\d{2}(?:ZR|R)\d{2}(?:\.5)?$/.test(dimensions.size as string)) reject("device_ai_identity_context_invalid");
    for (const name of ["gtin", "eprel_id"]) {
      if (Object.hasOwn(dimensions, name)) {
        const value = dimensions[name];
        if (value !== null && typeof value !== "string" && !(value instanceof DeviceAiJsonNumber && !value.isFloat)) reject("device_ai_identity_dimension_unsupported");
      }
    }
    if (Object.hasOwn(dimensions, "technology_features")) {
      const features = dimensions.technology_features;
      if (!Array.isArray(features) || features.some(feature => typeof feature !== "string")) reject("device_ai_identity_dimension_unsupported");
    }
  } else if (identity.state === "current") reject("device_ai_identity_context_invalid");
  const projected: AstRecord = {};
  for (const key of ["schema", "state", "current_key", "current_identity", "identity_status"]) projected[key] = cloneAst(identity[key]);
  noExcludedMaterial(projected);
  return projected;
}

const SINGLE_ALLOWED_CANDIDATE_KEYS = new Set(["id", "field", "source_field", "present", "value", "evidence_locator",
  "evidence_valid", "missing_evidence", "snapshot_id", "variant_id", "verification_id",
  "source_id", "source_url", "raw_hash", "parser_version", "observed_at", "verified_at"]);

/**
 * Python _tire for mode="single_observation" (frozen receipt-scoped candidates
 * only) and mode="frozen_decision_closure" (every candidate kept in full, the
 * whole field row kept, default_candidate_ids coverage enforced).
 */
function tireMaterial(member: AstRecord, members: Map<string, AstRecord>, mode: DeviceAiProjectionMode): AstRecord {
  const resolutionRow = tireResolution(member);
  const single = mode === "single_observation";
  const fields: DeviceAiJsonAst[] = [];
  const seen = new Set<string>();
  if (!Array.isArray(resolutionRow.fields)) reject("device_ai_material_invalid");
  const fieldList: DeviceAiJsonAst[] = resolutionRow.fields;
  for (const item of fieldList) {
    const field = shape(item, ["field", "label", "unit", "category", "identity_bound", "source_scope_only",
      "state", "has_default", "default_value", "default_candidate_ids", "candidates", "reasons"]);
    if (!Array.isArray(field.candidates) || !field.candidates.length) reject("device_ai_material_invalid");
    const candidateList: DeviceAiJsonAst[] = field.candidates;
    identifier(field.field);
    text(field.label);
    text(field.unit, true);
    if (seen.has(field.field as string)) reject("device_ai_field_ambiguous");
    seen.add(field.field as string);
    const ref = member.reference as AstRecord;
    const candidates: DeviceAiJsonAst[] = [];
    for (const entryItem of candidateList) {
      if (!isRecord(entryItem) || entryItem.field !== field.field) reject("device_ai_material_invalid");
      const entry: AstRecord = entryItem;
      if (single && (entry.snapshot_id !== ref.snapshot_id || entry.variant_id !== ref.variant_id
        || (Object.hasOwn(entry, "verification_id") && entry.verification_id !== ref.verification_id))) continue;
      const originKey = candidateOrigin(entry, members);
      if (single && originKey !== member.key) continue;
      if (single) {
        const projected: AstRecord = {};
        for (const [key, value] of Object.entries(entry)) if (SINGLE_ALLOWED_CANDIDATE_KEYS.has(key)) projected[key] = cloneAst(value);
        candidates.push(projected);
      } else {
        candidates.push(cloneAst(entry));
      }
    }
    if (!candidates.length) reject("device_ai_selected_field_proof_missing");
    if (single) {
      fields.push({ field: field.field, label: field.label, unit: field.unit, candidates });
    } else {
      // Python closure branch (core L570-573): default ids must be covered by
      // the kept candidates.
      if (!Array.isArray(field.default_candidate_ids)) reject("device_ai_decision_dependency_missing");
      const keptIds = new Set<unknown>();
      for (const candidate of candidates) keptIds.add((candidate as AstRecord).id);
      for (const idItem of field.default_candidate_ids as DeviceAiJsonAst[]) {
        if (!keptIds.has(idItem)) reject("device_ai_decision_dependency_missing");
      }
      fields.push(cloneAst(field));
    }
  }
  const result: AstRecord = {
    frozen_identity_contract: frozenIdentity(member),
    snapshot_identity_contract: cloneAst(shape(member.payload, ["variant", "identity_contract", "snapshot_identity_contract", "field_resolution", "lifecycle"]).snapshot_identity_contract),
    field_policy: cloneAst(resolutionRow.policy),
    fields,
    scope: single ? "device_single_observation" : "device_frozen_decision_closure",
  };
  noExcludedMaterial(result);
  return result;
}

/** Python _vehicle (complete_observation): closed fitment graph + fact digest row. */
function vehicleMaterial(member: AstRecord): AstRecord {
  const payload = shape(member.payload, ["vehicle", "trims", "fitments", "footnotes", "fact_hash", "fact_version", "excluded_document_count"]);
  hash64(payload.fact_hash);
  metaInt(payload.fact_version, DEVICE_AI_MAX_META_INTEGER, 1);
  metaInt(payload.excluded_document_count);
  if (!isRecord(payload.vehicle) || !Array.isArray(payload.trims)
    || !Array.isArray(payload.fitments) || !Array.isArray(payload.footnotes)) reject("device_ai_material_invalid");
  identifier(payload.vehicle.id);
  const trimIds: string[] = [];
  for (const trimItem of payload.trims) {
    if (!isRecord(trimItem)) continue;
    identifier(trimItem.id);
    trimIds.push(trimItem.id as string);
  }
  if (trimIds.length !== payload.trims.length || new Set(trimIds).size !== trimIds.length) reject("device_ai_material_invalid");
  const fitmentIds: string[] = [];
  for (const fitmentItem of payload.fitments) {
    if (!isRecord(fitmentItem) || !trimIds.includes(fitmentItem.trim_id as string)
      || !isRecord(fitmentItem.front) || !isRecord(fitmentItem.rear)) reject("device_ai_material_invalid");
    identifier(fitmentItem.id);
    fitmentIds.push(fitmentItem.id as string);
    for (const axle of ["front", "rear"] as const) identifier((fitmentItem[axle] as AstRecord).size);
  }
  if (new Set(fitmentIds).size !== fitmentIds.length) reject("device_ai_material_invalid");
  noExcludedMaterial(payload);
  return cloneAst(payload);
}

/** Python _receipt_evidence: recall-family evidence must match the member receipt. */
function receiptEvidence(evidence: unknown, member: AstRecord): AstRecord {
  if (!isRecord(evidence)) reject("device_ai_material_invalid");
  const ref = member.reference as AstRecord;
  const src = member.source as AstRecord;
  if (evidence.snapshot_id !== ref.snapshot_id || evidence.verification_id !== ref.verification_id) reject("device_ai_receipt_mismatch");
  for (const name of ["observed_at", "verified_at"]) if (evidence[name] !== src[name]) reject("device_ai_receipt_mismatch");
  return evidence;
}

/** Python _recall (complete_formal_observation): per-record scope hashes + fact equality. */
async function recallMaterial(member: AstRecord): Promise<AstRecord> {
  const payload = shape(member.payload, ["evidence", "records", "facts", "policy", "boundary"]);
  const evidence = receiptEvidence(payload.evidence, member);
  const records = payload.records;
  if (evidence.evidence_type !== "recall" || evidence.applicability !== "not_assessed"
    || evidence.recall_revision_id !== (member.reference as AstRecord).recall_revision_id) reject("device_ai_material_invalid");
  if (!Array.isArray(records) || records.length > 1000) reject("device_ai_material_invalid");
  if (metaInt(evidence.record_count, 1000) !== records.length) reject("device_ai_material_invalid");
  if (evidence.observation_kind !== (records.length ? "records" : "empty")) reject("device_ai_material_invalid");
  if (await sha256Text(canonicalDeviceAiJson(records)) !== evidence.records_hash) reject("device_ai_recall_records_mismatch");
  const boundary = shape(payload.boundary, ["policy", "mode", "applicability", "notice"]);
  if (boundary.policy !== "recall-fact-selection@1" || boundary.mode !== "announcement_facts_only"
    || boundary.applicability !== "not_assessed") reject("device_ai_material_invalid");
  const policy = shape(payload.policy, ["version", "digest"]);
  if (policy.version !== boundary.policy) reject("device_ai_material_invalid");
  hash64(policy.digest);
  const scopes = evidence.record_scopes;
  if (!Array.isArray(scopes) || scopes.length !== records.length) reject("device_ai_material_invalid");
  const recordByKey = new Map<string, AstRecord>();
  const occurrences = new Map<string, number>();
  for (let index = 0; index < records.length; index++) {
    const record = shape(records[index], ["campaign_number", "manufacturer", "report_received_date", "report_received_date_raw",
      "component", "potential_units", "summary", "consequence", "remedy", "notes",
      "make", "model", "model_year_raw", "applicability"]);
    if (record.campaign_number !== evidence.campaign_number || record.applicability !== "not_assessed") reject("device_ai_material_invalid");
    const digest = await sha256Text(canonicalDeviceAiJson(record));
    const occurrence = (occurrences.get(digest) ?? 0) + 1;
    occurrences.set(digest, occurrence);
    const scope = shape(scopes[index], ["index", "occurrence", "record_hash", "record_key"]);
    if (metaInt(scope.index, 999) !== index || metaInt(scope.occurrence, 1000, 1) !== occurrence
      || scope.record_hash !== digest || scope.record_key !== `${digest}:${occurrence}`) reject("device_ai_recall_records_mismatch");
    recordByKey.set(scope.record_key as string, record);
  }
  if (!Array.isArray(payload.facts)) reject("device_ai_material_invalid");
  for (const factItem of payload.facts as DeviceAiJsonAst[]) {
    const fact = shape(factItem, ["domain", "field", "field_code", "value", "scope", "record_key", "text"]);
    if (fact.domain !== "recall" || typeof fact.field_code !== "string" || !fact.field_code.startsWith("recall.")) reject("device_ai_material_invalid");
    const name = (fact.field_code as string).slice("recall.".length);
    let expected: DeviceAiJsonAst;
    if (fact.scope === "record") {
      const record = recordByKey.get(fact.record_key as string);
      if (record === undefined || !Object.hasOwn(record, name)) reject("device_ai_material_invalid");
      expected = record[name];
    } else {
      if (fact.scope !== "observation" || fact.record_key !== null
        || !["campaign_number", "record_count", "observation_kind", "applicability"].includes(name)) reject("device_ai_material_invalid");
      expected = evidence[name];
    }
    if (canonicalDeviceAiJson(fact.value) !== canonicalDeviceAiJson(expected)) reject("device_ai_recall_fact_mismatch");
  }
  noExcludedMaterial(payload);
  return cloneAst(payload);
}

/** Python _recall_search (candidate_page_context): page shape + discovery digest. */
async function recallSearchMaterial(member: AstRecord): Promise<AstRecord> {
  const payload = shape(member.payload, ["query", "discovery", "discovery_hash", "notices", "evidence", "empty_observation", "boundary"]);
  const evidence = shape(payload.evidence, ["snapshot_id", "query_id", "verification_id", "data_state", "observed_at", "verified_at"]);
  receiptEvidence(evidence, member);
  if (evidence.data_state !== "local_snapshot") reject("device_ai_material_invalid");
  const query = shape(payload.query, ["search", "offset"]);
  identifier(query.search);
  const offset = query.offset;
  // Python re.fullmatch(r"0|[1-9][0-9]{0,4}") + int(offset) <= 10000.
  if (typeof offset !== "string" || !/^(?:0|[1-9][0-9]{0,4})$/.test(offset) || Number(offset) > 10000) reject("device_ai_material_invalid");
  const discovery = shape(payload.discovery, ["products", "pagination"]);
  const products = discovery.products;
  if (!Array.isArray(products) || products.length > 10) reject("device_ai_material_invalid");
  // Python `is` on the exact bool: only true/false satisfy it.
  if (payload.empty_observation !== (products.length === 0)) reject("device_ai_material_invalid");
  const page = shape(discovery.pagination, ["count", "max", "offset", "total", "has_next", "has_previous"]);
  if (metaInt(page.count, 10) !== products.length || metaInt(page.max, 10) !== 10
    || metaInt(page.offset, 10000) !== Number(offset)) reject("device_ai_material_invalid");
  metaInt(page.total);
  if (typeof page.has_next !== "boolean" || typeof page.has_previous !== "boolean") reject("device_ai_material_invalid");
  const boundary = shape(payload.boundary, ["kind", "formal_campaign_revision", "applicability", "complete_query_result"]);
  if (boundary.kind !== "recall_search_candidate_page" || boundary.formal_campaign_revision !== false
    || boundary.applicability !== "not_assessed" || boundary.complete_query_result !== false) reject("device_ai_material_invalid");
  if (await sha256Text(canonicalDeviceAiJson(discovery)) !== payload.discovery_hash) reject("device_ai_search_page_mismatch");
  if (!Array.isArray(payload.notices) || (payload.notices as DeviceAiJsonAst[]).some(notice => typeof notice !== "string")) reject("device_ai_material_invalid");
  for (const productItem of products as DeviceAiJsonAst[]) {
    if (!isRecord(productItem) || productItem.applicability !== "not_assessed") reject("device_ai_material_invalid");
  }
  noExcludedMaterial(payload);
  return cloneAst(payload);
}

/** Codepoint order for the token-DTO key sort (Python sorted(); see device-ai-exact). */
const compareCodepoints = (a: string, b: string): number => {
  const first = Array.from(a, c => c.codePointAt(0)!), second = Array.from(b, c => c.codePointAt(0)!);
  for (let i = 0; i < Math.min(first.length, second.length); i++) if (first[i] !== second[i]) return first[i] - second[i];
  return first.length - second.length;
};

/** Python token_dto + json.dumps(sort_keys, compact, ensure_ascii=False) form. */
function tokenDtoTextOf(ast: DeviceAiJsonAst): string {
  const convert = (node: DeviceAiJsonAst): unknown => {
    if (node instanceof DeviceAiMetaInt) return Number(node.token); // plain json int, like Python _meta_int values
    if (node instanceof DeviceAiJsonNumber) return node.tokenDto();
    if (Array.isArray(node)) return node.map(convert);
    if (isRecord(node)) {
      const out: Record<string, unknown> = {};
      for (const key of Object.keys(node).sort(compareCodepoints)) out[key] = convert(node[key]);
      return out;
    }
    return node;
  };
  return JSON.stringify(convert(ast));
}

/** Validated resolved selector AST -> wire form (numbers back as JS numbers). */
function resolvedAstToWire(ast: AstRecord): DeviceAiSelectorWire {
  const ref = ast.reference as AstRecord;
  const referenceWire: { [key: string]: unknown } = {};
  for (const [key, value] of Object.entries(ref)) {
    referenceWire[key] = value instanceof DeviceAiJsonNumber ? metaInt(value, 2_147_483_647, 1) : value;
  }
  return {
    kind: ast.kind as DeviceAiSelectorWire["kind"],
    member_key: ast.member_key as string,
    document_id: (ast.document_id as string | null),
    record_index: ast.record_index === null ? null : metaInt(ast.record_index, 3999),
    reference: referenceWire as unknown as DeviceAiSelectorWire["reference"],
  };
}

/**
 * Unified port of project_offline_pack (round 50 P1-4b). Dispatches by
 * selector kind + mode across the sealed-vector accepted surface:
 * tire single_observation / frozen_decision_closure (with the candidate
 * dependency expansion and approved-closure consent gate of core L728-749),
 * vehicle complete_observation, recall complete_formal_observation,
 * recall_search candidate_page_context; test_event always fails closed with
 * device_ai_selected_restricted before any converter runs. Throws closed
 * DeviceAiProjectionPortError codes; never returns a partial projection.
 */
export async function projectDeviceAiPack(
  packageBytes: Uint8Array,
  binding: DeviceAiProjectionBinding,
  selectors: readonly DeviceAiSelectorWire[],
  mode: DeviceAiProjectionMode = "single_observation",
  approvedClosure: readonly DeviceAiSelectorWire[] | null = null,
  maxProjectionBytes = DEVICE_AI_MAX_PROJECTION_BYTES,
): Promise<DeviceAiProjectionPortResult> {
  if (!PROJECTION_MODES.has(mode)) reject("device_ai_projection_mode_unsupported");
  if (!Array.isArray(selectors) || selectors.length < 1 || selectors.length > 6) reject("device_ai_selector_capacity");
  metaInt(maxProjectionBytes, DEVICE_AI_MAX_PROJECTION_BYTES, 1);
  const { members, documents } = await loadPack(packageBytes, binding);
  const chosen = selectors.map(selector => selectEntry(selector, binding.schema, members, documents));
  const requested = new Map<string, AstRecord>();
  for (const item of chosen) {
    if (requested.has(item.resolved.member_key as string)) reject("device_ai_selector_ambiguous");
    requested.set(item.resolved.member_key as string, item.resolved);
  }
  const resolved = new Map(requested);
  if (mode === "frozen_decision_closure") {
    // Core L729-743: breadth-first expansion over candidate receipts; the
    // queue is consumed while appending (Python for-over-list semantics).
    const queue = [...resolved.keys()];
    for (let cursor = 0; cursor < queue.length; cursor++) {
      const key = queue[cursor];
      const member = members.get(key)!;
      if ((member.reference as AstRecord).kind !== "tire") reject("device_ai_projection_mode_unsupported");
      const resolutionRow = tireResolution(member);
      if (!Array.isArray(resolutionRow.fields)) reject("device_ai_material_invalid");
      for (const fieldItem of resolutionRow.fields as DeviceAiJsonAst[]) {
        if (!isRecord(fieldItem) || !Array.isArray(fieldItem.candidates)) reject("device_ai_material_invalid");
        for (const candidateItem of fieldItem.candidates as DeviceAiJsonAst[]) {
          if (!isRecord(candidateItem)) reject("device_ai_candidate_proof_missing");
          const dependency = candidateOrigin(candidateItem, members);
          if ((members.get(dependency)!.reference as AstRecord).variant_id
            !== (member.reference as AstRecord).variant_id) reject("device_ai_decision_dependency_mismatch");
          if (!resolved.has(dependency)) {
            resolved.set(dependency, {
              kind: "tire", member_key: dependency, document_id: null, record_index: null,
              reference: reference(members.get(dependency)!.reference, binding.schema),
            });
            queue.push(dependency);
          }
        }
      }
    }
    // Core L744-749: any expansion (or any supplied closure) demands an
    // approved closure with the exact same resolved selector set.
    if (resolved.size !== requested.size || approvedClosure !== null) {
      if (!Array.isArray(approvedClosure) || approvedClosure.length !== resolved.size) reject("device_ai_closure_consent_required");
      const approved = approvedClosure.map(selector => selectEntry(selector, binding.schema, members, documents).resolved);
      const approvedCanonical = new Set(approved.map(item => canonicalDeviceAiJson(item)));
      const resolvedCanonical = new Set([...resolved.values()].map(item => canonicalDeviceAiJson(item)));
      if (approvedCanonical.size !== resolvedCanonical.size
        || ![...approvedCanonical].every(item => resolvedCanonical.has(item))) reject("device_ai_closure_consent_required");
    }
  } else if (approvedClosure !== null) reject("device_ai_projection_mode_unsupported");
  const observations: DeviceAiJsonAst[] = [];
  const summaries: DeviceAiProjectionObservationSummary[] = [];
  for (const key of [...resolved.keys()].sort()) {
    const member = members.get(key)!;
    const ref = member.reference as AstRecord;
    const kind = ref.kind as string;
    // Test events always originate as restricted manual material; labels cannot downgrade them.
    if (member.privacy_class === "restricted" || kind === "test_event") reject("device_ai_selected_restricted");
    let material: DeviceAiJsonAst;
    if (kind === "tire") {
      if (mode !== "single_observation" && mode !== "frozen_decision_closure") reject("device_ai_projection_mode_unsupported");
      material = tireMaterial(member, members, mode);
    } else {
      if (mode !== CONVERTER_MODES[kind]) reject("device_ai_projection_mode_unsupported");
      material = kind === "vehicle" ? vehicleMaterial(member)
        : kind === "recall" ? await recallMaterial(member)
        : await recallSearchMaterial(member);
    }
    const resolvedEntry = resolved.get(key)!;
    const focus = resolvedEntry.record_index === null ? null : metaInt(resolvedEntry.record_index, 3999);
    if (focus !== null) {
      const payload = member.payload as AstRecord;
      const recordsNode: unknown = kind === "recall"
        ? payload.records
        : (isRecord(payload.discovery) ? (payload.discovery as AstRecord).products : undefined);
      const recordCount = Array.isArray(recordsNode) ? (recordsNode as DeviceAiJsonAst[]).length : -1;
      if (!(focus < recordCount)) reject("device_ai_record_mismatch");
    }
    const sourceAst = cloneAst(member.source as DeviceAiJsonAst);
    observations.push({
      selector: resolvedEntry as DeviceAiJsonAst,
      selection_reason: requested.has(key) ? "requested" : "decision_dependency",
      source: sourceAst,
      material,
    });
    summaries.push({
      member_key: key,
      kind,
      selection_reason: requested.has(key) ? "requested" : "decision_dependency",
      selector: resolvedAstToWire(resolvedEntry),
      selectorAst: cloneAst(resolvedEntry as DeviceAiJsonAst),
      sourceAst,
    });
  }
  const result: DeviceAiJsonAst = {
    schema: DEVICE_AI_PROJECTION_POLICY_VERSION,
    data_state: "local_snapshot",
    source_refresh_performed: false,
    privacy_class: "private",
    projection_mode: mode,
    archive: { package_id: binding.package_id, package_schema: binding.schema, sha256: binding.sha256 },
    observations,
  };
  const canonicalText = canonicalDeviceAiJson(result);
  const canonicalBytes = new TextEncoder().encode(canonicalText);
  if (canonicalBytes.byteLength > maxProjectionBytes) reject("device_ai_projection_capacity");
  const sha256 = await sha256Bytes(canonicalBytes);
  const selectionSha256 = await deviceAiDigest(observations.map(item => (item as AstRecord).selector), DEVICE_AI_SELECTION_NAMESPACE);
  return {
    canonicalText,
    sha256,
    byteCount: canonicalBytes.byteLength,
    memberCount: observations.length,
    selectionSha256,
    tokenDtoText: tokenDtoTextOf(result),
    observations: summaries,
  };
}

/**
 * Phase-A entry point kept for compatibility: tire selectors only, mode
 * single_observation, no closure expansion. Delegates to projectDeviceAiPack
 * with identical closed semantics.
 */
export async function projectDeviceAiSingleObservation(
  packageBytes: Uint8Array, binding: DeviceAiProjectionBinding, selectors: readonly DeviceAiTireSelectorWire[],
  maxProjectionBytes = DEVICE_AI_MAX_PROJECTION_BYTES,
): Promise<DeviceAiProjectionPortResult> {
  return projectDeviceAiPack(packageBytes, binding, selectors, "single_observation", null, maxProjectionBytes);
}
