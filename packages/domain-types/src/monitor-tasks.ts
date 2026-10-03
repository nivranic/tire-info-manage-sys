import type { RecallDiscoveryQuery, RecallQuery, TireQuery } from "./index";

export type MonitorTaskKind = "tire" | "recall" | "recall_discovery";
export type MonitorTaskScope = "local_workspace" | "session";
export type MonitorTaskPhase = "claimed" | "running" | "finished";
export type MonitorAttemptState = "running" | "succeeded" | "failed" | "blocked" | "interrupted";
export type MonitorTaskState = MonitorAttemptState | "never_run" | "result_unknown";
export interface MonitorTaskAttempt {
  id: string; started_at: string; finished_at: string | null; last_event_at: string;
  phase: MonitorTaskPhase; state: MonitorAttemptState; terminal: boolean;
  result_state: string | null; reason: string | null; query_id: string | null;
  source_access_generation: number | null;
}
export interface MonitorTaskEvent {
  id: string; sequence: number; cursor: string; attempt_id: string; phase: MonitorTaskPhase;
  state: MonitorAttemptState; result_state: string | null; reason: string | null;
  query_id: string | null; run_id: string | null; created_at: string;
}
export interface MonitorTaskLegacyRun { id: string; state: string; reason: string | null; started_at: string | null; finished_at: string | null; legacy: true }
export interface MonitorTask {
  kind: MonitorTaskKind; job_id: string; scope: MonitorTaskScope; source_id: string; query: TireQuery | RecallQuery | RecallDiscoveryQuery;
  rules: { id: string; name: string; revision: number; enabled: boolean; archived: boolean }[];
  rule_count: number; rules_truncated: boolean; next_due_at: string | null; lease_until: string | null;
  state: MonitorTaskState; terminal: boolean; phase: MonitorTaskPhase | null; last_event_at: string | null;
  last_attempt: MonitorTaskAttempt | null;
  last_run: MonitorTaskLegacyRun | null;
}
export interface MonitorTaskFilters { kind?: MonitorTaskKind; source_id?: string; rule_id?: string; state?: MonitorTaskState }
export interface MonitorTaskList {
  schema: "monitor-tasks@1"; items: MonitorTask[]; total: number; offset: number; limit: number; server_time: string;
}
export interface MonitorTaskDetail {
  schema: "monitor-tasks@1"; task: MonitorTask; attempts: MonitorTaskAttempt[]; attempts_total: number;
  attempt_offset: number; attempt_limit: number; cursor: string; server_time: string;
  legacy_runs: MonitorTaskLegacyRun[]; legacy_runs_total: number; legacy_offset: number; legacy_limit: number;
}
export interface MonitorTaskEvents {
  schema: "monitor-tasks@1"; kind: MonitorTaskKind; job_id: string; items: MonitorTaskEvent[];
  next_cursor: string; latest_cursor: string; has_more: boolean; server_time: string;
}
export type MonitorTaskStreamMessage =
  | { type: "task_event"; data: MonitorTaskEvent }
  | { type: "heartbeat"; data: { cursor: string; server_time: string } }
  | { type: "stream_end"; data: { cursor: string; server_time: string; reason: "window_complete" } }
  | { type: "reset"; data: { code: "task_cursor_reset_required"; server_time: string } };
