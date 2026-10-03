import type { DeviceFallbackIntentV2, DeviceFallbackGrantV2, DeviceFallbackResultV2, DeviceFallbackSlotBindingRequest, DeviceFallbackDecideRequestV2, DeviceFallbackQueryKind, OfflineMemberV2, TireFilter } from "@tire/domain-types";
import { canonicalDeviceFilters, canonicalDeviceQuery, compareCodepoints, selectDeviceTires } from "./device-criteria";
import { ExactJsonNumber, exactSafeInteger, materializeExactMetadata, parseExactJson, stringifyExactJson } from "./exact-json";
export const DEVICE_FALLBACK_NOTICE = "设备历史子集 · 本包保存的历史观察不代表官网当前完整结果。本包没有匹配不表示来源没有产品；空召回或候选页不表示没有风险。此视图不自动用于比较、关注、车库、报告或 AI。";
export const DEVICE_FALLBACK_KINDS: DeviceFallbackQueryKind[] = ["tire", "vehicle_fitments", "recall_campaign", "recall_search"];
const invalid = (): never => { throw Object.assign(new Error("设备授权与本次查询不匹配。"), { code: "OFFLINE_FALLBACK_MISMATCH" }); };
export const fallbackUUID = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
export const fallbackHash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
export const fallbackRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value) && !(value instanceof ExactJsonNumber);
export function fallbackShape(value: unknown, keys: string[]): Record<string, unknown> { if (!fallbackRecord(value) || Object.keys(value).length !== keys.length || keys.some(key => !Object.hasOwn(value, key))) return invalid(); return value; }
export function stableExactDeviceJson(value: unknown): string {
  const sort = (node: unknown): unknown => Array.isArray(node) ? node.map(sort) : fallbackRecord(node) ? Object.fromEntries(Object.keys(node).sort(compareCodepoints).map(key => [key, sort(node[key])])) : node;
  return stringifyExactJson(sort(value));
}
export function cloneExactDeviceValue<T>(value: T): T { return materializeExactMetadata(parseExactJson(stringifyExactJson(value))) as T; }
export const deviceIntentKey = (intent: DeviceFallbackIntentV2) => stableExactDeviceJson(intent);
export function validateDeviceFallbackIntent(value: unknown): asserts value is DeviceFallbackIntentV2 {
  const intent = fallbackShape(value, ["schema", "attempt_id", "query_fingerprint", "source_id", "source_access_generation", "fallback_policy", "authority", "failure", "query_kind", "query", "filters"]);
  if (intent.schema !== "device-fallback-intent@2" || !fallbackUUID(intent.attempt_id) || !fallbackHash(intent.query_fingerprint) || typeof intent.source_id !== "string" || !/^[a-z0-9][a-z0-9_-]{0,99}$/i.test(intent.source_id) || !["ask", "never"].includes(String(intent.fallback_policy)) || !DEVICE_FALLBACK_KINDS.includes(intent.query_kind as DeviceFallbackQueryKind)) return invalid();
  exactSafeInteger(intent.source_access_generation);
  const authority = fallbackShape(intent.authority, ["runtime_session_id", "authority_revision"]); if (!fallbackUUID(authority.runtime_session_id)) return invalid(); exactSafeInteger(authority.authority_revision);
  const failure = fallbackShape(intent.failure, ["scope", "reason", "query_id"]);
  if (failure.scope === "api_transport" ? !["api_network_unavailable", "api_timeout"].includes(String(failure.reason)) || failure.query_id !== null : failure.scope !== "source_response" || !["upstream_network_error", "upstream_timeout"].includes(String(failure.reason)) || !fallbackUUID(failure.query_id)) return invalid();
  const query = canonicalDeviceQuery(intent.query_kind as DeviceFallbackQueryKind, intent.query); if (stableExactDeviceJson(query) !== stableExactDeviceJson(intent.query)) return invalid();
  if (!Array.isArray(intent.filters) || intent.query_kind !== "tire" && intent.filters.length) return invalid();
  const filters = canonicalDeviceFilters(intent.filters); if (stableExactDeviceJson(filters) !== stableExactDeviceJson(intent.filters)) return invalid();
}
export function validateDeviceFallbackBinding(value: unknown, extra: string[] = []): asserts value is DeviceFallbackSlotBindingRequest {
  const row = fallbackShape(value, ["slot_id", "expected_generation", "expected_sha256", "expected_profile_id", "expected_owner_epoch", ...extra]);
  if (!fallbackUUID(row.slot_id) || !fallbackUUID(row.expected_profile_id) || !fallbackHash(row.expected_sha256)) return invalid(); exactSafeInteger(row.expected_generation, 1); exactSafeInteger(row.expected_owner_epoch);
}
export function validateDeviceFallbackDecision(request: unknown): asserts request is DeviceFallbackDecideRequestV2 {
  validateDeviceFallbackBinding(request, ["intent", "decision"]); const row = request as unknown as DeviceFallbackDecideRequestV2;
  if (!["allow", "deny"].includes(row.decision)) return invalid(); validateDeviceFallbackIntent(row.intent);
}
function validateAuthorization(value: unknown) {
  if (!fallbackRecord(value)) return invalid();
  if (value.type === "explicit_once") fallbackShape(value, ["type"]);
  else { const row = fallbackShape(value, ["type", "policy_id", "policy_revision"]); if (row.type !== "policy_once" || !fallbackUUID(row.policy_id)) return invalid(); exactSafeInteger(row.policy_revision, 1); }
}
export function validateDeviceFallbackGrant(value: unknown, request?: DeviceFallbackSlotBindingRequest & { intent: DeviceFallbackIntentV2 }, state?: DeviceFallbackGrantV2["state"]): asserts value is DeviceFallbackGrantV2 {
  const grant = fallbackShape(value, ["schema", "id", "scope", "state", "fallback_authorization", "intent", "profile_id", "owner_epoch", "slot_id", "generation", "package_sha256", "decided_at", "expires_at", "consumed_at"]);
  if (grant.schema !== "device-fallback-grant@2" || !fallbackUUID(grant.id) || !fallbackUUID(grant.profile_id) || !fallbackUUID(grant.slot_id) || !fallbackHash(grant.package_sha256) || grant.scope !== "local_once" || !["allowed", "denied", "consumed", "revoked"].includes(String(grant.state)) || state && grant.state !== state) return invalid();
  exactSafeInteger(grant.owner_epoch); exactSafeInteger(grant.generation, 1); validateDeviceFallbackIntent(grant.intent); validateAuthorization(grant.fallback_authorization);
  if (typeof grant.decided_at !== "string" || typeof grant.expires_at !== "string" || !Number.isFinite(Date.parse(grant.decided_at)) || Date.parse(grant.expires_at) - Date.parse(grant.decided_at) !== 300000 || (grant.state === "consumed" ? typeof grant.consumed_at !== "string" || !Number.isFinite(Date.parse(grant.consumed_at)) || Date.parse(grant.consumed_at) < Date.parse(grant.decided_at) || Date.parse(grant.consumed_at) >= Date.parse(grant.expires_at) : grant.consumed_at !== null)) return invalid();
  if (request && (grant.profile_id !== request.expected_profile_id || grant.owner_epoch !== request.expected_owner_epoch || grant.slot_id !== request.slot_id || grant.generation !== request.expected_generation || grant.package_sha256 !== request.expected_sha256 || deviceIntentKey(grant.intent as DeviceFallbackIntentV2) !== deviceIntentKey(request.intent))) return invalid();
}
export function deviceHistoricalMemberMatches(member: OfflineMemberV2, intent: DeviceFallbackIntentV2): boolean {
  if (!member || member.source?.source_id !== intent.source_id || !member.payload || typeof member.payload !== "object") return false;
  const payload = member.payload as unknown as Record<string, unknown>;
  if (intent.query_kind === "tire") return member.reference.kind === "tire" && selectDeviceTires([payload.variant], intent.filters, intent.query).matches[0] === true;
  if (intent.query_kind === "vehicle_fitments") return member.reference.kind === "vehicle" && fallbackRecord(payload.vehicle) && payload.vehicle.id === intent.query.vehicle_id;
  if (intent.query_kind === "recall_campaign") return member.reference.kind === "recall" && fallbackRecord(payload.evidence) && payload.evidence.campaign_number === intent.query.campaign_number;
  return member.reference.kind === "recall_search" && stableExactDeviceJson(payload.query) === stableExactDeviceJson(intent.query);
}
export function selectDeviceHistoricalMembers(members: OfflineMemberV2[], intent: DeviceFallbackIntentV2) {
  const source = members.filter(member => member.source.source_id === intent.source_id);
  if (intent.query_kind !== "tire") return { members: source.filter(member => deviceHistoricalMemberMatches(member, intent)), selection: null };
  const tire = source.filter(member => member.reference.kind === "tire"), rows = tire.map(member => (member.payload as Record<string, unknown>).variant), selected = selectDeviceTires(rows, intent.filters, intent.query);
  return { members: tire.filter((_, index) => selected.matches[index] === true), selection: selected.selection };
}
export async function createDeviceFallbackIntent(kind: DeviceFallbackQueryKind, query: unknown, filters: TireFilter[], sourceId: string, generation: number, failure: DeviceFallbackIntentV2["failure"], attemptId: string, authority: DeviceFallbackIntentV2["authority"], policy: "ask" | "never" = "ask"): Promise<DeviceFallbackIntentV2> {
  const canonical = { query_kind: kind, query: canonicalDeviceQuery(kind, query), filters: kind === "tire" ? canonicalDeviceFilters(filters) : filters, source_id: sourceId, source_access_generation: generation };
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(stableExactDeviceJson(canonical)));
  const intent = { schema: "device-fallback-intent@2", attempt_id: attemptId, query_fingerprint: Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join(""), ...canonical, fallback_policy: policy, authority, failure } as DeviceFallbackIntentV2;
  validateDeviceFallbackIntent(intent); return cloneExactDeviceValue(intent);
}
export function validateDeviceFallbackResult(value: unknown, request: DeviceFallbackSlotBindingRequest & { intent: DeviceFallbackIntentV2 }): asserts value is DeviceFallbackResultV2 {
  const row = fallbackShape(value, ["schema", "data_state", "fallback_consent", "fallback_authorization", "grant", "slot", "package_schema", "citations", "complete_query_result", "notice", "query_kind", "query", "selection", "members"]);
  validateDeviceFallbackGrant(row.grant, request, "consumed"); const grant = row.grant as DeviceFallbackGrantV2;
  if (row.schema !== "device-fallback-result@2" || row.data_state !== "local_snapshot" || row.fallback_consent !== "local_once" || row.complete_query_result !== false || typeof row.notice !== "string" || !["offline-pack@1", "offline-pack@2"].includes(String(row.package_schema)) || row.query_kind !== request.intent.query_kind || stableExactDeviceJson(row.query) !== stableExactDeviceJson(request.intent.query) || stableExactDeviceJson(row.fallback_authorization) !== stableExactDeviceJson(grant.fallback_authorization) || !Array.isArray(row.members) || row.members.length > 200 || !Array.isArray(row.citations) || row.citations.length > 4000) return invalid();
  const slot = row.slot; if (!fallbackRecord(slot) || slot.locked !== false || slot.previous_owner !== false || slot.slot_id !== grant.slot_id || slot.generation !== grant.generation || slot.sha256 !== grant.package_sha256) return invalid();
  if (row.query_kind === "recall_search" && row.package_schema !== "offline-pack@2") return invalid();
  const keys = new Set<string>(); for (const value of row.members) {
    const member = fallbackShape(value, ["key", "reference", "member_reasons", "privacy_class", "raw_included", "source", "payload"]);
    if (!fallbackHash(member.key) || keys.has(member.key) || member.raw_included !== false || !deviceHistoricalMemberMatches(value as OfflineMemberV2, request.intent)) return invalid(); keys.add(member.key);
  }
  if (row.query_kind === "tire") { const counts = fallbackShape(row.selection, ["filters", "source_count", "matched_count", "excluded_count", "undetermined_count"]); for (const key of ["source_count", "matched_count", "excluded_count", "undetermined_count"]) exactSafeInteger(counts[key], 0, 200); if (counts.matched_count !== row.members.length || Number(counts.source_count) !== Number(counts.matched_count) + Number(counts.excluded_count) + Number(counts.undetermined_count) || stableExactDeviceJson(counts.filters) !== stableExactDeviceJson(request.intent.filters)) return invalid(); } else if (row.selection !== null) return invalid();
  const citations = new Set<string>(); for (const value of row.citations) {
    const citation = fallbackShape(value, ["schema", "id", "profile_id", "owner_epoch", "slot_id", "generation", "package_sha256", "member_key", "document_id", "record_index", "observed_at", "verified_at", "verification_id"]);
    if (citation.schema !== "device-citation@1" || typeof citation.id !== "string" || !citation.id.startsWith("device:") || citations.has(citation.id) || citation.profile_id !== grant.profile_id || citation.owner_epoch !== grant.owner_epoch || citation.slot_id !== grant.slot_id || citation.generation !== grant.generation || citation.package_sha256 !== grant.package_sha256 || !keys.has(String(citation.member_key))) return invalid();
    if (citation.record_index !== null) exactSafeInteger(citation.record_index, 0, 3999); citations.add(citation.id);
  }
}
