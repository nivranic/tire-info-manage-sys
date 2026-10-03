// Round50 P1-3 web host frontend contracts: projection-port parity against the
// sealed authoritative vectors, journal persistence flow, policy fingerprint
// mirror. Pure Node: no browser, no database, no network, no model calls.
import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { loadTypeScript } from "../packages/native-client/tests/load-typescript.mjs";

const sdk = await loadTypeScript("../packages/api-client/src/device-ai-host.ts", import.meta.url);
const port = await loadTypeScript("../packages/api-client/src/device-ai-projection.ts", import.meta.url);
const webValues = await loadTypeScript("../apps/web/components/device-ai-values.ts", import.meta.url);
const browserHost = await loadTypeScript("../apps/web/components/browser-device-ai.ts", import.meta.url);

const ROOT = resolve(new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const VECTORS = resolve(ROOT, ".artifacts/device-ai50/projection-vectors-a");
const manifest = JSON.parse(readFileSync(resolve(VECTORS, "manifest.json"), "utf8"));

function vectorPack(binding) {
  for (const name of ["legacy-pack.json", "nonempty-pack.json", "empty-pack.json"]) {
    const bytes = readFileSync(resolve(VECTORS, "inputs", name));
    if (createHash("sha256").update(bytes).digest("hex") === binding.sha256) return new Uint8Array(bytes);
  }
  assert.fail("vector pack not found for binding");
}

test("projection port reproduces every sealed tire-single vector byte for byte", async () => {
  const cases = manifest.domain_vectors.filter(item => item.case.endsWith("tire-single") && item.expected_error_code === null);
  assert.ok(cases.length >= 3, `expected at least three tire-single vectors, got ${cases.length}`);
  for (const item of cases) {
    const input = JSON.parse(readFileSync(resolve(VECTORS, item.input.path), "utf8"));
    const expectation = JSON.parse(readFileSync(resolve(VECTORS, item.expectation.path), "utf8"));
    const canonical = readFileSync(resolve(VECTORS, expectation.canonical_projection.path), "utf8");
    const result = await port.projectDeviceAiSingleObservation(vectorPack(input.binding), input.binding, input.selectors);
    assert.equal(result.sha256, expectation.canonical_projection.sha256, `${item.case} sha256`);
    assert.equal(result.canonicalText, canonical, `${item.case} canonical bytes`);
    assert.equal(result.byteCount, expectation.canonical_projection.byte_count, `${item.case} byte count`);
    assert.equal(result.memberCount, expectation.member_count, `${item.case} member count`);
  }
});

test("projection port selection digest matches the SDK selection digest on the same selectors", async () => {
  const item = manifest.domain_vectors.find(entry => entry.case === "nonempty-tire-single");
  const input = JSON.parse(readFileSync(resolve(VECTORS, item.input.path), "utf8"));
  const result = await port.projectDeviceAiSingleObservation(vectorPack(input.binding), input.binding, input.selectors);
  assert.equal(result.selectionSha256, await sdk.selectionSha256(input.selectors));
});

test("projection port fails closed on receipt mismatch, mutated bytes and foreign selectors", async () => {
  const item = manifest.domain_vectors.find(entry => entry.case === "nonempty-tire-single");
  const input = JSON.parse(readFileSync(resolve(VECTORS, item.input.path), "utf8"));
  const bytes = vectorPack(input.binding);
  const foreign = structuredClone(input.selectors[0]);
  foreign.reference = { ...foreign.reference, snapshot_id: "00000000-0000-4000-8000-000000000000" };
  await assert.rejects(() => port.projectDeviceAiSingleObservation(bytes, input.binding, [foreign]),
    error => ["device_ai_member_missing", "device_ai_receipt_mismatch", "device_ai_material_invalid"].includes(error.code));
  const mutated = bytes.slice(); mutated[mutated.length - 2] ^= 1;
  await assert.rejects(() => port.projectDeviceAiSingleObservation(mutated, input.binding, input.selectors),
    { code: "device_ai_package_binding_mismatch" });
  await assert.rejects(() => port.projectDeviceAiSingleObservation(bytes, input.binding, []),
    { code: "device_ai_selector_capacity" });
});

// P1-4c: every open domain assembles a closed prepare body from a recomputed
// preview; expected_projection_sha256 is the on-device re-computation and
// equals the SEALED canonical vector sha for vehicle / recall / recall_search
// and the tire closure mode too.
test("four-domain prepare body assembly carries the sealed recomputed projection", async () => {
  const uuid = "11111111-2222-4333-8444-555555555555";
  const cases = manifest.domain_vectors.filter(item =>
    ["empty-tire-single", "empty-vehicle-complete", "empty-formal-recall-nonempty", "empty-recall-search-empty",
     "empty-tire-closure"].includes(item.case) && item.expected_error_code === null);
  assert.ok(cases.length === 5, `expected the five accepted domain vectors, got ${cases.length}`);
  for (const item of cases) {
    const input = JSON.parse(readFileSync(resolve(VECTORS, item.input.path), "utf8"));
    const expectation = JSON.parse(readFileSync(resolve(VECTORS, item.expectation.path), "utf8"));
    const origin = {
      expected_profile_id: uuid, expected_owner_epoch: 1, slot_id: "slot-1", expected_generation: 2,
      package_id: input.binding.package_id, expected_sha256: input.binding.sha256,
      expected_byte_count: input.binding.byte_count, owner_scope_id: input.binding.owner_scope_id,
      package_schema: input.binding.schema,
    };
    const closureMode = input.mode === "frozen_decision_closure";
    const summary = await sdk.computeLocalPreview(vectorPack(input.binding), {
      question: "四域包的设备历史如何解读？", selectors: input.selectors, origin,
      projectionMode: input.mode, approvedClosure: closureMode ? input.selectors : null,
    });
    const body = sdk.buildDeviceAiPrepareBody({
      origin, preview: summary, selectors: input.selectors,
      approvedClosure: closureMode ? input.selectors : null, hostReceiptId: uuid, intentId: uuid,
    });
    assert.deepEqual(Object.keys(body).sort(), [...sdk.DEVICE_AI_PREPARE_REQUEST_FIELDS].sort(), `${item.case} closed field set`);
    assert.equal(body.expected_projection_sha256, expectation.canonical_projection.sha256, `${item.case} sealed projection sha`);
    assert.equal(body.projection_mode, input.mode, `${item.case} mode echoed`);
    assert.equal(body.question_sha256, summary.question_sha256, `${item.case} question echo`);
    if (closureMode) {
      assert.ok(Array.isArray(body.approved_closure) && body.approved_closure.length === summary.resolved_closure_member_keys.length,
        `${item.case} approved closure carried`);
    } else {
      assert.equal(body.approved_closure, null, `${item.case} approved closure null`);
    }
  }
  // fail-closed: closure drift and out-of-mode approved closures never dispatch.
  const item = manifest.domain_vectors.find(entry => entry.case === "empty-tire-single");
  const input = JSON.parse(readFileSync(resolve(VECTORS, item.input.path), "utf8"));
  const origin = {
    expected_profile_id: uuid, expected_owner_epoch: 1, slot_id: "slot-1", expected_generation: 2,
    package_id: input.binding.package_id, expected_sha256: input.binding.sha256,
    expected_byte_count: input.binding.byte_count, owner_scope_id: input.binding.owner_scope_id,
    package_schema: input.binding.schema,
  };
  const summary = await sdk.computeLocalPreview(vectorPack(input.binding), {
    question: "四域包的设备历史如何解读？", selectors: input.selectors, origin,
    projectionMode: input.mode, approvedClosure: null,
  });
  assert.throws(() => sdk.buildDeviceAiPrepareBody({
    origin, preview: summary, selectors: input.selectors, approvedClosure: input.selectors, hostReceiptId: uuid, intentId: uuid,
  }), { code: "device_ai_host_invalid_argument" }, "approved_closure outside closure mode rejected");
  assert.throws(() => sdk.assertDeviceAiPrepareBody({
    package_id: "pkg-1", expected_sha256: "ef".repeat(32), expected_byte_count: 1,
    expected_schema: "offline-pack@2", expected_owner_scope_id: "9a".repeat(32),
    selectors: [{ kind: "test_event", member_key: "0c".repeat(32), document_id: null, record_index: null,
      reference: { kind: "test_event", event_id: "evt-1", event_revision: 1 } }],
    projection_mode: "complete_event_context", approved_closure: null,
    expected_projection_sha256: "99".repeat(32), question_sha256: "01".repeat(32),
    host_receipt_id: uuid, intent_id: uuid,
  }), { code: "device_ai_host_invalid_argument" }, "test_event stays closed on the prepare wire (N27)");
});

test("panel domain and mode labels cover the four open domains", () => {
  assert.deepEqual(webValues.deviceAiDomainLabels, { tire: "轮胎", vehicle: "车辆", recall: "召回公告", recall_search: "公告检索" });
  assert.equal(webValues.deviceAiDomainLabel("vehicle"), "车辆");
  assert.equal(webValues.deviceAiDomainLabel("test_event"), "测试事件（受限）");
  assert.equal(webValues.deviceAiProjectionModeLabel("frozen_decision_closure"), "冻结决定闭包");
  assert.equal(webValues.deviceAiProjectionModeLabel("candidate_page_context"), "候选检索页上下文");
  assert.equal(webValues.deviceAiHostErrorMessage(new Error("device_ai_closure_consent_required")),
    "冻结决定闭包与所选集合不一致：依赖展开改变了闭包，请调整所选成员后重试。");
  assert.match(webValues.deviceAiHostErrorMessage(new Error("device_ai_projection_mode_unsupported")), /域与投影模式不匹配/);
});

test("journal persistence flow: reuse on same owner, explicit rebuild on owner change", async () => {
  const memory = browserHost.memoryDeviceAiStores();
  const stores = memory.stores;
  const first = await browserHost.openDeviceAiJournal("device-ai-journal@1:profile-a:1", stores);
  assert.equal(first.rebuilt, true);
  assert.equal(first.system.generation, 1);
  await first.journal.append({ type: "preview_shown", intent_id: crypto.randomUUID(), local_preview_fingerprint: "a".repeat(64), question_sha256: "b".repeat(64), package_sha256: "c".repeat(64) });
  await first.journal.append({ type: "decision_made", intent_id: "intent-1", decision: "allow", local_preview_fingerprint: "a".repeat(64) });
  assert.ok(memory.state.blob instanceof Uint8Array && memory.state.blob.byteLength > 0, "sealed blob persisted");
  const blobAfterFirst = memory.state.blob;

  // Same owner, different tab session: reuse key/generation, entries readable,
  // cross-session entries reported (never silently replayed as authorized).
  const second = await browserHost.openDeviceAiJournal("device-ai-journal@1:profile-a:1", stores);
  assert.equal(second.rebuilt, false);
  assert.equal(second.system.generation, 1);
  const entries = await second.journal.readAll();
  assert.equal(entries.length, 2);
  assert.equal(entries[0].event.type, "preview_shown");
  const verification = await second.journal.verifyIntegrity();
  assert.equal(verification.ok, true);
  assert.deepEqual(verification.cross_session_entries.map(row => row.sequence), [1, 2]);

  // Owner epoch change: explicit rebuild (generation bump) instead of a
  // corrupt-blob failure; the stale blob is cleared.
  const third = await browserHost.openDeviceAiJournal("device-ai-journal@1:profile-a:2", stores);
  assert.equal(third.rebuilt, true);
  assert.equal(third.system.generation, 2);
  assert.equal(memory.state.blob, null, "stale blob cleared");
  assert.notEqual(blobAfterFirst, null);
  assert.equal((await third.journal.readAll()).length, 0);
  await third.journal.append({ type: "failure_observed", intent_id: null, stage: "recovery", code: "device_ai_unavailable" });
  assert.equal((await third.journal.readAll()).length, 1);
});

test("provider policy fingerprint mirror matches the Python server constants", async () => {
  // Expected values produced by apps/api tire_api.ai_analysis.device_provider_policy_fingerprint
  // (uv run python, digest over provider/model/allow_private/allowed_privacy_classes/
  // prompt_version='tire-grounding@1'/grounding_schema=digest(OUTPUT_SCHEMA)).
  assert.equal(await webValues.deviceProviderPolicyFingerprint({ model: "synthetic-device-ai-fixture", allowPrivate: true }),
    "5fc00af5b4beb91cf2a52478087827f753d905bb7b3fd0e3118a9a69898ba52e");
  assert.equal(await webValues.deviceProviderPolicyFingerprint({ model: "synthetic-device-ai-fixture", allowPrivate: false }),
    "094c0874f41f64bab4eca9f28b07be371ae144cc3638d764d870e4b79ec4b3e3");
});

test("recovery pointer parser keeps only closed identifier fields", () => {
  const pointer = { intentId: "10f4a320-4bb7-42a3-bd56-15565bbf980d", prepareKey: "10f4a320-4bb7-42a3-bd56-15565bbf980d",
    analysisKey: "10f4a320-4bb7-42a3-bd56-15565bbf980d", requestId: "req-1", question: "private question" };
  const { question, ...kept } = pointer;
  void question;
  assert.deepEqual(webValues.parseDeviceAiRecovery(JSON.stringify(pointer)), kept);
  for (const raw of [null, "not json", JSON.stringify({ ...pointer, analysisKey: "invalid" }), JSON.stringify({ ...pointer, requestId: "" })]) {
    assert.equal(webValues.parseDeviceAiRecovery(raw), null);
  }
});
