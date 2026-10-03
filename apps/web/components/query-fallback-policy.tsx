"use client";
import { useEffect, useRef, useState } from "react";
import { tireApi } from "@tire/api-client";
import type { DeviceFallbackPolicy, DeviceFallbackPolicyMode, DeviceFallbackPolicyPreview, DeviceFallbackPolicyPreviewRequest, DeviceFallbackPolicyScope, DeviceFallbackQueryKind, DeviceFallbackStatus, OfflineStorage, WarehouseFallbackPolicy, WarehouseFallbackPolicyPreview } from "@tire/domain-types";
import { useSourceAccess } from "./source-status";
import { useWorkbenchPlatform } from "./workbench-platform";
import { DataTree } from "./reparse-review";

const modes: Record<DeviceFallbackPolicyMode, string> = { ask: "每次询问", never: "始终拒绝自动回退", session_allow: "本次会话持续允许", source_allow: "所选来源持续允许", query_allow: "此查询类型持续允许" };
const kinds: Record<DeviceFallbackQueryKind, string> = { tire: "轮胎规格", vehicle_fitments: "车型配置", recall_campaign: "召回公告编号", recall_search: "召回名称检索页" };
const detail = (cause: unknown) => cause instanceof Error ? cause.message : "策略操作未完成。";
const sourceIdsIn = (scope: DeviceFallbackPolicyScope) => scope.kind === "source" ? [scope.source_id] : scope.sources.map(source => source.source_id);

export default function QueryFallbackPolicy({ kind, sourceIds, sessionReady }: { kind: DeviceFallbackQueryKind; sourceIds: string[]; sessionReady: boolean }) {
  const access = useSourceAccess(), platform = useWorkbenchPlatform(), storage = platform.offline;
  const [open, setOpen] = useState(false), [layer, setLayer] = useState<"warehouse" | "device">("warehouse");
  const [mode, setMode] = useState<DeviceFallbackPolicyMode>("ask"), [source, setSource] = useState("");
  const [preferenceScope, setPreferenceScope] = useState<"query" | "source" | "session">("query");
  const [explicitSources, setExplicitSources] = useState<string[] | null>(null);
  const [editing, setEditing] = useState<WarehouseFallbackPolicy | DeviceFallbackPolicy | null>(null);
  const [warehouse, setWarehouse] = useState<WarehouseFallbackPolicy[]>([]), [device, setDevice] = useState<DeviceFallbackStatus | null>(null);
  const [slotId, setSlotId] = useState(""), [advance, setAdvance] = useState(false), [confirmed, setConfirmed] = useState(false);
  const [preview, setPreview] = useState<WarehouseFallbackPolicyPreview | DeviceFallbackPolicyPreview | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const alive = useRef(true), revision = useRef(0);
  const idsKey = [...new Set(explicitSources ?? sourceIds)].sort().join("|"), ids = idsKey ? idsKey.split("|") : [];
  const registered = layer === "device" ? device?.authority.sources.filter(item => item.query_kinds.includes(kind)).map(item => item.source_id) || []
    : access.items.filter(item => kind === "vehicle_fitments" ? item.target_kind === "vehicle" : kind === "recall_campaign" || kind === "recall_search" ? item.source_id === "nhtsa-us-recalls" && item.target_kind === "recall" : item.target_kind === "tire").map(item => item.source_id);
  const selected = source && ids.includes(source) ? source : ids[0] || "";
  const isAllow = mode !== "ask" && mode !== "never";
  const binding = device?.package_bindings.find(item => item.slot_id === slotId);
  const scopeKind = mode === "source_allow" || !isAllow && preferenceScope === "source" ? "source" : mode === "session_allow" || !isAllow && preferenceScope === "session" ? "session" : "query";
  const whitelist = scopeKind === "source" ? [selected] : ids;
  const canAdvance = !!binding && binding.source_ids.every(id => whitelist.includes(id));
  useEffect(() => { alive.current = true; return () => { alive.current = false; revision.current++; }; }, []);
  useEffect(() => { revision.current++; setPreview(null); setConfirmed(false); setAdvance(false); }, [idsKey, selected, kind, layer, mode, preferenceScope, slotId, access.items]);
  async function load() {
    const current = ++revision.current; setError(""); setPreview(null); setConfirmed(false);
    try {
      const [policies, status] = await Promise.allSettled([tireApi.queryFallbackPolicies(), storage?.fallbackStatus?.()]);
      if (!alive.current || current !== revision.current) return;
      if (policies.status === "fulfilled") setWarehouse(policies.value.items);
      else setError(`仓库策略目录暂不可用：${detail(policies.reason)}；设备元数据仍独立读取。`);
      if (status.status === "fulfilled" && status.value) { setDevice(status.value); setSlotId(previous => previous || status.value?.package_bindings[0]?.slot_id || ""); }
      else if (status.status === "rejected") setError(`设备策略目录暂不可用：${detail(status.reason)}`);
    } catch (cause) { if (alive.current && current === revision.current) setError(detail(cause)); }
  }
  async function refreshDevice() {
    if (!storage?.refreshFallbackAuthority || !storage.fallbackStatus || busy) return;
    setBusy(true); setError(""); setPreview(null); setConfirmed(false);
    try { await storage.refreshFallbackAuthority(); setDevice(await storage.fallbackStatus()); setNotice("已通过固定目录接口刷新设备来源元数据；未读取设备包内容。"); }
    catch (cause) { setError(detail(cause)); } finally { if (alive.current) setBusy(false); }
  }
  function scopeFor(): DeviceFallbackPolicyScope {
    const chosen = scopeKind === "source" ? [selected] : ids;
    const pins = chosen.map(id => {
      const row = layer === "device" ? device?.authority.sources.find(item => item.source_id === id && item.query_kinds.includes(kind)) : access.get(id);
      if (!row) throw new Error("所选来源尚未在已注册目录中确认，请先刷新来源元数据。");
      return { source_id: id, access_generation: "access_generation" in row ? row.access_generation : row.management.access_generation };
    });
    if (!pins.length || pins.length > 10) throw new Error("请选择 1 至 10 个明确来源。");
    if (scopeKind === "source") return { kind: "source", ...pins[0], query_kinds: [kind] };
    if (scopeKind === "session") return { kind: "session", sources: pins.map(pin => ({ ...pin, query_kinds: [kind] })) };
    return { kind: "query", query_kind: kind, sources: pins };
  }
  async function prepare() {
    if (busy) return; const current = ++revision.current; setBusy(true); setError(""); setPreview(null); setConfirmed(false);
    try {
      const scope = scopeFor();
      let value: WarehouseFallbackPolicyPreview | DeviceFallbackPolicyPreview;
      if (layer === "warehouse") value = await tireApi.previewQueryFallbackPolicy({ mode, scope, expires_in_seconds: 3600,
        policy_id: editing?.schema === "query-fallback-policy@1" ? editing.id : null,
        expected_revision: editing?.schema === "query-fallback-policy@1" ? editing.revision : 0 });
      else {
        if (!storage?.previewFallbackPolicy || !device || device.authority.state !== "last_observed") throw new Error("设备冷启动后来源权限未知，请主动刷新固定来源元数据。");
        if (isAllow && !binding) throw new Error("请选择具有已保存范围元数据的设备包；旧包可先从独立历史库明确读取，再重新预览。");
        const choice = isAllow ? { mode, scope, binding: binding!, allow_same_scope_sync_binding_advance: advance && canAdvance } : { mode, scope, binding: null, allow_same_scope_sync_binding_advance: false };
        value = await storage.previewFallbackPolicy({ ...choice, expected_profile_id: device.profile_id, expected_owner_epoch: device.owner_epoch,
          authority: { runtime_session_id: device.authority.runtime_session_id, authority_revision: device.authority.authority_revision },
          policy_id: editing?.schema === "device-fallback-policy@1" ? editing.policy_id : null,
          expected_policy_revision: editing?.schema === "device-fallback-policy@1" ? editing.policy_revision : 0,
          expires_in_seconds: 3600 } as DeviceFallbackPolicyPreviewRequest);
      }
      if (alive.current && current === revision.current) setPreview(value);
    } catch (cause) { if (alive.current && current === revision.current) setError(detail(cause)); }
    finally { if (alive.current) setBusy(false); }
  }
  async function commit() {
    if (!preview || !confirmed || busy) return; const frozen = preview; setBusy(true); setError("");
    try {
      if (frozen.schema === "query-fallback-policy-preview@1") await tireApi.applyQueryFallbackPolicy({ preview_id: frozen.preview_id, expected_fingerprint: frozen.fingerprint, expected_revision: frozen.expected_revision, allow_continuous_history_fallback: true }, crypto.randomUUID());
      else { if (!storage?.applyFallbackPolicy) throw new Error("设备宿主不支持此策略。"); await storage.applyFallbackPolicy({ preview_id: frozen.preview_id, expected_fingerprint: frozen.fingerprint, expected_policy_revision: frozen.expected_policy_revision, allow_continuous_history_fallback: true }); }
      setNotice("已保存所选范围的策略，从下一次普通查询生效；不会重试当前失败，也不授权设备更新或 AI。"); await load();
    } catch (cause) { if (alive.current) setError(detail(cause)); } finally { if (alive.current) setBusy(false); }
  }
  async function change(policy: WarehouseFallbackPolicy | DeviceFallbackPolicy, action: "pause" | "revoke") {
    if (busy) return; setBusy(true); setError("");
    try {
      if (policy.schema === "query-fallback-policy@1") await (action === "pause" ? tireApi.pauseQueryFallbackPolicy : tireApi.revokeQueryFallbackPolicy)(policy.id, policy.revision, crypto.randomUUID());
      else { const operation = action === "pause" ? storage?.pauseFallbackPolicy : storage?.revokeFallbackPolicy; if (!operation) throw new Error("设备宿主不支持此操作。"); await operation({ policy_id: policy.policy_id, expected_policy_revision: policy.policy_revision }); }
      await load();
    } catch (cause) { if (alive.current) setError(detail(cause)); } finally { if (alive.current) setBusy(false); }
  }
  const policies = layer === "warehouse" ? warehouse : device?.policies || [];
  function edit(policy: WarehouseFallbackPolicy | DeviceFallbackPolicy) {
    setEditing(policy); setMode(policy.mode); setExplicitSources(sourceIdsIn(policy.scope)); setPreferenceScope(policy.scope.kind);
    if (policy.scope.kind === "source") setSource(policy.scope.source_id);
    if (policy.schema === "device-fallback-policy@1" && policy.binding) setSlotId(policy.binding.slot_id);
    setPreview(null); setConfirmed(false); setAdvance(false); setError("");
  }
  function switchLayer(next: "warehouse" | "device") {
    if (next === layer) return;
    setLayer(next); setEditing(null); setExplicitSources(null); setSource(""); setPreview(null); setConfirmed(false); setAdvance(false);
  }
  return <details className="recall-provenance" open={open} onToggle={event => { const next = event.currentTarget.open; setOpen(next); if (next && !open) void load(); }}><summary>{kinds[kind]} · 查询失败后的历史回退策略</summary>
    <p>仓库与设备各自保存授权。每次网络中断或超时仍须产生单次消费回执；拒绝优先。手动历史视图独立保留。</p>
    <div className="relation-modes"><button type="button" aria-pressed={layer === "warehouse"} disabled={busy} onClick={() => switchLayer("warehouse")}>仓库历史策略</button><button type="button" aria-pressed={layer === "device"} disabled={busy || !storage?.fallbackStatus} onClick={() => switchLayer("device")}>设备历史策略</button></div>
    <p className="muted">{layer === "warehouse" ? "仅普通服务端查询；不继承为设备包许可、更新或 AI 授权。" : "仅本机所选包；不继承为仓库读取、设备更新、外发或 AI 授权。"}</p>
    {layer === "device" ? <><p role="status">来源元数据：{device?.authority.state === "last_observed" ? `最近观察 ${device.authority.observed_at}` : "冷启动未知，暂不能新增策略"}</p><button type="button" className="secondary-button" disabled={busy} onClick={() => void refreshDevice()}>主动刷新设备固定来源元数据</button></> : <button type="button" className="text-button" disabled={busy} onClick={() => void access.refresh()}>刷新仓库来源目录</button>}
    <div className="review-form"><label><span>回退偏好 / 持续权限</span><select value={mode} disabled={busy} onChange={event => setMode(event.target.value as DeviceFallbackPolicyMode)}>{Object.entries(modes).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      <fieldset><legend>明确授权来源（不自动加入包来源）</legend>{registered.map(id => <label className="review-check" key={id}><input type="checkbox" disabled={busy || !ids.includes(id) && ids.length >= 10} checked={ids.includes(id)} onChange={() => setExplicitSources(ids.includes(id) ? ids.filter(value => value !== id) : [...ids, id])} />{access.get(id)?.name || id}</label>)}</fieldset>
      {editing ? <p>修改保留策略 {editing.schema === "query-fallback-policy@1" ? editing.id : editing.policy_id} 的修订 {editing.schema === "query-fallback-policy@1" ? editing.revision : editing.policy_revision}。旧记录已裁除时会拒绝，不自动改为新建。<button type="button" className="text-button" disabled={busy} onClick={() => { setEditing(null); setPreview(null); setConfirmed(false); }}>改为明确新建策略</button></p> : <p>当前为明确新建策略。</p>}
      {!isAllow ? <label><span>询问 / 拒绝偏好的范围</span><select value={preferenceScope} disabled={busy} onChange={event => setPreferenceScope(event.target.value as typeof preferenceScope)}><option value="query">此查询类型与所选来源</option><option value="source">唯一所选来源</option><option value="session">当前会话中的明确来源</option></select></label> : null}
      {scopeKind === "source" ? <label><span>唯一授权来源</span><select value={selected} disabled={busy} onChange={event => setSource(event.target.value)}>{ids.map(id => <option key={id} value={id}>{access.get(id)?.name || id}</option>)}</select></label> : <p>明确来源白名单：{ids.join("、") || "尚未选择来源"}；查询类型：{kinds[kind]}。新来源不会加入已保存策略。</p>}
      {scopeKind === "session" ? <p>{layer === "device" ? "此会话范围只在当前设备宿主运行有效；重启会暂停其中的允许、询问或拒绝偏好。" : "此会话范围绑定当前仓库 UserSession，不跨新会话恢复。"}</p> : null}
      {layer === "device" && isAllow ? <><label><span>绑定设备包（仅目录元数据）</span><select value={slotId} disabled={busy} onChange={event => setSlotId(event.target.value)}><option value="">请选择</option>{device?.package_bindings.map(item => <option key={item.slot_id} value={item.slot_id}>{item.package_id} · v{item.generation}</option>)}</select></label><label className="review-check"><input type="checkbox" disabled={busy || !canAdvance} checked={advance && canAdvance} onChange={event => { setAdvance(event.target.checked); setPreview(null); setConfirmed(false); }} />允许已另行授权的同范围同步推进此绑定</label><p>整包来源必须全部在以上白名单内。{!canAdvance ? "该包含白名单之外的来源，不能启用绑定推进。" : "推进不增加来源白名单。"} 手动替换或范围变化后需要新的预览与确认。</p>{device?.missing_package_bindings.length ? <p>有 {device.missing_package_bindings.length} 个旧包缺少已保存范围元数据，请先从独立历史库明确读取；本页面不会读取包体补存。</p> : null}</> : null}
      <button type="button" className="secondary-button" disabled={busy || !sessionReady || !ids.length || (layer === "device" && device?.authority.state !== "last_observed")} onClick={() => void prepare()}>预览所选策略（只读元数据）</button>
    </div>
    {preview ? <section className="review-boundary"><p>{preview.notice}</p><p>预览截止：{preview.expires_at}；本次明确范围：</p><DataTree label="策略范围和包绑定" value={preview.proposed_policy} /><label className="review-check"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} />确认此独立策略及其范围、期限</label><button type="button" className="primary-button" disabled={!confirmed || busy} onClick={() => void commit()}>确认保存所选策略</button></section> : null}
    {policies.filter(policy => sourceIdsIn(policy.scope).some(id => ids.includes(id))).map(policy => <article className="recall-record" key={policy.schema === "query-fallback-policy@1" ? policy.id : policy.policy_id}><p><strong>{modes[policy.mode]}</strong> · {policy.state} · 截止 {policy.expires_at}</p><DataTree label="已保存授权白名单与精确绑定" value={policy.scope} /><div className="consent-actions"><button type="button" className="text-button" disabled={busy} onClick={() => edit(policy)}>沿用此策略 ID 重新预览</button><button type="button" className="text-button" disabled={busy || policy.state !== "enabled"} onClick={() => void change(policy, "pause")}>暂停此策略</button><button type="button" className="text-button" disabled={busy || policy.state === "revoked"} onClick={() => void change(policy, "revoke")}>撤销此策略</button></div></article>)}
    {busy ? <p role="status">正在核对元数据与策略回执…</p> : null}{error ? <p className="inline-error" role="alert">{error}</p> : null}{notice ? <p role="status">{notice}</p> : null}
  </details>;
}

/** Offline metadata management: this entry performs no warehouse or body reads. */
export function DeviceFallbackPolicySummary({ storage }: { storage: OfflineStorage }) {
  const [status, setStatus] = useState<DeviceFallbackStatus | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const alive = useRef(true);
  async function load() { if (!storage.fallbackStatus) return; try { const value = await storage.fallbackStatus(); if (alive.current) setStatus(value); } catch (cause) { if (alive.current) setError(detail(cause)); } }
  useEffect(() => { alive.current = true; void load(); const refresh = () => void load(); window.addEventListener("tire-offline-owner-changed", refresh); return () => { alive.current = false; window.removeEventListener("tire-offline-owner-changed", refresh); }; }, [storage]);
  async function change(policy: DeviceFallbackPolicy, action: "pause" | "revoke") {
    if (busy) return; setBusy(true); setError("");
    try {
      const request = { policy_id: policy.policy_id, expected_policy_revision: policy.policy_revision };
      if (action === "pause") { if (!storage.pauseFallbackPolicy) throw new Error("设备宿主不支持暂停。"); await storage.pauseFallbackPolicy(request); }
      else { if (!storage.revokeFallbackPolicy) throw new Error("设备宿主不支持撤销。"); await storage.revokeFallbackPolicy(request); }
      await load();
    } catch (cause) { if (alive.current) setError(detail(cause)); } finally { if (alive.current) setBusy(false); }
  }
  if (!storage.fallbackStatus) return null;
  return <section className="recall-provenance" aria-label="设备回退策略离线管理"><h3>设备历史回退策略</h3><p>独立设备目录，仅查看授权元数据并暂停或撤销；不访问 API、不读取包内参数。冷启动未知不会清除已有来源/查询拒绝偏好。</p><p role="status">来源权限观察：{status?.authority.state === "last_observed" ? status.authority.observed_at : "未知；新增策略须另行刷新固定目录"}</p>{status?.policies.length ? status.policies.map(policy => <article className="recall-record" key={policy.policy_id}><p><strong>{modes[policy.mode]}</strong> · {policy.state} · 修订 {policy.policy_revision}</p>{policy.scope.kind === "session" ? <p>当前宿主运行范围，重启后暂停；不跨运行恢复允许或拒绝。</p> : null}<DataTree label="完整范围与包绑定元数据" value={{ scope: policy.scope, binding: policy.binding, expires_at: policy.expires_at }} /><div className="consent-actions"><button type="button" className="secondary-button" disabled={busy || policy.state !== "enabled"} onClick={() => void change(policy, "pause")}>暂停此设备策略</button><button type="button" className="secondary-button" disabled={busy || policy.state === "revoked"} onClick={() => void change(policy, "revoke")}>撤销此设备策略</button></div></article>) : <p>当前归属尚无设备回退策略。</p>}{error ? <p className="inline-error" role="alert">{error}</p> : null}</section>;
}
