"use client";

import { SourceStatus } from "./source-status";
import QuarantineReview from "./quarantine-review";

import { useEffect, useRef, useState } from "react";
import type { QuarantineEvidence, QuarantineRecord, Source, SourceHealthRecord, SourceHealthResult } from "@tire/domain-types";
import { tireApi } from "@tire/api-client";
import { Icon } from "./icons";
import CaptureJournal from "./capture-journal";
import EvidenceDocuments from "./evidence-documents";
import ParserReleases from "./parser-releases";
import GoldenSets from "./golden-sets";
import IdentityDirectory from "./identity-directory";
import IdentityMigration from "./identity-migration";
import FieldConflictCenter from "./field-conflicts";

const healthLabels: Record<SourceHealthRecord["status"], string> = {
  unknown: "未检查", healthy: "最近核验正常", degraded: "最近核验未完成", quarantined: "数据更新已隔离",
};
const reasonLabels: Record<string, string> = {
  vehicle_identity_changed: "同一车型标识的代际、地区或来源身份发生变化，需人工核对。",
  source_quality_quarantined: "来源数据出现明显缺失或无法可靠对应，已暂停本次更新。",
  field_loss_threshold: "已知参数缺失过多", row_loss_threshold: "已知规格缺失过多", ambiguous_alignment: "规格无法可靠对应",
  source_rate_limited: "来源限制了请求频率，请稍后重试。", circuit_open: "连续请求失败，已暂缓在线请求。",
  robots_disallowed: "来源的抓取规则不允许访问。", upstream_timeout: "来源响应超时。",
  upstream_network_error: "暂时无法连接来源。", parser_schema_changed: "来源页面未通过解析校验，需要重新核验。",
  parser_timeout: "来源内容解析超时，本次核验未完成。", parser_cancelled: "来源解析已取消，未采纳新的参数。",
  parser_isolation_unavailable: "本机解析环境暂时不可用。", parser_failed: "来源内容解析未完成，需要检查解析记录。",
  parser_crashed: "来源内容解析意外中断。", parser_code_mismatch: "解析代码与已固定版本不一致，需要核对解析器部署。",
  parser_protocol_invalid: "解析结果未通过完整性校验，本次参数未被采纳。",
  disabled: "来源已停用。", source_disabled: "来源已停用。", configuration_required: "来源尚待配置。",
  unsupported_model: "来源暂不支持该型号。", not_implemented: "来源尚未接入。",
  source_size_required: "此来源按尺寸提供规格，请填写轮胎尺寸。", invalid_size: "轮胎尺寸不符合来源支持的格式。",
  vehicle_source_fetch_failed: "车型官方来源暂时无法连接。", vehicle_source_schema_changed: "车型配置表结构发生变化。",
  vehicle_generation_not_verified: "车型代际的官方来源尚待核验。", vehicle_network_unavailable: "车型来源网络暂时不可用。",
  source_schema_validation_failed: "来源参数未通过结构校验，不能作为事实使用。",
  evidence_capture_failed: "原文保存未完成，本次参数未被采纳，请稍后重试。",
};
const formatTime = (value: string | null) => {
  if (!value) return "尚无记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
};
const formatRatio = (value: number) => new Intl.NumberFormat("zh-CN", { style: "percent", maximumFractionDigits: 1 }).format(value);
const errorText = (error: unknown) => error instanceof Error ? error.message : "请求未完成，请重试。";
const safeUrl = (value: string) => { try { const url = new URL(value); return url.protocol === "https:" || url.protocol === "http:" ? url.href : undefined; } catch { return undefined; } };

function QualityReason({ code }: { code: string }) {
  const label = reasonLabels[code];
  return label ? <span>{label}</span> : <span>本次核验未完成<details className="quality-error-code"><summary>查看原因代码</summary><code>{/^[a-z][a-z0-9_-]{0,79}$/i.test(code) ? code : "unclassified_error"}</code></details></span>;
}

export default function SourceQuality({ sources, sessionReady }: { sources: Source[]; sessionReady: boolean }) {
  const [health, setHealth] = useState<SourceHealthResult | null>(null);
  const [healthError, setHealthError] = useState("");
  const [healthLoading, setHealthLoading] = useState(true);
  const [healthRevision, setHealthRevision] = useState(0);
  const [sourceId, setSourceId] = useState("");
  const [records, setRecords] = useState<QuarantineRecord[] | null>(null);
  const [recordSourceIds, setRecordSourceIds] = useState<string[]>([]);
  const [listError, setListError] = useState("");
  const [listLoading, setListLoading] = useState(true);
  const [listRevision, setListRevision] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<QuarantineEvidence | null>(null);
  const [detailError, setDetailError] = useState("");
  const [detailRevision, setDetailRevision] = useState(0);
  const listController = useRef<AbortController | null>(null);
  const detailController = useRef<AbortController | null>(null);
  const detailPanel = useRef<HTMLElement>(null);
  const listPanel = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!sessionReady) return;
    const controller = new AbortController();
    setHealthLoading(true); setHealthError(""); setHealth(null);
    void tireApi.sourceHealth(controller.signal).then(result => {
      if (!controller.signal.aborted) setHealth(result);
    }).catch(error => { if (!controller.signal.aborted) setHealthError(errorText(error)); })
      .finally(() => { if (!controller.signal.aborted) setHealthLoading(false); });
    return () => controller.abort();
  }, [sessionReady, healthRevision]);

  useEffect(() => {
    if (!sessionReady) return;
    const controller = new AbortController();
    listController.current = controller;
    setListLoading(true); setListError(""); setRecords(null);
    void tireApi.quarantines(sourceId, controller.signal).then(result => {
      if (!controller.signal.aborted) { setRecords(result.items); setRecordSourceIds(result.source_ids || []); }
    }).catch(error => { if (!controller.signal.aborted) setListError(errorText(error)); })
      .finally(() => { if (!controller.signal.aborted) setListLoading(false); });
    return () => controller.abort();
  }, [sessionReady, sourceId, listRevision]);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    detailController.current = controller;
    setDetail(null); setDetailError("");
    void tireApi.quarantineEvidence(selectedId, controller.signal).then(result => {
      if (!controller.signal.aborted) setDetail(result);
    }).catch(error => { if (!controller.signal.aborted) setDetailError(errorText(error)); });
    detailPanel.current?.focus({ preventScroll: true });
    detailPanel.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    return () => controller.abort();
  }, [selectedId, detailRevision]);

  function closeDetail() {
    detailController.current?.abort(); detailController.current = null;
    setSelectedId(""); setDetail(null); setDetailError("");
  }

  function selectSource(id: string) {
    if (id !== sourceId) listController.current?.abort();
    closeDetail(); setSourceId(id); setListError("");
    if (id !== sourceId) { setRecords(null); setListLoading(true); }
    listPanel.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function refreshList() {
    listController.current?.abort();
    closeDetail(); setRecords(null); setListError(""); setListLoading(true); setListRevision(value => value + 1);
  }

  function openDetail(id: string) {
    detailController.current?.abort(); setDetail(null); setDetailError(""); setSelectedId(id); setDetailRevision(value => value + 1);
  }

  const names = new Map(sources.map(source => [source.id, source.name]));
  const sourceName = (id: string) => names.get(id) || (id.startsWith("xiaomi") ? "小米汽车官方配置" : id);
  const sourceIds = [...new Set([...sources.map(source => source.id), ...(health?.sources.map(source => source.source_id) || []), ...recordSourceIds])];
  const totalAttempts = health?.sources.reduce((sum, source) => sum + source.attempts, 0);
  const totalQuarantined = health?.sources.reduce((sum, source) => sum + source.quarantined_count, 0);
  const totalRejected = health?.sources.reduce((sum, source) => sum + (source.rejected_count || 0), 0);

  return <div className="source-quality">
    <section className="quality-health-panel" aria-labelledby="source-health-title" aria-busy={healthLoading}>
      <div className="panel-title"><span id="source-health-title"><Icon name="shield" size={18} />来源健康</span><button type="button" className="text-button" disabled={!sessionReady || healthLoading} onClick={() => setHealthRevision(value => value + 1)}><Icon name="refresh" size={14} />刷新记录</button></div>
      <p className="quality-intro">记录轮胎与车型来源最近 24 小时的在线核验，打开此页不会向来源发起查询。此期间没有检查记录的来源保持「未检查」。</p>
      {healthLoading ? <div className="run-loading" role="status"><span className="spinner" />正在读取来源健康记录…</div> : healthError ? <div className="inline-error" role="alert">来源健康记录读取失败：{healthError}<button type="button" className="text-button" onClick={() => setHealthRevision(value => value + 1)}>重试</button></div> : health ? <>
        <div className="quality-window"><span>最近 24 小时</span><span>核验 <b>{totalAttempts}</b> 次 · 字段隔离 <b>{totalQuarantined}</b> 次 · 异常原文 <b>{totalRejected}</b> 份</span><small>{formatTime(health.window.since)} — {formatTime(health.window.until)}</small></div>
        <div className="quality-health-list">{health.sources.map(source => <article className="quality-health-item" key={source.source_id}>
          <div className="quality-item-heading"><h3>{sourceName(source.source_id)}</h3><span className={`tag ${source.status === "healthy" ? "success" : source.status === "unknown" ? "quiet" : "warning"}`}>{source.status === "unknown" && source.attempts > 0 ? "尚无完成核验" : healthLabels[source.status]}</span></div>
          <dl className="quality-times"><div><dt>最后尝试</dt><dd>{formatTime(source.last_attempt_at)}</dd></div><div><dt>最后成功</dt><dd>{formatTime(source.last_success_at)}</dd></div></dl>
          <SourceStatus sourceId={source.source_id} />{source.last_reason ? <div className="quality-health-reason"><QualityReason code={source.last_reason} /></div> : source.status === "unknown" ? <p className="quality-unknown">最近 24 小时尚无已完成的在线核验，当前可用性未知。</p> : null}
          <div className="quality-item-footer"><span>24 小时：成功 {source.successes} · 失败 {source.failures} · 字段隔离 {source.quarantined_count} · 异常原文 {source.rejected_count || 0}</span>{source.quarantined_count > 0 || source.rejected_count > 0 ? <button type="button" className="text-button" onClick={() => selectSource(source.source_id)}>查看异常记录<Icon name="arrow" size={14} /></button> : null}</div>
        </article>)}</div>
        {!health.sources.length ? <p className="quality-empty">尚无已登记来源的健康记录。</p> : null}
      </> : null}
    </section>

    <section ref={listPanel} className="quarantine-panel" aria-labelledby="quarantine-title" aria-busy={listLoading}>
      <div className="panel-title"><span id="quarantine-title">待核验的异常记录</span><span className="tag warning">LOCAL SNAPSHOT</span></div>
      <p className="quality-intro">异常内容被单独留存，不会覆盖已确认的参数。列表仅展示记录信息；点击「核对隔离原文」后读取对应历史内容。</p>
      <div className="quarantine-filter"><label><span>筛选来源</span><select value={sourceId} onChange={event => selectSource(event.target.value)}><option value="">全部来源</option>{sourceIds.map(id => <option key={id} value={id}>{sourceName(id)}</option>)}</select></label><button type="button" className="secondary-button" disabled={!sessionReady || listLoading} onClick={refreshList}><Icon name="refresh" size={15} />刷新列表</button></div>
      {listLoading ? <div className="run-loading" role="status"><span className="spinner" />正在读取异常记录信息…</div> : listError ? <div className="inline-error" role="alert">异常记录读取失败：{listError}<button type="button" className="text-button" onClick={refreshList}>重试</button></div> : records?.length ? <>
        <p className="quarantine-list-count">显示最近 {records.length} 条隔离记录（最多 50 条，不限于最近 24 小时）</p>
        <div className="quarantine-list">{records.map(record => <article className={`quarantine-item${selectedId === record.id ? " selected" : ""}`} key={record.id}>
          <div className="quality-item-heading"><h3>{sourceName(record.source_id)}</h3><time dateTime={record.observed_at}>{formatTime(record.observed_at)}</time></div>
          <ul className="quality-reason-list">{record.reason_codes.map(code => <li key={code}><QualityReason code={code} /></li>)}</ul>
          <p className="quarantine-comparison">{record.metrics ? <>{record.target_kind === "vehicle" ? "车型资料" : "轮胎规格"} · 本次 {record.metrics.candidate_rows} 项 · 对照记录 {record.metrics.baseline_rows} 项</> : <>{record.target_kind === "vehicle" ? "车型" : "轮胎"}原文 · {record.stage === "parser" ? "解析未通过" : "参数校验未通过"}，未采纳为事实</>}</p>
          <button type="button" className="secondary-button" aria-expanded={selectedId === record.id} aria-controls="quarantine-evidence" onClick={() => selectedId === record.id ? closeDetail() : openDetail(record.id)}><Icon name="file" size={15} />{selectedId === record.id ? "关闭隔离原文" : "核对隔离原文"}</button>
        </article>)}</div>
      </> : <p className="quality-empty">{sourceId ? "该来源暂无隔离记录。" : "暂无隔离记录。"} 未检查的来源仍需在线核验。</p>}
      {selectedId ? <section id="quarantine-evidence" className="quarantine-evidence" ref={detailPanel} tabIndex={-1} aria-labelledby="quarantine-evidence-title">
        <div className="panel-title"><span id="quarantine-evidence-title">隔离原始记录</span><button type="button" className="icon-button" aria-label="关闭隔离原文" onClick={closeDetail}><Icon name="close" size={18} /></button></div>
        <div className="snapshot-banner"><strong>LOCAL SNAPSHOT · 未采纳的历史内容</strong><span>这份来源内容未通过数据质量检查，不作为当前参数，也不会加入比较。</span></div>
        {detailError ? <div className="inline-error" role="alert">隔离原文读取失败：{detailError}<button type="button" className="text-button" onClick={() => { setDetailError(""); setDetailRevision(value => value + 1); }}>重试读取</button></div> : detail?.id === selectedId ? <QuarantineDetail detail={detail} name={sourceName(detail.source_id)} /> : <div className="run-loading" role="status"><span className="spinner" />正在读取所选隔离原文…</div>}
      </section> : null}
    </section>
    <FieldConflictCenter sources={sources} sessionReady={sessionReady} />
    <GoldenSets sources={sources} sessionReady={sessionReady} />
    <ParserReleases sources={sources} sessionReady={sessionReady} />
    <IdentityMigration sessionReady={sessionReady} />
    <IdentityDirectory sessionReady={sessionReady} />
    <CaptureJournal sources={sources} sessionReady={sessionReady} />
    <EvidenceDocuments sessionReady={sessionReady} />
  </div>;
}

function QuarantineDetail({ detail, name }: { detail: QuarantineEvidence; name: string }) {
  const url = safeUrl(detail.source_url);
  return <div className="quarantine-detail-content">
    <dl className="quality-detail-meta"><div><dt>来源</dt><dd>{name}</dd></div><div><dt>原观察时间</dt><dd>{formatTime(detail.observed_at)}</dd></div><div><dt>原始页面</dt><dd>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{detail.source_url}<Icon name="external" size={13} /></a> : detail.source_url}</dd></div><div><dt>未采纳原因</dt><dd><ul className="quality-reason-list">{detail.reason_codes.map(code => <li key={code}><QualityReason code={code} /></li>)}</ul></dd></div></dl>
    {detail.metrics ? <div className="quality-loss-metrics"><div><span>规格缺失</span><strong>{detail.metrics.lost_rows} / {detail.metrics.baseline_rows}</strong><small>{formatRatio(detail.metrics.row_loss_ratio)}</small></div><div><span>已知字段缺失</span><strong>{detail.metrics.lost_fields} / {detail.metrics.known_fields}</strong><small>{formatRatio(detail.metrics.field_loss_ratio)}</small></div></div> : <p className="quality-intro">{detail.target_kind === "vehicle" ? "车型" : "轮胎"}原文未能形成通过校验的参数记录，未计算字段缺失比例。此原文不会用于在线验证、授权回退或比较。</p>}
    {detail.quality?.groups ? <section className="vehicle-quality-groups" aria-label="车型分组质量检查"><h4>按资料类型分别检查</h4><p className="quality-intro">任一分组的记录或已知字段缺失达到 30% 即隔离，合计比例不替代分组判断。</p>{Object.entries(detail.quality.groups).map(([key, group]) => <div key={key}><h5>{{ vehicle: "车型信息", trims: "配置版本", fitments: "轮毂与轴位" }[key] || key}</h5><div className="quality-loss-metrics"><div><span>记录缺失</span><strong>{group.lost_rows} / {group.baseline_rows}</strong><small>{formatRatio(group.row_loss_ratio)}</small></div><div><span>已知字段缺失</span><strong>{group.lost_field_count} / {group.known_fields}</strong><small>{formatRatio(group.field_loss_ratio)}</small></div></div>{group.reason_codes.length ? <ul className="quality-reason-list">{group.reason_codes.map(code => <li key={code}><QualityReason code={code} /></li>)}</ul> : null}</div>)}</section> : null}
    <details className="quality-technical"><summary>查看记录校验信息</summary><dl className="quality-detail-meta"><div><dt>解析器版本</dt><dd>{detail.parser_version}</dd></div><div><dt>SHA-256</dt><dd className="mono">{detail.raw_hash}</dd></div><div><dt>对照快照</dt><dd className="mono">{detail.previous_snapshot_id || "无适用基线（未形成合格参数）"}</dd></div><div><dt>隔离记录</dt><dd className="mono">{detail.id}</dd></div></dl></details>
    <details className="raw-evidence"><summary>展开纯文本原文<span className="mono">TEXT</span></summary><p>仅作为待核验证据展示，不执行来源脚本或指令。内容类型：{detail.content_type}</p><pre>{detail.body}</pre></details>
    {detail.kind === "field_loss" ? <QuarantineReview key={detail.id} id={detail.id} /> : <p className="quality-intro">解析或结构校验失败须先修复解析器，不能人工跳过。</p>}
  </div>;
}
