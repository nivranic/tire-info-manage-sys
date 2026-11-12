"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { DocumentTextExcerpt, DocumentTextSearchItem, DocumentTextSearchRequest, OriginalTextSearchItem, OriginalTextSearchResult, SourceTextExcerpt, SourceTextSearchItem, SourceTextSearchRequest, SourceTextSearchResult, TextEmbeddingSelection } from "@tire/domain-types";
import TextEmbeddingPurposeDialog from "./text-embedding-purpose";

type TextSearchItem = SourceTextSearchItem | DocumentTextSearchItem | OriginalTextSearchItem;
type TextSearchResult = Omit<SourceTextSearchResult, "items" | "index"> & { items: TextSearchItem[] };
type TextSearchProps = { automatic: boolean; selected: TextEmbeddingSelection[]; onToggle: (selection: TextEmbeddingSelection) => void } & (
  { origin?: "source"; search: SourceTextSearchRequest } |
  { origin: "document"; search: DocumentTextSearchRequest }
);

const stamp = (value: string) => new Date(value).toLocaleString("zh-CN");
const methods = { fts: "关键词召回", dense: "向量召回", hybrid: "关键词与向量融合" };
const regions = { exact: "优先地区", different: "其他已登记地区", unknown: "地区待核对", not_requested: "未设置地区偏好" };

function OriginalTextCard({ item, selected, disabled, onToggle }: {
  item: TextSearchItem; selected: boolean; disabled: boolean; onToggle: () => void;
}) {
  const operation = useRef<AbortController | null>(null);
  const [resolved, setResolved] = useState<SourceTextExcerpt | DocumentTextExcerpt | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [purposeOpen, setPurposeOpen] = useState(false);
  const excerpt = resolved || item;
  const source = excerpt.kind === "document_text" ? excerpt.document.source_url : excerpt.source_url;
  const sourceUrl = /^https?:\/\//i.test(source) ? source : undefined;
  const semanticMatch = "rrf_score" in item.match ? item.match : null;
  const material = semanticMatch?.source_attribution ?? semanticMatch?.freshness.publication;

  useEffect(() => () => { operation.current?.abort(); }, []);

  async function resolve() {
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true); setError(""); setResolved(null);
    try {
      const value = item.kind === "document_text"
        ? await tireApi.resolveDocumentText(item.reference, controller.signal)
        : await tireApi.resolveSourceText(item.reference, controller.signal);
      if (controller.signal.aborted || operation.current !== controller) return;
      setResolved(value);
    } catch (cause) {
      if (controller.signal.aborted || operation.current !== controller) return;
      setError(cause instanceof Error ? cause.message : "引用恢复未完成，请重试。");
    } finally {
      if (operation.current === controller) { operation.current = null; setBusy(false); }
    }
  }

  return <article className={`knowledge-card ${excerpt.kind === "document_text" ? "document-text-card" : "source-text-card"}${selected ? " selected" : ""}`}>
    <div className="knowledge-card-heading"><label className="knowledge-select"><input type="checkbox" aria-label={`选择正文引用 ${excerpt.kind === "document_text" ? `${excerpt.document.title} 第 ${excerpt.reference.page} 页` : excerpt.reference.snapshot_id}`} checked={selected} disabled={disabled} onChange={onToggle} /><span>{excerpt.kind === "document_text" ? `${excerpt.document.title} · 第 ${excerpt.reference.page} 页` : `${excerpt.source_id} · 页面正文摘录`}</span></label></div>
    <p className="knowledge-excerpt">{excerpt.text}</p>
    <p className="knowledge-stamp">{methods[item.match.method]}</p>
    <p className="knowledge-stamp">{excerpt.kind === "document_text" ? `留存 ${stamp(excerpt.document.created_at)}` : `观察 ${stamp(excerpt.observed_at)} · 验证 ${stamp(excerpt.verified_at)}`}</p>
    <details className="knowledge-provenance"><summary>原始来源与引用位置</summary>
      <dl><dt>原始来源</dt><dd>{sourceUrl ? <a href={sourceUrl} target="_blank" rel="noopener noreferrer">{source}</a> : source || "未提供链接"}</dd>
        {excerpt.kind === "document_text" ? <><dt>文档 ID</dt><dd>{excerpt.reference.document_id}</dd>
          <dt>文档元信息指纹</dt><dd className="mono">{excerpt.reference.document_fingerprint}</dd>
          <dt>文档页码</dt><dd>第 {excerpt.reference.page} 页</dd>
          <dt>声明的保存依据</dt><dd>{excerpt.document.rights_basis}</dd></> : <><dt>快照 ID</dt><dd>{excerpt.reference.snapshot_id}</dd></>}
        <dt>原件 SHA256</dt><dd className="mono">{excerpt.reference.raw_hash}</dd>
        <dt>抽取版本</dt><dd>{excerpt.reference.extractor_version}</dd>
        <dt>Unicode码点区间</dt><dd>[{excerpt.reference.start}, {excerpt.reference.end})</dd>
        <dt>匹配词</dt><dd>{item.match.matched_terms.join(" · ")}</dd></dl>
    </details>
    {"rrf_score" in item.match ? <details className="knowledge-provenance"><summary>召回与排序依据</summary>
      <dl><dt>来源类别</dt><dd>{item.match.source_class}</dd>
        <dt>来源类别层级</dt><dd>{item.match.authority_tier ?? "待核对"}</dd>
        <dt>来源地区</dt><dd>{item.match.region || "待核对"} · {regions[item.match.region_match]}</dd>
        <dt>RRF分数</dt><dd>{item.match.rrf_score.toFixed(6)}</dd>
        <dt>余弦距离</dt><dd>{item.match.cosine_distance === null ? "本条由关键词召回" : item.match.cosine_distance.toFixed(6)}</dd>
        <dt>时间依据</dt><dd>{item.match.freshness.time_basis === "observed_at" && item.match.freshness.observed_at
          ? `原件观察 ${stamp(item.match.freshness.observed_at)}`
          : item.match.freshness.time_basis === "policy_publication_date" && item.match.freshness.publication
            ? `材料策略声明出版日期 ${item.match.freshness.publication.published_at}` : "文档发布时间待核对"}</dd>
        {item.match.source_attribution ? <><dt>材料策略声明分类依据</dt><dd>{item.match.source_attribution.basis}</dd></> : null}
        {material ? <>
          <dt>材料捕获请求</dt><dd className="mono">{material.material_request_id}</dd>
          <dt>材料策略指纹</dt><dd className="mono">{material.policy_fingerprint}</dd>
        </> : null}</dl>
      <ul>{item.match.explanation.map(line => <li key={line}>{line}</li>)}</ul>
    </details> : null}
    <div className="knowledge-form-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => void resolve()}>{busy ? "正在恢复引用…" : "核对原文引用"}</button>
      <button type="button" className="secondary-button" onClick={() => setPurposeOpen(true)}>核对正文用途</button>
      <span role="status" aria-live="polite">{resolved ? "已从保存原件恢复引用" : ""}</span></div>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {purposeOpen ? <TextEmbeddingPurposeDialog selection={item.kind === "document_text" ? { kind: "document_text", reference: item.reference } : { kind: "source_text", reference: item.reference }} onClose={() => setPurposeOpen(false)} /> : null}
  </article>;
}

export function OriginalTextResults({ result, selected, onToggle }: {
  result: OriginalTextSearchResult; selected: TextEmbeddingSelection[];
  onToggle: (selection: TextEmbeddingSelection) => void;
}) {
  return <section className="knowledge-results" aria-label="正文混合检索结果"><h3>正文混合检索</h3>
    <p className="review-boundary">{result.notice}</p>
    <p>召回 {result.total} 段候选，展示 {result.items.length} 段。当前范围 {result.coverage.indexed_chunks} / {result.coverage.eligible_chunks} 段有可用向量。</p>
    {result.items.map(item => <OriginalTextCard key={item.reference.chunk_id} item={item}
      selected={selected.some(selection => selection.kind === item.kind && selection.reference.chunk_id === item.reference.chunk_id)}
      disabled={selected.length >= 32 && !selected.some(selection => selection.kind === item.kind && selection.reference.chunk_id === item.reference.chunk_id)}
      onToggle={() => onToggle(item.kind === "document_text" ? { kind: "document_text", reference: item.reference } : { kind: "source_text", reference: item.reference })} />)}
    {result.has_more ? <p>候选中还有正文，可缩小关键词、来源或地区范围继续核对。</p> : null}
  </section>;
}

export default function SourceTextSearch(props: TextSearchProps) {
  const { search, automatic } = props;
  const origin = props.origin || "source";
  const contentLabel = origin === "document" ? "PDF正文" : "页面正文";
  const source_id = props.origin === "document" ? undefined : props.search.source_id;
  const document_id = props.origin === "document" ? props.search.document_id : undefined;
  const operation = useRef<AbortController | null>(null);
  const [result, setResult] = useState<TextSearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const { text, limit } = search;

  const load = useCallback(async (offset = 0) => {
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true); setError(""); setStatus("");
    if (offset === 0) setResult(null);
    try {
      const value = origin === "document"
        ? await tireApi.searchDocumentText({ mode: "history", text, document_id, limit, offset }, controller.signal)
        : await tireApi.searchSourceText({ mode: "history", text, source_id, limit, offset }, controller.signal);
      if (controller.signal.aborted || operation.current !== controller) return;
      setResult(previous => previous && offset > 0
        ? { ...value, items: [...new Map([...previous.items, ...value.items].map(item => [item.reference.chunk_id, item])).values()] }
        : value);
      setStatus(`找到 ${value.total} 条正文摘录，已读取 ${Math.min(offset + value.items.length, value.total)} 条。`);
    } catch (cause) {
      if (controller.signal.aborted || operation.current !== controller) return;
      setError(cause instanceof Error ? cause.message : `${contentLabel}检索未完成，请重试。`);
    } finally {
      if (operation.current === controller) { operation.current = null; setBusy(false); }
    }
  }, [text, source_id, document_id, limit, origin, contentLabel]);

  useEffect(() => {
    if (automatic) void load();
    return () => { operation.current?.abort(); };
  }, [automatic, load]);

  function cancel() {
    operation.current?.abort(); operation.current = null;
    setBusy(false); setStatus("已取消正文检索。");
  }

  return <section className="knowledge-results" aria-label={`${contentLabel}检索`} aria-busy={busy}>
    <h3>已保存{contentLabel}</h3>
    <p>勾选正文后，可在“向量与混合检索”中预览所选正文的索引计划，每批最多32段。</p>
    <p>{origin === "document" ? "按关键词检索已建立索引的PDF文字层，引用记录文档页码和页内位置。具体SKU身份与适用性需要对应的结构化证据。" : `按关键词${source_id ? `及来源 ${source_id}` : ""}检索轮胎页面正文。摘录保留页面范围，具体SKU身份与适用性需要对应的结构化证据。`}</p>
    <div className="knowledge-form-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => void load()}>{result || error ? `重新检索${contentLabel}` : `检索已保存${contentLabel}`}</button>{busy ? <button type="button" className="text-button" onClick={cancel}>取消正文检索</button> : null}</div>
    <p role="status" aria-live="polite">{busy ? "正在读取保存原件与正文索引…" : status}</p>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {result ? <><p className="review-boundary">{result.notice}</p>
      {result.items.map(item => <OriginalTextCard key={item.reference.chunk_id} item={item}
        selected={props.selected.some(selection => selection.kind === item.kind && selection.reference.chunk_id === item.reference.chunk_id)}
        disabled={props.selected.length >= 32 && !props.selected.some(selection => selection.kind === item.kind && selection.reference.chunk_id === item.reference.chunk_id)}
        onToggle={() => props.onToggle(item.kind === "document_text" ? { kind: "document_text", reference: item.reference } : { kind: "source_text", reference: item.reference })} />)}
      {result.total === 0 ? <p>{origin === "document" ? "没有匹配的PDF正文，可调整关键词或在原始文档中提取并索引正文。" : "没有匹配的已保存页面正文，可调整关键词或在线保存相关来源。"}</p> : null}
      {result.has_more && result.offset + result.limit <= 2000 ? <button type="button" className="secondary-button" disabled={busy} onClick={() => void load(result.offset + result.limit)}>继续加载正文摘录</button> : null}
      {result.has_more && result.offset + result.limit > 2000 ? <p>已达到本次分页范围，请缩小关键词或来源范围继续检索。</p> : null}
    </> : null}
  </section>;
}
