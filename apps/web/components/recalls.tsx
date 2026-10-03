"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { RecallEvidence, RecallHistory, RecallNotification, RecallPage, RecallRecord, RecallResult, RecallRule, RecallRuleDetail, RecallRuleSettings, RecallSearchEvidence, RecallSearchProduct, RecallSearchQuery, RecallSearchResult } from "@tire/domain-types";
import { Icon } from "./icons";
import type { AITarget } from "./ai-analysis";
import { RecallAnalysisBoundary } from "./recall-evidence-meta";
import { DataTree } from "./reparse-review";
import { MonitorTaskDialog } from "./task-center";
import RecallDiscoveryMonitoring, { type DiscoveryRuleSeed } from "./recall-discovery-monitoring";
import { SourceOnlineNotice, SourceStatus, useSourceAccess } from "./source-status";
import QueryFallbackPolicy from "./query-fallback-policy";
import { useDeviceQueryFallback } from "./query-fallback-device";
const sourceId = "nhtsa-us-recalls";

const campaignPattern = /^\d{2}T\d{6}$/;
const normalize = (value: string) => value.trim().toUpperCase();
const stamp = (value?: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "未记录";
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "操作未完成，请重试。";
const kindText = (kind: string) => kind === "first_observed" ? "本系统首次观察" : "公告内容变化";
const states = { live: "本次在线核验", live_verified_304: "本次在线确认未变", local_snapshot: "LOCAL SNAPSHOT · 历史记录", consent_required: "需授权读取历史", source_unavailable: "在线来源不可用" };
const boundary = "官方公告记录与具体轮胎适用性分别核对。缺少 DOT/TIN、生产日期及适用范围时，不能判定某一精确 SKU 或您持有的轮胎受影响；品牌、型号或尺寸相同也不足以判定。";
type QueryContext = { campaign: string; controller: AbortController; deciding: boolean; accessGeneration: number; attemptId: string };
const isHistory = (value: RecallResult): value is RecallHistory => "revisions" in value;

function RecallRecords({ records }: { records: RecallRecord[] }) {
  const [page, setPage] = useState(0);
  const current = Math.min(page, Math.max(0, Math.ceil(records.length / 5) - 1));
  return <div className="recall-records">
    {records.slice(current * 5, current * 5 + 5).map((record, index) => <article className="recall-record" key={`${record.campaign_number}-${current * 5 + index}`}>
      <div className="recall-record-heading"><div><span className="eyebrow">NHTSA · 官方公告记录</span><h3>{record.make || "品牌未声明"} · {record.model || "型号未声明"}</h3></div><code>{record.campaign_number}</code></div>
      <dl className="recall-meta"><div><dt>厂家 Manufacturer</dt><dd>{record.manufacturer || "来源未声明"}</dd></div><div><dt>官方接收日期 Report Received Date</dt><dd>{record.report_received_date || "来源未声明"}</dd></div><div><dt>涉及部件 Component</dt><dd>{record.component || "来源未声明"}</dd></div><div><dt>潜在涉及数量 Potential Units</dt><dd>{record.potential_units ?? "来源未声明"}</dd></div><div><dt>官方原始年款 Model Year</dt><dd>{record.model_year_raw ?? "来源未声明"}</dd></div><div><dt>具体轮胎适用性</dt><dd>尚未评估 · not_assessed</dd></div></dl>
      <div className="recall-original"><DataTree label="官方概要 · Summary 原文" value={record.summary} /><DataTree label="官方后果 · Consequence 原文" value={record.consequence} /><DataTree label="官方措施 · Remedy 原文" value={record.remedy} /><DataTree label="官方备注 · Notes 原文" value={record.notes} /><DataTree label="完整规范化产品字段 · Product" value={record} /></div>
    </article>)}
    {records.length > 5 ? <div className="reparse-pages"><button type="button" className="text-button" disabled={!current} onClick={() => setPage(current - 1)}>上一组产品</button><span>{current + 1} / {Math.ceil(records.length / 5)} · 共 {records.length} 条产品记录</span><button type="button" className="text-button" disabled={(current + 1) * 5 >= records.length} onClick={() => setPage(current + 1)}>下一组产品</button></div> : null}
  </div>;
}

function RecallEvidencePanel({ id, kind = "campaign", onClose }: { id: string; kind?: "campaign" | "search"; onClose: () => void }) {
  const [data, setData] = useState<RecallEvidence | RecallSearchEvidence | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const headingId = useId();
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    heading.current?.focus();
    return () => { if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, []);
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError(""); heading.current?.focus({ preventScroll: true });
    void (kind === "search" ? tireApi.recallSearchEvidence(id, controller.signal) : tireApi.recallEvidence(id, controller.signal)).then(value => { if (!controller.signal.aborted) setData(value); }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [id, kind, attempt]);
  return <section className="recall-evidence" aria-labelledby={headingId}><div className="recall-section-heading"><h3 id={headingId} ref={heading} tabIndex={-1}>历史原始证据</h3><button type="button" className="text-button" onClick={onClose}>收起证据</button></div><p className="review-boundary">LOCAL SNAPSHOT · 读取已保存的官方响应，不会进行在线核验。正文仅以纯文本展示。</p>
    {error ? <p role="alert" className="inline-error">{error}<button type="button" className="text-button" onClick={() => setAttempt(value => value + 1)}>重新读取证据</button></p> : data ? <><dl className="recall-meta"><div><dt>公告编号</dt><dd>{"campaign_number" in data ? data.campaign_number : "名称检索单页响应"}</dd></div><div><dt>原文观察时间</dt><dd>{stamp(data.observed_at)}</dd></div><div><dt>历史核验时间</dt><dd>{stamp(data.verified_at)}</dd></div><div><dt>Parser 版本</dt><dd>{data.parser_version}</dd></div><div><dt>原文 SHA-256</dt><dd><code>{data.raw_hash}</code></dd></div><div><dt>官方来源地址</dt><dd>{data.source_url}</dd></div></dl><DataTree label="完整官方响应原文（分段阅读）" value={data.body} />{data.parser_identity ? <DataTree label="原文解析器身份" value={data.parser_identity} /> : null}</> : <p role="status">正在读取历史证据…</p>}
  </section>;
}

function RecallQueryPanel({ sessionReady, mode, campaign, onCampaign, onAnalyze }: { sessionReady: boolean; mode: "online" | "history"; campaign: string; onCampaign: (value: string) => void; onAnalyze?: (target: AITarget) => void }) {
  const sourceAccess = useSourceAccess();
  const deviceFallback = useDeviceQueryFallback("recall_campaign", sourceId);
  const [result, setResult] = useState<RecallResult | RecallHistory | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [denied, setDenied] = useState(false);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const active = useRef<QueryContext | null>(null);
  useEffect(() => () => { active.current?.controller.abort(); active.current = null; }, []);
  useEffect(() => { if (!sessionReady) { active.current?.controller.abort(); active.current = null; deviceFallback.clear(); setResult(null); setEvidenceId(null); setBusy(false); } }, [sessionReady]);
  useEffect(() => {
    if (active.current && active.current.campaign !== normalize(campaign)) {
      active.current.controller.abort(); active.current = null; deviceFallback.clear(); setResult(null); setEvidenceId(null); setBusy(false); setError(""); setDenied(false);
    }
  }, [campaign]);
  const current = (context: QueryContext) => active.current === context && !context.controller.signal.aborted;
  const accessGeneration = sourceAccess.get(sourceId)?.management.access_generation;
  useEffect(() => {
    const context = active.current;
    deviceFallback.clear();
    if (mode === "online" && context && context.accessGeneration >= 0 && context.accessGeneration !== accessGeneration) { context.controller.abort(); active.current = null; setBusy(false); setResult(previous => previous?.data_state === "consent_required" ? null : previous); setError("来源状态已变化，旧请求和待答授权已失效；历史证据仍可读取。"); }
  }, [accessGeneration, mode]);
  const normalized = normalize(campaign);
  const valid = campaignPattern.test(normalized);
  const ready = result && !denied && ["live", "live_verified_304", "local_snapshot"].includes(result.data_state) ? result : null;
  function clear() { active.current?.controller.abort(); active.current = null; deviceFallback.clear(); setResult(null); setError(""); setDenied(false); setEvidenceId(null); setBusy(false); }
  async function query() {
    if (!sessionReady || !valid || busy) return;
    const priorGeneration = sourceAccess.get(sourceId)?.management.access_generation ?? -1;
    clear(); const context: QueryContext = { campaign: normalized, controller: new AbortController(), deciding: false, accessGeneration: -1, attemptId: crypto.randomUUID() }; active.current = context; setBusy(true);
    try {
      if (mode === "online") {
        let failure: unknown; const metadata = await sourceAccess.refresh(cause => { failure = cause; });
        if (!current(context)) return;
        if (!metadata || !sourceAccess.canQuery(sourceId)) { setError("来源当前不能在线采集；可切换到已保存的历史。"); context.accessGeneration = priorGeneration; if (failure) await deviceFallback.show({ campaign_number: context.campaign }, priorGeneration, failure, context.attemptId, "NHTSA 召回公告", () => current(context)); return; }
      }
      if (!current(context)) return;
      context.accessGeneration = sourceAccess.get(sourceId)?.management.access_generation ?? -1;
      const response = mode === "online" ? await tireApi.liveRecall({ campaign_number: context.campaign }, context.controller.signal) : await tireApi.recallHistory(context.campaign, context.controller.signal); if (current(context)) { setResult(response); if (mode === "online") await deviceFallback.show({ campaign_number: context.campaign }, context.accessGeneration, response, context.attemptId, "NHTSA 召回公告", () => current(context)); }
    }
    catch (cause) { if (current(context)) { setError(errorText(cause)); if (mode === "online") await deviceFallback.show({ campaign_number: context.campaign }, context.accessGeneration, cause, context.attemptId, "NHTSA 召回公告", () => current(context)); } }
    finally { if (current(context)) setBusy(false); }
  }
  async function consent(decision: "allow" | "deny") {
    const context = active.current;
    if (!context || !current(context) || context.deciding || !result?.query_id || result.data_state !== "consent_required" || result.query.campaign_number !== context.campaign || denied) return;
    context.deciding = true; setBusy(true); setError("");
    deviceFallback.clear();
    try {
      if (!await sourceAccess.ensure(sourceId, "management") || context.controller.signal.aborted || context.accessGeneration !== sourceAccess.get(sourceId)?.management.access_generation) { setError("来源许可待核对或已变化，未使用旧授权。"); return; }
      const approval = await tireApi.consent(result.query_id, decision, context.controller.signal);
      if (!current(context)) return;
      if (decision === "deny") { setDenied(true); return; }
      const response = await tireApi.liveRecall({ campaign_number: context.campaign }, context.controller.signal, approval.id);
      if (current(context)) setResult(response);
    } catch (cause) { if (current(context)) setError(errorText(cause)); }
    finally { if (current(context)) { context.deciding = false; setBusy(false); } }
  }
  return <div className="recall-query-panel">
    {mode === "online" ? <QueryFallbackPolicy kind="recall_campaign" sourceIds={[sourceId]} sessionReady={sessionReady} /> : null}
    <form className="review-form recall-query-form" onSubmit={event => { event.preventDefault(); void query(); }}><label><span>轮胎召回公告编号</span><input id="recall-campaign-input" autoComplete="off" spellCheck={false} maxLength={9} value={campaign} pattern="[0-9]{2}[Tt][0-9]{6}" required aria-describedby="recall-campaign-help" onChange={event => { clear(); onCampaign(event.target.value); }} /></label><button type="submit" className="primary-button" disabled={!sessionReady || !valid || busy || (mode === "online" && !sourceAccess.canQuery(sourceId))}>{busy ? "正在读取…" : mode === "online" ? "在线核验公告" : "读取该公告历史"}<Icon name="arrow" size={16} /></button></form>
    <p id="recall-campaign-help" className="recall-help">格式为 2 位数字 + T + 6 位数字，例如 23T001000。示例可编辑，不会自动查询。无需 VIN 或任何个人信息。</p>
    <p className="recall-mode-notice">{mode === "online" ? "访问 NHTSA 官方来源。本次失败时，仅在您允许后读取该编号的历史快照。" : "历史入口仅读取本地已保存记录；历史核验时间不代表本次在线核验。"}</p>
    {!sessionReady ? <p role="status" className="review-boundary">正在准备本地会话…</p> : null}
    {error ? <p role="alert" className="inline-error">{error}</p> : null}
    {deviceFallback.panel}
    {result?.data_state === "consent_required" && !denied ? <section className="consent-card recall-consent"><div className="consent-symbol"><Icon name="shield" size={22} /></div><div><h3>在线核验未完成，是否读取这份公告的历史？</h3><p>仅授权 {result.query.campaign_number} 的本次查询；切换编号或重新查询需重新授权。</p>{result.reason ? <p className="recall-help">本次原因：{result.reason}</p> : null}<div className="consent-actions"><button type="button" className="primary-button compact" disabled={busy} onClick={() => void consent("allow")}>仅本次允许</button><button type="button" className="secondary-button compact" disabled={busy} onClick={() => void consent("deny")}>拒绝，保持无结果</button></div></div></section> : null}
    {denied ? <p role="status" className="recall-mode-notice">已拒绝本次回退，没有读取公告历史。可重新发起在线核验。</p> : null}
    {result?.data_state === "source_unavailable" ? <section className="recall-mode-notice" role="status"><strong>在线来源不可用</strong><p>未获得可用公告结果，不能据此判断轮胎是否涉及召回。</p>{result.reason ? <p>原因：{result.reason}</p> : null}</section> : null}
    {ready ? <section className="recall-results" aria-label="正式召回公告查询结果"><div className="recall-section-heading"><h3>{ready.query.campaign_number} · {ready.records.length ? "正式公告" : "本次观察"}</h3><span className={`tag ${ready.data_state === "local_snapshot" ? "warning" : "success"}`}>{states[ready.data_state]}</span></div>
      {ready.data_state === "local_snapshot" ? <div className="snapshot-banner"><strong>历史召回记录 · 非实时数据</strong><span>原文观察时间：{stamp(ready.snapshot_observed_at)}</span><span>历史核验时间：{stamp(ready.verified_at)}</span>{ready.consent_id ? <span className="mono">本次授权：{ready.consent_id}</span> : null}</div> : <p className="verification-line">本次在线核验：{stamp(ready.verified_at)}{ready.data_state === "live_verified_304" ? " · 官方响应 304，已验证同一原文及解析器身份" : ""}</p>}
      {ready.analysis_reference && onAnalyze ? <div className="recall-analysis-entry"><RecallAnalysisBoundary pending /><button type="button" className="secondary-button" disabled={busy} onClick={() => onAnalyze({ recall: { campaign_number: ready.query.campaign_number, reference: ready.analysis_reference! }, label: `${ready.query.campaign_number} · ${ready.records.length ? "正式公告全部记录" : "官方空响应观察"}`, defaultQuestion: "整理这份官方公告中的原始事实、措施和证据局限；不判断具体轮胎适用性。" })}>{ready.records.length ? "分析此公告全部记录" : "分析本次官方空响应的局限"}</button></div> : null}
      {ready.records.length ? <RecallRecords key={`${ready.query_id}-${ready.revision}-${mode}`} records={ready.records} /> : <p className="recall-empty">{ready.data_state === "local_snapshot" ? (ready.provenance.length ? "这份历史官方响应为 0 条产品记录。" : "本地没有此编号已保存的历史响应。") : "本次官方查询返回 0 条产品记录。"} 该结果不构成安全结论，也不表示旧公告解除。</p>}
      {ready.notices.map((notice, index) => <p className="recall-help" key={index}>{notice}</p>)}
      {ready.provenance.map(item => <details className="recall-provenance" key={item.snapshot_id}><summary>来源与证据 · Parser {item.parser_version}</summary><dl className="recall-meta"><div><dt>官方来源</dt><dd>{item.source_url}</dd></div><div><dt>原文观察时间</dt><dd>{stamp(item.observed_at)}</dd></div><div><dt>原文 SHA-256</dt><dd><code>{item.raw_hash}</code></dd></div><div><dt>已保存公告修订</dt><dd>{ready.revision ?? "未记录"}</dd></div></dl><button type="button" className="secondary-button" onClick={() => setEvidenceId(item.snapshot_id)}>查看完整原始证据</button></details>)}
      {isHistory(ready) ? <section className="recall-history"><h3>历史公告修订</h3><p className="recall-help">首次观察表示本系统第一次保存公告，不代表官方新发布。历史缺失或查询为空均不会产生解除结论。</p>{ready.revisions_truncated ? <p className="review-warning">仅展示最近 50 条修订，较早历史未在此返回。</p> : null}{ready.revisions.length ? ready.revisions.map(revision => <details key={revision.id} className="recall-provenance"><summary>#{revision.revision} · {kindText(revision.kind)} · {stamp(revision.observed_at)}</summary><DataTree label="该修订完整产品记录" value={revision.records} /><div className="variant-actions">{onAnalyze ? <button type="button" className="text-button" onClick={() => onAnalyze({ recall: { campaign_number: ready.query.campaign_number, reference: { kind: "recall", snapshot_id: revision.snapshot_id, recall_revision_id: revision.id } }, label: `${ready.query.campaign_number} · 历史修订 #${revision.revision}`, defaultQuestion: "整理所选历史公告修订中的原始事实、措施与局限，不判断当前状态或具体轮胎适用性。" })}>分析此历史修订</button> : null}<button type="button" className="text-button" onClick={() => setEvidenceId(revision.snapshot_id)}>查看该修订原文</button>{revision.previous_snapshot_id ? <button type="button" className="text-button" onClick={() => setEvidenceId(revision.previous_snapshot_id)}>查看变化前原文</button> : null}</div></details>) : <p className="recall-empty">没有已保存的公告修订。</p>}</section> : null}
    </section> : !result && !busy && !error ? <div className="recall-empty"><Icon name="shield" size={28} /><h3>{mode === "online" ? "先核对公告，再核对您的轮胎" : "按编号追溯已保存的公告"}</h3><p>{mode === "online" ? "按公告编号检索官方记录，也可先用上方品牌或型号检索定位公告。" : "请主动读取历史；不会自动用旧记录代替在线结果。"}</p></div> : null}
    {evidenceId ? <RecallEvidencePanel key={evidenceId} id={evidenceId} onClose={() => setEvidenceId(null)} /> : null}
  </div>;
}

function RecallDiscoveryProduct({ product, onChoose }: { product: RecallSearchProduct; onChoose: (campaign: string) => void }) {
  const [page, setPage] = useState(0);
  return <article className="recall-record"><div className="recall-record-heading"><div><span className="eyebrow">名称检索 · 产品候选</span><h3>{product.brand || "品牌未声明"} · {product.tireline || "型号未声明"}</h3></div><span className="tag quiet">适用性未评估</span></div><p>{product.size || "尺寸未声明"} · 官方召回计数 {product.recalls_count}</p>
    {product.campaigns.length ? <div className="recall-discovered-campaigns">{product.campaigns.slice(page * 5, page * 5 + 5).map((campaign, index) => <div key={`${campaign.campaign_number}-${index}`} className="recall-discovered-campaign"><div><strong>{campaign.campaign_number}</strong><p>{campaign.subject || "官方未声明主题"}</p><p className="recall-help">官方接收日期：{campaign.report_received_at || "未声明"}</p></div><button type="button" className="secondary-button" disabled={!campaignPattern.test(campaign.campaign_number)} onClick={() => onChoose(campaign.campaign_number)}>选用此编号</button></div>)}{product.campaigns.length > 5 ? <div className="reparse-pages"><button type="button" className="text-button" disabled={!page} onClick={() => setPage(value => value - 1)}>上一组编号</button><span>{page + 1} / {Math.ceil(product.campaigns.length / 5)}</span><button type="button" className="text-button" disabled={(page + 1) * 5 >= product.campaigns.length} onClick={() => setPage(value => value + 1)}>下一组编号</button></div> : null}</div> : <p className="recall-help">该产品的本页响应未列出公告候选，不能据此判定无召回或安全。</p>}
    <DataTree label="官方公告、风险、措施、文件与关联产品完整原文" value={product.campaigns} /><DataTree label="完整产品检索记录" value={product} />
  </article>;
}

function RecallDiscovery({ sessionReady, mode, onChoose, onCreateRule }: { sessionReady: boolean; mode: "online" | "history"; onChoose: (campaign: string) => void; onCreateRule: (search: string) => void }) {
  const sourceAccess = useSourceAccess();
  const deviceFallback = useDeviceQueryFallback("recall_search", sourceId);
  const [search, setSearch] = useState("GENERAL ALTIMAX RT43");
  const [result, setResult] = useState<RecallSearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [denied, setDenied] = useState(false);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const operation = useRef<{ query: RecallSearchQuery; controller: AbortController; deciding: boolean; accessGeneration: number; attemptId: string } | null>(null);
  const accessGeneration = sourceAccess.get(sourceId)?.management.access_generation;
  useEffect(() => {
    const context = operation.current;
    deviceFallback.clear();
    if (mode === "online" && context && context.accessGeneration >= 0 && context.accessGeneration !== accessGeneration) { context.controller.abort(); operation.current = null; setBusy(false); setResult(previous => previous?.data_state === "consent_required" ? null : previous); setError("来源状态已变化，旧检索和待答授权已失效；历史证据仍可读取。"); }
  }, [accessGeneration, mode]);
  const normalized = search.trim().replace(/\s+/g, " ");
  useEffect(() => () => { operation.current?.controller.abort(); operation.current = null; }, []);
  useEffect(() => { if (!sessionReady) { operation.current?.controller.abort(); operation.current = null; deviceFallback.clear(); setResult(null); setEvidenceId(null); setBusy(false); } }, [sessionReady]);
  function clear() { operation.current?.controller.abort(); operation.current = null; deviceFallback.clear(); setResult(null); setBusy(false); setError(""); setDenied(false); setEvidenceId(null); }
  async function query(offset = 0) {
    if (!normalized || !sessionReady || busy) return;
    const priorGeneration = sourceAccess.get(sourceId)?.management.access_generation ?? -1;
    clear(); const context = { query: { search: normalized, offset }, controller: new AbortController(), deciding: false, accessGeneration: -1, attemptId: crypto.randomUUID() }; operation.current = context; setBusy(true);
    try {
      if (mode === "online") {
        let failure: unknown; const metadata = await sourceAccess.refresh(cause => { failure = cause; });
        if (operation.current !== context || context.controller.signal.aborted) return;
        if (!metadata || !sourceAccess.canQuery(sourceId)) { setError("来源当前不能在线采集；可切换到已保存的历史。"); context.accessGeneration = priorGeneration; if (failure) await deviceFallback.show({ search: context.query.search, offset: String(context.query.offset) }, priorGeneration, failure, context.attemptId, "NHTSA 名称检索页", () => operation.current === context && !context.controller.signal.aborted); return; }
      }
      if (operation.current !== context || context.controller.signal.aborted) return;
      context.accessGeneration = sourceAccess.get(sourceId)?.management.access_generation ?? -1;
      const value = mode === "online" ? await tireApi.searchRecalls(context.query, context.controller.signal) : await tireApi.recallSearchHistory(context.query, context.controller.signal);
      if (operation.current === context && !context.controller.signal.aborted) { setResult(value); if (mode === "online") await deviceFallback.show({ search: context.query.search, offset: String(context.query.offset) }, context.accessGeneration, value, context.attemptId, "NHTSA 名称检索页", () => operation.current === context && !context.controller.signal.aborted); }
    } catch (cause) { if (operation.current === context && !context.controller.signal.aborted) { setError(errorText(cause)); if (mode === "online") await deviceFallback.show({ search: context.query.search, offset: String(context.query.offset) }, context.accessGeneration, cause, context.attemptId, "NHTSA 名称检索页", () => operation.current === context && !context.controller.signal.aborted); } }
    finally { if (operation.current === context && !context.controller.signal.aborted) setBusy(false); }
  }
  async function consent(decision: "allow" | "deny") {
    const context = operation.current;
    if (!context || context.controller.signal.aborted || context.deciding || !result?.query_id || result.data_state !== "consent_required" || denied) return;
    context.deciding = true; setBusy(true); setError("");
    deviceFallback.clear();
    try {
      if (!await sourceAccess.ensure(sourceId, "management") || context.controller.signal.aborted || context.accessGeneration !== sourceAccess.get(sourceId)?.management.access_generation) { setError("来源许可待核对或已变化，未使用旧授权。"); return; }
      const approval = await tireApi.consent(result.query_id, decision, context.controller.signal);
      if (operation.current !== context || context.controller.signal.aborted) return;
      if (decision === "deny") { setDenied(true); return; }
      const value = await tireApi.searchRecalls(context.query, context.controller.signal, approval.id);
      if (operation.current === context && !context.controller.signal.aborted) setResult(value);
    } catch (cause) { if (operation.current === context && !context.controller.signal.aborted) setError(errorText(cause)); }
    finally { if (operation.current === context && !context.controller.signal.aborted) { context.deciding = false; setBusy(false); } }
  }
  const ready = result && !denied && ["live", "live_verified_304", "local_snapshot"].includes(result.data_state) ? result : null;
  return <section className="recall-discovery" aria-labelledby="recall-discovery-title"><div className="recall-section-heading"><h3 id="recall-discovery-title">按品牌或型号找公告</h3><span className="tag quiet">NHTSA 产品检索</span></div><p className="recall-help">先查名称候选，再选用编号核验完整公告。名称匹配不能确定您的轮胎受影响。</p><form className="review-form recall-query-form" onSubmit={event => { event.preventDefault(); void query(); }}><label><span>品牌 / 型号关键词</span><input value={search} maxLength={120} required autoComplete="off" onChange={event => { clear(); setSearch(event.target.value); }} /></label><button type="submit" className="primary-button" disabled={!sessionReady || busy || !normalized || (mode === "online" && !sourceAccess.canQuery(sourceId))}>{busy ? "正在读取…" : mode === "online" ? "在线查找候选" : "读取检索历史"}</button></form><p className="recall-help">示例不会自动请求。每页最多 10 项，每次翻页是独立查询；历史仅覆盖已保存的同一关键词与页码。</p>
    {mode === "online" ? <QueryFallbackPolicy kind="recall_search" sourceIds={[sourceId]} sessionReady={sessionReady} /> : null}
    {error ? <p className="inline-error" role="alert">{error}</p> : null}{deviceFallback.panel}
    {result?.data_state === "consent_required" && !denied ? <section className="recall-mode-notice"><h4>在线检索未完成，是否读取这一页的历史？</h4><p>仅授权关键词「{result.query.search}」第 {Math.floor(Number(result.query.offset) / 10) + 1} 页的本次查询。更换关键词或翻页需要重新授权。</p>{result.reason ? <p className="recall-help">原因：{result.reason}</p> : null}<div className="consent-actions"><button type="button" className="primary-button" disabled={busy} onClick={() => void consent("allow")}>仅本次允许</button><button type="button" className="secondary-button" disabled={busy} onClick={() => void consent("deny")}>拒绝，保持无结果</button></div></section> : null}
    {denied ? <p className="recall-mode-notice" role="status">已拒绝此次检索回退，没有读取历史产品候选。</p> : null}
    {result?.data_state === "source_unavailable" ? <p className="recall-mode-notice" role="status">在线来源不可用，未获得可用产品候选。{result.reason ? `原因：${result.reason}。` : ""}不能据此判断是否涉及召回。</p> : null}
    {ready ? <div className="recall-search-results"><div className="recall-section-heading"><h4>产品候选 · {ready.query.search}</h4><span className={`tag ${ready.data_state === "local_snapshot" ? "warning" : "success"}`}>{states[ready.data_state]}</span></div><p className="recall-help">{ready.data_state === "local_snapshot" ? `历史原文观察：${stamp(ready.snapshot_observed_at)}；历史核验：${stamp(ready.verified_at)}，非本次在线数据。` : `本次在线核验：${stamp(ready.verified_at)}`}</p>{ready.products.length ? ready.products.map((product, index) => <RecallDiscoveryProduct key={`${ready.query_id}-${product.id}-${index}`} product={product} onChoose={onChoose} />) : <p className="recall-empty">{ready.data_state === "local_snapshot" ? (ready.provenance.length ? "这一页历史响应未保存产品候选。" : "本地没有这些关键词与页码的历史响应。") : "本次官方查询的这一页未返回产品候选。"} 不能推导全部产品均无召回，也不构成安全结论。</p>}{ready.notices.map((notice, index) => <p className="recall-help" key={index}>{notice}</p>)}{ready.pagination ? <div className="reparse-pages"><button type="button" className="text-button" disabled={!ready.pagination.has_previous || busy || (mode === "online" && !sourceAccess.canQuery(sourceId))} onClick={() => void query(Math.max(0, ready.pagination!.offset - 10))}>{mode === "online" ? "在线查询上一页" : "读取上一页历史"}</button><span>第 {Math.floor(ready.pagination.offset / 10) + 1} 页 · 本页 {ready.pagination.count} 项 · 官方产品匹配总数 {ready.pagination.total}</span><button type="button" className="text-button" disabled={!ready.pagination.has_next || busy || (mode === "online" && !sourceAccess.canQuery(sourceId))} onClick={() => void query(ready.pagination!.offset + 10)}>{mode === "online" ? "在线查询下一页" : "读取下一页历史"}</button></div> : null}{ready.provenance.map(item => <details className="recall-provenance" key={item.snapshot_id}><summary>检索原文与来源 · Parser {item.parser_version}</summary><dl className="recall-meta"><div><dt>来源地址</dt><dd>{item.source_url}</dd></div><div><dt>原文观察时间</dt><dd>{stamp(item.observed_at)}</dd></div><div><dt>SHA-256</dt><dd><code>{item.raw_hash}</code></dd></div></dl><button type="button" className="secondary-button" onClick={() => setEvidenceId(item.snapshot_id)}>读取完整检索证据</button></details>)}</div> : null}
    {ready ? <div className="discovery-create-entry"><button type="button" className="secondary-button" onClick={() => onCreateRule(ready.query.search)}>持续发现这些关键词的召回候选</button><p className="recall-help">创建规则只使用名称关键词；无论本页为空还是来自历史，都不会把这一个页面当作完整扫描基线。</p></div> : null}
    {evidenceId ? <RecallEvidencePanel key={evidenceId} id={evidenceId} kind="search" onClose={() => setEvidenceId(null)} /> : null}
  </section>;
}

function RecallRuleEditor({ ruleId, campaign, onClose, onSaved }: { ruleId: string | null; campaign: string; onClose: () => void; onSaved: () => void }) {
  const sourceAccess = useSourceAccess();
  const [rule, setRule] = useState<RecallRuleDetail | null>(null);
  const [number, setNumber] = useState(campaign);
  const [settings, setSettings] = useState<RecallRuleSettings>({ name: "", interval_seconds: 21600, enabled: false, archived: false });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const operation = useRef<AbortController | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); return () => operation.current?.abort(); }, []);
  useEffect(() => {
    if (!ruleId) return;
    const controller = new AbortController(); setRule(null); setError("");
    void tireApi.recallRule(ruleId, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      setRule(value); setNumber(value.query.campaign_number); setSettings({ name: value.name, interval_seconds: value.interval_seconds, enabled: value.enabled, archived: value.archived }); setStale(false);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [ruleId, attempt]);
  async function save(action: "save" | "archive" | "restore") {
    if (operation.current || stale || (ruleId && !rule) || !campaignPattern.test(normalize(number))) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError("");
    const next = { ...settings, name: settings.name.trim(), ...(action === "archive" ? { archived: true, enabled: false } : action === "restore" ? { archived: false, enabled: false } : {}) };
    try {
      if (action === "save" && next.enabled && !await sourceAccess.ensure(sourceId)) { setError("来源当前不能在线采集。可取消启用后保存暂停规则；原规则和历史继续保留。"); return; }
      if (controller.signal.aborted) return;
      if (rule) await tireApi.reviseRecallRule(rule.id, rule.revision, next, controller.signal);
      else await tireApi.createRecallRule({ campaign_number: normalize(number) }, { name: next.name, interval_seconds: next.interval_seconds, enabled: next.enabled }, controller.signal);
      if (!controller.signal.aborted) { onSaved(); onClose(); }
    } catch (cause) { if (!controller.signal.aborted) { setError(errorText(cause)); if (!(cause instanceof ApiError) || cause.status >= 500) { setStale(true); setError("保存结果尚未确认。请关闭编辑并刷新规则，核对是否已保存后再操作。"); } else if (cause.status === 409) setStale(true); } }
    finally { if (operation.current === controller) operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  const locked = busy || stale;
  return <section className="recall-rule-editor" aria-labelledby="recall-rule-heading"><div className="recall-section-heading"><h3 id="recall-rule-heading" ref={heading} tabIndex={-1}>{ruleId ? "编辑公告监控规则" : "创建公告监控规则"}</h3><button type="button" className="text-button" disabled={busy} onClick={onClose}>关闭编辑</button></div>
    <SourceStatus sourceId={sourceId} /><SourceOnlineNotice sourceId={sourceId} /><p className="review-boundary">规则仅属于当前浏览器会话，记录在本地。默认暂停；启用后由独立 Worker 按计划在线核验所选公告。这里只保存规则，不启动后台服务。</p>
    {error ? <p className="inline-error" role="alert">{error}{ruleId ? <button type="button" className="text-button" disabled={busy} onClick={() => setAttempt(value => value + 1)}>重新读取规则</button> : null}</p> : null}
    {ruleId && !rule ? <p role="status">正在读取规则…</p> : <form className="review-form" onSubmit={event => { event.preventDefault(); void save("save"); }}><label><span>规则名称</span><input required maxLength={120} disabled={locked || settings.archived} value={settings.name} onChange={event => setSettings(value => ({ ...value, name: event.target.value }))} /></label><label><span>公告编号（固定监控目标）</span><input required maxLength={9} pattern="[0-9]{2}[Tt][0-9]{6}" disabled={!!ruleId || locked} value={number} onChange={event => setNumber(event.target.value)} /></label><label><span>在线检查间隔（1–168 小时）</span><input type="number" min={1} max={168} step={1} required disabled={locked || settings.archived} value={settings.interval_seconds / 3600} onChange={event => setSettings(value => ({ ...value, interval_seconds: Number(event.target.value) * 3600 }))} /></label><label className="review-checkbox"><input type="checkbox" disabled={locked || settings.archived || (!settings.enabled && !sourceAccess.canQuery(sourceId))} checked={settings.enabled} onChange={event => setSettings(value => ({ ...value, enabled: event.target.checked }))} />启用此规则</label><p className="recall-help">提醒涵盖本系统首次观察和公告内容变化；首次观察不等于新发布召回。来源失败、空结果或暂停监控均不能代表召回解除。</p><div className="variant-actions">{!settings.archived ? <button type="submit" className="primary-button" disabled={locked || !campaignPattern.test(normalize(number)) || !settings.name.trim() || settings.interval_seconds < 3600 || settings.interval_seconds > 604800}>{busy ? "保存中…" : "保存监控规则"}</button> : null}{rule ? <button type="button" className="secondary-button" disabled={locked} onClick={() => void save(settings.archived ? "restore" : "archive")}>{settings.archived ? "恢复为暂停规则" : "归档规则"}</button> : null}</div></form>}
    {rule ? <div className="recall-history"><p className="recall-help">当前修订 #{rule.revision} · {rule.query.campaign_number}</p>{rule.history_truncated ? <p className="review-warning">仅返回最近 50 条规则修订。</p> : null}<DataTree label="规则追加修订历史" value={rule.history} /></div> : null}
  </section>;
}

function RecallMonitoring({ sessionReady, campaign }: { sessionReady: boolean; campaign: string }) {
  const [taskJobId, setTaskJobId] = useState<string | null>(null);
  const sourceAccess = useSourceAccess();
  const [rules, setRules] = useState<RecallPage<RecallRule> | null>(null);
  const [notices, setNotices] = useState<RecallPage<RecallNotification> | null>(null);
  const [ruleOffset, setRuleOffset] = useState(0);
  const [noticeOffset, setNoticeOffset] = useState(0);
  const [archived, setArchived] = useState(false);
  const [editor, setEditor] = useState<string | null | undefined>(undefined);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mutation = useRef<AbortController | null>(null);
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => () => mutation.current?.abort(), []);
  useEffect(() => {
    if (!sessionReady) return;
    const controller = new AbortController(); setLoading(true); setError(""); setRules(null); setNotices(null);
    void Promise.all([tireApi.recallRules(controller.signal, ruleOffset, archived), tireApi.recallNotifications(controller.signal, noticeOffset)]).then(([ruleList, noticeList]) => { if (!controller.signal.aborted) { setRules(ruleList); setNotices(noticeList); } }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [sessionReady, ruleOffset, noticeOffset, archived, attempt]);
  async function mark(notice: RecallNotification) {
    if (mutation.current) return;
    const controller = new AbortController(); mutation.current = controller; setBusy(true); setError("");
    try { await tireApi.markRecallNotification(notice.id, !notice.read_at, controller.signal); if (!controller.signal.aborted) setAttempt(value => value + 1); }
    catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (mutation.current === controller) mutation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  function closeEditor() { setEditor(undefined); title.current?.focus({ preventScroll: true }); }
  return <section className="recall-monitoring"><div className="recall-section-heading"><h3 ref={title} tabIndex={-1}>公告监控与站内提醒</h3><div className="variant-actions"><button type="button" className="text-button" disabled={!sessionReady || busy || loading} onClick={() => setAttempt(value => value + 1)}>刷新记录</button><button type="button" className="secondary-button" disabled={!sessionReady || editor !== undefined} onClick={() => setEditor(null)}>创建公告监控</button></div></div><p className="review-boundary">LOCAL SNAPSHOT · 当前浏览器会话的本地规则与提醒。只跟踪已选公告的后续变化，不自动发现全品牌新公告；不发送邮件、短信或其他外部消息。</p>
    {error ? <p role="alert" className="inline-error">{error}</p> : null}
    <div className="review-form"><label><span>监控规则范围</span><select value={archived ? "archived" : "active"} disabled={busy || editor !== undefined} onChange={event => { setArchived(event.target.value === "archived"); setRuleOffset(0); }}><option value="active">使用中的规则</option><option value="archived">已归档规则</option></select></label></div>
    {editor !== undefined ? <RecallRuleEditor key={editor || "new"} ruleId={editor} campaign={campaign} onClose={closeEditor} onSaved={() => { setRuleOffset(0); setAttempt(value => value + 1); }} /> : null}
    {loading ? <p role="status">正在读取本地记录…</p> : <><h4>监控规则 · {rules?.total ?? 0}</h4>{rules?.items.length ? rules.items.map(rule => <article className="recall-rule" key={rule.id}><div className="recall-section-heading"><h4>{rule.name}</h4><span className="tag quiet">{rule.archived ? "已归档" : rule.enabled ? "已启用" : "已暂停"}</span></div><SourceStatus sourceId={sourceId} /><SourceOnlineNotice sourceId={sourceId} /><p>{rule.query.campaign_number} · 每 {rule.interval_seconds / 3600} 小时 · 修订 #{rule.revision}</p><p className="recall-help">最近完成：{rule.job.last_run ? `${stamp(rule.job.last_run.finished_at)} · ${states[rule.job.last_run.state as keyof typeof states] || rule.job.last_run.state}` : "尚无完成记录"}{rule.job.next_due_at ? `；计划时间：${stamp(rule.job.next_due_at)}` : ""}</p>{rule.job.last_run?.reason ? <p className="recall-help">最近原因：{rule.job.last_run.reason}</p> : null}<button type="button" className="text-button" disabled={editor !== undefined} onClick={() => setTaskJobId(rule.job.id)}>查看任务运行</button><button type="button" className="text-button" disabled={editor !== undefined} onClick={() => setEditor(rule.id)}>编辑与修订历史</button></article>) : <p className="recall-empty">此页没有监控规则。在线查询不会自动创建或启用规则。</p>}
      {rules && (ruleOffset > 0 || ruleOffset + rules.items.length < rules.total) ? <div className="reparse-pages"><button type="button" className="text-button" disabled={!ruleOffset || busy} onClick={() => setRuleOffset(Math.max(0, ruleOffset - 10))}>上一页规则</button><span>第 {Math.floor(ruleOffset / 10) + 1} 页 · 共 {rules.total} 条</span><button type="button" className="text-button" disabled={ruleOffset + rules.items.length >= rules.total || busy} onClick={() => setRuleOffset(ruleOffset + 10)}>下一页规则</button></div> : null}
      <h4>站内提醒 · {notices?.total ?? 0}</h4>{notices?.items.length ? notices.items.map(notice => <article className="recall-notification" key={notice.id}><div className="recall-section-heading"><h4>{notice.rule_name} · {kindText(notice.kind)}</h4><span className="tag quiet">{notice.read_at ? "已读" : "未读"}</span></div><p>{notice.campaign_number} · 观察时间 {stamp(notice.observed_at)} · 公告修订 #{notice.revision}</p><p className="recall-help">{notice.kind === "first_observed" ? "这是本系统首次观察到该公告，不代表官方刚发布召回。" : "此记录保留变化前后原文，不将缺失内容解释为召回解除。"}</p><DataTree label="变化前完整产品记录" value={notice.changes.before} /><DataTree label="变化后完整产品记录" value={notice.changes.after} /><div className="variant-actions"><button type="button" className="text-button" onClick={() => setEvidenceId(notice.snapshot_id)}>查看变化后原文</button>{notice.previous_snapshot_id ? <button type="button" className="text-button" onClick={() => setEvidenceId(notice.previous_snapshot_id)}>查看变化前原文</button> : null}<button type="button" className="text-button" disabled={busy} onClick={() => void mark(notice)}>标记为{notice.read_at ? "未读" : "已读"}</button></div></article>) : <p className="recall-empty">此页没有站内提醒。没有提醒不能作为轮胎安全结论。</p>}
      {notices && (noticeOffset > 0 || noticeOffset + notices.items.length < notices.total) ? <div className="reparse-pages"><button type="button" className="text-button" disabled={!noticeOffset || busy} onClick={() => setNoticeOffset(Math.max(0, noticeOffset - 10))}>上一页提醒</button><span>第 {Math.floor(noticeOffset / 10) + 1} 页 · 共 {notices.total} 条</span><button type="button" className="text-button" disabled={noticeOffset + notices.items.length >= notices.total || busy} onClick={() => setNoticeOffset(noticeOffset + 10)}>下一页提醒</button></div> : null}</>}
    {taskJobId ? <MonitorTaskDialog key={taskJobId} kind="recall" jobId={taskJobId} onClose={() => setTaskJobId(null)} /> : null}
    {evidenceId ? <RecallEvidencePanel key={evidenceId} id={evidenceId} onClose={() => setEvidenceId(null)} /> : null}
  </section>;
}

export function RecallWorkspace({ sessionReady, initialCampaign, onAnalyze }: { sessionReady: boolean; initialCampaign?: string; onAnalyze?: (target: AITarget) => void }) {
  type Mode = "online" | "history" | "monitor" | "discovery_monitor";
  const [mode, setMode] = useState<Mode>("online");
  const [visited, setVisited] = useState({ monitor: false, discovery_monitor: false });
  const [campaign, setCampaign] = useState(initialCampaign || "23T001000");
  const [campaignNotice, setCampaignNotice] = useState("");
  const [seed, setSeed] = useState<DiscoveryRuleSeed | null>(null);
  const seedSequence = useRef(0);
  useEffect(() => { if (initialCampaign) { setCampaign(initialCampaign); setMode("online"); setCampaignNotice(`已填入 ${initialCampaign}，尚未在线核验。请核对编号后明确点击“在线核验公告”。`); } }, [initialCampaign]);
  const consumeSeed = useCallback(() => setSeed(null), []);
  function changeMode(value: Mode) {
    setMode(value);
    if (value === "monitor" || value === "discovery_monitor") setVisited(previous => ({ ...previous, [value]: true }));
  }
  function chooseCampaign(value: string) {
    setCampaign(value); changeMode("online"); setCampaignNotice(`已填入 ${value}，尚未在线核验。请核对编号后明确点击“在线核验公告”。`);
    requestAnimationFrame(() => document.getElementById("recall-campaign-input")?.focus());
  }
  function createDiscoveryRule(search: string) { setSeed({ search, sequence: ++seedSequence.current }); changeMode("discovery_monitor"); }
  return <div className="recall-workspace"><SourceStatus sourceId={sourceId} /><SourceOnlineNotice sourceId={sourceId} /><div className="recall-boundary"><Icon name="shield" size={22} /><p>{boundary}</p></div>
    <div className="recall-modes" role="group" aria-label="召回功能"><button type="button" aria-pressed={mode === "online"} onClick={() => changeMode("online")}>官方在线查询</button><button type="button" aria-pressed={mode === "history"} onClick={() => changeMode("history")}>已保存的历史</button><button type="button" aria-pressed={mode === "monitor"} onClick={() => changeMode("monitor")}>公告监控</button><button type="button" aria-pressed={mode === "discovery_monitor"} onClick={() => changeMode("discovery_monitor")}>名称发现监控</button></div>
    {visited.monitor ? <div hidden={mode !== "monitor"}><RecallMonitoring sessionReady={sessionReady} campaign={campaign} /></div> : null}
    {visited.discovery_monitor ? <div hidden={mode !== "discovery_monitor"}><RecallDiscoveryMonitoring sessionReady={sessionReady} seed={seed} onSeedHandled={consumeSeed} onChoose={chooseCampaign} /></div> : null}
    {mode === "online" || mode === "history" ? <><RecallDiscovery key={`discovery-${mode}`} sessionReady={sessionReady} mode={mode} onChoose={chooseCampaign} onCreateRule={createDiscoveryRule} /><div className="recall-campaign-section"><h3>按公告编号核验</h3>{campaignNotice && mode === "online" ? <p className="review-boundary" role="status">{campaignNotice}</p> : null}<RecallQueryPanel key={mode} onAnalyze={onAnalyze} sessionReady={sessionReady} mode={mode} campaign={campaign} onCampaign={value => { setCampaign(value); setCampaignNotice(""); }} /></div></> : null}
  </div>;
}

export default function RecallDialog({ onClose, sessionReady, initialCampaign, onAnalyze }: { onClose: () => void; sessionReady: boolean; initialCampaign?: string; onAnalyze?: (target: AITarget) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { node?.close(); (previous?.isConnected && !previous.closest("dialog:not([open])") ? previous : document.querySelector<HTMLElement>("[data-recall-entry]"))?.focus({ preventScroll: true }); };
  }, []);
  return <dialog ref={dialog} className="fact-review-dialog recall-dialog" aria-labelledby="recall-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}><div className="fact-review-heading"><div><span className="eyebrow">NHTSA · TIRE RECALLS</span><h2 id="recall-title">轮胎召回公告</h2><p>美国官方公告 · 原文证据与后续变化</p></div><button type="button" className="text-button" onClick={onClose}>关闭</button></div><div className="fact-review-content"><RecallWorkspace sessionReady={sessionReady} initialCampaign={initialCampaign} onAnalyze={onAnalyze} /></div></dialog>;
}
