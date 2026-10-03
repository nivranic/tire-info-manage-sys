"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { EmbeddingPlan, EmbeddingRun, KnowledgeSearchRequest, KnowledgeSearchResult, VectorStatus } from "@tire/domain-types";

type Action = { kind: "index"; documentIds: string[] } | { kind: "hybrid"; search: KnowledgeSearchRequest } | { kind: "history"; id: string };
const states = { pending: "处理中", outcome_unknown: "结果未确认", completed: "已完成", failed: "未完成" };
const filterNames: Record<string, string> = { kind: "证据类型", brand: "品牌", model: "型号", size: "尺寸", region: "地区", product_code: "产品代码", source_id: "来源 ID", variant_id: "规格 ID", technology: "技术", field: "关注字段", campaign_number: "公告编号" };
const kindNames: Record<string, string> = { tire: "轮胎规格", vehicle: "车型适配", test_event: "测试事件", recall: "正式召回公告 / 空观察" };
const stamp = (value: string) => new Date(value).toLocaleString("zh-CN");
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "向量操作未完成。";
const isSearch = (run: EmbeddingRun): run is EmbeddingRun & { result: KnowledgeSearchResult } => !!run.result && "items" in run.result;

function VectorActionDialog({ action, onClose, onChanged, onResult }: {
  action: Action; onClose: () => void; onChanged: () => void; onResult: (result: KnowledgeSearchResult) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const operation = useRef<AbortController | null>(null);
  const key = useRef<string | null>(null);
  const [plan, setPlan] = useState<EmbeddingPlan | null>(null);
  const [run, setRun] = useState<EmbeddingRun | null>(null);
  const [consent, setConsent] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [busy, setBusy] = useState(action.kind !== "hybrid");
  const [error, setError] = useState("");

  useEffect(() => {
    const node = dialog.current;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const controller = new AbortController();
    operation.current = controller; node?.showModal();
    void (async () => {
      if (action.kind === "index") {
        const value = await tireApi.embeddingPlan(action.documentIds, controller.signal);
        if (!controller.signal.aborted) setPlan(value);
      } else if (action.kind === "history") {
        const value = await tireApi.embeddingRun(action.id, controller.signal);
        if (!controller.signal.aborted) setRun(value);
      }
    })().catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); }).finally(() => {
      if (operation.current === controller) { operation.current = null; if (!controller.signal.aborted) setBusy(false); }
    });
    return () => { controller.abort(); operation.current?.abort(); node?.close(); if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, [action]);

  async function submit() {
    if (operation.current || !consent || action.kind === "history" || action.kind === "index" && !plan) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError("");
    key.current ||= crypto.randomUUID(); setAttempted(true);
    try {
      const value = action.kind === "index" ? await tireApi.runEmbedding(plan!.id, key.current, controller.signal)
        : await tireApi.hybridSearch(action.search, key.current, controller.signal);
      if (!controller.signal.aborted) { setRun(value); onChanged(); }
    } catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (operation.current === controller) { operation.current = null; if (!controller.signal.aborted) setBusy(false); } }
  }

  async function refreshRun() {
    if (!run || operation.current) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError("");
    try { const value = await tireApi.embeddingRun(run.id, controller.signal); if (!controller.signal.aborted) { setRun(value); onChanged(); } }
    catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (operation.current === controller) { operation.current = null; if (!controller.signal.aborted) setBusy(false); } }
  }

  const title = action.kind === "index" ? "核对将建立向量的证据" : action.kind === "hybrid" ? "确认本次混合检索" : "向量调用记录";
  return <dialog ref={dialog} className="fact-review-dialog vector-dialog" aria-labelledby="vector-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">RETRIEVAL · OPENAI EMBEDDINGS</span><h2 id="vector-title">{title}</h2></div><button type="button" className="icon-button" aria-label="关闭向量操作" onClick={onClose}>×</button></header>
    <div className="ai-content vector-content">
      <p className="review-boundary">向量用于寻找相关证据，不生成答案，也不修改来源事实。外部处理是本次独立授权；关闭窗口不会撤销供应商已受理的请求。</p>
      {error ? <p className="inline-error" role="alert">{error}</p> : null}
      {plan ? <section aria-label="向量发送清单"><p><strong>{plan.model} · {plan.dimensions} 维</strong></p><p>待发送 {plan.pending_chunks} 个分块；保守预留 {plan.reserved_tokens.toLocaleString()} tokens，不是账单金额。计划有效至 {stamp(plan.expires_at)}。</p>
        {plan.documents.map(doc => <article className="vector-plan-document" key={doc.id}><h3>{doc.label}</h3><span className="tag quiet">{doc.privacy_class === "public" ? "公开来源" : "非公开工作区证据"}</span>{doc.chunks.map((chunk, index) => <details key={`${chunk.hash}-${index}`}><summary>分块 {index + 1} · {chunk.cached ? "缓存已存在，本次不发送" : "本次待发送"}</summary><pre>{chunk.text}</pre></details>)}</article>)}
        {!plan.pending_chunks ? <p>所有内容已有匹配模型和维度的缓存，本次无需向供应商发送证据。</p> : null}
      </section> : action.kind === "index" && busy ? <p role="status">正在本地准备清单，尚未调用模型…</p> : null}
      {action.kind === "hybrid" ? <section><h3>本次查询</h3><p className="vector-query-text">{action.search.text || "仅结构化条件"}</p><dl className="quality-detail-meta">{Object.entries(action.search.filters).map(([name, value]) => <div key={name}><dt>{filterNames[name] || name}</dt><dd>{name === "kind" ? kindNames[value] || value : value}</dd></div>)}</dl><p>只有结构化查询不足时才向 OpenAI 发送查询文本生成向量。关键词与向量在相同筛选范围内召回，结果仍为历史证据；未建向量的记录可能无法被语义召回。</p></section> : null}
      {!run && action.kind !== "history" && (action.kind === "hybrid" || plan) ? <div className="ai-form"><label className="review-checkbox"><input type="checkbox" checked={consent} disabled={busy || attempted} onChange={event => setConsent(event.target.checked)} />{action.kind === "index" ? "我允许将清单中待发送的证据文本交给 OpenAI 建立向量。" : "我允许将本次查询文本交给 OpenAI 生成检索向量。"}</label><button className="primary-button" disabled={busy || !consent} onClick={() => void submit()}>{busy ? "正在等待回执…" : attempted ? "用同一标识核对结果" : action.kind === "index" ? "确认并建立向量" : "确认并执行混合检索"}</button>{attempted ? <p role="status">请求标识已固定；再次核对沿用同一标识，不自动重复已受理的付费调用。配置或计划失效时，请关闭后重新核对清单。</p> : null}</div> : null}
      {run ? <section className="ai-result" aria-label="向量操作结果"><h3>{states[run.state]}</h3><p>{run.kind === "index" ? "证据向量索引" : "历史混合检索"} · {stamp(run.created_at)}</p><p>{run.usage ? `已确认 ${run.usage.total_tokens} tokens` : run.reserved_tokens ? `用量未确认，保留 ${run.reserved_tokens} tokens 预留` : "本次没有付费调用预留"}</p>
        {run.error_code ? <p role="alert">{run.error_code}。本次没有可采纳的完整结果；失败不会自动转用陈旧数据。</p> : null}
        {run.state === "completed" && isSearch(run) ? <><p>记录中的查询：{run.result.text || "仅结构化条件"}</p><p>{run.result.total_scope === "candidates" ? `召回 ${run.result.total} 条候选，展示 ${run.result.items.length} 条；候选总数不等于全部语义相关记录。` : `结构化条件已足够，找到 ${run.result.total} 条记录；未调用供应商。`}</p><button className="primary-button" onClick={() => { onResult(run.result); onClose(); }}>查看本次检索结果</button></> : run.state === "completed" && run.result && "written_chunks" in run.result ? <p>新增 {run.result.written_chunks} 个分块，复用 {run.result.cached_chunks} 个缓存分块。可以另行授权一次混合检索。</p> : null}
        {run.state === "pending" || run.state === "outcome_unknown" ? <><p>结果尚未确认，不代表供应商未处理或未计费；不会自动重试。</p><button className="secondary-button" disabled={busy} onClick={() => void refreshRun()}>刷新这条调用记录</button></> : null}
      </section> : null}
    </div>
  </dialog>;
}

export default function VectorTools({ selectedIds, search, onResult }: {
  selectedIds: string[]; search: KnowledgeSearchRequest; onResult: (result: KnowledgeSearchResult) => void;
}) {
  const [status, setStatus] = useState<VectorStatus | null>(null);
  const [history, setHistory] = useState<EmbeddingRun[]>([]);
  const [revision, setRevision] = useState(0);
  const [action, setAction] = useState<Action | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([tireApi.vectorStatus(controller.signal), tireApi.embeddingHistory(controller.signal)]).then(([value, records]) => {
      if (!controller.signal.aborted) { setStatus(value); setHistory(records.items); setError(""); }
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [revision]);
  const ready = status?.available === true;
  return <section className="vector-tools" aria-label="向量与混合检索"><details><summary>向量与混合检索</summary>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    <p>{!status ? "正在读取本地能力状态…" : ready ? `${status.model.model} · ${status.model.dimensions} 维 · 可以预览和授权` : "向量能力尚未就绪。需配置 PostgreSQL / pgvector 与专用 Embeddings 模型后才会允许外部处理。"}</p>
    {status ? <><p className="review-boundary">{status.notice}</p>{status.coverage ? <p>当前可检索证据 {status.coverage.eligible_documents} 条，已建立向量 {status.coverage.indexed_documents} 条，未覆盖 {status.coverage.missing_documents} 条。</p> : null}<p>UTC {status.budget.day_utc}：共享预算已记账 {status.budget.accounted_tokens.toLocaleString()} tokens / {status.budget.requests} 次调用。</p><details><summary>能力详情</summary><p>{status.backend} · {status.model.state} · {status.reason || "可用"}</p></details></> : null}
    <div className="compare-toolbar"><button className="secondary-button" disabled={!ready || !selectedIds.length} onClick={() => setAction({ kind: "index", documentIds: [...selectedIds] })}>预览所选证据的向量索引</button><button className="secondary-button" disabled={!ready || !search.text.trim() && !Object.keys(search.filters).length} onClick={() => setAction({ kind: "hybrid", search: structuredClone(search) })}>核对并授权混合检索</button><button className="text-button" onClick={() => setRevision(value => value + 1)}>刷新能力与记录</button></div>
    <p>普通“检索历史证据”仍只在本地执行。上述两个操作分别确认外部处理，不沿用 AI 分析授权。</p>
    <h3>本浏览器会话的最近向量调用</h3>{history.length ? history.map(item => <button className="ai-history-item" key={item.id} onClick={() => setAction({ kind: "history", id: item.id })}><span>{item.kind === "index" ? "建立证据向量" : "混合检索"} · {states[item.state]}</span><small>{stamp(item.created_at)}</small></button>) : <p>暂无调用记录。</p>}
  </details>{action ? <VectorActionDialog action={action} onClose={() => setAction(null)} onChanged={() => setRevision(value => value + 1)} onResult={onResult} /> : null}</section>;
}
