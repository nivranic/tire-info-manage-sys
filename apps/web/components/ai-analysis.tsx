"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { AIAnalysis, AIAnalysisReference, AIPack, AIPrepareRequest, AIStatus, AIStreamDetail, EvidenceReportRecord, QueryResult, RecallAnalysisReference, RecallResult, Variant } from "@tire/domain-types";
import { IdentityContractBadge, IdentityContractEvidence } from "./identity-contract";
import { FrozenFieldResolutions } from "./field-authority";
import { SaveReportDialog } from "./reports";
import { AIStreamProgress } from "./ai-stream-progress";
import { RecallAnalysisBoundary, RecallEvidenceMeta, RecallFactScope, recallAnalysisNotice } from "./recall-evidence-meta";
import { recallCurrentRequest, uniqueAIReferences } from "./recall-evidence-values";
import { AI_RECOVERY_KEY, aiStreamErrorMessage, aiStreamErrorMessages, canExportAIAnalysis, parseAIRecovery, type AIRecoveryPointer } from "./ai-stream-values";

export type AITarget = ({ variant: Variant; sourceId?: string } | { references: AIAnalysisReference[]; label: string }
  | { recall: { campaign_number: string; reference: RecallAnalysisReference }; label: string }) & { defaultQuestion?: string };
const stamp = (value?: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "未记录";
const states = { pending: "调用处理中", outcome_unknown: "调用结果尚未确认", completed: "已完成引用校验", failed: "本次分析未完成" };
const errors: Record<string, string> = {
  ...aiStreamErrorMessages,
  ai_recall_contract_stale: "召回证据合同缺失或已变化。请重新准备公告证据，核对全部记录与适用性边界后重新授权；旧包仍可查看。",
  ai_evidence_field_contract_stale: "这份证据包的字段权威规则缺失或已经变化。请重新准备所选证据，核对默认值及全部来源，再重新授权分析；旧包仍可查看。",
  ai_evidence_identity_contract_stale: "这份证据包缺少有效的身份合同，或绑定已经变化。旧包仍可查看；请重新准备所选证据，再核对并授权分析。",
  identity_contract_review_required: "所选 SKU 的编码类型尚未完成身份核对。请先核对旧身份，不能自动改用相关候选。",
  ai_disabled: "AI 尚未启用。请在本机 API 环境中配置 OpenAI 后启用。",
  ai_configuration_required: "尚未配置专用 OpenAI 密钥或模型。",
  ai_configuration_invalid: "本机 AI 配置无效，请检查模型与预算设置。",
  ai_grounding_validation_failed: "输出未通过引用校验，已丢弃；没有生成可展示的分析。",
  ai_provider_timeout: "OpenAI 响应超时，可能已经计费。",
  ai_provider_network_error: "未能确认 OpenAI 响应，可能已经计费。",
  ai_provider_http_error: "OpenAI 返回错误，请核对本机配置与账户状态。",
  ai_response_incomplete: "模型输出不完整，未采纳为分析。",
  ai_refused: "模型拒绝了本次请求。",
};
const errorLabel = (code: string) => errors[code] || aiStreamErrorMessage(code);
const errorText = (cause: unknown) => cause instanceof ApiError && cause.code ? errors[cause.code] || (cause.code.startsWith("ai_stream_") ? aiStreamErrorMessage(cause.code) : `${cause.message}（${cause.code}）`) : cause instanceof Error ? errors[cause.message] || cause.message : "请求未完成。";
const sourceLink = (value: string) => { try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) ? url.href : undefined; } catch { return undefined; } };

export default function AIAnalysisDialog({ target, onClose, onOpenReport }: { target?: AITarget; onClose: () => void; onOpenReport?: (id: string) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const operation = useRef<AbortController | null>(null);
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [history, setHistory] = useState<AIAnalysis[]>([]);
  const [mode, setMode] = useState<"current" | "history">(target && "variant" in target ? "current" : "history");
  const [pack, setPack] = useState<AIPack | null>(null);
  const [fallback, setFallback] = useState<QueryResult | RecallResult | null>(null);
  const [preparedRequest, setPreparedRequest] = useState<AIPrepareRequest | null>(null);
  const [question, setQuestion] = useState(target?.defaultQuestion || "解释所选证据中的参数、缺失项与适用限制。");
  const [externalConsent, setExternalConsent] = useState(false);
  const [evidenceStale, setEvidenceStale] = useState(false);
  const [attempt, setAttempt] = useState<{ key: string; pack_id: string; question: string; allow_external_processing: boolean } | null>(null);
  const [run, setRun] = useState<AIAnalysis | null>(null);
  const [stream, setStream] = useState<AIStreamDetail | null>(null);
  const [streamEpoch, setStreamEpoch] = useState(0);
  const [recovery, setRecovery] = useState<AIRecoveryPointer | null>(null);
  const [retrySameRequest, setRetrySameRequest] = useState(false);
  const activeStream = useRef<string | null>(null);
  const viewGeneration = useRef(0);
  const intent = useRef<typeof attempt>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reportSave, setReportSave] = useState<{ pack: AIPack; analysis?: AIAnalysis } | null>(null);
  const [savedReport, setSavedReport] = useState<EvidenceReportRecord | null>(null);

  useEffect(() => {
    const node = dialog.current;
    const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    const controller = new AbortController();
    const initialGeneration = viewGeneration.current;
    void Promise.all([tireApi.aiStatus(controller.signal), tireApi.aiHistory(controller.signal)]).then(([s, h]) => {
      if (!controller.signal.aborted) { setStatus(s); setHistory(h.items); }
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    let pointer: AIRecoveryPointer | null = null;
    try { pointer = parseAIRecovery(sessionStorage.getItem(AI_RECOVERY_KEY)); } catch { /* Recovery can still use session history. */ }
    if (pointer) {
      setRecovery(pointer);
      void tireApi.lookupAIStream(pointer.key, controller.signal).then(value => {
        if (!controller.signal.aborted && viewGeneration.current === initialGeneration) showStream(value, pointer!.key);
      }).catch(cause => { if (!controller.signal.aborted && viewGeneration.current === initialGeneration) setError(cause instanceof ApiError && cause.status === 404 ? "当前会话未找到上次提交记录。可继续只读核对；恢复进度不会重新提交模型。" : errorText(cause)); });
    }
    return () => { controller.abort(); operation.current?.abort(); node?.close(); if (focus?.isConnected) focus.focus({ preventScroll: true }); };
  }, []);

  function remember(pointer: AIRecoveryPointer | null) {
    setRecovery(pointer);
    try { if (pointer) sessionStorage.setItem(AI_RECOVERY_KEY, JSON.stringify(pointer)); else sessionStorage.removeItem(AI_RECOVERY_KEY); } catch { /* Closing this tab still leaves the server-side history. */ }
  }

  function showStream(value: AIStreamDetail, key?: string) {
    activeStream.current = value.analysis.id;
    setStream(value); setStreamEpoch(previous => previous + 1); setRun(value.analysis);
    setPack(value.analysis.pack || null); setQuestion(value.analysis.question);
    setFallback(null); setExternalConsent(false); setEvidenceStale(false); setRetrySameRequest(false);
    setHistory(previous => [value.analysis, ...previous.filter(row => row.id !== value.analysis.id)].slice(0, 20));
    if (key) remember({ key, requestId: value.analysis.id, cursor: value.cursor });
  }

  function updateStream(value: AIStreamDetail) {
    if (activeStream.current !== value.analysis.id) return;
    setRun(value.analysis);
    setHistory(previous => [value.analysis, ...previous.filter(row => row.id !== value.analysis.id)].slice(0, 20));
  }

  function revealFact(id: string) {
    const node = dialog.current?.querySelector<HTMLElement>(`#ai-fact-${CSS.escape(id)}`);
    let parent = node?.parentElement;
    while (parent) { if (parent instanceof HTMLDetailsElement) parent.open = true; parent = parent.parentElement; }
    node?.scrollIntoView({ block: "center" }); node?.focus({ preventScroll: true });
  }

  async function perform(work: (signal: AbortSignal) => Promise<void>) {
    if (operation.current) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError("");
    try { await work(controller.signal); }
    catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }

  async function prepare(consentId?: string) {
    if (!target || attempt || recovery) return;
    viewGeneration.current++;
    await perform(async signal => {
      setPack(null); setRun(null);
      let payload: AIPrepareRequest;
      if (consentId && preparedRequest?.mode === "current") payload = { ...preparedRequest, consent_id: consentId };
      else if ("references" in target) payload = { mode: "history", references: uniqueAIReferences(target.references) };
      else if ("recall" in target) payload = mode === "history" ? { mode, references: [target.recall.reference] } : recallCurrentRequest(target.recall.campaign_number);
      else if (mode === "history") payload = { mode, references: [{ kind: "tire", snapshot_id: target.variant.snapshot_id, variant_id: target.variant.id }] };
      else {
        const source = target.sourceId || target.variant.source_id || (await tireApi.evidence(target.variant.snapshot_id, signal)).source_id;
        payload = { mode, source_id: source, query: { model: target.variant.model, size: target.variant.size }, variant_ids: [target.variant.id] };
      }
      if (signal.aborted) return;
      setPreparedRequest(payload); setFallback(null); setExternalConsent(false);
      const value = await tireApi.prepareAI(payload, signal);
      if (signal.aborted) return;
      setPack(value.pack); setFallback(value.pack ? null : value.query_result); setEvidenceStale(false);
      if (!value.pack && value.query_result?.data_state !== "consent_required") setError(`未取得可分析的精确证据：${value.reason || "来源不可用"}`);
    });
  }

  async function consent(decision: "allow" | "deny") {
    if (!fallback?.query_id || busy) return;
    const queryId = fallback.query_id;
    let id: string | undefined;
    await perform(async signal => {
      const value = await tireApi.consent(queryId, decision, signal);
      if (!signal.aborted) { id = value.id; setFallback(null); if (decision === "deny") setError("已拒绝本次历史数据使用；未调用 AI。"); }
    });
    if (decision === "allow" && id) await prepare(id);
  }

  async function submit() {
    if (!pack || busy || operation.current || evidenceStale) return;
    if (!intent.current && (!externalConsent || question.trim().length < 2 || !canSend)) return;
    viewGeneration.current++;
    const previous = intent.current;
    const value = previous || { key: crypto.randomUUID(), pack_id: pack.id, question: question.trim(), allow_external_processing: externalConsent };
    intent.current = value; setAttempt(value); remember({ key: value.key });
    await perform(async signal => {
      try {
        const result = previous && !retrySameRequest
          ? await tireApi.lookupAIStream(value.key, signal)
          : await tireApi.startAIStream({ pack_id: value.pack_id, question: value.question, allow_external_processing: value.allow_external_processing }, value.key, signal);
        if (!signal.aborted) showStream(result, value.key);
      } catch (cause) {
        if (!signal.aborted) {
          setRetrySameRequest(previous && !retrySameRequest && cause instanceof ApiError && cause.status === 404 ? true : false);
          if (cause instanceof ApiError && ["ai_evidence_identity_contract_stale", "ai_evidence_field_contract_stale", "ai_recall_contract_stale"].includes(cause.code || "")) {
            intent.current = null; setAttempt(null); remember(null); setEvidenceStale(true); setExternalConsent(false);
          }
        }
        throw cause;
      }
      const next = await tireApi.aiStatus(signal);
      if (!signal.aborted) setStatus(next);
    });
  }

  async function openRun(id: string, isStream = false) {
    if (operation.current) return;
    viewGeneration.current++;
    activeStream.current = null;
    await perform(async signal => {
      if (isStream) {
        const value = await tireApi.aiStream(id, signal);
        if (!signal.aborted) { intent.current = null; setAttempt(null); showStream(value, recovery?.requestId === id ? recovery.key : undefined); }
        return;
      }
      const value = await tireApi.aiAnalysis(id, signal);
      if (!signal.aborted) { setStream(null); intent.current = null; setRun(value); setPack(value.pack || null); setQuestion(value.question); setAttempt(null); setFallback(null); setExternalConsent(false); setEvidenceStale(false); }
    });
  }

  function reset() { viewGeneration.current++; activeStream.current = null; intent.current = null; remember(null); setAttempt(null); setStream(null); setRun(null); setPack(null); setFallback(null); setExternalConsent(false); setEvidenceStale(false); setRetrySameRequest(false); setError(""); }
  const frozen = !!attempt || !!run;
  const recallTarget = !!target && ("recall" in target || ("references" in target && target.references.some(reference => reference.kind === "recall")));
  const recallPack = !!pack?.evidence.some(evidence => evidence.evidence_type === "recall");
  const canSend = !evidenceStale && status?.model.state === "configured" && pack && status.model.allowed_privacy_classes?.includes(pack.privacy_class);

  return <><dialog ref={dialog} className="fact-review-dialog ai-dialog" aria-labelledby="ai-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">EVIDENCE → ANALYSIS</span><h2 id="ai-title">基于证据的 AI 分析</h2></div><button type="button" className="icon-button" aria-label="关闭 AI 分析" onClick={onClose}>×</button></header>
    <div className="ai-content">
      <p className="review-boundary">{recallTarget || recallPack ? recallAnalysisNotice : "分析限定于本次所选证据。事实逐项引用，推断单独标注；不会修改来源参数。"}关闭窗口仅停止等待和读取进度，不能保证已取消 OpenAI 的处理或免于计费。</p>
      <section className="ai-status" aria-label="模型状态"><strong>OpenAI Responses API</strong><p>{status ? status.model.state === "configured" ? `${status.model.model} · 已配置，连接待实际调用验证` : errors[status.model.state] || status.model.state : "正在读取配置…"}</p>{status ? <small>UTC {status.budget.day_utc}：{status.budget.requests} 次请求 / 已记账 {status.budget.accounted_tokens.toLocaleString()} tokens。含未知用量的预留，不是账单金额。</small> : null}</section>
      {error ? <p className="inline-error" role="alert">{error}</p> : null}
      {recovery && !stream && !attempt ? <section className="ai-recovery" aria-label="上次分析提交核对"><h3>核对本标签页上次提交</h3><p>刷新或重新打开不会重新调用模型。先读取原请求记录；如果无法确认，原调用仍可能处理或计费。</p><div className="compare-toolbar"><button type="button" className="secondary-button" disabled={busy} onClick={() => void perform(async signal => { const value = await tireApi.lookupAIStream(recovery.key, signal); if (!signal.aborted) showStream(value, recovery.key); })}>只读核对上次提交</button><button type="button" className="text-button" disabled={busy} onClick={reset}>返回证据准备</button></div></section> : null}
      {savedReport ? <section className="snapshot-banner" role="status"><strong>已保存报告：{savedReport.title}</strong><span>本浏览器会话 · 历史冻结正文 · 未新增模型调用</span>{onOpenReport ? <button type="button" className="text-button" onClick={() => onOpenReport(savedReport.id)}>在报告库打开</button> : null}</section> : null}
      {target && !run ? <section aria-label="分析范围">
        <h3>{"variant" in target ? `${target.variant.model} · ${target.variant.size} · ${target.variant.manufacturer_product_code || "代码未确认"}` : target.label}</h3>{"variant" in target ? <IdentityContractBadge contract={target.variant.identity_contract} /> : null}
        {"variant" in target || "recall" in target ? <fieldset className="ai-mode" disabled={busy || frozen}><legend>证据时间范围</legend><label><input type="radio" name="ai-mode" checked={mode === "current"} onChange={() => { setMode("current"); reset(); }} />先在线核验</label><label><input type="radio" name="ai-mode" checked={mode === "history"} onChange={() => { setMode("history"); reset(); }} />仅分析所选历史快照</label></fieldset> : <p>仅分析所选历史版本，保留各自的来源时间。</p>}
        {recallTarget ? <RecallAnalysisBoundary pending /> : null}
        {!frozen ? <button type="button" className="secondary-button" disabled={busy || !!recovery} onClick={() => void prepare()}>{busy ? "正在处理…" : mode === "current" ? "在线核验并准备证据" : "准备所选历史证据"}</button> : null}
      </section> : !target && !run ? <p>从轮胎卡片、规格比较、正式召回公告或测试事件选择证据开始；也可以查看下方本会话调用记录。</p> : null}
      {fallback?.data_state === "consent_required" ? <section className="consent-box" aria-label="AI 历史证据授权"><h3>在线核验失败</h3><p>是否仅为本次分析读取该查询的历史快照？同意后仍标记为 LOCAL SNAPSHOT。</p><div className="compare-toolbar"><button className="secondary-button" disabled={busy} onClick={() => void consent("allow")}>仅本次使用历史快照</button><button className="text-button" disabled={busy} onClick={() => void consent("deny")}>拒绝使用历史数据</button></div></section> : null}
      {pack ? <>
        <RecallAnalysisBoundary boundary={pack.recall_boundary} pending={recallPack} />
        <section className="snapshot-banner"><strong>{pack.source_state === "snapshot" ? "LOCAL SNAPSHOT · 历史证据" : "已在线核验的所选证据"}</strong><span>准备时间 {stamp(pack.created_at)} · 提交有效期至 {stamp(pack.expires_at)} · {pack.privacy_class === "public" ? "公开来源证据" : "非公开工作区证据"}</span></section>
        <details className="ai-evidence" open><summary>查看 {pack.evidence.length} 条来源与 {pack.facts.length} 个字段</summary>{pack.evidence.map(e => <section key={e.id} id={`ai-source-${e.id}`}><h4>{e.id} · {e.label}</h4>{e.kind === "tire" || e.identity_contract ? <IdentityContractEvidence contract={e.identity_contract} historical /> : null}<p>观察 {stamp(e.observed_at)} · 验证 {stamp(e.verified_at)}{e.revision ? ` · 修订 #${e.revision}` : ""}</p><p>{sourceLink(e.source_url) ? <a href={sourceLink(e.source_url)} target="_blank" rel="noopener noreferrer">打开原始来源</a> : "来源链接不可打开"} · {e.parser_version || "人工录入 / 车型证据"}</p>
          <RecallEvidenceMeta evidence={e} />
          {e.kind === "change_event" ? <div className="ai-change-provenance"><p className="review-boundary">这是 {stamp(e.change_observed_at)} 记录的历史变化。首次观察不代表新发布，后快照也不代表当前在线参数。</p><dl>
            <div><dt>变化前快照</dt><dd>{e.previous_snapshot_id ? <><code>{e.previous_snapshot_id}</code><br />观察 {stamp(e.previous_observed_at)}{e.previous_source_url && sourceLink(e.previous_source_url) ? <> · <a href={sourceLink(e.previous_source_url)} target="_blank" rel="noopener noreferrer">打开变化前来源</a></> : null}<br /><span>SHA-256 {e.previous_raw_hash || "未记录"}</span></> : "此前没有已采纳快照，不能据此推断厂商刚发布。"}</dd></div>
            <div><dt>变化后快照</dt><dd><code>{e.snapshot_id}</code><br />观察 {stamp(e.observed_at)}<br /><span>SHA-256 {e.raw_hash || "未记录"}</span></dd></div>
          </dl></div> : null}
          <details><summary>证据字段</summary><dl>{pack.facts.filter(f => f.evidence_id === e.id).map(f => <div key={f.id} id={`ai-fact-${f.id}`} tabIndex={-1}><dt>{f.id} · {f.field}<RecallFactScope fact={f} evidence={e} /></dt><dd>{f.text}</dd></div>)}</dl></details></section>)}</details>
        <FrozenFieldResolutions resolutions={pack.field_resolutions} policy={pack.field_policy} context="prepared" />
        {pack.conflicts.length ? <section className="source-conflict"><strong>所选证据存在 {pack.conflicts.length} 项未解决冲突</strong><details><summary>原始冲突记录</summary><pre>{JSON.stringify(pack.conflicts, null, 2)}</pre></details></section> : null}
        <div className="variant-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => setReportSave({ pack })}>保存证据报告</button>{canExportAIAnalysis(run) && run.pack_id === pack.id ? <button type="button" className="secondary-button" disabled={busy} onClick={() => setReportSave({ pack, analysis: run })}>保存含分析的报告</button> : null}</div>
        {!run ? <form className="ai-form" onSubmit={event => { event.preventDefault(); void submit(); }}>
          <label htmlFor="ai-question">本次问题</label><textarea id="ai-question" minLength={2} maxLength={2000} required rows={3} value={question} disabled={busy || !!attempt} onChange={event => setQuestion(event.target.value)} />
          <label className="review-checkbox"><input type="checkbox" checked={externalConsent} disabled={busy || !!attempt || evidenceStale} onChange={event => setExternalConsent(event.target.checked)} />我允许将本次问题及上述全部证据发送到 OpenAI 处理。</label>
          {!canSend ? <p className="review-boundary">{evidenceStale ? "证据合同或字段依据已失效。请重新准备所选证据并核对授权，旧包仍可查看。" : "模型配置或数据隐私策略尚不允许提交这份证据。"}</p> : null}
          <button type="submit" className="primary-button" disabled={busy || (!attempt && (!canSend || !externalConsent || question.trim().length < 2))}>{busy ? "正在核对受理结果…" : attempt ? retrySameRequest ? "用原标识重新提交" : "核对同一次提交" : "发送到 OpenAI 并分析"}</button>
          {attempt ? <><p role="status">{retrySameRequest ? "只读核对暂未找到记录。若继续，使用原请求内容和同一个标识重新提交；已受理的调用不会重复执行。" : "提交结果尚未确认，已锁定请求内容与标识。核对只读取原记录，不新建模型调用。"}</p><button type="button" className="text-button" disabled={busy} onClick={reset}>返回证据准备</button><p className="review-boundary">返回不会取消原调用。新的分析需要重新授权，并可能另外计费。</p></> : null}
        </form> : null}
      </> : null}
      {stream ? <AIStreamProgress key={`${stream.analysis.id}:${streamEpoch}`} initial={stream} recovery={recovery} onDetail={updateStream} onFact={revealFact} errorLabel={errorLabel} /> : null}
      {run && (!stream || run.state === "completed") ? <section className="ai-result" aria-label="AI 分析结果"><h3>{states[run.state]}</h3><p>{run.question}</p><small>{run.model} · {stamp(run.created_at)} · {run.usage ? `${run.usage.total_tokens} tokens` : `用量未确认，保留 ${run.reserved_tokens} tokens 预留`}</small>
        {run.error_code ? <p role="alert">{errors[run.error_code] || run.error_code}</p> : null}
        {canExportAIAnalysis(run) ? <><RecallAnalysisBoundary boundary={run.answer.recall_boundary || pack?.recall_boundary} pending={recallPack} />{run.answer.claims.filter(claim => !recallPack || claim.type === "fact").map((claim, index) => <article className={`ai-claim ${claim.type}`} key={index}><strong>{claim.type === "fact" ? "证据原始字段" : "模型推断 · 需人工核对"}</strong><p>{claim.text}</p><div className="compare-toolbar">{claim.fact_ids.map(id => <button type="button" className="text-button" key={id} onClick={() => revealFact(id)}>核对 {id}</button>)}</div></article>)}{!recallPack && run.answer.uncertainty ? <div className="ai-claim inference"><strong>模型报告的不确定性 · 需核对</strong><p>{run.answer.uncertainty}</p></div> : null}<p className="review-boundary">{run.answer.notice}</p></> : null}
        {run.state === "pending" || run.state === "outcome_unknown" ? <><p>未确认完成的调用不会自动重试。请核对调用记录及供应商用量；结果未知不代表未计费。</p><button className="secondary-button" disabled={busy} onClick={() => void openRun(run.id)}>刷新这条调用记录</button></> : target ? <button className="secondary-button" disabled={busy} onClick={reset}>重新准备证据，开始新的分析</button> : null}
      </section> : null}
      {stream && run && ["failed", "outcome_unknown"].includes(run.state) && target ? <button type="button" className="secondary-button" disabled={busy} onClick={reset}>重新准备证据，开始新的分析</button> : null}
      <section className="ai-history" aria-label="AI 调用记录"><div className="panel-title"><h3>本浏览器会话的最近调用</h3><button className="text-button" disabled={busy} onClick={() => void perform(async signal => { const [h, s] = await Promise.all([tireApi.aiHistory(signal), tireApi.aiStatus(signal)]); if (!signal.aborted) { setHistory(h.items); setStatus(s); } })}>刷新记录与配置</button></div>{history.length ? history.map(item => <button className="ai-history-item" type="button" key={item.id} disabled={busy} onClick={() => void openRun(item.id, item.request_contract?.delivery_mode === "stream")}><span>{item.question}</span><small>{states[item.state]} · {stamp(item.created_at)}</small></button>) : <p>暂无调用记录。准备证据不会调用模型。</p>}</section>
    </div>
  </dialog>{reportSave ? <SaveReportDialog pack={reportSave.pack} analysis={reportSave.analysis} onClose={() => setReportSave(null)} onSaved={setSavedReport} /> : null}</>;
}
