"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { AIAnalysis, AIPack, EvidenceReportDetail, EvidenceReportRecord, ReportCreate, ReportExport, ReportFormat } from "@tire/domain-types";
import { IdentityContractEvidence } from "./identity-contract";
import { FrozenFieldResolutions } from "./field-authority";
import { RecallAnalysisBoundary, RecallEvidenceMeta, RecallFactScope } from "./recall-evidence-meta";
import { useWorkbenchPlatform } from "./workbench-platform";
import { useToast } from "./toast";

const stamp = (value?: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "未记录";
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "请求未完成。";
const sourceLink = (value?: string | null) => {
  try { const url = new URL(value || ""); return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : undefined; }
  catch { return undefined; }
};
type SaveAttempt = { key: string; payload: ReportCreate };
// Keep uncertain saves across dialog closes in this tab, without writing private
// titles/notes or API payloads to browser storage. A page reload still requires
// checking the authoritative report library before starting another save.
const pendingSaves = new Map<string, SaveAttempt>();

export function SaveReportDialog({ pack, analysis, onClose, onSaved }: {
  pack: AIPack; analysis?: AIAnalysis; onClose: () => void; onSaved: (report: EvidenceReportDetail) => void;
}) {
  const platform = useWorkbenchPlatform();
  const dialog = useRef<HTMLDialogElement>(null);
  const operation = useRef<AbortController | null>(null);
  const pendingId = `${pack.id}:${analysis?.id || "evidence"}`;
  const attempt = useRef<SaveAttempt | null>(pendingSaves.get(pendingId) || null);
  const [title, setTitle] = useState(attempt.current?.payload.title || "");
  const [notes, setNotes] = useState(attempt.current?.payload.notes || "");
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(!!attempt.current);
  const [error, setError] = useState("");
  const analysisMatches = !analysis || (analysis.state === "completed" && !!analysis.answer && analysis.pack_id === pack.id);
  useEffect(() => {
    const node = dialog.current;
    const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { operation.current?.abort(); node?.close(); if (focus?.isConnected && !focus.closest("dialog:not([open])")) focus.focus({ preventScroll: true }); };
  }, []);

  async function save() {
    if (operation.current || !analysisMatches || !title.trim()) return;
    const value = attempt.current || { key: crypto.randomUUID(), payload: {
      mode: "history" as const, pack_id: pack.id, analysis_id: analysis?.id || null, title: title.trim(), notes,
    } };
    attempt.current = value; pendingSaves.set(pendingId, value); setLocked(true);
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError("");
    try {
      const report = await tireApi.createReport(value.payload, value.key, controller.signal);
      if (!controller.signal.aborted) { pendingSaves.delete(pendingId); onSaved(report); onClose(); }
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(errorText(cause));
        if (cause instanceof ApiError && cause.status >= 400 && cause.status < 500) { pendingSaves.delete(pendingId); attempt.current = null; setLocked(false); }
      }
    } finally { if (operation.current === controller) operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }

  return <dialog ref={dialog} className="fact-review-dialog report-save-dialog" aria-labelledby="report-save-title"
    onCancel={event => { event.preventDefault(); event.stopPropagation(); if (!busy) onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">FROZEN EVIDENCE REPORT</span><h2 id="report-save-title">{analysis ? "保存含分析的报告" : "保存证据报告"}</h2></div><button type="button" className="text-button" disabled={busy} onClick={onClose}>关闭</button></header>
    <div className="ai-content"><p className="review-boundary">报告保存在{platform.sessionLabel}的本地报告库。报告包含个人标题、备注或问题，统一按私有材料保存。正文固定保存已预览的来源、事实与冲突{analysis ? "，以及同一证据包已经完成的分析" : ""}，始终作为历史记录；保存不调用模型、不产生新的 AI 请求。</p>
      <RecallAnalysisBoundary boundary={pack.recall_boundary} pending={pack.evidence.some(evidence => evidence.evidence_type === "recall")} />
      <section className="snapshot-banner"><strong>{pack.evidence.length} 条来源 · {pack.facts.length} 个事实字段</strong><span>证据准备 {stamp(pack.created_at)} · {analysis ? pack.recall_boundary ? "包含已完成的公告事实整理，具体轮胎适用性尚未评估" : "包含已完成分析，推断仍需人工核对" : "纯证据报告，不包含模型分析"}</span></section>
      {!analysisMatches ? <p className="inline-error" role="alert">这条分析未完成或不属于当前证据包，不能合并保存。</p> : null}
      {error ? <p className="inline-error" role="alert">{error}</p> : null}
      <form className="review-form" onSubmit={event => { event.preventDefault(); void save(); }}>
        <label><span>报告标题</span><input required maxLength={160} value={title} disabled={busy || locked} onChange={event => setTitle(event.target.value)} /></label>
        <label><span>我的备注（与来源事实分别保存）</span><textarea rows={4} maxLength={4000} value={notes} disabled={busy || locked} onChange={event => setNotes(event.target.value)} /></label>
        {locked ? <p className="review-boundary" role="status">保存内容和请求标识已固定。网络异常后核对沿用同一标识；关闭后重新打开同一保存入口可继续核对。若已重新加载页面，请先到报告库确认记录。</p> : null}
        <button type="submit" className="primary-button" disabled={busy || !analysisMatches || !title.trim()}>{busy ? "正在保存…" : locked ? "核对同一次保存结果" : "保存报告（不调用模型）"}</button>
      </form>
    </div>
  </dialog>;
}

function FrozenReportBody({ report }: { report: EvidenceReportDetail }) {
  const { body } = report;
  function citation(kind: "fact" | "source", id: string) {
    const node = document.getElementById(`report-${report.id}-${kind}-${id}`);
    let parent = node?.parentElement;
    while (parent) { if (parent instanceof HTMLDetailsElement) parent.open = true; parent = parent.parentElement; }
    node?.scrollIntoView({ block: "center" }); node?.focus({ preventScroll: true });
  }
  const claims = body.analysis?.claims || [];
  const recallPack = body.evidence.some(evidence => evidence.evidence_type === "recall");
  return <section className="report-frozen-body" aria-label="冻结报告正文">
    <div className="snapshot-banner"><strong>LOCAL SNAPSHOT · 冻结报告正文</strong><span>证据包准备于 {stamp(body.source_pack.created_at)}；准备时状态 {body.source_pack.data_state}，原始证据包分类为{body.source_pack.privacy_class === "public" ? "公开来源" : "非公开材料"}。报告整体仍按私有材料保存；打开报告不代表重新在线核验。</span></div>
    <p className="review-boundary">{body.notice}</p>
    <RecallAnalysisBoundary boundary={body.recall_boundary} pending={recallPack} />
    <details className="report-hashes"><summary>正文与证据包校验值</summary><p>正文 SHA-256 <code>{report.body_hash}</code></p><p>证据包 <code>{body.source_pack.id}</code></p><p>证据包指纹 <code>{body.source_pack.fingerprint}</code></p></details>
    <h3>来源与原始事实</h3>
    {body.evidence.map(source => <section className="ai-evidence" key={source.id} id={`report-${report.id}-source-${source.id}`} tabIndex={-1}>
      {source.kind === "tire" || source.identity_contract ? <IdentityContractEvidence contract={source.identity_contract} historical /> : null}
      <h4>{source.id} · {source.label}</h4><RecallEvidenceMeta evidence={source} />
      <p>观察 {stamp(source.observed_at)} · 验证 {stamp(source.verified_at)}{source.revision ? ` · 修订 #${source.revision}` : ""}</p>
      <p>{source.source_id || "人工记录"} · {source.parser_version || "未记录解析器"}</p>
      {source.snapshot_id ? <p>快照 <code>{source.snapshot_id}</code></p> : null}
      {source.event_id ? <p>测试事件 <code>{source.event_id}</code></p> : null}
      {source.raw_hash ? <p>来源 SHA-256 <code>{source.raw_hash}</code></p> : null}
      <p>{sourceLink(source.source_url) ? <a href={sourceLink(source.source_url)} target="_blank" rel="noopener noreferrer">打开原始来源</a> : "来源链接不可安全打开"}</p>
      {source.kind === "change_event" ? <div className="ai-change-provenance"><p>历史变化记录于 {stamp(source.change_observed_at)}；首次观察不代表产品新发布。</p>{source.previous_snapshot_id ? <><p>变化前快照 <code>{source.previous_snapshot_id}</code> · 观察 {stamp(source.previous_observed_at)}</p><p>变化前 SHA-256 <code>{source.previous_raw_hash || "未记录"}</code></p>{sourceLink(source.previous_source_url) ? <a href={sourceLink(source.previous_source_url)} target="_blank" rel="noopener noreferrer">打开变化前来源</a> : null}</> : <p>此前没有已采纳快照。</p>}</div> : null}
      <details open><summary>引用字段</summary><dl>{body.facts.filter(fact => fact.evidence_id === source.id).map(fact => <div key={fact.id} id={`report-${report.id}-fact-${fact.id}`} tabIndex={-1}><dt>{fact.id} · {fact.field}<RecallFactScope fact={fact} evidence={source} /></dt><dd>{fact.text}</dd></div>)}</dl></details>
    </section>)}
    <FrozenFieldResolutions resolutions={body.field_resolutions} policy={body.field_policy} context="saved" />
    {body.conflicts.length ? <section className="source-conflict"><h3>来源冲突 · 未裁定</h3><p>这些冲突随正文冻结保存；模型解释不会自动裁定。</p><details><summary>原始冲突记录</summary><pre>{JSON.stringify(body.conflicts, null, 2)}</pre></details></section> : <p className="review-boundary">所保存的证据包没有记录来源冲突。</p>}
    {body.analysis ? <section className="report-analysis"><h3>已完成的证据分析</h3><p className="draft-original">{body.analysis.question}</p><p>{body.analysis.model} · 完成 {stamp(body.analysis.completed_at)} · {body.analysis.usage ? `${body.analysis.usage.total_tokens} tokens` : "原调用用量未确认"}</p>
      {(recallPack ? ["fact"] as const : ["fact", "inference"] as const).map(kind => <section key={kind}><h4>{kind === "fact" ? "引用事实" : "模型推断 · 需人工核对"}</h4>{claims.filter(claim => claim.type === kind).map((claim, index) => <article className={`ai-claim ${kind}`} key={index}><p>{claim.text}</p><div className="variant-actions">{claim.fact_ids.map(id => <button type="button" className="text-button" key={id} disabled={!body.facts.some(fact => fact.id === id)} onClick={() => citation("fact", id)}>核对字段 {id}</button>)}{claim.evidence_ids.map(id => <button type="button" className="text-button" key={id} disabled={!body.evidence.some(source => source.id === id)} onClick={() => citation("source", id)}>核对来源 {id}</button>)}</div></article>)}{!claims.some(claim => claim.type === kind) ? <p>这份分析没有此类内容。</p> : null}</section>)}
      {!recallPack ? <section className="ai-claim inference"><h4>模型报告的不确定性</h4><p>{body.analysis.uncertainty || "未另行陈述；不表示不存在不确定性。"}</p></section> : null}
    </section> : <p className="review-boundary">这是一份纯证据报告，没有保存模型分析。</p>}
  </section>;
}

export default function ReportsDialog({ initialId, onClose }: { initialId?: string; onClose: () => void }) {
  const toast = useToast();
  const platform = useWorkbenchPlatform();
  const dialog = useRef<HTMLDialogElement>(null);
  const listPane = useRef<HTMLElement>(null);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const focusDetail = useRef(!!initialId);
  const listRequest = useRef<AbortController | null>(null);
  const operation = useRef<AbortController | null>(null);
  const [archived, setArchived] = useState(false);
  const [items, setItems] = useState<EvidenceReportRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [listRevision, setListRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [moreBusy, setMoreBusy] = useState(false);
  const [listError, setListError] = useState("");
  const [selectedId, setSelectedId] = useState(initialId || "");
  const [detailRevision, setDetailRevision] = useState(0);
  const [detail, setDetail] = useState<EvidenceReportDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [exportRevision, setExportRevision] = useState(1);
  const [format, setFormat] = useState<ReportFormat>("markdown");
  const [downloaded, setDownloaded] = useState<ReportExport | null>(null);
  const [saveCancelled, setSaveCancelled] = useState(false);
  function accept(value: EvidenceReportDetail) { setDetail(value); setTitle(value.title); setNotes(value.notes); setExportRevision(value.revision); setStale(false); }

  useEffect(() => {
    const node = dialog.current;
    const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { operation.current?.abort(); node?.close(); if (focus?.isConnected) focus.focus({ preventScroll: true }); };
  }, []);

  useEffect(() => {
    const controller = new AbortController(); listRequest.current = controller; setLoading(true); setListError(""); setMoreBusy(false); setItems([]); setTotal(0);
    void tireApi.reports(archived, controller.signal).then(value => {
      if (!controller.signal.aborted) { setItems(value.items); setTotal(value.total); }
    }).catch(cause => { if (!controller.signal.aborted) setListError(errorText(cause)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [archived, listRevision]);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController(); setDetailLoading(true); setDetail(null); setError(""); setDownloaded(null); setSaveCancelled(false); setStale(false);
    void tireApi.report(selectedId, controller.signal).then(value => { if (!controller.signal.aborted) accept(value); })
      .catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); }).finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [selectedId, detailRevision]);

  useEffect(() => {
    if (!detailLoading && detail && focusDetail.current) {
      focusDetail.current = false;
      detailHeading.current?.focus({ preventScroll: true });
      detailHeading.current?.scrollIntoView({ block: "start" });
    }
  }, [detail, detailLoading]);

  function selectReport(id: string) {
    if (id === selectedId && detail) {
      detailHeading.current?.focus({ preventScroll: true });
      detailHeading.current?.scrollIntoView({ block: "start" });
    } else { focusDetail.current = true; setSelectedId(id); }
  }

  async function more() {
    const controller = listRequest.current;
    if (!controller || controller.signal.aborted || loading || moreBusy) return;
    setMoreBusy(true); setListError("");
    try {
      const value = await tireApi.reports(archived, controller.signal, items.length);
      if (!controller.signal.aborted) { setItems(previous => [...new Map([...previous, ...value.items].map(item => [item.id, item])).values()]); setTotal(value.total); }
    } catch (cause) { if (!controller.signal.aborted) setListError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setMoreBusy(false); }
  }

  async function perform(work: (signal: AbortSignal) => Promise<void>) {
    if (operation.current) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError("");
    try { await work(controller.signal); }
    catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (operation.current === controller) operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }

  async function mutate(action: "metadata" | "archive" | "restore") {
    if (!detail || stale) return;
    await perform(async signal => {
      try {
        const value = action === "metadata" ? await tireApi.editReport(detail.id, detail.revision, title.trim(), notes, signal)
          : await tireApi.reportState(detail.id, detail.revision, action, signal);
        if (!signal.aborted) { accept(value); setListRevision(previous => previous + 1); toast(action === "metadata" ? `已保存标题与备注修订 #${value.revision}。` : action === "archive" ? "报告已归档，可在归档范围查看。" : "报告已恢复为未归档。", "success"); }
      } catch (cause) {
        if (!signal.aborted && (!(cause instanceof ApiError) || cause.status === 409 || cause.status >= 500)) setStale(true);
        throw cause;
      }
    });
  }

  async function download() {
    if (!detail || !Number.isInteger(exportRevision) || exportRevision < 1 || exportRevision > detail.revision) return;
    const requested = { reportId: detail.id, revision: exportRevision, format };
    await perform(async signal => {
      setDownloaded(null);
      setSaveCancelled(false);
      const artifact = await tireApi.exportReport(requested.reportId, requested.revision, requested.format, signal);
      const mediaTypes: Record<ReportFormat, string> = { markdown: "text/markdown", html: "text/html", pdf: "application/pdf" };
      if (artifact.report_id !== requested.reportId || artifact.revision !== requested.revision || artifact.format !== requested.format
        || !/^[a-f0-9]{64}$/i.test(artifact.sha256) || !Number.isSafeInteger(artifact.byte_count) || artifact.byte_count < 1
        || artifact.content_type.split(";")[0].trim().toLowerCase() !== mediaTypes[requested.format]) throw new Error("导出记录与所选报告、修订或格式不匹配，未下载。");
      const blob = await tireApi.reportExportContent(requested.reportId, artifact.id, requested.revision, signal);
      if (blob.size !== artifact.byte_count || blob.type.split(";")[0].trim().toLowerCase() !== mediaTypes[requested.format]) throw new Error("文件大小或类型校验失败，未下载。");
      if (!crypto.subtle) throw new Error("当前浏览器无法校验文件完整性，未下载。");
      const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
      const actual = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, "0")).join("");
      if (actual !== artifact.sha256.toLowerCase()) throw new Error("文件 SHA-256 校验失败，未下载。");
      if (signal.aborted) return;
      const filename = `tire-report-${requested.reportId.replace(/[^a-z0-9-]/gi, "").slice(0, 64)}-r${requested.revision}.${requested.format === "markdown" ? "md" : requested.format}`;
      const result = await platform.saveDownload({ blob, filename, signal });
      if (signal.aborted) return;
      if (result.saved) setDownloaded(artifact);
      else setSaveCancelled(true);
      setDetail(previous => previous?.id === requested.reportId ? { ...previous, exports: [artifact, ...previous.exports.filter(item => item.id !== artifact.id)].sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at)).slice(0, 100) } : previous);
    });
  }

  return <dialog ref={dialog} className="fact-review-dialog reports-dialog" aria-labelledby="reports-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">REPORT LIBRARY</span><h2 id="reports-title">证据报告库</h2></div><button type="button" className="icon-button" aria-label="关闭报告库" onClick={onClose}>×</button></header>
    <div className="reports-content"><p className="review-boundary">仅显示{platform.sessionLabel}保存的报告。正文保留历史证据与原分析；标题、备注和归档状态另行记录修订。打开、编辑与导出不会调用模型。</p>
      <div className="reports-layout"><section className="reports-list" aria-label="报告列表" ref={listPane} tabIndex={-1}><div className="report-list-controls"><label><span>报告范围</span><select value={archived ? "archived" : "active"} disabled={busy || moreBusy} onChange={event => setArchived(event.target.value === "archived")}><option value="active">未归档报告</option><option value="archived">已归档报告</option></select></label><button type="button" className="text-button" disabled={busy || loading || moreBusy} onClick={() => setListRevision(value => value + 1)}>刷新列表</button></div>
        {listError ? <p className="inline-error" role="alert">{listError}</p> : null}
        {loading ? <p role="status">正在读取报告…</p> : <><p className="report-count">共 {total} 份报告</p>{items.map(item => <button type="button" className={`report-list-item${selectedId === item.id ? " selected" : ""}`} key={item.id} disabled={busy} aria-pressed={selectedId === item.id} onClick={() => selectReport(item.id)}><strong>{item.title}</strong><small>修订 #{item.revision} · {item.analysis_id ? "含证据分析" : "纯证据"}</small><small>{stamp(item.updated_at)}</small></button>)}{!items.length ? <p className="quality-empty">此范围暂无报告。在证据分析窗口预览证据后，可保存纯证据报告或已完成的分析。</p> : null}{items.length < total ? <button type="button" className="secondary-button" disabled={moreBusy || busy} onClick={() => void more()}>{moreBusy ? "正在加载…" : "加载更多报告"}</button> : null}</>}
      </section><section className="report-detail" aria-label="报告详情">
        {error ? <p className="inline-error" role="alert">{error}</p> : null}
        {selectedId ? <div className="variant-actions"><button type="button" className="text-button" onClick={() => { listPane.current?.focus({ preventScroll: true }); listPane.current?.scrollIntoView({ block: "start" }); }}>返回报告列表</button><button type="button" className="text-button" disabled={busy || detailLoading} onClick={() => setDetailRevision(value => value + 1)}>重新读取这份报告</button></div> : null}
        {detailLoading ? <p role="status">正在读取冻结报告与修订…</p> : detail ? <>
          <div className="quality-item-heading"><h3 ref={detailHeading} tabIndex={-1}>{detail.title}</h3><span className="tag quiet">{detail.archived ? "已归档" : "已保存"} · #{detail.revision}</span></div>
          <p>保存 {stamp(detail.created_at)} · 私有报告 · {platform.sessionLabel}可见</p>
          <section className="report-lifecycle" aria-label="读取时的版本状态"><strong>读取时版本状态 · 与冻结正文分别展示</strong>{detail.current_lifecycle.length ? <ul>{detail.current_lifecycle.map(row => <li key={row.variant_id}>规格 <code>{row.variant_id}</code> · {row.state === "revoked" ? "已撤销，使用报告前请核对此版本" : row.state === "active" ? "未标记撤销" : row.state} · 状态修订 #{row.revision}</li>)}</ul> : <p>这份报告没有可显示的轮胎生命周期状态。</p>}<p>这里的状态提醒不会修改下方历史正文，也不证明来源参数仍有效。</p></section>
          <details className="report-metadata"><summary>编辑标题、备注与归档状态</summary>{stale ? <p role="alert" className="inline-error">修订已变化或保存结果未确认。请重新读取报告，再继续编辑。</p> : null}
            <form className="review-form" onSubmit={event => { event.preventDefault(); void mutate("metadata"); }}><label><span>报告标题</span><input required maxLength={160} disabled={busy || stale || detail.archived} value={title} onChange={event => setTitle(event.target.value)} /></label><label><span>我的备注（不会修改来源事实）</span><textarea rows={4} maxLength={4000} disabled={busy || stale || detail.archived} value={notes} onChange={event => setNotes(event.target.value)} /></label><div className="variant-actions">{!detail.archived ? <button type="submit" className="primary-button" disabled={busy || stale || !title.trim()}>保存标题与备注修订</button> : null}<button type="button" className="secondary-button" disabled={busy || stale} onClick={() => void mutate(detail.archived ? "restore" : "archive")}>{detail.archived ? "恢复报告" : "归档报告"}</button></div></form>
          </details>
          {detail.notes ? <section className="report-notes"><h4>我的备注 · 修订 #{detail.revision}</h4><p className="draft-original">{detail.notes}</p></section> : null}
          <section className="report-download" aria-label="导出选定修订"><h3>下载报告</h3><p>先生成或复用所选修订的文件，再校验大小与 SHA-256。HTML 只下载，不在网页中自动打开。</p><div className="report-export-controls"><label><span>标题与备注修订</span><input type="number" min={1} max={detail.revision} step={1} value={Number.isFinite(exportRevision) ? exportRevision : ""} disabled={busy} onChange={event => setExportRevision(event.target.valueAsNumber)} /></label><label><span>文件格式</span><select value={format} disabled={busy} onChange={event => setFormat(event.target.value as ReportFormat)}><option value="markdown">Markdown（.md）</option><option value="html">HTML（.html）</option><option value="pdf">PDF（.pdf）</option></select></label><button type="button" className="primary-button" disabled={busy || !Number.isInteger(exportRevision) || exportRevision < 1 || exportRevision > detail.revision} onClick={() => void download()}>{busy ? "正在处理…" : "校验并下载"}</button></div>
            {Number.isInteger(exportRevision) && exportRevision >= 1 && exportRevision <= detail.revision ? <p>将导出修订 #{exportRevision}：{detail.metadata_history.find(row => row.revision === exportRevision)?.title || "该旧修订超出最近历史窗口，下载仍使用其原有标题与备注"}。冻结事实与分析正文保持不变。</p> : null}
            {saveCancelled ? <p role="status">已取消保存；导出文件记录仍保留在报告库中。</p> : null}{downloaded ? <p role="status">已校验修订 #{downloaded.revision} 的 {downloaded.format.toUpperCase()}，{downloaded.byte_count.toLocaleString()} 字节，{platform.kind !== "web" ? "并已保存到所选位置" : "并交由浏览器下载"}。SHA-256 <code>{downloaded.sha256}</code></p> : null}
            {detail.exports.length ? <details><summary>最近生成文件记录（{detail.exports.length} 条，最多显示 100 条）</summary><p>更早的文件仍可按报告修订与格式生成或复用，不受此展示窗口限制。</p>{detail.exports.map(item => <p key={item.id}>修订 #{item.revision} · {item.format.toUpperCase()} · {item.byte_count.toLocaleString()} 字节 · {stamp(item.created_at)}<br /><code>{item.sha256}</code></p>)}</details> : null}
          </section>
          <details className="report-history"><summary>标题、备注与状态历史{detail.history_truncated ? "（最近记录）" : ""}</summary>{detail.metadata_history.map(row => <article key={row.revision}><h4>修订 #{row.revision} · {row.archived ? "归档" : "未归档"} · {stamp(row.created_at)}</h4><p>{row.title}</p><p className="draft-original">{row.notes || "没有备注"}</p><button type="button" className="text-button" disabled={busy} onClick={() => setExportRevision(row.revision)}>选择此修订用于下载</button></article>)}</details>
          <FrozenReportBody report={detail} />
        </> : !selectedId ? <p className="quality-empty">选择一份报告，查看冻结事实、分析引用与修订。</p> : null}
      </section></div>
    </div>
  </dialog>;
}
