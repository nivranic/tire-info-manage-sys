"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { DrivingPreferenceState, DrivingWeightKey, DrivingWeights, Evidence, SaveComparisonRequest, SavedComparisonDetail, SavedComparisonRecord, SourceFieldConflict, Variant } from "@tire/domain-types";
import { Icon } from "./icons";
import { identityLabel } from "./identity-review";

const errorText = (value: unknown) => value instanceof Error ? value.message : "操作未完成，请重试。";
const stamp = (value: string) => new Date(value).toLocaleString("zh-CN");
const weightFields: [DrivingWeightKey, string][] = [["dry", "干地"], ["wet", "湿地"], ["quiet", "静音"], ["comfort", "舒适"], ["wear", "耐磨"], ["energy", "能耗"], ["appearance", "外观"]];
const example: DrivingWeights = { dry: 20, wet: 25, quiet: 20, comfort: 10, wear: 15, energy: 5, appearance: 5 };
type ComparisonRenderer = (variants: Variant[], onEvidence: (id: string) => void, conflicts: SourceFieldConflict[]) => ReactNode;

function ResearchDialog({ title, busy = false, onClose, children }: { title: string; busy?: boolean; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { node?.close(); const target = focus?.isConnected ? focus : document.getElementById("saved-comparisons-title"); target?.focus({ preventScroll: true }); };
  }, []);
  return <dialog ref={dialog} className="fact-review-dialog research-dialog" aria-label={title} onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="fact-review-heading"><div><span className="eyebrow">SAVED RESEARCH</span><h2>{title}</h2></div><button type="button" className="icon-button" aria-label="关闭比较记录窗口" disabled={busy} onClick={onClose}><Icon name="close" size={20} /></button></div>
    <div className="fact-review-content">{children}</div>
  </dialog>;
}

export function SaveComparisonDialog({ selection, onClose, onSaved, onRefresh }: {
  selection: Omit<SaveComparisonRequest, "title" | "notes">; onClose: () => void; onSaved: () => void; onRefresh: () => void;
}) {
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function save() {
    if (busy || stale) return;
    const request = new AbortController(); controller.current = request; setBusy(true); setError("");
    try { await tireApi.saveComparison({ ...selection, title: title.trim(), notes: notes.trim() }, request.signal); if (!request.signal.aborted) onSaved(); }
    catch (cause) { if (!request.signal.aborted) { setError(errorText(cause)); if (cause instanceof ApiError && cause.status === 409) setStale(true); } }
    finally { if (!request.signal.aborted) setBusy(false); }
  }
  return <ResearchDialog title="保存本次比较" busy={busy} onClose={onClose}>
    <p className="review-boundary">固定保存本次已核对的参数、证据版本和{selection.include_manual ? "所选人工修订" : "来源值"}。以后打开保持保存时内容，不会自动替换为新参数。</p>
    {selection.resolve_identities ? <p className="review-boundary">本次已明确采用身份更正与合并。原选择、目标映射及当时身份修订一并固定保存。</p> : null}
    {error ? <div className="inline-error" role="alert">{error}{stale ? <button type="button" className="text-button" onClick={onRefresh}>返回重新核对</button> : null}</div> : null}
    <form className="review-form" onSubmit={event => { event.preventDefault(); void save(); }}>
      <label><span>比较名称</span><input required maxLength={120} value={title} disabled={busy} onChange={event => setTitle(event.target.value)} /></label>
      <label><span>研究备注（可留空）</span><textarea maxLength={2000} value={notes} disabled={busy} onChange={event => setNotes(event.target.value)} /></label>
      <button className="primary-button" disabled={busy || stale} type="submit">{busy ? "正在保存…" : "固定保存此比较"}</button>
    </form>
  </ResearchDialog>;
}

function SavedComparisonDialog({ id, onClose, onChanged, renderComparison }: { id: string; onClose: () => void; onChanged: () => void; renderComparison: ComparisonRenderer }) {
  const [data, setData] = useState<SavedComparisonDetail | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [evidenceError, setEvidenceError] = useState("");
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const mutation = useRef<AbortController | null>(null);
  const evidenceRequest = useRef<AbortController | null>(null);
  const evidencePanel = useRef<HTMLDivElement>(null);
  useEffect(() => () => { mutation.current?.abort(); evidenceRequest.current?.abort(); }, []);
  function accept(value: SavedComparisonDetail) { setData(value); setTitle(value.title); setNotes(value.notes); setStale(false); }
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError("");
    void tireApi.savedComparison(id, controller.signal).then(value => { if (!controller.signal.aborted) accept(value); })
      .catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [id, attempt]);
  async function mutate(action: "edit" | "archive" | "restore") {
    if (!data || busy || stale) return;
    const controller = new AbortController(); mutation.current = controller; setBusy(true); setError("");
    try {
      if (action === "edit") await tireApi.editSavedComparison(id, data.revision, title, notes, controller.signal);
      else await tireApi.savedComparisonState(id, data.revision, action, controller.signal);
      const value = await tireApi.savedComparison(id, controller.signal);
      if (!controller.signal.aborted) { accept(value); onChanged(); }
    } catch (cause) { if (!controller.signal.aborted) { setError(errorText(cause)); if (cause instanceof ApiError && cause.status === 409) setStale(true); } }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  async function showEvidence(snapshotId: string) {
    evidenceRequest.current?.abort();
    const controller = new AbortController(); evidenceRequest.current = controller;
    setEvidence(null); setEvidenceError(""); setEvidenceLoading(true);
    try {
      const value = await tireApi.evidence(snapshotId, controller.signal);
      if (!controller.signal.aborted) { setEvidence(value); requestAnimationFrame(() => evidencePanel.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })); }
    } catch (cause) { if (!controller.signal.aborted) setEvidenceError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setEvidenceLoading(false); }
  }
  const nowRevoked = data?.comparison.variants.filter(row => data.current_lifecycle[row.id]?.state === "revoked") || [];
  const savedEvidence = data ? [...new Map(data.comparison.provenance.map(item => [item.snapshot_id, item])).values()] : [];
  return <ResearchDialog title={data?.title || "读取保存的比较"} busy={busy} onClose={onClose}>
    {error ? <div className="inline-error" role="alert">{error}<button className="text-button" disabled={busy} onClick={() => setAttempt(value => value + 1)}>重新载入记录</button></div> : null}
    {!data ? !error ? <p role="status">正在读取固定版本…</p> : null : <>
      <div className="snapshot-banner"><strong>LOCAL SNAPSHOT · 固定保存版本{data.archived ? " · 已归档" : ""}</strong><span>保存于 {stamp(data.created_at)} · {data.include_manual ? "含当时选择的人工修订" : "来源原值"}。此处不是当前在线参数。</span></div>
      {nowRevoked.length ? <p className="review-warning">以下版本目前已撤销，本记录仅保留当时的研究内容：{nowRevoked.map(row => row.manufacturer_product_code || row.model).join("、")}。</p> : null}
      {data.comparison.excluded_variants.length ? <p className="review-boundary">保存时已排除：{data.comparison.excluded_variants.map(row => row.manufacturer_product_code || row.model).join("、")}。</p> : null}
      {renderComparison(data.comparison.variants, snapshotId => void showEvidence(snapshotId), data.comparison.conflicts)}
      {data.comparison.resolve_identities ? <details className="quality-technical"><summary>保存时采用的身份映射</summary>{data.comparison.identity_mappings?.map(item => <p className="hash-value" key={item.requested_id}>{item.requested_id} → {item.resolved_id} · 修订{item.revision}</p>)}</details> : null}
      {Object.keys(data.current_identity_resolutions || {}).length ? <details className="quality-technical"><summary>目前的身份处理状态（不改写保存内容）</summary>{Object.entries(data.current_identity_resolutions || {}).map(([key, value]) => <p className="hash-value" key={key}>{key} · {identityLabel(value.state)} · 修订{value.revision}</p>)}</details> : null}
      <details className="quality-technical"><summary>保存时的证据版本</summary>{savedEvidence.map(item => <div className="saved-provenance" key={item.snapshot_id}><strong>{item.source_id}</strong><p>{stamp(item.observed_at)} · {item.parser_version}</p><p className="hash-value">SHA-256 {item.raw_hash}</p><button className="text-button" onClick={() => void showEvidence(item.snapshot_id)}>查看此版本原文</button></div>)}<p className="hash-value">比较指纹 {data.fingerprint}</p></details>
      <div ref={evidencePanel}>{evidenceLoading ? <p role="status">正在读取原始证据…</p> : evidenceError ? <p role="alert">{evidenceError}</p> : evidence ? <details className="raw-evidence" open><summary>引用的原文 · LOCAL SNAPSHOT</summary><p className="hash-value">SHA-256 {evidence.raw_hash}</p><pre>{evidence.body}</pre></details> : null}</div>
      <form className="review-form saved-metadata-form" onSubmit={event => { event.preventDefault(); void mutate("edit"); }}>
        <h3>名称与备注</h3><p className="review-boundary">这里只修改记录说明，固定参数和证据不会改变。需要最新官网参数时，请重新在线查询。</p>
        <label><span>比较名称</span><input required maxLength={120} disabled={busy} value={title} onChange={event => setTitle(event.target.value)} /></label>
        <label><span>研究备注</span><textarea maxLength={2000} disabled={busy} value={notes} onChange={event => setNotes(event.target.value)} /></label>
        <div className="variant-actions"><button type="submit" className="primary-button" disabled={busy || stale}>保存名称与备注</button><button type="button" className="text-button" disabled={busy || stale} onClick={() => void mutate(data.archived ? "restore" : "archive")}>{data.archived ? "恢复此记录" : "移入归档"}</button></div>
      </form>
      <section className="review-history"><h3>记录说明历史</h3>{data.history_truncated ? <p>显示最近 50 条。</p> : null}{data.history.map(row => <details key={row.revision}><summary>#{row.revision} · {row.operation === "save" ? "保存比较" : row.operation === "edit" ? "编辑说明" : row.operation === "archive" ? "归档" : "恢复"} · {stamp(row.created_at)}</summary><dl><div><dt>名称</dt><dd>{row.title}</dd></div><div><dt>备注</dt><dd>{row.notes || "无"}</dd></div></dl></details>)}</section>
    </>}
  </ResearchDialog>;
}

export function SavedComparisonsPanel({ sessionReady, refreshVersion, renderComparison }: { sessionReady: boolean; refreshVersion: number; renderComparison: ComparisonRenderer }) {
  const [items, setItems] = useState<SavedComparisonRecord[] | null>(null);
  const [total, setTotal] = useState(0);
  const [archived, setArchived] = useState(false);
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    if (!sessionReady) return;
    const controller = new AbortController(); request.current?.abort(); request.current = controller; setItems(null); setError(""); setLoadingMore(false);
    void tireApi.savedComparisons(archived, controller.signal).then(value => { if (!controller.signal.aborted) { setItems(value.items); setTotal(value.total); } })
      .catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => request.current?.abort();
  }, [sessionReady, refreshVersion, revision, archived]);
  async function more() {
    if (!items || loadingMore) return;
    const controller = new AbortController(); request.current = controller; setLoadingMore(true);
    try { const value = await tireApi.savedComparisons(archived, controller.signal, items.length); if (!controller.signal.aborted) { setItems([...new Map([...items, ...value.items].map(item => [item.id, item])).values()]); setTotal(value.total); } }
    catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setLoadingMore(false); }
  }
  return <section className="quarantine-panel saved-comparisons-panel" aria-labelledby="saved-comparisons-title">
    <div className="panel-title"><span id="saved-comparisons-title" tabIndex={-1}>已保存的比较</span><span className="tag quiet">本地工作区</span></div>
    <p className="quality-intro">保存时的参数和证据固定保留；列表只读取记录信息，点击后再打开内容。</p>
    <div className="quarantine-filter"><label><span>比较记录范围</span><select value={archived ? "archived" : "active"} onChange={event => setArchived(event.target.value === "archived")}><option value="active">使用中的比较</option><option value="archived">已归档比较</option></select></label><button className="secondary-button" disabled={!sessionReady} onClick={() => setRevision(value => value + 1)}>刷新保存记录</button></div>
    {error ? <p role="alert" className="inline-error">{error}</p> : null}
    {!items ? !error ? <p className="quality-empty" role="status">正在读取保存记录…</p> : null : items.length ? <><p className="quarantine-list-count">已显示 {items.length} / {total} 条</p>{items.map(item => <article className="quarantine-item" key={item.id}><div className="quality-item-heading"><h3>{item.title}</h3><time>{stamp(item.created_at)}</time></div><p className="quarantine-comparison">{item.variant_count} 项精确规格 · {item.include_manual ? "含保存时人工修订" : "来源原值"}</p><button className="secondary-button" onClick={() => setSelected(item.id)}>打开保存的比较</button></article>)}{items.length < total ? <button className="secondary-button" disabled={loadingMore} onClick={() => void more()}>加载更多记录</button> : null}</> : <p className="quality-empty">{archived ? "暂无归档比较。" : "尚未保存比较。核对当前比较后，可保存固定版本。"}</p>}
    {selected ? <SavedComparisonDialog key={selected} id={selected} onClose={() => setSelected("")} onChanged={() => setRevision(value => value + 1)} renderComparison={renderComparison} /> : null}
  </section>;
}

export function DrivingPreferences({ sessionReady }: { sessionReady: boolean }) {
  const [data, setData] = useState<DrivingPreferenceState | null>(null);
  const [values, setValues] = useState<Record<DrivingWeightKey, string>>(() => Object.fromEntries(weightFields.map(([key]) => [key, ""])) as Record<DrivingWeightKey, string>);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  function accept(value: DrivingPreferenceState) {
    setData(value); setValues(Object.fromEntries(weightFields.map(([key]) => [key, value.weights ? String(value.weights[key]) : ""])) as Record<DrivingWeightKey, string>); setStale(false);
  }
  useEffect(() => {
    if (!sessionReady) return;
    const controller = new AbortController(); request.current = controller; setData(null); setError(""); setNotice("");
    void tireApi.drivingPreferences(controller.signal).then(value => { if (!controller.signal.aborted) accept(value); })
      .catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [sessionReady, attempt]);
  const total = weightFields.reduce((sum, [key]) => sum + (Number(values[key]) || 0), 0);
  const valid = total === 100 && weightFields.every(([key]) => values[key].trim() !== "" && Number.isInteger(Number(values[key])) && Number(values[key]) >= 0 && Number(values[key]) <= 100);
  async function save(clear = false) {
    if (!data || busy || stale || (!clear && !valid)) return;
    const controller = new AbortController(); request.current = controller; setBusy(true); setError(""); setNotice("");
    try {
      const value = clear ? await tireApi.clearDrivingPreferences(data.revision, controller.signal)
        : await tireApi.saveDrivingPreferences(data.revision, Object.fromEntries(weightFields.map(([key]) => [key, Number(values[key])])) as DrivingWeights, controller.signal);
      if (!controller.signal.aborted) { accept(value); setNotice(clear ? "已清除当前偏好，修改历史仍保留。" : "偏好已保存，官方参数与测试排序保持原样。"); }
    } catch (cause) { if (!controller.signal.aborted) { setError(errorText(cause)); if (cause instanceof ApiError && cause.status === 409) setStale(true); } }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section className="quarantine-panel driving-preferences" aria-labelledby="driving-preferences-title">
    <div className="panel-title"><span id="driving-preferences-title">驾驶偏好</span><button className="text-button" disabled={!sessionReady || busy} onClick={() => setAttempt(value => value + 1)}>重新载入偏好</button></div>
    <p className="quality-intro">记录你的取舍，七项合计 100。权重独立于官方参数和测试排序；当前保存偏好，尚未启用推荐评分。本地工作区共享此设置。</p>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}{notice ? <p className="review-saved" role="status">{notice}</p> : null}
    {!data ? !error ? <p className="quality-empty" role="status">正在读取偏好…</p> : null : <form className="review-form preferences-form" onSubmit={event => { event.preventDefault(); void save(); }}>
      <p className="muted">{data.weights ? `已保存 · 修订 #${data.revision}` : "尚未设置当前偏好"}</p>
      <div className="preference-grid">{weightFields.map(([key, label]) => <label key={key}><span>{label}权重</span><input type="number" required min={0} max={100} step={1} disabled={busy} value={values[key]} onChange={event => setValues(previous => ({ ...previous, [key]: event.target.value }))} /></label>)}</div>
      <p className={valid ? "preference-total" : "review-warning"} aria-live="polite">合计 {total} / 100{valid ? "" : " · 请填写 0–100 的整数，合计为 100 后保存"}</p>
      <div className="variant-actions"><button type="submit" className="primary-button" disabled={busy || stale || !valid}>{busy ? "正在保存…" : "保存驾驶偏好"}</button><button type="button" className="text-button" disabled={busy} onClick={() => { setValues(Object.fromEntries(weightFields.map(([key]) => [key, String(example[key])])) as Record<DrivingWeightKey, string>); setNotice("示例仅填入表单，点击保存后才生效。"); }}>填入示例权重</button><button type="button" className="text-button" disabled={busy || stale || !data.weights} onClick={() => void save(true)}>清除当前偏好</button></div>
      {data.history.length ? <details className="quality-technical"><summary>偏好修改历史{data.history_truncated ? "（最近 20 条）" : ""}</summary>{data.history.map(row => <div className="preference-history-row" key={row.revision}><strong>#{row.revision} · {row.weights ? "保存偏好" : "清除偏好"} · {stamp(row.created_at)}</strong><p>{row.weights ? weightFields.map(([key, label]) => `${label} ${row.weights![key]}`).join(" · ") : "未设置当前权重"}</p></div>)}</details> : null}
    </form>}
  </section>;
}
