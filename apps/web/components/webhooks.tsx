"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ApiError, tireApi, WebhookContractError } from "@tire/api-client";
import type { Webhook, WebhookChannel, WebhookCreate, WebhookDelivery, WebhookDeliveryList, WebhookList, WebhookOperation, WebhookTarget, WebhookTargets } from "@tire/domain-types";
import { useWorkbenchAuth } from "./auth";
import "./webhooks.css";

const pointerKey = "tire-webhook-operation@1";
const validKey = (value: string) => /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(value);
const stamp = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "未记录";
const channelLabels: Record<WebhookChannel, string> = { tire_monitor: "本机共享轮胎提醒", recall_monitor: "本人召回规则通知", interest: "本人兴趣通知（当前九域）" };
const channelHelp: Record<WebhookChannel, string> = {
  tire_monitor: "接收本机共享轮胎规则的新提醒引用，不限于本人关注的规格。",
  recall_monitor: "仅接收通知创建时归属本人账户且已形成 RecallEvent 的规则通知；不含召回发现候选提醒。",
  interest: "仅接收通知创建时归属本人账户的兴趣通知引用，包含测试等九域；不外发来源事实或兴趣名称。",
};
const readinessLabels = { ready: "具备派送条件", paused: "暂停", archived: "已归档", target_missing: "目标已移出目录", key_unavailable: "目标签名配置不可用", policy_changed: "接收策略已变化", owner_missing: "账户已失效", configuration_invalid: "目标目录无效" };
const deliveryLabels = { pending: "等待派送", inflight: "请求进行中", delivered: "HTTP确认接收", failed: "本轮派送失败", blocked: "派送受阻", cancelled: "后续派送已取消" };
const attemptLabels = { inflight: "请求进行中", delivered: "HTTP确认接收", retryable_failure: "可重试失败", failed: "失败", blocked: "受阻", unknown: "接收情况未知", cancelled: "后续派送已取消" };
const actionLabels = { create: "创建", edit: "编辑", pause: "暂停", resume: "启用", archive: "归档", restore: "恢复为暂停", retry: "人工重试", cancel: "取消后续派送" };
const deliveryBoundary = "采用 at-least-once 投递，接收方须按稳定 delivery ID 去重。超时或进程中断时，对方可能已收到；暂停、取消或关闭页面不能撤回已发请求。HTTP 2xx 只确认接收，不证明对方业务处理完成。";
function safeError(cause: unknown) {
  if (cause instanceof WebhookContractError) return cause.message;
  if (cause instanceof ApiError) {
    if (cause.status === 401 || cause.status === 403) return "当前账户权限未确认，请重新核对登录状态。";
    if (cause.status === 404) return "未找到本账户的记录。恢复返回未找到也不代表原请求一定未执行，请保留UUID稍后只读核对。";
    if (cause.status === 409) return "修订、目标策略或投递状态已变化，请先读取当前记录；没有自动重新提交。";
    if (cause.status === 422) return "输入或确认未通过核对，请保留操作标识并检查当前记录。";
  }
  return "连接或响应未确认。请保留UUID并只读恢复；不会自动重复写入或发送测试消息。";
}

export default function WebhookCenter() {
  const auth = useWorkbenchAuth();
  if (!auth.ready || !auth.state.authenticated) return <section className="webhook-panel"><h3>对外变化通知 · Webhook</h3><p>登录并确认当前账户后可管理本人订阅；默认不外发。</p></section>;
  return <PrivateWebhooks key={auth.ownerEpoch} ownerEpoch={auth.ownerEpoch} />;
}

function PrivateWebhooks({ ownerEpoch }: { ownerEpoch: number }) {
  const auth = useWorkbenchAuth(), title = useId();
  const [targets, setTargets] = useState<WebhookTargets | null>(null), [list, setList] = useState<WebhookList | null>(null);
  const [offset, setOffset] = useState(0), [refresh, setRefresh] = useState(0), [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null), [selected, setSelected] = useState<Webhook | null>(null);
  const [deliveryPage, setDeliveryPage] = useState<WebhookDeliveryList | null>(null), [deliveryOffset, setDeliveryOffset] = useState(0);
  const [deliveryId, setDeliveryId] = useState<string | null>(null), [detail, setDetail] = useState<WebhookDelivery | null>(null);
  const [viewLoading, setViewLoading] = useState(false), [editor, setEditor] = useState<"create" | "edit" | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [receipt, setReceipt] = useState<WebhookOperation | null>(null), [pendingKey, setPendingKey] = useState<string | null>(null), [recovery, setRecovery] = useState("");
  const [resumeConsent, setResumeConsent] = useState<string | null>(null), [deliveryConsent, setDeliveryConsent] = useState(false);
  const mutation = useRef<AbortController | null>(null), reads = useRef(new Set<AbortController>()), generation = useRef(0), unresolved = useRef<string | null>(null);
  const selectionRequest = useRef<AbortController | null>(null), deliveryRequest = useRef<AbortController | null>(null);
  const currentOwner = () => auth.isCurrentOwner(ownerEpoch);
  const locked = busy || pendingKey !== null;
  const target = targets?.items.find(item => item.id === selected?.target_id);
  const resumeBinding = selected && target ? JSON.stringify([selected.id, selected.revision, selected.channels, target.id, target.endpoint_host, target.policy_fingerprint]) : null;
  function remember(key: string, pending: boolean) {
    try { sessionStorage.setItem(pointerKey, JSON.stringify({ schema: pointerKey, actor_id: auth.state.user?.id, key, unresolved: pending })); } catch { /* UUID can be copied or entered manually. */ }
  }
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(pointerKey), pointer: unknown = raw ? JSON.parse(raw) : null;
      if (pointer && typeof pointer === "object" && "actor_id" in pointer && pointer.actor_id === auth.state.user?.id && "key" in pointer && typeof pointer.key === "string" && validKey(pointer.key)) {
        setRecovery(pointer.key);
        if ("unresolved" in pointer && pointer.unresolved === true) { unresolved.current = pointer.key; setPendingKey(pointer.key); }
      }
    } catch { /* No private subscription data is stored in this pointer. */ }
    return () => { mutation.current?.abort(); reads.current.forEach(controller => controller.abort()); generation.current++; };
  }, [auth.state.user?.id]);
  useEffect(() => {
    const controller = new AbortController(); reads.current.add(controller); setLoading(true); setError("");
    const current = () => !controller.signal.aborted && auth.isCurrentOwner(ownerEpoch);
    void Promise.all([tireApi.webhookTargets(controller.signal), tireApi.webhooks(offset, 20, controller.signal)]).then(([catalog, records]) => {
      if (current()) { setTargets(catalog); setList(records); }
    }).catch(cause => { if (current()) setError(safeError(cause)); }).finally(() => { reads.current.delete(controller); if (current()) setLoading(false); });
    return () => controller.abort();
  }, [offset, refresh, ownerEpoch, auth.isCurrentOwner]);
  useEffect(() => {
    setSelected(null); setDeliveryPage(null); setDetail(null); setResumeConsent(null); setDeliveryConsent(false);
    if (!selectedId) { setViewLoading(false); return; }
    const controller = new AbortController(); selectionRequest.current = controller; reads.current.add(controller); setViewLoading(true);
    const current = () => !controller.signal.aborted && auth.isCurrentOwner(ownerEpoch);
    void Promise.all([tireApi.webhook(selectedId, controller.signal), tireApi.webhookDeliveries(selectedId, deliveryOffset, 20, controller.signal)]).then(([record, page]) => {
      if (current()) { setSelected(record); setDeliveryPage(page); }
    }).catch(cause => { if (current()) setError(safeError(cause)); }).finally(() => { reads.current.delete(controller); if (current()) setViewLoading(false); });
    return () => controller.abort();
  }, [selectedId, deliveryOffset, refresh, ownerEpoch, auth.isCurrentOwner]);
  useEffect(() => {
    setDetail(null); setDeliveryConsent(false);
    if (!selectedId || !deliveryId) return;
    const controller = new AbortController(); deliveryRequest.current = controller; reads.current.add(controller);
    const current = () => !controller.signal.aborted && auth.isCurrentOwner(ownerEpoch);
    void tireApi.webhookDelivery(selectedId, deliveryId, controller.signal).then(value => { if (current()) setDetail(value); })
      .catch(cause => { if (current()) setError(safeError(cause)); }).finally(() => reads.current.delete(controller));
    return () => controller.abort();
  }, [selectedId, deliveryId, refresh, ownerEpoch, auth.isCurrentOwner]);
  async function perform(work: (signal: AbortSignal) => Promise<WebhookOperation>, key: string, recoveryOnly = false) {
    if (mutation.current || !currentOwner() || !recoveryOnly && unresolved.current) return;
    const controller = new AbortController(), epoch = ++generation.current; mutation.current = controller;
    const current = () => !controller.signal.aborted && mutation.current === controller && generation.current === epoch && currentOwner();
    if (!recoveryOnly) { unresolved.current = key; setPendingKey(key); }
    setRecovery(key); remember(unresolved.current || key, !!unresolved.current); setBusy(true); setError(""); setResumeConsent(null); setDeliveryConsent(false);
    try {
      const value = await work(controller.signal);
      if (current()) {
        setReceipt(value);
        if (!unresolved.current || value.idempotency_key === unresolved.current) {
          unresolved.current = null; setPendingKey(null); remember(key, false); setEditor(null);
          selectionRequest.current?.abort(); deliveryRequest.current?.abort(); setSelected(null); setDetail(null); setDeliveryPage(null);
          setSelectedId(value.resource_type === "webhook" ? value.resource_id : value.response.webhook_id);
          setDeliveryId(value.resource_type === "delivery" ? value.resource_id : null); setDeliveryOffset(0); setRefresh(value => value + 1);
        }
      }
    } catch (cause) { if (current()) setError(safeError(cause)); }
    finally { if (current()) { mutation.current = null; setBusy(false); } }
  }
  function write(work: (key: string, signal: AbortSignal) => Promise<WebhookOperation>) {
    if (mutation.current || unresolved.current || !currentOwner()) return;
    const key = crypto.randomUUID(); void perform(signal => work(key, signal), key);
  }
  function state(action: "pause" | "resume" | "archive" | "restore") {
    if (!selected || locked || action === "resume" && (!resumeConsent || resumeConsent !== resumeBinding || !target?.ready)) return;
    const record = selected;
    write((key, signal) => tireApi.webhookState(record.id, { expected_revision: record.revision, action, target_fingerprint: action === "resume" ? target!.policy_fingerprint : null, acknowledged_external_delivery: action === "resume" }, key, signal));
  }
  function actOnDelivery(action: "retry" | "cancel") {
    if (!selected || !detail || locked || !deliveryConsent) return;
    const record = selected, delivery = detail;
    write((key, signal) => tireApi.webhookDeliveryAction(record.id, delivery.id, action, { expected_attempts: delivery.attempts, acknowledged: true }, key, signal));
  }
  function choose(id: string) { if (busy) return; selectionRequest.current?.abort(); deliveryRequest.current?.abort(); setSelected(null); setDeliveryPage(null); setDetail(null); setSelectedId(id); setDeliveryId(null); setDeliveryOffset(0); setEditor(null); setReceipt(null); setResumeConsent(null); setDeliveryConsent(false); setError(""); if (id === selectedId) setRefresh(value => value + 1); }
  const retryable = !!selected && !!detail && selected.enabled && !selected.archived && selected.readiness === "ready" && selected.revision === detail.webhook_revision && ["failed", "blocked"].includes(detail.state) && detail.max_attempts < 20;
  const cancellable = !!detail && !["delivered", "cancelled"].includes(detail.state);
  return <section className="webhook-panel" data-testid="webhooks-panel" aria-labelledby={title}>
    <div className="webhook-heading"><div><span className="eyebrow">OUTBOUND / REFERENCE ONLY</span><h3 id={title}>对外变化通知 · Webhook</h3></div><button type="button" className="text-button" data-testid="webhooks-refresh" disabled={busy} onClick={() => setRefresh(value => value + 1)}>只读刷新</button></div>
    <p>订阅属于当前账户，只对启用后的新通知建立投递。页面和只读刷新不会访问接收端、发送测试消息或补发旧通知。定时派送需要独立 Worker 运行。</p>
    <p className="review-boundary">{deliveryBoundary}</p>
    {error ? <p className="inline-error" role="alert" data-testid="webhooks-error">{error}</p> : null}
    {loading ? <p role="status">正在读取本人订阅与受管理目标…</p> : null}
    {targets ? <div className="webhook-catalog" data-testid="webhooks-targets"><strong>受管理接收目录 · {targets.items.length} 项</strong><p>{targets.notice}</p>
      {targets.catalog_state === "empty" ? <p>默认目录为空，不创建订阅、不外发。需要由本机操作者配置固定合法目标；此处不接受URL或签名密钥。</p> : targets.catalog_state === "invalid" ? <p className="review-warning">目录无效，已停止使用其中的目标。既有记录保留，可暂停、归档或取消后续派送。</p> : <ul>{targets.items.map(item => <li key={item.id}>{item.title} · <code>{item.endpoint_host}</code> · {item.ready ? "目标配置就绪（不证明对方可达）" : "签名配置不可用，仅可保存暂停草稿"}</li>)}</ul>}
    </div> : null}
    <button type="button" className="secondary-button" data-testid="webhooks-create" disabled={locked || !targets?.items.length || targets.catalog_state !== "ready"} onClick={() => { setEditor("create"); setReceipt(null); }}>新建暂停订阅</button>
    {list ? <div className="webhook-subscriptions" aria-label="本人Webhook订阅"><p>本人订阅 {list.total} 项；每账户最多16个未归档订阅。</p>{list.items.map(item => <article className="webhook-row" key={item.id}><div><strong>{item.name}</strong><span className="tag quiet">{readinessLabels[item.readiness]}</span><p>{item.endpoint_host} · 修订 #{item.revision} · {item.channels.map(channel => channelLabels[channel]).join("、")}</p></div><button type="button" className="text-button" data-webhook-id={item.id} disabled={busy} onClick={() => choose(item.id)}>读取订阅与投递</button></article>)}<PageControls offset={offset} total={list.total} disabled={busy || loading} onPage={setOffset} /></div> : null}
    {viewLoading ? <p role="status">正在核对当前订阅和投递状态…</p> : null}
    {selected ? <section className="webhook-detail" data-testid="webhook-detail"><h4>{selected.name} · 修订 #{selected.revision}</h4><p><code>{selected.endpoint_host}</code> · {readinessLabels[selected.readiness]} · {selected.channels.map(channel => channelLabels[channel]).join("、")}</p><p>{selected.notice}</p>
      <p>队列容量为每订阅1000个未终态投递。已省略 {selected.suppressed_count} 条，最近省略 {stamp(selected.last_suppressed_at)}；省略不是已送达。终态历史仍会增长。</p>
      <details><summary>当前策略绑定</summary><p className="webhook-mono">订阅 {selected.id}<br />修订 {selected.revision_id}<br />目标 {selected.target_id}<br />策略指纹 {selected.target_fingerprint || "未配置，暂停草稿"}</p></details>
      <div className="webhook-actions"><button type="button" className="text-button" disabled={locked || selected.archived} onClick={() => setEditor("edit")}>编辑设置</button>{selected.archived ? <button type="button" className="secondary-button" disabled={locked} onClick={() => state("restore")}>恢复为暂停订阅</button> : <><button type="button" className="secondary-button" data-testid="webhooks-pause" disabled={locked || !selected.enabled} onClick={() => state("pause")}>暂停订阅</button><button type="button" className="text-button" data-testid="webhooks-archive" disabled={locked} onClick={() => state("archive")}>归档订阅</button></>}</div>
      {!selected.enabled && !selected.archived ? <div className="webhook-enable"><label className="webhook-check"><input type="checkbox" data-testid="webhooks-resume-consent" checked={resumeConsent !== null && resumeConsent === resumeBinding} disabled={locked || !target?.ready} onChange={event => setResumeConsent(event.target.checked ? resumeBinding : null)} /><span>允许此订阅把上述频道的未来通知引用发送至 <strong>{target?.endpoint_host || selected.endpoint_host}</strong>。私人通知引用本身也会外发；不包含来源事实、名称、账户ID或凭据。</span></label><button type="button" className="primary-button" data-testid="webhooks-resume" disabled={locked || !target?.ready || !resumeConsent || resumeConsent !== resumeBinding} onClick={() => state("resume")}>确认并启用订阅</button></div> : null}
      <p className="review-boundary">保存编辑、暂停、启用、归档或恢复都会追加新修订并取消旧未终态队列；恢复不补发旧通知。开始HTTP后的请求无法撤回。</p>
      {deliveryPage ? <div className="webhook-deliveries"><h4>投递历史 · {deliveryPage.total} 项</h4>{deliveryPage.items.length ? deliveryPage.items.map(item => <article className="webhook-row" key={item.id}><div><strong>{deliveryLabels[item.state]}</strong><p>{channelLabels[item.channel]} · 尝试 {item.attempts}/{item.max_attempts} · {stamp(item.created_at)}</p><p className="webhook-mono">{item.id}{item.error_code ? ` · ${item.error_code}` : ""}</p></div><button type="button" className="text-button" data-webhook-delivery-id={item.id} disabled={busy} onClick={() => { deliveryRequest.current?.abort(); setDetail(null); setDeliveryId(item.id); setDeliveryConsent(false); if (item.id === deliveryId) setRefresh(value => value + 1); }}>读取冻结正文与尝试</button></article>) : <p>尚无投递。暂停订阅、旧通知或匿名私人通知不会补发；省略统计另列于上方。</p>}<PageControls offset={deliveryOffset} total={deliveryPage.total} disabled={busy || viewLoading} onPage={value => { setDeliveryId(null); setDeliveryOffset(value); }} /></div> : null}
      {detail ? <section className="webhook-delivery" data-testid="webhook-delivery"><h4>{deliveryLabels[detail.state]} · 冻结投递记录</h4><p>订阅修订 #{detail.webhook_revision} · 已尝试 {detail.attempts} 次／本轮预算 {detail.max_attempts} 次 · 下次 {stamp(detail.next_attempt_at)}</p><p>{deliveryBoundary}</p><details open><summary>完整冻结正文 · 仅通知引用</summary><pre className="webhook-mono">{JSON.stringify(detail.body, null, 2)}</pre><p className="webhook-mono">正文 SHA-256 {detail.body_sha256}</p></details><h5>全部尝试</h5>{detail.attempt_history.length ? <ol>{detail.attempt_history.map(attempt => <li key={attempt.number}>#{attempt.number} {attemptLabels[attempt.state]} · {stamp(attempt.started_at)} → {stamp(attempt.completed_at)}{attempt.http_status ? ` · HTTP ${attempt.http_status}` : ""}{attempt.error_code ? ` · ${attempt.error_code}` : ""}</li>)}</ol> : <p>尚无HTTP尝试。</p>}
        <label className="webhook-check"><input type="checkbox" data-testid="webhooks-delivery-consent" checked={deliveryConsent} disabled={locked} onChange={event => setDeliveryConsent(event.target.checked)} /><span>我确认操作此冻结投递。重试可能重复送到对方，使用相同delivery ID与正文；取消只阻止后续派送，不能追回已发请求。</span></label><div className="webhook-actions"><button type="button" className="secondary-button" data-testid="webhooks-retry" disabled={locked || !deliveryConsent || !retryable} onClick={() => actOnDelivery("retry")}>人工增加最多5次尝试</button><button type="button" className="text-button" data-testid="webhooks-cancel" disabled={locked || !deliveryConsent || !cancellable} onClick={() => actOnDelivery("cancel")}>取消后续派送</button></div><p>重试仅限同一有效修订、原策略仍可用、未过7天TTL且失败或受阻的投递，总尝试预算最多20次；服务器会再次核对。缺配置或归档后仍可取消。</p>
      </section> : null}
    </section> : null}
    {editor && targets ? <WebhookEditor key={`${editor}:${selected?.id}:${selected?.revision}`} catalog={targets.items} record={editor === "edit" ? selected : null} disabled={locked} onClose={() => setEditor(null)} onSave={payload => {
      if (editor === "edit" && selected) { const record = selected; const { target_id, ...settings } = payload; write((key, signal) => tireApi.editWebhook(record.id, { ...settings, expected_revision: record.revision }, key, signal)); }
      else write((key, signal) => tireApi.createWebhook(payload, key, signal));
    }} /> : null}
    {pendingKey ? <div className="webhook-recovery-warning" role="status" data-testid="webhooks-pending"><p>写入结果待核对，操作UUID <code>{pendingKey}</code> 已保留。其他写入暂时锁定；请只读恢复同一动作，不重新POST。读取其他UUID不会解除本次锁定。</p><button type="button" className="secondary-button" data-testid="webhooks-recover-pending" disabled={busy} onClick={() => void perform(signal => tireApi.webhookOperation(pendingKey, signal), pendingKey, true)}>只读核对待确认动作</button><button type="button" className="text-button" disabled={busy} onClick={() => { unresolved.current = null; setPendingKey(null); remember(pendingKey, false); setEditor(null); setRefresh(value => value + 1); }}>结束本次核对，保留原UUID</button><p>结束核对不会撤销原动作。之后新建操作可能产生另一条订阅或修订。</p></div> : null}
    <details className="webhook-recovery" open={!!recovery}><summary>按UUID只读恢复动作回执</summary><label className="webhook-field"><span>Webhook操作UUID</span><input aria-label="Webhook操作UUID" maxLength={36} value={recovery} disabled={busy} onChange={event => setRecovery(event.target.value)} /></label><button type="button" className="secondary-button" data-testid="webhooks-recover" disabled={busy || !validKey(recovery)} onClick={() => void perform(signal => tireApi.webhookOperation(recovery, signal), recovery, true)}>只读恢复动作回执</button></details>
    {receipt ? <section className="webhook-receipt" data-testid="webhook-operation"><h4>{actionLabels[receipt.action]}动作回执 · 冻结历史</h4><p>UUID <code>{receipt.idempotency_key}</code> · {receipt.replayed ? "只读重放" : "首次响应"} · {stamp(receipt.created_at)}。下方是动作首次响应，不是当前订阅或对端实时状态；当前状态需另行只读核对。</p><details><summary>完整冻结动作结果</summary><pre className="webhook-mono">{JSON.stringify(receipt.response, null, 2)}</pre></details></section> : null}
  </section>;
}

function PageControls({ offset, total, disabled, onPage }: { offset: number; total: number; disabled: boolean; onPage: (offset: number) => void }) {
  return <div className="webhook-actions"><button type="button" className="text-button" disabled={disabled || offset === 0} onClick={() => onPage(Math.max(0, offset - 20))}>上一页</button><span>{total ? offset + 1 : 0}–{Math.min(offset + 20, total)} / {total}</span><button type="button" className="text-button" disabled={disabled || offset + 20 >= total || offset + 20 > 10000} onClick={() => onPage(offset + 20)}>下一页</button></div>;
}

function WebhookEditor({ catalog, record, disabled, onSave, onClose }: { catalog: WebhookTarget[]; record: Webhook | null; disabled: boolean; onSave: (payload: WebhookCreate) => void; onClose: () => void }) {
  const [name, setName] = useState(record?.name || ""), [targetId, setTargetId] = useState(record?.target_id || ""), [channels, setChannels] = useState<WebhookChannel[]>(record?.channels || []);
  const [enabled, setEnabled] = useState(record?.enabled || false), [consent, setConsent] = useState(false);
  const target = catalog.find(item => item.id === targetId);
  const binding = JSON.stringify([record?.id, record?.revision, name, targetId, channels, target?.policy_fingerprint, enabled]);
  const [consentBinding, setConsentBinding] = useState<string | null>(null);
  const acknowledged = consent && consentBinding === binding;
  const canSave = !disabled && name.trim().length > 0 && channels.length > 0 && !!target && (!enabled || target.ready && acknowledged);
  function invalidate() { setConsent(false); setConsentBinding(null); }
  return <section className="webhook-editor" data-testid="webhooks-editor"><h4>{record ? "编辑本人订阅" : "新建暂停订阅"}</h4><p>不接受任意接收URL或密钥。仅通知引用外发，不包含规则／兴趣名称、条件、来源事实、账户ID、URL、偏好或凭据。</p><form onSubmit={event => { event.preventDefault(); if (canSave) onSave({ name: name.trim(), target_id: targetId, target_fingerprint: target!.policy_fingerprint, channels: [...channels], enabled, acknowledged_external_delivery: enabled && acknowledged }); }}>
    <fieldset disabled={disabled}><label className="webhook-field"><span>订阅名称（只保存在本机）</span><input aria-label="Webhook订阅名称" value={name} required maxLength={120} onChange={event => { setName(event.target.value); invalidate(); }} /></label><label className="webhook-field"><span>受管理接收目标</span><select aria-label="Webhook受管理目标" value={targetId} required disabled={!!record} onChange={event => { setTargetId(event.target.value); setEnabled(false); invalidate(); }}><option value="">请选择目标</option>{record && !target ? <option value={record.target_id}>{record.target_id}（已移出目录）</option> : null}{catalog.map(item => <option key={item.id} value={item.id}>{item.title} · {item.endpoint_host}{item.ready ? "" : "（仅暂停草稿）"}</option>)}</select></label>{record ? <p>接收目标固定；更换目标须另建订阅。保存编辑会取消旧修订的未终态队列。</p> : null}
      <fieldset className="webhook-channels"><legend>明确选择要外发引用的频道（无默认选择）</legend>{(Object.keys(channelLabels) as WebhookChannel[]).map(channel => <label className="webhook-check" key={channel}><input type="checkbox" data-webhook-channel={channel} checked={channels.includes(channel)} onChange={() => { setChannels(previous => previous.includes(channel) ? previous.filter(value => value !== channel) : [...previous, channel]); invalidate(); }} /><span><strong>{channelLabels[channel]}</strong><small>{channelHelp[channel]}</small></span></label>)}</fieldset>
      {target ? <p>接收host：<code>{target.endpoint_host}</code>。{target.ready ? "配置就绪不证明对方可达或Worker运行。" : "签名配置不可用，可以保存暂停草稿，不能启用。"}</p> : <p className="review-warning">请选目录内目标；缺目录或目标已移除时，可关闭编辑并使用暂停／归档。</p>}
      <label className="webhook-check"><input type="checkbox" data-testid="webhooks-enabled" checked={enabled} disabled={!target?.ready} onChange={event => { setEnabled(event.target.checked); invalidate(); }} /><span>保存后启用（默认关闭，只处理未来新通知）</span></label>
      <label className="webhook-check"><input type="checkbox" data-testid="webhooks-external-consent" checked={acknowledged} disabled={!enabled || !target?.ready} onChange={event => { setConsent(event.target.checked); setConsentBinding(event.target.checked ? binding : null); }} /><span>我同意将本次所选频道的新通知引用外发到 {target?.endpoint_host || "所选目标"}，包括私人通知的引用标识；接收方须按delivery ID去重。</span></label>
      <div className="webhook-actions"><button type="submit" className="primary-button" data-testid="webhooks-save" disabled={!canSave}>{enabled ? "确认同意并保存启用" : "保存暂停订阅"}</button><button type="button" className="text-button" onClick={onClose}>关闭编辑</button></div>
    </fieldset></form></section>;
}
