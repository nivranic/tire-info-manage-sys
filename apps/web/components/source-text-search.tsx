"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { SourceTextExcerpt, SourceTextSearchItem, SourceTextSearchRequest, SourceTextSearchResult } from "@tire/domain-types";

const stamp = (value: string) => new Date(value).toLocaleString("zh-CN");

function SourceTextCard({ item }: { item: SourceTextSearchItem }) {
  const operation = useRef<AbortController | null>(null);
  const [resolved, setResolved] = useState<SourceTextExcerpt | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const excerpt = resolved || item;
  const sourceUrl = /^https?:\/\//i.test(excerpt.source_url) ? excerpt.source_url : undefined;

  useEffect(() => () => { operation.current?.abort(); }, []);

  async function resolve() {
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true); setError(""); setResolved(null);
    try {
      const value = await tireApi.resolveSourceText(item.reference, controller.signal);
      if (controller.signal.aborted || operation.current !== controller) return;
      setResolved(value);
    } catch (cause) {
      if (controller.signal.aborted || operation.current !== controller) return;
      setError(cause instanceof Error ? cause.message : "引用恢复未完成，请重试。");
    } finally {
      if (operation.current === controller) { operation.current = null; setBusy(false); }
    }
  }

  return <article className="knowledge-card source-text-card">
    <div className="knowledge-card-heading"><strong>{excerpt.source_id} · 页面正文摘录</strong></div>
    <p className="knowledge-excerpt">{excerpt.text}</p>
    <p className="knowledge-stamp">观察 {stamp(excerpt.observed_at)} · 验证 {stamp(excerpt.verified_at)}</p>
    <details className="knowledge-provenance"><summary>原始来源与引用位置</summary>
      <dl><dt>来源页面</dt><dd>{sourceUrl ? <a href={sourceUrl} target="_blank" rel="noopener noreferrer">{excerpt.source_url}</a> : excerpt.source_url}</dd>
        <dt>快照 ID</dt><dd>{excerpt.reference.snapshot_id}</dd>
        <dt>原件 SHA256</dt><dd className="mono">{excerpt.reference.raw_hash}</dd>
        <dt>抽取版本</dt><dd>{excerpt.reference.extractor_version}</dd>
        <dt>Unicode码点区间</dt><dd>[{excerpt.reference.start}, {excerpt.reference.end})</dd>
        <dt>匹配词</dt><dd>{item.match.matched_terms.join(" · ")}</dd></dl>
    </details>
    <div className="knowledge-form-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => void resolve()}>{busy ? "正在恢复引用…" : "核对原文引用"}</button>
      <span role="status" aria-live="polite">{resolved ? "已从保存原件恢复引用" : ""}</span></div>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
  </article>;
}

export default function SourceTextSearch({ search, automatic }: { search: SourceTextSearchRequest; automatic: boolean }) {
  const operation = useRef<AbortController | null>(null);
  const [result, setResult] = useState<SourceTextSearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const { text, source_id, limit } = search;

  const load = useCallback(async (offset = 0) => {
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true); setError(""); setStatus("");
    if (offset === 0) setResult(null);
    try {
      const value = await tireApi.searchSourceText({ mode: "history", text, source_id, limit, offset }, controller.signal);
      if (controller.signal.aborted || operation.current !== controller) return;
      setResult(previous => previous && offset > 0
        ? { ...value, items: [...new Map([...previous.items, ...value.items].map(item => [item.reference.chunk_id, item])).values()] }
        : value);
      setStatus(`找到 ${value.total} 条正文摘录，已读取 ${Math.min(offset + value.items.length, value.total)} 条。`);
    } catch (cause) {
      if (controller.signal.aborted || operation.current !== controller) return;
      setError(cause instanceof Error ? cause.message : "页面正文检索未完成，请重试。");
    } finally {
      if (operation.current === controller) { operation.current = null; setBusy(false); }
    }
  }, [text, source_id, limit]);

  useEffect(() => {
    if (automatic) void load();
    return () => { operation.current?.abort(); };
  }, [automatic, load]);

  function cancel() {
    operation.current?.abort(); operation.current = null;
    setBusy(false); setStatus("已取消正文检索。");
  }

  return <section className="knowledge-results" aria-label="页面正文检索" aria-busy={busy}>
    <h3>已保存页面正文</h3>
    <p>按关键词{source_id ? `及来源 ${source_id}` : ""}检索轮胎页面正文。摘录保留页面范围，具体SKU身份与适用性需要对应的结构化证据。</p>
    <div className="knowledge-form-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => void load()}>{result || error ? "重新检索页面正文" : "检索已保存页面正文"}</button>{busy ? <button type="button" className="text-button" onClick={cancel}>取消正文检索</button> : null}</div>
    <p role="status" aria-live="polite">{busy ? "正在读取保存原件与正文索引…" : status}</p>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {result ? <><p className="review-boundary">{result.notice}</p>
      {result.items.map(item => <SourceTextCard key={item.reference.chunk_id} item={item} />)}
      {result.total === 0 ? <p>没有匹配的已保存页面正文，可调整关键词或在线保存相关来源。</p> : null}
      {result.has_more && result.offset + result.limit <= 2000 ? <button type="button" className="secondary-button" disabled={busy} onClick={() => void load(result.offset + result.limit)}>继续加载正文摘录</button> : null}
      {result.has_more && result.offset + result.limit > 2000 ? <p>已达到本次分页范围，请缩小关键词或来源范围继续检索。</p> : null}
    </> : null}
  </section>;
}
