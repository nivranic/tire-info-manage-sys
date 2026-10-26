"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type {
  FitmentCandidates, FitmentCandidateSelection, FitmentVehicleSnapshot, FitmentVehicleSnapshotDetail,
  InterestDomain, PersonalFeed, PersonalFeedItem,
} from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import { FrozenEvent, HistoricalEvidence } from "./interest-center";
import { Icon } from "./icons";
import TestCandidateInterpretation from "./test-candidate-interpretation";
import CandidateAiAssistance from "./candidate-ai";
import "./personalized-home.css";

const domains: [InterestDomain, string][] = [["tire", "来源参数"], ["test_event", "测试记录"], ["vehicle", "车型资料"], ["fitment", "适配关系"], ["tire_curation", "人工处理"], ["tire_lifecycle", "SKU 状态"], ["tire_identity", "身份映射"], ["tire_catalog", "来源目录"], ["tire_curation_validity", "人工处理适用性"]];
const dimensions = { dry: "干地", wet: "湿地", quiet: "静音", comfort: "舒适", wear: "耐磨", energy: "能耗", appearance: "外观" };
const stamp = (value: string) => Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN") : "时间未记录";
const text = (value: unknown): string => value === null || value === undefined || value === "" ? "未声明" : typeof value === "object" ? JSON.stringify(value) : String(value);
const hash = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const eventKey = (item: PersonalFeedItem) => `${item.event.domain}:${item.event.id}`;
const sameSelection = (a: FitmentCandidateSelection, b: FitmentCandidateSelection) => (["vehicle_id", "vehicle_snapshot_id", "trim_id", "wheel_option_id", "axle"] as const).every(key => a[key] === b[key]);
function errorText(cause: unknown, fallback: string) {
  if (cause instanceof ApiError) {
    if (cause.code === "personal_feed_cursor_invalid") return "历史续读依据无效，请从头重新读取。";
    if (cause.code?.includes("capacity")) return "本地记录超出单次处理范围，请缩小事件范围后重试。";
    if (cause.status === 409) return "兴趣、偏好或来源依据已变化，旧结果已清空。请重新载入依据后再核对。";
    if (cause.status === 422) return "所选车型快照、配置或轴位无法核验，请重新选择完整范围。";
    return fallback;
  }
  return cause instanceof Error ? cause.message : fallback;
}
function verifyFeed(value: PersonalFeed, domain: InterestDomain | null, limit: number) {
  if (value.schema !== "personal-feed@1" || value.policy_version !== "current-interests-history@1" || value.scope !== "actor"
    || value.data_state !== "local_snapshot" || value.feed_scope !== "current_interests_history" || value.domain !== domain || value.limit !== limit
    || !Number.isSafeInteger(value.active_interest_count) || value.active_interest_count < 0 || !Array.isArray(value.items)
    || !hash(value.binding?.interests_fingerprint) || !hash(value.binding?.candidates_fingerprint)
    || typeof value.has_more !== "boolean" || value.has_more !== (typeof value.next_cursor === "string" && value.next_cursor.length > 0)
    || [value.scanned_count, value.matched_count, value.indeterminate_count].some(count => !Number.isSafeInteger(count) || count < 0)
    || value.items.some(item => !["matched", "indeterminate"].includes(item.state) || !item.event?.id || !hash(item.event.event_hash)
      || !Array.isArray(item.matches) || !item.matches.length || item.matches.some(match => !match.interest_id || !hash(match.interest_fingerprint)
        || !Number.isSafeInteger(match.interest_revision) || match.interest_revision < 1 || !match.match?.criteria
        || !["matched", "indeterminate"].includes(match.match.state)))) throw new Error("历史结果与本次范围或冻结依据不一致，未展示替代内容。");
}
function verifyCandidates(value: FitmentCandidates, selection: FitmentCandidateSelection, vehicleFactHash: string, revision: number, fingerprint: string) {
  if (value.schema !== "fitment-candidates@1" || value.policy_version !== "reviewed-exact-axle@1" || value.scope !== "actor"
    || value.evidence_scope !== "local_workspace" || value.data_state !== "local_snapshot" || !sameSelection(value.selection, selection)
    || value.vehicle_binding?.snapshot_id !== selection.vehicle_snapshot_id || value.vehicle_binding.fact_hash !== vehicleFactHash
    || value.preference?.revision !== revision || value.preference.fingerprint !== fingerprint
    || value.ranking !== "not_computed" || value.performance_score !== null || value.official_oe?.state !== "not_established"
    || !Array.isArray(value.items) || !Array.isArray(value.excluded_relations) || !Array.isArray(value.research_focus)
    || value.items.some(item => !item.variant_id || item.performance_score !== null || item.ranking !== "not_computed" || item.official_oe?.state !== "not_established"
      || !Array.isArray(item.relations) || !item.relations.length || item.relations.some(relation =>
        !(["vehicle_id", "trim_id", "wheel_option_id", "axle"] as const).every(key => relation.selection[key] === selection[key])
        || relation.vehicle_evidence.fact_hash !== vehicleFactHash
        || relation.selection.variant_id !== item.variant_id || !hash(relation.binding_hash)
        || !relation.evidence?.some(ref => ref.kind === "fitment_relation_revision" && ref.record_id === relation.revision_id
          && ref.entity_id === relation.relation_id && ref.revision === relation.revision && ref.fingerprint === relation.binding_hash)))) {
    throw new Error("候选结果与所选轴位、本人偏好或精确关系修订不一致，未显示其他范围的候选。");
  }
}

export default function PersonalizedHome({ sessionReady, onNavigate }: { sessionReady: boolean; onNavigate: (view: "query" | "vehicles" | "garage" | "compare" | "watch") => void }) {
  const auth = useWorkbenchAuth();
  if (!sessionReady || !auth.ready) return <section className="quarantine-panel"><h2>我的研究</h2><p role="status">正在确认当前账户归属，个人信息流、偏好及旧结果暂不显示。</p><button type="button" className="text-button" onClick={() => void auth.refresh()}>重新确认账户</button></section>;
  return <PrivateHome key={auth.ownerEpoch} ownerEpoch={auth.ownerEpoch} onNavigate={onNavigate} />;
}
function PrivateHome({ ownerEpoch, onNavigate }: { ownerEpoch: number; onNavigate: (view: "query" | "vehicles" | "garage" | "compare" | "watch") => void }) {
  return <div className="personalized-home">
    <section className="home-intro"><span className="eyebrow">YOUR RESEARCH, WITH EVIDENCE</span><h2>从关注的问题，回到可核对的依据。</h2><p>回看本地已录历史，分别核对当前兴趣与精确轴位。这里没有自动联网，也不会补发通知。</p><div className="home-shortcuts"><button type="button" onClick={() => onNavigate("watch")}>管理本人兴趣<Icon name="arrow" size={14} /></button><button type="button" onClick={() => onNavigate("garage")}>查看车库与偏好<Icon name="arrow" size={14} /></button><button type="button" onClick={() => onNavigate("query")}>直接查询轮胎<Icon name="arrow" size={14} /></button></div></section>
    <FeedPanel ownerEpoch={ownerEpoch} onInterests={() => onNavigate("watch")} />
    <CandidatePanel ownerEpoch={ownerEpoch} onPreferences={() => onNavigate("garage")} onFitments={() => onNavigate("vehicles")} />
  </div>;
}

function FeedDetails({ item }: { item: PersonalFeedItem }) {
  const [selected, setSelected] = useState(0);
  const match = item.matches[selected];
  return <section className="home-frozen"><label><span>逐条核对当前兴趣的原修订与理由</span><select value={selected} onChange={event => setSelected(Number(event.target.value))}>{item.matches.map((row, index) => <option key={row.interest_id} value={index}>{row.interest_name} · 修订 #{row.interest_revision} · {row.match.state === "matched" ? "命中" : "待核对"}</option>)}</select></label><p className="hash-value">兴趣指纹 {match.interest_fingerprint}</p><FrozenEvent key={`${match.interest_id}:${match.interest_revision}`} item={{ event: item.event, match: match.match }} /></section>;
}
function FeedPanel({ ownerEpoch, onInterests }: { ownerEpoch: number; onInterests: () => void }) {
  const auth = useWorkbenchAuth();
  const [domain, setDomain] = useState<InterestDomain | null>(null);
  const [limit, setLimit] = useState(20);
  const [attempt, setAttempt] = useState(0);
  const [page, setPage] = useState<PersonalFeed | null>(null);
  const [items, setItems] = useState<PersonalFeedItem[]>([]);
  const [scanned, setScanned] = useState(0);
  const [filter, setFilter] = useState<"all" | "matched" | "indeterminate">("all");
  const [opened, setOpened] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const pageRef = useRef<PersonalFeed | null>(null);
  const itemsRef = useRef<PersonalFeedItem[]>([]);
  const reset = useCallback(() => {
    request.current?.abort(); generation.current++; pageRef.current = null; itemsRef.current = [];
    setPage(null); setItems([]); setScanned(0); setOpened(""); setError(""); setBusy(false);
  }, []);
  const load = useCallback(async (cursor: string | null) => {
    if (!auth.isCurrentOwner(ownerEpoch)) return;
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    const epoch = ++generation.current;
    const current = () => !controller.signal.aborted && request.current === controller && generation.current === epoch && auth.isCurrentOwner(ownerEpoch);
    setBusy(true); setError("");
    try {
      const value = await tireApi.previewPersonalFeed({ domain, limit, cursor }, controller.signal);
      if (!current()) return;
      verifyFeed(value, domain, limit);
      const old = pageRef.current;
      if (cursor && (!old || old.binding.interests_fingerprint !== value.binding.interests_fingerprint || old.binding.candidates_fingerprint !== value.binding.candidates_fingerprint)) throw new Error("历史续页的兴趣或记录集合已变化，请从头重新读取。");
      const merged = new Map((cursor ? itemsRef.current : []).map(item => [eventKey(item), item]));
      for (const item of value.items) {
        if (merged.has(eventKey(item)) && merged.get(eventKey(item))!.event.event_hash !== item.event.event_hash) throw new Error("同一历史记录的指纹已变化，未拼接不同版本。");
        merged.set(eventKey(item), item);
      }
      if (!current()) return;
      const rows = [...merged.values()]; pageRef.current = value; itemsRef.current = rows;
      setPage(value); setItems(rows); setScanned(previous => (cursor ? previous : 0) + value.scanned_count);
    } catch (cause) {
      if (!current()) return;
      if (!(cause instanceof ApiError) || cause.status === 400 || cause.status === 409) {
        pageRef.current = null; itemsRef.current = []; setPage(null); setItems([]); setOpened(""); setScanned(0);
      }
      setError(errorText(cause, "本次历史读取未完成，请重试；没有用示例记录替代。"));
    } finally { if (current()) setBusy(false); }
  }, [domain, limit, ownerEpoch, auth.isCurrentOwner]);
  useEffect(() => { reset(); void load(null); return () => { request.current?.abort(); generation.current++; }; }, [reset, load, attempt]);
  const visible = items.filter(item => filter === "all" || item.state === filter);
  return <section className="home-section" aria-labelledby="personal-feed-title">
    <div className="home-section-heading"><div><span className="eyebrow">01 / CURRENT INTERESTS</span><h2 id="personal-feed-title">我的兴趣历史信息流</h2></div><button type="button" className="secondary-button compact" onClick={() => { reset(); setAttempt(value => value + 1); }}>从头重新读取</button></div>
    <p className="quality-intro">按本人当前已启用兴趣回看本地历史，包含创建兴趣前的记录；同事件合并展示全部命中或待核对理由。这不是已投递通知，也不表示来源新发布。</p>
    <div className="home-filters"><label><span>事件范围</span><select value={domain || ""} onChange={event => { reset(); setDomain(event.target.value as InterestDomain || null); }}><option value="">全部已接入领域</option>{domains.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label><span>每次核对历史条数</span><select value={limit} onChange={event => { reset(); setLimit(Number(event.target.value)); }}>{[1, 5, 20, 50].map(value => <option key={value} value={value}>{value} 条</option>)}</select></label><label><span>结果显示</span><select value={filter} onChange={event => setFilter(event.target.value as typeof filter)}><option value="all">命中与待核对</option><option value="matched">仅命中</option><option value="indeterminate">仅待核对</option></select></label></div>
    {error ? <p className="inline-error" role="alert">{error}<button type="button" className="text-button" onClick={() => { reset(); setAttempt(value => value + 1); }}>重新读取当前范围</button></p> : null}
    {page ? <p className="home-counts" role="status">{page.active_interest_count} 条当前兴趣 · 本次已核对 {scanned} 条历史 · 已读取命中 {items.filter(item => item.state === "matched").length} 条 / 待核对 {items.filter(item => item.state === "indeterminate").length} 条</p> : null}
    {!page && !error ? <p role="status">正在读取本人当前兴趣与本地历史…</p> : null}
    {page?.active_interest_count === 0 ? <div className="home-empty"><h3>还没有启用的本人兴趣</h3><p>先设置研究条件，保存后可回看已有本地历史；不会创建抓取任务或补发通知。</p><button type="button" className="secondary-button" onClick={onInterests}>前往兴趣中心</button></div> : null}
    {page && page.active_interest_count > 0 && !items.length ? <p className="home-empty">{page.has_more ? "当前这段历史没有命中或待核对项，仍可继续读取下一段。" : "当前已录范围没有命中或待核对项；这不代表外网没有相关内容。"}</p> : null}
    {items.length && !visible.length ? <p className="home-empty">已读取结果中没有所选状态的记录，可切换结果显示或继续读取。</p> : null}
    <div className="home-feed-list">{visible.map(item => <article className="home-feed-item" key={eventKey(item)} data-feed-event-id={item.event.id}><div className="home-card-meta"><span className={`tag ${item.state === "matched" ? "success" : "warning"}`}>{item.state === "matched" ? "当前兴趣命中" : "待核对 · 证据不足"}</span><span>{domains.find(([key]) => key === item.event.domain)?.[1] || item.event.domain}</span><time>{stamp(item.event.observed_at)}</time></div><h3>{item.event.label}</h3><p>{item.matches.map(match => match.interest_name).join("、")} · {item.matches.length} 条独立兴趣依据</p><button type="button" className="text-button" aria-expanded={opened === eventKey(item)} onClick={() => setOpened(opened === eventKey(item) ? "" : eventKey(item))}>{opened === eventKey(item) ? "收起冻结依据" : "核对匹配理由与冻结依据"}<Icon name="chevron" size={14} /></button>{opened === eventKey(item) ? <FeedDetails key={`${eventKey(item)}:${item.event.event_hash}`} item={item} /> : null}</article>)}</div>
    {page?.has_more ? <button type="button" className="secondary-button home-more" disabled={busy} onClick={() => void load(page.next_cursor)}>{busy ? "正在核对下一段…" : "继续读取下一段历史"}<Icon name="arrow" size={15} /></button> : page && page.active_interest_count > 0 ? <p className="home-end">已到当前本地记录范围的末尾。</p> : null}
  </section>;
}

function CandidatePanel({ ownerEpoch, onPreferences, onFitments }: { ownerEpoch: number; onPreferences: () => void; onFitments: () => void }) {
  const auth = useWorkbenchAuth();
  const [catalog, setCatalog] = useState<FitmentVehicleSnapshot[]>([]);
  const [total, setTotal] = useState(0);
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [snapshotId, setSnapshotId] = useState("");
  const [snapshot, setSnapshot] = useState<FitmentVehicleSnapshotDetail | null>(null);
  const [snapshotError, setSnapshotError] = useState("");
  const [trimId, setTrimId] = useState("");
  const [wheelId, setWheelId] = useState("");
  const [axle, setAxle] = useState<"front" | "rear">("front");
  const [result, setResult] = useState<FitmentCandidates | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const catalogRequest = useRef<AbortController | null>(null);
  const detailRequest = useRef<AbortController | null>(null);
  const candidateRequest = useRef<AbortController | null>(null);
  const generations = useRef({ catalog: 0, detail: 0, candidate: 0 });
  const clearCandidate = () => { candidateRequest.current?.abort(); generations.current.candidate++; setResult(null); setBusy(false); setError(""); };
  const loadCatalog = useCallback(async (offset = 0) => {
    if (!auth.isCurrentOwner(ownerEpoch)) return;
    catalogRequest.current?.abort(); const controller = new AbortController(); catalogRequest.current = controller;
    const epoch = ++generations.current.catalog;
    const current = () => !controller.signal.aborted && catalogRequest.current === controller && generations.current.catalog === epoch && auth.isCurrentOwner(ownerEpoch);
    setCatalogBusy(true); setCatalogError("");
    try {
      const value = await tireApi.fitmentVehicleSnapshots("", offset, controller.signal);
      if (!current()) return;
      if (value.scope !== "local_workspace" || value.data_state !== "local_snapshot" || !Array.isArray(value.items)) throw new Error("车型快照范围无法核对，未展示其他资料。");
      setCatalog(previous => [...new Map((offset ? [...previous, ...value.items] : value.items).map(item => [item.id, item])).values()]); setTotal(value.total);
    } catch (cause) { if (current()) setCatalogError(errorText(cause, "车型快照读取未完成，请重试。")); }
    finally { if (current()) setCatalogBusy(false); }
  }, [ownerEpoch, auth.isCurrentOwner]);
  useEffect(() => {
    void loadCatalog();
    return () => { catalogRequest.current?.abort(); detailRequest.current?.abort(); candidateRequest.current?.abort(); generations.current.catalog++; generations.current.detail++; generations.current.candidate++; };
  }, [loadCatalog]);
  useEffect(() => {
    detailRequest.current?.abort(); const epoch = ++generations.current.detail;
    if (!snapshotId) return;
    const controller = new AbortController(); detailRequest.current = controller;
    const current = () => !controller.signal.aborted && detailRequest.current === controller && generations.current.detail === epoch && auth.isCurrentOwner(ownerEpoch);
    void tireApi.fitmentVehicleSnapshot(snapshotId, controller.signal).then(value => {
      if (!current()) return;
      if (value.id !== snapshotId || value.scope !== "local_workspace" || value.data_state !== "local_snapshot") throw new Error("返回的车型快照不属于所选范围。");
      setSnapshot(value);
    }).catch(cause => { if (current()) setSnapshotError(errorText(cause, "所选车型快照无法读取，请重新选择。")); });
    return () => { controller.abort(); generations.current.detail++; };
  }, [snapshotId, ownerEpoch, auth.isCurrentOwner]);
  function chooseSnapshot(id: string) {
    clearCandidate(); detailRequest.current?.abort(); generations.current.detail++;
    setSnapshot(null); setSnapshotError(""); setTrimId(""); setWheelId(""); setSnapshotId(id);
  }
  function refreshCatalog() { chooseSnapshot(""); setCatalog([]); setTotal(0); void loadCatalog(); }
  const wheels = snapshot?.fitments.filter(wheel => wheel.trim_id === trimId) || [];
  const wheel = wheels.find(item => item.id === wheelId);
  const selection: FitmentCandidateSelection | null = snapshot && snapshot.id === snapshotId && trimId && wheel
    ? { vehicle_id: snapshot.vehicle_id, vehicle_snapshot_id: snapshot.id, trim_id: trimId, wheel_option_id: wheel.id, axle } : null;
  async function preview() {
    if (!selection || busy || !auth.isCurrentOwner(ownerEpoch)) return;
    candidateRequest.current?.abort(); const controller = new AbortController(); candidateRequest.current = controller;
    const epoch = ++generations.current.candidate;
    const current = () => !controller.signal.aborted && candidateRequest.current === controller && generations.current.candidate === epoch && auth.isCurrentOwner(ownerEpoch);
    setResult(null); setError(""); setBusy(true);
    try {
      const preference = await tireApi.drivingPreferences(controller.signal);
      if (!current()) return;
      if (preference.scope !== "actor" || !hash(preference.fingerprint) || !Number.isSafeInteger(preference.revision) || preference.revision < 0) throw new Error("本人偏好归属或版本无法确认，未发起候选读取。");
      const value = await tireApi.previewFitmentCandidates({ selection, expected_preference_revision: preference.revision, expected_preference_fingerprint: preference.fingerprint }, controller.signal);
      if (!current()) return;
      verifyCandidates(value, selection, snapshot!.fact_hash, preference.revision, preference.fingerprint);
      if (current()) setResult(value);
    } catch (cause) { if (current()) setError(errorText(cause, "候选核对未完成，请重新读取；没有用相同尺寸或示例 SKU 补齐。")); }
    finally { if (current()) setBusy(false); }
  }
  return <section className="home-section" aria-labelledby="fitment-candidates-title">
    <div className="home-section-heading"><div><span className="eyebrow">02 / REVIEWED EXACT AXLE</span><h2 id="fitment-candidates-title">已审核精确 SKU 候选</h2></div><div className="home-section-actions"><span className="tag quiet">性能推荐尚未完成</span><button type="button" className="secondary-button compact" disabled={catalogBusy} onClick={refreshCatalog}>刷新车型快照</button></div></div>
    <p className="quality-intro">显式选择同一车型快照中的配置、轮毂与轴位，只读取证据仍有效的人工已审关系。车库文字、同名或同尺寸不用于自动配对。</p>
    <div className="home-candidate-selection"><label className="home-wide"><span>已录车型证据快照</span><select value={snapshotId} onChange={event => chooseSnapshot(event.target.value)}><option value="">请选择精确车型快照</option>{catalog.map(row => <option key={row.id} value={row.id}>{row.vehicle.model} · {row.vehicle.generation} · {row.vehicle.model_year ?? "年款未知"} · {row.vehicle.region} · 事实 #{row.fact_version} · {stamp(row.provenance.observed_at)}</option>)}</select></label><label><span>车型配置</span><select value={trimId} disabled={!snapshot} onChange={event => { clearCandidate(); setTrimId(event.target.value); setWheelId(""); }}><option value="">请选择配置</option>{snapshot?.trims.map(row => <option key={row.id} value={row.id}>{row.name} · {row.model_year ?? "年款未知"}</option>)}</select></label><label><span>轮毂配置</span><select value={wheelId} disabled={!trimId} onChange={event => { clearCandidate(); setWheelId(event.target.value); }}><option value="">请选择轮毂</option>{wheels.map(row => <option key={row.id} value={row.id}>{row.wheel_option_name} · {row.wheel_diameter_inches} 英寸</option>)}</select></label><label><span>核对轴位</span><select value={axle} onChange={event => { clearCandidate(); setAxle(event.target.value as "front" | "rear"); }}><option value="front">前轴</option><option value="rear">后轴</option></select></label><div className="home-submit"><button type="button" className="primary-button" disabled={!selection || busy} onClick={() => void preview()}>{busy ? "正在核对偏好与关系…" : "核对所选轴位候选"}<Icon name="arrow" size={15} /></button></div></div>
    {catalogBusy ? <p role="status">正在读取已录车型快照…</p> : null}
    {catalogError ? <p className="inline-error" role="alert">{catalogError}<button type="button" className="text-button" onClick={refreshCatalog}>重试车型列表</button></p> : null}
    {!catalogBusy && !catalogError && !catalog.length ? <div className="home-empty"><p>尚无已录车型快照。请先到车型适配中心核对来源，首页不会自动联网获取或猜测配置。</p><button type="button" className="secondary-button" onClick={onFitments}>前往车型适配</button></div> : null}
    {catalog.length < total ? <button type="button" className="text-button" disabled={catalogBusy} onClick={() => void loadCatalog(catalog.length)}>继续读取车型快照（已读 {catalog.length} / {total}）</button> : null}
    {snapshotId && !snapshot && !snapshotError ? <p role="status">正在核对所选车型快照…</p> : null}{snapshotError ? <p className="inline-error" role="alert">{snapshotError}<button type="button" className="text-button" onClick={() => chooseSnapshot("")}>重新选择车型快照</button></p> : null}
    {wheel ? <p className="home-selection-summary">所选{axle === "front" ? "前轴" : "后轴"}要求：{wheel[axle].size} · 载重 {text(wheel[axle].load_index)} / 速度 {text(wheel[axle].speed_rating)}。这是来源要求，不表示已确认官方原配 SKU。</p> : null}
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {result ? <div className="home-candidate-result" aria-live="polite">
      <div className="snapshot-banner"><strong>LOCAL SNAPSHOT · {result.selection.axle === "front" ? "前轴" : "后轴"}已审关系候选</strong><span>按稳定标识展示，不表达优劣；人工关系不等于官方原配认证、当前库存或整车组合验证。</span></div>
      <p className="home-counts">已核对 {result.inspected_count} / {result.relation_count} 条关系 · {result.items.length} 个去重 SKU · {result.excluded_relations.length} 条关系排除</p>
      {result.truncated ? <p className="review-warning">本次关系核对已达到处理范围上限，候选列表不完整；不能把当前数量当作全部可选项。</p> : null}
      <section className="home-focus"><h3>本人偏好的研究重点</h3><p>{result.preference.weights ? `已核对偏好修订 #${result.preference.revision}；权重只表达取舍。` : "尚未设置本人偏好，未填入默认权重，也不影响查看已审适配依据。"} 精确 SKU 性能证据尚未建立，不计算分数或跨测试总排名。</p><div>{result.research_focus.map(row => <span key={row.dimension}><strong>{dimensions[row.dimension]}</strong> {row.weight === null ? "未设置" : `${row.weight}%`}<small>精确 SKU 性能证据未建立</small></span>)}</div><button type="button" className="text-button" onClick={onPreferences}>查看或设置本人偏好</button></section>
      {!result.items.length ? <p className="home-empty">此精确车型轴位没有通过当前门禁的已审候选。未审核、已失效或证据损坏的关系没有按相同尺寸补齐；可查看下方排除项或前往车型适配中心核对。</p> : null}
      {result.items.map(item => <article className="home-candidate-card" key={item.variant_id} data-candidate-variant-id={item.variant_id}><div className="home-card-meta"><span className="tag success">人工已审关系 · 证据当前有效</span><span>无性能评分</span></div><h3>{text(item.identity.brand)} {text(item.identity.model)}</h3><dl className="home-identity">{[["manufacturer_product_code", "产品代码"], ["product_code_type", "代码命名空间"], ["size", "完整尺寸"], ["region", "市场"], ["oe_mark", "OE 声明"], ["acoustic_technology", "静音技术声明"]].map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{text(item.identity[key])}</dd></div>)}</dl><p>技术声明按记录原文展示，不据此判断更安静、抓地更强或更耐磨。</p>{item.relations.map(relation => <details className="home-relation" key={relation.revision_id}><summary>核对人工关系修订 #{relation.revision} 与双侧证据</summary><p className="hash-value">关系 {relation.relation_id} · 原修订 {relation.revision_id}<br />绑定指纹 {relation.binding_hash}</p><dl className="home-checks">{relation.checks.map(check => <div key={check.field}><dt>{check.field}</dt><dd>{({ match: "一致", conflict: "冲突", unknown: "未知", not_declared: "未声明" })[check.status]} · 车型 {text(check.vehicle_value)} / 轮胎 {text(check.tire_value)}</dd></div>)}</dl>{relation.unknown_fields.length ? <p className="review-warning">仍有未知检查：{relation.unknown_fields.join("、")}。{relation.acknowledged_unknowns ? "原审核明确确认了这些未知项，未知没有变成已证实。" : "未将未知项视为匹配。"}</p> : null}{relation.evidence.map((reference, index) => <HistoricalEvidence key={`${reference.kind}:${reference.record_id}:${index}`} evidence={reference} />)}</details>)}</article>)}
      {result.excluded_relations.length ? <details className="home-exclusions"><summary>查看没有进入候选的关系与原因</summary>{result.excluded_relations.map(row => <article key={row.relation_id}><strong>关系修订 #{row.revision} · {row.effective_state === "needs_review" ? "需要重新复核" : row.effective_state === "revoked" ? "已撤销" : row.effective_state === "pending_review" ? "尚未审核" : "当前门禁未通过"}</strong><p className="hash-value">关系 {row.relation_id} · SKU {row.variant_id}</p><p>排除依据：{row.reason_codes.join("、") || "未满足当前已审关系条件"}</p></article>)}</details> : null}
      <TestCandidateInterpretation candidates={result} onPreferences={onPreferences} onRefreshCandidates={() => void preview()} />
      <CandidateAiAssistance candidates={result} onPreferences={onPreferences} onRefreshCandidates={() => void preview()} />
    </div> : <p className="home-boundary">此处提供已审轴位研究候选；完整性能推荐与 AI 推荐尚未完成。</p>}
  </section>;
}
