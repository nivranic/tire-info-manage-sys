"use client";
import type { AIStatus } from "@tire/domain-types";

const providerLabels: Record<string, string> = { openai_responses: "OpenAI Responses API", openai_chat: "OpenAI Chat Completions", anthropic: "Anthropic Messages API" };
export const aiProviderLabel = (provider?: string) => providerLabels[provider || "openai_responses"] || provider || "AI Provider";

const compact = (value: number) => value >= 10000 ? (value / 1000).toFixed(1).replace(/\.0$/, "") + "k" : value.toLocaleString("en-US");

/** 今日 AI 预算余量：请求数与 token 记账量相对日限额的进度（数据来自 /v1/ai/status，零后端改动）。 */
export default function AiBudgetMeter({ status, compact: terse = false }: { status: AIStatus | null; compact?: boolean }) {
  if (!status) return terse ? null : <p className="ai-budget-line">正在读取今日用量…</p>;
  const budget = status.budget;
  const sources: { label: string; used: number; limit: number | undefined }[] = [
    { label: "请求", used: budget.requests, limit: status.model.daily_request_limit },
    { label: "Tokens", used: budget.accounted_tokens, limit: status.model.daily_token_limit },
  ];
  const rows = sources.filter((row): row is { label: string; used: number; limit: number } => typeof row.limit === "number" && row.limit > 0);
  if (!rows.length) return terse ? null : <p className="ai-budget-line">UTC {budget.day_utc}：{budget.requests} 次请求 / 已记账 {budget.accounted_tokens.toLocaleString()} tokens。</p>;
  return <div className="ai-budget" aria-label="今日 AI 用量">
    {rows.map(row => {
      const ratio = Math.min(1, row.used / row.limit);
      const level = row.used >= row.limit ? "exhausted" : ratio >= 0.8 ? "warn" : "";
      return <p className={["ai-budget-row", level].filter(Boolean).join(" ")} key={row.label}>
        <span className="ai-budget-label">{row.label}</span>
        <span className="ai-budget-meter" aria-hidden="true"><span style={{ width: Math.round(ratio * 100) + "%" }} /></span>
        <span className="mono ai-budget-value">{compact(row.used)} / {compact(row.limit)}</span>
      </p>; })}
    {terse ? null : <small className="ai-budget-note">UTC {budget.day_utc} 记账{budget.has_pending_request ? " · 有进行中的请求（含预留）" : ""}。含未知用量的预留，不是账单金额。</small>}
  </div>;
}
