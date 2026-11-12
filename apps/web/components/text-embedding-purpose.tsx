"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { TextEmbeddingAuthorizationPreview, TextEmbeddingSelection, TextUseAuthorizationPreview, TextUsePurpose } from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";

const states = { missing: "尚未授权", granted: "已授权", revoked: "已撤销", expired: "已到期" };
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "正文用途操作未完成。";

type Purpose = "embedding" | TextUsePurpose;
const purposeLabels: Record<Purpose, string> = { embedding: "正文向量用途", "original_text_ai@1": "正文 AI 分析用途", "original_text_report_export@1": "正文报告导出用途" };

function PurposeDialog({ selection, purpose, onPurposeChange, onClose, isAdmin, ownerSignal }: {
  selection: TextEmbeddingSelection; purpose: Purpose; onPurposeChange: (purpose: Purpose) => void;
  onClose: () => void; isAdmin: boolean; ownerSignal: AbortSignal;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const operation = useRef<AbortController | null>(null);
  const [preview, setPreview] = useState<TextEmbeddingAuthorizationPreview | TextUseAuthorizationPreview | null>(null);
  const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState<"read" | "grant" | "revoke" | null>("read");
  const [basis, setBasis] = useState("");
  const [privacy, setPrivacy] = useState<"" | "public" | "private">("");
  const [expires, setExpires] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [revokeAcknowledged, setRevokeAcknowledged] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (operation.current || ownerSignal.aborted) return;
    const controller = new AbortController();
    operation.current = controller;
    setBusy("read"); setError(""); setNotice(""); setVerified(false);
    setAcknowledged(false); setRevokeAcknowledged(false);
    try {
      const signal = AbortSignal.any([controller.signal, ownerSignal]);
      const value = purpose === "embedding" ? await tireApi.textEmbeddingAuthorizationPreview(selection, signal)
        : await tireApi.textUseAuthorizationPreview(selection, purpose, signal);
      if (controller.signal.aborted || ownerSignal.aborted || operation.current !== controller) return;
      setPreview(value); setVerified(true);
    } catch (cause) {
      if (!controller.signal.aborted && !ownerSignal.aborted && operation.current === controller) setError(errorText(cause));
    } finally {
      if (operation.current === controller) { operation.current = null; setBusy(null); }
    }
  }

  useEffect(() => {
    const node = dialog.current;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    void load();
    return () => {
      operation.current?.abort(); operation.current = null; node?.close();
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
    // The owner-keyed wrapper remounts this dialog when identity changes.
  }, []);

  async function authorize(action: "grant" | "revoke") {
    if (operation.current || ownerSignal.aborted || !isAdmin || !preview) return;
    if (action === "grant" && (!verified || !acknowledged || !basis.trim() || !privacy)) return;
    if (action === "revoke" && (!revokeAcknowledged || preview.authorization.revision === 0)) return;
    let expiresAt: string | null = null;
    if (action === "grant" && expires) {
      const date = new Date(expires);
      if (!Number.isFinite(date.getTime()) || date.getTime() <= Date.now()) {
        setError("用途许可到期时间须晚于当前时间。"); return;
      }
      expiresAt = date.toISOString();
    }
    const controller = new AbortController();
    operation.current = controller;
    setBusy(action); setError(""); setNotice("");
    try {
      const payload = {
        selection, scope_hash: preview.scope_hash, expected_revision: preview.authorization.revision,
        action, rights_basis: action === "grant" ? basis.trim() : `管理员撤销${purposeLabels[purpose]}`,
        privacy_class: privacy || "private" as const, expires_at: expiresAt, acknowledged: true,
      };
      const signal = AbortSignal.any([controller.signal, ownerSignal]);
      const value = purpose === "embedding" ? await tireApi.authorizeTextEmbedding(payload, signal)
        : await tireApi.authorizeTextUse({ ...payload, purpose }, signal);
      if (controller.signal.aborted || ownerSignal.aborted || operation.current !== controller) return;
      setPreview({ ...preview, authorization: value.authorization, scope_hash: value.scope_hash });
      setNotice(action === "grant" ? "已登记所选用途授权。执行时会重新核对原件及许可。" : "已登记撤销，已发生的调用用量保留在账本中。");
    } catch (cause) {
      if (controller.signal.aborted || ownerSignal.aborted || operation.current !== controller) return;
      setVerified(false); setError(errorText(cause));
      setNotice("请重新读取用途状态，核对本次提交结果和最新修订。");
    } finally {
      if (operation.current === controller) {
        operation.current = null; setBusy(null); setAcknowledged(false); setRevokeAcknowledged(false);
      }
    }
  }

  function stopWaiting() {
    operation.current?.abort(); operation.current = null;
    setVerified(false); setBusy(null); setAcknowledged(false); setRevokeAcknowledged(false);
    setNotice("已停止等待。请重新读取用途状态，核对最新授权修订及已提交操作的结果。");
  }

  const reference = selection.reference;
  return <dialog ref={dialog} className="fact-review-dialog vector-dialog" aria-labelledby="text-purpose-title" onCancel={event => {
    event.preventDefault(); event.stopPropagation(); onClose();
  }}>
    <header className="fact-review-heading"><h2 id="text-purpose-title">{purposeLabels[purpose]}</h2><button type="button" className="icon-button" aria-label="关闭正文用途" onClick={onClose}>×</button></header>
    <div className="ai-content vector-content">
      <label>正文用途<select value={purpose} onChange={event => onPurposeChange(event.target.value as Purpose)}><option value="embedding">建立正文向量</option><option value="original_text_ai@1">AI 分析</option><option value="original_text_report_export@1">研究报告导出</option></select></label>
      <dl className="quality-detail-meta"><div><dt>{selection.kind === "document_text" ? "文档 ID" : "快照 ID"}</dt><dd>{selection.kind === "document_text" ? selection.reference.document_id : selection.reference.snapshot_id}</dd></div>
        {selection.kind === "document_text" ? <div><dt>文档页码</dt><dd>第 {selection.reference.page} 页</dd></div> : null}
        <div><dt>原件 SHA256</dt><dd className="mono">{reference.raw_hash}</dd></div>
        <div><dt>抽取版本</dt><dd>{reference.extractor_version}</dd></div>
        <div><dt>Unicode码点区间</dt><dd>[{reference.start}, {reference.end})</dd></div></dl>
      <div className="knowledge-form-actions"><button type="button" className="secondary-button" disabled={!!busy || ownerSignal.aborted} onClick={() => void load()}>重新读取用途状态</button>
        {busy ? <button type="button" className="text-button" onClick={stopWaiting}>停止等待用途操作</button> : null}</div>
      <p role="status" aria-live="polite">{busy === "read" ? "正在本地核对原件、接收端与用途修订…" : busy ? "正在登记用途修订…" : notice}</p>
      {error ? <p className="inline-error" role="alert">{error}</p> : null}
      {preview ? <><p><strong>{states[preview.authorization.state]} · 修订 {preview.authorization.revision}</strong></p>
        <dl className="quality-detail-meta"><div><dt>接收端</dt><dd className="mono">{"endpoint" in preview.recipient ? preview.recipient.endpoint : "研究报告文件下载（Markdown／HTML／PDF）"}</dd></div>
          <div><dt>正文 SHA256</dt><dd className="mono">{preview.text_hash}</dd></div></dl>
        <section className="vector-plan-document" aria-label="用途授权原文"><h3>原件恢复的正文</h3><pre>{preview.text}</pre></section>
        <p className="review-boundary">{preview.notice}</p>
        {isAdmin ? <><form className="review-form" onSubmit={event => { event.preventDefault(); void authorize("grant"); }}>
          <label>用途依据<textarea required maxLength={1000} value={basis} disabled={!!busy} onChange={event => { setBasis(event.target.value); setAcknowledged(false); }} /></label>
          <label>正文公开性<select required value={privacy} disabled={!!busy} onChange={event => { setPrivacy(event.target.value as typeof privacy); setAcknowledged(false); }}><option value="">请选择</option><option value="public">公开材料</option><option value="private">非公开工作区材料</option></select></label>
          <label>用途到期时间（可选，按本地时间填写）<input type="datetime-local" value={expires} disabled={!!busy} onChange={event => { setExpires(event.target.value); setAcknowledged(false); }} /></label>
          <label className="review-checkbox"><input type="checkbox" checked={acknowledged} disabled={!!busy || !verified} onChange={event => setAcknowledged(event.target.checked)} />{purpose === "original_text_report_export@1" ? "我确认上述依据允许将此段正文作为研究报告文件导出。" : purpose === "original_text_ai@1" ? "我确认上述依据允许将此段正文交给所示接收端进行 AI 分析。" : "我确认上述依据允许将此段正文交给所示接收端建立向量。"}</label>
          <button type="submit" className="primary-button" disabled={!!busy || !verified || !acknowledged || !privacy || !basis.trim() || ownerSignal.aborted}>登记用途授权</button>
        </form>
          {preview.authorization.revision > 0 && preview.authorization.state !== "revoked" ? <section className="vector-plan-document" aria-label="撤销正文用途"><label className="review-checkbox"><input type="checkbox" checked={revokeAcknowledged} disabled={!!busy} onChange={event => setRevokeAcknowledged(event.target.checked)} />我确认撤销此引用当前选择的用途授权。</label><button type="button" className="secondary-button" disabled={!!busy || !revokeAcknowledged || ownerSignal.aborted} onClick={() => void authorize("revoke")}>撤销用途授权</button></section> : null}
        </> : <p>管理员可登记和撤销此接收端的正文用途许可。</p>}
      </> : null}
    </div>
  </dialog>;
}

export default function TextEmbeddingPurposeDialog({ selection, onClose }: {
  selection: TextEmbeddingSelection; onClose: () => void;
}) {
  const auth = useWorkbenchAuth();
  const [purpose, setPurpose] = useState<Purpose>("embedding");
  return <PurposeDialog key={`${auth.ownerEpoch}:${purpose}`} selection={selection} purpose={purpose} onPurposeChange={setPurpose} onClose={onClose}
    isAdmin={auth.ready && !!auth.state.user?.is_admin} ownerSignal={auth.ownerSignal} />;
}
