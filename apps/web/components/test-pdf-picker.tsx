"use client";

import { useState } from "react";
import type { DocumentTextReference } from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import SourceTextSearch from "./source-text-search";
import TestPdfCitation from "./test-pdf-citation";

export default function TestPdfPicker({ reference, onChange }: {
  reference?: DocumentTextReference; onChange: (reference: DocumentTextReference | undefined) => void;
}) {
  const auth = useWorkbenchAuth();
  const [text, setText] = useState("");
  return <div className="test-pdf-picker">
    {reference ? <><TestPdfCitation value={{ pdf_reference: reference }} />
      <button type="button" className="text-button" onClick={() => onChange(undefined)}>移除成绩 PDF 引用</button></> : null}
    <details><summary>{reference ? "更换成绩 PDF 引用" : "关联已保存 PDF 原件"}</summary>
      <label><span>查找成绩原文的关键词</span><input maxLength={200} value={text} onChange={event => setText(event.target.value)} /></label>
      <SourceTextSearch key={auth.ownerEpoch} origin="document" automatic={false} search={{ mode: "history", text, limit: 10 }}
        selectionHint="每项成绩关联一段原件区间。请将该区间内的原文子串填入短摘录，保存时会重新核对原件。"
        selected={reference ? [{ kind: "document_text", reference }] : []}
        onToggle={selection => {
          if (selection.kind === "document_text") onChange(selection.reference.chunk_id === reference?.chunk_id ? undefined : selection.reference);
        }} />
    </details>
  </div>;
}
