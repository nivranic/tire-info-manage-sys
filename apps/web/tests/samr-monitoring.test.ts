import assert from "node:assert/strict";
import test from "node:test";
import type { MonitorTask } from "@tire/domain-types";
import { taskKindLabels, taskProjectionMatches, taskQueryLabel, taskResultLabel } from "../components/task-center-values.ts";

const task: MonitorTask = {
  kind: "samr", job_id: "synthetic-job", scope: "session", source_id: "samr-cn-recalls",
  query: { operation: "search", keyword: "轮胎", page_limit: 4, notice_limit: 60, text: "批次" },
  rules: [], rule_count: 0, rules_truncated: false, next_due_at: null, lease_until: null,
  state: "never_run", terminal: false, phase: null, last_event_at: null, last_attempt: null, last_run: null,
};

test("Chinese recall task labels preserve configured search coverage and notification filters", () => {
  assert.equal(taskKindLabels.samr, "中国召回监控");
  assert.equal(taskQueryLabel(task), "检索 轮胎 · 最多 4 页 / 60 份公告 · 批次");
  assert.equal(taskResultLabel("samr_complete"), "中国召回配置范围核验完成");
  assert.equal(taskResultLabel("samr_incomplete"), "中国召回扫描覆盖不完整");
});

test("Chinese recall task labels support source-native notice monitoring", () => {
  assert.equal(taskQueryLabel({ ...task, query: { operation: "notice", reference: "/synthetic-native-reference", text: "" } }),
    "公告 /synthetic-native-reference · 全部标题和正文变化");
});

test("Chinese recall task projections retain private scope and the exact job", () => {
  const detail = { schema: "monitor-tasks@1", task, attempts: [], legacy_runs: [], cursor: "synthetic-cursor" };
  assert.equal(taskProjectionMatches(detail, "samr", task.job_id), true);
  assert.equal(taskProjectionMatches(detail, "samr", "different-job"), false);
  assert.equal(taskProjectionMatches({ ...detail, task: { ...task, scope: "local_workspace" } }, "samr", task.job_id), false);
});
