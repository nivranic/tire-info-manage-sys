/** Source-quality interest SDK contract probes; synthetic transport only. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError, setApiTransport, tireApi } from "@tire/api-client";
import type { InterestDomain, InterestEvidence, InterestMatch, InterestNotification, InterestSettings, InterestSourceQualityAfter, InterestSourceQualityCriteria, InterestSourceQualityEvent } from "@tire/domain-types";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type StrictOption = Assert<Equal<InterestSettings["source_quality_notifications"], boolean | undefined>>;
type QualityDomain = Assert<Equal<Extract<InterestDomain, "tire_source_quality">, "tire_source_quality">>;
type QualityPolicy = Assert<Equal<Extract<InterestMatch, { policy_version: "source-quality-interest@1" }>["criteria"], InterestSourceQualityCriteria>>;
type QualityEvidence = Assert<Equal<Extract<InterestEvidence["kind"], "tire_source_quarantine" | "tire_source_quality_baseline">, "tire_source_quarantine" | "tire_source_quality_baseline">>;
// @ts-expect-error Explicit subscription accepts booleans only, never truthy text.
const textOption: InterestSettings["source_quality_notifications"] = "true";
// @ts-expect-error Null is not an omitted option and must never mean opt-out.
const nullOption: InterestSettings["source_quality_notifications"] = null;
// @ts-expect-error A source quality candidate is never an accepted fact.
const acceptedCandidate: InterestSourceQualityAfter["accepted"] = true;
// @ts-expect-error Source quality matching cannot use a test organization condition.
const unsupportedCondition: InterestSourceQualityCriteria["conditions"][number] = { kind: "test_organization", values: ["Synthetic Lab"] };

const instant = "2026-10-25T00:00:00Z";
const id = "quality/notice?one";
const settings: InterestSettings & { source_quality_notifications: boolean } = {
  name: "Synthetic quality subscription", enabled: true,
  conditions: [{ kind: "brand", values: ["Synthetic Brand"] }],
  metric_keys: [], changed_fields: [], source_quality_notifications: true,
};
const record = { ...settings, id: "interest/one", scope: "actor", revision: 1, archived: false,
  fingerprint: "a".repeat(64), created_at: instant, updated_at: instant, monitoring_enabled: false };
const malformed = { id, interest_id: record.id, interest_revision: 1, interest_name: record.name,
  delivered_at: instant, read_at: null,
  event: { schema: "interest-event@1", id: "event-one", domain: "tire_source_quality", action: "quarantined",
    state: "quarantined", revision: 1, observed_at: instant, subject_id: "quarantine-one", label: "Synthetic unaccepted update",
    event_hash: "b".repeat(64), before: null, after: {}, changed_paths: ["source_quality"], evidence: [] },
  match: { state: "matched", criteria: { conditions: settings.conditions, metric_keys: [], changed_fields: [], source_quality_notifications: true },
    matched_sides: ["after"], reasons: ["matches_baseline_member"], policy_version: "source-quality-interest@1", matched_baseline_members: [] },
};

const baselineHash = "c".repeat(64), quarantineHash = "d".repeat(64);
const qualityEvent: InterestSourceQualityEvent = {
  schema: "interest-event@1", id: "event-one", domain: "tire_source_quality", action: "quarantined", state: "quarantined", revision: 1,
  observed_at: instant, subject_id: "quarantine-one", label: "Synthetic query update was quarantined", event_hash: "b".repeat(64),
  before: null, changed_paths: ["source_quality"],
  after: {
    accepted: false, state: "quarantined", evidence_valid: true,
    quarantine: { id: "quarantine-one", query_id: "query-one", source_id: "synthetic-source", query_key: "e".repeat(64), query: { model: "Synthetic Model", size: "265/40R20" },
      source_url: "https://fixture.invalid/changed-query", raw_hash: quarantineHash, parser_version: "synthetic@2", observed_at: instant,
      reason_codes: ["row_loss_threshold"], metrics: { baseline_rows: 2, candidate_rows: 1, aligned_rows: 1, lost_rows: 1, row_loss_ratio: 0.5, known_fields: 2, lost_fields: 0, field_loss_ratio: 0 }, previous_snapshot_id: "baseline-one" },
    baseline: { snapshot_id: "baseline-one", source_id: "synthetic-source", query_key: "e".repeat(64), source_url: "https://fixture.invalid/baseline-query", raw_hash: baselineHash,
      identity_contract_version: "identity-contract@synthetic", parsed_variants_hash: "f".repeat(64), verification_id: "verification-one", verification_status: "not_modified",
      verified_at: "2026-10-24T23:59:59Z", observed_at: "2026-10-24T20:00:00Z", parser_version: "synthetic@1" },
    baseline_members: [{ variant_id: "variant-one", structured_locator: "/variants/0", member_hash: "1".repeat(64), identity: { brand: "Synthetic Brand", model: "Synthetic Model", oe_mark: null },
      facts: { utqg_treadwear: 0 }, fact_version_id: "fact-one", fact_version: 1, facts_hash: "2".repeat(64), evidence_valid: true }],
  },
  evidence: [
    { kind: "tire_source_quarantine", record_id: "quarantine-one", entity_id: "quarantine-one", revision: null, snapshot_id: null, previous_snapshot_id: "baseline-one", source_id: "synthetic-source", source_url: "https://fixture.invalid/changed-query", verification_ids: [], fingerprint: quarantineHash, contract_version: "source-quality-interest@1" },
    { kind: "tire_source_quality_baseline", record_id: "baseline-one", entity_id: "baseline-one", revision: null, snapshot_id: "baseline-one", previous_snapshot_id: null, source_id: "synthetic-source", source_url: "https://fixture.invalid/baseline-query", verification_ids: ["verification-one"], fingerprint: baselineHash, contract_version: "identity-contract@synthetic" },
  ],
};
const qualityNotice: InterestNotification = {
  id, interest_id: record.id, interest_revision: 1, interest_name: record.name, delivered_at: instant, read_at: null, event: qualityEvent,
  match: { state: "matched", policy_version: "source-quality-interest@1", criteria: { conditions: [{ kind: "brand", values: ["Synthetic Brand"] }], metric_keys: [], changed_fields: [], source_quality_notifications: true },
    matched_sides: ["after"], reasons: ["matches_baseline_member"], matched_baseline_members: [{ variant_id: "variant-one", structured_locator: "/variants/0", member_hash: "1".repeat(64) }] },
};

function install(value: unknown, status = 200) {
  const calls: { path: string; init: RequestInit }[] = [];
  const restore = setApiTransport(async (path, init) => {
    calls.push({ path, init });
    return new Response(JSON.stringify(value), { status });
  });
  return { calls, restore };
}

await test("explicit opt-in and opt-out are serialized exactly; legacy edits keep omission", async () => {
  const transport = install(record), controller = new AbortController();
  try {
    await tireApi.createInterest(settings, controller.signal);
    await tireApi.updateInterest(record.id, 1, { ...settings, source_quality_notifications: false }, controller.signal);
    const { source_quality_notifications: _option, ...legacy } = settings;
    await tireApi.updateInterest(record.id, 1, legacy, controller.signal);
    assert.equal(transport.calls[0].path, "/v1/interests");
    assert.deepEqual(JSON.parse(String(transport.calls[0].init.body)), settings);
    assert.equal(transport.calls[1].path, "/v1/interests/interest%2Fone");
    assert.deepEqual(JSON.parse(String(transport.calls[1].init.body)), { ...settings, source_quality_notifications: false, expected_revision: 1 });
    assert.deepEqual(JSON.parse(String(transport.calls[2].init.body)), { ...legacy, expected_revision: 1 });
    for (const call of transport.calls) { assert.equal(call.init.signal, controller.signal); assert.equal(call.init.credentials, "include"); assert.equal(call.init.cache, "no-store"); }
    assert.equal(transport.calls.length, 3);
  } finally { transport.restore(); }
});

await test("legacy history omission remains compatible with an effective false option", async () => {
  const { source_quality_notifications: _option, ...legacy } = record;
  const transport = install({ ...legacy, history: [legacy], history_truncated: false });
  try {
    const result = await tireApi.interest(record.id);
    assert.deepEqual(result, { ...legacy, history: [legacy], history_truncated: false });
    assert.equal((result as typeof result & { source_quality_notifications?: boolean }).source_quality_notifications ?? false, false);
  } finally { transport.restore(); }
});

await test("quality notification detail rejects a missing frozen quarantine and baseline binding", async () => {
  const transport = install(malformed);
  try {
    await assert.rejects(tireApi.interestNotification(id));
    assert.equal(transport.calls[0].path, "/v1/interest-notifications/quality%2Fnotice%3Fone?mode=history");
    assert.equal(transport.calls.length, 1);
  } finally { transport.restore(); }
});

await test("quality notification list rejects missing bindings before exposing metadata", async () => {
  const transport = install({ scope: "actor", data_state: "local_snapshot", items: [malformed], total: 1, offset: 0, limit: 50 });
  try { await assert.rejects(tireApi.interestNotifications()); assert.equal(transport.calls.length, 1); }
  finally { transport.restore(); }
});

await test("valid metadata and detail retain exact quarantine, baseline, criteria and member references", async () => {
  const transport = install(qualityNotice), controller = new AbortController();
  try {
    const value = await tireApi.interestNotification(id, controller.signal);
    assert.deepEqual(value, qualityNotice);
    assert.equal(transport.calls[0].init.signal, controller.signal);
    assert.equal(transport.calls.length, 1);
    assert.equal(value.event.domain, "tire_source_quality");
    if (value.event.domain !== "tire_source_quality") throw new Error("missing quality event narrowing");
    assert.equal(value.event.after.accepted, false);
    assert.notEqual(value.event.after.quarantine.source_url, value.event.after.baseline.source_url);
    assert.notEqual(value.event.after.baseline.observed_at, value.event.after.baseline.verified_at);
    assert.equal("candidates" in value.event.after.quarantine, false);
    assert.equal("body" in value.event.after, false);
  } finally { transport.restore(); }
  const list = { scope: "actor", data_state: "local_snapshot", items: [qualityNotice], total: 51, offset: 50, limit: 20 };
  const listing = install(list);
  try {
    assert.deepEqual(await tireApi.interestNotifications(true, controller.signal, 50, 20), list);
    assert.equal(listing.calls[0].path, "/v1/interest-notifications?mode=history&unread=true&offset=50&limit=20");
    assert.equal(listing.calls.length, 1);
  } finally { listing.restore(); }
});

await test("new quality decoding fails closed for missing, conflicting, private or unsupported bindings", async () => {
  const corruptions: [string, (value: any) => void][] = [
    ["accepted candidate", value => { value.event.after.accepted = true; }],
    ["candidate leak", value => { value.event.after.quarantine.candidates = []; }],
    ["body leak", value => { value.event.after.body = "candidate text"; }],
    ["missing baseline", value => { delete value.event.after.baseline; }],
    ["wrong prior snapshot", value => { value.event.after.quarantine.previous_snapshot_id = "other"; }],
    ["wrong query", value => { value.event.after.baseline.query_key = "0".repeat(64); }],
    ["missing member proof", value => { delete value.event.after.baseline_members[0].member_hash; }],
    ["empty baseline", value => { value.event.after.baseline_members = []; }],
    ["unknown evidence", value => { value.event.evidence[0].kind = "tire_change"; }],
    ["wrong evidence SHA", value => { value.event.evidence[1].fingerprint = "0".repeat(64); }],
    ["wrong verification", value => { value.event.evidence[1].verification_ids = ["other"]; }],
    ["wrong subject", value => { value.event.subject_id = "other"; }],
    ["wrong changed paths", value => { value.event.changed_paths = ["facts"]; }],
    ["old policy on new event", value => { value.match.policy_version = "explicit-interest@1"; }],
    ["missing opt-in", value => { delete value.match.criteria.source_quality_notifications; }],
    ["unsupported filter", value => { value.match.criteria.changed_fields = ["facts"]; }],
    ["unsupported condition", value => { value.match.criteria.conditions = [{ kind: "test_organization", values: ["Lab"] }]; }],
    ["member from elsewhere", value => { value.match.matched_baseline_members[0].variant_id = "other"; }],
    ["before side", value => { value.match.matched_sides = ["before"]; }],
  ];
  for (const [name, corrupt] of corruptions) {
    const value = structuredClone(qualityNotice); corrupt(value);
    const transport = install(value);
    try { await assert.rejects(tireApi.interestNotification(id), { name: "SourceQualityInterestContractError" }, name); assert.equal(transport.calls.length, 1, name); }
    finally { transport.restore(); }
  }
});

await test("quality read and unread retain the original closed body and encoded route", async () => {
  for (const read of [true, false]) {
    const response = { id, read_at: read ? instant : null }, transport = install(response);
    try {
      assert.deepEqual(await tireApi.markInterestNotification(id, read), response);
      assert.equal(transport.calls[0].path, "/v1/interest-notifications/quality%2Fnotice%3Fone/read");
      assert.equal(transport.calls[0].init.method, "PUT");
      assert.deepEqual(JSON.parse(String(transport.calls[0].init.body)), { read });
      assert.equal(transport.calls.length, 1);
    } finally { transport.restore(); }
  }
});

await test("fixed history failures and owner 404 pass through without replay or substitute reads", async () => {
  for (const [status, code] of [[503, "source_quality_interest_history_invalid"], [404, "interest_notification_not_found"]] as const) {
    const transport = install({ detail: { code, message: "Synthetic fixed rejection" } }, status);
    try {
      await assert.rejects(tireApi.interestNotification(id), error => error instanceof ApiError && error.status === status && error.code === code);
      assert.equal(transport.calls.length, 1);
    } finally { transport.restore(); }
  }
});

await test("interest SDK operations forward caller cancellation and never retry", async () => {
  const operations = [
    (signal: AbortSignal) => tireApi.createInterest(settings, signal),
    (signal: AbortSignal) => tireApi.updateInterest(record.id, 1, settings, signal),
    (signal: AbortSignal) => tireApi.interest(record.id, signal),
    (signal: AbortSignal) => tireApi.interestNotifications(false, signal),
    (signal: AbortSignal) => tireApi.interestNotification(id, signal),
    (signal: AbortSignal) => tireApi.markInterestNotification(id, true, signal),
  ];
  for (const operation of operations) {
    const controller = new AbortController(), failure = new DOMException("Synthetic cancellation", "AbortError");
    let count = 0;
    const restore = setApiTransport((_path, init) => new Promise((_resolve, reject) => {
      count++; assert.equal(init.signal, controller.signal);
      init.signal!.addEventListener("abort", () => reject(failure), { once: true });
    }));
    try { const rejected = assert.rejects(operation(controller.signal), error => error === failure); controller.abort(); await rejected; assert.equal(count, 1); }
    finally { restore(); }
  }
});
