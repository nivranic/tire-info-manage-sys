import type { ApiKeyCreate, ApiKeyList, ApiKeyOperation, ApiKeyRecord, ExternalDeliveries, ExternalDelivery, ExternalDeliveryRequest, ExternalPageRequest, ExternalSource, ExternalSources, ExternalTireFactRequest, ExternalTireFactResult, ExternalTireFactPageRequest, ExternalTireFactPage } from "@tire/domain-types";
import { assertWebhookDelivery, assertWebhookDeliverySummary, verifyWebhookBodyHash } from "./webhooks";
import { EXTERNAL_TIRE_FACT_MAX_BYTES, isExternalTireFactRequest, isExternalTireFactResult } from "./external-tire-facts";
import { EXTERNAL_TIRE_FACT_PAGE_MAX_BYTES, isExternalTireFactPageRequest, isExternalTireFactPage, tireFactPageMatchesRequest } from "./external-tire-fact-page";

type Obj = Record<string, unknown>;
type Send = <T>(path: string, init?: RequestInit) => Promise<T>;
export class ExternalApiContractError extends Error { constructor() { super("外部 API 响应或参数未通过校验。"); this.name = "ExternalApiContractError"; } }
export class ExternalApiError extends Error {
  constructor(public readonly status: number, public readonly code: string) { super(`外部 API 请求未完成 (${status})。`); this.name = "ExternalApiError"; }
}
function check(v: unknown): asserts v { if (!v) throw new ExternalApiContractError(); }
export function assertExternalTireFactResult(v: unknown): asserts v is ExternalTireFactResult { check(isExternalTireFactResult(v)); }
export function assertExternalTireFactPage(v: unknown): asserts v is ExternalTireFactPage { check(isExternalTireFactPage(v)); }
const obj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);
const exact = (v: unknown, fields: string[]): v is Obj => obj(v) && Object.keys(v).length === fields.length && fields.every(f => Object.hasOwn(v, f));
const id = (v: unknown): v is string => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const text = (v: unknown, max: number): v is string => typeof v === "string" && [...v].length <= max && !/[\u0000-\u001f\u007f-\u009f]/.test(v);
/** Keep Python's microseconds: Date.parse alone loses ordering inside a millisecond. */
export function apiKeyTime(v: unknown): bigint {
  check(typeof v === "string");
  const match = /^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(v);
  check(match); const milliseconds = Date.parse(match[1] + "Z");
  check(Number.isFinite(milliseconds) && new Date(milliseconds).toISOString().slice(0, 19) === match[1]);
  return BigInt(milliseconds) * 1000n + BigInt((match[2] || "").padEnd(6, "0"));
}
const time = (v: unknown): v is string => { try { apiKeyTime(v); return true; } catch { return false; } };
const uuid = (v: unknown): v is string => typeof v === "string" && /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(v);
const token = (v: unknown): v is string => typeof v === "string" && /^ti_[a-f0-9]{32}\.[a-f0-9]{64}$/.test(v);
const cursor = (v: unknown): v is string => typeof v === "string" && /^[A-Za-z0-9_.-]{1,2048}$/.test(v);
const scopeList = (v: unknown): boolean => Array.isArray(v) && v.length >= 1 && v.length <= 3 && v.every(s => s === "sources:read" || s === "webhooks:read" || s === "facts:read") && new Set(v).size === v.length && [...v].sort().every((s, i) => s === v[i]);
export function assertApiKey(v: unknown): asserts v is ApiKeyRecord {
  check(exact(v, ["schema", "id", "name", "scopes", "created_at", "expires_at", "revoked_at"])
    && v.schema === "api-key@1" && typeof v.id === "string" && /^[a-f0-9]{32}$/.test(v.id) && text(v.name, 80) && v.name.trim() === v.name && v.name.length > 0 && scopeList(v.scopes)
    && time(v.created_at) && time(v.expires_at) && apiKeyTime(v.expires_at) > apiKeyTime(v.created_at)
    && (v.revoked_at === null || (time(v.revoked_at) && apiKeyTime(v.revoked_at) >= apiKeyTime(v.created_at))));
}
export function assertApiKeyOperation(v: unknown): asserts v is ApiKeyOperation {
  check(exact(v, ["schema", "idempotency_key", "action", "key", "token", "replayed"])
    && v.schema === "api-key-operation@1" && uuid(v.idempotency_key) && (v.action === "create" || v.action === "revoke") && typeof v.replayed === "boolean");
  assertApiKey(v.key);
  check(v.action === "create" ? v.key.revoked_at === null : v.key.revoked_at !== null);
  if (v.token !== null) check(v.action === "create" && v.replayed === false && token(v.token) && v.token.startsWith(`ti_${v.key.id}.`));
  else check(v.action === "revoke" || v.replayed === true);
}
function assertKeyList(v: unknown): asserts v is ApiKeyList {
  check(exact(v, ["schema", "items"]) && v.schema === "api-keys@1" && Array.isArray(v.items) && v.items.length <= 100);
  v.items.forEach(assertApiKey); check(new Set(v.items.map(k => k.id)).size === v.items.length);
}
export function createApiKeysApi(send: Send) {
  return {
    apiKeys: async (signal?: AbortSignal) => { const v = await send<unknown>("/v1/api-keys?mode=history", { signal }); assertKeyList(v); return v; },
    createApiKey: async (payload: ApiKeyCreate, key: string, signal?: AbortSignal) => {
      check(uuid(key) && exact(payload, ["name", "scopes", "expires_in_days", "acknowledged"]) && text(payload.name, 80) && payload.name.trim().length > 0
        && scopeList(payload.scopes) && Number.isInteger(payload.expires_in_days) && payload.expires_in_days >= 1 && payload.expires_in_days <= 90 && payload.acknowledged === true);
      const v = await send<unknown>("/v1/api-keys", { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal });
      assertApiKeyOperation(v); check(v.idempotency_key.toLowerCase() === key.toLowerCase() && v.action === "create" && v.key.name === payload.name.trim() && JSON.stringify(v.key.scopes) === JSON.stringify(payload.scopes)); return v;
    },
    revokeApiKey: async (idValue: string, key: string, signal?: AbortSignal) => {
      check(id(idValue) && uuid(key));
      const v = await send<unknown>(`/v1/api-keys/${encodeURIComponent(idValue)}/revoke`, { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify({ acknowledged: true }), signal });
      assertApiKeyOperation(v); check(v.idempotency_key.toLowerCase() === key.toLowerCase() && v.action === "revoke" && v.key.id === idValue); return v;
    },
    apiKeyOperation: async (key: string, signal?: AbortSignal) => {
      check(uuid(key)); const v = await send<unknown>(`/v1/api-key-operations?${new URLSearchParams({ mode: "history", key })}`, { signal });
      assertApiKeyOperation(v); check(v.idempotency_key.toLowerCase() === key.toLowerCase() && v.token === null && v.replayed === true); return v;
    },
  };
}
function page(v: unknown, schema: string, request: ExternalPageRequest, validate: (v: unknown) => void): asserts v is Obj & { items: Obj[] } {
  check(exact(v, ["schema", "items", "next_cursor", "limit", "data_state"]) && v.schema === schema && Array.isArray(v.items)
    && v.limit === (request.limit ?? 20) && v.items.length <= Number(v.limit) && v.data_state === "local_snapshot"
    && (v.next_cursor === null || (cursor(v.next_cursor) && v.next_cursor !== request.cursor && v.items.length === v.limit)));
  v.items.forEach(validate); check(new Set(v.items.map(item => (item as Obj).id)).size === v.items.length);
}
function source(v: unknown) {
  check(exact(v, ["id", "name", "source_class", "region", "parser_version", "status"]) && typeof v.id === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(v.id));
  for (const field of ["name", "source_class", "region", "parser_version", "status"]) check(v[field] === null || text(v[field], 500));
}
/** Supply a transport bound to a trusted API origin. Tokens remain in this client instance only. */
export function createExternalApiClient(bearer: string, transport: (path: string, init: RequestInit) => Promise<Response>) {
  check(token(bearer));
  async function get(path: string, signal?: AbortSignal, maximumBytes = 1024 * 1024): Promise<unknown> {
    const strictAbort = maximumBytes === EXTERNAL_TIRE_FACT_PAGE_MAX_BYTES;
    const abortError = () => new DOMException("请求已取消", "AbortError");
    function cancelWithoutWaiting(cancel: () => Promise<unknown> | undefined) {
      try { void cancel()?.catch(() => {}); } catch { /* Cleanup cannot replace the page result. */ }
    }
    function abortable<T>(pending: Promise<T>, lateCleanup?: (value: T) => void): Promise<T> {
      if (!strictAbort || !signal) return pending;
      return new Promise<T>((resolve, reject) => {
        let stopped = false;
        const stop = () => { stopped = true; signal!.removeEventListener("abort", stop); reject(abortError()); };
        if (signal!.aborted) stop(); else signal!.addEventListener("abort", stop, { once: true });
        pending.then(value => {
          signal!.removeEventListener("abort", stop);
          if (stopped || signal!.aborted) { lateCleanup?.(value); reject(abortError()); }
          else resolve(value);
        }, error => { signal!.removeEventListener("abort", stop); reject(error); });
      });
    }
    if (strictAbort && signal?.aborted) throw abortError();
    let response: Response;
    try { response = await abortable(transport(path, { method: "GET", headers: { Authorization: `Bearer ${bearer}`, Accept: "application/json" },
      credentials: "omit", cache: "no-store", redirect: "error", referrerPolicy: "no-referrer", signal }),
      value => cancelWithoutWaiting(() => value.body?.cancel())); }
    catch { if (signal?.aborted) throw new DOMException("请求已取消", "AbortError"); throw new ExternalApiError(0, "external_transport_failed"); }
    try {
      check(!response.redirected);
      if (!response.ok) throw new ExternalApiError(response.status, "external_request_rejected");
      check(response.headers.get("content-type")?.split(";")[0].trim() === "application/json");
    } catch (error) { if (strictAbort) cancelWithoutWaiting(() => response.body?.cancel()); throw error; }
    const reader = response.body?.getReader(); check(reader); const decoder = new TextDecoder("utf-8", { fatal: true }); let raw = "", size = 0;
    try { while (true) { const part = await abortable(reader.read()); if (part.done) break; size += part.value.byteLength; check(size <= maximumBytes); raw += decoder.decode(part.value, { stream: true }); } raw += decoder.decode(); }
    catch (error) { if (maximumBytes !== EXTERNAL_TIRE_FACT_MAX_BYTES && !strictAbort) throw error; if (signal?.aborted) throw new DOMException("请求已取消", "AbortError"); throw new ExternalApiContractError(); }
    finally {
      if (strictAbort) { cancelWithoutWaiting(() => reader.cancel()); try { reader.releaseLock(); } catch { /* Preserve the page error. */ } }
      else { await reader.cancel().catch(() => {}); reader.releaseLock(); }
    }
    if (strictAbort && signal?.aborted) throw abortError();
    try { return JSON.parse(raw); } catch { throw new ExternalApiContractError(); }
  }
  function query(request: ExternalPageRequest) {
    check(Number.isInteger(request.limit ?? 20) && (request.limit ?? 20) >= 1 && (request.limit ?? 20) <= 100 && (request.cursor === undefined || cursor(request.cursor)));
    const p = new URLSearchParams({ limit: String(request.limit ?? 20) }); if (request.cursor) p.set("cursor", request.cursor); return p;
  }
  return {
    tireFacts: async (request: ExternalTireFactPageRequest): Promise<ExternalTireFactPage> => {
      check(isExternalTireFactPageRequest(request, bearer.slice(3, 35)));
      const { source_id, query_id, verification_id, signal, cursor: pageCursor } = request, limit = request.limit ?? 20;
      const snapshot = { source_id, query_id, verification_id, signal, cursor: pageCursor, limit };
      const params = new URLSearchParams({ source_id, query_id, verification_id, limit: String(limit) });
      if (pageCursor !== undefined) params.set("cursor", pageCursor);
      const v = await get(`/external/v1/tire-facts?${params}`, signal, EXTERNAL_TIRE_FACT_PAGE_MAX_BYTES);
      assertExternalTireFactPage(v);
      check(tireFactPageMatchesRequest(v, snapshot, bearer.slice(3, 35)));
      return v;
    },
    tireFact: async (request: ExternalTireFactRequest): Promise<ExternalTireFactResult> => {
      check(isExternalTireFactRequest(request));
      const { source_id, query_id, verification_id, variant_id, signal } = request;
      const params = new URLSearchParams({ source_id, query_id, verification_id });
      const v = await get(`/external/v1/tire-facts/${encodeURIComponent(variant_id)}?${params}`, signal, EXTERNAL_TIRE_FACT_MAX_BYTES);
      assertExternalTireFactResult(v);
      check(v.item.observation.source_id === source_id && v.item.identity.variant_id === variant_id);
      return v;
    },
    sources: async (request: ExternalPageRequest = {}): Promise<ExternalSources> => {
      const v = await get(`/external/v1/sources?${query(request)}`, request.signal); page(v, "external-sources@1", request, source);
      const items = v.items as unknown as ExternalSource[]; check(items.every((item, i) => i === 0 || items[i - 1].id < item.id)); return v as unknown as ExternalSources;
    },
    deliveries: async (request: ExternalDeliveryRequest = {}): Promise<ExternalDeliveries> => {
      const p = query(request); if (request.channel !== undefined) { check(["tire_monitor", "recall_monitor", "interest"].includes(request.channel)); p.set("channel", request.channel); }
      if (request.webhook_id !== undefined) { check(id(request.webhook_id)); p.set("webhook_id", request.webhook_id); }
      const v = await get(`/external/v1/webhook-deliveries?${p}`, request.signal); page(v, "external-webhook-deliveries@1", request, assertWebhookDeliverySummary);
      check(v.items.every(item => (!request.channel || item.channel === request.channel) && (!request.webhook_id || item.webhook_id === request.webhook_id)));
      check(v.items.every((item, i) => i === 0 || String(v.items[i - 1].created_at) < String(item.created_at) || (v.items[i - 1].created_at === item.created_at && String(v.items[i - 1].id) < String(item.id))));
      return v as unknown as ExternalDeliveries;
    },
    delivery: async (idValue: string, signal?: AbortSignal): Promise<ExternalDelivery> => {
      check(id(idValue)); const v = await get(`/external/v1/webhook-deliveries/${encodeURIComponent(idValue)}`, signal); assertWebhookDelivery(v); check(v.id === idValue); await verifyWebhookBodyHash(v); return v;
    },
  };
}
