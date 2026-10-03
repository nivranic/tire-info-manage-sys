import type { LocalFallbackConsumeRequest, LocalFallbackDecideRequest, LocalFallbackGrant, LocalFallbackRevokeRequest, LocalFallbackResult } from "@tire/domain-types";
import { FALLBACK_NOTICE, FALLBACK_TTL_MS, fallbackIntentKey, fallbackMemberMatches, validateFallbackCommand, validateFallbackDecision } from "./local-fallback-values";
import { approvedDeviceScopeFingerprint, fallbackHash, fallbackShape, fallbackUUID, exactSafeInteger, tireApi } from "@tire/api-client";
import type { AnyOfflineEnvelope as OfflineEnvelope, OfflineHostStatus, OfflineInstallRequest, AnyOfflinePackDescriptor as OfflinePackDescriptor, OfflineReadRequest, OfflineSearchRequest,
  OfflineSlot, OfflineSlotRequest, OfflineStorage, OfflineUnlockRequest } from "@tire/domain-types";
import { MAX_OFFLINE_BYTES, MAX_OFFLINE_SLOTS, MAX_OFFLINE_STORE_BYTES, OfflineError, newOfflineKey, offlineError,
  openOfflineBytes, sealOfflineBytes, type OfflineCiphertext } from "./offline-crypto";
import { readOfflineEnvelope, readOfflineResponse, searchOfflineEnvelope, validateOfflineBytes, validateOfflineDescriptor, validateOfflineInstall } from "./offline-values";
import { createBrowserDeviceSync, type SyncInstallHooks } from "./browser-device-sync";
import { createBrowserDeviceFallback } from "./browser-device-fallback";

const DB_NAME = "tire-device-history-v1";
interface Profile { profile_id: string; owner_epoch: number; key: CryptoKey }
interface StoredSlot { slot_id: string; generation: number; owner_epoch: number; deleted: boolean; metadata: OfflineCiphertext | null; payload: OfflineCiphertext | null }
interface Metadata { descriptor: OfflinePackDescriptor; summary: OfflineSlot; unlocked_epoch: number | null; fallback_binding?: import("@tire/domain-types").DeviceFallbackPackageBinding }
interface Lease { id: string; owner_epoch: number; expires_at: number; sync_run_id?: string }
let database: Promise<IDBDatabase> | null = null;
function db(): Promise<IDBDatabase> {
  if (typeof indexedDB === "undefined" || !globalThis.crypto?.subtle) return Promise.reject(new OfflineError("OFFLINE_UNAVAILABLE"));
  if (!database) database = new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => { request.result.createObjectStore("system"); request.result.createObjectStore("slots", { keyPath: "slot_id" }); };
    request.onsuccess = () => { request.result.onversionchange = () => { request.result.close(); database = null; }; resolve(request.result); };
    request.onerror = () => { database = null; reject(offlineError(request.error)); };
    request.onblocked = () => { database = null; reject(new OfflineError("OFFLINE_STORAGE_UNAVAILABLE")); };
  });
  return database;
}
const result = <T,>(request: IDBRequest<T>) => new Promise<T>((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(offlineError(request.error)); });
async function transaction<T>(names: string[], mode: IDBTransactionMode, work: (tx: IDBTransaction) => Promise<T>): Promise<T> {
  const tx = (await db()).transaction(names, mode);
  const done = new Promise<void>((resolve, reject) => { tx.oncomplete = () => resolve(); tx.onerror = tx.onabort = () => reject(offlineError(tx.error)); });
  // Crypto/network work stays outside IDB transactions; only IDB requests are awaited here.
  try { const value = await work(tx); await done; return value; }
  catch (cause) { try { tx.abort(); } catch { /* Already completed or aborted. */ } await done.catch(() => {}); throw offlineError(cause); }
}
async function profile(): Promise<Profile> {
  const found = await transaction(["system"], "readonly", tx => result<Profile | undefined>(tx.objectStore("system").get("profile")));
  if (found) { if (!found.key || found.key.extractable || found.key.algorithm.name !== "AES-GCM" || !Number.isSafeInteger(found.owner_epoch) || found.owner_epoch < 0) throw new OfflineError("OFFLINE_KEY_UNAVAILABLE"); return found; }
  const key = await newOfflineKey();
  return transaction(["system", "slots"], "readwrite", async tx => {
    const system = tx.objectStore("system"), existing = await result<Profile | undefined>(system.get("profile"));
    if (existing) return existing;
    if (await result(tx.objectStore("slots").count())) throw new OfflineError("OFFLINE_KEY_UNAVAILABLE");
    const value: Profile = { profile_id: crypto.randomUUID(), owner_epoch: 1, key };
    await result(system.put(value, "profile")); return value;
  });
}
const binding = (owner: Profile, stored: StoredSlot, part: string) => JSON.stringify(["offline-vault@1", owner.profile_id, stored.slot_id, stored.generation, stored.owner_epoch, part]);
const abort = (signal?: AbortSignal) => { if (signal?.aborted) throw new DOMException("离线安装已停止等待", "AbortError"); };
function nextGeneration(value: number): number {
  if (!Number.isSafeInteger(value) || value < 0 || value >= Number.MAX_SAFE_INTEGER) throw new OfflineError("OFFLINE_GENERATION_EXHAUSTED");
  return value + 1;
}
function committedBytes(stored: StoredSlot): number {
  if (stored.deleted) return 0;
  if (!stored.payload || !(stored.payload.ciphertext instanceof ArrayBuffer) || stored.payload.ciphertext.byteLength <= 16 || stored.payload.ciphertext.byteLength > MAX_OFFLINE_BYTES + 16) throw new OfflineError("OFFLINE_CORRUPT");
  return stored.payload.ciphertext.byteLength - 16; // AES-GCM tag is 16 bytes; original bytes are encrypted unchanged.
}
async function metadata(owner: Profile, stored: StoredSlot): Promise<Metadata> {
  if (stored.deleted || !stored.metadata) throw new OfflineError("OFFLINE_NOT_FOUND");
  let value: Metadata;
  try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await openOfflineBytes(owner.key, stored.metadata, binding(owner, stored, "metadata")))); }
  catch { throw new OfflineError("OFFLINE_CORRUPT"); }
  validateOfflineDescriptor(value.descriptor);
  if (!value.summary || value.summary.slot_id !== stored.slot_id || value.summary.generation !== stored.generation
    || value.summary.package_id !== value.descriptor.id || value.summary.sha256 !== value.descriptor.sha256
    || value.summary.byte_count !== committedBytes(stored) || value.summary.byte_count !== value.descriptor.byte_count) throw new OfflineError("OFFLINE_CORRUPT");
  if (value.fallback_binding) {
    const saved = value.fallback_binding; fallbackShape(saved, ["binding_revision", "slot_id", "generation", "package_id", "sha256", "history_scope_fingerprint", "source_ids"]);
    exactSafeInteger(saved.binding_revision, 1); exactSafeInteger(saved.generation, 1);
    if (saved.slot_id !== stored.slot_id || saved.generation !== stored.generation || saved.package_id !== value.descriptor.id || saved.sha256 !== value.descriptor.sha256 || !fallbackUUID(saved.package_id) || !fallbackHash(saved.history_scope_fingerprint)
      || !Array.isArray(saved.source_ids) || saved.source_ids.length > 200 || new Set(saved.source_ids).size !== saved.source_ids.length || saved.source_ids.some(source => typeof source !== "string" || !source || source.length > 100)) throw new OfflineError("OFFLINE_CORRUPT");
  }
  return value;
}
function visibleSlot(owner: Profile, stored: StoredSlot, meta: Metadata): OfflineSlot {
  const previous_owner = stored.owner_epoch !== owner.owner_epoch;
  return { ...meta.summary, previous_owner, locked: previous_owner && meta.unlocked_epoch !== owner.owner_epoch };
}
async function find(request: OfflineSlotRequest) {
  const owner = await profile();
  const stored = await transaction(["slots"], "readonly", tx => result<StoredSlot | undefined>(tx.objectStore("slots").get(request.slot_id)));
  if (!stored || stored.deleted) throw new OfflineError("OFFLINE_NOT_FOUND");
  if (stored.generation !== request.expected_generation) throw new OfflineError("OFFLINE_SLOT_CONFLICT");
  const meta = await metadata(owner, stored), slot = visibleSlot(owner, stored, meta);
  return { owner, stored, meta, slot };
}
async function loaded(request: OfflineSlotRequest) {
  const value = await find(request);
  if (value.slot.locked) throw new OfflineError("OFFLINE_LOCKED");
  await deviceSync.requireValidated(value.slot);
  const bytes = await openOfflineBytes(value.owner.key, value.stored.payload!, binding(value.owner, value.stored, "payload"));
  const envelope = await validateOfflineBytes(bytes, value.meta.descriptor);
  // A reset/replacement during decryption must not return now-stale private data.
  await transaction(["system", "slots"], "readonly", async tx => {
    const owner = await result<Profile>(tx.objectStore("system").get("profile"));
    const stored = await result<StoredSlot | undefined>(tx.objectStore("slots").get(request.slot_id));
    if (!owner || owner.profile_id !== value.owner.profile_id || owner.owner_epoch !== value.owner.owner_epoch) throw new OfflineError("OFFLINE_OWNER_CHANGED");
    if (!stored || stored.deleted || stored.generation !== request.expected_generation || !sameCipher(stored.metadata, value.stored.metadata) || !sameCipher(stored.payload, value.stored.payload)) throw new OfflineError("OFFLINE_SLOT_CONFLICT");
  });
  // Old slots gain scope metadata only during this separately authorized manual body read.
  if (!value.meta.fallback_binding && !value.slot.previous_owner) {
    const fallback_binding: import("@tire/domain-types").DeviceFallbackPackageBinding = { binding_revision: 1, slot_id: value.slot.slot_id, generation: value.slot.generation, package_id: value.slot.package_id, sha256: value.slot.sha256,
      history_scope_fingerprint: await approvedDeviceScopeFingerprint(envelope.scope), source_ids: [...new Set(envelope.members.map(member => member.source.source_id).filter((source): source is string => source !== null))].sort() };
    const updated = { ...value.meta, fallback_binding }, encrypted = await sealOfflineBytes(value.owner.key, new TextEncoder().encode(JSON.stringify(updated)), binding(value.owner, value.stored, "metadata"));
    await transaction(["system", "slots"], "readwrite", async tx => { await requireFallbackSnapshot(tx, value.owner, value.stored); await result(tx.objectStore("slots").put({ ...value.stored, metadata: encrypted })); });
    value.meta = updated; value.stored = { ...value.stored, metadata: encrypted };
  }
  return { ...value, envelope, originalBytes: bytes };
}

async function install(request: OfflineInstallRequest, cancellation?: AbortSignal, hooks?: SyncInstallHooks): Promise<OfflineSlot> {
  validateOfflineInstall(request); abort(cancellation);
  if (!hooks) await deviceSync.cancelSlotMutation({ slot_id: request.slot_id, expected_generation: request.expected_generation });
  const owner = await profile(), lease: Lease = { id: crypto.randomUUID(), owner_epoch: owner.owner_epoch, expires_at: Date.now() + 120_000, ...(hooks ? { sync_run_id: hooks.runId } : {}) };
  await transaction(["system"], "readwrite", async tx => {
    const store = tx.objectStore("system"), current = await result<Profile>(store.get("profile")), pending = await result<Lease | undefined>(store.get("lease"));
    if (current.owner_epoch !== owner.owner_epoch) throw new OfflineError("OFFLINE_OWNER_CHANGED");
    if (pending && pending.expires_at > Date.now()) throw new OfflineError("OFFLINE_INSTALL_BUSY");
    lease.expires_at = Date.now() + 120_000;
    await result(store.put(lease, "lease"));
  });
  const lifetime = new AbortController(), signal = lifetime.signal;
  let timedOut = false;
  const cancel = () => lifetime.abort();
  cancellation?.addEventListener("abort", cancel, { once: true });
  if (cancellation?.aborted) cancel();
  // End transport before the cross-tab lease can expire; another tab must not
  // enter while an unbounded former download is still staging original bytes.
  const deadlineAt = lease.expires_at - 30_000;
  const deadline = setTimeout(() => { timedOut = true; lifetime.abort(); }, Math.max(0, deadlineAt - Date.now()));
  try {
    if (Date.now() >= deadlineAt) throw new OfflineError("API_TIMEOUT");
    abort(signal);
    const descriptor = validateOfflineDescriptor(await (hooks ? tireApi.offlineSyncPack(request.package_id, hooks.expectedOwner, signal) : tireApi.offlinePack(request.package_id, signal)));
    if (descriptor.id !== request.package_id || descriptor.sha256 !== request.expected_sha256 || descriptor.byte_count !== request.expected_byte_count || descriptor.plan_fingerprint !== request.approved_plan_fingerprint) throw new OfflineError("OFFLINE_HASH_MISMATCH");
    const bytes = await readOfflineResponse(await (hooks ? tireApi.offlineSyncBytes(request.package_id, hooks.expectedOwner, signal) : tireApi.offlinePackBytes(request.package_id, signal)), descriptor);
    const envelope = await validateOfflineBytes(bytes, descriptor); abort(signal);
    if (hooks) await hooks.validateEnvelope(envelope, bytes);
    const previous = await transaction(["slots"], "readonly", tx => result<StoredSlot | undefined>(tx.objectStore("slots").get(request.slot_id)));
    if ((previous?.generation || 0) !== request.expected_generation) throw new OfflineError("OFFLINE_SLOT_CONFLICT");
    if (previous && !previous.deleted && previous.owner_epoch !== owner.owner_epoch) throw new OfflineError("OFFLINE_LOCKED");
    const stored: StoredSlot = { slot_id: request.slot_id, generation: nextGeneration(previous?.generation || 0), owner_epoch: owner.owner_epoch, deleted: false, metadata: null, payload: null };
    const summary: OfflineSlot = { slot_id: stored.slot_id, generation: stored.generation, package_id: descriptor.id, sha256: descriptor.sha256,
      byte_count: descriptor.byte_count, title: `设备历史资料 · ${descriptor.counts.distinct_evidence} 份证据 / ${descriptor.counts.garage_profiles} 份车库档案`,
      created_at: envelope.created_at, installed_at: new Date().toISOString(), privacy_class: descriptor.privacy_class,
      owner_scope_id: descriptor.owner_scope_id, locked: false, previous_owner: false, counts: descriptor.counts };
    const previousBinding = previous && !previous.deleted ? (await metadata(owner, previous)).fallback_binding : undefined;
    const fallback_binding: import("@tire/domain-types").DeviceFallbackPackageBinding = { binding_revision: nextGeneration(previousBinding?.binding_revision || 0), slot_id: stored.slot_id, generation: stored.generation, package_id: descriptor.id, sha256: descriptor.sha256,
      history_scope_fingerprint: await approvedDeviceScopeFingerprint(envelope.scope), source_ids: [...new Set(envelope.members.map(member => member.source.source_id).filter((value): value is string => value !== null))].sort() };
    const fallbackInstall = await deviceFallback.prepareInstall(owner, summary, fallback_binding, !!hooks);
    stored.payload = await sealOfflineBytes(owner.key, bytes, binding(owner, stored, "payload"));
    stored.metadata = await sealOfflineBytes(owner.key, new TextEncoder().encode(JSON.stringify({ descriptor, summary, unlocked_epoch: null, fallback_binding } satisfies Metadata)), binding(owner, stored, "metadata"));
    abort(signal);
    await transaction(["system", "slots"], "readwrite", async tx => {
      const system = tx.objectStore("system"), slots = tx.objectStore("slots"), current = await result<Profile>(system.get("profile"));
      const pending = await result<Lease | undefined>(system.get("lease"));
      if (current.owner_epoch !== owner.owner_epoch || pending?.id !== lease.id || pending.expires_at < Date.now()) throw new OfflineError("OFFLINE_OWNER_CHANGED");
      const existing = await result<StoredSlot | undefined>(slots.get(request.slot_id));
      if ((existing?.generation || 0) !== request.expected_generation || (existing?.generation || 0) !== (previous?.generation || 0)) throw new OfflineError("OFFLINE_SLOT_CONFLICT");
      const all = (await result<StoredSlot[]>(slots.getAll())).filter(value => !value.deleted && value.slot_id !== request.slot_id);
      if (all.length >= MAX_OFFLINE_SLOTS || all.reduce((sum, value) => sum + committedBytes(value), 0) + descriptor.byte_count > MAX_OFFLINE_STORE_BYTES) throw new OfflineError("OFFLINE_STORE_LIMIT");
      if (hooks) await hooks.guard(tx);
      await fallbackInstall.guard(tx);
      abort(signal); await result(slots.put(stored));
      if (hooks) await hooks.write(tx);
      await fallbackInstall.write(tx);
      await result(system.delete("lease"));
    });
    // Permission denial is best-effort storage, not a failed committed installation.
    if (navigator.storage?.persist) await navigator.storage.persist().catch(() => false);
    return summary;
  } catch (cause) {
    if (timedOut) throw new OfflineError("API_TIMEOUT");
    throw cause;
  } finally {
    clearTimeout(deadline); cancellation?.removeEventListener("abort", cancel);
    await transaction(["system"], "readwrite", async tx => {
      const store = tx.objectStore("system"), pending = await result<Lease | undefined>(store.get("lease"));
      if (pending?.id === lease.id) await result(store.delete("lease"));
    }).catch(() => {});
  }
}

const deviceSync = createBrowserDeviceSync({ profile, install, result,
  describe: async request => (await find(request)).slot,
  slots: () => transaction(["slots"], "readonly", tx => result<StoredSlot[]>(tx.objectStore("slots").getAll())),
  transaction: work => transaction(["system", "slots"], "readwrite", work),
  async load(request) {
    const value = await find(request);
    const bytes = await openOfflineBytes(value.owner.key, value.stored.payload!, binding(value.owner, value.stored, "payload"));
    const envelope = await validateOfflineBytes(bytes, value.meta.descriptor);
    await transaction(["system", "slots"], "readonly", async tx => {
      const owner = await result<Profile>(tx.objectStore("system").get("profile")), stored = await result<StoredSlot | undefined>(tx.objectStore("slots").get(request.slot_id));
      if (owner.profile_id !== value.owner.profile_id || owner.owner_epoch !== value.owner.owner_epoch) throw new OfflineError("OFFLINE_OWNER_CHANGED");
      if (!stored || stored.deleted || stored.generation !== value.stored.generation || !sameCipher(stored.payload, value.stored.payload) || !sameCipher(stored.metadata, value.stored.metadata)) throw new OfflineError("OFFLINE_STALE_GENERATION");
    });
    return { ...value, envelope, originalBytes: bytes };
  },
});

interface PendingFallback { grant: LocalFallbackGrant; monotonic: number }
interface FallbackAudit { revision: number; encrypted: OfflineCiphertext }
const fallbackPending = new Map<string, PendingFallback>();
const fallbackAttempts = new Set<string>();
const deviceFallback = createBrowserDeviceFallback({ profile, result, attempts: fallbackAttempts,
  legacyPendingCount() { for (const [id, value] of fallbackPending) if (fallbackExpired(value)) fallbackPending.delete(id); return fallbackPending.size; },
  transaction: work => transaction(["system", "slots"], "readwrite", work),
  fence: (tx, owner, stored) => requireFallbackSnapshot(tx, owner, stored),
  async locate(request) { const value = await find(request); return { owner: value.owner, stored: value.stored, slot: value.slot, binding: value.meta.fallback_binding || null }; },
  async bindings() {
    const owner = await profile(), values = await transaction(["slots"], "readonly", tx => result<StoredSlot[]>(tx.objectStore("slots").getAll()));
    const bindings: import("@tire/domain-types").DeviceFallbackPackageBinding[] = [], missing: import("@tire/domain-types").DeviceFallbackStatus["missing_package_bindings"] = [];
    for (const stored of values.filter(value => !value.deleted && value.owner_epoch === owner.owner_epoch)) {
      const meta = await metadata(owner, stored), slot = visibleSlot(owner, stored, meta); if (slot.locked || slot.previous_owner) continue;
      if (meta.fallback_binding) bindings.push(meta.fallback_binding); else missing.push({ slot_id: stored.slot_id, generation: stored.generation, reason: "scope_metadata_missing" });
    }
    return { bindings, missing };
  },
  async load(value) {
    await deviceSync.requireValidated(value.slot);
    const meta = await metadata(value.owner, value.stored), bytes = await openOfflineBytes(value.owner.key, value.stored.payload!, binding(value.owner, value.stored, "payload"));
    return validateOfflineBytes(bytes, meta.descriptor);
  },
});
let fallbackTail: Promise<unknown> = Promise.resolve();
function fallbackLocked<T>(work: () => Promise<T>): Promise<T> {
  const next = fallbackTail.then(work, work); fallbackTail = next.catch(() => {}); return next;
}
const sameBytes = (a: ArrayBuffer | Uint8Array, b: ArrayBuffer | Uint8Array) => {
  const x = a instanceof Uint8Array ? a : new Uint8Array(a), y = b instanceof Uint8Array ? b : new Uint8Array(b);
  return x.length === y.length && x.every((byte, index) => byte === y[index]);
};
const sameCipher = (a: OfflineCiphertext | null, b: OfflineCiphertext | null) => !!a && !!b && sameBytes(a.iv, b.iv) && sameBytes(a.ciphertext, b.ciphertext);
const auditBinding = (owner: Profile, revision: number) => JSON.stringify(["device-fallback-audit@1", owner.profile_id, revision]);
const fallbackExpired = (value: PendingFallback) => {
  const wall = Date.now(), monotonic = performance.now();
  return wall < Date.parse(value.grant.decided_at) || wall >= Date.parse(value.grant.expires_at) || monotonic < value.monotonic || monotonic - value.monotonic >= FALLBACK_TTL_MS;
};
function currentFallback(value: Awaited<ReturnType<typeof find>>, request: LocalFallbackDecideRequest): void {
  if (value.owner.profile_id !== request.expected_profile_id || value.owner.owner_epoch !== request.expected_owner_epoch || value.slot.locked || value.slot.previous_owner) throw new OfflineError("OFFLINE_OWNER_LOCKED");
  if (value.slot.generation !== request.expected_generation || value.slot.sha256 !== request.expected_sha256) throw new OfflineError("OFFLINE_STALE_GENERATION");
}
async function fallbackFind(request: LocalFallbackDecideRequest) {
  try { const value = await find({ slot_id: request.slot_id, expected_generation: request.expected_generation }); currentFallback(value, request); return value; }
  catch (cause) { if (cause instanceof OfflineError && ["OFFLINE_NOT_FOUND", "OFFLINE_SLOT_CONFLICT"].includes(cause.code)) throw new OfflineError("OFFLINE_STALE_GENERATION"); throw cause; }
}
async function requireFallbackSnapshot(tx: IDBTransaction, owner: Profile, snapshot?: StoredSlot, pending?: PendingFallback): Promise<void> {
  const current = await result<Profile | undefined>(tx.objectStore("system").get("profile"));
  if (!current || current.profile_id !== owner.profile_id || current.owner_epoch !== owner.owner_epoch) throw new OfflineError("OFFLINE_OWNER_LOCKED");
  if (snapshot) {
    const stored = await result<StoredSlot | undefined>(tx.objectStore("slots").get(snapshot.slot_id));
    if (!stored || stored.deleted || stored.generation !== snapshot.generation || stored.owner_epoch !== owner.owner_epoch || !sameCipher(stored.metadata, snapshot.metadata) || !sameCipher(stored.payload, snapshot.payload)) throw new OfflineError("OFFLINE_STALE_GENERATION");
  }
  if (pending && fallbackExpired(pending)) throw new OfflineError("OFFLINE_FALLBACK_EXPIRED");
}
/** Crypto is outside IDB. Owner, slot ciphertext and audit revision commit atomically. */
async function appendFallbackAudit(owner: Profile, grant: LocalFallbackGrant, snapshot?: StoredSlot, pending?: PendingFallback, policyFence?: (tx: IDBTransaction) => Promise<void>): Promise<void> {
  for (let retry = 0; retry < 4; retry++) {
    const before = await transaction(["system"], "readonly", tx => result<FallbackAudit | undefined>(tx.objectStore("system").get("fallback-audit")));
    let receipts: LocalFallbackGrant[] = [];
    if (before) {
      if (!Number.isSafeInteger(before.revision) || before.revision < 1) throw new OfflineError("OFFLINE_CORRUPT");
      try { receipts = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await openOfflineBytes(owner.key, before.encrypted, auditBinding(owner, before.revision)))); }
      catch { throw new OfflineError("OFFLINE_CORRUPT"); }
      if (!Array.isArray(receipts) || receipts.length > 64) throw new OfflineError("OFFLINE_CORRUPT");
    }
    const revision = nextGeneration(before?.revision || 0);
    const encrypted = await sealOfflineBytes(owner.key, new TextEncoder().encode(JSON.stringify([...receipts, grant].slice(-64))), auditBinding(owner, revision));
    const committed = await transaction(["system", "slots"], "readwrite", async tx => {
      if (policyFence) await policyFence(tx);
      const system = tx.objectStore("system");
      await requireFallbackSnapshot(tx, owner, snapshot, pending);
      const currentAudit = await result<FallbackAudit | undefined>(system.get("fallback-audit"));
      if ((currentAudit?.revision || 0) !== (before?.revision || 0)) return false;
      await result(system.put({ revision, encrypted } satisfies FallbackAudit, "fallback-audit")); return true;
    });
    if (committed) return;
  }
  throw new OfflineError("OFFLINE_FALLBACK_CAPACITY");
}
function fallbackRequest(grant: LocalFallbackGrant): LocalFallbackDecideRequest {
  return { intent: grant.intent, slot_id: grant.slot_id, expected_generation: grant.generation, expected_sha256: grant.package_sha256,
    expected_profile_id: grant.profile_id, expected_owner_epoch: grant.owner_epoch, decision: "allow" };
}
async function decideFallback(request: LocalFallbackDecideRequest): Promise<LocalFallbackGrant> {
  validateFallbackDecision(request);
  // Clone before the first await: callers cannot mutate the authorized query later.
  const frozen = structuredClone(request);
  return fallbackLocked(async () => {
    let policyFence: (tx: IDBTransaction) => Promise<void>;
    try { policyFence = await deviceFallback.legacyFence(frozen.intent); } catch (cause) { if (!fallbackAttempts.has(frozen.intent.attempt_id) && fallbackAttempts.size >= 1024) throw new OfflineError("OFFLINE_FALLBACK_CAPACITY"); fallbackAttempts.add(frozen.intent.attempt_id); throw cause; }
    if (fallbackAttempts.has(frozen.intent.attempt_id)) throw new OfflineError("OFFLINE_FALLBACK_USED");
    for (const [id, pending] of fallbackPending) if (fallbackExpired(pending)) fallbackPending.delete(id);
    if (fallbackAttempts.size >= 1024 || (frozen.decision === "allow" && fallbackPending.size + deviceFallback.pendingCount() >= 16)) throw new OfflineError("OFFLINE_FALLBACK_CAPACITY");
    fallbackAttempts.add(frozen.intent.attempt_id);
    const value = await fallbackFind(frozen), now = Date.now();
    const grant: LocalFallbackGrant = { schema: "device-fallback-grant@1", id: crypto.randomUUID(), scope: "local_once", state: frozen.decision === "allow" ? "allowed" : "denied", intent: frozen.intent,
      profile_id: value.owner.profile_id, owner_epoch: value.owner.owner_epoch, slot_id: value.slot.slot_id, generation: value.slot.generation, package_sha256: value.slot.sha256,
      decided_at: new Date(now).toISOString(), expires_at: new Date(now + FALLBACK_TTL_MS).toISOString(), consumed_at: null };
    const pending = { grant, monotonic: performance.now() };
    await appendFallbackAudit(value.owner, grant, value.stored, pending, policyFence);
    if (grant.state === "allowed") fallbackPending.set(grant.id, pending);
    return structuredClone(grant);
  });
}
async function consumeFallback(request: LocalFallbackConsumeRequest): Promise<LocalFallbackResult> {
  validateFallbackCommand(request, true); const frozen = structuredClone(request);
  return fallbackLocked(async () => {
    const pending = fallbackPending.get(frozen.grant_id); fallbackPending.delete(frozen.grant_id);
    if (!pending) throw new OfflineError("OFFLINE_FALLBACK_USED");
    if (fallbackIntentKey(pending.grant.intent) !== fallbackIntentKey(frozen.intent)) throw new OfflineError("OFFLINE_FALLBACK_MISMATCH");
    if (fallbackExpired(pending)) throw new OfflineError("OFFLINE_FALLBACK_EXPIRED");
    const policyFence = await deviceFallback.legacyFence(frozen.intent);
    const value = await fallbackFind(fallbackRequest(pending.grant));
    const grant: LocalFallbackResult["grant"] = { ...pending.grant, state: "consumed", consumed_at: new Date().toISOString() };
    // The consumed receipt must commit before release validation can read a body.
    // A failed body read stays consumed; an audit failure cannot read the body.
    await appendFallbackAudit(value.owner, grant, value.stored, pending, policyFence);
    if (value.meta.descriptor.schema !== "offline-pack-descriptor@1") throw new OfflineError("OFFLINE_FALLBACK_UNSUPPORTED");
    await deviceSync.requireValidated(value.slot);
    const bytes = await openOfflineBytes(value.owner.key, value.stored.payload!, binding(value.owner, value.stored, "payload"));
    const envelope = await validateOfflineBytes(bytes, value.meta.descriptor);
    const response: LocalFallbackResult = { schema: "device-fallback-result@1", data_state: "local_snapshot", fallback_consent: "local_once", grant, slot: value.slot,
      members: (envelope.members as import("@tire/domain-types").OfflineMemberV2[]).filter((member): member is import("@tire/domain-types").OfflineMember => member.reference.kind === "tire" && fallbackMemberMatches(member as import("@tire/domain-types").OfflineMember, frozen.intent)), complete_query_result: false, notice: FALLBACK_NOTICE };
    if (new TextEncoder().encode(JSON.stringify(response)).byteLength > MAX_OFFLINE_BYTES) throw new OfflineError("OFFLINE_FALLBACK_CAPACITY");
    // Preserve the owner/ciphertext/expiry release fence without a second receipt.
    await transaction(["system", "slots"], "readonly", async tx => { await policyFence(tx); await requireFallbackSnapshot(tx, value.owner, value.stored, pending); });
    return response;
  });
}
async function revokeFallback(request: LocalFallbackRevokeRequest) {
  validateFallbackCommand(request, false); const id = request.grant_id;
  return fallbackLocked(async () => {
    const pending = fallbackPending.get(id); fallbackPending.delete(id);
    if (pending) { const owner = await profile(); if (owner.profile_id === pending.grant.profile_id && owner.owner_epoch === pending.grant.owner_epoch) await appendFallbackAudit(owner, { ...pending.grant, state: "revoked" }); }
    return { revoked: true as const, grant_id: id };
  });
}

export const browserOfflineStorage: OfflineStorage = {
  fallbackStatus: deviceFallback.fallbackStatus, refreshFallbackAuthority: deviceFallback.refreshFallbackAuthority,
  previewFallbackPolicy: deviceFallback.previewFallbackPolicy, applyFallbackPolicy: deviceFallback.applyFallbackPolicy,
  pauseFallbackPolicy: deviceFallback.pauseFallbackPolicy, revokeFallbackPolicy: deviceFallback.revokeFallbackPolicy,
  authorizeFallback: deviceFallback.authorizeFallback, decideFallbackV2: deviceFallback.decideFallbackV2,
  consumeFallbackV2: deviceFallback.consumeFallbackV2, revokeFallbackV2: deviceFallback.revokeFallbackV2,
  syncStatus: deviceSync.syncStatus, previewSyncPolicy: deviceSync.previewSyncPolicy, applySyncPolicy: deviceSync.applySyncPolicy,
  pauseSyncPolicy: deviceSync.pauseSyncPolicy, revokeSyncPolicy: deviceSync.revokeSyncPolicy, runSyncPolicy: deviceSync.runSyncPolicy, revalidateSync: deviceSync.revalidateSync,
  async status() {
    const base: OfflineHostStatus = { schema: "offline-host@1", available: false, state: "unavailable", storage: "indexeddb", profile_id: null, owner_epoch: 0,
      total_bytes: 0, max_store_bytes: MAX_OFFLINE_STORE_BYTES, max_package_bytes: MAX_OFFLINE_BYTES, max_slots: MAX_OFFLINE_SLOTS,
      encryption: "webcrypto", persistence: "best_effort", manual_updates: true, background_updates: false, error: null };
    try {
      const owner = await profile(), values = await transaction(["slots"], "readonly", tx => result<StoredSlot[]>(tx.objectStore("slots").getAll()));
      return { ...base, available: true, state: "ready", profile_id: owner.profile_id, owner_epoch: owner.owner_epoch,
        total_bytes: values.reduce((sum, value) => sum + committedBytes(value), 0), persistence: await navigator.storage?.persisted?.().catch(() => false) ? "persistent_granted" : "best_effort" };
    } catch (cause) { return { ...base, state: "error", error: offlineError(cause).code }; }
  },
  async list() {
    const owner = await profile(), values = await transaction(["slots"], "readonly", tx => result<StoredSlot[]>(tx.objectStore("slots").getAll()));
    const items: OfflineSlot[] = [];
    for (const stored of values.filter(value => !value.deleted)) items.push(visibleSlot(owner, stored, await metadata(owner, stored)));
    return { schema: "offline-host@1", data_state: "local_snapshot", profile_id: owner.profile_id, owner_epoch: owner.owner_epoch, items: items.sort((a, b) => b.installed_at.localeCompare(a.installed_at)) };
  },
  install, decideFallback, consumeFallback, revokeFallback,
  async search(request: OfflineSearchRequest) { const value = await loaded(request); return searchOfflineEnvelope(value.envelope, value.slot, request); },
  async read(request: OfflineReadRequest) { const value = await loaded(request); return readOfflineEnvelope(value.envelope, value.slot, request); },
  async remove(request: OfflineSlotRequest) {
    await deviceSync.cancelSlotMutation(request);
    const generation = await transaction(["slots"], "readwrite", async tx => {
      const store = tx.objectStore("slots"), existing = await result<StoredSlot | undefined>(store.get(request.slot_id));
      if (!existing || existing.deleted) throw new OfflineError("OFFLINE_NOT_FOUND");
      if (existing.generation !== request.expected_generation) throw new OfflineError("OFFLINE_SLOT_CONFLICT");
      const generation = nextGeneration(existing.generation);
      await result(store.put({ ...existing, generation, deleted: true, metadata: null, payload: null } satisfies StoredSlot));
      return generation;
    });
    return { removed: true, slot_id: request.slot_id, generation };
  },
  async unlockPreviousOwner(request: OfflineUnlockRequest) {
    if (request.allow_previous_owner !== true) throw new OfflineError("OFFLINE_INVALID_REQUEST");
    const value = await find(request); const updated = { ...value.meta, unlocked_epoch: value.owner.owner_epoch };
    const encrypted = await sealOfflineBytes(value.owner.key, new TextEncoder().encode(JSON.stringify(updated)), binding(value.owner, value.stored, "metadata"));
    await transaction(["system", "slots"], "readwrite", async tx => {
      const current = await result<Profile>(tx.objectStore("system").get("profile")), store = tx.objectStore("slots");
      const existing = await result<StoredSlot | undefined>(store.get(request.slot_id));
      if (current.owner_epoch !== value.owner.owner_epoch) throw new OfflineError("OFFLINE_OWNER_CHANGED");
      if (!existing || existing.deleted || existing.generation !== request.expected_generation) throw new OfflineError("OFFLINE_SLOT_CONFLICT");
      await result(store.put({ ...existing, metadata: encrypted }));
    });
    return visibleSlot(value.owner, value.stored, updated);
  },
};

// Browser-local explicit owner transition. Temporary network/session errors never call this.
export async function resetBrowserOfflineOwner(): Promise<void> {
  fallbackPending.clear();
  deviceFallback.resetOwner();
  await profile();
  const fallbackReset = await deviceFallback.prepareOwnerReset();
  await deviceSync.resetOwner(async (tx, current) => {
    const store = tx.objectStore("system");
    await fallbackReset.guard(tx);
    await result(store.put({ ...current, owner_epoch: nextGeneration(current.owner_epoch) }, "profile")); await result(store.delete("lease"));
    await fallbackReset.write(tx);
  });
  deviceFallback.resetOwner(true);
  if (typeof window !== "undefined") window.dispatchEvent(new Event("tire-offline-owner-changed"));
}

// Device-AI host hooks (roundtable proposal narrow host hooks): read-only owner
// identity and original package bytes for the local preview / projection port.
// Nothing here grants fallback, sync or AI authorization by itself.
export async function browserOfflineOwnerSummary(): Promise<{ profile_id: string; owner_epoch: number }> {
  const owner = await profile();
  return { profile_id: owner.profile_id, owner_epoch: owner.owner_epoch };
}

export async function readBrowserOfflinePackBytes(request: OfflineSlotRequest): Promise<{ slot: OfflineSlot; bytes: Uint8Array }> {
  const value = await loaded(request);
  return { slot: value.slot, bytes: value.originalBytes };
}
