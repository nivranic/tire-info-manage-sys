import assert from "node:assert/strict";
import test from "node:test";
import { testPdfReference } from "../components/test-pdf-values.ts";
import { aiReferenceKey, uniqueAIReferences } from "../components/recall-evidence-values.ts";
import type { AITestEventReference } from "@tire/domain-types";

test("AI test reference keys retain explicit original measurement numbers", () => {
  const whole: AITestEventReference = { kind: "test_event", event_id: "synthetic-event", event_revision: 1 };
  const subset = { ...whole, measurement_numbers: [3, 2] };
  assert.equal(aiReferenceKey(whole), JSON.stringify(["test_event", "synthetic-event", 1]));
  assert.equal(aiReferenceKey(subset), aiReferenceKey({ ...whole, measurement_numbers: [2, 3] }));
  assert.notEqual(aiReferenceKey(whole), aiReferenceKey(subset));
  assert.equal(uniqueAIReferences([whole, subset, { ...whole, measurement_numbers: [2, 3] }]).length, 2);
});

const reference = { document_id: "synthetic-document", document_fingerprint: "a".repeat(64), raw_hash: "b".repeat(64),
  extractor_version: "pdf-page-text@1+synthetic", page: 4, start: 12, end: 240, chunk_id: "c".repeat(64) };

test("legacy measurements have no original citation and exact PDF references retain all fields", () => {
  for (const value of [undefined, null, "value", {}, { raw_value: "38.00" }, { pdf_reference: undefined }]) assert.equal(testPdfReference(value), null);
  assert.deepEqual(testPdfReference({ raw_value: "38.00", pdf_reference: reference }), reference);
});

test("malformed PDF references cannot reach original recovery or purpose operations", () => {
  for (const change of [{ document_id: "" }, { document_fingerprint: "invalid" }, { raw_hash: true }, { chunk_id: "A".repeat(64) },
    { extractor_version: "" }, { page: 0 }, { page: 2001 }, { page: true }, { start: -1 }, { start: 1.5 },
    { end: 100001 }, { end: 12 }, { end: "240" }, { extra: "unbound" }]) {
    assert.throws(() => testPdfReference({ pdf_reference: { ...reference, ...change } }), /引用格式无效/);
  }
  for (const value of [null, false, [], "unbound"]) assert.throws(() => testPdfReference({ pdf_reference: value }), /引用格式无效/);
  const missing = { ...reference } as Partial<typeof reference>;
  delete missing.page;
  assert.throws(() => testPdfReference({ pdf_reference: missing }), /引用格式无效/);
});
