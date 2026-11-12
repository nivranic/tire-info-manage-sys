import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError, setApiTransport, tireApi } from "../src/index.ts";
import type { DocumentTextExcerpt, DocumentTextReference, DocumentTextSearchResult, DocumentTextState } from "@tire/domain-types";

const reference: DocumentTextReference = {
  document_id: "document/中文?one", document_fingerprint: "a".repeat(64), raw_hash: "b".repeat(64),
  extractor_version: "pdf-page-text@1+pypdf@6.19.0", page: 2, start: 1080, end: 1090, chunk_id: "c".repeat(64),
};
const excerpt: DocumentTextExcerpt = {
  kind: "document_text", reference, text: "轮胎🛞原文 <script>", offset_unit: "unicode_codepoints",
  document: {
    id: reference.document_id, raw_hash: reference.raw_hash, byte_count: 1024, content_type: "application/pdf",
    created_at: "2026-11-12T00:00:00Z", title: "合成PDF", source_url: "https://fixture.invalid/original.pdf",
    operator: "合成测试", rights_basis: "合成材料", status: "unparsed_receipt", accepted_as_facts: false,
  },
  data_state: "local_snapshot", verification_status: "original_text_excerpt", notice: "合成页码摘录",
};
const state: DocumentTextState = {
  mode: "history", document: excerpt.document,
  index: {
    status: "partial_text", page_count: 2, characters: 1090, chunks: 2, raw_hash: reference.raw_hash,
    document_fingerprint: reference.document_fingerprint, extractor_version: reference.extractor_version,
    indexed_at: "2026-11-12T00:00:00Z", parser_receipt: { reaped: true },
  },
  page: { page: 2, text: excerpt.text, text_hash: "d".repeat(64), status: "text" }, notice: excerpt.notice,
};
const result: DocumentTextSearchResult = {
  mode: "history", data_state: "local_snapshot", items: [{ ...excerpt, match: { method: "fts", matched_terms: ["轮胎"], score: -1 } }],
  total: 2040, offset: 2000, limit: 30, has_more: true, notice: excerpt.notice,
  index: { engine: "sqlite_fts5", extractor_version: reference.extractor_version, documents: 1 },
};

const actions = {
  index: (signal?: AbortSignal) => tireApi.indexDocumentText(reference.document_id, signal),
  page: (signal?: AbortSignal) => tireApi.documentText(reference.document_id, 2, signal),
  search: (signal?: AbortSignal) => tireApi.searchDocumentText({ mode: "history", text: "轮胎🛞", document_id: reference.document_id, limit: 30, offset: 2000 }, signal),
  resolve: (signal?: AbortSignal) => tireApi.resolveDocumentText(reference, signal),
};

await test("PDF index, pages, search and citation restore preserve their complete request contracts", async () => {
  const expected = [
    { path: "/v1/documents/document%2F%E4%B8%AD%E6%96%87%3Fone/text-index", method: "POST", body: { mode: "history" }, response: { ...state, page: null } },
    { path: "/v1/documents/document%2F%E4%B8%AD%E6%96%87%3Fone/text?mode=history&page=2", method: undefined, body: undefined, response: state },
    { path: "/v1/knowledge/document-text/search", method: "POST", body: { mode: "history", text: "轮胎🛞", document_id: reference.document_id, limit: 30, offset: 2000 }, response: result },
    { path: "/v1/knowledge/document-text/resolve", method: "POST", body: { mode: "history", reference }, response: excerpt },
  ];
  const controller = new AbortController();
  let calls = 0;
  const restore = setApiTransport(async (path, init) => {
    const contract = expected[calls++];
    assert.equal(path, contract.path);
    assert.equal(init.method, contract.method);
    assert.deepEqual(init.body ? JSON.parse(String(init.body)) : undefined, contract.body);
    assert.equal(init.signal, controller.signal);
    assert.equal(init.credentials, "include");
    assert.equal(init.cache, "no-store");
    return new Response(JSON.stringify(contract.response));
  });
  try {
    for (const [position, action] of Object.values(actions).entries()) {
      assert.deepEqual(await action(controller.signal), expected[position].response);
    }
    assert.equal(calls, 4);
  } finally { restore(); }
});

await test("unindexed and encrypted PDF states preserve null pages and counts", async () => {
  for (const value of [{ ...state, index: null, page: null }, {
    ...state, index: { ...state.index!, status: "encrypted" as const, page_count: null, characters: 0, chunks: 0 }, page: null,
  }]) {
    const restore = setApiTransport(async path => {
      assert.equal(path, "/v1/documents/one/text?mode=history&page=1");
      return new Response(JSON.stringify(value));
    });
    try { assert.deepEqual(await tireApi.documentText("one"), value); }
    finally { restore(); }
  }
});

for (const status of [404, 409, 422, 503]) {
  await test(`PDF ${status} errors retain status and code across all four operations`, async () => {
    let calls = 0;
    const restore = setApiTransport(async () => {
      calls++;
      return new Response(JSON.stringify({ detail: { code: "document_text_original_invalid", message: "原件核对失败" } }), { status });
    });
    try {
      for (const action of Object.values(actions)) {
        await assert.rejects(action(), cause => cause instanceof ApiError && cause.status === status && cause.code === "document_text_original_invalid");
      }
      assert.equal(calls, 4);
    } finally { restore(); }
  });
}

await test("each PDF operation propagates cancellation with one transport call", async () => {
  for (const action of Object.values(actions)) {
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
      const pending = action(controller.signal);
      controller.abort();
      await assert.rejects(pending, cause => cause instanceof DOMException && cause.name === "AbortError");
      assert.equal(calls, 1);
    } finally { restore(); }
  }
});
