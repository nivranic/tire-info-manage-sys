import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "../../../packages/native-client/tests/load-typescript.mjs";

const shared = await loadTypeScript("../../../packages/native-client/src/index.ts", import.meta.url);
const { createMobileDeviceAiBridge, deviceAiCommandCode, mobilePreviewOrigin, mobileSelectorFromRead,
  verifyMobilePackBytes, MOBILE_DEVICE_AI_DOMAINS, DEVICE_AI_PREPARE_DOMAIN_MODES,
  mobileJournalEventForPreview, mobileJournalEventForDecision, mobileJournalEventForPrepareCreated,
  mobileJournalEventForClaim, mobileJournalEventForOutcome, mobileJournalEventForFailure,
  mobileFailureStage, mobileFailureCode, mobileIntentKey, createMobileIntentCache } = await loadTypeScript("../src/device-ai-mobile.ts", import.meta.url);
const { createMobileInvoke } = await loadTypeScript("../src/native-platform.ts", import.meta.url);

const sha256Hex = async bytes => Array.from(new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", bytes)),
  byte => byte.toString(16).padStart(2, "0")).join("");

const slot = {
  slot_id: "slot-1", generation: 3, package_id: "pkg-1", sha256: "", byte_count: 0,
  title: "设备历史资料", created_at: "2026-10-01T00:00:00Z", installed_at: "2026-10-01T00:00:00Z",
  privacy_class: "private", owner_scope_id: "9a".repeat(32), locked: false, previous_owner: false,
  counts: { garage_profiles: 0, watch_items: 0, recent_queries: 0, distinct_evidence: 1, searchable_documents: 1 },
};
const status = { schema: "offline-host@1", available: true, state: "ready", storage: "native_encrypted_files",
  profile_id: "11111111-2222-4333-8444-555555555555", owner_epoch: 7, total_bytes: 1, max_store_bytes: 2,
  max_package_bytes: 3, max_slots: 4, encryption: "android_keystore", persistence: "app_private",
  manual_updates: true, background_updates: false, error: null };

const memberReference = kind => (kind === "tire"
  ? { kind: "tire", snapshot_id: "snap-1", variant_id: "var-1", verification_id: "ver-1" }
  : kind === "vehicle"
    ? { kind: "vehicle", snapshot_id: "snap-v", verification_id: "ver-v" }
    : kind === "recall"
      ? { kind: "recall", snapshot_id: "snap-r", recall_revision_id: null, verification_id: "ver-r" }
      : { kind: "recall_search", snapshot_id: "snap-rs", verification_id: "ver-rs" });
const readResult = (kind, recordIndex) => ({
  data_state: "local_snapshot", slot,
  document: { id: "doc-1", category: "evidence", kind, member_key: "ab".repeat(32), context_id: null,
    record_index: recordIndex, title: "记录", text: "", facets: { brand: null, model: null, size: null, source_id: null, campaign_number: null },
    membership: [], privacy_class: "private", observed_at: null, verified_at: null },
  member: { key: "ab".repeat(32), reference: memberReference(kind), member_reasons: [], privacy_class: "private", raw_included: false },
  context: null,
});

test("device-ai plugin commands map through createMobileInvoke with the {request} wrapper", async () => {
  const calls = [];
  const plugin = {
    deviceAiPrepare: async args => { calls.push(["deviceAiPrepare", args]); return { id: "prep-1", pack_id: "pack-1", replayed: false, device_context_fingerprint: "03".repeat(32) }; },
    deviceAiSubmitStream: async args => { calls.push(["deviceAiSubmitStream", args]); return { analysis: { id: "req-1" }, execution: { state: "accepted", terminal: false }, server_time: "2026-10-02T00:00:00Z" }; },
    deviceAiLookup: async args => { calls.push(["deviceAiLookup", args]); return {}; },
    deviceAiJournalRead: async args => { calls.push(["deviceAiJournalRead", args]); return { ok: true, length: 0, violations: [], cross_session_entries: [] }; },
    deviceAiJournalAppend: async args => { calls.push(["deviceAiJournalAppend", args]); return { sequence: 1, event: args.request.event }; },
    deviceAiResolveUnknown: async args => { calls.push(["deviceAiResolveUnknown", args]); return { kind: "not_submitted" }; },
  };
  const invoke = createMobileInvoke(plugin);
  const bridge = createMobileDeviceAiBridge(invoke);

  const report = await bridge.journalRead("profile-1", 7, "session-1");
  assert.equal(report.ok, true);
  assert.deepEqual(calls[0], ["deviceAiJournalRead", { request: { owner: "profile-1", generation: 7, session_id: "session-1" } }]);

  const detail = await bridge.submitStream({
    pack_id: "pack-1", question: "问题", prepare_id: "prep-1", host_receipt_id: "11111111-2222-4333-8444-555555555555",
    device_context_fingerprint: "03".repeat(32),
    provider_consent: { expected_pack_fingerprint: "aa".repeat(32), expected_device_context_fingerprint: "03".repeat(32),
      question_sha256: "01".repeat(32), provider: "openai_responses", model: "m-1", expected_provider_policy_fingerprint: "05".repeat(32) },
  }, "12345678-1234-4234-8345-123456789abc");
  assert.equal(detail.analysis.id, "req-1");
  assert.deepEqual(calls[1][1].request.idempotency_key, "12345678-1234-4234-8345-123456789abc");

  await bridge.lookup({ kind: "attempt", idempotency_key: "12345678-1234-4234-8345-123456789abc" });
  assert.deepEqual(calls[2][1], { request: { kind: "attempt", idempotency_key: "12345678-1234-4234-8345-123456789abc" } });

  await bridge.lookup({ kind: "prepare_read", prepare_id: "prep-1" });
  assert.deepEqual(calls[3][1], { request: { kind: "prepare_read", prepare_id: "prep-1" } });

  // journal append rides the same {request} wrapper and echoes the closed event back
  const entry = await bridge.journalAppend("profile-1", 7, "session-1",
    mobileJournalEventForPreview("11111111-2222-4333-8444-555555555555",
      { local_preview_fingerprint: "aa".repeat(32), question_sha256: "bb".repeat(32), package_sha256: "cc".repeat(32) }));
  assert.equal(entry.sequence, 1);
  assert.deepEqual(calls[4], ["deviceAiJournalAppend", { request: { owner: "profile-1", generation: 7, session_id: "session-1",
    event: { type: "preview_shown", intent_id: "11111111-2222-4333-8444-555555555555",
      local_preview_fingerprint: "aa".repeat(32), question_sha256: "bb".repeat(32), package_sha256: "cc".repeat(32) } } }]);

  // N18 resolve: request carries the journal binding + nullable intent filter
  const outcome = await bridge.resolveUnknown({ analysis_key: "12345678-1234-4234-8345-123456789abc", intent_id: null,
    owner: "profile-1", generation: 7, session_id: "session-1" });
  assert.equal(outcome.kind, "not_submitted");
  assert.deepEqual(calls[5], ["deviceAiResolveUnknown", { request: { analysis_key: "12345678-1234-4234-8345-123456789abc",
    intent_id: null, owner: "profile-1", generation: 7, session_id: "session-1" } }]);
});

test("device-ai journal append / resolve results pass closed-view checks and reject malformed shapes", async () => {
  const malformedEntry = createMobileInvoke({ deviceAiJournalAppend: async () => ({ sequence: "one" }) });
  await assert.rejects(createMobileDeviceAiBridge(malformedEntry).journalAppend("profile-1", 7, "session-1",
    { type: "failure_observed", intent_id: null, stage: "submit", code: "x" }), /台账写入结果格式不完整/);
  const malformedOutcome = createMobileInvoke({ deviceAiResolveUnknown: async () => ({ kind: "resolved" }) });
  await assert.rejects(createMobileDeviceAiBridge(malformedOutcome).resolveUnknown(
    { analysis_key: "12345678-1234-4234-8345-123456789abc", intent_id: null, owner: "profile-1", generation: 7, session_id: "session-1" }),
    /恢复核对结果格式不完整/);
  const noKind = createMobileInvoke({ deviceAiResolveUnknown: async () => ({}) });
  await assert.rejects(createMobileDeviceAiBridge(noKind).resolveUnknown(
    { analysis_key: "12345678-1234-4234-8345-123456789abc", intent_id: null, owner: "profile-1", generation: 7, session_id: "session-1" }),
    /恢复核对结果格式不完整/);
  // a resolved detail that passes the closed subset check is returned verbatim
  const resolvedInvoke = createMobileInvoke({ deviceAiResolveUnknown: async () => ({ kind: "resolved",
    detail: { analysis: { id: "req-1" }, execution: { state: "completed", terminal: true }, server_time: "2026-10-02T00:00:00Z" } }) });
  const resolved = await createMobileDeviceAiBridge(resolvedInvoke).resolveUnknown(
    { analysis_key: "12345678-1234-4234-8345-123456789abc", intent_id: null, owner: "profile-1", generation: 7, session_id: "session-1" });
  assert.equal(resolved.kind, "resolved");
  assert.equal(resolved.detail.analysis.id, "req-1");
});

test("per-stage journal event mappers produce the six closed event shapes", () => {
  const intentId = "11111111-2222-4333-8444-555555555555";
  assert.deepEqual(mobileJournalEventForPreview(intentId,
    { local_preview_fingerprint: "aa".repeat(32), question_sha256: "bb".repeat(32), package_sha256: "cc".repeat(32) }),
    { type: "preview_shown", intent_id: intentId, local_preview_fingerprint: "aa".repeat(32),
      question_sha256: "bb".repeat(32), package_sha256: "cc".repeat(32) });
  assert.deepEqual(mobileJournalEventForDecision(intentId, "deny", "aa".repeat(32)),
    { type: "decision_made", intent_id: intentId, decision: "deny", local_preview_fingerprint: "aa".repeat(32) });
  assert.deepEqual(mobileJournalEventForPrepareCreated(intentId, "12345678-1234-4234-8345-123456789abc",
    { id: "prep-1", projection_sha256: "99".repeat(32), device_context_fingerprint: "03".repeat(32) }),
    { type: "prepare_created", intent_id: intentId, prepare_id: "prep-1",
      idempotency_key: "12345678-1234-4234-8345-123456789abc", projection_sha256: "99".repeat(32),
      device_context_fingerprint: "03".repeat(32) });
  assert.deepEqual(mobileJournalEventForClaim(intentId, "prep-1", "12345678-1234-4234-8345-123456789abc", "bb".repeat(32)),
    { type: "claim_submitted", intent_id: intentId, prepare_id: "prep-1",
      analysis_key: "12345678-1234-4234-8345-123456789abc", question_sha256: "bb".repeat(32) });
  // outcome with a null intent keeps the web spelling (intentId ?? "")
  assert.deepEqual(mobileJournalEventForOutcome(null, "12345678-1234-4234-8345-123456789abc", "req-1", "completed"),
    { type: "outcome_observed", intent_id: "", analysis_key: "12345678-1234-4234-8345-123456789abc",
      request_id: "req-1", state: "completed" });
  assert.deepEqual(mobileJournalEventForFailure(intentId, "provider", "ai_provider_timeout"),
    { type: "failure_observed", intent_id: intentId, stage: "provider", code: "ai_provider_timeout" });
  assert.deepEqual(mobileJournalEventForFailure(null, "submit", "unknown"),
    { type: "failure_observed", intent_id: null, stage: "submit", code: "unknown" });
});

test("failure stage split and failure code mirror the web closed sets", () => {
  // provider-side failures
  assert.equal(mobileFailureStage("ai_provider_timeout"), "provider");
  assert.equal(mobileFailureStage("ai_refused"), "provider");
  assert.equal(mobileFailureStage("ai_response_incomplete"), "provider");
  // source / transport failures (including null / undefined error codes)
  assert.equal(mobileFailureStage("api_network_unavailable"), "source");
  assert.equal(mobileFailureStage(null), "source");
  assert.equal(mobileFailureStage(undefined), "source");
  // submit failure codes: closed code first, message second, never fabricated
  const withCode = Object.assign(new Error("x"), { code: "device_ai_host_http_error" });
  assert.equal(mobileFailureCode(withCode), "device_ai_host_http_error");
  assert.equal(mobileFailureCode(new Error("服务端准备记录与本机预览指纹不一致，已停止提交。")), "服务端准备记录与本机预览指纹不一致，已停止提交。");
  assert.equal(mobileFailureCode("not-an-error"), "unknown");
});

test("mobile intent cache keeps one intent id per selection+question for the whole dialog session", () => {
  const memberKeys = ["cd".repeat(32), "ab".repeat(32)];
  // key shape: slot : domain : sorted members : question sha
  assert.equal(mobileIntentKey("slot-1", "tire", memberKeys, "bb".repeat(32)),
    `slot-1:tire:${"ab".repeat(32)},${"cd".repeat(32)}:${"bb".repeat(32)}`);
  const nextIntent = createMobileIntentCache();
  const first = nextIntent("slot-1", "tire", memberKeys, "bb".repeat(32));
  const again = nextIntent("slot-1", "tire", [...memberKeys].reverse(), "bb".repeat(32));
  assert.equal(first, again); // member order must not matter
  assert.notEqual(first, nextIntent("slot-1", "tire", memberKeys, "00".repeat(32))); // new question -> new intent
  assert.notEqual(first, nextIntent("slot-2", "tire", memberKeys, "bb".repeat(32))); // new slot -> new intent
  const other = createMobileIntentCache();
  assert.notEqual(first, other("slot-1", "tire", memberKeys, "bb".repeat(32))); // caches are per dialog session
});

test("device-ai closed codes pass through the Capacitor adapter instead of generic request_failed", async () => {
  const rejection = Object.assign(Object.create(Error.prototype), { code: "device_ai_projection_mismatch", message: "device_ai_projection_mismatch" });
  const invoke = createMobileInvoke({ deviceAiPrepare: async () => { throw rejection; } });
  const bridge = createMobileDeviceAiBridge(invoke);
  const body = {
    package_id: "pkg-1", expected_sha256: "ef".repeat(32), expected_byte_count: 1234, expected_schema: "offline-pack@2",
    expected_owner_scope_id: "9a".repeat(32),
    selectors: [{ kind: "tire", member_key: "ab".repeat(32), document_id: null, record_index: null,
      reference: { kind: "tire", snapshot_id: "snap-1", variant_id: "var-1", verification_id: "ver-1" } }],
    projection_mode: "single_observation", approved_closure: null, expected_projection_sha256: "99".repeat(32),
    question_sha256: "01".repeat(32), host_receipt_id: "11111111-2222-4333-8444-555555555555",
    intent_id: "22222222-3333-4444-8555-666666666666",
  };
  await assert.rejects(bridge.prepare(body, "12345678-1234-4234-8345-123456789abc"), error => {
    assert.equal(deviceAiCommandCode(error), "device_ai_projection_mismatch");
    assert.equal(error.code, "device_ai_projection_mismatch");
    return true;
  });
  // a malformed prepare view is rejected before anything reaches the panel state
  const invokeBadView = createMobileInvoke({ deviceAiPrepare: async () => ({ id: "prep-1" }) });
  await assert.rejects(createMobileDeviceAiBridge(invokeBadView).prepare(body, "12345678-1234-4234-8345-123456789abc"),
    /准备记录响应格式不完整/);
});

test("mobileSelectorFromRead keeps the four-domain record_index rules", () => {
  // tire / vehicle are whole-observation domains: record_index always null.
  assert.deepEqual(mobileSelectorFromRead("tire", readResult("tire", 4)), {
    kind: "tire", member_key: "ab".repeat(32), document_id: "doc-1", record_index: null,
    reference: memberReference("tire"),
  });
  assert.equal(mobileSelectorFromRead("vehicle", readResult("vehicle", 9)).record_index, null);
  // recall / recall_search are record-carrying: document.record_index is preserved.
  assert.equal(mobileSelectorFromRead("recall", readResult("recall", 2)).record_index, 2);
  assert.equal(mobileSelectorFromRead("recall_search", readResult("recall_search", 0)).record_index, 0);
  // reference kind must match the requested domain.
  assert.throws(() => mobileSelectorFromRead("vehicle", readResult("tire", null)), /不是车辆域历史观察/);
  // a document without a member binding cannot be selected.
  const orphan = readResult("tire", null);
  orphan.member = null;
  assert.throws(() => mobileSelectorFromRead("tire", orphan), /不支持设备 AI 分析/);
});

test("mobilePreviewOrigin binds the native owner state and the slot", () => {
  const origin = mobilePreviewOrigin(status, slot, "offline-pack@2");
  assert.deepEqual(origin, {
    expected_profile_id: "11111111-2222-4333-8444-555555555555", expected_owner_epoch: 7,
    slot_id: "slot-1", expected_generation: 3, package_id: "pkg-1",
    expected_sha256: slot.sha256, expected_byte_count: slot.byte_count,
    owner_scope_id: "9a".repeat(32), package_schema: "offline-pack@2",
  });
  assert.throws(() => mobilePreviewOrigin({ ...status, profile_id: null }, slot, "offline-pack@2"), /归属未就绪/);
});

test("verifyMobilePackBytes pins the fetched archive to the slot digest before any projection", async () => {
  const envelope = JSON.stringify({ schema: "offline-pack@2", package_id: "pkg-1" });
  const bytes = new TextEncoder().encode(envelope);
  const bound = { ...slot, sha256: await sha256Hex(bytes), byte_count: bytes.byteLength };
  assert.deepEqual(await verifyMobilePackBytes(bytes, bound), { bytes, schema: "offline-pack@2" });
  // byte-count drift, digest drift and unsupported schema all stop the preview.
  await assert.rejects(verifyMobilePackBytes(bytes, { ...bound, byte_count: bound.byte_count + 1 }), /字节数与所选版本不一致/);
  await assert.rejects(verifyMobilePackBytes(bytes, { ...bound, sha256: "ff".repeat(32) }), /SHA-256 与所选版本不一致/);
  const legacy = new TextEncoder().encode(JSON.stringify({ schema: "offline-pack@3" }));
  await assert.rejects(verifyMobilePackBytes(legacy, { ...bound, sha256: await sha256Hex(legacy), byte_count: legacy.byteLength }), /包结构不受支持/);
});

test("mobile domains map onto the SDK per-domain converter modes", () => {
  assert.deepEqual(MOBILE_DEVICE_AI_DOMAINS, ["tire", "vehicle", "recall", "recall_search"]);
  assert.deepEqual(DEVICE_AI_PREPARE_DOMAIN_MODES, {
    tire: "single_observation", vehicle: "complete_observation",
    recall: "complete_formal_observation", recall_search: "candidate_page_context",
  });
});
