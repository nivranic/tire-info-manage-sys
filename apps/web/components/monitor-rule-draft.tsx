"use client";

import { useEffect, useRef, useState } from "react";
import { SourceOnlineNotice, useSourceAccess } from "./source-status";
import { ApiError, tireApi } from "@tire/api-client";
import type { AIRuleDraftPack, AIRuleDraftRun, AIStatus, Source } from "@tire/domain-types";

const stamp = (value: string) => new Date(value).toLocaleString("zh-CN");
const states = { pending: "生成处理中", outcome_unknown: "调用结果待确认", completed: "草稿已生成", failed: "生成未完成" };
const unsupportedLabels: Record<string, string> = { numeric_thresholds: "数值或价格阈值", inventory: "库存变化", external_delivery: "邮件、短信等外部通知", negative_conditions: "排除某类规格的负向条件", compound_logic: "多个条件的组合逻辑" };
const errors: Record<string, string> = {
  ai_disabled: "AI 尚未启用；仍可在本机准备需求。",
  ai_configuration_required: "尚未配置专用 OpenAI 密钥或模型。",
  ai_configuration_invalid: "本机 AI 配置无效，请检查模型与预算设置。",
  ai_grounding_validation_failed: "输出未通过草稿约束校验，未生成可应用的规则。",
  ai_provider_timeout: "模型响应超时，调用可能已经计费。",
  ai_provider_network_error: "未能确认模型响应，调用可能已经计费。",
  ai_response_incomplete: "模型输出不完整，未采纳为草稿。",
  ai_refused: "模型拒绝了本次请求。",
};
const errorText = (cause: unknown) => cause instanceof Error ? errors[cause.message] || cause.message : "请求未完成。";

export default function MonitorRuleDraftDialog({ sources, initialRunId, onClose, onReview }: {
  sources: Source[]; initialRunId?: string; onClose: () => void; onReview: (run: AIRuleDraftRun) => void;
}) {
  const sourceAccess = useSourceAccess();
  const available = sources.filter(source => (!source.target_kind || source.target_kind === "tire") && sourceAccess.canQuery(source.id));
  const dialog = useRef<HTMLDialogElement>(null);
  const operation = useRef<AbortController | null>(null);
  const [sourceId, setSourceId] = useState(available[0]?.id || "");
  const [instruction, setInstruction] = useState("");
  const [pack, setPack] = useState<AIRuleDraftPack | null>(null);
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [history, setHistory] = useState<AIRuleDraftRun[]>([]);
  const [run, setRun] = useState<AIRuleDraftRun | null>(null);
  const [externalConsent, setExternalConsent] = useState(false);
  const [attempt, setAttempt] = useState<{ key: string; packId: string } | null>(null);
  const attemptRef = useRef<{ key: string; packId: string } | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  function restore(value: AIRuleDraftRun) {
    setRun(value); setPack(value.pack || null); setExternalConsent(false);
    setAttempt(null); attemptRef.current = null;
    if (value.pack) { setSourceId(value.pack.source.id); setInstruction(value.pack.instruction); }
  }

  useEffect(() => {
    const node = dialog.current;
    const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    const controller = new AbortController();
    void Promise.allSettled([tireApi.aiStatus(controller.signal), tireApi.ruleDraftHistory(controller.signal),
      initialRunId ? tireApi.ruleDraft(initialRunId, controller.signal) : Promise.resolve(null)]).then(([configuration, recent, selected]) => {
      if (controller.signal.aborted) return;
      if (configuration.status === "fulfilled") setStatus(configuration.value); else setError(errorText(configuration.reason));
      if (recent.status === "fulfilled") setHistory(recent.value.items); else setError(errorText(recent.reason));
      if (selected.status === "fulfilled" && selected.value) restore(selected.value);
      else if (selected.status === "rejected") setError(errorText(selected.reason));
      setBusy(false);
    });
    return () => {
      controller.abort(); operation.current?.abort(); node?.close();
      (focus?.isConnected ? focus : document.getElementById("monitoring-title"))?.focus({ preventScroll: true });
    };
  }, [initialRunId]);

  async function perform(work: (signal: AbortSignal) => Promise<void>) {
    if (operation.current) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError("");
    try { await work(controller.signal); }
    catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (operation.current === controller) operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }

  async function prepare() {
    if (!sourceId || instruction.trim().length < 2 || attemptRef.current || run) return;
    await perform(async signal => {
      if (!await sourceAccess.ensure(sourceId)) { setError("来源当前不能在线采集，请重新核对来源后准备需求。"); return; }
      if (signal.aborted) return;
      const value = await tireApi.prepareRuleDraft(sourceId, instruction.trim(), signal);
      if (!signal.aborted) { setPack(value); setExternalConsent(false); }
    });
  }

  async function generate() {
    if (!pack || operation.current || (!attemptRef.current && !externalConsent)) return;
    const value = attemptRef.current || { key: crypto.randomUUID(), packId: pack.id };
    attemptRef.current = value; setAttempt(value);
    await perform(async signal => {
      try {
        const result = await tireApi.generateRuleDraft(value.packId, value.key, signal);
        if (!signal.aborted) {
          setRun(result); setHistory(previous => [result, ...previous.filter(item => item.id !== result.id)].slice(0, 20));
        }
      } catch (cause) {
        // Definite pre-reservation rejection can be corrected. Transport uncertainty
        // retains this exact pack and key for a user-requested result check.
        if (!signal.aborted && cause instanceof ApiError && cause.status >= 400 && cause.status < 500) {
          attemptRef.current = null; setAttempt(null);
        }
        throw cause;
      }
      const next = await tireApi.aiStatus(signal);
      if (!signal.aborted) setStatus(next);
    });
  }

  async function openRun(id: string) {
    await perform(async signal => {
      const value = await tireApi.ruleDraft(id, signal);
      if (!signal.aborted) restore(value);
    });
  }

  function reset() {
    if (operation.current) return;
    setPack(null); setRun(null); setExternalConsent(false); setAttempt(null); attemptRef.current = null; setError("");
  }

  const frozen = !!pack || !!run || !!attempt;
  const canSend = status?.model.state === "configured" && status.model.allowed_privacy_classes?.includes("private");
  const draft = run?.draft;
  const unresolved = !!draft && (!!draft.unsupported_requirements.length || !!draft.clarifications.length);
  const canReview = run?.state === "completed" && draft?.can_apply && !!draft.rule && !unresolved && !run.application;
  const pending = run?.state === "pending" || run?.state === "outcome_unknown";
  const draftSourceId = draft?.rule?.source_id;
  const draftRequiresSize = pack && pack.source.id === draftSourceId && pack.source.requires_size !== undefined
    ? pack.source.requires_size === true
    : sources.find(source => source.id === draftSourceId)?.requires_size === true;

  return <dialog ref={dialog} className="fact-review-dialog ai-dialog rule-draft-dialog" aria-labelledby="rule-draft-title"
    onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">INTENT → REVIEW → RULE</span><h2 id="rule-draft-title">用自然语言起草监控规则</h2></div><button type="button" className="icon-button" aria-label="关闭规则草稿" onClick={onClose}>×</button></header>
    <div className="ai-content">
      <p className="review-boundary">先在本机固定原文与来源能力，再由你授权发送到 OpenAI。生成草稿不会创建或启用规则；保存前须另行编辑、核对和确认。关闭窗口不会取消已经外发的调用。</p>
      <section className="ai-status" aria-label="草稿模型状态"><strong>OpenAI Responses API</strong><p>{status ? status.model.state === "configured" ? `${status.model.model} · 已配置，连接待实际调用验证` : errors[status.model.state] || status.model.state : "正在读取配置…"}</p>{status ? <small>UTC {status.budget.day_utc}：{status.budget.requests} 次请求，已记账 {status.budget.accounted_tokens.toLocaleString()} tokens。包含未知用量的预留。</small> : null}</section>
      {error ? <p className="inline-error" role="alert">{error}</p> : null}
      <SourceOnlineNotice sourceId={sourceId} /><form className="review-form draft-form" onSubmit={event => { event.preventDefault(); void prepare(); }}>
        <label><span>选择已经接入的来源</span><select required value={sourceId} disabled={busy || frozen} onChange={event => setSourceId(event.target.value)}>
          {!sourceId ? <option value="">暂无可用来源</option> : null}
          {sourceId && !available.some(source => source.id === sourceId) ? <option value={sourceId}>{pack?.source.name || sourceId}（历史来源）</option> : null}
          {available.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}
        </select></label>
        <label><span>描述你要关注的变化</span><textarea required minLength={2} maxLength={2000} rows={4} value={instruction} disabled={busy || frozen}
          placeholder="例如：每 6 小时检查已接入型号，关注带 Acoustic 技术的规格参数变化，通过站内提醒通知我。"
          onChange={event => setInstruction(event.target.value)} /></label>
        {!frozen ? <button type="submit" className="secondary-button" disabled={busy || !sourceAccess.canQuery(sourceId) || !sourceId || instruction.trim().length < 2}>在本机准备需求与能力清单</button> : null}
      </form>
      {pack ? <section className="draft-frozen" aria-label="已冻结的规则需求">
        <div className="snapshot-banner"><strong>本机需求快照 · {pack.source.name}</strong><span>准备 {stamp(pack.created_at)} · 调用有效期至 {stamp(pack.expires_at)}</span></div>
        <h3>将要发送的需求原文</h3><p className="draft-original">{pack.instruction}</p>
        <details open><summary>本次来源与支持边界</summary><dl className="draft-capabilities">
          <div><dt>来源</dt><dd>{pack.source.name} · {pack.source.region} · {pack.source.id}</dd></div>
          <div><dt>已经接入的型号</dt><dd>{pack.supported_models.join("、") || "无"}</dd></div>
          <div><dt>检查间隔</dt><dd>{pack.capabilities.interval_seconds.minimum / 3600}–{pack.capabilities.interval_seconds.maximum / 3600} 小时；默认 {pack.capabilities.interval_seconds.default / 3600} 小时</dd></div>
          <div><dt>提醒类型</dt><dd>{pack.capabilities.kinds.map(kind => kind === "facts_changed" ? "参数变化" : "首次观察到规格（非新发布）").join("、")}</dd></div>
          <div><dt>技术条件</dt><dd>{pack.capabilities.technologies.join("、") || "无预设技术"}；匹配精确 SKU 身份值，不搜索营销文案</dd></div>
          <div><dt>通知渠道</dt><dd>{pack.capabilities.notification_channels.map(channel => channel === "in_app" ? "站内提醒" : channel).join("、")}</dd></div>
        </dl><details><summary>可关注字段</summary><p>{pack.capabilities.fields.map(field => `${field.label}（${field.key}）`).join("、") || "未列出字段"}</p></details>
        {pack.capabilities.unsupported_features.length ? <><p>未实现的能力：</p><ul>{pack.capabilities.unsupported_features.map((value, index) => <li key={index}>{unsupportedLabels[value] || value}</li>)}</ul></> : null}</details>
        {!run ? <div className="draft-send"><label className="review-checkbox"><input type="checkbox" checked={externalConsent} disabled={busy || !!attempt} onChange={event => setExternalConsent(event.target.checked)} />我允许将上述需求原文、来源和能力清单发送到 OpenAI，生成待审核草稿。</label>
          {!canSend && !attempt ? <p className="review-boundary">模型配置或工作区隐私策略尚不允许提交。准备需求本身不会外发。</p> : null}
          <div className="variant-actions"><button type="button" className="primary-button" disabled={busy || (!attempt && (!canSend || !externalConsent))} onClick={() => void generate()}>{busy ? "正在处理…" : attempt ? "用同一请求标识核对结果" : "发送到 OpenAI 生成草稿"}</button>
          {!attempt ? <button type="button" className="text-button" disabled={busy} onClick={reset}>修改原文并重新准备</button> : null}</div>
          {attempt ? <p role="status">请求标识已保留。网络中断后的结果核对沿用同一标识；已受理调用不会再次外发。</p> : null}
        </div> : null}
      </section> : null}
      {run ? <section className="ai-result" aria-label="规则草稿结果"><h3>{states[run.state]}</h3><small>{stamp(run.created_at)} · {run.usage ? `${run.usage.total_tokens} tokens` : `用量待确认，保留 ${run.reserved_tokens} tokens 预留`}</small>
        {run.error_code ? <p className="inline-error" role="alert">{errors[run.error_code] || run.error_code}</p> : null}
        {draft ? <><p className="draft-original">{draft.summary}</p>
          {draft.unsupported_requirements.length ? <div className="source-conflict"><strong>这些要求目前不能执行</strong><ul>{draft.unsupported_requirements.map((item, index) => <li key={index}>{item}</li>)}</ul></div> : null}
          {draft.clarifications.length ? <div className="source-conflict"><strong>这些内容仍需补充</strong><ul>{draft.clarifications.map((item, index) => <li key={index}>{item}</li>)}</ul></div> : null}
          {draft.rule ? <dl className="draft-capabilities"><div><dt>草稿名称</dt><dd>{draft.rule.name}</dd></div><div><dt>查询目标</dt><dd>{draft.rule.source_id} · {draft.rule.query.model} · {draft.rule.query.size || (draftRequiresSize ? "缺少必需尺寸" : "全部尺寸")}</dd></div><div><dt>运行设置</dt><dd>每 {draft.rule.interval_seconds / 3600} 小时 · 保存前默认暂停</dd></div><div><dt>关注条件</dt><dd>{draft.rule.kinds.map(kind => kind === "facts_changed" ? "参数变化" : "首次观察到规格").join("、")} · {draft.rule.fields.join("、") || "全部字段"} · 技术 {draft.rule.conditions.technology || "不限"}</dd></div></dl> : null}
          {unresolved || !draft.can_apply ? <p className="review-boundary">存在未解决要求时不能应用；请修改原文、重新准备，并单独授权新的生成请求。</p> : null}
        </> : null}
        {run.application ? <div className="snapshot-banner"><strong>已确认保存为监控规则</strong><span>{run.application.reviewed_rule.name} · {run.application.reviewed_rule.enabled ? "已启用" : "已暂停"} · {stamp(run.application.created_at)}</span></div> : null}
        {canReview ? <button type="button" className="primary-button" disabled={busy} onClick={() => onReview({ ...run, ...(pack ? { pack } : {}) })}>编辑并确认</button> : null}
        {pending ? <><p>结果未知不代表未计费；不会自动发起新调用。</p><button type="button" className="secondary-button" disabled={busy} onClick={() => void openRun(run.id)}>刷新这条调用记录</button></> : <button type="button" className="secondary-button" disabled={busy} onClick={reset}>以原文重新准备需求</button>}
      </section> : null}
      <section className="ai-history" aria-label="历史规则草稿"><div className="panel-title"><h3>本浏览器会话的规则草稿</h3><button type="button" className="text-button" disabled={busy} onClick={() => void perform(async signal => {
        const [items, configuration] = await Promise.all([tireApi.ruleDraftHistory(signal), tireApi.aiStatus(signal)]);
        if (!signal.aborted) { setHistory(items.items); setStatus(configuration); }
      })}>刷新记录与配置</button></div>
        {history.length ? history.map(item => <button type="button" className="ai-history-item" key={item.id} disabled={busy} onClick={() => void openRun(item.id)}><span>{states[item.state]} · {stamp(item.created_at)}</span><small>打开原文、能力快照及审核结果</small></button>) : <p>暂无调用记录。在本机准备需求不会调用模型。</p>}
      </section>
    </div>
  </dialog>;
}
