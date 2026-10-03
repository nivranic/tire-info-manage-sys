"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type {
  FitmentOfficialOE, FitmentRelation, FitmentRelationAction, FitmentRelationCheck, FitmentRelationDecision,
  FitmentRelationDetail, FitmentRelationPage, FitmentRelationPreview, FitmentRelationSelection, FitmentRelationState,
  FitmentTireEvidence, FitmentTireEvidencePage, FitmentVehicleEvidence, FitmentVehicleSnapshot, FitmentVehicleSnapshotDetail,
  IdentityCandidates,
} from "@tire/domain-types";
import { IdentityContractBadge, IdentityContractEvidence } from "./identity-contract";
import { DataTree } from "./reparse-review";
import { Icon } from "./icons";

const text = (value: unknown): string => value === null || value === undefined || value === "" ? "未声明 / 未知" : typeof value === "boolean" ? value ? "是" : "否" : typeof value === "object" ? JSON.stringify(value) : String(value);
const stamp = (value?: string) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN") : "未记录";
const errorText = (error: unknown) => error instanceof Error ? error.message : "读取未完成，请重试。";
const axleLabel = (axle: "front" | "rear") => axle === "front" ? "前轴" : "后轴";
const stateLabel: Record<FitmentRelationState, string> = { pending_review: "人工候选 · 待复核", reviewed: "人工已复核", revoked: "已撤销", needs_review: "证据变化 · 需重新复核" };
const actionLabel: Record<FitmentRelationAction, string> = { create: "保存人工候选", revise: "追加关系修订", review: "确认人工复核", revoke: "撤销关系", restore: "恢复为待复核候选" };
const fieldLabels: Record<string, string> = { size: "尺寸（含 R / ZR）", load_index: "载重指数", speed_rating: "速度级别", manufacturer_product_code: "厂商产品代码", product_code_type: "产品代码命名空间", oe_mark: "OE 标记", region: "市场 / 地区", xl: "XL", hl: "HL", acoustic_technology: "静音技术", run_flat: "防爆" };
const staleLabels: Record<string, string> = { vehicle_facts_or_scope_changed: "车型事实或配置范围变化", tire_identity_changed: "轮胎身份内容变化", tire_identity_status_changed: "轮胎身份状态变化", tire_identity_contract_changed: "轮胎权威身份合同变化", tire_facts_changed: "轮胎来源事实变化", tire_catalogs_changed: "轮胎来源目录成员变化", tire_lifecycle_changed: "轮胎撤销 / 恢复状态变化", tire_identity_resolution_changed: "轮胎身份更正或合并决定变化" };
const blankSelection: FitmentRelationSelection = { vehicle_id: "", vehicle_snapshot_id: "", trim_id: "", wheel_option_id: "", axle: "front", variant_id: "", tire_snapshot_id: "", fact_version_id: "" };
const sameSelection = (a: FitmentRelationSelection, b: FitmentRelationSelection) => (Object.keys(blankSelection) as (keyof FitmentRelationSelection)[]).every(key => a[key] === b[key]);
type EvidenceHandler = (id: string, kind: "vehicle" | "tire") => void;
export type FitmentRelationTarget = { relationId: string } | { selection: FitmentRelationSelection };
type Attempt = { key: string; payload: FitmentRelationDecision };
const attempts = new Map<string, Attempt>();
const attemptScope = (target: FitmentRelationTarget) => "relationId" in target ? target.relationId : [target.selection.vehicle_id, target.selection.trim_id, target.selection.wheel_option_id, target.selection.axle].join("|");

function Pages({ total, offset, limit = 20, disabled = false, onPage, label }: { total: number; offset: number; limit?: number; disabled?: boolean; onPage: (offset: number) => void; label: string }) {
  return <div className="reparse-pages"><button type="button" className="text-button" disabled={disabled || offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}>上一页{label}</button><span>共 {total} 条 · 第 {Math.floor(offset / limit) + 1} 页</span><button type="button" className="text-button" disabled={disabled || offset + limit >= total} onClick={() => onPage(offset + limit)}>下一页{label}</button></div>;
}

export default function FitmentRelations({ sessionReady, refresh, onCreate, onOpen, onEvidence }: {
  sessionReady: boolean; refresh: number; onCreate: (selection: FitmentRelationSelection) => void; onOpen: (id: string) => void; onEvidence: EvidenceHandler;
}) {
  const [snapshots, setSnapshots] = useState<FitmentRelationPage<FitmentVehicleSnapshot> | null>(null);
  const [snapshotOffset, setSnapshotOffset] = useState(0);
  const [snapshotId, setSnapshotId] = useState("");
  const [snapshot, setSnapshot] = useState<FitmentVehicleSnapshotDetail | null>(null);
  const [trimId, setTrimId] = useState("");
  const [wheelId, setWheelId] = useState("");
  const [relations, setRelations] = useState<FitmentRelationPage<FitmentRelation> | null>(null);
  const [offset, setOffset] = useState(0);
  const [state, setState] = useState<FitmentRelationState | "">("");
  const [axle, setAxle] = useState<"front" | "rear" | "">("");
  const [reload, setReload] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const setError = (key: string, value = "") => setErrors(previous => ({ ...previous, [key]: value }));

  useEffect(() => {
    if (!sessionReady) return;
    const controller = new AbortController(); setSnapshots(null); setError("snapshots");
    void tireApi.fitmentVehicleSnapshots("", snapshotOffset, controller.signal).then(value => { if (!controller.signal.aborted) setSnapshots(value); }).catch(error => { if (!controller.signal.aborted) setError("snapshots", errorText(error)); });
    return () => controller.abort();
  }, [sessionReady, snapshotOffset, reload, refresh]);
  useEffect(() => {
    if (!sessionReady) return;
    const controller = new AbortController(); setRelations(null); setError("relations");
    void tireApi.fitmentRelations({ ...(state ? { state } : {}), ...(axle ? { axle } : {}) }, offset, controller.signal).then(value => { if (!controller.signal.aborted) setRelations(value); }).catch(error => { if (!controller.signal.aborted) setError("relations", errorText(error)); });
    return () => controller.abort();
  }, [sessionReady, state, axle, offset, reload, refresh]);
  useEffect(() => {
    setSnapshot(null); setError("snapshot");
    if (!snapshotId) return;
    const controller = new AbortController();
    void tireApi.fitmentVehicleSnapshot(snapshotId, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (value.id !== snapshotId) throw new Error("车型快照范围不匹配，请重新选择。");
      setSnapshot(value);
    }).catch(error => { if (!controller.signal.aborted) setError("snapshot", errorText(error)); });
    return () => controller.abort();
  }, [snapshotId, reload, refresh]);

  const wheels = snapshot?.fitments.filter(item => item.trim_id === trimId && item.availability !== "unavailable") || [];
  const wheel = wheels.find(item => item.id === wheelId);
  return <div className="fitment-relations-workspace">
    <div className="snapshot-banner"><strong>LOCAL SNAPSHOT · 车型与精确 SKU 证据关系</strong><span>显式读取本地历史，不会发起官网核验。原观察时间和旧引用会保留，历史内容不代表当前在线参数。</span></div>
    <p className="review-boundary">来源车型配置只说明车辆要求。这里单独保存人工候选与复核关系；人工复核、尺寸相同、OE 标记或车库装胎记录均不能确立官方原配。</p>
    <button type="button" className="secondary-button" onClick={() => setReload(value => value + 1)}>重新读取本地历史</button>
    {Object.entries(errors).filter(([, value]) => value).map(([key, value]) => <p className="inline-error" role="alert" key={key}>{value}</p>)}
    <section className="vehicle-fitment-panel relation-history-builder">
      <div className="panel-title"><span>从已保存的车型快照建立关系</span><span className="tag quiet">不会在线核验</span></div>
      <div className="relation-panel-content review-form">
        <label><span>车型历史快照 · 明确选择代际和观察时间</span><select value={snapshotId} disabled={!snapshots} onChange={event => { setSnapshotId(event.target.value); setSnapshot(null); setTrimId(""); setWheelId(""); }}><option value="">请选择已保存的车型快照</option>{snapshotId && !snapshots?.items.some(item => item.id === snapshotId) && snapshot ? <option value={snapshotId}>{snapshot.vehicle.model} · {snapshot.vehicle.generation} · 已选快照</option> : null}{snapshots?.items.map(item => <option value={item.id} key={item.id}>{item.vehicle.manufacturer.name} {item.vehicle.model} · {item.vehicle.generation} · {text(item.vehicle.model_year)} · {text(item.vehicle.region)} · {stamp(item.provenance.observed_at)}</option>)}</select></label>
        {snapshots ? <Pages total={snapshots.total} offset={snapshotOffset} onPage={setSnapshotOffset} label="快照" /> : !errors.snapshots ? <p role="status">正在读取已保存的车型快照…</p> : null}
        {snapshots && !snapshots.total ? <p className="muted">尚无已采纳车型快照。已有在线结果的轴位卡也可在保存来源证据后进入此流程。</p> : null}
        {snapshot ? <><div className="snapshot-banner"><strong>{snapshot.vehicle.manufacturer.name} {snapshot.vehicle.model} · {snapshot.vehicle.generation}</strong><span>年款：{text(snapshot.vehicle.model_year)} · 市场：{text(snapshot.vehicle.region)} · 原观察时间：{stamp(snapshot.provenance.observed_at)}</span><span>车型事实版本 #{snapshot.fact_version} · LOCAL SNAPSHOT</span></div>
          <div className="relation-form-pair"><label><span>配置版本</span><select value={trimId} onChange={event => { setTrimId(event.target.value); setWheelId(""); }}><option value="">请选择配置版本</option>{snapshot.trims.map(item => <option key={item.id} value={item.id}>{item.name} · 配置年款：{text(item.model_year)}</option>)}</select></label><label><span>轮毂配置</span><select value={wheelId} disabled={!trimId} onChange={event => setWheelId(event.target.value)}><option value="">请选择轮毂配置</option>{wheels.map(item => <option key={item.id} value={item.id}>{item.wheel_option_name} · {item.wheel_diameter_inches} 英寸 · {item.availability === "standard" ? "标配" : "选配"}</option>)}</select></label></div>
          {wheel ? <div className="axle-pair">{(["front", "rear"] as const).map(position => <section className="axle-card" key={position}><span className="axle-label">{axleLabel(position)}</span><strong className="axle-size">{wheel[position].size}</strong><p>载重 / 速度：{text(wheel[position].load_index)} / {text(wheel[position].speed_rating)}</p><p>OE 标记：{text(wheel[position].oe_mark)}</p><button type="button" className="secondary-button" onClick={() => onCreate({ ...blankSelection, vehicle_id: snapshot.vehicle_id, vehicle_snapshot_id: snapshot.id, trim_id: trimId, wheel_option_id: wheel.id, axle: position })}>为{axleLabel(position)}建立 SKU 证据关系</button></section>)}</div> : null}
          <button type="button" className="evidence-link" onClick={() => onEvidence(snapshot.id, "vehicle")}><Icon name="file" size={16} />查看此车型快照原始证据</button>
        </> : snapshotId && !errors.snapshot ? <p role="status">正在读取指定车型快照…</p> : null}
      </div>
    </section>
    <section className="vehicle-fitment-panel">
      <div className="panel-title"><span>已保存 SKU 证据关系</span><span className="tag quiet">独立追加修订</span></div>
      <div className="relation-panel-content"><div className="relation-form-pair review-form"><label><span>人工状态</span><select value={state} onChange={event => { setState(event.target.value as typeof state); setOffset(0); }}><option value="">全部状态</option>{Object.entries(stateLabel).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label><span>轴位</span><select value={axle} onChange={event => { setAxle(event.target.value as typeof axle); setOffset(0); }}><option value="">前后轴分别列出</option><option value="front">前轴</option><option value="rear">后轴</option></select></label></div>
        {relations ? <><div className="relation-list">{relations.items.map(item => <button type="button" className="report-list-item relation-list-item" key={item.id} onClick={() => onOpen(item.id)}><strong>{item.vehicle_evidence.vehicle.model} · {item.vehicle_evidence.vehicle.generation} · {axleLabel(item.axle)}</strong><span>{item.vehicle_evidence.trim.name} · {item.vehicle_evidence.wheel.wheel_option_name} · 年款 {text(item.vehicle_evidence.vehicle.model_year)} · {text(item.vehicle_evidence.vehicle.region)}</span><span>{text(item.tire_evidence.identity.brand)} {text(item.tire_evidence.identity.model)} · {text(item.tire_evidence.identity.size)} · 代码 {text(item.tire_evidence.identity.manufacturer_product_code)}</span><span className={`tag ${item.effective_state === "reviewed" ? "quiet" : "warning"}`}>{stateLabel[item.effective_state]} · #{item.revision}</span><small>官方原配：未确立 · 更新于 {stamp(item.updated_at)}</small></button>)}</div>{!relations.total ? <p className="relation-empty">此范围尚无保存的关系。先选择上方车型快照、配置与轮毂，再为前轴或后轴建立人工候选。</p> : null}<Pages total={relations.total} offset={offset} onPage={setOffset} label="关系" /></> : !errors.relations ? <p role="status">正在读取本地关系…</p> : null}
      </div>
    </section>
  </div>;
}

function OfficialOE({ value }: { value: FitmentOfficialOE }) {
  return <section className="relation-official-boundary"><strong>官方原配身份：未确立</strong><ul>{value.missing_evidence.map((item, index) => <li key={index}>{item}</li>)}</ul><p>保存、人工复核、恢复或勾选确认均不会升级此状态。</p></section>;
}

function EvidencePair({ vehicle, tire, onEvidence, historical = true }: { vehicle: FitmentVehicleEvidence; tire: FitmentTireEvidence; onEvidence: EvidenceHandler; historical?: boolean }) {
  return <div className="relation-evidence-pair">
    <section className="relation-evidence-card"><span className="eyebrow">车辆要求 / {axleLabel(vehicle.axle)}</span><h3>{vehicle.vehicle.manufacturer.name} {vehicle.vehicle.model} · {vehicle.vehicle.generation}</h3><dl className="relation-facts"><div><dt>年款 / 市场</dt><dd>{text(vehicle.vehicle.model_year)} / {text(vehicle.vehicle.region)}</dd></div><div><dt>配置 / 配置年款</dt><dd>{vehicle.trim.name} / {text(vehicle.trim.model_year)}</dd></div><div><dt>轮毂</dt><dd>{vehicle.wheel.wheel_option_name} · {vehicle.wheel.wheel_diameter_inches} 英寸</dd></div><div><dt>固定轴位</dt><dd>{axleLabel(vehicle.axle)} · {vehicle.requirements.size}</dd></div><div><dt>来源轮胎描述</dt><dd>{text(vehicle.wheel.source_tire_description)}</dd></div></dl><EvidenceLocation provenance={vehicle.provenance} pointer={vehicle.structured_locator.json_pointer} version={vehicle.fact_version} /><DataTree label="车型结构定位与来源位置标记" value={{ structured_locator: vehicle.structured_locator, source_locator_marker: vehicle.source_locator_marker, notice: vehicle.source_locator_notice }} /><button type="button" className="evidence-link" onClick={() => onEvidence(vehicle.provenance.snapshot_id, "vehicle")}><Icon name="file" size={16} />查看车型原始证据</button><DataTree label="冻结的车型要求与原文" value={{ vehicle: vehicle.vehicle, trim: vehicle.trim, wheel: vehicle.wheel, requirements: vehicle.requirements }} /></section>
    <section className="relation-evidence-card"><span className="eyebrow">精确 SKU / 轮胎事实</span><h3>{text(tire.identity.brand)} {text(tire.identity.model)}</h3><dl className="relation-facts">{["manufacturer_product_code", "size", "load_index", "speed_rating", "region", "oe_mark", "xl", "hl", "acoustic_technology", "run_flat"].map(field => <div key={field}><dt>{fieldLabels[field]}</dt><dd>{text(tire.identity[field])}</dd></div>)}<div><dt>SKU 记录</dt><dd><code>{tire.variant_id}</code></dd></div></dl><EvidenceLocation provenance={tire.provenance} pointer={tire.structured_locator.json_pointer} version={tire.fact_version} /><DataTree label="轮胎结构定位与来源位置标记" value={{ structured_locator: tire.structured_locator, source_locator_markers: tire.source_locator_markers, notice: tire.source_locator_notice }} /><button type="button" className="evidence-link" onClick={() => onEvidence(tire.provenance.snapshot_id, "tire")}><Icon name="file" size={16} />查看轮胎原始证据</button><p>原轮胎记录身份规则：{tire.identity_contract_version || "记录时未注明"}</p><IdentityContractEvidence contract={tire.identity_contract} historical={historical} /><DataTree label="冻结的精确身份与来源事实" value={{ identity: tire.identity, facts: tire.facts, fact_version_id: tire.fact_version_id }} /></section>
  </div>;
}

function EvidenceLocation({ provenance, pointer, version }: { provenance: FitmentVehicleEvidence["provenance"]; pointer: string; version: number }) {
  return <div className="relation-location"><strong>LOCAL SNAPSHOT · 事实版本 #{version}</strong><p>原观察时间：{stamp(provenance.observed_at)}</p><p>来源：{provenance.source_id}</p><p>来源地址：{provenance.source_url}</p><p>结构位置：<code>{pointer}</code></p><p>快照：<code>{provenance.snapshot_id}</code></p><p>SHA-256：<code>{provenance.raw_hash}</code></p><p>以上为历史记录，不表示当前在线状态。</p></div>;
}

function Checks({ checks }: { checks: FitmentRelationCheck[] }) {
  const labels = { match: "已知值一致", conflict: "已知矛盾 · 阻断", unknown: "未知 · 需确认", not_declared: "车辆来源未声明" };
  return <div className="relation-checks" aria-label="逐项核对车辆要求与精确 SKU"><div className="relation-check-head"><span>核对项</span><span>车型要求</span><span>精确 SKU</span><span>核对结果</span></div>{checks.map(item => <div className={`relation-check-row ${item.status}`} key={item.field}><strong>{fieldLabels[item.field] || item.field}</strong><span><small>车型要求</small>{text(item.vehicle_value)}</span><span><small>精确 SKU</small>{text(item.tire_value)}</span><span>{labels[item.status]}</span></div>)}</div>;
}

export function FitmentRelationDialog({ target, onClose, onSaved, onEvidence }: { target: FitmentRelationTarget; onClose: () => void; onSaved: (relation: FitmentRelationDetail) => void; onEvidence: EvidenceHandler }) {
  const relationId = "relationId" in target ? target.relationId : "";
  const targetScope = attemptScope(target);
  const savedAttempt = attempts.get(targetScope);
  const dialog = useRef<HTMLDialogElement>(null);
  const originFocus = useRef<HTMLElement | null>(null);
  const requestGeneration = useRef(0);
  const previewRequest = useRef<AbortController | null>(null);
  const saveRequest = useRef<AbortController | null>(null);
  const [record, setRecord] = useState<FitmentRelationDetail | null>(null);
  const [currentRelationId, setCurrentRelationId] = useState(relationId);
  const scope = currentRelationId || targetScope;
  const [selection, setSelection] = useState<FitmentRelationSelection>(savedAttempt?.payload.selection || ("selection" in target ? target.selection : blankSelection));
  const [action, setAction] = useState<FitmentRelationAction | null>(savedAttempt?.payload.action || (relationId ? null : "create"));
  const [preview, setPreview] = useState<FitmentRelationPreview | null>(null);
  const [pending, setPending] = useState<Attempt | null>(savedAttempt || null);
  const [busy, setBusy] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [paused, setPaused] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState("");
  const [operator, setOperator] = useState(savedAttempt?.payload.operator || "");
  const [reason, setReason] = useState(savedAttempt?.payload.reason || "");
  const [confirmed, setConfirmed] = useState(false);
  const [unknowns, setUnknowns] = useState(false);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [candidateOffset, setCandidateOffset] = useState(0);
  const [candidates, setCandidates] = useState<IdentityCandidates | null>(null);
  const [selectedIdentity, setSelectedIdentity] = useState<Record<string, unknown> | null>(null);
  const [tireEvidence, setTireEvidence] = useState<FitmentTireEvidencePage | null>(null);
  const [tireOffset, setTireOffset] = useState(0);
  const [vehicleChoices, setVehicleChoices] = useState<FitmentRelationPage<FitmentVehicleSnapshot> | null>(null);
  const [vehicleOffset, setVehicleOffset] = useState(0);
  const [vehicleSnapshot, setVehicleSnapshot] = useState<FitmentVehicleSnapshotDetail | null>(null);
  const locked = busy || !!pending;
  const editing = action === "create" || action === "revise";
  const complete = Object.values(selection).every(Boolean);
  const relationReady = !currentRelationId || (record?.id === currentRelationId && !errors.record);
  const setError = (key: string, value = "") => setErrors(previous => ({ ...previous, [key]: value }));

  function invalidate() { previewRequest.current?.abort(); requestGeneration.current++; setPreview(null); setPreviewLoading(false); setConfirmed(false); setUnknowns(false); setError("preview"); setError("save"); }
  function changeSelection(patch: Partial<FitmentRelationSelection>) { invalidate(); setSelection(previous => ({ ...previous, ...patch })); }
  function chooseAction(next: FitmentRelationAction) {
    if (locked || !record) return;
    invalidate(); setAction(next); setSelection(record.selection); setSelectedIdentity(record.tire_evidence.identity); setTireOffset(0); setReason(""); setNotice("");
  }
  function remember(attempt: Attempt | null) { setPending(attempt); if (attempt) attempts.set(scope, attempt); else attempts.delete(scope); }
  function openEvidence(id: string, kind: "vehicle" | "tire") { setPaused(true); dialog.current?.close(); onEvidence(id, kind); }

  useEffect(() => {
    originFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => { requestGeneration.current++; previewRequest.current?.abort(); saveRequest.current?.abort(); dialog.current?.close(); if (originFocus.current?.isConnected) originFocus.current.focus({ preventScroll: true }); };
  }, []);
  useEffect(() => { if (!paused) dialog.current?.showModal(); else dialog.current?.close(); }, [paused]);
  useEffect(() => {
    if (!currentRelationId) return;
    const controller = new AbortController(); setRecord(null); setError("record");
    void tireApi.fitmentRelation(currentRelationId, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (value.id !== currentRelationId) throw new Error("关系返回范围不匹配。");
      setRecord(value);
      if (!attempts.has(scope)) { setSelection(value.selection); setSelectedIdentity(value.tire_evidence.identity); }
    }).catch(error => { if (!controller.signal.aborted) setError("record", errorText(error)); });
    return () => controller.abort();
  }, [currentRelationId, scope, refresh]);
  useEffect(() => {
    setVehicleSnapshot(null); setError("vehicle");
    if (!selection.vehicle_snapshot_id) return;
    const controller = new AbortController();
    void tireApi.fitmentVehicleSnapshot(selection.vehicle_snapshot_id, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (value.id !== selection.vehicle_snapshot_id || value.vehicle_id !== selection.vehicle_id) throw new Error("车型快照与关系范围不一致。");
      setVehicleSnapshot(value);
    }).catch(error => { if (!controller.signal.aborted) setError("vehicle", errorText(error)); });
    return () => controller.abort();
  }, [selection.vehicle_snapshot_id, selection.vehicle_id, refresh]);
  useEffect(() => {
    if (action !== "revise") return;
    const controller = new AbortController(); setVehicleChoices(null); setError("vehicleChoices");
    void tireApi.fitmentVehicleSnapshots(selection.vehicle_id, vehicleOffset, controller.signal).then(value => { if (!controller.signal.aborted) setVehicleChoices(value); }).catch(error => { if (!controller.signal.aborted) setError("vehicleChoices", errorText(error)); });
    return () => controller.abort();
  }, [action, selection.vehicle_id, vehicleOffset, refresh]);
  useEffect(() => {
    if (!editing) return;
    const controller = new AbortController(); setCandidates(null); setError("candidates");
    void tireApi.identityCandidates(query, candidateOffset, controller.signal).then(value => { if (!controller.signal.aborted) setCandidates(value); }).catch(error => { if (!controller.signal.aborted) setError("candidates", errorText(error)); });
    return () => controller.abort();
  }, [editing, query, candidateOffset, refresh]);
  useEffect(() => {
    setTireEvidence(null); setError("tireEvidence");
    if (!editing || !selection.variant_id) return;
    const controller = new AbortController();
    void tireApi.fitmentTireEvidence(selection.variant_id, tireOffset, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (value.variant_id !== selection.variant_id) throw new Error("轮胎证据与选定 SKU 不一致。");
      setTireEvidence(value); setSelectedIdentity(value.identity);
    }).catch(error => { if (!controller.signal.aborted) setError("tireEvidence", errorText(error)); });
    return () => controller.abort();
  }, [editing, selection.variant_id, tireOffset, refresh]);

  async function prepare() {
    if (!action || !complete || locked || !relationReady) return;
    invalidate(); const generation = requestGeneration.current; const controller = new AbortController(); previewRequest.current = controller; setPreviewLoading(true);
    try {
      const value = await tireApi.fitmentRelationPreview({ mode: "history", action, ...(currentRelationId ? { relation_id: currentRelationId } : {}), selection }, controller.signal);
      if (controller.signal.aborted || generation !== requestGeneration.current) return;
      if (!sameSelection(value.selection, selection)) throw new Error("预览不属于当前选择，请重新核对。");
      setPreview(value);
    } catch (error) { if (!controller.signal.aborted && generation === requestGeneration.current) setError("preview", errorText(error)); }
    finally { if (!controller.signal.aborted && generation === requestGeneration.current) setPreviewLoading(false); }
  }
  async function perform(attempt: Attempt) {
    if (saveRequest.current) return;
    remember(attempt); const controller = new AbortController(); saveRequest.current = controller; setBusy(true); setError("save"); setNotice("");
    try {
      const result = await tireApi.reviseFitmentRelation(attempt.payload, attempt.key, controller.signal);
      if (controller.signal.aborted) return;
      if (result.event.idempotency_key !== attempt.key || result.event.action !== attempt.payload.action || result.event.revision !== attempt.payload.expected_revision + 1 || !sameSelection(result.event.selection, attempt.payload.selection) || result.relation.id !== result.event.relation_id || (attempt.payload.relation_id && result.relation.id !== attempt.payload.relation_id)) throw new Error("保存结果与固定请求不一致，请保留同一 UUID 核对。");
      remember(null); setCurrentRelationId(result.relation.id); setRecord(result.relation); setSelection(result.relation.selection); setSelectedIdentity(result.relation.tire_evidence.identity); invalidate(); setAction(null); setReason("");
      setNotice(`已保存修订 #${result.event.revision}${result.idempotent_replay ? "（同一次请求已核对）" : ""}。${stateLabel[result.relation.effective_state]}；官方原配身份仍未确立。`);
      onSaved(result.relation);
    } catch (error) {
      if (controller.signal.aborted) return;
      setError("save", errorText(error)); setConfirmed(false);
      if (error instanceof ApiError && [404, 409, 422].includes(error.status) && error.code !== "idempotency_payload_mismatch") {
        remember(null); previewRequest.current?.abort(); requestGeneration.current++; setPreview(null); setPreviewLoading(false); setUnknowns(false); setNotice("旧预览已失效。请重新读取关系与证据，并重新预览核对后提交。");
      }
    } finally { if (saveRequest.current === controller) saveRequest.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  const canSave = !!action && !!preview?.can_submit && complete && relationReady && !locked && confirmed && operator.trim().length > 0 && reason.trim().length >= 5 && (action === "revoke" || !preview.unknown_fields.length || unknowns);
  function submit() {
    if (!canSave || !preview || !action) return;
    void perform({ key: crypto.randomUUID(), payload: { mode: "history", action, ...(currentRelationId ? { relation_id: currentRelationId } : {}), selection: { ...selection }, expected_revision: preview.revision, expected_fingerprint: preview.fingerprint, operator: operator.trim(), reason: reason.trim(), acknowledged: true, acknowledge_unknowns: unknowns } });
  }
  const fixedWheel = vehicleSnapshot?.fitments.find(item => item.id === selection.wheel_option_id && item.trim_id === selection.trim_id);
  const fixedTrim = vehicleSnapshot?.trims.find(item => item.id === selection.trim_id);
  const displayedTire = selectedIdentity || record?.tire_evidence.identity;
  const displayedContract = tireEvidence?.variant_id === selection.variant_id ? tireEvidence.identity_contract : candidates?.items.find(item => item.id === selection.variant_id)?.identity_contract || (record?.variant_id === selection.variant_id ? record.tire_evidence.identity_contract : undefined);
  return <>
    {paused ? <div className="relation-resume" role="status"><span>关系核对草稿已保留，可检查原始证据后返回。</span><button type="button" className="primary-button" onClick={() => setPaused(false)}>返回关系核对</button><button type="button" className="text-button" onClick={onClose}>关闭核对</button></div> : null}
    <dialog ref={dialog} className="fact-review-dialog reports-dialog relation-dialog" aria-labelledby="fitment-relation-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
      <header className="fact-review-heading"><div><span className="eyebrow">AXLE × EXACT SKU / LOCAL SNAPSHOT</span><h2 id="fitment-relation-title">{record ? "车型轴位 · SKU 证据关系" : "建立车型轴位 · SKU 证据关系"}</h2></div><button type="button" className="icon-button" aria-label="关闭关系核对" onClick={onClose}>×</button></header>
      <div className="fact-review-content relation-dialog-content">
        <p className="review-boundary">车型要求与轮胎事实分侧保存，只有当前明确选择的轴位和精确 SKU 参与核对。原始来源字段保持原样；不会自动跟随身份更正目标，也不会把车库装胎当作官方适配证据。</p>
        {Object.entries(errors).filter(([, value]) => value).map(([key, value]) => <p className="inline-error" role="alert" key={key}>{value}</p>)}
        {notice ? <p className="review-saved" role="status">{notice}</p> : null}
        {pending ? <section className="review-boundary"><strong>操作结果尚待核对</strong><p>固定 UUID：<code>{pending.key}</code>。网络异常或关闭重开均保留同一请求；整页刷新后请先查看关系历史。</p><DataTree label="此请求的固定内容" value={pending.payload} /><button type="button" className="primary-button" disabled={busy} onClick={() => void perform(pending)}>{busy ? "正在核对…" : "核对同一次关系操作"}</button></section> : null}
        <button type="button" className="secondary-button" disabled={locked} onClick={() => { invalidate(); setRefresh(value => value + 1); setNotice(""); }}>重新读取关系与证据</button>
        {record ? <><div className="snapshot-banner"><strong>{stateLabel[record.effective_state]} · 修订 #{record.revision}</strong><span>记录时间：{stamp(record.updated_at)} · 署名：{record.operator}</span><span>{record.reason}</span></div>{record.needs_review ? <div className="inline-error"><strong>旧引用仍保留，不能自动沿用当前新身份或新事实。</strong><ul>{record.stale_reasons.map(item => <li key={item}>{staleLabels[item] || item}</li>)}</ul></div> : null}
          <OfficialOE value={record.official_oe} />
          {!action ? <><EvidencePair vehicle={record.vehicle_evidence} tire={record.tire_evidence} onEvidence={openEvidence} /><Checks checks={record.checks} /></> : null}
          <div className="relation-action-bar">{record.review_state === "revoked" ? <><button type="button" className="secondary-button" disabled={locked} onClick={() => chooseAction("revise")}>更新证据 / 修订 · 保持撤销</button><button type="button" className="secondary-button" disabled={locked} onClick={() => chooseAction("restore")}>恢复 · 重新核对后进入待复核</button></> : <><button type="button" className="secondary-button" disabled={locked} onClick={() => chooseAction("review")}>复核这条关系</button><button type="button" className="secondary-button" disabled={locked} onClick={() => chooseAction("revise")}>修订 SKU 或证据</button><button type="button" className="text-button" disabled={locked} onClick={() => chooseAction("revoke")}>撤销关系</button></>}</div>
        </> : relationId && !errors.record ? <p role="status">正在读取关系与追加历史…</p> : null}
        {action ? <section className="relation-editor"><h3>{actionLabel[action]}</h3>
          {action === "revise" && record?.review_state === "revoked" ? <p className="review-boundary">本次更新证据仍保持撤销状态。完成修订后，须另行预览并恢复为待复核候选，再进行人工复核。</p> : null}
          {vehicleSnapshot ? <div className="snapshot-banner"><strong>{vehicleSnapshot.vehicle.manufacturer.name} {vehicleSnapshot.vehicle.model} · {vehicleSnapshot.vehicle.generation}</strong><span>年款：{text(vehicleSnapshot.vehicle.model_year)} · 市场：{text(vehicleSnapshot.vehicle.region)}</span><span>{fixedTrim?.name || "配置未匹配"} · 配置年款：{text(fixedTrim?.model_year)} · {fixedWheel?.wheel_option_name || "轮毂未匹配"} · 固定{axleLabel(selection.axle)}</span><span>原观察时间：{stamp(vehicleSnapshot.provenance.observed_at)} · LOCAL SNAPSHOT</span><button type="button" className="evidence-link" onClick={() => openEvidence(vehicleSnapshot.id, "vehicle")}>查看已选车型原文</button></div> : selection.vehicle_snapshot_id && !errors.vehicle ? <p role="status">正在核对固定轴位的车型快照…</p> : null}
          {action === "revise" ? <div className="review-form"><label><span>修订车型证据 · 代际 / 年款 / 市场 / 配置 / 轮毂 / 轴位保持固定</span><select value={selection.vehicle_snapshot_id} disabled={locked || !vehicleChoices} onChange={event => changeSelection({ vehicle_snapshot_id: event.target.value })}>{!vehicleChoices?.items.some(item => item.id === selection.vehicle_snapshot_id) ? <option value={selection.vehicle_snapshot_id}>当前旧引用 · {selection.vehicle_snapshot_id}</option> : null}{vehicleChoices?.items.map(item => <option key={item.id} value={item.id}>{item.vehicle.model} · {item.vehicle.generation} · {text(item.vehicle.model_year)} · {text(item.vehicle.region)} · {stamp(item.provenance.observed_at)}</option>)}</select></label>{vehicleChoices ? <Pages total={vehicleChoices.total} offset={vehicleOffset} onPage={setVehicleOffset} disabled={locked} label="车型证据" /> : null}</div> : null}
          {editing ? <section className="relation-candidates"><h3>明确选择精确 SKU</h3><p className="muted">以下为历史目录候选，不是适配推荐；型号或尺寸相同也不能替代精确身份核对。</p><form className="relation-search review-form" onSubmit={event => { event.preventDefault(); setQuery(search.trim()); setCandidateOffset(0); }}><label><span>搜索品牌、型号或厂商产品代码</span><input value={search} maxLength={120} disabled={locked} onChange={event => setSearch(event.target.value)} /></label><button type="submit" className="secondary-button" disabled={locked}>搜索历史 SKU</button></form>
            {displayedTire && selection.variant_id ? <div className="relation-selection"><strong>当前明确选择</strong><p>{text(displayedTire.brand)} {text(displayedTire.model)} · {text(displayedTire.size)} · {text(displayedTire.region)} · 代码 {text(displayedTire.manufacturer_product_code)}</p><code>{selection.variant_id}</code><IdentityContractBadge contract={displayedContract} /></div> : <p className="muted">尚未选择 SKU，不会默认采用第一条候选。</p>}
            {candidates ? <><div className="relation-candidate-list">{candidates.items.map(item => <button type="button" key={item.id} className={`report-list-item${selection.variant_id === item.id ? " selected" : ""}`} aria-pressed={selection.variant_id === item.id} disabled={locked} onClick={() => { changeSelection({ variant_id: item.id, tire_snapshot_id: "", fact_version_id: "" }); setSelectedIdentity(item.identity); setTireOffset(0); }}><strong>{text(item.identity.brand)} {text(item.identity.model)} · {text(item.identity.manufacturer_product_code)}</strong><span>{text(item.identity.size)} · {text(item.identity.region)} · 载重 / 速度 {text(item.identity.load_index)} / {text(item.identity.speed_rating)}</span><span>OE {text(item.identity.oe_mark)} · XL {text(item.identity.xl)} · HL {text(item.identity.hl)} · 静音 {text(item.identity.acoustic_technology)} · 防爆 {text(item.identity.run_flat)}</span><IdentityContractBadge contract={item.identity_contract} /><small><code>{item.id}</code>{item.identity_resolution?.state === "redirected" || item.identity_resolution?.state === "needs_review" ? " · 存在身份指向，禁止自动跟随" : ""}</small></button>)}</div>{!candidates.total ? <p className="muted">没有匹配的历史 SKU。</p> : null}<Pages total={candidates.total} offset={candidateOffset} limit={candidates.limit} onPage={setCandidateOffset} disabled={locked} label="SKU" /></> : !errors.candidates ? <p role="status">正在读取历史 SKU…</p> : null}
            {selection.variant_id ? <div className="review-form"><label><span>此精确 SKU 的已采纳证据快照 · 必须明确选择</span><select value={selection.tire_snapshot_id && selection.fact_version_id ? `${selection.tire_snapshot_id}|${selection.fact_version_id}` : ""} disabled={locked || !tireEvidence} onChange={event => { const item = tireEvidence?.items.find(value => `${value.snapshot_id}|${value.fact_version_id}` === event.target.value); changeSelection({ tire_snapshot_id: item?.snapshot_id || "", fact_version_id: item?.fact_version_id || "" }); }}><option value="">请选择轮胎证据快照</option>{selection.tire_snapshot_id && !tireEvidence?.items.some(item => item.snapshot_id === selection.tire_snapshot_id && item.fact_version_id === selection.fact_version_id) ? <option value={`${selection.tire_snapshot_id}|${selection.fact_version_id}`}>当前旧引用 · {selection.tire_snapshot_id}</option> : null}{tireEvidence?.items.map(item => <option key={`${item.snapshot_id}|${item.fact_version_id}`} value={`${item.snapshot_id}|${item.fact_version_id}`}>{item.source_id} · 事实版本 #{item.fact_version} · {stamp(item.provenance.observed_at)}</option>)}</select></label>{tireEvidence ? <><Pages total={tireEvidence.total} offset={tireOffset} onPage={setTireOffset} disabled={locked} label="轮胎证据" />{!tireEvidence.total ? <p className="inline-error">此 SKU 尚无可选的已采纳证据，不能建立关系。</p> : null}</> : !errors.tireEvidence ? <p role="status">正在读取此 SKU 的来源证据…</p> : null}{selection.tire_snapshot_id ? <button type="button" className="evidence-link" onClick={() => openEvidence(selection.tire_snapshot_id, "tire")}>查看已选轮胎原文</button> : null}</div> : null}
          </section> : <p className="muted">本次沿用已保存的双侧引用。更换 SKU 或证据须选择“修订 SKU 或证据”。</p>}
          <button type="button" className="primary-button" disabled={locked || !complete || previewLoading || !relationReady} onClick={() => void prepare()}>{previewLoading ? "正在逐项核对…" : "预览双侧证据与本次操作"}</button>
          {preview ? <section className="relation-preview"><h3>冻结证据预览 · 修订 #{preview.revision} → #{preview.revision + 1}</h3><p>以下核对基于指定历史快照。保存时服务器会再次核对当前关系、来源事实、撤销状态和身份决定。</p><EvidencePair vehicle={preview.vehicle_evidence} tire={preview.tire_evidence} onEvidence={openEvidence} historical={false} /><Checks checks={preview.checks} /><OfficialOE value={preview.official_oe} />
            {preview.blockers.length ? <div className="inline-error" role="alert"><strong>本次操作被阻断</strong><ul>{preview.blockers.map(code => <li key={code}>{preview.blocker_messages?.find(item => item.code === code)?.message || (code.startsWith("conflict_") ? `${fieldLabels[code.slice(9)] || code.slice(9)}存在已知矛盾` : code)}</li>)}</ul></div> : null}
            <form className="review-form" onSubmit={event => { event.preventDefault(); submit(); }}><label><span>处理人署名（本地自报）</span><input required maxLength={100} disabled={locked} value={operator} onChange={event => { setOperator(event.target.value); setConfirmed(false); }} /></label><label><span>本次理由 · 至少 5 个字</span><textarea required minLength={5} maxLength={2000} rows={3} disabled={locked} value={reason} onChange={event => { setReason(event.target.value); setConfirmed(false); }} /></label>
              {preview.unknown_fields.length && action !== "revoke" ? <label className="review-checkbox"><input type="checkbox" disabled={locked} checked={unknowns} onChange={event => { setUnknowns(event.target.checked); setConfirmed(false); }} /><span>已逐项核对未知或未声明项：{preview.unknown_fields.map(field => fieldLabels[field] || field).join("、")}。未知不等于不存在，也不代表已满足车辆要求。</span></label> : null}
              <label className="review-checkbox"><input type="checkbox" checked={confirmed} disabled={locked} onChange={event => setConfirmed(event.target.checked)} /><span>确认上述固定车型范围、{axleLabel(selection.axle)}、精确 SKU、双侧证据与本次{actionLabel[action]}；理解这是本地人工记录，官方原配身份仍未确立。</span></label><button type="submit" className="primary-button" disabled={!canSave}>{busy ? "正在保存并核对…" : actionLabel[action]}</button>
            </form>
          </section> : null}
        </section> : null}
        {record ? <details className="report-history relation-history"><summary>追加修订历史（{record.history.length}{record.history_truncated ? "+，最近 100 条" : " 条"}）</summary><p>每次记录保留当时的旧引用与观察时间，历史复核状态不代表当前在线适配。</p>{record.history.map(item => <article key={item.id}><h4>#{item.revision} · {actionLabel[item.action]} · {stateLabel[item.review_state]}</h4><p>{stamp(item.created_at)} · {item.operator}</p><p>{item.reason}</p><EvidencePair vehicle={item.vehicle_evidence} tire={item.tire_evidence} onEvidence={openEvidence} /><OfficialOE value={item.official_oe} /><DataTree label="本次修订前后、冻结状态与审计记录" value={item} /></article>)}</details> : null}
      </div>
    </dialog>
  </>;
}
