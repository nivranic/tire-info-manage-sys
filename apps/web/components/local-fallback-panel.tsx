"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DeviceFallbackResultV2, LocalFallbackResult, OfflineHostList, OfflineMember, OfflineMemberV2, OfflineStorage } from "@tire/domain-types";
import { stringifyExactJson } from "@tire/api-client";
import { LocalFallbackController, type LocalFallbackOffer } from "./local-fallback-controller";
import { FALLBACK_NOTICE } from "./local-fallback-values";
import { offlineError } from "./offline-crypto";
import { DataTree } from "./reparse-review";

const shown = (value: unknown): string => value === null || value === undefined ? "未记录" : typeof value === "boolean" ? value ? "是" : "否" : typeof value === "object" ? stringifyExactJson(value) : String(value);
const labels: Record<string, string> = { brand: "品牌", model: "型号", size: "尺寸", region: "区域", manufacturer_product_code: "产品代码", load_index: "载重指数", speed_rating: "速度级别", xl: "XL", hl: "HL", oe_mark: "OE 标记", run_flat: "防爆技术", acoustic_technology: "静音技术", facts: "原来源技术参数", id: "历史规格 ID", snapshot_id: "快照 ID" };
const primaryFields = ["brand", "model", "size", "region", "manufacturer_product_code", "load_index", "speed_rating", "xl", "hl", "oe_mark", "run_flat", "acoustic_technology"];
const factNames: Record<string, string> = { utqg_treadwear: "UTQG 磨耗指数", utqg_traction: "UTQG 牵引力等级", utqg_temperature: "UTQG 耐热等级", weight_kg: "重量（kg）", tread_depth: "胎纹深度", noise_db: "外部噪音", wet_grip: "湿地抓地等级", fuel_efficiency: "燃油效率等级" };
function HistoricalMember({ member }: { member: OfflineMember | OfflineMemberV2 }) {
  if (member.reference.kind !== "tire") return <article className="local-fallback-member"><h4>{{ vehicle: "车型历史配置", recall: "正式召回历史记录", recall_search: "名称检索候选历史页", test_event: "测试事件" }[member.reference.kind]}</h4><p className="muted">仅所选包保存的历史观察；适用性未评估。</p><DataTree label="原始历史记录与页面边界" value={member.payload} /><DataTree label="精确来源与核验回执" value={member.source} /></article>;
  const variant = member.payload.variant && typeof member.payload.variant === "object" ? member.payload.variant as Record<string, unknown> : {};
  return <article className="local-fallback-member"><h4>{shown(variant.model)} · {shown(variant.size)}</h4><p className="muted">原来源参数 · 每份回执单独保留</p>
    <dl className="local-fallback-fields">{primaryFields.filter(key => Object.hasOwn(variant, key)).map(key => [key, variant[key]] as const).map(([key, value]) => <div key={key}><dt>{labels[key] || key}</dt><dd>{shown(value)}</dd></div>)}</dl>
    {variant.facts && typeof variant.facts === "object" ? <dl className="local-fallback-fields">{Object.entries(variant.facts).map(([key, value]) => <div key={key}><dt>{factNames[key] || key}</dt><dd>{shown(value)}</dd></div>)}</dl> : null}
    <DataTree label="完整原来源记录" value={variant} />
    <dl className="local-fallback-provenance"><div><dt>来源</dt><dd>{member.source.source_id}</dd></div><div><dt>观察时间</dt><dd>{member.source.observed_at}</dd></div><div><dt>核验时间</dt><dd>{member.source.verified_at || "未记录"}</dd></div><div><dt>核验回执</dt><dd>{member.source.verification_id || "未记录"}</dd></div><div><dt>原文 SHA-256</dt><dd>{member.source.raw_hash || "未记录"}</dd></div><div><dt>解析版本</dt><dd>{member.source.parser_version || "未记录"}</dd></div><div><dt>来源地址</dt><dd>{member.source.source_url || "未记录"}</dd></div></dl>
    <DataTree label="历史引用与解析身份" value={{ reference: member.reference, parser_identity: member.source.parser_identity }} />
    {member.payload.field_resolution !== undefined ? <div className="local-fallback-context"><p>这是保存时针对整包聚合的附带上下文；其中默认值不作为本次单源查询参数。</p><DataTree label="整包历史字段上下文（可能含其他来源/回执）" value={member.payload.field_resolution} /></div> : null}
  </article>;
}
export default function LocalFallbackPanel({ offer, storage, onClose }: { offer: LocalFallbackOffer; storage: OfflineStorage; onClose: () => void }) {
  const controller = useMemo(() => new LocalFallbackController(storage), [storage]);
  const [metadata, setMetadata] = useState<OfflineHostList | null>(null), [slotId, setSlotId] = useState("");
  const [busy, setBusy] = useState(false), [answered, setAnswered] = useState(false), [denied, setDenied] = useState(false), [error, setError] = useState("");
  const [authorizationReady, setAuthorizationReady] = useState(offer.intent.schema !== "device-fallback-intent@2");
  const [value, setValue] = useState<LocalFallbackResult | DeviceFallbackResultV2 | null>(null);
  const automaticAttempt = useRef(false);
  const returnFocus = useRef<HTMLElement | null>(null);
  useEffect(() => { returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; }, []);
  const alive = useRef(true), version = useRef(0), snapshot = useRef<OfflineHostList | null>(null);
  useEffect(() => {
    alive.current = true;
    const load = async () => {
      try {
        const next = await controller.metadata(); if (!alive.current) return;
        const previous = snapshot.current;
        if (previous && (previous.profile_id !== next.profile_id || previous.owner_epoch !== next.owner_epoch || previous.items.some(slot => !next.items.some(current => current.slot_id === slot.slot_id && current.generation === slot.generation && current.sha256 === slot.sha256 && current.locked === slot.locked && current.previous_owner === slot.previous_owner)))) {
          version.current++; controller.invalidate(); setValue(null); setAnswered(true); setBusy(false); setError("设备归属或包版本已变化，本次授权已结束。请重新查询。");
        }
        let preferred: string | undefined;
        if (offer.intent.schema === "device-fallback-intent@2" && storage.fallbackStatus) {
          const status = await storage.fallbackStatus();
          if (!alive.current) return;
          const intent = offer.intent;
          const candidates = status.policies.filter(policy => {
            if (policy.state !== "enabled" || !policy.mode.endsWith("_allow") || !policy.binding || Date.parse(policy.expires_at) <= Date.now()
              || policy.profile_id !== next.profile_id || policy.owner_epoch !== next.owner_epoch || policy.owner_scope_id !== status.authority.owner_scope_id
              || policy.scope.kind === "session" && policy.runtime_session_id !== status.authority.runtime_session_id) return false;
            const matches = policy.scope.kind === "source" ? policy.scope.source_id === intent.source_id && policy.scope.access_generation === intent.source_access_generation && policy.scope.query_kinds.includes(intent.query_kind)
              : policy.scope.kind === "query" ? policy.scope.query_kind === intent.query_kind && policy.scope.sources.some(source => source.source_id === intent.source_id && source.access_generation === intent.source_access_generation)
              : policy.scope.sources.some(source => source.source_id === intent.source_id && source.access_generation === intent.source_access_generation && source.query_kinds.includes(intent.query_kind));
            return matches && next.items.some(slot => slot.slot_id === policy.binding?.slot_id && slot.generation === policy.binding.generation && slot.sha256 === policy.binding.sha256 && !slot.locked && !slot.previous_owner);
          });
          const rank = { query: 0, source: 1, session: 2 };
          candidates.sort((a, b) => rank[a.scope.kind] - rank[b.scope.kind] || Date.parse(b.approved_at) - Date.parse(a.approved_at) || (a.policy_id < b.policy_id ? -1 : a.policy_id > b.policy_id ? 1 : 0));
          preferred = candidates[0]?.binding?.slot_id;
        }
        snapshot.current = next; setMetadata(next); setSlotId(previousId => previousId || preferred || next.items.find(slot => !slot.locked && !slot.previous_owner)?.slot_id || "");
      } catch (cause) { if (alive.current) setError(offlineError(cause).message); }
    };
    void load(); const focus = () => { if (document.visibilityState === "visible") void load(); };
    const ownerChanged = () => {
      // Native reset and same-page browser reset share this immediate invalidation.
      // Do not wait for an asynchronous metadata read before clearing private data.
      version.current++; controller.invalidate(); setValue(null); setMetadata(null); snapshot.current = null; setSlotId(""); setAnswered(true); setBusy(false);
      setError("设备资料归属已变化，本次设备授权已结束。请重新查询。"); void load();
    };
    window.addEventListener("focus", focus); document.addEventListener("visibilitychange", focus); window.addEventListener("tire-offline-owner-changed", ownerChanged);
    return () => { alive.current = false; version.current++; controller.invalidate(); window.removeEventListener("focus", focus); document.removeEventListener("visibilitychange", focus); window.removeEventListener("tire-offline-owner-changed", ownerChanged); };
  }, [controller, offer, storage]);
  useEffect(() => {
    const slot = metadata?.items.find(item => item.slot_id === slotId);
    if (offer.intent.schema !== "device-fallback-intent@2" || !metadata || !slot || slot.locked || slot.previous_owner || automaticAttempt.current) return;
    automaticAttempt.current = true; const current = version.current; setBusy(true);
    void controller.authorizeV2({ intent: offer.intent, slot_id: slot.slot_id, expected_generation: slot.generation, expected_sha256: slot.sha256,
      expected_profile_id: metadata.profile_id, expected_owner_epoch: metadata.owner_epoch }).then(result => {
      if (!alive.current || current !== version.current) return;
      if (result === "denied") { setDenied(true); setAnswered(true); }
      else if (result && result !== "ask") { setValue(result); setAnswered(true); }
    }).catch(cause => { if (alive.current && current === version.current) { setError(offlineError(cause).message); setAnswered(true); } })
      .finally(() => { if (alive.current && current === version.current) { setBusy(false); setAuthorizationReady(true); } });
  }, [controller, metadata, offer, slotId]);
  async function answer(decision: "allow" | "deny") {
    const slot = metadata?.items.find(item => item.slot_id === slotId);
    if (!metadata || !slot || slot.locked || slot.previous_owner || busy || answered || !authorizationReady) return;
    const current = version.current; setBusy(true); setAnswered(true); setError("");
    try {
      const binding = { slot_id: slot.slot_id, expected_generation: slot.generation, expected_sha256: slot.sha256,
        expected_profile_id: metadata.profile_id, expected_owner_epoch: metadata.owner_epoch, decision };
      const result = offer.intent.schema === "device-fallback-intent@2" ? await controller.answerV2({ ...binding, intent: offer.intent }) : await controller.answer({ ...binding, intent: offer.intent });
      if (!alive.current || current !== version.current) return;
      if (result === "denied") setDenied(true); else if (result) setValue(result);
    } catch (cause) { if (alive.current && current === version.current) setError(offlineError(cause).message); }
    finally { if (alive.current && current === version.current) setBusy(false); }
  }
  const eligible = metadata?.items.filter(slot => !slot.locked && !slot.previous_owner) || [];
  return <section className="local-fallback-panel" aria-label={`${offer.sourceName} 本次设备历史回退`}><div className="local-fallback-heading"><div><span className="tag warning">DEVICE HISTORY · 独立历史资料</span><h3>{offer.sourceName} · 本次设备历史回退</h3></div><button type="button" className="text-button" onClick={() => { version.current++; controller.invalidate(); const target = returnFocus.current; onClose(); requestAnimationFrame(() => { if (target?.isConnected) target.focus({ preventScroll: true }); }); }}>关闭设备回退</button></div>
    <p>{offer.intent.failure.scope === "api_transport" ? "本次连接 API 时发生网络中断或超时。来源许可只依据本页此前读取的已启用目录，离线时未重新核验当前服务端许可。" : "本次来源核验返回网络中断或超时。"}</p>
    <DataTree label="本次精确查询与筛选条件" value={{ query: offer.intent.query, filters: offer.intent.filters }} />
    <p>{FALLBACK_NOTICE}</p>
    {!answered ? <><p>是否允许在 5 分钟内单次读取一个当前归属设备包？作答前仅列出包信息，不检索其中参数。</p>{metadata ? eligible.length ? <label className="local-fallback-slot">本次资料包<select value={slotId} onChange={event => setSlotId(event.target.value)}>{eligible.map(slot => <option key={slot.slot_id} value={slot.slot_id}>{slot.title} · {slot.created_at} · v{slot.generation}</option>)}</select></label> : <p role="status">当前归属没有可用设备包。旧归属资料请从独立历史库查看。</p> : <p role="status">正在读取设备包目录…</p>}
      <div className="local-fallback-actions"><button type="button" className="primary-button" disabled={!slotId || !eligible.length || busy || !authorizationReady} onClick={() => void answer("allow")}>允许本次读取设备历史</button><button type="button" className="secondary-button" disabled={!slotId || !eligible.length || busy || !authorizationReady} onClick={() => void answer("deny")}>拒绝本次设备回退</button></div></> : null}
    {busy ? <p role="status">正在处理本次设备授权…</p> : null}{denied ? <p role="status">已拒绝本次设备回退，未读取包内参数。重新查询才会产生新的授权机会。</p> : null}{error ? <p className="inline-error" role="alert">{error}</p> : null}
    {value ? <div className="local-fallback-result"><p><strong>LOCAL SNAPSHOT · 已授权的本机历史</strong></p><p>包创建：{value.slot.created_at} · 包版本：{value.slot.generation} · 完整匹配 {value.members.length} 份历史回执</p>{value.schema === "device-fallback-result@2" ? <><p>授权：{value.fallback_authorization.type === "policy_once" ? "设备持续策略产生的本次单次消费" : "明确允许本次读取"}</p>{value.query_kind === "tire" ? <p>本包此来源的历史观察 {value.selection.source_count} 份；匹配 {value.selection.matched_count}、排除 {value.selection.excluded_count}、未能判定 {value.selection.undetermined_count}。不是在线完整目录。</p> : null}<DataTree label="设备本地引用（不转换为在线引用）" value={value.citations} /></> : null}<p className="local-fallback-hash">包 SHA-256：{value.slot.sha256}</p>{value.members.length ? value.members.map(member => <HistoricalMember key={member.key} member={member} />) : <p role="status">所选设备包中没有与本次精确条件匹配的历史记录。此结论仅适用于这个包。</p>}</div> : null}
  </section>;
}
