/** Public interest SDK probes, using only an injected synthetic transport. */
import assert from "node:assert/strict";
import { ApiError, setApiTransport, tireApi } from "@tire/api-client";
import type {
  FitmentRelationRevision, InterestCapabilities, InterestCondition, InterestCurationApplicabilityRecord, InterestDetail, InterestEvent, InterestList, InterestMatch, InterestNotification,
  InterestNotificationList, InterestOriginalEvidence, InterestOriginalEvidenceKind, InterestPreview, InterestPreviewRequest, InterestRecord, InterestSettings,
} from "@tire/domain-types";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type SettingsKeys = Assert<Equal<keyof InterestSettings, "name" | "enabled" | "conditions" | "metric_keys" | "changed_fields" | "source_quality_notifications">>;
type AllSevenKinds = Assert<Equal<InterestCondition["kind"], "brand" | "model" | "size" | "oe" | "technology" | "test_organization" | "vehicle_fitment">>;
type AllTenDomains = Assert<Equal<InterestEvent["domain"], "tire" | "test_event" | "vehicle" | "fitment" | "tire_curation" | "tire_lifecycle" | "tire_identity" | "tire_catalog" | "tire_curation_validity" | "tire_source_quality">>;
type AllGovernanceKinds = Assert<Equal<InterestOriginalEvidenceKind, "tire_curation_revision" | "tire_lifecycle_event" | "tire_identity_revision" | "tire_catalog_revision" | "tire_curation_applicability_event">>;
type PreviewKeys = Assert<Equal<keyof InterestPreviewRequest, "conditions" | "metric_keys" | "changed_fields">>;
type PublicDetail = Assert<Equal<Awaited<ReturnType<typeof tireApi.interest>>, InterestDetail>>;
type PublicPreview = Assert<Equal<Awaited<ReturnType<typeof tireApi.previewInterests>>, InterestPreview>>;
type PublicNotification = Assert<Equal<Awaited<ReturnType<typeof tireApi.interestNotification>>, InterestNotification>>;
type PublicHistoricalFitment = Assert<Equal<Awaited<ReturnType<typeof tireApi.fitmentRelationRevision>>, FitmentRelationRevision>>;
type PublicOriginalEvidence = Assert<Equal<Awaited<ReturnType<typeof tireApi.interestEvidence>>, InterestOriginalEvidence>>;
type FrozenCriteriaContract = Assert<Equal<Extract<InterestMatch, { policy_version: "explicit-interest@1" }>["criteria"], InterestPreviewRequest>>;
// @ts-expect-error Actor ownership is decided by the server session.
const actorOverride: keyof InterestSettings = "actor";
// @ts-expect-error A model condition requires its explicit brand.
const brandlessModel: InterestCondition = { kind: "model", values: [{ model: "Synthetic Model" }] };
// @ts-expect-error Every new match must preserve the criteria used for that evaluation.
const missingCriteria: InterestMatch = { state: "matched", matched_sides: ["after"], reasons: ["matches_after"], policy_version: "explicit-interest@1" };
// @ts-expect-error Original evidence accepts an immutable governance origin kind, not a current snapshot.
const snapshotAsOriginal: Parameters<typeof tireApi.interestEvidence>[0] = "tire_change";

const settings: InterestSettings = {
  name: "Synthetic combined interest", enabled: false,
  conditions: [
    { kind: "brand", values: ["Synthetic Brand"] },
    { kind: "model", values: [{ brand: "Synthetic Brand", model: "Synthetic Model" }] },
    { kind: "size", values: ["265/40R20", "265/40ZR20"] },
    { kind: "oe", values: ["Synthetic OE"] },
    { kind: "technology", values: ["Acoustic"] },
    { kind: "technology", values: ["Synthetic Foam"] },
    { kind: "test_organization", values: ["Synthetic Lab"] },
    { kind: "vehicle_fitment", values: [{ vehicle_id: "synthetic-vehicle", trim_id: "synthetic-trim", wheel_option_id: "synthetic-wheel", axle: "front" }] },
  ],
  metric_keys: ["wet", "raw.key-0"],
  changed_fields: ["facts.utqg_treadwear", "facts.utqg_traction", "facts.utqg_temperature", "facts.tread_depth", "facts.tread_depths", "event.measurements", "curation", "identity_resolution", "catalog_membership", "curation_applicability", "state"],
};
const record: InterestRecord = { ...settings, id: "synthetic/interest", scope: "actor", revision: 9, archived: false, fingerprint: "a".repeat(64), created_at: "2026-10-18T00:00:00Z", updated_at: "2026-10-18T00:01:00Z", monitoring_enabled: false };
const detail: InterestDetail = { ...record, history: [{ ...settings, revision: 9, archived: false, fingerprint: record.fingerprint, created_at: record.created_at }], history_truncated: false };
const capabilities: InterestCapabilities = {
  schema: "interest-capabilities@1", kinds: ["brand", "model", "size", "oe", "technology", "test_organization", "vehicle_fitment"],
  domains: ["tire", "test_event", "vehicle", "fitment", "tire_curation", "tire_lifecycle", "tire_identity", "tire_catalog", "tire_curation_validity"].map(domain => ({ domain: domain as InterestEvent["domain"], supported: true, event_kinds: ["synthetic"], limitations: ["Synthetic local events only"] })),
  changed_fields: settings.changed_fields, unsupported_events: [{ kind: "synthetic_unsupported", reason: "Not a complete domain coverage claim" }], network_refresh: false, notice: "Synthetic capability fixture",
};
const event: InterestEvent = {
  schema: "interest-event@1", id: "synthetic-event", domain: "test_event", action: "revise", state: "active", revision: 4, observed_at: record.updated_at,
  subject_id: "synthetic-test", label: "<script>synthetic text</script>", event_hash: "b".repeat(64), before: { absent_before: false, measurements: [{ raw_value: "-0", source_rank: 0 }] },
  after: { explicit_null: null, measurements: [{ raw_value: "38.00", source_rank: null }] }, changed_paths: ["event.measurements.wet"],
  evidence: [{ kind: "test_revision", record_id: "synthetic-revision", entity_id: "synthetic-test", revision: 4, snapshot_id: null, previous_snapshot_id: null, source_id: null, source_url: "https://example.com/synthetic", verification_ids: [], fingerprint: "c".repeat(64), contract_version: null }],
};
const previewRequest: InterestPreviewRequest = { conditions: settings.conditions, metric_keys: settings.metric_keys, changed_fields: settings.changed_fields };
const notice: InterestNotification = { id: "synthetic/notice", interest_id: record.id, interest_name: record.name, interest_revision: 9, delivered_at: record.updated_at, read_at: null, event, match: { state: "matched", criteria: structuredClone(previewRequest), matched_sides: ["after"], reasons: ["matches_after"], policy_version: "explicit-interest@1" } };
const preview: InterestPreview = { schema: "interest-preview@1", scope: "actor", data_state: "local_snapshot", items: [{ event, match: notice.match }, { event: { ...event, id: "synthetic-indeterminate" }, match: { state: "indeterminate", criteria: structuredClone(previewRequest), matched_sides: [], reasons: ["missing_vehicle_scope"], policy_version: "explicit-interest@1" } }], scanned_count: 50, matched_count: 1, indeterminate_count: 1, next_offset: 100, capabilities };
const listing: InterestList = { scope: "actor", data_state: "local_snapshot", items: [record], total: 1, offset: 50, limit: 20, capabilities };
const notifications: InterestNotificationList = { scope: "actor", data_state: "local_snapshot", items: [notice], total: 1, offset: 50, limit: 20 };
const controller = new AbortController();
const calls: { path: string; init: RequestInit }[] = [];
let response: unknown = capabilities;
let status = 200;
const restore = setApiTransport(async (path, init) => {
  calls.push({ path, init });
  if (init.signal?.aborted) throw new DOMException("aborted", "AbortError");
  return new Response(JSON.stringify(response), { status });
});
function check(path: string, method: string, body?: unknown) {
  const call = calls.at(-1)!;
  assert.equal(call.path, path);
  assert.equal(call.init.method || "GET", method);
  assert.equal(call.init.signal, controller.signal);
  assert.equal(call.init.credentials, "include");
  assert.equal(call.init.cache, "no-store");
  assert.deepEqual(call.init.body ? JSON.parse(String(call.init.body)) : undefined, body);
}
try {
  assert.deepEqual(await tireApi.interestCapabilities(controller.signal), capabilities);
  check("/v1/interests/capabilities?mode=history", "GET");
  response = listing;
  assert.deepEqual(await tireApi.interests(true, controller.signal, 50, 20), listing);
  check("/v1/interests?archived=true&offset=50&limit=20", "GET");
  response = record; status = 201;
  assert.deepEqual(await tireApi.createInterest(settings, controller.signal), record);
  check("/v1/interests", "POST", settings);
  status = 200; response = detail;
  assert.deepEqual(await tireApi.interest(record.id, controller.signal), detail);
  check("/v1/interests/synthetic%2Finterest?mode=history", "GET");
  response = record;
  await tireApi.updateInterest(record.id, 9, settings, controller.signal);
  check("/v1/interests/synthetic%2Finterest", "PUT", { ...settings, expected_revision: 9 });
  for (const action of ["archive", "restore"] as const) {
    await tireApi.interestState(record.id, 9, action, controller.signal);
    check("/v1/interests/synthetic%2Finterest/state", "POST", { expected_revision: 9, action });
  }
  response = preview;
  const result = await tireApi.previewInterests(previewRequest, controller.signal, 50, 50);
  assert.deepEqual(result, preview);
  assert.deepEqual(result.items[0].match.criteria, previewRequest);
  assert.deepEqual(result.items[1].match.criteria, previewRequest);
  assert.equal("interest_revision" in result.items[0], false);
  assert.equal(result.items[1].match.state, "indeterminate");
  assert.equal(result.items[0].event.before!.measurements && JSON.stringify(result.items[0].event.before!.measurements), '[{"raw_value":"-0","source_rank":0}]');
  assert.equal(result.items[0].event.after.explicit_null, null);
  check("/v1/interests/preview?mode=history&offset=50&limit=50", "POST", previewRequest);
  response = notifications;
  assert.deepEqual(await tireApi.interestNotifications(true, controller.signal, 50, 20), notifications);
  check("/v1/interest-notifications?mode=history&unread=true&offset=50&limit=20", "GET");
  response = notice;
  assert.deepEqual(await tireApi.interestNotification(notice.id, controller.signal), notice);
  check("/v1/interest-notifications/synthetic%2Fnotice?mode=history", "GET");
  for (const read of [true, false]) {
    response = { id: notice.id, read_at: read ? record.updated_at : null };
    assert.deepEqual(await tireApi.markInterestNotification(notice.id, read, controller.signal), response);
    check("/v1/interest-notifications/synthetic%2Fnotice/read", "PUT", { read });
  }
  // This route probe checks transport of a historical revision, not backend schema validation.
  const historicalBinding = { id: "synthetic-fitment-revision", relation_id: "synthetic/relation", revision: 123, before: { value: "-0" }, after: { value: null } };
  response = historicalBinding;
  assert.deepEqual(await tireApi.fitmentRelationRevision("synthetic/relation", 123, controller.signal), historicalBinding);
  check("/v1/fitment-relations/synthetic%2Frelation/revisions/123?mode=history", "GET");
  // Reopen the immutable origin, preserving its exact ID, values and frozen evidence.
  const originalKinds: InterestOriginalEvidenceKind[] = ["tire_curation_revision", "tire_lifecycle_event", "tire_identity_revision", "tire_catalog_revision"];
  const originalId = "synthetic/origin #?";
  for (const kind of originalKinds) {
    const original: InterestOriginalEvidence = {
      schema: "interest-original-evidence@1", scope: "local_workspace", data_state: "local_snapshot",
      kind, record_id: originalId, entity_id: "synthetic-original-variant", revision: 2, fingerprint: "d".repeat(64),
      record: { id: originalId, variant_id: "synthetic-original-variant", revision: 2, action: "synthetic", before: { present: false, value: null }, after: { present: true, value: 0 }, raw_value: "-0", source_before: { value: "38.00" } },
      evidence: [{ ...event.evidence[0], kind, record_id: originalId, entity_id: "synthetic-original-variant", revision: 2, fingerprint: "d".repeat(64) }],
    };
    if (kind === "tire_catalog_revision") {
      original.record.source_id = "synthetic-source"; original.record.query_key = "synthetic-query";
      original.record.binding = {
        before: { snapshot_id: "synthetic-present", raw_hash: "e".repeat(64), source_id: "synthetic-source", query_key: "synthetic-query", present: true },
        after: { snapshot_id: "synthetic-absent", raw_hash: "f".repeat(64), source_id: "synthetic-source", query_key: "synthetic-query", present: false },
      };
      original.evidence[0] = { ...original.evidence[0], source_id: "synthetic-source", snapshot_id: "synthetic-absent", previous_snapshot_id: "synthetic-present" };
    }
    response = original;
    const reread = await tireApi.interestEvidence(kind, originalId, controller.signal);
    assert.deepEqual(reread, original);
    assert.equal(reread.entity_id, "synthetic-original-variant");
    assert.deepEqual(reread.record.after, { present: true, value: 0 });
    assert.equal(reread.record.raw_value, "-0");
    assert.equal("operator_session_id" in reread.record, false);
    if (kind === "tire_catalog_revision") {
      assert.deepEqual(reread.record.binding, original.record.binding);
      assert.equal(reread.evidence[0].snapshot_id, "synthetic-absent");
      assert.notEqual(reread.fingerprint, "f".repeat(64));
    }
    check(`/v1/interest-evidence/${kind}/synthetic%2Forigin%20%23%3F?mode=history`, "GET");
  }
  for (const [rejectedStatus, code] of [[404, "interest_evidence_not_found"], [409, "interest_evidence_mismatch"]] as const) {
    status = rejectedStatus; response = { detail: { code, message: "Synthetic original evidence rejection" } };
    await assert.rejects(tireApi.interestEvidence(originalKinds[0], originalId, controller.signal), error => error instanceof ApiError && error.status === rejectedStatus && error.code === code);
  }
  const applicability: InterestCurationApplicabilityRecord = {
    id: "synthetic/applicability #?", variant_id: "synthetic-original-variant", source_id: "synthetic-source",
    before_fact_id: "synthetic-fact-v2", after_fact_id: "synthetic-fact-v3", verification_id: "synthetic-verification-304",
    revision: 7, action: "invalidate", manual_revision_watermark: 19, created_at: "2026-10-18T10:00:00Z",
    affected: [{ manual_revision_id: "synthetic-manual", manual_revision: 19, field: "utqg_treadwear", action: "manual_override", before_status: "manual_override", after_status: "needs_review", manual_fingerprint: "a".repeat(64) }],
    binding: {
      before: { snapshot_id: "synthetic-snapshot-B", source_id: "synthetic-source", query_key: "synthetic-query-B", source_url: "https://example.com/B", raw_hash: "b".repeat(64), identity_contract_version: "synthetic-identity", parsed_variants_hash: "c".repeat(64), verification_id: "synthetic-verification-B", verification_status: "ok", verified_at: "2026-10-18T09:00:00Z", present: true, member_hash: "d".repeat(64), structured_locator: "/parsed_variants/0", fact_version_id: "synthetic-fact-v2", fact_version: 2, facts_hash: "e".repeat(64), snapshot_member_fact_version: 2 },
      after: { snapshot_id: "synthetic-snapshot-A", source_id: "synthetic-source", query_key: "synthetic-query-A", source_url: "https://example.com/A", raw_hash: "f".repeat(64), identity_contract_version: "synthetic-identity", parsed_variants_hash: "c".repeat(64), verification_id: "synthetic-verification-304", verification_status: "not_modified", verified_at: "2026-10-18T10:00:00Z", present: true, member_hash: "d".repeat(64), structured_locator: "/parsed_variants/0", fact_version_id: "synthetic-fact-v3", fact_version: 3, facts_hash: "e".repeat(64), snapshot_member_fact_version: 1 },
    },
  };
  const applicabilityOriginal: InterestOriginalEvidence = { schema: "interest-original-evidence@1", scope: "local_workspace", data_state: "local_snapshot", kind: "tire_curation_applicability_event", record_id: applicability.id, entity_id: applicability.variant_id, revision: 7, fingerprint: "9".repeat(64), record: applicability, evidence: [{ ...event.evidence[0], kind: "tire_curation_applicability_event", record_id: applicability.id, entity_id: applicability.variant_id, revision: 7, source_id: applicability.source_id, snapshot_id: "synthetic-snapshot-A", previous_snapshot_id: "synthetic-snapshot-B", fingerprint: "9".repeat(64) }] };
  applicabilityOriginal.evidence[0].verification_ids = ["synthetic-verification-B", "synthetic-verification-304"];
  applicabilityOriginal.evidence.push({ ...event.evidence[0], kind: "tire_curation_revision", record_id: "synthetic-manual", entity_id: applicability.variant_id, source_id: applicability.source_id, revision: 19, fingerprint: "a".repeat(64) });
  status = 200; response = applicabilityOriginal;
  const readApplicability = await tireApi.interestEvidence("tire_curation_applicability_event", applicability.id, controller.signal);
  assert.deepEqual(readApplicability, applicabilityOriginal);
  assert.notEqual(applicability.binding.before.query_key, applicability.binding.after.query_key);
  assert.notEqual(applicability.binding.after.fact_version, applicability.binding.after.snapshot_member_fact_version);
  assert.notEqual(applicability.revision, applicability.affected[0].manual_revision);
  check("/v1/interest-evidence/tire_curation_applicability_event/synthetic%2Fapplicability%20%23%3F?mode=history", "GET");
  for (const [rejectedStatus, code] of [[404, "interest_not_found"], [404, "interest_notification_not_found"], [409, "interest_revision_conflict"], [409, "interest_archived"], [409, "interest_state_conflict"], [422, "invalid_interest"]] as const) {
    status = rejectedStatus; response = { detail: { code, message: "Synthetic rejection" } };
    await assert.rejects(tireApi.interest(record.id, controller.signal), error => error instanceof ApiError && error.status === rejectedStatus && error.code === code);
  }
  controller.abort();
  await assert.rejects(tireApi.previewInterests(previewRequest, controller.signal), error => error instanceof DOMException && error.name === "AbortError");
  await assert.rejects(tireApi.interestEvidence(originalKinds[0], originalId, controller.signal), error => error instanceof DOMException && error.name === "AbortError");
  await assert.rejects(tireApi.interestEvidence("tire_curation_applicability_event", applicability.id, controller.signal), error => error instanceof DOMException && error.name === "AbortError");
  console.log("interest-contract: seven conditions, nine domains, five immutable readers, independent applicability/manual revisions, cross-query actual/member versions, exact values, errors and cancellation passed (injected transport)");
} finally { restore(); }
