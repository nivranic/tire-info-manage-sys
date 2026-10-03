"use client";
import { useEffect, useRef, useState } from "react";
import type { DeviceSyncConditions, DeviceSyncPreview, DeviceSyncStatus, OfflineSlot, OfflineStorage } from "@tire/domain-types";
import { offlineError } from "./offline-crypto";
import InlineConfirm from "./inline-confirm";

const stamp = (value: string | null | undefined) => value ? new Date(value).toLocaleString("zh-CN") : "未安排";
const stateText = { enabled: "持续许可已开启", paused: "已暂停，须重新预览授权", revoked: "已撤销持续许可" };
const runText = { running: "运行中", succeeded: "已保存新本机版本", no_change: "完整历史语义没有变化", deferred: "等待执行条件", blocked: "执行已阻止", failed: "检查失败，保留旧包", cancelled: "本次已取消", interrupted: "响应或运行中断，许可已暂停" };
export default function DeviceSyncPanel({ storage, slot }: { storage: OfflineStorage; slot: OfflineSlot }) {
  const [status, setStatus] = useState<DeviceSyncStatus | null>(null), [preview, setPreview] = useState<DeviceSyncPreview | null>(null);
  const [interval, setIntervalMinutes] = useState("60"), [conditions, setConditions] = useState<DeviceSyncConditions>({ network: "any", power: "any" });
  const [consent, setConsent] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [revokeAsk, setRevokeAsk] = useState(false);
  const live = useRef(true), operation = useRef(false);
  const policy = status?.policies.find(value => value.slot_id === slot.slot_id), checks = status?.release_checks.find(value => value.slot_id === slot.slot_id && value.generation === slot.generation);
  const supported = !!storage.syncStatus && !!storage.previewSyncPolicy && !!storage.applySyncPolicy;
  useEffect(() => {
    live.current = true;
    async function refresh() { try { const value = await storage.syncStatus?.(); if (live.current && value) setStatus(value); } catch (cause) { if (live.current) setError(offlineError(cause).message); } }
    void refresh(); const changed = () => { void refresh(); }; window.addEventListener("tire-offline-sync-changed", changed);
    const timer = setInterval(changed, 30_000);
    return () => { live.current = false; clearInterval(timer); window.removeEventListener("tire-offline-sync-changed", changed); };
  }, [storage, slot.slot_id, slot.generation]);
  async function perform(work: () => Promise<void>) {
    if (operation.current) return; operation.current = true; setBusy(true); setError("");
    try { await work(); const value = await storage.syncStatus?.(); if (live.current && value) setStatus(value); }
    catch (cause) { if (live.current) setError(offlineError(cause).message); }
    finally { operation.current = false; if (live.current) setBusy(false); }
  }
  function changed() { setPreview(null); setConsent(false); setNotice(""); }
  if (!supported) return <p>此宿主尚未提供持续更新能力。</p>;
  const capabilities = status?.capabilities, old = slot.previous_owner || slot.locked;
  return <section className="consent-box" aria-label="设备包持续更新"><h3>独立持续更新许可</h3>
    <p>{capabilities?.scheduler === "page_open" ? "应用页面打开时自动检查；关闭页面后不执行。" : capabilities?.scheduler === "native_app_open" ? "桌面应用运行时自动检查；关闭应用后不执行。" : capabilities?.scheduler === "os_background" ? "系统按条件尽力安排后台检查；强制停止后不保证执行。" : "当前构建尚不能安排持续更新。"}这项许可与手动保存、历史查看和单次查询回退分别决定。</p>
    {old ? <p className="review-warning">旧归属包仅供历史查看，解锁不能授予更新许可。</p> : null}
    {error ? <p className="inline-error" role="alert">{error}</p> : null}{notice ? <p className="review-boundary" role="status">{notice}</p> : null}
    {checks ? <p>本机版本完整校验：{checks.state === "passed" ? "通过" : "失败，保留密文并阻止读取和更新"} · {stamp(checks.checked_at)}</p> : <p>尚未完成此版本的完整校验。</p>}
    {policy ? <><p><strong>{stateText[policy.state]}</strong> · 授权版本 #{policy.policy_revision} · 下次检查 {stamp(policy.next_due_at)}</p>
      <div className="compare-toolbar"><button type="button" className="secondary-button" disabled={busy || old || policy.state !== "enabled"} onClick={() => void perform(async () => {
        const run = await storage.runSyncPolicy!({ policy_id: policy.policy_id, expected_policy_revision: policy.policy_revision, trigger: "manual" });
        if (live.current) setNotice(`${runText[run.state]}。${run.state === "succeeded" ? "此包已有新版本，请点击重新读取本机资料；正在查看的历史内容保持原版本。" : ""}`);
      })}>现在按策略检查</button><button type="button" className="text-button" disabled={busy || policy.state !== "enabled"} onClick={() => void perform(async () => { await storage.pauseSyncPolicy!({ policy_id: policy.policy_id, expected_policy_revision: policy.policy_revision }); if (live.current) { changed(); setNotice("已暂停持续许可；重新启用须预览并重新授权。"); } })}>暂停持续更新</button>
      <button type="button" className="text-button" disabled={busy || policy.state === "revoked"} onClick={() => setRevokeAsk(true)}>撤销持续许可</button></div>
      {revokeAsk ? <InlineConfirm title="撤销此包的持续更新许可？" description="撤销后本机历史包仍保留，但不再自动检查更新；重新启用需重新预览并授权。" confirmLabel="确认撤销许可" busy={busy} onConfirm={() => { setRevokeAsk(false); void perform(async () => { await storage.revokeSyncPolicy!({ policy_id: policy.policy_id, expected_policy_revision: policy.policy_revision }); if (live.current) { changed(); setNotice("已撤销持续许可；本机历史包仍保留。"); } }); }} onCancel={() => setRevokeAsk(false)} /> : null}
      {status?.runs.filter(run => run.policy_id === policy.policy_id).slice(-3).reverse().map(run => <p key={run.run_id} role="status">{runText[run.state]} · {stamp(run.finished_at || run.started_at)}{run.reason ? ` · ${offlineError(run.reason).message}` : ""}</p>)}</> : <p>此包尚未获得持续更新许可。</p>}
    <details><summary>预览并配置持续更新</summary>
      <div className="offline-search"><label>检查间隔（分钟）<input type="number" min="15" max="10080" step="1" value={interval} disabled={busy || old} onChange={event => { setIntervalMinutes(event.target.value); changed(); }} /></label>
        <label>网络条件<select value={conditions.network} disabled={busy || old} onChange={event => { setConditions(value => ({ ...value, network: event.target.value as DeviceSyncConditions["network"] })); changed(); }}><option value="any">可连接当前工作区 API</option><option value="wifi" disabled={!capabilities?.wifi}>Wi-Fi{capabilities?.wifi ? "" : "（此宿主不支持）"}</option></select></label>
        <label>电源条件<select value={conditions.power} disabled={busy || old} onChange={event => { setConditions(value => ({ ...value, power: event.target.value as DeviceSyncConditions["power"] })); changed(); }}><option value="any">不要求电源状态</option><option value="external_power" disabled={!capabilities?.external_power}>外接电源{capabilities?.external_power ? "" : "（此宿主不支持）"}</option><option value="battery_charging" disabled={!capabilities?.battery_charging}>电池实际充电{capabilities?.battery_charging ? "" : "（此宿主不支持）"}</option></select></label></div>
      <p>所有选定条件须同时满足；状态未知会等待。手动检查仅跳过时间间隔，仍须满足许可、归属、条件与容量。</p>
      <button type="button" className="secondary-button" disabled={busy || old || !status || capabilities?.scheduler === "unsupported"} onClick={() => void perform(async () => {
        setPreview(null); setConsent(false); const value = await storage.previewSyncPolicy!({ slot_id: slot.slot_id, expected_generation: slot.generation,
          expected_profile_id: status!.profile_id, expected_owner_epoch: status!.owner_epoch, interval_seconds: Number(interval) * 60, conditions }); if (live.current) setPreview(value);
      })}>预览持续更新范围</button>
      {preview ? <div aria-label="持续更新本机范围预览"><p>这是已安装原包的范围与计数，未查询服务器当前内容。原包共 {preview.counts.distinct_evidence} 份证据、{preview.counts.garage_profiles} 份车库档案、{preview.counts.watch_items} 份关注资料。</p>
        <p>{preview.scope.garage.include ? preview.scope.garage.vehicle_ids === null ? "全部当前车库（动态范围）" : `${preview.scope.garage.vehicle_ids.length} 个固定车库 ID` : "不包含车库"}；{preview.scope.watchlist.include ? preview.scope.watchlist.item_ids === null ? "全部当前关注（动态范围）" : `${preview.scope.watchlist.item_ids.length} 个固定关注 ID` : "不包含关注"}；{preview.scope.recent.include ? `最近 ${preview.scope.recent.limit} 次正式查询（动态范围）` : "不包含最近查询"}；{preview.scope.references.length} 份固定回执证据。</p>
        <p>{preview.notice}</p><p>每包最多 8 MiB / 200 份证据 / 50 份车库档案 / 100 份关注 / 4000 条检索文档。预览到期 {stamp(preview.expires_at)}。</p>
        <label><input type="checkbox" checked={consent} disabled={busy} onChange={event => setConsent(event.target.checked)} />允许按以上范围、条件与容量持续更新此设备包，直到我暂停或撤销</label>
        <button type="button" className="primary-button" disabled={busy || !consent} onClick={() => void perform(async () => {
          const approved = preview; setPreview(null); setConsent(false); await storage.applySyncPolicy!({ preview_id: approved.preview_id,
            expected_fingerprint: approved.fingerprint, expected_policy_revision: approved.expected_policy_revision, allow_continuous_history_updates: true });
          if (live.current) setNotice("已记录独立持续许可。按宿主能力和全部条件尽力安排检查，来源核验时间保持原历史语义。");
        })}>明确授权持续更新</button></div> : null}
    </details></section>;
}
