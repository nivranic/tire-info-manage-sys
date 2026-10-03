import { ApiError, apiTransportAuthorityEpoch, tireApi } from "@tire/api-client";
import type { DeviceSyncApplyRequest, DeviceSyncCapabilities, DeviceSyncPolicy, DeviceSyncPolicyRequest, DeviceSyncPreview,
  DeviceSyncPreviewRequest, DeviceSyncReleaseCheck, DeviceSyncRun, DeviceSyncRunRequest, DeviceSyncStatus,
  AnyOfflineEnvelope as OfflineEnvelope, OfflineInstallRequest, AnyOfflinePackDescriptor as OfflinePackDescriptor, OfflineSlot, OfflineSlotRequest } from "@tire/domain-types";
import { DEVICE_SYNC_CAPACITY, DEVICE_SYNC_NOTICE, deriveDeviceSyncScope, deviceSyncSemanticDigestFromBytes, sameSyncValue,
  stableSyncJson, syncConditionsSatisfied, validateSyncPreviewRequest, validateSyncUpdate, validSyncDigest, validSyncUUID } from "./device-sync-values";
import { MAX_OFFLINE_BYTES, OfflineError, offlineError, offlineSha256, openOfflineBytes, sealOfflineBytes, type OfflineCiphertext } from "./offline-crypto";

export interface SyncProfile { profile_id: string; owner_epoch: number; key: CryptoKey }
export interface SyncStoredSlot { slot_id: string; generation: number; owner_epoch: number; deleted: boolean; metadata: OfflineCiphertext | null; payload: OfflineCiphertext | null }
export interface SyncLoadedSlot { owner: SyncProfile; stored: SyncStoredSlot; slot: OfflineSlot; meta: { descriptor: OfflinePackDescriptor }; envelope: OfflineEnvelope; originalBytes: Uint8Array }
export interface SyncInstallHooks {
  runId: string; expectedOwner: string; validateEnvelope(envelope: OfflineEnvelope, bytes: Uint8Array): Promise<void>;
  guard(tx: IDBTransaction): Promise<void>; write(tx: IDBTransaction): Promise<void>;
}
export interface BrowserSyncAdapter {
  profile(): Promise<SyncProfile>; slots(): Promise<SyncStoredSlot[]>;
  describe(request: OfflineSlotRequest): Promise<OfflineSlot>;
  load(request: OfflineSlotRequest): Promise<SyncLoadedSlot>;
  transaction<T>(work: (tx: IDBTransaction) => Promise<T>): Promise<T>;
  result<T>(request: IDBRequest<T>): Promise<T>;
  install(request: OfflineInstallRequest, signal?: AbortSignal, hooks?: SyncInstallHooks): Promise<OfflineSlot>;
}
interface Sidecar { schema: "device-sync-sidecar@1"; revision: number; encrypted: OfflineCiphertext }
interface RunLease { run_id: string; policy_id: string; page_id: string; expires_at: number }
interface SyncData {
  schema: "device-sync-store@1"; policies: DeviceSyncPolicy[]; runs: DeviceSyncRun[]; release_checks: DeviceSyncReleaseCheck[];
  lease: RunLease | null; journal: { run_id: string; plan_id: string; fingerprint: string; key: string } | null;
}
interface Snapshot { owner: SyncProfile; record: Sidecar | undefined; data: SyncData }
const KEY = "device-sync", LOCK = "tire-device-sync-v1", PREVIEW_MS = 300_000;
const empty = (): SyncData => ({ schema: "device-sync-store@1", policies: [], runs: [], release_checks: [], lease: null, journal: null });
const binding = (owner: SyncProfile, revision: number) => JSON.stringify(["device-sync-sidecar@1", owner.profile_id, revision]);
const now = () => new Date().toISOString();
const sameBuffer = (a: ArrayBuffer | Uint8Array | undefined, b: ArrayBuffer | Uint8Array | undefined) => {
  if (a === undefined || b === undefined) return a === b;
  const x = a instanceof Uint8Array ? a : new Uint8Array(a), y = b instanceof Uint8Array ? b : new Uint8Array(b);
  return x.byteLength === y.byteLength && x.every((value, index) => value === y[index]);
};
const sameCiphertext = (a: OfflineCiphertext | null | undefined, b: OfflineCiphertext | null | undefined) => !a || !b ? a === b
  : sameBuffer(a.iv, b.iv) && sameBuffer(a.ciphertext, b.ciphertext);
const next = (revision: number) => { if (!Number.isSafeInteger(revision) || revision < 0 || revision >= Number.MAX_SAFE_INTEGER) throw new OfflineError("OFFLINE_GENERATION_EXHAUSTED"); return revision + 1; };
const reason = (cause: unknown) => {
  const code = cause && typeof cause === "object" && "code" in cause ? cause.code : null;
  return typeof code === "string" && /^[A-Za-z0-9_@.-]{1,100}$/.test(code) ? code : "OFFLINE_SYNC_FAILED";
};
const observations = () => ({ network_available: typeof navigator === "undefined" ? null : navigator.onLine === true,
  wifi: null, external_power: null, battery_charging: null });
export function browserSyncCapabilities(): DeviceSyncCapabilities {
  let build: string | undefined;
  try { build = process.env.NEXT_PUBLIC_TI_OFFLINE_HOST_BUILD; }
  catch { build = (globalThis as { __TI_OFFLINE_HOST_BUILD?: string }).__TI_OFFLINE_HOST_BUILD; }
  return { schema: "device-sync-capabilities@1", scheduler: validSyncDigest(build) ? "page_open" : "unsupported", wifi: false,
    external_power: false, battery_charging: false, min_interval_seconds: 900, max_interval_seconds: 604800,
    host_build: validSyncDigest(build) ? build : "unverified-build", validator_version: "offline-validator@2" };
}
function validateData(data: SyncData): void {
  if (!data || data.schema !== "device-sync-store@1" || Object.keys(data).sort().join(",") !== "journal,lease,policies,release_checks,runs,schema"
    || !Array.isArray(data.policies) || data.policies.length > 16 || !Array.isArray(data.runs) || data.runs.length > 64
    || !Array.isArray(data.release_checks) || data.release_checks.length > 16) throw new OfflineError("OFFLINE_SYNC_CORRUPT");
  const ids = new Set<string>(), slots = new Set<string>();
  for (const policy of data.policies) {
    if (!policy || policy.schema !== "device-sync-policy@1" || !validSyncUUID(policy.policy_id) || ids.has(policy.policy_id) || slots.has(policy.slot_id)
      || !validSyncUUID(policy.profile_id) || !validSyncUUID(policy.slot_id) || !validSyncDigest(policy.owner_scope_id)
      || !Number.isSafeInteger(policy.policy_revision) || policy.policy_revision < 1 || !Number.isSafeInteger(policy.owner_epoch) || policy.owner_epoch < 1
      || !["enabled", "paused", "revoked"].includes(policy.state) || !sameSyncValue(policy.capacity, DEVICE_SYNC_CAPACITY)
      || !policy.binding || !validSyncUUID(policy.binding.package_id) || !validSyncDigest(policy.binding.sha256)
      || !Number.isSafeInteger(policy.binding.generation) || policy.binding.generation < 1 || !Number.isSafeInteger(policy.binding.binding_revision) || policy.binding.binding_revision < 1)
      throw new OfflineError("OFFLINE_SYNC_CORRUPT");
    // Stored unsupported conditions are valid data but cannot execute on this host.
    const broad = { ...browserSyncCapabilities(), scheduler: "page_open" as const, wifi: true, external_power: true, battery_charging: true };
    validateSyncPreviewRequest({ slot_id: policy.slot_id, expected_generation: policy.binding.generation, expected_profile_id: policy.profile_id,
      expected_owner_epoch: policy.owner_epoch, interval_seconds: policy.interval_seconds, conditions: policy.conditions }, broad);
    if (!policy.scope || !Array.isArray(policy.scope.references) || policy.scope.references.length > 1000) throw new OfflineError("OFFLINE_SYNC_CORRUPT");
    ids.add(policy.policy_id); slots.add(policy.slot_id);
  }
  for (const run of data.runs) if (!run || run.schema !== "device-sync-run@1" || !validSyncUUID(run.run_id) || !validSyncUUID(run.policy_id)
    || !["running", "succeeded", "no_change", "deferred", "blocked", "failed", "cancelled", "interrupted"].includes(run.state)
    || !Number.isSafeInteger(run.policy_revision) || run.policy_revision < 1) throw new OfflineError("OFFLINE_SYNC_CORRUPT");
  for (const check of data.release_checks) if (!check || !validSyncUUID(check.slot_id) || !(validSyncDigest(check.sha256) || check.sha256 === null && check.state === "failed")
    || !Number.isSafeInteger(check.generation) || check.generation < 1 || !["passed", "failed"].includes(check.state)) throw new OfflineError("OFFLINE_SYNC_CORRUPT");
  if (data.lease && (!validSyncUUID(data.lease.run_id) || !validSyncUUID(data.lease.policy_id) || !validSyncUUID(data.lease.page_id)
    || !Number.isFinite(data.lease.expires_at))) throw new OfflineError("OFFLINE_SYNC_CORRUPT");
  if (data.journal && (!validSyncUUID(data.journal.run_id) || !validSyncUUID(data.journal.plan_id) || !validSyncDigest(data.journal.fingerprint)
    || !validSyncUUID(data.journal.key))) throw new OfflineError("OFFLINE_SYNC_CORRUPT");
}
export function createBrowserDeviceSync(adapter: BrowserSyncAdapter) {
  const pageId = globalThis.crypto?.randomUUID?.() || "00000000-0000-0000-0000-000000000000";
  const previews = new Map<string, { preview: DeviceSyncPreview; monotonic: number; created: number; policyId: string | null }>();
  const active = new Map<string, AbortController>();
  const notifications = typeof window !== "undefined" && typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("tire-device-sync-v1") : null;
  const abortPolicies = (ids: string[], broadcast = true) => {
    for (const id of ids) active.get(id)?.abort();
    if (broadcast) notifications?.postMessage({ type: "invalidate", policy_ids: ids });
  };
  if (notifications) notifications.onmessage = event => {
    const value = event.data as { type?: unknown; policy_ids?: unknown };
    if (value?.type === "invalidate" && Array.isArray(value.policy_ids) && value.policy_ids.length <= 16 && value.policy_ids.every(validSyncUUID)) abortPolicies(value.policy_ids, false);
    if (typeof window !== "undefined") window.dispatchEvent(new Event("tire-offline-sync-changed"));
  };
  let initialized: Promise<void> | null = null;
  const notify = () => { if (typeof window !== "undefined") window.dispatchEvent(new Event("tire-offline-sync-changed")); };
  const capabilities = browserSyncCapabilities;
  async function snapshot(): Promise<Snapshot> {
    const owner = await adapter.profile();
    const record = await adapter.transaction(tx => adapter.result<Sidecar | undefined>(tx.objectStore("system").get(KEY)));
    if (!record) return { owner, record, data: empty() };
    if (record.schema !== "device-sync-sidecar@1" || !Number.isSafeInteger(record.revision) || record.revision < 1) throw new OfflineError("OFFLINE_SYNC_CORRUPT");
    let data: SyncData;
    try { data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await openOfflineBytes(owner.key, record.encrypted, binding(owner, record.revision)))); }
    catch { throw new OfflineError("OFFLINE_SYNC_CORRUPT"); }
    validateData(data); return { owner, record, data };
  }
  async function encoded(snapshot: Snapshot): Promise<Sidecar> {
    validateData(snapshot.data); const revision = next(snapshot.record?.revision || 0), bytes = new TextEncoder().encode(JSON.stringify(snapshot.data));
    if (bytes.byteLength > MAX_OFFLINE_BYTES) throw new OfflineError("OFFLINE_SYNC_CAPACITY");
    return { schema: "device-sync-sidecar@1", revision, encrypted: await sealOfflineBytes(snapshot.owner.key, bytes, binding(snapshot.owner, revision)) };
  }
  async function current(tx: IDBTransaction, value: Snapshot): Promise<void> {
    const system = tx.objectStore("system"), owner = await adapter.result<SyncProfile | undefined>(system.get("profile"));
    if (!owner || owner.profile_id !== value.owner.profile_id || owner.owner_epoch !== value.owner.owner_epoch) throw new OfflineError("OFFLINE_OWNER_CHANGED");
    const record = await adapter.result<Sidecar | undefined>(system.get(KEY));
    if ((record?.revision || 0) !== (value.record?.revision || 0) || record?.schema !== value.record?.schema
      || !sameCiphertext(record?.encrypted, value.record?.encrypted)) throw new OfflineError("OFFLINE_SYNC_CONFLICT");
  }
  async function mutate<T>(work: (value: Snapshot) => T | Promise<T>, guard?: (tx: IDBTransaction) => Promise<void>): Promise<T> {
    for (let retry = 0; retry < 4; retry++) {
      const value = await snapshot(), result = await work(value), record = await encoded(value);
      try { await adapter.transaction(async tx => { await current(tx, value); if (guard) await guard(tx); await adapter.result(tx.objectStore("system").put(record, KEY)); }); notify(); return result; }
      catch (cause) { if (!(cause instanceof OfflineError) || cause.code !== "OFFLINE_SYNC_CONFLICT" || retry === 3) throw cause; }
    }
    throw new OfflineError("OFFLINE_SYNC_CONFLICT");
  }
  async function withLock<T>(work: () => Promise<T>): Promise<T | undefined> {
    if (!navigator.locks) return work();
    return navigator.locks.request(LOCK, { ifAvailable: true }, lock => lock ? work() : Promise.resolve(undefined));
  }
  async function initialize(): Promise<void> {
    if (!initialized) initialized = (async () => {
      await withLock(async () => {
        const before = await snapshot();
        if (!before.data.runs.some(run => run.state === "running")) return;
        // A live tab holds the Web Lock. Without that API only an expired durable
        // lease establishes a lost run; a fresh tab must not cancel another tab.
        if (!navigator.locks && before.data.lease && before.data.lease.expires_at > Date.now()) return;
        await mutate(value => {
          for (const run of value.data.runs.filter(run => run.state === "running")) {
            run.state = "interrupted"; run.stage = "finished"; run.reason = "OFFLINE_SYNC_RESTARTED"; run.finished_at = now();
            const policy = value.data.policies.find(policy => policy.policy_id === run.policy_id);
            if (policy?.state === "enabled") { policy.state = "paused"; policy.policy_revision = next(policy.policy_revision); policy.next_due_at = null; policy.reason = run.reason; policy.updated_at = now(); }
          }
          value.data.lease = null;
        });
      });
    })().catch(cause => { initialized = null; throw cause; });
    await initialized;
  }
  async function slotGuard(tx: IDBTransaction, loaded: SyncLoadedSlot): Promise<void> {
    const slot = await adapter.result<SyncStoredSlot | undefined>(tx.objectStore("slots").get(loaded.slot.slot_id));
    if (!slot || slot.deleted || slot.generation !== loaded.stored.generation || slot.owner_epoch !== loaded.stored.owner_epoch
      || !sameCiphertext(slot.metadata, loaded.stored.metadata) || !sameCiphertext(slot.payload, loaded.stored.payload)) throw new OfflineError("OFFLINE_STALE_GENERATION");
  }
  function status(value: Snapshot): DeviceSyncStatus {
    return { schema: "device-sync-status@1", capabilities: capabilities(), profile_id: value.owner.profile_id,
      owner_epoch: value.owner.owner_epoch, policies: structuredClone(value.data.policies), runs: structuredClone(value.data.runs), release_checks: structuredClone(value.data.release_checks) };
  }
  async function revalidateSync(): Promise<DeviceSyncStatus> {
    await initialize(); const before = await snapshot(), build = capabilities(), slots = (await adapter.slots()).filter(slot => !slot.deleted);
    const previous = before.data.release_checks;
    if (slots.every(slot => previous.some(check => check.slot_id === slot.slot_id && check.generation === slot.generation && check.host_build === build.host_build && check.validator_version === build.validator_version)) && previous.length === slots.length) return status(before);
    const checks: DeviceSyncReleaseCheck[] = [];
    for (const stored of slots) {
      let sha256: string | null = null;
      let state: "passed" | "failed" = "passed", error: string | null = null;
      try { sha256 = (await adapter.describe({ slot_id: stored.slot_id, expected_generation: stored.generation })).sha256;
        await adapter.load({ slot_id: stored.slot_id, expected_generation: stored.generation }); }
      catch (cause) { state = "failed"; error = reason(cause); }
      checks.push({ slot_id: stored.slot_id, generation: stored.generation, sha256, host_build: build.host_build,
        validator_version: build.validator_version, checked_at: now(), state, reason: error });
    }
    await mutate(value => { value.data.release_checks = checks; }, async tx => {
      const currentSlots = (await adapter.result<SyncStoredSlot[]>(tx.objectStore("slots").getAll())).filter(slot => !slot.deleted);
      if (currentSlots.length !== slots.length || currentSlots.some(slot => !slots.some(previous => previous.slot_id === slot.slot_id && previous.generation === slot.generation))) throw new OfflineError("OFFLINE_STALE_GENERATION");
    });
    return status(await snapshot());
  }
  async function requireValidated(slot: OfflineSlot): Promise<void> {
    const value = await revalidateSync(), check = value.release_checks.find(check => check.slot_id === slot.slot_id && check.generation === slot.generation && check.sha256 === slot.sha256);
    if (!check || check.state !== "passed") throw new OfflineError("OFFLINE_RELEASE_VALIDATION_FAILED");
  }
  async function previewSyncPolicy(request: DeviceSyncPreviewRequest): Promise<DeviceSyncPreview> {
    const frozen = structuredClone(request); validateSyncPreviewRequest(frozen, capabilities()); await initialize();
    const loaded = await adapter.load(frozen); await requireValidated(loaded.slot);
    if (loaded.owner.profile_id !== frozen.expected_profile_id || loaded.owner.owner_epoch !== frozen.expected_owner_epoch
      || loaded.slot.locked || loaded.slot.previous_owner) throw new OfflineError("OFFLINE_OWNER_LOCKED");
    const value = await snapshot(), existing = value.data.policies.find(policy => policy.slot_id === frozen.slot_id);
    const preview: DeviceSyncPreview = { schema: "device-sync-preview@1", preview_id: crypto.randomUUID(), fingerprint: "",
      expires_at: new Date(Date.now() + PREVIEW_MS).toISOString(), expected_policy_revision: existing?.policy_revision || 0,
      profile_id: loaded.owner.profile_id, owner_epoch: loaded.owner.owner_epoch, owner_scope_id: loaded.slot.owner_scope_id,
      slot_id: loaded.slot.slot_id, generation: loaded.slot.generation, package_sha256: loaded.slot.sha256,
      scope: deriveDeviceSyncScope(loaded.envelope), capacity: structuredClone(DEVICE_SYNC_CAPACITY), interval_seconds: frozen.interval_seconds,
      conditions: frozen.conditions, capabilities: capabilities(), counts: loaded.slot.counts, notice: DEVICE_SYNC_NOTICE };
    preview.fingerprint = await offlineSha256(new TextEncoder().encode(stableSyncJson({ ...preview, fingerprint: undefined })));
    for (const [id, pending] of previews) if (Date.now() >= Date.parse(pending.preview.expires_at) || performance.now() - pending.monotonic >= PREVIEW_MS) previews.delete(id);
    if (previews.size >= 16) throw new OfflineError("OFFLINE_SYNC_CAPACITY");
    previews.set(preview.preview_id, { preview: structuredClone(preview), monotonic: performance.now(), created: Date.now(), policyId: existing?.policy_id || null });
    return structuredClone(preview);
  }
  async function applySyncPolicy(request: DeviceSyncApplyRequest): Promise<DeviceSyncPolicy> {
    const frozen = structuredClone(request), pending = previews.get(frozen.preview_id); previews.delete(frozen.preview_id);
    if (!pending || Object.keys(frozen).sort().join(",") !== "allow_continuous_history_updates,expected_fingerprint,expected_policy_revision,preview_id"
      || frozen.allow_continuous_history_updates !== true || frozen.expected_fingerprint !== pending.preview.fingerprint
      || frozen.expected_policy_revision !== pending.preview.expected_policy_revision) throw new OfflineError("OFFLINE_SYNC_PREVIEW_USED");
    if (Date.now() < pending.created || Date.now() >= Date.parse(pending.preview.expires_at) || performance.now() < pending.monotonic
      || performance.now() - pending.monotonic >= PREVIEW_MS) throw new OfflineError("OFFLINE_SYNC_PREVIEW_EXPIRED");
    const preview = pending.preview, loaded = await adapter.load({ slot_id: preview.slot_id, expected_generation: preview.generation });
    await requireValidated(loaded.slot);
    if (loaded.owner.profile_id !== preview.profile_id || loaded.owner.owner_epoch !== preview.owner_epoch || loaded.slot.previous_owner || loaded.slot.locked
      || loaded.slot.sha256 !== preview.package_sha256 || !sameSyncValue(capabilities(), preview.capabilities)) throw new OfflineError("OFFLINE_OWNER_LOCKED");
    return mutate(value => {
      const existing = value.data.policies.find(policy => policy.slot_id === preview.slot_id);
      if ((existing?.policy_revision || 0) !== preview.expected_policy_revision || (existing?.policy_id || null) !== pending.policyId) throw new OfflineError("OFFLINE_SYNC_CONFLICT");
      if (!existing && value.data.policies.length >= 16) throw new OfflineError("OFFLINE_SYNC_CAPACITY");
      if (existing && value.data.lease?.policy_id === existing.policy_id) throw new OfflineError("OFFLINE_SYNC_BUSY");
      const policy: DeviceSyncPolicy = { schema: "device-sync-policy@1", policy_id: existing?.policy_id || crypto.randomUUID(), policy_revision: next(existing?.policy_revision || 0),
        state: "enabled", profile_id: preview.profile_id, owner_epoch: preview.owner_epoch, owner_scope_id: preview.owner_scope_id,
        slot_id: preview.slot_id, scope: preview.scope, capacity: preview.capacity, interval_seconds: preview.interval_seconds, conditions: preview.conditions,
        approved_at: now(), updated_at: now(), binding: { binding_revision: next(existing?.binding.binding_revision || 0), generation: loaded.slot.generation,
          package_id: loaded.slot.package_id, sha256: loaded.slot.sha256 }, next_due_at: now(), reason: null };
      value.data.policies = [...value.data.policies.filter(policy => policy.slot_id !== preview.slot_id), policy]; return structuredClone(policy);
    }, tx => slotGuard(tx, loaded));
  }
  function getPolicy(value: Snapshot, request: DeviceSyncPolicyRequest): DeviceSyncPolicy {
    if (!validSyncUUID(request?.policy_id) || !Number.isSafeInteger(request.expected_policy_revision) || request.expected_policy_revision < 1) throw new OfflineError("OFFLINE_SYNC_INVALID");
    const policy = value.data.policies.find(policy => policy.policy_id === request.policy_id);
    if (!policy || policy.policy_revision !== request.expected_policy_revision) throw new OfflineError("OFFLINE_SYNC_CONFLICT");
    return policy;
  }
  async function changePolicy(request: DeviceSyncPolicyRequest, state: "paused" | "revoked") {
    const frozen = structuredClone(request);
    if (Object.keys(frozen).sort().join(",") !== "expected_policy_revision,policy_id") throw new OfflineError("OFFLINE_SYNC_INVALID");
    let interruptedRunId: string | null = null;
    const policy = await mutate(value => {
      interruptedRunId = null;
      const policy = getPolicy(value, frozen); policy.state = state; policy.policy_revision = next(policy.policy_revision); policy.updated_at = now(); policy.next_due_at = null;
      policy.reason = state === "paused" ? "OFFLINE_SYNC_PAUSED" : "OFFLINE_SYNC_REVOKED";
      for (const run of value.data.runs.filter(run => run.policy_id === policy.policy_id && run.state === "running")) { run.state = "cancelled"; run.stage = "finished"; run.reason = policy.reason; run.finished_at = now(); }
      if (value.data.lease?.policy_id === policy.policy_id) { interruptedRunId = value.data.lease.run_id; value.data.lease = null; }
      return structuredClone(policy);
    }, async tx => {
      const installLease = await adapter.result<{ sync_run_id?: string } | undefined>(tx.objectStore("system").get("lease"));
      if (interruptedRunId && installLease?.sync_run_id === interruptedRunId) await adapter.result(tx.objectStore("system").delete("lease"));
    });
    abortPolicies([policy.policy_id]); return policy;
  }
  function allowed(value: Snapshot, request: DeviceSyncRunRequest, loaded: SyncLoadedSlot, epoch: number): DeviceSyncPolicy {
    const policy = getPolicy(value, request);
    if (policy.state !== "enabled") throw new OfflineError("OFFLINE_SYNC_CONSENT_REQUIRED");
    if (policy.profile_id !== value.owner.profile_id || policy.owner_epoch !== value.owner.owner_epoch || loaded.slot.previous_owner || loaded.slot.locked
      || loaded.owner.profile_id !== policy.profile_id || loaded.owner.owner_epoch !== policy.owner_epoch || loaded.slot.owner_scope_id !== policy.owner_scope_id) throw new OfflineError("OFFLINE_OWNER_LOCKED");
    if (policy.binding.generation !== loaded.slot.generation || policy.binding.package_id !== loaded.slot.package_id || policy.binding.sha256 !== loaded.slot.sha256) throw new OfflineError("OFFLINE_STALE_GENERATION");
    if (apiTransportAuthorityEpoch() !== epoch) throw new OfflineError("SESSION_CHANGED");
    if (!syncConditionsSatisfied(policy.conditions, capabilities(), observations())) throw new OfflineError("OFFLINE_SYNC_CONDITIONS");
    return policy;
  }
  async function runUnlocked(request: DeviceSyncRunRequest): Promise<DeviceSyncRun> {
    await initialize(); await revalidateSync();
    const before = await snapshot(), selected = getPolicy(before, request), epoch = apiTransportAuthorityEpoch();
    const loaded = await adapter.load({ slot_id: selected.slot_id, expected_generation: selected.binding.generation }); await requireValidated(loaded.slot);
    const run: DeviceSyncRun = { schema: "device-sync-run@1", run_id: crypto.randomUUID(), policy_id: selected.policy_id,
      policy_revision: selected.policy_revision, trigger: request.trigger, state: "running", stage: "checking", reason: null,
      started_at: now(), finished_at: null, before_generation: loaded.slot.generation, after_generation: null, plan_id: null, package_id: null };
    // Deferred checks have a durable receipt and cannot bypass AND conditions.
    try { allowed(before, request, loaded, epoch); }
    catch (cause) {
      if (reason(cause) !== "OFFLINE_SYNC_CONDITIONS") throw cause;
      run.state = "deferred"; run.stage = "finished"; run.reason = "OFFLINE_SYNC_CONDITIONS"; run.finished_at = now();
      await mutate(value => { const policy = getPolicy(value, request); policy.next_due_at = new Date(Date.now() + policy.interval_seconds * 1000).toISOString(); value.data.runs = [...value.data.runs, run].slice(-64); }); return run;
    }
    if (request.trigger !== "manual" && selected.next_due_at && Date.parse(selected.next_due_at) > Date.now()) {
      return { ...run, state: "deferred", stage: "finished", reason: "OFFLINE_SYNC_NOT_DUE", finished_at: now() };
    }
    const controller = new AbortController(); active.set(selected.policy_id, controller);
    const deadline = setTimeout(() => controller.abort(), 90_000);
    let stage: DeviceSyncRun["stage"] = "checking";
    try {
      await mutate(value => {
        allowed(value, request, loaded, epoch);
        if (value.data.lease && value.data.lease.expires_at > Date.now()) throw new OfflineError("OFFLINE_SYNC_BUSY");
        value.data.lease = { run_id: run.run_id, policy_id: run.policy_id, page_id: pageId, expires_at: Date.now() + 120_000 };
        value.data.runs = [...value.data.runs, run].slice(-64);
      }, tx => slotGuard(tx, loaded));
      async function advance(nextStage: DeviceSyncRun["stage"], plan?: { id: string; fingerprint: string; package_id: string }) {
        stage = nextStage;
        await mutate(value => {
          allowed(value, request, loaded, epoch);
          if (value.data.lease?.run_id !== run.run_id || value.data.lease.expires_at <= Date.now()) throw new OfflineError("OFFLINE_SYNC_CANCELLED");
          const currentRun = value.data.runs.find(value => value.run_id === run.run_id); if (!currentRun || currentRun.state !== "running") throw new OfflineError("OFFLINE_SYNC_CANCELLED");
          currentRun.stage = nextStage;
          if (plan) { currentRun.plan_id = plan.id; currentRun.package_id = plan.package_id; value.data.journal = { run_id: run.run_id, plan_id: plan.id, fingerprint: plan.fingerprint, key: crypto.randomUUID() }; }
        }, tx => slotGuard(tx, loaded));
      }
      await advance("preparing");
      const response = validateSyncUpdate(await tireApi.offlineSyncPrepareV2({ mode: "history", base_pack_id: loaded.slot.package_id,
        expected_base_sha256: loaded.slot.sha256, scope: selected.scope, supported_pack_schemas: ["offline-pack@1", "offline-pack@2"] }, selected.owner_scope_id, controller.signal), selected, loaded.slot, loaded.meta.descriptor);
      if (controller.signal.aborted) throw new OfflineError("OFFLINE_SYNC_CANCELLED");
      if (response.base_semantic_digest !== await deviceSyncSemanticDigestFromBytes(loaded.originalBytes)) throw new OfflineError("OFFLINE_SYNC_RESPONSE_INVALID");
      if (response.state === "no_change") {
        if (!sameSyncValue(loaded.envelope.scope, selected.scope)) throw new OfflineError("OFFLINE_SYNC_RESPONSE_INVALID");
        const finished = await mutate(value => {
          const policy = allowed(value, request, loaded, epoch);
          if (value.data.lease?.run_id !== run.run_id || value.data.lease.expires_at <= Date.now()) throw new OfflineError("OFFLINE_SYNC_CANCELLED");
          const result = value.data.runs.find(value => value.run_id === run.run_id)!;
          Object.assign(result, { state: "no_change", stage: "finished", finished_at: now(), after_generation: loaded.slot.generation });
          policy.next_due_at = new Date(Date.now() + policy.interval_seconds * 1000).toISOString(); value.data.lease = null; return structuredClone(result);
        }, tx => slotGuard(tx, loaded)); return finished;
      }
      const plan = response.plan!; await advance("confirming", plan);
      const journal = (await snapshot()).data.journal;
      if (!journal || journal.run_id !== run.run_id) throw new OfflineError("OFFLINE_SYNC_CANCELLED");
      const descriptor = await tireApi.offlineSyncConfirm({ plan_id: plan.id, expected_fingerprint: plan.fingerprint, allow_device_storage: true }, journal.key, selected.owner_scope_id, controller.signal);
      if (descriptor.id !== plan.package_id || descriptor.plan_id !== plan.id || descriptor.plan_fingerprint !== plan.fingerprint
        || descriptor.owner_scope_id !== selected.owner_scope_id || descriptor.sha256 !== plan.content_sha256 || descriptor.byte_count !== plan.measured_bytes
        || descriptor.base_pack_id !== loaded.slot.package_id || !sameSyncValue(descriptor.counts, plan.counts)) throw new OfflineError("OFFLINE_SYNC_RESPONSE_INVALID");
      await advance("downloading");
      const commit = await snapshot(), policy = allowed(commit, request, loaded, epoch), result = commit.data.runs.find(value => value.run_id === run.run_id)!;
      const commitLease = commit.data.lease;
      if (!commitLease || commitLease.run_id !== run.run_id || commitLease.page_id !== pageId || commitLease.expires_at <= Date.now()
        || !result || result.state !== "running") throw new OfflineError("OFFLINE_SYNC_CANCELLED");
      policy.binding = { binding_revision: next(policy.binding.binding_revision), generation: next(loaded.slot.generation), package_id: descriptor.id, sha256: descriptor.sha256 };
      policy.next_due_at = new Date(Date.now() + policy.interval_seconds * 1000).toISOString();
      Object.assign(result, { state: "succeeded", stage: "finished", finished_at: now(), after_generation: policy.binding.generation });
      commit.data.lease = null;
      commit.data.release_checks = [...commit.data.release_checks.filter(check => check.slot_id !== loaded.slot.slot_id), {
        slot_id: loaded.slot.slot_id, generation: policy.binding.generation, sha256: descriptor.sha256, host_build: capabilities().host_build,
        validator_version: capabilities().validator_version, checked_at: now(), state: "passed", reason: null }];
      const record = await encoded(commit);
      await adapter.install({ package_id: descriptor.id, expected_sha256: descriptor.sha256, expected_byte_count: descriptor.byte_count,
        approved_plan_fingerprint: descriptor.plan_fingerprint, slot_id: loaded.slot.slot_id, expected_generation: loaded.slot.generation, allow_device_storage: true }, controller.signal, {
        runId: run.run_id, expectedOwner: selected.owner_scope_id,
        async validateEnvelope(envelope, bytes) {
          if (!sameSyncValue(envelope.scope, selected.scope) || envelope.owner_scope_id !== selected.owner_scope_id
            || await deviceSyncSemanticDigestFromBytes(bytes) !== response.current_semantic_digest) throw new OfflineError("OFFLINE_SYNC_RESPONSE_INVALID");
        },
        async guard(tx) {
          await current(tx, commit); await slotGuard(tx, loaded);
          if (controller.signal.aborted || apiTransportAuthorityEpoch() !== epoch) throw new OfflineError("OFFLINE_SYNC_CANCELLED");
          if (!syncConditionsSatisfied(selected.conditions, capabilities(), observations())) throw new OfflineError("OFFLINE_SYNC_CONDITIONS");
          const activeRecord = await adapter.result<Sidecar | undefined>(tx.objectStore("system").get(KEY));
          if (activeRecord?.revision !== commit.record?.revision) throw new OfflineError("OFFLINE_SYNC_CONFLICT");
          if (!commit.record || Date.now() >= commitLease.expires_at) throw new OfflineError("OFFLINE_SYNC_CANCELLED");
        },
        async write(tx) { await adapter.result(tx.objectStore("system").put(record, KEY)); },
      });
      notify(); return structuredClone(result);
    } catch (cause) {
      const code = reason(cause);
      const unknown = ["preparing", "confirming"].includes(stage) && !(cause instanceof ApiError && cause.status >= 400 && cause.status < 500)
        && !["OFFLINE_SYNC_CONFLICT", "OFFLINE_SYNC_CANCELLED", "OFFLINE_OWNER_CHANGED", "OFFLINE_STALE_GENERATION", "OFFLINE_SYNC_CONSENT_REQUIRED"].includes(code);
      await mutate(value => {
        const result = value.data.runs.find(value => value.run_id === run.run_id);
        if (!result || result.state !== "running") return;
        result.state = unknown ? "interrupted" : ["OFFLINE_SYNC_CONFLICT", "OFFLINE_SYNC_CANCELLED", "OFFLINE_SYNC_CONSENT_REQUIRED"].includes(code) ? "cancelled" : "failed";
        result.stage = "finished"; result.reason = unknown ? "OFFLINE_SYNC_RESPONSE_UNKNOWN" : code; result.finished_at = now();
        const policy = value.data.policies.find(policy => policy.policy_id === request.policy_id);
        if (policy?.policy_revision === request.expected_policy_revision && policy.state === "enabled") {
          if (unknown || ["SESSION_CHANGED", "offline_sync_session_required", "offline_sync_owner_mismatch", "OFFLINE_STALE_GENERATION"].includes(code)) {
            policy.state = "paused"; policy.policy_revision = next(policy.policy_revision); policy.reason = result.reason; policy.next_due_at = null; policy.updated_at = now();
          } else policy.next_due_at = new Date(Date.now() + policy.interval_seconds * 1000).toISOString();
        }
        if (value.data.lease?.run_id === run.run_id) value.data.lease = null;
      }).catch(() => {});
      const latest = (await snapshot()).data.runs.find(value => value.run_id === run.run_id);
      if (latest) return structuredClone(latest); throw offlineError(cause);
    } finally { clearTimeout(deadline); if (active.get(selected.policy_id) === controller) active.delete(selected.policy_id); }
  }
  async function runSyncPolicy(request: DeviceSyncRunRequest): Promise<DeviceSyncRun> {
    const frozen = structuredClone(request);
    if (!frozen || Object.keys(frozen).sort().join(",") !== "expected_policy_revision,policy_id,trigger" || !["manual", "timer", "resume", "online"].includes(frozen.trigger)) throw new OfflineError("OFFLINE_SYNC_INVALID");
    // Initialize outside the run lock: a nested ifAvailable request would suppress recovery.
    await initialize();
    const result = await withLock(() => runUnlocked(frozen)); if (!result) throw new OfflineError("OFFLINE_SYNC_BUSY"); return result;
  }
  async function resetOwner(commitOwner: (tx: IDBTransaction, owner: SyncProfile) => Promise<void>): Promise<void> {
    previews.clear();
    await mutate(value => {
      for (const policy of value.data.policies) if (policy.state !== "revoked") { policy.state = "revoked"; policy.policy_revision = next(policy.policy_revision); policy.next_due_at = null; policy.reason = "OFFLINE_OWNER_CHANGED"; policy.updated_at = now(); }
      for (const run of value.data.runs.filter(run => run.state === "running")) { run.state = "cancelled"; run.stage = "finished"; run.reason = "OFFLINE_OWNER_CHANGED"; run.finished_at = now(); }
      value.data.lease = null;
    }, async tx => { const owner = await adapter.result<SyncProfile>(tx.objectStore("system").get("profile")); await commitOwner(tx, owner); });
    abortPolicies([...active.keys()]);
  }
  async function cancelSlotMutation(request: OfflineSlotRequest): Promise<void> {
    let initial: Snapshot;
    try { initial = await snapshot(); } catch (cause) { if (reason(cause) === "OFFLINE_SYNC_CORRUPT") return; throw cause; }
    if (!initial.data.policies.some(policy => policy.slot_id === request.slot_id && policy.state !== "revoked")) return;
    let policyId: string | null = null, runId: string | null = null;
    await mutate(value => {
      const policy = value.data.policies.find(policy => policy.slot_id === request.slot_id && policy.state !== "revoked");
      if (!policy) return; policyId = policy.policy_id;
      policy.state = "paused"; policy.policy_revision = next(policy.policy_revision); policy.next_due_at = null; policy.updated_at = now(); policy.reason = "OFFLINE_STALE_GENERATION";
      if (value.data.lease?.policy_id === policyId) { runId = value.data.lease.run_id; value.data.lease = null; }
      for (const run of value.data.runs.filter(run => run.policy_id === policyId && run.state === "running")) { run.state = "cancelled"; run.stage = "finished"; run.reason = "OFFLINE_STALE_GENERATION"; run.finished_at = now(); }
    }, async tx => {
      const stored = await adapter.result<SyncStoredSlot | undefined>(tx.objectStore("slots").get(request.slot_id));
      if ((stored?.generation || 0) !== request.expected_generation) throw new OfflineError("OFFLINE_STALE_GENERATION");
      const lease = await adapter.result<{ sync_run_id?: string } | undefined>(tx.objectStore("system").get("lease"));
      if (runId && lease?.sync_run_id === runId) await adapter.result(tx.objectStore("system").delete("lease"));
    });
    if (policyId) abortPolicies([policyId]);
  }
  return { syncStatus: async () => revalidateSync(), previewSyncPolicy, applySyncPolicy,
    pauseSyncPolicy: (request: DeviceSyncPolicyRequest) => changePolicy(request, "paused"),
    revokeSyncPolicy: (request: DeviceSyncPolicyRequest) => changePolicy(request, "revoked"), runSyncPolicy, revalidateSync,
    requireValidated, resetOwner, cancelSlotMutation };
}
