import type { WebhookChannel, WebhookDelivery, WebhookDeliverySummary } from "./webhooks";

export type ApiKeyScope = "sources:read" | "webhooks:read" | "facts:read";
export interface ApiKeyRecord {
  schema: "api-key@1"; id: string; name: string; scopes: ApiKeyScope[];
  created_at: string; expires_at: string; revoked_at: string | null;
}
export interface ApiKeyCreate { name: string; scopes: ApiKeyScope[]; expires_in_days: number; acknowledged: true }
/** A frozen write result. Only the first successful create response contains a token. */
export interface ApiKeyOperation {
  schema: "api-key-operation@1"; idempotency_key: string; action: "create" | "revoke";
  key: ApiKeyRecord; token: string | null; replayed: boolean;
}
export interface ApiKeyList { schema: "api-keys@1"; items: ApiKeyRecord[] }
export interface ActiveApiKeys { schema: "active-api-keys@1"; items: ApiKeyRecord[]; read_at: string }
/** Bounded keyset window; revocation metadata is read separately for each page. */
export interface ApiKeyHistory {
  schema: "api-key-history@1"; items: ApiKeyRecord[]; limit: number; next_cursor: string | null;
  window_started_at: string; read_at: string;
}
export interface ApiKeyHistoryRequest { limit?: number; cursor?: string; signal?: AbortSignal }
export interface ExternalSource {
  id: string; name: string | null; source_class: string | null;
  region: string | null; parser_version: string | null; status: string | null;
}
export interface ExternalPage<T> {
  schema: "external-sources@1" | "external-webhook-deliveries@1";
  items: T[]; next_cursor: string | null; limit: number; data_state: "local_snapshot";
}
export interface ExternalPageRequest { limit?: number; cursor?: string; signal?: AbortSignal }
export interface ExternalDeliveryRequest extends ExternalPageRequest { channel?: WebhookChannel; webhook_id?: string }
export type ExternalSources = ExternalPage<ExternalSource> & { schema: "external-sources@1" };
export type ExternalDeliveries = ExternalPage<WebhookDeliverySummary> & { schema: "external-webhook-deliveries@1" };
export type ExternalDelivery = WebhookDelivery;

export interface ExternalTireFactRequest {
  source_id: string; query_id: string; verification_id: string; variant_id: string; signal?: AbortSignal;
}
export type ExternalTireFactKey = "utqg_treadwear" | "utqg_traction" | "utqg_temperature"
  | "eu_fuel_class" | "eu_wet_grip" | "eu_external_noise_db" | "eu_noise_class" | "weight_kg" | "tread_depth";
export type ExternalTireFactGrade = "A" | "B" | "C" | "D" | "E" | "F" | "G";
export interface ExternalTireFacts {
  utqg_treadwear?: number | null;
  utqg_traction?: "AA" | "A" | "B" | "C" | null;
  utqg_temperature?: "A" | "B" | "C" | null;
  eu_fuel_class?: ExternalTireFactGrade | null;
  eu_wet_grip?: ExternalTireFactGrade | null;
  eu_external_noise_db?: number | null;
  eu_noise_class?: "A" | "B" | "C" | null;
  weight_kg?: number | null;
  tread_depth?: { value: number; unit: "mm" | "1/32 in" | "in" } | null;
}
export interface ExternalTireFactIdentityValues {
  brand: string; model: string; region: string;
  manufacturer_product_code: string | null; product_code_type: string | null; size: string;
  load_index: string | null; speed_rating: string | null; xl: boolean | null; hl: boolean | null;
  run_flat: boolean | null; oe_mark: string | null; acoustic_technology: string | null;
  gtin: string | null; technology_features: string[] | null; eprel_id: string | null;
}
export type ExternalTireFactCompleteIdentityValues = ExternalTireFactIdentityValues & {
  manufacturer_product_code: string; product_code_type: string; load_index: string; speed_rating: string;
  xl: boolean; hl: boolean; run_flat: boolean; oe_mark: string; acoustic_technology: string;
};
export type ExternalTireFactIdentity = { variant_id: string; contract_version: "variant-identity@2" } & (
  { status: "complete"; values: ExternalTireFactCompleteIdentityValues }
  | { status: "source_scoped"; values: ExternalTireFactIdentityValues }
);
/** One permitted local observation; omitted facts and explicit null remain distinct. */
export interface ExternalTireFactProjection {
  schema: "external-tire-fact-projection@1"; data_state: "local_snapshot"; source_refresh_performed: false;
  observation: { source_id: string; snapshot_id: string; raw_hash: string; parser_version: string };
  identity: ExternalTireFactIdentity; facts: ExternalTireFacts; conflicted_fields: ExternalTireFactKey[];
}
export interface ExternalTireFactResult {
  status: "projected"; reason: "projected"; item: ExternalTireFactProjection;
}

/** One fixed owned Q/V window; the cursor never replaces current authorization. */
export interface ExternalTireFactPageRequest {
  source_id: string; query_id: string; verification_id: string;
  limit?: number; cursor?: string; signal?: AbortSignal;
}
export interface ExternalTireFactPage {
  schema: "external-tire-fact-page@1"; items: ExternalTireFactProjection[];
  next_cursor: string | null; limit: number; data_state: "local_snapshot";
  source_refresh_performed: false;
}
