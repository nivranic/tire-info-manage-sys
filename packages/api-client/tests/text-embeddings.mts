import assert from "node:assert/strict";
import test from "node:test";
import { setApiTransport, tireApi } from "../src/index.ts";
import type {
  TextEmbeddingAuthorizationPreview, TextEmbeddingAuthorizationRequest,
  TextEmbeddingAuthorizationResult, TextEmbeddingSelection, TextEmbeddingPlan,
} from "@tire/domain-types";

const selections: TextEmbeddingSelection[] = [
  { kind: "source_text", reference: { snapshot_id: "合成快照", raw_hash: "a".repeat(64),
    extractor_version: "source-html-text@1", start: 0, end: 8, chunk_id: "b".repeat(64) } },
  { kind: "document_text", reference: { document_id: "合成PDF", document_fingerprint: "c".repeat(64),
    raw_hash: "d".repeat(64), extractor_version: "workspace-pdf-text@1", page: 2,
    start: 1080, end: 1200, chunk_id: "e".repeat(64) } },
];
const authorization: TextEmbeddingAuthorizationResult = {
  purpose: "original_text_embedding@1", scope_hash: "f".repeat(64),
  authorization: { state: "granted", revision: 1, revision_id: "合成授权" },
};

await test("HTML and PDF purpose previews preserve references, recipient and cancellation", async () => {
  for (const selection of selections) {
    const response: TextEmbeddingAuthorizationPreview = {
      ...authorization, selection, text: "原始摘录🛞", text_hash: "1".repeat(64),
      recipient: { provider: "openai_embeddings", endpoint: "https://api.openai.com/v1/embeddings", allowed_host: "api.openai.com" },
      notice: "合成授权预览",
    };
    const controller = new AbortController();
    const restore = setApiTransport(async (path, init) => {
      assert.equal(path, "/v1/knowledge/text-embedding-authorizations/preview");
      assert.equal(init.method, "POST");
      assert.deepEqual(JSON.parse(String(init.body)), { selection });
      assert.equal(init.signal, controller.signal);
      assert.equal(init.credentials, "include");
      assert.equal(init.cache, "no-store");
      return new Response(JSON.stringify(response));
    });
    try { assert.deepEqual(await tireApi.textEmbeddingAuthorizationPreview(selection, controller.signal), response); }
    finally { restore(); }
  }
});

for (const action of ["grant", "revoke"] as const) {
  await test(`purpose ${action} preserves revision, explicit acknowledgement and declared rights`, async () => {
    const payload: TextEmbeddingAuthorizationRequest = {
      selection: selections[0], action, expected_revision: 1, acknowledged: true,
      scope_hash: "f".repeat(64),
      rights_basis: "自有合成材料声明", privacy_class: "private", expires_at: null,
    };
    const restore = setApiTransport(async (path, init) => {
      assert.equal(path, "/v1/knowledge/text-embedding-authorizations");
      assert.deepEqual(JSON.parse(String(init.body)), payload);
      return new Response(JSON.stringify(authorization));
    });
    try { assert.deepEqual(await tireApi.authorizeTextEmbedding(payload), authorization); }
    finally { restore(); }
  });
}

await test("text plans retain selected original bindings and use the shared run endpoint", async () => {
  const plan: TextEmbeddingPlan = {
    id: "正文计划", model: "synthetic-model", dimensions: 3, expires_at: "2026-11-12T23:59:59Z",
    documents: [], pending_chunks: 2, reserved_tokens: 200, text_contract: "original-text-semantic@1",
    selections: selections.map(selection => ({ selection, authorization_id: "合成授权" })),
  };
  const controller = new AbortController();
  let calls = 0;
  const restore = setApiTransport(async (path, init) => {
    assert.equal(init.signal, controller.signal);
    if (calls++ === 0) {
      assert.equal(path, "/v1/knowledge/text-embedding-plans");
      assert.deepEqual(JSON.parse(String(init.body)), { selections });
      return new Response(JSON.stringify(plan));
    }
    assert.equal(path, "/v1/knowledge/embedding-runs");
    assert.deepEqual(JSON.parse(String(init.body)), { plan_id: plan.id, allow_external_processing: true });
    assert.equal(new Headers(init.headers).get("Idempotency-Key"), "synthetic-key");
    return new Response(JSON.stringify({ state: "completed" }));
  });
  try {
    assert.deepEqual(await tireApi.textEmbeddingPlan(selections, controller.signal), plan);
    await tireApi.runEmbedding(plan.id, "synthetic-key", controller.signal);
    assert.equal(calls, 2);
  } finally { restore(); }
});

await test("permission errors propagate with their stable code", async () => {
  const restore = setApiTransport(async () => new Response(JSON.stringify({ detail: {
    code: "text_embedding_use_not_allowed", message: "用途许可需要核对",
  } }), { status: 403 }));
  try { await assert.rejects(tireApi.textEmbeddingPlan(selections), /用途许可需要核对/); }
  finally { restore(); }
});
