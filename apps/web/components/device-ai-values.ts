// Device-AI web host values: provider policy fingerprint mirror, recovery
// pointer persistence and Chinese labels. No networking here.
//
// The policy fingerprint mirrors apps/api/tire_api/ai_analysis.py
// device_provider_policy_fingerprint: digest({'provider','model','allow_private',
// 'allowed_privacy_classes','prompt_version','grounding_schema'}) with the
// server's stable_json semantics (codepoint-sorted compact JSON). The mirrored
// constants (PROMPT_VERSION, OUTPUT_SCHEMA) are intentionally pinned here: when
// the server policy changes, the consent fingerprint stops matching and the
// submit is rejected with device_ai_consent_mismatch — the user must re-preview
// and re-consent, which is the designed fail-closed behaviour, never a silent
// provider switch.
import { canonicalDeviceAiJson, type DeviceAiJsonAst } from "../../../packages/api-client/src/device-ai-exact";

const DEVICE_AI_PROMPT_VERSION = "tire-grounding@1";
const DEVICE_AI_GROUNDING_SCHEMA: DeviceAiJsonAst = {
  type: "object", additionalProperties: false,
  properties: {
    claims: { type: "array", items: {
      type: "object", additionalProperties: false,
      properties: { type: { type: "string", enum: ["fact", "inference"] },
        text: { type: "string" },
        fact_ids: { type: "array", items: { type: "string" } },
        evidence_ids: { type: "array", items: { type: "string" } } },
      required: ["type", "text", "fact_ids", "evidence_ids"] } },
    uncertainty: { type: "string" },
  },
  required: ["claims", "uncertainty"],
};

async function sha256Text(value: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

export async function deviceProviderPolicyFingerprint(input: { provider: string; model: string; allowPrivate: boolean }): Promise<string> {
  const groundingSchema = await sha256Text(canonicalDeviceAiJson(DEVICE_AI_GROUNDING_SCHEMA));
  const value: DeviceAiJsonAst = {
    provider: input.provider,
    model: input.model,
    allow_private: input.allowPrivate,
    allowed_privacy_classes: input.allowPrivate ? ["public", "private"] : ["public"],
    prompt_version: DEVICE_AI_PROMPT_VERSION,
    grounding_schema: groundingSchema,
  };
  return sha256Text(canonicalDeviceAiJson(value));
}

export const DEVICE_AI_RECOVERY_KEY = "tire-device-ai-recovery-v1";

export interface DeviceAiRecoveryPointer { intentId: string; prepareKey: string; analysisKey: string; requestId: string }

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export function parseDeviceAiRecovery(raw: string | null): DeviceAiRecoveryPointer | null {
  if (!raw) return null;
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return null; }
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (typeof row.intentId !== "string" || !UUID.test(row.intentId)) return null;
  if (typeof row.prepareKey !== "string" || !UUID.test(row.prepareKey)) return null;
  if (typeof row.analysisKey !== "string" || !UUID.test(row.analysisKey)) return null;
  if (typeof row.requestId !== "string" || !row.requestId || row.requestId.length > 80) return null;
  return { intentId: row.intentId, prepareKey: row.prepareKey, analysisKey: row.analysisKey, requestId: row.requestId };
}

export function rememberDeviceAiRecovery(pointer: DeviceAiRecoveryPointer | null): void {
  try {
    if (pointer) sessionStorage.setItem(DEVICE_AI_RECOVERY_KEY, JSON.stringify(pointer));
    else sessionStorage.removeItem(DEVICE_AI_RECOVERY_KEY);
  } catch { /* Server-side lookup remains available when tab storage is blocked. */ }
}

export const deviceAiEventLabels: Record<string, string> = {
  preview_shown: "已展示本机预览", decision_made: "已作出一次决定", prepare_created: "已创建服务端准备记录",
  claim_submitted: "已提交模型调用", outcome_observed: "已观察到调用结果", failure_observed: "记录到失败",
};

// P1-4c 四域标签：与 prepare DTO 的开放域集合（tire/vehicle/recall/recall_search）
// 一一对应；test_event 不在面板域选择中（N27 封闭集合，服务端 DTO 即 422）。
export type DeviceAiPanelDomain = "tire" | "vehicle" | "recall" | "recall_search";
export const deviceAiDomainLabels: Record<DeviceAiPanelDomain, string> = {
  tire: "轮胎", vehicle: "车辆", recall: "召回公告", recall_search: "公告检索",
};

// 投影模式标签：前五个是 prepare DTO Literal 的五个值；frozen_decision_closure
// 仅 tire 域可用（其余三域各自锁定 converter 模式）。
export const deviceAiProjectionModeLabels: Record<string, string> = {
  single_observation: "单条观察",
  frozen_decision_closure: "冻结决定闭包",
  complete_observation: "完整车辆观察",
  complete_formal_observation: "完整正式公告观察",
  candidate_page_context: "候选检索页上下文",
};

export function deviceAiDomainLabel(kind: string | null | undefined): string {
  if (kind && kind in deviceAiDomainLabels) return deviceAiDomainLabels[kind as DeviceAiPanelDomain];
  return kind === "test_event" ? "测试事件（受限）" : kind || "未知域";
}

export function deviceAiProjectionModeLabel(mode: string | null | undefined): string {
  return (mode && deviceAiProjectionModeLabels[mode]) || mode || "未知模式";
}

export const deviceAiFailureLabels: Record<string, string> = {
  local_preview: "本机预览", decision: "决定", prepare: "服务端准备", submit: "模型提交", outcome: "结果读取", recovery: "恢复核对",
  provider: "Provider 处理", source: "来源/传输",
};

export function deviceAiOutcomeLabel(kind: string): string {
  return ({
    resolved: "服务端已有该调用的记录，可直接查看既有结果。",
    not_submitted: "没有已提交的调用记录，可重新决定是否分析。",
    unknown_local_claim: "本机记录了提交但服务端未确认受理；只能用同一标识重放核对，不能自动重试。",
    cross_session_replay_blocked: "该提交属于另一个页面会话，本会话不能重放；只能只读查看原记录。",
    journal_integrity_failed: "本机设备 AI 台账未通过完整性校验，已停止自动恢复。",
  } as Record<string, string>)[kind] || kind;
}

export function deviceAiHostErrorMessage(error: unknown): string {
  const code = error instanceof Error && /^device_ai_/.test(error.message) ? error.message
    : (error as { code?: unknown })?.code;
  if (typeof code === "string" && code.startsWith("device_ai_")) {
    return ({
      device_ai_host_invalid_argument: "设备 AI 请求参数无效，请重新选择本机包与问题。",
      device_ai_host_package_mismatch: "本机包与所选指纹不一致，请重新读取包后再预览。",
      device_ai_host_preview_unsupported: "所选域或投影模式不在设备 AI 预览支持范围内（四域：轮胎/车辆/召回公告/公告检索）。",
      device_ai_host_journal_owner_mismatch: "设备 AI 台账归属已变化，旧记录已失效。",
      device_ai_host_journal_generation_mismatch: "设备 AI 台账已重建，旧记录已失效。",
      device_ai_host_journal_session_mismatch: "此台账条目属于其他页面会话，不能在本会话使用。",
      device_ai_host_journal_chain_broken: "设备 AI 台账链不连续，已停止写入。",
      device_ai_host_journal_entry_tampered: "设备 AI 台账条目未通过校验，已停止写入。",
      device_ai_host_journal_clock_regression: "设备 AI 台账时间戳回退，已停止写入。",
      device_ai_host_journal_corrupt: "设备 AI 台账无法解密或已损坏。",
      device_ai_projection_mismatch: "本地投影摘要与服务端重算不一致，本次未创建准备记录。",
      device_ai_prepare_idempotency_mismatch: "同一标识不能用于不同的准备请求。",
      device_ai_archive_expected_mismatch: "服务端归档与所选包不一致，请重新保存包。",
      device_ai_submission_echo_mismatch: "提交回显与准备记录不一致，请重新预览。",
      device_ai_consent_mismatch: "Provider 同意六元组与服务端复算不一致，需重新预览授权。",
      device_ai_question_mismatch: "提交的问题与准备记录绑定的问题不一致。",
      device_ai_preparation_expired: "准备记录已过期，请重新预览并授权。",
      device_ai_pack_expired: "证据包已过期，请重新预览并授权。",
      device_ai_projection_capacity: "所选材料的投影超过容量限制，未截断、未提交。",
      device_ai_selected_restricted: "所选材料受限制，不能交给 AI Provider 处理。",
      device_ai_domain_unsupported: "所选材料域不受支持（本包 schema 或所选域不匹配）。",
      device_ai_projection_mode_unsupported: "所选域与投影模式不匹配，或混选了不同域的材料。",
      device_ai_closure_consent_required: "冻结决定闭包与所选集合不一致：依赖展开改变了闭包，请调整所选成员后重试。",
      device_ai_member_missing: "所选成员不在本机包内，请重新选择。",
      device_ai_member_ambiguous: "本机包内成员指向不唯一，已停止外发。",
      device_ai_document_missing: "所选记录不在本机包内，请重新选择。",
      device_ai_document_mismatch: "所选记录与成员绑定不一致，请重新选择。",
      device_ai_selector_mismatch: "所选 selector 形状与包内材料不一致，请重新选择。",
      device_ai_selector_capacity: "一次请求最多选择 6 条成员。",
      device_ai_selector_ambiguous: "同一成员被重复选择。",
      device_ai_receipt_mismatch: "成员回执与所选引用不一致，已停止外发。",
      device_ai_record_mismatch: "所选记录序号超出包内记录范围。",
      device_ai_package_binding_mismatch: "本机包绑定校验失败，请重新保存包。",
    } as Record<string, string>)[code] || `设备 AI 操作被拒绝（${code}）。`;
  }
  return error instanceof Error ? error.message : "设备 AI 操作未完成，请重试。";
}
