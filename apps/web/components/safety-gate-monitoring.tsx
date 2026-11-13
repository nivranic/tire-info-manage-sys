"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { SafetyGateMonitorQuery, SafetyGateMonitorRule, SafetyGateMonitorRun, SafetyGateNotification, SafetyGatePage, SafetyGateRuleDetail, SafetyGateRuleSettings } from "@tire/domain-types";
import { DataTree } from "./reparse-review";
import { useSourceAccess } from "./source-status";
import { MonitorTaskDialog } from "./task-center";
import { taskResultLabel } from "./task-center-values";
import { safetyGateEventNames } from "./safety-gate-values";

const stamp = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "尚未记录";
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "Safety Gate监控操作未完成。";
type SaveIntent = { key: string; query: SafetyGateMonitorQuery; settings: SafetyGateRuleSettings; revision: number | null };

function RuleEditor({ id, onClose, onSaved }: { id: string | null; onClose: () => void; onSaved: (message: string) => void }) {
  const access = useSourceAccess();
  const [rule, setRule] = useState<SafetyGateRuleDetail | null>(null);
  const [query, setQuery] = useState<SafetyGateMonitorQuery>({ report_limit: 4, text: "tyre" });
  const [settings, setSettings] = useState<SafetyGateRuleSettings>({ name: "", enabled: false, archived: false, interval_seconds: 21600 });
  const [pending, setPending] = useState<SaveIntent | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const [reload, setReload] = useState(0);
  const operation = useRef<AbortController | null>(null);
  const intent = useRef<SaveIntent | null>(null);

  useEffect(() => () => operation.current?.abort(), []);
  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    setRule(null);
    setError("");
    void tireApi.safetyGateRule(id, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      setRule(value);
      setQuery(value.query);
      setSettings({ name: value.name, enabled: value.enabled, archived: value.archived, interval_seconds: value.interval_seconds });
      setStale(false);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [id, reload]);

  async function save(action: "save" | "archive" | "restore") {
    if (operation.current || stale || id && !rule) return;
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true);
    setError("");
    try {
      const next = { ...settings, name: settings.name.trim() };
      if (action !== "save") {
        next.archived = action === "archive";
        next.enabled = false;
      }
      if (!intent.current && next.enabled && !await access.ensure("eu-safety-gate")) {
        throw new Error("来源当前无法在线采集，可先保存为暂停规则。");
      }
      if (controller.signal.aborted) return;
      const write = intent.current ?? { key: crypto.randomUUID(), query: { ...query, text: query.text.trim() }, settings: next, revision: rule?.revision ?? null };
      intent.current = write;
      setPending(write);
      const saved = id
        ? await tireApi.reviseSafetyGateRule(id, write.revision!, write.settings, write.key, controller.signal)
        : await tireApi.createSafetyGateRule(write.query, { name: write.settings.name, enabled: write.settings.enabled, interval_seconds: write.settings.interval_seconds }, write.key, controller.signal);
      if (controller.signal.aborted) return;
      if (!saved.write_result?.revision_id || !Number.isSafeInteger(saved.write_result.revision) || saved.write_result.revision < 1 || saved.write_result.revision > saved.revision) {
        throw new Error("服务端保存回执尚未确认。");
      }
      intent.current = null;
      setPending(null);
      onSaved(`已确认本次操作保存于修订 ${saved.write_result.revision}，当前规则修订 ${saved.revision}。`);
      onClose();
    } catch (cause) {
      if (controller.signal.aborted) return;
      if (cause instanceof ApiError && cause.status < 500) {
        intent.current = null;
        setPending(null);
        setStale(cause.status === 409);
        setError(errorText(cause));
      } else {
        setError(intent.current ? "保存结果待确认，请核对同一次保存结果。" : errorText(cause));
      }
    } finally {
      if (operation.current === controller) operation.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  const locked = busy || !!pending || stale;
  return <section className="recall-rule-editor" aria-label="Safety Gate规则编辑">
    <div className="recall-section-heading"><h5>{id ? "编辑周报监控规则" : "新建周报监控规则"}</h5><button type="button" className="text-button" disabled={busy || !!pending} onClick={onClose}>关闭规则编辑</button></div>
    <p className="recall-help">保存后由Worker按计划核验最新周报。关键词匹配变化前后官方字段，留空关注范围内全部告警。</p>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {id && !pending ? <button type="button" className="text-button" disabled={busy} onClick={() => setReload(value => value + 1)}>重新读取规则</button> : null}
    {id && !rule ? <p role="status">正在读取规则…</p> : <form className="review-form" onSubmit={event => { event.preventDefault(); void save("save"); }}>
      <label><span>周报监控名称</span><input required maxLength={120} value={settings.name} disabled={locked} onChange={event => setSettings(value => ({ ...value, name: event.target.value }))} /></label>
      <label><span>告警关键词</span><input maxLength={120} value={query.text} disabled={locked || !!id} onChange={event => setQuery(value => ({ ...value, text: event.target.value }))} /></label>
      <label><span>最近周报数量</span><input type="number" required min={1} max={12} step={1} value={query.report_limit} disabled={locked || !!id} onChange={event => setQuery(value => ({ ...value, report_limit: Number(event.target.value) }))} /></label>
      <label><span>周报检查间隔（小时）</span><input type="number" required min={1} max={168} step={1} value={settings.interval_seconds / 3600} disabled={locked} onChange={event => setSettings(value => ({ ...value, interval_seconds: Number(event.target.value) * 3600 }))} /></label>
      <label className="review-checkbox"><input type="checkbox" checked={settings.enabled} disabled={locked || settings.archived} onChange={event => setSettings(value => ({ ...value, enabled: event.target.checked }))} />启用周报监控</label>
      <div className="variant-actions">
        {!settings.archived || pending ? <button type="submit" className="primary-button" disabled={busy || stale || !settings.name.trim()}>{pending ? "核对同一次保存结果" : "保存周报监控规则"}</button> : null}
        {id ? <button type="button" className="secondary-button" disabled={locked} onClick={() => void save(settings.archived ? "restore" : "archive")}>{settings.archived ? "恢复规则为暂停" : "归档周报监控规则"}</button> : null}
      </div>
    </form>}
    {rule ? <DataTree label="周报规则修订历史" value={{ revisions: rule.history, truncated: rule.history_truncated }} /> : null}
  </section>;
}

function RunHistory({ ruleId, onClose, onEvidence }: { ruleId: string; onClose: () => void; onEvidence: (id: string) => void }) {
  const [page, setPage] = useState<SafetyGatePage<SafetyGateMonitorRun> | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setPage(null);
    setError("");
    void tireApi.safetyGateMonitorRuns(ruleId, offset, controller.signal).then(value => {
      if (!controller.signal.aborted) setPage(value);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [ruleId, offset]);
  return <section className="recall-evidence" aria-label="Safety Gate核验记录">
    <div className="recall-section-heading"><h5>周报核验记录</h5><button type="button" className="text-button" onClick={onClose}>收起核验记录</button></div>
    {error ? <p role="alert">{error}</p> : !page ? <p role="status">正在读取核验记录…</p> : null}
    {page?.items.map(run => <article className="recall-product" key={run.id}>
      <strong>{taskResultLabel(run.state)} · {stamp(run.finished_at)}</strong>
      <p>{run.coverage === "complete" ? "所选范围已完成" : "本轮覆盖不完整"} · 计划 {run.selected_reports.length} 份周报 · 新增 {run.notification_count} 条提醒</p>
      {run.reason ? <p className="review-warning">{run.reason}</p> : null}
      <DataTree label="所选周报与逐次核验状态" value={{ reports: run.selected_reports, checks: run.checks }} />
      {run.checks.filter(check => check.snapshot_id).map(check => <button type="button" className="text-button" key={check.query_id} onClick={() => onEvidence(check.snapshot_id!)}>查看{check.query.operation === "reports" ? "索引" : check.query.reference}核验原件</button>)}
    </article>)}
    {page && !page.total ? <p>尚无已完成的运行记录，可在任务进度中查看当前执行。</p> : null}
    {page && page.total > page.limit ? <div className="reparse-pages"><button type="button" disabled={!offset} onClick={() => setOffset(value => Math.max(0, value - 10))}>上一页运行</button><button type="button" disabled={offset + page.limit >= page.total} onClick={() => setOffset(value => value + 10)}>下一页运行</button></div> : null}
  </section>;
}

export function SafetyGateMonitoring({ sessionReady, onEvidence }: { sessionReady: boolean; onEvidence: (id: string) => void }) {
  const [rules, setRules] = useState<SafetyGatePage<SafetyGateMonitorRule> | null>(null);
  const [notices, setNotices] = useState<SafetyGatePage<SafetyGateNotification> | null>(null);
  const [archived, setArchived] = useState(false);
  const [unread, setUnread] = useState(false);
  const [ruleOffset, setRuleOffset] = useState(0);
  const [noticeOffset, setNoticeOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const [editor, setEditor] = useState<{ id: string | null } | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [runRule, setRunRule] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [marking, setMarking] = useState(false);
  const mutation = useRef<AbortController | null>(null);

  useEffect(() => () => mutation.current?.abort(), []);
  useEffect(() => {
    if (!sessionReady) {
      mutation.current?.abort();
      mutation.current = null;
      setRules(null); setNotices(null); setEditor(null); setTaskId(null); setRunRule(null);
      setMarking(false); setError(""); setMessage("");
      return;
    }
    const controller = new AbortController();
    setRules(null); setNotices(null); setError("");
    void Promise.all([tireApi.safetyGateRules(archived, ruleOffset, controller.signal), tireApi.safetyGateNotifications(unread, noticeOffset, controller.signal)]).then(([ruleList, noticeList]) => {
      if (controller.signal.aborted) return;
      if (ruleList.scope !== "session" || noticeList.scope !== "session" || ruleList.offset !== ruleOffset || noticeList.offset !== noticeOffset) throw new Error("周报监控分页与当前请求不一致。");
      setRules(ruleList); setNotices(noticeList);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [sessionReady, archived, unread, ruleOffset, noticeOffset, version]);

  async function mark(notice: SafetyGateNotification) {
    if (mutation.current) return;
    const controller = new AbortController();
    mutation.current = controller;
    setMarking(true);
    try {
      await tireApi.markSafetyGateNotification(notice.id, !notice.read_at, controller.signal);
      if (!controller.signal.aborted) setVersion(value => value + 1);
    } catch (cause) {
      if (!controller.signal.aborted) setError(errorText(cause));
    } finally {
      if (mutation.current === controller) mutation.current = null;
      if (!controller.signal.aborted) setMarking(false);
    }
  }

  return <section className="recall-discovery" aria-labelledby="safety-monitor-title">
    <h4 id="safety-monitor-title">Safety Gate监控与提醒</h4>
    <p className="recall-help">按官方索引滚动核验所选数量的最新英文周报。提醒关注系统观察到的变化，具体轮胎适用性待核对。</p>
    <div className="variant-actions"><button type="button" className="secondary-button" disabled={!sessionReady || !!editor} onClick={() => setEditor({ id: null })}>新建周报监控规则</button><button type="button" className="text-button" disabled={!sessionReady || marking} onClick={() => setVersion(value => value + 1)}>刷新周报监控记录</button></div>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {message ? <p role="status">{message}</p> : null}
    {sessionReady && !rules && !error ? <p role="status">正在读取周报监控记录…</p> : null}
    {editor && sessionReady ? <RuleEditor key={editor.id || "new"} id={editor.id} onClose={() => setEditor(null)} onSaved={value => { setMessage(value); setVersion(current => current + 1); }} /> : null}
    <label className="review-checkbox"><input type="checkbox" checked={archived} onChange={event => { setArchived(event.target.checked); setRuleOffset(0); }} />查看已归档周报规则</label>
    {rules?.items.map(rule => <article className="recall-product" key={rule.id}>
      <h5>{rule.name}</h5><p>{rule.archived ? "已归档" : rule.enabled ? "已启用" : "已暂停"} · 每 {rule.interval_seconds / 3600} 小时 · 最近 {rule.query.report_limit} 份周报 · {rule.query.text || "全部告警"}</p>
      <p>下次计划 {stamp(rule.job.next_due_at)} · {rule.job.last_run ? taskResultLabel(rule.job.last_run.state) : "尚未运行"}</p>
      <div className="variant-actions"><button type="button" className="text-button" disabled={!!editor} onClick={() => setEditor({ id: rule.id })}>编辑周报规则</button><button type="button" className="text-button" onClick={() => setTaskId(rule.job.id)}>查看周报任务进度</button><button type="button" className="text-button" onClick={() => setRunRule(rule.id)}>读取周报核验记录</button></div>
    </article>)}
    {rules && !rules.total ? <p>当前范围尚无周报监控规则。</p> : null}
    {rules && rules.total > rules.limit ? <div className="reparse-pages"><button type="button" disabled={!ruleOffset} onClick={() => setRuleOffset(value => Math.max(0, value - 20))}>上一页规则</button><button type="button" disabled={ruleOffset + rules.limit >= rules.total} onClick={() => setRuleOffset(value => value + 20)}>下一页规则</button></div> : null}
    <h5>告警变化提醒</h5>
    <label className="review-checkbox"><input type="checkbox" checked={unread} onChange={event => { setUnread(event.target.checked); setNoticeOffset(0); }} />仅查看未读周报提醒</label>
    {notices?.items.map(notice => <article className="recall-product" key={notice.id}>
      <strong>{notice.rule_name} · {notice.observation.revision.alert.case_number}</strong>
      <p>{notice.observation.event ? safetyGateEventNames[notice.observation.event.kind] : "告警观察"} · {stamp(notice.delivered_at)} · {notice.read_at ? "已读" : "未读"}</p>
      <p>{notice.observation.revision.alert.fields.name} · 内容版本 {notice.observation.revision.revision} · 适用性待核对</p>
      <DataTree label="周报提醒变化前后字段" value={notice.observation.event?.changes ?? {}} />
      <div className="variant-actions"><button type="button" className="text-button" onClick={() => onEvidence(notice.observation.snapshot_id)}>查看周报提醒原件</button><button type="button" className="text-button" disabled={marking} onClick={() => void mark(notice)}>{notice.read_at ? "标为未读" : "标为已读"}</button></div>
    </article>)}
    {notices && !notices.total ? <p>当前范围尚无告警变化提醒。</p> : null}
    {notices && notices.total > notices.limit ? <div className="reparse-pages"><button type="button" disabled={!noticeOffset} onClick={() => setNoticeOffset(value => Math.max(0, value - 20))}>上一页提醒</button><button type="button" disabled={noticeOffset + notices.limit >= notices.total} onClick={() => setNoticeOffset(value => value + 20)}>下一页提醒</button></div> : null}
    {runRule ? <RunHistory key={runRule} ruleId={runRule} onClose={() => setRunRule(null)} onEvidence={onEvidence} /> : null}
    {taskId ? <MonitorTaskDialog key={taskId} kind="safety_gate" jobId={taskId} onClose={() => setTaskId(null)} /> : null}
  </section>;
}
