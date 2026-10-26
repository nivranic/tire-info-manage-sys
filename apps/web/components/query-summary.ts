import type { QueryResult } from "@tire/domain-types";

export type QuerySummaryRun = Readonly<{
  loading: boolean;
  data?: Readonly<Pick<QueryResult, "data_state">>;
  error?: string;
  consentPending?: boolean;
  denied?: boolean;
}>;

export type QuerySummaryState = "idle" | "querying" | "fallback_pending" | "consent_required"
  | "denied" | "unavailable" | "partial" | "complete";

export type QuerySummary = { text: string; busy: boolean; state: QuerySummaryState };

export const hasQueryData = (data?: QuerySummaryRun["data"]) =>
  !!data && ["live", "live_verified_304", "local_snapshot"].includes(data.data_state);

const pendingLabels = {
  querying: "正在在线查询",
  fallback_pending: "正在处理回退决定",
  consent_required: "等待回退授权",
  denied: "已拒绝回退",
  unavailable: "未获得可核验结果",
} as const;

export function getQuerySummary(runs: readonly QuerySummaryRun[], resultsCount: number): QuerySummary {
  if (!runs.length) return { text: "LIVE FIRST / EVIDENCE ALWAYS", busy: false, state: "idle" };

  let availableCount = 0;
  const counts = { querying: 0, fallback_pending: 0, consent_required: 0, denied: 0, unavailable: 0 };
  for (const run of runs) {
    const available = hasQueryData(run.data);
    if (available) availableCount++;
    if (run.loading) counts.querying++;
    else if (run.consentPending) counts.fallback_pending++;
    else if (available) continue;
    // A failed consent submission retains its old DTO, but it is no longer waiting for a response.
    else if (run.error) counts.unavailable++;
    else if (run.denied) counts.denied++;
    else if (run.data?.data_state === "consent_required") counts.consent_required++;
    else counts.unavailable++;
  }

  let state: QuerySummaryState;
  if (counts.querying) state = "querying";
  else if (counts.fallback_pending) state = "fallback_pending";
  else if (counts.consent_required) state = "consent_required";
  else if (availableCount) state = counts.denied || counts.unavailable ? "partial" : "complete";
  else state = counts.denied === runs.length ? "denied" : "unavailable";

  let headline = "本次未获得可核验结果";
  if (availableCount) headline = `${resultsCount} MATCHED SKU`;
  else if (state === "querying") headline = pendingLabels.querying;
  else if (state === "fallback_pending") headline = pendingLabels.fallback_pending;
  else if (state === "consent_required") headline = "在线查询未完成，等待回退授权";
  else if (state === "denied") headline = "已拒绝全部回退，本次无可核验结果";

  const details = (Object.keys(counts) as (keyof typeof counts)[])
    .filter(key => counts[key] > 0 && (availableCount > 0 || key !== state))
    .map(key => `${counts[key]} 个来源${pendingLabels[key]}`);
  return {
    text: `${headline} / ${runs.length} SOURCES${details.length ? ` · ${details.join("；")}` : ""}`,
    busy: counts.querying > 0 || counts.fallback_pending > 0,
    state,
  };
}
