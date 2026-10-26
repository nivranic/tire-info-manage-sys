/** R98 contract/authority targets. Written only; execution requires a separately reviewed wrapper. */
import assert from "node:assert/strict";
import {
  ApiError, ApiTransportError, QuarantineReviewContractError, QuarantineReviewContextError,
  assertBinaryQuarantineReviewStateV2, setApiTransport, tireApi,
} from "@tire/api-client";
import type { RawEvidenceContextFence } from "@tire/api-client";
import type {
  BinaryQuarantinePayloadV2, BinaryQuarantineReviewRequestV2, BinaryQuarantineReviewStateV2,
  QuarantineReviewRequest, QuarantineReviewState,
} from "@tire/domain-types";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type ReadResult = Assert<Equal<Awaited<ReturnType<typeof tireApi.quarantineReviewV2>>, BinaryQuarantineReviewStateV2>>;
type WriteResult = Assert<Equal<Awaited<ReturnType<typeof tireApi.reviewQuarantineV2>>, BinaryQuarantineReviewStateV2>>;
type LegacyWrite = Assert<Equal<Parameters<typeof tireApi.reviewQuarantine>[1], QuarantineReviewRequest>>;
type LegacyRead = Assert<Equal<Awaited<ReturnType<typeof tireApi.quarantineReview>>, QuarantineReviewState>>;
void (undefined as unknown as ReadResult); void (undefined as unknown as WriteResult);
void (undefined as unknown as LegacyWrite); void (undefined as unknown as LegacyRead);
function compileOnlyRequiredArguments() {
  // @ts-expect-error V2 reads require the caller's synchronous authority fence.
  void tireApi.quarantineReviewV2("quarantine");
  // @ts-expect-error Writes also require the expected account and fence.
  void tireApi.reviewQuarantineV2("quarantine", body());
  // @ts-expect-error Confirmation is the literal true, independent of the old boolean DTO.
  const bad: BinaryQuarantineReviewRequestV2 = { ...body(), confirmed_loss: false };
  void bad;
}
void compileOnlyRequiredArguments;

const method = "sha256_bound_reviewed_mapping" as const;
const instant = "2026-10-20T00:00:00+00:00";
function payload(rawHash = "a".repeat(64), bundle = "b".repeat(64), revision = 2): BinaryQuarantinePayloadV2 {
  const axle = { size: "245/45R19", load_index: null, speed_rating: null, oe_mark: null, manufacturer_product_code: null, matched_tire_variant_id: null };
  return {
    vehicle: { id: "xiaomi-su7-first-generation", manufacturer: { id: "xiaomi", name: "Xiaomi" }, model: "SU7", generation: "first", model_year: null, region: "CN", source_vehicle_id: "first" },
    trims: [{ id: "trim", name: "Trim", source_trim_id: "source-trim", model_year: null, wheel_option_ids: ["fitment"] }],
    fitments: [{ id: "fitment", trim_id: "trim", trim_name: "Trim", wheel_option_name: "19 inch", wheel_diameter_inches: 19, availability: "standard",
      front: { ...axle }, rear: { ...axle }, staggered: false, source_tire_description: null, constraints: [], source_description: "Source line\nSecond line", evidence_locator: "page=3" }],
    footnotes: [], documents: [],
    coverage: { axle_sizes: true, wheel_options: true, trim_mapping: true, model_year: false, exact_tire_sku: false, oe_mark: false, notice: "Synthetic evidence only" },
    parse_method: method, mapping_id: `xiaomi-su7-first-generation-pdf@${revision}`,
    parse_provenance: { contract: "vehicle-pdf-parse@1", method, mapping_id: `xiaomi-su7-first-generation-pdf@${revision}`,
      source_raw_hash: rawHash, bundle_id: bundle, mapping_file_sha256: "c".repeat(64) },
  };
}
function fixture(): BinaryQuarantineReviewStateV2 {
  const candidate = payload();
  return {
    quarantine_id: "quarantine", scope: "local_workspace", state: "pending", revision: 0, can_approve: true, restriction: null,
    baseline_snapshot_id: "baseline", current_snapshot_id: "baseline", applied_query_id: null,
    comparison: { before: payload("d".repeat(64), "e".repeat(64), 1), candidate }, history: [], history_truncated: false,
    evidence_format: "raw-evidence-v2", binding_contract: "vehicle-binary@1", binding_hash: "f".repeat(64),
    raw_evidence: { body_encoding: "binary", body: null, raw_capture_id: "capture", raw_hash: "a".repeat(64), byte_count: 42,
      content_type: "application/pdf", source_url: "https://fixture.invalid/original.pdf", parser_version: "reviewed@2",
      parser_identity: { bundle_id: "b".repeat(64), parser_digest: "1".repeat(64), deployment_revision: 2 },
      parse_provenance: structuredClone(candidate.parse_provenance) },
  };
}
function body(): BinaryQuarantineReviewRequestV2 {
  return { action: "approve", expected_revision: 0, operator: "Operator", reason: "Reviewed explicit loss", confirmed_loss: true, expected_binding_hash: "f".repeat(64) };
}
function event(revision = 1) {
  return { id: `review_${revision}`, quarantine_id: "another_same_binding_quarantine", revision, action: "keep_quarantined" as const,
    operator: " \r\n\t😀", reason: " \r\n\t😀", created_at: instant, expires_at: "2026-10-21T00:00:00+00:00" };
}
class CallerChanged extends Error {}
let current = true;
const fence: RawEvidenceContextFence = { assertCurrent() { if (!current) throw new CallerChanged(); } };
const calls: { path: string; init: RequestInit }[] = [];
let responseValue: unknown = fixture(), status: number | undefined, errorBody: unknown;
let transportFailure: unknown, jsonFailure: unknown;
let afterTransport: (() => void) | undefined, beforeJson: (() => void) | undefined, afterJson: (() => void) | undefined;
let pendingJson: Promise<unknown> | undefined;
const restore = setApiTransport(async (path, init) => {
  calls.push({ path, init });
  if (transportFailure) throw transportFailure;
  const response = new Response(JSON.stringify(errorBody ?? responseValue), { status: status ?? (init.method === "POST" ? 201 : 200), headers: { "Content-Type": "application/json" } });
  const read = response.json.bind(response);
  response.json = async () => {
    beforeJson?.();
    if (jsonFailure) throw jsonFailure;
    const result = pendingJson ? await pendingJson : await read();
    afterJson?.(); return result;
  };
  afterTransport?.(); return response;
});
function reset(value: unknown = fixture()) {
  current = true; calls.length = 0; responseValue = value; status = undefined; errorBody = undefined;
  transportFailure = undefined; jsonFailure = undefined; afterTransport = undefined; beforeJson = undefined; afterJson = undefined; pendingJson = undefined;
}
const get = (signal?: AbortSignal) => tireApi.quarantineReviewV2("quarantine", fence, signal);
const post = (value = body(), signal?: AbortSignal) => tireApi.reviewQuarantineV2("quarantine", value, "account_A", fence, signal);
const rejectsContract = async (operation: () => Promise<unknown>) => assert.rejects(operation, QuarantineReviewContractError);

try {
  reset(); const controller = new AbortController();
  assert.deepEqual(await get(controller.signal), fixture());
  assert.equal(calls[0].path, "/v1/quarantines/quarantine/review?mode=history&format=raw-evidence-v2");
  assert.equal(calls[0].init.signal, controller.signal);
  assert.equal(calls[0].init.credentials, "include"); assert.equal(calls[0].init.cache, "no-store");
  assert.deepEqual([...new Headers(calls[0].init.headers)], []);

  reset(); await post(body(), controller.signal);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, "/v1/quarantines/quarantine/reviews?mode=history&format=raw-evidence-v2");
  assert.equal(calls[0].init.method, "POST"); assert.equal(calls[0].init.signal, controller.signal);
  assert.deepEqual([...new Headers(calls[0].init.headers)], [["content-type", "application/json"], ["x-tire-expected-account", "account_A"]]);
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), body());
  assert.equal(Object.keys(JSON.parse(String(calls[0].init.body))).length, 6);

  // The real API retains whitespace and multiline DescriptionText, counted as Unicode code points.
  for (const operator of [" ", "\r\n\t", "😀".repeat(80)]) {
    const request = { ...body(), operator, reason: "😀".repeat(2000) };
    reset(); await post(request); assert.deepEqual(JSON.parse(String(calls[0].init.body)), request);
  }
  const latest = fixture(); latest.revision = 7; latest.state = "kept_quarantined"; latest.history = [event(7), event(6)];
  reset(latest); assert.deepEqual(await post(), latest); // No expected+1, same-action, actor or same-Q inference.
  latest.history[0].operator = " "; latest.history[0].reason = "     ";
  assertBinaryQuarantineReviewStateV2(latest, "quarantine");
  latest.history[0].operator = "😀".repeat(80); latest.history[0].reason = "😀".repeat(2000);
  assertBinaryQuarantineReviewStateV2(latest, "quarantine");
  assertBinaryQuarantineReviewStateV2(fixture(), "quarantine"); // Independent baseline hash/bundle/mapping is legitimate.

  // Explicit legal projections cover all seven states without a test-side projection algorithm.
  const restricted = fixture(); restricted.state = "restricted"; restricted.can_approve = false;
  restricted.restriction = "identity_or_alignment_requires_repair";
  const stale = fixture(); stale.state = "stale_baseline"; stale.can_approve = false; stale.current_snapshot_id = "new_baseline";
  const expired = fixture(); expired.state = "expired"; expired.revision = 4; expired.history = [{ ...event(4), action: "approve" }];
  const approved = structuredClone(expired); approved.state = "approved_waiting_online";
  const applied = structuredClone(approved); applied.state = "applied_on_online_fetch"; applied.applied_query_id = "online_query"; applied.can_approve = false;
  for (const valid of [fixture(), restricted, stale, latest, expired, approved, applied]) {
    assertBinaryQuarantineReviewStateV2(valid, "quarantine"); reset(valid); assert.deepEqual(await get(), valid);
  }
  // A used approval wins over a changed baseline and a restriction; stale wins over restriction.
  const usedAndBlocked = structuredClone(applied); usedAndBlocked.current_snapshot_id = "new_baseline";
  usedAndBlocked.restriction = "identity_or_alignment_requires_repair";
  const staleAndBlocked = structuredClone(stale); staleAndBlocked.restriction = "identity_or_alignment_requires_repair";
  staleAndBlocked.revision = latest.revision; staleAndBlocked.history = structuredClone(latest.history);
  const restrictedApproval = structuredClone(restricted); restrictedApproval.revision = approved.revision; restrictedApproval.history = structuredClone(approved.history);
  for (const valid of [usedAndBlocked, staleAndBlocked, restrictedApproval]) assertBinaryQuarantineReviewStateV2(valid, "quarantine");
  // Relative timestamp order retains sub-millisecond precision and makes no local-clock/24h claim.
  const shortApproval = structuredClone(approved);
  shortApproval.history[0].created_at = "2026-10-20T00:00:00.000001Z";
  shortApproval.history[0].expires_at = "2026-10-20T00:00:00.000002+00:00";
  assertBinaryQuarantineReviewStateV2(shortApproval, "quarantine");
  const contradictory: BinaryQuarantineReviewStateV2[] = [];
  const falseApplied = fixture(); falseApplied.state = "applied_on_online_fetch"; contradictory.push(falseApplied);
  const appliedWithoutReview = fixture(); appliedWithoutReview.state = "applied_on_online_fetch";
  appliedWithoutReview.applied_query_id = "online_query"; appliedWithoutReview.can_approve = false; contradictory.push(appliedWithoutReview);
  const appliedKeep = structuredClone(applied); appliedKeep.history[0].action = "keep_quarantined"; contradictory.push(appliedKeep);
  const falsePending = fixture(); falsePending.can_approve = false; contradictory.push(falsePending);
  const missingAppliedState = structuredClone(approved); missingAppliedState.applied_query_id = "online_query"; missingAppliedState.can_approve = false; contradictory.push(missingAppliedState);
  const missingStaleState = fixture(); missingStaleState.current_snapshot_id = null; missingStaleState.can_approve = false; contradictory.push(missingStaleState);
  const missingRestrictedState = fixture(); missingRestrictedState.restriction = "identity_or_alignment_requires_repair"; missingRestrictedState.can_approve = false; contradictory.push(missingRestrictedState);
  const approveShownPending = structuredClone(approved); approveShownPending.state = "pending"; contradictory.push(approveShownPending);
  const keepShownApproved = structuredClone(latest); keepShownApproved.state = "approved_waiting_online"; contradictory.push(keepShownApproved);
  const approveShownKeep = structuredClone(approved); approveShownKeep.state = "kept_quarantined"; contradictory.push(approveShownKeep);
  const appliedShownStale = structuredClone(usedAndBlocked); appliedShownStale.state = "stale_baseline"; contradictory.push(appliedShownStale);
  const staleShownRestricted = structuredClone(staleAndBlocked); staleShownRestricted.state = "restricted"; contradictory.push(staleShownRestricted);
  for (const valid of [restricted, stale, applied]) { const invalid = structuredClone(valid); invalid.can_approve = true; contradictory.push(invalid); }
  for (const invalid of contradictory) {
    assert.throws(() => assertBinaryQuarantineReviewStateV2(invalid, "quarantine"), QuarantineReviewContractError);
    reset(invalid); await rejectsContract(get);
  }

  const invalidResponses: ((v: any) => void)[] = [
    v => { v.extra = true; }, v => { delete v.binding_hash; }, v => { v.quarantine_id = "foreign"; },
    v => { v.scope = "account"; }, v => { v.state = "accepted"; }, v => { v.revision = true; }, v => { v.revision = -1; },
    v => { v.can_approve = 1; }, v => { v.restriction = "unknown"; }, v => { v.baseline_snapshot_id = null; },
    v => { v.current_snapshot_id = 1; }, v => { v.applied_query_id = "unsafe/id"; }, v => { v.evidence_format = "text"; },
    v => { v.binding_contract = "vehicle-binary@2"; }, v => { v.binding_hash = "F".repeat(64); },
    v => { v.comparison.extra = 1; }, v => { v.comparison.candidate = null; }, v => { v.comparison.candidate.fitments = []; },
    v => { v.comparison.before.fitments = []; }, v => { v.comparison.candidate.fitments.push(structuredClone(v.comparison.candidate.fitments[0])); },
    v => { v.comparison.candidate.trims.push(structuredClone(v.comparison.candidate.trims[0])); },
    v => { v.comparison.candidate.fitments[0].trim_id = "missing"; }, v => { v.comparison.candidate.trims[0].wheel_option_ids = ["missing"]; },
    v => { v.comparison.candidate.trims[0].wheel_option_ids = ["fitment", "fitment"]; },
    v => { v.comparison.candidate.fitments[0].trim_name = "wrong"; }, v => { v.comparison.candidate.fitments[0].staggered = true; },
    v => { v.comparison.candidate.vehicle.id = "other-vehicle"; }, v => { v.comparison.candidate.extra = 1; },
    v => { v.comparison.candidate.parse_provenance.mapping_file_sha256 = "9".repeat(64); },
    v => { v.comparison.candidate.mapping_id = "xiaomi-su7-first-generation-pdf@3"; },
    v => { v.raw_evidence.content_path = "/arbitrary"; }, v => { v.raw_evidence.body = ""; }, v => { v.raw_evidence.body_encoding = "utf-8"; },
    v => { v.raw_evidence.byte_count = 0; }, v => { v.raw_evidence.byte_count = 1.5; }, v => { v.raw_evidence.byte_count = 8 * 1024 * 1024 + 1; },
    v => { v.raw_evidence.raw_capture_id = null; }, v => { v.raw_evidence.content_type = "application/json"; },
    v => { v.raw_evidence.parser_identity = null; }, v => { v.raw_evidence.parser_identity.extra = true; },
    v => { v.raw_evidence.parser_identity.deployment_revision = 0; }, v => { v.raw_evidence.parser_identity.parser_digest = "G".repeat(64); },
    v => { v.raw_evidence.parser_identity.bundle_id = "8".repeat(64); }, v => { v.raw_evidence.parse_provenance.extra = 1; },
    v => { v.raw_evidence.parse_provenance.contract = "other@1"; }, v => { v.raw_evidence.parse_provenance.source_raw_hash = "7".repeat(64); },
    v => { v.raw_evidence.parse_provenance.mapping_id = "xiaomi-su7-first-generation-pdf@1234567890"; },
    v => { v.history_truncated = true; }, v => { v.history = [event()]; },
  ];
  for (const mutate of invalidResponses) {
    const value: any = fixture(); mutate(value);
    assert.throws(() => assertBinaryQuarantineReviewStateV2(value, "quarantine"), QuarantineReviewContractError);
    reset(value); await rejectsContract(get);
  }
  for (const mutate of [
    (v: any) => { v.history[0].actor_user_id = "account_A"; }, (v: any) => { v.history[0].operator = "\ud800"; },
    (v: any) => { v.history[0].reason = "bad\u0001text"; }, (v: any) => { v.history[0].reason = "four"; },
    (v: any) => { v.history[0].operator = "😀".repeat(81); }, (v: any) => { v.history[0].reason = "😀".repeat(2001); },
    (v: any) => { v.history[1].revision = v.history[0].revision; }, (v: any) => { v.history[1].id = v.history[0].id; },
    (v: any) => { v.history[0].expires_at = v.history[0].created_at; },
    (v: any) => { v.history[0].expires_at = "2026-10-19T23:59:59.999999Z"; },
  ]) {
    const value: any = structuredClone(latest); mutate(value);
    assert.throws(() => assertBinaryQuarantineReviewStateV2(value, "quarantine"), QuarantineReviewContractError);
  }
  const full = fixture(); full.state = "kept_quarantined"; full.revision = 101; full.history = Array.from({ length: 100 }, (_, i) => event(101 - i)); full.history_truncated = true;
  assertBinaryQuarantineReviewStateV2(full, "quarantine");

  for (const change of [
    (v: any) => { v.extra = 1; }, (v: any) => { delete v.expected_binding_hash; }, (v: any) => { v.expected_revision = true; },
    (v: any) => { v.expected_revision = Number.MAX_SAFE_INTEGER + 1; }, (v: any) => { v.confirmed_loss = false; },
    (v: any) => { v.action = "adopt"; }, (v: any) => { v.expected_binding_hash = "BAD"; }, (v: any) => { v.operator = ""; },
    (v: any) => { v.operator = "😀".repeat(81); }, (v: any) => { v.reason = "four"; }, (v: any) => { v.reason = "\udfffaaaa"; },
    (v: any) => { v.reason = "bad\u0000text"; },
  ]) {
    reset(); const value: any = body(); change(value); await rejectsContract(() => post(value)); assert.equal(calls.length, 0);
  }
  for (const bad of ["", "unsafe/id", " id", "id ", "%69d", "x".repeat(65)]) {
    reset(); await rejectsContract(() => tireApi.quarantineReviewV2(bad, fence)); assert.equal(calls.length, 0);
    await rejectsContract(() => tireApi.reviewQuarantineV2("quarantine", body(), bad, fence)); assert.equal(calls.length, 0);
  }
  for (const badFence of [undefined, {}, { assertCurrent: 1 }, { assertCurrent: async () => {} }]) {
    reset(); await rejectsContract(() => tireApi.quarantineReviewV2("quarantine", badFence as any)); assert.equal(calls.length, 0);
    await rejectsContract(() => tireApi.reviewQuarantineV2("quarantine", body(), "account_A", badFence as any)); assert.equal(calls.length, 0);
  }
  reset(); status = 201; await rejectsContract(get);
  reset(); status = 200; await rejectsContract(post);
  reset(); const malformedJson = new SyntaxError("bad JSON"); jsonFailure = malformedJson;
  await assert.rejects(get, cause => cause === malformedJson);
  const failure = new Error("unchanged JSON reader failure");
  reset(); jsonFailure = failure; await assert.rejects(get, cause => cause === failure);

  // Normal request keeps status/code/string/validation-list errors and performs no write retry.
  for (const [httpStatus, detail, code, message] of [
    [403, { code: "vehicle_original_read_not_allowed" }, "vehicle_original_read_not_allowed", undefined],
    [503, { code: "vehicle_raw_integrity_failed" }, "vehicle_raw_integrity_failed", undefined],
    [409, { code: "review_actor_changed" }, "review_actor_changed", undefined],
    [409, { code: "review_binding_changed" }, "review_binding_changed", undefined],
    [409, "审批记录已更新", undefined, "审批记录已更新"],
    [422, [{ msg: "Value error, Bad confirmation" }], undefined, "Bad confirmation"],
  ] as const) {
    reset(); status = httpStatus; errorBody = { detail };
    await assert.rejects(post, cause => cause instanceof ApiError && cause.status === httpStatus && cause.code === code && (message === undefined || cause.message === message));
    assert.equal(calls.length, 1);
  }
  reset(); transportFailure = failure; await assert.rejects(post, cause => cause === failure); assert.equal(calls.length, 1);
  reset(); const timeout = new ApiTransportError("api_timeout"); transportFailure = timeout;
  await assert.rejects(post, cause => cause === timeout); assert.equal(calls.length, 1);

  for (const operation of [get, post]) {
    reset(); current = false; await assert.rejects(operation, CallerChanged); assert.equal(calls.length, 0);
    reset(); const aborted = new AbortController(); aborted.abort();
    await assert.rejects(() => operation === get ? get(aborted.signal) : post(body(), aborted.signal), { name: "AbortError" }); assert.equal(calls.length, 0);
    for (const at of ["transport", "json"] as const) {
      const hook = (f: () => void) => { if (at === "transport") afterTransport = f; else afterJson = f; };
      reset(); hook(() => { current = false; }); await assert.rejects(operation, CallerChanged); assert.equal(calls.length, 1);
      reset(); hook(() => { const undo = setApiTransport(async () => new Response()); undo(); });
      await assert.rejects(operation, QuarantineReviewContextError); assert.equal(calls.length, 1);
      reset(); const cancel = new AbortController(); hook(() => cancel.abort());
      await assert.rejects(() => operation === get ? get(cancel.signal) : post(body(), cancel.signal), { name: "AbortError" }); assert.equal(calls.length, 1);
    }
  }
  reset(); let release: (v: unknown) => void = () => {}, entered: () => void = () => {};
  const jsonEntered = new Promise<void>(resolve => { entered = resolve; }); beforeJson = entered;
  pendingJson = new Promise(resolve => { release = resolve; });
  const late = post(); await jsonEntered; current = false; release(fixture());
  await assert.rejects(late, CallerChanged); assert.equal(calls.length, 1);
  reset(); afterTransport = () => { current = false; }; status = 409; errorBody = { detail: { code: "review_binding_changed" } };
  await assert.rejects(post, CallerChanged); assert.equal(calls.length, 1);

  // The legacy routes retain their original unnegotiated text contract.
  reset({ old: "text contract" }); await tireApi.quarantineReview("legacy");
  assert.equal(calls[0].path, "/v1/quarantines/legacy/review?mode=history");
  reset({ old: "text contract" }); await tireApi.reviewQuarantine("legacy", { action: "keep_quarantined", expected_revision: 0, operator: "Old", reason: "Old reason", confirmed_loss: true });
  assert.equal(calls[0].path, "/v1/quarantines/legacy/reviews");
  assert.equal(new Headers(calls[0].init.headers).has("X-Tire-Expected-Account"), false);
  assert.equal(Object.keys(JSON.parse(String(calls[0].init.body))).length, 5);
} finally { restore(); }
