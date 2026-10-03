"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, tireApi } from "@tire/api-client";
import type { RecallDiscoveryList, RecallDiscoveryNotification, RecallDiscoveryRule, RecallDiscoveryRuleDetail, RecallDiscoveryRuleSettings } from "@tire/domain-types";
import { MonitorTaskDialog } from "./task-center";
import { DataTree } from "./reparse-review";
import { SourceOnlineNotice, SourceStatus, useSourceAccess } from "./source-status";
import { DiscoveryPolicy, DiscoveryRunDialog, DiscoverySearchEvidence } from "./recall-discovery-runs";
import { discoveryCampaignValid, discoveryReason, discoveryRunLabel, normalizeDiscoverySearch, validDiscoverySearch } from "./recall-discovery-values";

const sourceId = "nhtsa-us-recalls";
const stamp = (value: string | null | undefined) => value ? new Date(value).toLocaleString("zh-CN") : "尚未记录";
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : "操作未完成，请核对后重试。";
export type DiscoveryRuleSeed = { search: string; sequence: number };
type EditorTarget = { id: string | null; search: string };
type SaveIntent = { key: string; id: string | null; revision: number | null; search: string; settings: RecallDiscoveryRuleSettings };

function DiscoveryRuleEditor({ target, onClose, onSaved }: { target: EditorTarget; onClose: () => void; onSaved: (message: string) => void }) {
  const sourceAccess = useSourceAccess();
  const [rule, setRule] = useState<RecallDiscoveryRuleDetail | null>(null);
  const [search, setSearch] = useState(target.search);
  const [settings, setSettings] = useState<RecallDiscoveryRuleSettings>({ name: target.search ? `名称发现：${target.search}`.slice(0, 120) : "", enabled: false, archived: false, interval_seconds: 21600 });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [reload, setReload] = useState(0);
  const [pending, setPending] = useState<SaveIntent | null>(null);
  const pendingRef = useRef<SaveIntent | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const mutation = useRef<AbortController | null>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); return () => mutation.current?.abort(); }, []);
  useEffect(() => {
    if (!target.id) return;
    const controller = new AbortController(); setRule(null); setError("");
    void tireApi.discoveryRule(target.id, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      setRule(value); setSearch(value.query.search);
      setSettings({ name: value.name, enabled: value.enabled, archived: value.archived, interval_seconds: value.interval_seconds }); setStale(false);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); });
    return () => controller.abort();
  }, [target.id, reload]);
  async function save(action: "save" | "archive" | "restore") {
    if (mutation.current || stale || (target.id && !rule) || !validDiscoverySearch(search)) return;
    const controller = new AbortController(); mutation.current = controller; setBusy(true); setError("");
    const next = { ...settings, name: settings.name.trim(), ...(action === "archive" ? { archived: true, enabled: false } : action === "restore" ? { archived: false, enabled: false } : {}) };
    try {
      if (!pendingRef.current && action === "save" && next.enabled && !await sourceAccess.ensure(sourceId)) { setError("来源当前不能在线采集。可取消启用后保存暂停规则，草稿仍保留。"); return; }
      if (controller.signal.aborted) return;
      const intent = pendingRef.current || { key: crypto.randomUUID(), id: rule?.id || null, revision: rule?.revision || null, search: normalizeDiscoverySearch(search), settings: next };
      pendingRef.current = intent; setPending(intent);
      const saved = intent.id ? await tireApi.reviseDiscoveryRule(intent.id, intent.revision!, intent.settings, controller.signal, intent.key)
        : await tireApi.createDiscoveryRule({ search: intent.search }, { name: intent.settings.name, enabled: intent.settings.enabled, interval_seconds: intent.settings.interval_seconds }, controller.signal, intent.key);
      if (controller.signal.aborted) return;
      if (!saved.write_result || !Number.isSafeInteger(saved.write_result.revision) || saved.write_result.revision < 1 || saved.write_result.revision > saved.revision || !saved.write_result.revision_id) throw new Error("服务端尚未返回可确认的原操作修订。");
      pendingRef.current = null; setPending(null);
      onSaved(saved.revision > saved.write_result.revision ? `已确认本次操作保存于修订 #${saved.write_result.revision}；当前规则已更新为 #${saved.revision}，请按最新记录核对。` : `已确认名称规则保存于修订 #${saved.write_result.revision}。保存规则不会立即启动扫描。`);
      onClose();
    } catch (cause) {
      if (controller.signal.aborted) return;
      if (!(cause instanceof ApiError) || cause.status >= 500) setError(pendingRef.current ? "保存结果尚未确认。草稿与本次请求已固定；使用“核对同一次保存结果”重试同一操作，不会另建规则或追加重复修订。" : "尚未完成来源状态核对，未发送保存请求；草稿仍保留，可以重试。");
      else { pendingRef.current = null; setPending(null); setError(errorText(cause)); if (cause.status === 409) setStale(true); }
    } finally { if (mutation.current === controller) mutation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  const locked = busy || stale || !!pending || !!rule?.archived;
  return <section className="recall-rule-editor discovery-rule-editor" aria-labelledby="discovery-rule-heading"><div className="recall-section-heading"><h3 id="discovery-rule-heading" ref={heading} tabIndex={-1}>{target.id ? "编辑名称发现规则" : "创建名称发现规则"}</h3><button type="button" className="text-button" disabled={busy || !!pending} onClick={onClose}>关闭名称规则编辑</button></div>
    <SourceStatus sourceId={sourceId} /><SourceOnlineNotice sourceId={sourceId} /><p className="review-boundary">规则只属于当前会话，默认暂停。这里只保存关键词和计划；不会立即扫描、核验公告或创建已选公告规则。手动检索的单页结果和历史快照都不会成为扫描基线。</p>
    {error ? <p className="inline-error" role="alert">{error}{target.id && !pending ? <button type="button" className="text-button" disabled={busy} onClick={() => setReload(value => value + 1)}>放弃当前修改并重新读取规则</button> : null}</p> : null}
    {pending ? <p className="review-boundary" role="status">本次请求与草稿已固定。页面切换会保留编辑内容；核对完成前暂不接受新的保存意图。</p> : null}
    {target.id && !rule ? <p role="status">正在读取名称规则…</p> : <form className="review-form" onSubmit={event => { event.preventDefault(); void save("save"); }}>
      <label><span>名称规则名称</span><input aria-label="名称规则名称" required maxLength={120} value={settings.name} disabled={locked} onChange={event => setSettings(value => ({ ...value, name: event.target.value }))} /></label>
      <label><span>持续发现的品牌 / 型号关键词</span><input aria-label="持续发现的品牌 / 型号关键词" required maxLength={120} autoComplete="off" value={search} disabled={locked || !!target.id} onChange={event => setSearch(event.target.value)} /></label>
      <p className="recall-help">仅按名称匹配候选，不限定在手动检索的当前页。保存后关键词固定；更换关键词请新建规则，原记录仍可追溯。</p>
      <label><span>名称扫描间隔（1–168 小时）</span><input aria-label="名称扫描间隔（1–168 小时）" type="number" required min={1} max={168} step={1} value={settings.interval_seconds / 3600} disabled={locked} onChange={event => setSettings(value => ({ ...value, interval_seconds: Number(event.target.value) * 3600 }))} /></label>
      <label className="review-checkbox"><input type="checkbox" checked={settings.enabled} disabled={locked || (!settings.enabled && !sourceAccess.canQuery(sourceId))} onChange={event => setSettings(value => ({ ...value, enabled: event.target.checked }))} />启用此名称发现规则</label>
      <div className="variant-actions">{!rule?.archived || pending ? <button type="submit" className="primary-button" disabled={busy || stale || !settings.name.trim() || !validDiscoverySearch(search) || settings.interval_seconds < 3600 || settings.interval_seconds > 604800}>{busy ? "正在保存…" : pending ? "核对同一次保存结果" : "保存名称发现规则"}</button> : null}{rule ? <button type="button" className="secondary-button" disabled={busy || stale || !!pending} onClick={() => void save(rule.archived ? "restore" : "archive")}>{rule.archived ? "恢复名称规则为暂停" : "归档名称规则"}</button> : null}</div>
    </form>}
    {rule ? <section className="recall-history"><h4>名称规则修订历史</h4>{rule.history_truncated ? <p className="review-warning">这里只展示最近 50 条修订。</p> : null}{rule.history.map(item => <details key={item.revision}><summary>#{item.revision} · {item.archived ? "已归档" : item.enabled ? "已启用" : "已暂停"} · {stamp(item.created_at)}</summary><p>{item.name} · 每 {item.interval_seconds / 3600} 小时</p></details>)}</section> : null}
  </section>;
}

export default function RecallDiscoveryMonitoring({ sessionReady, seed, onSeedHandled, onChoose }: { sessionReady: boolean; seed: DiscoveryRuleSeed | null; onSeedHandled: () => void; onChoose: (campaign: string) => void }) {
  const [rules, setRules] = useState<RecallDiscoveryList<RecallDiscoveryRule> | null>(null);
  const [notices, setNotices] = useState<RecallDiscoveryList<RecallDiscoveryNotification> | null>(null);
  const [ruleOffset, setRuleOffset] = useState(0);
  const [noticeOffset, setNoticeOffset] = useState(0);
  const [archived, setArchived] = useState(false);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [draftNotice, setDraftNotice] = useState("");
  const [savedNotice, setSavedNotice] = useState("");
  const [editor, setEditor] = useState<EditorTarget | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [marking, setMarking] = useState(false);
  const mutation = useRef<AbortController | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => () => mutation.current?.abort(), []);
  useEffect(() => {
    if (!seed) return;
    if (editor) setDraftNotice("已有未保存的名称规则草稿，已保留原内容。请先保存或关闭当前编辑，再创建另一个关键词规则。");
    else { setEditor({ id: null, search: normalizeDiscoverySearch(seed.search) }); setDraftNotice(""); }
    onSeedHandled();
  }, [seed, editor, onSeedHandled]);
  useEffect(() => {
    if (!sessionReady) return;
    const controller = new AbortController(); setLoading(true); setError(""); setRules(null); setNotices(null);
    void Promise.all([tireApi.discoveryRules(archived, ruleOffset, controller.signal), tireApi.discoveryNotifications(unreadOnly, noticeOffset, controller.signal)]).then(([ruleList, noticeList]) => {
      if (controller.signal.aborted) return;
      if (ruleList.scope !== "session" || noticeList.scope !== "session" || ruleList.offset !== ruleOffset || noticeList.offset !== noticeOffset) throw new Error("名称监控记录与当前会话或分页不匹配。");
      setRules(ruleList); setNotices(noticeList);
    }).catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [sessionReady, archived, unreadOnly, ruleOffset, noticeOffset, version]);
  async function mark(notice: RecallDiscoveryNotification) {
    if (mutation.current) return;
    const controller = new AbortController(); mutation.current = controller; setMarking(true); setError("");
    try { await tireApi.markDiscoveryNotification(notice.id, !notice.read_at, controller.signal); if (!controller.signal.aborted) setVersion(value => value + 1); }
    catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (mutation.current === controller) mutation.current = null; if (!controller.signal.aborted) setMarking(false); }
  }
  function closeEditor() { setEditor(null); setDraftNotice(""); heading.current?.focus({ preventScroll: true }); }
  return <section className="recall-discovery-monitoring" aria-labelledby="discovery-monitor-title"><div className="recall-section-heading"><h3 id="discovery-monitor-title" ref={heading} tabIndex={-1}>名称发现规则与候选提醒</h3><div className="variant-actions"><button type="button" className="text-button" disabled={!sessionReady || loading || marking} onClick={() => setVersion(value => value + 1)}>刷新名称监控记录</button><button type="button" className="secondary-button" disabled={!sessionReady || !!editor} onClick={() => setEditor({ id: null, search: "" })}>创建名称发现规则</button></div></div>
    <p className="review-boundary">这里按品牌或型号关键词持续发现候选，与跟踪固定公告内容的规则分别保存。仅当前会话可见；提醒不代表官方刚发布，也不确定您的轮胎受影响。不会自动核验公告、自动采纳公告或发送外部消息。</p><DiscoveryPolicy />
    {draftNotice ? <p className="review-warning" role="status">{draftNotice}</p> : null}{savedNotice ? <p className="review-saved" role="status">{savedNotice}</p> : null}{error ? <p className="inline-error" role="alert">{error}</p> : null}
    {editor ? <DiscoveryRuleEditor key={editor.id || "new"} target={editor} onClose={closeEditor} onSaved={message => { setSavedNotice(message); setRuleOffset(0); setVersion(value => value + 1); }} /> : null}
    <div className="discovery-list-filters"><label><span>名称规则范围</span><select aria-label="名称规则范围" value={archived ? "archived" : "active"} onChange={event => { setArchived(event.target.value === "archived"); setRuleOffset(0); }}><option value="active">使用中的名称规则</option><option value="archived">已归档名称规则</option></select></label><label className="review-checkbox"><input type="checkbox" checked={unreadOnly} onChange={event => { setUnreadOnly(event.target.checked); setNoticeOffset(0); }} />仅看未读候选提醒</label></div>
    {loading ? <p role="status">正在读取名称监控记录…</p> : <><h4>名称规则 · {rules?.total ?? 0}</h4>{rules?.items.map(rule => <article className="recall-rule discovery-rule" key={rule.id}><div className="recall-section-heading"><h4>{rule.name}</h4><span className="tag quiet">{rule.archived ? "已归档" : rule.enabled ? "已启用" : "已暂停"}</span></div><p>名称关键词：{rule.query.search} · 每 {rule.interval_seconds / 3600} 小时 · 修订 #{rule.revision}</p><p className="recall-help">本规则计划：{rule.enabled && !rule.archived ? stamp(rule.job.next_due_at) : "未启用"} · {rule.job.last_run ? discoveryRunLabel(rule.job.last_run) : "尚无扫描终态；保存规则不代表已经运行"}</p><p className="recall-help">最近完整基线：{rule.baseline ? stamp(rule.baseline.finished_at) : "尚未建立"}。不完整扫描不会更新此基线。</p>{rule.job.last_run?.reason ? <p className="recall-help">最近原因：{discoveryReason(rule.job.last_run.reason)}</p> : null}<div className="variant-actions"><button type="button" className="text-button" onClick={() => setTaskId(rule.job.id)}>查看名称任务运行</button>{rule.job.last_run ? <button type="button" className="text-button" onClick={() => setRunId(rule.job.last_run!.id)}>查看最近扫描覆盖</button> : null}<button type="button" className="text-button" disabled={!!editor} onClick={() => setEditor({ id: rule.id, search: rule.query.search })}>编辑名称规则与历史</button></div></article>)}{!rules?.items.length ? <p className="recall-empty">当前页没有名称发现规则。查阅历史不会创建规则。</p> : null}
      {rules ? <div className="reparse-pages"><button type="button" className="text-button" disabled={!ruleOffset} onClick={() => setRuleOffset(value => Math.max(0, value - 20))}>上一页名称规则</button><span>第 {Math.floor(ruleOffset / 20) + 1} 页</span><button type="button" className="text-button" disabled={ruleOffset + rules.items.length >= rules.total} onClick={() => setRuleOffset(value => value + 20)}>下一页名称规则</button></div> : null}
      <h4>新增观察候选提醒 · {notices?.total ?? 0}</h4><p className="recall-help">首次完整基线不发送已有候选提醒。后续完整扫描首次记录的公告才提醒；同一公告消失后再次出现不重复提醒。未读状态与公告是否核验分别记录。</p>
      {notices?.items.map(notice => <article className="recall-notification discovery-notification" key={notice.id}><div className="recall-section-heading"><h4>{notice.rule_name} · 首次观察到候选</h4><span className="tag quiet">{notice.read_at ? "已读" : "未读"}</span></div><p><strong>{notice.candidate.campaign_number}</strong> · 关键词：{notice.query.search}</p><p className="recall-help">首次观察：{stamp(notice.candidate.first_seen_at)} · 提醒送达：{stamp(notice.delivered_at)} · 规则修订 #{notice.rule_revision}</p><p className="review-boundary">仅名称匹配的候选。选用编号只进入在线查询并填入编号，需要再次明确点击“在线核验公告”；不会自动查询或创建固定公告监控。</p><DataTree label="候选公告字段" value={notice.candidate.campaign} /><DataTree label="匹配产品与检索证据引用" value={notice.candidate.evidence} /><div className="variant-actions"><button type="button" className="secondary-button" disabled={!discoveryCampaignValid(notice.candidate.campaign_number)} onClick={() => onChoose(notice.candidate.campaign_number)}>选用此编号，准备在线核验</button><button type="button" className="text-button" onClick={() => setRunId(notice.candidate.first_seen_run_id)}>查看首次记录扫描</button><button type="button" className="text-button" onClick={() => setTaskId(notice.job_id)}>查看名称任务运行</button><button type="button" className="text-button" disabled={marking} onClick={() => void mark(notice)}>标记候选提醒为{notice.read_at ? "未读" : "已读"}</button></div>{notice.candidate.evidence.map(evidence => <button type="button" className="text-button" key={evidence.page_id} onClick={() => setEvidenceId(evidence.snapshot_id)}>查看候选检索页原文 · {evidence.product_ids.length} 个匹配产品</button>)}</article>)}
      {!notices?.items.length ? <p className="recall-empty">当前页没有候选提醒；可能尚未建立完整基线、扫描不完整或尚无新增观察，不能据此判断没有召回。</p> : null}{notices ? <div className="reparse-pages"><button type="button" className="text-button" disabled={!noticeOffset || marking} onClick={() => setNoticeOffset(value => Math.max(0, value - 20))}>上一页候选提醒</button><span>第 {Math.floor(noticeOffset / 20) + 1} 页</span><button type="button" className="text-button" disabled={marking || noticeOffset + notices.items.length >= notices.total} onClick={() => setNoticeOffset(value => value + 20)}>下一页候选提醒</button></div> : null}
    </>}
    {evidenceId ? <DiscoverySearchEvidence key={evidenceId} id={evidenceId} onClose={() => setEvidenceId(null)} /> : null}
    {taskId ? <MonitorTaskDialog key={taskId} kind="recall_discovery" jobId={taskId} onClose={() => setTaskId(null)} /> : null}
    {runId ? <DiscoveryRunDialog key={runId} id={runId} onClose={() => setRunId(null)} onChoose={onChoose} /> : null}
  </section>;
}
