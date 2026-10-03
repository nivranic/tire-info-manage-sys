// 桌面设备 AI IPC 映射层：六个已注册 Tauri 命令
// （device_ai_prepare / device_ai_submit_stream / device_ai_lookup_attempt /
//   device_ai_read_journal / device_ai_journal_append /
//   device_ai_resolve_unknown，lib.rs）的信封 → 领域错误翻译。
//
// 服务端 HTTP 拒绝不是 IPC 错误：lib.rs 以 `{outcome:"rejected", http_status,
// code, message, run_id}` 信封透传，这里映射为 ApiError（与 Web 管线同构，
// 404 驱动 N18 只读核对、409 驱动冲突 UX）。device_ai_resolve_unknown 复用
// 同一信封（accepted.value 即 {kind,...} 恢复分支）。Tauri 命令的
// Err(&'static str) 原生闭集码映射为 DesktopError；device_ai_host_* 码保留
// 原样交给 deviceAiHostErrorMessage 显示。journal 读/写命令不走 HTTP 信封，
// 用 deviceAiRawInvoke 原值透传（同一套错误翻译）。invoke 以参数注入，便于
// Node 单测。
import { ApiError } from "@tire/api-client";
import { DesktopError } from "./native-platform";
import type { DeviceAiJournalEntry } from "../../../packages/api-client/src/device-ai-host";

export type DeviceAiHttpEnvelope =
  | { outcome: "accepted"; http_status: number; value: unknown }
  | { outcome: "rejected"; http_status: number; code: string | null; message: string | null; run_id: string | null };

export interface DeviceAiJournalView {
  schema: string;
  owner: string;
  generation: number;
  session_id: string;
  length: number;
  entries: DeviceAiJournalEntry[];
  verification: { ok: boolean; length: number; violations: { code: string; sequence: number | null }[]; cross_session_entries: { sequence: number; session_id: string }[] };
}

export type DeviceAiInvoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

function translateInvokeError(cause: unknown): Error {
  // Tauri 命令的 Err(&'static str)：device_ai_host_* 保留闭集码原文，
  // 其余按原生闭集码走 DesktopError 的中文文案表。
  const code = typeof cause === "string" ? cause : (cause as { code?: unknown } | null)?.code;
  if (typeof code === "string" && code.startsWith("device_ai_")) return Object.assign(new Error(code), { code });
  return new DesktopError(typeof code === "string" ? code : cause);
}

export async function deviceAiInvoke<T>(invoke: DeviceAiInvoke, command: string, args?: Record<string, unknown>): Promise<T> {
  let envelope: unknown;
  try {
    envelope = await invoke(command, args);
  } catch (cause) {
    throw translateInvokeError(cause);
  }
  if (!envelope || typeof envelope !== "object"
    || ((envelope as { outcome?: unknown }).outcome !== "accepted"
      && (envelope as { outcome?: unknown }).outcome !== "rejected")) {
    throw new DesktopError("invalid_response");
  }
  const result = envelope as DeviceAiHttpEnvelope;
  if (result.outcome === "accepted") return result.value as T;
  throw new ApiError(result.http_status, result.message ?? `请求失败（HTTP ${result.http_status}）`, result.code ?? undefined, result.run_id ?? undefined);
}

/** 不走 HTTP 信封的命令（device_ai_read_journal / device_ai_journal_append）：原值透传 + 同一套错误翻译。 */
export async function deviceAiRawInvoke<T>(invoke: DeviceAiInvoke, command: string, args?: Record<string, unknown>): Promise<T> {
  try {
    return (await invoke(command, args)) as T;
  } catch (cause) {
    throw translateInvokeError(cause);
  }
}

/** 面板打开时的恢复指针：台账中最后一条尚无对应 outcome_observed 的 claim_submitted。 */
export interface DeviceAiPendingClaim { intentId: string; analysisKey: string }

export function deriveDeviceAiPendingClaim(entries: DeviceAiJournalEntry[]): DeviceAiPendingClaim | null {
  const pending = new Map<string, DeviceAiPendingClaim>();
  for (const entry of entries) {
    const event = entry?.event;
    if (!event || typeof event !== "object") continue;
    if (event.type === "claim_submitted") pending.set(event.analysis_key, { intentId: event.intent_id, analysisKey: event.analysis_key });
    else if (event.type === "outcome_observed") pending.delete(event.analysis_key);
  }
  const remaining = [...pending.values()];
  return remaining.length ? remaining[remaining.length - 1] : null;
}
