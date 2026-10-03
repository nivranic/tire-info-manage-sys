"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { Evidence, FieldCandidate, FieldConflictPage, FieldPolicyCatalog, FieldResolution, Source } from "@tire/domain-types";
import FactReviewDialog, { type FactReviewVariant } from "./fact-review";
import IdentityReviewDialog from "./identity-review";
import { FieldPolicyStamp, FieldResolutionView } from "./field-authority";
import { fieldDefaultText } from "./field-authority-values";

const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "字段依据读取失败，请重试。";
const stringValue = (value: unknown) => typeof value === "string" ? value : "未记录";
const conflictFields = (resolution: FieldResolution) => resolution.fields.filter(field => field.state === "conflict_preferred" || field.state === "conflict_tied");
const sourceClasses: Record<string, string> = { regulatory: "监管机构", manufacturer_official: "厂商官方", oem_fitment: "汽车 OEM",
  high_quality_distributor: "高质量经销数据库", authorized_retailer: "授权零售来源", official_store: "官方商城",
  original_test_organization: "原始测试机构", professional_media: "专业测试媒体", commissioned_lab_report: "受委托实验室原始报告" };

function PolicyCatalog({ catalog }: { catalog: FieldPolicyCatalog }) {
  return <details className="field-policy-catalog"><summary>查看字段权威规则与适用范围</summary>
    <FieldPolicyStamp policy={catalog.policy} /><p>{catalog.notice}</p>
    <p>{catalog.coverage}</p><ol>{catalog.criteria.map(criterion => <li key={criterion}>{criterion}</li>)}</ol>
    <div className="field-policy-categories">{catalog.information_categories.map(category => <article key={category.id}><h3>{category.label}</h3><ul>{Object.entries(category.source_tiers).map(([sourceClass, tier]) => <li key={sourceClass}>第 {tier} 层 · {sourceClasses[sourceClass] || sourceClass}</li>)}</ul>{!category.projection_available ? <p>本轮仅保留此类规则，尚无相应字段投影。</p> : null}</article>)}</div>
    <div className="field-policy-list">{catalog.fields.map(field => <article key={field.field}><strong>{field.label}{field.unit ? `（${field.unit}）` : ""}</strong><p>{field.identity_bound ? "身份字段：只核对来源，不用默认值改写实体身份。" : field.source_scope_only ? "来源范围字段：不同商家或来源的价格、库存、在售记录不自动合并。" : "按本字段规则核对正式来源证据，保留全部候选。"}</p><small><code>{field.field}</code> · {field.category}</small></article>)}</div>
  </details>;
}

function FieldResolutionDialog({ variantId, initialField, onClose, onChanged }: {
  variantId: string; initialField?: string; onClose: () => void; onChanged: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const evidenceRequest = useRef<AbortController | null>(null);
  const reviewRequest = useRef<AbortController | null>(null);
  const [resolution, setResolution] = useState<FieldResolution | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState("");
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [review, setReview] = useState<{ variant: FactReviewVariant; sourceId: string; initialField: string } | null>(null);
  const [identityId, setIdentityId] = useState("");
  const evidencePanel = useRef<HTMLElement>(null);
  useEffect(() => {
    const node = dialog.current;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { evidenceRequest.current?.abort(); reviewRequest.current?.abort(); node?.close(); if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, []);
  useEffect(() => {
    const controller = new AbortController(); setResolution(null); setError("");
    void tireApi.fieldResolution(variantId, controller.signal).then(value => {
      if (!controller.signal.aborted) { if (value.variant_id !== variantId) throw new Error("字段依据的精确版本不匹配，未展示。"); setResolution(value); }
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [variantId, revision]);
  useEffect(() => {
    if (!resolution || !initialField) return;
    const frame = requestAnimationFrame(() => {
      const target = Array.from(dialog.current?.querySelectorAll<HTMLElement>('.field-decision') || [])
        .find(item => item.dataset.field === initialField);
      target?.scrollIntoView({ block: "start" });
    });
    return () => cancelAnimationFrame(frame);
  }, [resolution, initialField]);

  async function showEvidence(candidate: FieldCandidate) {
    if (!candidate.snapshot_id) return;
    evidenceRequest.current?.abort(); const controller = new AbortController(); evidenceRequest.current = controller;
    setEvidence(null); setEvidenceError(""); setEvidenceLoading(true);
    try {
      const value = await tireApi.evidence(candidate.snapshot_id, controller.signal);
      if (!controller.signal.aborted) {
        if (value.id !== candidate.snapshot_id || value.source_id !== candidate.source_id || value.raw_hash !== candidate.raw_hash) throw new Error("原文与所选字段引用不匹配，请重新读取字段依据。");
        setEvidence(value);
        requestAnimationFrame(() => evidencePanel.current?.scrollIntoView({ block: "start" }));
      }
    } catch (cause) { if (!controller.signal.aborted) setEvidenceError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setEvidenceLoading(false); }
  }

  async function openReview(candidate: FieldCandidate) {
    if (!candidate.curation_field || !candidate.snapshot_id) return;
    reviewRequest.current?.abort(); const controller = new AbortController(); reviewRequest.current = controller;
    setReviewLoading(true); setReviewError("");
    try {
      const detail = await tireApi.identityReview(candidate.variant_id, controller.signal);
      if (!controller.signal.aborted) {
        if (detail.source.id !== candidate.variant_id) throw new Error("来源内纠错的原始版本不匹配。");
        const identity = detail.source.identity;
        setReview({ variant: { id: candidate.variant_id, model: stringValue(identity.model), size: stringValue(identity.size),
          region: stringValue(identity.region), manufacturer_product_code: typeof identity.manufacturer_product_code === "string" ? identity.manufacturer_product_code : null,
          snapshot_id: candidate.snapshot_id, source_id: candidate.source_id, identity_contract: detail.source.identity_contract },
          sourceId: candidate.source_id, initialField: candidate.curation_field });
      }
    } catch (cause) { if (!controller.signal.aborted) setReviewError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setReviewLoading(false); }
  }

  return <><dialog ref={dialog} className="fact-review-dialog reports-dialog field-resolution-dialog" aria-labelledby="field-resolution-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">FIELD EVIDENCE</span><h2 id="field-resolution-title">核对字段来源与默认值</h2><p>精确版本 <code>{variantId}</code></p></div><button type="button" className="icon-button" aria-label="关闭字段核对" onClick={onClose}>×</button></header>
    <div className="reports-content"><p className="snapshot-banner">LOCAL SNAPSHOT · 读取正式保存的来源证据，不进行官网查询。来源内纠错保留原值，不改写身份或已有历史报告。</p>
      <button type="button" className="secondary-button" onClick={() => setRevision(value => value + 1)}>重新读取字段依据</button>
      {error ? <p className="inline-error" role="alert">{error}</p> : !resolution ? <p role="status">正在读取字段与全部来源…</p> : <FieldResolutionView resolution={resolution} initialField={initialField} onEvidence={candidate => void showEvidence(candidate)} onReview={candidate => void openReview(candidate)} onIdentity={setIdentityId} />}
      {reviewLoading ? <p role="status">正在核对来源内纠错范围…</p> : null}{reviewError ? <p className="inline-error" role="alert">{reviewError}</p> : null}
      <section className="field-raw-evidence" ref={evidencePanel} aria-label="所选字段原文">{evidenceLoading ? <p role="status">正在读取所选来源原文…</p> : evidenceError ? <p className="inline-error" role="alert">{evidenceError}</p> : evidence ? <><h3>所选来源原文</h3><p>{evidence.source_id} · 快照 <code>{evidence.id}</code></p><p>SHA-256 <code>{evidence.raw_hash}</code></p><details className="raw-evidence" open><summary>纯文本原文</summary><pre>{evidence.body}</pre></details></> : null}</section>
    </div>
  </dialog>{review ? <FactReviewDialog {...review} onClose={() => setReview(null)} onSaved={() => { setRevision(value => value + 1); onChanged(); }} /> : null}
    {identityId ? <IdentityReviewDialog variantId={identityId} onClose={() => setIdentityId("")} onSaved={() => { setRevision(value => value + 1); onChanged(); }} /> : null}</>;
}

export default function FieldConflictCenter({ sources, sessionReady }: { sources: Source[]; sessionReady: boolean }) {
  const [opened, setOpened] = useState(false);
  const [catalog, setCatalog] = useState<FieldPolicyCatalog | null>(null);
  const [page, setPage] = useState<FieldConflictPage | null>(null);
  const [field, setField] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [policyError, setPolicyError] = useState("");
  const [selected, setSelected] = useState<{ id: string; field?: string } | null>(null);
  useEffect(() => {
    if (!opened || !sessionReady) return;
    const controller = new AbortController(); setPolicyError("");
    void tireApi.fieldPolicies(controller.signal).then(value => { if (!controller.signal.aborted) setCatalog(value); })
      .catch(cause => { if (!controller.signal.aborted) setPolicyError(errorText(cause)); });
    return () => controller.abort();
  }, [opened, sessionReady, revision]);
  useEffect(() => {
    if (!opened || !sessionReady) return;
    const controller = new AbortController(); setPage(null); setError("");
    void tireApi.fieldConflicts({ field, source_id: sourceId }, offset, controller.signal).then(value => { if (!controller.signal.aborted) setPage(value); })
      .catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [opened, sessionReady, field, sourceId, offset, revision]);
  return <section className="quarantine-panel field-conflict-center" aria-label="字段冲突中心">
    <div className="panel-title"><span>字段冲突中心</span><button type="button" className="secondary-button" disabled={!sessionReady} onClick={() => setOpened(value => !value)}>{opened ? "收起字段冲突" : "核对字段冲突"}</button></div>
    <p className="quality-intro">按精确身份核对来源分歧、默认展示值及其依据。名称、尺寸或相同数字代码不会自动合并为同一 SKU；选出默认值仍保留冲突。</p>
    {opened ? <>
      <div className="snapshot-banner"><strong>LOCAL SNAPSHOT · 已保存的正式来源记录</strong><span>这里不访问官网，也不修改来源等级。来源内纠错与身份核对需另行明确操作。</span></div>
      {policyError ? <p className="inline-error" role="alert">规则目录读取失败：{policyError}</p> : catalog ? <PolicyCatalog catalog={catalog} /> : <p role="status">正在读取字段规则…</p>}
      <div className="quarantine-filter"><label><span>冲突字段</span><select value={field} onChange={event => { setField(event.target.value); setOffset(0); }}><option value="">全部字段</option>{catalog?.fields.map(item => <option key={item.field} value={item.field}>{item.label}</option>)}</select></label>
        <label><span>候选来源</span><select value={sourceId} onChange={event => { setSourceId(event.target.value); setOffset(0); }}><option value="">全部来源</option>{sources.filter(source => !source.target_kind || source.target_kind === "tire").map(source => <option key={source.id} value={source.id}>{source.name}</option>)}</select></label>
        <button type="button" className="secondary-button" onClick={() => setRevision(value => value + 1)}>刷新字段冲突</button></div>
      {error ? <p className="inline-error" role="alert">{error}</p> : !page ? <p role="status">正在读取冲突记录…</p> : <>
        <p>{page.notice}</p><p>共有 {page.total} 个精确版本包含所选范围的冲突。</p>
        <div className="field-conflict-list">{page.items.map(item => <article className="field-conflict-item" data-variant-id={item.variant_id} key={item.variant_id}><h3>精确版本 <code>{item.variant_id}</code></h3>{conflictFields(item).map(decision => <div key={decision.field}><strong>{decision.label}</strong><p>{fieldDefaultText(decision)}</p><p>{new Set(decision.candidates.map(candidate => candidate.source_name || candidate.source_id)).size} 个来源 · {decision.candidates.length} 条记录</p><button type="button" className="text-button" onClick={() => setSelected({ id: item.variant_id, field: decision.field })}>核对{decision.label}的全部来源</button></div>)}<button type="button" className="secondary-button" onClick={() => setSelected({ id: item.variant_id })}>打开此版本字段依据</button></article>)}</div>
        {!page.items.length ? <p className="quality-empty">此范围没有已记录的字段冲突；不表示未接入来源或未知字段已经核验。</p> : null}
        <div className="reparse-pages"><button type="button" className="text-button" disabled={!offset} onClick={() => setOffset(value => Math.max(0, value - 20))}>上一页冲突</button><span>第 {Math.floor(offset / 20) + 1} 页</span><button type="button" className="text-button" disabled={offset + page.items.length >= page.total} onClick={() => setOffset(value => value + 20)}>下一页冲突</button></div>
      </>}
    </> : null}
    {selected ? <FieldResolutionDialog key={selected.id} variantId={selected.id} initialField={selected.field} onClose={() => setSelected(null)} onChanged={() => setRevision(value => value + 1)} /> : null}
  </section>;
}
