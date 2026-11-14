"use client";

import { useState } from "react";
import type { DocumentTextReference } from "@tire/domain-types";
import OriginalTextCitation from "./original-text-citation";
import TextEmbeddingPurposeDialog from "./text-embedding-purpose";
import { testPdfReference } from "./test-pdf-values";
import { useWorkbenchAuth } from "./auth";

function Citation({ reference }: { reference: DocumentTextReference }) {
  const [purposeOpen, setPurposeOpen] = useState(false);
  const selection = { kind: "document_text", reference } as const;
  return <div className="test-pdf-citation">
    <OriginalTextCitation selection={selection} />
    <button type="button" className="text-button" onClick={() => setPurposeOpen(true)}>核对成绩 PDF 用途</button>
    {purposeOpen ? <TextEmbeddingPurposeDialog selection={selection} onClose={() => setPurposeOpen(false)} /> : null}
  </div>;
}

export default function TestPdfCitation({ value }: { value: unknown }) {
  const auth = useWorkbenchAuth();
  let reference: DocumentTextReference | null;
  try { reference = testPdfReference(value); }
  catch (cause) { return <p role="alert">{cause instanceof Error ? cause.message : "成绩 PDF 引用读取失败。"}</p>; }
  return reference ? <Citation key={`${auth.ownerEpoch}:${JSON.stringify(reference)}`} reference={reference} /> : null;
}
