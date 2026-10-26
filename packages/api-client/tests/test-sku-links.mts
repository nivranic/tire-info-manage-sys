/** Public R71 SDK contract: injected transport, no server, source, PDF parser or model. */
import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, setApiTransport, tireApi } from "@tire/api-client";
import type {
  BridgeDecision, BridgeMaterial, BridgePreviewRequest, BridgeSelection, BridgeBoundary,
  BridgeHistoryItem, BridgeMaterialsPage, TestSkuLinkDetail, TestSkuLinkPage, TestSkuLinkPreview,
} from "@tire/domain-types";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type PreviewKeys = Assert<Equal<keyof BridgePreviewRequest, "mode" | "action" | "link_id" | "selection" | "materials" | "assertions" | "evidence_level">>;
type SelectionKeys = Assert<Equal<keyof BridgeSelection, "event_id" | "event_revision_id" | "participant_key" | "variant_id" | "tire_snapshot_id" | "fact_version_id">>;
type DecisionKeys = Assert<Equal<keyof BridgeDecision, keyof BridgePreviewRequest | "expected_revision" | "expected_fingerprint" | "declaration_revision_id" | "operator" | "reason" | "acknowledged" | "opened_materials" | "confirmed_event_revision_id" | "confirmed_participant_hash">>;
type PreviewResult = Assert<Equal<Awaited<ReturnType<typeof tireApi.previewTestSkuLink>>, TestSkuLinkPreview>>;
type DetailResult = Assert<Equal<Awaited<ReturnType<typeof tireApi.testSkuLink>>, TestSkuLinkDetail>>;
type ListingHasNoHistory = Assert<Equal<"history" extends keyof TestSkuLinkPage["items"][number] ? true : false, false>>;
// @ts-expect-error Actor identity is server derived, never a request override.
const actorOverride: keyof BridgeDecision = "actor_user_id";
// @ts-expect-error A client cannot promote origin verification.
const verificationOverride: keyof BridgePreviewRequest = "origin_verification";
// @ts-expect-error Materials refer to a frozen document, never inline PDF bytes.
const inlineOriginal: keyof BridgeMaterial = "body";

const h = "a".repeat(64), mh = "b".repeat(64);
const selection: BridgeSelection = { event_id: "synthetic/event?x", event_revision_id: "event-r7", participant_key: "p1", variant_id: "synthetic-sku", tire_snapshot_id: "original-tire-snapshot", fact_version_id: "original-fact-version" };
const material: BridgeMaterial = { document_id: "synthetic-doc", expected_raw_hash: h, expected_metadata_hash: mh,
  event_locator: { page: 2, region: "Original event heading", quote: "Synthetic event 2026" },
  participant_locator: { page: 3, region: "Original row A", quote: "Synthetic P1" },
  rights: { rights_holder: "Synthetic rights holder", basis: "Synthetic workspace and quote permission", store_original: true, workspace_reopen: true, quote_identifiers: true } };
const request: BridgePreviewRequest = { mode: "history", action: "create", link_id: null, selection, materials: [material],
  assertions: [{ field: "run_flat", material_document_id: material.document_id, material_value: false, quote: "明确否 / false", page: 3, region: "row A" },
    { field: "manufacturer_product_code", material_document_id: material.document_id, material_value: "000123", quote: "000123", page: 3, region: "row A" }], evidence_level: "source_explicit_identifiers_in_supplied_material" };
const boundary: BridgeBoundary = { material_origin: "operator_supplied", origin_verification: "unverified", read_scope: "local_workspace", test_record_kind: "manual_transcription", test_verification: "unverified", provider_use: false, export: false, notice: "Synthetic supplied material, not online verification or recommendation" };
const metadata = { id: material.document_id, raw_hash: h, byte_count: 98, title: "Synthetic PDF", source_url: "https://fixture.example/material", operator: "Synthetic submitter", rights_basis: "Synthetic permission", content_type: "application/pdf", created_at: "2026-10-18T12:00:00+00:00", status: "unparsed_receipt" as const, accepted_as_facts: false as const };
const preview: TestSkuLinkPreview = {
  schema: "test-sku-link@1", scope: "local_workspace", data_state: "local_snapshot", id: null, revision: 0, revision_id: null,
  review_state: null, effective_state: "pending_review", eligibility: "none", boundary, selection, materials: request.materials,
  assertions: request.assertions.map(item => ({ ...item, quote_sha256: h })), evidence_level: request.evidence_level,
  frozen_evidence: {
    test: { event_id: selection.event_id, revision_id: selection.event_revision_id, revision: 7, state: "active", fingerprint: h, participant_hash: mh, participant_present: true,
      participant: { key: "p1", brand: "Synthetic", model: "P1", source_designation: "Original description" },
      event: { title: "Synthetic event", organization: "Synthetic org", relationship: "unknown", publication_date: null, source_url: "https://fixture.example/test", rights_basis: "Synthetic permission", tested_size: "245/40ZR20", vehicle: null, surface: null, conditions: "Synthetic conditions", coverage: "selected_results", reported_participants: null, participants: [], metrics: [], measurements: [] } },
    tire: { variant_id: selection.variant_id, snapshot_id: selection.tire_snapshot_id, source_id: "synthetic-source", query_key: h, raw_hash: h,
      identity_contract_version: "variant-identity@2", identity: { manufacturer_product_code: "000123", run_flat: false }, identity_key: "synthetic-key", identity_status: "exact",
      facts: { original_value: "38.00", explicit_false: false }, facts_hash: h, fact_version_id: selection.fact_version_id, fact_version: 3, snapshot_member: { original: true }, parsed_variants_hash: mh,
      structured_locator: { json_pointer: "/variants/0" }, provenance: { snapshot_id: selection.tire_snapshot_id, source_id: "synthetic-source", source_url: "https://fixture.example/tire", parser_version: "synthetic@1", observed_at: metadata.created_at, raw_hash: h } },
  },
  material_evidence: [{ document_id: material.document_id, metadata, raw_hash: h, metadata_hash: mh,
    event_locator: { ...material.event_locator, quote_sha256: h }, participant_locator: { ...material.participant_locator, quote_sha256: h }, rights: material.rights,
    material_origin: "operator_supplied", origin_verification: "unverified", read_scope: "local_workspace" }],
  checks: [{ field: "run_flat", status: "match", material_value: false, sku_value: false }], required_identity_fields: ["run_flat"], unknown_fields: [], blockers: [], stale_reasons: [], binding_hash: mh, fingerprint: h,
  declared_by_user_id: "synthetic-declarer", declaration_revision_id: null, allowed_actions: ["create"], can_submit: true,
  confirmed_participant_hash: mh, confirmed_event_revision_id: selection.event_revision_id,
};
const history: BridgeHistoryItem = { revision_id: "link-r1", revision: 1, action: "create", review_state: "pending_review", declaration_revision_id: "link-r1", declared_by_user_id: "synthetic-declarer", actor_user_id: "synthetic-declarer", operator: "Synthetic declaration", reason: "Synthetic contract only", created_at: metadata.created_at, fingerprint: h };
const { can_submit: _canSubmit, ...savedView } = preview;
const detail: TestSkuLinkDetail = { ...savedView, id: "synthetic/link?x", revision: 1, revision_id: "link-r1", review_state: "pending_review", declared_by_user_id: "synthetic-declarer", declaration_revision_id: "link-r1", history: [history], history_truncated: false };
const decision: BridgeDecision = { ...request, expected_revision: 0, expected_fingerprint: preview.fingerprint, declaration_revision_id: null, operator: "Synthetic declaration", reason: "Synthetic contract only", acknowledged: true,
  opened_materials: [{ document_id: material.document_id, raw_hash: h, metadata_hash: mh }], confirmed_event_revision_id: selection.event_revision_id, confirmed_participant_hash: mh };
type Call = { path: string; init: RequestInit };
async function withTransport<T>(response: unknown, work: (calls: Call[]) => Promise<T>, status = 200) {
  const calls: Call[] = [];
  const restore = setApiTransport(async (path, init) => {
    calls.push({ path, init });
    if (init.signal?.aborted) throw new DOMException("Synthetic cancelled", "AbortError");
    return new Response(JSON.stringify(response), { status });
  });
  try { return await work(calls); } finally { restore(); }
}
function assertPrivateTransport(call: Call, signal?: AbortSignal) {
  assert.equal(call.init.credentials, "include"); assert.equal(call.init.cache, "no-store"); assert.equal(call.init.signal, signal);
}

test("materials metadata pagination does not fetch or parse a PDF", async () => {
  const page: BridgeMaterialsPage = { scope: "local_workspace", items: [{ ...metadata, metadata_hash: mh }], offset: 20, total: 21, boundary };
  await withTransport(page, async calls => { const result = await tireApi.testSkuLinkMaterials(20); assert.deepEqual(result, page); assert.equal(calls.length, 1); assert.equal(calls[0].path, "/v1/test-sku-links/materials?mode=history&offset=20"); assertPrivateTransport(calls[0]); assert.equal(result.items[0].metadata_hash, mh); });
});
test("shared link list binds encoded event and explicit page", async () => {
  const { history: _history, history_truncated: _truncated, ...summary } = detail;
  const page: TestSkuLinkPage = { schema: "test-sku-link@1", scope: "local_workspace", items: [summary], offset: 20, total: 21, boundary };
  await withTransport(page, async calls => { const result = await tireApi.testSkuLinks(selection.event_id, 20); assert.deepEqual(result, page); assert.equal("history" in result.items[0], false); assert.equal("history_truncated" in result.items[0], false); assert.equal(calls[0].path, "/v1/test-sku-links?mode=history&event_id=synthetic%2Fevent%3Fx&offset=20"); assertPrivateTransport(calls[0]); });
});
test("exact historical read preserves revision and original references", async () => {
  const abort = new AbortController();
  await withTransport(detail, async calls => { const value = await tireApi.testSkuLink(detail.id!, abort.signal, 1); assert.equal(calls[0].path, "/v1/test-sku-links/synthetic%2Flink%3Fx?mode=history&revision=1"); assertPrivateTransport(calls[0], abort.signal); assert.equal(value.selection.tire_snapshot_id, "original-tire-snapshot"); assert.equal(value.history[0].declared_by_user_id, "synthetic-declarer"); });
});
test("current read does not invent a revision or silently redirect the id", async () => {
  await withTransport(detail, async calls => { await tireApi.testSkuLink(detail.id!); assert.equal(calls[0].path, "/v1/test-sku-links/synthetic%2Flink%3Fx?mode=history"); assert.equal(calls.length, 1); });
});
test("preview sends the complete closed declaration and no actor or UUID", async () => {
  const abort = new AbortController(), before = structuredClone(request);
  await withTransport(preview, async calls => { assert.deepEqual(await tireApi.previewTestSkuLink(request, abort.signal), preview); const call = calls[0]; assert.equal(call.path, "/v1/test-sku-links/preview"); assert.equal(call.init.method, "POST"); assertPrivateTransport(call, abort.signal); assert.deepEqual(JSON.parse(String(call.init.body)), request); assert.equal(new Headers(call.init.headers).has("Idempotency-Key"), false); assert.deepEqual(request, before); });
});
test("literal false, original zero-prefixed code and both material locators survive", async () => {
  await withTransport(preview, async calls => { const value = await tireApi.previewTestSkuLink(request); const sent = JSON.parse(String(calls[0].init.body)) as BridgePreviewRequest; assert.equal(sent.assertions[0].material_value, false); assert.equal(sent.assertions[1].material_value, "000123"); assert.equal(value.material_evidence[0].event_locator.page, 2); assert.equal(value.material_evidence[0].participant_locator.page, 3); assert.equal(value.material_evidence[0].participant_locator.quote_sha256, h); assert.equal(value.frozen_evidence.tire.facts.original_value, "38.00"); });
});
test("decision uses fixed UUID, declaration identity and exact opened material set", async () => {
  const key = "158bb3b6-ed8a-4b9f-9161-a1588e4ef12f", abort = new AbortController();
  await withTransport({ link: detail, event: history, idempotent_replay: true }, async calls => { const first = await tireApi.decideTestSkuLink(decision, key, abort.signal); await tireApi.decideTestSkuLink(decision, key, abort.signal); assert.equal(first.idempotent_replay, true); assert.equal(first.link.revision_id, "link-r1"); for (const call of calls) { assert.equal(call.path, "/v1/test-sku-links/decisions"); assert.equal(call.init.method, "POST"); assertPrivateTransport(call, abort.signal); assert.equal(new Headers(call.init.headers).get("Idempotency-Key"), key); assert.deepEqual(JSON.parse(String(call.init.body)), decision); } assert.equal(calls.length, 2); assert.equal(String(calls[0].init.body), String(calls[1].init.body)); });
});
test("review retains original declaration revision and does not override its actor", async () => {
  const review: BridgeDecision = { ...decision, action: "review", link_id: detail.id, expected_revision: 1, declaration_revision_id: "link-r1" };
  await withTransport({ link: detail, event: history, idempotent_replay: false }, async calls => { await tireApi.decideTestSkuLink(review, "synthetic-review-key"); const sent = JSON.parse(String(calls[0].init.body)); assert.equal(sent.declaration_revision_id, "link-r1"); assert.deepEqual(sent.opened_materials, decision.opened_materials); assert.equal("actor_user_id" in sent, false); });
});
test("insufficient applicability remains none and never promotes source verification", async () => {
  await withTransport(preview, async () => { const value = await tireApi.previewTestSkuLink(request); assert.equal(value.eligibility, "none"); assert.equal(value.boundary.origin_verification, "unverified"); assert.equal(value.boundary.provider_use, false); assert.equal(value.boundary.export, false); assert.equal(value.evidence_level, "source_explicit_identifiers_in_supplied_material"); });
});
test("stale or forbidden writes expose server code and are not automatically retried", async () => {
  for (const [status, code] of [[409, "bridge_preview_stale"], [403, "admin_required"], [409, "bridge_self_review_forbidden"], [422, "bridge_material_invalid"]] as const) {
    await withTransport({ detail: { code, message: "Synthetic rejection" } }, async calls => { await assert.rejects(tireApi.decideTestSkuLink(decision, "fixed-key"), cause => cause instanceof ApiError && cause.status === status && cause.code === code); assert.equal(calls.length, 1); }, status);
  }
});
test("cancelled preview and write preserve AbortError and use caller signal", async () => {
  const abort = new AbortController(); abort.abort();
  await withTransport(preview, async calls => { await assert.rejects(tireApi.previewTestSkuLink(request, abort.signal), cause => cause instanceof DOMException && cause.name === "AbortError"); await assert.rejects(tireApi.decideTestSkuLink(decision, "fixed-key", abort.signal), cause => cause instanceof DOMException && cause.name === "AbortError"); calls.forEach(call => assert.equal(call.init.signal, abort.signal)); });
});
test("ambiguous transport failure is not retried or turned into a new declaration", async () => {
  let calls = 0;
  const restore = setApiTransport(async () => { calls++; throw new TypeError("Synthetic network interruption"); });
  try { await assert.rejects(tireApi.decideTestSkuLink(decision, "fixed-key"), TypeError); assert.equal(calls, 1); } finally { restore(); }
});
