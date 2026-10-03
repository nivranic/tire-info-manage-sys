import type { MonitorTask, MonitorTaskEvent, MonitorTaskKind, MonitorTaskPhase, MonitorTaskState } from "@tire/domain-types";

export const taskStateLabels: Record<MonitorTaskState, string> = { never_run: "尚未执行", running: "执行中", succeeded: "已完成", failed: "执行失败", blocked: "来源设置阻止采纳", interrupted: "执行已中断", result_unknown: "结果待确认" };
export const taskKindLabels: Record<MonitorTaskKind, string> = { tire: "轮胎规格监控", recall: "已选召回公告监控", recall_discovery: "召回名称发现监控" };
export const taskPhaseLabels: Record<MonitorTaskPhase, string> = { claimed: "已领取任务", running: "正在执行", finished: "已记录结果" };
export const taskScopeLabel = (scope: MonitorTask["scope"]) => scope === "local_workspace" ? "本机工作区共享" : "当前会话";
export const taskResultLabel = (value: string | null) => ({ live: "在线采纳成功", live_verified_304: "在线确认未变", source_unavailable: "来源不可用", worker_error: "任务执行异常", discovery_complete: "名称双遍扫描一致，尚未核验公告", discovery_incomplete: "名称扫描覆盖不完整，不推进基线或产生候选提醒" } as Record<string, string>)[value || ""] || value || "尚无来源结果";
export function taskQueryLabel(task: MonitorTask): string {
  if ("search" in task.query) return `名称关键词：${task.query.search}`;
  return "campaign_number" in task.query ? `公告 ${task.query.campaign_number}` : [task.query.model, task.query.size || "全部尺寸"].filter(Boolean).join(" · ");
}
export function mergeTaskEvents(previous: readonly MonitorTaskEvent[], incoming: readonly MonitorTaskEvent[], limit = 200): MonitorTaskEvent[] {
  const byId = new Map(previous.map(event => [event.id, event]));
  const bySequence = new Map(previous.map(event => [event.sequence, event.id]));
  for (const event of incoming) {
    const existing = byId.get(event.id);
    if (existing && (Object.keys(existing) as (keyof MonitorTaskEvent)[]).some(key => existing[key] !== event[key])) throw new Error("同一任务事件内容发生变化，请重新读取任务。");
    if (bySequence.has(event.sequence) && bySequence.get(event.sequence) !== event.id) throw new Error("任务事件顺序冲突，请重新读取任务。");
    byId.set(event.id, event); bySequence.set(event.sequence, event.id);
  }
  return [...byId.values()].sort((a, b) => a.sequence - b.sequence).slice(-Math.min(200, Math.max(1, limit)));
}
export const isTaskCursorReset = (cause: unknown) => !!cause && typeof cause === "object" && "code" in cause && cause.code === "task_cursor_reset_required";
export function taskProjectionMatches(value: unknown, kind: string, jobId: string): value is import("@tire/domain-types").MonitorTaskDetail {
  if (!value || typeof value !== "object") return false;
  const detail = value as import("@tire/domain-types").MonitorTaskDetail;
  return detail.schema === "monitor-tasks@1" && detail.task?.kind === kind && detail.task?.job_id === jobId
    && Object.hasOwn(taskKindLabels, kind) && detail.task.scope === (kind === "tire" ? "local_workspace" : "session") && Object.hasOwn(taskStateLabels, detail.task.state)
    && Array.isArray(detail.attempts) && Array.isArray(detail.legacy_runs) && Array.isArray(detail.task.rules)
    && typeof detail.cursor === "string" && detail.cursor.length > 0 && detail.cursor.length <= 512;
}
