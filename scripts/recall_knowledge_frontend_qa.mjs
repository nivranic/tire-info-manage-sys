// Pure selection and browser/native transport contracts; no API, DB or provider.
import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "../packages/native-client/tests/load-typescript.mjs";

const values = await loadTypeScript("../apps/web/components/recall-evidence-values.ts", import.meta.url);
const sdk = await loadTypeScript("../packages/api-client/src/index.ts", import.meta.url);
const native = await loadTypeScript("../packages/native-client/src/index.ts", import.meta.url);
const recall = (snapshot_id = "snapshot-a", recall_revision_id = "revision-a") => ({ kind: "recall", snapshot_id, recall_revision_id });

test("product hits deduplicate by whole announcement reference, retaining raw and semantic bindings", () => {
  const refs = [recall(), { recall_revision_id: "revision-a", kind: "recall", snapshot_id: "snapshot-a" },
    recall("snapshot-b"), recall("snapshot-a", "revision-b"), recall("snapshot-empty", null)];
  const items = refs.map((reference, index) => ({ id: `doc-${index}`, reference }));
  assert.deepEqual(values.selectedKnowledgeReferences(items, items.map(item => item.id)), [refs[1], ...refs.slice(2)]);
  assert.deepEqual(values.selectedKnowledgeReferences(items, ["doc-0", "doc-1"]), [refs[1]]);
  assert.deepEqual(values.selectedKnowledgeReferences(items, ["doc-4"]), [recall("snapshot-empty", null)]);
});

test("six-source cap counts distinct references and still permits another hit from an already selected announcement", () => {
  const refs = Array.from({ length: 6 }, (_, index) => recall(`snapshot-${index}`));
  assert.equal(values.canSelectKnowledgeReference(refs, recall("snapshot-new")), false);
  assert.equal(values.canSelectKnowledgeReference(refs, recall("snapshot-0")), true);
  assert.equal(values.canSelectKnowledgeReference(refs, recall("snapshot-0", "another-revision")), false);
  assert.equal(values.canSelectKnowledgeReference(refs.slice(0, 5), recall("snapshot-new")), true);
});

test("mixed-domain references and event revisions never collapse into a recall reference", () => {
  const refs = [recall(), { kind: "vehicle", snapshot_id: "snapshot-a" },
    { kind: "tire", snapshot_id: "snapshot-a", variant_id: "tire-a" },
    { kind: "tire", snapshot_id: "snapshot-a", variant_id: "tire-b" },
    { kind: "test_event", event_id: "event-a", event_revision: 1 },
    { kind: "test_event", event_id: "event-a", event_revision: 2 },
    { kind: "change_event", change_id: "event-a" }];
  assert.equal(new Set(refs.map(values.aiReferenceKey)).size, refs.length);
  assert.deepEqual(values.uniqueAIReferences([...refs, ...refs]), refs);
});

test("browser and native preserve recall current kind, campaign and one-time consent; empty observation retains explicit null", async t => {
  for (const host of ["browser", "native"]) await t.test(host, async () => {
    const originalFetch = globalThis.fetch, calls = []; let restore;
    const queryResult = { query_id: "query-recall", source_id: "nhtsa-us-recalls", query: { campaign_number: "23T001000" }, data_state: "consent_required", records: [], consent_id: null };
    const emptyReference = recall("snapshot-empty", null);
    const reply = (path, method, body) => {
      calls.push({ path, method, body });
      if (path === "/v1/fallback-consents") return { id: "consent-recall" };
      if (path === "/v1/knowledge/search") return { items: [], applied_filters: body.filters };
      return body.consent_id ? { pack: { evidence: [{ evidence_type: "recall", observation_kind: "empty", record_count: 0 }], facts: [] }, query_result: null, reason: null }
        : body.mode === "history" ? { pack: { reference: body.references[0] }, query_result: null, reason: null }
        : { pack: null, query_result: queryResult, reason: "synthetic_offline" };
    };
    try {
      if (host === "browser") globalThis.fetch = async (path, init) => new Response(JSON.stringify(reply(path.slice(4), init.method || "GET", JSON.parse(init.body))), { headers: { "Content-Type": "application/json" } });
      else {
        globalThis.fetch = async () => assert.fail("native must not use browser networking");
        restore = sdk.setApiTransport(native.createNativeTransport(async (command, { request }) => {
          assert.equal(command, "api_request");
          const body = JSON.parse(Buffer.from(request.body_base64, "base64").toString("utf8"));
          return { status: 200, headers: { "content-type": "application/json" }, body_base64: Buffer.from(JSON.stringify(reply(request.path, request.method, body))).toString("base64") };
        }));
      }
      const payload = values.recallCurrentRequest("23T001000");
      const failed = await sdk.tireApi.prepareAI(payload);
      assert.deepEqual(failed.query_result, queryResult); assert.equal(failed.pack, null);
      const consent = await sdk.tireApi.consent(failed.query_result.query_id, "allow");
      const prepared = await sdk.tireApi.prepareAI({ ...payload, consent_id: consent.id });
      assert.equal(prepared.pack.evidence[0].record_count, 0);
      assert.deepEqual(calls[0].body, { mode: "current", query_kind: "recall_by_campaign", source_id: "nhtsa-us-recalls", query: { campaign_number: "23T001000" } });
      assert.deepEqual(calls[2].body, { ...calls[0].body, consent_id: "consent-recall" });
      assert.deepEqual(calls[1].body, { query_id: "query-recall", decision: "allow", scope: "once" });
      assert.equal("variant_ids" in calls[2].body, false); assert.equal("references" in calls[2].body, false);
      const history = await sdk.tireApi.prepareAI({ mode: "history", references: [emptyReference] });
      assert.deepEqual(history.pack.reference, emptyReference);
      await sdk.tireApi.searchKnowledge({ mode: "history", text: "", filters: { kind: "recall", campaign_number: "23T001000" } });
      assert.deepEqual(calls.at(-1).body.filters, { kind: "recall", campaign_number: "23T001000" });
      assert.ok(calls.every(call => !call.path.includes("/analyses") && !call.path.includes("analysis-streams")));
    } finally { restore?.(); globalThis.fetch = originalFetch; }
  });
});
