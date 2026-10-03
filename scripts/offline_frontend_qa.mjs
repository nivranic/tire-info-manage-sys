// Round46 pure client validation/crypto/transport. No HTTP, database or model calls.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { loadOfflineTypeScript } from "./load_offline_typescript.mjs";
import { loadTypeScript } from "../packages/native-client/tests/load-typescript.mjs";
const values = await loadOfflineTypeScript("../apps/web/components/offline-values.ts", import.meta.url);
const cryptoValues = await loadOfflineTypeScript("../apps/web/components/offline-crypto.ts", import.meta.url);
const native = await loadTypeScript("../packages/native-client/src/index.ts", import.meta.url);
const mobile = await loadTypeScript("../apps/mobile/src/native-platform.ts", import.meta.url);
const sdk = await loadTypeScript("../packages/api-client/src/index.ts", import.meta.url);
const selection = await loadTypeScript("../apps/web/components/recall-evidence-values.ts", import.meta.url);
const bytes = new Uint8Array(await readFile(new URL("../.artifacts/of46-wire-v2/valid-envelope.json", import.meta.url)));
const descriptor = JSON.parse(await readFile(new URL("../.artifacts/of46-wire-v2/valid-descriptor.json", import.meta.url), "utf8"));
const envelope = await values.validateOfflineBytes(bytes, descriptor);
const slot = { slot_id: "c58a0a6b-2c34-4bc4-8f8e-19d8a51f7ec9", generation: 1, package_id: descriptor.id,
  sha256: descriptor.sha256, byte_count: descriptor.byte_count, title: "合成设备历史", created_at: descriptor.content_created_at,
  installed_at: "2026-10-01T00:00:00Z", privacy_class: descriptor.privacy_class, owner_scope_id: descriptor.owner_scope_id,
  locked: false, previous_owner: false, counts: descriptor.counts };
const install = { package_id: descriptor.id, expected_sha256: descriptor.sha256, expected_byte_count: descriptor.byte_count,
  approved_plan_fingerprint: descriptor.plan_fingerprint, slot_id: slot.slot_id, expected_generation: 0, allow_device_storage: true };
async function changed(mutate) {
  const data = structuredClone(envelope); mutate(data);
  const body = new TextEncoder().encode(JSON.stringify(data));
  return values.validateOfflineBytes(body, { ...descriptor, byte_count: body.length, sha256: await cryptoValues.offlineSha256(body) });
}

test("actual four-domain producer bytes, personal contexts and per-record documents validate", () => {
  assert.equal(envelope.members.length, 5); assert.equal(envelope.documents.length, 9);
  assert.equal(envelope.contexts.find(row => row.kind === "garage").scope, "local_workspace");
  assert.equal(envelope.contexts.find(row => row.kind === "watchlist").scope, "current_session");
  const recalls = envelope.members.filter(row => row.reference.kind === "recall");
  assert.equal(recalls.length, 2); assert.ok(recalls.some(row => row.reference.recall_revision_id === null));
  assert.ok(recalls.every(row => row.payload.boundary.applicability === "not_assessed"));
});

test("original bytes are hashed before parsing; whitespace is not silently canonicalized", async () => {
  const altered = new Uint8Array([...bytes, 32]);
  await assert.rejects(values.validateOfflineBytes(altered, descriptor), { code: "OFFLINE_HASH_MISMATCH" });
  const pretty = new TextEncoder().encode(JSON.stringify(envelope, null, 2));
  assert.equal((await values.validateOfflineBytes(pretty, { ...descriptor, byte_count: pretty.length, sha256: await cryptoValues.offlineSha256(pretty) })).package_id, descriptor.id);
});

test("repeated input selectors retain approved raw scope without consuming distinct evidence or context capacity", async () => {
  const parsed = await changed(data => {
    data.scope.references = Array.from({ length: 201 }, () => data.members[0].reference);
    data.scope.garage.vehicle_ids = Array.from({ length: 51 }, () => data.contexts.find(row => row.kind === "garage").payload.vehicle_id);
    data.scope.watchlist.item_ids = Array.from({ length: 101 }, () => data.contexts.find(row => row.kind === "watchlist").payload.item_id);
  });
  assert.equal(parsed.scope.references.length, 201); assert.equal(parsed.scope.garage.vehicle_ids.length, 51);
  assert.equal(parsed.members.length, 5); assert.equal(parsed.contexts.length, 2);
  await assert.rejects(changed(data => { data.scope.references = Array.from({ length: 1001 }, () => data.members[0].reference); }), { code: "OFFLINE_INVALID_PACK" });
});

test("strict JSON rejects duplicate keys, BOM, invalid UTF-8, malformed numbers and excessive nesting", () => {
  for (const input of ['{"a":1,"a":2}', '{"a":{"x":1,"x":2}}', '[1,]', '{"x":1e400}', '{"x":"\\ud800"}', '['.repeat(66)+'0'+']'.repeat(66)]) {
    assert.throws(() => cryptoValues.parseOfflineJson(new TextEncoder().encode(input)), { code: "OFFLINE_INVALID_PACK" });
  }
  assert.throws(() => cryptoValues.parseOfflineJson(new Uint8Array([0xef, 0xbb, 0xbf, 123, 125])), { code: "OFFLINE_INVALID_PACK" });
  assert.throws(() => cryptoValues.parseOfflineJson(new Uint8Array([0xc3, 0x28])), { code: "OFFLINE_INVALID_PACK" });
  assert.deepEqual(cryptoValues.parseOfflineJson(new TextEncoder().encode('{"emoji":"🚗","text":"<script>never execute</script>"}')), { emoji: "🚗", text: "<script>never execute</script>" });
});

test("rehashed malformed packages cannot cross scope, verification, document or recall record boundaries", async () => {
  const changes = [
    data => { data.unknown = true; },
    data => { data.members[0].source.body = "unapproved raw"; },
    data => { data.members.find(row => row.reference.kind === "tire").reference.verification_id = undefined; },
    data => { data.contexts[0].evidence_keys = ["f".repeat(64)]; },
    data => { data.contexts.find(row => row.kind === "watchlist").scope = "local_workspace"; },
    data => { data.contexts.find(row => row.kind === "garage").payload.profile.raw_body = "not approved"; },
    data => { data.documents[0].context_id = "missing"; },
    data => { data.documents.push(data.documents[0]); },
    data => { data.documents.find(row => row.kind === "recall" && row.record_index === 0).facets.model = "Model B"; },
    data => { data.members.find(row => row.reference.kind === "recall" && row.payload.records.length).payload.records[0].applicability = "safe"; },
    data => { data.members.find(row => row.reference.kind === "recall" && !row.payload.records.length).reference.recall_revision_id = "old-nonempty"; },
  ];
  for (const mutate of changes) await assert.rejects(changed(mutate), { code: "OFFLINE_INVALID_PACK" });
});

test("device search never combines two product records and stale generations cannot read a replacement", () => {
  const request = { slot_id: slot.slot_id, expected_generation: 1, kind: "recall", query: "Brand A Model A", offset: 0, limit: 20 };
  assert.equal(values.searchOfflineEnvelope(envelope, slot, request).total, 1);
  assert.equal(values.searchOfflineEnvelope(envelope, slot, { ...request, query: "Brand A Model B" }).total, 0);
  assert.throws(() => values.searchOfflineEnvelope(envelope, slot, { ...request, offset: 4001 }), { code: "OFFLINE_INVALID_REQUEST" });
  assert.throws(() => values.searchOfflineEnvelope(envelope, slot, { ...request, kind: "unknown" }), { code: "OFFLINE_INVALID_REQUEST" });
  const empty = values.searchOfflineEnvelope(envelope, slot, { ...request, query: "", kind: "garage" });
  assert.equal(empty.total, 1);
  const detail = values.readOfflineEnvelope(envelope, slot, { slot_id: slot.slot_id, expected_generation: 1, document_id: empty.items[0].id });
  assert.equal(detail.member, null); assert.equal(detail.context.kind, "garage");
  assert.throws(() => values.readOfflineEnvelope(envelope, { ...slot, generation: 2 }, { slot_id: slot.slot_id, expected_generation: 1, document_id: empty.items[0].id }), { code: "OFFLINE_SLOT_CONFLICT" });
});

test("non-exportable AES-GCM key encrypts original bytes and rejects changed slot/version bindings", async () => {
  const key = await cryptoValues.newOfflineKey();
  assert.equal(key.extractable, false);
  await assert.rejects(crypto.subtle.exportKey("raw", key));
  const encrypted = await cryptoValues.sealOfflineBytes(key, bytes, "profile:slot:1:payload");
  assert.equal(Buffer.from(encrypted.ciphertext).includes(Buffer.from("合成车库车辆")), false);
  assert.deepEqual(await cryptoValues.openOfflineBytes(key, encrypted, "profile:slot:1:payload"), bytes);
  await assert.rejects(cryptoValues.openOfflineBytes(key, encrypted, "profile:slot:2:payload"), { code: "OFFLINE_CORRUPT" });
  const changed = encrypted.ciphertext.slice(0); new Uint8Array(changed)[0] ^= 1;
  await assert.rejects(cryptoValues.openOfflineBytes(key, { ...encrypted, ciphertext: changed }, "profile:slot:1:payload"), { code: "OFFLINE_CORRUPT" });
});

test("bounded response download rejects size/hash headers and never accepts oversize content", async () => {
  const headers = { "Content-Type": "application/json", "Content-Length": String(bytes.length), "X-Content-SHA256": descriptor.sha256 };
  assert.deepEqual(await values.readOfflineResponse(new Response(bytes, { headers }), descriptor), bytes);
  await assert.rejects(values.readOfflineResponse(new Response(bytes, { headers: { ...headers, "Content-Length": "1" } }), descriptor), { code: "OFFLINE_HASH_MISMATCH" });
  await assert.rejects(values.readOfflineResponse(new Response(new Uint8Array(bytes.length + 1), { headers }), descriptor), { code: "OFFLINE_TOO_LARGE" });
});

test("native offline RPC uses fixed typed commands without browser HTTP or body/path/url install arguments", async () => {
  const originalFetch = globalThis.fetch, calls = [];
  globalThis.fetch = () => assert.fail("offline native read must not call browser HTTP");
  try {
    const storage = native.createNativeOfflineStorage(async (command, args) => { calls.push({ command, args }); return command === "offline_list" ? { items: [slot] } : slot; });
    await storage.status(); await storage.list(); await storage.install(install);
    await storage.search({ slot_id: slot.slot_id, expected_generation: 1, query: "Brand A", offset: 0, limit: 20 });
    await storage.read({ slot_id: slot.slot_id, expected_generation: 1, document_id: envelope.documents[0].id });
    await storage.remove({ slot_id: slot.slot_id, expected_generation: 1 });
    await storage.unlockPreviousOwner({ slot_id: slot.slot_id, expected_generation: 1, allow_previous_owner: true });
    assert.deepEqual(calls.map(row => row.command), ["offline_status", "offline_list", "offline_install", "offline_search", "offline_read", "offline_remove", "offline_unlock_previous_owner"]);
    assert.deepEqual(calls[2].args, { request: install });
    assert.ok(!["url", "path", "body_base64", "bytes"].some(name => name in calls[2].args.request));
  } finally { globalThis.fetch = originalFetch; }
});

test("Android camel RPC mapping preserves offline error code instead of misclassifying it as a session failure", async () => {
  const calls = [], plugin = Object.fromEntries(["offlineStatus", "offlineList", "offlineInstall", "offlineSearch", "offlineRead", "offlineRemove", "offlineUnlockPreviousOwner"].map(name => [name, async args => { calls.push({ name, args }); return slot; }]));
  const invoke = mobile.createMobileInvoke(plugin), storage = native.createNativeOfflineStorage(invoke);
  await storage.install(install); await storage.unlockPreviousOwner({ slot_id: slot.slot_id, expected_generation: 1, allow_previous_owner: true });
  assert.equal(calls[0].name, "offlineInstall"); assert.deepEqual(calls[0].args, { request: install });
  assert.equal(calls[1].name, "offlineUnlockPreviousOwner");
  plugin.offlineRead = async () => { throw { code: "OFFLINE_LOCKED" }; };
  await assert.rejects(storage.read({ slot_id: slot.slot_id, expected_generation: 1, document_id: "member:x" }), { code: "OFFLINE_LOCKED" });
  plugin.offlineInstall = async () => { throw { code: "API_UNAVAILABLE" }; };
  await assert.rejects(storage.install(install), { code: "API_UNAVAILABLE" });
  assert.match(cryptoValues.offlineError({ code: "OFFLINE_PACK_CORRUPT" }).message, /完整性检查/);
  assert.match(cryptoValues.offlineError({ code: "API_UNAVAILABLE" }).message, /已有设备历史仍可查看/);
});

test("device selection accepts seven distinct references while AI keeps six and the offline cap remains 200", () => {
  const refs = Array.from({ length: 200 }, (_, index) => ({ kind: "test_event", event_id: `event-${index}`, event_revision: 1 }));
  assert.equal(selection.canSelectKnowledgeReference(refs.slice(0, 6), refs[6]), false);
  assert.equal(selection.canSelectKnowledgeReference(refs.slice(0, 6), refs[6], 200), true);
  assert.equal(selection.canSelectKnowledgeReference(refs, { kind: "test_event", event_id: "extra", event_revision: 1 }, 200), false);
  assert.equal(selection.canSelectKnowledgeReference(refs, refs[0], 200), true);
});

test("offline plan SDK retains default scopes and more than six explicit references; confirm consent is separate", async () => {
  const originalFetch = globalThis.fetch, calls = [];
  globalThis.fetch = async (path, init) => { calls.push({ path, body: init.body ? JSON.parse(init.body) : null, headers: Object.fromEntries(init.headers) }); return new Response(JSON.stringify(descriptor)); };
  try {
    const scope = values.defaultOfflineScope(); scope.references = Array.from({ length: 7 }, () => envelope.members.find(row => row.reference.kind === "tire").reference);
    await sdk.tireApi.offlinePlan({ mode: "history", scope, base_pack_id: null });
    await sdk.tireApi.confirmOfflinePack({ plan_id: descriptor.plan_id, expected_fingerprint: descriptor.plan_fingerprint, allow_device_storage: true }, "3591a79d-bc61-4b7d-a420-65038723c02c");
    assert.equal(calls[0].body.scope.references.length, 7); assert.equal(calls[0].body.scope.garage.include, true); assert.equal(calls[0].body.scope.recent.limit, 20);
    assert.ok(calls[1].body.allow_device_storage); assert.equal("allow_external_processing" in calls[1].body, false);
    assert.ok(calls.every(row => !row.path.includes("live-query") && !row.path.includes("ai/")));
  } finally { globalThis.fetch = originalFetch; }
});
