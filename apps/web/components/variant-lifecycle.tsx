"use client";

import { useEffect, useRef, useState } from "react";
import type { Evidence, LifecycleReview } from "@tire/domain-types";
import { ApiError, tireApi } from "@tire/api-client";
import { IdentityContractEvidence } from "./identity-contract";
import { Icon } from "./icons";

const label = (state: string) => state === "revoked" ? "已撤销" : "未撤销";
const showTime = (value: string) => new Date(value).toLocaleString("zh-CN");
const errorText = (value: unknown) => value instanceof Error ? value.message : "操作未完成，请重试。";

export default function VariantLifecycleDialog({ variantId, onClose, onSaved, onIdentity }: {
  variantId: string; onClose: () => void; onSaved: (review: LifecycleReview) => void; onIdentity?: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const saveRequest = useRef<AbortController | null>(null);
  const evidenceRequest = useRef<AbortController | null>(null);
  const [review, setReview] = useState<LifecycleReview | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [stale, setStale] = useState(false);
  const [saving, setSaving] = useState(false);
  const [operator, setOperator] = useState("");
  const [reason, setReason] = useState("");
  const [locator, setLocator] = useState("");
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState("");

  useEffect(() => {
    const node = dialog.current;
    const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => {
      node?.close(); saveRequest.current?.abort(); evidenceRequest.current?.abort();
      if (focus?.isConnected) focus.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setReview(null); setError(""); setSaved(""); setStale(false); setReason(""); setLocator("");
    evidenceRequest.current?.abort(); setEvidence(null); setEvidenceLoading(false); setEvidenceError("");
    void tireApi.lifecycle(variantId, controller.signal).then(result => {
      if (!controller.signal.aborted) { setReview(result); onSaved(result); }
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [variantId, revision]);

  async function showEvidence(id: string) {
    evidenceRequest.current?.abort();
    const controller = new AbortController(); evidenceRequest.current = controller;
    setEvidence(null); setEvidenceError(""); setEvidenceLoading(true);
    try {
      const result = await tireApi.evidence(id, controller.signal);
      if (!controller.signal.aborted) setEvidence(result);
    } catch (cause) { if (!controller.signal.aborted) setEvidenceError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setEvidenceLoading(false); }
  }

  async function save() {
    if (!review?.provenance || saving || stale) return;
    const controller = new AbortController(); saveRequest.current = controller;
    const action = review.lifecycle.state === "revoked" ? "restore" : "revoke";
    setSaving(true); setError(""); setSaved("");
    try {
      const result = await tireApi.reviseLifecycle(variantId, { action, expected_revision: review.lifecycle.revision,
        operator: operator.trim(), reason: reason.trim(),
        evidence: [{ snapshot_id: review.provenance.snapshot_id, locator: locator.trim() }] }, controller.signal);
      if (!controller.signal.aborted) {
        setReview(result); onSaved(result); setReason(""); setLocator("");
        setSaved(action === "revoke" ? "已撤销此版本，原始身份、参数与证据均保留。" : "已恢复此版本，撤销历史仍然保留。");
      }
    } catch (cause) {
      if (!controller.signal.aborted) { setError(errorText(cause)); if (cause instanceof ApiError && cause.status === 409) setStale(true); }
    } finally { if (!controller.signal.aborted) setSaving(false); }
  }

  return <dialog ref={dialog} className="fact-review-dialog" aria-labelledby="lifecycle-title" onCancel={event => { event.preventDefault(); if (!saving) onClose(); }}>
    <div className="fact-review-heading"><div><small>LOCAL WORKSPACE</small><h2 id="lifecycle-title">精确版本的撤销与恢复</h2></div><button type="button" className="icon-button" disabled={saving} aria-label="关闭版本状态" onClick={onClose}><Icon name="close" size={20} /></button></div>
    <div className="fact-review-content">
      {onIdentity ? <button type="button" className="secondary-button" disabled={saving} onClick={onIdentity}>核对身份更正与合并</button> : null}
      <p className="review-warning">这是本地工作区的版本管理决定，不代表厂商停售或安全召回。撤销后仍保留官网查询和历史证据，但此版本不参与规格比较；新的官网响应不会自动恢复它。</p>
      {error ? <div className="inline-error" role="alert">{error}{!saving ? <button type="button" className="text-button" onClick={() => setRevision(value => value + 1)}>重新载入并核对</button> : null}</div> : null}
      {saved ? <p role="status">{saved}</p> : null}
      {!review ? !error ? <p role="status">正在读取版本状态…</p> : null : <>
        <div className="snapshot-banner"><strong>{String(review.identity.brand)} · {String(review.identity.model)} · {String(review.identity.size)}</strong><span>产品代码 {String(review.identity.manufacturer_product_code || "未知")} · {String(review.identity.region)} · {label(review.lifecycle.state)} · 修订 #{review.lifecycle.revision}</span></div>
        <IdentityContractEvidence contract={review.identity_contract} />
        {review.lifecycle.reason ? <p className="review-warning">上次原因：{review.lifecycle.reason}</p> : null}
        <form className="review-form" onSubmit={event => { event.preventDefault(); void save(); }}>
          <div className="review-evidence"><strong>本次引用：此精确版本的来源证据</strong><p>{review.provenance ? `观察时间 ${showTime(review.provenance.observed_at)}` : "暂无可引用的已采纳证据"}</p>{review.provenance ? <button type="button" className="secondary-button" onClick={() => void showEvidence(review.provenance!.snapshot_id)}>核对当前引用原文</button> : null}</div>
          <label><span>证据位置或原文摘录</span><textarea required minLength={3} maxLength={2000} disabled={saving} value={locator} onChange={event => setLocator(event.target.value)} /></label>
          <label><span>{review.lifecycle.state === "revoked" ? "恢复原因" : "撤销原因"}</span><textarea required minLength={5} maxLength={2000} disabled={saving} value={reason} onChange={event => setReason(event.target.value)} /></label>
          <label><span>处理人署名</span><input required maxLength={80} disabled={saving} value={operator} onChange={event => setOperator(event.target.value)} /><small>本地自报署名，尚未接入生产身份认证。</small></label>
          <button type="submit" className="primary-button" disabled={saving || stale || !review.provenance}>{saving ? "正在保存状态…" : review.lifecycle.state === "revoked" ? "恢复此版本" : "撤销此版本"}</button>
        </form>
        <section className="review-history" aria-label="版本状态历史"><h3>版本状态历史</h3>{review.history_truncated ? <p>显示最近 200 条，完整记录仍保留。</p> : null}{review.history.length ? review.history.map(row => <details key={row.id}><summary>#{row.revision} · {label(row.before_state)} → {label(row.after_state)}</summary><dl><div><dt>署名与时间</dt><dd>{row.operator} · {showTime(row.created_at)}</dd></div><div><dt>原因</dt><dd>{row.reason}</dd></div></dl>{row.evidence.map(item => <blockquote key={item.snapshot_id}>{item.locator}<small>SHA-256 {item.raw_hash}</small><button type="button" className="text-button" onClick={() => void showEvidence(item.snapshot_id)}>核对此次处理的原文</button></blockquote>)}</details>) : <p>此版本尚无撤销或恢复记录。</p>}</section>
      </>}
      {evidenceLoading ? <p role="status">正在读取证据原文…</p> : evidenceError ? <p role="alert">{evidenceError}</p> : evidence ? <details className="raw-evidence" open><summary>引用的历史原文 · LOCAL SNAPSHOT</summary><p className="hash-value">SHA-256 {evidence.raw_hash}</p><pre>{evidence.body}</pre></details> : null}
    </div>
  </dialog>;
}
