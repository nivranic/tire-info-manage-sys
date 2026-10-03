"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { SourceSettingAction, SourceSettingHistory, SourceSettingPreview, SourceSettingView } from "@tire/domain-types";
import { Icon } from "./icons";
import { SourceStatus, useSourceAccess } from "./source-status";
import { matchesSourceSettingAttempt, matchesSourceSettingPreview, sourceBlockerText, sourceStateLabels, type SourceSettingAttempt } from "./source-management-values";

const actions: Record<SourceSettingAction, string> = { enable: "启用来源", pause: "暂停来源", archive: "归档来源", restore: "恢复为暂停", edit_notes: "修改备注" };
const pendingRequests = new Map<string, SourceSettingAttempt>();
const stamp = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "尚无人工操作";
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "操作未完成，请核对后重试。";
const publicUrl = (value: string) => { try { const url = new URL(value); return url.protocol === "https:" ? url.href : undefined; } catch { return undefined; } };

function SourceSettingEditor({ sourceId, onClose }: { sourceId: string; onClose: () => void }) {
  const access = useSourceAccess();
  const saved = pendingRequests.get(sourceId);
  const [record, setRecord] = useState<SourceSettingView | null>(null);
  const [history, setHistory] = useState<SourceSettingHistory | null>(null);
  const [offset, setOffset] = useState(0);
  const [readVersion, setReadVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<SourceSettingAction>(saved?.payload.action || "edit_notes");
  const [notes, setNotes] = useState(saved?.payload.notes || "");
  const [operator, setOperator] = useState(saved?.payload.operator || "");
  const [reason, setReason] = useState(saved?.payload.reason || "");
  const [preview, setPreview] = useState<SourceSettingPreview | null>(null);
  const [pending, setPending] = useState<SourceSettingAttempt | null>(saved || null);
  const [busy, setBusy] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const pendingPanel = useRef<HTMLElement>(null);
  const mutation = useRef<AbortController | null>(null);
  const previewRequest = useRef<AbortController | null>(null);
  const previewGeneration = useRef(0);
  const loadedDraftVersion = useRef<number | null>(null);
  const locked = busy || !!pending;
  useEffect(() => {
    const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.current?.showModal();
    return () => { mutation.current?.abort(); previewRequest.current?.abort(); previewGeneration.current++; dialog.current?.close(); if (focus?.isConnected) focus.focus({ preventScroll: true }); };
  }, []);
  useEffect(() => {
    const modal = dialog.current, panel = pendingPanel.current;
    if (!pending || !modal || !panel) return;
    const headerHeight = modal.querySelector(".fact-review-heading")?.getBoundingClientRect().height || 0;
    modal.scrollTop += panel.getBoundingClientRect().top - modal.getBoundingClientRect().top - headerHeight - 12;
  }, [pending]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    void Promise.all([tireApi.sourceSetting(sourceId, controller.signal), tireApi.sourceSettingHistory(sourceId, offset, controller.signal)]).then(([source, events]) => {
      if (controller.signal.aborted) return;
      if (source.source_id !== sourceId || events.source_id !== sourceId) throw new Error("来源记录范围不匹配。");
      setRecord(source); setHistory(events);
      if (!pendingRequests.has(sourceId) && loadedDraftVersion.current !== readVersion) { setNotes(source.management.notes); loadedDraftVersion.current = readVersion; }
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [sourceId, offset, readVersion]);
  function invalidate() { previewRequest.current?.abort(); previewGeneration.current++; setPreview(null); setPreviewing(false); setError(""); setNotice(""); }
  async function prepare() {
    if (locked || loading || !record) return;
    invalidate(); const current = previewGeneration.current; const controller = new AbortController(); previewRequest.current = controller; setPreviewing(true);
    try {
      const result = await tireApi.previewSourceSetting(sourceId, { action, ...(action === "edit_notes" ? { notes } : {}) }, controller.signal);
      if (controller.signal.aborted || current !== previewGeneration.current) return;
      if (!matchesSourceSettingPreview(result, record, { action, notes })) throw new Error("当前来源已变化，请重新读取后预览。");
      setPreview(result);
    } catch (cause) { if (!controller.signal.aborted && current === previewGeneration.current) setError(errorText(cause)); }
    finally { if (!controller.signal.aborted && current === previewGeneration.current) setPreviewing(false); }
  }
  function remember(attempt: SourceSettingAttempt | null) { setPending(attempt); if (attempt) pendingRequests.set(sourceId, attempt); else pendingRequests.delete(sourceId); }
  async function perform(attempt: SourceSettingAttempt) {
    if (mutation.current) return;
    remember(attempt); const controller = new AbortController(); mutation.current = controller; setBusy(true); setError("");
    try {
      const result = await tireApi.reviseSourceSetting(sourceId, attempt.payload, attempt.key, controller.signal);
      if (controller.signal.aborted) return;
      if (!matchesSourceSettingAttempt(result, attempt)) throw new Error("响应与固定请求不一致，请保留同一 UUID 核对。");
      remember(null); setRecord(result.source); setNotes(result.source.management.notes); setPreview(null); setReason(""); setOffset(0); setReadVersion(value => value + 1);
      setNotice(`已核对操作修订 #${result.event.revision}${result.replayed ? "（同一次请求）" : ""}。当前来源修订 #${result.source.management.revision}，${sourceStateLabels[result.source.management.state]}。`);
      access.accept(result.source);
    } catch (cause) {
      if (controller.signal.aborted) return;
      setError(errorText(cause));
      if (cause instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(cause.status) && cause.code !== "idempotency_payload_mismatch") {
        remember(null); invalidate(); setError(errorText(cause)); setNotice("本次请求未被接受，请重新读取来源和历史后预览。"); setReadVersion(value => value + 1);
      }
    } finally { if (mutation.current === controller) mutation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  function submit() {
    if (locked || !preview?.can_submit || !operator.trim() || reason.trim().length < 5) return;
    void perform({ sourceId, key: crypto.randomUUID(), before: { ...preview.before }, after: { ...preview.after }, payload: {
      action: preview.action, ...(preview.action === "edit_notes" ? { notes: preview.after.notes } : {}), expected_revision: preview.revision,
      expected_fingerprint: preview.fingerprint, operator: operator.trim(), reason: reason.trim(),
    } });
  }
  return <dialog ref={dialog} className="fact-review-dialog source-management-dialog" aria-labelledby="source-management-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">LOCAL WORKSPACE · SOURCE SETTINGS</span><h2 id="source-management-title">{record?.name || sourceId} · 来源管理</h2></div><button type="button" className="text-button" onClick={onClose}>关闭</button></header>
    <div className="fact-review-content"><p className="review-boundary">设置仅控制本机工作区的在线采集。历史证据、关注和监控规则继续保留；启用不能解除待配置、环境停用或 Parser 限制。署名为本地自报记录。</p>
      {error ? <p className="inline-error" role="alert">{error}</p> : null}{notice ? <p className="review-saved" role="status">{notice}</p> : null}
      {pending ? <section ref={pendingPanel} className="source-pending review-boundary"><strong>操作结果尚待核对</strong><p>固定 UUID：<code>{pending.key}</code>。关闭重开保留同一次请求；整页刷新后请先核对追加历史。</p><p>{actions[pending.payload.action]} · 基于修订 #{pending.payload.expected_revision} · {pending.payload.operator}</p><p>{pending.payload.reason}</p>{pending.payload.action === "edit_notes" ? <pre>{pending.payload.notes || "（清空备注）"}</pre> : null}<button type="button" className="primary-button" disabled={busy} onClick={() => void perform(pending)}>{busy ? "正在核对…" : "核对同一次来源操作"}</button></section> : null}
      <button type="button" className="secondary-button" disabled={locked || loading} onClick={() => { invalidate(); setReadVersion(value => value + 1); void access.refresh(); }}>重新读取来源与历史</button>
      {record ? <><SourceStatus source={record} /><p className="source-management-meta">当前修订 #{record.management.revision} · {stamp(record.management.changed_at)}{record.management.operator ? ` · ${record.management.operator}` : ""}</p><p>{record.management.reason}</p>
        <div className="review-form"><label><span>本次操作</span><select value={action} disabled={locked || loading} onChange={event => { invalidate(); setAction(event.target.value as SourceSettingAction); setNotes(record.management.notes); }}>{Object.entries(actions).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          {action === "edit_notes" ? <label><span>来源备注（可清空）</span><textarea value={notes} maxLength={2000} rows={3} disabled={locked || loading} onChange={event => { invalidate(); setNotes(event.target.value); }} /></label> : <p className="review-boundary">当前备注：{record.management.notes || "未填写"}。本次状态操作保留备注。</p>}
          <button type="button" className="secondary-button" disabled={locked || loading || previewing} onClick={() => void prepare()}>{previewing ? "正在预览…" : "预览本次变更"}</button>
        </div>
        {preview ? <section className="source-change-preview" aria-label="来源变更预览"><h3>{actions[preview.action]} · 修订 #{preview.revision} → #{preview.revision + 1}</h3><p>{sourceStateLabels[preview.before.state]} → {sourceStateLabels[preview.after.state]}</p>{preview.action === "edit_notes" ? <div><p>变更前备注：{preview.before.notes || "未填写"}</p><p>变更后备注：{preview.after.notes || "清空"}</p><p>备注变化不影响在途查询和有效授权。</p></div> : <p>状态变化会使旧的在途在线请求和待答授权失效；已完成的证据保留。</p>}<p>{preview.effective_after.can_fetch ? "变更后允许新的在线采集，实际可用性仍以请求结果为准。" : `变更后仍不能在线采集：${preview.effective_after.blockers.map(sourceBlockerText).join("；") || preview.effective_after.effective_status}`}</p>{preview.blockers.map(value => <p className="review-warning" key={value}>{sourceBlockerText(value)}</p>)}<p>{preview.notice}</p><div className="review-form"><label><span>本次操作署名（本地自报）</span><input maxLength={100} value={operator} disabled={locked} onChange={event => setOperator(event.target.value)} /></label><label><span>操作理由</span><textarea maxLength={2000} minLength={5} rows={2} value={reason} disabled={locked} onChange={event => setReason(event.target.value)} /></label><button type="button" className="primary-button" disabled={locked || !preview.can_submit || !operator.trim() || reason.trim().length < 5} onClick={submit}>保存本次来源操作</button></div></section> : null}
      </> : loading ? <p role="status">正在读取来源…</p> : null}
      <section className="source-setting-history" aria-label="来源操作追加历史"><h3>操作追加历史 · {history?.total ?? 0}</h3>{loading ? <p role="status">正在读取历史…</p> : history?.items.length ? history.items.map(event => <details key={event.id}><summary>#{event.revision} · {actions[event.action]} · {stamp(event.created_at)}</summary><p>{event.operator} · {event.reason}</p><p>{sourceStateLabels[event.before.state]} → {sourceStateLabels[event.after.state]}</p>{event.action === "edit_notes" ? <><p>原备注：{event.before.notes || "未填写"}</p><p>新备注：{event.after.notes || "清空"}</p></> : <p>保留备注：{event.notes || "未填写"}</p>}<p className="mono">UUID：{event.idempotency_key}</p></details>) : <p>尚无人工操作，使用来源默认设置。</p>}<div className="reparse-pages"><button type="button" className="text-button" disabled={loading || !offset} onClick={() => setOffset(value => Math.max(0, value - 10))}>上一页操作</button><span>第 {Math.floor(offset / 10) + 1} 页</span><button type="button" className="text-button" disabled={loading || !history || offset + history.items.length >= history.total} onClick={() => setOffset(value => value + 10)}>下一页操作</button></div></section>
    </div>
  </dialog>;
}

export default function SourceManagement() {
  const access = useSourceAccess(); const [editor, setEditor] = useState<string | null>(null); const [scope, setScope] = useState("active");
  const visible = access.items.filter(source => scope === "all" || (scope === "archived" ? source.management.state === "archived" : source.management.state !== "archived"));
  return <section className="sources-section source-management"><div className="panel-title"><span>原文来源管理</span><button type="button" className="text-button" disabled={access.loading} onClick={() => void access.refresh()}><Icon name="refresh" size={15} />刷新来源目录</button></div><p className="quality-intro">本机工作区 · {access.items.length} 个已登记来源。只管理在线采集状态与备注；官网、来源权威和 Parser 由登记合同提供。</p><div className="quarantine-filter"><label><span>来源范围</span><select value={scope} onChange={event => setScope(event.target.value)}><option value="active">未归档来源</option><option value="archived">已归档来源</option><option value="all">全部来源</option></select></label></div>
    {access.error ? <p className="inline-error" role="alert">{access.error} 暂停新的在线操作；历史证据仍可读取。</p> : null}{access.loading ? <p role="status">正在核对来源目录…</p> : null}
    {visible.map(source => <article className="source-directory-item" key={source.source_id}><div className="source-directory-head"><span className="source-monogram">{source.name.slice(0, 1)}</span><div><h3>{source.name}</h3><span>{source.region} · {source.target_kind === "vehicle" ? "车型原文" : source.target_kind === "recall" ? "召回公告" : "轮胎规格"} · {source.source_class}</span></div></div><SourceStatus source={source} /><p>{source.description}</p>{source.blockers.length ? <p className="source-access-notice">{source.blockers.map(sourceBlockerText).join("；")}</p> : null}<p className="source-management-notes">备注：{source.management.notes || "未填写"}</p>{source.supported_models.length ? <div className="source-supported-models"><span>已接入型号</span><ul>{source.supported_models.map(model => <li key={model}>{model}</li>)}</ul></div> : null}<div className="source-directory-footer"><code>{source.source_id}</code><button type="button" className="secondary-button compact" onClick={() => setEditor(source.source_id)}>管理与历史</button>{publicUrl(source.homepage) ? <a href={publicUrl(source.homepage)} target="_blank" rel="noopener noreferrer">访问官网<Icon name="external" size={14} /></a> : null}</div></article>)}
    {!access.loading && !visible.length ? <p className="quality-empty">当前范围没有来源。</p> : null}{editor ? <SourceSettingEditor key={editor} sourceId={editor} onClose={() => setEditor(null)} /> : null}
  </section>;
}
