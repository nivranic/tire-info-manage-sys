"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { IdentityMigrationApplication, IdentityMigrationApply, IdentityMigrationAssessment,
  IdentityMigrationPreview, IdentityMigrationSummary, IdentityReview, ParserPage } from "@tire/domain-types";
import { DataTree } from "./reparse-review";
import { IdentityContractEvidence, identityReasonLabel } from "./identity-contract";
import { useWorkbenchAuth } from "./auth";

type Attempt = { key: string; payload: IdentityMigrationApply };
// One fixed write per tab, retained across dialog closes; no private payload in browser storage.
let pendingAttempt: Attempt | null = null;
const stamp = (value: string) => new Date(value).toLocaleString("zh-CN");
const labels = { eligible: "证据充分 · 可追加绑定", needs_review: "需要人工核对 · 本次不绑定", already_bound: "已经绑定" };
const errorText = (cause: unknown) => cause instanceof ApiError && cause.code
  ? `操作未完成（${cause.code}）。请核对迁移历史并重新读取预览。`
  : cause instanceof Error ? cause.message : "操作未完成，请核对记录。";
const valueText = (value: unknown) => typeof value === "string" && value.trim() ? value : "未确认";

function Summary({ value }: { value: IdentityMigrationSummary }) {
  return <dl className="identity-migration-summary">
    <div><dt>旧身份记录</dt><dd>{value.legacy_total}</dd></div><div><dt>可安全追加绑定</dt><dd>{value.eligible}</dd></div>
    <div><dt>需要核对</dt><dd>{value.needs_review}</dd></div><div><dt>已经绑定</dt><dd>{value.already_bound}</dd></div>
    <div><dt>需注意的旧关注</dt><dd>{value.watch_risk_count}</dd></div><div><dt>需注意的监控规则</dt><dd>{value.rule_risk_count}</dd></div>
  </dl>;
}

function Assessment({ item, disabled, onRead }: { item: IdentityMigrationAssessment; disabled: boolean; onRead: (id: string) => void }) {
  return <article className="identity-migration-item"><div className="panel-title"><strong>{labels[item.state]}</strong><button type="button" className="text-button" disabled={disabled} onClick={() => onRead(item.variant_id)}>核对原始身份</button></div>
    <p>旧 SKU <code>{item.variant_id}</code></p>
    {item.current_identity ? <p>预览身份：{valueText(item.current_identity.brand)} {valueText(item.current_identity.model)} · {valueText(item.current_identity.size)} · {valueText(item.current_identity.product_code_type)} <code>{valueText(item.current_identity.manufacturer_product_code)}</code></p> : <p>现有证据不足以确定命名空间，不推定为同一 SKU。</p>}
    <p>关联旧关注 {item.affected_watch_count} 条 · 监控规则 {item.affected_rule_count} 条</p>
    {item.reason_codes.length ? <p>原因：{item.reason_codes.map(identityReasonLabel).join("；")}</p> : null}<DataTree label="此项证据判定与指纹" value={item} />
  </article>;
}

function MigrationDialog({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const operation = useRef<AbortController | null>(null);
  const originalRequest = useRef<AbortController | null>(null);
  const auth = useWorkbenchAuth();
  // 会话未就绪（ready=false，如首帧或桌面宿主未注入）时不禁用，避免误伤只读浏览。
  const adminBlocked = auth.ready && (!auth.state.authenticated || !auth.state.user?.is_admin);
  const [refresh, setRefresh] = useState(0);
  const [preview, setPreview] = useState<IdentityMigrationPreview | null>(null);
  const [filter, setFilter] = useState<"all" | IdentityMigrationAssessment["state"]>("all");
  const [itemOffset, setItemOffset] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [history, setHistory] = useState<ParserPage<IdentityMigrationApplication> | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [detailRevision, setDetailRevision] = useState(0);
  const [application, setApplication] = useState<IdentityMigrationApplication | null>(null);
  const [original, setOriginal] = useState<IdentityReview | null>(null);
  const [originalLoading, setOriginalLoading] = useState(false);
  const [operator, setOperator] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState<Attempt | null>(pendingAttempt);
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState("");
  const locked = busy || !!pending;
  const items = preview?.items.filter(item => filter === "all" || item.state === filter) || [];
  const offset = Math.min(itemOffset, Math.max(0, Math.floor((items.length - 1) / 10) * 10));
  function error(key: string, value = "") { setErrors(current => ({ ...current, [key]: value })); }
  function remember(value: Attempt | null) { pendingAttempt = value; setPending(value); }
  function reload() { originalRequest.current?.abort(); setOriginal(null); setOriginalLoading(false); setConfirmed(false); setRefresh(value => value + 1); setDetailRevision(value => value + 1); }
  useEffect(() => {
    const node = dialog.current; const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal(); return () => { operation.current?.abort(); originalRequest.current?.abort(); node?.close(); if (focus?.isConnected) focus.focus({ preventScroll: true }); };
  }, []);
  useEffect(() => {
    const controller = new AbortController(); setPreview(null); setConfirmed(false); error("preview");
    void tireApi.identityMigrationPreview(controller.signal).then(value => {
      if (!controller.signal.aborted) {
        if (value.schema !== "variant-identity@2" || value.scope !== "local_workspace" || !value.preview_fingerprint) throw new Error("预览身份合同或范围不匹配，未展示。");
        setPreview(value); setStale(false);
      }
    }).catch(cause => { if (!controller.signal.aborted) error("preview", errorText(cause)); });
    return () => controller.abort();
  }, [refresh]);
  useEffect(() => {
    const controller = new AbortController(); setHistory(null); error("history");
    void tireApi.identityMigrationApplications(historyOffset, controller.signal).then(value => { if (!controller.signal.aborted) setHistory(value); })
      .catch(cause => { if (!controller.signal.aborted) error("history", errorText(cause)); });
    return () => controller.abort();
  }, [refresh, historyOffset]);
  useEffect(() => {
    setApplication(null); error("application");
    if (!selectedId) return;
    const controller = new AbortController();
    void tireApi.identityMigrationApplication(selectedId, controller.signal).then(value => {
      if (!controller.signal.aborted) { if (value.id !== selectedId) throw new Error("迁移历史 ID 不匹配，未展示。"); setApplication(value); }
    }).catch(cause => { if (!controller.signal.aborted) error("application", errorText(cause)); });
    return () => controller.abort();
  }, [selectedId, detailRevision]);
  useEffect(() => { setConfirmed(false); }, [operator, reason, preview?.preview_fingerprint]);

  async function readOriginal(id: string) {
    originalRequest.current?.abort(); const controller = new AbortController(); originalRequest.current = controller;
    setOriginal(null); setOriginalLoading(true); error("original");
    try {
      const value = await tireApi.identityReview(id, controller.signal);
      if (!controller.signal.aborted) { if (value.source.id !== id) throw new Error("原始身份范围不匹配，未展示。"); setOriginal(value); }
    } catch (cause) { if (!controller.signal.aborted) error("original", errorText(cause)); }
    finally { if (!controller.signal.aborted) setOriginalLoading(false); }
  }
  async function perform(attempt: Attempt) {
    if (operation.current) return;
    const controller = new AbortController(); operation.current = controller; remember(attempt); setBusy(true); error("apply"); setNotice("");
    try {
      const value = await tireApi.applyIdentityMigration(attempt.payload, attempt.key, controller.signal);
      if (controller.signal.aborted) return;
      if (value.schema !== attempt.payload.schema || value.preview_fingerprint !== attempt.payload.expected_preview_fingerprint
        || value.revision !== attempt.payload.expected_revision + 1 || value.current_revision < value.revision) throw new Error("应用回执与固定预览不匹配，请保留请求标识核对历史。");
      remember(null); setSelectedId(value.id); setApplication(value); setHistoryOffset(0); setConfirmed(false); setReason("");
      originalRequest.current?.abort(); setOriginal(null); setOriginalLoading(false);
      setNotice(`已核对迁移应用 #${value.revision}，追加 ${value.binding_ids.length} 条绑定。${value.idempotent_replay ? "本次返回同一原事件，没有重复应用。" : ""}${value.current_revision > value.revision ? `当前迁移已到 #${value.current_revision}，下方记录仍保留本次原事件。` : ""}旧 SKU、快照和引用未改写；正在重新读取当前预览。`);
      setRefresh(current => current + 1);
    } catch (cause) {
      if (!controller.signal.aborted) {
        error("apply", errorText(cause)); setConfirmed(false);
        if (cause instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(cause.status) && cause.code !== "idempotency_payload_mismatch") {
          remember(null); setStale(true);
        }
      }
    } finally { if (operation.current === controller) operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  function apply() {
    if (!preview || locked || stale || !confirmed || !operator.trim() || !reason.trim() || !preview.can_apply) return;
    void perform({ key: crypto.randomUUID(), payload: { mode: "history", schema: preview.schema,
      expected_revision: preview.revision, expected_preview_fingerprint: preview.preview_fingerprint,
      acknowledged: true, operator: operator.trim(), reason: reason.trim() } });
  }

  return <dialog ref={dialog} className="fact-review-dialog reports-dialog identity-migration-dialog" aria-labelledby="identity-migration-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">SKU IDENTITY CONTRACT</span><h2 id="identity-migration-title">旧 SKU 身份迁移</h2></div><button type="button" className="icon-button" aria-label="关闭身份迁移" onClick={onClose}>×</button></header>
    <div className="reports-content parser-release-content"><div className="snapshot-banner"><strong>本机工作区 · 追加权威身份绑定</strong><span>先依据已有证据预览，再明确应用。旧 UUID、原身份、快照、关注与引用继续保留；不会访问官网、自动合并或把待核对记录指向候选。</span></div>
      <div className="parser-release-toolbar"><p>编码字面值相同不等于同一 SKU；CAI、MSPN、EAN 等类型必须分别核对。</p><button type="button" className="secondary-button" disabled={locked} onClick={reload}>重新读取迁移预览与历史</button></div>
      {Object.entries(errors).filter(([, value]) => value).map(([key, value]) => <p key={key} className="inline-error" role="alert">{value}</p>)}{notice ? <p className="review-saved" role="status">{notice}</p> : null}
      {pending ? <section className="review-boundary"><strong>应用结果待核对，保留同一次请求</strong><p>固定 UUID <code>{pending.key}</code>。关闭重开仍保留；整页刷新后先核对应用历史。</p><DataTree label="待核对的固定应用请求" value={pending.payload} /><button type="button" className="primary-button" disabled={busy} onClick={() => void perform(pending)}>核对同一次迁移应用</button></section> : null}
      <section><h3>1 · 当前迁移预览</h3>{preview ? <><Summary value={preview.summary} /><p>迁移修订 #{preview.revision} · 合同 {preview.schema}</p><p>预览指纹 <code>{preview.preview_fingerprint}</code></p><DataTree label="当前规则摘要" value={{ schema: preview.schema, contract_digest: preview.contract_digest, notice: preview.notice }} />
        {preview.summary.watch_risk_count || preview.summary.rule_risk_count ? <p className="review-warning">旧关注／监控存在待核对身份。它们继续引用原 SKU，不会跟随新候选；请分别核对，避免误以为已经监测到新身份的变化。</p> : null}
        <label className="golden-field"><span>筛选预览记录（不改变应用范围）</span><select value={filter} disabled={busy} onChange={event => { setFilter(event.target.value as typeof filter); setItemOffset(0); }}><option value="all">全部</option><option value="eligible">可追加绑定</option><option value="needs_review">需要核对</option><option value="already_bound">已经绑定</option></select></label>
        <div>{items.slice(offset, offset + 10).map(item => <Assessment key={item.variant_id} item={item} disabled={busy} onRead={id => void readOriginal(id)} />)}</div>{!items.length ? <p>当前筛选没有记录。</p> : null}
        <div className="reparse-pages"><button type="button" className="text-button" disabled={busy || !offset} onClick={() => setItemOffset(offset - 10)}>上一页预览</button><span>共 {items.length} 条 · 第 {Math.floor(offset / 10) + 1} 页</span><button type="button" className="text-button" disabled={busy || offset + 10 >= items.length} onClick={() => setItemOffset(offset + 10)}>下一页预览</button></div>
      </> : !errors.preview ? <p role="status">正在读取本机已有证据的迁移预览…</p> : null}</section>
      {originalLoading ? <p role="status">正在读取所选旧身份…</p> : original ? <section><h3>所选 SKU 的原始记录</h3><p><code>{original.source.id}</code> · 原身份状态 {original.source.identity_status}</p><DataTree label="旧身份原貌与原事实引用（未改写）" value={original.source} /><IdentityContractEvidence contract={original.source.identity_contract} /></section> : null}
      <section><h3>2 · 明确应用本次预览</h3><p>只为预览中证据充分的 {preview?.summary.eligible ?? "未读取"} 条旧 SKU 追加绑定；同时记录待核对判定。{preview?.summary.needs_review ?? "未读取"} 条待核对记录继续保留，不会借此合并或改写历史。</p>{preview && !preview.can_apply ? <p>当前预览没有可追加的安全绑定或新的待核对判定；已有应用可在下方查看。</p> : null}
        {stale ? <p className="inline-error">当前预览已失效或提交被拒绝。重新读取预览后再核对，不能沿用旧确认。</p> : null}
        <form className="review-form" onSubmit={event => { event.preventDefault(); apply(); }}><label><span>迁移署名（本地自报）</span><input maxLength={100} value={operator} disabled={locked} onChange={event => setOperator(event.target.value)} /></label><label><span>迁移理由</span><textarea rows={3} maxLength={2000} value={reason} disabled={locked} onChange={event => setReason(event.target.value)} /></label>
          <label className="review-checkbox"><input type="checkbox" checked={confirmed} disabled={locked || stale || !preview} onChange={event => setConfirmed(event.target.checked)} /><span>已核对整个预览的可绑定项、待核对项及旧关注／监控风险；确认按上述指纹追加绑定，不自动改变任何旧引用或关联候选。</span></label>
          <button type="submit" className="primary-button" disabled={adminBlocked || locked || stale || !preview?.can_apply || !confirmed || !operator.trim() || !reason.trim()} title={adminBlocked ? "需要管理员账户" : undefined}>应用已核对的迁移预览</button>
        </form>
      </section>
      <section><h3>3 · 迁移应用历史</h3><div className="parser-bundle-options">{history?.items.map(item => <button type="button" className={`report-list-item${selectedId === item.id ? " selected" : ""}`} key={item.id} disabled={busy} aria-pressed={selectedId === item.id} onClick={() => { setSelectedId(item.id); setDetailRevision(value => value + 1); }}><strong>迁移 #{item.revision} · {item.operator}</strong><span>{stamp(item.created_at)}</span><small>{item.binding_ids.length} 条绑定 · {item.summary.needs_review} 条待核对</small></button>)}</div>{history?.total === 0 ? <p>还没有迁移应用记录。读取预览不会产生应用。</p> : null}
        <div className="reparse-pages"><button type="button" className="text-button" disabled={busy || !history || historyOffset === 0} onClick={() => setHistoryOffset(value => Math.max(0, value - 10))}>上一页应用</button><span>共 {history?.total ?? "未读取"} 条 · 第 {Math.floor(historyOffset / 10) + 1} 页</span><button type="button" className="text-button" disabled={busy || !history || historyOffset + 10 >= history.total} onClick={() => setHistoryOffset(value => value + 10)}>下一页应用</button></div>
        {application ? <article className="review-boundary"><h4>固定应用 #{application.revision}</h4><p>{stamp(application.created_at)} · {application.operator}（本地自报）</p><p className="draft-original">{application.reason}</p><p>以下为应用时的判定；当前状态请读取上方最新预览。原事件不会随新证据改写。</p><Summary value={application.summary} /><DataTree label="完整应用回执、判定与绑定ID" value={application} /></article> : selectedId && !errors.application ? <p role="status">正在读取所选应用…</p> : null}
      </section>
    </div>
  </dialog>;
}

export default function IdentityMigration({ sessionReady }: { sessionReady: boolean }) {
  const [opened, setOpened] = useState(false);
  return <section className="report-entry panel"><div><span className="eyebrow">SKU IDENTITY CONTRACT</span><h3>旧 SKU 身份迁移</h3><p>预览编码类型证据、待核对项和旧关注风险，再署名追加身份绑定。</p></div><button type="button" className="secondary-button" disabled={!sessionReady} onClick={() => setOpened(true)}>预览身份迁移</button>{opened ? <MigrationDialog onClose={() => setOpened(false)} /> : null}</section>;
}
