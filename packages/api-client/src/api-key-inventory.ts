import type { ActiveApiKeys, ApiKeyHistory, ApiKeyHistoryRequest, ApiKeyRecord } from "@tire/domain-types";
import { apiKeyTime, assertApiKey, ExternalApiContractError } from "./external-api";

type Obj = Record<string, unknown>;
type Send = <T>(path: string, init?: RequestInit) => Promise<T>;
function check(v: unknown): asserts v { if (!v) throw new ExternalApiContractError(); }
const exact = (v: unknown, fields: string[]): v is Obj => !!v && typeof v === "object" && !Array.isArray(v)
  && Object.keys(v).length === fields.length && fields.every(f => Object.hasOwn(v, f));
const validCursor = (v: unknown): v is string => typeof v === "string" && v.length <= 2048 && /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(v) && !/[\r\n]/.test(v);
function headers(owner: string) {
  check(typeof owner === "string" && owner.length >= 1 && owner.length <= 64 && !/[^A-Za-z0-9_-]/.test(owner));
  return { "X-Tire-Expected-Account": owner };
}
function keys(v: unknown): asserts v is ApiKeyRecord[] {
  check(Array.isArray(v)); v.forEach(assertApiKey);
  check(new Set(v.map(item => item.id)).size === v.length);
  check(v.every((item, i) => i === 0 || apiKeyTime(v[i - 1].created_at) > apiKeyTime(item.created_at)
    || (apiKeyTime(v[i - 1].created_at) === apiKeyTime(item.created_at) && v[i - 1].id > item.id)));
}
export function createApiKeyInventoryApi(send: Send) {
  return {
    activeApiKeys: async (expectedAccountId: string, signal?: AbortSignal): Promise<ActiveApiKeys> => {
      const v = await send<unknown>("/v1/api-keys/active?mode=history", { headers: headers(expectedAccountId), signal });
      check(exact(v, ["schema", "items", "read_at"]) && v.schema === "active-api-keys@1");
      const read = apiKeyTime(v.read_at); keys(v.items);
      check(v.items.length <= 16 && v.items.every(item => item.revoked_at === null && apiKeyTime(item.expires_at) > read));
      return v as unknown as ActiveApiKeys;
    },
    apiKeyHistory: async (expectedAccountId: string, request: ApiKeyHistoryRequest = {}): Promise<ApiKeyHistory> => {
      const accountHeaders = headers(expectedAccountId);
      check(!!request && typeof request === "object" && !Array.isArray(request) && Object.keys(request).every(k => ["limit", "cursor", "signal"].includes(k)));
      const limit = request.limit ?? 20;
      check(Number.isInteger(limit) && limit >= 1 && limit <= 100 && (request.cursor === undefined || validCursor(request.cursor)));
      const query = new URLSearchParams({ mode: "history", limit: String(limit) }); if (request.cursor !== undefined) query.set("cursor", request.cursor);
      const v = await send<unknown>(`/v1/api-key-history?${query}`, { headers: accountHeaders, signal: request.signal });
      check(exact(v, ["schema", "items", "limit", "next_cursor", "window_started_at", "read_at"]) && v.schema === "api-key-history@1" && v.limit === limit);
      check(apiKeyTime(v.read_at) >= apiKeyTime(v.window_started_at)); keys(v.items);
      check(v.items.length <= limit && (v.next_cursor === null || (validCursor(v.next_cursor) && v.next_cursor !== request.cursor && v.items.length === limit)));
      return v as unknown as ApiKeyHistory;
    },
  };
}
