"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { SamrMonitorQuery, SamrMonitorRule, SamrMonitorRun, SamrNotification, SamrPage, SamrRuleDetail, SamrRuleSettings } from "@tire/domain-types";
import { DataTree } from "./reparse-review";
import { useSourceAccess } from "./source-status";
import { MonitorTaskDialog } from "./task-center";
import { taskResultLabel } from "./task-center-values";

const stamp = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "尚未记录";
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "中国召回监控操作未完成。";
type SaveIntent = { key: string; query: SamrMonitorQuery; settings: SamrRuleSettings; revision: number | null };

function RuleEditor({ id, onClose, onSaved }: { id: string | null; onClose: () => void; onSaved: (message: string) => void }) {
  const access = useSourceAccess();
  const [rule, setRule] = useState<SamrRuleDetail | null>(null);
  const [query, setQuery] = useState<SamrMonitorQuery>({ operation: "search", keyword: "轮胎", page_limit: 4, notice_limit: 60, text: "" });
  const [settings, setSettings] = useState<SamrRuleSettings>({ name: "", enabled: false, archived: false, interval_seconds: 21600 });
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
    void tireApi.samrRule(id, controller.signal).then(value => {
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
      if (!intent.current && next.enabled && !await access.ensure("samr-cn-recalls")) {
        throw new Error("来源当前无法在线采集，可先保存为暂停规则。");
      }
      if (controller.signal.aborted) return;
      const write = intent.current ?? { key: crypto.randomUUID(), query: { ...query, text: query.text.trim() }, settings: next, revision: rule?.revision ?? null };
      intent.current = write;
      setPending(write);
      const saved = id
        ? await tireApi.reviseSamrRule(id, write.revision!, write.settings, write.key, controller.signal)
        : await tireApi.createSamrRule(write.query, { name: write.settings.name, enabled: write.settings.enabled, interval_seconds: write.settings.interval_seconds }, write.key, controller.signal);
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
  return <section className="recall-rule-editor" aria-label="中国召回规则编辑">
    <div className="recall-section-heading"><h5>{id ? "编辑公告监控规则" : "新建公告监控规则"}</h5><button type="button" className="text-button" disabled={busy || !!pending} onClick={onClose}>关闭规则编辑</button></div>
    <p className="recall-help">保存后由Worker按计划核验配置范围。检索先两遍核对列表，提醒关键词匹配变化前后的标题和正文。</p>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {id && !pending ? <button type="button" className="text-button" disabled={busy} onClick={() => setReload(value => value + 1)}>重新读取规则</button> : null}
    {id && !rule ? <p role="status">正在读取规则…</p> : <form className="review-form" onSubmit={event => { event.preventDefault(); void save("save"); }}>
      <label><span>公告监控名称</span><input required maxLength={120} value={settings.name} disabled={locked} onChange={event => setSettings(value => ({ ...value, name: event.target.value }))} /></label>
      <label><span>提醒匹配关键词</span><input maxLength={120} value={query.text} disabled={locked || !!id} onChange={event => setQuery(value => ({ ...value, text: event.target.value }))} /></label>
      <label><span>监控范围</span><select value={query.operation} disabled={locked || !!id} onChange={event => setQuery(event.target.value === "search"
        ? { operation: "search", keyword: "轮胎", page_limit: 4, notice_limit: 60, text: query.text }
        : { operation: "notice", reference: "", text: query.text })}><option value="search">检索发现</option><option value="notice">指定公告</option></select></label>
      {query.operation === "search" ? <>
        <label><span>官方检索关键词</span><input maxLength={80} value={query.keyword} disabled={locked || !!id} onChange={event => setQuery(value => value.operation === "search" ? { ...value, keyword: event.target.value } : value)} /></label>
        <label><span>每遍最多检索页数</span><input type="number" required min={1} max={60} step={1} value={query.page_limit} disabled={locked || !!id} onChange={event => setQuery(value => value.operation === "search" ? { ...value, page_limit: Number(event.target.value) } : value)} /></label>
        <label><span>最多核验公告数量</span><input type="number" required min={1} max={900} step={1} value={query.notice_limit} disabled={locked || !!id} onChange={event => setQuery(value => value.operation === "search" ? { ...value, notice_limit: Number(event.target.value) } : value)} /></label>
      </> : <label><span>官方公告原生路径</span><input required maxLength={200} value={query.reference} disabled={locked || !!id} onChange={event => setQuery(value => value.operation === "notice" ? { ...value, reference: event.target.value } : value)} /></label>}
      <label><span>公告检查间隔（小时）</span><input type="number" required min={1} max={168} step={1} value={settings.interval_seconds / 3600} disabled={locked} onChange={event => setSettings(value => ({ ...value, interval_seconds: Number(event.target.value) * 3600 }))} /></label>
      <label className="review-checkbox"><input type="checkbox" checked={settings.enabled} disabled={locked || settings.archived} onChange={event => setSettings(value => ({ ...value, enabled: event.target.checked }))} />启用公告监控</label>
      <div className="variant-actions">
        {!settings.archived || pending ? <button type="submit" className="primary-button" disabled={busy || stale || !settings.name.trim()}>{pending ? "核对同一次保存结果" : "保存公告监控规则"}</button> : null}
        {id ? <button type="button" className="secondary-button" disabled={locked} onClick={() => void save(settings.archived ? "restore" : "archive")}>{settings.archived ? "恢复规则为暂停" : "归档公告监控规则"}</button> : null}
      </div>
    </form>}
    {rule ? <DataTree label="公告规则修订历史" value={{ revisions: rule.history, truncated: rule.history_truncated }} /> : null}
  </section>;
}

function RunHistory({ ruleId, onClose, onEvidence }: { ruleId: string; onClose: () => void; onEvidence: (id: string) => void }) {
  const [page, setPage] = useState<SamrPage<SamrMonitorRun> | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setPage(null);
    setError("");
    void tireApi.samrMonitorRuns(ruleId, offset, controller.signal).then(value => {
      if (!controller.signal.aborted) setPage(value);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [ruleId, offset]);
  return <section className="recall-evidence" aria-label="中国召回核验记录">
    <div className="recall-section-heading"><h5>公告核验记录</h5><button type="button" className="text-button" onClick={onClose}>收起核验记录</button></div>
    {error ? <p role="alert">{error}</p> : !page ? <p role="status">正在读取核验记录…</p> : null}
    {page?.items.map(run => <article className="recall-product" key={run.id}>
      <strong>{taskResultLabel(run.state)} · {stamp(run.finished_at)}</strong>
      <p>{run.coverage.status === "complete" ? "配置范围已完成" : "本轮覆盖不完整"} · 已核验 {run.coverage.checked_notice_count} / {run.coverage.selected_notice_count} 份公告 · 新增 {run.notification_count} 条提醒</p>
      {run.coverage.listing_consistency !== "not_applicable" ? <p>来源结果{run.coverage.source_results_fully_covered ? "已完整覆盖" : "完整覆盖尚未确认"} · 列表一致性 {run.coverage.listing_consistency}</p> : null}
      {run.reason ? <p className="review-warning">{run.reason}</p> : null}
      <DataTree label="所选公告与逐次核验状态" value={{ coverage: run.coverage, notices: run.selected_notices, checks: run.checks }} />
      {run.checks.filter(check => check.snapshot_id).map(check => <button type="button" className="text-button" key={check.query_id} onClick={() => onEvidence(check.snapshot_id!)}>查看{check.query.operation === "search" ? `检索第${check.query.page}页` : check.query.reference}核验原件</button>)}
    </article>)}
    {page && !page.total ? <p>尚无已完成的运行记录，可在任务进度中查看当前执行。</p> : null}
    {page && page.total > page.limit ? <div className="reparse-pages"><button type="button" disabled={!offset} onClick={() => setOffset(value => Math.max(0, value - 10))}>上一页运行</button><button type="button" disabled={offset + page.limit >= page.total} onClick={() => setOffset(value => value + 10)}>下一页运行</button></div> : null}
  </section>;
}

export function SamrMonitoring({ sessionReady, onEvidence }: { sessionReady: boolean; onEvidence: (id: string) => void }) {
  const [rules, setRules] = useState<SamrPage<SamrMonitorRule> | null>(null);
  const [notices, setNotices] = useState<SamrPage<SamrNotification> | null>(null);
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
    void Promise.all([tireApi.samrRules(archived, ruleOffset, controller.signal), tireApi.samrNotifications(unread, noticeOffset, controller.signal)]).then(([ruleList, noticeList]) => {
      if (controller.signal.aborted) return;
      if (ruleList.scope !== "session" || noticeList.scope !== "session" || ruleList.offset !== ruleOffset || noticeList.offset !== noticeOffset) throw new Error("公告监控分页与当前请求不一致。");
      setRules(ruleList); setNotices(noticeList);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [sessionReady, archived, unread, ruleOffset, noticeOffset, version]);

  async function mark(notice: SamrNotification) {
    if (mutation.current) return;
    const controller = new AbortController();
    mutation.current = controller;
    setMarking(true);
    try {
      await tireApi.markSamrNotification(notice.id, !notice.read_at, controller.signal);
      if (!controller.signal.aborted) setVersion(value => value + 1);
    } catch (cause) {
      if (!controller.signal.aborted) setError(errorText(cause));
    } finally {
      if (mutation.current === controller) mutation.current = null;
      if (!controller.signal.aborted) setMarking(false);
    }
  }

  return <section className="recall-discovery" aria-labelledby="samr-monitor-title">
    <h4 id="samr-monitor-title">中国召回监控与提醒</h4>
    <p className="recall-help">支持检索发现和指定公告监控，保存逐次核验和变化通知。具体SKU与生产批次适用性待核对。</p>
    <div className="variant-actions"><button type="button" className="secondary-button" disabled={!sessionReady || !!editor} onClick={() => setEditor({ id: null })}>新建公告监控规则</button><button type="button" className="text-button" disabled={!sessionReady || marking} onClick={() => setVersion(value => value + 1)}>刷新公告监控记录</button></div>
    {error ? <p className="inline-error" role="alert">{error}</p> : null}
    {message ? <p role="status">{message}</p> : null}
    {sessionReady && !rules && !error ? <p role="status">正在读取公告监控记录…</p> : null}
    {editor && sessionReady ? <RuleEditor key={editor.id || "new"} id={editor.id} onClose={() => setEditor(null)} onSaved={value => { setMessage(value); setVersion(current => current + 1); }} /> : null}
    <label className="review-checkbox"><input type="checkbox" checked={archived} onChange={event => { setArchived(event.target.checked); setRuleOffset(0); }} />查看已归档公告规则</label>
    {rules?.items.map(rule => <article className="recall-product" key={rule.id}>
      <h5>{rule.name}</h5><p>{rule.archived ? "已归档" : rule.enabled ? "已启用" : "已暂停"} · 每 {rule.interval_seconds / 3600} 小时 · {rule.query.operation === "search" ? `检索${rule.query.keyword || "全部公告"}，最多${rule.query.page_limit}页 / ${rule.query.notice_limit}份公告` : `公告${rule.query.reference}`} · {rule.query.text || "全部标题和正文变化"}</p>
      <p>下次计划 {stamp(rule.job.next_due_at)} · {rule.job.last_run ? taskResultLabel(rule.job.last_run.state) : "尚未运行"}</p>
      <div className="variant-actions"><button type="button" className="text-button" disabled={!!editor} onClick={() => setEditor({ id: rule.id })}>编辑公告规则</button><button type="button" className="text-button" onClick={() => setTaskId(rule.job.id)}>查看公告任务进度</button><button type="button" className="text-button" onClick={() => setRunRule(rule.id)}>读取公告核验记录</button></div>
    </article>)}
    {rules && !rules.total ? <p>当前范围尚无公告监控规则。</p> : null}
    {rules && rules.total > rules.limit ? <div className="reparse-pages"><button type="button" disabled={!ruleOffset} onClick={() => setRuleOffset(value => Math.max(0, value - 20))}>上一页规则</button><button type="button" disabled={ruleOffset + rules.limit >= rules.total} onClick={() => setRuleOffset(value => value + 20)}>下一页规则</button></div> : null}
    <h5>公告变化提醒</h5>
    <label className="review-checkbox"><input type="checkbox" checked={unread} onChange={event => { setUnread(event.target.checked); setNoticeOffset(0); }} />仅查看未读公告提醒</label>
    {notices?.items.map(notice => <article className="recall-product" key={notice.id}>
      <strong>{notice.rule_name} · {notice.observation.revision.notice.title}</strong>
      <p>{notice.observation.event?.kind === "first_observed" ? "系统首次观察" : "公告内容变化"} · {stamp(notice.delivered_at)} · {notice.read_at ? "已读" : "未读"}</p>
      <p>系统观察 {stamp(notice.observed_at)} · 排队 {stamp(notice.queued_at)} · 通知耗时 {notice.lag_seconds.toFixed(3)} 秒 · 内容版本 {notice.observation.revision.revision} · 适用性待核对</p>
      <DataTree label="公告提醒变化前后字段" value={notice.observation.event?.changes ?? {}} />
      <div className="variant-actions"><button type="button" className="text-button" onClick={() => onEvidence(notice.observation.snapshot_id)}>查看公告提醒原件</button>{notice.observation.event?.previous_snapshot_id ? <button type="button" className="text-button" onClick={() => onEvidence(notice.observation.event!.previous_snapshot_id!)}>查看变化前原件</button> : null}<button type="button" className="text-button" disabled={marking} onClick={() => void mark(notice)}>{notice.read_at ? "标为未读" : "标为已读"}</button></div>
    </article>)}
    {notices && !notices.total ? <p>当前范围尚无公告变化提醒。</p> : null}
    {notices && notices.total > notices.limit ? <div className="reparse-pages"><button type="button" disabled={!noticeOffset} onClick={() => setNoticeOffset(value => Math.max(0, value - 20))}>上一页提醒</button><button type="button" disabled={noticeOffset + notices.limit >= notices.total} onClick={() => setNoticeOffset(value => value + 20)}>下一页提醒</button></div> : null}
    {runRule ? <RunHistory key={runRule} ruleId={runRule} onClose={() => setRunRule(null)} onEvidence={onEvidence} /> : null}
    {taskId ? <MonitorTaskDialog key={taskId} kind="samr" jobId={taskId} onClose={() => setTaskId(null)} /> : null}
  </section>;
}
