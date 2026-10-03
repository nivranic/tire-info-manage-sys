"use client";

import { useEffect, useRef, useState } from "react";
import { MonitorTaskDialog } from "./task-center";
import { SourceOnlineNotice, SourceStatus, useSourceAccess } from "./source-status";
import { ApiError, tireApi } from "@tire/api-client";
import type { AIRuleDraftRun, AlertRuleCreate, AlertRuleDetail, AlertRuleRecord, AlertRuleSettings, LocalNotification, Source, WatchItem } from "@tire/domain-types";
import { IdentityContractBadge, identityContractText } from "./identity-contract";
import MonitorRuleDraftDialog from "./monitor-rule-draft";

const errorText = (cause: unknown) => cause instanceof ApiError && cause.code === "identity_contract_review_required" ? "此精确 SKU 的身份编码类型尚未完成核对，不能自动跟随相关候选。请先核对身份。" : cause instanceof Error ? cause.message : "操作未完成，请重试。";
const stamp = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "尚未记录";
const valueText = (value: unknown) => value === null || value === undefined ? "未声明" : typeof value === "object" ? JSON.stringify(value) : String(value);
const kindText = (kind: string) => kind === "variant_observed" ? "首次观察到规格" : "参数变化";
const stateText: Record<string, string> = { live: "在线采纳成功", live_verified_304: "在线确认未变", source_unavailable: "在线来源不可用", worker_error: "任务执行异常" };
const blank = (): AlertRuleSettings => ({ name: "", interval_seconds: 21600, enabled: false, kinds: ["facts_changed"], fields: [], conditions: {} });
const ruleSettings = (value: AlertRuleCreate, enabled = value.enabled): AlertRuleSettings => ({ name: value.name, interval_seconds: value.interval_seconds, enabled, kinds: value.kinds, fields: value.fields, conditions: value.conditions || {} });

function RuleEditor({ id, draft, sources, watches, onClose, onChanged }: { id: string | null; draft?: AIRuleDraftRun; sources: Source[]; watches: WatchItem[]; onClose: () => void; onChanged: () => void }) {
  const sourceAccess = useSourceAccess();
  const available = sources.filter(source => (!source.target_kind || source.target_kind === "tire") && sourceAccess.canQuery(source.id));
  const seed = draft?.draft?.rule;
  const [data, setData] = useState<AlertRuleDetail | null>(null);
  const [settings, setSettings] = useState<AlertRuleSettings>(() => seed ? ruleSettings(seed, false) : blank());
  const [sourceId, setSourceId] = useState(seed?.source_id || available[0]?.id || "");
  const [model, setModel] = useState(seed?.query.model || available[0]?.supported_models?.[0] || "");
  const [size, setSize] = useState(seed?.query.size || "");
  const [variantId, setVariantId] = useState(seed?.variant_id || "");
  const [fields, setFields] = useState(seed?.fields.join(", ") || "");
  const [technology, setTechnology] = useState(seed?.conditions?.technology || "");
  const [acknowledged, setAcknowledged] = useState(false);
  const [applyAttempt, setApplyAttempt] = useState<{ key: string; rule: AlertRuleCreate } | null>(null);
  const applyAttemptRef = useRef<{ key: string; rule: AlertRuleCreate } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const mutation = useRef<AbortController | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { node?.close(); mutation.current?.abort(); (focus?.isConnected && !focus.closest("dialog:not([open])") ? focus : document.getElementById("monitoring-title"))?.focus({ preventScroll: true }); };
  }, []);
  useEffect(() => {
    if (!id) return;
    const controller = new AbortController(); setData(null); setError("");
    void tireApi.alertRule(id, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      setData(value); setSettings(ruleSettings(value));
      setSourceId(value.source_id); setModel(value.query.model || ""); setSize(value.query.size || ""); setVariantId(value.variant_id || ""); setFields(value.fields.join(", ")); setTechnology(value.conditions?.technology || ""); setStale(false);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [id, attempt]);
  async function save(action: "save" | "archive" | "restore") {
    if (mutation.current || busy || stale || (id && !data) || (draft && !acknowledged)) return;
    const controller = new AbortController(); mutation.current = controller; setBusy(true); setError("");
    try {
      if (action === "save" && !applyAttemptRef.current && (!data || settings.enabled) && !await sourceAccess.ensure(sourceId)) { setError("来源当前不能在线采集。已有规则仍保留，可取消启用后保存暂停设置。"); return; }
      if (controller.signal.aborted) return;
      const payload = { ...settings, conditions: technology.trim() ? { technology: technology.trim() } : {}, fields: fields.split(/[,，\s]+/).filter(Boolean) };
      if (action !== "save" && data) await tireApi.alertRuleState(data.id, data.revision, action, controller.signal);
      else if (data) await tireApi.editAlertRule(data.id, data.revision, payload, controller.signal);
      else {
        const request: AlertRuleCreate = { ...payload, source_id: sourceId, query: { model, ...(size.trim() ? { size: size.trim() } : {}) }, variant_id: variantId || null };
        if (draft) {
          if (!draft.draft?.can_apply || draft.draft.unsupported_requirements.length || draft.draft.clarifications.length || draft.application) return;
          const saved = applyAttemptRef.current || { key: crypto.randomUUID(), rule: request };
          applyAttemptRef.current = saved; setApplyAttempt(saved);
          await tireApi.applyRuleDraft(draft.id, saved.rule, saved.key, controller.signal);
        } else await tireApi.createAlertRule(request, controller.signal);
      }
      if (!controller.signal.aborted) { onChanged(); onClose(); }
    } catch (cause) { if (!controller.signal.aborted) {
      setError(errorText(cause));
      if (cause instanceof ApiError && cause.status >= 400 && cause.status < 500) { setApplyAttempt(null); applyAttemptRef.current = null; }
      if (cause instanceof ApiError && cause.status === 409) setStale(true);
    } }
    finally { if (mutation.current === controller) mutation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  function toggleKind(kind: "facts_changed" | "variant_observed", checked: boolean) {
    setSettings(previous => ({ ...previous, kinds: checked ? [...previous.kinds, kind] : previous.kinds.filter(value => value !== kind) }));
  }
  const locked = busy || !!applyAttempt || stale || data?.archived;
  const models = draft?.pack?.source.id === sourceId ? draft.pack.supported_models : available.find(source => source.id === sourceId)?.supported_models || [];
  const requiresSize = sources.find(source => source.id === sourceId)?.requires_size === true
    || (draft?.pack?.source.id === sourceId && draft.pack.source.requires_size === true);
  return <dialog className="fact-review-dialog monitor-dialog" ref={dialog} aria-label={id ? "编辑监控规则" : draft ? "审核 AI 监控草稿" : "创建监控规则"} onCancel={event => { event.preventDefault(); event.stopPropagation(); if (!busy) onClose(); }}>
    <div className="fact-review-heading"><div><span className="eyebrow">MONITOR RULE</span><h2>{id ? "编辑监控规则" : draft ? "审核 AI 监控草稿" : "创建监控规则"}</h2></div><button className="text-button" type="button" disabled={busy} onClick={onClose}>关闭</button></div>
    <div className="fact-review-content"><SourceStatus sourceId={sourceId} /><SourceOnlineNotice sourceId={sourceId} /><p className="review-boundary">本地工作区共享规则。仅在启用后记录已采纳的变化，暂停期间不补发；首次观察不代表厂商刚发布。定时抓取需要独立 Worker 运行。</p>
      {error ? <div role="alert" className="inline-error">{error}{id ? <button type="button" className="text-button" disabled={busy} onClick={() => setAttempt(value => value + 1)}>重新载入规则</button> : null}</div> : null}
      {draft ? <p className="review-boundary">本页是人工审核步骤。来源沿用已冻结需求，默认暂停；只有勾选“启用此规则”并确认保存，规则才会启用。一次草稿最多创建一条规则。</p> : null}
      {draft?.pack ? <section className="ai-claim" aria-label="审核对照的需求原文"><h3>需求原文</h3><p className="draft-original">{draft.pack.instruction}</p></section> : null}
      {applyAttempt ? <p role="status" className="review-boundary">保存请求已固定。网络中断后使用下方按钮核对同一次保存；审核内容暂时锁定，不会另建一条规则。</p> : null}
      {id && !data ? <p role="status">正在读取规则…</p> : <form className="review-form" onSubmit={event => { event.preventDefault(); void save("save"); }}>
        <label><span>规则名称</span><input required maxLength={120} disabled={locked} value={settings.name} onChange={event => setSettings(previous => ({ ...previous, name: event.target.value }))} /></label>
        {id ? <p className="review-boundary">来源 {sourceId} · {model} · {size || (requiresSize ? "缺少必需尺寸" : "全部尺寸")} · {variantId ? "限定精确 SKU" : "查询范围内规格"}。更换目标请新建规则，旧历史继续保留。</p> : <>
          <label><span>监控来源{draft ? "（沿用需求快照）" : ""}</span><select required value={sourceId} disabled={locked || !!draft} onChange={event => { setSourceId(event.target.value); setModel(available.find(item => item.id === event.target.value)?.supported_models?.[0] || ""); setVariantId(""); }}>{sourceId && !available.some(source => source.id === sourceId) ? <option value={sourceId}>{sourceId}（来源待重新核对）</option> : null}{available.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}</select></label>
          <label><span>监控型号</span><select required value={model} disabled={locked} onChange={event => { setModel(event.target.value); setVariantId(""); }}>{model && !models.includes(model) ? <option value={model}>{model}（型号待重新核对）</option> : null}{models.map(item => <option key={item}>{item}</option>)}</select></label>
          <label><span>{requiresSize ? "监控尺寸（此来源必填）" : "监控尺寸（留空为全部尺寸）"}</span><input required={requiresSize} value={size} maxLength={24} placeholder="265/40R20" disabled={locked} onChange={event => { setSize(event.target.value); setVariantId(""); }} /></label>
          <label><span>规格范围</span><select value={variantId} disabled={locked} onChange={event => {
            setVariantId(event.target.value);
            const selected = watches.find(item => item.variant_id === event.target.value)?.variant;
            if (selected) setSize(selected.size);
          }}><option value="">查询范围内全部规格</option>{watches.filter(item => item.variant && item.variant.model.includes(model) && item.variant.source_id === sourceId).map(item => <option value={item.variant_id} key={item.id}>{item.variant!.model} · {item.variant!.size} · {item.variant!.manufacturer_product_code || "代码未知"} · {identityContractText(item.variant!.identity_contract)}</option>)}</select></label>
        </>}
        <label><span>检查间隔（小时）</span><input type="number" required min={4} max={168} step={1} value={settings.interval_seconds / 3600} disabled={locked} onChange={event => setSettings(previous => ({ ...previous, interval_seconds: Number(event.target.value) * 3600 }))} /></label>
        <fieldset disabled={locked} className="monitor-kinds"><legend>提醒条件</legend><label className="review-checkbox"><input type="checkbox" checked={settings.kinds.includes("facts_changed")} onChange={event => toggleKind("facts_changed", event.target.checked)} />参数变化</label><label className="review-checkbox"><input type="checkbox" checked={settings.kinds.includes("variant_observed")} onChange={event => toggleKind("variant_observed", event.target.checked)} />首次观察到规格</label></fieldset>
        <label><span>关注字段（留空为全部参数）</span><input maxLength={3200} disabled={locked} value={fields} placeholder="例如 utqg_treadwear, eu_wet_grip" onChange={event => setFields(event.target.value)} /></label>
        <label><span>技术条件（留空为不限）</span><input maxLength={100} disabled={locked} value={technology} placeholder="例如 Acoustic、PNCS、ContiSilent" aria-describedby="monitor-technology-help" onChange={event => setTechnology(event.target.value)} /></label>
        <p id="monitor-technology-help" className="review-boundary">技术名称与精确 SKU 身份中的技术值完整匹配；只统一大小写、空格和全半角，不匹配营销文案或相似关键词。</p>
        <label className="review-checkbox"><input type="checkbox" checked={settings.enabled} disabled={locked || (!settings.enabled && !sourceAccess.canQuery(sourceId))} onChange={event => setSettings(previous => ({ ...previous, enabled: event.target.checked }))} />启用此规则</label>
        {draft ? <label className="review-checkbox"><input type="checkbox" checked={acknowledged} disabled={locked} onChange={event => setAcknowledged(event.target.checked)} />我已核对来源、条件与启用状态，确认保存以上监控规则。</label> : null}
        <div className="variant-actions">{!data?.archived ? <button type="submit" className="primary-button" disabled={busy || stale || !settings.kinds.length || !sourceId || !model || (!!draft && !acknowledged)}>{applyAttempt ? "核对同一次保存结果" : draft ? "确认并保存监控规则" : "保存规则"}</button> : null}{data ? <button type="button" className="text-button" disabled={busy || stale} onClick={() => void save(data.archived ? "restore" : "archive")}>{data.archived ? "恢复为暂停规则" : "归档规则"}</button> : null}</div>
        {data ? <section className="review-history"><h3>规则历史{data.history_truncated ? "（最近 50 条）" : ""}</h3>{data.history.map(row => <details key={row.revision}><summary>#{row.revision} · {row.archived ? "已归档" : row.enabled ? "启用" : "暂停"} · {stamp(row.created_at)}</summary><p>{row.name} · 每 {row.interval_seconds / 3600} 小时</p><p>{row.kinds.map(kindText).join("、")} · {row.fields.join("、") || "全部字段"} · 技术 {row.conditions?.technology || "不限"}</p></details>)}</section> : null}
      </form>}
    </div>
  </dialog>;
}

export default function MonitoringCenter({ sources, watches, onEvidence, onExplain }: { sources: Source[]; watches: WatchItem[]; onEvidence: (id: string) => void; onExplain: (notice: LocalNotification) => void }) {
  const [taskJobId, setTaskJobId] = useState<string | null>(null);
  const sourceAccess = useSourceAccess();
  const [rules, setRules] = useState<AlertRuleRecord[]>([]);
  const [notices, setNotices] = useState<LocalNotification[]>([]);
  const [ruleTotal, setRuleTotal] = useState(0);
  const [noticeTotal, setNoticeTotal] = useState(0);
  const [archived, setArchived] = useState(false);
  const [unread, setUnread] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [editor, setEditor] = useState<string | null | undefined>(undefined);
  const [draftId, setDraftId] = useState<string | null | undefined>(undefined);
  const [draftReview, setDraftReview] = useState<AIRuleDraftRun | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  const mutation = useRef<AbortController | null>(null);
  useEffect(() => () => mutation.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController(); request.current = controller; setLoading(true); setError("");
    void Promise.all([tireApi.alertRules(archived, controller.signal), tireApi.notifications(unread, controller.signal)]).then(([ruleList, noticeList]) => {
      if (!controller.signal.aborted) { setRules(ruleList.items); setRuleTotal(ruleList.total); setNotices(noticeList.items); setNoticeTotal(noticeList.total); }
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [archived, unread, attempt]);
  async function more(kind: "rules" | "notices") {
    if (busy || loading) return;
    const controller = request.current;
    if (!controller) return;
    setBusy(true);
    try {
      if (kind === "rules") { const data = await tireApi.alertRules(archived, controller.signal, rules.length); if (!controller.signal.aborted) { setRules(previous => [...new Map([...previous, ...data.items].map(item => [item.id, item])).values()]); setRuleTotal(data.total); } }
      else { const data = await tireApi.notifications(unread, controller.signal, notices.length); if (!controller.signal.aborted) { setNotices(previous => [...new Map([...previous, ...data.items].map(item => [item.id, item])).values()]); setNoticeTotal(data.total); } }
    } catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  async function mark(notice: LocalNotification) {
    if (busy) return;
    const controller = new AbortController(); mutation.current = controller; setBusy(true); setError("");
    try { await tireApi.markNotification(notice.id, !notice.read_at, controller.signal); if (!controller.signal.aborted) setAttempt(value => value + 1); }
    catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section className="monitoring-center" aria-labelledby="monitoring-title">
    <div className="panel-title"><span id="monitoring-title" tabIndex={-1}>监控与站内提醒</span><button type="button" className="text-button" disabled={loading || busy} onClick={() => setAttempt(value => value + 1)}>刷新记录</button></div>
    <p className="quality-intro">规则与提醒保存在本地工作区。启用规则后，由独立运行的监控服务按计划访问来源；页面不会自行启动后台服务。提醒是历史变化记录，不代表当前在线参数。</p>
    {error ? <p role="alert" className="inline-error">{error}</p> : null}
    <div className="quarantine-filter"><label><span>监控规则范围</span><select disabled={busy} value={archived ? "archived" : "active"} onChange={event => setArchived(event.target.value === "archived")}><option value="active">使用中的规则</option><option value="archived">已归档规则</option></select></label><button type="button" className="secondary-button" onClick={() => { setDraftReview(null); setEditor(null); }} disabled={!sources.some(source => (!source.target_kind || source.target_kind === "tire") && sourceAccess.canQuery(source.id))}>创建监控规则</button><button type="button" className="secondary-button" onClick={() => setDraftId(null)}>用自然语言起草</button></div>
    {loading ? <p role="status" className="quality-empty">正在读取监控记录…</p> : <>
      {rules.length ? rules.map(rule => <article className="quarantine-item" key={rule.id}><div className="quality-item-heading"><h3>{rule.name}</h3><span className="tag quiet">{rule.archived ? "已归档" : rule.enabled ? "规则已启用" : "已暂停"}</span></div><SourceStatus sourceId={rule.source_id} /><SourceOnlineNotice sourceId={rule.source_id} /><p className="monitor-text">{rule.source_id} · {rule.query.model} · {rule.query.size || (sources.some(source => source.id === rule.source_id && source.requires_size === true) ? "缺少必需尺寸" : "全部尺寸")} · 每 {rule.interval_seconds / 3600} 小时{rule.variant_id ? " · 精确 SKU" : ""} · 技术 {rule.conditions?.technology || "不限"}</p>{rule.variant_id ? <IdentityContractBadge contract={rule.identity_contract || undefined} /> : null}{rule.tracking_state === "identity_review_required" ? <p className="review-warning">此规则继续引用旧 SKU，身份需要核对；不会自动跟随相关新候选。</p> : null}<p className="monitor-text">最近执行：{rule.job.last_run ? `${stamp(rule.job.last_run.finished_at)} · ${stateText[rule.job.last_run.state] || rule.job.last_run.state}` : "尚无完成记录"}{rule.job.next_due_at ? `；计划时间 ${stamp(rule.job.next_due_at)}` : ""}</p><div className="variant-actions"><button type="button" className="text-button" onClick={() => setTaskJobId(rule.job.id)}>查看任务运行</button><button type="button" className="text-button" onClick={() => { setDraftReview(null); setEditor(rule.id); }}>编辑与历史</button>{rule.origin ? <button type="button" className="text-button" onClick={() => setDraftId(rule.origin!.draft_id)}>来源：已人工确认的 AI 草稿</button> : null}</div></article>) : <p className="quality-empty">暂无此范围的监控规则。关注标记不会自动创建或启用规则。</p>}
      {rules.length < ruleTotal ? <button type="button" className="secondary-button" disabled={busy} onClick={() => void more("rules")}>加载更多规则</button> : null}
      <div className="panel-title"><span>站内提醒 · {noticeTotal}</span><label className="review-checkbox"><input type="checkbox" checked={unread} disabled={busy} onChange={event => setUnread(event.target.checked)} />只看未读</label></div>
      {notices.length ? notices.map(notice => <article className="quarantine-item" key={notice.id}><div className="quality-item-heading"><h3>{notice.rule_name} · {kindText(notice.kind)}</h3><span className="tag quiet">{notice.read_at ? "已读" : "未读"}</span></div><p className="monitor-text">{valueText(notice.identity.model)} · {valueText(notice.identity.size)} · {valueText(notice.identity.manufacturer_product_code)}</p><IdentityContractBadge contract={notice.identity_contract} /><p className="monitor-text">LOCAL SNAPSHOT · {notice.source_id} · {stamp(notice.observed_at)} · 规则修订 #{notice.rule_revision}</p><dl className="monitor-diff">{Object.entries(notice.changes).map(([field, change]) => <div key={field}><dt>{field}</dt><dd>{change.before_present ? valueText(change.before) : "原未声明"} → {change.after_present ? valueText(change.after) : "现未声明"}</dd></div>)}</dl><div className="variant-actions"><button type="button" className="text-button" onClick={() => onExplain(notice)}>解释这次变化</button><button type="button" className="text-button" onClick={() => onEvidence(notice.snapshot_id)}>查看变化后证据</button>{notice.previous_snapshot_id ? <button type="button" className="text-button" onClick={() => onEvidence(notice.previous_snapshot_id!)}>查看变化前证据</button> : null}<button type="button" className="text-button" disabled={busy} onClick={() => void mark(notice)}>标记为{notice.read_at ? "未读" : "已读"}</button></div></article>) : <p className="quality-empty">暂无{unread ? "未读" : ""}站内提醒。只有启用规则后采纳且符合条件的变化才会出现；不会补发旧记录。</p>}
      {notices.length < noticeTotal ? <button type="button" className="secondary-button" disabled={busy} onClick={() => void more("notices")}>加载更多提醒</button> : null}
    </>}
    {taskJobId ? <MonitorTaskDialog key={taskJobId} kind="tire" jobId={taskJobId} onClose={() => setTaskJobId(null)} /> : null}
    {draftId !== undefined ? <MonitorRuleDraftDialog key={draftId || "new-draft"} sources={sources} initialRunId={draftId || undefined} onClose={() => setDraftId(undefined)} onReview={run => { setDraftReview(run); setEditor(null); }} /> : null}
    {editor !== undefined ? <RuleEditor key={draftReview?.id || editor || "new"} id={editor} draft={draftReview || undefined} sources={sources} watches={watches} onClose={() => { setEditor(undefined); setDraftReview(null); }} onChanged={() => { setAttempt(value => value + 1); if (draftReview) setDraftId(undefined); }} /> : null}
  </section>;
}
