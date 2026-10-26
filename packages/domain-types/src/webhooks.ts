import type { InterestDomain } from "./interests";

export type WebhookChannel = "tire_monitor" | "recall_monitor" | "interest";
export type WebhookReadiness = "ready" | "paused" | "archived" | "target_missing" | "key_unavailable" | "policy_changed" | "owner_missing" | "configuration_invalid";
export type WebhookDeliveryState = "pending" | "inflight" | "delivered" | "failed" | "blocked" | "cancelled";
export type WebhookAttemptState = "inflight" | "delivered" | "retryable_failure" | "failed" | "blocked" | "unknown" | "cancelled";
export type WebhookAction = "create" | "edit" | "pause" | "resume" | "archive" | "restore" | "retry" | "cancel";
export interface WebhookTarget {
  id: string; title: string; endpoint_host: string; ready: boolean;
  state: "ready" | "key_unavailable"; policy_fingerprint: string | null;
}
export interface WebhookTargets {
  schema: "webhook-targets@1"; catalog_state: "empty" | "ready" | "invalid";
  items: WebhookTarget[]; notice: string;
}
export interface WebhookSettings {
  name: string; target_fingerprint: string | null; channels: WebhookChannel[];
  enabled: boolean; acknowledged_external_delivery: boolean;
}
export interface WebhookCreate extends WebhookSettings { target_id: string }
export interface WebhookEdit extends WebhookSettings { expected_revision: number }
export interface WebhookStateRequest {
  expected_revision: number; action: "pause" | "resume" | "archive" | "restore";
  target_fingerprint: string | null; acknowledged_external_delivery: boolean;
}
export interface Webhook {
  schema: "webhook@1"; id: string; owner_scope: "current_account";
  revision: number; revision_id: string; name: string; target_id: string;
  target_fingerprint: string | null; endpoint_host: string; channels: WebhookChannel[];
  enabled: boolean; archived: boolean; created_at: string; updated_at: string;
  readiness: WebhookReadiness; suppressed_count: number; last_suppressed_at: string | null; notice: string;
}
export interface WebhookList { schema: "webhooks@1"; items: Webhook[]; total: number; limit: number; offset: number }
/** Only references leave the application; this is not a source-fact export. */
export interface WebhookBody {
  schema: "tire-webhook-event@1"; delivery_id: string; channel: WebhookChannel;
  notification_id: string; event_id: string; domain: InterestDomain | null;
  occurred_at: string; data_scope: "notification_reference_only"; notice: string;
}
export interface WebhookDeliverySummary {
  id: string; webhook_id: string; webhook_revision: number; channel: WebhookChannel;
  notification_id: string; event_id: string; domain: InterestDomain | null;
  state: WebhookDeliveryState; attempts: number; max_attempts: number;
  next_attempt_at: string | null; created_at: string; completed_at: string | null;
  error_code: string | null; http_status: number | null; body_sha256: string;
}
export interface WebhookAttempt {
  number: number; started_at: string; completed_at: string | null;
  state: WebhookAttemptState; error_code: string | null; http_status: number | null;
}
export interface WebhookDelivery extends WebhookDeliverySummary {
  schema: "webhook-delivery@1"; body: WebhookBody; attempt_history: WebhookAttempt[]; current: false;
}
export interface WebhookDeliveryList { schema: "webhook-deliveries@1"; items: WebhookDeliverySummary[]; total: number; limit: number; offset: number }
export interface WebhookDeliveryActionRequest { expected_attempts: number; acknowledged: true }
interface WebhookOperationBase {
  schema: "webhook-operation@1"; id: string; idempotency_key: string;
  created_at: string; resource_id: string; current: false; replayed: boolean;
}
/** Frozen action result; current resource state must be read separately. */
export type WebhookOperation = WebhookOperationBase & (
  { action: Exclude<WebhookAction, "retry" | "cancel">; resource_type: "webhook"; response: Webhook }
  | { action: "retry" | "cancel"; resource_type: "delivery"; response: WebhookDelivery }
);
