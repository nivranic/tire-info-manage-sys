/** Synthetic shared SDK transport; no source or provider requests. */
import assert from "node:assert/strict";
import test from "node:test";
import { setApiTransport, tireApi } from "@tire/api-client";
import type { AIPrepareRequest, OfflineReference, SafetyGateAnalysisReference, SafetyGateResult } from "@tire/domain-types";

const reference: SafetyGateAnalysisReference = { kind: "safety_gate", snapshot_id: "synthetic-snapshot", alert_id: "-1782" };
// @ts-expect-error Server AI references do not expand device offline package domains.
const offline: OfflineReference = reference;
const query = { operation: "report", report_id: "900001", reference: "Report-2026-19" } as const;

test("historical and current Safety Gate AI requests preserve exact selection and single-use consent", async () => {
  const requests: AIPrepareRequest[] = [{ mode: "history", references: [reference] },
    { mode: "current", query_kind: "safety_gate_report", source_id: "eu-safety-gate", query, alert_ids: [reference.alert_id], consent_id: "synthetic-once" }];
  const calls: { path: string; init: RequestInit }[] = [];
  const result = { pack: null, query_result: { query, source_id: "eu-safety-gate", data_state: "consent_required", query_id: "synthetic-query" } as SafetyGateResult, reason: "timeout" };
  const restore = setApiTransport(async (path, init) => { calls.push({ path, init }); return Response.json(result); });
  try {
    for (const request of requests) {
      const response = await tireApi.prepareAI(request);
      assert.deepEqual(response, result);
    }
    calls.forEach((call, i) => {
      assert.equal(call.path, "/v1/ai/evidence-packs");
      assert.equal(call.init.method, "POST");
      assert.deepEqual(JSON.parse(String(call.init.body)), requests[i]);
    });
  } finally { restore(); }
});

test("source recovery uses the Safety Gate history endpoint and forwards cancellation", async () => {
  const controller = new AbortController();
  const restore = setApiTransport(async (path, init) => {
    assert.equal(path, "/v1/safety-gate/evidence/synthetic-snapshot?mode=history");
    assert.equal(init.signal, controller.signal);
    return Response.json({ id: reference.snapshot_id, raw_hash: "a".repeat(64), query, body: "<Safety-Gate/>" });
  });
  try { assert.equal((await tireApi.safetyGateEvidence(reference.snapshot_id, controller.signal)).id, reference.snapshot_id); }
  finally { restore(); }
});

test("cancelled preparation never creates a second request", async () => {
  const controller = new AbortController(); let calls = 0;
  const restore = setApiTransport(async (_path, init) => {
    calls++;
    return new Promise<Response>((_resolve, reject) => init.signal?.addEventListener("abort", () => reject(new DOMException("Synthetic cancellation", "AbortError")), { once: true }));
  });
  try {
    const pending = tireApi.prepareAI({ mode: "history", references: [reference] }, controller.signal);
    controller.abort();
    await assert.rejects(pending, { name: "AbortError" });
    assert.equal(calls, 1);
  } finally { restore(); }
});
