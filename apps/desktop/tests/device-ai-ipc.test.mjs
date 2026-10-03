// 桌面设备 AI IPC 映射层单测：六个已注册 Tauri 命令的信封翻译
// （accepted 值透传 / rejected → ApiError / 原生闭集码 → DesktopError /
//   device_ai_host_* 闭集码保留原文）＋ 非信封命令的 deviceAiRawInvoke ＋
//   面板打开时的未决 claim 推导（deriveDeviceAiPendingClaim）。纯 Node，无
//   Tauri、无网络。
import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript as load } from "../../../packages/native-client/tests/load-typescript.mjs";
const loadTypeScript = relative => load(relative, import.meta.url);

const { deviceAiInvoke, deviceAiRawInvoke, deriveDeviceAiPendingClaim } = await loadTypeScript("../src/device-ai-ipc.ts");
const { ApiError } = await loadTypeScript("../../../packages/api-client/src/index.ts");
const { DesktopError } = await loadTypeScript("../src/native-platform.ts");

test("accepted envelope passes the server value through", async () => {
  const calls = [];
  const value = await deviceAiInvoke(async (command, args) => {
    calls.push({ command, args });
    return { outcome: "accepted", http_status: 201, value: { id: "prep-1", replayed: false } };
  }, "device_ai_prepare", { body: { package_id: "pkg-1" }, key: "11111111-2222-4333-8444-555555555555" });
  assert.deepEqual(value, { id: "prep-1", replayed: false });
  assert.deepEqual(calls, [{ command: "device_ai_prepare", args: { body: { package_id: "pkg-1" }, key: "11111111-2222-4333-8444-555555555555" } }]);
});

test("rejected envelope maps to ApiError passthrough with closed code and run id", async () => {
  await assert.rejects(
    deviceAiInvoke(async () => ({ outcome: "rejected", http_status: 409, code: "device_ai_consent_mismatch", message: "六元组不一致", run_id: "run-9" }), "device_ai_submit_stream", { body: {}, key: "k" }),
    cause => {
      assert.ok(cause instanceof ApiError);
      assert.equal(cause.status, 409);
      assert.equal(cause.code, "device_ai_consent_mismatch");
      assert.equal(cause.message, "六元组不一致");
      assert.equal(cause.runId, "run-9");
      return true;
    },
  );
  // 404 keeps its status for the N18 lookup-first recovery branch.
  await assert.rejects(
    deviceAiInvoke(async () => ({ outcome: "rejected", http_status: 404, code: null, message: null, run_id: null }), "device_ai_lookup_attempt", { key: "k" }),
    cause => cause instanceof ApiError && cause.status === 404 && /HTTP 404/.test(cause.message),
  );
});

test("native closed IPC codes map to DesktopError; device_ai host codes keep their text", async () => {
  await assert.rejects(
    deviceAiInvoke(async () => { throw "API_TIMEOUT"; }, "device_ai_read_journal"),
    cause => {
      assert.ok(cause instanceof DesktopError);
      assert.equal(cause.code, "API_TIMEOUT");
      return true;
    },
  );
  await assert.rejects(
    deviceAiInvoke(async () => { throw Object.assign(new Error("boom"), { code: "DEVICE_AI_JOURNAL_KEY_UNAVAILABLE" }); }, "device_ai_read_journal"),
    cause => {
      // Unknown DEVICE_AI_* store codes surface through the closed native path
      // (DesktopError with the shared fallback code), never as a value.
      assert.ok(cause instanceof DesktopError);
      assert.equal(cause.code, "request_failed");
      return true;
    },
  );
  // device_ai_host_* codes stay verbatim so deviceAiHostErrorMessage can map them.
  await assert.rejects(
    deviceAiInvoke(async () => { throw "device_ai_host_invalid_argument"; }, "device_ai_prepare", { body: {}, key: "k" }),
    cause => {
      assert.ok(!(cause instanceof DesktopError));
      assert.equal(cause.message, "device_ai_host_invalid_argument");
      assert.equal(cause.code, "device_ai_host_invalid_argument");
      return true;
    },
  );
});

test("malformed envelopes fail closed instead of yielding a value", async () => {
  for (const malformed of [null, undefined, 42, "accepted", {}, { outcome: "unknown", value: 1 }]) {
    await assert.rejects(
      deviceAiInvoke(async () => malformed, "device_ai_read_journal"),
      cause => cause instanceof DesktopError && cause.code === "invalid_response",
    );
  }
});

test("raw invoke passes the journal command value through verbatim", async () => {
  const calls = [];
  const view = { schema: "device-ai-journal@1", owner: "acct-1", generation: 1, session_id: "s#1", length: 1,
    entries: [{ sequence: 1, event: { type: "preview_shown" } }], verification: { ok: true } };
  const value = await deviceAiRawInvoke(async (command, args) => {
    calls.push({ command, args });
    return view;
  }, "device_ai_read_journal");
  assert.deepEqual(value, view);
  assert.deepEqual(calls, [{ command: "device_ai_read_journal", args: undefined }]);
  // device_ai_journal_append carries the closed event payload unchanged.
  const event = { type: "claim_submitted", intent_id: "i-1", prepare_id: "p-1", analysis_key: "a-1", question_sha256: "q".repeat(64) };
  const entry = await deviceAiRawInvoke(async (command, args) => {
    assert.equal(command, "device_ai_journal_append");
    assert.deepEqual(args, { event });
    return { sequence: 2, event };
  }, "device_ai_journal_append", { event });
  assert.deepEqual(entry, { sequence: 2, event });
});

test("raw invoke keeps the closed error translation of the envelope path", async () => {
  await assert.rejects(
    deviceAiRawInvoke(async () => { throw "API_TIMEOUT"; }, "device_ai_journal_append", { event: {} }),
    cause => cause instanceof DesktopError && cause.code === "API_TIMEOUT",
  );
  await assert.rejects(
    deviceAiRawInvoke(async () => { throw "device_ai_host_journal_chain_broken"; }, "device_ai_read_journal"),
    cause => !(cause instanceof DesktopError) && cause.code === "device_ai_host_journal_chain_broken",
  );
});

test("resolve_unknown rides the accepted envelope: value is the {kind,...} resolution", async () => {
  const resolution = await deviceAiInvoke(async () => ({ outcome: "accepted", http_status: 200, value: { kind: "unknown_local_claim", analysis_key: "a-1", resubmission: "same_key_same_body_user_decision_only" } }),
    "device_ai_resolve_unknown", { analysisKey: "a-1", intentId: "i-1" });
  assert.deepEqual(resolution, { kind: "unknown_local_claim", analysis_key: "a-1", resubmission: "same_key_same_body_user_decision_only" });
  // A server rejection (e.g. 409) still maps to ApiError for conflict UX.
  await assert.rejects(
    deviceAiInvoke(async () => ({ outcome: "rejected", http_status: 409, code: null, message: "冲突", run_id: null }), "device_ai_resolve_unknown", { analysisKey: "a-1" }),
    cause => cause instanceof ApiError && cause.status === 409 && cause.message === "冲突",
  );
});

const entry = (sequence, event) => ({ sequence, session_id: "s#1", event });

test("deriveDeviceAiPendingClaim picks the last claim without a matching outcome", () => {
  assert.equal(deriveDeviceAiPendingClaim([]), null);
  assert.equal(deriveDeviceAiPendingClaim([entry(1, { type: "preview_shown" })]), null);
  // claim without outcome -> pending pointer
  assert.deepEqual(deriveDeviceAiPendingClaim([
    entry(1, { type: "preview_shown" }),
    entry(2, { type: "claim_submitted", intent_id: "i-1", prepare_id: "p-1", analysis_key: "a-1", question_sha256: "q" }),
  ]), { intentId: "i-1", analysisKey: "a-1" });
  // matching outcome (any later sequence) clears the claim
  assert.equal(deriveDeviceAiPendingClaim([
    entry(1, { type: "claim_submitted", intent_id: "i-1", prepare_id: "p-1", analysis_key: "a-1", question_sha256: "q" }),
    entry(2, { type: "outcome_observed", intent_id: "i-1", analysis_key: "a-1", request_id: "req-1", state: "completed" }),
  ]), null);
  // failure_observed does NOT clear the claim (outcome stays unknown; N18)
  assert.deepEqual(deriveDeviceAiPendingClaim([
    entry(1, { type: "claim_submitted", intent_id: "i-1", prepare_id: "p-1", analysis_key: "a-1", question_sha256: "q" }),
    entry(2, { type: "failure_observed", intent_id: "i-1", stage: "submit", code: "API_TIMEOUT" }),
  ]), { intentId: "i-1", analysisKey: "a-1" });
  // several pending claims -> the LAST one wins
  assert.deepEqual(deriveDeviceAiPendingClaim([
    entry(1, { type: "claim_submitted", intent_id: "i-1", prepare_id: "p-1", analysis_key: "a-1", question_sha256: "q" }),
    entry(2, { type: "claim_submitted", intent_id: "i-2", prepare_id: "p-2", analysis_key: "a-2", question_sha256: "q" }),
  ]), { intentId: "i-2", analysisKey: "a-2" });
});
