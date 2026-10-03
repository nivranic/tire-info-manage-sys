"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, isMonitorTaskEvent, tireApi } from "@tire/api-client";
import type { MonitorTask, MonitorTaskDetail, MonitorTaskEvent, MonitorTaskFilters, MonitorTaskKind, MonitorTaskList, MonitorTaskState } from "@tire/domain-types";
import { useWorkbenchPlatform } from "./workbench-platform";
import { useSourceAccess } from "./source-status";
import { DiscoveryRunHistory } from "./recall-discovery-runs";
import { isTaskCursorReset, mergeTaskEvents, taskKindLabels, taskPhaseLabels, taskProjectionMatches, taskQueryLabel, taskResultLabel, taskScopeLabel, taskStateLabels } from "./task-center-values";

const stamp = (value: string | null | undefined) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN") : "尚未记录";
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "任务记录读取未完成。";
const kindLabel = (kind: MonitorTaskKind) => taskKindLabels[kind];
const reasonLabels: Record<string, string> = { source_paused: "来源已暂停", source_archived: "来源已归档", source_access_changed: "来源状态变化，原运行不再采纳", source_access_pin_missing: "原运行缺少有效来源授权", lease_expired: "执行租约失效", lease_reclaimed: "原执行已被新的领取替代", worker_error: "Worker 执行异常" };
const reasonText = (reason: string | null) => reason ? reasonLabels[reason] || reason : "未记录具体原因";
type TaskTarget = { kind: MonitorTaskKind; jobId: string };
type ConnectionState = "connecting" | "streaming" | "polling" | "reconnecting" | "disconnected" | "paused" | "unavailable";
function waitForNextRead(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const cancel = () => { clearTimeout(timer); signal.removeEventListener("abort", cancel); reject(new DOMException("已停止读取进度。", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", cancel); resolve(); }, ms);
    if (signal.aborted) cancel(); else signal.addEventListener("abort", cancel, { once: true });
  });
}

function TaskSummary({ task }: { task: MonitorTask }) {
  const sourceAccess = useSourceAccess();
  return <><div className="task-identity"><strong>{sourceAccess.get(task.source_id)?.name || task.source_id}</strong><span>{kindLabel(task.kind)} · {taskScopeLabel(task.scope)}</span><p>{taskQueryLabel(task)}</p></div><div className="task-state-line"><span className={`tag ${task.state === "succeeded" ? "success" : ["failed", "blocked", "interrupted", "result_unknown"].includes(task.state) ? "warning" : "quiet"}`}>{taskStateLabels[task.state]}</span><span>{task.phase ? taskPhaseLabels[task.phase] : "尚无阶段事件"}</span></div>{task.state === "result_unknown" ? <p className="review-warning">原执行尚无可确认的终态。已过期或失配的租约不能证明任务成功，也不表示已强制终止外部请求。</p> : null}<p className="task-meta">下一计划时间：{stamp(task.next_due_at)} · 最近持久事件：{stamp(task.last_event_at)}</p><ul className="task-rules">{task.rules.map(rule => <li key={rule.id}><span>{rule.name}</span><span>{rule.archived ? "规则已归档" : rule.enabled ? "规则已启用" : "规则已暂停"} · 修订 #{rule.revision}</span></li>)}</ul>{task.rules_truncated ? <p className="task-meta">关联规则共 {task.rule_count} 条，此处仅展示返回范围。</p> : null}</>;
}

export function MonitorTaskDialog({ kind, jobId, onClose }: TaskTarget & { onClose: () => void }) {
  const platform = useWorkbenchPlatform();
  const [detail, setDetail] = useState<MonitorTaskDetail | null>(null);
  const [events, setEvents] = useState<MonitorTaskEvent[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [error, setError] = useState("");
  const [lastConfirmed, setLastConfirmed] = useState<string | null>(null);
  const [attemptOffset, setAttemptOffset] = useState(0);
  const [legacyOffset, setLegacyOffset] = useState(0);
  const [connectionVersion, setConnectionVersion] = useState(0);
  const [visible, setVisible] = useState(true);
  const dialog = useRef<HTMLDialogElement>(null);
  const cursor = useRef<string | null>(null);
  const eventBuffer = useRef<MonitorTaskEvent[]>([]);
  const highestSequence = useRef(0);
  const requestGeneration = useRef(0);
  useEffect(() => {
    const node = dialog.current;
    const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    const changed = () => setVisible(document.visibilityState === "visible");
    changed(); document.addEventListener("visibilitychange", changed);
    return () => { document.removeEventListener("visibilitychange", changed); node?.close(); if (focus?.isConnected && !focus.closest("dialog:not([open])")) focus.focus({ preventScroll: true }); };
  }, []);
  useEffect(() => {
    if (!visible) { setConnection("paused"); return; }
    const controller = new AbortController(); const signal = controller.signal; const generation = ++requestGeneration.current;
    let failures = 0, cursorResets = 0;
    const current = () => !signal.aborted && generation === requestGeneration.current;
    async function readDetail(reset: boolean) {
      const result = await tireApi.monitorTask(kind, jobId, { attemptOffset, legacyOffset }, signal);
      if (!current()) return;
      if (!taskProjectionMatches(result, kind, jobId)) throw new Error("任务详情与当前范围不匹配。");
      if (reset) { cursor.current = result.cursor; eventBuffer.current = []; highestSequence.current = 0; setEvents([]); }
      setDetail(result); setLastConfirmed(result.server_time); setError("");
    }
    function acceptEvents(incoming: MonitorTaskEvent[]) {
      if (!incoming.every(isMonitorTaskEvent)) throw new Error("任务事件格式不受支持。");
      eventBuffer.current = mergeTaskEvents(eventBuffer.current, incoming); setEvents(eventBuffer.current);
      for (const event of incoming) if (event.sequence > highestSequence.current) { highestSequence.current = event.sequence; cursor.current = event.cursor; }
    }
    async function follow() {
      setConnection("connecting"); setError("");
      while (current()) {
        try {
          await readDetail(!cursor.current);
          if (!current() || !cursor.current) return;
          if (platform.kind === "web") {
            const outcome = await tireApi.streamMonitorTaskEvents(kind, jobId, cursor.current, async message => {
              if (!current()) return;
              if (message.type === "reset") { cursor.current = null; if (++cursorResets > 3) throw new Error("进度游标连续失效，请重新读取并连接进度。"); setConnection("reconnecting"); setError("进度游标已更新，正在重新读取任务记录。"); return; }
              if (message.type === "task_event") acceptEvents([message.data]);
              else if (message.data.cursor !== cursor.current) throw new Error("任务心跳跳过了未读取事件，正在保留已读记录。");
              await readDetail(false);
              if (current()) { failures = 0; cursorResets = 0; setConnection("streaming"); }
            }, signal);
            if (!current()) return;
            if (outcome === "reset") continue;
            await waitForNextRead(250, signal);
          } else {
            let pages = 0, more = true;
            while (more && current() && pages < 4) {
              const before: string = cursor.current;
              const page = await tireApi.monitorTaskEvents(kind, jobId, before, signal);
              if (!current()) return;
              if (page.schema !== "monitor-tasks@1" || page.kind !== kind || page.job_id !== jobId || !Array.isArray(page.items) || typeof page.next_cursor !== "string" || !page.next_cursor || page.next_cursor.length > 512 || page.next_cursor !== (page.items.at(-1)?.cursor || before) || (page.has_more && page.next_cursor === before)) throw new Error("任务事件页与当前范围不匹配。");
              acceptEvents(page.items); cursor.current = page.next_cursor; more = page.has_more; pages++;
            }
            await readDetail(false);
            if (!current()) return;
            failures = 0; cursorResets = 0; setConnection("polling"); await waitForNextRead(more ? 750 : 3000, signal);
          }
        } catch (cause) {
          if (!current() || (cause instanceof Error && cause.name === "AbortError")) return;
          if (isTaskCursorReset(cause) && ++cursorResets <= 3) { cursor.current = null; setConnection("reconnecting"); setError("进度游标已更新，正在重新读取任务记录。"); try { await waitForNextRead(250, signal); } catch { return; } continue; }
          if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) { setConnection("unavailable"); setError("当前会话无法读取此任务，请核对会话和访问范围。"); return; }
          failures++; setConnection("disconnected"); setError(errorText(cause));
          if (failures >= 5) return;
          try { await waitForNextRead(Math.min(1000 * 2 ** (failures - 1), 10000), signal); } catch { return; }
        }
      }
    }
    void follow();
    return () => { controller.abort(); requestGeneration.current++; };
  }, [kind, jobId, platform.kind, visible, attemptOffset, legacyOffset, connectionVersion]);
  const uncertain = ["disconnected", "unavailable", "paused", "reconnecting"].includes(connection);
  const connectionText: Record<ConnectionState, string> = { connecting: "正在读取任务并连接后续进度", streaming: "Web 进度流已连接", polling: "原生端正在按游标定时读取进度", reconnecting: "正在恢复进度连接，最新状态未知", disconnected: "连接中断，最新状态未知", paused: "页面已隐藏，进度读取暂停；最新状态未知", unavailable: "任务当前不可读取，最新状态未知" };
  return <dialog ref={dialog} className="fact-review-dialog task-dialog" aria-labelledby="monitor-task-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">DURABLE TASK EVENTS · READ ONLY</span><h2 id="monitor-task-title">监控任务运行记录</h2></div><button type="button" className="text-button" onClick={onClose}>关闭任务记录</button></header>
    <div className="fact-review-content"><p className="review-boundary">此处只读取已保存的运行记录，不启动或重试任务。执行中尚不代表在线核验成功；规则设置、来源状态与本次运行结果分别保留。</p><div className={`task-connection ${uncertain ? "uncertain" : ""}`} role="status"><strong>{connectionText[connection]}</strong><span>最近读取服务端记录：{stamp(lastConfirmed)}</span>{platform.kind !== "web" ? <span>使用同一游标的有界 REST 轮询，通常每 3 秒读取一次。</span> : null}</div>{error ? <p className="inline-error" role="alert">{error}</p> : null}<button type="button" className="secondary-button" onClick={() => setConnectionVersion(value => value + 1)}>重新读取并连接进度</button>
      {detail ? <><section className="task-summary" aria-label="任务最后确认状态">{uncertain ? <p className="review-warning">以下保留最后确认记录，不能代表当前执行状态。</p> : null}<TaskSummary task={detail.task} /><p className="task-meta">任务标识 <code>{jobId}</code></p></section>
        {kind === "recall_discovery" ? <DiscoveryRunHistory key={jobId} jobId={jobId} refreshKey={detail.task.last_event_at} /> : null}
        <section className="task-attempts" aria-label="任务执行历史"><h3>执行历史 · {detail.attempts_total}</h3>{detail.attempts.length ? detail.attempts.map(attempt => <details key={attempt.id} className="task-attempt"><summary>{taskStateLabels[attempt.state]} · {stamp(attempt.started_at)}</summary><p>{taskPhaseLabels[attempt.phase]} · {attempt.terminal ? "已有终态" : "尚无终态"}</p><p>开始：{stamp(attempt.started_at)}<br />结束：{stamp(attempt.finished_at)}</p><p>来源结果：{taskResultLabel(attempt.result_state)}</p>{attempt.reason ? <p>原因：{reasonText(attempt.reason)}</p> : null}<p className="task-meta">运行标识 <code>{attempt.id}</code>{attempt.query_id ? <> · 查询标识 <code>{attempt.query_id}</code></> : null}</p></details>) : <p>没有新格式的执行记录。</p>}<div className="reparse-pages"><button type="button" className="text-button" disabled={!attemptOffset} onClick={() => setAttemptOffset(value => Math.max(0, value - 20))}>上一页执行</button><span>第 {Math.floor(attemptOffset / 20) + 1} 页</span><button type="button" className="text-button" disabled={attemptOffset + detail.attempts.length >= detail.attempts_total} onClick={() => setAttemptOffset(value => value + 20)}>下一页执行</button></div></section>
        <section className="task-events" aria-label="本次连接的持久阶段事件"><h3>本次连接读取的阶段事件</h3><p className="task-meta">仅展示本次连接最近 200 条事件；完整运行记录在上方分页读取。重连不创建新的执行。</p>{events.length ? <ol>{events.map(event => <li key={event.id}><strong>{taskPhaseLabels[event.phase]}</strong><span>{taskStateLabels[event.state]} · {stamp(event.created_at)}</span>{event.result_state ? <p>{taskResultLabel(event.result_state)}{event.reason ? ` · ${reasonText(event.reason)}` : ""}</p> : null}</li>)}</ol> : <p>尚未收到新的持久阶段事件。保持连接不表示任务正在执行。</p>}</section>
        <section className="task-legacy" aria-label="旧版任务终态历史"><h3>旧版终态记录 · {detail.legacy_runs_total}</h3><p className="task-meta">这些旧记录没有阶段事件，不补造领取、执行进度或新的任务历史。</p>{detail.legacy_runs.map(run => <details key={run.id}><summary>{taskResultLabel(run.state)} · {stamp(run.finished_at)}</summary><p>开始：{stamp(run.started_at)}<br />结束：{stamp(run.finished_at)}</p>{run.reason ? <p>{reasonText(run.reason)}</p> : null}<p className="task-meta">记录标识 <code>{run.id}</code></p></details>)}{!detail.legacy_runs.length ? <p>当前页没有旧版终态记录。</p> : null}<div className="reparse-pages"><button type="button" className="text-button" disabled={!legacyOffset} onClick={() => setLegacyOffset(value => Math.max(0, value - 20))}>上一页旧记录</button><span>第 {Math.floor(legacyOffset / 20) + 1} 页</span><button type="button" className="text-button" disabled={legacyOffset + detail.legacy_runs.length >= detail.legacy_runs_total} onClick={() => setLegacyOffset(value => value + 20)}>下一页旧记录</button></div></section>
      </> : <p role="status">正在读取任务记录…</p>}
    </div>
  </dialog>;
}

export default function MonitorTaskCenter() {
  const sourceAccess = useSourceAccess();
  const [expanded, setExpanded] = useState(false);
  const [filters, setFilters] = useState<MonitorTaskFilters>({});
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<MonitorTaskList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [target, setTarget] = useState<TaskTarget | null>(null);
  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController(); setLoading(true); setError(""); setData(null);
    void tireApi.monitorTasks(filters, offset, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (value.schema !== "monitor-tasks@1" || !Array.isArray(value.items) || value.offset !== offset || value.items.some(task => !Object.hasOwn(taskKindLabels, task.kind) || !Object.hasOwn(taskStateLabels, task.state) || task.scope !== (task.kind === "tire" ? "local_workspace" : "session"))) throw new Error("任务列表格式或可见范围不受支持。");
      setData(value);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [expanded, filters, offset, revision]);
  function changeFilters(patch: MonitorTaskFilters) { setFilters(previous => ({ ...previous, ...patch })); setOffset(0); }
  return <section className="quarantine-panel task-center" aria-label="监控任务执行中心"><div className="panel-title"><span>监控任务执行中心</span><button type="button" className="secondary-button" onClick={() => setExpanded(value => !value)}>{expanded ? "收起任务列表" : "查看任务执行"}</button></div><p className="quality-intro">查看轮胎规格与召回监控的真实运行记录。轮胎任务属于本机共享工作区，召回任务只在当前会话可见；暂停或归档规则后仍可追溯历史。</p>
    {expanded ? <><div className="task-filters"><label><span>任务类型</span><select aria-label="任务类型" value={filters.kind || ""} onChange={event => changeFilters({ kind: (event.target.value || undefined) as MonitorTaskKind | undefined })}><option value="">全部可见任务</option>{Object.entries(taskKindLabels).map(([kind, label]) => <option key={kind} value={kind}>{label}</option>)}</select></label><label><span>来源</span><select aria-label="来源" value={filters.source_id || ""} onChange={event => changeFilters({ source_id: event.target.value || undefined })}><option value="">全部来源</option>{sourceAccess.items.filter(source => source.target_kind !== "vehicle").map(source => <option key={source.source_id} value={source.source_id}>{source.name}</option>)}</select></label><label><span>最后确认状态</span><select aria-label="最后确认状态" value={filters.state || ""} onChange={event => changeFilters({ state: (event.target.value || undefined) as MonitorTaskState | undefined })}><option value="">全部状态</option>{Object.entries(taskStateLabels).map(([state, label]) => <option value={state} key={state}>{label}</option>)}</select></label><button type="button" className="secondary-button" disabled={loading} onClick={() => setRevision(value => value + 1)}>刷新任务列表</button></div>{error ? <p className="inline-error" role="alert">{error} 已显示记录不代表最新状态。</p> : null}{loading ? <p role="status">正在读取任务列表…</p> : null}{data ? <><p className="task-meta">列表读取时间：{stamp(data.server_time)} · 共 {data.total} 个可见任务。打开单个任务后跟踪进度。</p><div className="task-list">{data.items.map(task => <article className="task-list-item" key={`${task.kind}:${task.job_id}`}><TaskSummary task={task} /><button type="button" className="secondary-button" onClick={() => setTarget({ kind: task.kind, jobId: task.job_id })}>查看运行与进度</button></article>)}</div>{!data.items.length ? <p className="quality-empty">当前范围没有任务。查看列表不会创建、启用或运行监控规则。</p> : null}<div className="reparse-pages"><button type="button" className="text-button" disabled={loading || !offset} onClick={() => setOffset(value => Math.max(0, value - 20))}>上一页任务</button><span>第 {Math.floor(offset / 20) + 1} 页</span><button type="button" className="text-button" disabled={loading || offset + data.items.length >= data.total} onClick={() => setOffset(value => value + 20)}>下一页任务</button></div></> : null}</> : null}
    {target ? <MonitorTaskDialog key={`${target.kind}:${target.jobId}`} {...target} onClose={() => setTarget(null)} /> : null}
  </section>;
}
