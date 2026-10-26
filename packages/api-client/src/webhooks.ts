import type {
  Webhook, WebhookAction, WebhookCreate, WebhookDelivery, WebhookDeliveryActionRequest,
  WebhookDeliveryList, WebhookEdit, WebhookList, WebhookOperation, WebhookStateRequest, WebhookTargets,
} from "@tire/domain-types";

type Obj = Record<string, unknown>;
type Send = <T>(path: string, init?: RequestInit) => Promise<T>;
const channels = ["tire_monitor", "recall_monitor", "interest"];
const domains = ["tire", "test_event", "vehicle", "fitment", "tire_curation", "tire_lifecycle", "tire_identity", "tire_catalog", "tire_curation_validity"];
const summaryKeys = ["id", "webhook_id", "webhook_revision", "channel", "notification_id", "event_id", "domain", "state", "attempts", "max_attempts", "next_attempt_at", "created_at", "completed_at", "error_code", "http_status", "body_sha256"];
const settingKeys = ["name", "target_fingerprint", "channels", "enabled", "acknowledged_external_delivery"];
const obj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);
const exact = (v: unknown, keys: readonly string[]): v is Obj => obj(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const str = (v: unknown, max = 4000): v is string => typeof v === "string" && v.trim().length > 0 && v.length <= max && !/[\u0000-\u001f\u007f]/.test(v);
const id = (v: unknown): v is string => str(v, 200);
const integer = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const one = (v: unknown, values: readonly string[]) => typeof v === "string" && values.includes(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const fingerprint = (v: unknown) => v === null || hash(v);
const uuid = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(v);
const time = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|\+00:00)$/.test(v) && Number.isFinite(Date.parse(v));
const nullableTime = (v: unknown) => v === null || time(v);
const status = (v: unknown) => v === null || integer(v, 100, 599);
const error = (v: unknown) => v === null || typeof v === "string" && /^[a-z][a-z0-9_]{0,119}$/.test(v);
const unique = (v: readonly unknown[]) => new Set(v).size === v.length;
const channelList = (v: unknown) => Array.isArray(v) && v.length >= 1 && v.length <= 3 && v.every(c => one(c, channels)) && unique(v);
const scopedDomain = (channel: unknown, domain: unknown) => channel === "interest" ? one(domain, domains) : domain === null;
const host = (v: unknown) => typeof v === "string" && v.length <= 253 && !/[:/@?#\s]/.test(v) && !/^(?:0x[0-9a-f]+|\d+)(?:\.(?:0x[0-9a-f]+|\d+))*$/i.test(v) && v.split(".").every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label));

export class WebhookContractError extends Error {
  readonly code = "webhook_contract_invalid";
  constructor() { super("Webhook数据与专用合同或本次请求不一致，未显示替代结果。"); this.name = "WebhookContractError"; }
}
function check(v: unknown): asserts v { if (!v) throw new WebhookContractError(); }
export function assertWebhookTargets(v: unknown): asserts v is WebhookTargets {
  check(exact(v, ["schema", "catalog_state", "items", "notice"]) && v.schema === "webhook-targets@1" && one(v.catalog_state, ["empty", "ready", "invalid"]) && str(v.notice) && Array.isArray(v.items) && v.items.length <= 16);
  check(v.catalog_state === "ready" ? v.items.length > 0 : v.items.length === 0);
  check(unique(v.items.map(item => obj(item) ? item.id : null)));
  for (const item of v.items) check(exact(item, ["id", "title", "endpoint_host", "ready", "state", "policy_fingerprint"]) && id(item.id) && str(item.title, 200) && host(item.endpoint_host)
    && typeof item.ready === "boolean" && (item.ready ? item.state === "ready" && hash(item.policy_fingerprint) : item.state === "key_unavailable" && item.policy_fingerprint === null));
}
export function assertWebhook(v: unknown): asserts v is Webhook {
  check(exact(v, ["schema", "id", "owner_scope", "revision", "revision_id", "name", "target_id", "target_fingerprint", "endpoint_host", "channels", "enabled", "archived", "created_at", "updated_at", "readiness", "suppressed_count", "last_suppressed_at", "notice"])
    && v.schema === "webhook@1" && v.owner_scope === "current_account" && id(v.id) && integer(v.revision, 1) && id(v.revision_id) && str(v.name, 120)
    && id(v.target_id) && fingerprint(v.target_fingerprint) && host(v.endpoint_host) && channelList(v.channels) && typeof v.enabled === "boolean" && typeof v.archived === "boolean"
    && time(v.created_at) && time(v.updated_at) && one(v.readiness, ["ready", "paused", "archived", "target_missing", "key_unavailable", "policy_changed", "owner_missing", "configuration_invalid"])
    && integer(v.suppressed_count) && nullableTime(v.last_suppressed_at) && str(v.notice));
  if (v.enabled) check(hash(v.target_fingerprint) && v.archived === false);
  if (v.readiness === "ready") check(v.enabled === true && v.archived === false);
}
function delivery(v: unknown, detail: boolean) {
  check(exact(v, detail ? [...summaryKeys, "schema", "body", "attempt_history", "current"] : summaryKeys));
  check(id(v.id) && id(v.webhook_id) && integer(v.webhook_revision, 1) && one(v.channel, channels) && id(v.notification_id) && id(v.event_id) && scopedDomain(v.channel, v.domain)
    && one(v.state, ["pending", "inflight", "delivered", "failed", "blocked", "cancelled"]) && integer(v.attempts, 0, 20) && integer(v.max_attempts, 5, 20) && v.max_attempts >= v.attempts
    && nullableTime(v.next_attempt_at) && time(v.created_at) && nullableTime(v.completed_at) && error(v.error_code) && status(v.http_status) && hash(v.body_sha256));
  if (!detail) return;
  check(v.schema === "webhook-delivery@1" && v.current === false && Array.isArray(v.attempt_history) && v.attempt_history.length === v.attempts);
  const body = v.body;
  check(exact(body, ["schema", "delivery_id", "channel", "notification_id", "event_id", "domain", "occurred_at", "data_scope", "notice"])
    && body.schema === "tire-webhook-event@1" && body.delivery_id === v.id && body.channel === v.channel && body.notification_id === v.notification_id && body.event_id === v.event_id && body.domain === v.domain
    && time(body.occurred_at) && body.data_scope === "notification_reference_only" && str(body.notice));
  v.attempt_history.forEach((attempt, index) => check(exact(attempt, ["number", "started_at", "completed_at", "state", "error_code", "http_status"])
    && attempt.number === index + 1 && time(attempt.started_at) && nullableTime(attempt.completed_at) && one(attempt.state, ["inflight", "delivered", "retryable_failure", "failed", "blocked", "unknown", "cancelled"])
    && error(attempt.error_code) && status(attempt.http_status)));
}
export function assertWebhookDelivery(v: unknown): asserts v is WebhookDelivery { delivery(v, true); }
export function assertWebhookDeliverySummary(v: unknown): void { delivery(v, false); }
async function bodyHash(v: WebhookDelivery) {
  const canonical = JSON.stringify(Object.fromEntries(Object.keys(v.body).sort().map(k => [k, (v.body as unknown as Obj)[k]])));
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical));
  check(Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, "0")).join("") === v.body_sha256);
}
export { bodyHash as verifyWebhookBodyHash };
export function assertWebhookOperation(v: unknown): asserts v is WebhookOperation {
  check(exact(v, ["schema", "id", "idempotency_key", "action", "created_at", "resource_type", "resource_id", "response", "current", "replayed"])
    && v.schema === "webhook-operation@1" && id(v.id) && uuid(v.idempotency_key) && time(v.created_at) && id(v.resource_id) && v.current === false && typeof v.replayed === "boolean");
  if (v.resource_type === "webhook") { check(one(v.action, ["create", "edit", "pause", "resume", "archive", "restore"])); assertWebhook(v.response); }
  else { check(v.resource_type === "delivery" && one(v.action, ["retry", "cancel"])); assertWebhookDelivery(v.response); }
  check(v.resource_id === v.response.id);
}
function settings(v: Obj) {
  check(str(v.name, 120) && fingerprint(v.target_fingerprint) && channelList(v.channels) && typeof v.enabled === "boolean" && typeof v.acknowledged_external_delivery === "boolean");
  if (v.enabled) check(hash(v.target_fingerprint) && v.acknowledged_external_delivery === true);
}
function page(v: unknown, schema: string, validate: (item: unknown) => void, expectedOffset: number, expectedLimit: number) {
  check(exact(v, ["schema", "items", "total", "limit", "offset"]) && v.schema === schema && Array.isArray(v.items) && integer(v.total) && v.limit === expectedLimit && v.offset === expectedOffset && v.items.length <= expectedLimit);
  v.items.forEach(validate); check(v.total >= v.items.length && unique(v.items.map(item => (item as Obj).id)));
}
const encoded = (v: string) => { check(id(v)); return encodeURIComponent(v); };
const paging = (offset: number, limit: number) => { check(integer(offset, 0, 10000) && integer(limit, 1, 100)); return new URLSearchParams({ mode: "history", limit: String(limit), offset: String(offset) }); };

/** Uses shared no-store transport. Never retries a write or dispatches from a GET. */
export function createWebhooksApi(send: Send) {
  async function write(path: string, method: string, payload: unknown, key: string, action: WebhookAction, signal?: AbortSignal, resourceId?: string) {
    check(uuid(key));
    const value = await send<unknown>(path, { method, headers: { "Idempotency-Key": key }, body: JSON.stringify(payload), signal });
    assertWebhookOperation(value); check(value.idempotency_key === key && value.action === action && (!resourceId || value.resource_id === resourceId));
    if (value.resource_type === "delivery") await bodyHash(value.response);
    return value;
  }
  return {
    webhookTargets: async (signal?: AbortSignal) => { const v = await send<unknown>("/v1/webhooks/targets", { signal }); assertWebhookTargets(v); return v; },
    webhooks: async (offset = 0, limit = 20, signal?: AbortSignal) => { const v = await send<unknown>(`/v1/webhooks?${paging(offset, limit)}`, { signal }); page(v, "webhooks@1", assertWebhook, offset, limit); return v as unknown as WebhookList; },
    webhook: async (id: string, signal?: AbortSignal) => { const v = await send<unknown>(`/v1/webhooks/${encoded(id)}?mode=history`, { signal }); assertWebhook(v); check(v.id === id); return v; },
    createWebhook: async (payload: WebhookCreate, key: string, signal?: AbortSignal): Promise<WebhookOperation> => {
      check(exact(payload, [...settingKeys, "target_id"]) && id(payload.target_id)); settings(payload);
      const v = await write("/v1/webhooks", "POST", payload, key, "create", signal);
      check(v.resource_type === "webhook" && v.response.revision === 1 && v.response.target_id === payload.target_id && v.response.target_fingerprint === payload.target_fingerprint
        && v.response.name === payload.name.trim() && v.response.enabled === payload.enabled && !v.response.archived && v.response.channels.length === payload.channels.length && v.response.channels.every(c => payload.channels.includes(c)));
      return v;
    },
    editWebhook: async (id: string, payload: WebhookEdit, key: string, signal?: AbortSignal): Promise<WebhookOperation> => {
      check(exact(payload, [...settingKeys, "expected_revision"]) && integer(payload.expected_revision, 1)); settings(payload);
      const v = await write(`/v1/webhooks/${encoded(id)}`, "PUT", payload, key, "edit", signal, id);
      check(v.resource_type === "webhook" && v.response.revision === payload.expected_revision + 1 && v.response.target_fingerprint === payload.target_fingerprint && v.response.name === payload.name.trim()
        && v.response.enabled === payload.enabled && !v.response.archived && v.response.channels.length === payload.channels.length && v.response.channels.every(c => payload.channels.includes(c)));
      return v;
    },
    webhookState: async (id: string, payload: WebhookStateRequest, key: string, signal?: AbortSignal): Promise<WebhookOperation> => {
      check(exact(payload, ["expected_revision", "action", "target_fingerprint", "acknowledged_external_delivery"]) && integer(payload.expected_revision, 1) && one(payload.action, ["pause", "resume", "archive", "restore"]) && fingerprint(payload.target_fingerprint) && typeof payload.acknowledged_external_delivery === "boolean");
      if (payload.action === "resume") check(hash(payload.target_fingerprint) && payload.acknowledged_external_delivery === true);
      const v = await write(`/v1/webhooks/${encoded(id)}/state`, "POST", payload, key, payload.action, signal, id);
      check(v.resource_type === "webhook" && v.response.revision === payload.expected_revision + 1 && v.response.enabled === (payload.action === "resume") && v.response.archived === (payload.action === "archive"));
      if (payload.action === "resume") check(v.response.target_fingerprint === payload.target_fingerprint);
      return v;
    },
    webhookDeliveries: async (id: string, offset = 0, limit = 20, signal?: AbortSignal) => {
      const v = await send<unknown>(`/v1/webhooks/${encoded(id)}/deliveries?${paging(offset, limit)}`, { signal });
      page(v, "webhook-deliveries@1", item => { delivery(item, false); check((item as Obj).webhook_id === id); }, offset, limit); return v as unknown as WebhookDeliveryList;
    },
    webhookDelivery: async (id: string, deliveryId: string, signal?: AbortSignal) => {
      const v = await send<unknown>(`/v1/webhooks/${encoded(id)}/deliveries/${encoded(deliveryId)}?mode=history`, { signal }); assertWebhookDelivery(v); check(v.id === deliveryId && v.webhook_id === id); await bodyHash(v); return v;
    },
    webhookDeliveryAction: async (id: string, deliveryId: string, action: "retry" | "cancel", payload: WebhookDeliveryActionRequest, key: string, signal?: AbortSignal): Promise<WebhookOperation> => {
      check(one(action, ["retry", "cancel"]) && exact(payload, ["expected_attempts", "acknowledged"]) && integer(payload.expected_attempts, 0, 20) && payload.acknowledged === true);
      const v = await write(`/v1/webhooks/${encoded(id)}/deliveries/${encoded(deliveryId)}/${action}`, "POST", payload, key, action, signal, deliveryId); check(v.resource_type === "delivery" && v.response.webhook_id === id); return v;
    },
    webhookOperation: async (key: string, signal?: AbortSignal) => {
      check(uuid(key)); const v = await send<unknown>(`/v1/webhook-operations?${new URLSearchParams({ mode: "history", key })}`, { signal });
      assertWebhookOperation(v); check(v.idempotency_key === key && v.replayed === true); if (v.resource_type === "delivery") await bodyHash(v.response); return v;
    },
  };
}
