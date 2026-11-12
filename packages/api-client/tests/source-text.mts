import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError, setApiTransport, tireApi } from "../src/index.ts";
import type { SourceTextExcerpt, SourceTextReference, SourceTextSearchResult } from "@tire/domain-types";

const excerptText = "轮胎🛞原文 <script>";
const reference: SourceTextReference = {
  snapshot_id: "old-snapshot", raw_hash: "a".repeat(64), extractor_version: "source-html-text@1",
  start: 1080, end: 1080 + Array.from(excerptText).length, chunk_id: "b".repeat(64),
};
const excerpt: SourceTextExcerpt = {
  kind: "source_text", reference, text: excerptText, offset_unit: "unicode_codepoints",
  content_type: "text/html", snapshot_id: reference.snapshot_id, raw_hash: reference.raw_hash,
  source_id: "synthetic-source", source_url: "https://fixture.invalid/original",
  parser_version: "fixture@1", observed_at: "2026-11-12T00:00:00Z", verified_at: "2026-11-12T00:00:00Z",
  data_state: "local_snapshot", verification_status: "original_text_excerpt", notice: "合成页面范围摘录",
};
const result: SourceTextSearchResult = {
  mode: "history", data_state: "local_snapshot", items: [{ ...excerpt, match: { method: "fts", matched_terms: ["轮胎"], score: -1 } }],
  total: 2040, offset: 2000, limit: 30, has_more: true, notice: "合成页面范围摘录",
  index: { engine: "sqlite_fts5", extractor_version: reference.extractor_version, snapshots: 1 },
};

await test("source-text search retains explicit history, Unicode, source and bounded pagination", async () => {
  const payload = { mode: "history" as const, text: "轮胎🛞原文", source_id: "source/one?中文", limit: 30, offset: 2000 };
  const controller = new AbortController();
  let calls = 0;
  const restore = setApiTransport(async (path, init) => {
    calls++;
    assert.equal(path, "/v1/knowledge/source-text/search");
    assert.equal(init.method, "POST");
    assert.deepEqual(JSON.parse(String(init.body)), payload);
    assert.equal(init.signal, controller.signal);
    assert.equal(init.credentials, "include");
    assert.equal(init.cache, "no-store");
    return new Response(JSON.stringify(result));
  });
  try { assert.deepEqual(await tireApi.searchSourceText(payload, controller.signal), result); assert.equal(calls, 1); }
  finally { restore(); }
});

await test("citation restore sends the complete old reference and preserves server Unicode text", async () => {
  const controller = new AbortController();
  let calls = 0;
  const restore = setApiTransport(async (path, init) => {
    calls++;
    assert.equal(path, "/v1/knowledge/source-text/resolve");
    assert.deepEqual(JSON.parse(String(init.body)), { mode: "history", reference });
    assert.equal(init.signal, controller.signal);
    assert.equal(init.credentials, "include");
    assert.equal(init.cache, "no-store");
    return new Response(JSON.stringify(excerpt));
  });
  try { assert.deepEqual(await tireApi.resolveSourceText(reference, controller.signal), excerpt); assert.equal(calls, 1); }
  finally { restore(); }
});

for (const status of [404, 409, 422, 503]) {
  await test(`source-text ${status} errors preserve status and code after one request`, async () => {
    let calls = 0;
    const restore = setApiTransport(async () => {
      calls++;
      return new Response(JSON.stringify({ detail: { code: "source_text_original_invalid", message: "原件核对失败" } }), { status });
    });
    try {
      for (const request of [() => tireApi.searchSourceText({ mode: "history", text: "轮胎" }), () => tireApi.resolveSourceText(reference)]) {
        await assert.rejects(request(), cause => cause instanceof ApiError && cause.status === status && cause.code === "source_text_original_invalid");
      }
      assert.equal(calls, 2);
    } finally { restore(); }
  });
}

await test("both original-text operations propagate abort and perform one transport call", async () => {
  for (const action of ["search", "resolve"] as const) {
    const controller = new AbortController();
    let calls = 0;
    const restore = setApiTransport(async (_path, init) => {
      calls++;
      assert.equal(init.signal, controller.signal);
      return new Promise<Response>((_resolve, reject) => {
        init.signal!.addEventListener("abort", () => reject(new DOMException("cancelled", "AbortError")), { once: true });
      });
    });
    try {
      const pending = action === "search" ? tireApi.searchSourceText({ mode: "history", text: "轮胎" }, controller.signal) : tireApi.resolveSourceText(reference, controller.signal);
      controller.abort();
      await assert.rejects(pending, cause => cause instanceof DOMException && cause.name === "AbortError");
      assert.equal(calls, 1);
    } finally { restore(); }
  }
});

await test("tokenless empty results preserve the API's omitted index field", async () => {
  const empty: SourceTextSearchResult = { mode: "history", data_state: "local_snapshot", items: [], total: 0, offset: 0, limit: 12, has_more: false, notice: "合成空结果" };
  const restore = setApiTransport(async () => new Response(JSON.stringify(empty)));
  try { assert.deepEqual(await tireApi.searchSourceText({ mode: "history", text: "!!!" }), empty); }
  finally { restore(); }
});

await test("existing exact-SKU knowledge requests retain their structured endpoint and filters", async () => {
  const payload = { mode: "history" as const, text: "轮胎", filters: { kind: "tire" as const, variant_id: "exact-sku", product_code: "fixture-code", size: "245/40R20" } };
  let calls = 0;
  const restore = setApiTransport(async (path, init) => {
    calls++;
    assert.equal(path, "/v1/knowledge/search");
    assert.deepEqual(JSON.parse(String(init.body)), payload);
    return new Response(JSON.stringify({ synthetic: true }));
  });
  try { await tireApi.searchKnowledge(payload); assert.equal(calls, 1); }
  finally { restore(); }
});
