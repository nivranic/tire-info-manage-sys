"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { EvidenceDocument, EvidenceDocumentMetadata } from "@tire/domain-types";
import { useWorkbenchPlatform } from "./workbench-platform";

const empty = (): EvidenceDocumentMetadata => ({ title: "", source_url: "", operator: "", rights_basis: "" });
const errorText = (value: unknown) => value instanceof Error ? value.message : "文档操作未完成，请重试。";

export default function EvidenceDocuments({ sessionReady }: { sessionReady: boolean }) {
  const platform = useWorkbenchPlatform();
  const [records, setRecords] = useState<EvidenceDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [metadata, setMetadata] = useState<EvidenceDocumentMetadata>(empty);
  const input = useRef<HTMLInputElement>(null);
  const operation = useRef<AbortController | null>(null);
  const list = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);
  useEffect(() => {
    if (!sessionReady) return;
    const controller = new AbortController(); list.current = controller; setLoading(true); setError("");
    void tireApi.documents(controller.signal).then(result => {
      if (!controller.signal.aborted) { setRecords(result.items); setTotal(result.total); }
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [sessionReady, revision]);
  async function upload() {
    if (!file || busy) return;
    if (file.size > 8 * 1024 * 1024) { setError("PDF 不得超过 8 MiB。"); return; }
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError(""); setNotice("");
    try {
      await tireApi.uploadDocument(metadata, file, controller.signal);
      if (!controller.signal.aborted) { setMetadata(empty()); setFile(null); if (input.current) input.current.value = ""; setRevision(value => value + 1); setNotice("原始文档已留存，尚未解析或核验，不会自动成为轮胎参数。"); }
    } catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  async function download(row: EvidenceDocument) {
    if (busy) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError(""); setNotice("");
    try {
      const blob = await tireApi.documentContent(row.id, controller.signal);
      if (controller.signal.aborted) return;
      if (blob.type.split(";")[0].trim().toLowerCase() !== "application/pdf") throw new Error("下载内容类型校验失败，未提供文件。");
      const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
      const hash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
      if (hash !== row.raw_hash || blob.size !== row.byte_count) throw new Error("下载内容完整性校验失败，未提供文件。");
      if (controller.signal.aborted) return;
      const result = await platform.saveDownload({ blob, filename: `evidence-${row.raw_hash}.pdf`, signal: controller.signal });
      if (controller.signal.aborted) return;
      setNotice(result.saved ? platform.kind !== "web" ? "原始字节已校验，并已保存到所选位置；未解析或执行 PDF。" : "原始字节已校验，已发起附件下载；未在页面中解析或执行 PDF。" : "已取消保存文件。");
    } catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  async function more() {
    if (busy || loading || !list.current) return;
    const controller = list.current; setBusy(true);
    try { const result = await tireApi.documents(controller.signal, records.length); if (!controller.signal.aborted) { setRecords(previous => [...new Map([...previous, ...result.items].map(row => [row.id, row])).values()]); setTotal(result.total); } }
    catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  return <section className="quarantine-panel evidence-documents" aria-labelledby="evidence-documents-title">
    <div className="panel-title"><span id="evidence-documents-title">原始 PDF 文档</span><button className="text-button" type="button" disabled={busy || loading} onClick={() => setRevision(value => value + 1)}>刷新文档</button></div>
    <p className="quality-intro">仅保存你已获授权留存的原始文件。文档属于本地工作区，原始字节固定保留；上传不会解析 PDF，也不会自动建立轮胎或车型事实。</p>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}{notice ? <p className="review-saved" role="status">{notice}</p> : null}
    <details className="document-upload"><summary>留存一份 PDF 原文</summary><form className="review-form" onSubmit={event => { event.preventDefault(); void upload(); }}>
      <label><span>PDF 文件（最大 8 MiB）</span><input ref={input} type="file" accept="application/pdf,.pdf" required disabled={busy} onChange={event => { const selected = event.target.files?.[0] || null; setFile(selected); setError(""); if (selected) setMetadata(previous => ({ ...previous, title: previous.title || selected.name.slice(0, 160) })); }} /></label>
      <label><span>文档名称</span><input required maxLength={160} value={metadata.title} disabled={busy} onChange={event => setMetadata(previous => ({ ...previous, title: event.target.value }))} /></label>
      <label><span>来源 HTTPS 链接（可留空，不自动抓取）</span><input type="url" maxLength={2048} value={metadata.source_url} disabled={busy} onChange={event => setMetadata(previous => ({ ...previous, source_url: event.target.value }))} /></label>
      <label><span>留存署名</span><input required maxLength={80} value={metadata.operator} disabled={busy} onChange={event => setMetadata(previous => ({ ...previous, operator: event.target.value }))} /></label>
      <label><span>保存授权依据</span><textarea required maxLength={500} value={metadata.rights_basis} disabled={busy} placeholder="说明文件的保存授权或许可依据" onChange={event => setMetadata(previous => ({ ...previous, rights_basis: event.target.value }))} /></label>
      <button type="submit" className="primary-button" disabled={!sessionReady || busy || !file}>{busy ? "正在处理…" : "保存原始文档"}</button>
    </form></details>
    {loading ? <p role="status" className="quality-empty">正在读取文档记录…</p> : records.length ? <><p className="quarantine-list-count">已显示 {records.length} / {total} 份</p>{records.map(row => <article className="quarantine-item" key={row.id}><div className="quality-item-heading"><h3>{row.title}</h3><span className="tag quiet">原文收件 · 未核验</span></div><p className="document-description">{new Date(row.created_at).toLocaleString("zh-CN")} · {row.byte_count.toLocaleString()} 字节 · 署名 {row.operator}</p><p className="hash-value">SHA-256 {row.raw_hash}</p><details className="quality-technical"><summary>来源与留存说明</summary><p className="document-description">来源：{row.source_url || "未提供链接"}</p><p className="document-description">声明的保存依据：{row.rights_basis}</p></details><button type="button" className="text-button" disabled={busy} onClick={() => void download(row)}>校验并下载原文</button></article>)}{records.length < total ? <button type="button" className="secondary-button" disabled={busy} onClick={() => void more()}>加载更多文档</button> : null}</> : <p className="quality-empty">尚未留存 PDF 原文。</p>}
  </section>;
}
