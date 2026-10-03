// Device-AI web host persistence: the encrypted journal blob and its
// non-extractable AES-GCM key in a dedicated IndexedDB database
// ("tire-device-ai-v1"), following the offline-crypto conventions of
// browser-offline-store.ts (non-extractable CryptoKey stored via structured
// clone, owner-bound AAD inside the SDK seal, separate database so the sealed
// tire-device-history-v1 schema never needs a version bump).
//
// Owner fence input comes from the browser offline profile (profile_id +
// owner_epoch, the established device-local identity convention); a profile
// owner reset therefore voids the journal explicitly (generation bump + new
// key) instead of leaving an undecryptable blob to surface as corrupt.
//
// The store seams (system/blob stores) are interfaces so Node selftests can
// exercise the exact persistence decision flow without IndexedDB; the real
// IndexedDB path is exercised by the Chromium QA.
import { newOfflineKey } from "./offline-crypto";
import { DeviceAiJournal, type DeviceAiJournalStore } from "../../../packages/api-client/src/device-ai-host";
import { browserOfflineOwnerSummary } from "./browser-offline-store";

const DB_NAME = "tire-device-ai-v1";
const SESSION_KEY = "tire-device-ai-session-v1";
const UUID_CANONICAL = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export interface DeviceAiJournalSystem { owner: string; generation: number; key: CryptoKey }
export interface DeviceAiSystemStore {
  get(): Promise<DeviceAiJournalSystem | null>;
  put(record: DeviceAiJournalSystem): Promise<void>;
  /** Remove any sealed blob left by a previous owner (rebuild path only). */
  clear(): Promise<void>;
}
export interface DeviceAiStores { system: DeviceAiSystemStore; blobs: DeviceAiJournalStore }

/** Owner fence string: the offline profile identity this journal belongs to. */
export function deviceAiJournalOwner(profile: { profile_id: string; owner_epoch: number }): string {
  return `device-ai-journal@1:${profile.profile_id}:${profile.owner_epoch}`;
}

/** Fence 5 input: one id per browser tab session (survives reload, not new tabs). */
export function deviceAiSessionId(): string {
  try {
    const existing = sessionStorage.getItem(SESSION_KEY);
    if (existing && UUID_CANONICAL.test(existing)) return existing;
  } catch { /* Tab storage blocked: fall through to a per-call id. */ }
  const id = crypto.randomUUID();
  try { sessionStorage.setItem(SESSION_KEY, id); } catch { /* Same fallback as above. */ }
  return id;
}

export async function newDeviceAiJournalKey(): Promise<CryptoKey> { return newOfflineKey(); }

/**
 * Integer monotonic clock for the journal fence: Date.now() (wall ms, integer,
 * survives reloads, unlike performance.now) with +1 stepping so two appends in
 * the same millisecond still strictly increase. Stored entries keep their own
 * chain, so blob truncation/reordering still fails verification.
 */
export function deviceAiMonotonicClock(): () => number {
  let last = Number.NEGATIVE_INFINITY;
  return () => { const now = Date.now(); const value = now > last ? now : last + 1; last = value; return value; };
}

/** In-memory seam for Node selftests of the persistence decision flow. */
export function memoryDeviceAiStores() {
  const state = { system: null as DeviceAiJournalSystem | null, blob: null as Uint8Array | null };
  const stores: DeviceAiStores = {
    system: {
      async get() { return state.system; },
      async put(record) { state.system = record; },
      async clear() { state.blob = null; },
    },
    blobs: {
      async load() { return state.blob; },
      async save(blob) { state.blob = blob; },
    },
  };
  return { stores, state };
}

function idbRequest<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
}

let database: Promise<IDBDatabase> | null = null;
function db(): Promise<IDBDatabase> {
  if (typeof indexedDB === "undefined" || !globalThis.crypto?.subtle) return Promise.reject(new Error("device_ai_unavailable"));
  if (!database) database = new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => { request.result.createObjectStore("system"); request.result.createObjectStore("journal"); };
    request.onsuccess = () => { request.result.onversionchange = () => { request.result.close(); database = null; }; resolve(request.result); };
    request.onerror = () => { database = null; reject(request.error); };
    request.onblocked = () => { database = null; reject(request.error ?? new Error("device_ai_storage_blocked")); };
  });
  return database;
}

function browserDeviceAiStores(): DeviceAiStores {
  const withStores = async <T>(names: string[], mode: IDBTransactionMode, work: (tx: IDBTransaction) => Promise<T>): Promise<T> => {
    const tx = (await db()).transaction(names, mode);
    const done = new Promise<void>((resolve, reject) => { tx.oncomplete = () => resolve(); tx.onerror = tx.onabort = () => reject(tx.error); });
    try { const value = await work(tx); await done; return value; }
    catch (cause) { try { tx.abort(); } catch { /* Already settled. */ } await done.catch(() => {}); throw cause; }
  };
  return {
    system: {
      async get() {
        return withStores(["system"], "readonly", async tx => {
          const record = await idbRequest<{ owner?: unknown; generation?: unknown; key?: unknown } | undefined>(tx.objectStore("system").get("journal"));
          if (!record || typeof record !== "object" || typeof record.owner !== "string"
            || !Number.isSafeInteger(record.generation) || !(record.key instanceof CryptoKey)) return null;
          return record as DeviceAiJournalSystem;
        });
      },
      async put(record) {
        await withStores(["system"], "readwrite", async tx => { await idbRequest(tx.objectStore("system").put(record, "journal")); });
      },
      async clear() {
        await withStores(["journal"], "readwrite", async tx => { await idbRequest(tx.objectStore("journal").clear()); });
      },
    },
    blobs: {
      async load() {
        return withStores(["journal"], "readonly", async tx => {
          const blob = await idbRequest<Uint8Array | undefined>(tx.objectStore("journal").get("blob"));
          return blob instanceof Uint8Array ? blob : null;
        });
      },
      async save(blob) {
        await withStores(["journal"], "readwrite", async tx => { await idbRequest(tx.objectStore("journal").put(blob, "blob")); });
      },
    },
  };
}

export interface OpenedDeviceAiJournal { journal: DeviceAiJournal; system: DeviceAiJournalSystem; rebuilt: boolean }

/**
 * Resolve the journal for the CURRENT owner: reuse the stored key and
 * generation when the owner matches; otherwise void the old blob explicitly
 * (generation bump, fresh key) so an owner reset never resurrects old claims.
 */
export async function openDeviceAiJournal(owner: string, stores: DeviceAiStores): Promise<OpenedDeviceAiJournal> {
  const clock = deviceAiMonotonicClock();
  const existing = await stores.system.get();
  if (existing && existing.owner === owner && existing.key.algorithm.name === "AES-GCM") {
    const journal = new DeviceAiJournal({ owner, generation: existing.generation, sessionId: deviceAiSessionId(),
      key: existing.key, store: stores.blobs, monotonicNow: clock });
    return { journal, system: existing, rebuilt: false };
  }
  const system: DeviceAiJournalSystem = { owner, generation: (existing?.generation ?? 0) + 1, key: await newDeviceAiJournalKey() };
  await stores.system.put(system);
  await stores.system.clear();
  const journal = new DeviceAiJournal({ owner, generation: system.generation, sessionId: deviceAiSessionId(),
    key: system.key, store: stores.blobs, monotonicNow: clock });
  return { journal, system, rebuilt: true };
}

/** Browser entry point: offline-profile owner + IndexedDB stores. */
export async function openBrowserDeviceAiJournal(): Promise<OpenedDeviceAiJournal> {
  const summary = await browserOfflineOwnerSummary();
  return openDeviceAiJournal(deviceAiJournalOwner(summary), browserDeviceAiStores());
}
