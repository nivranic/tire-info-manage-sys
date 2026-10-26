import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, setApiTransport, tireApi } from "../src/index.ts";
import type {
  EvidenceDocument, SourceMaterialCaptureRequest, SourceMaterialCaptureResult, SourceMaterialPolicies,
  SourceMaterialPolicy, SourceMaterialPreview, SourceMaterialPreviewRequest, SourceMaterialReceipt,
  SourceMaterialRequests, SourceMaterialRequestView, SourceMaterialStop, SourceMaterialStopRequest, SourceMaterialStopResult,
} from "@tire/domain-types";

const h = "a".repeat(64), mh = "b".repeat(64), key = "a1f2b3c4-1223-4234-8456-123456789abc";
const policy: SourceMaterialPolicy = {
  policy_id: "synthetic-material", title: "合成材料，仅验证合同", publisher: "项目合成出版者", edition: null, published_at: null,
  source_reference_url: "https://publisher.example.invalid/reference", download_url: "https://files.example.invalid/material.pdf",
  redirect_urls: ["https://cdn.example.invalid/final.pdf"], policy_fingerprint: h,
  rights: { rights_holder: "Synthetic rights holder", basis: "Synthetic rights declaration, not a real license", license_url: null,
    store_original: true, workspace_reopen: true, quote_identifiers: true, provider_use: false, export: false },
};
const metadata: EvidenceDocument = { id: "document/id?synthetic", title: policy.title, source_url: policy.source_reference_url,
  operator: "Synthetic operator", rights_basis: policy.rights.basis, raw_hash: h, byte_count: 13, content_type: "application/pdf",
  created_at: "2026-10-18T08:00:00Z", status: "unparsed_receipt", accepted_as_facts: false };
const receipt: SourceMaterialReceipt = { schema: "source-material-receipt@1", request_id: "synthetic-request", policy_fingerprint: h,
  source_reference_url: policy.source_reference_url, initial_url: policy.download_url, final_url: policy.redirect_urls[0],
  redirects: [{ from_url: policy.download_url, to_url: policy.redirect_urls[0], status: 302 }],
  robots: [{ url: "https://files.example.invalid/robots.txt", status: 200, raw_hash: mh, byte_count: 26, allowed: true, minimum_interval: 3, target_url: policy.download_url },
    { url: "https://cdn.example.invalid/robots.txt", status: 404, raw_hash: null, byte_count: 0, allowed: true, minimum_interval: 2, target_url: policy.redirect_urls[0] }],
  started_at: metadata.created_at, completed_at: metadata.created_at, raw_hash: h, byte_count: metadata.byte_count,
  content_type: "application/pdf", content_encoding: "identity", document_id: metadata.id, document_metadata_hash: mh,
  transport_verification: "https_transport_observed", content_authenticity: "unverified", source_reference_relation: "operator_configured", fingerprint: mh };
const previewRequest: SourceMaterialPreviewRequest = { policy_id: policy.policy_id, expected_policy_fingerprint: h };
const captureRequest: SourceMaterialCaptureRequest = { ...previewRequest, idempotency_key: key, operator: metadata.operator, rights_confirmed: true };
const preview: SourceMaterialPreview = { policy, can_capture: true, blockers: [], notice: "Synthetic transport contract only" };
const succeeded: SourceMaterialRequestView = { request_id: receipt.request_id, idempotency_key: key, state: "succeeded", policy,
  policy_fingerprint: h, operator: metadata.operator, requested_at: metadata.created_at, completed_at: metadata.created_at,
  failure_code: null, document: metadata, receipt, notice: "Transport observed; content unverified" };
const captured: SourceMaterialCaptureResult = { ...succeeded, replayed: false };
const processing: SourceMaterialRequestView = { ...succeeded, state: "processing_unconfirmed", completed_at: null, document: null, receipt: null };
const failed: SourceMaterialRequestView = { ...succeeded, state: "failed", failure_code: "source_material_robots_disallowed", document: null, receipt: null };
const stopRequest: SourceMaterialStopRequest = { expected_request_id: succeeded.request_id, operator: "Synthetic stop operator", reason: "仅验证停止采纳合同" };
const stop: SourceMaterialStop = { schema: "source-material-stop@1", request_id: succeeded.request_id, idempotency_key: key,
  operator: stopRequest.operator, reason: stopRequest.reason, stopped_at: "2026-10-25T08:00:00Z" };
const stopped: SourceMaterialRequestView = { ...processing, state: "stopped_unconfirmed", failure_code: null, stop };
const stopResult: SourceMaterialStopResult = { request: stopped, effect: "stopped" };

// Public callers cannot add URL, actor or permission overrides to the closed requests.
const extraPreview: SourceMaterialPreviewRequest = { ...previewRequest,
  // @ts-expect-error the caller cannot choose an arbitrary download URL
  download_url: policy.download_url };
const extraCapture: SourceMaterialCaptureRequest = { ...captureRequest,
  // @ts-expect-error actor identity belongs to the server session
  actor_user_id: "another-user" };
const deniedRights: SourceMaterialCaptureRequest = { ...captureRequest,
  // @ts-expect-error confirmation is a strict literal
  rights_confirmed: false };
// @ts-expect-error only POST adds replayed
void succeeded.replayed;
void extraPreview; void extraCapture; void deniedRights;
const extraStop: SourceMaterialStopRequest = { ...stopRequest,
  // @ts-expect-error actual identity comes from the authenticated session
  actor_user_id: "another-user" };
const extraStopKey: SourceMaterialStopRequest = { ...stopRequest,
  // @ts-expect-error the original key is a path parameter, never a replacement body UUID
  idempotency_key: key };
const falseStopEffect: SourceMaterialStopResult = { request: stopped,
  // @ts-expect-error stopping adoption never claims capture success
  effect: "succeeded" };
void extraStop; void extraStopKey; void falseStopEffect;

type Call = { path: string; init: RequestInit };
async function withTransport<T>(value: unknown, work: (calls: Call[]) => Promise<T>, status = 200) {
  const calls: Call[] = [];
  const restore = setApiTransport(async (path, init) => { calls.push({ path, init }); if (init.signal?.aborted) throw new DOMException("Synthetic cancellation", "AbortError"); return new Response(JSON.stringify(value), { status }); });
  try { return await work(calls); } finally { restore(); }
}
function privateCall(call: Call, signal?: AbortSignal) {
  assert.equal(call.init.credentials, "include"); assert.equal(call.init.cache, "no-store"); assert.equal(call.init.signal, signal);
}

test("empty policy catalogue stays empty and makes one API read only", async () => {
  const page: SourceMaterialPolicies = { scope: "local_workspace", items: [], notice: "No configured source" };
  await withTransport(page, async calls => { assert.deepEqual(await tireApi.sourceMaterialPolicies(), page); assert.equal(calls.length, 1); assert.equal(calls[0].path, "/v1/source-materials/policies"); privateCall(calls[0]); assert.equal(calls[0].init.method, undefined); });
});

test("configured policy preserves reference versus download and restricted rights", async () => {
  const page: SourceMaterialPolicies = { scope: "local_workspace", items: [policy], notice: "Configured declarations only" }, abort = new AbortController();
  await withTransport(page, async calls => { const value = await tireApi.sourceMaterialPolicies(abort.signal); privateCall(calls[0], abort.signal); assert.notEqual(value.items[0].source_reference_url, value.items[0].download_url); assert.equal(value.items[0].rights.provider_use, false); assert.equal(value.items[0].rights.export, false); assert.equal(value.items[0].edition, null); assert.equal(value.items[0].rights.license_url, null); });
});

test("preview sends only exact policy ID and fingerprint without UUID or URL", async () => {
  const original = structuredClone(previewRequest), abort = new AbortController();
  await withTransport(preview, async calls => { assert.deepEqual(await tireApi.previewSourceMaterial(previewRequest, abort.signal), preview); assert.equal(calls[0].path, "/v1/source-materials/preview"); assert.equal(calls[0].init.method, "POST"); privateCall(calls[0], abort.signal); assert.deepEqual(JSON.parse(String(calls[0].init.body)), original); assert.equal(new Headers(calls[0].init.headers).has("Idempotency-Key"), false); assert.deepEqual(previewRequest, original); });
});

test("capture carries one fixed body UUID and explicit confirmation without actor overrides", async () => {
  const abort = new AbortController(), original = structuredClone(captureRequest);
  await withTransport(captured, async calls => { assert.deepEqual(await tireApi.captureSourceMaterial(captureRequest, abort.signal), captured); assert.equal(calls.length, 1); const call = calls[0]; assert.equal(call.path, "/v1/source-materials/captures"); assert.equal(call.init.method, "POST"); privateCall(call, abort.signal); assert.deepEqual(JSON.parse(String(call.init.body)), original); assert.equal(new Headers(call.init.headers).has("Idempotency-Key"), false); assert.deepEqual(captureRequest, original); });
});

test("POST replay is distinct from a read result and retains original document ID", async () => {
  await withTransport({ ...captured, replayed: true }, async calls => { const value = await tireApi.captureSourceMaterial(captureRequest); assert.equal(value.replayed, true); assert.equal(value.document?.id, metadata.id); assert.equal(calls.length, 1); });
  await withTransport(succeeded, async () => { const value = await tireApi.sourceMaterialRequest(key); assert.equal("replayed" in value, false); assert.equal(value.receipt?.document_id, metadata.id); });
});

test("private history sends explicit offset without inventing limit or source filter", async () => {
  const page: SourceMaterialRequests = { scope: "current_user", items: [succeeded], offset: 50, total: 51, notice: "Current account only" };
  await withTransport(page, async calls => { assert.deepEqual(await tireApi.sourceMaterialRequests(50), page); assert.equal(calls[0].path, "/v1/source-materials/requests?mode=history&offset=50"); privateCall(calls[0]); assert.equal(calls.length, 1); });
});

test("UUID lookup encodes its path and reads history without recapture", async () => {
  const abort = new AbortController();
  await withTransport(succeeded, async calls => { await tireApi.sourceMaterialRequest("key/with?special", abort.signal); assert.equal(calls[0].path, "/v1/source-materials/requests/key%2Fwith%3Fspecial?mode=history"); assert.equal(calls[0].init.method, undefined); privateCall(calls[0], abort.signal); assert.equal(calls.length, 1); });
});

test("source receipt lookup uses document ID and preserves byte/robots/encoding evidence", async () => {
  await withTransport(succeeded, async calls => { const value = await tireApi.sourceMaterialDocument(metadata.id); assert.equal(calls[0].path, "/v1/source-materials/documents/document%2Fid%3Fsynthetic?mode=history"); assert.equal(value.receipt?.content_encoding, "identity"); assert.equal(value.receipt?.content_authenticity, "unverified"); assert.equal(value.receipt?.source_reference_relation, "operator_configured"); assert.equal(value.receipt?.robots[1].raw_hash, null); assert.equal(value.receipt?.redirects[0].status, 302); privateCall(calls[0]); });
});

test("original download reuses the binary document endpoint without another source fetch", async () => {
  const calls: Call[] = [], abort = new AbortController(), bytes = new TextEncoder().encode("%PDF-synthetic");
  const restore = setApiTransport(async (path, init) => { calls.push({ path, init }); return new Response(bytes, { headers: { "Content-Type": "application/pdf" } }); });
  try { const blob = await tireApi.documentContent(metadata.id, abort.signal); assert.deepEqual(new Uint8Array(await blob.arrayBuffer()), bytes); assert.equal(blob.type, "application/pdf"); assert.equal(calls.length, 1); assert.equal(calls[0].path, "/v1/documents/document%2Fid%3Fsynthetic/content?mode=history"); privateCall(calls[0], abort.signal); } finally { restore(); }
});

test("failed and processing responses are not promoted or automatically retried", async () => {
  for (const response of [failed, processing]) await withTransport(response, async calls => { const value = await tireApi.sourceMaterialRequest(key); assert.equal(value.state, response.state); assert.equal(value.document, null); assert.equal(value.receipt, null); assert.equal(calls.length, 1); assert.equal(calls[0].init.method, undefined); });
});

test("permission, policy, idempotency, absence and integrity errors keep server codes", async () => {
  for (const [status, code] of [[403, "admin_required"], [409, "source_material_policy_changed"], [409, "source_material_idempotency_mismatch"], [404, "source_material_receipt_not_found"], [503, "source_material_integrity_failed"]] as const)
    await withTransport({ detail: { code, message: "Synthetic rejection" } }, async calls => { await assert.rejects(tireApi.captureSourceMaterial(captureRequest), cause => cause instanceof ApiError && cause.status === status && cause.code === code); assert.equal(calls.length, 1); }, status);
});

test("aborted and ambiguous captures make one attempt and never invent a new UUID", async () => {
  const abort = new AbortController(); abort.abort();
  await withTransport(captured, async calls => { await assert.rejects(tireApi.captureSourceMaterial(captureRequest, abort.signal), cause => cause instanceof DOMException && cause.name === "AbortError"); assert.equal(calls.length, 1); assert.equal(calls[0].init.signal, abort.signal); });
  let calls = 0;
  const restore = setApiTransport(async (_path, init) => { calls++; assert.equal(JSON.parse(String(init.body)).idempotency_key, key); throw new TypeError("Synthetic lost response"); });
  try { await assert.rejects(tireApi.captureSourceMaterial(captureRequest), TypeError); assert.equal(calls, 1); } finally { restore(); }
});

test("stop sends one encoded original key and an exact immutable body with optional abort signal", async () => {
  const abort = new AbortController(), original = structuredClone(stopRequest);
  await withTransport(stopResult, async calls => {
    assert.deepEqual(await tireApi.stopSourceMaterialRequest("key/with?special", stopRequest, abort.signal), stopResult);
    assert.equal(calls.length, 1); const call = calls[0];
    assert.equal(call.path, "/v1/source-materials/requests/key%2Fwith%3Fspecial/stop"); assert.equal(call.init.method, "POST");
    privateCall(call, abort.signal); assert.deepEqual(JSON.parse(String(call.init.body)), original);
    assert.equal(new Headers(call.init.headers).has("Idempotency-Key"), false); assert.deepEqual(stopRequest, original);
  });
});

test("stop effects preserve unknown network state and an already terminal result without recapture", async () => {
  for (const [effect, request] of [["stopped", stopped], ["already_stopped", stopped], ["already_terminal", succeeded], ["already_terminal", failed]] as const) {
    const result: SourceMaterialStopResult = { effect, request };
    await withTransport(result, async calls => { assert.deepEqual(await tireApi.stopSourceMaterialRequest(key, stopRequest), result); assert.equal(calls.length, 1); });
  }
  await withTransport(stopped, async calls => {
    const result = await tireApi.sourceMaterialRequest(key); assert.equal(result.state, "stopped_unconfirmed");
    assert.deepEqual(result.stop, stop); assert.equal(result.document, null); assert.equal(result.receipt, null);
    assert.equal(result.completed_at, null); assert.equal(result.failure_code, null); assert.equal(calls.length, 1); assert.equal(calls[0].init.method, undefined);
  });
});

test("stop permission, ownership, conflict and uncertain commit errors keep their fixed server codes", async () => {
  for (const [status, code] of [[403, "admin_required"], [404, "source_material_request_not_found"], [409, "source_material_stop_conflict"],
    [503, "source_material_stop_commit_unconfirmed"], [503, "source_material_integrity_failed"]] as const)
    await withTransport({ detail: { code, message: "Synthetic stop rejection" } }, async calls => {
      await assert.rejects(tireApi.stopSourceMaterialRequest(key, stopRequest), cause => cause instanceof ApiError && cause.status === status && cause.code === code);
      assert.equal(calls.length, 1); assert.deepEqual(JSON.parse(String(calls[0].init.body)), stopRequest);
    }, status);
});

test("aborted and lost stop responses make one POST and only an explicit original UUID read recovers", async () => {
  const abort = new AbortController(); abort.abort();
  await withTransport(stopResult, async calls => {
    await assert.rejects(tireApi.stopSourceMaterialRequest(key, stopRequest, abort.signal), cause => cause instanceof DOMException && cause.name === "AbortError");
    assert.equal(calls.length, 1); privateCall(calls[0], abort.signal);
  });
  const calls: Call[] = [];
  const restore = setApiTransport(async (path, init) => {
    calls.push({ path, init });
    if (init.method === "POST") { assert.deepEqual(JSON.parse(String(init.body)), stopRequest); throw new TypeError("Synthetic lost stop acknowledgement"); }
    return new Response(JSON.stringify(stopped));
  });
  try {
    await assert.rejects(tireApi.stopSourceMaterialRequest(key, stopRequest), TypeError); assert.equal(calls.length, 1);
    assert.deepEqual(await tireApi.sourceMaterialRequest(key), stopped); assert.equal(calls.length, 2);
    assert.equal(calls[1].path, `/v1/source-materials/requests/${key}?mode=history`); assert.equal(calls[1].init.method, undefined);
  } finally { restore(); }
});
