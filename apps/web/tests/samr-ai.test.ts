import assert from "node:assert/strict";
import test from "node:test";
import type { AIEvidence, SamrRecallEvidence, SamrRecallResult } from "@tire/domain-types";
import { samrCurrentRequest, samrTarget, verifySamrOriginal } from "../components/samr-ai-values.ts";
import { uniqueAIReferences } from "../components/recall-evidence-values.ts";

const article = "a".repeat(32);
const reference = `/zhxx/jdczh/jdczh/art/2021/art_${article}.html`;
const sourceUrl = `https://www.samrdprc.org.cn${reference}`;
const query = { operation: "notice", reference } as const;
const result = { source_id: "samr-cn-recalls", query, data_state: "local_snapshot",
  provenance: [{ snapshot_id: "synthetic-snapshot", source_id: "samr-cn-recalls", source_url: sourceUrl }],
  document: { operation: "notice", notice: { article_id: article, reference, source_url: sourceUrl } },
} as unknown as SamrRecallResult;

test("Chinese announcement targets retain exact snapshot, native article and current query", () => {
  const target = samrTarget(result);
  assert.deepEqual(target, { query, reference: { kind: "samr_recall", snapshot_id: "synthetic-snapshot", article_id: article } });
  assert.deepEqual(samrCurrentRequest(target!), { mode: "current", source_id: "samr-cn-recalls", query_kind: "samr_recall_notice", query });
});

test("search results, absent provenance and mismatched Chinese announcement identity cannot become targets", () => {
  for (const change of [
    { query: { operation: "search" } }, { provenance: [] }, { data_state: "source_unavailable" },
    { source_id: "other" }, { query: { ...query, reference: reference.replace(article, "b".repeat(32)) } },
    { provenance: [{ ...result.provenance[0], source_url: "https://example.org/other" }] },
  ]) assert.equal(samrTarget({ ...result, ...change } as SamrRecallResult), null);
});

test("Chinese announcement reference deduplication preserves each snapshot and article", () => {
  const first = { kind: "samr_recall", snapshot_id: "one", article_id: article } as const;
  assert.equal(uniqueAIReferences([first, { ...first }, { ...first, snapshot_id: "two" }, { ...first, article_id: "b".repeat(32) }]).length, 3);
});

test("Chinese announcement original verification accepts exact bytes as plain text", async () => {
  const body = '<html><script>untrusted()</script><img src="https://example.org/private"></html>';
  const rawHash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body))), byte => byte.toString(16).padStart(2, "0")).join("");
  const evidence = { evidence_type: "samr_recall", source_id: "samr-cn-recalls", snapshot_id: "one",
    article_id: article, reference, source_url: sourceUrl, raw_hash: rawHash } as AIEvidence;
  const original = { id: "one", snapshot_id: "one", source_id: "samr-cn-recalls", query,
    body, content_type: "text/html", raw_hash: rawHash, source_url: sourceUrl } as SamrRecallEvidence;
  assert.equal(await verifySamrOriginal(evidence, original), body);
  for (const change of [{ id: "other" }, { snapshot_id: "other" }, { raw_hash: "b".repeat(64) },
    { query: { ...query, reference: reference.replace(article, "b".repeat(32)) } }, { source_id: "other" },
    { source_url: "https://example.org/other" }, { content_type: "application/json" }, { body: "tampered" }]) {
    await assert.rejects(verifySamrOriginal(evidence, { ...original, ...change } as SamrRecallEvidence), /原件与所选/);
  }
  await assert.rejects(verifySamrOriginal({ ...evidence, article_id: "b".repeat(32) }, original), /原件与所选/);
});
