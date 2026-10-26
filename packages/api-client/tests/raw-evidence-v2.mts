/** Written for R93; NOT EXECUTED under the current ChildPolicy. Synthetic transport only, never HTTP/source/Native acceptance. */
import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import {
  ApiError, ApiTransportError, RawEvidenceContractError, RawEvidenceContextError,
  assertVehicleEvidenceV2, assertRawCaptureEvidenceV2, assertQuarantineEvidenceV2,
  setApiTransport, tireApi,
} from "@tire/api-client";
import type { ApiTransport, RawEvidenceContextFence, VerifiedRawEvidenceContent } from "@tire/api-client";
import type {
  Evidence, RawCaptureEvidence, QuarantineEvidence,
  VehicleEvidenceV2, RawCaptureEvidenceV2, QuarantineEvidenceV2, VehicleRawPayloadV2,
} from "@tire/domain-types";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type OldBodies = Assert<Equal<[Evidence["body"], RawCaptureEvidence["body"], QuarantineEvidence["body"]], [string, string, string]>>;
type ContentResult = Assert<Equal<Awaited<ReturnType<typeof tireApi.vehicleEvidenceContent>>, VerifiedRawEvidenceContent<VehicleEvidenceV2>>>;
function compileOnlyRequiredFence() {
  // @ts-expect-error New metadata reads require an account/context fence.
  void tireApi.vehicleEvidenceV2("snapshot");
  // @ts-expect-error The content method cannot accept server-provided metadata in place of a fence.
  void tireApi.captureEvidenceContent("capture", { content_path: "/arbitrary" });
}
void (undefined as unknown as OldBodies); void (undefined as unknown as ContentResult); void compileOnlyRequiredFence;

const instant = "2026-10-19T00:00:00+00:00";
const pdf = new TextEncoder().encode("%PDF-1.7\nSynthetic R93 SDK original\n%%EOF\n");
const sha = (bytes: Uint8Array | string) => createHash("sha256").update(bytes).digest("hex");
const parsed = { parse_method: "sha256_bound_reviewed_mapping" as const, mapping_id: "xiaomi-su7-first-generation-pdf@1" };
const binary = {
  evidence_format: "raw-evidence-v2" as const, body_encoding: "binary" as const, body: null,
  raw_capture_id: "capture", raw_hash: sha(pdf), byte_count: pdf.byteLength, content_type: "application/pdf" as const,
};
const source = { source_id: "xiaomi-cn-vehicles", source_url: "https://fixture.invalid/original.pdf", parser_version: "reviewed@1", observed_at: instant };
const vehicle: VehicleEvidenceV2 = {
  ...binary, ...parsed, ...source, id: "snapshot", vehicle_id: "xiaomi-su7-first-generation", snapshot_id: "snapshot",
  source_page: "https://fixture.invalid/source", parser_identity: { bundle_id: "c".repeat(64), parser_digest: "a".repeat(64), deployment_revision: 1 },
  evidence_path: "/v1/vehicle-evidence/snapshot", quality_review: null, verified_at: instant, data_state: "local_snapshot",
  documents: [{ url: "https://fixture.invalid/original.pdf", title: null, status: "official_source_link" }],
  content_path: "/v1/vehicle-evidence/snapshot/content?mode=history",
};
const capture: RawCaptureEvidenceV2 = {
  ...binary, ...source, id: "capture", query_id: "query", target_kind: "vehicle", parser_identity: { bundle_id: "c".repeat(64), parser_digest: "a".repeat(64), deployment_revision: 1 },
  query_state: "pending", query_reason: null, query: { vehicle_id: "xiaomi-su7-first-generation" }, processing_unconfirmed: true,
  evidence_path: "/v1/captures/capture?mode=history", data_state: "local_snapshot", receipt_only: true, storage_kind: "object_store",
  content_path: "/v1/captures/capture/content?mode=history", parse_method: null, mapping_id: null,
};
const axle = { size: "245/45R19", load_index: null, speed_rating: null, oe_mark: null, manufacturer_product_code: null, matched_tire_variant_id: null };
const fitment = {
  id: "fitment", trim_id: "trim", trim_name: "Trim", wheel_option_name: "19 inch", wheel_diameter_inches: 19,
  availability: "standard" as const, front: axle, rear: axle, staggered: false, source_tire_description: null,
  constraints: [], source_description: "A source line\nAnother line", evidence_locator: "page=3",
};
const payload: VehicleRawPayloadV2 = {
  vehicle: { id: "xiaomi-su7-first-generation", manufacturer: { id: "xiaomi", name: "Xiaomi" }, model: "SU7", generation: "first", model_year: null, region: "CN", source_vehicle_id: "first" },
  trims: [{ id: "trim", name: "Trim", source_trim_id: "source-trim", model_year: null, wheel_option_ids: ["fitment"] }],
  fitments: [fitment], footnotes: [], documents: [],
  coverage: { axle_sizes: true, wheel_options: true, trim_mapping: true, model_year: false, exact_tire_sku: false, oe_mark: false, notice: "Synthetic coverage" },
  ...parsed, parse_provenance: { contract: "vehicle-pdf-parse@1", method: parsed.parse_method, mapping_id: parsed.mapping_id, source_raw_hash: binary.raw_hash, bundle_id: "c".repeat(64), mapping_file_sha256: "b".repeat(64) },
};
const legacyVehiclePayload = structuredClone(payload);
delete legacyVehiclePayload.parse_method; delete legacyVehiclePayload.mapping_id; delete legacyVehiclePayload.parse_provenance;
const metrics = { baseline_rows: 1, candidate_rows: 1, aligned_rows: 1, lost_rows: 0, row_loss_ratio: 0, known_fields: 10, lost_fields: 4, field_loss_ratio: 0.4 };
const quality = { baseline_rows: 1, candidate_rows: 1, aligned_rows: 1, lost_rows: 0, row_loss_ratio: 0, known_fields: 10, field_loss_ratio: 0.4, ruleset: "synthetic@1", threshold: 0.3, lost_field_count: 4, reason_codes: ["field_loss_threshold"], lost_fields: [], lost_row_keys: [], ambiguous_keys: [] };
const quarantine: QuarantineEvidenceV2 = {
  ...binary, ...parsed, ...source, id: "quarantine", query_id: "query", previous_snapshot_id: "previous", status: "quarantined", kind: "field_loss",
  target_kind: "vehicle", vehicle_id: "xiaomi-su7-first-generation", reason_codes: quality.reason_codes, metrics, candidates: [fitment], quality,
  vehicle_payload: payload, evidence_path: "/v1/quarantines/quarantine?mode=history", data_state: "local_snapshot", accepted: false,
  content_path: "/v1/quarantines/quarantine/content?mode=history",
};
const rejected: QuarantineEvidenceV2 = {
  ...binary, ...source, id: "rejected", query_id: "query", previous_snapshot_id: null, status: "quarantined", kind: "response_rejected",
  target_kind: "vehicle", stage: "parser", reason_codes: ["vehicle_pdf_revision_unreviewed"], metrics: null, candidates: [], quality: null,
  evidence_path: "/v1/quarantines/rejected?mode=history", data_state: "local_snapshot", accepted: false,
  content_path: "/v1/quarantines/rejected/content?mode=history", parse_method: null, mapping_id: null,
};
const textBody = '{"legacy":"文本"}';
const textRaw = { evidence_format: "raw-evidence-v2" as const, body_encoding: "utf-8" as const, body: textBody, raw_capture_id: null, raw_hash: sha(textBody), byte_count: new TextEncoder().encode(textBody).byteLength, content_type: "application/json" as const, content_path: null, parse_method: null, mapping_id: null };
const tire: QuarantineEvidenceV2 = {
  ...textRaw, id: "tire", query_id: "query", source_id: "tire-source", source_url: "https://fixture.invalid/tire", parser_version: "tire@1", observed_at: instant,
  previous_snapshot_id: "previous", status: "quarantined", kind: "field_loss", target_kind: "tire", reason_codes: quality.reason_codes,
  metrics, candidates: [{ brand: "Brand", model: "Model", manufacturer_product_code: null, region: "CN", size: "245/45R19", load_index: null, speed_rating: null, xl: null, hl: null, oe_mark: null, acoustic_technology: null, run_flat: null, source_variant_name: null, facts: { nested_source_fact: { value: 1, labels: ["source"] } } }],
  quality: { ...quality, namespace_reference_alignments: [{ baseline_key: "old", candidate_key: "new", entity_equivalence: false }] }, evidence_path: "/v1/quarantines/tire?mode=history", data_state: "local_snapshot", accepted: false,
};

class CallerContextChanged extends Error {}
let current = true, checks = 0;
const fence: RawEvidenceContextFence = { assertCurrent() { checks++; if (!current) throw new CallerContextChanged(); } };
type Stage = "metadata" | "blob" | "arrayBuffer" | "digest";
let hook: ((stage: Stage) => void) | undefined;
let metadata: any = vehicle, blobStatus = 200, metaStatus = 200, htmlMetadata = false, transportFailure = false;
let original: Blob;
const calls: { path: string; init: RequestInit }[] = [];
function makeBlob(bytes: Uint8Array = pdf, mime = "application/pdf"): Blob {
  const result = new Blob([bytes as BlobPart], { type: mime });
  const arrayBuffer = result.arrayBuffer.bind(result);
  result.arrayBuffer = async () => { const value = await arrayBuffer(); hook?.("arrayBuffer"); return value; };
  return result;
}
const transport: ApiTransport = async (path, init) => {
  calls.push({ path, init });
  if (transportFailure) throw Object.assign(new Error("synthetic transport error"), { code: "request_timeout" });
  const content = path.endsWith("/content?mode=history"), status = content ? blobStatus : metaStatus;
  if (status !== 200) return new Response(JSON.stringify({ detail: { code: status === 503 ? "vehicle_raw_integrity_failed" : "vehicle_original_read_not_allowed" } }), { status, headers: { "Content-Type": "application/json" } });
  if (content) {
    const response = new Response(original);
    response.blob = async () => { hook?.("blob"); return original; };
    return response;
  }
  if (htmlMetadata) return new Response("<html>error page</html>", { headers: { "Content-Type": "text/html" } });
  const response = new Response(JSON.stringify(metadata), { headers: { "Content-Type": "application/json" } });
  response.json = async () => { const value = structuredClone(metadata); hook?.("metadata"); return value; };
  return response;
};
const restore = setApiTransport(transport);
const cryptoDescriptor = Object.getOwnPropertyDescriptor(globalThis, "crypto");
const realDigest = webcrypto.subtle.digest.bind(webcrypto.subtle);
Object.defineProperty(globalThis, "crypto", { configurable: true, value: { subtle: { digest: async (algorithm: string, bytes: ArrayBuffer) => { const result = await realDigest(algorithm, bytes); hook?.("digest"); return result; } } } });
function reset(value: unknown = vehicle, bytes: Uint8Array = pdf) {
  metadata = structuredClone(value); original = makeBlob(bytes); current = true; checks = 0; hook = undefined;
  metaStatus = 200; blobStatus = 200; htmlMetadata = false; transportFailure = false; calls.length = 0;
}
try {
  for (const [fixture, method, contentMethod, endpoint] of [
    [vehicle, tireApi.vehicleEvidenceV2, tireApi.vehicleEvidenceContent, "vehicle-evidence"],
    [capture, tireApi.captureEvidenceV2, tireApi.captureEvidenceContent, "captures"],
    [quarantine, tireApi.quarantineEvidenceV2, tireApi.quarantineEvidenceContent, "quarantines"],
    [rejected, tireApi.quarantineEvidenceV2, tireApi.quarantineEvidenceContent, "quarantines"],
  ] as const) {
    reset(fixture); const controller = new AbortController();
    assert.deepEqual(await method(fixture.id, fence, controller.signal), fixture);
    assert.equal(calls[0].path, `/v1/${endpoint}/${fixture.id}?format=raw-evidence-v2&mode=history`);
    calls.length = 0;
    const result = await contentMethod(fixture.id, fence, controller.signal);
    assert.deepEqual(result.metadata, fixture); assert.equal(result.blob, original); assert(checks > 4);
    assert.deepEqual(calls.map(call => call.path), [`/v1/${endpoint}/${fixture.id}?format=raw-evidence-v2&mode=history`, `/v1/${endpoint}/${fixture.id}/content?mode=history`]);
    for (const call of calls) { assert.equal(call.init.signal, controller.signal); assert.equal(call.init.credentials, "include"); assert.equal(call.init.cache, "no-store"); }
  }
  // All real text branches retain body:string and null parse/path, without PDF fetches.
  const textVehicle = { ...vehicle, ...textRaw, vehicle_id: "legacy-vehicle", parser_identity: null };
  const textCapture = { ...capture, ...textRaw, parser_identity: null, raw_capture_id: "capture", storage_kind: "database_legacy", target_kind: "recall", query: { manufacturer: "source", nested_criteria: { region: "CN" } } };
  const textRejected = { ...rejected, ...textRaw, target_kind: "recall", stage: "schema" };
  for (const [fixture, method, contentMethod] of [
    [textVehicle, tireApi.vehicleEvidenceV2, tireApi.vehicleEvidenceContent], [textCapture, tireApi.captureEvidenceV2, tireApi.captureEvidenceContent],
    [tire, tireApi.quarantineEvidenceV2, tireApi.quarantineEvidenceContent], [textRejected, tireApi.quarantineEvidenceV2, tireApi.quarantineEvidenceContent],
    [{ ...quarantine, ...textRaw, vehicle_id: "legacy-vehicle", vehicle_payload: { ...legacyVehiclePayload, vehicle: { ...legacyVehiclePayload.vehicle, id: "legacy-vehicle" } } }, tireApi.quarantineEvidenceV2, tireApi.quarantineEvidenceContent],
  ] as const) {
    reset(fixture); assert.deepEqual(await method(fixture.id, fence), fixture);
    calls.length = 0; await assert.rejects(contentMethod(fixture.id, fence), (error: unknown) => error instanceof RawEvidenceContractError && error.code === "raw_evidence_content_unavailable");
    assert.equal(calls.length, 1);
  }
  // Legacy SDK methods retain their old paths and body:string responses.
  for (const [method, requestedId, path] of [[tireApi.vehicleEvidence, "snapshot", "/v1/vehicle-evidence/snapshot"], [tireApi.captureEvidence, "capture", "/v1/captures/capture?mode=history"], [tireApi.quarantineEvidence, "tire", "/v1/quarantines/tire?mode=history"]] as const) {
    reset({ body: textBody }); assert.equal((await method(requestedId)).body, textBody); assert.equal(calls[0].path, path);
  }
  // Endpoint schemas stay closed, including required historical envelope fields.
  for (const [fixture, decoder, changes] of [
    [vehicle, assertVehicleEvidenceV2, [(v: any) => { v.extra = 1; }, (v: any) => { delete v.documents; }, (v: any) => { v.snapshot_id = "foreign"; }, (v: any) => { v.quality_review = {}; }]],
    [capture, assertRawCaptureEvidenceV2, [(v: any) => { delete v.storage_kind; }, (v: any) => { delete v.query; }, (v: any) => { v.receipt_only = false; }, (v: any) => { v.raw_capture_id = "foreign"; }, (v: any) => { v.mapping_id = parsed.mapping_id; }]],
    [rejected, assertQuarantineEvidenceV2, [(v: any) => { v.accepted = true; }, (v: any) => { v.candidates = [fitment]; }, (v: any) => { delete v.stage; }, (v: any) => { v.vehicle_payload = payload; }, (v: any) => { v.quality = quality; }]],
    [quarantine, assertQuarantineEvidenceV2, [(v: any) => { delete v.vehicle_payload; }, (v: any) => { v.kind = "response_rejected"; }, (v: any) => { v.vehicle_id = "other"; }, (v: any) => { v.vehicle_payload.parse_provenance.source_raw_hash = "0".repeat(64); }]],
    [tire, assertQuarantineEvidenceV2, [(v: any) => { v.stage = "schema"; }, (v: any) => { v.vehicle_payload = payload; }, (v: any) => { v.quality.namespace_reference_alignments[0].entity_equivalence = true; }]],
  ] as const) for (const change of changes) { const value: any = structuredClone(fixture); change(value); const check: (value: unknown, id: string) => void = decoder; assert.throws(() => check(value, fixture.id), RawEvidenceContractError); }
  for (const change of [
    (v: any) => { v.body = ""; }, (v: any) => { v.raw_capture_id = null; }, (v: any) => { v.raw_hash = "g".repeat(64); },
    (v: any) => { v.byte_count = 0; }, (v: any) => { v.byte_count = 8 * 1024 * 1024 + 1; }, (v: any) => { v.byte_count = 1.5; },
    (v: any) => { v.content_type = "application/json"; }, (v: any) => { v.parse_method = null; }, (v: any) => { v.mapping_id = "current-mapping"; },
    (v: any) => { v.id = "foreign"; }, (v: any) => { v.content_path = "https://fixture.invalid/original.pdf"; },
    (v: any) => { v.content_path = "/v1/captures/snapshot/content?mode=history"; }, (v: any) => { v.content_path = "/v1/vehicle-evidence/foreign/content?mode=history"; },
    (v: any) => { v.content_path += "&other=1"; },
  ]) { const value: any = structuredClone(vehicle); change(value); assert.throws(() => assertVehicleEvidenceV2(value, "snapshot"), RawEvidenceContractError); }
  const oldMapping = structuredClone(quarantine);
  if (oldMapping.kind !== "field_loss" || oldMapping.target_kind !== "vehicle" || oldMapping.body_encoding !== "binary") throw new Error("bad test fixture");
  oldMapping.mapping_id = "xiaomi-su7-first-generation-pdf@2"; oldMapping.vehicle_payload.mapping_id = oldMapping.mapping_id;
  oldMapping.vehicle_payload.parse_provenance!.mapping_id = oldMapping.mapping_id;
  assertQuarantineEvidenceV2(oldMapping, "quarantine");
  const longMapping = { ...vehicle, mapping_id: "xiaomi-su7-first-generation-pdf@1234567890" };
  assert.throws(() => assertVehicleEvidenceV2(longMapping, "snapshot"), RawEvidenceContractError);
  reset(textVehicle); metadata.raw_hash = "0".repeat(64); await assert.rejects(tireApi.vehicleEvidenceV2("snapshot", fence), RawEvidenceContractError);
  reset(textVehicle); metadata.body = "\ud800"; metadata.byte_count = 3; await assert.rejects(tireApi.vehicleEvidenceV2("snapshot", fence), RawEvidenceContractError);
  // Binary Snapshot/Capture identities are non-null; every retained non-null identity and provenance uses hash bundle IDs.
  for (const [fixture, check] of [[vehicle, assertVehicleEvidenceV2], [capture, assertRawCaptureEvidenceV2]] as const) {
    for (const identity of [null, { bundle_id: "bundle", parser_digest: "a".repeat(64), deployment_revision: 1 }, { bundle_id: "C".repeat(64), parser_digest: "a".repeat(64), deployment_revision: 1 }]) {
      const value = { ...fixture, parser_identity: identity }; const decode: (value: unknown, id: string) => void = check;
      assert.throws(() => decode(value, fixture.id), RawEvidenceContractError);
    }
  }
  const invalidProvenance = structuredClone(quarantine);
  if (invalidProvenance.kind !== "field_loss" || invalidProvenance.target_kind !== "vehicle") throw new Error("bad test fixture");
  invalidProvenance.vehicle_payload.parse_provenance!.bundle_id = "bundle";
  assert.throws(() => assertQuarantineEvidenceV2(invalidProvenance, "quarantine"), RawEvidenceContractError);
  reset(textVehicle); metadata.parser_identity = { bundle_id: "bundle", parser_digest: "a".repeat(64), deployment_revision: 1 };
  await assert.rejects(tireApi.vehicleEvidenceV2("snapshot", fence), RawEvidenceContractError);
  // Blob validation checks actual bytes; correct header/hash claims alone never suffice.
  reset(); original = makeBlob(pdf, "text/html"); await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence), RawEvidenceContractError);
  reset(); original = makeBlob(pdf, "application/json"); await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence), RawEvidenceContractError);
  reset(); original = makeBlob(new Uint8Array()); await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence), RawEvidenceContractError);
  reset(); original = makeBlob(new Uint8Array(8 * 1024 * 1024 + 1)); await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence), RawEvidenceContractError);
  reset(); metadata.byte_count++; await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence), RawEvidenceContractError);
  reset(); const tampered = pdf.slice(); tampered[12] ^= 1; original = makeBlob(tampered); await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence), RawEvidenceContractError);
  reset(); const nonPdf = pdf.slice(); nonPdf[0] = 33; original = makeBlob(nonPdf); metadata.raw_hash = sha(nonPdf); await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence), RawEvidenceContractError);
  reset(); original.arrayBuffer = async () => pdf.slice(1).buffer as ArrayBuffer; await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence), RawEvidenceContractError);
  // Required fence is enforced at runtime before any request, for all six methods.
  for (const method of [tireApi.vehicleEvidenceV2, tireApi.captureEvidenceV2, tireApi.quarantineEvidenceV2, tireApi.vehicleEvidenceContent, tireApi.captureEvidenceContent, tireApi.quarantineEvidenceContent]) {
    reset(); await assert.rejects((method as any)("snapshot"), RawEvidenceContractError); assert.equal(calls.length, 0);
    await assert.rejects((method as any)("snapshot", { assertCurrent: 1 }), RawEvidenceContractError); assert.equal(calls.length, 0);
    await assert.rejects((method as any)("snapshot", { assertCurrent: async () => {} }), RawEvidenceContractError); assert.equal(calls.length, 0);
  }
  reset(); current = false; await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence), CallerContextChanged); assert.equal(calls.length, 0);
  reset(); const alreadyAborted = new AbortController(); alreadyAborted.abort(); await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence, alreadyAborted.signal), { name: "AbortError" }); assert.equal(calls.length, 0);
  // Account fence, cancellation and transport replacement fail at every asynchronous boundary.
  for (const stage of ["metadata", "blob", "arrayBuffer", "digest"] as const) {
    reset(); hook = at => { if (at === stage) current = false; }; await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence), CallerContextChanged);
    reset(); const controller = new AbortController(); hook = at => { if (at === stage) controller.abort(); }; await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence, controller.signal), { name: "AbortError" });
    reset(); hook = at => { if (at === stage) { const undo = setApiTransport(transport); undo(); } }; await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence), RawEvidenceContextError);
  }
  reset(); hook = at => { if (at === "metadata") current = false; }; await assert.rejects(tireApi.vehicleEvidenceV2("snapshot", fence), CallerContextChanged);
  // A context change after hashing still refuses a returned verified result.
  reset(); let staleAfterDigest = false;
  const finalFence = { assertCurrent() { if (staleAfterDigest) throw new CallerContextChanged(); } };
  hook = at => { if (at === "digest") staleAfterDigest = true; };
  await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", finalFence), CallerContextChanged);
  // HTTP errors keep ApiError status/code; a successful HTML/JSON error page is never a PDF Blob.
  for (const status of [401, 403, 404, 409, 422, 503]) for (const at of ["metadata", "blob"]) {
    reset(); if (at === "metadata") metaStatus = status; else blobStatus = status;
    await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence), (error: unknown) => error instanceof ApiError && error.status === status);
  }
  reset(); htmlMetadata = true; await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence));
  reset(); original = makeBlob(new TextEncoder().encode('{"detail":{"code":"forbidden"}}'), "application/json"); await assert.rejects(tireApi.vehicleEvidenceContent("snapshot", fence), RawEvidenceContractError);
  reset(); transportFailure = true; await assert.rejects(tireApi.vehicleEvidenceV2("snapshot", fence), (error: unknown) => error instanceof ApiTransportError && error.code === "api_timeout");
  console.log("R93 synthetic SDK assertions completed; this is not real HTTP, UI or Native acceptance.");
} finally {
  restore();
  if (cryptoDescriptor) Object.defineProperty(globalThis, "crypto", cryptoDescriptor);
  else Reflect.deleteProperty(globalThis, "crypto");
}
