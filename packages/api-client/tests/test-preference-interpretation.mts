/** Public SDK contract probes. Synthetic transport only; no app or Provider. */
import assert from "node:assert/strict";
import { ApiError, setApiTransport, tireApi } from "@tire/api-client";
import type { TestPreferenceInterpretation, TestPreferenceInterpretationRequest } from "@tire/domain-types";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type RequestFields = Assert<Equal<keyof TestPreferenceInterpretationRequest,
  "expected_event_revision" | "expected_event_fingerprint" | "expected_preference_revision" |
  "expected_preference_fingerprint" | "participant_ids" | "metric_dimensions">>;
type ClientReturnsInterpretation = Assert<Equal<Awaited<ReturnType<typeof tireApi.interpretTestEventPreferences>>, TestPreferenceInterpretation>>;
// @ts-expect-error Weights are authoritative saved state, not request overrides.
const overrideWeights: keyof TestPreferenceInterpretationRequest = "weights";
// @ts-expect-error Actor attribution is never supplied by the client.
const overrideActor: keyof TestPreferenceInterpretationRequest = "actor";

const request: TestPreferenceInterpretationRequest = {
  expected_event_revision: 7, expected_event_fingerprint: "a".repeat(64),
  expected_preference_revision: 42, expected_preference_fingerprint: "b".repeat(64),
  participant_ids: ["synthetic-p1", "synthetic-p2"],
  metric_dimensions: [{ metric_key: "braking", dimension: "wet" }, { metric_key: "unspecified", dimension: null }],
};
const response: TestPreferenceInterpretation = {
  schema: "test-preference-interpretation@1", data_state: "local_snapshot", scope: "actor",
  evidence_scope: "local_workspace", comparison_scope: "same_event_only", ranking: "source_reported_only", policy_version: "same-event-preference@1",
  binding: { event: { id: "synthetic/event", revision_id: "synthetic-r7", revision: 7, fingerprint: request.expected_event_fingerprint }, preference: { revision: 42, fingerprint: request.expected_preference_fingerprint }, interpretation_fingerprint: "c".repeat(64) },
  source_evidence: {
    event: { title: "Synthetic event", organization: "Synthetic source", relationship: "unknown", publication_date: null, source_url: "https://example.com/synthetic", rights_basis: "synthetic input", tested_size: "225/50R17", vehicle: null, surface: null, conditions: "synthetic conditions", coverage: "selected_results", reported_participants: 3 },
    participants: request.participant_ids.map((id, index) => ({ id, key: `p${index + 1}`, brand: "Synthetic", model: `Model ${index + 1}`, source_designation: "", identity_status: "participant_only" })),
    metrics: [{ key: "braking", label: "Synthetic braking", unit: "m", protocol: "synthetic protocol", direction: "lower" }, { key: "unspecified", label: "Unspecified", unit: "raw", protocol: "direction absent", direction: "unspecified" }],
    measurements: ["38.00", "40.0", "-0"].map((raw_value, index) => ({ raw_value, participant_key: index === 1 ? "p2" : "p1", participant_id: index === 1 ? "synthetic-p2" : "synthetic-p1", metric_key: index === 2 ? "unspecified" : "braking", source_rank: index === 0 ? 7 : null, evidence_span: "Synthetic short evidence", evidence_locator: "synthetic row", evidence_id: `test-measurement:${index}`, reference: { event_id: "synthetic/event", revision: 7, participant_id: index === 1 ? "synthetic-p2" : "synthetic-p1", metric_key: index === 2 ? "unspecified" : "braking" } })),
    record_kind: "manual_transcription", verification_status: "unverified", verified_at: null, recorded_at: "2026-10-18T00:00:00Z", recorded_participant_count: 3, selected_participant_count: 2,
  },
  personal_interpretation: {
    mapping_origin: "user_explicit_once", weights: { dry: 20, wet: 25, quiet: 20, comfort: 10, wear: 15, energy: 5, appearance: 5 }, metric_dimensions: request.metric_dimensions,
    dimensions: [{ dimension: "wet", weight: 25, metric_keys: ["braking"], complete_comparable_metric_keys: ["braking"] }],
    metrics: [{ metric_key: "braking", dimension: "wet", observed_participant_ids: request.participant_ids, missing_participant_ids: [], evidence_ids: ["test-measurement:0", "test-measurement:1"], limitations: [], complete_comparable: true, observation_comparison: { scope: "selected_recorded_observations", favorable_participant_ids: ["synthetic-p1"], evidence_ids: ["test-measurement:0"] } }, { metric_key: "unspecified", dimension: null, observed_participant_ids: ["synthetic-p1"], missing_participant_ids: ["synthetic-p2"], evidence_ids: ["test-measurement:2"], limitations: ["excluded_by_user", "missing_measurements", "direction_unspecified", "insufficient_observations"], complete_comparable: false, observation_comparison: null }],
    coverage: { mapped_weight: 25, fully_comparable_weight: 25, unmapped_weight: 75, mapped_not_fully_comparable_weight: 0 },
  },
  notices: ["Synthetic contract only; not a source, runtime or recommendation acceptance claim."],
};

let status = 200;
let errorCode = "test_event_changed";
const controller = new AbortController();
const calls: { path: string; init: RequestInit }[] = [];
const restore = setApiTransport(async (path, init) => {
  calls.push({ path, init });
  if (init.signal?.aborted) throw new DOMException("aborted", "AbortError");
  return new Response(JSON.stringify(status === 200 ? response : { detail: { code: errorCode, message: "synthetic rejection" } }), { status });
});
try {
  const result = await tireApi.interpretTestEventPreferences("synthetic/event", request, controller.signal);
  assert.deepEqual(result, response);
  assert.equal(calls[0].path, "/v1/test-events/synthetic%2Fevent/preference-interpretation?mode=history");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.signal, controller.signal);
  assert.equal(calls[0].init.cache, "no-store");
  assert.equal(calls[0].init.credentials, "include");
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), request);
  assert.equal(result.personal_interpretation.metric_dimensions[1].dimension, null);
  assert.deepEqual(result.source_evidence.measurements.map(item => item.raw_value), ["38.00", "40.0", "-0"]);
  assert.deepEqual(result.source_evidence.measurements.map(item => item.source_rank), [7, null, null]);

  for (const [expectedStatus, code] of [[404, "test_event_not_found"], [409, "test_event_changed"], [409, "driving_preference_changed"], [422, "invalid_preference_interpretation"]] as const) {
    status = expectedStatus; errorCode = code;
    await assert.rejects(tireApi.interpretTestEventPreferences("synthetic/event", request), error => error instanceof ApiError && error.status === expectedStatus && error.code === code);
  }
  controller.abort();
  await assert.rejects(tireApi.interpretTestEventPreferences("synthetic/event", request, controller.signal), error => error instanceof DOMException && error.name === "AbortError");
  console.log("preference-contract: public request/response, explicit null, raw strings, source ranks, error codes and cancellation passed (injected transport)");
} finally { restore(); }
