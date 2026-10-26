/** Public contract and injected transport probes; synthetic, no API or material verification. */
import assert from "node:assert/strict";
import { ApiError, setApiTransport, tireApi } from "@tire/api-client";
import type { TestCandidateInterpretation, TestCandidateInterpretationRequest, TestCandidateLinkEvidence, TestCandidateReference } from "@tire/domain-types";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type RequestKeys = Assert<Equal<keyof TestCandidateInterpretationRequest, "selection" | "expected_event_revision_id" | "expected_event_revision" | "expected_event_fingerprint" | "expected_preference_revision" | "expected_preference_fingerprint" | "candidates" | "metric_dimensions">>;
type ReferenceKeys = Assert<Equal<keyof TestCandidateReference, "variant_id" | "link_id" | "expected_link_revision_id" | "expected_link_revision" | "expected_link_fingerprint">>;
type Return = Assert<Equal<Awaited<ReturnType<typeof tireApi.interpretTestEventCandidates>>, TestCandidateInterpretation>>;
type NoScore = Assert<Equal<TestCandidateInterpretation["performance_score"], null>>;
type Ranking = Assert<Equal<TestCandidateInterpretation["ranking"], "source_reported_only">>;
type NoProvider = Assert<Equal<TestCandidateInterpretation["boundary"]["provider_use"], false>>;
type NoExport = Assert<Equal<TestCandidateInterpretation["boundary"]["export"], false>>;
type SourceIdentity = Assert<Equal<TestCandidateInterpretation["source_evidence"]["participants"][number]["identity_status"], "participant_only">>;
type NoManagementActions = Assert<Equal<Extract<keyof TestCandidateLinkEvidence, "allowed_actions" | "history" | "frozen_evidence">, never>>;
type ConfirmedEvent = Assert<Equal<TestCandidateLinkEvidence["confirmed_event_revision_id"], string>>;
// @ts-expect-error Client cannot substitute participant IDs for current server-reconstructed bridges.
const participantOverride: TestCandidateReference = { variant_id: "v", participant_id: "p" };
// @ts-expect-error A same-event interpretation cannot establish a performance score.
const inferredScore: TestCandidateInterpretation["performance_score"] = 90;
// @ts-expect-error No client actor selection exists.
const actorOverride: TestCandidateInterpretationRequest = { actor: "another-user" };
// @ts-expect-error Full current bridge revision ID is required.
const incompleteRef: TestCandidateReference = { variant_id: "v", link_id: "l", expected_link_revision: 2, expected_link_fingerprint: "a".repeat(64) };

const fingerprint = "a".repeat(64);
const payload: TestCandidateInterpretationRequest = {
  selection: { vehicle_id: "synthetic-vehicle", vehicle_snapshot_id: "synthetic-snapshot", trim_id: "synthetic-trim", wheel_option_id: "synthetic-wheel", axle: "front" },
  expected_event_revision_id: "synthetic-event-revision", expected_event_revision: 8, expected_event_fingerprint: fingerprint,
  expected_preference_revision: 3, expected_preference_fingerprint: fingerprint,
  candidates: ["a", "b"].map(key => ({ variant_id: `synthetic-sku-${key}`, link_id: `synthetic-link-${key}`, expected_link_revision_id: `synthetic-review-${key}`, expected_link_revision: 2, expected_link_fingerprint: fingerprint })),
  metric_dimensions: [{ metric_key: "wet", dimension: "wet" }, { metric_key: "missing", dimension: null }],
};
// Runtime transport deliberately returns selected sentinel fields. Backend response validation
// is covered by private HTTP probes; this test checks transparent public SDK consumption.
const response = {
  schema: "test-candidate-interpretation@1", status: "insufficient_evidence", ranking: "source_reported_only", performance_score: null,
  boundary: { provider_use: false, export: false },
  source_evidence: { participants: [{ id: "synthetic:a", identity_status: "participant_only" }], measurements: [{ raw_value: "-0.000", source_rank: 2 }, { raw_value: "38.00", source_rank: 2 }] },
  personal_interpretation: null,
  excluded: [{ variant_id: "synthetic-sku-b", link_id: "synthetic-link-b", reason_codes: ["not_current_fitment_candidate"] }],
};
let status = 200;
let code = "test_candidate_binding_changed";
const calls: { path: string; init: RequestInit }[] = [];
const restore = setApiTransport(async (path, init) => {
  calls.push({ path, init });
  if (init.signal?.aborted) throw new DOMException("aborted", "AbortError");
  return new Response(JSON.stringify(status === 200 ? response : { detail: { code, message: "Synthetic rejection" } }), { status });
});
try {
  const controller = new AbortController();
  const result = await tireApi.interpretTestEventCandidates("synthetic/event?unsafe#id", payload, controller.signal);
  const call = calls.at(-1)!;
  assert.equal(call.path, "/v1/test-events/synthetic%2Fevent%3Funsafe%23id/candidate-interpretation?mode=history");
  assert.equal(call.init.method, "POST"); assert.equal(call.init.cache, "no-store"); assert.equal(call.init.credentials, "include");
  assert.equal(call.init.signal, controller.signal); assert.deepEqual(JSON.parse(String(call.init.body)), payload);
  assert.deepEqual(result, response); assert.equal(result.personal_interpretation, null);
  assert.equal(result.source_evidence.measurements[0].raw_value, "-0.000");
  assert.equal(result.source_evidence.measurements[1].raw_value, "38.00");
  assert.equal(result.excluded[0].variant_id, payload.candidates[1].variant_id);
  for (const [nextStatus, nextCode] of [[401, "authentication_required"], [409, "test_candidate_binding_changed"], [422, "test_candidate_scope_mismatch"]] as const) {
    status = nextStatus; code = nextCode;
    await assert.rejects(tireApi.interpretTestEventCandidates("event", payload), error => error instanceof ApiError && error.status === status && error.code === code);
  }
  controller.abort();
  await assert.rejects(tireApi.interpretTestEventCandidates("event", payload, controller.signal), error => error instanceof DOMException && error.name === "AbortError");
  console.log("candidate-interpretation-contract: public positive/negative types, exact body/path, no-store, credentials, raw decimals, exclusions, errors and cancellation passed (injected transport only)");
} finally { restore(); }
