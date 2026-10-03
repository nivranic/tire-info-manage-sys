import type { AIAnalysis, AIStreamDetail, AIStreamEvent } from "@tire/domain-types";

export const AI_RECOVERY_KEY = "tire-ai-stream-recovery-v1";
export interface AIRecoveryPointer { key: string; requestId?: string; cursor?: string }
export interface AIEventPosition { cursor: string; sequence: number; eventId: string | null }

/** Only identifiers are retained in this tab; never persist evidence, question or consent. */
export function parseAIRecovery(raw: string | null): AIRecoveryPointer | null {
  if (!raw || raw.length > 1400) return null;
  try {
    const value = JSON.parse(raw);
    if (!value || typeof value !== "object" || typeof value.key !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value.key)) return null;
    if (value.requestId !== undefined && (typeof value.requestId !== "string" || !/^[a-z0-9-]{1,64}$/i.test(value.requestId))) return null;
    if (value.cursor !== undefined && (typeof value.cursor !== "string" || !value.cursor || value.cursor.length > 512 || /[\r\n\0]/.test(value.cursor))) return null;
    return { key: value.key, ...(value.requestId ? { requestId: value.requestId } : {}), ...(value.cursor ? { cursor: value.cursor } : {}) };
  } catch { return null; }
}

export function advanceAIEvent(requestId: string, current: AIEventPosition, event: AIStreamEvent): AIEventPosition {
  if (event.request_id !== requestId) throw new Error("AI 事件属于另一条请求，已停止读取。");
  if (event.sequence < current.sequence) return current;
  if (event.sequence === current.sequence) {
    if (event.id !== current.eventId || event.cursor !== current.cursor) throw new Error("AI 事件序号发生冲突。");
    return current;
  }
  if (current.sequence && event.sequence !== current.sequence + 1) throw new Error("AI 事件序号不连续，请重新读取已保存进度。");
  return { cursor: event.cursor, sequence: event.sequence, eventId: event.id };
}

export function visibleAIDrafts(detail: AIStreamDetail, invalidated = false) {
  const active = !invalidated && !detail.execution.terminal && detail.analysis.state === "pending";
  return { claims: active ? [...detail.draft_claims].sort((a, b) => a.index - b.index) : [], uncertainty: active ? detail.draft_uncertainty : null };
}

export function canExportAIAnalysis(run: AIAnalysis | null): run is AIAnalysis & { answer: NonNullable<AIAnalysis["answer"]> } {
  return !!run && run.state === "completed" && !!run.answer;
}

export const aiStreamStateLabels = {
  accepted: "请求已受理，等待开始", running: "正在生成分析", completed: "已完成并提交引用校验结果",
  failed: "本次分析未完成，草稿已作废", outcome_unknown: "调用结果尚未确认，草稿已作废",
};

export const aiStreamErrorMessages: Record<string, string> = {
  ai_stream_interrupted: "分析响应在完成前中断，结果与用量尚未确认。请核对原调用记录和供应商用量；不会自动重新调用模型。",
  ai_stream_protocol_error: "模型响应的顺序或最终正文不一致，未通过完整性校验，生成内容已丢弃。不会自动重试；请核对本次调用用量。",
  ai_stream_owner_expired: "执行期限已过，仍没有可信的完成记录。结果与用量尚未确认；读取进度不会恢复模型调用。",
  ai_stream_start_failed: "分析任务未能可靠启动，尚未形成正式结果。请核对调用记录与用量；不会自动重试。",
  ai_stream_shutdown: "服务关闭时本次分析尚未完成，结果与用量仍需核对。不会自动重新调用模型。",
  ai_stream_invalid: "模型返回的流式内容无效，未形成正式分析，生成草稿已作废。不会自动重试；已有调用仍可能计费。",
  ai_stream_too_large: "模型输出超过允许的大小，未形成正式分析，生成草稿已作废。不会自动重试；已有调用仍可能计费。",
  ai_stream_cursor_reset_required: "进度读取位置已失效，请重新读取同一请求的已保存记录。这不会重新调用模型。",
  ai_stream_mode_conflict: "此请求标识属于已有的非流式分析。请从调用记录核对原结果；不能使用它新建流式调用。",
};

export function aiStreamErrorMessage(code: string): string {
  return aiStreamErrorMessages[code] || "本次分析未形成可确认的结果。请核对原调用记录与供应商用量；不会自动重新调用模型。";
}
