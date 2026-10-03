/**
 * Mobile device-AI wiring glue (round 50 P1 final step).
 *
 * Pure, DOM-free helpers so the JS panel (device-ai-panel.tsx) stays thin and
 * every rule below runs under node:test. Three groups, none of them a new
 * wire: the six TireNativePlugin command bindings (deviceAiPrepare /
 * deviceAiSubmitStream / deviceAiLookup / deviceAiJournalRead /
 * deviceAiJournalAppend / deviceAiResolveUnknown — the Java command layer
 * mirrors the four-domain closed DTO plus the journal write and N18 recovery),
 * the four-domain selector assembly from native offline reads, and the
 * local-preview input assembly (pack bytes fetched through the standard native
 * API transport, sha256-bound to the slot BEFORE any projection port call —
 * the bytes never persist in the JS layer).
 *
 * The local preview reuses the packages projection port verbatim
 * (computeLocalPreview / buildDeviceAiPrepareBody): the port is anchored
 * 20/20 against the sealed authoritative vectors, so the mobile panel gains
 * the same recomputed projection_sha256 / device_context_fingerprint without
 * a second implementation.
 */
import type { NativeInvoke } from "@tire/native-client";
import type { OfflineHostStatus, OfflineReadResult, OfflineSlot } from "@tire/domain-types";
import {
  assertDeviceAiPrepareBody, buildDeviceAiPrepareBody, computeLocalPreview,
  DEVICE_AI_PREPARE_DOMAIN_MODES,
  type DeviceAiLocalPreviewSummary, type DeviceAiOriginBindingWire, type DeviceAiPrepareBody,
  type DeviceAiPrepareResultView, type DeviceAiPrepareSelectorWire, type DeviceAiProviderConsentBody,
  type DeviceAiSelectorWire,
} from "../../../packages/api-client/src/device-ai-host";
import { deviceAiDomainLabel } from "../../web/components/device-ai-values";

export { DEVICE_AI_PREPARE_DOMAIN_MODES };
export type MobileDeviceAiDomain = keyof typeof DEVICE_AI_PREPARE_DOMAIN_MODES;
/** Panel domain order (prepare wire's four open domains; test_event stays closed, N27). */
export const MOBILE_DEVICE_AI_DOMAINS: readonly MobileDeviceAiDomain[] = ["tire", "vehicle", "recall", "recall_search"];

// ---------------------------------------------------------------------------
// Plugin command bridge (the four Java TireNativePlugin entries, wire JSON).
// ---------------------------------------------------------------------------

/** Capacitor rejection carrying the closed Java code (call.reject(serverCode||code, code)). */
export function deviceAiCommandCode(cause: unknown): string {
  if (typeof cause === "string" && cause) return cause;
  const value = cause as { code?: unknown; message?: unknown } | null;
  if (value && typeof value === "object") {
    if (typeof value.code === "string" && value.code) return value.code;
    if (typeof value.message === "string" && /^[A-Za-z]/.test(value.message) && !/\s/.test(value.message)) return value.message;
  }
  return "device_ai_host_unavailable";
}

export interface MobileDeviceAiBridge {
  /** POST /v1/ai/device-evidence-packs via the Java host client (closed four-domain body). */
  prepare(body: DeviceAiPrepareBody, idempotencyKey: string): Promise<DeviceAiPrepareResultView>;
  /** POST /v1/ai/analysis-streams with the closed device_submission branch. */
  submitStream(submission: MobileDeviceAiStreamSubmission, idempotencyKey: string): Promise<MobileDeviceAiStreamDetail>;
  /** Read-only recovery: kind=prepare (by key) | attempt (by key) | prepare_read (by id). */
  lookup(request: { kind: "prepare" | "attempt"; idempotency_key: string } | { kind: "prepare_read"; prepare_id: string }): Promise<unknown>;
  /** Keystore-sealed journal verification + recovery read (never writes). */
  journalRead(owner: string, generation: number, sessionId: string): Promise<MobileDeviceAiJournalReport>;
  /** Keystore-sealed journal append (the ONLY write path into the local ledger; five fences). */
  journalAppend(owner: string, generation: number, sessionId: string, event: MobileDeviceAiJournalEvent): Promise<MobileDeviceAiJournalEntry>;
  /** N18 lookup-first unknown-outcome resolution (read-only; never resubmits on its own). */
  resolveUnknown(request: MobileDeviceAiResolveUnknownRequest): Promise<MobileDeviceAiUnknownOutcome>;
}

export interface MobileDeviceAiStreamSubmission {
  pack_id: string;
  question: string;
  prepare_id: string;
  host_receipt_id: string;
  device_context_fingerprint: string;
  provider_consent: DeviceAiProviderConsentBody;
}

/** Closed subset of AIStreamDetail the Java checkedStreamDetail already validated. */
export interface MobileDeviceAiStreamDetail {
  analysis: { id: string; question: string; state: string; answer: unknown; error_code: string | null; model: string; created_at: string; usage: unknown; reserved_tokens: number };
  execution: { state: string; terminal: boolean };
  server_time: string;
}

export interface MobileDeviceAiJournalReport {
  ok: boolean;
  length: number;
  violations: unknown[];
  cross_session_entries: unknown[];
  entries?: unknown[];
}

// ---------------------------------------------------------------------------
// Journal events (the six closed classes) + N18 unknown-outcome resolution.
// Java command layer mirrors: deviceAiJournalAppend / deviceAiResolveUnknown.
// ---------------------------------------------------------------------------

/** Six journal event classes (TS discriminated union parity; wire not frozen, D15). */
export type MobileDeviceAiJournalEvent =
  | { type: "preview_shown"; intent_id: string; local_preview_fingerprint: string; question_sha256: string; package_sha256: string }
  | { type: "decision_made"; intent_id: string; decision: "allow" | "deny"; local_preview_fingerprint: string }
  | { type: "prepare_created"; intent_id: string; prepare_id: string; idempotency_key: string; projection_sha256: string; device_context_fingerprint: string }
  | { type: "claim_submitted"; intent_id: string; prepare_id: string; analysis_key: string; question_sha256: string }
  | { type: "outcome_observed"; intent_id: string; analysis_key: string; request_id: string; state: string }
  | { type: "failure_observed"; intent_id: string | null; stage: string; code: string };

/** Closed subset of the appended entry the Java append command returns. */
export interface MobileDeviceAiJournalEntry {
  sequence: number;
  owner?: string;
  generation?: number;
  session_id?: string;
  clock?: number;
  wall_clock?: string;
  event: { type: string } & Record<string, unknown>;
}

export interface MobileDeviceAiResolveUnknownRequest {
  analysis_key: string;
  /** null disables the intent filter (TS resolveUnknownOutcome intentId?). */
  intent_id: string | null;
  owner: string;
  generation: number;
  session_id: string;
}

/** N18 four-plus-one outcome kinds (deviceAiOutcomeLabel carries the UI text). */
export type MobileDeviceAiUnknownOutcome =
  | { kind: "resolved"; detail: MobileDeviceAiStreamDetail }
  | { kind: "not_submitted" }
  | { kind: "unknown_local_claim"; analysis_key: string; resubmission: "same_key_same_body_user_decision_only" }
  | { kind: "cross_session_replay_blocked" }
  | { kind: "journal_integrity_failed"; violations: unknown[] };

function checkedJournalEntry(value: unknown): MobileDeviceAiJournalEntry {
  const entry = value as Partial<MobileDeviceAiJournalEntry> | null;
  if (!entry || typeof entry.sequence !== "number" || !entry.event || typeof entry.event.type !== "string")
    throw new Error("设备 AI 台账写入结果格式不完整。");
  return value as MobileDeviceAiJournalEntry;
}

function checkedUnknownOutcome(value: unknown): MobileDeviceAiUnknownOutcome {
  const outcome = value as Partial<MobileDeviceAiUnknownOutcome> | null;
  if (!outcome || typeof outcome.kind !== "string") throw new Error("未知结果恢复核对结果格式不完整。");
  if (outcome.kind === "resolved") {
    const detail = (value as { detail?: unknown }).detail;
    try { checkedStreamDetail(detail); } catch { throw new Error("未知结果恢复核对结果格式不完整。"); }
  }
  return value as MobileDeviceAiUnknownOutcome;
}

function commandError(cause: unknown): never {
  const code = deviceAiCommandCode(cause);
  const error = new Error(code);
  (error as Error & { code?: string }).code = code;
  throw error;
}

/** Minimal closed-view re-check (the Java layer already ran the full check). */
function checkedPrepareView(value: unknown): DeviceAiPrepareResultView {
  const view = value as Partial<DeviceAiPrepareResultView> | null;
  if (!view || typeof view.id !== "string" || typeof view.pack_id !== "string"
    || typeof view.replayed !== "boolean" || typeof view.device_context_fingerprint !== "string")
    throw new Error("设备 AI 准备记录响应格式不完整。");
  return value as DeviceAiPrepareResultView;
}

function checkedStreamDetail(value: unknown): MobileDeviceAiStreamDetail {
  const detail = value as Partial<MobileDeviceAiStreamDetail> | null;
  if (!detail || !detail.analysis || typeof detail.analysis.id !== "string"
    || !detail.execution || typeof detail.execution.terminal !== "boolean"
    || typeof detail.execution.state !== "string")
    throw new Error("AI 受理结果与当前请求不匹配或格式不完整。");
  return value as MobileDeviceAiStreamDetail;
}

function checkedJournalReport(value: unknown): MobileDeviceAiJournalReport {
  const report = value as Partial<MobileDeviceAiJournalReport> | null;
  if (!report || typeof report.ok !== "boolean" || typeof report.length !== "number" || !Array.isArray(report.violations))
    throw new Error("设备 AI 台账核对结果格式不完整。");
  return value as MobileDeviceAiJournalReport;
}

export function createMobileDeviceAiBridge(invoke: NativeInvoke): MobileDeviceAiBridge {
  /** Only the IPC rejection is code-mapped; local view checks keep their own messages. */
  async function command<T>(name: string, request: Record<string, unknown>): Promise<T> {
    try {
      return await invoke<T>(name, { request });
    } catch (cause) { commandError(cause); }
  }
  return {
    async prepare(body, idempotencyKey) {
      assertDeviceAiPrepareBody(body); // same closed assertion as the Java command layer
      return checkedPrepareView(await command<unknown>("device_ai_prepare", { ...body, idempotency_key: idempotencyKey }));
    },
    async submitStream(submission, idempotencyKey) {
      return checkedStreamDetail(await command<unknown>("device_ai_submit_stream", { ...submission, idempotency_key: idempotencyKey }));
    },
    async lookup(request) {
      return command<unknown>("device_ai_lookup", request);
    },
    async journalRead(owner, generation, sessionId) {
      return checkedJournalReport(await command<unknown>("device_ai_journal_read", { owner, generation, session_id: sessionId }));
    },
    async journalAppend(owner, generation, sessionId, event) {
      return checkedJournalEntry(await command<unknown>("device_ai_journal_append",
        { owner, generation, session_id: sessionId, event }));
    },
    async resolveUnknown(request) {
      return checkedUnknownOutcome(await command<unknown>("device_ai_resolve_unknown", { ...request }));
    },
  };
}

// ---------------------------------------------------------------------------
// Orchestration helpers: per-stage journal event mapping (web panel parity) and
// the N18 failure-stage split (provider vs source). Pure, node:test-covered.
// ---------------------------------------------------------------------------

/** 预览完成：记录本机重算指纹的展示（preview_shown）。 */
export function mobileJournalEventForPreview(intentId: string, summary: DeviceAiLocalPreviewSummary): MobileDeviceAiJournalEvent {
  return { type: "preview_shown", intent_id: intentId,
    local_preview_fingerprint: summary.local_preview_fingerprint,
    question_sha256: summary.question_sha256, package_sha256: summary.package_sha256 };
}

/** 决定：allow / deny 一次性决定（decision_made）。 */
export function mobileJournalEventForDecision(intentId: string, decision: "allow" | "deny",
  localPreviewFingerprint: string): MobileDeviceAiJournalEvent {
  return { type: "decision_made", intent_id: intentId, decision, local_preview_fingerprint: localPreviewFingerprint };
}

/** 准备记录创建成功（prepare_created）。 */
export function mobileJournalEventForPrepareCreated(intentId: string, idempotencyKey: string,
  view: Pick<DeviceAiPrepareResultView, "id" | "projection_sha256" | "device_context_fingerprint">): MobileDeviceAiJournalEvent {
  return { type: "prepare_created", intent_id: intentId, prepare_id: view.id, idempotency_key: idempotencyKey,
    projection_sha256: view.projection_sha256, device_context_fingerprint: view.device_context_fingerprint };
}

/** 提交主张：写于 submitStream 之前（claim_submitted，恢复的本地凭据）。 */
export function mobileJournalEventForClaim(intentId: string, prepareId: string, analysisKey: string,
  questionSha256: string): MobileDeviceAiJournalEvent {
  return { type: "claim_submitted", intent_id: intentId, prepare_id: prepareId,
    analysis_key: analysisKey, question_sha256: questionSha256 };
}

/** 结果观察（outcome_observed）；无 intent 时与 Web 一致落空串。 */
export function mobileJournalEventForOutcome(intentId: string | null, analysisKey: string, requestId: string,
  state: string): MobileDeviceAiJournalEvent {
  return { type: "outcome_observed", intent_id: intentId ?? "", analysis_key: analysisKey, request_id: requestId, state };
}

/** 失败观察（failure_observed）。 */
export function mobileJournalEventForFailure(intentId: string | null, stage: string, code: string): MobileDeviceAiJournalEvent {
  return { type: "failure_observed", intent_id: intentId, stage, code };
}

/** Provider 失败与来源/传输失败分离（web isProviderFailure 同一封闭集合）。 */
export function mobileFailureStage(code: string | null | undefined): "provider" | "source" {
  return !!code && (code.startsWith("ai_provider_") || code === "ai_refused" || code === "ai_response_incomplete")
    ? "provider" : "source";
}

/** 提交失败的台账 code：优先封闭码，其次本地消息，绝不伪造。 */
export function mobileFailureCode(cause: unknown): string {
  const error = cause as { code?: unknown } | null;
  if (error && typeof error === "object" && typeof error.code === "string" && error.code) return error.code;
  if (cause instanceof Error && cause.message) return cause.message;
  return "unknown";
}

/**
 * 意图标识缓存键（web intentIdFor 同一拼法）：同一 slot + 域 + 成员集合 + 问题摘要
 * 在一次面板会话内复用同一 intent_id，使 preview/decision/prepare/claim/outcome
 * 五类事件可按意图串起来。
 */
export function mobileIntentKey(slotId: string, domain: string, memberKeys: readonly string[], questionSha256: string): string {
  return `${slotId}:${domain}:${[...memberKeys].sort().join(",")}:${questionSha256}`;
}

/** Intent cache factory: same key -> same UUID for the whole dialog session. */
export function createMobileIntentCache(): (slotId: string, domain: string, memberKeys: readonly string[], questionSha256: string) => string {
  const cache = new Map<string, string>();
  return (slotId, domain, memberKeys, questionSha256) => {
    const key = mobileIntentKey(slotId, domain, memberKeys, questionSha256);
    let existing = cache.get(key);
    if (!existing) { existing = crypto.randomUUID(); cache.set(key, existing); }
    return existing;
  };
}

// ---------------------------------------------------------------------------
// Four-domain selector assembly from a native offline read.
// ---------------------------------------------------------------------------

/**
 * Selector from a read document (web panel parity): record-carrying domains
 * (recall / recall_search) keep document.record_index; tire / vehicle are
 * whole-observation domains and always send null.
 */
export function mobileSelectorFromRead(domain: MobileDeviceAiDomain, read: OfflineReadResult): DeviceAiPrepareSelectorWire {
  const member = read.member;
  if (!member || member.reference.kind !== domain) {
    throw new Error(`所选记录不是${deviceAiDomainLabel(domain)}域历史观察，本阶段不支持设备 AI 分析。`);
  }
  const recordIndex = domain === "tire" || domain === "vehicle" ? null : read.document.record_index;
  return {
    kind: domain, member_key: member.key, document_id: read.document.id, record_index: recordIndex,
    reference: member.reference as unknown as DeviceAiPrepareSelectorWire["reference"],
  } as DeviceAiPrepareSelectorWire;
}

// ---------------------------------------------------------------------------
// Local preview inputs: origin binding from the native owner state, and the
// pack-bytes fetch bound to the slot's pinned sha256/byte_count.
// ---------------------------------------------------------------------------

export function mobilePreviewOrigin(status: OfflineHostStatus, slot: OfflineSlot,
  schema: "offline-pack@1" | "offline-pack@2"): DeviceAiOriginBindingWire {
  if (!status.profile_id) throw new Error("本机离线归属未就绪，暂不能预览设备 AI 材料。");
  return {
    expected_profile_id: status.profile_id, expected_owner_epoch: status.owner_epoch,
    slot_id: slot.slot_id, expected_generation: slot.generation, package_id: slot.package_id,
    expected_sha256: slot.sha256, expected_byte_count: slot.byte_count,
    owner_scope_id: slot.owner_scope_id, package_schema: schema,
  };
}

export async function sha256HexOf(bytes: Uint8Array): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes as unknown as ArrayBuffer);
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

export interface MobilePackEnvelope { bytes: Uint8Array; schema: "offline-pack@1" | "offline-pack@2" }

/**
 * Verify fetched archive bytes against the SLOT's pinned digest before any
 * local projection (the native store never hands its stored copy to the JS
 * layer; this re-download is the same server archive the slot pinned).
 */
export async function verifyMobilePackBytes(bytes: Uint8Array, slot: OfflineSlot): Promise<MobilePackEnvelope> {
  if (bytes.byteLength !== slot.byte_count) throw new Error("本机包字节数与所选版本不一致，已停止预览。");
  const digest = await sha256HexOf(bytes);
  if (digest !== slot.sha256) throw new Error("本机包 SHA-256 与所选版本不一致，已停止预览。");
  let envelope: { schema?: unknown };
  try { envelope = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
  catch { throw new Error("本机包结构不是有效 UTF-8 JSON。"); }
  if (envelope.schema !== "offline-pack@1" && envelope.schema !== "offline-pack@2") throw new Error("本机包结构不受支持。");
  return { bytes, schema: envelope.schema };
}

/**
 * Full local preview over the packages projection port (four domains plus
 * frozen_decision_closure). projection_binding is "recomputed": the panel
 * shows locally recomputed fingerprints BEFORE any export consent. The mode is
 * the caller's decision (single pick -> the domain's locked converter mode;
 * tire multi-pick -> frozen_decision_closure), exactly like the web panel.
 */
export async function mobileLocalPreview(bytes: Uint8Array, status: OfflineHostStatus, slot: OfflineSlot,
  input: { question: string; selectors: DeviceAiSelectorWire[]; projectionMode: string },
): Promise<{ summary: DeviceAiLocalPreviewSummary; origin: DeviceAiOriginBindingWire; body: DeviceAiPrepareBody }> {
  const { schema } = await verifyMobilePackBytes(bytes, slot);
  const origin = mobilePreviewOrigin(status, slot, schema);
  const frozen = input.projectionMode === "frozen_decision_closure";
  const summary = await computeLocalPreview(bytes, {
    question: input.question, selectors: input.selectors, origin,
    projectionMode: input.projectionMode as Parameters<typeof computeLocalPreview>[1]["projectionMode"],
    approvedClosure: frozen ? input.selectors : null,
  });
  const body = buildDeviceAiPrepareBody({
    origin, preview: summary, selectors: input.selectors as DeviceAiPrepareSelectorWire[],
    approvedClosure: frozen ? input.selectors as DeviceAiPrepareSelectorWire[] : null,
    hostReceiptId: crypto.randomUUID(), intentId: crypto.randomUUID(),
  });
  return { summary, origin, body };
}
