"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, ExactJsonNumber, tireApi } from "@tire/api-client";
import type { ParserBundle, ParserPage, QualityReport, RawCaptureRecord, ReparseCatalog, ReparseCreate, ReparseDetail, ReparseReviewStatus, ReparseSummary } from "@tire/domain-types";

const stamp = (value?: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "未记录";
const bytes = (value?: number) => typeof value === "number" ? `${value.toLocaleString("zh-CN")} 字节` : "未报告";
const states = { pending: "执行结果待确认", unknown: "执行结果未知", completed: "历史解析完成", failed: "历史解析失败" };
const reviewLabels: Record<ReparseReviewStatus, string> = { reviewed: "已审阅", needs_fix: "需修复", rejected: "不认可" };
const errors: Record<string, string> = {
  parser_deployment_changed: "已部署 Parser 已变化。请刷新目录，重新核对版本与代码指纹。",
  capture_integrity_failed: "历史原文缺失或完整性校验失败。此次结果已记录，未使用其他正文替代。",
  unsupported_reparse_source: "这份原文没有可用的固定 Parser，不能重解析。",
  capture_query_mismatch: "原文与原查询范围不匹配，未执行重解析。",
  capture_source_metadata_mismatch: "原文来源信息不匹配，未执行重解析。",
  reparse_not_completed: "执行结果尚未完成，暂不能追加审阅。",
  parser_timeout: "解析超时，未采纳任何候选。",
  parser_output_too_large: "解析输出超过限制，未采纳任何候选。",
  parser_failed: "解析进程失败，未采纳任何候选。",
  parser_catalog_unavailable: "暂时无法读取固定 Parser 目录；已有任务仍可在下方核对。",
  candidate_validation_failed: "解析输出未通过候选结构或身份检查，未生成可用候选。",
  reparse_review_revision_conflict: "审阅修订已变化，请重新读取任务并核对最新记录。",
  reparse_integrity_failed: "冻结任务或结果的完整性校验失败，未展示结果。",
  idempotency_payload_mismatch: "此请求标识已绑定其他输入；请保留标识并核对历史记录。",
  reparse_not_found: "未找到所选历史任务，请刷新历史列表核对。",
  capture_not_found: "未找到原文收件记录，请返回接收日志核对。",
  reparse_baseline_too_large: "当前对照基线超过本轮大小限制，未创建重解析任务。",
  parser_isolation_unavailable: "执行环境无法建立所需的进程限制，未执行解析。",
  parser_code_mismatch: "实际执行代码与固定指纹不一致，结果已拒收。",
  parser_version_mismatch: "实际执行版本与固定请求不一致，结果已拒收。",
  parser_protocol_invalid: "子进程输出未通过协议校验，结果已拒收。",
  parser_input_too_large: "原文超过执行大小上限，未执行解析。",
  parser_cleanup_failed: "进程回收未完成，结果已拒收，请核对运行环境。",
};
export const qualityLabels: Record<string, string> = {
  field_loss_threshold: "已知字段缺失达到阈值", row_loss_threshold: "记录缺失达到阈值",
  ambiguous_alignment: "记录无法可靠对齐", tire_identity_changed: "精确轮胎身份变化",
  vehicle_identity_changed: "车型身份变化",
  recall_member_loss: "召回公告、关联产品或附件成员缺失",
  recall_safety_field_loss: "已知召回安全字段缺失",
  recall_identity_changed: "公告或关联产品标识变化（不代表适用性结论）",
  recall_pagination_changed: "召回检索分页范围变化",
  recall_payload_kind_changed: "公告详情与检索结果结构不一致",
};
export const qualityGroupLabels: Record<string, string> = {
  vehicle: "车型", trims: "配置", fitments: "轮毂与轴位", products: "检索关联产品",
  campaigns: "召回公告", documents: "公告附件", associated_products: "公告关联产品",
};
export function targetLabel(kind: RawCaptureRecord["target_kind"], query?: Record<string, unknown>) {
  if (kind === "recall") {
    if (typeof query?.search === "string") return "召回检索页（候选）";
    if (typeof query?.campaign_number === "string") return "召回公告";
    return "召回原文";
  }
  return kind === "vehicle" ? "车型" : "轮胎";
}
export function queryScope(query: Record<string, unknown>) {
  if (typeof query.campaign_number === "string") return `公告编号 ${query.campaign_number}`;
  if (typeof query.search === "string") return `检索 ${query.search} · 分页起点 ${String(query.offset ?? "未记录")}`;
  return null;
}
const errorText = (cause: unknown) => cause instanceof ApiError && cause.code
  ? errors[cause.code] || `操作未完成（${cause.code}）。请核对历史记录。`
  : cause instanceof Error ? cause.message : "操作未完成，请核对历史记录。";
type Attempt = { key: string; payload: ReparseCreate; runId?: string };
// Unknown submissions survive closing/reopening this capture within the tab.
// Never persist source data or review text in browser storage.
const pendingAttempts = new Map<string, Attempt>();

export function DataTree({ label, value }: { label: string; value: unknown }) {
  const [opened, setOpened] = useState(false);
  const [page, setPage] = useState(0);
  const compound = value !== null && typeof value === "object" && !(value instanceof ExactJsonNumber);
  const entries = compound ? Object.entries(value as Record<string, unknown>) : [];
  const text = compound ? "" : typeof value === "string" ? value : value instanceof ExactJsonNumber || typeof value === "bigint" ? String(value) : JSON.stringify(value) ?? "未提供";
  const count = compound ? entries.length : text.length;
  const size = compound ? 10 : 1200;
  const pageCount = Math.max(1, Math.ceil(count / size));
  const current = Math.min(page, pageCount - 1);
  return <details className="reparse-data" onToggle={event => setOpened(event.currentTarget.open)}>
    <summary>{label} <span>{compound ? `${Array.isArray(value) ? "列表" : "对象"} · ${count} 项` : count > size ? `${count} 字符` : "查看值"}</span></summary>
    {opened ? <div className="reparse-data-content">{compound ? count ? entries.slice(current * size, (current + 1) * size).map(([key, child]) => <DataTree key={key} label={Array.isArray(value) ? `第 ${Number(key) + 1} 项` : key} value={child} />) : <p>空{Array.isArray(value) ? "列表" : "对象"}</p> : <pre>{text.slice(current * size, (current + 1) * size)}</pre>}
      {pageCount > 1 ? <div className="reparse-pages"><button type="button" className="text-button" disabled={current === 0} onClick={() => setPage(current - 1)}>上一段</button><span>第 {current + 1} / {pageCount} 段 · 每段最多 {size} {compound ? "项" : "字符"}，内容未省略</span><button type="button" className="text-button" disabled={current + 1 >= pageCount} onClick={() => setPage(current + 1)}>下一段</button></div> : null}
    </div> : null}
  </details>;
}

export function QualityMetrics({ value, label }: { value: QualityReport; label: string }) {
  return <section className="reparse-quality-metrics" aria-label={label}><h4>{label}</h4><dl>
    <div><dt>记录缺失 / 基线记录</dt><dd>{value.lost_rows} / {value.baseline_rows}{value.baseline_rows ? ` · ${(value.row_loss_ratio * 100).toFixed(1)}%` : " · 无分母"}</dd></div>
    <div><dt>字段缺失 / 已对齐的已知字段</dt><dd>{value.lost_field_count} / {value.known_fields}{value.known_fields ? ` · ${(value.field_loss_ratio * 100).toFixed(1)}%` : " · 无分母"}</dd></div>
    <div><dt>已对齐 / 候选记录</dt><dd>{value.aligned_rows} / {value.candidate_rows}</dd></div>
  </dl><p>{value.ruleset.startsWith("recall-field-loss@") ? "召回规则对任何已知成员或字段缺失触发质量阻断，比例仅供核对；标识、对齐与分页范围问题另行判断。" : <>任一缺失比例达到或超过 {(value.threshold * 100).toFixed(0)}% 时触发质量阻断；身份与对齐问题另行判断。</>}</p></section>;
}

function FrozenResult({ run }: { run: ReparseDetail }) {
  const completed = run.completion;
  const recall = run.input.target_kind === "recall";
  return <div className="reparse-frozen">
    <p className="review-boundary">此历史结果的代码来源：{run.parser.bundle_id ? <>已封存包 <code>{run.parser.bundle_id}</code></> : "任务创建时的当前安装源码（未指定历史封存包）"}。与上方新任务选择分别记录。</p>
    <div className="snapshot-banner"><strong>LOCAL SNAPSHOT · 始终未采纳</strong><span>这是已保存原文的历史解析结果；不会更新正式记录、在线核验时间、比较或监控提醒。</span></div>
    <dl className="quality-detail-meta reparse-meta"><div><dt>原文观察时间</dt><dd>{stamp(run.input.observed_at)}</dd></div><div><dt>重解析任务预留时间</dt><dd>{stamp(run.started_at || run.created_at)}</dd></div><div><dt>重解析完成时间</dt><dd>{stamp(completed?.completed_at)}</dd></div><div><dt>执行 Parser 版本</dt><dd>{run.parser.version}</dd></div><div><dt>原文存储类型</dt><dd>{run.input.storage_kind}</dd></div><div><dt>原查询范围</dt><dd>{run.input.source_id} · {targetLabel(run.input.target_kind, run.input.query)}</dd></div></dl>
    {recall ? <p className="review-boundary">本次{targetLabel(run.input.target_kind, run.input.query)}解析结果的适用性始终未评估（not_assessed）；不判断精确轮胎 SKU 或 DOT/TIN 是否受影响。空响应、成员减少或解析差异不表示风险解除。{queryScope(run.input.query)}</p> : null}
    <details className="reparse-technical"><summary>来源、版本与完整性凭据</summary><dl className="quality-detail-meta"><div><dt>来源地址（仅作文字核对）</dt><dd>{run.input.source_url}</dd></div><div><dt>原文 SHA-256</dt><dd><code>{run.input.raw_hash}</code></dd></div><div><dt>执行代码指纹</dt><dd><code>{run.parser.digest}</code></dd></div><div><dt>原收件 Parser 版本</dt><dd>{run.input.original_parser_version}</dd></div><div><dt>候选内容指纹</dt><dd><code>{completed?.candidate_hash || "未生成候选"}</code></dd></div></dl><DataTree label="原查询条件" value={run.input.query} />{completed ? <DataTree label="受限进程执行回执" value={completed.receipt} /> : null}</details>
    {run.state === "pending" || run.state === "unknown" ? <p className="review-boundary" role="status">{run.state === "unknown" ? "服务端暂时无法确认这次执行的最终结果。" : "已记录本次任务，执行结果仍待确认。"}重新读取或核对只跟踪同一次任务，不自动重新运行。</p> : null}
    {completed?.error_code ? <p className="inline-error" role="alert">{errors[completed.error_code] || "此次重解析未完成，未生成可用历史候选。"} <code>{completed.error_code}</code></p> : null}
    <section className="reparse-baseline"><h4>本次冻结的对照基线</h4>{run.baseline ? <><p>快照 <code>{run.baseline.snapshot_id}</code></p><p>基线原文观察 {stamp(run.baseline.observed_at)} · 基线原核验 {stamp(run.baseline.verified_at)}</p><p>基线选取 {stamp(run.baseline.selected_at)} · 基线 Parser {run.baseline.parser_version}</p><p className={run.baseline_current ? "review-boundary" : "inline-error"}>{run.baseline_current ? "读取时仍是同一已采纳基线；这不表示重解析结果已被采纳。" : "读取时已采纳基线已变化。下方差异只针对此次冻结基线，不代表与当前正式记录的差异。"}</p><DataTree label="冻结基线结构" value={run.baseline.payload} /></> : <p>任务创建时没有可用的已采纳基线，不能据此声称完成了历史缺失比较。</p>}</section>
    {completed?.quality ? <section className="reparse-quality"><h4>质量核对 · {completed.quality_blocked ? "有阻断项" : "未触发当前质量规则"}</h4><p>质量检查不是人工核验或正式采纳。缺失分母使用本次冻结基线；各分组单独判断。</p><QualityMetrics value={completed.quality} label="本次比较分母" />{Object.entries(completed.quality.groups || {}).slice(0, 10).map(([name, value]) => <QualityMetrics key={name} value={value} label={`分组 ${qualityGroupLabels[name] || name}`} />)}{completed.quality_reason_codes.length ? <p>原因：{completed.quality_reason_codes.map(code => qualityLabels[code] || code).join("、")}</p> : null}<DataTree label="质量报告与缺失字段" value={completed.quality} /></section> : completed ? <p className="review-boundary">未生成质量比较结果，不表示质量检查通过。</p> : null}
    {completed && completed.candidate !== null ? <section><h4>未采纳的历史候选</h4><p>以下内容按需展开，每层每段最多 10 项；长文本另行分段。所有来源内容均作为文本显示。</p><DataTree label="候选结构" value={completed.candidate} /></section> : null}
    {completed?.diff ? <section><h4>相对冻结基线的差异</h4><p>字段的缺失与明确未知（null）分别保留；解析变化不等于官网内容发生了变更。</p><p>新增记录 {completed.diff.added_row_keys.length} · 移除记录 {completed.diff.removed_row_keys.length} · 变化字段 {completed.diff.total_changed_fields} · 身份变化记录 {completed.diff.identity_changed_row_keys.length}</p>{!completed.diff.baseline_available ? <p className="review-boundary">没有旧基线；这里的新增只表示当前候选中出现，不代表来源刚发布了这些记录。</p> : null}{completed.diff.truncated ? <p className="inline-error">差异字段达到服务端展示上限，只返回部分差异；完整候选和冻结基线仍可分别核对。</p> : null}<DataTree label="字段差异与新增、移除记录" value={completed.diff} /></section> : null}
    <p className="review-boundary">{run.notice}</p>
  </div>;
}

export default function ReparseReviewDialog({ capture, sourceName, onClose }: { capture: RawCaptureRecord; sourceName: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const listPane = useRef<HTMLElement>(null);
  const focusDetail = useRef(false);
  const operation = useRef<AbortController | null>(null);
  const attemptRef = useRef<Attempt | null>(pendingAttempts.get(capture.id) || null);
  const [attempt, setAttempt] = useState(attemptRef.current);
  const [catalog, setCatalog] = useState<ReparseCatalog | null>(null);
  const [bundleId, setBundleId] = useState(attemptRef.current?.payload.bundle_id || "");
  const [bundles, setBundles] = useState<ParserPage<ParserBundle> | null>(null);
  const [bundleOffset, setBundleOffset] = useState(0);
  const [bundleError, setBundleError] = useState("");
  const [catalogRevision, setCatalogRevision] = useState(0);
  const [catalogError, setCatalogError] = useState("");
  const [parserChoice, setParserChoice] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [items, setItems] = useState<ReparseSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [listRevision, setListRevision] = useState(0);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [selectedId, setSelectedId] = useState(attemptRef.current?.runId || "");
  const [detailRevision, setDetailRevision] = useState(0);
  const [run, setRun] = useState<ReparseDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [operator, setOperator] = useState("");
  const [reason, setReason] = useState("");
  const [reviewStatus, setReviewStatus] = useState<ReparseReviewStatus>("reviewed");
  const [reviewConfirmed, setReviewConfirmed] = useState(false);
  const parsers = (catalog?.parsers || []).filter(parser => parser.source_id === capture.source_id && parser.target_kind === capture.target_kind);
  const parser = parsers.find(value => `${value.parser_version}:${value.parser_digest}` === parserChoice) || (!parserChoice ? parsers[0] : undefined);

  function remember(value: Attempt | null) {
    attemptRef.current = value; setAttempt(value);
    if (value) pendingAttempts.set(capture.id, value); else pendingAttempts.delete(capture.id);
  }
  function accept(value: ReparseDetail) {
    if (value.input.capture_id !== capture.id || value.input.source_id !== capture.source_id || value.input.target_kind !== capture.target_kind
      || value.input.raw_hash !== capture.raw_hash || value.input.byte_count !== capture.byte_count
      || value.data_state !== "local_snapshot" || value.accepted_as_facts !== false) throw new Error("返回结果与所选历史原文不匹配，未展示。");
    setRun(value); setStale(false); setReviewConfirmed(false);
    const active = attemptRef.current;
    if (active?.runId === value.id) {
      if (value.state === "completed" || value.state === "failed") remember(null);
    }
  }

  useEffect(() => {
    const node = dialog.current;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { operation.current?.abort(); node?.close(); if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true }); };
  }, []);
  useEffect(() => {
    const controller = new AbortController(); setCatalog(null); setCatalogError(""); setConfirmed(false); setParserChoice("");
    void tireApi.reparseCatalog(controller.signal, bundleId || undefined).then(value => { if (!controller.signal.aborted) setCatalog(value); })
      .catch(cause => { if (!controller.signal.aborted) setCatalogError(errorText(cause)); });
    return () => controller.abort();
  }, [catalogRevision, bundleId]);
  useEffect(() => {
    const controller = new AbortController(); setBundles(null); setBundleError("");
    void tireApi.parserBundles(controller.signal, bundleOffset).then(value => { if (!controller.signal.aborted) setBundles(value); })
      .catch(cause => { if (!controller.signal.aborted) setBundleError(errorText(cause)); });
    return () => controller.abort();
  }, [catalogRevision, bundleOffset]);
  useEffect(() => {
    const controller = new AbortController(); setListLoading(true); setListError(""); setItems([]);
    void tireApi.reparses(capture.id, controller.signal, offset).then(value => {
      if (!controller.signal.aborted) { setItems(value.items); setTotal(value.total); }
    }).catch(cause => { if (!controller.signal.aborted) setListError(errorText(cause)); }).finally(() => { if (!controller.signal.aborted) setListLoading(false); });
    return () => controller.abort();
  }, [capture.id, offset, listRevision]);
  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController(); setRun(null); setDetailLoading(true); setError(""); setNotice(""); setReviewConfirmed(false);
    void tireApi.reparse(selectedId, controller.signal).then(value => { if (!controller.signal.aborted) { if (value.id !== selectedId) throw new Error("返回任务标识不匹配，未展示。"); accept(value); } })
      .catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); }).finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
    // Capture and selection are fixed for the lifetime of this dialog.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, detailRevision]);
  useEffect(() => {
    if (run && !detailLoading && focusDetail.current) { focusDetail.current = false; detailHeading.current?.focus({ preventScroll: true }); detailHeading.current?.scrollIntoView({ block: "start" }); }
  }, [run, detailLoading]);

  async function execute() {
    if (operation.current || (!attemptRef.current && (!catalog?.available || !parser || !confirmed))) return;
    const value = attemptRef.current || { key: crypto.randomUUID(), payload: { mode: "history" as const, capture_id: capture.id, parser_version: parser!.parser_version, parser_digest: parser!.parser_digest, ...(bundleId ? { bundle_id: bundleId } : {}) } };
    remember(value);
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError(""); setNotice("");
    try {
      const result = value.runId ? await tireApi.reparse(value.runId, controller.signal) : await tireApi.createReparse(value.payload, value.key, controller.signal);
      if (controller.signal.aborted) return;
      if ((value.runId && result.id !== value.runId) || result.parser.version !== value.payload.parser_version || result.parser.digest !== value.payload.parser_digest || (result.parser.bundle_id || "") !== (value.payload.bundle_id || "")) throw new Error("执行标识或版本与已固定请求不匹配，请保留请求标识并核对服务端记录。");
      remember({ ...value, runId: result.id }); accept(result); focusDetail.current = true;
      setSelectedId(result.id); setConfirmed(false); setOffset(0); setListRevision(current => current + 1);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(errorText(cause));
        if (cause instanceof ApiError && cause.runId) { remember({ ...value, runId: cause.runId }); focusDetail.current = true; setSelectedId(cause.runId); setListRevision(current => current + 1); }
        else if (cause instanceof ApiError && cause.code && ["parser_deployment_changed", "unsupported_reparse_source", "capture_query_mismatch", "capture_source_metadata_mismatch", "invalid_idempotency_key", "reparse_baseline_too_large"].includes(cause.code)) { remember(null); setConfirmed(false); if (cause.code === "parser_deployment_changed") setCatalogRevision(current => current + 1); }
      }
    } finally { if (operation.current === controller) operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  async function review() {
    if (!run || operation.current || stale || !reviewConfirmed || !operator.trim() || !reason.trim() || !run.completion) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError(""); setNotice("");
    try {
      const value = await tireApi.reviewReparse(run.id, { mode: "history", expected_revision: run.review_revision, status: reviewStatus, operator: operator.trim(), reason: reason.trim() }, controller.signal);
      if (!controller.signal.aborted) { if (value.id !== run.id) throw new Error("返回审阅与所选任务不匹配，请重新读取后核对。"); accept(value); setReason(""); setNotice("历史审阅已追加；候选仍未采纳，未发起在线查询。"); setListRevision(current => current + 1); }
    } catch (cause) {
      if (!controller.signal.aborted) { setError(errorText(cause)); if (!(cause instanceof ApiError) || cause.status === 409 || cause.status >= 500) setStale(true); }
    } finally { if (operation.current === controller) operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }

  return <dialog ref={dialog} className="fact-review-dialog reports-dialog reparse-dialog" aria-labelledby="reparse-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">HISTORICAL PARSER REVIEW</span><h2 id="reparse-title">历史重解析与审阅</h2></div><button type="button" className="icon-button" aria-label="关闭历史重解析" onClick={onClose}>×</button></header>
    <div className="reports-content reparse-content"><div className="snapshot-banner"><strong>LOCAL SNAPSHOT · 未采纳的历史研究</strong><span>只解析已保存原文，不重新访问来源、不调用模型。人工审阅也不会改变正式事实或授权离线回退。</span></div>
      <p>{sourceName} · {targetLabel(capture.target_kind, capture.query)}{capture.target_kind === "recall" ? "" : "原文"} · {bytes(capture.byte_count)} · 原文观察 {stamp(capture.observed_at)}</p>
      {capture.query && queryScope(capture.query) ? <p>{queryScope(capture.query)}</p> : null}
      {capture.target_kind === "recall" ? <p className="review-boundary">仅复核已保存的公告详情或检索原文；历史候选不会成为精确适用性结论，也不据空响应判断召回解除。</p> : null}
      <details className="reparse-technical"><summary>所选原文完整性信息</summary><p>收件 <code>{capture.id}</code></p><p>原文 SHA-256 <code>{capture.raw_hash}</code></p><p>原解析器 {capture.parser_version}</p><p>{capture.content_type} · {capture.source_url}</p></details>
      <section className="reparse-launch" aria-labelledby="reparse-launch-title"><div className="panel-title"><h3 id="reparse-launch-title">固定 Parser 与执行范围</h3><button type="button" className="text-button" disabled={busy || !!attempt} onClick={() => setCatalogRevision(value => value + 1)}>刷新解析器目录</button></div>
        <label className="reparse-parser-choice"><span>历史执行代码来源</span><select value={bundleId} disabled={busy || !!attempt} onChange={event => { setBundleId(event.target.value); setConfirmed(false); setCatalog(null); }}><option value="">当前安装源码（不代表活动部署）</option>{bundleId && !bundles?.items.some(item => item.id === bundleId) ? <option value={bundleId}>已固定包 {bundleId.slice(0, 12)}…</option> : null}{bundles?.items.filter(item => item.parsers.some(parser => parser.source_id === capture.source_id)).map(item => <option key={item.id} value={item.id}>封存包 {item.id.slice(0, 12)}… · {stamp(item.created_at)}</option>)}</select></label>
        {bundleError ? <p className="inline-error" role="alert">{bundleError}</p> : null}
        {bundles ? <div className="reparse-pages"><button type="button" className="text-button" disabled={busy || !!attempt || bundleOffset === 0} onClick={() => setBundleOffset(value => Math.max(0, value - 10))}>上一页封存包</button><span>已登记 {bundles.total} 个包 · 第 {Math.floor(bundleOffset / 10) + 1} 页</span><button type="button" className="text-button" disabled={busy || !!attempt || bundleOffset + bundles.items.length >= bundles.total} onClick={() => setBundleOffset(value => value + 10)}>下一页封存包</button></div> : null}
        <p className="review-boundary">{bundleId ? <>仅用已登记历史包 <code>{bundleId}</code> 重放原文，不改变活动部署。</> : "使用当前安装源码生成研究候选；活动部署可能仍指向另一份封存包。"}</p>
        <DataTree label="原收件执行身份（旧记录可能未知）" value={capture.parser_identity ?? null} />
        {catalogError ? <p className="inline-error" role="alert">{catalogError}</p> : !catalog ? <p role="status">正在读取已部署 Parser 与限制…</p> : <>
          <label className="reparse-parser-choice"><span>所选代码的来源版本</span><select value={parser ? `${parser.parser_version}:${parser.parser_digest}` : ""} disabled={busy || !!attempt || !parsers.length} onChange={event => { setParserChoice(event.target.value); setConfirmed(false); }}>{!parsers.length ? <option value="">当前来源没有可用 Parser</option> : parsers.map(value => <option key={`${value.parser_version}:${value.parser_digest}`} value={`${value.parser_version}:${value.parser_digest}`}>{value.parser_version}</option>)}</select></label>
          {parser ? <p>代码 SHA-256 <code>{parser.parser_digest}</code></p> : null}
          <p className="review-boundary"><strong>进程故障隔离</strong>：固定代码在受限子进程中执行。{parser?.network_enforced === true ? "运行环境报告已启用操作系统网络隔离。" : parser?.network_enforced === false ? "当前未启用操作系统网络沙箱，不能视为完整安全沙箱。" : "当前没有报告操作系统网络隔离状态，不能据此认定启用安全沙箱。"}不接受上传代码、任意网址或 PDF 文档。</p>
          <p>单次时限 {catalog.limits.timeout_seconds} 秒 · 输入上限 {bytes(catalog.limits.max_body_bytes)} · 输出上限 {bytes(catalog.limits.max_output_bytes)}</p>
          <details className="reparse-technical"><summary>其他执行限额与说明</summary><p>CPU {catalog.limits.cpu_seconds ?? "未报告"} 秒 · 内存 {bytes(catalog.limits.max_memory_bytes)} · 并发 {catalog.limits.max_concurrency ?? "未报告"} · 错误输出 {bytes(catalog.limits.max_stderr_bytes)}</p><p>结构化候选上限 {bytes(catalog.limits.max_candidate_bytes)} · 冻结基线上限 {bytes(catalog.limits.max_baseline_bytes)} · 超过 {catalog.limits.unknown_after_seconds ?? "未报告"} 秒没有终态则记为结果未知，不自动重跑。</p><p>{catalog.notice}</p></details>
          {!catalog.available ? <p className="inline-error">当前执行环境不可用，只能查看已有历史记录。</p> : null}
        </>}
        {attempt ? <div className="review-boundary" role="status"><p>本次请求标识已固定：<code>{attempt.key}</code></p><p>请求版本 {attempt.payload.parser_version}。网络中断或关闭窗口不会取消已提交任务；本标签页重新打开仍沿用此标识。刷新整个页面后应先核对历史列表。</p></div> : <label className="review-checkbox"><input type="checkbox" checked={confirmed} disabled={busy || !catalog?.available || !parser} onChange={event => setConfirmed(event.target.checked)} /><span>确认使用上述固定版本，仅生成未采纳的历史候选及质量差异。</span></label>}
        <button type="button" className="primary-button" disabled={busy || (!attempt && (!catalog?.available || !parser || !confirmed))} onClick={() => void execute()}>{busy ? "正在处理…" : attempt?.runId ? "核对同一次重解析状态" : attempt ? "继续 / 核对同一次重解析" : "生成历史候选（不访问来源）"}</button>
      </section>
      {error ? <p className="inline-error" role="alert">{error}</p> : null}{notice ? <p className="review-saved" role="status">{notice}</p> : null}
      <div className="reports-layout"><section className="reports-list" aria-label="此原文的重解析历史" ref={listPane} tabIndex={-1}><div className="panel-title"><h3>此原文的历史任务</h3><button type="button" className="text-button" disabled={busy || listLoading} onClick={() => setListRevision(value => value + 1)}>刷新历史</button></div><p>本地共享工作区可见 · 共 {total} 次</p>
        {listError ? <p className="inline-error" role="alert">{listError}</p> : null}{listLoading ? <p role="status">正在读取重解析历史…</p> : <>{items.map(item => <button type="button" key={item.id} className={`report-list-item${item.id === selectedId ? " selected" : ""}`} aria-pressed={item.id === selectedId} disabled={busy} onClick={() => { focusDetail.current = true; if (item.id === selectedId) setDetailRevision(value => value + 1); else setSelectedId(item.id); }}><strong>{states[item.state]}</strong><small>{item.parser.version}</small><small>{stamp(item.created_at)}</small><small>{item.latest_review ? reviewLabels[item.latest_review.status] : "尚未审阅"} · 始终未采纳</small></button>)}{!items.length ? <p className="quality-empty">此原文暂无重解析任务。</p> : null}<div className="reparse-pages"><button type="button" className="text-button" disabled={busy || offset === 0} onClick={() => setOffset(value => Math.max(0, value - 10))}>上一页</button><span>{total ? `${offset + 1}–${Math.min(offset + items.length, total)} / ${total}` : "0 条"}</span><button type="button" className="text-button" disabled={busy || offset + items.length >= total} onClick={() => setOffset(value => value + 10)}>下一页</button></div></>}
      </section><section className="report-detail" aria-label="历史重解析详情">{selectedId ? <div className="variant-actions"><button type="button" className="text-button" onClick={() => { listPane.current?.focus({ preventScroll: true }); listPane.current?.scrollIntoView({ block: "start" }); }}>返回任务列表</button><button type="button" className="text-button" disabled={busy || detailLoading} onClick={() => setDetailRevision(value => value + 1)}>重新读取任务与审阅</button></div> : null}
        {detailLoading ? <p role="status">正在核对冻结结果与最新审阅…</p> : run ? <><h3 tabIndex={-1} ref={detailHeading}>{states[run.state]} · 始终未采纳</h3><p>任务 <code>{run.id}</code> · 审阅修订 #{run.review_revision}</p><FrozenResult run={run} />
          <section className="reparse-human-review"><h3>追加历史审阅</h3><p>署名为本地自报。决定只说明对这份冻结结果的看法，不批准正式入库，不跳过 Schema、身份或质量规则。</p>{stale ? <p className="inline-error" role="alert">审阅修订已变化或保存结果未确认。请重新读取任务，再核对决定；此表单暂时锁定。</p> : null}
            {run.completion ? <form className="review-form" onSubmit={event => { event.preventDefault(); void review(); }}><label><span>历史审阅结论</span><select value={reviewStatus} disabled={busy || stale} onChange={event => { setReviewStatus(event.target.value as ReparseReviewStatus); setReviewConfirmed(false); }}>{Object.entries(reviewLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label><span>审阅署名（本地自报）</span><input required maxLength={100} value={operator} disabled={busy || stale} onChange={event => setOperator(event.target.value)} /></label><label><span>审阅理由</span><textarea required rows={3} maxLength={2000} value={reason} disabled={busy || stale} onChange={event => setReason(event.target.value)} /></label><label className="review-checkbox"><input type="checkbox" checked={reviewConfirmed} disabled={busy || stale} onChange={event => setReviewConfirmed(event.target.checked)} /><span>已核对本次历史结果与可用的质量信息；理解此决定不会采纳候选或改变在线状态。</span></label><button type="submit" className="primary-button" disabled={busy || stale || !reviewConfirmed || !operator.trim() || !reason.trim()}>追加审阅（仍不采纳）</button></form> : <p>执行结果尚未完成，暂不提供审阅表单。</p>}
          </section><details className="report-history"><summary>历史审阅记录（{run.reviews.length}{run.reviews_truncated ? "+，仅最近 100 条" : " 条"}）</summary>{run.reviews.length ? run.reviews.map(item => <article key={item.id}><h4>#{item.revision} · {reviewLabels[item.status]} · {stamp(item.created_at)}</h4><p>{item.operator} · 本地自报</p><p className="draft-original">{item.reason}</p></article>) : <p>尚未追加人工审阅。</p>}</details>
        </> : !selectedId ? <p className="quality-empty">选择历史任务核对候选、差异和审阅，或在上方显式创建一次历史重解析。</p> : null}
      </section></div>
    </div>
  </dialog>;
}
