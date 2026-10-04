import type { ChangeItem, Evidence, Health, QuarantineEvidence, QuarantineRecord, QueryResult, Source, SourceHealthResult, SourceHealthTrends, AIUsageHistory, AuthState, AuthUser, AuthUserListItem, TireQuery, Variant, VehicleCandidate, VehicleFitmentResult, WatchItem } from "@tire/domain-types";
import type { ExcludedVariant, FactReview, FactRevisionRequest, LifecycleRequest, LifecycleReview, RawCaptureEvidence, RawCaptureRecord } from "@tire/domain-types";
import type { GarageDetail, GarageList, GarageProfile, GarageRecord } from "@tire/domain-types";
import type { ComparisonView, DrivingPreferenceState, DrivingWeights, SaveComparisonRequest, SavedComparisonDetail, SavedComparisonRecord } from "@tire/domain-types";
import type { AlertRuleCreate, AlertRuleDetail, AlertRuleRecord, AlertRuleSettings, LocalNotification } from "@tire/domain-types";
import type { EvidenceDocument, EvidenceDocumentMetadata } from "@tire/domain-types";
import { stringifyExactJson } from "./exact-json";
import { fallbackUUID } from "./device-fallback-values";
export * from "./exact-json";
export * from "./device-criteria";
export * from "./device-fallback-values";

export class ApiError extends Error {
  constructor(public readonly status: number, message: string, public readonly code?: string, public readonly runId?: string) { super(message); this.name = "ApiError"; }
}

/** A caller-observed transport failure, never a claim about a source receipt or HTTP status. */
export class ApiTransportError extends Error {
  readonly scope = "api_transport";
  constructor(public readonly code: "api_network_unavailable" | "api_timeout") {
    super(code === "api_timeout" ? "连接本机 API 超时；本次没有取得来源核验结果。" : "当前未能连接本机 API；本次没有取得来源核验结果。");
    this.name = "ApiTransportError";
  }
}

/** The path is API-relative; the host owns networking and session handling. */
export type ApiTransport = (path: string, init: RequestInit) => Promise<Response>;

const browserTransport: ApiTransport = async (path, init) => {
  const lifetime = new AbortController(); let timedOut = false;
  const cancel = () => lifetime.abort();
  init.signal?.addEventListener("abort", cancel, { once: true });
  if (init.signal?.aborted) cancel();
  const deadline = setTimeout(() => { timedOut = true; lifetime.abort(); }, 75_000);
  try { return await fetch(`/api${path}`, { ...init, signal: lifetime.signal }); }
  catch (cause) {
    if (init.signal?.aborted) throw new DOMException("请求已取消", "AbortError");
    if (timedOut) throw new ApiTransportError("api_timeout");
    // This boundary encloses fetch itself only. JSON parsing and HTTP errors
    // cannot be upgraded to transport failure by a message or status code.
    if (cause instanceof TypeError) throw new ApiTransportError("api_network_unavailable");
    throw cause;
  } finally { clearTimeout(deadline); init.signal?.removeEventListener("abort", cancel); }
};
let transport: ApiTransport = browserTransport;
let transportAuthorityEpoch = 0;
let observedSyncOwner: string | null = null;
export const apiTransportAuthorityEpoch = () => transportAuthorityEpoch;

type BrowserDenialCapture = (queryId: string, epoch: number) => Promise<() => Promise<void>>;
const browserDenialObservers = new Set<BrowserDenialCapture>();
/** Ledger identity only; preserve accepted intent, grant and HTTP query_id text. */
export const fallbackDenialQueryKey = (queryId: string): string => fallbackUUID(queryId) ? queryId.toLowerCase() : queryId;
/** Browser storage observes the existing owned HTTP exchange; native hosts observe it privately. */
export function observeBrowserFallbackDenials(capture: BrowserDenialCapture): () => void {
  browserDenialObservers.add(capture); return () => { browserDenialObservers.delete(capture); };
}

/** Install before mounting the workbench. Does not replace global fetch. */
export function setApiTransport(next: ApiTransport): () => void {
  const previous = transport;
  transport = next;
  transportAuthorityEpoch++;
  return () => { if (transport === next) { transport = previous; transportAuthorityEpoch++; } };
}

async function request<T>(path: string, init: RequestInit = {}, format: "json" | "blob" | "response" = "json"): Promise<T> {
  const headers = new Headers(init.headers);
  const syncOwner = headers.get("X-Tire-Offline-Expected-Owner"), syncEpoch = transportAuthorityEpoch;
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  let denialQuery: string | null = null;
  if (transport === browserTransport && path === "/v1/fallback-consents" && init.method === "POST" && typeof init.body === "string") {
    try { const body = JSON.parse(init.body); if (body.decision === "deny" && body.scope === "once" && typeof body.query_id === "string" && body.query_id.length > 0 && body.query_id.length <= 64 && !/[\r\n\0]/.test(body.query_id)) denialQuery = fallbackDenialQueryKey(body.query_id); } catch { /* Invalid requests do not create a host observation. */ }
  }
  const denialObservers = denialQuery ? await Promise.all([...browserDenialObservers].map(capture => capture(denialQuery!, syncEpoch))) : [];
  let response: Response;
  try {
    response = await transport(path, { ...init, credentials: "include", cache: "no-store", headers });
  } catch (cause) {
    if (init.signal?.aborted) throw cause;
    const code = cause && typeof cause === "object" && "code" in cause ? cause.code : null;
    if (code === "API_UNAVAILABLE" || code === "api_unavailable") throw new ApiTransportError("api_network_unavailable");
    if (code === "API_TIMEOUT" || code === "request_timeout") throw new ApiTransportError("api_timeout");
    throw cause;
  }
  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`;
    let code: string | undefined;
    let runId: string | undefined;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") detail = body.detail;
      else if (body && typeof body === "object" && "detail" in body && Array.isArray(body.detail)) {
        const messages = body.detail.slice(0, 3).filter((item): item is { msg: string } => !!item && typeof item.msg === "string").map(item => item.msg.replace(/^Value error, /, ""));
        if (messages.length) detail = messages.join("；");
      }
      else if (body && typeof body === "object" && "detail" in body && body.detail && typeof body.detail === "object") {
        if ("message" in body.detail && typeof body.detail.message === "string") detail = body.detail.message;
        if ("code" in body.detail && typeof body.detail.code === "string" && /^[a-z0-9_@.-]{1,100}$/i.test(body.detail.code)) code = body.detail.code;
        if ("run_id" in body.detail && typeof body.detail.run_id === "string" && /^[a-z0-9-]{1,64}$/i.test(body.detail.run_id)) runId = body.detail.run_id;
      }
    } catch { /* A proxy may return a non-JSON response. */ }
    throw new ApiError(response.status, detail, code, runId);
  }
  if (headers.get("X-Tire-Offline-Sync") === "1") {
    const owner = response.headers.get("X-Tire-Offline-Owner-Scope");
    if (owner && observedSyncOwner && owner !== observedSyncOwner) transportAuthorityEpoch++;
    if (owner) observedSyncOwner = owner;
    if (!syncOwner || !/^[a-f0-9]{64}$/.test(syncOwner) || owner !== syncOwner || transportAuthorityEpoch !== syncEpoch)
      throw new ApiError(409, "持续更新的在线归属已变化，请重新预览授权。", "SESSION_CHANGED");
  }
  if (response.status === 204) return undefined as T;
  if (format === "response") return response as T;
  if (format === "blob") return await response.blob() as T;
  const value = await response.json();
  if (denialQuery && response.status === 201 && value && typeof value === "object" && value.decision === "deny" && value.scope === "once" && typeof value.id === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value.id) && syncEpoch === transportAuthorityEpoch) {
    await Promise.all(denialObservers.map(observe => observe()));
  }
  return value as T;
}

const post = <T>(path: string, body: unknown, signal?: AbortSignal) => request<T>(path, { method: "POST", body: JSON.stringify(body), signal });
// Only this additive precise criteria path needs a lossless writer; generic HTTP budgets stay unchanged.
const postExactCriteria = <T>(path: string, body: unknown, signal?: AbortSignal) => request<T>(path, { method: "POST", body: stringifyExactJson(body, Number.MAX_SAFE_INTEGER), signal });
const syncHeaders = (owner: string) => {
  if (!/^[a-f0-9]{64}$/.test(owner)) throw new ApiError(400, "持续更新归属参数无效。", "OFFLINE_SYNC_INVALID");
  return { "X-Tire-Offline-Sync": "1", "X-Tire-Offline-Expected-Owner": owner };
};

type TaskStreamMessage = import("@tire/domain-types").MonitorTaskStreamMessage;
const taskKinds = new Set(["tire", "recall", "recall_discovery"]);
const taskPhases = new Set(["claimed", "running", "finished"]);
const taskOutcomes = new Set(["running", "succeeded", "failed", "blocked", "interrupted"]);
const boundedCursor = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 512 && !/[\r\n\0]/.test(value);
const stringOrNull = (value: unknown) => value === null || typeof value === "string";
export function isMonitorTaskEvent(value: unknown): value is import("@tire/domain-types").MonitorTaskEvent {
  if (!value || typeof value !== "object") return false;
  const event = value as Record<string, unknown>;
  return typeof event.id === "string" && !!event.id && typeof event.attempt_id === "string" && !!event.attempt_id
    && Number.isSafeInteger(event.sequence) && Number(event.sequence) > 0 && boundedCursor(event.cursor)
    && taskPhases.has(String(event.phase)) && taskOutcomes.has(String(event.state))
    && stringOrNull(event.result_state) && stringOrNull(event.reason) && stringOrNull(event.query_id) && stringOrNull(event.run_id)
    && typeof event.created_at === "string" && Number.isFinite(Date.parse(event.created_at));
}

/** Consume only the bounded task-events protocol. Never routes native IPC through an SSE bridge. */
export async function consumeMonitorTaskStream(response: Response, receive: (message: TaskStreamMessage) => void | Promise<void>, signal?: AbortSignal): Promise<"window_complete" | "reset"> {
  if (response.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "text/event-stream" || !response.body) throw new Error("任务进度响应格式不受支持。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const encoder = new TextEncoder();
  let buffer = "", eventType = "", eventId = "", data: string[] = [], frameBytes = 0;
  let ended: "window_complete" | "reset" | null = null;
  const abort = () => { void reader.cancel().catch(() => {}); };
  const throwIfAborted = () => { if (signal?.aborted) throw new DOMException("进度读取已取消。", "AbortError"); };
  signal?.addEventListener("abort", abort, { once: true });
  async function dispatch() {
    if (!data.length) { eventType = ""; eventId = ""; frameBytes = 0; return; }
    let value: Record<string, unknown>;
    try { value = JSON.parse(data.join("\n")); } catch { throw new Error("任务进度事件不是有效 JSON。"); }
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("任务进度事件格式不受支持。");
    let message: TaskStreamMessage;
    if (eventType === "task_event") {
      if (!isMonitorTaskEvent(value) || eventId !== value.cursor) throw new Error("任务事件与恢复游标不匹配。");
      message = { type: "task_event", data: value };
    } else if (eventType === "reset") {
      if (value.code !== "task_cursor_reset_required" || typeof value.server_time !== "string" || !Number.isFinite(Date.parse(value.server_time))) throw new Error("任务游标恢复指令无效。");
      message = { type: "reset", data: { code: "task_cursor_reset_required", server_time: value.server_time } }; ended = "reset";
    } else if (eventType === "heartbeat" || eventType === "stream_end") {
      if (!boundedCursor(value.cursor) || typeof value.server_time !== "string" || !Number.isFinite(Date.parse(value.server_time))) throw new Error("任务进度心跳格式不受支持。");
      if (eventType === "stream_end") {
        if (value.reason !== "window_complete") throw new Error("任务进度结束标记无效。");
        message = { type: "stream_end", data: { cursor: value.cursor, server_time: value.server_time, reason: "window_complete" } }; ended = "window_complete";
      } else message = { type: "heartbeat", data: { cursor: value.cursor, server_time: value.server_time } };
    } else throw new Error("任务进度事件类型不受支持。");
    throwIfAborted(); await receive(message); throwIfAborted();
    eventType = ""; eventId = ""; data = []; frameBytes = 0;
  }
  try {
    while (!ended) {
      throwIfAborted(); const { value, done } = await reader.read(); throwIfAborted();
      buffer += decoder.decode(value, { stream: !done });
      let newline: number;
      while (!ended && (newline = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, newline).replace(/\r$/, ""); buffer = buffer.slice(newline + 1);
        if (!line) { await dispatch(); continue; }
        frameBytes += encoder.encode(line).length;
        if (frameBytes > 65536) throw new Error("任务进度事件超过限制。");
        if (line.startsWith(":")) continue;
        const separator = line.indexOf(":");
        const field = separator < 0 ? line : line.slice(0, separator);
        const text = separator < 0 ? "" : line.slice(separator + 1).replace(/^ /, "");
        if (field === "data") data.push(text);
        else if (field === "event") eventType = text;
        else if (field === "id") { if (!boundedCursor(text)) throw new Error("任务恢复游标无效。"); eventId = text; }
      }
      // Network reads may coalesce hundreds of valid small frames. Bound the
      // unconsumed tail after parsing, not the transport's arbitrary chunk size.
      if (!ended && encoder.encode(buffer).length > 131072) throw new Error("任务进度缓冲区超过限制。");
      if (done) break;
    }
    if (!ended) throw new Error("任务进度连接已中断，最新状态未知。");
    return ended;
  } finally { signal?.removeEventListener("abort", abort); await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

function monitorTaskPath(kind: import("@tire/domain-types").MonitorTaskKind, jobId: string) {
  if (!taskKinds.has(kind) || !jobId) throw new Error("任务范围无效。");
  return `/v1/monitor-tasks/${kind}/${encodeURIComponent(jobId)}`;
}

const aiStreamStates = new Set(["accepted", "running", "completed", "failed", "outcome_unknown"]);
const aiTerminalStates = new Set(["completed", "failed", "outcome_unknown"]);
const aiTimestamp = (value: unknown): value is string => typeof value === "string" && Number.isFinite(Date.parse(value));
const aiObject = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
export function isAIClaim(value: unknown): value is import("@tire/domain-types").AIClaim {
  if (!aiObject(value)) return false;
  const references = (items: unknown, max: number) => Array.isArray(items) && items.length <= max && items.every(item => typeof item === "string" && !!item);
  return ["fact", "inference"].includes(String(value.type)) && typeof value.text === "string" && !!value.text.trim()
    && (value.type !== "inference" || Array.from(value.text).length <= 2000)
    && references(value.fact_ids, 24) && references(value.evidence_ids, 6)
    && new TextEncoder().encode(JSON.stringify(value)).length <= 65536;
}
function isAIStreamExecution(value: unknown): value is import("@tire/domain-types").AIStreamExecution {
  return aiObject(value) && aiStreamStates.has(String(value.state)) && value.terminal === aiTerminalStates.has(String(value.state))
    && aiTimestamp(value.deadline_at) && (value.last_event_at === null || aiTimestamp(value.last_event_at)) && typeof value.projection_only === "boolean";
}
function isAIDraft(value: unknown): value is import("@tire/domain-types").AIStreamDraftClaim {
  return aiObject(value) && Number.isInteger(value.index) && Number(value.index) >= 0 && Number(value.index) < 12 && isAIClaim(value.claim);
}
export function isAIStreamDetail(value: unknown, requestId?: string): value is import("@tire/domain-types").AIStreamDetail {
  if (!aiObject(value) || value.schema !== "ai-streams@1" || value.scope !== "session" || !isAIStreamExecution(value.execution)
    || !boundedCursor(value.cursor) || !aiTimestamp(value.server_time) || !aiObject(value.analysis)
    || typeof value.analysis.id !== "string" || !value.analysis.id || (requestId !== undefined && value.analysis.id !== requestId)
    || typeof value.analysis.pack_id !== "string" || typeof value.analysis.question !== "string"
    || !Array.isArray(value.draft_claims) || value.draft_claims.length > 12 || !value.draft_claims.every(isAIDraft)
    || new Set(value.draft_claims.map(row => row.index)).size !== value.draft_claims.length
    || !(value.draft_uncertainty === null || (typeof value.draft_uncertainty === "string" && Array.from(value.draft_uncertainty).length <= 2000))) return false;
  const state = value.execution.state;
  if (value.analysis.state !== (state === "accepted" || state === "running" ? "pending" : state)) return false;
  if (value.execution.terminal && (value.draft_claims.length || value.draft_uncertainty !== null)) return false;
  if (state !== "completed") return value.analysis.answer === null;
  const answer = value.analysis.answer;
  return aiObject(answer) && Array.isArray(answer.claims) && answer.claims.length <= 12 && answer.claims.every(isAIClaim)
    && typeof answer.uncertainty === "string" && typeof answer.notice === "string";
}
export function isAIStreamEvent(value: unknown, requestId?: string): value is import("@tire/domain-types").AIStreamEvent {
  if (!aiObject(value) || typeof value.id !== "string" || !value.id || typeof value.request_id !== "string" || !value.request_id
    || (requestId !== undefined && value.request_id !== requestId) || !Number.isSafeInteger(value.sequence) || Number(value.sequence) < 1
    || !boundedCursor(value.cursor) || !aiTimestamp(value.created_at) || !aiObject(value.payload)) return false;
  if (value.type === "accepted" || value.type === "started") return Object.keys(value.payload).length === 0;
  if (value.type === "claim_draft") return isAIDraft(value.payload);
  if (value.type === "uncertainty_draft") return typeof value.payload.text === "string" && Array.from(value.payload.text).length <= 2000;
  return aiTerminalStates.has(String(value.type)) && value.payload.state === value.type && stringOrNull(value.payload.error_code);
}
function checkedAIStreamDetail(value: unknown, requestId?: string) {
  if (!isAIStreamDetail(value, requestId)) throw new Error("AI 进度记录与当前请求不匹配或格式不完整。");
  return value;
}

/** Reads complete server-projected claims only; never exposes provider JSON fragments. */
export async function consumeAIStream(response: Response, requestId: string, receive: (message: import("@tire/domain-types").AIStreamMessage) => void | Promise<void>, signal?: AbortSignal): Promise<"window_complete" | "reset"> {
  if (response.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "text/event-stream" || !response.body) throw new Error("AI 进度响应格式不受支持。");
  const reader = response.body.getReader(), decoder = new TextDecoder("utf-8", { fatal: true }), encoder = new TextEncoder();
  let buffer = "", eventType = "", eventId = "", data: string[] = [], frameBytes = 0;
  let ended: "window_complete" | "reset" | null = null;
  const abort = () => { void reader.cancel().catch(() => {}); };
  const checkAbort = () => { if (signal?.aborted) throw new DOMException("已停止读取 AI 进度。", "AbortError"); };
  signal?.addEventListener("abort", abort, { once: true });
  async function dispatch() {
    if (!data.length) { eventType = ""; eventId = ""; frameBytes = 0; return; }
    let value: unknown;
    try { value = JSON.parse(data.join("\n")); } catch { throw new Error("AI 进度事件不是完整 JSON。"); }
    if (!aiObject(value)) throw new Error("AI 进度事件格式不受支持。");
    let message: import("@tire/domain-types").AIStreamMessage;
    if (eventType === "ai_event") {
      if (!isAIStreamEvent(value, requestId) || eventId !== value.cursor) throw new Error("AI 事件与当前请求或恢复游标不匹配。");
      message = { type: "ai_event", data: value };
    } else if (eventType === "reset") {
      if (value.code !== "ai_stream_cursor_reset_required" || !aiTimestamp(value.server_time)) throw new Error("AI 游标恢复指令无效。");
      message = { type: "reset", data: { code: "ai_stream_cursor_reset_required", server_time: value.server_time } }; ended = "reset";
    } else if (eventType === "heartbeat" || eventType === "stream_end") {
      if (!boundedCursor(value.cursor) || !aiTimestamp(value.server_time)) throw new Error("AI 进度心跳格式不受支持。");
      if (eventType === "stream_end") {
        if (value.reason !== "window_complete") throw new Error("AI 进度窗口结束标记无效。");
        message = { type: "stream_end", data: { cursor: value.cursor, server_time: value.server_time, reason: "window_complete" } }; ended = "window_complete";
      } else message = { type: "heartbeat", data: { cursor: value.cursor, server_time: value.server_time } };
    } else throw new Error("AI 进度事件类型不受支持。");
    checkAbort(); await receive(message); checkAbort();
    eventType = ""; eventId = ""; data = []; frameBytes = 0;
  }
  try {
    while (!ended) {
      checkAbort(); const { value, done } = await reader.read(); checkAbort(); buffer += decoder.decode(value, { stream: !done });
      let newline: number;
      while (!ended && (newline = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, newline).replace(/\r$/, ""); buffer = buffer.slice(newline + 1);
        if (!line) { await dispatch(); continue; }
        frameBytes += encoder.encode(line).length;
        if (frameBytes > 131072) throw new Error("AI 进度事件超过限制。");
        if (line.startsWith(":")) continue;
        const separator = line.indexOf(":"), field = separator < 0 ? line : line.slice(0, separator);
        const text = separator < 0 ? "" : line.slice(separator + 1).replace(/^ /, "");
        if (field === "data") data.push(text);
        else if (field === "event") eventType = text;
        else if (field === "id") { if (!boundedCursor(text)) throw new Error("AI 恢复游标无效。"); eventId = text; }
      }
      if (!ended && encoder.encode(buffer).length > 262144) throw new Error("AI 进度缓冲区超过限制。");
      if (done) break;
    }
    if (!ended) throw new Error("AI 进度连接中断，当前调用结果尚未确认。");
    return ended;
  } finally { signal?.removeEventListener("abort", abort); await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

function aiStreamPath(id: string) { return `/v1/ai/analysis-streams/${encodeURIComponent(id)}`; }

export const tireApi = {
  previewQueryFallbackPolicy: (payload: import("@tire/domain-types").WarehouseFallbackPolicyPreviewRequest, signal?: AbortSignal) => post<import("@tire/domain-types").WarehouseFallbackPolicyPreview>("/v1/query-fallback-policies:preview", payload, signal),
  applyQueryFallbackPolicy: (payload: import("@tire/domain-types").WarehouseFallbackPolicyApplyRequest, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").WarehouseFallbackPolicy>("/v1/query-fallback-policies:apply", { method: "POST", headers: { "Idempotency-Key": key }, body: stringifyExactJson(payload), signal }),
  queryFallbackPolicies: (offset = 0, signal?: AbortSignal) => request<import("@tire/domain-types").WarehouseFallbackPolicyList>(`/v1/query-fallback-policies?${new URLSearchParams({ limit: "16", offset: String(offset) })}`, { signal }),
  pauseQueryFallbackPolicy: (id: string, expectedRevision: number, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").WarehouseFallbackPolicy>(`/v1/query-fallback-policies/${encodeURIComponent(id)}:pause`, { method: "POST", headers: { "Idempotency-Key": key }, body: stringifyExactJson({ expected_revision: expectedRevision }), signal }),
  revokeQueryFallbackPolicy: (id: string, expectedRevision: number, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").WarehouseFallbackPolicy>(`/v1/query-fallback-policies/${encodeURIComponent(id)}:revoke`, { method: "POST", headers: { "Idempotency-Key": key }, body: stringifyExactJson({ expected_revision: expectedRevision }), signal }),
  offlinePlanV2: (payload: import("@tire/domain-types").OfflinePlanRequestV2, signal?: AbortSignal) => post<import("@tire/domain-types").AnyOfflinePlan>("/v1/offline-pack-plans", payload, signal),
  offlineSyncPrepareV2: (payload: import("@tire/domain-types").OfflinePackUpdateRequestV2, owner: string, signal?: AbortSignal) => request<import("@tire/domain-types").OfflinePackUpdate | import("@tire/domain-types").OfflinePackUpdateV2>("/v1/offline-pack-updates:prepare", { method: "POST", headers: syncHeaders(owner), body: stringifyExactJson(payload), signal }),
  /** Fixed metadata observation. The host still owns the same-session and store CAS fences. */
  fallbackSourceSettings: async (signal?: AbortSignal) => {
    const epoch = transportAuthorityEpoch, response = await request<Response>("/v1/source-settings", { signal }, "response");
    const owner_scope_id = response.headers.get("X-Tire-Offline-Owner-Scope");
    if (!owner_scope_id || !/^[a-f0-9]{64}$/.test(owner_scope_id) || epoch !== transportAuthorityEpoch) throw new ApiError(409, "来源归属无法确认，请重新读取。", "SESSION_CHANGED");
    return { catalog: await response.json() as import("@tire/domain-types").SourceSettingCatalog, owner_scope_id, transport_epoch: epoch };
  },
  offlinePlan: (payload: import("@tire/domain-types").OfflinePlanRequest, signal?: AbortSignal) => post<import("@tire/domain-types").OfflinePlan>("/v1/offline-pack-plans", payload, signal),
  offlineSyncPrepare: (payload: import("@tire/domain-types").OfflinePackUpdateRequest, owner: string, signal?: AbortSignal) => request<import("@tire/domain-types").OfflinePackUpdate>("/v1/offline-pack-updates:prepare", { method: "POST", headers: syncHeaders(owner), body: JSON.stringify(payload), signal }),
  offlineSyncConfirm: (payload: import("@tire/domain-types").OfflineConfirmRequest, key: string, owner: string, signal?: AbortSignal) => request<import("@tire/domain-types").AnyOfflinePackDescriptor>("/v1/offline-packs", { method: "POST", headers: { ...syncHeaders(owner), "Idempotency-Key": key }, body: JSON.stringify(payload), signal }),
  offlineSyncPack: (id: string, owner: string, signal?: AbortSignal) => request<import("@tire/domain-types").AnyOfflinePackDescriptor>(`/v1/offline-packs/${encodeURIComponent(id)}?mode=history`, { headers: syncHeaders(owner), signal }),
  offlineSyncBytes: (id: string, owner: string, signal?: AbortSignal) => request<Response>(`/v1/offline-packs/${encodeURIComponent(id)}/download?mode=history`, { headers: syncHeaders(owner), signal }, "response"),
  offlinePlanDetail: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").AnyOfflinePlan>(`/v1/offline-pack-plans/${encodeURIComponent(id)}?mode=history`, { signal }),
  confirmOfflinePack: (payload: import("@tire/domain-types").OfflineConfirmRequest, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").AnyOfflinePackDescriptor>("/v1/offline-packs", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal }),
  offlinePacks: (signal?: AbortSignal) => request<{ items: import("@tire/domain-types").AnyOfflinePackDescriptor[] }>("/v1/offline-packs?mode=history&limit=50", { signal }),
  offlinePack: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").AnyOfflinePackDescriptor>(`/v1/offline-packs/${encodeURIComponent(id)}?mode=history`, { signal }),
  offlinePackBytes: (id: string, signal?: AbortSignal) => request<Response>(`/v1/offline-packs/${encodeURIComponent(id)}/download?mode=history`, { signal }, "response"),
  startAIStream: async (payload: { pack_id: string; question: string; allow_external_processing: boolean }, key: string, signal?: AbortSignal) => {
    const result = await request<unknown>("/v1/ai/analysis-streams", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal });
    const detail = checkedAIStreamDetail(result);
    if (!("replayed" in detail) || typeof detail.replayed !== "boolean") throw new Error("AI 受理结果缺少同请求核对信息。");
    return detail as import("@tire/domain-types").AIStreamAcceptance;
  },
  aiStream: async (id: string, signal?: AbortSignal) => checkedAIStreamDetail(await request<unknown>(`${aiStreamPath(id)}?mode=history`, { signal }), id),
  lookupAIStream: async (key: string, signal?: AbortSignal) => checkedAIStreamDetail(await request<unknown>(`/v1/ai/analysis-streams/lookup?${new URLSearchParams({ mode: "history", idempotency_key: key })}`, { signal })),
  aiStreamEvents: async (id: string, cursor: string, signal?: AbortSignal) => {
    const value = await request<import("@tire/domain-types").AIStreamEvents>(`${aiStreamPath(id)}/events?${new URLSearchParams({ cursor, limit: "50" })}`, { signal });
    if (!value || value.schema !== "ai-streams@1" || value.scope !== "session" || value.request_id !== id || !Array.isArray(value.items)
      || !value.items.every(event => isAIStreamEvent(event, id)) || !boundedCursor(value.next_cursor) || !boundedCursor(value.latest_cursor)
      || value.next_cursor !== (value.items.at(-1)?.cursor || cursor) || typeof value.has_more !== "boolean" || (value.has_more && value.next_cursor === cursor)
      || !isAIStreamExecution(value.execution) || !aiTimestamp(value.server_time)) throw new Error("AI 事件页与当前请求不匹配。");
    return value;
  },
  streamAIEvents: async (id: string, cursor: string, receive: (message: import("@tire/domain-types").AIStreamMessage) => void | Promise<void>, signal?: AbortSignal) => {
    const response = await request<Response>(`${aiStreamPath(id)}/events/stream?${new URLSearchParams({ cursor })}`, { signal, headers: { Accept: "text/event-stream" } }, "response");
    return consumeAIStream(response, id, receive, signal);
  },
  monitorTasks: (filters: import("@tire/domain-types").MonitorTaskFilters = {}, offset = 0, signal?: AbortSignal) => {
    const query = new URLSearchParams({ offset: String(offset), limit: "20" });
    for (const key of ["kind", "source_id", "rule_id", "state"] as const) if (filters[key]) query.set(key, filters[key]!);
    return request<import("@tire/domain-types").MonitorTaskList>(`/v1/monitor-tasks?${query}`, { signal });
  },
  monitorTask: (kind: import("@tire/domain-types").MonitorTaskKind, jobId: string, page: { attemptOffset?: number; legacyOffset?: number } = {}, signal?: AbortSignal) => request<import("@tire/domain-types").MonitorTaskDetail>(`${monitorTaskPath(kind, jobId)}?${new URLSearchParams({ attempt_offset: String(page.attemptOffset || 0), attempt_limit: "20", legacy_offset: String(page.legacyOffset || 0), legacy_limit: "20" })}`, { signal }),
  monitorTaskEvents: (kind: import("@tire/domain-types").MonitorTaskKind, jobId: string, cursor: string, signal?: AbortSignal) => request<import("@tire/domain-types").MonitorTaskEvents>(`${monitorTaskPath(kind, jobId)}/events?${new URLSearchParams({ cursor, limit: "50" })}`, { signal }),
  streamMonitorTaskEvents: async (kind: import("@tire/domain-types").MonitorTaskKind, jobId: string, cursor: string, receive: (message: TaskStreamMessage) => void | Promise<void>, signal?: AbortSignal) => {
    const response = await request<Response>(`${monitorTaskPath(kind, jobId)}/events/stream?${new URLSearchParams({ cursor })}`, { signal, headers: { Accept: "text/event-stream" } }, "response");
    return consumeMonitorTaskStream(response, receive, signal);
  },
  fieldPolicies: (signal?: AbortSignal) => request<import("@tire/domain-types").FieldPolicyCatalog>("/v1/field-policies", { signal }),
  fieldConflicts: (filters: { field?: string; source_id?: string } = {}, offset = 0, signal?: AbortSignal) => request<import("@tire/domain-types").FieldConflictPage>(`/v1/field-conflicts?mode=history&offset=${offset}&limit=20${filters.field ? `&field=${encodeURIComponent(filters.field)}` : ""}${filters.source_id ? `&source_id=${encodeURIComponent(filters.source_id)}` : ""}`, { signal }),
  fieldResolution: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").FieldResolution>(`/v1/tire-variants/${encodeURIComponent(id)}/field-resolution?mode=history`, { signal }),
  identityMigrationPreview: (signal?: AbortSignal) => request<import("@tire/domain-types").IdentityMigrationPreview>("/v1/identity-contract/migration-preview?mode=history", { signal }),
  applyIdentityMigration: (payload: import("@tire/domain-types").IdentityMigrationApply, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").IdentityMigrationApplication>("/v1/identity-contract/migration-applications", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal }),
  identityMigrationApplications: (offset = 0, signal?: AbortSignal) => request<import("@tire/domain-types").ParserPage<import("@tire/domain-types").IdentityMigrationApplication>>(`/v1/identity-contract/migration-applications?mode=history&offset=${offset}&limit=10`, { signal }),
  identityMigrationApplication: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").IdentityMigrationApplication>(`/v1/identity-contract/migration-applications/${encodeURIComponent(id)}?mode=history`, { signal }),
  goldenCases: (source: string, signal?: AbortSignal, offset = 0) => request<import("@tire/domain-types").ParserPage<import("@tire/domain-types").GoldenCaseSummary>>(`/v1/golden/cases?mode=history&source_id=${encodeURIComponent(source)}&offset=${offset}&limit=10`, { signal }),
  goldenCase: (id: string, signal?: AbortSignal, revision?: number) => request<import("@tire/domain-types").GoldenCase>(`/v1/golden/cases/${encodeURIComponent(id)}?mode=history${revision === undefined ? "" : `&revision=${revision}`}`, { signal }),
  createGoldenCase: (payload: import("@tire/domain-types").GoldenCaseCreate, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").GoldenCase>("/v1/golden/cases", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal }),
  reviseGoldenCase: (id: string, payload: import("@tire/domain-types").GoldenCaseEdit, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").GoldenCase>(`/v1/golden/cases/${encodeURIComponent(id)}/revisions`, { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal }),
  reviewGoldenCase: (id: string, payload: import("@tire/domain-types").GoldenCaseReviewRequest, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").GoldenCase>(`/v1/golden/cases/${encodeURIComponent(id)}/reviews`, { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal }),
  goldenSets: (source: string, signal?: AbortSignal, offset = 0) => request<import("@tire/domain-types").ParserPage<import("@tire/domain-types").GoldenSet>>(`/v1/golden/sets?mode=history&source_id=${encodeURIComponent(source)}&offset=${offset}&limit=10`, { signal }),
  goldenSet: (id: string, signal?: AbortSignal, revision?: number) => request<import("@tire/domain-types").GoldenSet>(`/v1/golden/sets/${encodeURIComponent(id)}?mode=history${revision === undefined ? "" : `&revision=${revision}`}`, { signal }),
  createGoldenSet: (payload: import("@tire/domain-types").GoldenSetCreate, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").GoldenSet>("/v1/golden/sets", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal }),
  reviseGoldenSet: (id: string, payload: import("@tire/domain-types").GoldenSetRevision, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").GoldenSet>(`/v1/golden/sets/${encodeURIComponent(id)}/revisions`, { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal }),
  fitmentVehicleSnapshots: (vehicleId: string, offset = 0, signal?: AbortSignal) => request<import("@tire/domain-types").FitmentRelationPage<import("@tire/domain-types").FitmentVehicleSnapshot>>(`/v1/fitment-relations/vehicle-snapshots?mode=history&offset=${offset}&limit=20${vehicleId ? `&vehicle_id=${encodeURIComponent(vehicleId)}` : ""}`, { signal }),
  fitmentVehicleSnapshot: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").FitmentVehicleSnapshotDetail>(`/v1/fitment-relations/vehicle-snapshots/${encodeURIComponent(id)}?mode=history`, { signal }),
  fitmentTireEvidence: (variantId: string, offset = 0, signal?: AbortSignal) => request<import("@tire/domain-types").FitmentTireEvidencePage>(`/v1/fitment-relations/tire-evidence/${encodeURIComponent(variantId)}?mode=history&offset=${offset}&limit=20`, { signal }),
  fitmentRelations: (filters: { vehicle_id?: string; axle?: "front" | "rear"; state?: import("@tire/domain-types").FitmentRelationState }, offset = 0, signal?: AbortSignal) => request<import("@tire/domain-types").FitmentRelationPage<import("@tire/domain-types").FitmentRelation>>(`/v1/fitment-relations?mode=history&offset=${offset}&limit=20${Object.entries(filters).filter(([, value]) => value).map(([key, value]) => `&${key}=${encodeURIComponent(value!)}`).join("")}`, { signal }),
  fitmentRelation: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").FitmentRelationDetail>(`/v1/fitment-relations/${encodeURIComponent(id)}?mode=history`, { signal }),
  fitmentRelationPreview: (payload: import("@tire/domain-types").FitmentRelationPreviewRequest, signal?: AbortSignal) => post<import("@tire/domain-types").FitmentRelationPreview>("/v1/fitment-relations/preview", payload, signal),
  reviseFitmentRelation: (payload: import("@tire/domain-types").FitmentRelationDecision, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").FitmentRelationDecisionResult>("/v1/fitment-relations/revisions", { method: "POST", body: JSON.stringify(payload), headers: { "Idempotency-Key": key }, signal }),
  searchRecalls: (query: import("@tire/domain-types").RecallSearchQuery, signal?: AbortSignal, consentId?: string) => post<import("@tire/domain-types").RecallSearchResult>("/v1/recalls/search", { query, fallback_policy: "ask", ...(consentId ? { consent_id: consentId } : {}) }, signal),
  recallSearchHistory: (query: import("@tire/domain-types").RecallSearchQuery, signal?: AbortSignal) => request<import("@tire/domain-types").RecallSearchResult>(`/v1/recalls/search-history?mode=history&search=${encodeURIComponent(query.search)}&offset=${query.offset}`, { signal }),
  recallSearchEvidence: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").RecallSearchEvidence>(`/v1/recall-search-evidence/${encodeURIComponent(id)}?mode=history`, { signal }),
  liveRecall: (query: import("@tire/domain-types").RecallQuery, signal?: AbortSignal, consentId?: string) => post<import("@tire/domain-types").RecallResult>("/v1/recalls/live-query", { query, fallback_policy: "ask", ...(consentId ? { consent_id: consentId } : {}) }, signal),
  recallHistory: (campaign: string, signal?: AbortSignal) => request<import("@tire/domain-types").RecallHistory>(`/v1/recalls/${encodeURIComponent(campaign)}/history?mode=history`, { signal }),
  recallEvidence: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").RecallEvidence>(`/v1/recall-evidence/${encodeURIComponent(id)}?mode=history`, { signal }),
  recallRules: (signal?: AbortSignal, offset = 0, archived = false) => request<import("@tire/domain-types").RecallPage<import("@tire/domain-types").RecallRule>>(`/v1/recall-monitor-rules?mode=history&offset=${offset}&limit=10&archived=${archived}`, { signal }),
  recallRule: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").RecallRuleDetail>(`/v1/recall-monitor-rules/${encodeURIComponent(id)}?mode=history`, { signal }),
  createRecallRule: (query: import("@tire/domain-types").RecallQuery, settings: Omit<import("@tire/domain-types").RecallRuleSettings, "archived">, signal?: AbortSignal) => post<import("@tire/domain-types").RecallRule>("/v1/recall-monitor-rules", { query, ...settings }, signal),
  reviseRecallRule: (id: string, revision: number, settings: import("@tire/domain-types").RecallRuleSettings, signal?: AbortSignal) => post<import("@tire/domain-types").RecallRule>(`/v1/recall-monitor-rules/${encodeURIComponent(id)}/revisions`, { expected_revision: revision, ...settings }, signal),
  recallNotifications: (signal?: AbortSignal, offset = 0) => request<import("@tire/domain-types").RecallPage<import("@tire/domain-types").RecallNotification>>(`/v1/recall-notifications?mode=history&offset=${offset}&limit=10`, { signal }),
  markRecallNotification: (id: string, read: boolean, signal?: AbortSignal) => request<{ id: string; read_at: string | null }>(`/v1/recall-notifications/${encodeURIComponent(id)}/read`, { method: "PUT", body: JSON.stringify({ read }), signal }),
  discoveryRules: (archived = false, offset = 0, signal?: AbortSignal) => request<import("@tire/domain-types").RecallDiscoveryList<import("@tire/domain-types").RecallDiscoveryRule>>(`/v1/recall-discovery-rules?archived=${archived}&offset=${offset}&limit=20`, { signal }),
  discoveryRule: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").RecallDiscoveryRuleDetail>(`/v1/recall-discovery-rules/${encodeURIComponent(id)}?mode=history`, { signal }),
  createDiscoveryRule: (query: import("@tire/domain-types").RecallDiscoveryQuery, settings: Omit<import("@tire/domain-types").RecallDiscoveryRuleSettings, "archived">, signal?: AbortSignal, key?: string) => request<import("@tire/domain-types").RecallDiscoveryRuleWrite>("/v1/recall-discovery-rules", { method: "POST", body: JSON.stringify({ query, ...settings }), signal, ...(key ? { headers: { "Idempotency-Key": key } } : {}) }),
  reviseDiscoveryRule: (id: string, revision: number, settings: import("@tire/domain-types").RecallDiscoveryRuleSettings, signal?: AbortSignal, key?: string) => request<import("@tire/domain-types").RecallDiscoveryRuleWrite>(`/v1/recall-discovery-rules/${encodeURIComponent(id)}/revisions`, { method: "POST", body: JSON.stringify({ expected_revision: revision, ...settings }), signal, ...(key ? { headers: { "Idempotency-Key": key } } : {}) }),
  discoveryRuns: (jobId: string, offset = 0, signal?: AbortSignal) => request<import("@tire/domain-types").RecallDiscoveryList<import("@tire/domain-types").RecallDiscoveryRun>>(`/v1/recall-discovery-runs?${new URLSearchParams({ job_id: jobId, mode: "history", offset: String(offset), limit: "20" })}`, { signal }),
  discoveryRun: (id: string, pageOffset = 0, signal?: AbortSignal) => request<import("@tire/domain-types").RecallDiscoveryRunDetail>(`/v1/recall-discovery-runs/${encodeURIComponent(id)}?mode=history&page_offset=${pageOffset}&page_limit=20`, { signal }),
  discoveryNotifications: (unreadOnly = false, offset = 0, signal?: AbortSignal) => request<import("@tire/domain-types").RecallDiscoveryList<import("@tire/domain-types").RecallDiscoveryNotification>>(`/v1/recall-discovery-notifications?unread_only=${unreadOnly}&offset=${offset}&limit=20`, { signal }),
  markDiscoveryNotification: (id: string, read: boolean, signal?: AbortSignal) => post<{ id: string; read_at: string | null }>(`/v1/recall-discovery-notifications/${encodeURIComponent(id)}/read`, { read }, signal),
  identityReview: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").IdentityReview>(`/v1/tire-variants/${encodeURIComponent(id)}/identity-resolution?mode=history`, { signal }),
  identityCandidates: (q: string, offset: number, signal?: AbortSignal) => request<import("@tire/domain-types").IdentityCandidates>(`/v1/identity-candidates?mode=history&q=${encodeURIComponent(q)}&offset=${offset}`, { signal }),
  identityPreview: (id: string, target: string | null, signal?: AbortSignal) => post<import("@tire/domain-types").IdentityPreview>(`/v1/tire-variants/${encodeURIComponent(id)}/identity-preview`, { mode: "history", target_id: target }, signal),
  identityDecision: (id: string, payload: import("@tire/domain-types").IdentityDecision, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").IdentityDecisionResult>(`/v1/tire-variants/${encodeURIComponent(id)}/identity-revisions`, { method: "POST", body: JSON.stringify(payload), headers: { "Idempotency-Key": key }, signal }),
  reparseCatalog: (signal?: AbortSignal, bundleId?: string) => request<import("@tire/domain-types").ReparseCatalog>(`/v1/reparse/catalog?mode=history${bundleId ? `&bundle_id=${encodeURIComponent(bundleId)}` : ""}`, { signal }),
  parserBundles: (signal?: AbortSignal, offset = 0) => request<import("@tire/domain-types").ParserPage<import("@tire/domain-types").ParserBundle>>(`/v1/parser-bundles?mode=history&offset=${offset}&limit=10`, { signal }),
  parserDeployment: (source: string, signal?: AbortSignal) => request<import("@tire/domain-types").ParserDeployment>(`/v1/parser-deployments/${encodeURIComponent(source)}?mode=history`, { signal }),
  bootstrapParser: (source: string, payload: import("@tire/domain-types").ParserSignedAction, signal?: AbortSignal) => post<import("@tire/domain-types").ParserDeploymentRevision>(`/v1/parser-deployments/${encodeURIComponent(source)}/bootstrap`, payload, signal),
  parserCaptures: (source: string, signal?: AbortSignal, offset = 0) => request<import("@tire/domain-types").ParserPage<RawCaptureRecord>>(`/v1/captures?mode=history&source_id=${encodeURIComponent(source)}&offset=${offset}&limit=10`, { signal }),
  parserEvaluations: (source: string, signal?: AbortSignal, offset = 0) => request<import("@tire/domain-types").ParserPage<import("@tire/domain-types").ParserEvaluation>>(`/v1/parser-evaluations?mode=history&source_id=${encodeURIComponent(source)}&offset=${offset}&limit=10`, { signal }),
  parserEvaluation: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").ParserEvaluation>(`/v1/parser-evaluations/${encodeURIComponent(id)}?mode=history`, { signal }),
  evaluateParser: (payload: import("@tire/domain-types").ParserEvaluationCreate, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").ParserEvaluation>("/v1/parser-evaluations", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal }),
  reviewParser: (id: string, payload: import("@tire/domain-types").ParserEvaluationReviewCreate, signal?: AbortSignal) => post<import("@tire/domain-types").ParserEvaluation>(`/v1/parser-evaluations/${encodeURIComponent(id)}/reviews`, payload, signal),
  transitionParser: (source: string, payload: import("@tire/domain-types").ParserTransition, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").ParserDeploymentRevision>(`/v1/parser-deployments/${encodeURIComponent(source)}/transitions`, { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal }),
  createReparse: (payload: import("@tire/domain-types").ReparseCreate, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").ReparseDetail>("/v1/reparse/runs", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal }),
  reparses: (captureId: string, signal?: AbortSignal, offset = 0) => request<import("@tire/domain-types").ReparseList>(`/v1/reparse/runs?mode=history&capture_id=${encodeURIComponent(captureId)}&offset=${offset}&limit=10`, { signal }),
  reparse: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").ReparseDetail>(`/v1/reparse/runs/${encodeURIComponent(id)}?mode=history`, { signal }),
  reviewReparse: (id: string, payload: import("@tire/domain-types").ReparseReviewRequest, signal?: AbortSignal) => post<import("@tire/domain-types").ReparseDetail>(`/v1/reparse/runs/${encodeURIComponent(id)}/reviews`, payload, signal),
  createReport: (payload: import("@tire/domain-types").ReportCreate, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").EvidenceReportDetail>("/v1/reports", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal }),
  reports: (archived: boolean, signal?: AbortSignal, offset = 0) => request<import("@tire/domain-types").EvidenceReportList>(`/v1/reports?mode=history&archived=${archived}&offset=${offset}`, { signal }),
  report: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").EvidenceReportDetail>(`/v1/reports/${encodeURIComponent(id)}?mode=history`, { signal }),
  editReport: (id: string, revision: number, title: string, notes: string, signal?: AbortSignal) => request<import("@tire/domain-types").EvidenceReportDetail>(`/v1/reports/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ expected_revision: revision, title, notes }), signal }),
  reportState: (id: string, revision: number, action: "archive" | "restore", signal?: AbortSignal) => post<import("@tire/domain-types").EvidenceReportDetail>(`/v1/reports/${encodeURIComponent(id)}/state`, { expected_revision: revision, action }, signal),
  exportReport: (id: string, revision: number, format: import("@tire/domain-types").ReportFormat, signal?: AbortSignal) => post<import("@tire/domain-types").ReportExport>(`/v1/reports/${encodeURIComponent(id)}/exports`, { revision, format }, signal),
  reportExportContent: (id: string, exportId: string, revision: number, signal?: AbortSignal) => request<Blob>(`/v1/reports/${encodeURIComponent(id)}/exports/${encodeURIComponent(exportId)}/content?mode=history&revision=${revision}`, { signal }, "blob"),
  vectorStatus: (signal?: AbortSignal) => request<import("@tire/domain-types").VectorStatus>("/v1/knowledge/vector-status", { signal }),
  embeddingPlan: (documentIds: string[], signal?: AbortSignal) => post<import("@tire/domain-types").EmbeddingPlan>("/v1/knowledge/embedding-plans", { document_ids: documentIds }, signal),
  runEmbedding: (planId: string, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").EmbeddingRun>("/v1/knowledge/embedding-runs", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify({ plan_id: planId, allow_external_processing: true }), signal }),
  hybridSearch: (search: import("@tire/domain-types").KnowledgeSearchRequest, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").EmbeddingRun>("/v1/knowledge/hybrid-search", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify({ search, allow_external_processing: true }), signal }),
  embeddingRun: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").EmbeddingRun>(`/v1/knowledge/embedding-runs/${encodeURIComponent(id)}?mode=history`, { signal }),
  embeddingHistory: (signal?: AbortSignal) => request<{ items: import("@tire/domain-types").EmbeddingRun[] }>("/v1/knowledge/embedding-runs?mode=history", { signal }),
  searchKnowledge: (payload: import("@tire/domain-types").KnowledgeSearchRequest, signal?: AbortSignal) => post<import("@tire/domain-types").KnowledgeSearchResult>("/v1/knowledge/search", payload, signal),
  aiStatus: (signal?: AbortSignal) => request<import("@tire/domain-types").AIStatus>("/v1/ai/status", { signal }),
  authMe: (signal?: AbortSignal) => request<AuthState>("/v1/auth/me", { signal }),
  authRegister: (payload: { username: string; password: string; display_name?: string }, signal?: AbortSignal) => post<AuthState>("/v1/auth/register", payload, signal),
  authLogin: (payload: { username: string; password: string }, signal?: AbortSignal) => post<AuthState>("/v1/auth/login", payload, signal),
  authLogout: (signal?: AbortSignal) => post<AuthState>("/v1/auth/logout", {}, signal),
  authUsers: (signal?: AbortSignal) => request<{ items: AuthUserListItem[] }>("/v1/auth/users", { signal }),
  authSetRole: (userId: string, isAdmin: boolean, signal?: AbortSignal) => post<AuthUser>(`/v1/auth/users/${encodeURIComponent(userId)}/role`, { is_admin: isAdmin }, signal),
  authResetPassword: (userId: string, newPassword: string, signal?: AbortSignal) => post<{ id: string }>(`/v1/auth/users/${encodeURIComponent(userId)}/password`, { new_password: newPassword }, signal),
  prepareAI: (payload: import("@tire/domain-types").AIPrepareRequest, signal?: AbortSignal) => post<{ pack: import("@tire/domain-types").AIPack | null; query_result: QueryResult | import("@tire/domain-types").RecallResult | null; reason: string | null }>("/v1/ai/evidence-packs", payload, signal),
  analyzeAI: (payload: { pack_id: string; question: string; allow_external_processing: boolean }, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").AIAnalysis>("/v1/ai/analyses", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal }),
  aiHistory: (signal?: AbortSignal) => request<{ items: import("@tire/domain-types").AIAnalysis[] }>("/v1/ai/analyses?mode=history", { signal }),
  aiAnalysis: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").AIAnalysis>(`/v1/ai/analyses/${encodeURIComponent(id)}?mode=history`, { signal }),
  prepareRuleDraft: (sourceId: string, instruction: string, signal?: AbortSignal) => post<import("@tire/domain-types").AIRuleDraftPack>("/v1/ai/rule-draft-packs", { source_id: sourceId, instruction }, signal),
  generateRuleDraft: (packId: string, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").AIRuleDraftRun>("/v1/ai/rule-drafts", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify({ pack_id: packId, allow_external_processing: true }), signal }),
  ruleDraftHistory: (signal?: AbortSignal) => request<{ items: import("@tire/domain-types").AIRuleDraftRun[] }>("/v1/ai/rule-drafts?mode=history", { signal }),
  ruleDraft: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").AIRuleDraftRun>(`/v1/ai/rule-drafts/${encodeURIComponent(id)}?mode=history`, { signal }),
  applyRuleDraft: (id: string, rule: AlertRuleCreate, key: string, signal?: AbortSignal) => request<AlertRuleRecord>(`/v1/ai/rule-drafts/${encodeURIComponent(id)}/apply`, { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify({ rule, acknowledged: true }), signal }),
  documents: (signal?: AbortSignal, offset = 0) => request<{ items: EvidenceDocument[]; total: number; storage_backend: string }>(`/v1/documents?mode=history&offset=${offset}`, { signal }),
  uploadDocument: (metadata: EvidenceDocumentMetadata, file: File, signal?: AbortSignal) => request<EvidenceDocument>("/v1/documents", { method: "POST", body: file, signal, headers: { "Content-Type": "application/pdf", "X-Evidence-Metadata": btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(metadata)))) } }),
  documentContent: (id: string, signal?: AbortSignal) => request<Blob>(`/v1/documents/${encodeURIComponent(id)}/content?mode=history`, { signal }, "blob"),
  alertRules: (archived: boolean, signal?: AbortSignal, offset = 0) => request<{ items: AlertRuleRecord[]; total: number }>(`/v1/alert-rules?archived=${archived}&offset=${offset}`, { signal }),
  alertRule: (id: string, signal?: AbortSignal) => request<AlertRuleDetail>(`/v1/alert-rules/${encodeURIComponent(id)}?mode=history`, { signal }),
  createAlertRule: (payload: AlertRuleCreate, signal?: AbortSignal) => post<AlertRuleRecord>("/v1/alert-rules", payload, signal),
  editAlertRule: (id: string, revision: number, payload: AlertRuleSettings, signal?: AbortSignal) => request<AlertRuleRecord>(`/v1/alert-rules/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ ...payload, expected_revision: revision }), signal }),
  alertRuleState: (id: string, revision: number, action: "archive" | "restore", signal?: AbortSignal) => post<AlertRuleRecord>(`/v1/alert-rules/${encodeURIComponent(id)}/state`, { expected_revision: revision, action }, signal),
  notifications: (unread: boolean, signal?: AbortSignal, offset = 0) => request<{ items: LocalNotification[]; total: number }>(`/v1/notifications?unread=${unread}&offset=${offset}`, { signal }),
  markNotification: (id: string, read: boolean, signal?: AbortSignal) => request<{ id: string; read_at: string | null }>(`/v1/notifications/${encodeURIComponent(id)}/read`, { method: "PUT", body: JSON.stringify({ read }), signal }),
  saveComparison: (payload: SaveComparisonRequest, signal?: AbortSignal) => post<SavedComparisonRecord>("/v1/saved-comparisons", payload, signal),
  savedComparisons: (archived = false, signal?: AbortSignal, offset = 0) => request<{ items: SavedComparisonRecord[]; total: number; offset: number; limit: number }>(`/v1/saved-comparisons?archived=${archived}&offset=${offset}`, { signal }),
  savedComparison: (id: string, signal?: AbortSignal) => request<SavedComparisonDetail>(`/v1/saved-comparisons/${encodeURIComponent(id)}?mode=history`, { signal }),
  editSavedComparison: (id: string, revision: number, title: string, notes: string, signal?: AbortSignal) => request<SavedComparisonRecord>(`/v1/saved-comparisons/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ expected_revision: revision, title, notes }), signal }),
  savedComparisonState: (id: string, revision: number, action: "archive" | "restore", signal?: AbortSignal) => post<SavedComparisonRecord>(`/v1/saved-comparisons/${encodeURIComponent(id)}/state`, { expected_revision: revision, action }, signal),
  drivingPreferences: (signal?: AbortSignal) => request<DrivingPreferenceState>("/v1/driving-preferences", { signal }),
  saveDrivingPreferences: (revision: number, weights: DrivingWeights, signal?: AbortSignal) => request<DrivingPreferenceState>("/v1/driving-preferences", { method: "PUT", body: JSON.stringify({ expected_revision: revision, weights }), signal }),
  clearDrivingPreferences: (revision: number, signal?: AbortSignal) => post<DrivingPreferenceState>("/v1/driving-preferences/clear", { expected_revision: revision }, signal),
  garage: (archived = false, signal?: AbortSignal, offset = 0) => request<GarageList>(`/v1/garage?archived=${archived}&offset=${offset}`, { signal }),
  garageDetail: (id: string, signal?: AbortSignal) => request<GarageDetail>(`/v1/garage/${encodeURIComponent(id)}?mode=history`, { signal }),
  createGarage: (profile: GarageProfile, signal?: AbortSignal) => post<GarageRecord>("/v1/garage", profile, signal),
  garageFromFitment: (snapshotId: string, fitmentId: string, nickname: string, signal?: AbortSignal) => post<GarageRecord>("/v1/garage/from-fitment", { snapshot_id: snapshotId, fitment_id: fitmentId, nickname }, signal),
  updateGarage: (id: string, revision: number, profile: GarageProfile, signal?: AbortSignal) => request<GarageRecord>(`/v1/garage/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ expected_revision: revision, profile }), signal }),
  garageState: (id: string, revision: number, action: "archive" | "restore", signal?: AbortSignal) => post<GarageRecord>(`/v1/garage/${encodeURIComponent(id)}/state`, { expected_revision: revision, action }, signal),
  garageTire: (id: string, revision: number, axle: "front" | "rear", variantId: string | null, signal?: AbortSignal) => post<GarageRecord>(`/v1/garage/${encodeURIComponent(id)}/tires`, { expected_revision: revision, axle, variant_id: variantId }, signal),
  sources: (signal?: AbortSignal) => request<{ sources: Source[] }>("/v1/sources", { signal }),
  sourceSettings: (signal?: AbortSignal) => request<import("@tire/domain-types").SourceSettingCatalog>("/v1/source-settings", { signal }),
  sourceSetting: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").SourceSettingView>(`/v1/source-settings/${encodeURIComponent(id)}`, { signal }),
  sourceSettingHistory: (id: string, offset = 0, signal?: AbortSignal) => request<import("@tire/domain-types").SourceSettingHistory>(`/v1/source-settings/${encodeURIComponent(id)}/history?offset=${offset}&limit=10`, { signal }),
  previewSourceSetting: (id: string, payload: import("@tire/domain-types").SourceSettingIntent, signal?: AbortSignal) => post<import("@tire/domain-types").SourceSettingPreview>(`/v1/source-settings/${encodeURIComponent(id)}/preview`, payload, signal),
  reviseSourceSetting: (id: string, payload: import("@tire/domain-types").SourceSettingRevisionRequest, key: string, signal?: AbortSignal) => request<import("@tire/domain-types").SourceSettingRevisionResult>(`/v1/source-settings/${encodeURIComponent(id)}/revisions`, { method: "POST", body: JSON.stringify(payload), headers: { "Idempotency-Key": key }, signal }),
  health: (signal?: AbortSignal) => request<Health>("/health", { signal }),
  sourceHealth: (signal?: AbortSignal) => request<SourceHealthResult>("/v1/source-health", { signal }),
  sourceHealthTrends: (days = 14, signal?: AbortSignal) => request<SourceHealthTrends>(`/v1/source-health/trends?days=${days}`, { signal }),
  aiUsageHistory: (days = 14, signal?: AbortSignal) => request<AIUsageHistory>(`/v1/ai/usage/history?days=${days}`, { signal }),
  quarantines: (sourceId: string, signal?: AbortSignal) => request<{ data_state: "local_snapshot"; items: QuarantineRecord[]; source_ids: string[] }>(`/v1/quarantines?limit=50${sourceId ? `&source_id=${encodeURIComponent(sourceId)}` : ""}`, { signal }),
  quarantineEvidence: (id: string, signal?: AbortSignal) => request<QuarantineEvidence>(`/v1/quarantines/${encodeURIComponent(id)}?mode=history`, { signal }),
  testEvents: (signal?: AbortSignal, offset = 0) => request<{ items: import("@tire/domain-types").TestEventRecord[]; total: number }>(`/v1/test-events?mode=history&offset=${offset}`, { signal }),
  testEvent: (id: string, signal?: AbortSignal, revision?: number) => request<import("@tire/domain-types").TestEventDetail>(`/v1/test-events/${encodeURIComponent(id)}?mode=history${revision ? `&revision=${revision}` : ""}`, { signal }),
  saveTestEvent: (payload: import("@tire/domain-types").SaveTestEvent, id?: string, revision?: number, signal?: AbortSignal) => request<import("@tire/domain-types").TestEventDetail>(`/v1/test-events${id ? `/${encodeURIComponent(id)}` : ""}`, { method: id ? "PUT" : "POST", body: JSON.stringify({ ...payload, ...(id ? { expected_revision: revision } : {}) }), signal }),
  testEventState: (id: string, payload: { action: "revoke" | "restore"; expected_revision: number; operator: string; reason: string }, signal?: AbortSignal) => request<import("@tire/domain-types").TestEventDetail>(`/v1/test-events/${encodeURIComponent(id)}/state`, { method: "POST", body: JSON.stringify(payload), signal }),
  compareTestEvent: (id: string, payload: { expected_revision: number; participant_ids: string[]; metric_keys: string[] }, signal?: AbortSignal) => request<import("@tire/domain-types").TestEventComparison>(`/v1/test-events/${encodeURIComponent(id)}/compare?mode=history`, { method: "POST", body: JSON.stringify(payload), signal }),
  quarantineReview: (id: string, signal?: AbortSignal) => request<import("@tire/domain-types").QuarantineReviewState>(`/v1/quarantines/${encodeURIComponent(id)}/review?mode=history`, { signal }),
  reviewQuarantine: (id: string, payload: import("@tire/domain-types").QuarantineReviewRequest, signal?: AbortSignal) => request<import("@tire/domain-types").QuarantineReviewState>(`/v1/quarantines/${encodeURIComponent(id)}/reviews`, { method: "POST", body: JSON.stringify(payload), signal }),
  captures: (pendingOnly: boolean, signal?: AbortSignal) => request<{ data_state: "local_snapshot"; items: RawCaptureRecord[] }>(`/v1/captures?mode=history&limit=50&pending_only=${pendingOnly}`, { signal }),
  captureEvidence: (id: string, signal?: AbortSignal) => request<RawCaptureEvidence>(`/v1/captures/${encodeURIComponent(id)}?mode=history`, { signal }),
  tireQueryFilters: (signal?: AbortSignal) => request<import("@tire/domain-types").TireFilterCatalog>("/v1/tire-query-filters", { signal }),
  liveQuery: (sourceId: string, query: TireQuery, signal?: AbortSignal, consentId?: string, filters: readonly import("@tire/domain-types").TireFilter[] = []) => postExactCriteria<QueryResult>(`/v1/sources/${encodeURIComponent(sourceId)}/live-query`, { query, filters, fallback_policy: "ask", ...(consentId ? { consent_id: consentId } : {}) }, signal),
  consent: (queryId: string, decision: "allow" | "deny", signal?: AbortSignal) => post<{ id: string; decision: "allow" | "deny" }>("/v1/fallback-consents", { query_id: queryId, decision, scope: "once" }, signal),
  evidence: (snapshotId: string, signal?: AbortSignal) => request<Evidence>(`/v1/evidence/${encodeURIComponent(snapshotId)}`, { signal }),
  compare: (variantIds: string[], signal?: AbortSignal, includeManual = false, resolveIdentities = false) => post<ComparisonView>("/v1/compare", { variant_ids: variantIds, include_manual: includeManual, resolve_identities: resolveIdentities }, signal),
  lifecycle: (variantId: string, signal?: AbortSignal) => request<LifecycleReview>(`/v1/tire-variants/${encodeURIComponent(variantId)}/lifecycle?mode=history`, { signal }),
  reviseLifecycle: (variantId: string, payload: LifecycleRequest, signal?: AbortSignal) => post<LifecycleReview>(`/v1/tire-variants/${encodeURIComponent(variantId)}/lifecycle-events`, payload, signal),
  factReview: (variantId: string, sourceId: string, signal?: AbortSignal) => request<FactReview>(`/v1/tire-variants/${encodeURIComponent(variantId)}/fact-review?mode=history&source_id=${encodeURIComponent(sourceId)}`, { signal }),
  reviseFact: (variantId: string, payload: FactRevisionRequest, signal?: AbortSignal) => post<FactReview>(`/v1/tire-variants/${encodeURIComponent(variantId)}/fact-revisions`, payload, signal),
  watchlists: (signal?: AbortSignal) => request<{ items: WatchItem[] }>("/v1/watchlists", { signal }),
  watch: (variantId: string) => post<WatchItem>("/v1/watchlists", { variant_id: variantId }),
  unwatch: (id: string) => request<void>(`/v1/watchlists/${encodeURIComponent(id)}`, { method: "DELETE" }),
  changes: (signal?: AbortSignal) => request<{ items: ChangeItem[] }>("/v1/changes", { signal }),
  vehicles: (signal?: AbortSignal) => request<{ data_state: "source_catalog"; vehicles: VehicleCandidate[] }>("/v1/vehicles", { signal }),
  liveFitments: (vehicleId: string, signal?: AbortSignal, consentId?: string) => post<VehicleFitmentResult>(`/v1/vehicles/${encodeURIComponent(vehicleId)}/live-fitments`, { fallback_policy: "ask", ...(consentId ? { consent_id: consentId } : {}) }, signal),
  vehicleEvidence: (snapshotId: string, signal?: AbortSignal) => request<Evidence>(`/v1/vehicle-evidence/${encodeURIComponent(snapshotId)}`, { signal }),
};

// device-ai internal reuse points (wire not frozen; device-ai-host.ts consumes
// these so the unfrozen Host SDK shares the sealed transport pipeline — session
// cookies, Idempotency-Key handling, ApiError mapping — instead of growing a
// second client). Not part of the frozen product surface.
export { request as deviceAiInternalRequest, checkedAIStreamDetail as deviceAiInternalStreamDetail };
