import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { tireApi } from "@tire/api-client";
import type { AIStreamDetail, OfflineHostStatus, OfflineReadResult, OfflineSearchResult, OfflineSlot } from "@tire/domain-types";
import type { WorkbenchPlatform } from "../../web/components/workbench-platform";
import { advanceAIEvent, aiStreamStateLabels, visibleAIDrafts, type AIEventPosition } from "../../web/components/ai-stream-values";
import {
  deviceAiDomainLabel, deviceAiDomainLabels, deviceAiEventLabels, deviceAiHostErrorMessage, deviceAiOutcomeLabel,
  deviceAiProjectionModeLabel, deviceProviderPolicyFingerprint, parseDeviceAiRecovery, rememberDeviceAiRecovery,
  type DeviceAiRecoveryPointer,
} from "../../web/components/device-ai-values";
import type { DeviceAiLocalPreviewSummary, DeviceAiOriginBindingWire, DeviceAiPrepareBody, DeviceAiPrepareResultView, DeviceAiProviderConsentBody, DeviceAiPrepareSelectorWire } from "../../../packages/api-client/src/device-ai-host";
import type { DeviceAiProjectionMode } from "../../../packages/api-client/src/device-ai-projection";
import {
  createMobileDeviceAiBridge, createMobileIntentCache, DEVICE_AI_PREPARE_DOMAIN_MODES, mobileFailureCode, mobileFailureStage,
  mobileJournalEventForClaim, mobileJournalEventForDecision, mobileJournalEventForFailure, mobileJournalEventForOutcome,
  mobileJournalEventForPrepareCreated, mobileJournalEventForPreview, mobileLocalPreview, mobileSelectorFromRead,
  MOBILE_DEVICE_AI_DOMAINS, type MobileDeviceAiDomain, type MobileDeviceAiJournalEvent, type MobileDeviceAiJournalReport,
  type MobileDeviceAiUnknownOutcome,
} from "./device-ai-mobile";
import { createMobileInvoke, type TireNativePlugin } from "./native-platform";

/**
 * Mobile device-AI panel (round 50 P1): the TireNativePlugin commands
 * (deviceAiPrepare -> deviceAiSubmitStream -> 事件轮询 -> deviceAiJournalRead)
 * over the four-domain closed DTO, with a local preview recomputed by the
 * packages projection port over archive bytes fetched through the standard
 * native API transport and sha256-bound to the slot. 各环节经
 * deviceAiJournalAppend 写入本机加密台账；未知结果恢复走
 * deviceAiResolveUnknown（N18 lookup-first，绝不自动重放）。
 *
 * 流式消费决策：移动端无既有 SSE 桥（原生请求注册表按整请求收发），沿用
 * AIStreamProgress 原生分支的既有先例 —— 通过标准 API 通道用
 * tireApi.aiStreamEvents/aiStream 游标轮询读取同一调用的已保存进度，绝不
 * 重复提交模型调用。
 */

type Phase = "select" | "preview" | "prepared" | "submitted";

interface DomainChoice {
  slot: OfflineSlot;
  domain: MobileDeviceAiDomain;
  mode: DeviceAiProjectionMode;
  selectors: DeviceAiPrepareSelectorWire[];
  reads: OfflineReadResult[];
}

/** 原样冻结的提交载荷：N18 同 key 同 body 重放核对的唯一来源（不落盘）。 */
interface FrozenSubmission {
  intentId: string;
  prepareKey: string;
  analysisKey: string;
  packId: string;
  prepareId: string;
  hostReceiptId: string;
  deviceContextFingerprint: string;
  question: string;
  consent: DeviceAiProviderConsentBody;
}

const stamp = (value?: string | null) => (value ? new Date(value).toLocaleString("zh-CN") : "未记录");
const isProviderFailure = (code?: string | null) => !!code && (code.startsWith("ai_provider_") || code === "ai_refused" || code === "ai_response_incomplete");

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const cancel = () => { clearTimeout(timer); signal.removeEventListener("abort", cancel); reject(new DOMException("停止读取进度。", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", cancel); resolve(); }, ms);
    if (signal.aborted) cancel();
    else signal.addEventListener("abort", cancel, { once: true });
  });
}

export function MobileDeviceAiEntry({ plugin, online, platform }: { plugin: TireNativePlugin; online: boolean; platform: WorkbenchPlatform }) {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" disabled={!online} title={online ? "设备 AI 分析（本机预览 · 四域历史观察）" : "连接就绪后可用设备 AI 分析"} onClick={() => setOpen(true)}>设备 AI</button>
    {open ? <MobileDeviceAiDialog plugin={plugin} platform={platform} onClose={() => setOpen(false)} /> : null}
  </>;
}

export default function MobileDeviceAiDialog({ plugin, platform, onClose }: { plugin: TireNativePlugin; platform: WorkbenchPlatform; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const operation = useRef<AbortController | null>(null);
  const poller = useRef<AbortController | null>(null);
  const pollGeneration = useRef(0);
  const sessionId = useRef(crypto.randomUUID());
  const [status, setStatus] = useState<OfflineHostStatus | null>(null);
  const [slots, setSlots] = useState<OfflineSlot[]>([]);
  const [selectedSlot, setSelectedSlot] = useState<OfflineSlot | null>(null);
  const [domain, setDomain] = useState<MobileDeviceAiDomain>("tire");
  const [search, setSearch] = useState<OfflineSearchResult | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [choice, setChoice] = useState<DomainChoice | null>(null);
  const [phase, setPhase] = useState<Phase>("select");
  const [question, setQuestion] = useState("解读这条设备历史轮胎观察中的字段候选与身份合同，说明证据限制。");
  const [preview, setPreview] = useState<DeviceAiLocalPreviewSummary | null>(null);
  const [prepareBody, setPrepareBody] = useState<DeviceAiPrepareBody | null>(null);
  const [exportConsent, setExportConsent] = useState(false);
  const [closureConsent, setClosureConsent] = useState(false);
  const [preparation, setPreparation] = useState<DeviceAiPrepareResultView | null>(null);
  const [providerPreview, setProviderPreview] = useState<Record<string, unknown> | null>(null);
  const [providerConsent, setProviderConsent] = useState(false);
  const [stream, setStream] = useState<AIStreamDetail | null>(null);
  const [pollState, setPollState] = useState<"polling" | "finished" | "disconnected" | "unavailable">("polling");
  const [journal, setJournal] = useState<MobileDeviceAiJournalReport | null>(null);
  const [journalError, setJournalError] = useState("");
  const [recovery, setRecovery] = useState<DeviceAiRecoveryPointer | null>(null);
  const [recoveryResult, setRecoveryResult] = useState<MobileDeviceAiUnknownOutcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const statusRef = useRef<OfflineHostStatus | null>(null);
  const originRef = useRef<DeviceAiOriginBindingWire | null>(null);
  const analysisKeyRef = useRef<string | null>(null);
  const consentRef = useRef<{ packId: string; prepareId: string; hostReceiptId: string; fingerprint: string; question: string } | null>(null);
  const activeIntent = useRef<string | null>(null);
  const activePrepareKey = useRef<string | null>(null);
  const frozenSubmission = useRef<FrozenSubmission | null>(null);
  const terminalRecorded = useRef<string | null>(null);
  const intentFor = useRef(createMobileIntentCache()).current;

  const bridge = useRef(createMobileDeviceAiBridge(createMobileInvoke(plugin))).current;

  const perform = useCallback(async (work: (signal: AbortSignal) => Promise<void>) => {
    if (operation.current) return;
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true); setError("");
    try { await work(controller.signal); }
    catch (cause) { if (!controller.signal.aborted) setError(deviceAiHostErrorMessage(cause)); }
    finally { operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }, []);

  const refreshJournal = useCallback(async () => {
    const active = statusRef.current;
    if (!active?.profile_id) return;
    try {
      setJournal(await bridge.journalRead(active.profile_id, active.owner_epoch, sessionId.current));
    } catch (cause) {
      setJournal(null);
      setError(`台账读取未完成：${deviceAiHostErrorMessage(cause)}`);
    }
  }, [bridge]);

  /** 台账事件写入（Web recordJournal 对位）：写入失败只降级提示，不阻断主流程。 */
  const recordJournal = useCallback(async (event: MobileDeviceAiJournalEvent): Promise<void> => {
    const active = statusRef.current;
    if (!active?.profile_id) return;
    try {
      await bridge.journalAppend(active.profile_id, active.owner_epoch, sessionId.current, event);
      await refreshJournal();
    } catch (cause) {
      setJournalError(`台账写入未完成：${deviceAiHostErrorMessage(cause)}`);
    }
  }, [bridge, refreshJournal]);

  /** 终态入账（Web recordTerminal 对位）：Provider 失败与来源/传输失败分离。 */
  const recordTerminal = useCallback(async (detail: AIStreamDetail) => {
    if (terminalRecorded.current === detail.analysis.id) return;
    terminalRecorded.current = detail.analysis.id;
    if (detail.analysis.error_code) {
      await recordJournal(mobileJournalEventForFailure(activeIntent.current,
        mobileFailureStage(detail.analysis.error_code), detail.analysis.error_code));
    } else {
      await recordJournal(mobileJournalEventForOutcome(activeIntent.current, analysisKeyRef.current ?? detail.analysis.id,
        detail.analysis.id, detail.execution.state));
    }
  }, [recordJournal]);

  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    try { setRecovery(parseDeviceAiRecovery(sessionStorage.getItem("tire-device-ai-recovery-v1"))); } catch { /* Lookup remains possible. */ }
    void perform(async () => {
      if (!platform.offline) throw new Error("此宿主没有设备离线存储能力。");
      const hostStatus = await platform.offline.status();
      statusRef.current = hostStatus;
      setStatus(hostStatus);
      setSlots((await platform.offline.list()).items);
    });
    return () => { operation.current?.abort(); poller.current?.abort(); node?.close(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { void refreshJournal(); }, [refreshJournal, status]);

  /** 事件轮询（移动端流式消费先例：AIStreamProgress 原生分支的游标轮询）。 */
  const followProgress = useCallback((requestId: string, initialCursor: string) => {
    poller.current?.abort();
    const controller = new AbortController();
    poller.current = controller;
    const runGeneration = ++pollGeneration.current;
    const current = () => !controller.signal.aborted && runGeneration === pollGeneration.current;
    setPollState("polling");
    void (async () => {
      let cursor = initialCursor, failures = 0, finished = false;
      try {
        let detail = await tireApi.aiStream(requestId, controller.signal);
        if (current()) setStream(detail);
        finished = detail.execution.terminal;
        if (finished && current()) void recordTerminal(detail);
        let position: AIEventPosition = { cursor, sequence: 0, eventId: null };
        while (current() && !finished) {
          let pages = 0, more = true;
          while (more && current() && !finished && pages < 4) {
            const page = await tireApi.aiStreamEvents(requestId, position.cursor, controller.signal);
            if (!current()) return;
            for (const event of page.items) position = advanceAIEvent(requestId, position, event);
            more = page.has_more; pages++;
            detail = await tireApi.aiStream(requestId, controller.signal);
            if (!current()) return;
            setStream(detail);
            finished = detail.execution.terminal;
            if (finished) void recordTerminal(detail);
          }
          if (!current() || finished) break;
          failures = 0;
          await delay(more ? 500 : 2500, controller.signal);
        }
        if (current()) setPollState(finished ? "finished" : "polling");
      } catch (cause) {
        if (!current() || (cause instanceof Error && cause.name === "AbortError")) return;
        setPollState("disconnected");
        if (++failures >= 5 || !current()) { setError(cause instanceof Error ? cause.message : "分析进度暂时无法读取。"); return; }
        await delay(Math.min(1000 * 2 ** (failures - 1), 8000), controller.signal).catch(() => undefined);
      }
    })();
  }, [recordTerminal]);

  async function selectSlot(slot: OfflineSlot) {
    setChoice(null); setPreview(null); setSearch(null); setPicked([]); setPhase("select"); setError(""); setNotice("");
    setSelectedSlot(slot);
    if (!platform.offline || slot.locked || slot.previous_owner) return;
    await perform(async signal => {
      const value = await platform.offline!.search({ slot_id: slot.slot_id, expected_generation: slot.generation, query: "", kind: domain, offset: 0, limit: 20 });
      if (!signal.aborted) setSearch(value);
    });
  }

  async function selectDomain(next: MobileDeviceAiDomain) {
    if (!selectedSlot || busy) return;
    setDomain(next); setChoice(null); setPreview(null); setPicked([]); setPhase("select"); setError(""); setNotice("");
    if (!platform.offline || selectedSlot.locked || selectedSlot.previous_owner) return;
    await perform(async signal => {
      const value = await platform.offline!.search({ slot_id: selectedSlot.slot_id, expected_generation: selectedSlot.generation, query: "", kind: next, offset: 0, limit: 20 });
      if (!signal.aborted) setSearch(value);
    });
  }

  async function readDocuments(slot: OfflineSlot, documentIds: string[]): Promise<OfflineReadResult[]> {
    if (!platform.offline) throw new Error("此宿主没有设备离线存储能力。");
    const reads: OfflineReadResult[] = [];
    for (const documentId of documentIds) {
      reads.push(await platform.offline.read({ slot_id: slot.slot_id, expected_generation: slot.generation, document_id: documentId }));
    }
    return reads;
  }

  async function selectDocument(documentId: string) {
    if (!selectedSlot) return;
    await perform(async signal => {
      const [read] = await readDocuments(selectedSlot, [documentId]);
      const selectors = [mobileSelectorFromRead(domain, read)];
      if (!signal.aborted) {
        setChoice({ slot: selectedSlot, domain, mode: DEVICE_AI_PREPARE_DOMAIN_MODES[domain], selectors, reads: [read] });
        setPhase("preview"); setPreview(null); setClosureConsent(false);
      }
    });
  }

  /** tire 多选 → 冻结决定闭包入口（N==1 退化为单条观察）。 */
  async function previewPicked() {
    if (!selectedSlot || busy) return;
    await perform(async signal => {
      const reads = await readDocuments(selectedSlot, picked);
      const selectors = reads.map(read => mobileSelectorFromRead("tire", read));
      const mode = selectors.length >= 2 ? "frozen_decision_closure" : "single_observation";
      if (!signal.aborted) {
        setChoice({ slot: selectedSlot, domain: "tire", mode, selectors, reads });
        setPhase("preview"); setPreview(null); setClosureConsent(false);
      }
    });
  }

  async function buildPreview() {
    if (!choice || !status || busy) return;
    await perform(async signal => {
      // 包原始字节不驻留 JS 层：经标准本机 API 通道取回后先对 slot 指纹核对，
      // 再交 packages 投影端口本机重算（projection_binding=recomputed）。
      const response = await tireApi.offlinePackBytes(choice.slot.package_id, signal);
      const bytes = new Uint8Array(await response.arrayBuffer());
      const local = await mobileLocalPreview(bytes, status, choice.slot, {
        question, selectors: choice.selectors, projectionMode: choice.mode,
      });
      if (signal.aborted) return;
      setPreview(local.summary);
      setPrepareBody(local.body);
      originRef.current = local.origin;
      // 同一 选择+问题 在本面板会话内复用同一 intent_id，五类台账事件按意图串联。
      const intentId = intentFor(choice.slot.slot_id, choice.domain, choice.selectors.map(item => item.member_key),
        local.summary.question_sha256);
      activeIntent.current = intentId;
      await recordJournal(mobileJournalEventForPreview(intentId, local.summary));
    });
  }

  async function runPrepare(decision: "allow" | "deny") {
    if (!choice || !preview || !prepareBody || busy) return;
    const intentId = intentFor(choice.slot.slot_id, choice.domain, choice.selectors.map(item => item.member_key),
      preview.question_sha256);
    activeIntent.current = intentId;
    if (decision === "deny") {
      await recordJournal(mobileJournalEventForDecision(intentId, "deny", preview.local_preview_fingerprint));
      setNotice("已记录拒绝：本次材料不会交给 AI Provider。");
      setExportConsent(false);
      return;
    }
    if (!exportConsent) return;
    if (choice.mode === "frozen_decision_closure" && !closureConsent) return;
    const origin = originRef.current;
    if (!origin || origin.package_id !== choice.slot.package_id || origin.expected_sha256 !== choice.slot.sha256) return;
    await perform(async signal => {
      await recordJournal(mobileJournalEventForDecision(intentId, "allow", preview.local_preview_fingerprint));
      const prepareKey = crypto.randomUUID();
      const view = await bridge.prepare({ ...prepareBody, intent_id: intentId }, prepareKey);
      if (signal.aborted) return;
      if (view.question_sha256 !== preview.question_sha256 || view.selection_sha256 !== preview.selection_sha256) {
        throw new Error("服务端准备记录与本机预览指纹不一致，已停止提交。");
      }
      activePrepareKey.current = prepareKey;
      consentRef.current = {
        packId: view.pack_id, prepareId: view.id, hostReceiptId: prepareBody.host_receipt_id,
        fingerprint: view.device_context_fingerprint, question,
      };
      setPreparation(view);
      setProviderPreview((view.provider_preview as Record<string, unknown> | undefined) ?? null);
      setProviderConsent(false);
      setPhase("prepared");
      await recordJournal(mobileJournalEventForPrepareCreated(intentId, prepareKey, view));
    });
  }

  async function runSubmit(replay = false) {
    if (busy) return;
    const previous = frozenSubmission.current;
    if (!replay && (!preparation || !providerConsent || !providerPreview || !choice || !preview || !consentRef.current)) return;
    if (replay && !previous) { setError("本页没有保留原提交内容，无法重放；请回到原页面核对，或重新预览作新决定。"); return; }
    await perform(async signal => {
      let submission: FrozenSubmission;
      if (replay && previous) submission = previous;
      else {
        const consentInfo = consentRef.current!;
        const provider = typeof providerPreview!.provider === "string" ? providerPreview!.provider : null;
        const model = typeof providerPreview!.model === "string" ? providerPreview!.model : null;
        const allowPrivate = Array.isArray(providerPreview!.allowed_privacy_classes) && (providerPreview!.allowed_privacy_classes as string[]).includes("private");
        if (!provider || !model) throw new Error("模型未配置，不能提交设备历史材料。");
        const packFingerprint = (preparation!.pack as { fingerprint?: unknown }).fingerprint;
        if (typeof packFingerprint !== "string" || !/^[0-9a-f]{64}$/.test(packFingerprint)) throw new Error("准备记录缺少证据包指纹。");
        submission = {
          intentId: activeIntent.current!, prepareKey: activePrepareKey.current!, analysisKey: crypto.randomUUID(),
          packId: consentInfo.packId, prepareId: consentInfo.prepareId, hostReceiptId: consentInfo.hostReceiptId,
          deviceContextFingerprint: consentInfo.fingerprint, question: consentInfo.question,
          consent: {
            expected_pack_fingerprint: packFingerprint, expected_device_context_fingerprint: preparation!.device_context_fingerprint,
            question_sha256: preparation!.question_sha256, provider, model,
            expected_provider_policy_fingerprint: await deviceProviderPolicyFingerprint({ provider, model, allowPrivate }),
          },
        };
        frozenSubmission.current = submission;
        analysisKeyRef.current = submission.analysisKey;
      }
      // claim 先于提交写入：它是 N18 恢复「本机已提交主张」的唯一本地凭据。
      await recordJournal(mobileJournalEventForClaim(submission.intentId, submission.prepareId,
        submission.analysisKey, submission.consent.question_sha256));
      rememberDeviceAiRecovery({ intentId: submission.intentId, prepareKey: submission.prepareKey,
        analysisKey: submission.analysisKey, requestId: submission.analysisKey });
      setRecovery(parseDeviceAiRecovery(sessionStorage.getItem("tire-device-ai-recovery-v1")));
      setRecoveryResult(null);
      try {
        const acceptance = await bridge.submitStream({
          pack_id: submission.packId, question: submission.question, prepare_id: submission.prepareId,
          host_receipt_id: submission.hostReceiptId, device_context_fingerprint: submission.deviceContextFingerprint,
          provider_consent: submission.consent,
        }, submission.analysisKey);
        if (signal.aborted) return;
        setPhase("submitted");
        await recordJournal(mobileJournalEventForOutcome(submission.intentId, submission.analysisKey,
          acceptance.analysis.id, acceptance.execution.state));
        // 移动端流式消费：无 SSE 桥，按既有原生先例走事件游标轮询。
        followProgress(acceptance.analysis.id, "");
      } catch (cause) {
        await recordJournal(mobileJournalEventForFailure(submission.intentId, "submit", mobileFailureCode(cause)));
        throw cause;
      }
    });
  }

  /** N18 未知结果恢复：只读核对（lookup 优先），绝不自动重放。 */
  async function runRecovery() {
    if (!recovery || !status?.profile_id || busy) return;
    await perform(async () => {
      const result = await bridge.resolveUnknown({
        analysis_key: recovery.analysisKey, intent_id: recovery.intentId,
        owner: status!.profile_id!, generation: status!.owner_epoch, session_id: sessionId.current,
      });
      setRecoveryResult(result);
      if (result.kind === "resolved") {
        // 已受理的调用直接接上进度轮询（terminal 去重由 terminalRecorded 保证）。
        setPhase("submitted");
        followProgress(result.detail.analysis.id, "");
      }
    });
  }

  function reset() {
    poller.current?.abort();
    setStream(null); setPreparation(null); setProviderPreview(null); setProviderConsent(false);
    setExportConsent(false); setClosureConsent(false); setPreview(null); setPrepareBody(null); setChoice(null); setPicked([]);
    setSelectedSlot(null); setSearch(null); setPhase("select"); setError(""); setNotice("");
    originRef.current = null; analysisKeyRef.current = null; consentRef.current = null;
    activeIntent.current = null; activePrepareKey.current = null;
    frozenSubmission.current = null; terminalRecorded.current = null;
    rememberDeviceAiRecovery(null);
    setRecovery(null); setRecoveryResult(null);
  }

  if (typeof document === "undefined") return null;
  const budget = (providerPreview?.outbound_budget ?? null) as Record<string, unknown> | null;
  const dailyBudget = budget && typeof budget.daily_budget === "object" && budget.daily_budget !== null ? budget.daily_budget as Record<string, unknown> : null;
  const budgetBlocked = budget?.blocked === true || dailyBudget?.blocked === true;
  const draft = stream ? visibleAIDrafts(stream, false) : null;
  return createPortal(<dialog ref={dialog} className="mobile-settings-dialog mobile-device-ai-dialog" aria-labelledby="mobile-device-ai-title"
    onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header><div><span className="eyebrow">DEVICE HISTORY → AI</span><h2 id="mobile-device-ai-title">设备 AI 分析</h2><p>本机预览 · 一次决定 · 服务端复核 · 轮询结果</p></div><button type="button" onClick={onClose}>关闭</button></header>
    <div className="mobile-settings-content mobile-device-ai-content">
      <p className="review-boundary">分析对象是本设备保存的离线历史观察（轮胎 / 车辆 / 召回公告 / 公告检索四域）。预览指纹在本机重算；确认后才创建服务端准备记录，第二次确认后才交给 AI Provider。</p>
      {error ? <p className="inline-error" role="alert">{error}</p> : null}
      {notice ? <p className="review-boundary" role="status">{notice}</p> : null}

      {phase === "select" && !stream ? <section aria-label="选择本机离线包">
        <h3>第 1 步 · 选择本机离线包与历史观察</h3>
        {!platform.offline ? <p className="inline-error">此宿主没有设备离线存储能力。</p>
          : !slots.length ? <p>本机还没有可用的离线资料包。请先在设备离线资料库保存，再回到这里。</p>
          : <div className="offline-pack-list">{slots.map(slot => <button type="button" className={`offline-pack-item${selectedSlot?.slot_id === slot.slot_id ? " selected" : ""}`} key={slot.slot_id} disabled={busy || slot.locked || slot.previous_owner} onClick={() => void selectSlot(slot)}><strong>{slot.title}</strong><span>本机版本 #{slot.generation} · 包 SHA-256 {slot.sha256.slice(0, 12)}…</span>{slot.previous_owner ? <span className="tag warning">旧归属 · 不能用于设备 AI</span> : null}</button>)}</div>}
        {selectedSlot && !selectedSlot.locked && !selectedSlot.previous_owner ? <div className="compare-toolbar" role="group" aria-label="选择历史观察域">
          {MOBILE_DEVICE_AI_DOMAINS.map(item => <button type="button" key={item} className={domain === item ? "primary-button" : "secondary-button"} disabled={busy} onClick={() => void selectDomain(item)}>{deviceAiDomainLabels[item]}</button>)}
        </div> : null}
        {search ? (search.items.length ? <div className="offline-search"><p role="status">此包含 {search.total} 条{deviceAiDomainLabel(domain)}域历史记录。</p>
          {domain === "tire" ? <p className="review-boundary">单条观察：直接点击记录。冻结决定闭包：勾选 2..6 条后用下方入口预览。</p> : <p className="review-boundary">{deviceAiDomainLabel(domain)}域按「{deviceAiProjectionModeLabel(DEVICE_AI_PREPARE_DOMAIN_MODES[domain])}」模式整条投影，点击记录即选。</p>}
          {search.items.map(document => <div className="offline-search-row" key={document.id}>
            <button type="button" className={`offline-search-item${picked.includes(document.id) ? " selected" : ""}`} disabled={busy} onClick={() => void selectDocument(document.id)}><strong>{document.title}</strong><span>来源证据 · {document.observed_at ? `观察 ${stamp(document.observed_at)}` : "时间未记录"}</span></button>
            {domain === "tire" ? <label className="review-checkbox"><input type="checkbox" disabled={busy || (!picked.includes(document.id) && picked.length >= 6)}
              checked={picked.includes(document.id)} onChange={event => setPicked(current => event.target.checked ? [...current, document.id] : current.filter(id => id !== document.id))} />加入冻结决定闭包</label> : null}
          </div>)}
          {domain === "tire" && picked.length ? <div className="compare-toolbar">
            <button type="button" className="secondary-button" disabled={busy || picked.length > 6} onClick={() => void previewPicked()}>
              {picked.length >= 2 ? `以冻结决定闭包预览所选 ${picked.length} 条` : "预览所选 1 条（单条观察）"}
            </button>
            <span className="review-boundary">{picked.length > 6 ? "一次请求最多选择 6 条成员（服务端封闭容量）。" : `已选 ${picked.length}/6 条。`}</span>
          </div> : null}
        </div> : <p>此包没有{deviceAiDomainLabel(domain)}域历史记录。</p>) : null}
      </section> : null}

      {choice && phase === "preview" && !stream ? <section aria-label="本机预览">
        <h3>第 2 步 · 本机预览即将外发的材料指纹</h3>
        <p><strong>{deviceAiDomainLabel(choice.domain)}域 · {deviceAiProjectionModeLabel(choice.mode)}</strong> · {choice.reads.length > 1 ? `已选 ${choice.reads.length} 条成员` : choice.reads[0].document.title} · 本机版本 #{choice.slot.generation} · 包 {choice.slot.byte_count.toLocaleString()} 字节</p>
        <label htmlFor="mobile-device-ai-question">本次问题（2..2000 字符，服务端会与预览指纹绑定）</label>
        <textarea id="mobile-device-ai-question" rows={2} maxLength={2000} value={question} disabled={busy || !!preview} onChange={event => { setQuestion(event.target.value); setPreview(null); setPrepareBody(null); setClosureConsent(false); }} />
        {!preview ? <div className="compare-toolbar">
          <button type="button" className="secondary-button" disabled={busy || question.trim().length < 2} onClick={() => void buildPreview()}>在本机重算指纹（含包字节核对）</button>
          <span className="review-boundary">包原始字节经本机 API 通道取回并核对 slot 指纹后即用即弃，不在 JS 层保存。</span>
        </div> : <div className="device-ai-preview">
          <dl>
            <div><dt>question_sha256</dt><dd className="hash-value">{preview.question_sha256}</dd></div>
            <div><dt>selection_sha256</dt><dd className="hash-value">{preview.selection_sha256}</dd></div>
            <div><dt>expected_projection_sha256</dt><dd className="hash-value">{preview.projection_sha256}（{preview.projection_byte_count.toLocaleString()} B 规范字节）</dd></div>
            <div><dt>device_context_fingerprint（本机重算）</dt><dd className="hash-value">{preview.device_context_fingerprint}</dd></div>
            <div><dt>local_preview_fingerprint</dt><dd className="hash-value">{preview.local_preview_fingerprint}</dd></div>
            <div><dt>package_sha256 / 字节</dt><dd className="hash-value">{preview.package_sha256} / {preview.package_byte_count.toLocaleString()} B</dd></div>
            {choice.mode === "frozen_decision_closure" ? <div><dt>resolved 闭包（approved_closure）</dt><dd className="hash-value">{preview.resolved_closure_member_keys.map(key => `${key.slice(0, 12)}…`).join(" ")}</dd></div> : null}
          </dl>
          <p className="review-boundary">SDK 预览的 projection_binding = {preview.projection_binding}：投影摘要由本机投影端口重算（对封存向量 20/20 对拍）；服务端 prepare 仍以其权威重算复核，不一致即闭环拒绝。</p>
          {choice.mode === "frozen_decision_closure" ? <label className="review-checkbox"><input type="checkbox" checked={closureConsent} disabled={busy} onChange={event => setClosureConsent(event.target.checked)} />我确认按上方展示的 {preview.resolved_closure_member_keys.length} 条成员组成冻结决定闭包（approved_closure 精确相等清单）提交。</label> : null}
          <label className="review-checkbox"><input type="checkbox" checked={exportConsent} disabled={busy} onChange={event => setExportConsent(event.target.checked)} />我允许将上述材料与问题交由 AI Provider 处理；这是一次性决定，不会自动重复。</label>
          <div className="compare-toolbar">
            <button type="button" className="mobile-primary" disabled={busy || !exportConsent || (choice.mode === "frozen_decision_closure" && !closureConsent)} onClick={() => void runPrepare("allow")}>{busy ? "正在创建准备记录…" : "确认并创建服务端准备记录"}</button>
            <button type="button" className="mobile-secondary" disabled={busy} onClick={() => void runPrepare("deny")}>拒绝本次外发</button>
          </div>
        </div>}
      </section> : null}

      {phase === "prepared" && preparation && !stream ? <section aria-label="服务端准备与二次确认">
        <h3>第 3 步 · 服务端准备记录与二次确认</h3>
        <dl>
          <div><dt>prepare_id</dt><dd className="hash-value">{preparation.id}</dd></div>
          <div><dt>投影 / 上下文指纹</dt><dd className="hash-value">{preparation.projection_sha256}<br />{preparation.device_context_fingerprint}</dd></div>
          <div><dt>有效期至</dt><dd>{stamp(preparation.expires_at)}（replayed: {String(preparation.replayed)}）</dd></div>
        </dl>
        {providerPreview ? <section className="ai-status" aria-label="Provider 预检"><strong>Provider 预检（prepare 只读，不调用模型）</strong>
          <p>{String(providerPreview.provider)} · {String(providerPreview.state)} · 模型 {typeof providerPreview.model === "string" ? providerPreview.model : "未配置"}</p>
          {budget ? <p>外发预算：真实值 {String(budget.evidence_only_request_bytes)} B / 上界 {String(budget.upper_bound_request_bytes)} B{budget.blocked === true ? " · 上界超限，已阻止" : ""}</p> : null}
        </section> : null}
        <label className="review-checkbox"><input type="checkbox" checked={providerConsent} disabled={busy} onChange={event => setProviderConsent(event.target.checked)} />我再次确认：将把该材料发送到已显示的模型处理（allow_external_processing 字面为 true）。</label>
        <div className="compare-toolbar">
          <button type="button" className="mobile-primary" disabled={busy || !providerConsent || budgetBlocked} onClick={() => void runSubmit(false)}>{busy ? "正在提交…" : "确认提交并接收结果"}</button>
          <button type="button" className="mobile-secondary" disabled={busy} onClick={reset}>放弃本次准备</button>
        </div>
      </section> : null}

      {/* 与 Web 对位的未知结果恢复区：一旦有恢复指针即常驻，四分支文案对齐 Web。 */}
      {recovery && (!stream || recoveryResult !== null) ? <section className="ai-recovery" aria-label="未知结果恢复">
        <h3>未知结果恢复</h3>
        <p>{recoveryResult ? deviceAiOutcomeLabel(recoveryResult.kind) : "检测到本机有未确认结果的提交。恢复只做只读核对，不会自动重新提交模型。"}</p>
        <div className="compare-toolbar">
          <button type="button" className="mobile-secondary" disabled={busy} onClick={() => void runRecovery()}>只读核对上次提交</button>
          {recoveryResult?.kind === "not_submitted" ? <button type="button" className="mobile-secondary" disabled={busy} onClick={reset}>重新决定（新的一次决定）</button> : null}
          {recoveryResult?.kind === "unknown_local_claim" && frozenSubmission.current ? <button type="button" className="mobile-secondary" disabled={busy} onClick={() => void runSubmit(true)}>用同一标识重放核对（已受理的调用不会重复执行）</button> : null}
          {recoveryResult?.kind === "unknown_local_claim" && !frozenSubmission.current ? <span className="review-boundary">本页未保留原问题原文（不落盘），不能重放；请回原页面核对或重新预览作新决定。</span> : null}
          {recoveryResult?.kind === "cross_session_replay_blocked" ? <span className="review-boundary">跨会话重放已被台账会话栅栏明确拒绝，仅可只读查看。</span> : null}
        </div>
      </section> : null}

      {stream ? <section className="ai-stream-progress" aria-label="设备 AI 分析进度">
        <div className="ai-stream-heading"><h3>{aiStreamStateLabels[stream.execution.state] ?? stream.execution.state}</h3>
          <button type="button" className="secondary-button" disabled={pollState === "finished"} onClick={() => analysisKeyRef.current && followProgress(stream.analysis.id, "")}>重新读取进度</button></div>
        <p className="ai-stream-question">本次问题：{stream.analysis.question}</p>
        <p className="ai-stream-connection" role="status" aria-live="polite">{pollState === "polling" ? "正在定时读取分析进度" : pollState === "finished" ? "已读取本次调用终态" : "进度连接中断，最新状态未知"} · 最后读取 {new Date(stream.server_time).toLocaleTimeString("zh-CN")}</p>
        <p className="review-boundary">移动端通过本机 API 通道轮询同一调用的已保存进度；断线或关闭页面不会重复调用模型。</p>
        {stream.analysis.error_code ? <p className="review-warning" role="alert">{isProviderFailure(stream.analysis.error_code) ? "Provider 处理失败" : "来源/传输失败"}：{stream.analysis.error_code} 生成中内容已作废。</p> : null}
        {!stream.execution.terminal && draft ? <section className="ai-stream-drafts" aria-label="未完成校验的分析草稿">
          <h4>生成中草稿 · 整份结果尚未完成引用校验</h4>
          {draft.claims.map(({ index, claim }) => <article className={`ai-claim ${claim.type}`} key={index}><strong>{claim.type === "fact" ? "证据字段草稿" : "模型推断草稿 · 需人工核对"}</strong><p>{claim.text}</p></article>)}
          {!draft.claims.length ? <p>尚未收到可展示的完整片段。</p> : null}
        </section> : null}
        {stream.execution.terminal && stream.analysis.answer ? <section className="ai-result" aria-label="设备 AI 分析结果">
          <h3>{stream.analysis.state === "completed" ? "已完成引用校验" : "本次分析未完成"}</h3>
          <small>{stream.analysis.model} · {stamp(stream.analysis.created_at)} · {stream.analysis.usage ? `${stream.analysis.usage.total_tokens} tokens` : `用量未确认，保留 ${stream.analysis.reserved_tokens} tokens 预留`}</small>
          {stream.analysis.answer.claims.map((claim, index) => <article className={`ai-claim ${claim.type}`} key={index}><strong>{claim.type === "fact" ? "证据字段" : "模型推断 · 需人工核对"}</strong><p>{claim.text}</p></article>)}
          {stream.analysis.answer.uncertainty ? <div className="ai-claim inference"><strong>不确定性说明 · 需核对</strong><p>{stream.analysis.answer.uncertainty}</p></div> : null}
          <p className="review-boundary">{stream.analysis.answer.notice}</p>
          <div className="compare-toolbar"><button type="button" className="mobile-secondary" onClick={reset}>重新预览，开始新的分析</button></div>
        </section> : null}
      </section> : null}

      <section className="ai-history" aria-label="设备 AI 台账">
        <div className="panel-title"><h3>设备 AI 台账（本机 Keystore 加密 · 只读核对）</h3><button type="button" className="mobile-secondary" disabled={busy} onClick={() => void refreshJournal()}>刷新台账</button></div>
        {journalError ? <p className="inline-error" role="alert">台账不可用：{journalError}</p> : null}
        {journal ? (journal.ok ? <p role="status">台账完整性校验通过（{journal.length} 条记录）。会话 {sessionId.current.slice(0, 8)} · 归属 {status?.profile_id?.slice(0, 8) ?? "…"} · 世代 {status?.owner_epoch}</p>
          : <p className="inline-error" role="alert">台账未通过完整性校验：{JSON.stringify(journal.violations[0] ?? {})}</p>)
          : <p>正在读取本机台账…</p>}
        {journal?.entries?.length ? <ul className="device-ai-journal">{[...journal.entries].reverse().map((entry, index) => {
          const record = entry as { sequence?: number; wall_clock?: string; session_id?: string; event?: { type?: string } };
          return <li key={index}><span>#{record.sequence} {deviceAiEventLabels[record.event?.type ?? ""] ?? record.event?.type}</span><small>{stamp(record.wall_clock)} · 会话 {String(record.session_id ?? "").slice(0, 8)}</small></li>;
        })}</ul> : null}
        <p className="review-boundary">各环节（预览 / 决定 / 准备 / 提交 / 结果 / 失败）事件经 deviceAiJournalAppend 写入本机加密台账（五栅栏校验）；未知结果恢复按 N18 只读核对。</p>
      </section>
    </div>
  </dialog>, document.body);
}
