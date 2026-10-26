"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type {
  BridgeBoundary, DrivingPreferenceState, DrivingWeightKey, FitmentCandidates, FitmentCandidateSelection,
  TestCandidateInterpretation as Interpretation, TestCandidateInterpretationRequest, TestCandidateLinkEvidence,
  TestEventDetail, TestEventRecord, TestMetricDimension, TestPreferenceLimitation, TestSkuLinkPage, TestSkuLinkView,
} from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import { HistoricalEvidence } from "./interest-center";
import "./test-candidate-interpretation.css";

const dimensions: [DrivingWeightKey, string][] = [["dry", "干地"], ["wet", "湿地"], ["quiet", "静音"], ["comfort", "舒适"], ["wear", "耐磨"], ["energy", "能耗"], ["appearance", "外观"]];
const dimensionLabel = (key: DrivingWeightKey | null) => dimensions.find(([value]) => value === key)?.[1] || "不纳入本次解读";
const directionLabels = { lower: "来源声明较低较好", higher: "来源声明较高较好", unspecified: "来源未说明数值方向" };
const relationshipLabels = { independent: "独立测试（录入声明）", manufacturer_commissioned: "厂商委托（录入声明）", unknown: "关系未确认" };
const stateLabels = { pending_review: "尚待人工复核", reviewed: "已人工复核", revoked: "已撤销", needs_review: "依据变化，需重新复核" };
const checkLabels = { match: "一致", conflict: "冲突", unknown: "未知", unsupported: "暂不支持" };
const limitations: Record<TestPreferenceLimitation, string> = {
  excluded_by_user: "本次未纳入个人解读，保留原始证据。", missing_measurements: "存在未录入成绩；不补零，不判断缺失对象。",
  direction_unspecified: "来源没有声明方向，不能推导数值倾向。", insufficient_observations: "已录观察不足两条，不能形成比较。",
};
const fieldLabels: Record<string, string> = {
  brand: "品牌", model: "型号", manufacturer_product_code: "产品代码", product_code_type: "代码命名空间", region: "市场",
  size: "完整尺寸", load_index: "载重指数", speed_rating: "速度级别", oe_mark: "OE 声明", acoustic_technology: "静音技术声明",
  technology_features: "技术配置", gtin: "GTIN", eprel_id: "EPREL 标识", xl: "XL", hl: "HL", run_flat: "缺气保用",
};
const reasonLabels: Record<string, string> = {
  candidate_not_current: "未进入当前精确轴位候选", link_not_eligible: "当前身份桥不具备条件化解释资格",
  selected_candidates_excluded: "存在明确排除项，整次个人解释未生成", insufficient_eligible_candidates: "合格候选不足两项",
  no_comparable_mapped_metrics: "本次没有可比较的映射指标",
};
const valueText = (value: unknown): string => value === null || value === undefined || value === "" ? "未声明" : typeof value === "object" ? JSON.stringify(value) : String(value);
const hash = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const stamp = (value: string) => Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN") : "时间未记录";
const sameSelection = (a: FitmentCandidateSelection, b: FitmentCandidateSelection) => (["vehicle_id", "vehicle_snapshot_id", "trim_id", "wheel_option_id", "axle"] as const).every(key => a[key] === b[key]);
const canonical = (value: unknown): unknown => Array.isArray(value) ? value.map(canonical)
  : value !== null && typeof value === "object" ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, entry]) => [key, canonical(entry)])) : value;
const equal = (a: unknown, b: unknown) => JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
const boundaryValid = (value: BridgeBoundary) => value.material_origin === "operator_supplied" && value.origin_verification === "unverified"
  && value.read_scope === "local_workspace" && value.test_record_kind === "manual_transcription" && value.test_verification === "unverified"
  && value.provider_use === false && value.export === false;
const responseError = "返回的解释与本次场次、偏好、轴位或逐项桥修订不一致，结果已清空。请重新核对依据。";
const reasons = (codes: string[]) => codes.map(code => reasonLabels[code] ? `${reasonLabels[code]}（${code}）` : code).join("、") || "未声明具体原因";

function errorText(cause: unknown) {
  if (cause instanceof ApiError) {
    if (cause.status === 409) return "事件、偏好、桥或轴位依据已变化，或本次范围不完整。旧结果已清空，请重新核对当前依据。";
    if (cause.status === 422) return "本次选择的作用域、逐项映射或证据完整性未通过，未生成替代解释。请重新核对。";
    if (cause.status === 404) return "所选场次或桥记录已无法读取，请刷新当前记录。";
  }
  return cause instanceof Error && cause.message === responseError ? responseError : "本次读取或解释未完成，请重试；没有使用示例或相同名称的记录补齐。";
}

function assertLink(link: TestSkuLinkView, event: TestEventDetail) {
  if (link.schema !== "test-sku-link@1" || link.scope !== "local_workspace" || link.data_state !== "local_snapshot"
    || !link.id || !link.revision_id || !hash(link.fingerprint) || !boundaryValid(link.boundary)
    || link.selection.event_id !== event.id || link.frozen_evidence.test.event_id !== event.id
    || link.selection.variant_id !== link.frozen_evidence.tire.variant_id
    || link.selection.participant_key !== link.frozen_evidence.test.participant.key) throw new Error(responseError);
}

/** Validate the entire requested set before exposing any response evidence or personal result. */
function assertInterpretation(result: Interpretation, payload: TestCandidateInterpretationRequest, event: TestEventDetail, basis: FitmentCandidates) {
  const projection = result.candidate_projection, source = result.source_evidence, personal = result.personal_interpretation;
  if (result.schema !== "test-candidate-interpretation@1" || result.policy_version !== "same-event-candidate-interpretation@1"
    || result.scope !== "actor" || result.evidence_scope !== "local_workspace" || result.data_state !== "local_snapshot"
    || result.comparison_scope !== "same_event_only" || result.ranking !== "source_reported_only" || result.performance_score !== null
    || result.official_oe.state !== "not_established" || !boundaryValid(result.boundary) || !sameSelection(result.selection, payload.selection)
    || result.binding.event.id !== event.id || result.binding.event.revision_id !== payload.expected_event_revision_id
    || result.binding.event.revision !== payload.expected_event_revision || result.binding.event.fingerprint !== payload.expected_event_fingerprint
    || result.binding.preference.revision !== payload.expected_preference_revision || result.binding.preference.fingerprint !== payload.expected_preference_fingerprint
    || !hash(result.binding.candidate_fingerprint) || !hash(result.binding.interpretation_fingerprint)
    || projection.schema !== "fitment-candidates@1" || projection.policy_version !== "reviewed-exact-axle@1"
    || projection.scope !== "actor" || projection.evidence_scope !== "local_workspace" || projection.data_state !== "local_snapshot"
    || !sameSelection(projection.selection, payload.selection) || projection.truncated || projection.ranking !== "not_computed"
    || projection.performance_score !== null || projection.official_oe.state !== "not_established"
    || projection.vehicle_binding.snapshot_id !== payload.selection.vehicle_snapshot_id || projection.vehicle_binding.fact_hash !== basis.vehicle_binding.fact_hash
    || projection.preference.revision !== payload.expected_preference_revision || projection.preference.fingerprint !== payload.expected_preference_fingerprint
    || !equal(projection.preference.weights, basis.preference.weights)
    || !Array.isArray(result.items) || !Array.isArray(result.excluded) || !Array.isArray(source.participants)
    || result.items.length !== payload.candidates.length || result.requested_count !== payload.candidates.length
    || source.record_kind !== "manual_transcription" || source.verification_status !== "unverified" || source.verified_at !== null || source.recorded_at !== event.recorded_at
    || !equal(source.metrics, event.event.metrics)) throw new Error(responseError);
  const { participants: _participants, metrics: _metrics, measurements: _measurements, ...sourceEvent } = event.event;
  if (!equal(source.event, sourceEvent)) throw new Error(responseError);
  const participants = new Set<string>(), keys = new Set<string>();
  result.items.forEach((item, index) => {
    const ref = payload.candidates[index], link = item.link;
    const participant = event.participants.find(row => row.key === item.participant_key);
    if (item.variant_id !== ref.variant_id || link.id !== ref.link_id || link.revision_id !== ref.expected_link_revision_id
      || link.revision !== ref.expected_link_revision || link.fingerprint !== ref.expected_link_fingerprint
      || link.selection.variant_id !== ref.variant_id || link.selection.event_id !== event.id
      || link.selection.event_revision_id !== payload.expected_event_revision_id || link.confirmed_event_revision_id !== payload.expected_event_revision_id
      || link.selection.participant_key !== item.participant_key || !participant || participant.id !== item.participant_id
      || participants.has(item.participant_id) || keys.has(item.participant_key) || !hash(link.confirmed_participant_hash)
      || !hash(link.binding_hash) || !boundaryValid(link.boundary) || typeof item.eligible !== "boolean" || !Array.isArray(item.reason_codes)) throw new Error(responseError);
    participants.add(item.participant_id); keys.add(item.participant_key);
    const excluded = result.excluded.filter(row => row.variant_id === item.variant_id && row.link_id === link.id);
    if (item.eligible ? excluded.length !== 0 : excluded.length !== 1 || !equal(excluded[0].reason_codes, item.reason_codes)) throw new Error(responseError);
    if (item.eligible && (link.review_state !== "reviewed" || link.effective_state !== "reviewed" || link.eligibility !== "conditional_reviewed_transcription"
      || !projection.items.some(row => row.variant_id === item.variant_id))) throw new Error(responseError);
  });
  if (result.eligible_count !== result.items.filter(item => item.eligible).length || result.excluded.length !== result.items.filter(item => !item.eligible).length
    || source.selected_participant_count !== participants.size || source.participants.length !== participants.size
    || source.recorded_participant_count !== event.participants.length
    || new Set(source.participants.map(row => row.id)).size !== participants.size
    || source.participants.some(row => !participants.has(row.id) || row.identity_status !== "participant_only"
      || !equal(row, event.participants.find(person => person.id === row.id)))
    || (result.excluded.length > 0 && (personal !== null || result.status !== "insufficient_evidence"))
    || !["conditional_observations", "insufficient_evidence"].includes(result.status)
    || (result.status === "conditional_observations" && personal === null)) throw new Error(responseError);
  const expectedMeasurements = event.event.measurements.filter(row => keys.has(row.participant_key));
  if (source.measurements.length !== expectedMeasurements.length || new Set(source.measurements.map(row => JSON.stringify([row.participant_key, row.metric_key]))).size !== expectedMeasurements.length
    || source.measurements.some(row => {
      const original = expectedMeasurements.find(value => value.participant_key === row.participant_key && value.metric_key === row.metric_key);
      const participant = event.participants.find(value => value.key === row.participant_key);
      return !original || !participant || row.participant_id !== participant.id || typeof row.raw_value !== "string"
        || !(["raw_value", "source_rank", "evidence_span", "evidence_locator"] as const).every(key => row[key] === original[key])
        || !row.evidence_id || row.reference.event_id !== event.id || row.reference.revision !== payload.expected_event_revision
        || row.reference.participant_id !== row.participant_id || row.reference.metric_key !== row.metric_key;
    })) throw new Error(responseError);
  for (const candidate of projection.items) {
    if (candidate.performance_score !== null || candidate.ranking !== "not_computed" || candidate.official_oe.state !== "not_established"
      || !candidate.relations.length || candidate.relations.some(relation => !(["vehicle_id", "trim_id", "wheel_option_id", "axle"] as const).every(key => relation.selection[key] === payload.selection[key])
        || relation.selection.variant_id !== candidate.variant_id || relation.vehicle_evidence.fact_hash !== basis.vehicle_binding.fact_hash
        || !hash(relation.binding_hash))) throw new Error(responseError);
  }
  if (personal && (personal.mapping_origin !== "user_explicit_once" || !equal(personal.weights, projection.preference.weights)
    || personal.metric_dimensions.length !== payload.metric_dimensions.length
    || payload.metric_dimensions.some(row => !personal.metric_dimensions.some(value => value.metric_key === row.metric_key && value.dimension === row.dimension))
    || new Set(personal.metric_dimensions.map(row => row.metric_key)).size !== payload.metric_dimensions.length)) throw new Error(responseError);
  if (personal) {
    if (personal.metrics.length !== source.metrics.length || new Set(personal.metrics.map(row => row.metric_key)).size !== source.metrics.length) throw new Error(responseError);
    for (const metric of personal.metrics) {
      const definition = source.metrics.find(row => row.key === metric.metric_key);
      const mapped = payload.metric_dimensions.find(row => row.metric_key === metric.metric_key);
      const observations = source.measurements.filter(row => row.metric_key === metric.metric_key);
      const observed = new Set(observations.map(row => row.participant_id));
      const sameIds = (ids: string[], expected: Set<string>) => ids.length === expected.size && new Set(ids).size === expected.size && ids.every(id => expected.has(id));
      if (!definition || !mapped || metric.dimension !== mapped.dimension
        || !sameIds(metric.observed_participant_ids, observed) || !sameIds(metric.missing_participant_ids, new Set([...participants].filter(id => !observed.has(id))))
        || !sameIds(metric.evidence_ids, new Set(observations.map(row => row.evidence_id)))
        || (metric.observation_comparison !== null && (metric.observation_comparison.scope !== "selected_recorded_observations"
          || metric.dimension === null || definition.direction === "unspecified" || observed.size < 2
          || !metric.observation_comparison.favorable_participant_ids.length
          || metric.observation_comparison.favorable_participant_ids.some(id => !observed.has(id))
          || metric.observation_comparison.evidence_ids.some(id => !metric.evidence_ids.includes(id))))) throw new Error(responseError);
    }
  }
}

type Props = { candidates: FitmentCandidates; onPreferences: () => void; onRefreshCandidates: () => void };
type ReadKind = "events" | "event" | "links" | "preference" | "interpret";
const kinds: ReadKind[] = ["events", "event", "links", "preference", "interpret"];

export default function TestCandidateInterpretation(props: Props) {
  const auth = useWorkbenchAuth();
  if (!auth.ready) return <section className="test-candidate-panel"><h3>同场精确候选解读</h3><p role="status">正在确认账户归属，当前草稿和旧结果暂不显示。</p></section>;
  const basisKey = JSON.stringify([auth.ownerEpoch, props.candidates.selection, props.candidates.vehicle_binding, props.candidates.preference,
    props.candidates.truncated, props.candidates.items.map(item => [item.variant_id, item.relations.map(row => [row.relation_id, row.revision_id, row.revision, row.binding_hash])])]);
  return <CandidateWorkspace key={basisKey} {...props} ownerEpoch={auth.ownerEpoch} />;
}

function CandidateWorkspace({ candidates, ownerEpoch, onPreferences, onRefreshCandidates }: Props & { ownerEpoch: number }) {
  const auth = useWorkbenchAuth(), titleId = useId();
  const [eventPage, setEventPage] = useState<{ items: TestEventRecord[]; total: number } | null>(null);
  const [eventOffset, setEventOffset] = useState(0), [eventReload, setEventReload] = useState(0), [eventsBusy, setEventsBusy] = useState(false), [eventsError, setEventsError] = useState("");
  const [eventId, setEventId] = useState(""), [event, setEvent] = useState<TestEventDetail | null>(null), [eventError, setEventError] = useState("");
  const [linkPage, setLinkPage] = useState<TestSkuLinkPage | null>(null), [knownLinks, setKnownLinks] = useState<TestSkuLinkView[]>([]);
  const [linkOffset, setLinkOffset] = useState(0), [linkReload, setLinkReload] = useState(0), [linksBusy, setLinksBusy] = useState(false), [linksError, setLinksError] = useState("");
  const [selected, setSelected] = useState<string[]>([]), [selectedLinks, setSelectedLinks] = useState<Record<string, string>>({});
  const [mapping, setMapping] = useState<TestMetricDimension[]>([]), [preference, setPreference] = useState<DrivingPreferenceState | null>(null), [preferenceError, setPreferenceError] = useState("");
  const [result, setResult] = useState<Interpretation | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(""), [stale, setStale] = useState(false);
  const requests = useRef<Partial<Record<ReadKind, AbortController>>>({}), generations = useRef<Record<ReadKind, number>>({ events: 0, event: 0, links: 0, preference: 0, interpret: 0 });
  const knownLinksRef = useRef<TestSkuLinkView[]>([]);
  const cancel = useCallback((kind: ReadKind) => { requests.current[kind]?.abort(); generations.current[kind]++; }, []);
  const begin = useCallback((kind: ReadKind) => {
    cancel(kind); const controller = new AbortController(); requests.current[kind] = controller;
    const generation = generations.current[kind];
    return { controller, current: () => !controller.signal.aborted && requests.current[kind] === controller
      && generations.current[kind] === generation && auth.isCurrentOwner(ownerEpoch) };
  }, [cancel, ownerEpoch, auth.isCurrentOwner]);
  const invalidate = useCallback(() => { cancel("interpret"); setResult(null); setBusy(false); setError(""); }, [cancel]);
  function clearLinks() {
    cancel("links"); knownLinksRef.current = []; setKnownLinks([]); setLinkPage(null); setLinkOffset(0); setLinksError(""); setLinksBusy(false);
    setSelected([]); setSelectedLinks({});
  }
  function chooseEvent(id: string) {
    invalidate(); cancel("event"); clearLinks(); setEvent(null); setEventError(""); setMapping([]); setStale(false); setEventId(id);
  }
  function refreshEvents() { chooseEvent(""); setEventPage(null); setEventOffset(0); setEventReload(value => value + 1); }
  function refreshLinks() { invalidate(); clearLinks(); setStale(false); setLinkReload(value => value + 1); }
  useEffect(() => () => kinds.forEach(kind => cancel(kind)), [cancel]);
  useEffect(() => {
    const { controller, current } = begin("events"); setEventPage(null); setEventsError(""); setEventsBusy(true);
    void tireApi.testEvents(controller.signal, eventOffset).then(value => {
      if (!current()) return;
      if (!Array.isArray(value.items) || !Number.isSafeInteger(value.total) || value.total < 0
        || value.items.some(row => !row.id || !row.revision_id || !hash(row.fingerprint))) throw new Error(responseError);
      setEventPage(value);
    }).catch(cause => { if (current()) setEventsError(errorText(cause)); }).finally(() => { if (current()) setEventsBusy(false); });
    return () => controller.abort();
  }, [begin, eventOffset, eventReload]);
  useEffect(() => {
    const { controller, current } = begin("preference"); setPreference(null); setPreferenceError("");
    void tireApi.drivingPreferences(controller.signal).then(value => {
      if (!current()) return;
      if (value.scope !== "actor" || value.revision !== candidates.preference.revision || value.fingerprint !== candidates.preference.fingerprint
        || !equal(value.weights, candidates.preference.weights)) {
        setPreferenceError("本人偏好已与这批候选的核对依据不同，请重新核对轴位候选。"); return;
      }
      setPreference(value);
    }).catch(cause => { if (current()) setPreferenceError(errorText(cause)); });
    return () => controller.abort();
  }, [begin, candidates.preference]);
  useEffect(() => {
    if (!eventId) return;
    const { controller, current } = begin("event");
    void tireApi.testEvent(eventId, controller.signal).then(value => {
      if (!current()) return;
      if (value.id !== eventId || value.scope !== "local_workspace" || value.data_state !== "local_snapshot"
        || !value.revision_id || !hash(value.fingerprint) || !Array.isArray(value.participants) || !Array.isArray(value.event.metrics)) throw new Error(responseError);
      if (value.state !== "active") { setEventError("这场记录已撤销，请刷新并选择当前有效场次。"); return; }
      setEvent(value); setMapping(value.event.metrics.map(metric => ({ metric_key: metric.key, dimension: null })));
    }).catch(cause => { if (current()) setEventError(errorText(cause)); });
    return () => controller.abort();
  }, [begin, eventId]);
  useEffect(() => {
    if (!event) return;
    const { controller, current } = begin("links"); setLinkPage(null); setLinksError(""); setLinksBusy(true);
    void tireApi.testSkuLinks(event.id, linkOffset, controller.signal).then(value => {
      if (!current()) return;
      if (value.schema !== "test-sku-link@1" || value.scope !== "local_workspace" || value.offset !== linkOffset
        || !Number.isSafeInteger(value.total) || value.total < 0 || !Array.isArray(value.items) || !boundaryValid(value.boundary)) throw new Error(responseError);
      value.items.forEach(link => assertLink(link, event));
      const merged = new Map(knownLinksRef.current.map(link => [link.id, link]));
      for (const link of value.items) {
        const old = merged.get(link.id);
        if (old && (old.revision_id !== link.revision_id || old.fingerprint !== link.fingerprint)) throw new Error(responseError);
        merged.set(link.id, link);
      }
      knownLinksRef.current = [...merged.values()]; setKnownLinks(knownLinksRef.current); setLinkPage(value);
    }).catch(cause => { if (current()) { invalidate(); setLinksError(errorText(cause)); } }).finally(() => { if (current()) setLinksBusy(false); });
    return () => controller.abort();
  }, [begin, event, linkOffset, linkReload, invalidate]);
  const chosen = selected.map(variant => knownLinks.find(link => link.id === selectedLinks[variant] && link.selection.variant_id === variant));
  const uniqueParticipants = new Set(chosen.filter(link => !!link).map(link => link!.selection.participant_key));
  const completeSelection = selected.length >= 2 && selected.length <= 60 && chosen.every(link => !!link)
    && uniqueParticipants.size === selected.length && new Set(chosen.map(link => link?.id)).size === selected.length;
  const canInterpret = !!event && !!preference?.weights && !candidates.truncated && !stale && !linksError && completeSelection && !busy;
  async function interpret() {
    if (!canInterpret || !event || !preference || !auth.isCurrentOwner(ownerEpoch)) return;
    invalidate(); const { controller, current } = begin("interpret"); setBusy(true);
    const payload: TestCandidateInterpretationRequest = {
      selection: { ...candidates.selection }, expected_event_revision_id: event.revision_id, expected_event_revision: event.revision,
      expected_event_fingerprint: event.fingerprint, expected_preference_revision: preference.revision, expected_preference_fingerprint: preference.fingerprint,
      candidates: chosen.map(link => ({ variant_id: link!.selection.variant_id, link_id: link!.id!, expected_link_revision_id: link!.revision_id!,
        expected_link_revision: link!.revision, expected_link_fingerprint: link!.fingerprint })), metric_dimensions: mapping.map(row => ({ ...row })),
    };
    try {
      const value = await tireApi.interpretTestEventCandidates(event.id, payload, controller.signal);
      if (!current()) return;
      assertInterpretation(value, payload, event, candidates);
      if (current()) setResult(value);
    } catch (cause) {
      if (!current()) return;
      setResult(null); setError(errorText(cause));
      if ((cause instanceof ApiError && [404, 409, 422].includes(cause.status)) || (cause instanceof Error && cause.message === responseError)) setStale(true);
    } finally { if (current()) setBusy(false); }
  }
  return <section className="test-candidate-panel" aria-labelledby={titleId} data-testid="test-candidate-interpretation">
    <div className="test-candidate-heading"><div><span className="eyebrow">SAME EVENT / EXPLICIT EVIDENCE</span><h3 id={titleId}>同场精确候选解读</h3></div><span className="tag quiet">本地条件化观察</span></div>
    <p>明确选择一场测试及每项候选的身份桥，再按本人的七维偏好核对已录观察。名称和尺寸不会自动建立关联；不生成综合性能分、跨场总榜或安装建议。</p>
    {candidates.truncated ? <p className="review-warning">当前轴位候选范围不完整，不能发起解释。请先重新核对完整候选范围。</p> : null}
    <fieldset className="test-candidate-step"><legend>1 / 明确选择当前测试场次</legend>
      <label className="test-candidate-field"><span>当前页已录场次</span><select aria-label="选择当前测试场次" value={eventId} disabled={eventsBusy} onChange={e => chooseEvent(e.target.value)}><option value="">请选择本场测试</option>{eventId && !eventPage?.items.some(row => row.id === eventId) ? <option value={eventId}>当前已选：{event?.title || eventId}（其他页）</option> : null}{eventPage?.items.map(row => <option key={row.id} value={row.id} disabled={row.state !== "active"}>{row.title} · {row.organization} · {row.tested_size} · #{row.revision}{row.state === "revoked" ? " · 已撤销" : ""}</option>)}</select></label>
      <div className="test-candidate-actions"><button type="button" className="text-button" disabled={eventsBusy} onClick={refreshEvents}>刷新测试场次</button><button type="button" className="text-button" disabled={eventsBusy || eventOffset === 0} onClick={() => setEventOffset(value => Math.max(0, value - 50))}>上一页场次</button><button type="button" className="text-button" disabled={eventsBusy || !eventPage || eventOffset + eventPage.items.length >= eventPage.total || !eventPage.items.length} onClick={() => setEventOffset(value => value + (eventPage?.items.length || 0))}>下一页场次</button>{eventPage ? <span>共 {eventPage.total} 场；当前页 {eventPage.items.length} 场</span> : null}</div>
      {eventsBusy ? <p role="status">正在读取本地场次…</p> : null}{eventsError ? <p className="inline-error" role="alert">{eventsError}</p> : null}
      {eventPage?.total === 0 ? <p className="test-candidate-empty">尚无已录测试场次。缺少来源记录时保留材料不足状态。</p> : null}
      {eventId && !event && !eventError ? <p role="status">正在核对所选场次的当前修订…</p> : null}{eventError ? <p className="inline-error" role="alert">{eventError}</p> : null}
      {event ? <div className="test-candidate-event"><strong>{event.title} · 当前修订 #{event.revision}</strong><p>{event.organization} · {relationshipLabels[event.relationship]} · {event.tested_size} · 人工转录，未在线核验</p><p>{event.event.conditions}</p><p>{event.coverage === "full_event" ? "声明录入整场" : "仅选录部分结果"}；已录 {event.participant_count} / 来源总数 {event.event.reported_participants ?? "未知"}。当前页切换不会替换已明确选中的场次。</p></div> : null}
    </fieldset>
    {event ? <>
      <fieldset className="test-candidate-step"><legend>2 / 逐项选择候选与本场身份桥</legend><p>勾选 2–60 项，逐项明确选择桥。未通过资格的桥也可明确提交核对；任一所选项被排除时，整次不会生成个人解释。</p>
        <div className="test-candidate-actions"><button type="button" className="text-button" disabled={linksBusy} onClick={refreshLinks}>刷新本场身份桥</button><span>{linkPage ? `已读取 ${knownLinks.length} / ${linkPage.total} 条桥记录` : "正在核对本场桥记录"}</span></div>
        {linksBusy ? <p role="status">正在读取本场身份桥…</p> : null}{linksError ? <p className="inline-error" role="alert">{linksError}</p> : null}
        {linkPage && knownLinks.length < linkPage.total ? <p className="review-boundary">本场桥目录尚未读完，当前没有选项不代表没有已保存的桥。</p> : null}
        <div className="test-candidate-choices">{candidates.items.map(candidate => {
          const options = knownLinks.filter(link => link.selection.variant_id === candidate.variant_id);
          const chosenLink = options.find(link => link.id === selectedLinks[candidate.variant_id]);
          const label = `${valueText(candidate.identity.brand)} ${valueText(candidate.identity.model)} · ${valueText(candidate.identity.manufacturer_product_code)}`;
          return <article className="test-candidate-choice" key={candidate.variant_id} data-candidate-choice={candidate.variant_id}>
            <label className="test-candidate-checkbox"><input type="checkbox" aria-label={`${label} 纳入本次候选解读`} checked={selected.includes(candidate.variant_id)} disabled={!options.length || selected.length >= 60 && !selected.includes(candidate.variant_id)} onChange={() => { invalidate(); setSelected(previous => previous.includes(candidate.variant_id) ? previous.filter(id => id !== candidate.variant_id) : [...previous, candidate.variant_id]); }} /><strong>{label}</strong></label>
            <p>{valueText(candidate.identity.product_code_type)} · {valueText(candidate.identity.region)} · {valueText(candidate.identity.size)}</p>
            <label className="test-candidate-field"><span>明确选择本场桥</span><select data-candidate-bridge={candidate.variant_id} aria-label={`${label}的本场身份桥`} value={selectedLinks[candidate.variant_id] || ""} disabled={!options.length} onChange={e => { invalidate(); setSelectedLinks(previous => ({ ...previous, [candidate.variant_id]: e.target.value })); }}><option value="">请选择一条明确的桥</option>{options.map(link => {
              const person = event.participants.find(row => row.key === link.selection.participant_key);
              return <option key={link.id} value={link.id!}>{person ? `${person.brand} ${person.model} · ${person.source_designation || person.key}` : `当前参测对象已不在记录中 · ${link.selection.participant_key}`} · #{link.revision} · {stateLabels[link.effective_state]}</option>;
            })}</select></label>
            {!options.length ? <p className="test-candidate-empty">已读取的桥中，没有该精确候选的明确关联。可继续读取下一页；不会按同名或同尺寸补桥。</p> : null}
            {chosenLink ? <><p>{chosenLink.eligibility === "conditional_reviewed_transcription" ? "列表所载：条件化人工转录关联，仍须提交时重新核验。" : "列表所载：尚不具备条件化解释资格；提交后将明确核对不足。"}</p><p className="test-candidate-hash">桥 {chosenLink.id} · 修订 ID {chosenLink.revision_id}</p><p>{chosenLink.boundary.notice}</p></> : null}
          </article>;
        })}</div>
        {linkPage && linkOffset + linkPage.items.length < linkPage.total ? <button type="button" className="secondary-button" disabled={linksBusy || !linkPage.items.length} onClick={() => setLinkOffset(linkOffset + linkPage.items.length)}>继续读取本场身份桥</button> : null}
        <p role="status">已勾选 {selected.length} 项；须为不同精确 SKU、不同桥及不同本场参测对象。{selected.length >= 2 && uniqueParticipants.size !== selected.length ? "请补齐桥选择并排除重复参测对象。" : ""}</p>
      </fieldset>
      <fieldset className="test-candidate-step"><legend>3 / 明确本次七维映射</legend><p>本场所有指标均列在下方，默认不纳入。分类来自你的本次选择，不是测试机构结论。</p>
        {event.event.metrics.map((metric, index) => <label className="test-candidate-mapping" key={metric.key}><span><strong>{metric.label}</strong><small>{metric.unit} · {directionLabels[metric.direction]}</small><small>{metric.protocol}</small></span><select aria-label={`${metric.label}的候选解读维度`} value={mapping[index]?.dimension ?? ""} onChange={e => { invalidate(); const dimension = e.target.value ? e.target.value as DrivingWeightKey : null; setMapping(previous => previous.map((row, at) => at === index ? { ...row, dimension } : row)); }}><option value="">不纳入本次解读</option>{dimensions.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>)}
        {preference?.weights ? <p className="test-candidate-weights">本人偏好修订 #{preference.revision}：{dimensions.map(([key, label]) => <span key={key}>{label} {preference.weights![key]}%</span>)}</p> : <p>{preferenceError || (preference ? "尚未保存本人偏好；不会补入默认权重。" : "正在确认本人偏好…")}</p>}
        <button type="button" className="text-button" onClick={onPreferences}>查看或设置本人驾驶偏好</button>
      </fieldset>
      <div className="test-candidate-submit"><button type="button" className="primary-button" disabled={!canInterpret} onClick={() => void interpret()}>{busy ? "正在重核全部组合依据…" : "按已选桥与映射解读候选"}</button>{busy ? <button type="button" className="text-button" onClick={invalidate}>取消本次候选解读</button> : null}<p>全部映射为“不纳入”时也可明确核对证据；覆盖为零不会生成最佳候选。</p></div>
    </> : null}
    {error ? <p className="inline-error" role="alert" data-testid="test-candidate-error">{error}</p> : null}
    {stale || preferenceError || candidates.truncated ? <div className="test-candidate-actions"><button type="button" className="secondary-button" onClick={onRefreshCandidates}>重新核对轴位候选</button><span>场次或桥变化后，也请刷新其当前记录并重新明确选择。</span></div> : null}
    {result ? <InterpretationResult result={result} /> : null}
  </section>;
}

function BridgeEvidence({ link }: { link: TestCandidateLinkEvidence }) {
  return <div className="test-candidate-bridge-evidence"><p>{link.boundary.notice}</p><p>操作者提供 · 人工转录 · 未在线核验 · 共享工作区；材料不可用于 Provider 或导出。</p><p className="test-candidate-hash">桥 {link.id} · 修订 #{link.revision} · {link.revision_id}<br />桥指纹 {link.fingerprint}<br />绑定指纹 {link.binding_hash}</p>
    <div className="test-candidate-checks">{link.checks.map(check => <div key={check.field}><strong>{fieldLabels[check.field] || check.field}</strong><span>材料：{valueText(check.material_value)}</span><span>SKU：{valueText(check.sku_value)}</span><span>{checkLabels[check.status]}</span></div>)}</div>
    {link.unknown_fields.length ? <p className="review-boundary">未知或未声明：{link.unknown_fields.map(key => fieldLabels[key] || key).join("、")}。不从 SKU 侧补填材料声明。</p> : null}
    {link.blockers.length || link.stale_reasons.length ? <p className="review-warning">桥限制：{reasons([...link.blockers, ...link.stale_reasons])}</p> : null}
    {link.material_evidence.map(material => <article className="test-candidate-material" key={material.document_id}><h5>{material.metadata.title}</h5><p>原件 {material.metadata.byte_count.toLocaleString()} 字节 · {material.metadata.source_url || "来源链接未声明"}</p><p className="test-candidate-hash">材料 {material.document_id}<br />原件 SHA-256 {material.raw_hash}<br />元数据 SHA-256 {material.metadata_hash}</p><p>场次定位：第 {material.event_locator.page} 页 · {material.event_locator.region}</p><blockquote>{material.event_locator.quote}</blockquote><p>参测对象定位：第 {material.participant_locator.page} 页 · {material.participant_locator.region}</p><blockquote>{material.participant_locator.quote}</blockquote><p>权利人：{material.rights.rights_holder}；留存、工作区重开与短引文依据：{material.rights.basis}</p></article>)}
    <details><summary>逐项材料声明与完整定位</summary>{link.assertions.map((assertion, index) => <article className="test-candidate-assertion" key={`${assertion.field}:${index}`}><strong>{fieldLabels[assertion.field] || assertion.field}：{valueText(assertion.material_value)}</strong><p>{assertion.material_document_id} · 第 {assertion.page} 页 · {assertion.region}</p><blockquote>{assertion.quote}</blockquote><p className="test-candidate-hash">引文 SHA-256 {assertion.quote_sha256}</p></article>)}<pre>{JSON.stringify(link, null, 2)}</pre></details>
  </div>;
}

function InterpretationResult({ result }: { result: Interpretation }) {
  const source = result.source_evidence, personal = result.personal_interpretation;
  const people = new Map(source.participants.map(person => [person.id, `${person.brand} ${person.model}${person.source_designation ? ` · ${person.source_designation}` : ""}`]));
  const metricNames = new Map(source.metrics.map(metric => [metric.key, metric.label]));
  const names = (ids: string[]) => ids.map(id => people.get(id) || id).join("、") || "无";
  return <div className="test-candidate-result" data-testid="test-candidate-result" aria-live="polite">
    <div className="snapshot-banner"><strong>{result.status === "conditional_observations" ? "本场已录观察下的条件化解读" : "材料或映射不足 · 仅核对已有证据"}</strong><span>请求 {result.requested_count} 项 / 通过 {result.eligible_count} 项；来源名次保持原值，无综合性能分、官方 OE 或安装安全结论。</span></div>
    <p className="test-candidate-hash">绑定事件 #{result.binding.event.revision} · {result.binding.event.revision_id}<br />本人偏好 #{result.binding.preference.revision}<br />候选指纹 {result.binding.candidate_fingerprint}<br />组合指纹 {result.binding.interpretation_fingerprint}</p><p>这是本次读快照的绑定，不保证响应到达后所有依据仍为最新。</p>
    {result.excluded.length ? <section className="test-candidate-excluded" aria-label="本次排除项"><h4>存在排除项，整次个人解释未生成</h4>{result.excluded.map(row => <article key={row.variant_id}><strong>精确 SKU {row.variant_id}</strong><p className="test-candidate-hash">桥 {row.link_id}</p><p>{reasons(row.reason_codes)}</p></article>)}<p>保留下方原始来源观察供核对；被排除参测对象的成绩不作为精确 SKU 性能依据。需重新明确选择有效集合后再发起。</p></section> : null}
    <section aria-label="本次精确轴位依据"><h4>本次重核的精确轴位依据</h4><p>{result.selection.axle === "front" ? "前轴" : "后轴"} · 配置 {result.selection.trim_id} · 轮组 {result.selection.wheel_option_id}；车型快照 {result.selection.vehicle_snapshot_id}。</p>
      {result.items.map(item => {
        const candidate = result.candidate_projection.items.find(row => row.variant_id === item.variant_id);
        return <details className="test-candidate-evidence" key={item.variant_id}><summary>{candidate ? `${valueText(candidate.identity.brand)} ${valueText(candidate.identity.model)} · ${valueText(candidate.identity.manufacturer_product_code)}` : item.variant_id} · {item.eligible ? "条件准入" : "明确排除"}</summary>
          {candidate ? <><dl className="test-candidate-meta">{Object.entries(candidate.identity).map(([key, value]) => <div key={key}><dt>{fieldLabels[key] || key}</dt><dd>{valueText(value)}</dd></div>)}</dl>{candidate.relations.map(relation => <article className="test-candidate-relation" key={relation.revision_id}><h5>已审适配关系 #{relation.revision}</h5><p className="test-candidate-hash">关系 {relation.relation_id} · {relation.revision_id}<br />绑定 {relation.binding_hash}</p><div className="test-candidate-checks">{relation.checks.map(check => <div key={check.field}><strong>{fieldLabels[check.field] || check.field}</strong><span>车型：{valueText(check.vehicle_value)}</span><span>轮胎：{valueText(check.tire_value)}</span><span>{{ match: "一致", conflict: "冲突", unknown: "未知", not_declared: "未声明" }[check.status]}</span></div>)}</div>{relation.unknown_fields.length ? <p className="review-boundary">未知项：{relation.unknown_fields.join("、")}；{relation.acknowledged_unknowns ? "原审核确认知悉未知，未知仍未变为已证实。" : "未知未视为匹配。"}</p> : null}<details><summary>完整车型、轮胎来源与结构化定位</summary><pre>{JSON.stringify({ vehicle_evidence: relation.vehicle_evidence, tire_evidence: relation.tire_evidence }, null, 2)}</pre></details>{relation.evidence.map((ref, index) => <HistoricalEvidence key={`${ref.record_id}:${index}`} evidence={ref} />)}</article>)}</> : <p className="review-warning">该项未进入本次当前轴位候选，原始来源观察不得移植为其性能结论。</p>}
          {item.reason_codes.length ? <p>{reasons(item.reason_codes)}</p> : null}
        </details>;
      })}
      {result.candidate_projection.excluded_relations.length ? <details><summary>本次轴位关系排除记录</summary>{result.candidate_projection.excluded_relations.map(row => <p key={row.relation_id}>关系 {row.relation_id} · #{row.revision} · SKU {row.variant_id} · {reasons(row.reason_codes)}</p>)}</details> : null}
    </section>
    <section aria-label="本次条件性身份桥"><h4>参测对象与 SKU 的条件性桥</h4><p>来源身份仍为本场参测对象；独立显示的桥只表达本次材料条件下的人工关联，不升级为在线核验。</p>{result.items.map(item => <details className="test-candidate-evidence" key={item.variant_id}><summary>{people.get(item.participant_id) || item.participant_key} → SKU {item.variant_id} · {item.eligible ? "条件化人工转录关联" : "不具备本次资格"}</summary><BridgeEvidence link={item.link} /></details>)}</section>
    <section aria-label="本次个人取舍与覆盖"><h4>本人偏好下的逐项取舍</h4>{personal ? <>
      <div className="test-candidate-coverage">{[["已映射权重", personal.coverage.mapped_weight], ["具有完整可比较指标的权重", personal.coverage.fully_comparable_weight], ["未映射权重", personal.coverage.unmapped_weight], ["已映射但不可完整比较的权重", personal.coverage.mapped_not_fully_comparable_weight]].map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}%</strong></div>)}</div>
      <p>同维度多项指标只计一次权重，覆盖部分不会放大到 100%；零权重不删除原始证据。完整可比较指标不代表覆盖该维度全部性能。</p>
      {personal.dimensions.map(row => <article className="test-candidate-metric-result" key={row.dimension}><h5>{dimensionLabel(row.dimension)} · {row.weight}%</h5><p>本次映射：{row.metric_keys.map(key => metricNames.get(key) || key).join("、") || "无"}</p><p>完整可比较指标：{row.complete_comparable_metric_keys.map(key => metricNames.get(key) || key).join("、") || "无"}</p></article>)}
      {personal.metrics.map(row => <article className="test-candidate-metric-result" key={row.metric_key}><h5>{metricNames.get(row.metric_key) || row.metric_key} · {dimensionLabel(row.dimension)}</h5><p>已录观察：{names(row.observed_participant_ids)}；缺失：{names(row.missing_participant_ids)}。</p>{row.limitations.map(limit => <p className="review-boundary" key={limit}>{limitations[limit]}</p>)}{row.observation_comparison ? <p>本次已录观察中的有利数值对象（含并列）：{names(row.observation_comparison.favorable_participant_ids)}。仅是逐项数值观察，不是来源排名或最佳 SKU。</p> : <p>本项不产生个人数值倾向比较。</p>}</article>)}
    </> : <p className="review-boundary">本次未生成个人解释。请核对排除项、桥依据及本场材料后重新明确选择。</p>}</section>
    <section aria-label="本场原始来源与成绩"><h4>本场原始来源与成绩</h4><p>人工转录 · 未在线核验 · 来源身份为参测对象，不由商品名推断精确 SKU。</p>
      <dl className="test-candidate-meta"><div><dt>场次 / 机构</dt><dd>{source.event.title} / {source.event.organization}</dd></div><div><dt>来源关系</dt><dd>{relationshipLabels[source.event.relationship]}</dd></div><div><dt>发布日期 / 尺寸</dt><dd>{source.event.publication_date || "未披露"} / {source.event.tested_size}</dd></div><div><dt>车辆 / 路面</dt><dd>{source.event.vehicle || "未披露"} / {source.event.surface || "未披露"}</dd></div><div><dt>测试条件</dt><dd>{source.event.conditions}</dd></div><div><dt>录入范围</dt><dd>{source.event.coverage === "full_event" ? "声明录入整场" : "选录部分结果"}；来源总数 {source.event.reported_participants ?? "未知"} / 已录 {source.recorded_participant_count} / 本次 {source.selected_participant_count}</dd></div><div><dt>原始来源</dt><dd>{source.event.source_url}</dd></div><div><dt>留存依据</dt><dd>{source.event.rights_basis}</dd></div><div><dt>录入时间</dt><dd>{stamp(source.recorded_at)}；不是来源核验时间</dd></div></dl>
      {source.metrics.map(metric => <section className="test-candidate-source-metric" key={metric.key}><h5>{metric.label} · {metric.unit}</h5><p>{metric.protocol} · {directionLabels[metric.direction]}</p><div className="test-candidate-table-wrap" tabIndex={0} aria-label={`${metric.label}原始成绩，可横向滚动`}><table><thead><tr><th scope="col">来源参测对象</th><th scope="col">原始数值</th><th scope="col">来源名次</th><th scope="col">短证据与定位</th></tr></thead><tbody>{source.participants.map(person => {
        const measurement = source.measurements.find(row => row.participant_id === person.id && row.metric_key === metric.key);
        return <tr key={person.id}><th scope="row">{people.get(person.id)}</th><td data-raw-value={measurement?.raw_value}>{measurement ? `${measurement.raw_value} ${metric.unit}` : "未录入成绩，不补零"}</td><td>{measurement?.source_rank ?? "未记录"}</td><td>{measurement ? <details><summary>核对原始短证据</summary><p>{measurement.evidence_span}</p><p>定位：{measurement.evidence_locator}</p><p className="test-candidate-hash">证据 ID {measurement.evidence_id}<br />事件 {measurement.reference.event_id} · 修订 #{measurement.reference.revision}<br />参测对象 {measurement.reference.participant_id} · 指标 {measurement.reference.metric_key}</p></details> : "缺失，不生成伪证据"}</td></tr>;
      })}</tbody></table></div></section>)}
    </section>
    <section aria-label="本次解释限制">{result.reason_codes.length ? <p className="review-boundary">本次限制：{reasons(result.reason_codes)}</p> : null}{result.notices.map((notice, index) => <p className="review-boundary" key={index}>{notice}</p>)}</section>
  </div>;
}
