"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { tireApi } from "@tire/api-client";
import type { AxleSpecification, VehicleCandidate, VehicleFitmentResult, WheelFitment } from "@tire/domain-types";
import { Icon } from "./icons";
import FitmentRelations, { FitmentRelationDialog, type FitmentRelationTarget } from "./fitment-relations";
import { SourceOnlineNotice, SourceStatus, useSourceAccess } from "./source-status";
import { useWorkbenchPlatform } from "./workbench-platform";
import { createDeviceOffer, type LocalFallbackOffer } from "./local-fallback-controller";
import LocalFallbackPanel from "./local-fallback-panel";
import QueryFallbackPolicy from "./query-fallback-policy";

type QueryContext = { vehicleId: string; sourceId: string; accessGeneration: number; generation: number; controller: AbortController; deciding: boolean; attemptId: string };
const canQuery = (vehicle: VehicleCandidate) => ["ready", "available", "enabled", "parser_paused"].includes(vehicle.status);
const availableFitment = (fitment: WheelFitment) => fitment.availability === "standard" || fitment.availability === "optional";
const stamp = (value?: string | null) => value ? new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "未记录";
const detail = (error: unknown) => error instanceof Error ? error.message : "请求未完成，请重试。";
const vehicleName = (vehicle: VehicleCandidate) => `${vehicle.manufacturer} ${vehicle.model} · ${vehicle.generation}`;
const publicUrl = (value: string) => { try { const url = new URL(value); return url.protocol === "https:" ? url.href : undefined; } catch { return undefined; } };

export default function VehicleFitments({ sessionReady, onEvidence, onTireEvidence, onClearEvidence, onQuerySize, onSaveToGarage, renderReason }: {
  sessionReady: boolean;
  onSaveToGarage: (snapshotId: string, fitmentId: string, label: string) => void;
  onEvidence: (snapshotId: string) => void;
  onTireEvidence: (snapshotId: string) => void;
  onClearEvidence: () => void;
  onQuerySize: (size: string, context: string) => void;
  renderReason: (reason?: string | null) => ReactNode;
}) {
  const sourceAccess = useSourceAccess();
  const platform = useWorkbenchPlatform();
  const [localOffer, setLocalOffer] = useState<LocalFallbackOffer | null>(null);
  const vehicleSource = sourceAccess.get("xiaomi-cn-vehicles");
  const sourceCatalogKey = `${vehicleSource?.management.access_generation}:${vehicleSource?.registered_status}:${vehicleSource?.environment_disabled}:${vehicleSource?.parser_deployment?.state}`;
  const [mode, setMode] = useState<"source" | "relations">("source");
  const [relationTarget, setRelationTarget] = useState<FitmentRelationTarget | null>(null);
  const [relationRefresh, setRelationRefresh] = useState(0);
  const [catalog, setCatalog] = useState<VehicleCandidate[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [catalogAttempt, setCatalogAttempt] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [result, setResult] = useState<VehicleFitmentResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [consentPending, setConsentPending] = useState(false);
  const [denied, setDenied] = useState(false);
  const [trimId, setTrimId] = useState("");
  const [optionId, setOptionId] = useState("");
  const generation = useRef(0);
  const active = useRef<QueryContext | null>(null);

  useEffect(() => {
    if (!sessionReady) return;
    const controller = new AbortController();
    setCatalogLoading(true); setCatalogError("");
    tireApi.vehicles(controller.signal).then(response => {
      if (controller.signal.aborted) return;
      setCatalog(response.vehicles);
      setSelectedId(previous => response.vehicles.some(vehicle => vehicle.id === previous) ? previous : (response.vehicles.find(canQuery) || response.vehicles[0])?.id || "");
    }).catch(error => { if (!controller.signal.aborted) setCatalogError(detail(error)); })
      .finally(() => { if (!controller.signal.aborted) setCatalogLoading(false); });
    return () => controller.abort();
  }, [sessionReady, catalogAttempt, sourceCatalogKey]);

  useEffect(() => () => { active.current?.controller.abort(); generation.current++; }, []);
  useEffect(() => { if (!sessionReady) clearQuery(); }, [sessionReady]);
  useEffect(() => { const ownerChanged = () => clearQuery(); window.addEventListener("tire-offline-owner-changed", ownerChanged); return () => window.removeEventListener("tire-offline-owner-changed", ownerChanged); }, []);

  useEffect(() => {
    const context = active.current;
    if (context && context.accessGeneration >= 0 && context.accessGeneration !== sourceAccess.get(context.sourceId)?.management.access_generation) {
      context.controller.abort(); active.current = null; generation.current++; setLoading(false); setConsentPending(false);
      setLocalOffer(null);
      setResult(previous => previous?.data_state === "consent_required" ? null : previous);
      setError("来源状态已变化，旧在线请求及待答授权已失效；已完成证据仍可读取。");
    }
  }, [sourceAccess.items]);

  const selected = catalog.find(vehicle => vehicle.id === selectedId);
  const readyResult = result && !denied && ["live", "live_verified_304", "local_snapshot"].includes(result.data_state) ? result : null;
  const available = (readyResult?.fitments || []).filter(availableFitment);
  const trims = (readyResult?.trims || []).filter(trim => available.some(fitment => fitment.trim_id === trim.id));
  const options = available.filter(fitment => fitment.trim_id === trimId);
  const fitment = options.find(option => option.id === optionId);
  const current = (context: QueryContext) => active.current === context && generation.current === context.generation && !context.controller.signal.aborted;

  function clearQuery() {
    active.current?.controller.abort(); active.current = null; generation.current++;
    setLocalOffer(null);
    setResult(null); setLoading(false); setError(""); setConsentPending(false); setDenied(false); setTrimId(""); setOptionId("");
    onClearEvidence();
  }

  function acceptResult(response: VehicleFitmentResult) {
    setResult(response);
    const firstOption = response.fitments.find(availableFitment);
    setTrimId(firstOption?.trim_id || ""); setOptionId(firstOption?.id || "");
  }

  async function query() {
    if (!selected || !canQuery(selected) || !sessionReady || loading) return;
    const priorGeneration = sourceAccess.get(selected.source_id)?.management.access_generation ?? -1;
    clearQuery();
    const context: QueryContext = { vehicleId: selected.id, sourceId: selected.source_id, accessGeneration: -1, generation: generation.current, controller: new AbortController(), deciding: false, attemptId: crypto.randomUUID() };
    active.current = context; setLoading(true);
    const offerFailure = async (cause: unknown) => { const offer = await createDeviceOffer(platform.offline, "vehicle_fitments", { vehicle_id: context.vehicleId }, [], context.sourceId, context.accessGeneration, cause, context.attemptId, vehicleName(selected)); if (current(context)) setLocalOffer(offer); };
    try {
      let metadataFailure: unknown;
      const metadata = await sourceAccess.refresh(cause => { metadataFailure = cause; });
      if (!current(context)) return;
      if (!metadata || !sourceAccess.canQuery(context.sourceId)) {
        setError("此来源当前不能在线采集，请核对来源管理；历史证据仍可读取。");
        context.accessGeneration = priorGeneration;
        if (metadataFailure) await offerFailure(metadataFailure);
        return;
      }
      context.accessGeneration = sourceAccess.get(context.sourceId)!.management.access_generation;
      const response = await tireApi.liveFitments(context.vehicleId, context.controller.signal);
      if (current(context)) { acceptResult(response); await offerFailure(response); }
    }
    catch (error) { if (current(context)) { setError(detail(error)); try { await offerFailure(error); } catch (cause) { if (current(context)) setError(detail(cause)); } } }
    finally { if (current(context)) setLoading(false); }
  }

  async function consent(decision: "allow" | "deny") {
    const context = active.current;
    if (!context || !current(context) || context.deciding || !result || result.data_state !== "consent_required" || result.vehicle_id !== context.vehicleId || denied) return;
    context.deciding = true; setConsentPending(true); setError("");
    setLocalOffer(null);
    const queryId = result.query_id;
    try {
      if (!await sourceAccess.ensure(context.sourceId, "management") || !current(context) || context.accessGeneration !== sourceAccess.get(context.sourceId)?.management.access_generation) { setError("来源许可待核对或已变化，未使用旧授权。"); return; }
      const approval = await tireApi.consent(queryId, decision, context.controller.signal);
      if (!current(context)) return;
      if (decision === "deny") { setDenied(true); return; }
      const response = await tireApi.liveFitments(context.vehicleId, context.controller.signal, approval.id);
      if (current(context)) acceptResult(response);
    } catch (error) { if (current(context)) setError(detail(error)); }
    finally { if (current(context)) { context.deciding = false; setConsentPending(false); } }
  }

  function chooseTrim(id: string) { setTrimId(id); setOptionId(available.find(option => option.trim_id === id)?.id || ""); }
  function createRelation(axle: "front" | "rear") {
    const snapshotId = readyResult?.provenance[0]?.snapshot_id;
    if (!readyResult || !fitment || !snapshotId) return;
    setRelationTarget({ selection: { vehicle_id: readyResult.vehicle_id, vehicle_snapshot_id: snapshotId, trim_id: fitment.trim_id, wheel_option_id: fitment.id, axle, variant_id: "", tire_snapshot_id: "", fact_version_id: "" } });
  }
  const relationEvidence = (id: string, kind: "vehicle" | "tire") => kind === "vehicle" ? onEvidence(id) : onTireEvidence(id);

  return <div className="vehicle-workspace">
    <nav className="relation-modes" aria-label="车型资料视图"><button type="button" aria-pressed={mode === "source"} onClick={() => setMode("source")}>来源配置</button><button type="button" aria-pressed={mode === "relations"} onClick={() => setMode("relations")}>已保存 SKU 证据关系（本地历史）</button></nav>
    {mode === "relations" ? <FitmentRelations sessionReady={sessionReady} refresh={relationRefresh} onCreate={selection => setRelationTarget({ selection })} onOpen={relationId => setRelationTarget({ relationId })} onEvidence={relationEvidence} /> : <>
    <section className="vehicle-query-panel">
      <div className="panel-title"><span><Icon name="vehicle" size={19} />核验官方车型配置</span><span className="tag quiet">代际分别记录</span></div>
      {catalogLoading ? <div className="run-loading"><span className="spinner" />正在加载车型目录…</div> : catalogError ? <div className="inline-error" role="alert">{catalogError}<button className="text-button" onClick={() => setCatalogAttempt(value => value + 1)}>重新加载</button></div> : catalog.length ? <>
        {selected ? <><SourceStatus sourceId={selected.source_id} /><SourceOnlineNotice sourceId={selected.source_id} /></> : null}<div className="vehicle-query-controls"><label><span>车型 / 代际</span><select value={selectedId} onChange={event => { clearQuery(); setSelectedId(event.target.value); }}>{catalog.map(vehicle => <option key={vehicle.id} value={vehicle.id}>{vehicleName(vehicle)}{canQuery(vehicle) ? "" : " · 待核验"}</option>)}</select></label><button className="primary-button" disabled={!selected || !canQuery(selected) || !sourceAccess.canQuery(selected.source_id) || !sessionReady || loading} onClick={() => void query()}>{loading ? "在线核验中…" : "在线核验配置"}<Icon name="arrow" size={17} /></button></div>
        {selected ? <div className="vehicle-catalog-description"><div><strong>{vehicleName(selected)}</strong><span className={`tag ${canQuery(selected) ? "quiet" : "warning"}`}>{canQuery(selected) ? "来源已接入" : "来源待核验"}</span></div><p>{selected.description}</p><p>地区：{selected.region} · 年款：{selected.model_year ?? "来源未独立声明"}</p>{!canQuery(selected) ? <p className="vehicle-generation-warning">该代际目前没有已核验配置，不使用其他代际的尺寸填充。</p> : null}</div> : null}
      </> : <p className="padded muted">暂未登记车型来源。</p>}
    </section>
    <QueryFallbackPolicy kind="vehicle_fitments" sourceIds={["xiaomi-cn-vehicles"]} sessionReady={sessionReady} />
    {localOffer && platform.offline ? <LocalFallbackPanel key={localOffer.intent.attempt_id} offer={localOffer} storage={platform.offline} onClose={() => setLocalOffer(null)} /> : null}

    {error ? <div className="inline-error" role="alert">{error}</div> : null}
    {result?.data_state === "consent_required" && !denied ? <section className="consent-card vehicle-consent"><div className="consent-symbol"><Icon name="shield" size={22} /></div><div><h4>在线核验未完成，是否查看该车型的历史配置？</h4>{renderReason(result.reason)}<p>仅授权「{selected ? vehicleName(selected) : result.vehicle_id}」本次查询。切换车型或重新查询需要重新授权。</p><div className="consent-actions"><button className="primary-button compact" disabled={consentPending} onClick={() => void consent("allow")}>{consentPending ? "处理中…" : "仅本次允许"}</button><button className="secondary-button compact" disabled={consentPending} onClick={() => void consent("deny")}>拒绝，保持无结果</button></div></div></section> : null}
    {denied ? <p className="result-explanation">已拒绝本次回退，没有读取车型历史配置。可重新发起在线核验。</p> : null}
    {result?.data_state === "source_unavailable" ? <div className="result-explanation">{renderReason(result.reason)}</div> : null}

    {readyResult ? <section className="vehicle-fitment-panel">
      <div className="panel-title"><span>官方轮毂与前后轴配置</span><span className={`tag ${readyResult.data_state === "local_snapshot" ? "warning" : "success"}`}>{readyResult.data_state === "local_snapshot" ? "LOCAL SNAPSHOT" : "实时核验"}</span></div>
      {readyResult.data_state === "local_snapshot" ? <div className="snapshot-banner"><strong>历史车型配置 · 非实时数据</strong><span>原观察时间：{stamp(readyResult.snapshot_observed_at)}</span><span className="mono">consent_id: {readyResult.consent_id || "未提供"}</span></div> : <div className="verification-line">在线核验时间：{stamp(readyResult.verified_at)}</div>}
      {readyResult.vehicle ? <div className="vehicle-record-title"><h2>{readyResult.vehicle.manufacturer.name} {readyResult.vehicle.model} · {readyResult.vehicle.generation}</h2><p>年款：{readyResult.vehicle.model_year ?? "来源未独立声明"} · 配置版本 {readyResult.fact_version ?? "未记录"}</p></div> : null}
      {available.length ? <>
        <div className="vehicle-filters"><label><span>车辆版本</span><select value={trimId} onChange={event => chooseTrim(event.target.value)}>{trims.map(trim => <option key={trim.id} value={trim.id}>{trim.name}</option>)}</select></label><label><span>官方可用轮毂配置</span><select value={optionId} onChange={event => setOptionId(event.target.value)}>{options.map(option => <option key={option.id} value={option.id}>{option.wheel_option_name} · {option.availability === "standard" ? "标配" : "选配"}</option>)}</select></label></div>
        {fitment ? <article className="fitment-card"><div className="fitment-heading"><div><h3>{fitment.wheel_option_name}</h3><p>{fitment.trim_name} · {fitment.wheel_diameter_inches} 英寸轮毂</p></div><span className="tag quiet">{fitment.availability === "standard" ? "官方标配" : "官方选配"} · {fitment.staggered ? "前后异宽" : "前后同尺寸"}</span></div><div className="axle-pair"><AxleCard axle={fitment.front} position="前轴" onRelation={readyResult.provenance.length ? () => createRelation("front") : undefined} onQuery={() => onQuerySize(fitment.front.size, `${readyResult.vehicle?.model || "车型"} ${readyResult.vehicle?.generation || ""} · ${fitment.trim_name} · 前轴`)} /><AxleCard axle={fitment.rear} position="后轴" onRelation={readyResult.provenance.length ? () => createRelation("rear") : undefined} onQuery={() => onQuerySize(fitment.rear.size, `${readyResult.vehicle?.model || "车型"} ${readyResult.vehicle?.generation || ""} · ${fitment.trim_name} · 后轴`)} /></div><div className="fitment-source-description"><strong>官方轮胎描述</strong><p>{fitment.source_tire_description || "来源未标明具体轮胎名称"}</p>{fitment.constraints.length ? <ul>{fitment.constraints.map((constraint, index) => <li key={index}>{constraint}</li>)}</ul> : null}</div><div className="fitment-boundary"><Icon name="shield" size={19} /><p>{readyResult.coverage?.notice || "车型配置仅证明尺寸与轴位的适配关系，不证明具体轮胎 SKU、产品代码或 OE 身份。"} 按尺寸查找后，仍须独立核对地区、载重、速度与 OE 标记。</p></div><div className="fitment-evidence-actions">{readyResult.provenance[0] ? <button className="secondary-button" onClick={() => onSaveToGarage(readyResult.provenance[0].snapshot_id, fitment.id, `${readyResult.vehicle?.model || "我的车"} ${fitment.trim_name}`)}>将此配置存入车库</button> : null}{readyResult.provenance.map(item => <button key={item.snapshot_id} className="evidence-link" onClick={() => onEvidence(item.snapshot_id)}><Icon name="file" size={16} />查看车型原始证据<Icon name="chevron" size={13} /></button>)}</div><details className="fitment-source-text"><summary>官方配置原文</summary><pre>{fitment.source_description}</pre><p className="mono">{fitment.evidence_locator}</p></details></article> : null}
        <p className="fitment-availability-note">仅列出来源明确为标配或选配的配置。不可用配置不会进入选择列表。</p>
      </> : <p className="result-explanation">{readyResult.data_state === "local_snapshot" ? "本地没有该车型的可用历史配置。" : "来源未返回明确可用的版本与轮毂配置。"}</p>}
      {readyResult.footnotes.length ? <details className="vehicle-footnotes"><summary>官方配置说明</summary>{readyResult.footnotes.map((note, index) => <p key={index}>{typeof note === "string" ? note : "结构化说明，详见车型原始证据。"}</p>)}</details> : null}
      {readyResult.documents.length ? <div className="vehicle-source-documents">{readyResult.documents.map(document => publicUrl(document.url) ? <a key={document.url} href={publicUrl(document.url)} target="_blank" rel="noopener noreferrer">{document.title || "官方配置文件"}<Icon name="external" size={14} /></a> : null)}</div> : null}
    </section> : !result && !loading ? <div className="vehicle-empty"><Icon name="vehicle" size={32} /><h3>先确认车辆，再确认轮胎</h3><p>选择准确代际并在线核验后，分别查看车辆版本、轮毂与前后轴尺寸。目录中的车型名称本身不代表已获取配置。</p></div> : null}
    </>}
    {relationTarget ? <FitmentRelationDialog key={"relationId" in relationTarget ? relationTarget.relationId : `${relationTarget.selection.vehicle_snapshot_id}:${relationTarget.selection.trim_id}:${relationTarget.selection.wheel_option_id}:${relationTarget.selection.axle}`} target={relationTarget} onClose={() => setRelationTarget(null)} onSaved={() => setRelationRefresh(value => value + 1)} onEvidence={relationEvidence} /> : null}
  </div>;
}

function AxleCard({ axle, position, onQuery, onRelation }: { axle: AxleSpecification; position: string; onQuery: () => void; onRelation?: () => void }) {
  return <section className="axle-card"><span className="axle-label">{position}</span><strong className="axle-size">{axle.size}</strong><dl><div><dt>载重 / 速度</dt><dd>{axle.load_index || "未标明"} / {axle.speed_rating || "未标明"}</dd></div><div><dt>OE 标记</dt><dd>{axle.oe_mark || "来源未标明"}</dd></div><div><dt>产品代码</dt><dd>{axle.manufacturer_product_code || "来源未标明"}</dd></div></dl><button className="secondary-button" onClick={onQuery}>按{position}尺寸查轮胎<Icon name="arrow" size={15} /></button>{onRelation ? <button type="button" className="text-button relation-axle-entry" onClick={onRelation}>建立{position} SKU 证据关系</button> : null}</section>;
}
