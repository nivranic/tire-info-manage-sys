/** Public package consumer: injected transport only; never fetches or calls AI. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  ApiError,
  DEVICE_AI_WIRE_CONTRACT,
  DeviceAiHostClient,
  assertDeviceAiPrepareBody,
  questionSha256,
  setApiTransport,
  type DeviceAiPrepareBody,
  type DeviceAiPreparationView,
  type DeviceAiPrepareResultView,
  type DeviceAiStreamSubmission,
} from "@tire/api-client";
import { DEVICE_AI_WIRE_CONTRACT as sharedContract } from "@tire/domain-types";

assert.equal(DEVICE_AI_WIRE_CONTRACT, sharedContract);
assert.equal(sharedContract.wire_frozen, true);
assert.throws(
  () => readFileSync(new URL("../../../../.artifacts/contract-test-must-not-read.json", import.meta.url)),
  /tracked fixtures only/,
);

const key = "11111111-2222-4333-8444-555555555555";
const question = "compare saved tire evidence";
const questionHash = await questionSha256(question);
const body: DeviceAiPrepareBody = {
  package_id: "synthetic-public-package", expected_sha256: "a".repeat(64), expected_byte_count: 128,
  expected_schema: "offline-pack@2", expected_owner_scope_id: "b".repeat(64),
  selectors: [{
    kind: "tire", member_key: "c".repeat(64), document_id: null, record_index: null,
    reference: { kind: "tire", snapshot_id: "synthetic-snapshot", variant_id: "synthetic-variant", verification_id: "synthetic-receipt" },
  }],
  projection_mode: "single_observation", approved_closure: null,
  expected_projection_sha256: "d".repeat(64), question_sha256: questionHash,
  host_receipt_id: key, intent_id: "22222222-3333-4444-8555-666666666666",
};
const preparation: DeviceAiPreparationView = {
  id: "synthetic-prepare", created_at: "2026-10-18T00:00:00Z", expires_at: "2026-10-18T00:30:00Z", expired: false,
  idempotency_key: key, host_receipt_id: key, intent_id: body.intent_id,
  pack_id: "synthetic-pack", offline_pack_id: body.package_id, question_sha256: questionHash,
  selection_sha256: "c".repeat(64), projection_sha256: body.expected_projection_sha256, projection_byte_count: 128,
  device_context_fingerprint: "e".repeat(64), request_hash: "f".repeat(64), contract: {}, pack: {},
};
const jsonResponse = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
// All responses are synthetic transport fixtures, including successful reads;
// these probes make no API, database, Provider or platform acceptance claim.
let respond = () => jsonResponse({ detail: { code: "synthetic_contract_probe", message: "contract probe" } }, 409);
const calls: { path: string; method: string; body?: Record<string, unknown>; headers: Headers }[] = [];
const restore = setApiTransport(async (path, init) => {
  calls.push({ path, method: init.method ?? "GET", body: init.body ? JSON.parse(String(init.body)) : undefined, headers: new Headers(init.headers) });
  return respond();
});
const isProbe = (error: unknown) => error instanceof ApiError && error.code === "synthetic_contract_probe";

try {
  const client = new DeviceAiHostClient();
  await assert.rejects(client.prepare(body, key.toUpperCase()), isProbe);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].path, "/v1/ai/device-evidence-packs");
  assert.equal(calls[0].headers.get("Idempotency-Key"), key);
  assert.deepEqual(calls[0].body, body);

  // Runtime closure still rejects untrusted JS input before dispatch, despite
  // the type package carrying ordinary strings instead of validation brands.
  assert.throws(() => assertDeviceAiPrepareBody({ ...body, question } as DeviceAiPrepareBody));
  assert.throws(() => assertDeviceAiPrepareBody({ ...body, expected_byte_count: 8_388_609 }));
  assert.throws(() => assertDeviceAiPrepareBody({ ...body, approved_closure: [] }));
  assert.equal(calls.length, 1);

  const submission: DeviceAiStreamSubmission = {
    pack_id: "synthetic-pack", question: `\u3000${question}\u3000`, prepare_id: "synthetic-prepare",
    host_receipt_id: key, device_context_fingerprint: "e".repeat(64),
    provider_consent: {
      expected_pack_fingerprint: "f".repeat(64), expected_device_context_fingerprint: "e".repeat(64),
      question_sha256: questionHash, provider: "anthropic", model: "synthetic-model",
      expected_provider_policy_fingerprint: "a".repeat(64),
    },
  };
  await assert.rejects(client.submitStream(submission, key), isProbe);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].method, "POST");
  assert.equal(calls[1].path, "/v1/ai/analysis-streams");
  assert.deepEqual(calls[1].body, {
    pack_id: submission.pack_id, question, allow_external_processing: true,
    device_submission: {
      prepare_id: submission.prepare_id, host_receipt_id: key,
      device_context_fingerprint: submission.device_context_fingerprint,
      provider_consent: submission.provider_consent,
    },
  });
  assert.equal(submission.provider_consent.provider, "anthropic");

  // The server GET _view contains neither replayed nor provider_preview.
  // The public SDK must preserve that shape rather than inventing an outcome.
  respond = () => jsonResponse(preparation);
  const recovered = await client.lookupPrepare(key.toUpperCase());
  assert.deepEqual(recovered, preparation);
  assert.equal("replayed" in recovered, false);
  assert.equal("provider_preview" in recovered, false);
  assert.equal(calls.at(-1)!.method, "GET");
  assert.equal(calls.at(-1)!.path, `/v1/ai/device-evidence-packs/lookup?mode=history&idempotency_key=${key}`);
  const read = await client.readPrepare(preparation.id);
  assert.deepEqual(read, preparation);
  assert.equal("replayed" in read, false);
  assert.equal(calls.at(-1)!.method, "GET");
  assert.equal(calls.at(-1)!.path, `/v1/ai/device-evidence-packs/${preparation.id}?mode=history`);

  // POST has a distinct result contract: a fresh result and an idempotent
  // replay both require the explicit replayed boolean.
  const fresh: DeviceAiPrepareResultView = { ...preparation, replayed: false, provider_preview: { configured: true } };
  respond = () => jsonResponse(fresh, 201);
  assert.deepEqual(await client.prepare(body, key), fresh);
  const replay: DeviceAiPrepareResultView = { ...preparation, replayed: true };
  respond = () => jsonResponse(replay);
  assert.deepEqual(await client.prepare(body, key), replay);
  respond = () => jsonResponse(preparation, 201);
  await assert.rejects(client.prepare(body, key), /准备记录响应格式不完整/);
  respond = () => jsonResponse({ ...preparation, replayed: "false" }, 201);
  await assert.rejects(client.prepare(body, key), /准备记录响应格式不完整/);

  // Sharing the read decoder must retain the common response checks.
  respond = () => jsonResponse({ ...preparation, expires_at: "not-a-date" });
  await assert.rejects(client.lookupPrepare(key), /准备记录响应格式不完整/);
  await assert.rejects(client.readPrepare(preparation.id), /准备记录响应格式不完整/);

  respond = () => jsonResponse({ detail: { code: "synthetic_not_found", message: "not found" } }, 404);
  const isNotFound = (error: unknown) => error instanceof ApiError && error.status === 404 && error.code === "synthetic_not_found";
  await assert.rejects(client.lookupPrepare(key), isNotFound);
  await assert.rejects(client.readPrepare(preparation.id), isNotFound);
  const transportError = new Error("synthetic transport failure");
  respond = () => { throw transportError; };
  await assert.rejects(client.lookupPrepare(key), error => error === transportError);
  await assert.rejects(client.readPrepare(preparation.id), error => error === transportError);

  console.log("public-contract: package imports, closed requests, GET views, POST replay checks and error propagation passed (injected transport)");
} finally {
  restore();
}
