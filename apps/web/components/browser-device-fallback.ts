import type { AnyOfflineEnvelope, DeviceFallbackAuthorityBinding, DeviceFallbackAuthorizeRequest, DeviceFallbackAuthorizeResult,
  DeviceFallbackCapabilities, DeviceFallbackConsumeRequestV2, DeviceFallbackDecideRequestV2, DeviceFallbackGrantV2,
  DeviceFallbackIntentV2, DeviceFallbackPackageBinding, DeviceFallbackPolicy, DeviceFallbackPolicyApplyRequest, DeviceFallbackPolicyChoice,
  DeviceFallbackPolicyPreview, DeviceFallbackPolicyPreviewRequest, DeviceFallbackPolicyRequest, DeviceFallbackPolicyScope,
  DeviceFallbackResultV2, DeviceFallbackSourceAuthority, DeviceFallbackStatus, DeviceFallbackStorageV2, OfflineSlot } from "@tire/domain-types";
import { apiTransportAuthorityEpoch, cloneExactDeviceValue, DEVICE_FALLBACK_KINDS, DEVICE_FALLBACK_NOTICE, deviceIntentKey,
  exactSafeInteger, fallbackDenialQueryKey, fallbackHash, fallbackRecord, fallbackShape, fallbackUUID, materializeExactMetadata, observeBrowserFallbackDenials, parseExactJson,
  selectDeviceHistoricalMembers, stableExactDeviceJson, stringifyExactJson, tireApi, validateDeviceFallbackBinding,
  validateDeviceFallbackDecision, validateDeviceFallbackGrant, validateDeviceFallbackIntent, validateDeviceFallbackResult } from "@tire/api-client";
import { OfflineError, openOfflineBytes, sealOfflineBytes, type OfflineCiphertext } from "./offline-crypto";

export interface FallbackProfile { profile_id: string; owner_epoch: number; key: CryptoKey }
export interface FallbackStoredSlot { slot_id: string; generation: number; owner_epoch: number; deleted: boolean; metadata: OfflineCiphertext | null; payload: OfflineCiphertext | null }
export interface FallbackLocated { owner: FallbackProfile; stored: FallbackStoredSlot; slot: OfflineSlot; binding: DeviceFallbackPackageBinding | null }
export interface BrowserFallbackAdapter {
  profile(): Promise<FallbackProfile>;
  locate(request: { slot_id: string; expected_generation: number }): Promise<FallbackLocated>;
  bindings(): Promise<{ bindings: DeviceFallbackPackageBinding[]; missing: DeviceFallbackStatus["missing_package_bindings"] }>;
  load(value: FallbackLocated): Promise<AnyOfflineEnvelope>;
  transaction<T>(work: (tx: IDBTransaction) => Promise<T>): Promise<T>;
  result<T>(request: IDBRequest<T>): Promise<T>;
  fence(tx: IDBTransaction, owner: FallbackProfile, stored?: FallbackStoredSlot): Promise<void>;
  attempts: Set<string>;
  legacyPendingCount(): number;
}
interface Denials { runtime_session_id: string; owner_epoch: number; transport_epoch: number; owner_scope_id: string | null; query_ids: string[]; overflow: boolean }
interface State { schema: "device-fallback-store@2"; policies: DeviceFallbackPolicy[]; receipts: DeviceFallbackGrantV2[]; warehouse_denials?: Denials }
interface Sidecar { revision: number; encrypted: OfflineCiphertext }
interface Snapshot { owner: FallbackProfile; record: Sidecar | undefined; data: State }
interface Pending { grant: DeviceFallbackGrantV2; monotonic: number; authority: DeviceFallbackSourceAuthority }
interface Preview { value: DeviceFallbackPolicyPreview; request: DeviceFallbackPolicyPreviewRequest; wall: number; monotonic: number }
const KEY = "device-fallback-policy-v2", LOCK = "tire-device-fallback-v2", TTL = 300000;
function fail(code = "OFFLINE_FALLBACK_INVALID"): never { throw new OfflineError(code); }
const next = (value: number) => { if (!Number.isSafeInteger(value) || value < 0 || value >= Number.MAX_SAFE_INTEGER) return fail("OFFLINE_GENERATION_EXHAUSTED"); return value + 1; };
const same = (a: unknown, b: unknown) => stableExactDeviceJson(a) === stableExactDeviceJson(b);
const sameBuffer = (a: ArrayBuffer | Uint8Array, b: ArrayBuffer | Uint8Array) => { const x = new Uint8Array(a instanceof Uint8Array ? a.buffer : a, a instanceof Uint8Array ? a.byteOffset : 0, a.byteLength), y = new Uint8Array(b instanceof Uint8Array ? b.buffer : b, b instanceof Uint8Array ? b.byteOffset : 0, b.byteLength); return x.length === y.length && x.every((v, i) => v === y[i]); };
const sameCipher = (a: OfflineCiphertext | undefined, b: OfflineCiphertext | undefined) => !a || !b ? a === b : sameBuffer(a.iv, b.iv) && sameBuffer(a.ciphertext, b.ciphertext);
const stamp = () => new Date().toISOString();
const binding = (owner: FallbackProfile, revision: number) => JSON.stringify(["device-fallback-policy-store@2", owner.profile_id, revision]);
export const browserFallbackCapabilities = (): DeviceFallbackCapabilities => ({ schema: "device-fallback-capabilities@1", intent_schemas: ["device-fallback-intent@1", "device-fallback-intent@2"], supported_pack_schemas: ["offline-pack@1", "offline-pack@2"], query_kinds: [...DEVICE_FALLBACK_KINDS], filter_contract: "tire-query-filters@1", unicode_contract: "tire-query-unicode@1", continuous_policies: true, max_filters: 16, max_policies: 16, max_sources: 10, max_pending_grants: 16, max_attempts_per_runtime: 1024, max_audit_receipts: 64, grant_ttl_seconds: 300 });

function scopePins(scope: DeviceFallbackPolicyScope) { return scope.kind === "source" ? [{ source_id: scope.source_id, access_generation: scope.access_generation, query_kinds: scope.query_kinds }] : scope.kind === "query" ? scope.sources.map(source => ({ ...source, query_kinds: [scope.query_kind] })) : scope.sources; }
function matching(policy: DeviceFallbackPolicy, sourceId: string, generation: number | null, kind: string): boolean { return scopePins(policy.scope).some(pin => pin.source_id === sourceId && (generation === null || pin.access_generation === generation) && pin.query_kinds.includes(kind as never)); }
function active(policy: DeviceFallbackPolicy): boolean { const now = Date.now(); return policy.state === "enabled" && now >= Date.parse(policy.approved_at) && now < Date.parse(policy.expires_at); }
function validatePolicyChoice(choice: DeviceFallbackPolicyChoice, authority?: DeviceFallbackSourceAuthority): void {
  fallbackShape(choice, ["mode", "scope", "binding", "allow_same_scope_sync_binding_advance"]);
  if (!["ask", "never", "session_allow", "source_allow", "query_allow"].includes(choice.mode)) fail();
  const allow = choice.mode.endsWith("_allow");
  const scope = choice.scope;
  if (!scope || !["session", "source", "query"].includes(scope.kind)) fail();
  if (scope.kind === "source") fallbackShape(scope, ["kind", "source_id", "access_generation", "query_kinds"]);
  else fallbackShape(scope, scope.kind === "session" ? ["kind", "sources"] : ["kind", "query_kind", "sources"]);
  if (scope.kind === "query" && !DEVICE_FALLBACK_KINDS.includes(scope.query_kind)) fail();
  const pins = scopePins(scope), ids = new Set<string>(); if (!pins.length || pins.length > 10) fail();
  for (const pin of pins) {
    if (typeof pin.source_id !== "string" || !/^[a-z0-9][a-z0-9_-]{0,99}$/i.test(pin.source_id) || ids.has(pin.source_id)) fail(); ids.add(pin.source_id); exactSafeInteger(pin.access_generation);
    if (!Array.isArray(pin.query_kinds) || !pin.query_kinds.length || pin.query_kinds.length > 4 || new Set(pin.query_kinds).size !== pin.query_kinds.length || pin.query_kinds.some(kind => !DEVICE_FALLBACK_KINDS.includes(kind))) fail();
    const source = authority?.sources.find(source => source.source_id === pin.source_id);
    if (authority && (!source || source.access_generation !== pin.access_generation || allow && (!source.can_query || !source.can_fetch) || pin.query_kinds.some(kind => !source.query_kinds.includes(kind)))) fail("OFFLINE_FALLBACK_AUTHORITY_CHANGED");
  }
  if (scope.kind !== "source") {
    for (const pin of scope.sources) fallbackShape(pin, scope.kind === "session" ? ["source_id", "access_generation", "query_kinds"] : ["source_id", "access_generation"]);
  }
  if (allow) {
    if (choice.mode !== scope.kind + "_allow" || typeof choice.allow_same_scope_sync_binding_advance !== "boolean" || !choice.binding) fail();
    const value = choice.binding; fallbackShape(value, ["binding_revision", "slot_id", "generation", "package_id", "sha256", "history_scope_fingerprint", "source_ids"]);
    for (const key of ["binding_revision", "generation"] as const) exactSafeInteger(value[key], 1);
    if (!fallbackUUID(value.slot_id) || !fallbackUUID(value.package_id) || !fallbackHash(value.sha256) || !fallbackHash(value.history_scope_fingerprint) || !Array.isArray(value.source_ids) || value.source_ids.length > 200 || new Set(value.source_ids).size !== value.source_ids.length || value.source_ids.some(id => typeof id !== "string")) fail();
    if (choice.allow_same_scope_sync_binding_advance && value.source_ids.some(sourceId => !ids.has(sourceId))) fail("OFFLINE_FALLBACK_SYNC_ADVANCE_SCOPE_UNAVAILABLE");
  } else if (choice.binding !== null || choice.allow_same_scope_sync_binding_advance !== false) fail();
}
function validateState(data: State): void {
  fallbackShape(data, ["schema", "policies", "receipts", ...(Object.hasOwn(data, "warehouse_denials") ? ["warehouse_denials"] : [])]); if (data.schema !== "device-fallback-store@2" || !Array.isArray(data.policies) || data.policies.length > 64 || data.policies.filter(policy => policy?.state !== "revoked").length > 16 || !Array.isArray(data.receipts) || data.receipts.length > 64) fail("OFFLINE_CORRUPT");
  if (data.warehouse_denials) {
    const denied = data.warehouse_denials; fallbackShape(denied, ["runtime_session_id", "owner_epoch", "transport_epoch", "owner_scope_id", "query_ids", "overflow"]);
    if (!fallbackUUID(denied.runtime_session_id) || denied.owner_scope_id !== null && !fallbackHash(denied.owner_scope_id) || typeof denied.overflow !== "boolean" || !Array.isArray(denied.query_ids) || denied.query_ids.length > 1024 || new Set(denied.query_ids).size !== denied.query_ids.length || denied.query_ids.some(id => typeof id !== "string" || !id || id.length > 64 || /[\r\n\0]/.test(id))) fail("OFFLINE_CORRUPT");
    exactSafeInteger(denied.owner_epoch); exactSafeInteger(denied.transport_epoch);
  }
  const ids = new Set<string>();
  for (const policy of data.policies) {
    fallbackShape(policy, ["schema", "policy_id", "policy_revision", "state", "profile_id", "owner_epoch", "owner_scope_id", "runtime_session_id", "approved_at", "updated_at", "expires_at", "fingerprint", "reason", "mode", "scope", "binding", "allow_same_scope_sync_binding_advance"]);
    validatePolicyChoice({ mode: policy.mode, scope: policy.scope, binding: policy.binding, allow_same_scope_sync_binding_advance: policy.allow_same_scope_sync_binding_advance } as DeviceFallbackPolicyChoice);
    if (policy.schema !== "device-fallback-policy@1" || !fallbackUUID(policy.policy_id) || ids.has(policy.policy_id) || !fallbackUUID(policy.profile_id) || !fallbackHash(policy.owner_scope_id) || !fallbackHash(policy.fingerprint) || !["enabled", "paused", "revoked"].includes(policy.state) || (policy.runtime_session_id !== null && !fallbackUUID(policy.runtime_session_id)) || ![policy.approved_at, policy.updated_at, policy.expires_at].every(value => typeof value === "string" && Number.isFinite(Date.parse(value))) || Date.parse(policy.expires_at) <= Date.parse(policy.approved_at) || policy.reason !== null && typeof policy.reason !== "string") fail("OFFLINE_CORRUPT");
    exactSafeInteger(policy.policy_revision, 1); exactSafeInteger(policy.owner_epoch); ids.add(policy.policy_id);
    if (policy.scope.kind === "session" ? policy.runtime_session_id === null : policy.runtime_session_id !== null) fail("OFFLINE_CORRUPT");
  }
  for (const receipt of data.receipts) validateDeviceFallbackGrant(receipt);
}
function fullPolicyCapacity(data: State, previous?: DeviceFallbackPolicy): boolean { return (!previous || previous.state === "revoked") && data.policies.filter(policy => policy.state !== "revoked").length >= 16; }
function retainPolicies(data: State): void {
  if (data.policies.filter(policy => policy.state !== "revoked").length > 16) fail("OFFLINE_FALLBACK_CAPACITY");
  if (data.policies.length <= 64) return;
  const revoked = data.policies.filter(policy => policy.state === "revoked").sort((a, b) => Date.parse(a.updated_at) - Date.parse(b.updated_at) || (a.policy_id < b.policy_id ? -1 : a.policy_id > b.policy_id ? 1 : 0));
  const remove = new Set(revoked.slice(0, data.policies.length - 64).map(policy => policy.policy_id));
  data.policies = data.policies.filter(policy => !remove.has(policy.policy_id));
  if (data.policies.length > 64) fail("OFFLINE_FALLBACK_CAPACITY");
}

export function createBrowserDeviceFallback(adapter: BrowserFallbackAdapter): DeviceFallbackStorageV2 & {
  legacyFence(intent: import("@tire/domain-types").LocalFallbackIntent): Promise<(tx: IDBTransaction) => Promise<void>>;
  prepareInstall(owner: FallbackProfile, slot: OfflineSlot, packageBinding: DeviceFallbackPackageBinding, isSync: boolean): Promise<{ guard(tx: IDBTransaction): Promise<void>; write(tx: IDBTransaction): Promise<void> }>;
  resetOwner(committed?: boolean): void;
  prepareOwnerReset(): Promise<{ guard(tx: IDBTransaction): Promise<void>; write(tx: IDBTransaction): Promise<void> }>;
  pendingCount(): number;
} {
  const runtime = crypto.randomUUID(), pending = new Map<string, Pending>(), previews = new Map<string, Preview>();
  let authority: DeviceFallbackSourceAuthority | null = null, tail: Promise<unknown> = Promise.resolve();
  let denialUnavailable = false;
  const observedDeniedQueries = new Set<string>();
  const channel = typeof window !== "undefined" && typeof BroadcastChannel !== "undefined" ? new BroadcastChannel(LOCK) : null;
  channel?.addEventListener("message", () => { pending.clear(); previews.clear(); if (typeof window !== "undefined") window.dispatchEvent(new Event("tire-offline-fallback-changed")); });
  const notify = () => { channel?.postMessage({ type: "changed" }); if (typeof window !== "undefined") window.dispatchEvent(new Event("tire-offline-fallback-changed")); };
  const locked = <T,>(work: () => Promise<T>): Promise<T> => { const run = async (): Promise<T> => typeof navigator !== "undefined" && navigator.locks ? await navigator.locks.request(LOCK, async () => await work()) as T : await work(); const result = tail.then(run, run); tail = result.catch(() => {}); return result; };
  const unknownAuthority = (owner: FallbackProfile): DeviceFallbackSourceAuthority => ({ schema: "device-fallback-source-authority@1", runtime_session_id: runtime, authority_revision: authority ? next(authority.authority_revision) : 0, state: "unknown", observed_at: null, profile_id: owner.profile_id, owner_epoch: owner.owner_epoch, owner_scope_id: null, sources: [] });
  async function currentAuthority(owner: FallbackProfile) { if (!authority || authority.profile_id !== owner.profile_id || authority.owner_epoch !== owner.owner_epoch) { authority = unknownAuthority(owner); pending.clear(); previews.clear(); } return authority; }
  async function snapshot(): Promise<Snapshot> {
    const owner = await adapter.profile(), record = await adapter.transaction(tx => adapter.result<Sidecar | undefined>(tx.objectStore("system").get(KEY)));
    if (!record) return { owner, record, data: { schema: "device-fallback-store@2", policies: [], receipts: [] } };
    exactSafeInteger(record.revision, 1); let data: State;
    try { data = materializeExactMetadata(parseExactJson(await openOfflineBytes(owner.key, record.encrypted, binding(owner, record.revision)))) as State; } catch { return fail("OFFLINE_CORRUPT"); }
    validateState(data); const value = { owner, record, data }; let changed = false, denialChanged = false;
    // Validate the old shape before canonicalizing valid same-runtime aliases.
    const denied = data.warehouse_denials;
    if (denied?.runtime_session_id === runtime) {
      const keys = [...new Set(denied.query_ids.map(fallbackDenialQueryKey))];
      if (!same(keys, denied.query_ids)) { denied.query_ids = keys; denialChanged = true; }
    }
    for (const policy of data.policies) if (policy.state === "enabled") {
      const reason = Date.now() < Date.parse(policy.approved_at) ? "clock_rollback" : Date.now() >= Date.parse(policy.expires_at) ? "expired" : policy.runtime_session_id !== null && policy.runtime_session_id !== runtime ? "runtime_changed" : null;
      if (reason) { policy.state = "paused"; policy.reason = reason; policy.policy_revision = next(policy.policy_revision); policy.updated_at = stamp(); changed = true; }
    }
    if (changed || denialChanged) { if (changed) { pending.clear(); previews.clear(); } return commit(value); } return value;
  }
  async function current(tx: IDBTransaction, value: Snapshot, stored?: FallbackStoredSlot) {
    await adapter.fence(tx, value.owner, stored); const record = await adapter.result<Sidecar | undefined>(tx.objectStore("system").get(KEY));
    if ((record?.revision || 0) !== (value.record?.revision || 0) || !sameCipher(record?.encrypted, value.record?.encrypted)) fail("OFFLINE_FALLBACK_POLICY_CHANGED");
  }
  async function encoded(value: Snapshot): Promise<Sidecar> { retainPolicies(value.data); validateState(value.data); const revision = next(value.record?.revision || 0); return { revision, encrypted: await sealOfflineBytes(value.owner.key, new TextEncoder().encode(stringifyExactJson(value.data)), binding(value.owner, revision)) }; }
  async function commit(value: Snapshot, stored?: FallbackStoredSlot, extra?: (tx: IDBTransaction) => Promise<void>): Promise<Snapshot> {
    const record = await encoded(value); await adapter.transaction(async tx => { await current(tx, value, stored); if (extra) await extra(tx); await adapter.result(tx.objectStore("system").put(record, KEY)); }); return { ...value, record };
  }
  function requireNoWarehouseDenial(value: Snapshot, intent: { attempt_id: string; failure: import("@tire/domain-types").LocalFallbackFailure }): void {
    if (intent.failure.scope !== "source_response") return;
    const denied = value.data.warehouse_denials;
    const current = denied?.runtime_session_id === runtime && denied.owner_epoch === value.owner.owner_epoch && denied.transport_epoch === apiTransportAuthorityEpoch() && (denied.owner_scope_id === null || !authority?.owner_scope_id || denied.owner_scope_id === authority.owner_scope_id);
    const queryKey = fallbackDenialQueryKey(intent.failure.query_id);
    const reason = denialUnavailable || current && denied.overflow ? "OFFLINE_FALLBACK_CAPACITY" : observedDeniedQueries.has(queryKey) || current && denied.query_ids.includes(queryKey) ? "OFFLINE_FALLBACK_NEVER" : null;
    if (reason) { if (!adapter.attempts.has(intent.attempt_id) && adapter.attempts.size >= 1024) fail("OFFLINE_FALLBACK_CAPACITY"); adapter.attempts.add(intent.attempt_id); fail(reason); }
  }
  observeBrowserFallbackDenials(async (queryId, epoch) => {
    const queryKey = fallbackDenialQueryKey(queryId);
    let capture: { owner: FallbackProfile; ownerScope: string | null } | null = null;
    try { capture = await locked(async () => { const owner = await adapter.profile(), auth = await currentAuthority(owner); return { owner, ownerScope: auth.owner_scope_id }; }); } catch { /* A successful denial will close fallback if durable observation is unavailable. */ }
    return async () => {
      if (!capture) { denialUnavailable = true; return; }
      try { await locked(async () => {
        const value = await snapshot();
        if (value.owner.profile_id !== capture!.owner.profile_id || value.owner.owner_epoch !== capture!.owner.owner_epoch || epoch !== apiTransportAuthorityEpoch() || capture!.ownerScope !== null && authority?.owner_scope_id !== capture!.ownerScope) return;
        let denied = value.data.warehouse_denials;
        if (!denied || denied.runtime_session_id !== runtime || denied.owner_epoch !== value.owner.owner_epoch || denied.transport_epoch !== epoch) denied = { runtime_session_id: runtime, owner_epoch: value.owner.owner_epoch, transport_epoch: epoch, owner_scope_id: capture!.ownerScope, query_ids: [...observedDeniedQueries], overflow: denialUnavailable };
        if (!denied.query_ids.includes(queryKey)) { if (denied.query_ids.length >= 1024) denied.overflow = true; else denied.query_ids.push(queryKey); }
        value.data.warehouse_denials = denied;
        await commit(value, undefined, async () => { if (epoch !== apiTransportAuthorityEpoch()) fail("OFFLINE_FALLBACK_AUTHORITY_CHANGED"); });
        if (denied.query_ids.includes(queryKey)) observedDeniedQueries.add(queryKey); if (denied.overflow) denialUnavailable = true; notify();
      }); } catch { denialUnavailable = true; }
    };
  });
  function requireAuthority(owner: FallbackProfile, wanted: DeviceFallbackAuthorityBinding, intent?: DeviceFallbackIntentV2) {
    const value = authority; if (!value || value.state !== "last_observed" || value.profile_id !== owner.profile_id || value.owner_epoch !== owner.owner_epoch || wanted.runtime_session_id !== runtime || wanted.authority_revision !== value.authority_revision || !value.owner_scope_id) fail("OFFLINE_FALLBACK_AUTHORITY_UNKNOWN");
    if (intent) { const source = value.sources.find(source => source.source_id === intent.source_id); if (!source || source.access_generation !== intent.source_access_generation || !source.can_query || !source.can_fetch || !source.query_kinds.includes(intent.query_kind)) fail("OFFLINE_FALLBACK_AUTHORITY_CHANGED"); }
    return value;
  }
  function requireNoNever(value: Snapshot, intent: DeviceFallbackIntentV2) {
    requireNoWarehouseDenial(value, intent);
    if (intent.fallback_policy === "never" || value.data.policies.some(policy => policy.profile_id === value.owner.profile_id && policy.owner_epoch === value.owner.owner_epoch && active(policy) && policy.mode === "never" && matching(policy, intent.source_id, intent.source_access_generation, intent.query_kind))) { if (!adapter.attempts.has(intent.attempt_id) && adapter.attempts.size >= 1024) fail("OFFLINE_FALLBACK_CAPACITY"); adapter.attempts.add(intent.attempt_id); fail("OFFLINE_FALLBACK_NEVER"); }
  }
  function requirePending(value: Snapshot, grant: DeviceFallbackGrantV2) {
    const auth = requireAuthority(value.owner, grant.intent.authority, grant.intent); requireNoNever(value, grant.intent);
    if (grant.profile_id !== value.owner.profile_id || grant.owner_epoch !== value.owner.owner_epoch) fail("OFFLINE_OWNER_LOCKED");
    if (grant.fallback_authorization.type === "policy_once") {
      const authorization = grant.fallback_authorization, policy = value.data.policies.find(policy => policy.policy_id === authorization.policy_id);
      if (!policy || policy.policy_revision !== authorization.policy_revision || !active(policy) || !policy.mode.endsWith("_allow") || !matching(policy, grant.intent.source_id, grant.intent.source_access_generation, grant.intent.query_kind) || policy.owner_scope_id !== auth.owner_scope_id || policy.runtime_session_id !== null && policy.runtime_session_id !== runtime || !policy.binding || policy.binding.slot_id !== grant.slot_id || policy.binding.generation !== grant.generation || policy.binding.sha256 !== grant.package_sha256) fail("OFFLINE_FALLBACK_POLICY_CHANGED");
    }
  }
  function expired(value: Pending) { const wall = Date.now(), mono = performance.now(); return wall < Date.parse(value.grant.decided_at) || wall >= Date.parse(value.grant.expires_at) || mono < value.monotonic || mono - value.monotonic >= TTL; }
  async function locate(request: DeviceFallbackAuthorizeRequest): Promise<FallbackLocated> {
    const value = await adapter.locate({ slot_id: request.slot_id, expected_generation: request.expected_generation });
    if (value.owner.profile_id !== request.expected_profile_id || value.owner.owner_epoch !== request.expected_owner_epoch || value.slot.locked || value.slot.previous_owner || value.slot.owner_scope_id !== authority?.owner_scope_id) fail("OFFLINE_OWNER_LOCKED");
    if (value.slot.generation !== request.expected_generation || value.slot.sha256 !== request.expected_sha256) fail("OFFLINE_STALE_GENERATION"); return value;
  }
  async function issue(value: Snapshot, request: DeviceFallbackDecideRequestV2, authorization: DeviceFallbackGrantV2["fallback_authorization"]): Promise<DeviceFallbackGrantV2> {
    requireNoNever(value, request.intent); requireAuthority(value.owner, request.intent.authority, request.intent);
    if (adapter.attempts.has(request.intent.attempt_id)) fail("OFFLINE_FALLBACK_USED"); if (adapter.attempts.size >= 1024) fail("OFFLINE_FALLBACK_CAPACITY");
    for (const [id, grant] of pending) if (expired(grant)) pending.delete(id);
    if (request.decision === "allow" && pending.size + adapter.legacyPendingCount() >= 16) fail("OFFLINE_FALLBACK_CAPACITY"); adapter.attempts.add(request.intent.attempt_id);
    const located = await locate(request), now = Date.now();
    const grant: DeviceFallbackGrantV2 = { schema: "device-fallback-grant@2", id: crypto.randomUUID(), scope: "local_once", state: request.decision === "allow" ? "allowed" : "denied", fallback_authorization: authorization, intent: cloneExactDeviceValue(request.intent), profile_id: value.owner.profile_id, owner_epoch: value.owner.owner_epoch, slot_id: located.slot.slot_id, generation: located.slot.generation, package_sha256: located.slot.sha256, decided_at: new Date(now).toISOString(), expires_at: new Date(now + TTL).toISOString(), consumed_at: null };
    const item: Pending = { grant, monotonic: performance.now(), authority: cloneExactDeviceValue(authority!) };
    value.data.receipts = [...value.data.receipts, grant].slice(-64); await commit(value, located.stored, async () => { requirePending(value, grant); if (expired(item)) fail("OFFLINE_FALLBACK_EXPIRED"); });
    if (grant.state === "allowed") pending.set(grant.id, item); return cloneExactDeviceValue(grant);
  }
  async function status(): Promise<DeviceFallbackStatus> {
    const value = await snapshot(), auth = await currentAuthority(value.owner), packages = await adapter.bindings();
    return { schema: "device-fallback-status@1", profile_id: value.owner.profile_id, owner_epoch: value.owner.owner_epoch, authority: cloneExactDeviceValue(auth), capabilities: browserFallbackCapabilities(), policies: cloneExactDeviceValue(value.data.policies.filter(policy => policy.profile_id === value.owner.profile_id && policy.owner_epoch === value.owner.owner_epoch)), package_bindings: packages.bindings, missing_package_bindings: packages.missing };
  }
  return {
    fallbackStatus: () => locked(status),
    async refreshFallbackAuthority() {
      const captured = await locked(async () => { const value = await snapshot(), auth = await currentAuthority(value.owner); return { value, auth: cloneExactDeviceValue(auth), epoch: apiTransportAuthorityEpoch() }; });
      const first = await tireApi.fallbackSourceSettings(), directory = await tireApi.sources(), last = await tireApi.fallbackSourceSettings();
      return locked(async () => {
        await adapter.transaction(tx => current(tx, captured.value));
        if (!authority || !same(authority, captured.auth) || captured.epoch !== apiTransportAuthorityEpoch() || first.transport_epoch !== captured.epoch || last.transport_epoch !== captured.epoch || first.owner_scope_id !== last.owner_scope_id || !same(first.catalog, last.catalog) || !directory || !Array.isArray(directory.sources)) fail("OFFLINE_FALLBACK_AUTHORITY_CHANGED");
        if (last.catalog.scope !== "local_workspace" || !Array.isArray(last.catalog.items) || last.catalog.items.length > 200 || last.catalog.total !== last.catalog.items.length) fail();
        const ids = new Set<string>(), sources: DeviceFallbackSourceAuthority["sources"] = [];
        for (const item of last.catalog.items) {
          if (!item || typeof item.source_id !== "string" || ids.has(item.source_id) || typeof item.can_fetch !== "boolean" || !item.management || !["tire", "vehicle", "recall"].includes(item.target_kind)) fail(); ids.add(item.source_id); exactSafeInteger(item.management.access_generation);
          const registered = directory.sources.find(source => source.id === item.source_id);
          const declaredKind = registered?.target_kind ?? registered?.source_setting?.target_kind;
          if (declaredKind !== undefined && declaredKind !== item.target_kind) fail();
          const kinds = item.target_kind === "vehicle" ? ["vehicle_fitments" as const] : item.target_kind === "tire" ? ["tire" as const] : item.source_id === "nhtsa-us-recalls" ? ["recall_campaign" as const, "recall_search" as const] : [];
          sources.push({ source_id: item.source_id, access_generation: item.management.access_generation, query_kinds: kinds, can_query: kinds.length > 0 && item.effective_status === "ready" && item.can_fetch, can_fetch: item.can_fetch });
        }
        sources.sort((a, b) => a.source_id.localeCompare(b.source_id));
        const changed = authority.state !== "last_observed" || authority.owner_scope_id !== last.owner_scope_id || !same(authority.sources, sources);
        const auth: DeviceFallbackSourceAuthority = { ...authority, authority_revision: changed ? next(authority.authority_revision) : authority.authority_revision, state: "last_observed", owner_scope_id: last.owner_scope_id, sources, observed_at: stamp() };
        if (changed) {
          for (const policy of captured.value.data.policies) if (policy.state === "enabled") {
            let reason: string | null = policy.profile_id !== auth.profile_id || policy.owner_epoch !== auth.owner_epoch || policy.owner_scope_id !== auth.owner_scope_id ? "owner_changed" : policy.runtime_session_id !== null && policy.runtime_session_id !== runtime ? "runtime_changed" : null;
            if (!reason) try {
              validatePolicyChoice({ mode: policy.mode, scope: policy.scope, binding: policy.binding, allow_same_scope_sync_binding_advance: policy.allow_same_scope_sync_binding_advance } as DeviceFallbackPolicyChoice, auth);
              if (authority?.state === "last_observed" && scopePins(policy.scope).some(pin => !same(authority!.sources.find(source => source.source_id === pin.source_id), auth.sources.find(source => source.source_id === pin.source_id)))) reason = "source_authority_changed";
            } catch { reason = "source_authority_changed"; }
            if (reason) { policy.state = "paused"; policy.reason = reason; policy.policy_revision = next(policy.policy_revision); policy.updated_at = stamp(); }
          }
          await commit(captured.value); pending.clear(); previews.clear(); notify();
        }
        authority = auth; return cloneExactDeviceValue(auth);
      });
    },
    previewFallbackPolicy(request) {
      fallbackShape(request, ["mode", "scope", "binding", "allow_same_scope_sync_binding_advance", "expected_profile_id", "expected_owner_epoch", "authority", "policy_id", "expected_policy_revision", "expires_in_seconds"]);
      const frozen = cloneExactDeviceValue(request); return locked(async () => {
        const value = await snapshot(), auth = requireAuthority(value.owner, frozen.authority);
        if (frozen.expected_profile_id !== value.owner.profile_id || frozen.expected_owner_epoch !== value.owner.owner_epoch) fail("OFFLINE_OWNER_LOCKED");
        exactSafeInteger(frozen.expires_in_seconds, 900, 604800); exactSafeInteger(frozen.expected_policy_revision);
        const choice = { mode: frozen.mode, scope: frozen.scope, binding: frozen.binding, allow_same_scope_sync_binding_advance: frozen.allow_same_scope_sync_binding_advance } as DeviceFallbackPolicyChoice; validatePolicyChoice(choice, auth);
        const previous = frozen.policy_id === null ? undefined : value.data.policies.find(policy => policy.policy_id === frozen.policy_id);
        if (previous && (previous.profile_id !== value.owner.profile_id || previous.owner_epoch !== value.owner.owner_epoch)) fail("OFFLINE_OWNER_LOCKED");
        if (frozen.policy_id !== null && !fallbackUUID(frozen.policy_id) || frozen.expected_policy_revision !== (previous?.policy_revision || 0) || frozen.policy_id !== null && !previous) fail("OFFLINE_FALLBACK_POLICY_CHANGED");
        if (fullPolicyCapacity(value.data, previous)) fail("OFFLINE_FALLBACK_CAPACITY");
        let located: FallbackLocated | null = null;
        if (choice.binding) { located = await adapter.locate({ slot_id: choice.binding.slot_id, expected_generation: choice.binding.generation }); if (located.slot.locked || located.slot.previous_owner || located.owner.profile_id !== value.owner.profile_id || located.owner.owner_epoch !== value.owner.owner_epoch || !same(located.binding, choice.binding)) fail("OFFLINE_STALE_GENERATION"); }
        const wall = Date.now(), digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(stableExactDeviceJson(frozen))), fingerprint = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
        const preview: DeviceFallbackPolicyPreview = { schema: "device-fallback-policy-preview@1", preview_id: crypto.randomUUID(), fingerprint, expires_at: new Date(wall + TTL).toISOString(), policy_expires_at: new Date(wall + frozen.expires_in_seconds * 1000).toISOString(), expected_policy_revision: frozen.expected_policy_revision, profile_id: value.owner.profile_id, owner_epoch: value.owner.owner_epoch, authority: cloneExactDeviceValue(auth), proposed_policy: choice, notice: "此许可只在所选来源和查询类型发生明确网络失败时读取指定设备历史子集。会话许可仅限当前应用运行；页面关闭后不执行。保存或持续更新许可与此许可分别批准。" };
        await adapter.transaction(tx => current(tx, value, located?.stored)); requireAuthority(value.owner, frozen.authority);
        if (previews.size >= 16) fail("OFFLINE_FALLBACK_CAPACITY"); previews.set(preview.preview_id, { value: preview, request: frozen, wall, monotonic: performance.now() }); return cloneExactDeviceValue(preview);
      });
    },
    applyFallbackPolicy(request) {
      fallbackShape(request, ["preview_id", "expected_fingerprint", "expected_policy_revision", "allow_continuous_history_fallback"]); const frozen = cloneExactDeviceValue(request);
      return locked(async () => {
        const preview = previews.get(frozen.preview_id); previews.delete(frozen.preview_id);
        if (!preview || frozen.allow_continuous_history_fallback !== true || frozen.expected_fingerprint !== preview.value.fingerprint || frozen.expected_policy_revision !== preview.value.expected_policy_revision || Date.now() < preview.wall || Date.now() >= Date.parse(preview.value.expires_at) || performance.now() < preview.monotonic || performance.now() - preview.monotonic >= TTL) fail("OFFLINE_FALLBACK_POLICY_CHANGED");
        const value = await snapshot(), auth = requireAuthority(value.owner, preview.request.authority), choice = preview.value.proposed_policy; validatePolicyChoice(choice, auth);
        if (value.owner.profile_id !== preview.value.profile_id || value.owner.owner_epoch !== preview.value.owner_epoch) fail("OFFLINE_OWNER_LOCKED");
        const previous = value.data.policies.find(policy => policy.policy_id === preview.request.policy_id); if ((previous?.policy_revision || 0) !== frozen.expected_policy_revision || preview.request.policy_id !== null && !previous) fail("OFFLINE_FALLBACK_POLICY_CHANGED");
        if (fullPolicyCapacity(value.data, previous)) fail("OFFLINE_FALLBACK_CAPACITY");
        if (previous && (previous.profile_id !== value.owner.profile_id || previous.owner_epoch !== value.owner.owner_epoch)) fail("OFFLINE_OWNER_LOCKED");
        let located: FallbackLocated | null = null; if (choice.binding) { located = await adapter.locate({ slot_id: choice.binding.slot_id, expected_generation: choice.binding.generation }); if (!same(located.binding, choice.binding) || located.slot.locked || located.slot.previous_owner) fail("OFFLINE_STALE_GENERATION"); }
        const policy = { ...choice, schema: "device-fallback-policy@1", policy_id: previous?.policy_id || crypto.randomUUID(), policy_revision: next(previous?.policy_revision || 0), state: "enabled", profile_id: value.owner.profile_id, owner_epoch: value.owner.owner_epoch, owner_scope_id: auth.owner_scope_id!, runtime_session_id: choice.scope.kind === "session" ? runtime : null, approved_at: stamp(), updated_at: stamp(), expires_at: preview.value.policy_expires_at, fingerprint: preview.value.fingerprint, reason: null } as DeviceFallbackPolicy;
        value.data.policies = [...value.data.policies.filter(item => item.policy_id !== policy.policy_id), policy]; await commit(value, located?.stored, async () => { requireAuthority(value.owner, preview.request.authority); }); pending.clear(); notify(); return cloneExactDeviceValue(policy);
      });
    },
    pauseFallbackPolicy: request => changePolicy(request, "paused"),
    revokeFallbackPolicy: request => changePolicy(request, "revoked"),
    authorizeFallback(request) {
      validateDeviceFallbackBinding(request, ["intent"]); validateDeviceFallbackIntent(request.intent); const frozen = cloneExactDeviceValue(request);
      return locked(async () => {
        const value = await snapshot(); await currentAuthority(value.owner);
        try { requireNoNever(value, frozen.intent); } catch (cause) { if (cause instanceof OfflineError && cause.code === "OFFLINE_FALLBACK_NEVER") return { schema: "device-fallback-authorization@1", state: "blocked", reason: "never", grant: null }; throw cause; }
        requireAuthority(value.owner, frozen.intent.authority, frozen.intent); const located = await locate(frozen);
        const policies = value.data.policies.filter(policy => active(policy) && policy.profile_id === value.owner.profile_id && policy.owner_epoch === value.owner.owner_epoch && policy.owner_scope_id === authority!.owner_scope_id && (policy.runtime_session_id === null || policy.runtime_session_id === runtime) && matching(policy, frozen.intent.source_id, frozen.intent.source_access_generation, frozen.intent.query_kind));
        if (policies.some(policy => policy.mode === "ask")) return { schema: "device-fallback-authorization@1", state: "ask", reason: "explicit_once_required", grant: null };
        const rank = { query_allow: 3, source_allow: 2, session_allow: 1 };
        const allowed = policies.filter(policy => policy.mode.endsWith("_allow") && same(policy.binding, located.binding)).sort((a, b) => (rank[b.mode as keyof typeof rank] || 0) - (rank[a.mode as keyof typeof rank] || 0) || b.approved_at.localeCompare(a.approved_at) || a.policy_id.localeCompare(b.policy_id))[0];
        if (!allowed) return { schema: "device-fallback-authorization@1", state: "ask", reason: "explicit_once_required", grant: null };
        const grant = await issue(value, { ...frozen, decision: "allow" }, { type: "policy_once", policy_id: allowed.policy_id, policy_revision: allowed.policy_revision });
        return { schema: "device-fallback-authorization@1", state: "allowed", reason: null, grant: grant as DeviceFallbackGrantV2 & { state: "allowed" } };
      });
    },
    decideFallbackV2(request) { validateDeviceFallbackDecision(request); const frozen = cloneExactDeviceValue(request); return locked(async () => { const value = await snapshot(); await currentAuthority(value.owner); return issue(value, frozen, { type: "explicit_once" }); }); },
    async consumeFallbackV2(request) {
      fallbackShape(request, ["grant_id", "intent"]); if (!fallbackUUID(request.grant_id)) fail(); validateDeviceFallbackIntent(request.intent); const frozen = cloneExactDeviceValue(request);
      const capture = await locked(async () => {
        const item = pending.get(frozen.grant_id); pending.delete(frozen.grant_id); if (!item) fail("OFFLINE_FALLBACK_USED");
        if (deviceIntentKey(item.grant.intent) !== deviceIntentKey(frozen.intent)) fail("OFFLINE_FALLBACK_MISMATCH"); if (expired(item)) fail("OFFLINE_FALLBACK_EXPIRED");
        let value = await snapshot(); requirePending(value, item.grant); const located = await locate({ intent: frozen.intent, slot_id: item.grant.slot_id, expected_generation: item.grant.generation, expected_sha256: item.grant.package_sha256, expected_profile_id: item.grant.profile_id, expected_owner_epoch: item.grant.owner_epoch });
        const grant = { ...item.grant, state: "consumed" as const, consumed_at: stamp() }; value.data.receipts = [...value.data.receipts, grant].slice(-64);
        // Durable audit and all metadata gates commit before either release validation or body decryption.
        value = await commit(value, located.stored, async () => { requirePending(value, item.grant); if (expired(item)) fail("OFFLINE_FALLBACK_EXPIRED"); });
        return { value, located, grant, item };
      });
      const { value, located, grant, item } = capture;
        const envelope = await adapter.load(located), selected = selectDeviceHistoricalMembers(envelope.members, frozen.intent);
        if (frozen.intent.query_kind === "recall_search" && envelope.schema !== "offline-pack@2") fail("OFFLINE_FALLBACK_UNSUPPORTED");
        const documents = envelope.documents.filter(document => selected.members.some(member => member.key === document.member_key));
        const citations = documents.map(document => { const member = selected.members.find(member => member.key === document.member_key)!; return { schema: "device-citation@1" as const, id: `device:${grant.profile_id}:${grant.owner_epoch}:${grant.slot_id}:${grant.generation}:${grant.package_sha256}:${document.id}`, profile_id: grant.profile_id, owner_epoch: grant.owner_epoch, slot_id: grant.slot_id, generation: grant.generation, package_sha256: grant.package_sha256, member_key: member.key, document_id: document.id, record_index: document.record_index, observed_at: member.source.observed_at, verified_at: member.source.verified_at, verification_id: member.source.verification_id }; });
        const response = { schema: "device-fallback-result@2", data_state: "local_snapshot", fallback_consent: "local_once", fallback_authorization: grant.fallback_authorization, grant, slot: located.slot, package_schema: envelope.schema, citations, complete_query_result: false, notice: DEVICE_FALLBACK_NOTICE, query_kind: frozen.intent.query_kind, query: cloneExactDeviceValue(frozen.intent.query), ...selected } as DeviceFallbackResultV2;
        validateDeviceFallbackResult(response, { intent: frozen.intent, slot_id: grant.slot_id, expected_generation: grant.generation, expected_sha256: grant.package_sha256, expected_profile_id: grant.profile_id, expected_owner_epoch: grant.owner_epoch }); stringifyExactJson(response);
        await locked(async () => {
          const latest = await snapshot(); requirePending(latest, item.grant);
          await adapter.transaction(async tx => { await current(tx, value, located.stored); requirePending(latest, item.grant); if (expired(item)) fail("OFFLINE_FALLBACK_EXPIRED"); });
        }); return response;
    },
    revokeFallbackV2(request) { fallbackShape(request, ["grant_id"]); if (!fallbackUUID(request.grant_id)) fail(); const id = request.grant_id; return locked(async () => { const item = pending.get(id); pending.delete(id); if (item) { const value = await snapshot(); if (value.owner.profile_id === item.grant.profile_id && value.owner.owner_epoch === item.grant.owner_epoch) { value.data.receipts = [...value.data.receipts, { ...item.grant, state: "revoked" as const }].slice(-64); await commit(value); } } return { revoked: true, grant_id: id }; }); },
    legacyFence(intent) { return locked(async () => { const value = await snapshot(); requireNoWarehouseDenial(value, intent); if (value.data.policies.some(policy => active(policy) && policy.profile_id === value.owner.profile_id && policy.owner_epoch === value.owner.owner_epoch && policy.mode === "never" && matching(policy, intent.source_id, null, "tire"))) fail("OFFLINE_FALLBACK_NEVER"); return async (tx: IDBTransaction) => { requireNoWarehouseDenial(value, intent); await current(tx, value); }; }); },
    async prepareInstall(owner, slot, packageBinding, isSync) {
      const value = await snapshot(); if (value.owner.profile_id !== owner.profile_id || value.owner.owner_epoch !== owner.owner_epoch) fail("OFFLINE_OWNER_LOCKED");
      for (const policy of value.data.policies) if (policy.binding?.slot_id === slot.slot_id && policy.state === "enabled") {
        const whitelist = new Set(scopePins(policy.scope).map(source => source.source_id));
        if (isSync && policy.allow_same_scope_sync_binding_advance && policy.profile_id === owner.profile_id && policy.owner_epoch === owner.owner_epoch && policy.owner_scope_id === slot.owner_scope_id && policy.binding.history_scope_fingerprint === packageBinding.history_scope_fingerprint && packageBinding.source_ids.every(source => whitelist.has(source))) { policy.binding = cloneExactDeviceValue(packageBinding); policy.policy_revision = next(policy.policy_revision); policy.updated_at = stamp(); }
        else { policy.state = "paused"; policy.reason = isSync ? "sync_binding_changed" : "manual_package_replaced"; policy.policy_revision = next(policy.policy_revision); policy.updated_at = stamp(); }
      }
      const record = await encoded(value); return { guard: tx => current(tx, value), write: async tx => { await adapter.result(tx.objectStore("system").put(record, KEY)); pending.clear(); previews.clear(); notify(); } };
    },
    resetOwner(committed = false) { pending.clear(); previews.clear(); authority = null; if (committed) { denialUnavailable = false; observedDeniedQueries.clear(); } notify(); },
    prepareOwnerReset() { return locked(async () => {
      const value = await snapshot();
      for (const policy of value.data.policies) if (policy.profile_id === value.owner.profile_id && policy.owner_epoch <= value.owner.owner_epoch && policy.state !== "revoked") { policy.state = "revoked"; policy.reason = "OFFLINE_FALLBACK_OWNER_CHANGED"; policy.policy_revision = next(policy.policy_revision); policy.updated_at = stamp(); }
      delete value.data.warehouse_denials;
      const record = await encoded(value);
      return { guard: tx => current(tx, value), write: async tx => { await adapter.result(tx.objectStore("system").put(record, KEY)); pending.clear(); previews.clear(); authority = null; notify(); } };
    }); },
    pendingCount() { for (const [id, value] of pending) if (expired(value)) pending.delete(id); return pending.size; },
  };
  function changePolicy(request: DeviceFallbackPolicyRequest, state: "paused" | "revoked"): Promise<DeviceFallbackPolicy> {
    fallbackShape(request, ["policy_id", "expected_policy_revision"]); if (!fallbackUUID(request.policy_id)) fail(); exactSafeInteger(request.expected_policy_revision, 1); const frozen = cloneExactDeviceValue(request);
    return locked(async () => { const value = await snapshot(), policy = value.data.policies.find(policy => policy.policy_id === frozen.policy_id); if (!policy || policy.profile_id !== value.owner.profile_id || policy.owner_epoch !== value.owner.owner_epoch || policy.policy_revision !== frozen.expected_policy_revision || policy.state === "revoked") fail("OFFLINE_FALLBACK_POLICY_CHANGED"); policy.state = state; policy.reason = state === "paused" ? "user_paused" : "user_revoked"; policy.policy_revision = next(policy.policy_revision); policy.updated_at = stamp(); await commit(value); pending.clear(); previews.clear(); notify(); return cloneExactDeviceValue(policy); });
  }
}
