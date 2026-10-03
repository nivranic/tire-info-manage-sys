import type { TireFilter, TireQuerySelection } from "./filters";
import type { LocalFallbackFailure } from "./local-fallback";
import type { OfflineMember, OfflineSlot, ResolvedOfflineReference } from "./offline-packs";
import type { OfflineMemberV2, OfflinePackSchema } from "./offline-packs-v2";

/** @2 is explicit. None of these types changes the @1 caller-observed contract. */
export type DeviceFallbackQueryKind = "tire" | "vehicle_fitments" | "recall_campaign" | "recall_search";
export type DeviceFallbackPolicyMode = "ask" | "never" | "session_allow" | "source_allow" | "query_allow";
export type DeviceFallbackCanonicalTireQuery = { model: string; size?: string } | { size: string; model?: string };
export interface DeviceFallbackCanonicalVehicleQuery { vehicle_id: string }
export interface DeviceFallbackCanonicalRecallQuery { campaign_number: string }
export interface DeviceFallbackCanonicalSearchQuery { search: string; offset: string }

export interface DeviceFallbackSourcePin { source_id: string; access_generation: number }
export interface DeviceFallbackSourceSelection extends DeviceFallbackSourcePin { query_kinds: DeviceFallbackQueryKind[] }
export type DeviceFallbackPolicyScope =
  | { kind: "session"; sources: DeviceFallbackSourceSelection[] }
  | ({ kind: "source" } & DeviceFallbackSourceSelection)
  | { kind: "query"; query_kind: DeviceFallbackQueryKind; sources: DeviceFallbackSourcePin[] };

/** Non-secret metadata from fixed host API reads; this is not a signed capability. */
export interface DeviceFallbackSourceAuthority {
  schema: "device-fallback-source-authority@1";
  runtime_session_id: string;
  authority_revision: number;
  state: "unknown" | "last_observed";
  observed_at: string | null;
  profile_id: string;
  owner_epoch: number;
  owner_scope_id: string | null;
  sources: (DeviceFallbackSourceSelection & { can_query: boolean; can_fetch: boolean })[];
}
export interface DeviceFallbackAuthorityBinding { runtime_session_id: string; authority_revision: number }

interface DeviceFallbackIntentBaseV2 {
  schema: "device-fallback-intent@2";
  attempt_id: string;
  /** Opaque device criteria fingerprint; never recompute a Python QueryRun.query_key. */
  query_fingerprint: string;
  source_id: string;
  source_access_generation: number;
  fallback_policy: "ask" | "never";
  authority: DeviceFallbackAuthorityBinding;
  failure: LocalFallbackFailure;
}
/** Number-token precision is an explicit semantic gate, not a safe-integer API restriction. */
export type DeviceFallbackIntentV2 = DeviceFallbackIntentBaseV2 & (
  | { query_kind: "tire"; query: DeviceFallbackCanonicalTireQuery; filters: TireFilter[] }
  | { query_kind: "vehicle_fitments"; query: DeviceFallbackCanonicalVehicleQuery; filters: [] }
  | { query_kind: "recall_campaign"; query: DeviceFallbackCanonicalRecallQuery; filters: [] }
  | { query_kind: "recall_search"; query: DeviceFallbackCanonicalSearchQuery; filters: [] }
);

export interface DeviceFallbackSlotBindingRequest {
  slot_id: string;
  expected_generation: number;
  expected_sha256: string;
  expected_profile_id: string;
  expected_owner_epoch: number;
}
export interface DeviceFallbackDecideRequestV2 extends DeviceFallbackSlotBindingRequest {
  intent: DeviceFallbackIntentV2;
  decision: "allow" | "deny";
}
export type DeviceFallbackAuthorization =
  | { type: "explicit_once" }
  | { type: "policy_once"; policy_id: string; policy_revision: number };
export interface DeviceFallbackGrantV2 {
  schema: "device-fallback-grant@2";
  id: string;
  scope: "local_once";
  state: "allowed" | "denied" | "consumed" | "revoked";
  fallback_authorization: DeviceFallbackAuthorization;
  intent: DeviceFallbackIntentV2;
  profile_id: string;
  owner_epoch: number;
  slot_id: string;
  generation: number;
  package_sha256: string;
  decided_at: string;
  expires_at: string;
  consumed_at: string | null;
}
export interface DeviceFallbackConsumeRequestV2 { grant_id: string; intent: DeviceFallbackIntentV2 }
/** Native boundary only: raw_json is the exact core object without this transport field. */
export type DeviceFallbackNativeWire<T extends object> = T & { raw_json: string };
export interface DeviceFallbackRevokeRequestV2 { grant_id: string }
export interface DeviceFallbackRevokeResultV2 { revoked: true; grant_id: string }

export interface DeviceFallbackCitationV2 {
  schema: "device-citation@1";
  id: string;
  profile_id: string;
  owner_epoch: number;
  slot_id: string;
  generation: number;
  package_sha256: string;
  member_key: string;
  document_id: string | null;
  record_index: number | null;
  observed_at: string;
  verified_at: string | null;
  verification_id: string | null;
}
interface DeviceFallbackResultBaseV2 {
  schema: "device-fallback-result@2";
  data_state: "local_snapshot";
  fallback_consent: "local_once";
  fallback_authorization: DeviceFallbackAuthorization;
  grant: DeviceFallbackGrantV2 & { state: "consumed"; consumed_at: string };
  slot: OfflineSlot;
  package_schema: OfflinePackSchema;
  citations: DeviceFallbackCitationV2[];
  complete_query_result: false;
  notice: string;
}
export type DeviceFallbackHistoricalMember<Kind extends "tire" | "vehicle" | "recall"> =
  Omit<OfflineMember, "reference"> & { reference: Extract<ResolvedOfflineReference, { kind: Kind }> };
export type DeviceFallbackResultV2 = DeviceFallbackResultBaseV2 & (
  | { query_kind: "tire"; query: DeviceFallbackCanonicalTireQuery; selection: TireQuerySelection; members: DeviceFallbackHistoricalMember<"tire">[] }
  | { query_kind: "vehicle_fitments"; query: DeviceFallbackCanonicalVehicleQuery; selection: null; members: DeviceFallbackHistoricalMember<"vehicle">[] }
  | { query_kind: "recall_campaign"; query: DeviceFallbackCanonicalRecallQuery; selection: null; members: DeviceFallbackHistoricalMember<"recall">[] }
  | { query_kind: "recall_search"; query: DeviceFallbackCanonicalSearchQuery; selection: null; members: Extract<OfflineMemberV2, { reference: { kind: "recall_search" } }>[] }
);

export interface DeviceFallbackPackageBinding {
  binding_revision: number;
  slot_id: string;
  generation: number;
  package_id: string;
  sha256: string;
  /** Saved during approved install/sync; never derived by reading a body in policy preview. */
  history_scope_fingerprint: string;
  source_ids: string[];
}
type DeviceFallbackAllowChoice =
  | { mode: "session_allow"; scope: Extract<DeviceFallbackPolicyScope, { kind: "session" }> }
  | { mode: "source_allow"; scope: Extract<DeviceFallbackPolicyScope, { kind: "source" }> }
  | { mode: "query_allow"; scope: Extract<DeviceFallbackPolicyScope, { kind: "query" }> };
export type DeviceFallbackPolicyChoice =
  | (DeviceFallbackAllowChoice & { binding: DeviceFallbackPackageBinding; allow_same_scope_sync_binding_advance: boolean })
  | { mode: "ask" | "never"; scope: DeviceFallbackPolicyScope; binding: null; allow_same_scope_sync_binding_advance: false };
export type DeviceFallbackPolicy = DeviceFallbackPolicyChoice & {
  schema: "device-fallback-policy@1";
  policy_id: string;
  policy_revision: number;
  state: "enabled" | "paused" | "revoked";
  profile_id: string;
  owner_epoch: number;
  owner_scope_id: string;
  runtime_session_id: string | null;
  approved_at: string;
  updated_at: string;
  expires_at: string;
  fingerprint: string;
  reason: string | null;
};
export type DeviceFallbackPolicyPreviewRequest = DeviceFallbackPolicyChoice & {
  expected_profile_id: string;
  expected_owner_epoch: number;
  authority: DeviceFallbackAuthorityBinding;
  policy_id: string | null;
  expected_policy_revision: number;
  expires_in_seconds: number;
};
export interface DeviceFallbackPolicyPreview {
  schema: "device-fallback-policy-preview@1";
  preview_id: string;
  fingerprint: string;
  expires_at: string;
  policy_expires_at: string;
  expected_policy_revision: number;
  profile_id: string;
  owner_epoch: number;
  authority: DeviceFallbackSourceAuthority;
  proposed_policy: DeviceFallbackPolicyChoice;
  notice: string;
}
export interface DeviceFallbackPolicyApplyRequest {
  preview_id: string;
  expected_fingerprint: string;
  expected_policy_revision: number;
  allow_continuous_history_fallback: true;
}
export interface DeviceFallbackPolicyRequest { policy_id: string; expected_policy_revision: number }
export interface DeviceFallbackAuthorizeRequest extends DeviceFallbackSlotBindingRequest { intent: DeviceFallbackIntentV2 }
export type DeviceFallbackAuthorizeResult =
  | { schema: "device-fallback-authorization@1"; state: "ask"; reason: string; grant: null }
  | { schema: "device-fallback-authorization@1"; state: "blocked"; reason: string; grant: null }
  | { schema: "device-fallback-authorization@1"; state: "allowed"; reason: null; grant: DeviceFallbackGrantV2 & { state: "allowed" } };
export interface DeviceFallbackCapabilities {
  schema: "device-fallback-capabilities@1";
  intent_schemas: ["device-fallback-intent@1", "device-fallback-intent@2"];
  supported_pack_schemas: OfflinePackSchema[];
  query_kinds: DeviceFallbackQueryKind[];
  filter_contract: "tire-query-filters@1";
  unicode_contract: "tire-query-unicode@1";
  continuous_policies: boolean;
  max_filters: 16;
  max_policies: 16;
  max_sources: 10;
  max_pending_grants: 16;
  max_attempts_per_runtime: 1024;
  max_audit_receipts: 64;
  grant_ttl_seconds: 300;
}
export interface DeviceFallbackStatus {
  schema: "device-fallback-status@1";
  profile_id: string;
  owner_epoch: number;
  authority: DeviceFallbackSourceAuthority;
  capabilities: DeviceFallbackCapabilities;
  policies: DeviceFallbackPolicy[];
  package_bindings: DeviceFallbackPackageBinding[];
  missing_package_bindings: { slot_id: string; generation: number; reason: "scope_metadata_missing" }[];
}

/** Additive @2 contract draft; runtime adapters opt in only after strict handlers exist. */
export interface DeviceFallbackStorageV2 {
  fallbackStatus(): Promise<DeviceFallbackStatus>;
  refreshFallbackAuthority(): Promise<DeviceFallbackSourceAuthority>;
  previewFallbackPolicy(request: DeviceFallbackPolicyPreviewRequest): Promise<DeviceFallbackPolicyPreview>;
  applyFallbackPolicy(request: DeviceFallbackPolicyApplyRequest): Promise<DeviceFallbackPolicy>;
  pauseFallbackPolicy(request: DeviceFallbackPolicyRequest): Promise<DeviceFallbackPolicy>;
  revokeFallbackPolicy(request: DeviceFallbackPolicyRequest): Promise<DeviceFallbackPolicy>;
  authorizeFallback(request: DeviceFallbackAuthorizeRequest): Promise<DeviceFallbackAuthorizeResult>;
  decideFallbackV2(request: DeviceFallbackDecideRequestV2): Promise<DeviceFallbackGrantV2>;
  consumeFallbackV2(request: DeviceFallbackConsumeRequestV2): Promise<DeviceFallbackResultV2>;
  revokeFallbackV2(request: DeviceFallbackRevokeRequestV2): Promise<DeviceFallbackRevokeResultV2>;
}
