import type { ApiTransport } from "@tire/api-client";
import { cloneExactDeviceValue, decodeExactDeviceFallbackWire, deviceIntentKey, encodeExactDeviceFallbackWire, fallbackShape,
  validateDeviceFallbackBinding, validateDeviceFallbackDecision, validateDeviceFallbackGrant, validateDeviceFallbackIntent, validateDeviceFallbackResult } from "@tire/api-client";
import type { DeviceFallbackGrantV2, DeviceFallbackResultV2, DeviceFallbackAuthorizeResult } from "@tire/domain-types";

export type NativeInvoke = <T>(command: string, args?: Record<string, unknown>) => Promise<T>;

/** Device storage has its own IPC path. API health and session bootstrap never gate reads. */
export function createNativeOfflineStorage(invoke: NativeInvoke): import("@tire/domain-types").OfflineStorage {
  const grants = new Map<string, DeviceFallbackGrantV2>();
  async function rpc<T>(command: string, request?: object): Promise<T> {
    try { return await invoke<T>(command, request ? { request } : undefined); }
    catch (cause) {
      const value = cause && typeof cause === "object" ? cause as { code?: unknown; message?: unknown } : null;
      const candidate = typeof cause === "string" ? cause : value?.code || value?.message;
      const code = typeof candidate === "string" && (/^OFFLINE_[A-Z_]+$/.test(candidate) || ["API_UNAVAILABLE", "API_TIMEOUT", "API_REDIRECT_BLOCKED", "REQUEST_CANCELLED", "SESSION_CHANGED", "SESSION_RESET_IN_PROGRESS"].includes(candidate)) ? candidate : "OFFLINE_STORAGE_UNAVAILABLE";
      throw Object.assign(new Error("设备离线操作未完成，请重新读取本机状态。"), { code });
    }
  }
  return {
    fallbackStatus: () => rpc("offline_fallback_status"),
    refreshFallbackAuthority: () => rpc("offline_fallback_authority_refresh"),
    previewFallbackPolicy: request => rpc("offline_fallback_policy_preview", request),
    applyFallbackPolicy: request => rpc("offline_fallback_policy_apply", request),
    pauseFallbackPolicy: request => rpc("offline_fallback_policy_pause", request),
    revokeFallbackPolicy: request => rpc("offline_fallback_policy_revoke", request),
    authorizeFallback: async request => {
      validateDeviceFallbackBinding(request, ["intent"]); validateDeviceFallbackIntent(request.intent);
      const frozen = cloneExactDeviceValue(request), response = await rpc<unknown>("offline_fallback_authorize", encodeExactDeviceFallbackWire(frozen));
      const state = response && typeof response === "object" && "state" in response ? response.state : null;
      if (state === "allowed") {
        const value = decodeExactDeviceFallbackWire<DeviceFallbackAuthorizeResult>(response).core;
        fallbackShape(value, ["schema", "state", "reason", "grant"]);
        if (value.schema !== "device-fallback-authorization@1" || value.state !== "allowed" || value.reason !== null) throw Object.assign(new Error("设备授权响应无效。"), { code: "OFFLINE_FALLBACK_MISMATCH" });
        validateDeviceFallbackGrant(value.grant, frozen, "allowed"); grants.set(value.grant.id, cloneExactDeviceValue(value.grant)); return value;
      }
      const value = fallbackShape(response, ["schema", "state", "reason", "grant"]);
      if (value.schema !== "device-fallback-authorization@1" || !["ask", "blocked"].includes(String(value.state)) || typeof value.reason !== "string" || value.grant !== null) throw Object.assign(new Error("设备授权响应无效。"), { code: "OFFLINE_FALLBACK_MISMATCH" });
      return value as unknown as DeviceFallbackAuthorizeResult;
    },
    decideFallbackV2: async request => {
      validateDeviceFallbackDecision(request); const frozen = cloneExactDeviceValue(request);
      const grant = decodeExactDeviceFallbackWire<DeviceFallbackGrantV2>(await rpc("offline_fallback_decide", encodeExactDeviceFallbackWire(frozen))).core;
      validateDeviceFallbackGrant(grant, frozen, frozen.decision === "allow" ? "allowed" : "denied");
      if (grant.fallback_authorization.type !== "explicit_once") throw Object.assign(new Error("设备授权类型无效。"), { code: "OFFLINE_FALLBACK_MISMATCH" });
      if (grant.state === "allowed") grants.set(grant.id, cloneExactDeviceValue(grant)); return grant;
    },
    consumeFallbackV2: async request => {
      fallbackShape(request, ["grant_id", "intent"]); validateDeviceFallbackIntent(request.intent); const frozen = cloneExactDeviceValue(request), grant = grants.get(frozen.grant_id); grants.delete(frozen.grant_id);
      if (!grant || deviceIntentKey(grant.intent) !== deviceIntentKey(frozen.intent)) throw Object.assign(new Error("设备授权已结束或不匹配。"), { code: "OFFLINE_FALLBACK_USED" });
      const value = decodeExactDeviceFallbackWire<DeviceFallbackResultV2>(await rpc("offline_fallback_consume", encodeExactDeviceFallbackWire(frozen))).core;
      validateDeviceFallbackResult(value, { intent: frozen.intent, slot_id: grant.slot_id, expected_generation: grant.generation, expected_sha256: grant.package_sha256, expected_profile_id: grant.profile_id, expected_owner_epoch: grant.owner_epoch });
      if (value.grant.id !== grant.id) throw Object.assign(new Error("设备授权响应不匹配。"), { code: "OFFLINE_FALLBACK_MISMATCH" }); return value;
    },
    revokeFallbackV2: request => { grants.delete(request.grant_id); return rpc("offline_fallback_revoke", request); },
    status: () => rpc("offline_status"),
    list: () => rpc("offline_list"),
    install: async (request, signal) => {
      if (signal?.aborted) throw new DOMException("离线安装已停止等待", "AbortError");
      // The host owns download/validation/atomic commit; closing a WebView cannot
      // claim that an accepted install was undone. Re-read the slot after uncertainty.
      return rpc("offline_install", request);
    },
    search: request => rpc("offline_search", request),
    read: async request => {
      const response = await rpc<unknown>("offline_read", request);
      if (response && typeof response === "object" && "schema" in response && response.schema === "offline-read-result@2") {
        const value = decodeExactDeviceFallbackWire<import("@tire/domain-types").OfflineReadResultV2>(response).core;
        fallbackShape(value, ["schema", "package_schema", "data_state", "slot", "document", "member", "context"]);
        if (value.data_state !== "local_snapshot" || value.slot?.slot_id !== request.slot_id || value.slot.generation !== request.expected_generation || value.document?.id !== request.document_id) throw Object.assign(new Error("设备历史响应不匹配。"), { code: "OFFLINE_FALLBACK_MISMATCH" }); return value;
      }
      if (response && typeof response === "object" && ("raw_json" in response || "schema" in response)) throw Object.assign(new Error("设备历史版本不支持。"), { code: "OFFLINE_FALLBACK_UNSUPPORTED" });
      return response as import("@tire/domain-types").OfflineReadResult;
    },
    remove: request => rpc("offline_remove", request),
    unlockPreviousOwner: request => rpc("offline_unlock_previous_owner", request),
    decideFallback: request => rpc("offline_fallback_decide", request),
    consumeFallback: request => rpc("offline_fallback_consume", request),
    revokeFallback: request => rpc("offline_fallback_revoke", request),
    syncStatus: () => rpc("offline_sync_status"),
    previewSyncPolicy: request => rpc("offline_sync_preview", request),
    applySyncPolicy: request => rpc("offline_sync_apply", request),
    pauseSyncPolicy: request => rpc("offline_sync_pause", request),
    revokeSyncPolicy: request => rpc("offline_sync_revoke", request),
    runSyncPolicy: request => rpc("offline_sync_run", request),
    revalidateSync: () => rpc("offline_sync_revalidate"),
  };
}

export interface NativeDownload {
  blob: Blob;
  filename: string;
  signal?: AbortSignal;
}

export type NativeSave = (download: NativeDownload) => Promise<{ saved: boolean }>;

export interface NativeResponse {
  status: number;
  headers: Record<string, string>;
  body_base64: string;
}

const messages: Record<string, string> = {
  secure_store_unavailable: "系统安全凭据存储不可用。请解锁系统密钥环或凭据管理器后重试。",
  session_store_unavailable: "系统安全凭据存储不可用。请解锁系统密钥环或凭据管理器后重试。",
  session_unavailable: "安全会话尚未就绪，请重新连接本机 API。",
  api_unavailable: "无法连接本机 API，请确认服务已启动后重试。",
  request_failed: "本机 API 请求未完成，请检查连接。写入结果可能已保存，请先重新读取记录。",
  request_timeout: "本机 API 响应超时。写入结果可能已保存，请先重新读取记录。",
  invalid_request: "请求未通过原生安全检查。",
  invalid_response: "本机 API 返回了无法读取的响应。",
  save_failed: "文件未保存，请检查目标文件夹权限后重试。",
  invalid_download: "文件未通过保存检查。",
  external_open_failed: "未能打开系统浏览器，请重试。",
  invalid_external_url: "此链接不允许通过系统浏览器打开。",
  desktop_unavailable: "桌面系统能力未就绪，请从已安装的桌面应用打开。",
  MOBILE_UNAVAILABLE: "移动端系统能力未就绪，请从已安装的 Android 应用打开。",
  RELEASE_API_NOT_CONFIGURED: "此安装包尚未配置正式移动端 API，当前无法连接工作区。",
  INVALID_NATIVE_STATUS: "原生连接状态未通过验证，请重新打开应用。",
  NATIVE_COMMAND_UNAVAILABLE: "当前安装包不支持此原生操作。",
  INVALID_NATIVE_ARGUMENT: "原生操作参数未通过验证。",
  IPC_ORIGIN_DENIED: "当前页面无权访问应用系统能力。",
  BACK_REQUEST_EXPIRED: "本次返回操作已结束，请重新操作。",
  INVALID_THEME: "系统外观设置未通过验证。",
  DOWNLOAD_DIALOG_BUSY: "正在选择另一个文件的保存位置，请先完成当前保存。",
  DOWNLOAD_DIALOG_FAILED: "未能打开系统文件选择器，请重试。",
  DOWNLOAD_TOO_LARGE: "文件超出本机保存大小限制。",
  REQUEST_CANCELLED: "请求已取消；服务器写入结果须重新读取确认。",
  API_TIMEOUT: "本机 API 响应超时。写入结果可能已保存，请先重新读取记录。",
  API_UNAVAILABLE: "无法连接本机 API，请确认服务已启动后重试。",
  API_REQUEST_FAILED: "本机 API 请求未完成。写入结果可能已保存，请先重新读取记录。",
  API_HEALTH_FAILED: "本机 API 健康检查未通过，请确认服务状态后重试。",
  API_REDIRECT_BLOCKED: "本机 API 返回了不允许的跳转，请检查服务配置。",
  TOO_MANY_REQUESTS: "当前操作过多，请稍后再试。",
  REQUEST_TOO_LARGE: "上传内容超出原生请求大小限制。",
  RESPONSE_TOO_LARGE: "响应内容超出原生接收大小限制。",
  SESSION_CHANGED: "本机会话已更改，请重新连接后读取记录。",
  SESSION_RESET_IN_PROGRESS: "本机会话正在重置，请稍后重新连接。",
  SESSION_COOKIE_MISSING: "本机 API 未能建立安全会话，请检查服务后重试。",
  INVALID_SESSION_COOKIE: "本机会话未通过验证，请重置会话后重试。",
  SESSION_STORE_UNAVAILABLE: "系统安全凭据存储不可用。请解锁系统密钥环或凭据管理器后重试。",
  SESSION_STORE_READ_FAILED: "无法读取系统安全会话，请解锁系统凭据存储后重试。",
  SESSION_STORE_WRITE_FAILED: "无法将会话保存到系统安全存储，已停止连接。",
  SESSION_STORE_DELETE_FAILED: "系统安全会话未能重置，请检查系统凭据存储权限。",
  SESSION_STORE_INVALID: "系统保存的会话无法验证，请重置本机会话后重试。",
  SESSION_STORE_UNSUPPORTED_PLATFORM: "当前系统不支持此桌面安全会话存储。",
  INVALID_API_PATH: "请求路径未通过原生安全检查。",
  INVALID_API_METHOD: "请求方法未通过原生安全检查。",
  INVALID_API_HEADER: "请求标头未通过原生安全检查。",
  INVALID_API_BODY: "请求内容未通过原生安全检查。",
  INVALID_REQUEST_ID: "请求标识无效，请重新发起操作。",
  DUPLICATE_REQUEST_ID: "请求标识重复，请重新读取记录后再操作。",
  INVALID_BASE64: "文件传输内容未通过校验。",
  INVALID_DOWNLOAD_NAME: "保存文件名称不符合要求。",
  INVALID_DOWNLOAD_TYPE: "此文件类型不允许保存。",
  DOWNLOAD_WRITE_FAILED: "文件未保存，请检查目标文件夹权限后重试。",
  INVALID_EXTERNAL_URL: "此链接不允许通过系统浏览器打开。",
  EXTERNAL_OPEN_FAILED: "未能打开系统浏览器，请重试。",
  CANCEL_QUEUE_FULL: "待取消操作过多，请等待当前请求结束后重试。",
  INVALID_API_PORT: "本机 API 端口配置无效。",
  INVALID_SESSION_NAMESPACE: "桌面会话配置无效。",
  API_CLIENT_UNAVAILABLE: "桌面网络组件未就绪，请重新启动应用。",
};

export class NativeError extends Error {
  readonly code: string;
  constructor(cause: unknown) {
    const code = typeof cause === "string" && Object.hasOwn(messages, cause) ? cause : "request_failed";
    super(messages[code]);
    this.name = "NativeError";
    this.code = code;
  }
}

const aborted = () => new DOMException("已停止等待本次操作；这不代表已撤回服务器写入。", "AbortError");
const throwIfAborted = (signal?: AbortSignal | null) => { if (signal?.aborted) throw aborted(); };

export function bytesToBase64(bytes: Uint8Array): string {
  const chunks: string[] = [];
  for (let offset = 0; offset < bytes.length; offset += 0x8000) chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + 0x8000)));
  return btoa(chunks.join(""));
}

function base64ToBytes(encoded: string): Uint8Array<ArrayBuffer> {
  const binary = atob(encoded);
  return Uint8Array.from(binary, character => character.charCodeAt(0));
}

async function bodyBytes(body: BodyInit): Promise<Uint8Array> {
  if (typeof body === "string") return new TextEncoder().encode(body);
  if (body instanceof Blob) return new Uint8Array(await body.arrayBuffer());
  if (body instanceof ArrayBuffer) return new Uint8Array(body);
  if (ArrayBuffer.isView(body)) return new Uint8Array(body.buffer, body.byteOffset, body.byteLength);
  if (body instanceof URLSearchParams) return new TextEncoder().encode(body.toString());
  throw new NativeError("invalid_request");
}

const allowedHeaders = new Set(["content-type", "idempotency-key", "x-evidence-metadata"]);

/** Abort remains effective while reading a File, while IPC is pending, and before response delivery. */
export function createNativeTransport(invoke: NativeInvoke): ApiTransport {
  return (path, init = {}) => new Promise<Response>((resolve, reject) => {
    const signal = init.signal;
    if (signal?.aborted) { reject(aborted()); return; }
    const id = crypto.randomUUID();
    let settled = false;
    let dispatched = false;
    const settle = (operation: () => void) => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener("abort", onAbort);
      operation();
    };
    const cancel = () => { void invoke("api_cancel", { id }).catch(() => { /* Cancellation is best effort at the server boundary. */ }); };
    const onAbort = () => {
      settle(() => reject(aborted()));
      if (dispatched) cancel();
    };
    signal?.addEventListener("abort", onAbort, { once: true });
    void (async () => {
      try {
        throwIfAborted(signal);
        if (!path.startsWith("/") || path.startsWith("//")) throw new NativeError("invalid_request");
        const headers: Record<string, string> = {};
        new Headers(init.headers).forEach((value, key) => {
          if (!allowedHeaders.has(key)) throw new NativeError("invalid_request");
          headers[key] = value;
        });
        const bytes = init.body === undefined || init.body === null ? undefined : await bodyBytes(init.body);
        throwIfAborted(signal);
        const request = { id, path, method: (init.method || "GET").toUpperCase(), headers, ...(bytes ? { body_base64: bytesToBase64(bytes) } : {}) };
        throwIfAborted(signal);
        dispatched = true;
        const result = await invoke<NativeResponse>("api_request", { request });
        if (settled) return;
        throwIfAborted(signal);
        if (!result || !Number.isInteger(result.status) || result.status < 200 || result.status > 599 || typeof result.body_base64 !== "string" || !result.headers || typeof result.headers !== "object") throw new NativeError("invalid_response");
        const responseHeaders = new Headers();
        for (const [key, value] of Object.entries(result.headers)) {
          if (typeof value !== "string") throw new NativeError("invalid_response");
          // Session cookies are owned by the native host and must never enter the WebView.
          if (key.toLowerCase() !== "set-cookie" && key.toLowerCase() !== "set-cookie2") responseHeaders.set(key, value);
        }
        const body = [204, 205, 304].includes(result.status) || request.method === "HEAD" ? null : base64ToBytes(result.body_base64);
        const response = new Response(body, { status: result.status, headers: responseHeaders });
        settle(() => resolve(response));
      } catch (cause) {
        settle(() => reject(signal?.aborted ? aborted() : cause instanceof NativeError ? cause : new NativeError(cause)));
      }
    })();
  });
}

export function createNativeSave(invoke: NativeInvoke): NativeSave {
  return async ({ blob, filename, signal }) => {
    throwIfAborted(signal);
    const body = new Uint8Array(await blob.arrayBuffer());
    throwIfAborted(signal);
    try {
      const result = await invoke<{ saved: boolean }>("save_download", { filename, mime: blob.type, body_base64: bytesToBase64(body) });
      throwIfAborted(signal);
      if (!result || typeof result.saved !== "boolean") throw new NativeError("save_failed");
      return { saved: result.saved };
    } catch (cause) {
      if (signal?.aborted) throw aborted();
      throw cause instanceof NativeError ? cause : new NativeError("save_failed");
    }
  };
}

/** A decision helper kept independent of the DOM so URL policy is directly testable. */
export function externalLink(href: string): { action: "internal" | "external" | "blocked"; url?: string } {
  if (href === "/" || href.startsWith("#")) return { action: "internal" };
  try {
    const url = new URL(href);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return { action: "blocked" };
    return { action: "external", url: url.href };
  } catch { return { action: "blocked" }; }
}

export async function openNativeExternal(invoke: NativeInvoke, href: string): Promise<void> {
  const link = externalLink(href);
  if (link.action !== "external") throw new NativeError("invalid_external_url");
  try { await invoke("open_external", { url: link.url }); }
  catch { throw new NativeError("external_open_failed"); }
}
