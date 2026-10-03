"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { GarageDetail, GarageProfile, GarageRecord, LifecycleReview, Variant } from "@tire/domain-types";
import { IdentityContractBadge } from "./identity-contract";
import { Icon } from "./icons";
import { DrivingPreferences } from "./research";

const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "操作未完成，请重试。";
const stamp = (value: string) => new Date(value).toLocaleString("zh-CN");
const operations: Record<string, string> = { create: "手工创建", from_fitment: "从配置复制", update: "编辑车辆", set_tire: "更新当前轮胎", archive: "移入归档", restore: "恢复记录" };
const emptyProfile = (): GarageProfile => ({ nickname: "", manufacturer: "", model: "", model_year: null, generation: null, trim: null, wheel_option: null, optional_wheels: [], front: { size: null, current_variant_id: null }, rear: { size: null, current_variant_id: null } });

function GarageDialog({ title, busy = false, onClose, children }: { title: string; busy?: boolean; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { node?.close(); if (focus?.isConnected) focus.focus({ preventScroll: true }); };
  }, []);
  return <dialog ref={dialog} className="fact-review-dialog" aria-label={title} onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="fact-review-heading"><div><span className="eyebrow">MY GARAGE</span><h2>{title}</h2></div><button type="button" className="icon-button" disabled={busy} aria-label="关闭车库窗口" onClick={onClose}><Icon name="close" size={20} /></button></div>
    <div className="fact-review-content">{children}</div>
  </dialog>;
}

function GarageEditor({ record, onClose, onSaved }: { record: GarageRecord | null; onClose: () => void; onSaved: () => void }) {
  const [base, setBase] = useState(record);
  const [profile, setProfile] = useState<GarageProfile>(() => record ? structuredClone(record.profile) : emptyProfile());
  const [wheels, setWheels] = useState(record?.profile.optional_wheels.join("\n") || "");
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  function setField<K extends keyof GarageProfile>(key: K, value: GarageProfile[K]) { setProfile(previous => ({ ...previous, [key]: value })); }
  async function save() {
    if (busy || stale) return;
    const request = new AbortController(); controller.current = request; setBusy(true); setError("");
    const value = { ...profile, optional_wheels: wheels.split("\n").map(item => item.trim()).filter(Boolean) };
    try {
      if (base) await tireApi.updateGarage(base.id, base.revision, value, request.signal);
      else await tireApi.createGarage(value, request.signal);
      if (!request.signal.aborted) onSaved();
    } catch (cause) { if (!request.signal.aborted) { setError(errorText(cause)); if (cause instanceof ApiError && cause.status === 409) setStale(true); } }
    finally { if (!request.signal.aborted) setBusy(false); }
  }
  async function reload() {
    if (!base || busy) return;
    const request = new AbortController(); controller.current = request; setBusy(true);
    try {
      const value = await tireApi.garageDetail(base.id, request.signal);
      if (request.signal.aborted) return;
      setBase(value); setProfile(structuredClone(value.profile)); setWheels(value.profile.optional_wheels.join("\n"));
      setError(value.archived ? "此记录已归档，请先在归档列表恢复。" : ""); setStale(value.archived);
    } catch (cause) { if (!request.signal.aborted) setError(errorText(cause)); }
    finally { if (!request.signal.aborted) setBusy(false); }
  }
  const textFields = [["nickname", "车辆昵称"], ["manufacturer", "车辆品牌"], ["model", "车型"], ["generation", "代际（可留空）"], ["trim", "配置版本（可留空）"], ["wheel_option", "当前轮毂（可留空）"]] as const;
  return <GarageDialog title={base ? "编辑车库车辆" : "添加车库车辆"} busy={busy} onClose={onClose}>
    <p className="review-boundary">保存你确认的车辆信息。未知年款或配置可留空；记录属于当前本地工作区，不作为官方适配证明。无需填写 VIN 或车牌。</p>
    {base?.fitment_reference ? <p className="review-warning">编辑后的内容标记为用户记录，原参考配置仍保留。</p> : null}
    {error ? <div className="inline-error" role="alert">{error}{base && stale ? <button type="button" className="text-button" disabled={busy} onClick={() => void reload()}>重新载入并核对</button> : null}</div> : null}
    <form className="review-form" onSubmit={event => { event.preventDefault(); void save(); }}>
      <div className="garage-form-grid">{textFields.map(([key, label]) => <label key={key}><span>{label}</span><input value={profile[key] || ""} required={["nickname", "manufacturer", "model"].includes(key)} maxLength={key === "wheel_option" ? 160 : key === "nickname" || key === "manufacturer" ? 80 : key === "generation" ? 100 : 120} disabled={busy} onChange={event => setField(key, event.target.value)} /></label>)}
        <label><span>年款（未知可留空）</span><input type="number" min={1900} max={2100} step={1} disabled={busy} value={profile.model_year ?? ""} onChange={event => setField("model_year", event.target.value ? Number(event.target.value) : null)} /></label>
        {(["front", "rear"] as const).map(axle => <label key={axle}><span>{axle === "front" ? "前" : "后"}轴轮胎尺寸</span><input placeholder="例如 245/40R20" maxLength={24} value={profile[axle].size || ""} disabled={busy} onChange={event => setField(axle, { ...profile[axle], size: event.target.value || null })} />{profile[axle].current_variant_id ? <><small>此轴已关联精确轮胎，尺寸须与其一致。</small><button type="button" className="text-button" disabled={busy} onClick={() => setField(axle, { ...profile[axle], current_variant_id: null })}>取消此轴的当前轮胎记录</button></> : null}</label>)}
      </div>
      <label><span>可选轮毂（每行一项，可留空）</span><textarea maxLength={3220} value={wheels} disabled={busy} onChange={event => setWheels(event.target.value)} /></label>
      <button type="submit" className="primary-button" disabled={busy || stale}>{busy ? "正在保存…" : "保存车辆记录"}</button>
    </form>
  </GarageDialog>;
}

function GarageHistory({ id, onClose }: { id: string; onClose: () => void }) {
  const [data, setData] = useState<GarageDetail | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError("");
    void tireApi.garageDetail(id, controller.signal).then(result => { if (!controller.signal.aborted) setData(result); })
      .catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [id, attempt]);
  return <GarageDialog title="车库记录历史" onClose={onClose}>
    {error ? <div className="inline-error" role="alert">{error}<button className="text-button" onClick={() => setAttempt(value => value + 1)}>重试</button></div> : !data ? <p role="status">正在读取历史…</p> : <section className="review-history"><p>LOCAL SNAPSHOT · {data.profile.nickname} · {data.history_truncated ? "显示最近 50 条" : `${data.history.length} 条记录`}</p>{data.history.map(row => <details key={row.revision}><summary>#{row.revision} · {operations[row.operation] || row.operation} · {stamp(row.created_at)}</summary><dl><div><dt>车辆</dt><dd>{row.profile.nickname} · {row.profile.manufacturer} {row.profile.model} · {row.profile.model_year || "年款未知"}</dd></div><div><dt>前 / 后轴</dt><dd>{row.profile.front.size || "未知"} / {row.profile.rear.size || "未知"}</dd></div><div><dt>配置 / 轮毂</dt><dd>{row.profile.trim || "未知"} / {row.profile.wheel_option || "未知"}</dd></div><div><dt>记录状态</dt><dd>{row.archived ? "已归档" : "使用中"} · {row.basis === "copied_fitment" ? "从来源配置复制" : "用户记录"}</dd></div></dl></details>)}</section>}
  </GarageDialog>;
}

export default function GarageWorkspace({ sessionReady, onQuerySize, onVehicleEvidence, onVariant, lifecycleReview }: {
  sessionReady: boolean; onQuerySize: (size: string, context: string) => void;
  onVehicleEvidence: (id: string) => void; onVariant: (id: string) => void;
  lifecycleReview: LifecycleReview | null;
}) {
  const [records, setRecords] = useState<GarageRecord[] | null>(null);
  const [total, setTotal] = useState(0);
  const [archived, setArchived] = useState(false);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [editor, setEditor] = useState<GarageRecord | "new" | null>(null);
  const [historyId, setHistoryId] = useState("");
  const mutation = useRef<AbortController | null>(null);
  const pageRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    if (!lifecycleReview) return;
    setRecords(previous => previous?.map(record => {
      const update = (tire: GarageRecord["current_tires"]["front"]) => tire?.id === lifecycleReview.variant_id ? { ...tire, lifecycle: lifecycleReview.lifecycle } : tire;
      return { ...record, current_tires: { front: update(record.current_tires.front), rear: update(record.current_tires.rear) } };
    }) || null);
  }, [lifecycleReview]);
  useEffect(() => () => { mutation.current?.abort(); pageRequest.current?.abort(); }, []);
  useEffect(() => {
    if (!sessionReady) return;
    const controller = new AbortController(); pageRequest.current = controller; setRecords(null); setError("");
    void tireApi.garage(archived, controller.signal).then(result => {
      if (!controller.signal.aborted) { setRecords(result.items); setTotal(result.total); }
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [sessionReady, archived, revision]);
  async function more() {
    if (!records || busy) return;
    const controller = new AbortController(); pageRequest.current = controller; setBusy("page");
    try {
      const result = await tireApi.garage(archived, controller.signal, records.length);
      if (!controller.signal.aborted) { setRecords([...new Map([...records, ...result.items].map(item => [item.id, item])).values()]); setTotal(result.total); }
    } catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setBusy(""); }
  }
  async function change(record: GarageRecord, axle?: "front" | "rear") {
    if (busy) return;
    const controller = new AbortController(); mutation.current = controller; setBusy(record.id); setError("");
    try {
      if (axle) await tireApi.garageTire(record.id, record.revision, axle, null, controller.signal);
      else await tireApi.garageState(record.id, record.revision, record.archived ? "restore" : "archive", controller.signal);
      if (!controller.signal.aborted) setRevision(value => value + 1);
    } catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setBusy(""); }
  }
  return <div className="garage-workspace">
    <div className="snapshot-banner"><strong>本地工作区 · 我的车库</strong><span>记录保存在当前服务，重启后仍保留；不同浏览器访问此本机服务共享车库。车辆与当前轮胎由你确认，不等于官方适配认证。</span></div>
    <section className="vehicle-query-panel"><div className="panel-title"><span><Icon name="vehicle" size={18} />{archived ? "归档车辆" : "我的车辆"}</span><button className="primary-button compact" disabled={!sessionReady || !!busy} onClick={() => setEditor("new")}>添加车辆</button></div>
      <div className="quarantine-filter"><label><span>记录范围</span><select value={archived ? "archived" : "active"} disabled={!!busy} onChange={event => { pageRequest.current?.abort(); setArchived(event.target.value === "archived"); }}><option value="active">使用中的车辆</option><option value="archived">已归档车辆</option></select></label><button className="secondary-button" disabled={!!busy || !sessionReady} onClick={() => setRevision(value => value + 1)}>刷新车库</button></div>
      {error ? <div className="inline-error" role="alert">{error} 请刷新后核对当前记录。</div> : null}
      {!records ? !error ? <p className="quality-empty" role="status">正在读取车库…</p> : null : !records.length ? <div className="vehicle-empty"><Icon name="vehicle" size={30} /><h3>{archived ? "暂无归档车辆" : "把车辆与前后轴规格放在一起"}</h3><p>{archived ? "移入归档的车辆可在这里恢复。" : "可手工添加，也可从车型适配中的已核验配置保存。查询轮胎后，选择「记入车库」记录当前轮胎。"}</p></div> : <>
        <p className="quality-intro">已显示 {records.length} / {total} 辆 · 保存记录不会自动向官网查询。</p>
        {records.map(record => <article className="garage-card" key={record.id}>
          <div className="quality-item-heading"><h3>{record.profile.nickname}</h3><span className="tag quiet">{record.basis === "copied_fitment" ? "配置复制记录" : "用户记录"}</span></div>
          <p>{record.profile.manufacturer} {record.profile.model} · {record.profile.model_year || "年款未知"}{record.profile.generation ? ` · ${record.profile.generation}` : ""}</p>
          <dl className="quality-times"><div><dt>配置版本</dt><dd>{record.profile.trim || "未记录"}</dd></div><div><dt>当前轮毂</dt><dd>{record.profile.wheel_option || "未记录"}</dd></div></dl>
          <div className="garage-axles">{(["front", "rear"] as const).map(axle => {
            const tire = record.current_tires[axle]; const size = record.profile[axle].size;
            return <section className="axle-card" key={axle}><span className="axle-label">{axle === "front" ? "前轴" : "后轴"}</span><strong className="axle-size">{size || "尺寸未记录"}</strong>
              {tire ? <><p>当前轮胎（用户记录）</p><p>{tire.brand} {tire.model}<br /><span className="mono">{tire.manufacturer_product_code || "产品代码未知"}</span> · {tire.region}</p><IdentityContractBadge contract={tire.identity_contract} />{tire.lifecycle?.state === "revoked" ? <p className="review-warning">关联的轮胎版本已撤销，请重新核对。</p> : null}<button className="text-button" onClick={() => onVariant(tire.id)}>核对版本状态与证据</button>{!record.archived ? <button className="text-button" disabled={!!busy} onClick={() => void change(record, axle)}>取消当前轮胎记录</button> : null}</> : <p>尚未关联精确轮胎版本。</p>}
              {size ? <button className="secondary-button" onClick={() => onQuerySize(size, `${record.profile.nickname}${axle === "front" ? "前轴" : "后轴"}`)}>按此尺寸查轮胎</button> : null}
            </section>;
          })}</div>
          {record.profile.optional_wheels.length ? <p className="garage-wheel-options">可选轮毂：{record.profile.optional_wheels.join("、")}</p> : null}
          {record.fitment_reference ? <details className="vehicle-footnotes"><summary>保存时的参考配置 · {stamp(record.fitment_reference.observed_at)}</summary><p>{record.fitment_reference.source_description}</p>{record.fitment_reference.constraints.map((item, index) => <p key={index}>{item}</p>)}<button className="text-button" onClick={() => onVehicleEvidence(record.fitment_reference!.snapshot_id)}>核对车型历史证据</button></details> : null}
          <div className="variant-actions">{!record.archived ? <button className="secondary-button" disabled={!!busy} onClick={() => setEditor(record)}>编辑车辆</button> : null}<button className="text-button" onClick={() => setHistoryId(record.id)}>查看记录历史</button><button className="text-button" disabled={!!busy} onClick={() => void change(record)}>{busy === record.id ? "正在保存…" : record.archived ? "恢复车辆" : "移入归档"}</button></div>
          <p className="garage-stamp">更新于 {stamp(record.updated_at)} · 修订 #{record.revision}</p>
        </article>)}{records.length < total ? <button className="secondary-button" disabled={!!busy} onClick={() => void more()}>加载更多车辆</button> : null}
      </>}
    </section>
    <DrivingPreferences sessionReady={sessionReady} />
    {editor ? <GarageEditor key={editor === "new" ? "new" : editor.id} record={editor === "new" ? null : editor} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); setRevision(value => value + 1); }} /> : null}
    {historyId ? <GarageHistory id={historyId} onClose={() => setHistoryId("")} /> : null}
  </div>;
}

export function AssignTireDialog({ variant, onClose, onSaved }: { variant: Variant; onClose: () => void; onSaved: () => void }) {
  const [cars, setCars] = useState<GarageRecord[] | null>(null);
  const [total, setTotal] = useState(0);
  const [carId, setCarId] = useState("");
  const [axle, setAxle] = useState<"front" | "rear">("front");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [stale, setStale] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController(); request.current = controller; setCars(null); setError(""); setStale(false);
    void tireApi.garage(false, controller.signal).then(result => { if (!controller.signal.aborted) { setCars(result.items); setTotal(result.total); setCarId(result.items[0]?.id || ""); } })
      .catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [attempt]);
  useEffect(() => () => request.current?.abort(), []);
  const car = cars?.find(row => row.id === carId);
  const mismatch = !!car?.profile[axle].size && car.profile[axle].size !== variant.size;
  async function more() {
    if (!cars || busy) return;
    const controller = new AbortController(); request.current = controller; setBusy(true);
    try { const result = await tireApi.garage(false, controller.signal, cars.length); if (!controller.signal.aborted) { setCars([...new Map([...cars, ...result.items].map(item => [item.id, item])).values()]); setTotal(result.total); } }
    catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  async function save() {
    if (!car || busy || stale || mismatch) return;
    const controller = new AbortController(); request.current = controller; setBusy(true); setError("");
    try { await tireApi.garageTire(car.id, car.revision, axle, variant.id, controller.signal); if (!controller.signal.aborted) onSaved(); }
    catch (cause) { if (!controller.signal.aborted) { setError(errorText(cause)); if (cause instanceof ApiError && cause.status === 409) setStale(true); } }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <GarageDialog title="记录当前轮胎" busy={busy} onClose={onClose}>
    <p className="review-boundary">{variant.brand} {variant.model} · {variant.size} · {variant.manufacturer_product_code || "代码未知"} · {variant.region}</p><IdentityContractBadge contract={variant.identity_contract} />
    <p className="review-warning">请按车辆实际安装情况选择。此操作是你的用车记录，不是官方适配认证。轴位尺寸未填写时会一并保存所选轮胎的尺寸。</p>
    {error ? <div className="inline-error" role="alert">{error}<button className="text-button" disabled={busy} onClick={() => setAttempt(value => value + 1)}>重新载入车库</button></div> : null}
    {!cars ? !error ? <p role="status">正在读取车库…</p> : null : !cars.length ? <p>车库还没有车辆，请先到“我的车库”添加车辆，再记录当前轮胎。</p> : <form className="review-form" onSubmit={event => { event.preventDefault(); void save(); }}>
      <label><span>车库车辆</span><select value={carId} disabled={busy} onChange={event => setCarId(event.target.value)}>{cars.map(row => <option value={row.id} key={row.id}>{row.profile.nickname} · {row.profile.manufacturer} {row.profile.model}</option>)}</select></label>
      <label><span>安装轴位</span><select value={axle} disabled={busy} onChange={event => setAxle(event.target.value as "front" | "rear")}><option value="front">前轴</option><option value="rear">后轴</option></select></label>
      <p>已记录尺寸：{car?.profile[axle].size || "未知，将使用所选轮胎尺寸"}</p>
      {mismatch ? <p className="review-warning">尺寸与当前轴位不同，请先核对并编辑车库规格。R / ZR 标记也分别保留。</p> : null}
      <button className="primary-button" type="submit" disabled={busy || stale || mismatch || variant.lifecycle?.state === "revoked"}>{busy ? "正在保存…" : `保存为${axle === "front" ? "前轴" : "后轴"}当前轮胎`}</button>
      {cars.length < total ? <button type="button" className="text-button" disabled={busy} onClick={() => void more()}>加载更多车辆</button> : null}
    </form>}
  </GarageDialog>;
}

export function SaveFitmentDialog({ snapshotId, fitmentId, label, onClose, onSaved }: { snapshotId: string; fitmentId: string; label: string; onClose: () => void; onSaved: () => void }) {
  const [nickname, setNickname] = useState(label.slice(0, 80));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  async function save() {
    if (busy) return;
    const controller = new AbortController(); request.current = controller; setBusy(true); setError("");
    try { await tireApi.garageFromFitment(snapshotId, fitmentId, nickname.trim(), controller.signal); if (!controller.signal.aborted) onSaved(); }
    catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <GarageDialog title="将所选配置存入车库" busy={busy} onClose={onClose}>
    <p className="review-boundary">保存所选车型、配置、轮毂与前后轴尺寸，并保留此时的来源证据。未知年款保持未知，不自动指定当前轮胎或 OE SKU。</p>
    {error ? <p role="alert" className="inline-error">{error}</p> : null}
    <form className="review-form" onSubmit={event => { event.preventDefault(); void save(); }}><label><span>车辆昵称</span><input required maxLength={80} value={nickname} disabled={busy} onChange={event => setNickname(event.target.value)} /></label><button type="submit" className="primary-button" disabled={busy}>{busy ? "正在保存…" : "保存到我的车库"}</button></form>
  </GarageDialog>;
}
