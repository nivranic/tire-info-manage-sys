import assert from "node:assert/strict";
import { test } from "node:test";
import type { BinaryQuarantinePayloadV2, WheelFitment } from "@tire/domain-types";
import { assertBinaryReviewBasis, assertFrozenBinaryReviewBasis, binaryLossValue, binaryReviewEventBasis, binaryReviewInput, binaryReviewKnown, binaryReviewLossRows,
  captureBinaryReviewOwner, createBinaryReviewRevocation, freezeBinaryReviewBasis, isBinaryQuarantineDetail,
  type BinaryReviewBasis, type BinaryReviewSelection } from "../components/binary-quarantine-review-context.ts";
import { createRawEvidenceOperations, RawEvidenceDisplayChanged, RawEvidenceViewChanged, type RawEvidenceOwner } from "../components/raw-evidence-v2-context.ts";

const hash = "a".repeat(64), bundle = "b".repeat(64), digest = "c".repeat(64);
const selection: BinaryReviewSelection = { id: "quarantine-a", sourceId: "fixture-vehicle", query: { vehicle_id: "xiaomi-su7-first-generation" } };
function fitment(id: string): WheelFitment {
  const axle = { size: "245/45 R19", load_index: "102", speed_rating: "V", oe_mark: null, manufacturer_product_code: null, matched_tire_variant_id: null };
  return { id: `fitment-${id}`, trim_id: `trim-${id}`, trim_name: `版本 ${id}`, wheel_option_name: "19 英寸", wheel_diameter_inches: 19,
    availability: "standard", front: { ...axle }, rear: { ...axle }, staggered: false, source_tire_description: "原厂轮胎",
    constraints: [], source_description: "来源说明", evidence_locator: `第 2 页 ${id}` };
}
function fixture(): BinaryReviewBasis {
  const parserIdentity = { bundle_id: bundle, parser_digest: digest, deployment_revision: 1 };
  const provenance = { contract: "vehicle-pdf-parse@1" as const, method: "sha256_bound_reviewed_mapping" as const,
    mapping_id: "xiaomi-su7-first-generation-pdf@1", source_raw_hash: hash, bundle_id: bundle, mapping_file_sha256: "d".repeat(64) };
  const payload: BinaryQuarantinePayloadV2 = {
    vehicle: { id: selection.query.vehicle_id, manufacturer: { id: "maker", name: "制造商" }, model: "车型", generation: "第一代", model_year: null,
      region: "CN", source_vehicle_id: "vehicle-source" },
    trims: ["a", "b"].map(id => ({ id: `trim-${id}`, name: `版本 ${id}`, source_trim_id: id, model_year: null, wheel_option_ids: [`fitment-${id}`] })),
    fitments: [fitment("a"), fitment("b")], footnotes: ["第一条", "第二条"],
    parse_method: "sha256_bound_reviewed_mapping", mapping_id: provenance.mapping_id, parse_provenance: provenance,
  };
  const quality = { ruleset: "vehicle-field-loss@1", threshold: 0.3, baseline_rows: 5, candidate_rows: 5, aligned_rows: 5, lost_rows: 0,
    row_loss_ratio: 0, known_fields: 10, lost_field_count: 4, field_loss_ratio: 0.4, reason_codes: ["field_loss_threshold"],
    lost_fields: [{ row_key: "fitment-a", paths: ["front.load_index"] }], lost_row_keys: [], ambiguous_keys: [] };
  const common = { evidence_format: "raw-evidence-v2" as const, body_encoding: "binary" as const, body: null,
    raw_capture_id: "capture-a", raw_hash: hash, byte_count: 80, content_type: "application/pdf" as const,
    source_url: "https://fixture.invalid/config.pdf", parser_version: "parser@1" };
  return {
    detail: { ...common, id: selection.id, query_id: "query-a", source_id: selection.sourceId, observed_at: "2026-10-20T02:00:00Z",
      previous_snapshot_id: "snapshot-a", status: "quarantined", reason_codes: ["field_loss_threshold"],
      evidence_path: `/v1/quarantines/${selection.id}?mode=history`, data_state: "local_snapshot", accepted: false,
      kind: "field_loss", target_kind: "vehicle", vehicle_id: selection.query.vehicle_id,
      content_path: `/v1/quarantines/${selection.id}/content?mode=history`, parse_method: payload.parse_method, mapping_id: payload.mapping_id,
      metrics: { baseline_rows: 5, candidate_rows: 5, aligned_rows: 5, lost_rows: 0, row_loss_ratio: 0, known_fields: 10, lost_fields: 4, field_loss_ratio: 0.4 },
      candidates: structuredClone(payload.fitments), vehicle_payload: structuredClone(payload), quality },
    review: { quarantine_id: selection.id, scope: "local_workspace", state: "pending", revision: 0, can_approve: true, restriction: null,
      baseline_snapshot_id: "snapshot-a", current_snapshot_id: "snapshot-a", applied_query_id: null,
      comparison: { before: structuredClone(payload), candidate: structuredClone(payload) }, history: [], history_truncated: false,
      evidence_format: "raw-evidence-v2", binding_contract: "vehicle-binary@1", binding_hash: "e".repeat(64),
      raw_evidence: { body_encoding: common.body_encoding, body: null, raw_capture_id: common.raw_capture_id, raw_hash: hash,
        byte_count: common.byte_count, content_type: common.content_type, source_url: common.source_url, parser_version: common.parser_version,
        parser_identity: parserIdentity, parse_provenance: structuredClone(provenance) } },
    capture: { ...common, id: "capture-a", query_id: "query-a", source_id: selection.sourceId, target_kind: "vehicle",
      observed_at: "2026-10-20T01:00:00Z", parser_identity: structuredClone(parserIdentity), query: structuredClone(selection.query),
      query_state: "completed", query_reason: null, processing_unconfirmed: false, evidence_path: "/v1/captures/capture-a?mode=history",
      data_state: "local_snapshot", receipt_only: true, storage_kind: "object_store", content_path: "/v1/captures/capture-a/content?mode=history",
      parse_method: null, mapping_id: null },
  };
}

test("parsed detail and unparsed capture bind with real null and independent phase timestamps", () => {
  const value = fixture(); assertBinaryReviewBasis(value, selection);
  assert.equal(value.capture.parse_method, null); assert.notEqual(value.capture.observed_at, value.detail.observed_at);
  assert.ok(isBinaryQuarantineDetail(value.detail));
  assert.ok(!isBinaryQuarantineDetail({ ...value.detail, kind: "response_rejected" } as unknown as BinaryReviewBasis["detail"]));
  for (const reason_codes of [["row_loss_threshold"], ["field_loss_threshold"], ["row_loss_threshold", "field_loss_threshold"]]) {
    const next = fixture(); next.detail.reason_codes = reason_codes; assertBinaryReviewBasis(next, selection);
  }
});

test("every ownership and common raw mismatch fails closed without relying on PDF hash alone", () => {
  const changes: [string, (value: BinaryReviewBasis) => void][] = [
    ["detail id", value => { value.detail.id = "other"; }], ["review id", value => { value.review.quarantine_id = "other"; }],
    ["baseline", value => { value.review.baseline_snapshot_id = "other"; }], ["detail source", value => { value.detail.source_id = "other"; }],
    ["capture id", value => { value.capture.id = "other"; }], ["query id", value => { value.capture.query_id = "other"; }],
    ["capture source", value => { value.capture.source_id = "other"; }], ["target", value => { value.capture.target_kind = "tire"; }],
    ["full query", value => { value.capture.query.extra = true; }],
    ["candidate", value => { value.review.comparison.candidate.footnotes = ["变化"]; }],
    ["fitment list", value => { value.detail.candidates.reverse(); }],
    ["capture parser digest", value => { value.capture.parser_identity!.parser_digest = "f".repeat(64); }],
    ["capture parser bundle", value => { value.capture.parser_identity!.bundle_id = "f".repeat(64); }],
    ["capture parser revision", value => { value.capture.parser_identity!.deployment_revision = 2; }],
    ["capture mapping must remain null", value => { (value.capture as unknown as Record<string, unknown>).mapping_id = value.detail.mapping_id; }],
    ["capture method must remain null", value => { (value.capture as unknown as Record<string, unknown>).parse_method = value.detail.parse_method; }],
  ];
  for (const field of ["body_encoding", "body", "raw_capture_id", "raw_hash", "byte_count", "content_type", "source_url", "parser_version"] as const) {
    changes.push([`review raw ${field}`, value => { (value.review.raw_evidence as unknown as Record<string, unknown>)[field] = "changed"; }]);
    changes.push([`capture raw ${field}`, value => { (value.capture as unknown as Record<string, unknown>)[field] = "changed"; }]);
  }
  for (const field of ["contract", "method", "mapping_id", "source_raw_hash", "bundle_id", "mapping_file_sha256"] as const) {
    changes.push([`provenance ${field}`, value => { (value.review.raw_evidence.parse_provenance as unknown as Record<string, unknown>)[field] = "changed"; }]);
  }
  for (const [label, change] of changes) { const value = fixture(); change(value); assert.throws(() => assertBinaryReviewBasis(value, selection), RawEvidenceDisplayChanged, label); }
});

test("all metadata is copied/deep-frozen; every endpoint field drift clears the frozen basis", () => {
  const value = fixture(), frozen = freezeBinaryReviewBasis(value, selection);
  assert.notEqual(frozen.metadata.detail, value.detail);
  assert.ok(Object.isFrozen(frozen.metadata.review.comparison.candidate.fitments[0].front));
  assert.ok(Object.isFrozen(frozen.metadata.capture.query));
  for (const endpoint of ["detail", "review", "capture"] as const) {
    for (const key of Object.keys(value[endpoint])) {
      const changed = structuredClone(value);
      (changed[endpoint] as unknown as Record<string, unknown>)[key] = "changed";
      assert.throws(() => assertFrozenBinaryReviewBasis(frozen, changed, selection), RawEvidenceDisplayChanged, `${endpoint}.${key}`);
    }
  }
  const reordered = structuredClone(value); reordered.capture = Object.fromEntries(Object.entries(reordered.capture).reverse()) as BinaryReviewBasis["capture"];
  assertFrozenBinaryReviewBasis(frozen, reordered, selection);
  const ordered = structuredClone(value); ordered.capture.query.order = ["front", "rear"];
  const orderSelection = { ...selection, query: { ...selection.query, order: ["front", "rear"] } } as BinaryReviewSelection;
  const withOrder = freezeBinaryReviewBasis(ordered, orderSelection);
  ordered.capture.query.order = ["rear", "front"];
  assert.throws(() => assertFrozenBinaryReviewBasis(withOrder, ordered, orderSelection));
});

test("root-null and empty-fitments candidates cannot masquerade as total row loss", () => {
  for (const invalid of [null, { ...fixture().review.comparison.candidate, fitments: [] }]) {
    const value = fixture(); value.review.comparison.candidate = invalid as BinaryQuarantinePayloadV2;
    assert.throws(() => assertBinaryReviewBasis(value, selection), RawEvidenceDisplayChanged);
    assert.throws(() => binaryReviewLossRows(value.review.comparison.before, invalid), RawEvidenceDisplayChanged);
  }
});

test("stable-ID row loss and null/absent field loss render without borrowing baseline values", () => {
  const before = fixture().review.comparison.before, candidate = structuredClone(before);
  candidate.trims = [candidate.trims[1]]; candidate.fitments = [candidate.fitments[1]];
  candidate.fitments[0].front.load_index = null;
  delete (candidate.fitments[0].rear as unknown as Record<string, unknown>).oe_mark;
  before.fitments[1].rear.oe_mark = "T0";
  const rows = binaryReviewLossRows(before, candidate);
  assert.deepEqual(rows.filter(row => row.kind === "record").map(row => [row.path, row.candidate]), [
    ["trims[id=trim-a]", "记录缺失"], ["fitments[id=fitment-a]", "记录缺失"],
  ]);
  assert.equal(rows.find(row => row.path === "fitments[id=fitment-b].front.load_index")?.candidate, "字段缺失（null）");
  assert.equal(rows.find(row => row.path === "fitments[id=fitment-b].rear.oe_mark")?.candidate, "字段缺失（未提供）");
  assert.equal(candidate.fitments[0].front.load_index, null); assert.ok(!Object.hasOwn(candidate.fitments[0].rear, "oe_mark"));
  assert.equal(binaryLossValue(null), "字段缺失（null）"); assert.equal(binaryLossValue(undefined, false), "字段缺失（未提供）");
  const reversed = structuredClone(before); reversed.trims.reverse(); reversed.fitments.reverse();
  assert.deepEqual(binaryReviewLossRows(before, reversed), []);
});

test("quality known-value semantics include blank strings and recursively empty lists, but keep zero/false", () => {
  for (const value of [undefined, null, "", " \t\r\n", "\u001c\u0085\u3000", [], [null, " ", [], { code: null }], {}, { nested: [null, " "] }]) {
    assert.equal(binaryReviewKnown(value), false, JSON.stringify(value));
  }
  for (const value of [0, false, [null, 0], ["", false], { flag: false }, { count: 0 }, "A", "\ufeff"]) {
    assert.equal(binaryReviewKnown(value), true, JSON.stringify(value));
  }
  const before = fixture().review.comparison.before;
  before.fitments[0].constraints = ["A"];
  for (const [constraints, label] of [[[], "字段缺失（空数组）"], [[" ", "\t"], "字段缺失（全未知数组）"]] as const) {
    const candidate = structuredClone(before);
    candidate.fitments[0].constraints = [...constraints]; candidate.fitments[0].source_tire_description = " \t\r\n";
    const rows = binaryReviewLossRows(before, candidate);
    assert.equal(rows.find(row => row.path === "fitments[id=fitment-a].constraints")?.candidate, label);
    assert.equal(rows.find(row => row.path === "fitments[id=fitment-a].source_tire_description")?.candidate, "字段缺失（空白字符串）");
    assert.deepEqual(candidate.fitments[0].constraints, constraints);
    assert.deepEqual(before.fitments[0].constraints, ["A"]);
  }
  const vehicle: Record<string, unknown> = { id: "vehicle", flag: false, count: 0, unknown: " " };
  const old = { vehicle, trims: [], fitments: [{ id: "fitment" }] }, next = structuredClone(old);
  assert.deepEqual(binaryReviewLossRows(old, next), []);
  next.vehicle.flag = null; next.vehicle.count = null; next.vehicle.unknown = null;
  assert.deepEqual(binaryReviewLossRows(old, next).map(row => [row.path, row.before, row.candidate]), [
    ["vehicle.flag", "false", "字段缺失（null）"], ["vehicle.count", "0", "字段缺失（null）"],
  ]);
});

test("new UI input trims and counts Unicode code points; history preserves legal whitespace exactly", () => {
  assert.deepEqual(binaryReviewInput("  核验员  ", "  核对\r\nPDF\t原件  "), { operator: "核验员", reason: "核对\r\nPDF\t原件" });
  assert.ok(binaryReviewInput("😀".repeat(80), "😀".repeat(5)));
  assert.equal(binaryReviewInput("😀".repeat(81), "核对原件记录"), null);
  assert.ok(binaryReviewInput("核验员", "😀".repeat(2000)));
  assert.equal(binaryReviewInput("核验员", "😀".repeat(2001)), null);
  for (const reason of ["    ", "四个字", "核对\u0000失败", "核对\ud800失败"]) assert.equal(binaryReviewInput("核验员", reason), null);
  const value = fixture(), text = "  <script>文本</script>\r\n\t 保持原样  ";
  value.review.history.push({ id: "review-a", quarantine_id: "other-shared-binding", revision: 1, action: "approve", operator: " \t自报\r\n ", reason: text,
    created_at: "2026-10-20T02:00:00Z", expires_at: "2026-10-21T02:00:00Z" });
  const display = freezeBinaryReviewBasis(value, selection);
  assert.equal(display.metadata.review.history[0].reason, text);
  assert.equal(display.metadata.review.history[0].operator, " \t自报\r\n ");
});

function authority() {
  let liveEpoch = 1, transportEpoch = 1;
  const owner = new AbortController(), revocation = createBinaryReviewRevocation(), observers = new Set<() => void>();
  let current: RawEvidenceOwner = { ready: true, ownerEpoch: 1, ownerSignal: owner.signal, isCurrentOwner: epoch => epoch === liveEpoch, selection: "A", transportEpoch: 1 };
  const read = () => ({ ...current, transportEpoch, selection: `${current.selection}:${revocation.generation()}` });
  const operations = createRawEvidenceOperations(read, listener => { observers.add(listener); return () => { observers.delete(listener); }; });
  return { owner, revocation, operations, read, observers, update(value: Partial<RawEvidenceOwner>) { current = { ...current, ...value }; },
    rebind() { liveEpoch++; }, silentTransport() { transportEpoch++; }, notifyTransport() { transportEpoch++; for (const listener of [...observers]) listener(); } };
}

test("idle basis checks live owner epoch, signal, parent generation and silent transport changes", () => {
  const changes: [string, (value: ReturnType<typeof authority>) => void][] = [
    ["owner starts before render", value => value.rebind()], ["owner abort", value => value.owner.abort()],
    ["new signal", value => value.update({ ownerSignal: new AbortController().signal })], ["not ready", value => value.update({ ready: false })],
    ["owner epoch", value => value.update({ ownerEpoch: 3 })], ["selection", value => value.update({ selection: "B" })],
    ["silent transport getter", value => value.silentTransport()], ["parent close/open/refresh", value => value.revocation.revoke()],
  ];
  for (const [label, change] of changes) {
    const value = authority(), idle = captureBinaryReviewOwner(value.read); idle.assertCurrent(); change(value);
    assert.throws(idle.assertCurrent, RawEvidenceViewChanged, label);
  }
  const value = authority(), original = captureBinaryReviewOwner(value.read);
  value.revocation.revoke(); value.update({ selection: "B" }); value.revocation.revoke(); value.update({ selection: "A" });
  assert.throws(original.assertCurrent, RawEvidenceViewChanged);
});

test("confirm/save events revoke a silently stale idle basis and late then/finally cannot restore it", async () => {
  for (const event of ["confirm", "save"]) {
    const value = authority(), operation = value.operations.begin(); operation.finish();
    const idle = { owner: captureBinaryReviewOwner(value.read) };
    let displayed = true, confirmed = true, revokes = 0, lateUpdates = 0, finish!: () => void;
    const revoke = () => { revokes++; displayed = false; confirmed = false; value.operations.invalidate(); };
    assert.equal(binaryReviewEventBasis(idle, revoke), idle); assert.equal(revokes, 0);
    const pending = new Promise<void>(resolve => { finish = resolve; });
    const late = (async () => {
      try { await pending; operation.fence.assertCurrent(); displayed = true; confirmed = true; }
      finally { try { operation.fence.assertCurrent(); lateUpdates++; } catch { /* Stale finally cannot update UI. */ } }
    })();
    // No observer is called; the user event checks the live transport getter.
    value.silentTransport(); assert.equal(binaryReviewEventBasis(idle, revoke), null, event);
    assert.equal(revokes, 1); assert.equal(displayed, false); assert.equal(confirmed, false);
    finish(); await assert.rejects(late, RawEvidenceViewChanged, event);
    assert.equal(displayed, false); assert.equal(confirmed, false); assert.equal(lateUpdates, 0);
    assert.equal(binaryReviewEventBasis(null, revoke), null); assert.equal(revokes, 2);
  }
});

test("detail/review/capture share one begin, so sequential reads do not cancel each other", async () => {
  const value = authority(), operation = value.operations.begin(), seen: string[] = [];
  for (const name of ["detail", "review", "capture"]) {
    operation.fence.assertCurrent(); await Promise.resolve(); operation.fence.assertCurrent(); seen.push(name);
  }
  assert.deepEqual(seen, ["detail", "review", "capture"]); assert.equal(operation.controller.signal.aborted, false);
  operation.finish(); assert.equal(value.observers.size, 0);
});

test("synchronous parent revocation clears idle confirmation and prevents every late async stage", async () => {
  for (const stage of ["detail", "review", "capture", "preflight", "post-response", "finally"]) {
    const value = authority(), operation = value.operations.begin(); let confirmed = true, updates = 0, finish!: () => void;
    const stop = value.revocation.subscribe(() => { confirmed = false; value.operations.invalidate(); });
    const pending = new Promise<void>(resolve => { finish = resolve; });
    const result = (async () => { operation.fence.assertCurrent(); await pending; operation.fence.assertCurrent(); updates++; })();
    value.revocation.revoke(); assert.equal(confirmed, false); finish();
    await assert.rejects(result, RawEvidenceViewChanged, stage); assert.equal(updates, 0); stop(); operation.finish();
  }
});

test("uncertain dispatched result survives close/reopen without acting as a success receipt", () => {
  const control = createBinaryReviewRevocation(); control.markUncertain(selection.id); control.revoke();
  assert.equal(control.isUncertain(selection.id), true); assert.equal(control.isUncertain("other"), false);
  assert.equal(control.generation(), 1);
  const latest = fixture(); latest.review.revision = 9; latest.review.state = "kept_quarantined";
  latest.review.history = [{ id: "latest-review", quarantine_id: "other-shared-binding", revision: 9, action: "keep_quarantined", operator: "另一署名", reason: "最新决定保留隔离",
    created_at: "2026-10-20T04:00:00Z", expires_at: "2026-10-21T04:00:00Z" }];
  assertBinaryReviewBasis(latest, selection);
  assert.equal(freezeBinaryReviewBasis(latest, selection).metadata.review.revision, 9);
});
