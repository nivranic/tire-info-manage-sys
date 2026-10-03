"use client";

import { useEffect, useRef, useState } from "react";
import type { Evidence, FactReview, FieldValue, RevisionAction, Variant } from "@tire/domain-types";
import { ApiError, tireApi } from "@tire/api-client";
import { IdentityContractBadge } from "./identity-contract";
import { Icon } from "./icons";

const actions: Record<RevisionAction, string> = { manual_override: "新增 / 修改人工值", revoke: "撤销此参数", clear_override: "撤回人工处理，恢复来源值" };
const states: Record<string, string> = { manual_override: "人工纠错", revoked: "已撤销", cleared: "沿用来源", needs_review: "来源已更新 · 需要复核" };
const showValue = (value: unknown): string => value === null || value === undefined ? "未知" : typeof value === "boolean" ? value ? "是" : "否" : typeof value === "object" ? JSON.stringify(value) : String(value);
const showField = (value: FieldValue) => value.present ? showValue(value.value) : "未列出 / 已撤销";
const showTime = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "尚未结束";

export type FactReviewVariant = Pick<Variant, "id" | "model" | "size" | "region" | "manufacturer_product_code" | "snapshot_id" | "source_id" | "identity_contract">;

export default function FactReviewDialog({ variant, sourceId, initialField, onClose, onSaved }: { variant: FactReviewVariant; sourceId?: string; initialField?: string; onClose: () => void; onSaved: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const saveController = useRef<AbortController | null>(null);
  const evidenceController = useRef<AbortController | null>(null);
  const [review, setReview] = useState<FactReview | null>(null);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [stale, setStale] = useState(false);
  const [saving, setSaving] = useState(false);
  const [field, setField] = useState("");
  const [action, setAction] = useState<RevisionAction>("manual_override");
  const [value, setValue] = useState("");
  const [unknown, setUnknown] = useState(false);
  const [unit, setUnit] = useState("mm");
  const [operator, setOperator] = useState("");
  const [reason, setReason] = useState("");
  const [locator, setLocator] = useState("");
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState("");
  const [historyEvidenceId, setHistoryEvidenceId] = useState("");
  const [historyEvidence, setHistoryEvidence] = useState<Evidence | null>(null);
  const [historyEvidenceError, setHistoryEvidenceError] = useState("");
  const historyController = useRef<AbortController | null>(null);

  useEffect(() => {
    const node = dialog.current;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => {
      node?.close(); saveController.current?.abort(); evidenceController.current?.abort(); historyController.current?.abort();
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    evidenceController.current?.abort(); setEvidence(null); setEvidenceError(""); setEvidenceLoading(false);
    historyController.current?.abort(); setHistoryEvidenceId(""); setHistoryEvidence(null); setHistoryEvidenceError("");
    setLocator(""); setReason("");
    setReview(null); setError(""); setSaved(""); setStale(false);
    void (async () => {
      const source = sourceId || variant.source_id || (await tireApi.evidence(variant.snapshot_id, controller.signal)).source_id;
      const result = await tireApi.factReview(variant.id, source, controller.signal);
      if (controller.signal.aborted) return;
      if (initialField && !result.field_catalog[initialField]) throw new Error("此字段不支持来源内人工纠错，请返回核对字段依据或使用身份核对。");
      setReview(result);
      setField(previous => initialField || (previous && result.field_catalog[previous] ? previous : Object.keys(result.field_catalog).find(key => key in result.source_facts) || Object.keys(result.field_catalog)[0]));
    })().catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "核验记录读取失败"); });
    return () => controller.abort();
  }, [variant.id, variant.snapshot_id, variant.source_id, sourceId, initialField, reload]);

  useEffect(() => {
    const current = review?.effective_facts[field];
    setUnknown(current === null || current === undefined);
    if (current && typeof current === "object" && "value" in current) {
      setValue(String(current.value ?? ""));
      const originalUnit = "unit" in current ? String(current.unit) : "";
      setUnit(review?.field_catalog[field]?.units?.includes(originalUnit) ? originalUnit : "");
    } else setValue(current === undefined || current === null ? "" : String(current));
  }, [field, review]);

  async function showEvidence() {
    if (!review) return;
    evidenceController.current?.abort();
    const controller = new AbortController(); evidenceController.current = controller;
    setEvidenceLoading(true); setEvidenceError("");
    try { const result = await tireApi.evidence(review.provenance.snapshot_id, controller.signal); if (!controller.signal.aborted) setEvidence(result); }
    catch (cause) { if (!controller.signal.aborted) setEvidenceError(cause instanceof Error ? cause.message : "原文读取失败"); }
    finally { if (!controller.signal.aborted) setEvidenceLoading(false); }
  }

  async function showHistoryEvidence(snapshotId: string) {
    historyController.current?.abort();
    const controller = new AbortController(); historyController.current = controller;
    setHistoryEvidenceId(snapshotId); setHistoryEvidence(null); setHistoryEvidenceError("");
    try {
      const result = await tireApi.evidence(snapshotId, controller.signal);
      if (!controller.signal.aborted) setHistoryEvidence(result);
    } catch (cause) { if (!controller.signal.aborted) setHistoryEvidenceError(cause instanceof Error ? cause.message : "历史原文读取失败，请重试"); }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!review || saving || stale) return;
    const definition = review.field_catalog[field];
    if (!definition) return;
    let parsed: unknown = null;
    if (action === "manual_override" && !unknown) {
      if (definition.type === "number" || definition.type === "measurement") {
        const number = Number(value);
        if (!value.trim() || !Number.isFinite(number) || number < 0) { setError("请输入有效的非负数值。"); return; }
        if (definition.type === "measurement" && !definition.units?.includes(unit)) { setError("请选择已核对的参数单位。"); return; }
        parsed = definition.type === "measurement" ? { value: number, unit } : number;
      } else if (definition.type === "boolean") parsed = value === "true";
      else parsed = value.trim();
    }
    const controller = new AbortController(); saveController.current = controller;
    setSaving(true); setError(""); setSaved("");
    try {
      const result = await tireApi.reviseFact(variant.id, {
        source_id: review.source_id, base_fact_id: review.base_fact_id, expected_revision: review.revision,
        field, action, ...(action === "manual_override" ? { value: parsed } : {}), operator, reason,
        evidence: [{ snapshot_id: review.provenance.snapshot_id, locator }],
      }, controller.signal);
      if (controller.signal.aborted) return;
      setReview(result); setReason(""); setLocator(""); setSaved(`人工修订已保存，当前修订序号为 ${result.revision}。来源原文与原始参数保留。`); onSaved();
    } catch (cause) {
      if (!controller.signal.aborted) { setError(cause instanceof Error ? cause.message : "提交结果未确认，请重新载入核对。"); if (cause instanceof ApiError && cause.status === 409) setStale(true); }
    } finally { if (!controller.signal.aborted) setSaving(false); }
  }

  const definition = review?.field_catalog[field];
  const active = review?.fields[field];
  const raw = review ? { present: field in review.source_facts, value: review.source_facts[field] } : null;
  const effective = review ? { present: field in review.effective_facts, value: review.effective_facts[field] } : null;
  return <dialog ref={dialog} className="fact-review-dialog" aria-labelledby="fact-review-title" onCancel={event => { event.preventDefault(); if (!saving) onClose(); }}>
    <div className="fact-review-heading"><div><span className="eyebrow">LOCAL SNAPSHOT · 人工核验</span><h2 id="fact-review-title">核验与纠错</h2><p>{variant.model} · {variant.size} · {variant.region} · {variant.manufacturer_product_code || "无产品代码"}</p><IdentityContractBadge contract={review?.identity_contract || variant.identity_contract} /></div><button type="button" className="icon-button" aria-label="关闭核验窗口" disabled={saving} onClick={onClose}><Icon name="close" size={20} /></button></div>
    <div className="fact-review-content">
      <p className="review-boundary">人工处理只用于核验视图和主动选择的历史比较。普通在线查询与授权快照保留来源值。来源事实更新后，旧处理需要重新核对。</p>
      {error ? <div className="inline-error" role="alert">{error}<button className="text-button" type="button" disabled={saving} onClick={() => setReload(n => n + 1)}>重新载入核对</button></div> : null}
      {saved ? <p className="review-saved" role="status">{saved}</p> : null}
      {!review ? !error ? <div className="run-loading" role="status"><span className="spinner" />正在读取历史事实和修订…</div> : null : <>
        <div className="review-baseline"><span>来源 {review.source_id} · 事实版本 {review.fact_version} · 人工修订 {review.revision}</span><button className="text-button" disabled={saving} onClick={() => setReload(n => n + 1)}>重新载入</button></div>
        <form className="review-form" onSubmit={submit}>
          <label><span>核验参数</span><select value={field} disabled={saving} onChange={event => { setField(event.target.value); setAction("manual_override"); setSaved(""); }}>{Object.entries(review.field_catalog).map(([key, item]) => <option key={key} value={key}>{item.label}{item.unit ? ` (${item.unit})` : ""}{key in review.source_facts ? "" : " · 来源未列"}</option>)}</select></label>
          <div className="review-values"><div><span>来源原值</span><strong>{raw ? showField(raw) : ""}</strong></div><div><span>核验视图当前值</span><strong>{effective ? showField(effective) : ""}</strong><small>{active ? states[active.status] : "沿用来源"}</small></div></div>
          {active?.status === "needs_review" ? <p className="review-warning" role="status">来源已经更新，旧人工结论暂停适用。请核对新原文，再决定是否重新纠错。</p> : null}
          <label><span>处理方式</span><select value={action} disabled={saving} onChange={event => setAction(event.target.value as RevisionAction)}>{Object.entries(actions).map(([key, label]) => <option key={key} value={key} disabled={key === "clear_override" && (!active || active.status === "cleared")}>{label}</option>)}</select></label>
          {action === "manual_override" ? <div className="review-edit-value"><label className="review-checkbox"><input type="checkbox" checked={unknown} disabled={saving} onChange={event => setUnknown(event.target.checked)} />标为未知（保留字段）</label>{!unknown && definition ? <label><span>人工新值{definition.unit ? ` (${definition.unit})` : ""}</span>{definition.type === "boolean" ? <select value={value === "true" ? "true" : "false"} disabled={saving} onChange={event => setValue(event.target.value)}><option value="true">是</option><option value="false">否</option></select> : definition.choices?.length ? <select value={value} required disabled={saving} onChange={event => setValue(event.target.value)}><option value="" disabled>请选择</option>{definition.choices.map(choice => <option key={choice}>{choice}</option>)}</select> : <input type={definition.type === "number" || definition.type === "measurement" ? "number" : "text"} step="any" min="0" maxLength={400} value={value} required disabled={saving} onChange={event => setValue(event.target.value)} />}{definition.type === "measurement" ? <select aria-label="人工新值单位" value={unit} required disabled={saving} onChange={event => setUnit(event.target.value)}><option value="" disabled>请选择已核对的单位</option>{definition.units?.map(item => <option key={item}>{item}</option>)}</select> : null}</label> : null}</div> : <p className="review-warning">{action === "revoke" ? "在核验视图中撤销此参数；原值和撤销记录保留。" : "停止使用此字段的人工处理，重新使用当前来源值。历史修订保留。"}</p>}
          <div className="review-evidence"><strong>本次依据：当前来源快照</strong><p>观察时间 {showTime(review.provenance.observed_at)}</p><button type="button" className="secondary-button" disabled={evidenceLoading} onClick={() => void showEvidence()}>{evidenceLoading ? "正在读取…" : "核对引用原文"}</button>{evidenceError ? <p role="alert">{evidenceError}</p> : null}{evidence ? <details className="raw-evidence"><summary>展开纯文本原文</summary><p className="hash-value">SHA-256 {evidence.raw_hash}</p><pre>{evidence.body}</pre></details> : null}</div>
          <label><span>证据位置或原文摘录</span><textarea required minLength={3} maxLength={2000} value={locator} disabled={saving} onChange={event => setLocator(event.target.value)} placeholder="例如规格表中的列名、产品代码及相应原文" /></label>
          <label><span>处理原因</span><textarea required minLength={5} maxLength={2000} value={reason} disabled={saving} onChange={event => setReason(event.target.value)} /></label>
          <label><span>核验人署名</span><input required maxLength={80} value={operator} disabled={saving} onChange={event => setOperator(event.target.value)} /><small>本地工作区署名，尚未接入生产身份认证。</small></label>
          <button className="primary-button" disabled={saving || stale} type="submit">{saving ? "正在保存修订…" : "保存人工修订"}</button>
        </form>
        <section className="review-history" aria-label="人工修订历史"><h3>人工修订历史</h3>{review.history_truncated ? <p>显示最近 200 条，完整记录仍保存在审计库。</p> : null}{!review.history.length ? <p>尚无人工作出修改。</p> : review.history.map(row => <details key={row.id}><summary>#{row.revision} · {review.field_catalog[row.field]?.label || row.field} · {actions[row.action]}</summary><dl><div><dt>核验人</dt><dd>{row.operator}</dd></div><div><dt>原因</dt><dd>{row.reason}</dd></div><div><dt>修改前</dt><dd>{showField(row.before)}</dd></div><div><dt>修改后</dt><dd>{showField(row.after)}</dd></div><div><dt>创建时间</dt><dd>{showTime(row.created_at)}</dd></div><div><dt>适用结束</dt><dd>{showTime(row.valid_to)}</dd></div></dl>{row.evidence.map(item => <blockquote key={item.snapshot_id}>{item.locator}<small>快照 {item.snapshot_id} · SHA-256 {item.raw_hash}</small><button type="button" className="text-button" onClick={() => void showHistoryEvidence(item.snapshot_id)}>查看此修订的证据原文</button>{historyEvidenceId === item.snapshot_id ? historyEvidenceError ? <p role="alert">{historyEvidenceError}</p> : historyEvidence ? <details className="raw-evidence"><summary>展开该历史快照纯文本</summary><p className="hash-value">SHA-256 {historyEvidence.raw_hash}</p><pre>{historyEvidence.body}</pre></details> : <p role="status">正在读取该历史快照…</p> : null}</blockquote>)}</details>)}</section>
      </>}
    </div>
  </dialog>;
}
