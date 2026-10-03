"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ApiError, tireApi } from "@tire/api-client";
import type { GarageRecord, OfflineHostStatus, AnyOfflinePlan as OfflinePlan, OfflineReferenceV2 as OfflineReference, OfflineReadResult, OfflineScopeV2 as OfflineScope, OfflineSearchResult, OfflineSlot, WatchItem } from "@tire/domain-types";
import { useWorkbenchPlatform, type WorkbenchPlatform } from "./workbench-platform";
import { defaultOfflineScope } from "./offline-values";
import { offlineError } from "./offline-crypto";
import { resetBrowserOfflineOwner } from "./browser-offline-store";
import { DataTree } from "./reparse-review";
import { RecallAnalysisBoundary, RecallEvidenceMeta } from "./recall-evidence-meta";
import DeviceSyncPanel from "./device-sync-panel";
import { DeviceFallbackPolicySummary } from "./query-fallback-policy";

const stamp = (value?: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "未记录";
const bytes = (value: number) => `${(value / 1024 / 1024).toFixed(2)} MiB`;
const errorText = (cause: unknown) => cause instanceof ApiError ? cause.message : offlineError(cause).message;
const kinds = { tire: "轮胎规格", vehicle: "车型依据", test_event: "测试记录", recall: "正式召回 / 空观察", recall_search: "召回检索候选页", garage: "车库档案", watchlist: "关注记录" };
const selectors = { garage: "车库", watchlist: "关注", recent: "最近正式查询", explicit: "明确选择" };
const sourceLink = (value: string | null) => { try { const url = new URL(value || ""); return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : undefined; } catch { return undefined; } };

export function OfflinePlanDialog({ platform, references = [], replacing, onClose, onInstalled }: {
  platform: WorkbenchPlatform; references?: OfflineReference[]; replacing?: OfflineSlot; onClose: () => void; onInstalled: (slot: OfflineSlot) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null), operation = useRef<AbortController | null>(null);
  const attempt = useRef<{ planId: string; key: string; slotId: string } | null>(null);
  const [scope, setScope] = useState<OfflineScope>(() => references.length ? { garage: { include: false, vehicle_ids: null }, watchlist: { include: false, item_ids: null }, recent: { include: false, limit: 20 }, references } : defaultOfflineScope());
  const [plan, setPlan] = useState<OfflinePlan | null>(null), [consent, setConsent] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [catalog, setCatalog] = useState<{ garage: GarageRecord[]; watches: WatchItem[]; offset: number; hasMore: boolean } | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [baseReady, setBaseReady] = useState(!replacing), [previewPage, setPreviewPage] = useState(0);
  useEffect(() => {
    const node = dialog.current, focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    if (replacing) void perform(async signal => {
      const descriptor = await tireApi.offlinePack(replacing.package_id, signal);
      const original = await tireApi.offlinePlanDetail(descriptor.plan_id, signal);
      if (!signal.aborted) { setScope(original.requested_scope); setBaseReady(true); }
    });
    return () => { operation.current?.abort(); operation.current = null; node?.close(); if (focus?.isConnected && !focus.closest("dialog:not([open])")) focus.focus({ preventScroll: true }); };
  }, []);
  function change(next: OfflineScope) { if (busy || accepted) return; setScope(next); setPlan(null); setConsent(false); setError(""); attempt.current = null; }
  async function perform(work: (signal: AbortSignal) => Promise<void>) {
    if (operation.current) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError("");
    try { await work(controller.signal); } catch (cause) { if (!controller.signal.aborted) setError(errorText(cause)); }
    finally { if (operation.current === controller) operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }
  async function loadChoices(offset = 0) {
    await perform(async signal => {
      const [garage, watches] = await Promise.all([tireApi.garage(false, signal, offset), tireApi.watchlists(signal)]);
      if (!signal.aborted) setCatalog({ garage: garage.items, watches: watches.items, offset, hasMore: garage.items.length === garage.limit });
    });
  }
  async function prepare() {
    if (accepted || !baseReady) return;
    setPlan(null); setConsent(false); setPreviewPage(0);
    await perform(async signal => { const value = await tireApi.offlinePlanV2({ mode: "history", scope, base_pack_id: replacing?.package_id || null, supported_pack_schemas: ["offline-pack@1", "offline-pack@2"] }, signal); if (!signal.aborted) { setPlan(value); attempt.current = null; } });
  }
  async function install() {
    if (!plan?.can_confirm || !consent || !platform.offline || busy) return;
    const value = attempt.current || { planId: plan.id, key: crypto.randomUUID(), slotId: replacing?.slot_id || crypto.randomUUID() };
    attempt.current = value; setAccepted(true);
    await perform(async signal => {
      const descriptor = await tireApi.confirmOfflinePack({ plan_id: value.planId, expected_fingerprint: plan.fingerprint, allow_device_storage: true }, value.key, signal);
      if (signal.aborted) return;
      if (descriptor.plan_fingerprint !== plan.fingerprint || descriptor.id !== plan.package_id || descriptor.sha256 !== plan.content_sha256 || descriptor.byte_count !== plan.measured_bytes) throw new Error("OFFLINE_HASH_MISMATCH");
      const slot = await platform.offline!.install({ package_id: descriptor.id, expected_sha256: descriptor.sha256, expected_byte_count: descriptor.byte_count,
        approved_plan_fingerprint: plan.fingerprint, slot_id: value.slotId, expected_generation: replacing?.generation || 0, allow_device_storage: true }, signal);
      if (!signal.aborted) { onInstalled(slot); onClose(); }
    });
  }
  return <dialog ref={dialog} className="fact-review-dialog offline-dialog" aria-labelledby="offline-plan-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">SAVE HISTORY ON THIS DEVICE</span><h2 id="offline-plan-title">{replacing ? "预览设备资料更新" : "预览保存到设备的资料"}</h2></div><button className="text-button" onClick={onClose}>关闭</button></header>
    <div className="offline-content"><p className="review-boundary">只打包已经采纳的历史事实和短引用，不访问官网、不调用 AI。完整原文、图片与媒体不包含在此包中。保存到设备不授权在线查询自动使用旧参数。</p>
      {error ? <p className="inline-error" role="alert">{error}</p> : null}
      {!baseReady ? <p role="status">正在读取旧包明确批准的范围；读取成功前不生成更新计划。</p> : null}
      <fieldset className="offline-scope" disabled={busy || accepted || !baseReady}><legend>选择保存范围</legend>
        <label><input type="checkbox" checked={scope.garage.include} onChange={event => change({ ...scope, garage: { ...scope.garage, include: event.target.checked } })} />车库档案与关联证据 · 本地工作区</label>
        <label><input type="checkbox" checked={scope.watchlist.include} onChange={event => change({ ...scope, watchlist: { ...scope.watchlist, include: event.target.checked } })} />我的关注与关联证据 · 当前会话</label>
        <label><input type="checkbox" checked={scope.recent.include} onChange={event => change({ ...scope, recent: { ...scope.recent, include: event.target.checked } })} />最近查询产生的正式证据 · 当前会话</label>
        <label className="offline-recent-limit">最近查询数量<input type="number" min={0} max={20} value={scope.recent.limit} disabled={!scope.recent.include} onChange={event => change({ ...scope, recent: { ...scope.recent, limit: Math.max(0, Math.min(20, Math.trunc(event.target.valueAsNumber || 0))) } })} /></label>
        <p>车库资料与当前会话的关注、最近查询分别保存。档案由用户填写，不能当作官方事实；不自动保存未采纳候选或 reparse 输出。</p>
        <button type="button" className="text-button" onClick={() => void loadChoices()}>挑选具体车库与关注记录</button>
        {catalog ? <div className="offline-specific-scope"><fieldset><legend>车库档案</legend><label><input type="radio" name="offline-garage-scope" checked={scope.garage.vehicle_ids === null} onChange={() => change({ ...scope, garage: { include: true, vehicle_ids: null } })} />全部使用中的档案</label><label><input type="radio" name="offline-garage-scope" checked={scope.garage.vehicle_ids !== null} onChange={() => change({ ...scope, garage: { include: true, vehicle_ids: [] } })} />只保存勾选的档案</label>
          {scope.garage.vehicle_ids !== null ? catalog.garage.map(item => <label key={item.id}><input type="checkbox" checked={scope.garage.vehicle_ids!.includes(item.id)} onChange={() => change({ ...scope, garage: { include: true, vehicle_ids: scope.garage.vehicle_ids!.includes(item.id) ? scope.garage.vehicle_ids!.filter(id => id !== item.id) : [...scope.garage.vehicle_ids!, item.id] } })} />{item.profile.nickname || item.profile.model} · 修订 #{item.revision}</label>) : null}
          <div className="compare-toolbar"><button className="text-button" disabled={!catalog.offset} onClick={() => void loadChoices(Math.max(0, catalog.offset - 20))}>上一页档案</button><button className="text-button" disabled={!catalog.hasMore} onClick={() => void loadChoices(catalog.offset + catalog.garage.length)}>下一页档案</button></div></fieldset>
          <fieldset><legend>关注记录</legend><label><input type="radio" name="offline-watch-scope" checked={scope.watchlist.item_ids === null} onChange={() => change({ ...scope, watchlist: { include: true, item_ids: null } })} />全部当前会话关注</label><label><input type="radio" name="offline-watch-scope" checked={scope.watchlist.item_ids !== null} onChange={() => change({ ...scope, watchlist: { include: true, item_ids: [] } })} />只保存勾选的关注</label>
          {scope.watchlist.item_ids !== null ? catalog.watches.map(item => <label key={item.id}><input type="checkbox" checked={scope.watchlist.item_ids!.includes(item.id)} onChange={() => change({ ...scope, watchlist: { include: true, item_ids: scope.watchlist.item_ids!.includes(item.id) ? scope.watchlist.item_ids!.filter(id => id !== item.id) : [...scope.watchlist.item_ids!, item.id] } })} />{item.variant ? `${item.variant.brand} ${item.variant.model} · ${item.variant.size}` : item.variant_id}</label>) : null}</fieldset></div> : null}
        {scope.references.length ? <details open><summary>明确选中的 {scope.references.length} 份精确证据</summary>{scope.references.map((reference, index) => <div className="offline-reference" key={index}><span>{kinds[reference.kind]} · {"snapshot_id" in reference ? reference.snapshot_id : `${reference.event_id} #${reference.event_revision}`}</span><button type="button" className="text-button" onClick={() => change({ ...scope, references: scope.references.filter((_, position) => position !== index) })}>移除此引用</button></div>)}</details> : null}
      </fieldset>
      {!accepted ? <button type="button" className="secondary-button" disabled={busy || !baseReady} onClick={() => void prepare()}>{busy ? "正在读取历史范围…" : "生成本次内容预览"}</button> : <><p className="review-boundary">本次计划与确认标识已固定。失败后沿用相同标识核对；关闭不会保证已经受理的安装被取消，请重开设备库核对。</p><button className="text-button" disabled={busy} onClick={() => { setAccepted(false); setPlan(null); setConsent(false); setError(""); attempt.current = null; }}>重新选择范围与预览</button></>}
      {plan ? <section className="offline-plan-preview" aria-label="设备离线内容预览"><h3>{plan.can_confirm ? "核对将保存的内容" : "此范围暂不能保存"}</h3>
        <p><strong>{bytes(plan.measured_bytes)} / {bytes(plan.capacity.max_package_bytes)}</strong> · {plan.counts.distinct_evidence} / {plan.capacity.max_distinct_evidence} 份不同证据 · {plan.counts.searchable_documents} / {plan.capacity.max_searchable_documents} 条可检索记录</p>
        <p>车库档案 {plan.counts.garage_profiles} / {plan.capacity.max_garage_profiles} · 关注 {plan.counts.watch_items} / {plan.capacity.max_watch_items} · 最近查询 {plan.counts.recent_queries} / {plan.capacity.max_recent_query_candidates}</p>
        <p>内容冻结 {stamp(plan.created_at)} · 本次授权窗口至 {stamp(plan.expires_at)}。容量超限时请调整范围重新预览，系统不会删掉部分记录后假称完整。</p>
        <p className="review-boundary">{plan.privacy_notice}</p><p className="review-boundary">{plan.rights_notice}</p>
        <details><summary>核对将保存的个人档案与关注（{plan.contexts.length} 条）</summary>{plan.contexts.map(context => <article key={context.id}><strong>{context.kind === "garage" ? "车库档案 · 本地工作区" : "关注记录 · 当前会话"}</strong><DataTree label="本次实际保存的个人资料" value={context.payload} /></article>)}</details>
        <details><summary>核对来源标题、产品范围与时间（{plan.documents.length} 条）</summary>{plan.documents.slice(previewPage * 50, previewPage * 50 + 50).map(document => <article key={document.id}><strong>{document.title}</strong><p>{kinds[document.kind]} · {document.record_index === null ? "完整历史观察 / 档案" : `产品记录 ${document.record_index + 1}`}</p><p>{[document.facets.brand, document.facets.model, document.facets.size, document.facets.campaign_number].filter(Boolean).join(" · ")}</p><p>观察 {stamp(document.observed_at)} · 核验 {stamp(document.verified_at)}</p><details><summary>短引用与检索字段</summary><p>{document.text}</p></details></article>)}<div className="compare-toolbar"><button className="text-button" disabled={!previewPage} onClick={() => setPreviewPage(value => value - 1)}>上一页预览</button><span>第 {previewPage + 1} / {Math.max(1, Math.ceil(plan.documents.length / 50))} 页，全部记录均计入包</span><button className="text-button" disabled={(previewPage + 1) * 50 >= plan.documents.length} onClick={() => setPreviewPage(value => value + 1)}>下一页预览</button></div></details>
        {replacing ? <p>更新差异：新增 {plan.diff.added.length}，移除 {plan.diff.removed.length}，变化 {plan.diff.changed.length}。新包验证完成前保留现有版本。</p> : null}
        <details><summary>逐项核对精确版本与入包原因（{plan.resolved.length} 份）</summary>{plan.resolved.map(item => <article key={item.key}><strong>{kinds[item.reference.kind]}</strong><p>{item.member_reasons.map(reason => `${selectors[reason.selector]}${reason.revision ? ` #${reason.revision}` : ""}`).join("；")}</p><code>{JSON.stringify(item.reference)}</code></article>)}</details>
        {plan.omissions.length ? <details open><summary>未包含的内容与限制（{plan.omissions.length} 项）</summary><ul>{plan.omissions.map((item, index) => <li key={index}>{item.blocking ? "需要调整范围：" : "未包含："}{item.reason}{item.object_id ? <small> · {item.object_id}</small> : null}</li>)}</ul></details> : null}
        <label className="review-checkbox"><input type="checkbox" checked={consent} disabled={!plan.can_confirm || busy || accepted} onChange={event => setConsent(event.target.checked)} />我允许将上述私有历史材料保存在{platform.kind === "web" ? "此浏览器资料空间" : "此设备应用"}，用于主动离线查看。</label>
        <p>仅手动更新。安装时间不是来源核验时间。{platform.kind === "web" ? "浏览器密钥受同一站点和浏览器资料空间保护，不等于系统硬件密钥隔离；清理站点数据或存储回收可能移除资料。" : "本机密钥与文件由原生应用保护；在线会话重置后旧资料会锁定，需单独确认查看。"}</p>
        <button type="button" className="primary-button" disabled={!plan.can_confirm || !consent || busy || !platform.offline} onClick={() => void install()}>{busy ? "正在核对并保存…" : accepted ? "核对同一次保存" : "确认保存到此设备"}</button>
      </section> : null}
    </div>
  </dialog>;
}

function OfflineDetail({ detail }: { detail: OfflineReadResult }) {
  const { member, context, document, slot } = detail;
  const payload = member?.payload;
  return <section className="offline-detail" aria-label="设备历史资料详情"><h3>{document.title}</h3>
    <p className="snapshot-banner"><strong>DEVICE HISTORY · LOCAL SNAPSHOT</strong><span>设备版本 #{slot.generation} · 保存到本机 {stamp(slot.installed_at)}</span></p>
    {slot.previous_owner ? <p className="review-warning">这是已单独确认查看的旧归属设备副本，不属于当前在线会话。</p> : null}
    {context ? <><p className="review-boundary">{context.kind === "garage" ? "车库档案 · 本地工作区的用户资料" : "关注记录 · 保存时会话的个人选择"}。这些内容不构成官方轮胎参数，也没有回写当前工作区。</p><DataTree label="保存的个人资料与关联" value={context.payload} /></> : null}
    {member ? <><p>来源观察 {stamp(member.source.observed_at)} · 来源核验 {stamp(member.source.verified_at)}</p><p className="review-boundary">以上时间属于原始历史证据；离线打开、下载或更新检查不会重新核验来源。本包不包含完整原文或图片。</p>
      {member.reference.kind === "recall" && payload ? <><RecallAnalysisBoundary boundary={payload.boundary as import("@tire/domain-types").RecallBoundary} /><RecallEvidenceMeta evidence={payload.evidence as import("@tire/domain-types").AIEvidence} />{document.record_index !== null ? <DataTree label={`本条命中的完整公告产品记录 ${document.record_index + 1}`} value={(payload.records as unknown[])[document.record_index]} /> : null}<DataTree label="此公告观察的全部产品记录与固定边界" value={{ records: payload.records, boundary: payload.boundary }} /></> : null}
      {member.reference.kind === "tire" && payload ? <><DataTree label="精确轮胎规格 · 保存时原始字段" value={payload.variant} /><DataTree label="保存时身份合同" value={payload.identity_contract} /><DataTree label="保存时字段规则、默认值与全部候选" value={payload.field_resolution} /></> : null}
      {member.reference.kind === "vehicle" && payload ? <DataTree label="所选历史车型与配置依据" value={payload} /> : null}
      {member.reference.kind === "recall_search" && payload ? <><p className="review-boundary">此历史检索只保存一页候选和当时分页；未采纳为正式召回版本，具体 SKU、DOT/TIN 与生产批次适用性未评估。空页不表示无风险。</p><DataTree label="冻结候选产品、原页码与边界" value={payload} /></> : null}
      {member.reference.kind === "test_event" && payload ? <><p className="review-boundary">人工转录测试事件 · 尚未核验；仅保留所选事件版本，不能跨事件排名。</p><DataTree label="冻结测试事件与参与产品" value={payload} /></> : null}
      <details><summary>核对来源与版本校验值</summary><DataTree label="精确引用" value={member.reference} /><p>Parser {member.source.parser_version || "人工记录"}</p><p>原文 SHA-256 <code>{member.source.raw_hash || "未记录"}</code></p><p>包 SHA-256 <code>{slot.sha256}</code></p>{sourceLink(member.source.source_url) ? <a href={sourceLink(member.source.source_url)} target="_blank" rel="noopener noreferrer">联网后通过浏览器打开来源</a> : <p>未保存可打开的来源地址。</p>}</details>
    </> : null}
  </section>;
}

export default function OfflineLibraryDialog({ platform: supplied, references, onlineEnabled = true, onClose }: {
  platform?: WorkbenchPlatform; references?: OfflineReference[]; onlineEnabled?: boolean; onClose: () => void;
}) {
  const inherited = useWorkbenchPlatform(), platform = supplied || inherited, storage = platform.offline;
  const [portalTheme] = useState(() => typeof document === "undefined" ? "light" : document.querySelector<HTMLElement>(".app-shell")?.dataset.theme || document.documentElement.dataset.mobileTheme || "light");
  const dialog = useRef<HTMLDialogElement>(null), generation = useRef(0);
  const [status, setStatus] = useState<OfflineHostStatus | null>(null), [items, setItems] = useState<OfflineSlot[]>([]);
  const [selected, setSelected] = useState<OfflineSlot | null>(null), [search, setSearch] = useState<OfflineSearchResult | null>(null), [detail, setDetail] = useState<OfflineReadResult | null>(null);
  const [query, setQuery] = useState(""), [kind, setKind] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [plan, setPlan] = useState<{ replacing?: OfflineSlot; references?: OfflineReference[] } | null>(null);
  const [confirmation, setConfirmation] = useState<"remove" | "unlock" | "reset" | null>(null);
  useEffect(() => {
    const node = dialog.current, focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal(); void refresh();
    if (references?.length) setPlan({ references });
    const ownerChanged = () => { generation.current++; setBusy(false); setSelected(null); setSearch(null); setDetail(null); setPlan(null); setItems([]); setNotice("本机资料归属已变化，请重新读取；旧资料仍须单独确认查看。"); };
    window.addEventListener("tire-offline-owner-changed", ownerChanged);
    return () => { window.removeEventListener("tire-offline-owner-changed", ownerChanged); generation.current++; node?.close(); if (focus?.isConnected && !focus.closest("dialog:not([open])")) focus.focus({ preventScroll: true }); };
  }, []);
  async function perform(work: (current: () => boolean) => Promise<void>) {
    if (busy || !storage) return;
    const token = ++generation.current; setBusy(true); setError("");
    const current = () => generation.current === token;
    try { await work(current); } catch (cause) { if (current()) setError(errorText(cause)); } finally { if (current()) setBusy(false); }
  }
  async function refresh() {
    await perform(async current => {
      const capability = await storage!.status(); if (!current()) return; setStatus(capability);
      if (!capability.available) { setItems([]); setSelected(null); setSearch(null); setDetail(null); setError(offlineError(capability.error || "OFFLINE_UNAVAILABLE").message); return; }
      const value = await storage!.list(); if (!current()) return; setItems(value.items);
      setSelected(previous => previous ? value.items.find(item => item.slot_id === previous.slot_id && item.generation === previous.generation) || null : null);
      setSearch(null); setDetail(null);
    });
  }
  async function select(slot: OfflineSlot) {
    setSelected(slot); setDetail(null); setSearch(null); setConfirmation(null); setQuery(""); setKind("");
    if (slot.locked) return;
    await perform(async current => { const value = await storage!.search({ slot_id: slot.slot_id, expected_generation: slot.generation, query: "", offset: 0, limit: 20 }); if (current()) setSearch(value); });
  }
  async function find(offset = 0) {
    if (!selected || selected.locked) return;
    setDetail(null);
    await perform(async current => { const value = await storage!.search({ slot_id: selected.slot_id, expected_generation: selected.generation, query, ...(kind ? { kind: kind as import("@tire/domain-types").OfflineDocument["kind"] } : {}), offset, limit: 20 }); if (current()) { setSearch(value); setDetail(null); } });
  }
  async function read(documentId: string) {
    if (!selected || selected.locked) return;
    setDetail(null);
    await perform(async current => { const value = await storage!.read({ slot_id: selected.slot_id, expected_generation: selected.generation, document_id: documentId }); if (current()) setDetail(value); });
  }
  async function confirm() {
    const action = confirmation; setConfirmation(null);
    await perform(async current => {
      if (action === "reset") { await resetBrowserOfflineOwner(); if (current()) setNotice("旧设备资料已锁定，密文仍保留。重新查看须单独确认旧归属历史。"); }
      else if (selected && action === "remove") { await storage!.remove({ slot_id: selected.slot_id, expected_generation: selected.generation }); if (current()) setNotice("已删除本设备所选包；服务器资料与其他设备不受影响。"); }
      else if (selected && action === "unlock") { await storage!.unlockPreviousOwner({ slot_id: selected.slot_id, expected_generation: selected.generation, allow_previous_owner: true }); if (current()) setNotice("已允许查看此份旧设备历史，仍保留原归属标记。"); }
      if (!current()) return;
      const value = await storage!.list(); if (current()) { setItems(value.items); setSelected(null); setSearch(null); setDetail(null); setStatus(await storage!.status()); }
    });
  }
  if (typeof document === "undefined") return null;
  return createPortal(<div className="offline-portal" data-theme={portalTheme}><dialog ref={dialog} className="fact-review-dialog offline-dialog" aria-labelledby="offline-library-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">DEVICE HISTORY</span><h2 id="offline-library-title">设备离线资料库</h2><p>主动查看本设备保存的历史资料。</p></div><button type="button" className="text-button" onClick={onClose}>关闭</button></header>
    <div className="offline-content"><div className="snapshot-banner"><strong>LOCAL SNAPSHOT · 与在线查询分别使用</strong><span>打开此库不需要 API 连接。这里的资料不表示当前参数、当前召回状态或具体轮胎适用性，也不会自动回填在线查询。</span></div>
      {storage ? <DeviceFallbackPolicySummary storage={storage} /> : null}
      {!storage ? <p className="inline-error" role="alert">此宿主没有提供设备离线存储能力。</p> : null}
      {error ? <p className="inline-error" role="alert">{error}</p> : null}{notice ? <p className="review-boundary" role="status">{notice}</p> : null}
      <div className="compare-toolbar"><button type="button" className="primary-button" disabled={busy || !onlineEnabled || !status?.available} onClick={() => setPlan({})}>选择范围并保存到设备</button><button type="button" className="text-button" disabled={busy || !storage} onClick={() => void refresh()}>重新读取本机资料</button></div>
      {!onlineEnabled ? <p>当前可查看已经保存的包；新建或更新内容需恢复连接后明确预览。</p> : null}
      {status ? <details className="offline-storage-status"><summary>本设备存储与更新能力</summary><p>{platform.kind === "web" ? "当前站点 / 浏览器资料空间 · WebCrypto 加密" : platform.kind === "desktop" ? "当前桌面应用资料空间 · 系统安全存储密钥" : "当前 Android 应用资料空间 · Keystore 密钥"}</p><p>{bytes(status.total_bytes)} / {bytes(status.max_store_bytes)} 已提交原始包字节；最多 {status.max_slots} 份包。加密开销与临时保存另计。</p><p>手动保存仍逐次预览。持续更新另需按包预览并明确授权，执行能力与条件显示在所选包中。</p>{platform.kind === "web" ? <><p>{status.persistence === "persistent_granted" ? "浏览器已授予持久存储。" : "浏览器存储为尽力保留，空间回收或清理站点数据可能移除资料。"}浏览器密钥的保护范围是同一站点与浏览器资料空间，不等于系统硬件密钥隔离。</p><button type="button" className="text-button" disabled={busy} onClick={() => setConfirmation("reset")}>锁定旧资料，切换本地归属</button></> : null}<small>本地资料空间 {status.profile_id || "不可用"} · 归属版本 {status.owner_epoch}</small></details> : null}
      {confirmation ? <section className="consent-box" aria-label="确认设备资料操作"><h3>{confirmation === "remove" ? "删除此设备上的资料包？" : confirmation === "unlock" ? "确认查看旧归属的设备历史？" : "锁定现有设备资料并切换归属？"}</h3><p>{confirmation === "unlock" ? "这些私有资料来自原归属，确认后仍标为旧设备历史，不会合并为当前在线会话的数据。" : confirmation === "remove" ? "只移除此设备上的副本，不删除服务器内容。" : "此浏览器当前保存的资料将保持密文并锁定；不会修改服务器会话或工作区。"}</p><div className="compare-toolbar"><button className="secondary-button" disabled={busy} onClick={() => void confirm()}>确认{confirmation === "remove" ? "删除" : confirmation === "unlock" ? "查看旧历史" : "切换归属"}</button><button className="text-button" onClick={() => setConfirmation(null)}>取消</button></div></section> : null}
      <div className="offline-layout"><section className="offline-pack-list" aria-label="本机资料包"><h3>本机已保存 {items.length} 份</h3>{items.map(item => <button type="button" className={`offline-pack-item${selected?.slot_id === item.slot_id ? " selected" : ""}`} key={item.slot_id} disabled={busy} onClick={() => void select(item)}><strong>{item.title}</strong><span>本机版本 #{item.generation} · {bytes(item.byte_count)}</span><span>内容冻结 {stamp(item.created_at)}</span><span>本机安装 {stamp(item.installed_at)}</span>{item.previous_owner ? <span className="tag warning">{item.locked ? "旧归属 · 已锁定" : "旧归属 · 仅历史查看"}</span> : null}</button>)}{!items.length && !busy ? <p>此设备目前没有可读取的资料包。首次使用需连接后明确保存；清理站点数据也可能移除以前的副本。</p> : null}</section>
        <section aria-label="包内检索与内容">{selected ? <><h3>{selected.title}</h3><div className="compare-toolbar">{selected.locked ? <button className="secondary-button" disabled={busy} onClick={() => setConfirmation("unlock")}>单独确认查看旧设备历史</button> : null}<button className="secondary-button" disabled={busy || !onlineEnabled || selected.previous_owner} onClick={() => setPlan({ replacing: selected })}>手动预览更新</button><button className="text-button" disabled={busy} onClick={() => setConfirmation("remove")}>删除本机包</button></div>
          {selected.previous_owner ? <p className="review-warning">此包保留旧归属标签；不使用当前会话覆盖它。需要当前资料时，请另行预览保存。</p> : null}
          {storage ? <DeviceSyncPanel key={`${selected.slot_id}:${selected.generation}`} storage={storage} slot={selected} /> : null}
          {!selected.locked ? <><form className="offline-search" onSubmit={event => { event.preventDefault(); void find(); }}><label>包内关键词<input maxLength={500} value={query} onChange={event => setQuery(event.target.value)} /></label><label>资料类别<select aria-label="离线资料类别" value={kind} onChange={event => setKind(event.target.value)}><option value="">全部类别</option>{Object.entries(kinds).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label><button className="secondary-button" disabled={busy}>搜索本机历史</button></form>
            {search ? <><p role="status">此包匹配 {search.total} 条，显示 {search.items.length} 条。文本匹配仅在本机执行，不调用模型。</p>{search.items.map(document => <button type="button" className="offline-search-item" key={document.id} disabled={busy} onClick={() => void read(document.id)}><strong>{document.title}</strong><span>{kinds[document.kind]} · {document.category === "evidence" ? "来源证据" : "用户资料"}</span><small>{document.membership.map(member => selectors[member]).join(" · ")}{document.record_index !== null ? ` · 产品记录 ${document.record_index + 1}` : ""}</small></button>)}<div className="compare-toolbar"><button className="text-button" disabled={busy || !search.offset} onClick={() => void find(Math.max(0, search.offset - search.limit))}>上一页资料</button><button className="text-button" disabled={busy || !search.has_more} onClick={() => void find(search.offset + search.limit)}>下一页资料</button></div></> : null}{detail ? <OfflineDetail detail={detail} /> : null}</> : <p>未确认前不读取此包的证据与个人内容。</p>}
        </> : <p>选择本机包，查看其中的冻结事实与个人资料。</p>}</section></div>
    </div>
  </dialog>{plan ? <OfflinePlanDialog platform={platform} references={plan.references} replacing={plan.replacing} onClose={() => setPlan(null)} onInstalled={slot => { setNotice(`已保存本机版本 #${slot.generation}，未重新核验来源。`); void refresh(); }} /> : null}</div>, document.body);
}

export function OfflineLibraryEntry({ platform, onlineEnabled = true, className = "text-button" }: { platform?: WorkbenchPlatform; onlineEnabled?: boolean; className?: string }) {
  const [open, setOpen] = useState(false);
  return <><button type="button" className={className} onClick={() => setOpen(true)}>设备离线资料库</button>{open ? <OfflineLibraryDialog platform={platform} onlineEnabled={onlineEnabled} onClose={() => setOpen(false)} /> : null}</>;
}
