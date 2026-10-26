"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { DrivingPreferenceState, DrivingWeightKey, TestEventDetail, TestMeasurementReference, TestMetricDimension, TestPreferenceInterpretation as Interpretation, TestPreferenceInterpretationRequest, TestPreferenceLimitation } from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import { DrivingPreferences } from "./research";

const dimensions: [DrivingWeightKey, string][] = [["dry", "干地"], ["wet", "湿地"], ["quiet", "静音"], ["comfort", "舒适"], ["wear", "耐磨"], ["energy", "能耗"], ["appearance", "外观"]];
const dimensionLabel = (key: DrivingWeightKey | null) => key === null ? "不纳入本次解读" : dimensions.find(([value]) => value === key)![1];
const directionLabels = { lower: "来源声明较低较好", higher: "来源声明较高较好", unspecified: "来源未说明数值方向" };
const relationshipLabels = { independent: "独立测试（录入声明）", manufacturer_commissioned: "厂商委托（录入声明）", unknown: "关系未确认" };
const limitations: Record<TestPreferenceLimitation, string> = {
  excluded_by_user: "本次未纳入个人解读，保留原始证据。",
  missing_measurements: "所选对象存在未录入成绩；不补零，也不能判断缺失对象。",
  direction_unspecified: "来源没有声明数值方向，不能推导数值倾向。",
  insufficient_observations: "已录成绩不足两条，不能形成已录观察比较。",
};
const errors: Record<string, string> = {
  test_event_not_found: "这场记录已不可读取，请重新载入测试列表。",
  test_event_revoked: "这场记录已撤销，不能产生新的当前偏好解读。",
  test_event_changed: "测试记录的修订或内容已变化，请重新载入最新版后核对选择。",
  driving_preference_missing: "本人当前没有已保存偏好，请在下方设置后重新发起。",
  driving_preference_changed: "上次计算所用的本人偏好已变化，请核对重新载入的偏好后发起新的解读。",
  invalid_preference_interpretation: "本次参测选择或逐项映射不完整，请重新核对本场全部指标。",
};
const errorText = (cause: unknown) => cause instanceof ApiError && cause.code && errors[cause.code]
  ? errors[cause.code] : cause instanceof Error ? cause.message : "本次解读未完成，请重新核对依据后重试。";
const sourceLink = (value: string) => { try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) ? url.href : undefined; } catch { return undefined; } };

type Props = { event: TestEventDetail; participantIds: string[]; onReload: () => void; onHistory: (revision: number, reference?: TestMeasurementReference) => void; onClose: () => void };

export default function TestPreferenceInterpretation(props: Props) {
  const auth = useWorkbenchAuth();
  if (!auth.ready) return <section className="test-preference-panel"><p role="status">正在重新确认账户归属，已清空本次个人解读。</p><button type="button" className="text-button" onClick={() => void auth.refresh()}>重新确认账户</button></section>;
  // A new identity, event revision or participant set cannot inherit private
  // drafts, completed results, or requests from the previous calculation.
  const key = JSON.stringify([auth.ownerEpoch, props.event.id, props.event.revision, props.event.fingerprint, [...props.participantIds].sort()]);
  return <InterpretationPanel key={key} {...props} ownerEpoch={auth.ownerEpoch} />;
}

function InterpretationPanel({ event, participantIds, ownerEpoch, onReload, onHistory, onClose }: Props & { ownerEpoch: number }) {
  const auth = useWorkbenchAuth();
  const titleId = useId();
  const [mapping, setMapping] = useState<TestMetricDimension[]>(() => event.event.metrics.map(metric => ({ metric_key: metric.key, dimension: null })));
  const [preference, setPreference] = useState<DrivingPreferenceState | null>(null);
  const [preferenceError, setPreferenceError] = useState("");
  const [preferenceReload, setPreferenceReload] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [verified, setVerified] = useState(false);
  const [basisError, setBasisError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Interpretation | null>(null);
  const operation = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const invalidate = useCallback(() => {
    operation.current?.abort(); generation.current++;
    setResult(null); setBusy(false);
  }, []);
  const preferenceChanged = useCallback((value: DrivingPreferenceState | null) => { invalidate(); setPreferenceError(""); setPreference(value); }, [invalidate]);

  useEffect(() => {
    const controller = new AbortController();
    // Reopening or returning from an identity/connection recheck verifies that
    // the parent detail is still the active latest immutable event snapshot.
    void tireApi.testEvent(event.id, controller.signal).then(latest => {
      if (controller.signal.aborted || !auth.isCurrentOwner(ownerEpoch)) return;
      if (latest.state !== "active" || latest.revision !== event.revision || latest.fingerprint !== event.fingerprint) {
        setBasisError(latest.state !== "active" ? errors.test_event_revoked : errors.test_event_changed);
      } else setVerified(true);
    }).catch(cause => { if (!controller.signal.aborted && auth.isCurrentOwner(ownerEpoch)) setBasisError(errorText(cause)); });
    return () => { controller.abort(); operation.current?.abort(); generation.current++; };
  }, [event.id, event.revision, event.fingerprint, ownerEpoch, auth.isCurrentOwner]);

  async function interpret() {
    if (!verified || !preference?.weights || participantIds.length < 2 || busy || !auth.isCurrentOwner(ownerEpoch)) return;
    invalidate(); setError("");
    const controller = new AbortController(); operation.current = controller;
    const epoch = generation.current;
    const payload: TestPreferenceInterpretationRequest = {
      expected_event_revision: event.revision, expected_event_fingerprint: event.fingerprint,
      expected_preference_revision: preference.revision, expected_preference_fingerprint: preference.fingerprint,
      participant_ids: [...participantIds], metric_dimensions: mapping.map(item => ({ ...item })),
    };
    const current = () => !controller.signal.aborted && generation.current === epoch && auth.isCurrentOwner(ownerEpoch);
    setBusy(true);
    try {
      const value = await tireApi.interpretTestEventPreferences(event.id, payload, controller.signal);
      if (!current()) return;
      if (value.schema !== "test-preference-interpretation@1" || value.binding?.event.id !== event.id
        || value.binding.event.revision !== payload.expected_event_revision || value.binding.event.fingerprint !== payload.expected_event_fingerprint
        || value.binding.preference.revision !== payload.expected_preference_revision || value.binding.preference.fingerprint !== payload.expected_preference_fingerprint) {
        throw new Error("解读结果与本次核对的事件或偏好不一致，请重新载入依据。");
      }
      setResult(value);
    } catch (cause) {
      if (!current()) return;
      setError(errorText(cause));
      if (cause instanceof ApiError && ["test_event_changed", "test_event_revoked", "test_event_not_found"].includes(cause.code || "")) {
        setVerified(false); setBasisError(errorText(cause));
      }
      if (cause instanceof ApiError && ["driving_preference_changed", "driving_preference_missing"].includes(cause.code || "")) {
        setPreference(null); setPreferenceReload(value => value + 1); setSettingsOpen(true);
      }
    } finally { if (current()) setBusy(false); }
  }

  return <section className="test-preference-panel" aria-labelledby={titleId}>
    <div className="panel-title"><h3 id={titleId}>按我的偏好解读本场</h3><button type="button" className="text-button" onClick={onClose}>关闭偏好解读</button></div>
    <p>你为指标选择的维度仅用于本次个人解读；原始数值、单位及来源名次保持原样。本功能不生成综合分、总榜或车辆适配推荐。</p>
    <p role="status" aria-live="polite">{busy ? "正在按已核对的本场记录和本人偏好计算…" : !verified && !basisError ? "正在重核本场最新修订…" : preferenceError ? "本人偏好尚未确认，本次不能计算。" : !preference ? "正在读取本人偏好；结果已清空。" : !preference.weights ? "尚未设置本人偏好，请展开下方设置；不会自动填入或保存默认权重。" : `已读取本人偏好修订 #${preference.revision}。${mapping.every(item => item.dimension === null) ? "全部指标当前均不纳入，仍可明确发起覆盖为 0 的解读。" : "映射调整后需要重新发起解读。"}`}</p>
    {basisError ? <div className="inline-error" role="alert"><p>{basisError}</p><button type="button" className="secondary-button" onClick={onReload}>重新载入场次最新版</button></div> : null}
    {preferenceError ? <p className="inline-error" role="alert">本人偏好读取或保存未完成：{preferenceError} 请展开设置并重新载入。</p> : null}
    {preference?.weights ? <p className="test-preference-weights">{dimensions.map(([key, label]) => <span key={key}>{label} {preference.weights![key]}%</span>)}</p> : null}
    {!preference?.weights ? <button type="button" className="text-button" onClick={() => setSettingsOpen(true)}>在本场设置驾驶偏好</button> : null}
    <details className="test-preference-settings" open={settingsOpen} onToggle={e => setSettingsOpen(e.currentTarget.open)}><summary>设置或修改本人的驾驶偏好</summary><DrivingPreferences key={preferenceReload} sessionReady={auth.ready} onChanged={preferenceChanged} onError={setPreferenceError} /></details>
    <form onSubmit={e => { e.preventDefault(); void interpret(); }}>
      <fieldset className="test-preference-mapping"><legend>逐项指定本次个人维度</legend><p>所有本场指标均列在下方；默认不纳入。分类由你本次明确选择，不是测试机构结论。</p>
        {event.event.metrics.map((metric, index) => <label className="test-preference-metric" key={metric.key}><span><strong>{metric.label}</strong><small>{metric.unit} · {directionLabels[metric.direction]}</small><small>{metric.protocol}</small></span><select aria-label={`${metric.label}的个人偏好维度`} value={mapping[index].dimension ?? ""} onChange={e => { invalidate(); setError(""); const dimension = e.target.value ? e.target.value as DrivingWeightKey : null; setMapping(previous => previous.map((item, at) => at === index ? { ...item, dimension } : item)); }}><option value="">不纳入本次解读</option>{dimensions.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>)}
      </fieldset>
      <div className="test-event-actions"><button type="submit" className="primary-button" disabled={busy || !verified || !preference?.weights || participantIds.length < 2}>按已选映射解读本场</button>{busy ? <button type="button" className="text-button" onClick={invalidate}>取消本次计算</button> : null}<span>已选 {participantIds.length} 个参测对象；至少选择 2 个。</span></div>
    </form>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {result ? <InterpretationResult result={result} onHistory={onHistory} /> : null}
  </section>;
}

function InterpretationResult({ result, onHistory }: { result: Interpretation; onHistory: Props["onHistory"] }) {
  const { source_evidence: source, personal_interpretation: personal } = result;
  const people = new Map(source.participants.map(person => [person.id, `${person.brand} ${person.model}${person.source_designation ? ` · ${person.source_designation}` : ""}`]));
  const metricLabels = new Map(source.metrics.map(metric => [metric.key, metric.label]));
  const measurements = new Map(source.measurements.map(item => [`${item.metric_key}:${item.participant_id}`, item]));
  const names = (ids: string[]) => ids.map(id => people.get(id) || id).join("、") || "无";
  const href = sourceLink(source.event.source_url);
  return <div className="test-preference-result" aria-live="polite">
    <section aria-label="本次个人解读"><h4>本次个人解读</h4><p>本人的权重 · 修订 #{result.binding.preference.revision}；分类来自本次明确映射。解释绑定测试修订 #{result.binding.event.revision}，不是响应到达时仍为最新的保证。</p>
      <dl className="test-preference-coverage"><div><dt>已映射权重</dt><dd>{personal.coverage.mapped_weight}%</dd></div><div><dt>具有完整可比较指标的权重</dt><dd>{personal.coverage.fully_comparable_weight}%</dd></div><div><dt>未映射权重</dt><dd>{personal.coverage.unmapped_weight}%</dd></div><div><dt>已映射但不可完整比较的权重</dt><dd>{personal.coverage.mapped_not_fully_comparable_weight}%</dd></div></dl>
      <p>同维度多项指标只计一次权重；覆盖部分不重新放大到 100%。有一项完整可比较指标，不表示该维度的全部性能均已覆盖。零权重不会删除证据。</p>
      {personal.dimensions.map(dimension => <section className="test-preference-dimension" key={dimension.dimension}><h5>{dimensionLabel(dimension.dimension)} · {dimension.weight}%</h5><p>本次映射：{dimension.metric_keys.map(key => metricLabels.get(key) || key).join("、") || "未映射任何指标"}</p><p>完整可比较指标：{dimension.complete_comparable_metric_keys.map(key => metricLabels.get(key) || key).join("、") || "无"}</p></section>)}
      {personal.metrics.map(metric => <section className="test-preference-metric-result" key={metric.metric_key}><h5>{metricLabels.get(metric.metric_key)} · {dimensionLabel(metric.dimension)}</h5><p>已录成绩：{names(metric.observed_participant_ids)}；缺失：{names(metric.missing_participant_ids)}。</p>{metric.limitations.map(limit => <p className="review-boundary" key={limit}>{limitations[limit]}</p>)}{metric.observation_comparison ? <p>所选已录观察中的有利数值对象（含并列）：{names(metric.observation_comparison.favorable_participant_ids)}。仅适用于所选已录成绩，不是来源排名或全场胜者。</p> : <p>本项不产生个人数值倾向比较。</p>}</section>)}
    </section>
    <section aria-label="原始测试证据"><h4>原始测试证据</h4><p>人工转录 · 未在线核验 · 仅为本场参测对象，不自动关联精确 SKU 或证明车型适配。</p>
      <dl className="quality-detail-meta"><div><dt>机构 / 关系</dt><dd>{source.event.organization} · {relationshipLabels[source.event.relationship]}</dd></div><div><dt>发布日期 / 尺寸</dt><dd>{source.event.publication_date || "未披露"} · {source.event.tested_size}</dd></div><div><dt>车辆 / 路面</dt><dd>{source.event.vehicle || "未披露"} / {source.event.surface || "未披露"}</dd></div><div><dt>条件</dt><dd>{source.event.conditions}</dd></div><div><dt>录入范围</dt><dd>{source.event.coverage === "full_event" ? "本场全部参测对象" : "选录部分结果"}；来源总数 {source.event.reported_participants ?? "未知"} / 已录 {source.recorded_participant_count} / 本次选择 {source.selected_participant_count}</dd></div><div><dt>原始来源</dt><dd>{href ? <a href={href} target="_blank" rel="noopener noreferrer">{source.event.source_url}</a> : source.event.source_url}</dd></div><div><dt>留存依据</dt><dd>{source.event.rights_basis}</dd></div><div><dt>录入时间</dt><dd>{new Date(source.recorded_at).toLocaleString("zh-CN")}；不是来源核验时间</dd></div></dl>
      {source.metrics.map(metric => <section className="test-preference-source-metric" key={metric.key}><h5>{metric.label} · {metric.unit}</h5><p>{metric.protocol} · {directionLabels[metric.direction]}</p><div className="comparison-table-wrap" tabIndex={0} aria-label={`${metric.label}原始证据，可横向滚动`}><table className="comparison-table"><thead><tr><th scope="col">参测对象</th><th scope="col">原始数值</th><th scope="col">来源名次</th><th scope="col">证据与历史修订</th></tr></thead><tbody>{source.participants.map(person => {
        const item = measurements.get(`${metric.key}:${person.id}`);
        return <tr key={person.id}><th scope="row">{people.get(person.id)}</th><td>{item ? `${item.raw_value} ${metric.unit}` : "未录入成绩"}</td><td>{item?.source_rank ?? "未记录"}</td><td>{item ? <details><summary>核对原始短证据</summary><p>{item.evidence_span}</p><p>定位：{item.evidence_locator}</p><p className="test-preference-evidence-id">证据 ID：{item.evidence_id}</p><button type="button" className="text-button" onClick={() => onHistory(item.reference.revision, item.reference)}>打开绑定历史修订 #{item.reference.revision}</button></details> : "缺失，不补零或生成伪证据"}</td></tr>;
      })}</tbody></table></div></section>)}
      <button type="button" className="text-button" onClick={() => onHistory(result.binding.event.revision)}>核对本次绑定的历史修订 #{result.binding.event.revision}</button>
    </section>
    <section aria-label="本次解读的范围与限制">{result.notices.map((notice, index) => <p className="review-boundary" key={index}>{notice}</p>)}</section>
  </div>;
}
