"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { DocumentTextState } from "@tire/domain-types";

const labels = { text_available: "已抽取全部页文字", partial_text: "部分页面有可抽取文字", no_extractable_text: "未发现可抽取文字，需核对空白或扫描情况", encrypted: "文档已加密，正文提取待处理" };

export default function DocumentTextPanel({ documentId }: { documentId: string }) {
  const operation = useRef<AbortController | null>(null);
  const [value, setValue] = useState<DocumentTextState | null>(null);
  const [busy, setBusy] = useState<"read" | "index" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => () => { operation.current?.abort(); }, []);

  async function load(action: "read" | "index", page = 1) {
    operation.current?.abort();
    const controller = new AbortController(); operation.current = controller;
    setBusy(action); setError(""); setNotice("");
    try {
      const result = action === "index"
        ? await tireApi.indexDocumentText(documentId, controller.signal)
        : await tireApi.documentText(documentId, page, controller.signal);
      if (controller.signal.aborted || operation.current !== controller) return;
      setValue(result);
      if (action === "index" && result.index?.page_count) {
        const first = await tireApi.documentText(documentId, 1, controller.signal);
        if (controller.signal.aborted || operation.current !== controller) return;
        setValue(first);
      }
    } catch (cause) {
      if (controller.signal.aborted || operation.current !== controller) return;
      setError(cause instanceof Error ? cause.message : "PDF正文操作未完成，请重试。");
    } finally {
      if (operation.current === controller) { operation.current = null; setBusy(null); }
    }
  }

  function stopWaiting() {
    operation.current?.abort(); operation.current = null;
    setNotice(busy === "index" ? "已停止等待索引请求，可重新读取正文状态核对结果。" : "已停止读取正文。");
    setBusy(null);
  }

  return <details className="quality-technical document-text-panel" onToggle={event => {
    if (event.currentTarget.open) void load("read"); else stopWaiting();
  }}>
    <summary>PDF正文与页码</summary>
    <p>在本机受限进程中提取文字层并建立正文索引。摘录使用文档页码和页内Unicode码点区间。</p>
    <div className="knowledge-form-actions"><button type="button" className="secondary-button" disabled={!!busy} onClick={() => void load("index")}>{busy === "index" ? "正在提取并索引…" : "提取并索引正文"}</button>
      <button type="button" className="text-button" disabled={!!busy} onClick={() => void load("read", value?.page?.page || 1)}>重新读取正文状态</button>
      {busy ? <button type="button" className="text-button" onClick={stopWaiting}>停止等待</button> : null}</div>
    <p role="status" aria-live="polite">{busy === "index" ? "正在核对原件并抽取PDF文字层…" : busy ? "正在读取保存的PDF正文…" : notice}</p>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {value ? <><p>{value.index ? labels[value.index.status] : "尚未建立正文索引。"}</p>
      {value.index ? <p className="document-description">{value.index.page_count === null ? "页数未读取" : `${value.index.page_count} 页`} · {value.index.characters.toLocaleString()} 个Unicode码点 · {value.index.extractor_version}</p> : null}
      {value.page ? <><div className="knowledge-form-actions"><button type="button" className="text-button" disabled={!!busy || value.page.page <= 1} onClick={() => void load("read", value.page!.page - 1)}>上一页</button><strong>第 {value.page.page} / {value.index?.page_count} 页</strong><button type="button" className="text-button" disabled={!!busy || value.page.page >= (value.index?.page_count || 0)} onClick={() => void load("read", value.page!.page + 1)}>下一页</button></div>
        <p className="document-text-page">{value.page.text || "本页没有可抽取文字，需核对空白或扫描情况。"}</p></> : null}
      <p className="review-boundary">{value.notice}</p></> : null}
  </details>;
}
