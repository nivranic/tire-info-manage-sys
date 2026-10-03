"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { TestEventDetail, TestEventPayload, TestMeasurement } from "@tire/domain-types";

const empty = (): TestEventPayload => ({ title: "", organization: "", relationship: "unknown", publication_date: null,
  source_url: "", rights_basis: "", tested_size: "", vehicle: null, surface: null, conditions: "",
  coverage: "selected_results", reported_participants: null,
  participants: [{ key: "p1", brand: "", model: "", source_designation: "" }],
  metrics: [{ key: "m1", label: "", unit: "", protocol: "", direction: "unspecified" }], measurements: [] });
const blankMeasurement = (participant: string, metric: string): TestMeasurement => ({ participant_key: participant,
  metric_key: metric, raw_value: "", source_rank: null, evidence_span: "", evidence_locator: "" });
const newKey = (prefix: string) => prefix + crypto.randomUUID().replaceAll("-", "");

export default function TestEventEditor({ initial, onSaved, onClose }: {
  initial?: TestEventDetail; onSaved: (row: TestEventDetail) => void; onClose: () => void;
}) {
  const [draft, setDraft] = useState<TestEventPayload>(() => initial ? structuredClone(initial.event) : empty());
  const [operator, setOperator] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  function field<K extends keyof TestEventPayload>(key: K, value: TestEventPayload[K]) {
    setDraft(previous => ({ ...previous, [key]: value }));
  }
  function measurement(participant: string, metric: string, patch: Partial<TestMeasurement>) {
    setDraft(previous => {
      const found = previous.measurements.find(row => row.participant_key === participant && row.metric_key === metric);
      const next = { ...(found || blankMeasurement(participant, metric)), ...patch };
      return { ...previous, measurements: [...previous.measurements.filter(row => row !== found), next] };
    });
  }
  async function save() {
    if (busy) return;
    const request = new AbortController(); controller.current = request; setBusy(true); setError("");
    try {
      const result = await tireApi.saveTestEvent({ event: { ...draft, measurements: draft.measurements.filter(row => row.raw_value.trim() !== "") }, operator, reason }, initial?.id, initial?.revision, request.signal);
      if (!request.signal.aborted) onSaved(result);
    } catch (cause) { if (!request.signal.aborted) setError(cause instanceof Error ? cause.message : "保存未完成，请重试。"); }
    finally { if (!request.signal.aborted) setBusy(false); }
  }
  return <section className="test-event-editor" aria-label={initial ? "修订测试事件" : "录入测试事件"}>
    <div className="panel-title"><h3>{initial ? `修订测试事件 · 基于 #${initial.revision}` : "录入一场测试"}</h3><button type="button" className="text-button" disabled={busy} onClick={onClose}>取消编辑</button></div>
    <p className="review-boundary">仅保存你有权留存的数值事实、测试元信息和短摘录。此处是人工录入，未经在线核验；不要粘贴全文或图片。精确 SKU 未知时保留为参测胎，不猜测关联。</p>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    <form className="review-form" onSubmit={event => { event.preventDefault(); void save(); }}>
      <fieldset disabled={busy} className="test-event-fields"><legend>来源与测试条件</legend>
        <label><span>测试标题</span><input required maxLength={200} value={draft.title} onChange={e => field("title", e.target.value)} /></label>
        <label><span>发布机构</span><input required maxLength={160} value={draft.organization} onChange={e => field("organization", e.target.value)} /></label>
        <label><span>测试关系（以原文声明为准）</span><select value={draft.relationship} onChange={e => field("relationship", e.target.value as TestEventPayload["relationship"])}><option value="unknown">关系未确认</option><option value="independent">独立测试</option><option value="manufacturer_commissioned">厂商委托测试</option></select></label>
        <label><span>发布日期（未知可留空）</span><input type="date" value={draft.publication_date || ""} onChange={e => field("publication_date", e.target.value || null)} /></label>
        <label><span>来源 HTTPS 链接（不自动访问）</span><input type="url" required maxLength={2048} value={draft.source_url} onChange={e => field("source_url", e.target.value)} /></label>
        <label><span>保存授权或使用依据</span><textarea required minLength={5} maxLength={1000} value={draft.rights_basis} onChange={e => field("rights_basis", e.target.value)} /></label>
        <label><span>本场测试尺寸</span><input required maxLength={24} placeholder="如 225/50R17" value={draft.tested_size} onChange={e => field("tested_size", e.target.value)} /></label>
        <label><span>测试车辆（未知可留空）</span><input maxLength={200} value={draft.vehicle || ""} onChange={e => field("vehicle", e.target.value || null)} /></label>
        <label><span>路面（未知可留空）</span><input maxLength={200} value={draft.surface || ""} onChange={e => field("surface", e.target.value || null)} /></label>
        <label><span>条件与适用范围</span><textarea required minLength={3} maxLength={2000} placeholder="记录速度、温度、方法及限制；未披露的信息明确写未知" value={draft.conditions} onChange={e => field("conditions", e.target.value)} /></label>
        <label><span>来源参测总数（未知可留空）</span><input type="number" min={1} max={10000} value={draft.reported_participants ?? ""} onChange={e => field("reported_participants", e.target.value ? Number(e.target.value) : null)} /></label>
        <label><span>当前录入范围</span><select value={draft.coverage} onChange={e => field("coverage", e.target.value as TestEventPayload["coverage"])}><option value="selected_results">选录部分结果</option><option value="full_event">已录入本场全部参测胎</option></select></label>
      </fieldset>
      <fieldset disabled={busy} className="test-event-fields"><legend>参测胎（最多 60 项）</legend>
        {draft.participants.map((person, index) => <div className="test-entry" key={person.key}><h4>参测胎 {index + 1}</h4>
          <label><span>品牌</span><input required maxLength={120} value={person.brand} onChange={e => field("participants", draft.participants.map(p => p.key === person.key ? { ...p, brand: e.target.value } : p))} /></label>
          <label><span>型号</span><input required maxLength={200} value={person.model} onChange={e => field("participants", draft.participants.map(p => p.key === person.key ? { ...p, model: e.target.value } : p))} /></label>
          <label><span>原文规格/版本描述（可留空）</span><input maxLength={300} value={person.source_designation} onChange={e => field("participants", draft.participants.map(p => p.key === person.key ? { ...p, source_designation: e.target.value } : p))} /></label>
          <button type="button" className="text-button" disabled={draft.participants.length < 2} onClick={() => setDraft(previous => ({ ...previous, participants: previous.participants.filter(p => p.key !== person.key), measurements: previous.measurements.filter(m => m.participant_key !== person.key) }))}>移除此参测胎</button>
        </div>)}
        <button type="button" className="secondary-button" disabled={draft.participants.length >= 60} onClick={() => field("participants", [...draft.participants, { key: newKey("p"), brand: "", model: "", source_designation: "" }])}>添加参测胎</button>
      </fieldset>
      <fieldset disabled={busy} className="test-event-fields"><legend>同条件指标与成绩（最多 24 项指标）</legend>
        {draft.metrics.map((metric, index) => <div className="test-entry" key={metric.key}><h4>指标 {index + 1}</h4>
          <label><span>指标名称</span><input required maxLength={120} value={metric.label} onChange={e => field("metrics", draft.metrics.map(m => m.key === metric.key ? { ...m, label: e.target.value } : m))} /></label>
          <label><span>原始单位</span><input required maxLength={40} placeholder="m、dB、秒或评分单位" value={metric.unit} onChange={e => field("metrics", draft.metrics.map(m => m.key === metric.key ? { ...m, unit: e.target.value } : m))} /></label>
          <label><span>本指标方法/条件</span><textarea required minLength={3} maxLength={1000} value={metric.protocol} onChange={e => field("metrics", draft.metrics.map(m => m.key === metric.key ? { ...m, protocol: e.target.value } : m))} /></label>
          <label><span>原文对数值方向的说明</span><select value={metric.direction} onChange={e => field("metrics", draft.metrics.map(m => m.key === metric.key ? { ...m, direction: e.target.value as typeof m.direction } : m))}><option value="unspecified">未说明</option><option value="lower">较低较好</option><option value="higher">较高较好</option></select></label>
          {draft.participants.map(person => {
            const value = draft.measurements.find(row => row.participant_key === person.key && row.metric_key === metric.key) || blankMeasurement(person.key, metric.key);
            return <div className="test-measurement-input" key={person.key}><h5>{person.brand} {person.model || "尚未填写的参测胎"}</h5>
              <label><span>原始数值（缺少成绩请留空）</span><input inputMode="decimal" pattern="-?[0-9]+(\.[0-9]+)?" maxLength={22} value={value.raw_value} onChange={e => measurement(person.key, metric.key, { raw_value: e.target.value })} /></label>
              <label><span>来源名次（未知或未录入请留空）</span><input type="number" min={1} max={10000} value={value.source_rank ?? ""} onChange={e => measurement(person.key, metric.key, { source_rank: e.target.value ? Number(e.target.value) : null })} /></label>
              <label><span>证据短摘录（最多 300 字）</span><textarea required={!!value.raw_value} maxLength={300} value={value.evidence_span} onChange={e => measurement(person.key, metric.key, { evidence_span: e.target.value })} /></label>
              <label><span>原文定位（章节、表格或页码）</span><input required={!!value.raw_value} maxLength={300} value={value.evidence_locator} onChange={e => measurement(person.key, metric.key, { evidence_locator: e.target.value })} /></label>
            </div>;
          })}
          <button type="button" className="text-button" disabled={draft.metrics.length < 2} onClick={() => setDraft(previous => ({ ...previous, metrics: previous.metrics.filter(m => m.key !== metric.key), measurements: previous.measurements.filter(m => m.metric_key !== metric.key) }))}>移除此指标</button>
        </div>)}
        <button type="button" className="secondary-button" disabled={draft.metrics.length >= 24} onClick={() => field("metrics", [...draft.metrics, { key: newKey("m"), label: "", unit: "", protocol: "", direction: "unspecified" }])}>添加指标</button>
      </fieldset>
      <label><span>录入/修订署名</span><input required maxLength={80} disabled={busy} value={operator} onChange={e => setOperator(e.target.value)} /></label>
      <label><span>本次记录依据</span><textarea required minLength={5} maxLength={2000} disabled={busy} value={reason} onChange={e => setReason(e.target.value)} /></label>
      <button type="submit" className="primary-button" disabled={busy}>{busy ? "正在保存…" : initial ? "追加修订，保留旧版" : "保存人工测试记录"}</button>
    </form>
  </section>;
}
