"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { TextEmbeddingSelection } from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";

export default function OriginalTextCitation({ selection, retainedAt }: { selection: TextEmbeddingSelection; retainedAt?: string }) {
  const auth = useWorkbenchAuth();
  const operation = useRef<AbortController | null>(null);
  const key = `${auth.ownerEpoch}:${JSON.stringify(selection)}`;
  const [resolved, setResolved] = useState<{ key: string; text: string } | null>(null);
  const [error, setError] = useState<{ key: string; text: string } | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const busy = busyKey === key;

  useEffect(() => () => { operation.current?.abort(); operation.current = null; }, [key]);

  async function resolve() {
    if (operation.current || auth.ownerSignal.aborted) return;
    const controller = new AbortController();
    operation.current = controller; setBusyKey(key); setError(null); setResolved(null);
    const signal = AbortSignal.any([controller.signal, auth.ownerSignal]);
    try {
      const value = selection.kind === "source_text"
        ? await tireApi.resolveSourceText(selection.reference, signal)
        : await tireApi.resolveDocumentText(selection.reference, signal);
      if (!signal.aborted && operation.current === controller) setResolved({ key, text: value.text });
    } catch (cause) {
      if (!signal.aborted && operation.current === controller) setError({ key, text: cause instanceof Error ? cause.message : "原件引用核对未完成。" });
    } finally {
      if (operation.current === controller) { operation.current = null; setBusyKey(null); }
    }
  }

  return <section className="ai-original-text vector-plan-document" aria-label="原文摘录引用">
    <p className="review-boundary">原文摘录保留{selection.kind === "document_text" ? `文档第 ${selection.reference.page} 页` : "来源页面"}范围，具体SKU及适用性需对应结构化证据。</p>
    {retainedAt ? <p>原件留存 {new Date(retainedAt).toLocaleString("zh-CN")} · 发布时间待核对。</p> : null}
    <details className="knowledge-provenance"><summary>原件引用定位</summary><pre>{JSON.stringify(selection.reference, null, 2)}</pre></details>
    <button type="button" className="text-button" disabled={busy || auth.ownerSignal.aborted} onClick={() => void resolve()}>{busy ? "正在核对原件…" : "从原件核对摘录"}</button>
    {resolved?.key === key ? <pre>{resolved.text}</pre> : null}
    {error?.key === key ? <p role="alert">{error.text}</p> : null}
  </section>;
}
