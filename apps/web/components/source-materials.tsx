"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type {
  EvidenceDocument, SourceMaterialCaptureRequest, SourceMaterialPolicies, SourceMaterialPolicy,
  SourceMaterialPreview, SourceMaterialRequestView, SourceMaterialRequests, SourceMaterialStopRequest,
} from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import { useWorkbenchPlatform, type WorkbenchPlatform } from "./workbench-platform";
import "./source-materials.css";

type PendingCapture = Readonly<{ userId: string; payload: Readonly<SourceMaterialCaptureRequest> }>;
type StopConfirmation = Readonly<{ key: string; requestId: string; ownerEpoch: number; generation: number }>;
// Account-scoped recovery survives component/session revalidation. The server's own
// request history also makes reserved UUIDs recoverable after a full page reload.
const unresolved = new Map<string, PendingCapture>();
const journalKey = (userId: string, key: string) => JSON.stringify([userId, key]);
const pendingFor = (userId: string) => [...unresolved.values()].filter(row => row.userId === userId);
const hash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const uuid = (value: string) => /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
const canonicalUuid = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);
// Match Python plain/UTF-8 validation and Pydantic's Unicode code-point bounds.
// Python strip treats U+0085 as whitespace and preserves U+FEFF; JS trim differs.
function plain(value: unknown, maximum: number): value is string {
  if (typeof value !== "string" || !value.length || value.length > maximum * 2
    || /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/.test(value)
    || /[\u0000-\u001f\u007f]/.test(value)) return false;
  const points = Array.from(value);
  return points.length <= maximum && !points.some(point => point.length === 1 && point.charCodeAt(0) >= 0xd800 && point.charCodeAt(0) <= 0xdfff);
}
const stopReasonText = (value: unknown): value is string => plain(value, 500) && !/[\u0085\u2028\u2029]/.test(value);
const timestamp = (value: unknown): value is string => typeof value === "string" && Number.isFinite(Date.parse(value));
const date = (value: string | null) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN") : "未声明";
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "来源材料操作未完成，请保留原请求标识核对。";
const stateLabel = { processing_unconfirmed: "结果尚未确认", stopped_unconfirmed: "已停止采纳 · 网络结果未确认", succeeded: "原件已捕获", failed: "捕获失败" } as const;

function assertPolicy(policy: SourceMaterialPolicy): void {
  if (!policy || !policy.policy_id || !policy.title || !policy.publisher || !hash(policy.policy_fingerprint)
    || typeof policy.source_reference_url !== "string" || typeof policy.download_url !== "string"
    || !Array.isArray(policy.redirect_urls) || policy.redirect_urls.length > 3
    || !policy.rights || !policy.rights.rights_holder || !policy.rights.basis
    || policy.rights.store_original !== true || policy.rights.workspace_reopen !== true
    || policy.rights.quote_identifiers !== true || policy.rights.provider_use !== false || policy.rights.export !== false)
    throw new Error("来源策略或许可边界响应不完整，未开放捕获。");
}

function assertView(view: SourceMaterialRequestView, key?: string, documentId?: string): void {
  if (!view || !view.request_id || !uuid(view.idempotency_key) || (key && view.idempotency_key !== key)
    || !["processing_unconfirmed", "stopped_unconfirmed", "succeeded", "failed"].includes(view.state))
    throw new Error("捕获响应与原请求不符；保留 UUID，仅查询原操作。");
  assertPolicy(view.policy);
  if (view.policy_fingerprint !== view.policy.policy_fingerprint) throw new Error("冻结策略指纹不一致，未展示来源结论。");
  const stop = view.stop ?? null;
  if (view.state === "stopped_unconfirmed") {
    if (!stop || !canonicalUuid(view.request_id) || !canonicalUuid(view.idempotency_key)
      || stop.schema !== "source-material-stop@1" || stop.request_id !== view.request_id
      || stop.idempotency_key !== view.idempotency_key || !plain(stop.operator, 80) || !stopReasonText(stop.reason)
      || !timestamp(stop.stopped_at) || !timestamp(view.requested_at) || Date.parse(stop.stopped_at) < Date.parse(view.requested_at)
      || Object.keys(stop).length !== 6 || Object.keys(stop).some(field => !["schema", "request_id", "idempotency_key", "operator", "reason", "stopped_at"].includes(field))
      || view.completed_at !== null || view.failure_code !== null || view.document !== null || view.receipt !== null || documentId)
      throw new Error("停止记录与原请求或未确认边界不符，未展示停止结论或原件。");
    return;
  }
  if (stop !== null) throw new Error("捕获状态与停止记录冲突，未展示结果或原件。");
  if (view.state !== "succeeded") {
    if (view.document !== null || view.receipt !== null || documentId
      || (view.state === "processing_unconfirmed" && (view.completed_at !== null || view.failure_code !== null)))
      throw new Error("尚未成功的捕获不能提供来源原件。");
    return;
  }
  const doc = view.document, receipt = view.receipt;
  if (!doc || !receipt || (documentId && doc.id !== documentId) || !hash(doc.raw_hash)
    || !Number.isInteger(doc.byte_count) || doc.byte_count < 1 || doc.byte_count > 8 * 1024 * 1024
    || doc.content_type !== "application/pdf" || doc.status !== "unparsed_receipt" || doc.accepted_as_facts !== false
    || doc.source_url !== view.policy.source_reference_url || receipt.schema !== "source-material-receipt@1"
    || receipt.request_id !== view.request_id || receipt.policy_fingerprint !== view.policy_fingerprint
    || receipt.document_id !== doc.id || receipt.raw_hash !== doc.raw_hash || receipt.byte_count !== doc.byte_count
    || !hash(receipt.document_metadata_hash) || !hash(receipt.fingerprint)
    || receipt.content_type !== "application/pdf" || receipt.content_encoding !== "identity"
    || receipt.transport_verification !== "https_transport_observed" || receipt.content_authenticity !== "unverified"
    || receipt.source_reference_relation !== "operator_configured" || receipt.source_reference_url !== view.policy.source_reference_url
    || receipt.initial_url !== view.policy.download_url || !Array.isArray(receipt.redirects) || receipt.redirects.length > 3
    || !Array.isArray(receipt.robots) || receipt.robots.length < 1 || receipt.robots.length > 4
    || receipt.robots.some(row => row.allowed !== true || ![200, 404, 410].includes(row.status)
      || (row.status === 200 ? !hash(row.raw_hash) : row.raw_hash !== null)))
    throw new Error("来源凭证、原件或未核验边界不一致，未提供文件或来源结论。");
}

function Reference({ value }: { value: string }) {
  let permitted = false;
  try { const url = new URL(value); permitted = url.protocol === "https:" && !url.username && !url.password && !url.search && !url.hash && ["", "443"].includes(url.port); } catch { /* Text remains inert. */ }
  return permitted ? <a href={value} target="_blank" rel="noreferrer noopener">{value}</a> : <span>{value}</span>;
}

function PolicyDetails({ policy }: { policy: SourceMaterialPolicy }) {
  return <div className="source-material-policy">
    <dl className="source-material-facts">
      <div><dt>出版者 / 材料</dt><dd>{policy.publisher} · {policy.title}</dd></div>
      <div><dt>版本 / 发布日期</dt><dd>{policy.edition ?? "版本未声明"} · {policy.published_at ?? "日期未声明"}</dd></div>
      <div><dt>配置的引用页</dt><dd><Reference value={policy.source_reference_url} /></dd></div>
      <div><dt>实际初始 PDF 地址</dt><dd><Reference value={policy.download_url} /></dd></div>
      <div><dt>许可权利人声明</dt><dd>{policy.rights.rights_holder}</dd></div>
      <div><dt>许可 / 留存依据</dt><dd>{policy.rights.basis}</dd></div>
      <div><dt>许可引用</dt><dd>{policy.rights.license_url ? <Reference value={policy.rights.license_url} /> : "未提供许可链接；仍须人工核对依据"}</dd></div>
      <div><dt>许可范围声明</dt><dd>保存原件 · 本地工作区共享重开 · 标识短引文；不授权模型使用或导出。</dd></div>
    </dl>
    <p className="source-material-boundary">引用页与 PDF 的关系来自操作者配置，许可也是配置声明。系统不认证版权、出版者或 PDF 内容，不自动读取引用页及许可链接。</p>
    <details className="source-material-technical"><summary>允许的精确跳转与策略指纹</summary>
      {policy.redirect_urls.length ? <ul>{policy.redirect_urls.map(url => <li key={url}><Reference value={url} /></li>)}</ul> : <p>不允许跳转到其他地址。</p>}
      <p className="source-material-hash">策略 SHA-256 {policy.policy_fingerprint}</p>
    </details>
  </div>;
}

async function downloadOriginal(row: EvidenceDocument, platform: WorkbenchPlatform, controller: AbortController, current: () => boolean): Promise<string> {
  const blob = await tireApi.documentContent(row.id, controller.signal);
  if (!current()) return "";
  if (blob.type.split(";")[0].trim().toLowerCase() !== "application/pdf" || blob.size !== row.byte_count)
    throw new Error("原件类型或完整字节数不符，未提供文件。");
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer())), byte => byte.toString(16).padStart(2, "0")).join("");
  if (!current()) return "";
  if (digest !== row.raw_hash) throw new Error("完整 PDF SHA-256 校验失败，未提供文件。");
  const result = await platform.saveDownload({ blob, filename: `source-material-${row.raw_hash}.pdf`, signal: controller.signal });
  return current() ? result.saved ? "完整 SHA-256 与字节数已校验，已提供原件下载。下载不证明已阅读、内容真实或身份匹配；仍须人工核对。" : "已取消保存原件。" : "";
}

function ReceiptDetails({ view, busy, onDownload }: { view: SourceMaterialRequestView; busy: boolean; onDownload: () => void }) {
  const receipt = view.receipt, doc = view.document;
  if (view.state !== "succeeded" || !receipt || !doc) return null;
  return <section className="source-material-receipt" aria-label="来源传输凭证">
    <div className="source-material-heading"><h4>来源传输凭证</h4><span className="tag quiet">传输已观察 · 内容未核验</span></div>
    <p>HTTPS 传输已观察；PDF 内容、许可真实性及精确 SKU 身份未核验。来源传输记录不会替代人工身份核对，也不开放测试性能 AI 推荐。</p>
    <dl className="source-material-facts">
      <div><dt>新原件记录</dt><dd>{doc.id} · {doc.title}</dd></div>
      <div><dt>配置的引用页</dt><dd><Reference value={receipt.source_reference_url} />（关系来自配置声明）</dd></div>
      <div><dt>实际初始地址</dt><dd><Reference value={receipt.initial_url} /></dd></div>
      <div><dt>实际最终地址</dt><dd><Reference value={receipt.final_url} /></dd></div>
      <div><dt>完整原件 SHA-256</dt><dd className="source-material-hash">{receipt.raw_hash}</dd></div>
      <div><dt>大小 / 类型 / 编码</dt><dd>{receipt.byte_count.toLocaleString()} 字节 · {receipt.content_type} · {receipt.content_encoding}</dd></div>
      <div><dt>观察起止时间</dt><dd>{date(receipt.started_at)} → {date(receipt.completed_at)}</dd></div>
    </dl>
    <p className="source-material-boundary">PDF 标记不证明可读性或出版物真伪。请下载完整原件后人工核读内容与身份。</p>
    <button type="button" className="secondary-button" disabled={busy} onClick={onDownload}>校验完整 SHA 与大小并下载来源原件</button>
    <details className="source-material-technical"><summary>冻结来源和许可声明</summary><PolicyDetails policy={view.policy} /></details>
    <details className="source-material-technical"><summary>原始字节的技术范围</summary><p>保存字节为 HTTP transfer decoding 后的 identity body，未做内容解压或文字重编码；不含 TLS 数据包、HTTP 头帧或 chunk framing。</p></details>
    <details className="source-material-technical"><summary>实际跳转和 robots 检查</summary>
      {receipt.redirects.length ? <ol>{receipt.redirects.map((row, index) => <li key={index}>HTTP {row.status}：<Reference value={row.from_url} /> → <Reference value={row.to_url} /></li>)}</ol> : <p>没有发生重定向。</p>}
      {receipt.robots.map((row, index) => <article className="source-material-robot" key={index}>
        <p>robots：<Reference value={row.url} /> · HTTP {row.status} · {row.status === 200 ? "规则允许该目标" : "明确未提供规则（404/410）"}</p>
        <p>实际核对目标：<Reference value={row.target_url} /></p>
        <p>{row.byte_count.toLocaleString()} 字节 · 最小间隔 {row.minimum_interval} 秒</p>
        <p className="source-material-hash">robots SHA-256：{row.raw_hash ?? "无正文"}</p>
      </article>)}
    </details>
    <details className="source-material-technical"><summary>凭证与原件元信息指纹</summary><p className="source-material-hash">凭证 SHA-256 {receipt.fingerprint}</p><p className="source-material-hash">原件元信息 SHA-256 {receipt.document_metadata_hash}</p><p>来源凭证只关联本 document ID；同字节的旧手工上传不会被追认为来源捕获。</p></details>
  </section>;
}

export default function SourceMaterials({ sessionReady, onCaptured }: { sessionReady: boolean; onCaptured: () => void }) {
  const auth = useWorkbenchAuth();
  return <section className="source-materials" data-testid="source-materials" aria-label="许可来源 PDF 捕获">
    <div className="source-material-heading"><h3>从许可来源捕获 PDF 原件</h3><span className="tag quiet">固定来源 · 逐次确认</span></div>
    <p className="quality-intro">按已配置的许可策略取得完整 PDF，保留来源传输凭证。内容仍未核验，不自动解析、审核身份或生成推荐。</p>
    {!sessionReady || !auth.ready ? <p role="status">正在重新确认账户，旧预览和请求暂不显示。</p> : !auth.state.user ? <p>登录后可查看自己的捕获请求；捕获和预览需要管理员。</p>
      : <CaptureWorkspace key={`${auth.ownerEpoch}:${auth.state.user.id}`} userId={auth.state.user.id} administrator={auth.state.user.is_admin} ownerEpoch={auth.ownerEpoch} onCaptured={onCaptured} />}
  </section>;
}

function CaptureWorkspace({ userId, administrator, ownerEpoch, onCaptured }: { userId: string; administrator: boolean; ownerEpoch: number; onCaptured: () => void }) {
  const auth = useWorkbenchAuth(), platform = useWorkbenchPlatform();
  const [catalog, setCatalog] = useState<SourceMaterialPolicies | null>(null);
  const [history, setHistory] = useState<SourceMaterialRequests | null>(null);
  const [selected, setSelected] = useState("");
  const [operator, setOperator] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [captureStarted, setCaptureStarted] = useState(false);
  const [preview, setPreview] = useState<SourceMaterialPreview | null>(null);
  const [view, setView] = useState<SourceMaterialRequestView | null>(null);
  const [stopConfirmation, setStopConfirmation] = useState<StopConfirmation | null>(null);
  const [stopOperator, setStopOperator] = useState("");
  const [stopReason, setStopReason] = useState("");
  const [stopConfirmed, setStopConfirmed] = useState(false);
  const [lookupKey, setLookupKey] = useState("");
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [journalRefresh, setJournalRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const operations = useRef(new Set<AbortController>());
  const writing = useRef(false);
  const generation = useRef(0);
  const capturedCallback = useRef(onCaptured); capturedCallback.current = onCaptured;
  const notified = useRef(new Set<string>());
  const policy = catalog?.items.find(row => row.policy_id === selected);
  const pending = pendingFor(userId); void journalRefresh;
  const current = (controller: AbortController) => !controller.signal.aborted && auth.isCurrentOwner(ownerEpoch);
  const operation = () => { const controller = new AbortController(); operations.current.add(controller); return controller; };
  useEffect(() => () => { operations.current.forEach(controller => controller.abort()); }, []);

  useEffect(() => {
    const controller = operation(); setLoading(true);
    // Catalogue and private history are independent. A removed/broken current
    // policy never prevents reopening an already reserved request.
    void tireApi.sourceMaterialPolicies(controller.signal).then(result => {
      if (!current(controller)) return;
      if (result.scope !== "local_workspace" || !Array.isArray(result.items) || result.items.length > 16) throw new Error("来源目录响应不完整。");
      result.items.forEach(assertPolicy); setCatalog(result);
      setSelected(previous => result.items.some(row => row.policy_id === previous) ? previous : "");
      setPreview(previous => previous && result.items.some(row => row.policy_id === previous.policy.policy_id && row.policy_fingerprint === previous.policy.policy_fingerprint) ? previous : null);
    }).catch(cause => { if (current(controller)) { setCatalog(null); setError(errorText(cause)); } });
    return () => { controller.abort(); operations.current.delete(controller); };
  }, [refresh, ownerEpoch]);

  useEffect(() => {
    const controller = operation(); setLoading(true);
    void tireApi.sourceMaterialRequests(offset, controller.signal).then(result => {
      if (!current(controller)) return;
      if (result.scope !== "current_user" || !Array.isArray(result.items) || result.offset !== offset || result.items.length > 50) throw new Error("本人捕获历史响应不完整。");
      result.items.forEach(row => assertView(row)); setHistory(result);
    }).catch(cause => { if (current(controller)) { setHistory(null); setError(errorText(cause)); } })
      .finally(() => { if (current(controller)) setLoading(false); });
    return () => { controller.abort(); operations.current.delete(controller); };
  }, [offset, refresh, ownerEpoch]);

  function closeStop() { generation.current++; setStopConfirmation(null); setStopOperator(""); setStopReason(""); setStopConfirmed(false); }
  function invalidate() { closeStop(); setPreview(null); setConfirmed(false); setError(""); setNotice(""); }
  function applyResult(result: SourceMaterialRequestView, notify: boolean) {
    closeStop();
    setView(result); setLookupKey(result.idempotency_key);
    if (result.state !== "processing_unconfirmed") {
      unresolved.delete(journalKey(userId, result.idempotency_key)); setJournalRefresh(value => value + 1);
    }
    if (notify && result.state === "succeeded" && result.document && !notified.current.has(result.document.id)) {
      notified.current.add(result.document.id); capturedCallback.current();
    }
  }

  async function prepare() {
    if (busy || captureStarted || !administrator || !policy) return;
    invalidate(); const token = generation.current, controller = operation(); setBusy(true);
    try {
      const result = await tireApi.previewSourceMaterial({ policy_id: policy.policy_id, expected_policy_fingerprint: policy.policy_fingerprint }, controller.signal);
      if (!current(controller) || generation.current !== token) return;
      assertPolicy(result.policy);
      if (result.policy.policy_id !== policy.policy_id || result.policy.policy_fingerprint !== policy.policy_fingerprint
        || typeof result.can_capture !== "boolean" || !Array.isArray(result.blockers)) throw new Error("预览不属于当前来源策略，请刷新后重新选择。");
      setPreview(result);
    } catch (cause) { if (current(controller) && generation.current === token) setError(errorText(cause)); }
    finally { operations.current.delete(controller); if (current(controller)) setBusy(false); }
  }

  async function capture() {
    if (writing.current || busy || captureStarted || !administrator || !preview?.can_capture || !confirmed || !operator.trim() || !auth.isCurrentOwner(ownerEpoch)) return;
    if (pendingFor(userId).length >= 16) { setError("本账户尚有较多原请求待核对，请先查询其结果；不会丢弃旧 UUID。"); return; }
    const payload: SourceMaterialCaptureRequest = { policy_id: preview.policy.policy_id, expected_policy_fingerprint: preview.policy.policy_fingerprint,
      idempotency_key: crypto.randomUUID(), operator: operator.trim(), rights_confirmed: true };
    const entry = Object.freeze({ userId, payload: Object.freeze({ ...payload }) });
    unresolved.set(journalKey(userId, payload.idempotency_key), entry); setJournalRefresh(value => value + 1);
    setLookupKey(payload.idempotency_key); setView(null); setPreview(null); setConfirmed(false); setCaptureStarted(true);
    const controller = operation(); writing.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const result = await tireApi.captureSourceMaterial(payload, controller.signal);
      if (!current(controller)) return;
      assertView(result, payload.idempotency_key);
      if (typeof result.replayed !== "boolean" || result.policy.policy_id !== payload.policy_id
        || result.policy_fingerprint !== payload.expected_policy_fingerprint || result.operator !== payload.operator)
        throw new Error("捕获返回与原请求不一致，请保留 UUID 查询原结果。");
      applyResult(result, true); setRefresh(value => value + 1);
      setNotice(result.state === "succeeded" ? "原件和来源传输凭证已登记，现有原件列表已刷新，可供人工证据核对选择；身份仍须人工核对。" : result.state === "failed" ? "本次捕获失败，不会自动重抓。可查看原请求，或明确开始另一项新捕获。" : result.state === "stopped_unconfirmed"
        ? "已停止这次请求的后续采纳，网络结果仍未确认；不会重新抓取。" : "已登记原请求，但尚无可靠终态。请查询同一 UUID，不要据此判断仍在下载。");
    } catch (cause) {
      if (current(controller)) setError(`${errorText(cause)} 原 UUID 已保留；请先“核对原捕获请求”，本页不会自动重新联网。`);
    } finally { writing.current = false; operations.current.delete(controller); if (current(controller)) setBusy(false); }
  }

  async function lookup(key: string, notify = true) {
    if (busy || !uuid(key)) { if (!uuid(key)) setError("请输入完整的原请求 UUID。"); return; }
    closeStop();
    const controller = operation(); setBusy(true); setError(""); setNotice("");
    try {
      const result = await tireApi.sourceMaterialRequest(key, controller.signal);
      if (!current(controller)) return;
      assertView(result, key); applyResult(result, notify); setRefresh(value => value + 1);
      setNotice(result.state === "processing_unconfirmed" ? "服务器尚无可靠终态；这不证明后台仍有下载进程，也不会自动重新抓取。" : result.state === "stopped_unconfirmed"
        ? "已按原 UUID 重开停止记录；网络结果仍未确认，不会恢复采纳或重新抓取。" : "已按本账户的原 UUID 重开冻结结果，没有发起新的来源抓取。");
    } catch (cause) {
      if (current(controller)) {
        setView(null);
        setError(cause instanceof ApiError && cause.status === 404 ? "本账户当前未找到此 UUID 的请求。原标识仍保留，可再次查询；若另行捕获，须明确开始新请求并重新预览。" : errorText(cause));
      }
    } finally { operations.current.delete(controller); if (current(controller)) setBusy(false); }
  }

  function beginStop() {
    if (busy || writing.current || !administrator || view?.state !== "processing_unconfirmed" || !auth.isCurrentOwner(ownerEpoch)) return;
    invalidate();
    setStopConfirmation(Object.freeze({ key: view.idempotency_key, requestId: view.request_id, ownerEpoch, generation: generation.current }));
  }

  async function stopAdoption() {
    const confirmation = stopConfirmation, original = view;
    if (writing.current || busy || !administrator || !confirmation || !stopConfirmed || original?.state !== "processing_unconfirmed"
      || confirmation.ownerEpoch !== ownerEpoch || !auth.isCurrentOwner(ownerEpoch) || confirmation.generation !== generation.current
      || confirmation.key !== original.idempotency_key || confirmation.requestId !== original.request_id
      || !plain(stopOperator, 80) || !stopReasonText(stopReason)) return;
    const payload: SourceMaterialStopRequest = { expected_request_id: confirmation.requestId, operator: stopOperator, reason: stopReason };
    const controller = operation(); writing.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const result = await tireApi.stopSourceMaterialRequest(confirmation.key, payload, controller.signal);
      if (!current(controller) || confirmation.generation !== generation.current) return;
      if (!result || !["stopped", "already_stopped", "already_terminal"].includes(result.effect))
        throw new Error("停止采纳响应不完整，请只查询原 UUID 核对。");
      assertView(result.request, confirmation.key);
      if (result.request.request_id !== confirmation.requestId || result.request.policy_fingerprint !== original.policy_fingerprint
        || result.request.operator !== original.operator || result.request.requested_at !== original.requested_at
        || (result.effect === "already_terminal" ? !["succeeded", "failed"].includes(result.request.state)
          : result.request.state !== "stopped_unconfirmed" || result.request.stop?.operator !== payload.operator || result.request.stop.reason !== payload.reason))
        throw new Error("停止采纳返回与原请求或署名原因不一致，请只查询原 UUID 核对。");
      applyResult(result.request, true); setRefresh(value => value + 1);
      setNotice(result.effect === "already_terminal" ? "原请求已先完成，本次没有新增停止记录；现已重开其冻结结果。"
        : "已停止这次请求后续的原件采纳。网络结果仍未确认；不会重新抓取或自动恢复下载。");
    } catch (cause) {
      if (current(controller) && confirmation.generation === generation.current) {
        closeStop(); setView(null); setLookupKey(confirmation.key);
        setError(`${errorText(cause)} 停止采纳结果尚未核对，原 UUID 已保留；请仅“按 UUID 查询原请求”，不会自动再次提交停止或重新抓取。`);
      }
    } finally {
      operations.current.delete(controller);
      if (current(controller)) { writing.current = false; setBusy(false); }
    }
  }

  async function download() {
    if (busy || view?.state !== "succeeded" || !view.document) return;
    const controller = operation(); setBusy(true); setError(""); setNotice("");
    try { const message = await downloadOriginal(view.document, platform, controller, () => current(controller)); if (current(controller)) setNotice(message); }
    catch (cause) { if (current(controller)) setError(errorText(cause)); }
    finally { operations.current.delete(controller); if (current(controller)) setBusy(false); }
  }

  return <div className="source-material-workspace">
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {notice ? <p className="review-saved" role="status">{notice}</p> : null}
    {catalog === null ? <p role="status">来源目录尚未取得；已登记的本人请求仍可单独查询。</p> : catalog.items.length === 0 ? <div className="source-material-empty">
      <strong>当前没有配置可捕获的许可来源。</strong><p>请工作区管理员核对具体材料和留存许可后，参照 <code>docs/SOURCE-MATERIAL-POLICY.md</code> 配置来源并重启 API。不会自动访问专业媒体；已有手工 PDF 仍可使用。</p>
    </div> : <div className="source-material-create">
      {!administrator ? <p className="snapshot-banner">当前账户可读取来源和自己的历史；预览与捕获需要管理员。</p> : null}
      <label><span>固定 PDF 来源</span><select value={selected} disabled={busy || captureStarted} onChange={event => { invalidate(); setSelected(event.target.value); setView(null); }}><option value="">请选择已核对的固定来源</option>{catalog.items.map(row => <option key={row.policy_id} value={row.policy_id}>{row.title} · {row.publisher}</option>)}</select></label>
      {policy ? <PolicyDetails policy={policy} /> : null}
      <label><span>捕获署名</span><input value={operator} maxLength={80} disabled={busy || captureStarted || !administrator} onChange={event => { invalidate(); setOperator(event.target.value); }} autoComplete="off" /></label>
      <button type="button" className="secondary-button" disabled={busy || captureStarted || !administrator || !policy || !operator.trim()} onClick={() => void prepare()}>预览来源与许可</button>
      {preview ? <div className="source-material-preview" aria-label="来源捕获预览">
        <h4>本次冻结预览</h4><PolicyDetails policy={preview.policy} />
        <p>{preview.notice}</p>{preview.blockers.length ? <ul className="inline-error">{preview.blockers.map(code => <li key={code}>{code}</li>)}</ul> : null}
        <label className="source-material-confirm"><input type="checkbox" checked={confirmed} disabled={busy || !administrator} onChange={event => setConfirmed(event.target.checked)} /><span>我已核对许可，确认可保存原件、在本地工作区重开并摘录标识；不授权模型使用或导出。</span></label>
        <p className="source-material-boundary">这是一次新捕获，将使用独立 UUID。未知结果只查询原请求；失败不会自动重抓。</p>
        <button type="button" className="primary-button" disabled={busy || !preview.can_capture || !confirmed || !administrator || !operator.trim()} onClick={() => void capture()}>确认并捕获原件</button>
      </div> : null}
    </div>}
    {pending.length ? <div className="source-material-pending"><h4>本账户待核对的原请求</h4>{pending.map(entry => <article key={entry.payload.idempotency_key}><p>{entry.payload.operator} · {entry.payload.policy_id}</p><p className="source-material-hash">原 UUID {entry.payload.idempotency_key}</p><button type="button" className="secondary-button" disabled={busy} onClick={() => { setLookupKey(entry.payload.idempotency_key); void lookup(entry.payload.idempotency_key); }}>核对原捕获请求</button></article>)}</div> : null}
    <form className="source-material-lookup" onSubmit={event => { event.preventDefault(); void lookup(lookupKey.trim().toLowerCase()); }}>
      <label><span>原请求 UUID</span><input value={lookupKey} maxLength={36} disabled={busy} onChange={event => { closeStop(); setLookupKey(event.target.value); }} placeholder="同账户可跨会话找回" autoComplete="off" /></label>
      <button type="submit" className="secondary-button" disabled={busy || !uuid(lookupKey.trim())}>按 UUID 查询原请求</button>
    </form>
    {view ? <article className="source-material-result" aria-label="原捕获请求结果">
      <div className="source-material-heading"><h4>{stateLabel[view.state]}</h4><span>{date(view.requested_at)}</span></div>
      <p>{view.policy.title} · 署名 {view.operator}</p><p className="source-material-hash">原 UUID {view.idempotency_key}</p><p>{view.notice}</p>
      {view.state === "failed" ? <p className="inline-error">失败代码：{view.failure_code ?? "未提供"}。没有自动重试；相同 UUID 只会返回原结果。</p> : null}
      {view.state === "processing_unconfirmed" ? <>
        <p className="snapshot-banner">尚无可靠终态，不能推断后台仍在下载。可查询此 UUID，或明确停止它继续采纳；不会自动重新抓取。</p>
        {administrator && !stopConfirmation ? <button type="button" className="secondary-button" disabled={busy} onClick={beginStop}>停止采纳此请求</button> : null}
        {stopConfirmation ? <form className="source-material-stop" aria-label="停止采纳确认" onSubmit={event => { event.preventDefault(); void stopAdoption(); }}>
          <h4>确认停止采纳此请求</h4>
          <p className="source-material-hash">固定原 UUID {stopConfirmation.key}</p>
          <p>停止后不会再登记这次请求的原件；网络结果仍未确认，可能已留下无引用对象。停止不证明网络传输已终止，也不授权以新 UUID 重新抓取。</p>
          <label><span>停止操作署名</span><input value={stopOperator} maxLength={160} required disabled={busy} autoComplete="off" onChange={event => { setStopOperator(event.target.value); setStopConfirmed(false); }} /></label>
          <label><span>停止原因（单段，最多 500 字符）</span><input value={stopReason} maxLength={1000} required disabled={busy} autoComplete="off" onChange={event => { setStopReason(event.target.value); setStopConfirmed(false); }} /></label>
          <label className="source-material-confirm"><input type="checkbox" checked={stopConfirmed} disabled={busy} onChange={event => setStopConfirmed(event.target.checked)} /><span>我确认停止上述原请求的后续采纳，并保留网络结果未确认的记录。</span></label>
          <div className="source-material-stop-actions"><button type="submit" className="primary-button" disabled={busy || !stopConfirmed || !plain(stopOperator, 80) || !stopReasonText(stopReason)}>确认停止采纳</button><button type="button" className="secondary-button" disabled={busy} onClick={closeStop}>取消停止操作</button></div>
        </form> : null}
      </> : null}
      {view.state === "stopped_unconfirmed" && view.stop ? <div className="source-material-stopped">
        <p className="snapshot-banner">已停止后续采纳，网络结果仍未确认。不会再为此请求登记来源原件；可能已有无引用对象，停止不证明网络传输已终止或对象已删除。</p>
        <dl className="source-material-facts"><div><dt>停止时间</dt><dd>{date(view.stop.stopped_at)}</dd></div><div><dt>停止署名</dt><dd>{view.stop.operator}</dd></div><div><dt>停止原因</dt><dd>{view.stop.reason}</dd></div></dl>
      </div> : null}
      <ReceiptDetails view={view} busy={busy} onDownload={() => void download()} />
    </article> : null}
    {captureStarted && (view?.state === "succeeded" || view?.state === "failed") ? <button type="button" className="secondary-button" disabled={busy} onClick={() => { invalidate(); setView(null); setSelected(""); setOperator(""); setCaptureStarted(false); }}>开始新的捕获</button> : null}
    <div className="source-material-history">
      <div className="source-material-heading"><h4>我的捕获请求历史</h4><button className="text-button" type="button" disabled={busy || loading} onClick={() => { invalidate(); setRefresh(value => value + 1); }}>刷新来源与本人历史</button></div>
      <p className="source-material-boundary">请求历史仅当前账户可见。原件及成功来源凭证属于本地工作区；同账户重新登录可查询原 UUID，其他账户不能接管请求。</p>
      {loading ? <p role="status">正在读取本人捕获历史…</p> : history ? <>{history.items.length ? history.items.map(row => <article key={row.request_id} className="source-material-history-row"><div><strong>{row.policy.title}</strong><p>{stateLabel[row.state]} · {date(row.requested_at)}</p><p className="source-material-hash">{row.idempotency_key}</p></div><button type="button" className="text-button" disabled={busy} onClick={() => void lookup(row.idempotency_key, false)}>查看捕获请求</button></article>) : <p>这一页没有捕获请求。</p>}
        <div className="source-material-pagination"><span>第 {offset + 1}–{offset + history.items.length} 条 / 共 {history.total} 条</span><button type="button" className="text-button" disabled={busy || offset === 0} onClick={() => setOffset(value => Math.max(0, value - 50))}>上一页请求</button><button type="button" className="text-button" disabled={busy || offset + history.items.length >= history.total || history.items.length === 0} onClick={() => setOffset(value => value + 50)}>下一页请求</button></div>
      </> : <p>本人历史尚未取得；可使用原 UUID 单独查询。</p>}
    </div>
  </div>;
}

/** Lazy lookup by document ID; a matching raw hash never marks an old upload. */
export function SourceMaterialDocumentReceipt({ documentId }: { documentId: string }) {
  const auth = useWorkbenchAuth();
  if (!auth.ready || !auth.state.user) return null;
  return <DocumentReceipt key={`${auth.ownerEpoch}:${documentId}`} documentId={documentId} ownerEpoch={auth.ownerEpoch} />;
}

function DocumentReceipt({ documentId, ownerEpoch }: { documentId: string; ownerEpoch: number }) {
  const auth = useWorkbenchAuth(), platform = useWorkbenchPlatform();
  const [view, setView] = useState<SourceMaterialRequestView | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  const current = (controller: AbortController) => !controller.signal.aborted && auth.isCurrentOwner(ownerEpoch);
  async function read() {
    if (busy) return;
    const controller = new AbortController(); active.current = controller; setBusy(true); setView(null); setError(""); setNotice("");
    try { const result = await tireApi.sourceMaterialDocument(documentId, controller.signal); if (!current(controller)) return; assertView(result, undefined, documentId); setView(result); }
    catch (cause) { if (current(controller)) { if (cause instanceof ApiError && cause.status === 404) setNotice("这份原件没有来源捕获凭证。手工上传仍为操作者提供、未核验；不会按相同字节追认来源。"); else setError(errorText(cause)); } }
    finally { if (current(controller)) setBusy(false); }
  }
  async function download() {
    if (busy || !view?.document) return;
    const controller = new AbortController(); active.current = controller; setBusy(true); setError(""); setNotice("");
    try { const message = await downloadOriginal(view.document, platform, controller, () => current(controller)); if (current(controller)) setNotice(message); }
    catch (cause) { if (current(controller)) setError(errorText(cause)); }
    finally { if (current(controller)) setBusy(false); }
  }
  return <div className="source-materials source-material-document">
    <button type="button" className="text-button" disabled={busy} onClick={() => void read()}>查看此原件的来源捕获凭证</button>
    {error ? <p role="alert" className="inline-error">{error}</p> : null}{notice ? <p role="status">{notice}</p> : null}
    {view ? <><ReceiptDetails view={view} busy={busy} onDownload={() => void download()} /><button type="button" className="text-button" onClick={() => setView(null)}>收起来源凭证</button></> : null}
  </div>;
}
