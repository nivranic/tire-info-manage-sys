// Round48 pure contracts and fixed history-only transport; no network or database.
import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { loadOfflineTypeScript } from "./load_offline_typescript.mjs";
import { loadTypeScript } from "../packages/native-client/tests/load-typescript.mjs";
const values = await loadOfflineTypeScript("../apps/web/components/device-sync-values.ts", import.meta.url);
const sdk = await loadOfflineTypeScript("../packages/api-client/src/index.ts", import.meta.url);
const native = await loadTypeScript("../packages/native-client/src/index.ts", import.meta.url);
const mobile = await loadTypeScript("../apps/mobile/src/native-platform.ts", import.meta.url);
const id = "123e4567-e89b-42d3-a456-426614174000", owner = "a".repeat(64), sha = "b".repeat(64);
const capabilities = { schema: "device-sync-capabilities@1", scheduler: "page_open", wifi: false, external_power: false,
  battery_charging: false, min_interval_seconds: 900, max_interval_seconds: 604800, host_build: "d".repeat(64), validator_version: "offline-validator@2" };
const scope = { garage: { include: true, vehicle_ids: null }, watchlist: { include: true, item_ids: null }, recent: { include: true, limit: 20 }, references: [] };
const counts = { garage_profiles: 0, watch_items: 0, recent_queries: 0, distinct_evidence: 0, searchable_documents: 0 };
const descriptor = { schema: "offline-pack-descriptor@1", id, plan_id: id, created_at: "2026-10-01T00:00:00Z", content_created_at: "2026-10-01T00:00:00Z",
  plan_fingerprint: sha, owner_scope_id: owner, privacy_class: "private", sha256: sha, byte_count: 64, base_pack_id: null, counts,
  download_path: `/v1/offline-packs/${id}/download?mode=history`, data_state: "local_snapshot", source_refresh_performed: false };
const slot = { slot_id: id, generation: 1, package_id: id, sha256: sha, byte_count: 64 };
const policy = { binding: { package_id: id, sha256: sha }, owner_scope_id: owner, scope, capacity: values.DEVICE_SYNC_CAPACITY };
const request = { slot_id: id, expected_generation: 1, expected_profile_id: id, expected_owner_epoch: 1, interval_seconds: 900,
  conditions: { network: "any", power: "any" } };

test("conditions are strict AND; unknown and unsupported never grant execution", () => {
  const observations = { network_available: true, wifi: true, external_power: true, battery_charging: true };
  assert.equal(values.syncConditionsSatisfied(request.conditions, capabilities, observations), true);
  for (const unknown of [false, null, undefined]) assert.equal(values.syncConditionsSatisfied(request.conditions, capabilities, { ...observations, network_available: unknown }), false);
  for (const condition of [{ network: "wifi", power: "any" }, { network: "any", power: "external_power" }, { network: "any", power: "battery_charging" }]) {
    assert.equal(values.syncConditionsSatisfied(condition, capabilities, observations), false);
    assert.throws(() => values.validateSyncPreviewRequest({ ...request, conditions: condition }, capabilities), { code: "OFFLINE_SYNC_UNSUPPORTED" });
  }
  const native = { ...capabilities, scheduler: "os_background", wifi: true, external_power: true, battery_charging: true };
  for (const field of ["network_available", "wifi", "battery_charging"]) assert.equal(values.syncConditionsSatisfied({ network: "wifi", power: "battery_charging" }, native, { ...observations, [field]: null }), false);
  assert.equal(values.syncConditionsSatisfied({ network: "wifi", power: "battery_charging" }, native, { ...observations, external_power: false }), true);
});
test("preview rejects arbitrary URL/scope, intervals, one-time consent and stale identity shapes", () => {
  values.validateSyncPreviewRequest(request, capabilities);
  for (const change of [{ api_url: "https://example.test" }, { scope }, { allow_device_storage: true }, { interval_seconds: 899 }, { interval_seconds: 900.1 },
    { expected_generation: 0 }, { expected_owner_epoch: 0 }, { expected_profile_id: "wrong" }, { conditions: { network: "any", power: "any", or: true } }])
    assert.throws(() => values.validateSyncPreviewRequest({ ...request, ...change }, capabilities), { code: "OFFLINE_SYNC_INVALID" });
});
test("dynamic selectors persist; distinct explicit keys pin exact resolved verification receipts", () => {
  const evidence = verification => ({ key: verification, reference: { kind: "tire", snapshot_id: "same", variant_id: "same", verification_id: verification }, member_reasons: [{ selector: "explicit" }] });
  const envelope = { scope: { ...scope, references: [{ kind: "tire", snapshot_id: "same", variant_id: "same" }] }, members: [evidence("receipt-a"), evidence("receipt-b"), { ...evidence("garage-only"), member_reasons: [{ selector: "garage" }] }] };
  const derived = values.deriveDeviceSyncScope(envelope);
  assert.equal(derived.garage.vehicle_ids, null); assert.equal(derived.watchlist.item_ids, null); assert.equal(derived.recent.limit, 20);
  assert.deepEqual(derived.references.map(ref => ref.verification_id), ["receipt-a", "receipt-b"]);
  derived.references[0].verification_id = "changed"; assert.equal(envelope.members[0].reference.verification_id, "receipt-a");
});
test("semantic digest excludes only four top-level nonce fields and preserves nested changes and order", async () => {
  const envelope = { schema: "offline-pack@1", package_id: id, created_at: "one", plan_fingerprint: sha, base_pack_id: null,
    scope, members: [{ observed_at: "one", record: "🚗" }], contexts: [{ revision: 1 }], documents: [1, 2], omissions: [], contracts: { policy: 1 } };
  const digest = await values.deviceSyncSemanticDigest(envelope);
  assert.equal(await values.deviceSyncSemanticDigest({ ...envelope, package_id: "two", created_at: "two", plan_fingerprint: "two", base_pack_id: "two" }), digest);
  for (const changed of [{ members: [{ observed_at: "two" }] }, { contexts: [{ revision: 2 }] }, { documents: [2, 1] }, { omissions: [{ reason: "changed" }] }, { contracts: { policy: 2 } }, { scope: { ...scope, recent: { include: false, limit: 20 } } }])
    assert.notEqual(await values.deviceSyncSemanticDigest({ ...envelope, ...changed }), digest);
  assert.equal(values.stableSyncJson({ "🚗": 1, "\ue000": 2 }), '{"":2,"🚗":1}');
});
test("original-byte semantic gate preserves producer float numeric tokens", async () => {
  const bytes = new TextEncoder().encode('{"created_at":"nonce","package_id":"nonce","x":1.0,"nested":{"a":-0.0,"b":1e+2}}');
  const canonical = '{"envelope":{"nested":{"a":-0.0,"b":1e+2},"x":1.0},"namespace":"offline-semantic@1"}';
  assert.equal(await values.deviceSyncSemanticDigestFromBytes(bytes), createHash("sha256").update(canonical).digest("hex"));
  assert.notEqual(await values.deviceSyncSemanticDigestFromBytes(bytes), await values.deviceSyncSemanticDigest(JSON.parse(new TextDecoder().decode(bytes))));
});
test("no_change validates full base descriptor and matching digests; planned validates complete scope and capacity", () => {
  const response = { schema: "offline-pack-update@1", state: "no_change", mode: "history", base_pack_id: id,
    base_semantic_digest: sha, current_semantic_digest: sha, base_pack: descriptor, plan: null, source_refresh_performed: false };
  assert.equal(values.validateSyncUpdate(response, policy, slot, descriptor).state, "no_change");
  for (const change of [{ current_semantic_digest: owner }, { plan: {} }, { mode: "live" }, { source_refresh_performed: true }, { base_pack: { ...descriptor, counts: { ...counts, garage_profiles: 1 } } }, { extra: true }])
    assert.throws(() => values.validateSyncUpdate({ ...response, ...change }, policy, slot, descriptor));
  const plan = { schema: "offline-pack-plan@1", id, package_id: id, fingerprint: sha, content_sha256: sha, owner_scope_id: owner,
    base_pack_id: id, requested_scope: scope, capacity: policy.capacity, state: "ready", can_confirm: true, measured_bytes: 64,
    expires_at: new Date(Date.now() + 600000).toISOString(), resolved: [], contexts: [], documents: [], omissions: [], counts };
  assert.equal(values.validateSyncUpdate({ ...response, state: "planned", current_semantic_digest: owner, plan }, policy, slot, descriptor).state, "planned");
  for (const change of [{ capacity: { ...policy.capacity, max_package_bytes: 999999999 } }, { requested_scope: { ...scope, references: [{ kind: "test_event", event_id: "changed", event_revision: 1 }] } },
    { measured_bytes: policy.capacity.max_package_bytes + 1 }, { counts: { ...counts, searchable_documents: 1 } }, { omissions: [{ blocking: true }] }])
    assert.throws(() => values.validateSyncUpdate({ ...response, state: "planned", current_semantic_digest: owner, plan: { ...plan, ...change } }, policy, slot, descriptor));
});
test("native sync uses only independent fixed IPC, including mobile plugin mapping", async () => {
  const calls = [], plugin = Object.fromEntries(["Status", "Preview", "Apply", "Pause", "Revoke", "Run", "Revalidate"].map(name => [`offlineSync${name}`, async args => { calls.push([name, args]); return {}; }]));
  const storage = native.createNativeOfflineStorage(mobile.createMobileInvoke(plugin));
  await storage.syncStatus(); await storage.previewSyncPolicy(request); await storage.applySyncPolicy({ preview_id: id });
  await storage.pauseSyncPolicy({ policy_id: id }); await storage.revokeSyncPolicy({ policy_id: id }); await storage.runSyncPolicy({ policy_id: id }); await storage.revalidateSync();
  assert.deepEqual(calls.map(call => call[0]), ["Status", "Preview", "Apply", "Pause", "Revoke", "Run", "Revalidate"]);
  assert.equal(calls[1][1].request, request); assert.equal(calls[0][1], undefined);
});
test("sync SDK fixes owner fence headers on all history-only paths and rejects observed authority changes", async () => {
  const calls = [], restore = sdk.setApiTransport(async (path, init) => {
    calls.push({ path, init }); return new Response(JSON.stringify(descriptor), { headers: { "X-Tire-Offline-Owner-Scope": owner } });
  });
  try {
    const epoch = sdk.apiTransportAuthorityEpoch();
    await sdk.tireApi.offlineSyncPrepare({ mode: "history", base_pack_id: id, expected_base_sha256: sha, scope }, owner);
    await sdk.tireApi.offlineSyncConfirm({ plan_id: id, expected_fingerprint: sha, allow_device_storage: true }, id, owner);
    await sdk.tireApi.offlineSyncPack(id, owner); await sdk.tireApi.offlineSyncBytes(id, owner);
    assert.equal(sdk.apiTransportAuthorityEpoch(), epoch);
    assert.deepEqual(calls.map(call => call.path), ["/v1/offline-pack-updates:prepare", "/v1/offline-packs", `/v1/offline-packs/${id}?mode=history`, `/v1/offline-packs/${id}/download?mode=history`]);
    for (const call of calls) { assert.equal(call.init.headers.get("X-Tire-Offline-Sync"), "1"); assert.equal(call.init.headers.get("X-Tire-Offline-Expected-Owner"), owner); assert.equal(call.init.cache, "no-store"); }
    assert.equal(calls[1].init.headers.get("Idempotency-Key"), id);
    assert.throws(() => sdk.tireApi.offlineSyncPack(id, "invalid"), { code: "OFFLINE_SYNC_INVALID" });
  } finally { restore(); }
  const restoreBad = sdk.setApiTransport(async () => new Response("{}", { headers: { "X-Tire-Offline-Owner-Scope": "c".repeat(64) } }));
  try { await assert.rejects(sdk.tireApi.offlineSyncPack(id, owner), { code: "SESSION_CHANGED" }); } finally { restoreBad(); }
});
