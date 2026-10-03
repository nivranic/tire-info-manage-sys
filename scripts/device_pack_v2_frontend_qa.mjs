import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { loadOfflineTypeScript } from "./load_offline_typescript.mjs";
const values = await loadOfflineTypeScript("../apps/web/components/offline-values.ts", import.meta.url);
const api = await loadOfflineTypeScript("../packages/api-client/src/index.ts", import.meta.url);
const native = await loadOfflineTypeScript("../packages/native-client/src/index.ts", import.meta.url);
const base = new URL("../.artifacts/query-fallback49/producer-v2-samples-a/", import.meta.url);
const source = async name => { const bytes = new Uint8Array(await readFile(new URL(name + "-pack.json", base))), descriptor = JSON.parse(await readFile(new URL(name + "-descriptor.json", base), "utf8")); return { bytes, descriptor }; };
const slotId = "00000000-0000-4000-8000-000000000049", profileId = "00000000-0000-4000-8000-000000000050";
test("frozen actual @2 producer original bytes preserve all members, record pages and exact numeric facts", async () => {
  for (const name of ["nonempty", "empty"]) {
    const { bytes, descriptor } = await source(name), pack = await values.validateOfflineBytes(bytes, descriptor);
    assert.equal(pack.schema, "offline-pack@2"); assert.equal(pack.members.length, descriptor.counts.distinct_evidence);
    const tire = pack.members.find(member => member.reference.kind === "tire");
    assert.equal(tire.payload.variant.facts.reference_int.token, "9007199254740993"); assert.equal(tire.payload.variant.facts.reference_float.token, "1.0"); assert.equal(tire.payload.variant.facts.reference_tiny.token, "5e-324");
    const member = pack.members.find(member => member.reference.kind === "recall_search"); assert.equal(member.payload.empty_observation, name === "empty");
    assert.deepEqual(Object.keys(member.payload.evidence).sort(), ["snapshot_id", "query_id", "verification_id", "data_state", "observed_at", "verified_at"].sort());
  }
});
test("rehashed unknown versions, injected @1 discovery and malformed discovery boundaries fail closed", async () => {
  const original = await source("nonempty");
  for (const change of [pack => pack.schema = "offline-pack@3", pack => pack.members.find(member => member.reference.kind === "recall_search").payload.boundary.formal_campaign_revision = true, pack => pack.members.find(member => member.reference.kind === "recall_search").payload.query.offset = "00", pack => pack.members.find(member => member.reference.kind === "recall_search").payload.evidence.extra = "x"]) {
    const pack = api.parseExactJson(original.bytes); change(pack); const bytes = new TextEncoder().encode(api.stringifyExactJson(pack));
    const descriptor = { ...original.descriptor, sha256: await crypto.subtle.digest("SHA-256", bytes).then(value => Buffer.from(value).toString("hex")), byte_count: bytes.length };
    await assert.rejects(values.validateOfflineBytes(bytes, descriptor));
  }
  await assert.rejects(values.validateOfflineBytes(original.bytes, { ...original.descriptor, schema: "offline-pack-descriptor@1" }));
});
test("manual native @2 read core uses mandatory exact transport and original safe indices", async () => {
  const original = await source("nonempty"), pack = await values.validateOfflineBytes(original.bytes, original.descriptor), member = pack.members.find(member => member.reference.kind === "tire"), document = pack.documents.find(document => document.member_key === member.key);
  const slot = { slot_id: slotId, generation: 1, package_id: original.descriptor.id, sha256: original.descriptor.sha256, byte_count: original.bytes.length, title: "fixture", created_at: pack.created_at, installed_at: pack.created_at, owner_scope_id: pack.owner_scope_id, locked: false, previous_owner: false, counts: original.descriptor.counts, privacy_class: "private" };
  const request = { slot_id: slotId, expected_generation: 1, document_id: document.id }, core = values.readOfflineEnvelope(pack, slot, request);
  assert.equal(core.schema, "offline-read-result@2"); const wire = JSON.parse(JSON.stringify(api.encodeExactDeviceFallbackWire(core)));
  assert.equal(wire.member.payload.variant.facts.reference_int, 9007199254740992);
  const storage = native.createNativeOfflineStorage(async command => { assert.equal(command, "offline_read"); return wire; });
  const read = await storage.read(request); assert.equal(read.member.payload.variant.facts.reference_int.token, "9007199254740993");
  wire.member.payload.variant.facts.reference_int = "9007199254740993"; await assert.rejects(storage.read(request));
});
test("all four intent branches and exact large criterion cross mandatory native request codec", async () => {
  const authority = { runtime_session_id: profileId, authority_revision: 1 }, failure = { scope: "api_transport", reason: "api_network_unavailable", query_id: null };
  for (const [kind, query] of [["tire", { size: "265/40ZR20" }], ["vehicle_fitments", { vehicle_id: slotId }], ["recall_campaign", { campaign_number: "23T001000" }], ["recall_search", { search: "SYNTHETIC DEMO", offset: "0" }]]) {
    const filters = kind === "tire" ? api.canonicalDeviceFilters(api.parseExactJson('[{"field":"utqg_treadwear","op":"gte","value":9007199254740993}]')) : [];
    const intent = await api.createDeviceFallbackIntent(kind, query, filters, "fixture", 0, failure, crypto.randomUUID(), authority);
    const request = { intent, slot_id: slotId, expected_generation: 1, expected_sha256: "a".repeat(64), expected_profile_id: profileId, expected_owner_epoch: 0, decision: "deny" };
    const storage = native.createNativeOfflineStorage(async (command, args) => {
      assert.equal(command, "offline_fallback_decide"); assert.equal(typeof args.request.raw_json, "string"); const exact = api.decodeExactDeviceFallbackWire(args.request).core; assert.equal(api.deviceIntentKey(exact.intent), api.deviceIntentKey(intent));
      const now = Date.now(); return JSON.parse(JSON.stringify(api.encodeExactDeviceFallbackWire({ schema: "device-fallback-grant@2", id: crypto.randomUUID(), scope: "local_once", state: "denied", fallback_authorization: { type: "explicit_once" }, intent, profile_id: profileId, owner_epoch: 0, slot_id: slotId, generation: 1, package_sha256: "a".repeat(64), decided_at: new Date(now).toISOString(), expires_at: new Date(now + 300000).toISOString(), consumed_at: null })));
    });
    assert.equal((await storage.decideFallbackV2(request)).state, "denied");
  }
});
test("discovery nullable size and positive arbitrary integer business ids remain exact", async () => {
  const original = await source("nonempty"), pack = api.parseExactJson(original.bytes), member = pack.members.find(member => member.reference.kind === "recall_search"), product = member.payload.discovery.products[0];
  product.size = null; product.id = new api.ExactJsonNumber("9007199254740993"); product.artemis_id = new api.ExactJsonNumber("1" + "0".repeat(400));
  pack.documents.find(document => document.member_key === member.key && document.record_index.token === "0").facets.size = null;
  const bytes = new TextEncoder().encode(api.stringifyExactJson(pack)), descriptor = { ...original.descriptor, byte_count: bytes.length, sha256: Buffer.from(await crypto.subtle.digest("SHA-256", bytes)).toString("hex") }, validated = await values.validateOfflineBytes(bytes, descriptor);
  const actual = validated.members.find(member => member.reference.kind === "recall_search").payload.discovery.products[0];
  assert.equal(actual.size, null); assert.equal(actual.id.token, "9007199254740993"); assert.equal(actual.artemis_id.token, "1" + "0".repeat(400));
  assert.equal(api.projectExactJson(actual).artemis_id, null);
});
