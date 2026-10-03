/**
 * device-ai internal, wire not frozen (roundtable D15 layered strategy).
 *
 * Host-side SDK layer for the device-AI bridge (round 50, P1-3 host step 2).
 * Four concerns, none of them a Provider call and none of them a new wire:
 *
 *  1. DeviceAiHostClient — metadata-only prepare + lookup/read against the
 *     implemented server routes, and the device branch of the existing stream
 *     entry. Request bodies match the closed server DTOs in
 *     apps/api/tire_api/device_ai.py (DeviceAIPrepareRequest / DeviceSubmission /
 *     ProviderConsent) and ai_analysis.py (AnalysisRequest) VERBATIM: the server
 *     models are extra=forbid, so any extra key is a 422 and any misspelled key
 *     is a silent 422 on a required field. Field-name lists are frozen in
 *     DEVICE_AI_*_FIELDS constants and asserted before dispatch. Round 50
 *     P1-4c: the prepare wire accepts the four open domains (tire / vehicle /
 *     recall / recall_search) and the five prepare modes; buildDeviceAiPrepareBody
 *     maps a recomputed preview onto the closed body, with
 *     expected_projection_sha256 taken from the on-device re-computation.
 *     Transport/errors reuse the sealed pipeline from ./index.ts (session
 *     cookies, Idempotency-Key handling, ApiError 404/409/422 mapping).
 *  2. computeLocalPreview + fingerprint helpers — question_sha256 (bare
 *     sha256 of trim-once UTF-8, no namespace, no JSON wrapping, no NFKC),
 *     selection_sha256 / device_context_fingerprint / local_preview_fingerprint
 *     per .artifacts/device-ai50/specs/fingerprint-spec.md sections 2/3/4.
 *     Round 50 P1-4b: computeLocalPreview dispatches the on-device projection
 *     port (./device-ai-projection.ts, locked 20/20 against the sealed
 *     authoritative vectors) across tire single_observation /
 *     frozen_decision_closure plus the vehicle / recall / recall_search
 *     domains, so projection_sha256 and the resolved closure are recomputed
 *     locally (projection_binding="recomputed"). The three new namespaces are
 *     proposals pending Root approval; they are centralized below so a rename
 *     is a single edit.
 *  3. DeviceAiJournal — AES-GCM encrypted append-only journal with the five
 *     fences: owner, generation, SHA chain, monotonic clock, session. The key
 *     is injected by the Host (Web uses the same non-extractable IndexedDB
 *     CryptoKey convention as apps/web/components/offline-crypto.ts
 *     newOfflineKey; native hosts use their secure store) — this module never
 *     derives or persists a key itself.
 *  4. resolveUnknownOutcome — N18 lookup-first recovery after a disconnect or
 *     crash. Read-only; it never resubmits on its own.
 *
 * Deliberately NOT exported from index.ts: the wire is not frozen. Import this
 * module by path (packages/api-client/src/device-ai-host.ts) until the
 * protocol is approved and frozen.
 */
import { ApiError, deviceAiInternalRequest, deviceAiInternalStreamDetail } from "./index";
import {
  DeviceAiJsonNumber,
  canonicalDeviceAiJson,
  deviceAiDigest,
  type DeviceAiJsonAst,
} from "./device-ai-exact";
import { projectDeviceAiPack, type DeviceAiProjectionMode } from "./device-ai-projection";
import type { AIStreamAcceptance, AIStreamDetail } from "@tire/domain-types";

// ---------------------------------------------------------------------------
// Namespaces and schemas (proposals pending Root approval; fingerprint-spec
// sections 2/3/4 and the journal schemas are Host-side internal contracts).
// ---------------------------------------------------------------------------

export const DEVICE_AI_SELECTION_NAMESPACE = "device-ai-selection@1";
export const DEVICE_AI_CONTEXT_NAMESPACE = "device-ai-context@1";
export const DEVICE_AI_LOCAL_PREVIEW_NAMESPACE = "device-ai-local-preview@1";
export const DEVICE_AI_JOURNAL_SCHEMA = "device-ai-journal@1";
export const DEVICE_AI_JOURNAL_ENTRY_SCHEMA = "device-ai-journal-entry@1";
export const DEVICE_AI_PROJECTION_POLICY_VERSION = "device-ai-projection@1";
/**
 * D4 (decoder-spec 4.3-2): prepare-assert upper bound for expected_byte_count,
 * mirroring the server object store cap (apps/api/tire_api/object_store.py
 * MAX_OBJECT_BYTES = 8 * 1024 * 1024, checked as 0 < size <= MAX) so the Host
 * assert layer accepts exactly 1..8,388,608 inclusive and is never looser
 * than the closed server check.
 */
export const DEVICE_AI_MAX_PACKAGE_BYTES = 8_388_608;

/** Closed server DTO field lists (apps/api/tire_api/device_ai.py, verbatim). */
export const DEVICE_AI_PREPARE_REQUEST_FIELDS = [
  "package_id", "expected_sha256", "expected_byte_count", "expected_schema", "expected_owner_scope_id",
  "selectors", "projection_mode", "approved_closure", "expected_projection_sha256", "question_sha256",
  "host_receipt_id", "intent_id",
] as const;
export const DEVICE_AI_SUBMISSION_FIELDS = ["prepare_id", "host_receipt_id", "device_context_fingerprint", "provider_consent"] as const;
export const DEVICE_AI_PROVIDER_CONSENT_FIELDS = [
  "expected_pack_fingerprint", "expected_device_context_fingerprint", "question_sha256",
  "provider", "model", "expected_provider_policy_fingerprint",
] as const;
export const DEVICE_AI_ANALYSIS_REQUEST_FIELDS = ["pack_id", "question", "allow_external_processing", "device_submission"] as const;

export type DeviceAiHostErrorCode =
  | "device_ai_host_invalid_argument"
  | "device_ai_host_package_mismatch"
  | "device_ai_host_preview_unsupported"
  | "device_ai_host_journal_owner_mismatch"
  | "device_ai_host_journal_generation_mismatch"
  | "device_ai_host_journal_session_mismatch"
  | "device_ai_host_journal_chain_broken"
  | "device_ai_host_journal_entry_tampered"
  | "device_ai_host_journal_clock_regression"
  | "device_ai_host_journal_corrupt";

/** Closed failure; the message is a fixed description, never source content. */
export class DeviceAiHostError extends Error {
  constructor(readonly code: DeviceAiHostErrorCode) {
    super(code);
    this.name = "DeviceAiHostError";
  }
}
function hostFail(code: DeviceAiHostErrorCode): never { throw new DeviceAiHostError(code); }

const HASH64 = /^[0-9a-f]{64}$/;
const UUID_CANONICAL = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
/**
 * RFC 3339 date-time with a MANDATORY timezone offset (decoder-spec 2.5, D6):
 * `Date.parse` alone also accepts naive ISO strings and date-only forms, which
 * the Rust/Java hosts reject (chrono `parse_from_rfc3339` / `OffsetDateTime
 * .parse`). The regex pins the offset-carrying shape first; `Date.parse` then
 * rejects impossible calendar values (e.g. month 13). Accepts the server's
 * Python `isoformat()` spelling (`+00:00`, optional fractional seconds) and Z.
 */
const RFC3339_WITH_OFFSET = /^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$/;
const isRfc3339WithOffset = (value: unknown): value is string =>
  typeof value === "string" && RFC3339_WITH_OFFSET.test(value) && Number.isFinite(Date.parse(value));
const isHash64 = (value: unknown): value is string => typeof value === "string" && HASH64.test(value);
const isPlainString = (value: unknown, max: number): value is string =>
  typeof value === "string" && value.length >= 1 && value.length <= max && !/[\r\n\0]/.test(value);
const isSafePositiveInt = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 1;

/**
 * Canonical lowercase UUID normalization, mirroring device_ai.py canonical_uuid
 * (accepts uppercase and braced spellings; output is the canonical hyphenated
 * lowercase form so idempotency keys never drift by spelling).
 */
export function canonicalDeviceAiUuid(value: string): string {
  if (typeof value !== "string" || !value.length || value.length > 68) hostFail("device_ai_host_invalid_argument");
  let text = value.trim().toLowerCase();
  if (text.startsWith("{") && text.endsWith("}")) text = text.slice(1, -1);
  if (!UUID_CANONICAL.test(text)) hostFail("device_ai_host_invalid_argument");
  return text;
}

// ---------------------------------------------------------------------------
// question: trim-once + codepoint counting + bare UTF-8 sha256 (spec section 5).
// ---------------------------------------------------------------------------

/**
 * Python str.strip() whitespace set, explicit (roundtable D3: the trim-once
 * algorithm must pin its whitespace set; JS String.prototype.trim() differs —
 * it strips U+FEFF but not U+001C..U+001F/U+0085). One trim pass strips the
 * whole leading/trailing run, exactly like Python's single .strip() call;
 * internal whitespace is preserved and NFKC normalization is forbidden.
 */
const PYTHON_WHITESPACE_RE = /[\t\n\v\f\r \x1c\x1d\x1e\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u;
const stripPythonWhitespace = (text: string): string => {
  let start = 0, end = text.length;
  while (start < end && PYTHON_WHITESPACE_RE.test(text[start])) start++;
  while (end > start && PYTHON_WHITESPACE_RE.test(text[end - 1])) end--;
  return text.slice(start, end);
};

/** Exactly one trim pass over the pinned whitespace set (no double trim). */
export function trimOnceQuestion(text: string): string {
  if (typeof text !== "string") hostFail("device_ai_host_invalid_argument");
  return stripPythonWhitespace(text);
}

/** Unicode codepoint count (Python len()), never UTF-16 code units. */
export function questionCodepoints(text: string): number {
  return Array.from(text).length;
}

/** The single normalization point before any digest or submit body. */
export function normalizeQuestion(text: string): string {
  const trimmed = trimOnceQuestion(text);
  const count = questionCodepoints(trimmed);
  if (count < 2 || count > 2000) hostFail("device_ai_host_invalid_argument");
  return trimmed;
}

/** Bare sha256(UTF-8 bytes): no namespace, no JSON quoting, no NFKC (spec 5). */
export async function questionSha256(normalizedQuestion: string): Promise<string> {
  if (typeof normalizedQuestion !== "string") hostFail("device_ai_host_invalid_argument");
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(normalizedQuestion));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

// ---------------------------------------------------------------------------
// selector wire shapes. The server prepare DTO is four-domain (P1-4a:
// tire / vehicle / recall / recall_search); the local preview additionally
// accepts test_event so computeLocalPreview can reproduce the projection
// port's restricted-rejection for it (the prepare assertion stays closed to
// the four open domains — assertDeviceAiPrepareSelector).
// ---------------------------------------------------------------------------

export interface DeviceAiTireReferenceWire {
  kind: "tire";
  snapshot_id: string;
  variant_id: string;
  verification_id: string;
}
export interface DeviceAiVehicleReferenceWire {
  kind: "vehicle";
  snapshot_id: string;
  verification_id: string;
}
export interface DeviceAiRecallReferenceWire {
  kind: "recall";
  snapshot_id: string;
  recall_revision_id: string | null;
  verification_id: string;
}
export interface DeviceAiRecallSearchReferenceWire {
  kind: "recall_search";
  snapshot_id: string;
  verification_id: string;
}
export interface DeviceAiTestEventReferenceWire {
  kind: "test_event";
  event_id: string;
  event_revision: number;
}
export type DeviceAiReferenceWire =
  | DeviceAiTireReferenceWire
  | DeviceAiVehicleReferenceWire
  | DeviceAiRecallReferenceWire
  | DeviceAiRecallSearchReferenceWire
  | DeviceAiTestEventReferenceWire;
export interface DeviceAiTireSelectorWire {
  kind: "tire";
  member_key: string;
  document_id: string | null;
  record_index: number | null;
  reference: DeviceAiTireReferenceWire;
}
export interface DeviceAiVehicleSelectorWire {
  kind: "vehicle";
  member_key: string;
  document_id: string | null;
  record_index: number | null;
  reference: DeviceAiVehicleReferenceWire;
}
export interface DeviceAiRecallSelectorWire {
  kind: "recall";
  member_key: string;
  document_id: string | null;
  record_index: number | null;
  reference: DeviceAiRecallReferenceWire;
}
export interface DeviceAiRecallSearchSelectorWire {
  kind: "recall_search";
  member_key: string;
  document_id: string | null;
  record_index: number | null;
  reference: DeviceAiRecallSearchReferenceWire;
}
export interface DeviceAiSelectorWire {
  kind: DeviceAiReferenceWire["kind"];
  member_key: string;
  document_id: string | null;
  record_index: number | null;
  reference: DeviceAiReferenceWire;
}

// ---------------------------------------------------------------------------
// Prepare-wire domain set (P1-4c). The server DeviceSelector Literal is exactly
// tire / vehicle / recall / recall_search (device_ai.py L121; test_event stays
// out — N27 closed set, DTO-layer 422), and DeviceAIPrepareRequest.projection_
// mode is the five-value Literal WITHOUT complete_event_context (L157-158).
// ---------------------------------------------------------------------------

export type DeviceAiPrepareSelectorWire =
  | DeviceAiTireSelectorWire
  | DeviceAiVehicleSelectorWire
  | DeviceAiRecallSelectorWire
  | DeviceAiRecallSearchSelectorWire;
export type DeviceAiPrepareProjectionMode =
  | "single_observation"
  | "frozen_decision_closure"
  | "complete_observation"
  | "complete_formal_observation"
  | "candidate_page_context";
export const DEVICE_AI_PREPARE_PROJECTION_MODES: ReadonlySet<string> = new Set([
  "single_observation", "frozen_decision_closure", "complete_observation",
  "complete_formal_observation", "candidate_page_context",
]);
/**
 * Per-domain converter mode of the projection core (core L753-754; enforced
 * again by the server prepare recompute). tire additionally accepts
 * frozen_decision_closure (the only closure-capable domain).
 */
export const DEVICE_AI_PREPARE_DOMAIN_MODES: Readonly<Record<DeviceAiPrepareSelectorWire["kind"], DeviceAiPrepareProjectionMode>> = {
  tire: "single_observation",
  vehicle: "complete_observation",
  recall: "complete_formal_observation",
  recall_search: "candidate_page_context",
};
/**
 * D9 (decoder-spec 4.3-9): the prepare-wire selector key set and the per-kind
 * reference field lists of the four open domains (device_ai.py selector /
 * reference models). Used only by the prepare WIRE assertion below — py rejects
 * nested unknown keys through recursive extra=forbid and rs through recursive
 * deny_unknown_fields, so the runtime wire assert must not be looser (TS types
 * only fence SDK-built payloads, not third-party objects).
 */
export const DEVICE_AI_PREPARE_SELECTOR_FIELDS = [
  "kind", "member_key", "document_id", "record_index", "reference",
] as const;
export const DEVICE_AI_PREPARE_REFERENCE_FIELDS: Readonly<Record<DeviceAiPrepareSelectorWire["kind"], readonly string[]>> = {
  tire: ["kind", "snapshot_id", "variant_id", "verification_id"],
  vehicle: ["kind", "snapshot_id", "verification_id"],
  recall: ["kind", "snapshot_id", "recall_revision_id", "verification_id"],
  recall_search: ["kind", "snapshot_id", "verification_id"],
};

export function assertDeviceAiSelector(selector: DeviceAiTireSelectorWire): void {
  if (!selector || selector.kind !== "tire") hostFail("device_ai_host_invalid_argument");
  if (!isHash64(selector.member_key)) hostFail("device_ai_host_invalid_argument");
  if (selector.document_id !== null && !isPlainString(selector.document_id, 200)) hostFail("device_ai_host_invalid_argument");
  if (selector.record_index !== null) hostFail("device_ai_host_invalid_argument"); // tire branch: always null (server model)
  const reference = selector.reference;
  if (!reference || reference.kind !== "tire"
    || !isPlainString(reference.snapshot_id, 64) || !isPlainString(reference.variant_id, 64)
    || !isPlainString(reference.verification_id, 64)) hostFail("device_ai_host_invalid_argument");
}

/**
 * Closed per-kind selector check for the five reference kinds (mirror of the
 * core _reference/_select bounds: member_key 64-hex, document ids bounded,
 * record_index 0..3999, event_revision 1..2^31-1).
 */
export function assertDeviceAiAnySelector(selector: DeviceAiSelectorWire): void {
  if (!selector || typeof selector.kind !== "string") hostFail("device_ai_host_invalid_argument");
  if (!isHash64(selector.member_key)) hostFail("device_ai_host_invalid_argument");
  if (selector.document_id !== null && !isPlainString(selector.document_id, 200)) hostFail("device_ai_host_invalid_argument");
  if (selector.record_index !== null
    && !(Number.isSafeInteger(selector.record_index) && selector.record_index >= 0 && selector.record_index <= 3999)) hostFail("device_ai_host_invalid_argument");
  const reference = selector.reference as unknown as Record<string, unknown> | null | undefined;
  if (!reference || typeof reference !== "object" || reference.kind !== selector.kind) hostFail("device_ai_host_invalid_argument");
  const id64 = (value: unknown): void => { if (!isPlainString(value, 64)) hostFail("device_ai_host_invalid_argument"); };
  switch (selector.kind) {
    case "tire":
      id64(reference.snapshot_id); id64(reference.variant_id); id64(reference.verification_id);
      break;
    case "vehicle":
    case "recall_search":
      id64(reference.snapshot_id); id64(reference.verification_id);
      break;
    case "recall":
      id64(reference.snapshot_id); id64(reference.verification_id);
      if (reference.recall_revision_id !== null && !isPlainString(reference.recall_revision_id, 64)) hostFail("device_ai_host_invalid_argument");
      break;
    case "test_event":
      id64(reference.event_id);
      if (!(typeof reference.event_revision === "number" && Number.isSafeInteger(reference.event_revision)
        && reference.event_revision >= 1 && reference.event_revision <= 2_147_483_647)) hostFail("device_ai_host_invalid_argument");
      break;
    default:
      hostFail("device_ai_host_invalid_argument");
  }
}

/**
 * Closed prepare-wire selector check (P1-4c): the four open domains of the
 * server DeviceSelector Literal plus its model_validator semantics —
 * document_id absent => record_index must be absent, and tire/vehicle never
 * carry record_index (whole-observation domains). test_event fails here the
 * same way it fails the server DTO (N27 closed set, 422).
 */
export function assertDeviceAiPrepareSelector(selector: DeviceAiPrepareSelectorWire): void {
  if (!selector || (selector.kind !== "tire" && selector.kind !== "vehicle"
    && selector.kind !== "recall" && selector.kind !== "recall_search")) hostFail("device_ai_host_invalid_argument");
  assertDeviceAiAnySelector(selector);
  if (selector.document_id === null && selector.record_index !== null) hostFail("device_ai_host_invalid_argument");
  if ((selector.kind === "tire" || selector.kind === "vehicle") && selector.record_index !== null) hostFail("device_ai_host_invalid_argument");
}

/**
 * D9 (decoder-spec 4.3-9): prepare-wire nested key-set closure. A wire selector
 * carries exactly the five-key set DEVICE_AI_PREPARE_SELECTOR_FIELDS and its
 * reference exactly the per-kind DEVICE_AI_PREPARE_REFERENCE_FIELDS list —
 * EXTRA-key rejection only, so a missing key keeps this layer's existing rules
 * (ts already fails absent keys through the field checks). Deliberately NOT
 * part of assertDeviceAiAnySelector: the digest/preview layers consume
 * package-derived selector objects that may legitimately carry internal fields.
 */
export function assertDeviceAiPrepareWireSelectorKeyClosure(selector: DeviceAiPrepareSelectorWire): void {
  const wireKeys = DEVICE_AI_PREPARE_SELECTOR_FIELDS as readonly string[];
  for (const key of Object.keys(selector)) {
    if (!wireKeys.includes(key)) hostFail("device_ai_host_invalid_argument");
  }
  const referenceKeys = DEVICE_AI_PREPARE_REFERENCE_FIELDS[selector.kind];
  const reference = selector.reference as unknown as Record<string, unknown> | null | undefined;
  if (reference) {
    for (const key of Object.keys(reference)) {
      if (!referenceKeys.includes(key)) hostFail("device_ai_host_invalid_argument");
    }
  }
}

const metaInt = (value: number): DeviceAiJsonNumber => {
  if (!Number.isSafeInteger(value) || Math.abs(value) > 9_007_199_254_740_991) hostFail("device_ai_host_invalid_argument");
  return new DeviceAiJsonNumber(String(value));
};

/** Selector as canonical AST input (fingerprint-spec section 2 item shape). */
export function selectorAst(selector: DeviceAiSelectorWire): DeviceAiJsonAst {
  assertDeviceAiAnySelector(selector);
  const reference: { [key: string]: DeviceAiJsonAst } = {};
  for (const [key, value] of Object.entries(selector.reference)) {
    reference[key] = typeof value === "number" ? metaInt(value) : (value as string | null);
  }
  return {
    document_id: selector.document_id,
    kind: selector.kind,
    member_key: selector.member_key,
    record_index: selector.record_index === null ? null : metaInt(selector.record_index),
    reference,
  };
}

const byMemberKey = (a: DeviceAiSelectorWire, b: DeviceAiSelectorWire): number =>
  a.member_key < b.member_key ? -1 : a.member_key > b.member_key ? 1 : 0;

/** fingerprint-spec section 2: member_key-ascending resolved closure digest. */
export async function selectionSha256(resolved: DeviceAiSelectorWire[]): Promise<string> {
  // REQUESTED selectors are capped at 6 (server DTO); the RESOLVED closure may
  // grow past that after frozen_decision_closure dependency expansion (the
  // pack member bound is 200), so only the non-empty/uniqueness fences apply.
  if (!Array.isArray(resolved) || !resolved.length || resolved.length > 200) hostFail("device_ai_host_invalid_argument");
  const sorted = [...resolved].sort(byMemberKey);
  const keys = new Set(sorted.map(item => item.member_key));
  if (keys.size !== sorted.length) hostFail("device_ai_host_invalid_argument");
  return deviceAiDigest(sorted.map(selectorAst), DEVICE_AI_SELECTION_NAMESPACE);
}

// ---------------------------------------------------------------------------
// device_context_fingerprint (spec section 3) — content identity computed over
// the exact-AST inputs; the SERVER value is authoritative, this helper exists
// so a decoder can independently verify it once the inputs are exposed.
// ---------------------------------------------------------------------------

export interface DeviceAiReceiptSourceInput {
  selector: DeviceAiSelectorWire;
  selection_reason: string;
  /** Receipt source canonical AST; archived numbers must enter as lexemes. */
  source: DeviceAiJsonAst;
}
export interface DeviceAiContextIdentityInput {
  package_id: string;
  package_schema: "offline-pack@1" | "offline-pack@2";
  package_sha256: string;
  projection_mode: string;
  projection_sha256: string;
  selection_sha256: string;
  receipt_sources: DeviceAiReceiptSourceInput[];
  device_citations: DeviceAiJsonAst[];
  domain_boundaries: DeviceAiJsonAst[];
}

export async function deviceContextFingerprint(input: DeviceAiContextIdentityInput): Promise<string> {
  if (!input || !isHash64(input.package_sha256) || !isHash64(input.projection_sha256)
    || !isHash64(input.selection_sha256) || !Array.isArray(input.receipt_sources)) hostFail("device_ai_host_invalid_argument");
  const canonicalBytesOrder = (nodes: DeviceAiJsonAst[]): DeviceAiJsonAst[] =>
    // Spec section 3: sort by the node's canonical bytes, but keep the ORIGINAL
    // AST nodes (a JSON.parse round-trip would destroy number lexemes).
    nodes.map(node => ({ node, text: canonicalDeviceAiJson(node) }))
      .sort((a, b) => (a.text < b.text ? -1 : a.text > b.text ? 1 : 0)).map(pair => pair.node);
  const ast: DeviceAiJsonAst = {
    device_citations: canonicalBytesOrder(input.device_citations),
    domain_boundaries: canonicalBytesOrder(input.domain_boundaries),
    numeric_encoding: "device-number-token@1",
    package_id: input.package_id,
    package_schema: input.package_schema,
    package_sha256: input.package_sha256,
    projection_mode: input.projection_mode,
    projection_sha256: input.projection_sha256,
    receipt_sources: [...input.receipt_sources].sort((a, b) => byMemberKey(a.selector, b.selector))
      .map(item => ({ selection_reason: item.selection_reason, selector: selectorAst(item.selector), source: item.source })),
    schema: "device-ai-context@1",
    selection_sha256: input.selection_sha256,
  };
  return deviceAiDigest(ast, DEVICE_AI_CONTEXT_NAMESPACE);
}

// ---------------------------------------------------------------------------
// local_preview_fingerprint (spec section 4) — frozen intent + origin +
// selection closure + projection digest. `state` and the nullable
// `projection_sha256` stay in the input: blocked and ready are different
// authorization objects and must never share a fingerprint.
// ---------------------------------------------------------------------------

export interface DeviceAiOriginBindingWire {
  expected_profile_id: string;
  expected_owner_epoch: number;
  slot_id: string;
  expected_generation: number;
  package_id: string;
  expected_sha256: string;
  expected_byte_count: number;
  owner_scope_id: string;
  package_schema: "offline-pack@1" | "offline-pack@2";
}
export interface DeviceAiLocalPreviewInput {
  questionSha256Value: string;
  includeContextIds: string[];
  projectionMode: string;
  queryContext: DeviceAiJsonAst | null;
  origin: DeviceAiOriginBindingWire;
  /** Requested selectors, REQUEST ORDER preserved (order is user input). */
  selected: DeviceAiSelectorWire[];
  /** Resolved closure, member_key ascending (same array as selection_sha256). */
  resolvedClosure: DeviceAiSelectorWire[];
  state: "ready" | "blocked";
  projectionSha256Value: string | null;
}

export async function localPreviewFingerprint(input: DeviceAiLocalPreviewInput): Promise<string> {
  if (!input || !isHash64(input.questionSha256Value)) hostFail("device_ai_host_invalid_argument");
  // M4 (decoder-spec section 3): include_context_ids must stay EMPTY until the
  // frozen wire opens the archive-id intent channel; a non-empty list (or a
  // non-array) fails closed before it can enter the fingerprint AST.
  if (!Array.isArray(input.includeContextIds) || input.includeContextIds.length) hostFail("device_ai_host_invalid_argument");
  if (input.state === "blocked" && input.projectionSha256Value !== null) hostFail("device_ai_host_invalid_argument");
  if (input.state === "ready" && input.projectionSha256Value !== null && !isHash64(input.projectionSha256Value)) hostFail("device_ai_host_invalid_argument");
  if (!Array.isArray(input.selected) || !input.selected.length || !Array.isArray(input.resolvedClosure)) hostFail("device_ai_host_invalid_argument");
  const origin = input.origin;
  if (!origin || !isHash64(origin.expected_sha256) || !isHash64(origin.owner_scope_id)
    || !isSafePositiveInt(origin.expected_byte_count) || !isSafePositiveInt(origin.expected_owner_epoch)
    || !isSafePositiveInt(origin.expected_generation) || !isPlainString(origin.package_id, 64)
    || !isPlainString(origin.slot_id, 64) || !isPlainString(origin.expected_profile_id, 64)) hostFail("device_ai_host_invalid_argument");
  const ast: DeviceAiJsonAst = {
    intent: {
      include_context_ids: [...input.includeContextIds],
      policy_version: DEVICE_AI_PROJECTION_POLICY_VERSION,
      purpose: "device_history_analysis",
      question_sha256: input.questionSha256Value,
    },
    origin: {
      expected_byte_count: metaInt(origin.expected_byte_count),
      expected_generation: metaInt(origin.expected_generation),
      expected_owner_epoch: metaInt(origin.expected_owner_epoch),
      expected_profile_id: origin.expected_profile_id,
      expected_sha256: origin.expected_sha256,
      owner_scope_id: origin.owner_scope_id,
      package_id: origin.package_id,
      package_schema: origin.package_schema,
      slot_id: origin.slot_id,
    },
    projection_mode: input.projectionMode,
    projection_sha256: input.projectionSha256Value,
    query_context: input.queryContext,
    resolved_closure: [...input.resolvedClosure].sort(byMemberKey).map(selectorAst),
    selected: input.selected.map(selectorAst),
    state: input.state,
  };
  return deviceAiDigest(ast, DEVICE_AI_LOCAL_PREVIEW_NAMESPACE);
}

// ---------------------------------------------------------------------------
// computeLocalPreview — local recomputation from the ORIGINAL package bytes,
// for showing "the fingerprints about to leave this device" BEFORE any export
// consent. Server-independent; makes no attestation claim (B01).
//
// Round 50 P1-4b: dispatches the on-device projection port across the four
// accepted domains plus frozen_decision_closure, so projection_sha256, the
// resolved closure (and therefore selection_sha256 per fingerprint-spec
// section 2) and device_context_fingerprint are now computed locally. The
// port is anchored 20/20 byte-for-byte against the sealed authoritative
// vectors (.artifacts/device-ai50/projection-vectors-a); the server still
// re-verifies everything on prepare, so "recomputed" is a local preview
// capability, never an equivalence attestation.
// ---------------------------------------------------------------------------

const PREVIEW_MODES: ReadonlySet<string> = new Set([
  "single_observation", "frozen_decision_closure", "complete_observation",
  "complete_formal_observation", "candidate_page_context", "complete_event_context",
]);

export interface DeviceAiPreviewRequest {
  question: string;
  selectors: DeviceAiSelectorWire[];
  origin: DeviceAiOriginBindingWire;
  includeContextIds?: string[];
  projectionMode?: DeviceAiProjectionMode;
  /** Exact approved selectors for mode="frozen_decision_closure" (core L744-749 gate). */
  approvedClosure?: DeviceAiSelectorWire[] | null;
}
export interface DeviceAiLocalPreviewSummary {
  question_sha256: string;
  selection_sha256: string;
  /** Local re-computation (fingerprint-spec section 3) over the port's observations. */
  device_context_fingerprint: string;
  local_preview_fingerprint: string;
  package_sha256: string;
  package_byte_count: number;
  package_schema: string;
  projection_mode: string;
  /** Member keys located in the original envelope for each requested selector. */
  located_member_keys: string[];
  /** Resolved closure member keys (requested + decision_dependency), ascending. */
  resolved_closure_member_keys: string[];
  /**
   * projection_sha256 IS recomputed here by the projection port locked 20/20
   * against the sealed vectors (byte-equal canonical, sha256 and token DTO;
   * rejected vectors carry equal error codes). The server still re-verifies on
   * every prepare; any divergence is a closed 409, never a silent mismatch.
   */
  projection_binding: "recomputed";
  projection_sha256: string;
  projection_byte_count: number;
  notices: string[];
}

export async function computeLocalPreview(
  packageBytes: Uint8Array, request: DeviceAiPreviewRequest,
): Promise<DeviceAiLocalPreviewSummary> {
  if (!(packageBytes instanceof Uint8Array) || !packageBytes.byteLength) hostFail("device_ai_host_invalid_argument");
  const origin = request.origin;
  if (!origin || !isHash64(origin.expected_sha256) || !isSafePositiveInt(origin.expected_byte_count)) hostFail("device_ai_host_invalid_argument");
  if (origin.expected_byte_count !== packageBytes.byteLength) hostFail("device_ai_host_package_mismatch");
  const mode: DeviceAiProjectionMode = request.projectionMode ?? "single_observation";
  if (!PREVIEW_MODES.has(mode)) hostFail("device_ai_host_preview_unsupported");
  if (!Array.isArray(request.selectors) || !request.selectors.length) hostFail("device_ai_host_invalid_argument");
  for (const selector of request.selectors) assertDeviceAiAnySelector(selector);
  const digestBytes = await globalThis.crypto.subtle.digest("SHA-256", packageBytes.slice().buffer as ArrayBuffer);
  const packageSha = Array.from(new Uint8Array(digestBytes), byte => byte.toString(16).padStart(2, "0")).join("");
  if (packageSha !== origin.expected_sha256) hostFail("device_ai_host_package_mismatch");

  const normalized = normalizeQuestion(request.question);
  const questionHash = await questionSha256(normalized);

  // Full local projection over the original bytes. The port re-validates the
  // whole envelope (members, receipts, converters) with the server's closed
  // codes — a stricter check than the phase-A locate scan it replaces.
  const projection = await projectDeviceAiPack(
    packageBytes,
    {
      package_id: origin.package_id, owner_scope_id: origin.owner_scope_id, sha256: packageSha,
      byte_count: packageBytes.byteLength, schema: origin.package_schema,
    },
    request.selectors, mode, request.approvedClosure ?? null,
  );
  const resolvedWires = projection.observations.map(item => item.selector);
  const selectionHash = await selectionSha256(resolvedWires);
  // Defense in depth: the port's own resolved-closure digest must equal the
  // SDK helper over the same closure (fingerprint-spec section 2 ordering).
  if (selectionHash !== projection.selectionSha256) hostFail("device_ai_host_preview_unsupported");
  const contextFingerprint = await deviceContextFingerprint({
    package_id: origin.package_id,
    package_schema: origin.package_schema,
    package_sha256: packageSha,
    projection_mode: mode,
    projection_sha256: projection.sha256,
    selection_sha256: selectionHash,
    receipt_sources: projection.observations.map(item => ({
      selector: item.selector, selection_reason: item.selection_reason, source: item.sourceAst,
    })),
    device_citations: [],
    domain_boundaries: [],
  });
  const previewFingerprint = await localPreviewFingerprint({
    questionSha256Value: questionHash,
    includeContextIds: request.includeContextIds ?? [],
    projectionMode: mode,
    queryContext: null,
    origin,
    selected: request.selectors,
    resolvedClosure: resolvedWires,
    state: "ready",
    projectionSha256Value: projection.sha256,
  });
  return {
    question_sha256: questionHash,
    selection_sha256: selectionHash,
    device_context_fingerprint: contextFingerprint,
    local_preview_fingerprint: previewFingerprint,
    package_sha256: packageSha,
    package_byte_count: packageBytes.byteLength,
    package_schema: origin.package_schema,
    projection_mode: mode,
    located_member_keys: request.selectors.map(item => item.member_key),
    resolved_closure_member_keys: projection.observations.map(item => item.member_key),
    projection_binding: "recomputed",
    projection_sha256: projection.sha256,
    projection_byte_count: projection.byteCount,
    notices: [
      "本预览为本地重算：question_sha256 / selection_sha256 / projection_sha256 / device_context_fingerprint / local_preview_fingerprint 均不依赖服务端。",
      "projection_sha256 由本机投影复刻端口重算（对封存向量 20/20 逐字节对拍）；服务端 prepare 仍会以 expected_projection_sha256 复核，不一致即闭环拒绝。",
      "device_context_fingerprint 本机值仅用于预览展示；上行绑定以服务端从自有投影权威计算的值为准。",
    ],
  };
}

// ---------------------------------------------------------------------------
// Encrypted append-only journal with five fences.
//
// Storage layout (one opaque byte blob, Host-owned store):
//   { "schema": "device-ai-journal@1", "owner": <str>, "generation": <int>,
//     "iv_hex": <24 hex chars>, "ciphertext_base64": <str> }
// ciphertext = AES-GCM(canonical({entries:[...]}), aad = canonical(
//   ["device-ai-journal@1", owner]) )  — key and store are Host-injected, the
// same conventions as apps/web/components/offline-crypto.ts (AES-GCM-256,
// 12-byte random IV, binding as additionalData); the AAD pins the owner, so a
// blob copied across owners fails to decrypt outright (cryptographic owner
// fence below the explicit one).
// ---------------------------------------------------------------------------

export type DeviceAiJournalEvent =
  | { type: "preview_shown"; intent_id: string; local_preview_fingerprint: string; question_sha256: string; package_sha256: string }
  | { type: "decision_made"; intent_id: string; decision: "allow" | "deny"; local_preview_fingerprint: string }
  | { type: "prepare_created"; intent_id: string; prepare_id: string; idempotency_key: string; projection_sha256: string; device_context_fingerprint: string }
  | { type: "claim_submitted"; intent_id: string; prepare_id: string; analysis_key: string; question_sha256: string }
  | { type: "outcome_observed"; intent_id: string; analysis_key: string; request_id: string; state: string }
  | { type: "failure_observed"; intent_id: string | null; stage: string; code: string };

export interface DeviceAiJournalEntry {
  schema: typeof DEVICE_AI_JOURNAL_ENTRY_SCHEMA;
  sequence: number;
  owner: string;
  generation: number;
  session_id: string;
  clock: number;
  wall_clock: string;
  event: DeviceAiJournalEvent;
  entry_sha256: string;
  prev_sha256: string;
}

export interface DeviceAiJournalStore {
  /** Load the whole encrypted blob, or null when the journal does not exist. */
  load(): Promise<Uint8Array | null>;
  /** Persist the whole encrypted blob atomically (Host store's own CAS). */
  save(blob: Uint8Array): Promise<void>;
}

export interface DeviceAiJournalOptions {
  /** Fence 1: profile/device ownership identity (free-form Host identifier). */
  owner: string;
  /** Fence 2: journal generation; a rebuild bumps it and voids older blobs. */
  generation: number;
  /** Fence 5: the current session; entries from other sessions never replay. */
  sessionId: string;
  /** AES-GCM-256 key, injected by the Host (never derived or stored here). */
  key: CryptoKey;
  store: DeviceAiJournalStore;
  /** Fence 4: injected monotonic clock (browsers: performance.now). */
  monotonicNow: () => number;
  /** Wall clock for audit display only; never used in fence decisions. */
  wallNow?: () => string;
}

export type DeviceAiJournalFenceCode =
  | "device_ai_host_journal_owner_mismatch"
  | "device_ai_host_journal_generation_mismatch"
  | "device_ai_host_journal_session_mismatch"
  | "device_ai_host_journal_chain_broken"
  | "device_ai_host_journal_entry_tampered"
  | "device_ai_host_journal_clock_regression"
  | "device_ai_host_journal_corrupt";

export interface DeviceAiJournalVerification {
  ok: boolean;
  length: number;
  /** Fence violations over owner/generation/SHA chain/clock (never session). */
  violations: { code: DeviceAiJournalFenceCode; sequence: number | null }[];
  /** Entries whose session differs from the journal's current session. */
  cross_session_entries: { sequence: number; session_id: string }[];
}

const GENESIS_HASH = "0".repeat(64);
const JOURNAL_AAD = (owner: string): Uint8Array => new TextEncoder().encode(JSON.stringify([DEVICE_AI_JOURNAL_SCHEMA, owner]));

/** Entry hash input: the entry WITHOUT entry_sha256, canonicalized. */
const entryHashAst = (entry: Omit<DeviceAiJournalEntry, "entry_sha256">): DeviceAiJsonAst => ({
  clock: metaInt(entry.clock),
  event: toJournalAst(entry.event),
  generation: metaInt(entry.generation),
  owner: entry.owner,
  prev_sha256: entry.prev_sha256,
  schema: entry.schema,
  sequence: metaInt(entry.sequence),
  session_id: entry.session_id,
  wall_clock: entry.wall_clock,
});

/** Plain journal values -> canonical AST (bounded metadata ints as lexemes). */
function toJournalAst(value: unknown): DeviceAiJsonAst {
  if (value === null) return null;
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return metaInt(value);
  if (Array.isArray(value)) return value.map(toJournalAst);
  if (value && typeof value === "object" && !(value instanceof DeviceAiJsonNumber)) {
    const out: { [key: string]: DeviceAiJsonAst } = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) out[key] = toJournalAst(item);
    return out;
  }
  return hostFail("device_ai_host_invalid_argument");
}

async function sha256Text(text: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

interface JournalBlobWire {
  schema: string;
  owner: string;
  generation: number;
  iv_hex: string;
  ciphertext_base64: string;
}

export class DeviceAiJournal {
  private readonly options: DeviceAiJournalOptions;

  constructor(options: DeviceAiJournalOptions) {
    if (!options || !isPlainString(options.owner, 128) || !isSafePositiveInt(options.generation)
      || !isPlainString(options.sessionId, 128) || typeof options.monotonicNow !== "function") hostFail("device_ai_host_invalid_argument");
    if (!options.key || options.key.algorithm?.name !== "AES-GCM") hostFail("device_ai_host_invalid_argument");
    this.options = options;
  }

  /** Fence context exposure (read-only) for recovery flows and self-tests. */
  get owner(): string { return this.options.owner; }
  get generation(): number { return this.options.generation; }
  get sessionId(): string { return this.options.sessionId; }

  private async seal(entries: DeviceAiJournalEntry[]): Promise<Uint8Array> {
    const iv = globalThis.crypto.getRandomValues(new Uint8Array(12));
    const plaintext = new TextEncoder().encode(canonicalDeviceAiJson({ entries: entries.map(entry => toJournalAst(entry)) }));
    const ciphertext = await globalThis.crypto.subtle.encrypt(
      { name: "AES-GCM", iv: iv.slice().buffer as ArrayBuffer, additionalData: JOURNAL_AAD(this.options.owner).slice().buffer as ArrayBuffer }, this.options.key, plaintext);
    const blob: JournalBlobWire = {
      schema: DEVICE_AI_JOURNAL_SCHEMA,
      owner: this.options.owner,
      generation: this.options.generation,
      iv_hex: Array.from(iv, byte => byte.toString(16).padStart(2, "0")).join(""),
      ciphertext_base64: btoa(String.fromCharCode(...new Uint8Array(ciphertext))),
    };
    return new TextEncoder().encode(JSON.stringify(blob));
  }

  private async unseal(blob: Uint8Array): Promise<DeviceAiJournalEntry[]> {
    let wire: JournalBlobWire;
    try { wire = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(blob)); }
    catch { return hostFail("device_ai_host_journal_corrupt"); }
    return this.entriesFromWire(wire);
  }

  private async entriesFromWire(wire: JournalBlobWire): Promise<DeviceAiJournalEntry[]> {
    if (!wire || typeof wire !== "object" || wire.schema !== DEVICE_AI_JOURNAL_SCHEMA
      || !isPlainString(wire.owner, 128) || !isSafePositiveInt(wire.generation)
      || typeof wire.iv_hex !== "string" || wire.iv_hex.length !== 24 || /^[0-9a-f]+$/.test(wire.iv_hex) === false
      || typeof wire.ciphertext_base64 !== "string") hostFail("device_ai_host_journal_corrupt");
    // Fence 1 (owner) — explicit header check; the AAD below is the
    // cryptographic layer of the same fence: a blob saved under another owner
    // simply fails to decrypt here.
    if (wire.owner !== this.options.owner) hostFail("device_ai_host_journal_owner_mismatch");
    // Fence 2 (generation) — a rebuilt journal (generation+1) voids old blobs.
    if (wire.generation !== this.options.generation) hostFail("device_ai_host_journal_generation_mismatch");
    const ciphertext = Uint8Array.from(atob(wire.ciphertext_base64), char => char.charCodeAt(0));
    const iv = Uint8Array.from(wire.iv_hex.match(/../g)!, hex => Number.parseInt(hex, 16));
    let plaintext: Uint8Array;
    try {
      plaintext = new Uint8Array(await globalThis.crypto.subtle.decrypt(
        { name: "AES-GCM", iv: iv.slice().buffer as ArrayBuffer, additionalData: JOURNAL_AAD(this.options.owner).slice().buffer as ArrayBuffer }, this.options.key, ciphertext));
    } catch { return hostFail("device_ai_host_journal_corrupt"); }
    let parsed: unknown;
    try { parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(plaintext)); }
    catch { return hostFail("device_ai_host_journal_corrupt"); }
    const entries = (parsed as { entries?: unknown }).entries;
    if (!Array.isArray(entries)) hostFail("device_ai_host_journal_corrupt");
    return entries as unknown as DeviceAiJournalEntry[];
  }

  /**
   * Structural verification (fences 1/2/4/5 + chain shape of fence 3) over a
   * decrypted entry list. entry_sha256 re-computation is consolidated in
   * verifyIntegrityOf so every entry is awaited exactly once.
   */
  private structureCheck(entries: DeviceAiJournalEntry[]): DeviceAiJournalVerification {
    const violations: DeviceAiJournalVerification["violations"] = [];
    const crossSession: DeviceAiJournalVerification["cross_session_entries"] = [];
    let previousHash = GENESIS_HASH, previousClock = Number.NEGATIVE_INFINITY;
    entries.forEach((entry, index) => {
      const sequence = index + 1;
      const broken = (code: DeviceAiJournalFenceCode) => violations.push({ code, sequence });
      if (!entry || typeof entry !== "object" || entry.schema !== DEVICE_AI_JOURNAL_ENTRY_SCHEMA
        || !Number.isSafeInteger(entry.sequence) || !isHash64(entry.entry_sha256) || !isHash64(entry.prev_sha256)) {
        violations.push({ code: "device_ai_host_journal_corrupt", sequence });
        return;
      }
      // Fence 3 (SHA): chain continuity + sequence numbering (hash re-computation below).
      if (entry.sequence !== sequence) broken("device_ai_host_journal_chain_broken");
      if (entry.prev_sha256 !== previousHash) broken("device_ai_host_journal_chain_broken");
      // Fence 1/2 apply per entry as well (defense in depth under the header).
      if (entry.owner !== this.options.owner) broken("device_ai_host_journal_owner_mismatch");
      if (entry.generation !== this.options.generation) broken("device_ai_host_journal_generation_mismatch");
      // Fence 4 (clock): strictly increasing monotonic timestamps, no replay
      // of an older entry after a newer one, no clock rollback.
      if (!Number.isFinite(entry.clock) || entry.clock <= previousClock) broken("device_ai_host_journal_clock_regression");
      // Fence 5 (session): recorded, but never fails readAll — recovery reads
      // the ledger; cross-session authorization is blocked at consumption.
      if (entry.session_id !== this.options.sessionId) crossSession.push({ sequence, session_id: entry.session_id });
      previousHash = entry.entry_sha256;
      previousClock = entry.clock;
    });
    return { ok: violations.length === 0, length: entries.length, violations, cross_session_entries: crossSession };
  }

  async append(event: DeviceAiJournalEvent): Promise<DeviceAiJournalEntry> {
    if (!event || typeof event.type !== "string") hostFail("device_ai_host_invalid_argument");
    const blob = await this.options.store.load();
    let entries: DeviceAiJournalEntry[] = [];
    if (blob) entries = await this.unseal(blob);
    const structural = this.structureCheck(entries);
    if (!structural.ok) hostFail(structural.violations[0].code);
    const tail = entries.at(-1);
    const clock = this.options.monotonicNow();
    // Fence 4 at write time: the new entry must strictly advance the clock.
    if (tail && !(clock > tail.clock)) hostFail("device_ai_host_journal_clock_regression");
    const draft: Omit<DeviceAiJournalEntry, "entry_sha256"> = {
      schema: DEVICE_AI_JOURNAL_ENTRY_SCHEMA,
      sequence: entries.length + 1,
      owner: this.options.owner,          // fence 1 stamped at write time
      generation: this.options.generation, // fence 2 stamped at write time
      session_id: this.options.sessionId,  // fence 5 stamped at write time
      clock,
      wall_clock: (this.options.wallNow ?? (() => new Date().toISOString()))(),
      event,
      prev_sha256: tail ? tail.entry_sha256 : GENESIS_HASH,
    };
    const entry: DeviceAiJournalEntry = { ...draft, entry_sha256: await sha256Text(canonicalDeviceAiJson(entryHashAst(draft))) };
    await this.options.store.save(await this.seal([...entries, entry]));
    return structuredClone(entry);
  }

  /** Decrypt + full verification. Fence violations throw their closed code. */
  async readAll(): Promise<DeviceAiJournalEntry[]> {
    const blob = await this.options.store.load();
    if (!blob) return [];
    const entries = await this.unseal(blob);
    const verification = await this.verifyIntegrityOf(entries);
    if (!verification.ok) hostFail(verification.violations[0].code);
    return structuredClone(entries);
  }

  /** Full five-fence report; never throws on fence violations (audit view). */
  async verifyIntegrity(): Promise<DeviceAiJournalVerification> {
    const blob = await this.options.store.load();
    if (!blob) return { ok: true, length: 0, violations: [], cross_session_entries: [] };
    try {
      const entries = await this.unseal(blob);
      return await this.verifyIntegrityOf(entries);
    } catch (cause) {
      if (cause instanceof DeviceAiHostError) {
        // owner/generation/corrupt fences surface from unseal itself.
        return { ok: false, length: 0, violations: [{ code: cause.code as DeviceAiJournalFenceCode, sequence: null }], cross_session_entries: [] };
      }
      throw cause;
    }
  }

  private async verifyIntegrityOf(entries: DeviceAiJournalEntry[]): Promise<DeviceAiJournalVerification> {
    const verification = this.structureCheck(entries);
    // Fence 3 (SHA): full per-entry hash re-computation over the canonical form.
    for (let index = 0; index < entries.length; index++) {
      const entry = entries[index];
      if (!entry || typeof entry !== "object" || !isHash64(entry.entry_sha256)) continue;
      const hash = await sha256Text(canonicalDeviceAiJson(entryHashAst(entry)));
      if (hash !== entry.entry_sha256) verification.violations.push({ code: "device_ai_host_journal_entry_tampered", sequence: index + 1 });
    }
    return { ...verification, ok: verification.violations.length === 0 };
  }

  /**
   * Fence 5 hard gate: every entry must belong to the current session.
   * Used before consuming any authorization-bearing entry (submit paths);
   * pure recovery reads use readAll and handle cross-session explicitly.
   */
  assertSameSession(entries: DeviceAiJournalEntry[]): void {
    for (const entry of entries) {
      if (entry.session_id !== this.options.sessionId) hostFail("device_ai_host_journal_session_mismatch");
    }
  }
}

// ---------------------------------------------------------------------------
// Host client — prepare/lookup/read + stream submit + attempt lookup.
// ---------------------------------------------------------------------------

export type DeviceAiPrepareBody = {
  package_id: string;
  expected_sha256: string;
  expected_byte_count: number;
  expected_schema: "offline-pack@1" | "offline-pack@2";
  expected_owner_scope_id: string;
  selectors: DeviceAiPrepareSelectorWire[];
  projection_mode: DeviceAiPrepareProjectionMode;
  approved_closure: DeviceAiPrepareSelectorWire[] | null;
  expected_projection_sha256: string;
  question_sha256: string;
  host_receipt_id: string;
  intent_id: string;
};

export interface DeviceAiProviderConsentBody {
  expected_pack_fingerprint: string;
  expected_device_context_fingerprint: string;
  question_sha256: string;
  provider: string;
  model: string;
  expected_provider_policy_fingerprint: string;
}

export interface DeviceAiSubmissionBody {
  prepare_id: string;
  host_receipt_id: string;
  device_context_fingerprint: string;
  provider_consent: DeviceAiProviderConsentBody;
}

export interface DeviceAiStreamSubmission {
  pack_id: string;
  /** Raw question text; normalized (trim-once) exactly once before dispatch. */
  question: string;
  prepare_id: string;
  host_receipt_id: string;
  device_context_fingerprint: string;
  provider_consent: DeviceAiProviderConsentBody;
}

/** Server preparation view (device_ai_routes.py _view), replay-tolerant. */
export interface DeviceAiPrepareResultView {
  id: string;
  created_at: string;
  expires_at: string;
  expired: boolean;
  idempotency_key: string;
  host_receipt_id: string;
  intent_id: string;
  pack_id: string;
  offline_pack_id: string;
  question_sha256: string;
  selection_sha256: string;
  projection_sha256: string;
  projection_byte_count: number;
  device_context_fingerprint: string;
  request_hash: string;
  contract: Record<string, unknown>;
  pack: Record<string, unknown>;
  replayed: boolean;
  /** Present on fresh creation only (server replay branch omits it). */
  provider_preview?: Record<string, unknown>;
}

const assertClosedFields = (body: object, fields: readonly string[], label: string): void => {
  const keys = Object.keys(body);
  const expected = [...fields];
  const extra = keys.filter(key => !expected.includes(key));
  const missing = expected.filter(key => !keys.includes(key));
  if (extra.length || missing.length) {
    throw new Error(`${label} 字段与服务端 closed DTO 不一致（多余: ${extra.join(",") || "无"}; 缺失: ${missing.join(",") || "无"}）`);
  }
};

/**
 * Closed-body assertion against the frozen server field lists (self-test
 * anchor). Selector/approved_closure items and the mode Literal mirror the
 * P1-4a server DTO semantics verbatim (device_ai.py): four open domains,
 * five prepare modes (no complete_event_context), approved_closure required
 * and 1..SELECTOR_CAPACITY(6) exactly in frozen_decision_closure, null in
 * every other mode, requested selector member_keys unique. D9 (decoder-spec
 * 4.3-9): selector/reference nested key sets are closed here (extra keys
 * rejected), matching py/rs recursive unknown-key rejection.
 */
export function assertDeviceAiPrepareBody(body: DeviceAiPrepareBody): void {
  assertClosedFields(body, DEVICE_AI_PREPARE_REQUEST_FIELDS, "DeviceAIPrepareRequest");
  if (!isPlainString(body.package_id, 64)) hostFail("device_ai_host_invalid_argument");
  if (!isHash64(body.expected_sha256) || !isHash64(body.expected_owner_scope_id)
    || !isHash64(body.expected_projection_sha256) || !isHash64(body.question_sha256)) hostFail("device_ai_host_invalid_argument");
  // D4 (decoder-spec 4.3-2): 1..DEVICE_AI_MAX_PACKAGE_BYTES inclusive — the
  // same bound as the server object store, instead of 1..2^53-1.
  if (!isSafePositiveInt(body.expected_byte_count) || body.expected_byte_count > DEVICE_AI_MAX_PACKAGE_BYTES) {
    hostFail("device_ai_host_invalid_argument");
  }
  if (body.expected_schema !== "offline-pack@1" && body.expected_schema !== "offline-pack@2") hostFail("device_ai_host_invalid_argument");
  if (!DEVICE_AI_PREPARE_PROJECTION_MODES.has(body.projection_mode)) hostFail("device_ai_host_invalid_argument");
  if (!Array.isArray(body.selectors) || !body.selectors.length || body.selectors.length > 6) hostFail("device_ai_host_invalid_argument");
  for (const selector of body.selectors) {
    assertDeviceAiPrepareSelector(selector);
    // D9 (decoder-spec 4.3-9): nested key-set closure, prepare wire only.
    assertDeviceAiPrepareWireSelectorKeyClosure(selector);
  }
  const keys = new Set(body.selectors.map(item => item.member_key));
  if (keys.size !== body.selectors.length) hostFail("device_ai_host_invalid_argument");
  if (body.projection_mode === "frozen_decision_closure") {
    if (!Array.isArray(body.approved_closure) || !body.approved_closure.length) hostFail("device_ai_host_invalid_argument");
    if (body.approved_closure.length > 6) hostFail("device_ai_host_invalid_argument");
    for (const selector of body.approved_closure) {
      assertDeviceAiPrepareSelector(selector);
      // D9: closure entries carry the same nested key-set closure (py closure
      // items are the same extra=forbid selector models).
      assertDeviceAiPrepareWireSelectorKeyClosure(selector);
    }
    // D5 (decoder-spec 2.6): closure member_key uniqueness — the same fence as
    // the requested selector list, now asserted at the decoder layer (Rust
    // parity) instead of relying on the buildDeviceAiPrepareBody equality gate.
    const closureKeys = new Set(body.approved_closure.map(item => item.member_key));
    if (closureKeys.size !== body.approved_closure.length) hostFail("device_ai_host_invalid_argument");
  } else if (body.approved_closure !== null) hostFail("device_ai_host_invalid_argument");
  canonicalDeviceAiUuid(body.host_receipt_id);
  canonicalDeviceAiUuid(body.intent_id);
}

// ---------------------------------------------------------------------------
// buildDeviceAiPrepareBody — the preview->prepare wiring (P1-4c). Maps a
// recomputed local preview (computeLocalPreview, projection_binding=
// "recomputed") onto the closed prepare body: expected_projection_sha256 now
// comes from the ON-DEVICE recomputation, so a host can dispatch prepare
// without any prior server round-trip; the server still re-verifies against
// its own authoritative projection (closed 409 on divergence, never silent).
// ---------------------------------------------------------------------------

export interface DeviceAiPrepareBodyInput {
  origin: DeviceAiOriginBindingWire;
  preview: DeviceAiLocalPreviewSummary;
  /** Requested selectors, REQUEST ORDER (must match the previewed selection). */
  selectors: readonly DeviceAiPrepareSelectorWire[];
  /**
   * Exact approved closure for projection_mode="frozen_decision_closure"
   * (user-confirmed resolved set; 1..6 per the server DTO capacity). Must be
   * null in every other mode.
   */
  approvedClosure: readonly DeviceAiPrepareSelectorWire[] | null;
  hostReceiptId: string;
  intentId: string;
}

export function buildDeviceAiPrepareBody(input: DeviceAiPrepareBodyInput): DeviceAiPrepareBody {
  const { origin, preview } = input;
  if (!input || !origin || !preview) hostFail("device_ai_host_invalid_argument");
  if (preview.projection_binding !== "recomputed") hostFail("device_ai_host_preview_unsupported");
  // complete_event_context (test_event) is preview-capable on the port but is
  // NOT on the prepare wire Literal — fail closed instead of a server 422.
  if (!DEVICE_AI_PREPARE_PROJECTION_MODES.has(preview.projection_mode)) hostFail("device_ai_host_preview_unsupported");
  if (!isHash64(origin.expected_sha256) || !isHash64(origin.owner_scope_id)
    || !isSafePositiveInt(origin.expected_byte_count) || !isPlainString(origin.package_id, 64)) hostFail("device_ai_host_invalid_argument");
  // Package echo: the previewed bytes are the bytes the body is about to name.
  if (preview.package_sha256 !== origin.expected_sha256
    || preview.package_byte_count !== origin.expected_byte_count
    || preview.package_schema !== origin.package_schema) hostFail("device_ai_host_package_mismatch");
  if (!Array.isArray(input.selectors) || !input.selectors.length || input.selectors.length > 6) hostFail("device_ai_host_invalid_argument");
  for (const selector of input.selectors) assertDeviceAiPrepareSelector(selector);
  const requestedKeys = input.selectors.map(item => item.member_key);
  if (new Set(requestedKeys).size !== requestedKeys.length) hostFail("device_ai_host_invalid_argument");
  // The preview must be OF this request: located members echo in request order.
  if (JSON.stringify(preview.located_member_keys) !== JSON.stringify(requestedKeys)) hostFail("device_ai_host_invalid_argument");
  let approvedClosure: DeviceAiPrepareSelectorWire[] | null = null;
  if (preview.projection_mode === "frozen_decision_closure") {
    if (!Array.isArray(input.approvedClosure) || !input.approvedClosure.length || input.approvedClosure.length > 6) hostFail("device_ai_host_invalid_argument");
    for (const selector of input.approvedClosure) assertDeviceAiPrepareSelector(selector);
    // Consent set must equal the previewed resolved closure (the port already
    // enforced exact equality against the pack; this is the order-free echo).
    const approvedKeys = input.approvedClosure.map(item => item.member_key);
    if (new Set(approvedKeys).size !== approvedKeys.length) hostFail("device_ai_host_invalid_argument");
    if (JSON.stringify([...approvedKeys].sort()) !== JSON.stringify([...preview.resolved_closure_member_keys].sort())) {
      hostFail("device_ai_host_invalid_argument");
    }
    approvedClosure = [...input.approvedClosure];
  } else if (input.approvedClosure !== null && input.approvedClosure !== undefined) {
    hostFail("device_ai_host_invalid_argument");
  }
  const body: DeviceAiPrepareBody = {
    package_id: origin.package_id,
    expected_sha256: origin.expected_sha256,
    expected_byte_count: origin.expected_byte_count,
    expected_schema: origin.package_schema,
    expected_owner_scope_id: origin.owner_scope_id,
    selectors: [...input.selectors],
    projection_mode: preview.projection_mode as DeviceAiPrepareProjectionMode,
    approved_closure: approvedClosure,
    expected_projection_sha256: preview.projection_sha256,
    question_sha256: preview.question_sha256,
    host_receipt_id: input.hostReceiptId,
    intent_id: input.intentId,
  };
  assertDeviceAiPrepareBody(body);
  return body;
}

function checkedDeviceAiPrepareView(value: unknown): DeviceAiPrepareResultView {
  if (!value || typeof value !== "object") throw new Error("设备 AI 准备记录响应格式不完整。");
  const view = value as Partial<DeviceAiPrepareResultView>;
  if (!isPlainString(view.id, 64) || !isPlainString(view.pack_id, 64)
    || !isHash64(view.projection_sha256) || !isHash64(view.device_context_fingerprint)
    || !isHash64(view.question_sha256) || !isHash64(view.selection_sha256)
    || typeof view.replayed !== "boolean" || typeof view.expired !== "boolean"
    || !isRfc3339WithOffset(view.expires_at)) {
    throw new Error("设备 AI 准备记录响应格式不完整。");
  }
  return value as DeviceAiPrepareResultView;
}

export class DeviceAiHostClient {
  /**
   * POST /v1/ai/device-evidence-packs — metadata-only prepare.
   * `key` is the Idempotency-Key UUID (same key + same body replays the
   * original result; same key + different body is a server 409, transparently
   * surfaced as ApiError). Body is closed-asserted before dispatch.
   */
  async prepare(body: DeviceAiPrepareBody, key: string, signal?: AbortSignal): Promise<DeviceAiPrepareResultView> {
    assertDeviceAiPrepareBody(body);
    const idempotencyKey = canonicalDeviceAiUuid(key);
    const value = await deviceAiInternalRequest<unknown>("/v1/ai/device-evidence-packs", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({
        ...body,
        host_receipt_id: canonicalDeviceAiUuid(body.host_receipt_id),
        intent_id: canonicalDeviceAiUuid(body.intent_id),
      }),
      signal,
    });
    return checkedDeviceAiPrepareView(value);
  }

  /** GET /v1/ai/device-evidence-packs/lookup — read-only recovery by key. */
  async lookupPrepare(key: string, signal?: AbortSignal): Promise<DeviceAiPrepareResultView> {
    const idempotencyKey = canonicalDeviceAiUuid(key);
    const value = await deviceAiInternalRequest<unknown>(
      `/v1/ai/device-evidence-packs/lookup?${new URLSearchParams({ mode: "history", idempotency_key: idempotencyKey })}`, { signal });
    return checkedDeviceAiPrepareView(value);
  }

  /** GET /v1/ai/device-evidence-packs/{prepare_id} — owned immutable read. */
  async readPrepare(prepareId: string, signal?: AbortSignal): Promise<DeviceAiPrepareResultView> {
    if (!isPlainString(prepareId, 64)) hostFail("device_ai_host_invalid_argument");
    const value = await deviceAiInternalRequest<unknown>(
      `/v1/ai/device-evidence-packs/${encodeURIComponent(prepareId)}?mode=history`, { signal });
    return checkedDeviceAiPrepareView(value);
  }

  /**
   * POST /v1/ai/analysis-streams with the closed device branch: the existing
   * AnalysisRequest plus device_submission. The question is normalized
   * (trim-once, codepoint-counted) exactly once here so the server's triple
   * binding digest(trim_once(question)) == preparation.question_sha256 ==
   * consent.question_sha256 can hold. allow_external_processing is the
   * literal true of the closed device branch.
   */
  async submitStream(submission: DeviceAiStreamSubmission, key: string, signal?: AbortSignal): Promise<AIStreamAcceptance> {
    if (!submission || !isPlainString(submission.pack_id, 64) || !isPlainString(submission.prepare_id, 64)) hostFail("device_ai_host_invalid_argument");
    const question = normalizeQuestion(submission.question);
    const consent = submission.provider_consent;
    assertClosedFields(consent, DEVICE_AI_PROVIDER_CONSENT_FIELDS, "ProviderConsent");
    if (!isHash64(consent.expected_pack_fingerprint) || !isHash64(consent.expected_device_context_fingerprint)
      || !isHash64(consent.question_sha256) || !isHash64(consent.expected_provider_policy_fingerprint)
      || !isPlainString(consent.provider, 32) || !isPlainString(consent.model, 120)) hostFail("device_ai_host_invalid_argument");
    if (!isHash64(submission.device_context_fingerprint)) hostFail("device_ai_host_invalid_argument");
    const deviceSubmission = {
      prepare_id: submission.prepare_id,
      host_receipt_id: canonicalDeviceAiUuid(submission.host_receipt_id),
      device_context_fingerprint: submission.device_context_fingerprint,
      provider_consent: consent,
    };
    assertClosedFields(deviceSubmission, DEVICE_AI_SUBMISSION_FIELDS, "DeviceSubmission");
    const body = { pack_id: submission.pack_id, question, allow_external_processing: true, device_submission: deviceSubmission };
    assertClosedFields(body, DEVICE_AI_ANALYSIS_REQUEST_FIELDS, "AnalysisRequest");
    const result = await deviceAiInternalRequest<unknown>("/v1/ai/analysis-streams", {
      method: "POST",
      headers: { "Idempotency-Key": canonicalDeviceAiUuid(key) },
      body: JSON.stringify(body),
      signal,
    });
    const detail = deviceAiInternalStreamDetail(result);
    if (!("replayed" in detail) || typeof (detail as { replayed?: unknown }).replayed !== "boolean") {
      throw new Error("AI 受理结果缺少同请求核对信息。");
    }
    return detail as AIStreamAcceptance;
  }

  /**
   * GET /v1/ai/analysis-streams/lookup — read-only attempt recovery by the
   * frozen analysis key. Never starts or cancels anything (N18).
   */
  async lookupAttempt(key: string, signal?: AbortSignal): Promise<AIStreamDetail> {
    const idempotencyKey = canonicalDeviceAiUuid(key);
    const value = await deviceAiInternalRequest<unknown>(
      `/v1/ai/analysis-streams/lookup?${new URLSearchParams({ mode: "history", idempotency_key: idempotencyKey })}`, { signal });
    return deviceAiInternalStreamDetail(value);
  }
}

// ---------------------------------------------------------------------------
// N18: unknown-outcome resolution. Lookup first, never resubmit on its own.
// ---------------------------------------------------------------------------

export type DeviceAiUnknownOutcomeResolution =
  | { kind: "resolved"; detail: AIStreamDetail }
  | { kind: "not_submitted" }
  | { kind: "unknown_local_claim"; analysis_key: string; resubmission: "same_key_same_body_user_decision_only" }
  | { kind: "cross_session_replay_blocked" }
  | { kind: "journal_integrity_failed"; violations: DeviceAiJournalVerification["violations"] };

/**
 * After a disconnect or crash: read-only lookup with the SAME idempotency key
 * first. A hit returns the existing attempt reference and NOTHING is ever
 * resubmitted automatically. On a miss, only the absence of a local
 * claim_submitted entry makes a fresh user decision legitimate; a recorded
 * claim allows exactly one recovery path — same key, same body, explicit user
 * decision — and a cross-session claim is never replayed (fence 5).
 * Transport failures propagate untouched: the caller retries later and the
 * state stays genuinely unknown.
 */
export async function resolveUnknownOutcome(
  client: DeviceAiHostClient,
  input: { analysisKey: string; journal?: DeviceAiJournal; intentId?: string; signal?: AbortSignal },
): Promise<DeviceAiUnknownOutcomeResolution> {
  const key = canonicalDeviceAiUuid(input.analysisKey);
  let detail: AIStreamDetail | null = null;
  try {
    detail = await client.lookupAttempt(key, input.signal);
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) detail = null;
    else throw cause;
  }
  if (detail !== null) return { kind: "resolved", detail };
  if (!input.journal) return { kind: "not_submitted" };
  const verification = await input.journal.verifyIntegrity();
  if (!verification.ok) return { kind: "journal_integrity_failed", violations: verification.violations };
  const entries = await input.journal.readAll();
  const claims = entries.filter(entry => entry.event?.type === "claim_submitted" && entry.event.analysis_key === key
    && (input.intentId === undefined || entry.event.intent_id === input.intentId));
  if (!claims.length) return { kind: "not_submitted" };
  // Fence 5: a claim recorded under a different session never replays here.
  const crossSession = claims.some(entry => entry.session_id !== input.journal!.sessionId);
  if (crossSession) return { kind: "cross_session_replay_blocked" };
  return { kind: "unknown_local_claim", analysis_key: key, resubmission: "same_key_same_body_user_decision_only" };
}
