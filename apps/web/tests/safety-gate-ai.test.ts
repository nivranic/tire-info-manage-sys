import assert from "node:assert/strict";
import test from "node:test";
import type { AIEvidence, SafetyGateEvidence, SafetyGateResult } from "@tire/domain-types";
import { safetyGateCurrentRequest, safetyGateTarget, verifySafetyGateOriginal } from "../components/safety-gate-ai-values.ts";
import { uniqueAIReferences } from "../components/recall-evidence-values.ts";

const query = { operation: "report", report_id: "900001", reference: "Report-2026-19" } as const;
const result = {
  source_id: "eu-safety-gate", query, data_state: "local_snapshot",
  provenance: [{ snapshot_id: "report-snapshot", source_id: "eu-safety-gate" }],
  document: { report: { ...query }, alerts: [{ alert_id: "-1782", case_number: "SR/00001/26" }] },
} as unknown as SafetyGateResult;

test("analysis target binds the selected report snapshot and native negative alert ID", () => {
  const target = safetyGateTarget(result, "-1782");
  assert.deepEqual(target, { query, reference: { kind: "safety_gate", snapshot_id: "report-snapshot", alert_id: "-1782" } });
  assert.deepEqual(safetyGateCurrentRequest(target!), {
    mode: "current", source_id: "eu-safety-gate", query_kind: "safety_gate_report", query, alert_ids: ["-1782"],
  });
});

test("catalog, missing provenance, wrong report and absent alert cannot create an AI target", () => {
  const alternatives = [
    { ...result, query: { operation: "reports" } },
    { ...result, provenance: [] },
    { ...result, document: { ...result.document, report: { report_id: "900002", reference: query.reference } } },
    { ...result, document: { ...result.document, alerts: [] } },
    { ...result, data_state: "source_unavailable" },
  ];
  for (const value of alternatives) assert.equal(safetyGateTarget(value as SafetyGateResult, "-1782"), null);
});

test("deduplication preserves different snapshots and different alerts", () => {
  const first = { kind: "safety_gate", snapshot_id: "one", alert_id: "-1782" } as const;
  assert.equal(uniqueAIReferences([first, { ...first }, { ...first, snapshot_id: "two" }, { ...first, alert_id: "900001" }]).length, 3);
});

test("unbound originals are rejected before XML parsing or display", async () => {
  const evidence = { evidence_type: "safety_gate", source_id: "eu-safety-gate", snapshot_id: "one", alert_id: "-1782",
    case_number: "SR/00001/26", report_id: query.report_id, report_reference: query.reference, raw_hash: "a".repeat(64), source_url: "https://example.org/source" } as AIEvidence;
  evidence.raw_hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode("<Safety-Gate/>"))), byte => byte.toString(16).padStart(2, "0")).join("");
  const original = { id: "one", snapshot_id: "one", source_id: "eu-safety-gate", query,
    body: "<Safety-Gate/>", content_type: "application/xml", raw_hash: evidence.raw_hash, source_url: evidence.source_url } as SafetyGateEvidence;
  for (const change of [{ id: "other" }, { snapshot_id: "other" }, { raw_hash: "b".repeat(64) },
    { query: { ...query, report_id: "900002" } }, { source_id: "other" }, { source_url: "https://example.org/other" },
    { content_type: "text/html" }, { body: "tampered" }]) {
    await assert.rejects(verifySafetyGateOriginal(evidence, { ...original, ...change } as SafetyGateEvidence), /原件与所选/);
  }
});
