// 桌面端设备 AI 面板（第50轮 Windows 前端接线 + journal 事件写入编排与未知
// 结果恢复）。与 Web 面板 (apps/web/components/device-ai-panel.tsx) 同一四域 +
// 决定/复核流程，但全部外发动作走 Tauri IPC 的六个已注册命令：
//   device_ai_prepare / device_ai_submit_stream / device_ai_lookup_attempt /
//   device_ai_read_journal / device_ai_journal_append /
//   device_ai_resolve_unknown（lib.rs，HTTP 拒绝以 rejected 信封透传）。
//
// journal 编排（对齐 Web 面板经 SDK 的写入时机）：预览展示 → preview_shown；
// 决定 → decision_made；prepare 成功 → prepare_created；提交前先落
// claim_submitted（断线/崩溃后本机留有 claim，恢复才能 same-key 核对）；受理
// /流式终态 → outcome_observed；任何失败 → failure_observed（provider/source
// 阶段分离）。恢复：面板打开时从台账推导未决 claim 并调
// device_ai_resolve_unknown（N18 lookup-first，四分支 + 完整性失败，绝不自动
// 重提交）。
//
// 本机预览的架构决策：
//  - 投影复刻端口（packages/api-client/src/device-ai-projection.ts，20/20
//    向量对拍）在前端直接复用——import 路径与 Web 面板一致
//    （../../../packages/api-client/src/device-ai-host），无需 vite alias。
//  - 桌面离线库的原包字节没有导出 IPC（offline_* 命令只有 list/search/
//    read/remove…）。预览字节改由既有 tireApi.offlinePackBytes 从本机 API
//    下载，并先逐一校验 sha256/字节与本机槽位一致后才进入本机重算；
//    校验失败即停止（fail-closed），绝不以未钉住的内容计算指纹。
//  - 服务端 prepare 仍以其权威投影复核 expected_projection_sha256，本机
//    预览不是等值性声明（B01）。
//
// 流式结果沿用桌面端既有通道：AIStreamProgress 在非 web 平台按游标定时
// 读取（tireApi.aiStreamEvents，经 api_request IPC 的缓冲传输）；SSE 仅
// Web 使用，桌面端不做 SSE 转发。
"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { ApiError, tireApi } from "@tire/api-client";
import type { AIStreamAcceptance, AIStreamDetail, OfflineReadResult, OfflineSearchResult, OfflineSlot } from "@tire/domain-types";
import { WorkbenchPlatformContext, type WorkbenchPlatform } from "../../web/components/workbench-platform";
import { AIStreamProgress } from "../../web/components/ai-stream-progress";
import {
  deviceAiDomainLabel, deviceAiDomainLabels, deviceAiEventLabels, deviceAiFailureLabels, deviceAiHostErrorMessage,
  deviceAiOutcomeLabel, deviceAiProjectionModeLabel, deviceProviderPolicyFingerprint,
} from "../../web/components/device-ai-values";
import {
  buildDeviceAiPrepareBody, computeLocalPreview, DEVICE_AI_PREPARE_DOMAIN_MODES,
  type DeviceAiJournalEntry, type DeviceAiJournalEvent, type DeviceAiLocalPreviewSummary, type DeviceAiOriginBindingWire,
  type DeviceAiPrepareResultView, type DeviceAiPrepareSelectorWire, type DeviceAiProviderConsentBody,
  type DeviceAiUnknownOutcomeResolution,
} from "../../../packages/api-client/src/device-ai-host";
import type { DeviceAiProjectionMode } from "../../../packages/api-client/src/device-ai-projection";
import { deviceAiInvoke, deviceAiRawInvoke, deriveDeviceAiPendingClaim, type DeviceAiJournalView, type DeviceAiPendingClaim } from "./device-ai-ipc";

const stamp = (value?: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "未记录";
const isProviderFailure = (code?: string | null) => !!code && (code.startsWith("ai_provider_") || code === "ai_refused" || code === "ai_response_incomplete");
function panelErrorText(cause: unknown): string {
  if (cause instanceof ApiError) return `${cause.message}${cause.code ? `（${cause.code}）` : ""}`;
  return deviceAiHostErrorMessage(cause);
}
/** failure_observed 的 code 透传：闭合到命令层校验允许的形状（1..=100 码点，无控制字符）。 */
function failureCode(cause: unknown): string {
  const raw = cause instanceof ApiError ? (cause.code ?? `http_${cause.status}`)
    : cause instanceof Error ? cause.message : "unknown";
  const text = raw.replace(/[\r\n\0]+/g, " ").trim();
  return text ? Array.from(text).slice(0, 100).join("") : "unknown";
}

type Phase = "select" | "preview" | "prepared" | "submitted";
type PanelDomain = keyof typeof deviceAiDomainLabels;
const PANEL_DOMAINS = Object.keys(deviceAiDomainLabels) as PanelDomain[];

interface DomainChoice {
  slot: OfflineSlot;
  domain: PanelDomain;
  mode: DeviceAiProjectionMode;
  selectors: DeviceAiPrepareSelectorWire[];
  reads: OfflineReadResult[];
}
interface FrozenSubmission {
  intentId: string; prepareKey: string; analysisKey: string; packId: string; prepareId: string; hostReceiptId: string;
  deviceContextFingerprint: string; question: string; consent: DeviceAiProviderConsentBody;
}

async function sha256Hex(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

/** 预览字节来源：本机 API 下载 + 与本机槽位 sha256/字节逐一钉死。 */
async function fetchPinnedPackBytes(slot: OfflineSlot, signal?: AbortSignal): Promise<{ bytes: Uint8Array; schema: "offline-pack@1" | "offline-pack@2" }> {
  const response = await tireApi.offlinePackBytes(slot.package_id, signal);
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength !== slot.byte_count) throw new Error("下载的离线包字节数与本机槽位记录不一致，已停止本机预览。");
  if (await sha256Hex(bytes) !== slot.sha256) throw new Error("下载的离线包摘要与本机槽位记录不一致，已停止本机预览。");
  const envelope = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as { schema?: unknown };
  if (envelope.schema !== "offline-pack@1" && envelope.schema !== "offline-pack@2") throw new Error("本机包结构不受支持。");
  return { bytes, schema: envelope.schema };
}

export function DesktopDeviceAiEntry({ platform, online, className = "text-button" }: {
  platform: WorkbenchPlatform; online: boolean; className?: string;
}) {
  const [open, setOpen] = useState(false);
  return <><button type="button" className={className} disabled={!online} onClick={() => setOpen(true)}>设备 AI 分析</button>
    {open && online && isTauri() ? <DesktopDeviceAiDialog platform={platform} onClose={() => setOpen(false)} /> : null}</>;
}

function DesktopDeviceAiDialog({ platform, onClose }: { platform: WorkbenchPlatform; onClose: () => void }) {
  const [portalTheme] = useState(() => document.querySelector<HTMLElement>(".app-shell")?.dataset.theme || "light");
  const dialog = useRef<HTMLDialogElement>(null);
  const operation = useRef<AbortController | null>(null);
  const frozenSubmission = useRef<FrozenSubmission | null>(null);
  const [slots, setSlots] = useState<OfflineSlot[]>([]);
  const [origin, setOrigin] = useState<{ profileId: string; ownerEpoch: number } | null>(null);
  const [selectedSlot, setSelectedSlot] = useState<OfflineSlot | null>(null);
  const [domain, setDomain] = useState<PanelDomain>("tire");
  const [search, setSearch] = useState<OfflineSearchResult | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [choice, setChoice] = useState<DomainChoice | null>(null);
  const [phase, setPhase] = useState<Phase>("select");
  const [question, setQuestion] = useState("解读这条设备历史轮胎观察中的字段候选与身份合同，说明证据限制。");
  const [preview, setPreview] = useState<DeviceAiLocalPreviewSummary | null>(null);
  const [exportConsent, setExportConsent] = useState(false);
  const [closureConsent, setClosureConsent] = useState(false);
  const [preparation, setPreparation] = useState<DeviceAiPrepareResultView | null>(null);
  const [providerPreview, setProviderPreview] = useState<Record<string, unknown> | null>(null);
  const [providerConsent, setProviderConsent] = useState(false);
  const [stream, setStream] = useState<AIStreamDetail | null>(null);
  const [streamEpoch, setStreamEpoch] = useState(0);
  const [journal, setJournal] = useState<DeviceAiJournalView | null>(null);
  const [journalError, setJournalError] = useState("");
  const [recovery, setRecovery] = useState<DeviceAiPendingClaim | null>(null);
  const [recoveryResult, setRecoveryResult] = useState<DeviceAiUnknownOutcomeResolution | null>(null);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const originRef = useRef<DeviceAiOriginBindingWire | null>(null);
  const activeIntent = useRef<string | null>(null);
  const activePrepareKey = useRef<string | null>(null);
  const activeAnalysisKey = useRef<string | null>(null);
  const terminalRecorded = useRef<string | null>(null);
  const intentCache = useRef(new Map<string, string>());
  // refreshJournal 派生恢复指针后会立刻自动核对一次；runRecovery 读取的是 ref
  // 镜像，避免 setState 闭包里的旧值。
  const recoveryRef = useRef<DeviceAiPendingClaim | null>(null);
  const recoveryAutoRan = useRef(false);
  const dismissedRecovery = useRef<string | null>(null);

  useEffect(() => {
    const node = dialog.current, focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    void refreshJournal();
    void loadSlots();
    return () => { operation.current?.abort(); node?.close(); if (focus?.isConnected && !focus.closest("dialog:not([open])")) focus.focus({ preventScroll: true }); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function perform(work: (signal: AbortSignal) => Promise<void>) {
    if (operation.current) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError("");
    try { await work(controller.signal); }
    catch (cause) { if (!controller.signal.aborted) setError(panelErrorText(cause)); }
    finally { operation.current = null; if (!controller.signal.aborted) setBusy(false); }
  }

  async function loadSlots() {
    if (!platform.offline) { setError("此宿主没有设备离线存储能力。"); return; }
    try {
      const list = await platform.offline.list();
      setSlots(list.items);
      setOrigin({ profileId: list.profile_id, ownerEpoch: list.owner_epoch });
    } catch (cause) { setError(panelErrorText(cause)); }
  }

  function setPendingRecovery(next: DeviceAiPendingClaim | null) {
    recoveryRef.current = next;
    setRecovery(next);
  }

  async function refreshJournal(): Promise<void> {
    let pending: DeviceAiPendingClaim | null = null;
    try {
      const view = await deviceAiRawInvoke<DeviceAiJournalView>(invoke, "device_ai_read_journal");
      setJournal(view);
      pending = deriveDeviceAiPendingClaim(view.entries);
      if (pending?.analysisKey === dismissedRecovery.current) pending = null;
    } catch (cause) {
      setJournalError(panelErrorText(cause));
      return;
    }
    setPendingRecovery(pending);
    // 面板打开时对未决 claim 自动做一次只读核对（N18 lookup-first，安全）。
    if (pending && !recoveryAutoRan.current) { recoveryAutoRan.current = true; void runRecovery(false); }
  }

  /** journal 事件写入（device_ai_journal_append，封闭校验在命令层）；失败不阻断主流程。 */
  async function recordJournal(event: DeviceAiJournalEvent): Promise<void> {
    try {
      await deviceAiRawInvoke<unknown>(invoke, "device_ai_journal_append", { event });
      await refreshJournal();
    } catch (cause) { setJournalError(panelErrorText(cause)); }
  }

  /** 同一 预览对象（槽位+域+成员闭包+问题摘要）复用同一 intent_id，与 Web intentIdFor 同语义。 */
  function intentIdFor(target: DomainChoice, questionSha: string): string {
    const key = `${target.slot.slot_id}:${target.domain}:${target.selectors.map(item => item.member_key).sort().join(",")}:${questionSha}`;
    let existing = intentCache.current.get(key);
    if (!existing) { existing = crypto.randomUUID(); intentCache.current.set(key, existing); }
    return existing;
  }

  function showStream(detail: AIStreamDetail) {
    terminalRecorded.current = null;
    setStream(detail); setStreamEpoch(value => value + 1); setPhase("submitted");
  }

  /** 流式终态落账：失败按 provider/source 阶段分离，否则记录最终 outcome。 */
  async function recordTerminal(detail: AIStreamDetail, intentId: string | null, analysisKey: string): Promise<void> {
    if (terminalRecorded.current === detail.analysis.id) return;
    terminalRecorded.current = detail.analysis.id;
    if (detail.analysis.error_code) {
      await recordJournal({ type: "failure_observed", intent_id: intentId,
        stage: isProviderFailure(detail.analysis.error_code) ? "provider" : "source",
        code: detail.analysis.error_code });
    } else {
      await recordJournal({ type: "outcome_observed", intent_id: intentId ?? "", analysis_key: analysisKey,
        request_id: detail.analysis.id, state: detail.execution.state });
    }
  }

  /** N18 未知结果只读核对：device_ai_resolve_unknown lookup-first，绝不自动重提交。 */
  async function runRecovery(manual: boolean) {
    const pointer = recoveryRef.current;
    if (!pointer || recoveryBusy) return;
    setRecoveryBusy(true); setRecoveryResult(null);
    try {
      const resolution = await deviceAiInvoke<DeviceAiUnknownOutcomeResolution>(invoke, "device_ai_resolve_unknown", {
        analysisKey: pointer.analysisKey, intentId: pointer.intentId,
      });
      setRecoveryResult(resolution);
      if (resolution.kind === "resolved") showStream(resolution.detail);
    } catch (cause) {
      // 自动核对失败保持静默（章节文案仍引导手动核对）；手动核对才报错。
      if (manual) setError(panelErrorText(cause));
    } finally { setRecoveryBusy(false); }
  }

  async function runSearch(slot: OfflineSlot, kind: PanelDomain, signal: AbortSignal) {
    const value = await platform.offline!.search({ slot_id: slot.slot_id, expected_generation: slot.generation, query: "", kind, offset: 0, limit: 20 });
    if (!signal.aborted) setSearch(value);
  }

  function selectSlot(slot: OfflineSlot) {
    setChoice(null); setPreview(null); setSearch(null); setPicked([]); setPhase("select"); setError(""); setNotice("");
    setSelectedSlot(slot);
    if (!platform.offline || slot.locked || slot.previous_owner) return;
    void perform(signal => runSearch(slot, domain, signal));
  }

  function selectDomain(next: PanelDomain) {
    if (!selectedSlot || busy) return;
    setDomain(next); setChoice(null); setPreview(null); setPicked([]); setPhase("select"); setError(""); setNotice("");
    if (!platform.offline || selectedSlot.locked || selectedSlot.previous_owner) return;
    void perform(signal => runSearch(selectedSlot, next, signal));
  }

  /** 记录携带域保留 document.record_index；tire/vehicle 整观察域恒为 null（服务端 model_validator 同语义）。 */
  function selectorFromRead(target: PanelDomain, read: OfflineReadResult): DeviceAiPrepareSelectorWire {
    const member = read.member;
    if (!member || member.reference.kind !== target) {
      throw new Error(`所选记录不是${deviceAiDomainLabel(target)}域历史观察，本阶段不支持设备 AI 分析。`);
    }
    const recordIndex = target === "tire" || target === "vehicle" ? null : read.document.record_index;
    return {
      kind: target, member_key: member.key, document_id: read.document.id, record_index: recordIndex,
      reference: member.reference as unknown as DeviceAiPrepareSelectorWire["reference"],
    } as DeviceAiPrepareSelectorWire;
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
      const selectors = [selectorFromRead(domain, read)];
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
      const selectors = reads.map(read => selectorFromRead("tire", read));
      const mode: DeviceAiProjectionMode = selectors.length >= 2 ? "frozen_decision_closure" : "single_observation";
      if (!signal.aborted) {
        setChoice({ slot: selectedSlot, domain: "tire", mode, selectors, reads });
        setPhase("preview"); setPreview(null); setClosureConsent(false);
      }
    });
  }

  async function buildPreview() {
    if (!choice || !origin || busy) return;
    await perform(async signal => {
      const { bytes, schema } = await fetchPinnedPackBytes(choice.slot, signal);
      const slot = choice.slot;
      const binding: DeviceAiOriginBindingWire = {
        expected_profile_id: origin.profileId, expected_owner_epoch: origin.ownerEpoch,
        slot_id: slot.slot_id, expected_generation: slot.generation, package_id: slot.package_id,
        expected_sha256: slot.sha256, expected_byte_count: slot.byte_count, owner_scope_id: slot.owner_scope_id,
        package_schema: schema,
      };
      const local = await computeLocalPreview(bytes, {
        question, selectors: choice.selectors, origin: binding, projectionMode: choice.mode,
        approvedClosure: choice.mode === "frozen_decision_closure" ? choice.selectors : null,
      });
      if (signal.aborted) return;
      setPreview(local);
      originRef.current = binding;
      await recordJournal({ type: "preview_shown", intent_id: intentIdFor(choice, local.question_sha256),
        local_preview_fingerprint: local.local_preview_fingerprint, question_sha256: local.question_sha256,
        package_sha256: local.package_sha256 });
    });
  }

  async function runPrepare(decision: "allow" | "deny") {
    if (!choice || !preview || busy) return;
    const intentId = intentIdFor(choice, preview.question_sha256);
    if (decision === "deny") {
      await recordJournal({ type: "decision_made", intent_id: intentId, decision: "deny",
        local_preview_fingerprint: preview.local_preview_fingerprint });
      setNotice("已记录拒绝：本次材料不会交给 AI Provider。");
      setExportConsent(false);
      return;
    }
    if (!exportConsent) return;
    if (choice.mode === "frozen_decision_closure" && !closureConsent) return;
    const binding = originRef.current;
    if (!binding || binding.package_id !== choice.slot.package_id || binding.expected_sha256 !== choice.slot.sha256) return;
    await perform(async signal => {
      await recordJournal({ type: "decision_made", intent_id: intentId, decision: "allow",
        local_preview_fingerprint: preview.local_preview_fingerprint });
      const prepareKey = crypto.randomUUID(), hostReceiptId = crypto.randomUUID();
      const body = buildDeviceAiPrepareBody({
        origin: binding, preview, selectors: choice.selectors,
        approvedClosure: choice.mode === "frozen_decision_closure" ? choice.selectors : null,
        hostReceiptId, intentId,
      });
      const view = await deviceAiInvoke<DeviceAiPrepareResultView>(invoke, "device_ai_prepare", { body, key: prepareKey });
      if (signal.aborted) return;
      if (view.question_sha256 !== preview.question_sha256 || view.selection_sha256 !== preview.selection_sha256) {
        throw new Error("服务端准备记录与本机预览指纹不一致，已停止提交。");
      }
      activeIntent.current = intentId;
      activePrepareKey.current = prepareKey;
      activeAnalysisKey.current = null;
      frozenSubmission.current = null;
      setPreparation(view);
      setProviderPreview((view.provider_preview as Record<string, unknown> | undefined) ?? null);
      setProviderConsent(false);
      setPhase("prepared");
      await recordJournal({ type: "prepare_created", intent_id: intentId, prepare_id: view.id,
        idempotency_key: prepareKey, projection_sha256: view.projection_sha256,
        device_context_fingerprint: view.device_context_fingerprint });
    });
  }

  async function runSubmit(replay = false) {
    if (busy) return;
    const previous = frozenSubmission.current;
    if (!replay && (!preparation || !providerConsent || !providerPreview || !choice || !preview)) return;
    if (replay && !previous) { setError("本窗口没有保留原提交内容，无法重放核对；请重新预览作新决定。"); return; }
    await perform(async signal => {
      let submission: FrozenSubmission;
      if (replay && previous) submission = previous;
      else {
        const view = preparation!;
        const model = typeof providerPreview!.model === "string" ? providerPreview!.model : null;
        const allowPrivate = Array.isArray(providerPreview!.allowed_privacy_classes) && (providerPreview!.allowed_privacy_classes as string[]).includes("private");
        if (!model) throw new Error("模型未配置，不能提交设备历史材料。");
        const packFingerprint = (view.pack as { fingerprint?: unknown }).fingerprint;
        if (typeof packFingerprint !== "string" || !/^[0-9a-f]{64}$/.test(packFingerprint)) throw new Error("准备记录缺少证据包指纹。");
        submission = {
          intentId: activeIntent.current!, prepareKey: activePrepareKey.current ?? crypto.randomUUID(), analysisKey: crypto.randomUUID(),
          packId: view.pack_id, prepareId: view.id, hostReceiptId: view.host_receipt_id,
          deviceContextFingerprint: view.device_context_fingerprint, question,
          consent: {
            expected_pack_fingerprint: packFingerprint, expected_device_context_fingerprint: view.device_context_fingerprint,
            question_sha256: view.question_sha256, provider: "openai_responses", model,
            expected_provider_policy_fingerprint: await deviceProviderPolicyFingerprint({ model, allowPrivate }),
          },
        };
        frozenSubmission.current = submission;
        activeAnalysisKey.current = submission.analysisKey;
      }
      // 先落台账再提交：断线/崩溃后本机留有 claim_submitted，恢复才能 same-key 核对。
      await recordJournal({ type: "claim_submitted", intent_id: submission.intentId, prepare_id: submission.prepareId,
        analysis_key: submission.analysisKey, question_sha256: submission.consent.question_sha256 });
      setRecoveryResult(null);
      try {
        const acceptance = await deviceAiInvoke<AIStreamAcceptance>(invoke, "device_ai_submit_stream", {
          key: submission.analysisKey,
          body: {
            pack_id: submission.packId, question: submission.question, prepare_id: submission.prepareId,
            host_receipt_id: submission.hostReceiptId, device_context_fingerprint: submission.deviceContextFingerprint,
            provider_consent: submission.consent,
          },
        });
        if (signal.aborted) return;
        terminalRecorded.current = null;
        setStream(acceptance); setStreamEpoch(value => value + 1); setPhase("submitted");
        await recordJournal({ type: "outcome_observed", intent_id: submission.intentId, analysis_key: submission.analysisKey,
          request_id: acceptance.analysis.id, state: acceptance.execution.state });
        if (acceptance.execution.terminal) await recordTerminal(acceptance, submission.intentId, submission.analysisKey);
      } catch (cause) {
        await recordJournal({ type: "failure_observed", intent_id: submission.intentId, stage: "submit", code: failureCode(cause) });
        // 404 与传输层失败（无确定服务端答复）都保持结果未知：仅同键重放可核对。
        if (!(cause instanceof ApiError) || cause.status === 404) {
          setNotice("提交结果尚未确认：服务端未找到该标识的受理记录或连接中断。只能用同一标识重放核对，不会重复执行已受理的调用。");
        }
        throw cause;
      }
    });
  }

  /** 未知结果只读核对（N18）：lookup 永不重新提交。 */
  async function runLookup() {
    const submission = frozenSubmission.current;
    if (!submission || busy) return;
    await perform(async signal => {
      const detail = await deviceAiInvoke<AIStreamDetail>(invoke, "device_ai_lookup_attempt", { key: submission.analysisKey });
      if (signal.aborted) return;
      setStream(detail); setStreamEpoch(value => value + 1); setPhase("submitted");
    });
  }

  function reset() {
    frozenSubmission.current = null;
    // 用户显式放弃后不再向其重复推销同一未决 claim（本轮窗口内）。
    if (recoveryRef.current) dismissedRecovery.current = recoveryRef.current.analysisKey;
    setPendingRecovery(null);
    setRecoveryResult(null);
    setStream(null); setPreparation(null); setProviderPreview(null);
    setProviderConsent(false); setExportConsent(false); setClosureConsent(false); setPreview(null); setChoice(null); setPicked([]);
    setSelectedSlot(null); setSearch(null); setPhase("select"); setError(""); setNotice("");
    originRef.current = null;
  }

  const budget = (providerPreview?.outbound_budget ?? null) as Record<string, unknown> | null;
  const dailyBudget = budget && typeof budget.daily_budget === "object" && budget.daily_budget !== null ? budget.daily_budget as Record<string, unknown> : null;
  const budgetBlocked = budget?.blocked === true || dailyBudget?.blocked === true;
  const activeStream = stream;
  // 平台上下文提供原生 kind=desktop：AIStreamProgress 据此走游标定时读取而非 SSE。
  return createPortal(<WorkbenchPlatformContext.Provider value={platform}><div className="offline-portal" data-theme={portalTheme}><dialog ref={dialog} className="fact-review-dialog offline-dialog device-ai-dialog" aria-labelledby="desktop-device-ai-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}>
    <header className="fact-review-heading"><div><span className="eyebrow">DEVICE HISTORY → AI · 桌面</span><h2 id="desktop-device-ai-title">设备 AI 分析</h2><p>本机预览 · 一次决定 · 服务端复核 · IPC 流式轮询</p></div><button type="button" className="text-button" onClick={onClose}>关闭</button></header>
    <div className="offline-content">
      <p className="review-boundary">分析对象是本设备保存的离线历史观察（轮胎 / 车辆 / 召回公告 / 公告检索四域）。面板通过 Tauri IPC 与本机 API 通信：预览指纹在本机 WebView 内用投影复刻端口重算（预览字节与本机槽位 sha256 逐一钉死后才使用），只有你明确确认后才会创建服务端准备记录，第二次确认后才交给 AI Provider。</p>
      {error ? <p className="inline-error" role="alert">{error}</p> : null}
      {notice ? <p className="review-boundary" role="status">{notice}</p> : null}
      {journalError ? <p className="inline-error" role="alert">台账不可用：{journalError}</p> : null}

      {phase === "select" && !activeStream ? <section aria-label="选择本机离线包">
        <h3>第 1 步 · 选择本机离线包与历史观察</h3>
        {!platform.offline ? <p className="inline-error">此宿主没有设备离线存储能力。</p> : !slots.length ? <p>本机还没有可用的离线资料包。请先在设备离线资料库保存，再回到这里。</p> : <div className="offline-pack-list">{slots.map(slot => <button type="button" className={`offline-pack-item${selectedSlot?.slot_id === slot.slot_id ? " selected" : ""}`} key={slot.slot_id} disabled={busy || slot.locked || slot.previous_owner} onClick={() => selectSlot(slot)}><strong>{slot.title}</strong><span>本机版本 #{slot.generation} · 包 SHA-256 {slot.sha256.slice(0, 12)}…</span>{slot.previous_owner ? <span className="tag warning">旧归属 · 不能用于设备 AI</span> : null}</button>)}</div>}
        {selectedSlot && !selectedSlot.locked && !selectedSlot.previous_owner ? <div className="compare-toolbar" role="group" aria-label="选择历史观察域">
          {PANEL_DOMAINS.map(item => <button type="button" key={item} className={domain === item ? "primary-button" : "secondary-button"} disabled={busy} onClick={() => selectDomain(item)}>{deviceAiDomainLabels[item]}</button>)}
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

      {choice && (phase === "preview" || phase === "prepared") && !activeStream ? <section aria-label="本机预览">
        <h3>第 2 步 · 本机预览即将外发的材料指纹</h3>
        <p><strong>{deviceAiDomainLabel(choice.domain)}域 · {deviceAiProjectionModeLabel(choice.mode)}</strong> · {choice.reads.length > 1 ? `已选 ${choice.reads.length} 条成员` : choice.reads[0].document.title} · 本机版本 #{choice.slot.generation} · 包 {choice.slot.byte_count.toLocaleString()} 字节 · {choice.slot.package_id}</p>
        <label htmlFor="desktop-device-ai-question">本次问题（2..2000 字符，服务端会与预览指纹绑定）</label>
        <textarea id="desktop-device-ai-question" rows={2} maxLength={2000} value={question} disabled={busy || phase !== "preview" || !!preview} onChange={event => { setQuestion(event.target.value); setPreview(null); setClosureConsent(false); }} />
        {phase === "preview" && !preview ? <div className="compare-toolbar"><button type="button" className="secondary-button" disabled={busy || question.trim().length < 2} onClick={() => void buildPreview()}>在本机重算指纹</button></div> : null}
        {preview ? <div className="device-ai-preview">
          <dl>
            <div><dt>question_sha256</dt><dd className="hash-value">{preview.question_sha256}</dd></div>
            <div><dt>selection_sha256</dt><dd className="hash-value">{preview.selection_sha256}</dd></div>
            <div><dt>local_preview_fingerprint</dt><dd className="hash-value">{preview.local_preview_fingerprint}</dd></div>
            <div><dt>package_sha256 / 字节</dt><dd className="hash-value">{preview.package_sha256} / {preview.package_byte_count.toLocaleString()} B</dd></div>
            <div><dt>expected_projection_sha256</dt><dd className="hash-value">{preview.projection_sha256}（{preview.projection_byte_count.toLocaleString()} B 规范字节）</dd></div>
            <div><dt>device_context_fingerprint（本机值）</dt><dd className="hash-value">{preview.device_context_fingerprint}</dd></div>
            {choice.mode === "frozen_decision_closure" ? <div><dt>resolved 闭包（approved_closure）</dt><dd className="hash-value">{preview.resolved_closure_member_keys.map(key => `${key.slice(0, 12)}…`).join(" ")}</dd></div> : null}
          </dl>
          <p className="review-boundary">预览由本机投影复刻端口重算（对封存向量 20/20 逐字节对拍）；预览字节先与本机槽位 sha256/字节钉死一致。服务端 prepare 仍以其权威投影复核，不一致即拒绝。上行的 device_context_fingerprint 以服务端准备记录为权威。</p>
          <details><summary>SDK 预览说明（原样展示）</summary><ul>{preview.notices.map((item, index) => <li key={index}>{item}</li>)}</ul></details>
          {phase === "preview" ? <>
            {choice.mode === "frozen_decision_closure" ? <label className="review-checkbox"><input type="checkbox" checked={closureConsent} disabled={busy} onChange={event => setClosureConsent(event.target.checked)} />我确认按上方展示的 {preview.resolved_closure_member_keys.length} 条成员组成冻结决定闭包（approved_closure 精确相等清单）提交。</label> : null}
            <label className="review-checkbox"><input type="checkbox" checked={exportConsent} disabled={busy} onChange={event => setExportConsent(event.target.checked)} />我允许将上述材料与问题交由 AI Provider 处理；这是一次性决定，不会自动重复。</label>
            <div className="compare-toolbar">
              <button type="button" className="primary-button" disabled={busy || !exportConsent || (choice.mode === "frozen_decision_closure" && !closureConsent)} onClick={() => void runPrepare("allow")}>{busy ? "正在创建准备记录…" : "确认并创建服务端准备记录"}</button>
              <button type="button" className="secondary-button" disabled={busy} onClick={() => void runPrepare("deny")}>拒绝本次外发</button>
            </div>
          </> : null}
        </div> : null}
      </section> : null}

      {phase === "prepared" && preparation && !activeStream ? <section aria-label="服务端准备与二次确认">
        <h3>第 3 步 · 服务端准备记录与二次确认</h3>
        <dl>
          <div><dt>prepare_id</dt><dd className="hash-value">{preparation.id}</dd></div>
          <div><dt>投影 / 上下文指纹</dt><dd className="hash-value">{preparation.projection_sha256}<br />{preparation.device_context_fingerprint}</dd></div>
          <div><dt>有效期至</dt><dd>{stamp(preparation.expires_at)}（replayed: {String(preparation.replayed)}）</dd></div>
        </dl>
        {providerPreview ? <section className="ai-status" aria-label="Provider 预检"><strong>Provider 预检（prepare 只读，不调用模型）</strong>
          <p>{String(providerPreview.provider)} · {String(providerPreview.state)} · 模型 {typeof providerPreview.model === "string" ? providerPreview.model : "未配置"}</p>
          {budget ? <p>外发预算：真实值 {String(budget.evidence_only_request_bytes)} B / 上界 {String(budget.upper_bound_request_bytes)} B / 限额 {String(budget.limit_bytes)} B · 投影 {String(budget.projection_bytes)} B{budget.blocked === true ? " · 上界超限，已阻止" : ""}{Number(budget.shortfall_bytes) > 0 ? ` · 缺口 ${String(budget.shortfall_bytes)} B` : ""}</p> : null}
          {dailyBudget ? <p>共享日预算：{String(dailyBudget.requests)} 次请求 / {(Number(dailyBudget.accounted_tokens) || 0).toLocaleString()} tokens 已记账{dailyBudget.blocked === true ? " · 预算已阻止提交" : ""}</p> : null}
        </section> : null}
        <label className="review-checkbox"><input type="checkbox" checked={providerConsent} disabled={busy} onChange={event => setProviderConsent(event.target.checked)} />我再次确认：将把该材料发送到已显示的模型处理（allow_external_processing 字面为 true）。</label>
        <div className="compare-toolbar">
          <button type="button" className="primary-button" disabled={busy || !providerConsent || budgetBlocked} onClick={() => void runSubmit(false)}>{busy ? "正在提交…" : "确认提交并接收流式结果"}</button>
          <button type="button" className="text-button" disabled={busy} onClick={reset}>放弃本次准备</button>
        </div>
      </section> : null}

      {/* 有未决 claim 即常驻显示（resolved 同时展示既有结果引用）；新提交会清空
          recoveryResult 并在 outcome 落账后由推导自动收回该区。 */}
      {recovery && (!activeStream || recoveryResult !== null) ? <section className="ai-recovery" aria-label="未知结果恢复">
        <h3>未知结果恢复</h3>
        <p>{recoveryResult ? deviceAiOutcomeLabel(recoveryResult.kind) : "检测到本机有未确认结果的提交记录。恢复只做只读核对，不会自动重新提交模型。"}</p>
        <div className="compare-toolbar">
          <button type="button" className="secondary-button" disabled={recoveryBusy} onClick={() => void runRecovery(true)}>{recoveryBusy ? "正在核对…" : "只读核对上次提交"}</button>
          {recoveryResult?.kind === "not_submitted" ? <button type="button" className="text-button" onClick={reset}>重新决定（新的一次决定）</button> : null}
          {recoveryResult?.kind === "unknown_local_claim" && frozenSubmission.current ? <button type="button" className="secondary-button" disabled={busy} onClick={() => void runSubmit(true)}>用同一标识重放核对（已受理的调用不会重复执行）</button> : null}
          {recoveryResult?.kind === "unknown_local_claim" && !frozenSubmission.current ? <span className="review-boundary">本窗口未保留原提交内容（不落盘），不能重放；请重新预览作新决定。</span> : null}
          {recoveryResult?.kind === "cross_session_replay_blocked" ? <span className="review-boundary">跨会话重放已被台账会话栅栏明确拒绝，仅可只读查看。</span> : null}
          {recoveryResult?.kind === "journal_integrity_failed" ? <span className="review-boundary">台账完整性校验未通过，自动恢复已停止；只读核对结果不可信。</span> : null}
        </div>
      </section> : null}

      {frozenSubmission.current && !busy ? <section className="ai-recovery" aria-label="未知结果核对">
        <h3>未知结果核对（只读）</h3>
        <div className="compare-toolbar">
          <button type="button" className="secondary-button" disabled={busy} onClick={() => void runLookup()}>用同一标识只读核对</button>
          <span className="review-boundary">核对只读取既有受理记录（device_ai_lookup_attempt），绝不重新提交模型调用。</span>
        </div>
      </section> : null}

      {activeStream ? <AIStreamProgress key={`${activeStream.analysis.id}:${streamEpoch}`} initial={activeStream} recovery={null}
        onDetail={value => { setStream(value); if (value.execution.terminal) { activeAnalysisKey.current = value.analysis.id; void recordTerminal(value, activeIntent.current, activeAnalysisKey.current); } }}
        onFact={() => {}} errorLabel={code => isProviderFailure(code) ? `Provider 处理失败：${code}` : `来源/传输失败：${code}`} /> : null}
      {activeStream && activeStream.execution.terminal ? <section className="ai-result" aria-label="设备 AI 分析结果">
        <h3>{activeStream.analysis.state === "completed" ? "已完成引用校验" : activeStream.analysis.state === "failed" ? "本次分析未完成" : "调用结果尚未确认"}</h3>
        <p>{activeStream.analysis.question}</p>
        <small>{activeStream.analysis.model} · {stamp(activeStream.analysis.created_at)} · {activeStream.analysis.usage ? `${activeStream.analysis.usage.total_tokens} tokens` : `用量未确认，保留 ${activeStream.analysis.reserved_tokens} tokens 预留`}</small>
        {activeStream.analysis.error_code ? <p role="alert">{isProviderFailure(activeStream.analysis.error_code) ? "Provider 处理失败" : "来源/传输失败"}：{activeStream.analysis.error_code} 生成中内容已作废。</p> : null}
        {activeStream.analysis.answer ? <>
          {activeStream.analysis.answer.claims.map((claim, index) => <article className={`ai-claim ${claim.type}`} key={index}><strong>{claim.type === "fact" ? "证据字段" : "模型推断 · 需人工核对"}</strong><p>{claim.text}</p></article>)}
          {activeStream.analysis.answer.uncertainty ? <div className="ai-claim inference"><strong>不确定性说明 · 需核对</strong><p>{activeStream.analysis.answer.uncertainty}</p></div> : null}
          <p className="review-boundary">{activeStream.analysis.answer.notice}</p>
        </> : null}
        <div className="compare-toolbar"><button type="button" className="secondary-button" onClick={reset}>重新预览，开始新的分析</button></div>
      </section> : null}

      <section className="ai-history" aria-label="设备 AI 台账">
        <div className="panel-title"><h3>设备 AI 历史台账（本机加密台账 · IPC 读写）</h3><button type="button" className="text-button" disabled={busy} onClick={() => void perform(async () => { await refreshJournal(); })}>刷新台账</button></div>
        {journalError ? <p className="inline-error" role="alert">{journalError}</p> : null}
        {journal ? (journal.entries.length ? <ul className="device-ai-journal">{[...journal.entries].reverse().map(entry => <li key={entry.sequence} className={entry.session_id !== journal.session_id ? "cross-session" : ""}>
          <span>#{entry.sequence} {deviceAiEventLabels[entry.event.type] ?? entry.event.type}</span>
          <small>{stamp(entry.wall_clock)} · 会话 {entry.session_id.slice(0, 8)}{entry.session_id !== journal.session_id ? " · 其他会话（只读）" : ""}</small>
          {entry.event.type === "failure_observed" ? <small>失败阶段 {deviceAiFailureLabels[entry.event.stage] ?? entry.event.stage} · {entry.event.code}{isProviderFailure(entry.event.code) ? "（Provider 处理失败）" : "（来源/传输失败）"}</small> : null}
        </li>)}</ul> : <p>本机台账还没有记录。预览与决定会先落账，只有确认后才提交模型。</p>) : <p>台账尚未读取。</p>}
        {journal && !journal.verification.ok ? <p className="inline-error" role="alert">台账完整性校验未通过（{journal.verification.violations.map(item => item.code).join("、")}），已停止使用台账内容。</p> : null}
      </section>
    </div>
  </dialog></div></WorkbenchPlatformContext.Provider>, document.body);
}
