import type { RecallDiscoveryCoverage, RecallDiscoveryRun } from "@tire/domain-types";

export const normalizeDiscoverySearch = (value: string) => value.trim().replace(/\s+/g, " ");
export const validDiscoverySearch = (value: string) => {
  const normalized = normalizeDiscoverySearch(value);
  return normalized.length > 0 && normalized.length <= 120 && !/[\u0000-\u001f\u007f]/.test(normalized);
};
export const discoveryCampaignValid = (value: string) => /^\d{2}T\d{6}$/.test(value);
export function discoveryCoverageComplete(coverage: RecallDiscoveryCoverage): boolean {
  return coverage.status === "complete" && coverage.passes_required === 2 && coverage.passes_completed === 2
    && coverage.pass_fingerprints.length === 2 && !!coverage.pass_fingerprints[0]
    && coverage.pass_fingerprints[0] === coverage.pass_fingerprints[1];
}
export function discoveryRunLabel(run: RecallDiscoveryRun): string {
  if (run.state === "discovery_complete" && discoveryCoverageComplete(run.coverage)) return run.coverage.is_initial_baseline ? "已建立首次完整基线" : "双遍扫描一致";
  if (run.state === "source_unavailable") return "来源不可用，覆盖不完整";
  if (run.state === "worker_error") return "扫描异常，覆盖不完整";
  return "覆盖不完整";
}
export function discoveryNoticeHeading(run: RecallDiscoveryRun): string {
  if (!discoveryCoverageComplete(run.coverage)) return "本轮不推进基线，不产生新增候选提醒。";
  if (run.coverage.is_initial_baseline) return "本轮建立首次完整基线，不批量发送已有候选提醒。";
  return run.coverage.new_candidates_count > 0 ? `本轮新增观察 ${run.coverage.new_candidates_count} 个候选，不代表官方刚发布。` : "本轮未新增观察候选，不代表没有召回。";
}
export const discoveryReason = (reason: string | null) => reason ? ({
  source_paused: "来源已暂停", source_archived: "来源已归档", source_access_changed: "来源许可在扫描期间变化",
  source_access_pin_missing: "来源许可记录缺失", discovery_scope_budget_exceeded: "匹配范围超过每遍 200 个产品，请缩小关键词范围",
  discovery_page_budget_exceeded: "已达到页面读取上限，请缩小关键词范围", discovery_time_budget_exceeded: "已达到本轮时间上限",
  discovery_raw_budget_exceeded: "已达到原文大小上限", discovery_page_failed: "部分页面未能完成在线读取",
  discovery_pagination_changed: "扫描期间分页范围发生变化", discovery_content_changed: "两遍扫描的完整内容不一致",
  discovery_parser_changed: "扫描期间解析器身份发生变化", recall_discovery_execution_failed: "本轮执行异常",
  recall_discovery_lease_lost: "本次执行许可已失效", recall_discovery_rule_disabled: "规则已暂停或归档",
  recall_discovery_rule_changed: "扫描期间规则修订发生变化",
  discovery_incomplete: "本轮未满足完整扫描条件", worker_error: "本轮执行异常",
} as Record<string, string>)[reason] || reason : "未记录";
