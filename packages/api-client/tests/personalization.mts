/** Public personalization probes use an injected synthetic transport only. */
import assert from "node:assert/strict";
import { ApiError, setApiTransport, tireApi } from "@tire/api-client";
import type { FitmentCandidateRelation, FitmentCandidates, FitmentCandidatesRequest, InterestEvent, InterestMatch, PersonalFeed, PersonalFeedRequest } from "@tire/domain-types";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type FeedKeys = Assert<Equal<keyof PersonalFeedRequest, "domain" | "limit" | "cursor">>;
type CandidateKeys = Assert<Equal<keyof FitmentCandidatesRequest, "selection" | "expected_preference_revision" | "expected_preference_fingerprint">>;
type FeedReturn = Assert<Equal<Awaited<ReturnType<typeof tireApi.previewPersonalFeed>>, PersonalFeed>>;
type CandidateReturn = Assert<Equal<Awaited<ReturnType<typeof tireApi.previewFitmentCandidates>>, FitmentCandidates>>;
type NoScore = Assert<Equal<FitmentCandidates["performance_score"], null>>;
type NoRanking = Assert<Equal<FitmentCandidates["ranking"], "not_computed">>;
// @ts-expect-error The server session chooses the actor; no client actor override exists.
const actorOverride: PersonalFeedRequest = { actor: "someone-else" };
// @ts-expect-error Candidate selection requires an explicit immutable vehicle snapshot.
const incompleteSelection: FitmentCandidatesRequest["selection"] = { vehicle_id: "v", trim_id: "t", wheel_option_id: "w", axle: "front" };
// @ts-expect-error Reviewed fitment evidence does not establish a performance score.
const inferredScore: FitmentCandidates["performance_score"] = 95;

const fingerprint = "a".repeat(64), bindingHash = "b".repeat(64);
const event: InterestEvent = {
  schema: "interest-event@1", id: "synthetic-same-origin", domain: "tire", action: "facts_changed", state: "accepted", revision: 3,
  observed_at: "2026-10-18T00:00:00Z", subject_id: "synthetic-sku", label: "Synthetic historical event before interest creation", event_hash: "c".repeat(64),
  before: { facts: { tread_depth: "38.00", explicit_zero: 0, absent: { present: false } } }, after: { facts: { tread_depth: null, raw_value: "-0" } }, changed_paths: ["facts.tread_depth"], evidence: [],
};
const match: InterestMatch = { state: "matched", criteria: { conditions: [{ kind: "brand", values: ["Synthetic Brand"] }], metric_keys: [], changed_fields: [] }, matched_sides: ["before"], reasons: ["matches_before"], policy_version: "explicit-interest@1" };
const emptyPage: PersonalFeed = {
  schema: "personal-feed@1", policy_version: "current-interests-history@1", data_state: "local_snapshot", scope: "actor", feed_scope: "current_interests_history",
  domain: null, limit: 1, active_interest_count: 2, items: [], scanned_count: 1, matched_count: 0, indeterminate_count: 0, has_more: true,
  next_cursor: "synthetic/signed cursor?next=1", binding: { interests_fingerprint: fingerprint, candidates_fingerprint: bindingHash }, notices: ["Synthetic local history only"],
};
const feed: PersonalFeed = { ...emptyPage, has_more: false, next_cursor: null, matched_count: 1, items: [{ state: "matched", event, matches: [
  { interest_id: "synthetic-interest-a", interest_revision: 12, interest_fingerprint: fingerprint, interest_name: "Synthetic A", match },
  { interest_id: "synthetic-interest-b", interest_revision: 4, interest_fingerprint: bindingHash, interest_name: "Synthetic B", match: { ...match, state: "indeterminate", matched_sides: [], reasons: ["historical_evidence_unverifiable"] } },
] }] };
const selection: FitmentCandidatesRequest["selection"] = { vehicle_id: "synthetic-vehicle", vehicle_snapshot_id: "synthetic-new-metadata-snapshot", trim_id: "synthetic-trim", wheel_option_id: "synthetic-wheel", axle: "front" };
const provenance = { snapshot_id: "synthetic-old-vehicle-snapshot", source_id: "synthetic-source", source_url: "https://fixture.example/vehicle", parser_version: "synthetic-1", observed_at: event.observed_at, raw_hash: fingerprint };
const axle = { size: "245/40ZR20", load_index: "99", speed_rating: "Y", oe_mark: null, manufacturer_product_code: null, matched_tire_variant_id: null };
const relation: FitmentCandidateRelation = {
  relation_id: "synthetic/relation", revision_id: "synthetic-origin-revision", revision: 7, binding_hash: bindingHash,
  selection: { ...selection, vehicle_snapshot_id: provenance.snapshot_id, variant_id: "synthetic-sku", tire_snapshot_id: "synthetic-tire-snapshot", fact_version_id: "synthetic-fact" },
  vehicle_evidence: {
    role: "vehicle_requirement", vehicle: { id: selection.vehicle_id, manufacturer: { id: "synthetic-maker", name: "Synthetic Maker" }, model: "Synthetic Model", generation: "gen-1", model_year: 2026, region: "synthetic", source_vehicle_id: "source-v" },
    trim: { id: selection.trim_id, name: "Synthetic Trim", source_trim_id: "source-t", model_year: 2026, wheel_option_ids: [selection.wheel_option_id] },
    wheel: { id: selection.wheel_option_id, trim_id: selection.trim_id, trim_name: "Synthetic Trim", wheel_option_name: "Synthetic Wheel", wheel_diameter_inches: 20, availability: "standard", front: axle, rear: axle, staggered: false, source_tire_description: null, constraints: [], source_description: "Synthetic requirements", evidence_locator: "synthetic-locator" },
    axle: "front", requirements: axle, fact_version: 2, fact_hash: fingerprint, provenance,
    structured_locator: { kind: "vehicle_snapshot_payload", json_pointer: "/fitments/0/front", snapshot_id: provenance.snapshot_id, fitment_index: 0, wheel_option_id: selection.wheel_option_id, axle: "front" }, source_locator_marker: null, source_locator_notice: "Synthetic locator only",
  },
  tire_evidence: { role: "tire_sku_fact", variant_id: "synthetic-sku", identity: { brand: "Synthetic Brand", size: axle.size }, identity_status: "exact", facts: { zero: 0, raw: "-0", explicit_null: null }, fact_version_id: "synthetic-fact", fact_version: 3, facts_hash: fingerprint,
    provenance: { ...provenance, snapshot_id: "synthetic-tire-snapshot", source_url: "https://fixture.example/tire" }, query_key: "synthetic-query", structured_locator: { kind: "tire_snapshot_parsed_variants", json_pointer: "/variants/0", snapshot_id: "synthetic-tire-snapshot", variant_index: 0, variant_id: "synthetic-sku" }, source_locator_markers: [], source_locator_notice: "Synthetic only" },
  checks: [{ field: "size", status: "match", vehicle_value: axle.size, tire_value: axle.size }, { field: "oe_mark", status: "unknown", vehicle_value: null, tire_value: null }], unknown_fields: ["oe_mark"], acknowledged_unknowns: true,
  evidence: [{ kind: "fitment_relation_revision", record_id: "synthetic-origin-revision", entity_id: "synthetic/relation", revision: 7, snapshot_id: "synthetic-tire-snapshot", previous_snapshot_id: null, source_id: "synthetic-source", source_url: null, verification_ids: [], fingerprint: bindingHash, contract_version: null }],
};
const candidates: FitmentCandidates = {
  schema: "fitment-candidates@1", policy_version: "reviewed-exact-axle@1", data_state: "local_snapshot", scope: "actor", evidence_scope: "local_workspace", selection,
  vehicle_binding: { snapshot_id: selection.vehicle_snapshot_id, current_snapshot_id: selection.vehicle_snapshot_id, fact_hash: fingerprint, fact_version: 2, scope: { vehicle_id: selection.vehicle_id, trim_id: selection.trim_id, wheel_option_id: selection.wheel_option_id, axle: selection.axle } },
  preference: { revision: 0, fingerprint, weights: null }, research_focus: [{ dimension: "quiet", weight: null, evidence_status: "exact_sku_performance_not_established" }],
  items: [{ variant_id: "synthetic-sku", identity: { brand: "Synthetic Brand", acoustic_technology: "Synthetic source declaration" }, relations: [relation], performance_score: null, ranking: "not_computed", official_oe: { state: "not_established", missing_evidence: ["synthetic-official-proof"] } }],
  excluded_relations: [{ relation_id: "synthetic-stale", revision: 9, variant_id: "synthetic-other", effective_state: "needs_review", reason_codes: ["tire_facts_changed"] }], inspected_count: 2, relation_count: 2, truncated: false,
  ranking: "not_computed", performance_score: null, official_oe: { state: "not_established", missing_evidence: ["synthetic-official-proof"] }, notices: ["Synthetic fitment evidence is not performance recommendation"],
};

let response: unknown = emptyPage, status = 200, code = "personal_feed_binding_changed";
const calls: { path: string; init: RequestInit }[] = [];
const controller = new AbortController();
const restore = setApiTransport(async (path, init) => {
  calls.push({ path, init });
  if (init.signal?.aborted) throw new DOMException("aborted", "AbortError");
  return new Response(JSON.stringify(status === 200 ? response : { detail: { code, message: "Synthetic rejection" } }), { status });
});
function check(path: string, payload: unknown) {
  const call = calls.at(-1)!;
  assert.equal(call.path, path); assert.equal(call.init.method, "POST"); assert.equal(call.init.signal, controller.signal);
  assert.equal(call.init.cache, "no-store"); assert.equal(call.init.credentials, "include"); assert.deepEqual(JSON.parse(String(call.init.body)), payload);
}
try {
  const firstRequest: PersonalFeedRequest = { domain: null, limit: 1, cursor: null };
  const first = await tireApi.previewPersonalFeed(firstRequest, controller.signal);
  assert.deepEqual(first, emptyPage); assert.equal(first.items.length, 0); assert.equal(first.has_more, true); assert.ok(first.next_cursor);
  check("/v1/personal-feed/preview?mode=history", firstRequest);
  response = feed;
  const nextRequest: PersonalFeedRequest = { domain: null, limit: 1, cursor: first.next_cursor };
  const next = await tireApi.previewPersonalFeed(nextRequest, controller.signal);
  check("/v1/personal-feed/preview?mode=history", nextRequest); assert.deepEqual(next, feed);
  assert.equal(next.items.length, 1); assert.equal(next.items[0].matches.length, 2); assert.equal(next.items[0].matches[1].match.state, "indeterminate");
  assert.equal(next.items[0].event.before!.facts && JSON.stringify(next.items[0].event.before!.facts), '{"tread_depth":"38.00","explicit_zero":0,"absent":{"present":false}}');
  assert.equal("read_at" in next.items[0], false);
  const candidateRequest: FitmentCandidatesRequest = { selection, expected_preference_revision: 0, expected_preference_fingerprint: fingerprint };
  response = candidates;
  const found = await tireApi.previewFitmentCandidates(candidateRequest, controller.signal);
  check("/v1/fitment-candidates/preview?mode=history", candidateRequest); assert.deepEqual(found, candidates);
  assert.notEqual(found.items[0].relations[0].selection.vehicle_snapshot_id, found.selection.vehicle_snapshot_id);
  assert.equal(found.items[0].relations[0].vehicle_evidence.fact_hash, found.vehicle_binding.fact_hash);
  assert.equal(found.items[0].relations[0].evidence[0].fingerprint, bindingHash);
  assert.equal(found.items[0].relations[0].checks[1].status, "unknown"); assert.equal(found.preference.weights, null); assert.equal(found.performance_score, null);
  for (const [nextStatus, nextCode] of [[400, "personal_feed_cursor_invalid"], [409, "personal_feed_binding_changed"], [409, "personal_feed_capacity_exceeded"]] as const) {
    status = nextStatus; code = nextCode;
    await assert.rejects(tireApi.previewPersonalFeed(nextRequest), error => error instanceof ApiError && error.status === nextStatus && error.code === nextCode);
  }
  status = 409; code = "driving_preference_changed";
  await assert.rejects(tireApi.previewFitmentCandidates(candidateRequest), error => error instanceof ApiError && error.status === 409 && error.code === code);
  controller.abort();
  await assert.rejects(tireApi.previewPersonalFeed(firstRequest, controller.signal), error => error instanceof DOMException && error.name === "AbortError");
  await assert.rejects(tireApi.previewFitmentCandidates(candidateRequest, controller.signal), error => error instanceof DOMException && error.name === "AbortError");
  console.log("personalization-contract: public types, exact POST bodies, empty page continuation, merged interests, frozen original evidence, metadata-only snapshot separation, unknowns/null/no ranking, error codes and cancellation passed (injected transport only)");
} finally { restore(); }
