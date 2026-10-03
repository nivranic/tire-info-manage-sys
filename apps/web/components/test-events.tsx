"use client";

import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { TestEventComparison, TestEventDetail, TestEventRecord } from "@tire/domain-types";
import TestEventEditor from "./test-event-editor";
import AIAnalysisDialog from "./ai-analysis";

const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "测试记录操作未完成。";
const relations = { independent: "独立测试（录入声明）", manufacturer_commissioned: "厂商委托测试（录入声明）", unknown: "测试关系未确认" };
const stamp = (value: string) => new Date(value).toLocaleString("zh-CN");

function EventDetail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const [row, setRow] = useState<TestEventDetail | null>(null);
  const [revision, setRevision] = useState(0);
  const [historyRevision, setHistoryRevision] = useState<number | undefined>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<TestEventComparison | null>(null);
  const [operator, setOperator] = useState("");
  const [reason, setReason] = useState("");
  const operation = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController(); setRow(null); setError(""); setComparison(null); setEditing(false);
    void tireApi.testEvent(id, controller.signal, historyRevision).then(result => {
      if (!controller.signal.aborted) { setRow(result); setSelected(result.participants.slice(0, 6).map(p => p.id)); }
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [id, revision, historyRevision]);
  async function compare() {
    if (!row || busy || !selected.length) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError(""); setComparison(null);
    try { const value = await tireApi.compareTestEvent(id, { expected_revision: row.revision, participant_ids: selected, metric_keys: row.event.metrics.map(m => m.key) }, controller.signal); if (!controller.signal.aborted) setComparison(value); }
    catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  async function changeState() {
    if (!row || busy) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError(""); setComparison(null);
    try { const value = await tireApi.testEventState(id, { action: row.state === "revoked" ? "restore" : "revoke", expected_revision: row.revision, operator, reason }, controller.signal); if (!controller.signal.aborted) { setRow(value); setReason(""); onChanged(); } }
    catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  function changed(value: TestEventDetail) { setRow(value); setEditing(false); setComparison(null); setSelected(value.participants.slice(0, 6).map(p => p.id)); onChanged(); }
  return <section className="test-event-detail" aria-label="测试事件详情">
    <div className="panel-title"><h3>场次详情</h3><button type="button" className="text-button" disabled={busy} onClick={() => { setHistoryRevision(undefined); setRevision(v => v + 1); }}>重新载入最新版</button></div>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {!row ? !error ? <p role="status">正在读取测试记录…</p> : null : editing ? <TestEventEditor initial={row} onSaved={changed} onClose={() => setEditing(false)} /> : <>
      <h4>{row.title}</h4>{!historyRevision && row.state !== "revoked" ? <button type="button" className="secondary-button" disabled={busy} onClick={() => setAiOpen(true)}>AI 解释本场测试证据</button> : null}{aiOpen ? <AIAnalysisDialog target={{ references: [{ kind: "test_event", event_id: row.id, event_revision: row.revision }], label: row.title + " · 人工记录，仅限本场" }} onClose={() => setAiOpen(false)} /> : null}<div className="snapshot-banner"><strong>LOCAL SNAPSHOT · 人工录入，未在线核验 · {row.state === "revoked" ? "已撤销" : "未撤销"}</strong><span>修订 #{row.revision} · {stamp(row.recorded_at)}；录入时间不是来源验证时间。</span></div>
      <dl className="quality-detail-meta"><div><dt>机构 / 关系</dt><dd>{row.organization} · {relations[row.relationship]}</dd></div><div><dt>发布日期 / 尺寸</dt><dd>{row.publication_date || "未知"} · {row.tested_size}</dd></div><div><dt>车辆 / 路面</dt><dd>{row.event.vehicle || "未披露"} / {row.event.surface || "未披露"}</dd></div><div><dt>条件与适用范围</dt><dd>{row.event.conditions}</dd></div><div><dt>录入范围</dt><dd>{row.coverage === "full_event" ? "本场全部参测胎" : "选录部分结果"} · 已录 {row.participant_count} / 来源总数 {row.event.reported_participants ?? "未知"}</dd></div><div><dt>原始来源</dt><dd><a href={row.event.source_url} target="_blank" rel="noopener noreferrer">{row.event.source_url}</a></dd></div><div><dt>留存依据</dt><dd>{row.event.rights_basis}</dd></div></dl>
      {historyRevision ? <p className="review-boundary">正在查看历史修订；恢复最新版后才可比较或管理。</p> : <>
        <p className="quality-intro">选择本场参测胎进行对照。来源名次保持原值，选录子集不重新排名；未披露的成绩显示缺失，不补零。不关联未确认的精确 SKU，也不修改厂商参数。</p>
        <div className="test-participant-selection">{row.participants.map(person => <label className="review-checkbox" key={person.id}><input type="checkbox" disabled={busy || row.state === "revoked"} checked={selected.includes(person.id)} onChange={() => { setComparison(null); setSelected(previous => previous.includes(person.id) ? previous.filter(value => value !== person.id) : [...previous, person.id]); }} /><span>{person.brand} {person.model}{person.source_designation ? ` · ${person.source_designation}` : ""}</span></label>)}</div>
        <div className="test-event-actions"><button type="button" className="primary-button" disabled={busy || !selected.length || row.state === "revoked"} onClick={() => void compare()}>只比较本场成绩</button><button type="button" className="secondary-button" disabled={busy || row.state === "revoked"} onClick={() => setEditing(true)}>修订这场记录</button></div>
      </>}
      {comparison ? <div className="test-event-comparison"><p className="review-boundary">{comparison.notice}</p>{comparison.metrics.map(metric => <section key={metric.key}><h4>{metric.label} · {metric.unit}</h4><p>{metric.protocol} · 数值方向：{{ lower: "原文说明较低较好", higher: "原文说明较高较好", unspecified: "未说明" }[metric.direction]}</p><div className="comparison-table-wrap" tabIndex={0} aria-label={`${metric.label}同场成绩，可横向滚动`}><table className="comparison-table"><thead><tr><th>参测胎</th><th>原始数值</th><th>来源名次</th><th>短证据</th></tr></thead><tbody>{comparison.participants.map(person => { const value = comparison.measurements.find(m => m.participant_key === person.key && m.metric_key === metric.key); return <tr key={person.id}><th scope="row">{person.brand} {person.model}</th><td>{value ? `${value.raw_value} ${metric.unit}` : "未录入成绩"}</td><td>{value?.source_rank ?? "未记录"}</td><td>{value ? <details><summary>核对摘录</summary><p>{value.evidence_span}</p><p>定位：{value.evidence_locator}</p></details> : "—"}</td></tr>; })}</tbody></table></div></section>)}</div> : null}
      <details className="quality-technical"><summary>本修订的全部原始数值与短证据</summary>{row.event.measurements.map(value => <article key={`${value.metric_key}:${value.participant_key}`}><p>{row.event.participants.find(p => p.key === value.participant_key)?.model} · {row.event.metrics.find(m => m.key === value.metric_key)?.label}：{value.raw_value} {row.event.metrics.find(m => m.key === value.metric_key)?.unit} · 来源名次 {value.source_rank ?? "未记录"}</p><p>{value.evidence_span}</p><p>定位：{value.evidence_locator}</p></article>)}</details>
      <details className="quality-technical"><summary>修订历史（{row.history.length}{row.history_truncated ? "+" : ""} 条）</summary>{row.history.map(item => <article key={item.id}><p>#{item.revision} · {{ create: "创建", revise: "修订", revoke: "撤销", restore: "恢复" }[item.action] || item.action} · {item.operator} · {stamp(item.recorded_at)}</p><p>{item.reason}</p><button type="button" className="text-button" disabled={busy} onClick={() => setHistoryRevision(item.revision)}>查看修订 #{item.revision}</button></article>)}</details>
      {!historyRevision ? <details className="quality-technical"><summary>{row.state === "revoked" ? "恢复这场记录" : "撤销这场记录"}</summary><form className="review-form" onSubmit={event => { event.preventDefault(); void changeState(); }}><label><span>管理署名</span><input required maxLength={80} value={operator} disabled={busy} onChange={e => setOperator(e.target.value)} /></label><label><span>管理原因</span><textarea required minLength={5} maxLength={2000} value={reason} disabled={busy} onChange={e => setReason(e.target.value)} /></label><button type="submit" className="secondary-button" disabled={busy}>{row.state === "revoked" ? "恢复记录" : "撤销并排除比较"}</button></form></details> : null}
    </>}
  </section>;
}

export default function TestEvents({ sessionReady }: { sessionReady: boolean }) {
  const [rows, setRows] = useState<TestEventRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!sessionReady) return;
    const controller = new AbortController(); setLoading(true); setError("");
    void tireApi.testEvents(controller.signal, offset).then(result => { if (!controller.signal.aborted) { setRows(result.items); setTotal(result.total); } })
      .catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [sessionReady, offset, revision]);
  return <section className="test-events quarantine-panel" aria-label="独立测试与场次比较"><div className="panel-title"><span>测试事件 · 同场成绩</span><button type="button" className="text-button" disabled={!sessionReady || creating} onClick={() => { setCreating(true); setSelectedId(""); }}>录入一场测试</button></div>
    <p className="quality-intro">测试成绩属于具体场次、尺寸与条件。不同场次分开核对，不生成跨测试总榜；厂商委托与独立测试分别标记。此处保存本地人工记录，自动来源接入尚待完成。</p>
    {creating ? <TestEventEditor onClose={() => setCreating(false)} onSaved={row => { setCreating(false); setSelectedId(row.id); setOffset(0); setRevision(value => value + 1); }} /> : null}
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    <div className="test-event-actions"><button className="text-button" type="button" disabled={loading} onClick={() => setRevision(value => value + 1)}>刷新测试列表</button><span>{total} 场已保存记录</span></div>
    {loading ? <p className="quality-empty" role="status">正在读取测试场次…</p> : rows.length ? rows.map(row => <article className="quarantine-item" key={row.id}><h3>{row.title}</h3><p>{row.organization} · {row.tested_size} · {row.publication_date || "发布日期未知"}</p><p>{relations[row.relationship]} · {row.state === "revoked" ? "已撤销" : "未撤销"} · 人工记录未在线核验</p><button className="secondary-button" type="button" onClick={() => { setSelectedId(selectedId === row.id ? "" : row.id); setCreating(false); }}>{selectedId === row.id ? "关闭场次" : "核对本场成绩"}</button></article>) : <p className="quality-empty">尚无测试事件。缺少来源数据时不生成成绩或排名。</p>}
    {total > 50 ? <div className="test-event-actions"><button type="button" className="secondary-button" disabled={loading || offset === 0} onClick={() => setOffset(v => Math.max(0, v - 50))}>上一页</button><button type="button" className="secondary-button" disabled={loading || offset + 50 >= total} onClick={() => setOffset(v => v + 50)}>下一页</button></div> : null}
    {selectedId ? <EventDetail key={selectedId} id={selectedId} onChanged={() => setRevision(value => value + 1)} /> : null}
  </section>;
}
