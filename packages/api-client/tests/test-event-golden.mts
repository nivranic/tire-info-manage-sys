/** R119 SDK contract only: injected transport, no API, database, PDF or browser. */
import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, setApiTransport, tireApi } from "@tire/api-client";
import type { TestEventGoldenContent, TestEventGoldenEvaluateRequest, TestEventGoldenMaterial,
  TestEventGoldenReviewRequest, TestEventGoldenSetWrite } from "@tire/domain-types";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type ContentKeys = Assert<Equal<keyof TestEventGoldenContent,
  "title" | "event_ref" | "materials" | "link_refs" | "expected" | "evidence_note" | "operator" | "reason" | "expected_revision" | "expected_fingerprint">>;
type ReviewKeys = Assert<Equal<keyof TestEventGoldenReviewRequest,
  "case_revision" | "case_fingerprint" | "action" | "acknowledged" | "opened_materials" | "operator" | "reason" | "expected_revision" | "expected_fingerprint">>;
type SetKeys = Assert<Equal<keyof TestEventGoldenSetWrite,
  "title" | "action" | "case_refs" | "acknowledged" | "operator" | "reason" | "expected_revision" | "expected_fingerprint">>;
// @ts-expect-error Actor identity comes from the server session.
const actorOverride: keyof TestEventGoldenContent = "actor_user_id";
// @ts-expect-error No inline PDF bytes are accepted as a material reference.
const inlineBytes: keyof TestEventGoldenMaterial = "body";

const sha = "a".repeat(64), metadataSha = "b".repeat(64), key = "971986a7-8d8c-42f8-9664-a2261d30f22a";
const material: TestEventGoldenMaterial = { document_id: "doc-1", expected_raw_hash: sha, expected_metadata_hash: metadataSha,
  event_locator: { page: 2, region: "event heading", quote: "synthetic event" },
  participant_locator: { page: 3, region: "measurement row", quote: "synthetic result" },
  rights: { rights_holder: "Synthetic holder", basis: "Synthetic workspace permission", store_original: true,
    workspace_reopen: true, quote_identifiers: true, quote_test_results: true } };
const event = { title: "Synthetic event", organization: "Synthetic org", relationship: "unknown" as const,
  publication_date: null, source_url: "https://fixture.invalid/synthetic", rights_basis: "Synthetic permission",
  tested_size: "245/40R20", vehicle: null, surface: null, conditions: "Synthetic conditions",
  coverage: "selected_results" as const, reported_participants: null,
  participants: [{ key: "p1", brand: "Synthetic", model: "Model", source_designation: "" }],
  metrics: [{ key: "braking", label: "Braking", unit: "m", protocol: "Synthetic method", direction: "lower" as const }],
  measurements: [{ participant_key: "p1", metric_key: "braking", raw_value: "-0.00", source_rank: null,
    evidence_span: "Synthetic literal -0.00", evidence_locator: "page 3 row A" }] };
const content: TestEventGoldenContent = { title: "Synthetic Golden", event_ref: { event_id: "event/?1", event_revision_id: "event-r1", event_fingerprint: sha },
  materials: [material], link_refs: [], expected: { event, identity_assertions: [{ participant_key: "p1", truth: "unknown", sku_label: null, expected_variant_id: null }], distinct_pairs: [] },
  evidence_note: "Synthetic source page 3", operator: "Synthetic author", reason: "Synthetic contract", expected_revision: 0, expected_fingerprint: null };
const review: TestEventGoldenReviewRequest = { case_revision: 1, case_fingerprint: sha, action: "approve", acknowledged: true,
  opened_materials: [{ document_id: material.document_id, raw_hash: sha, metadata_hash: metadataSha }],
  operator: "Synthetic reviewer", reason: "Synthetic review", expected_revision: 0, expected_fingerprint: null };
const setWrite: TestEventGoldenSetWrite = { title: "Synthetic set", action: "freeze", case_refs: [{ case_id: "case/?1",
  case_revision: 1, case_fingerprint: sha, review_revision: 1, review_fingerprint: metadataSha }],
  acknowledged: true, operator: "Synthetic freezer", reason: "Synthetic freeze", expected_revision: 0, expected_fingerprint: null };
const evaluate: TestEventGoldenEvaluateRequest = { expected_set_revision: 1, expected_set_fingerprint: sha, target: "current_head" };
type Call = { path: string; init: RequestInit };
async function withTransport<T>(response: unknown, work: (calls: Call[]) => Promise<T>, status = 200): Promise<T> {
  const calls: Call[] = [];
  const restore = setApiTransport(async (path, init) => { calls.push({ path, init });
    if (init.signal?.aborted) throw new DOMException("Synthetic abort", "AbortError");
    return new Response(JSON.stringify(response), { status }); });
  try { return await work(calls); } finally { restore(); }
}
function assertTransport(call: Call, method: string, path: string, signal?: AbortSignal) {
  assert.equal(call.path, path); assert.equal(call.init.method || "GET", method);
  assert.equal(call.init.credentials, "include"); assert.equal(call.init.cache, "no-store"); assert.equal(call.init.signal, signal);
}

test("case and set reads use history mode, encode ids and preserve requested revision", async () => {
  const abort = new AbortController();
  await withTransport({ items: [], total: 0, offset: 10, limit: 10 }, async calls => {
    await tireApi.testEventGoldenCases("event/?1", abort.signal, 10);
    await tireApi.testEventGoldenCases(undefined, abort.signal, 20);
    await tireApi.testEventGoldenSets(abort.signal, 10);
    assertTransport(calls[0], "GET", "/v1/test-event-golden/cases?mode=history&event_id=event%2F%3F1&offset=10&limit=10", abort.signal);
    assertTransport(calls[1], "GET", "/v1/test-event-golden/cases?mode=history&offset=20&limit=10", abort.signal);
    assertTransport(calls[2], "GET", "/v1/test-event-golden/sets?mode=history&offset=10&limit=10", abort.signal);
  });
  await withTransport({}, async calls => {
    await tireApi.testEventGoldenCase("case/?1", abort.signal, 2);
    await tireApi.testEventGoldenSet("set/?1", abort.signal, 3);
    assertTransport(calls[0], "GET", "/v1/test-event-golden/cases/case%2F%3F1?mode=history&revision=2", abort.signal);
    assertTransport(calls[1], "GET", "/v1/test-event-golden/sets/set%2F%3F1?mode=history&revision=3", abort.signal);
  });
});

test("all five writes keep caller UUID and exact frozen body", async () => {
  const abort = new AbortController();
  const revised = { ...content, expected_revision: 1, expected_fingerprint: sha };
  const revisedSet = { ...setWrite, action: "revoke" as const, case_refs: [], expected_revision: 1, expected_fingerprint: sha };
  const writes = [
    [() => tireApi.testEventGoldenCreateCase(content, key, abort.signal), "/v1/test-event-golden/cases", content],
    [() => tireApi.testEventGoldenReviseCase("case/?1", revised, key, abort.signal), "/v1/test-event-golden/cases/case%2F%3F1/revisions", revised],
    [() => tireApi.testEventGoldenReviewCase("case/?1", review, key, abort.signal), "/v1/test-event-golden/cases/case%2F%3F1/reviews", review],
    [() => tireApi.testEventGoldenCreateSet(setWrite, key, abort.signal), "/v1/test-event-golden/sets", setWrite],
    [() => tireApi.testEventGoldenReviseSet("set/?1", revisedSet, key, abort.signal), "/v1/test-event-golden/sets/set%2F%3F1/revisions", revisedSet],
  ] as const;
  await withTransport({}, async calls => {
    for (const [write] of writes) await write();
    writes.forEach(([, path, payload], index) => { const call = calls[index]; assertTransport(call, "POST", path, abort.signal);
      assert.equal(new Headers(call.init.headers).get("Idempotency-Key"), key);
      assert.deepEqual(JSON.parse(String(call.init.body)), payload); });
    assert.equal((JSON.parse(String(calls[0].init.body)) as TestEventGoldenContent).expected.event.measurements[0].raw_value, "-0.00");
    assert.equal((JSON.parse(String(calls[0].init.body)) as TestEventGoldenContent).materials[0].rights.quote_test_results, true);
  });
});

test("evaluation is a history-scoped read-only POST without a write UUID", async () => {
  await withTransport({ schema: "test-event-golden-evaluation@1", human_truth_status: "pending_external_review", wrong_merge_count: null }, async calls => {
    const result = await tireApi.testEventGoldenEvaluateSet("set/?1", evaluate);
    assert.equal(result.human_truth_status, "pending_external_review"); assert.equal(result.wrong_merge_count, null);
    assertTransport(calls[0], "POST", "/v1/test-event-golden/sets/set%2F%3F1/evaluate?mode=history");
    assert.equal(new Headers(calls[0].init.headers).has("Idempotency-Key"), false);
    assert.deepEqual(JSON.parse(String(calls[0].init.body)), evaluate);
  });
});

test("rejected or ambiguous writes are surfaced once, without a new UUID", async () => {
  await withTransport({ detail: { code: "golden_case_stale" } }, async calls => {
    await assert.rejects(tireApi.testEventGoldenCreateCase(content, key), cause => cause instanceof ApiError && cause.code === "golden_case_stale");
    assert.equal(calls.length, 1);
  }, 409);
  let calls = 0; const restore = setApiTransport(async () => { calls++; throw new TypeError("Synthetic transport interruption"); });
  try { await assert.rejects(tireApi.testEventGoldenReviewCase("case-1", review, key), TypeError); assert.equal(calls, 1); }
  finally { restore(); }
});
