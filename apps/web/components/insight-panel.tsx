"use client";
import { useEffect, useMemo, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { AIUsageHistory, Source, SourceHealthTrendDay, SourceHealthTrends } from "@tire/domain-types";
import { Icon } from "./icons";

const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "读取未完成，请重试。";
const WINDOWS = [7, 14, 30];

/** 运行洞察：来源成功率/解析拒绝的按天趋势与 AI 日用量（DB 聚合只读端点，纯手写 SVG，零新增依赖）。 */
export default function SourceInsight({ sources }: { sources: Source[] }) {
  const [days, setDays] = useState(14);
  const [trends, setTrends] = useState<SourceHealthTrends | null>(null);
  const [usage, setUsage] = useState<AIUsageHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const names = useMemo(() => new Map(sources.map(source => [source.id, source.name])), [sources]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    Promise.all([tireApi.sourceHealthTrends(days, controller.signal), tireApi.aiUsageHistory(days, controller.signal)])
      .then(([trendResult, usageResult]) => { if (!controller.signal.aborted) { setTrends(trendResult); setUsage(usageResult); } })
      .catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [days]);
  const withActivity = trends?.sources.filter(entry => entry.days.some(day => day.attempts || day.rejected)) || [];
  const [sourceId, setSourceId] = useState("");
  const selected = withActivity.find(entry => entry.source_id === sourceId) || withActivity[0];
  const totals = useMemo(() => {
    if (!selected) return null;
    return selected.days.reduce((acc, day) => ({ attempts: acc.attempts + day.attempts, successes: acc.successes + day.successes,
      failures: acc.failures + day.failures, rejected: acc.rejected + day.rejected }), { attempts: 0, successes: 0, failures: 0, rejected: 0 });
  }, [selected]);
  return <section className="insight-panel" aria-labelledby="insight-title">
    <div className="panel-title"><span id="insight-title"><Icon name="source" size={18} />运行洞察</span>
      <label className="result-sort">窗口<select value={days} disabled={loading} onChange={event => setDays(Number(event.target.value))}>{WINDOWS.map(value => <option key={value} value={value}>最近 {value} 天</option>)}</select></label></div>
    <p className="quality-intro">按 UTC 日聚合的只读统计，来自本机已记录的查询运行、解析拒绝与 AI 记账；重启不清零，但只反映已发生的本机活动，不代表来源当前可用性。</p>
    {error ? <div className="inline-error" role="alert">{error}</div> : null}
    {loading && !trends ? <p role="status" className="quality-empty">正在读取运行统计…</p> : null}
    {trends && !withActivity.length ? <p className="quality-empty">此窗口内没有查询运行记录。发起在线查询后，这里会出现各来源的成功率趋势。</p> : null}
    {trends && withActivity.length ? <div className="insight-grid">
      <div className="insight-block" aria-label="来源成功率趋势">
        <div className="insight-block-heading">
          <label>来源<select value={selected?.source_id || ""} onChange={event => setSourceId(event.target.value)}>{withActivity.map(entry => <option key={entry.source_id} value={entry.source_id}>{names.get(entry.source_id) || entry.source_id}</option>)}</select></label>
          {totals ? <span className="tag quiet">尝试 {totals.attempts} · 成功 {totals.successes} · 失败 {totals.failures} · 解析拒绝 {totals.rejected}</span> : null}
        </div>
        {selected ? <RateChart days={selected.days} /> : null}
        {selected ? <BarChart days={selected.days} pick="rejected" label="解析拒绝" /> : null}
      </div>
      <div className="insight-block" aria-label="AI 日用量">
        <div className="insight-block-heading"><strong>AI 日用量</strong>{usage ? <span className="tag quiet">{usage.days.reduce((sum, day) => sum + day.requests, 0)} 次请求 · {usage.days.reduce((sum, day) => sum + day.accounted_tokens, 0).toLocaleString("en-US")} tokens（窗口合计）</span> : null}</div>
        {usage ? <UsageChart usage={usage} /> : <p className="quality-empty">暂无用量记录。</p>}
        <p className="insight-note">计量口径与预算护栏一致：有 Provider usage 用实际值，否则按保守预留记账；不是账单金额。</p>
      </div>
    </div> : null}
  </section>;
}

function RateChart({ days }: { days: SourceHealthTrendDay[] }) {
  const width = 640, height = 140;
  const pad = { left: 36, right: 12, top: 10, bottom: 20 };
  const innerW = width - pad.left - pad.right, innerH = height - pad.top - pad.bottom;
  const points = days.map((day, index) => ({ ...day,
    x: pad.left + (days.length === 1 ? innerW / 2 : (index / (days.length - 1)) * innerW),
    rate: day.attempts ? day.successes / day.attempts : null }));
  const yOf = (rate: number) => pad.top + innerH * (1 - rate);
  const visible = points.filter(point => point.rate !== null);
  const polyline = visible.map(point => point.x.toFixed(1) + "," + yOf(point.rate as number).toFixed(1)).join(" ");
  const labelIndex = [0, Math.floor((days.length - 1) / 2), days.length - 1];
  return <svg className="insight-chart" viewBox={"0 0 " + width + " " + height} role="img" aria-label="各来源每日查询成功率趋势图">
    {[0, 0.5, 1].map(ratio => <g key={ratio}>
      <line x1={pad.left} x2={width - pad.right} y1={yOf(ratio)} y2={yOf(ratio)} className="chart-gridline" />
      <text x={pad.left - 6} y={yOf(ratio) + 3} textAnchor="end" className="chart-label">{Math.round(ratio * 100)}%</text>
    </g>)}
    {visible.length > 1 ? <polyline points={polyline} className="chart-line" /> : null}
    {visible.map(point => <circle key={point.date} cx={point.x} cy={yOf(point.rate as number)} r={3} className="chart-dot">
      <title>{point.date + " · 尝试 " + point.attempts + " · 成功 " + point.successes + " · 失败 " + point.failures + " · 成功率 " + Math.round((point.rate as number) * 100) + "%"}</title>
    </circle>)}
    {labelIndex.map(index => days[index] ? <text key={days[index].date} x={points[index].x} y={height - 6} textAnchor="middle" className="chart-label">{days[index].date.slice(5)}</text> : null)}
  </svg>;
}

function BarChart({ days, pick, label }: { days: SourceHealthTrendDay[]; pick: "rejected"; label: string }) {
  const width = 640, height = 90;
  const pad = { left: 36, right: 12, top: 8, bottom: 18 };
  const innerW = width - pad.left - pad.right, innerH = height - pad.top - pad.bottom;
  const max = Math.max(1, ...days.map(day => day[pick]));
  const step = days.length ? innerW / days.length : innerW;
  const yOf = (value: number) => pad.top + innerH * (1 - value / max);
  return <svg className="insight-chart" viewBox={"0 0 " + width + " " + height} role="img" aria-label={"每日" + label + "柱状图"}>
    <line x1={pad.left} x2={width - pad.right} y1={pad.top + innerH} y2={pad.top + innerH} className="chart-gridline" />
    <text x={pad.left - 6} y={pad.top + 10} textAnchor="end" className="chart-label">{max}</text>
    {days.map((day, index) => day[pick] ? <rect key={day.date} x={pad.left + index * step + step * 0.2} width={Math.max(1, step * 0.6)}
      y={yOf(day[pick])} height={pad.top + innerH - yOf(day[pick])} className="chart-bar-warn">
      <title>{day.date + " · " + label + " " + day[pick]}</title>
    </rect> : null)}
    <text x={pad.left + innerW} y={height - 4} textAnchor="end" className="chart-label">{days[days.length - 1]?.date.slice(5) || ""}</text>
    <text x={pad.left} y={height - 4} className="chart-label">{days[0]?.date.slice(5) || ""}</text>
  </svg>;
}

function UsageChart({ usage }: { usage: AIUsageHistory }) {
  const width = 640, height = 110;
  const pad = { left: 52, right: 12, top: 8, bottom: 18 };
  const innerW = width - pad.left - pad.right, innerH = height - pad.top - pad.bottom;
  const days = usage.days;
  const max = Math.max(1, ...days.map(day => day.accounted_tokens));
  const step = days.length ? innerW / days.length : innerW;
  const yOf = (value: number) => pad.top + innerH * (1 - value / max);
  const compact = (value: number) => value >= 1000 ? (value / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(value);
  return <svg className="insight-chart" viewBox={"0 0 " + width + " " + height} role="img" aria-label="AI 每日记账 token 柱状图">
    <line x1={pad.left} x2={width - pad.right} y1={pad.top + innerH} y2={pad.top + innerH} className="chart-gridline" />
    <line x1={pad.left} x2={width - pad.right} y1={yOf(max)} y2={yOf(max)} className="chart-gridline" />
    <text x={pad.left - 6} y={yOf(max) + 3} textAnchor="end" className="chart-label">{compact(max)}</text>
    <text x={pad.left - 6} y={pad.top + innerH + 3} textAnchor="end" className="chart-label">0</text>
    {days.map((day, index) => day.accounted_tokens ? <rect key={day.date} x={pad.left + index * step + step * 0.2} width={Math.max(1, step * 0.6)}
      y={yOf(day.accounted_tokens)} height={pad.top + innerH - yOf(day.accounted_tokens)} className="chart-bar">
      <title>{day.date + " · " + day.requests + " 次请求 · " + day.accounted_tokens.toLocaleString("en-US") + " tokens"}</title>
    </rect> : null)}
    <text x={pad.left} y={height - 4} className="chart-label">{days[0]?.date.slice(5) || ""}</text>
    <text x={pad.left + innerW} y={height - 4} textAnchor="end" className="chart-label">{days[days.length - 1]?.date.slice(5) || ""}</text>
  </svg>;
}
