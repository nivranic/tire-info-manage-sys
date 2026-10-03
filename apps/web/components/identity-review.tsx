"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { Evidence, IdentityCandidates, IdentityDecision, IdentityPreview, IdentityReview, IdentityResolution } from "@tire/domain-types";
import { IdentityContractBadge, IdentityContractEvidence } from "./identity-contract";
import { DataTree } from "./reparse-review";

export const identityLabel = (state: IdentityResolution["state"]) => ({ independent: "独立版本", cleared: "已撤回身份处理", redirected: "已记录身份指向", needs_review: "身份决定待复核" })[state];
const actionLabel = { correct: "身份更正", merge: "重复版本合并", clear: "撤回身份处理" };
const fieldLabels: Record<string, string> = { brand: "品牌", model: "型号", manufacturer_product_code: "厂商产品代码", product_code_type: "产品代码命名空间", region: "区域", size: "尺寸", load_index: "载重指数", speed_rating: "速度级别", xl: "XL", hl: "HL", oe_mark: "OE标记", acoustic_technology: "静音技术", run_flat: "防爆", gtin: "GTIN", eprel_id: "EPREL编号", technology_features: "技术配置" };
const blockers: Record<string, string> = { identity_contract_review_required: "身份编码类型尚未完成核对，不能用旧混合身份建立新的更正或合并决定", accepted_evidence_required: "双方须已有正式采纳证据", active_variants_required: "双方必须处于未撤销状态", target_has_identity_decision: "目标已有未撤回的身份指向，请核对其最终目标并明确选择", nothing_to_clear: "当前没有可撤回的身份处理" };
const text = (value: unknown) => value === null || value === undefined ? "未知" : typeof value === "boolean" ? value ? "是" : "否" : typeof value === "object" ? JSON.stringify(value) : String(value);
const stamp = (value: string) => new Date(value).toLocaleString("zh-CN");
const errorText = (error: unknown) => error instanceof Error ? error.message : "操作未完成，请重新核对。";
type Attempt = { key: string; payload: IdentityDecision };
const attempts = new Map<string, Attempt>();

export default function IdentityReviewDialog({ variantId, onClose, onSaved, restoreFocus }: {
  variantId: string; onClose: () => void; onSaved: (review: IdentityReview) => void; restoreFocus?: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const saveRequest = useRef<AbortController | null>(null);
  const rawRequest = useRef<AbortController | null>(null);
  const [review, setReview] = useState<IdentityReview | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [candidates, setCandidates] = useState<IdentityCandidates | null>(null);
  const [target, setTarget] = useState("");
  const [action, setAction] = useState<IdentityDecision["action"]>("correct");
  const [preview, setPreview] = useState<IdentityPreview | null>(null);
  const [fieldReasons, setFieldReasons] = useState<Record<string, string>>({});
  const [snapshots, setSnapshots] = useState<Record<string, string>>({});
  const [locators, setLocators] = useState<Record<string, string>>({});
  const [operator, setOperator] = useState("");
  const [reason, setReason] = useState("");
  const [unknowns, setUnknowns] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState<Attempt | null>(attempts.get(variantId) || null);
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState("");
  const [raw, setRaw] = useState<Evidence | null>(null);
  const [rawLoading, setRawLoading] = useState(false);
  const locked = busy || !!pending;
  const targetId = action === "clear" ? null : target || null;
  const endpoints = preview ? [preview.binding.source, ...(preview.binding.target ? [preview.binding.target] : [])] : [];
  const evidenceIds = [...new Set(endpoints.map(item => snapshots[item.id]).filter(Boolean))];
  const canSave = !!preview && !locked && !stale && confirmed && !!operator.trim() && reason.trim().length >= 5
    && (action === "correct" ? preview.can_correct : action === "merge" ? preview.can_merge : preview.can_clear)
    && (!preview.unknown_fields.length || unknowns)
    && preview.differences.every(item => (fieldReasons[item.field] || "").trim().length >= 5)
    && endpoints.every(item => !!snapshots[item.id]) && evidenceIds.every(id => (locators[id] || "").trim().length >= 3);

  function error(key: string, value = "") { setErrors(previous => ({ ...previous, [key]: value })); }
  function reload() { setRefresh(value => value + 1); setConfirmed(false); setUnknowns(false); error("save"); setNotice(""); }
  function remember(value: Attempt | null) { setPending(value); if (value) attempts.set(variantId, value); else attempts.delete(variantId); }

  useEffect(() => {
    const node = dialog.current;
    const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { saveRequest.current?.abort(); rawRequest.current?.abort(); node?.close(); if (focus?.isConnected) focus.focus({ preventScroll: true }); else restoreFocus?.(); };
  }, [restoreFocus]);
  useEffect(() => {
    const controller = new AbortController(); setReview(null); error("review");
    void tireApi.identityReview(variantId, controller.signal).then(value => {
      if (!controller.signal.aborted) { if (value.source.id !== variantId) throw new Error("身份记录范围不匹配。"); setReview(value); setStale(false); }
    }).catch(cause => { if (!controller.signal.aborted) error("review", errorText(cause)); });
    return () => controller.abort();
  }, [variantId, refresh]);
  useEffect(() => {
    const controller = new AbortController(); setCandidates(null); error("candidates");
    void tireApi.identityCandidates(query, offset, controller.signal).then(value => { if (!controller.signal.aborted) setCandidates(value); })
      .catch(cause => { if (!controller.signal.aborted) error("candidates", errorText(cause)); });
    return () => controller.abort();
  }, [query, offset, refresh]);
  useEffect(() => {
    const controller = new AbortController(); setPreview(null); setConfirmed(false); setUnknowns(false);
    setFieldReasons({}); setSnapshots({}); setLocators({}); error("preview");
    if (action !== "clear" && !targetId) return;
    void tireApi.identityPreview(variantId, targetId, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (value.binding.source.id !== variantId || (value.binding.target?.id || null) !== targetId) throw new Error("预览身份范围不匹配。");
      setPreview(value);
      setSnapshots(Object.fromEntries([value.binding.source, ...(value.binding.target ? [value.binding.target] : [])].map(item => [item.id, item.facts[0]?.snapshot_id || ""])));
    }).catch(cause => { if (!controller.signal.aborted) error("preview", errorText(cause)); });
    return () => controller.abort();
  }, [variantId, targetId, action === "clear", refresh]);

  async function showRaw(id: string) {
    rawRequest.current?.abort(); const controller = new AbortController(); rawRequest.current = controller;
    setRaw(null); setRawLoading(true); error("raw");
    try { const value = await tireApi.evidence(id, controller.signal); if (!controller.signal.aborted) { if (value.id !== id) throw new Error("证据返回范围不匹配。"); setRaw(value); } }
    catch (cause) { if (!controller.signal.aborted) error("raw", errorText(cause)); }
    finally { if (!controller.signal.aborted) setRawLoading(false); }
  }
  async function perform(attempt: Attempt) {
    if (saveRequest.current) return;
    remember(attempt); const controller = new AbortController(); saveRequest.current = controller;
    setBusy(true); error("save"); setNotice("");
    try {
      const result = await tireApi.identityDecision(variantId, attempt.payload, attempt.key, controller.signal);
      if (controller.signal.aborted) return;
      if (result.event.variant_id !== variantId || result.event.target_id !== attempt.payload.target_id || result.event.action !== attempt.payload.action || result.event.revision !== attempt.payload.expected_revision + 1 || result.review.source.id !== variantId) throw new Error("结果与固定请求不匹配，请保留UUID核对。");
      remember(null); onSaved(result.review); setReview(result.review); setPreview(null); setConfirmed(false); setReason(""); setStale(false);
      setNotice(`已核对身份修订 #${result.event.revision}${result.idempotent_replay ? "（同一次请求）" : ""}。当前状态：${identityLabel(result.review.resolution.state)}。原始事实和引用保持不变。`);
      setRefresh(value => value + 1);
    } catch (cause) {
      if (!controller.signal.aborted) {
        error("save", errorText(cause)); setConfirmed(false);
        if (cause instanceof ApiError && [404, 409, 422].includes(cause.status) && cause.code !== "idempotency_payload_mismatch") { remember(null); setStale(true); }
      }
    } finally { if (saveRequest.current === controller) saveRequest.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  function submit() {
    if (!canSave || !preview) return;
    void perform({ key: crypto.randomUUID(), payload: { mode: "history", target_id: targetId, action,
      expected_revision: preview.revision, expected_fingerprint: preview.fingerprint, operator: operator.trim(), reason: reason.trim(),
      field_reasons: Object.fromEntries(preview.differences.map(item => [item.field, fieldReasons[item.field].trim()])),
      acknowledge_unknowns: unknowns, acknowledged: true, evidence: evidenceIds.map(snapshot_id => ({ snapshot_id, locator: locators[snapshot_id].trim() })) } });
  }

  return <dialog ref={dialog} className="fact-review-dialog reports-dialog identity-dialog" aria-labelledby="identity-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">EXACT VARIANT / LOCAL REVIEW</span><h2 id="identity-title">身份更正与版本合并</h2></div><button type="button" className="icon-button" aria-label="关闭身份核对" onClick={onClose}>×</button></header>
    <div className="fact-review-content">
      <p className="review-boundary">把当前记录明确指向另一个有证据的精确版本。来源ID、旧事实和引用全部保留；关注与监控不迁移。合并不代表轮胎可互换，型号与尺寸相同不能作为唯一依据。</p>
      <button type="button" className="secondary-button" disabled={busy} onClick={reload}>重新读取身份与预览</button>
      {Object.entries(errors).filter(([, value]) => value).map(([key, value]) => <p key={key} className="inline-error" role="alert">{value}</p>)}
      {notice ? <p className="review-saved" role="status">{notice}</p> : null}
      {pending ? <section className="review-boundary"><strong>身份操作结果待核对</strong><p>固定UUID <code>{pending.key}</code>。关闭重开保留同一次请求；整页刷新后先核对历史记录。</p><DataTree label="此请求的固定内容" value={pending.payload} /><button type="button" className="primary-button" disabled={busy} onClick={() => void perform(pending)}>核对同一次身份操作</button></section> : null}
      {review ? <>
        <div className="snapshot-banner"><strong>{text(review.source.identity.brand)} {text(review.source.identity.model)} · {text(review.source.identity.manufacturer_product_code)}</strong><span>{text(review.source.identity.size)} · {text(review.source.identity.region)} · {identityLabel(review.resolution.state)} · 修订 #{review.resolution.revision}</span>{review.resolution.target_id ? <span>已记录目标 <code>{review.resolution.target_id}</code></span> : null}</div>
        <DataTree label="当前记录的完整原始身份" value={review.source.identity} /><IdentityContractEvidence contract={review.source.identity_contract} />
        {review.resolution.state === "needs_review" ? <p className="inline-error">来源事实、版本状态或目标身份关系已变化。旧决定不再用于解析比较，须重新核对，不能自动沿用目标的新指向。</p> : null}
        <label className="identity-action"><span>本次操作</span><select value={action} disabled={locked} onChange={event => { setAction(event.target.value as IdentityDecision["action"]); setConfirmed(false); }}><option value="correct">身份更正 · 逐项解释差异</option><option value="merge">重复版本合并 · 有稳定标识依据</option><option value="clear">撤回身份处理 · 恢复独立选择</option></select></label>
        {action !== "clear" ? <section className="identity-candidates"><h3>选择有证据的目标</h3><form className="compare-toolbar" onSubmit={event => { event.preventDefault(); setQuery(search.trim()); setOffset(0); }}><label><span>品牌、型号或产品代码</span><input maxLength={120} value={search} disabled={locked} onChange={event => setSearch(event.target.value)} /></label><button className="secondary-button" disabled={locked}>搜索历史版本</button></form>
          {candidates?.items.filter(item => item.id !== variantId).map(item => <button type="button" key={item.id} className={`report-list-item${target === item.id ? " selected" : ""}`} disabled={locked} aria-pressed={target === item.id} onClick={() => { setTarget(item.id); setConfirmed(false); }}><strong>{text(item.identity.brand)} {text(item.identity.model)} · {text(item.identity.manufacturer_product_code)}</strong><span>{text(item.identity.size)} · {text(item.identity.region)} · OE {text(item.identity.oe_mark)}</span><IdentityContractBadge contract={item.identity_contract} /><small><code>{item.id}</code>{item.identity_resolution ? ` · ${identityLabel(item.identity_resolution.state)}` : ""}</small></button>)}
          <div className="reparse-pages"><button type="button" className="text-button" disabled={locked || !offset} onClick={() => setOffset(value => Math.max(0, value - 20))}>上一页目标</button><span>共 {candidates?.total || 0} 个记录 · 第 {offset / 20 + 1} 页</span><button type="button" className="text-button" disabled={locked || !candidates || offset + 20 >= candidates.total} onClick={() => setOffset(value => value + 20)}>下一页目标</button></div>
        </section> : null}
        {preview ? <section className="identity-preview"><h3>核对本次身份决定</h3><p>来源身份修订 #{preview.revision} → #{preview.revision + 1}；目标已有身份修订 #{preview.binding.target_resolution_revision}。</p>
          {preview.binding.target ? <><DataTree label="目标的完整身份与来源事实版本" value={preview.binding.target} /><IdentityContractEvidence contract={preview.binding.target.identity_contract} /></> : null}
          {preview.blockers.map(item => <p className="inline-error" key={item}>{blockers[item] || item}</p>)}
          {action === "merge" ? <p className={preview.can_merge ? "review-boundary" : "inline-error"}>相同稳定标识：{preview.stable_anchors.map(key => fieldLabels[key] || key).join("、") || "没有"}。已知矛盾：{preview.known_contradictions.map(key => fieldLabels[key] || key).join("、") || "没有"}。有已知矛盾不能合并。</p> : null}
          <form className="review-form" onSubmit={event => { event.preventDefault(); submit(); }}>
            {preview.differences.map(item => <label key={item.field} className="identity-difference"><span>{fieldLabels[item.field] || item.field}：{item.before.present ? text(item.before.value) : "未记录"} → {item.after.present ? text(item.after.value) : "未记录"}</span><textarea required minLength={5} maxLength={1000} rows={2} disabled={locked || stale} value={fieldReasons[item.field] || ""} onChange={event => setFieldReasons(values => ({ ...values, [item.field]: event.target.value }))} placeholder="解释这项身份差异及其证据依据" /></label>)}
            {!preview.differences.length ? <p>完整身份未见差异；仍须核对未知项与双方证据。</p> : null}
            {endpoints.map((item, index) => <label key={item.id}><span>{index ? "目标版本" : "当前版本"}的已采纳证据</span><select value={snapshots[item.id] || ""} disabled={locked || stale} onChange={event => { setSnapshots(values => ({ ...values, [item.id]: event.target.value })); setConfirmed(false); }}><option value="">选择来源证据</option>{item.facts.map(fact => <option key={fact.id} value={fact.snapshot_id}>{fact.source_id} · 事实版本{fact.version} · {fact.snapshot_id}</option>)}</select></label>)}
            {evidenceIds.map(id => <div className="identity-evidence" key={id}><p>证据 <code>{id}</code></p><button type="button" className="text-button" onClick={() => void showRaw(id)}>核对身份原文</button><label><span>证据位置或短摘录 · {id.slice(0, 8)}</span><textarea required minLength={3} maxLength={2000} rows={2} disabled={locked || stale} value={locators[id] || ""} onChange={event => setLocators(values => ({ ...values, [id]: event.target.value }))} placeholder="覆盖当前与目标的精确产品代码位置" /></label></div>)}
            <label><span>处理人署名（本地自报）</span><input required maxLength={100} value={operator} disabled={locked || stale} onChange={event => setOperator(event.target.value)} /></label>
            <label><span>本次处理理由</span><textarea required minLength={5} maxLength={2000} rows={3} value={reason} disabled={locked || stale} onChange={event => setReason(event.target.value)} /></label>
            {preview.unknown_fields.length ? <label className="review-checkbox"><input type="checkbox" checked={unknowns} disabled={locked || stale} onChange={event => setUnknowns(event.target.checked)} /><span>确认存在未知项：{preview.unknown_fields.map(key => fieldLabels[key] || key).join("、")}；已核对原文，不能把未知自动解释为无。</span></label> : null}
            <label className="review-checkbox"><input type="checkbox" checked={confirmed} disabled={locked || stale} onChange={event => setConfirmed(event.target.checked)} /><span>确认上述双方身份、全部差异与引用；理解这是本地人工决定，不代表厂商确认或轮胎互换许可。</span></label>
            {stale ? <p className="inline-error">当前表单已失效，请先重新读取身份与预览。</p> : null}<button type="submit" className="primary-button" disabled={!canSave}>{busy ? "正在核对…" : `确认${actionLabel[action]}`}</button>
          </form></section> : <p className="muted">{action === "clear" || target ? "正在准备双方身份预览…" : "选定目标后再核对身份差异与证据。"}</p>}
        <details className="report-history"><summary>身份处理历史（{review.history.length}{review.history_truncated ? "+，最近100条" : "条"}）</summary>{review.history.map(item => <article key={item.id}><h4>#{item.revision} · {actionLabel[item.action]}</h4><p>{item.operator} · {stamp(item.created_at)}</p><p>{item.reason}</p>{item.target_id ? <p>目标 <code>{item.target_id}</code></p> : null}<DataTree label="冻结身份、差异说明和证据" value={item} />{item.evidence.map(ref => <button type="button" className="text-button" key={ref.snapshot_id} onClick={() => void showRaw(ref.snapshot_id)}>核对此次引用原文</button>)}</article>)}</details>
        {review.incoming.length ? <details className="report-history"><summary>明确指向此版本的记录（{review.incoming.length}{review.incoming_truncated ? "+" : ""}）</summary>{review.incoming.map(item => <p key={item.variant_id}><code>{item.variant_id}</code> · {identityLabel(item.state)} · 修订{item.revision}</p>)}</details> : null}
      </> : <p role="status">正在读取精确身份…</p>}
      {rawLoading ? <p role="status">正在读取已采纳原文…</p> : raw ? <section className="identity-raw"><h3>历史原文 · LOCAL SNAPSHOT</h3><p><code>{raw.id}</code> · SHA-256 <code>{raw.raw_hash}</code></p><DataTree label="原文分页文本" value={raw.body} /></section> : null}
    </div>
  </dialog>;
}
