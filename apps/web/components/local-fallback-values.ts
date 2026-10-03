import type { LocalFallbackDecideRequest, LocalFallbackFailure, LocalFallbackGrant, LocalFallbackIntent, LocalFallbackResult, OfflineMember, QueryResult, TireQuery, TireFilter } from "@tire/domain-types";
import { ApiTransportError } from "@tire/api-client";
import { OfflineError } from "./offline-crypto";

export const FALLBACK_TTL_MS = 300_000;
export const FALLBACK_NOTICE = "仅显示所选本机包中的历史记录，不是完整在线查询，也不代表当前身份、生命周期或 AI 使用授权。附带的整包历史字段上下文可能包含其他来源或回执。";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const sha = /^[0-9a-f]{64}$/;
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const exact = (value: unknown, keys: string[]): value is Record<string, unknown> => object(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const nonempty = (value: unknown, max: number): value is string => typeof value === "string" && value.trim().length > 0 && value.length <= max && !/[\u0000-\u001f]/.test(value);
const integer = (value: unknown, min = 0) => Number.isSafeInteger(value) && Number(value) >= min && Number(value) < Number.MAX_SAFE_INTEGER;
export function validateFallbackIntent(value: unknown): asserts value is LocalFallbackIntent {
  if (!exact(value, ["schema", "attempt_id", "query_fingerprint", "source_id", "source_access_generation", "query", "filters", "failure"]) || value.schema !== "device-fallback-intent@1"
    || typeof value.attempt_id !== "string" || !uuid.test(value.attempt_id) || typeof value.query_fingerprint !== "string" || !sha.test(value.query_fingerprint)
    || typeof value.source_id !== "string" || !/^[a-z0-9-]{1,80}$/.test(value.source_id) || !integer(value.source_access_generation)
    || !exact(value.query, ["model", "size"]) || !nonempty(value.query.model, 200) || !(value.query.size === null || nonempty(value.query.size, 80))
    || !Array.isArray(value.filters) || value.filters.length || !exact(value.failure, ["scope", "reason", "query_id"])) throw new OfflineError("OFFLINE_FALLBACK_INVALID");
  const failure = value.failure;
  if (!(failure.scope === "api_transport" && ["api_network_unavailable", "api_timeout"].includes(String(failure.reason)) && failure.query_id === null)
    && !(failure.scope === "source_response" && ["upstream_timeout", "upstream_network_error"].includes(String(failure.reason)) && typeof failure.query_id === "string" && uuid.test(failure.query_id))) throw new OfflineError("OFFLINE_FALLBACK_INVALID");
}
export function validateFallbackDecision(value: unknown): asserts value is LocalFallbackDecideRequest {
  if (!exact(value, ["intent", "slot_id", "expected_generation", "expected_sha256", "expected_profile_id", "expected_owner_epoch", "decision"]) || typeof value.slot_id !== "string" || !uuid.test(value.slot_id)
    || !integer(value.expected_generation, 1) || typeof value.expected_sha256 !== "string" || !sha.test(value.expected_sha256) || !nonempty(value.expected_profile_id, 80)
    || !integer(value.expected_owner_epoch) || !["allow", "deny"].includes(String(value.decision))) throw new OfflineError("OFFLINE_FALLBACK_INVALID");
  validateFallbackIntent(value.intent);
}
export function validateFallbackCommand(value: unknown, consuming: boolean): void {
  if (!exact(value, consuming ? ["grant_id", "intent"] : ["grant_id"]) || typeof value.grant_id !== "string" || !uuid.test(value.grant_id)) throw new OfflineError("OFFLINE_FALLBACK_INVALID");
  if (consuming) validateFallbackIntent(value.intent);
}
export function fallbackIntentKey(intent: LocalFallbackIntent): string {
  return JSON.stringify([intent.schema, intent.attempt_id, intent.query_fingerprint, intent.source_id, intent.source_access_generation,
    intent.query.model, intent.query.size, intent.filters, intent.failure.scope, intent.failure.reason, intent.failure.query_id]);
}
export function fallbackMemberMatches(member: OfflineMember, intent: LocalFallbackIntent): boolean {
  const variant = member.payload.variant;
  return member.reference.kind === "tire" && member.source.source_id === intent.source_id && object(variant)
    && variant.model === intent.query.model && (intent.query.size === null || variant.size === intent.query.size);
}
export function fallbackFailure(cause: unknown, sourceId: string): LocalFallbackFailure | null {
  if (cause instanceof ApiTransportError) return { scope: "api_transport", reason: cause.code, query_id: null };
  if (!object(cause)) return null;
  const data = cause as unknown as QueryResult;
  if (data.source_id !== sourceId || !["source_unavailable", "consent_required"].includes(data.data_state) || !uuid.test(data.query_id || "")) return null;
  return data.reason === "upstream_timeout" || data.reason === "upstream_network_error" ? { scope: "source_response", reason: data.reason, query_id: data.query_id } : null;
}
function supportedQueryInput(query: TireQuery): boolean {
  // Mirror the ordinary API query boundary before a transport failure can
  // bypass server validation. Checking compact syntax does not alter the intent.
  if (!nonempty(query.model, 120)) return false;
  if (query.size === undefined) return true;
  if (!nonempty(query.size, 24)) return false;
  const match = /^(\d{3})\/(\d{2})(ZR|R)(\d{2}(?:\.5)?)$/.exec(query.size.toUpperCase().replace(/\s+/g, ""));
  return !!match && Number(match[1]) >= 100 && Number(match[1]) <= 455 && Number(match[2]) >= 20 && Number(match[2]) <= 95 && Number(match[4]) >= 10 && Number(match[4]) <= 30;
}
export async function createFallbackIntent(query: TireQuery, filters: readonly TireFilter[], sourceId: string, accessGeneration: number, failure: LocalFallbackFailure, attemptId: string): Promise<LocalFallbackIntent | null> {
  if (filters.length || !supportedQueryInput(query) || Object.keys(query).some(key => key !== "model" && key !== "size")) return null;
  const frozen = { model: query.model!, size: query.size ?? null };
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify([sourceId, accessGeneration, frozen, []])));
  const intent: LocalFallbackIntent = { schema: "device-fallback-intent@1", attempt_id: attemptId, query_fingerprint: Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join(""), source_id: sourceId,
    source_access_generation: accessGeneration, query: frozen, filters: [], failure: { ...failure } };
  validateFallbackIntent(intent); return intent;
}
export function validateFallbackReceipt(grant: LocalFallbackGrant, request: LocalFallbackDecideRequest, state: LocalFallbackGrant["state"]): void {
  if (!grant || grant.schema !== "device-fallback-grant@1" || !uuid.test(grant.id || "") || grant.scope !== "local_once" || grant.state !== state
    || grant.profile_id !== request.expected_profile_id || grant.owner_epoch !== request.expected_owner_epoch || grant.slot_id !== request.slot_id || grant.generation !== request.expected_generation || grant.package_sha256 !== request.expected_sha256
    || !Number.isFinite(Date.parse(grant.decided_at)) || Date.parse(grant.expires_at) - Date.parse(grant.decided_at) !== FALLBACK_TTL_MS
    || (state === "consumed" ? !grant.consumed_at || !Number.isFinite(Date.parse(grant.consumed_at)) : grant.consumed_at !== null)) throw new OfflineError("OFFLINE_FALLBACK_MISMATCH");
  validateFallbackIntent(grant.intent);
  if (fallbackIntentKey(grant.intent) !== fallbackIntentKey(request.intent)) throw new OfflineError("OFFLINE_FALLBACK_MISMATCH");
}
export function validateFallbackResult(value: LocalFallbackResult, request: LocalFallbackDecideRequest): void {
  const grant = value?.grant, slot = value?.slot;
  validateFallbackReceipt(grant, request, "consumed");
  if (value?.schema !== "device-fallback-result@1" || value.data_state !== "local_snapshot" || value.fallback_consent !== "local_once" || value.complete_query_result !== false
    || !grant || grant.state !== "consumed" || grant.scope !== "local_once" || !grant.consumed_at || fallbackIntentKey(grant.intent) !== fallbackIntentKey(request.intent)
    || grant.profile_id !== request.expected_profile_id || grant.owner_epoch !== request.expected_owner_epoch || grant.slot_id !== request.slot_id || grant.generation !== request.expected_generation || grant.package_sha256 !== request.expected_sha256
    || !slot || slot.locked || slot.previous_owner || slot.slot_id !== request.slot_id || slot.generation !== request.expected_generation || slot.sha256 !== request.expected_sha256
    || !Array.isArray(value.members) || value.members.some(member => !fallbackMemberMatches(member, request.intent))) throw new OfflineError("OFFLINE_FALLBACK_MISMATCH");
}
