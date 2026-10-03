"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { AIPackReference, KnowledgeFilters, KnowledgeSearchItem, KnowledgeSearchResult } from "@tire/domain-types";
import { IdentityContractBadge } from "./identity-contract";
import { FieldResolutionView } from "./field-authority";
import VectorTools from "./vector-tools";
import { RecallKnowledgeMeta } from "./recall-evidence-meta";
import { canSelectKnowledgeReference, selectedKnowledgeReferences } from "./recall-evidence-values";

const kindLabels = { tire: "轮胎规格", vehicle: "车型适配", test_event: "测试事件", recall: "正式召回公告 / 空观察" };
const filterLabels: Record<keyof KnowledgeFilters, string> = {
  kind: "证据类型", brand: "品牌", model: "型号", size: "尺寸", region: "地区", product_code: "产品代码",
  source_id: "来源 ID", variant_id: "规格 ID", technology: "技术", field: "关注字段", campaign_number: "公告编号",
};
const fieldLabels: Record<string, string> = {
  eu_fuel_class: "欧标 · 滚阻等级", eu_wet_grip: "欧标 · 湿地抓地", eu_external_noise_db: "欧标 · 外部噪声值", eu_noise_class: "欧标 · 噪声等级",
  utqg_treadwear: "UTQG · 耐磨", utqg_traction: "UTQG · 牵引力", utqg_temperature: "UTQG · 温度", manufacturer_product_code: "产品代码", acoustic_technology: "降噪技术",
};
const textFilters = ["brand", "model", "size", "region", "product_code", "technology", "campaign_number"] as const;
const stamp = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "未记录";
const safeLink = (value: string) => { try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) ? url.href : undefined; } catch { return undefined; } };
const filterValue = (name: string, value: string) => name === "kind" ? kindLabels[value as keyof typeof kindLabels] || value : name === "field" ? fieldLabels[value] || value : value;

function Version({ reference }: { reference: AIPackReference }) {
  return reference.kind === "test_event" ? <><dt>事件版本</dt><dd>{reference.event_id} · 修订 #{reference.event_revision}</dd></> : <>
    <dt>快照 ID</dt><dd>{reference.snapshot_id}</dd>
    {reference.kind === "tire" ? <><dt>精确规格 ID</dt><dd>{reference.variant_id}</dd></> : null}
    {reference.kind === "recall" ? <><dt>公告修订 ID</dt><dd>{reference.recall_revision_id || "空观察，不绑定历史公告修订"}</dd></> : null}
  </>;
}

function ResultCard({ item, selected, disabled, onToggle }: { item: KnowledgeSearchItem; selected: boolean; disabled: boolean; onToggle: () => void }) {
  const url = safeLink(item.source_url);
  return <article className={`knowledge-card${selected ? " selected" : ""}`}>
    <div className="knowledge-card-heading">
      <label className="knowledge-select"><input type="checkbox" checked={selected} disabled={disabled} onChange={onToggle} /><span>{item.label}</span></label>
      <span className="tag quiet">{item.kind ? kindLabels[item.kind] : "证据记录"}</span>
    </div>
    <div className="knowledge-meta"><span>{item.privacy_class === "public" ? "公开来源证据" : "非公开工作区证据"}</span><span>{item.region || "地区未记录"}</span><span>{item.source_id || "人工录入来源"}</span></div>
    {item.kind === "tire" ? <IdentityContractBadge contract={item.identity_contract} context="search" /> : null}
    {item.kind !== "recall" ? <p className="knowledge-excerpt">{item.excerpt}</p> : null}
    <p className="knowledge-stamp">观察 {stamp(item.observed_at)} · 验证 {stamp(item.verified_at)}</p>
    <RecallKnowledgeMeta item={item} />
    {item.kind === "recall" ? <details className="knowledge-recall-excerpt"><summary>核对本条检索字段</summary><p className="knowledge-excerpt">{item.excerpt}</p></details> : null}
    {item.kind === "tire" ? <details className="knowledge-field-resolution"><summary>核对检索时的字段默认值与全部来源</summary><FieldResolutionView resolution={item.field_resolution} context="search" /></details> : null}
    {item.conflicts.length ? <div className="source-conflict"><strong>{item.conflicts.length} 项来源冲突</strong><details><summary>核对冲突记录</summary><pre>{JSON.stringify(item.conflicts, null, 2)}</pre></details></div> : null}
    <details className="knowledge-provenance"><summary>版本、来源与匹配依据</summary>
      <dl><Version reference={item.reference} /><dt>原始来源</dt><dd>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{item.source_url}</a> : "无可打开的来源链接"}</dd><dt>匹配方式</dt><dd>{{ fts: "关键词全文检索", structured: "结构化条件筛选", dense: "向量召回", hybrid: "关键词与向量融合" }[item.match.method]}</dd>
        {item.match.matched_terms.length ? <><dt>匹配词</dt><dd>{item.match.matched_terms.join(" · ")}</dd></> : null}
        <dt>字段来源优先级</dt><dd>{item.match.authority_tier === null ? "本项未使用字段来源优先级" : `等级 ${item.match.authority_tier}`} · {item.match.authority_rule}</dd>
      </dl>
      <ul>{item.match.explanation.map((line, index) => <li key={index}>{line}</li>)}</ul>
    </details>
  </article>;
}

export default function KnowledgeSearchDialog({ onClose, onAnalyze, onLiveQuery, onOffline }: {
  onClose: () => void; onAnalyze: (references: AIPackReference[]) => void; onLiveQuery: (recall?: { campaign_number?: string }) => void; onOffline?: (references: AIPackReference[]) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const textInput = useRef<HTMLInputElement>(null);
  const operation = useRef<AbortController | null>(null);
  const [text, setText] = useState("");
  const [filters, setFilters] = useState<KnowledgeFilters>({});
  const [limit, setLimit] = useState(12);
  const [result, setResult] = useState<KnowledgeSearchResult | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [moreBusy, setMoreBusy] = useState(false);
  const [error, setError] = useState("");
  const [needsLive, setNeedsLive] = useState(false);
  const [status, setStatus] = useState("");
  const lastSearch = useRef<{ text: string; filters: KnowledgeFilters; limit: number } | null>(null);
  const selectedItems = result?.items.filter(item => selected.includes(item.id)) || [];
  const selectedReferences = selectedKnowledgeReferences(result?.items || [], selected);
  const selectedProducts = selectedItems.filter(item => item.recall?.observation_kind === "records").length;
  const selectedRecallReferences = selectedReferences.filter(reference => reference.kind === "recall").length;
  const liveQuery = () => onLiveQuery(filters.kind === "recall" || filters.campaign_number ? { campaign_number: filters.campaign_number?.trim().toUpperCase() } : undefined);

  useEffect(() => {
    const node = dialog.current;
    const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    textInput.current?.focus({ preventScroll: true });
    return () => { operation.current?.abort(); node?.close(); if (focus?.isConnected) focus.focus({ preventScroll: true }); };
  }, []);

  function invalidate() {
    operation.current?.abort(); operation.current = null;
    setBusy(false); setResult(null); setSelected([]); setError(""); setNeedsLive(false); setStatus("");
    lastSearch.current = null;
  }

  function updateFilter(name: keyof KnowledgeFilters, value: string) {
    invalidate();
    setFilters(previous => { const next = { ...previous }; if (value) Object.assign(next, { [name]: value }); else delete next[name]; return next; });
  }

  async function search() {
    invalidate();
    const exactFilters = Object.fromEntries(Object.entries(filters).map(([key, value]) => [key, value.trim()]).filter(([, value]) => value)) as KnowledgeFilters;
    if (!text.trim() && !Object.keys(exactFilters).length) { setError("至少输入关键词或一项筛选条件。"); textInput.current?.focus({ preventScroll: true }); return; }
    const controller = new AbortController(); operation.current = controller; setBusy(true);
    lastSearch.current = { text: text.trim(), filters: exactFilters, limit };
    try {
      const value = await tireApi.searchKnowledge({ mode: "history", text: text.trim(), filters: exactFilters, limit }, controller.signal);
      if (controller.signal.aborted || operation.current !== controller) return;
      setResult(value); setStatus(`找到 ${value.total} 条历史证据，展示 ${value.items.length} 条。`);
    } catch (cause) {
      if (controller.signal.aborted || operation.current !== controller) return;
      setNeedsLive(cause instanceof ApiError && cause.status === 409);
      setError(cause instanceof Error ? cause.message : "历史证据检索未完成，请重试。");
    } finally {
      if (operation.current === controller) { operation.current = null; setBusy(false); }
    }
  }

  async function loadMore() {
    const previous = lastSearch.current;
    if (!previous || !result || busy || moreBusy || !result.has_more) return;
    const controller = new AbortController(); operation.current = controller; setMoreBusy(true);
    const offset = result.items.length;
    try {
      const value = await tireApi.searchKnowledge({ mode: "history", text: previous.text, filters: previous.filters, limit: previous.limit, offset }, controller.signal);
      if (controller.signal.aborted || operation.current !== controller) return;
      setResult(merged => merged && value.items.length ? { ...value, items: [...new Map([...merged.items, ...value.items].map(item => [item.id, item])).values()], notice: merged.notice } : value);
      setStatus(`已加载 ${Math.min(offset + value.items.length, value.total)} / ${value.total} 条历史证据。`);
    } catch (cause) {
      if (controller.signal.aborted || operation.current !== controller) return;
      setError(cause instanceof Error ? cause.message : "继续加载未完成，请重试。");
    } finally {
      if (operation.current === controller) { operation.current = null; setMoreBusy(false); }
    }
  }

  function cancel() { invalidate(); setStatus("已取消本次检索。"); }
  function close() { operation.current?.abort(); onClose(); }
  function analyze() {
    if (!result || busy) return;
    const references = selectedReferences;
    if (references.length && references.length <= 6) { operation.current?.abort(); onAnalyze(references); }
  }

  return <dialog ref={dialog} className="fact-review-dialog knowledge-dialog" aria-labelledby="knowledge-title" aria-describedby="knowledge-boundary" onCancel={event => { event.preventDefault(); event.stopPropagation(); close(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">EVIDENCE LIBRARY</span><h2 id="knowledge-title">历史证据知识检索</h2><p>从参数和来源，找到可以核对的记录。</p></div><button type="button" className="icon-button" aria-label="关闭历史证据检索" onClick={close}>×</button></header>
    <div className="knowledge-content">
      <div className="snapshot-banner" id="knowledge-boundary"><strong>LOCAL SNAPSHOT · 仅限历史记录</strong><span>{result?.external_processing?.query_text_sent ? "本条混合检索记录的查询文本经过单次授权发送到 OpenAI 生成向量；结果仍为历史证据，不代表当前在线参数。" : "普通检索只读取已采纳的本地证据，不联网、不调用模型；结果不代表当前在线参数。"}隔离记录与未解析文档不参与检索。</span></div>
      <form className="review-form knowledge-form" onSubmit={event => { event.preventDefault(); void search(); }}>
        <label htmlFor="knowledge-text">关键词<input ref={textInput} id="knowledge-text" maxLength={500} value={text} onChange={event => { invalidate(); setText(event.target.value); }} aria-describedby="knowledge-text-hint" /></label>
        <small id="knowledge-text-hint">支持已保存证据中的关键词；留空可按下方条件浏览历史记录。</small>
        <div className="knowledge-filter-grid">
          <label>证据类型<select value={filters.kind || ""} onChange={event => updateFilter("kind", event.target.value)}><option value="">全部类型</option>{Object.entries(kindLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>关注字段<select value={filters.field || ""} onChange={event => updateFilter("field", event.target.value)}><option value="">不限字段</option>{Object.entries(fieldLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          {textFilters.map(name => <label key={name}>{filterLabels[name]}<input maxLength={160} value={filters[name] || ""} onChange={event => updateFilter(name, event.target.value)} /></label>)}
        </div>
        <details className="knowledge-exact"><summary>按来源或精确规格 ID 筛选</summary><div className="knowledge-filter-grid">{(["source_id", "variant_id"] as const).map(name => <label key={name}>{filterLabels[name]}<input maxLength={160} value={filters[name] || ""} onChange={event => updateFilter(name, event.target.value)} /></label>)}</div></details>
        <small>结构化条件限定版本范围；尺寸按几何规格匹配，R / ZR 分别保留版本；关键词用于检索相关字段。未选择关注字段时，不启用字段来源优先级。</small>
        <div className="knowledge-form-actions"><label className="knowledge-limit">展示数量<select value={limit} onChange={event => { invalidate(); setLimit(Number(event.target.value)); }}><option value={12}>12 条</option><option value={24}>24 条</option><option value={30}>30 条</option></select></label><button className="primary-button" type="submit" disabled={busy}>{busy ? "正在检索…" : "检索历史证据"}</button>{busy ? <button className="text-button" type="button" onClick={cancel}>取消检索</button> : <button className="text-button" type="button" onClick={() => { invalidate(); setText(""); setFilters({}); }}>清空条件</button>}</div>
      </form>
      {error ? <section className="inline-error" role="alert"><p>{error}</p>{needsLive ? <><p>涉及当前状态的问题需要重新在线核验。返回查询页面后，请选择来源并发起在线查询。</p><button type="button" className="secondary-button" onClick={() => { operation.current?.abort(); liveQuery(); }}>返回在线查询</button></> : null}</section> : null}
      <p className="knowledge-status" role="status" aria-live="polite">{busy ? "正在读取本地历史证据…" : status || "输入关键词或设置条件后开始检索。"}</p>
      <VectorTools selectedIds={selected} search={{ mode: "history", text: text.trim(), filters, limit }} onResult={value => { invalidate(); setText(value.text); setFilters(value.applied_filters); lastSearch.current = { text: value.text, filters: value.applied_filters, limit }; setResult(value); setStatus(value.total_scope === "candidates" ? `已召回 ${value.total} 条候选，展示 ${value.items.length} 条；不是全部语义匹配数。` : `结构化条件已足够，找到 ${value.total} 条历史证据；本次未发送查询文本。`); }} />
      {result ? <section className="knowledge-results" aria-label="历史证据检索结果" aria-busy={busy}>
        <p className="review-boundary">{result.notice}</p>
        {result.coverage ? <p className="review-boundary">本次筛选范围：{result.coverage.indexed_documents} / {result.coverage.eligible_documents} 条记录有完整向量，{result.coverage.missing_documents} 条未覆盖。向量结果不保证召回全部相关证据。</p> : null}
        {Object.keys(result.applied_filters).length ? <div className="knowledge-applied" aria-label="已应用条件">{Object.entries(result.applied_filters).map(([name, value]) => <span className="tag quiet" key={name}>{filterLabels[name as keyof KnowledgeFilters] || name}：{filterValue(name, String(value))}{Object.prototype.hasOwnProperty.call(result.inferred_filters, name) ? " · 从关键词识别" : ""}</span>)}</div> : null}
        {result.items.length ? <><div className="knowledge-result-summary"><strong>{result.total} 条{result.total_scope === "candidates" ? "检索候选" : "历史证据"}</strong><span>同公告产品命中合并；AI最多6份，设备离线范围另行预览</span></div>{result.items.map(item => <ResultCard key={item.id} item={item} selected={selected.includes(item.id)} disabled={!selected.includes(item.id) && !canSelectKnowledgeReference(selectedReferences, item.reference, 200)} onToggle={() => setSelected(previous => previous.includes(item.id) ? previous.filter(id => id !== item.id) : canSelectKnowledgeReference(selectedKnowledgeReferences(result.items, previous), item.reference, 200) ? [...previous, item.id] : previous)} />)}{result.has_more ? result.total_scope === "candidates"
  ? <p>本次候选中还有记录未展示；候选上限可能影响召回，可缩小筛选范围。</p>
  : <div className="compare-toolbar"><p>还有匹配记录未展示，可继续加载。</p><button type="button" className="secondary-button" disabled={busy || moreBusy} onClick={() => void loadMore()}>{moreBusy ? "正在加载…" : `继续加载（已展示 ${result.items.length} / ${result.total}）`}</button></div> : null}</> : <div className="knowledge-empty"><strong>没有匹配的已采纳证据</strong><p>可减少筛选条件，或先到在线查询保存所需来源记录。</p><button type="button" className="secondary-button" onClick={liveQuery}>前往在线查询</button></div>}
        <details className="knowledge-technical"><summary>检索能力与索引状态</summary><p>{result.index.engine} · {result.index.documents} 份索引文档 · {result.index.version}</p><ul>{result.stages.map((stage, index) => <li key={`${stage.name}-${index}`}><strong>{stage.name} · {stage.state === "succeeded" ? "已执行" : stage.state === "not_needed" ? "本次无需" : "尚不可用"}</strong><p>{stage.reason}</p></li>)}</ul></details>
      </section> : null}
    </div>
    <footer className="knowledge-footer"><div><strong>已选 {selectedReferences.length} 份不同证据 · AI上限6份</strong>{selectedRecallReferences ? <small>召回产品命中 {selectedProducts} 条 · 公告 / 空观察证据 {selectedRecallReferences} 份</small> : null}<small>进入下一步核对全部记录后，才能授权发送给 AI。</small></div>{onOffline ? <button className="secondary-button" disabled={!selected.length || busy || !result} type="button" onClick={() => onOffline(selectedReferences)}>预览所选设备离线资料</button> : null}<button className="primary-button" disabled={!selected.length || selectedReferences.length > 6 || busy || !result} type="button" onClick={analyze}>用所选历史证据分析</button></footer>
  </dialog>;
}
