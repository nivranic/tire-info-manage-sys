import type { DeviceFallbackPolicyMode, DeviceFallbackPolicyScope, DeviceFallbackQueryKind, DeviceFallbackSourceSelection } from "./device-fallback";
export interface WarehouseFallbackPolicyPreviewRequest {
  mode: DeviceFallbackPolicyMode;
  scope: DeviceFallbackPolicyScope;
  expires_in_seconds?: number;
  policy_id?: string | null;
  expected_revision?: number;
}
export interface WarehouseFallbackPolicy {
  schema: "query-fallback-policy@1";
  layer: "canonical_warehouse";
  id: string;
  revision: number;
  state: "enabled" | "paused" | "revoked";
  mode: DeviceFallbackPolicyMode;
  audience: "programmatic";
  owner_scope_id: string;
  scope: DeviceFallbackPolicyScope;
  approved_at: string;
  expires_at: string;
  updated_at: string;
  reason: string | null;
  fingerprint: string;
}
export interface WarehouseFallbackPolicyPreview {
  schema: "query-fallback-policy-preview@1";
  preview_id: string;
  fingerprint: string;
  expires_at: string;
  expected_revision: number;
  owner_scope_id: string;
  proposed_policy: Omit<WarehouseFallbackPolicy, "fingerprint" | "approved_at" | "updated_at"> & { approved_at: null; updated_at: null };
  source_metadata: (DeviceFallbackSourceSelection & { fingerprint: string })[];
  notice: string;
}
export interface WarehouseFallbackPolicyApplyRequest { preview_id: string; expected_fingerprint: string; expected_revision: number; allow_continuous_history_fallback: true }
export interface WarehouseFallbackPolicyList { schema: "query-fallback-policy-list@1"; scope: "current_session"; audience: "programmatic"; items: WarehouseFallbackPolicy[] }
export interface WarehouseFallbackUse {
  schema: "query-fallback-use@1";
  id: string;
  policy_id: string;
  policy_revision: number;
  query_id: string;
  query_kind: DeviceFallbackQueryKind;
  audience: "programmatic";
  data_state: "local_snapshot";
  reason: "upstream_network_error" | "upstream_timeout";
  criteria_fingerprint: string;
  claimed_at: string;
  expires_at: string;
  scope: "policy_once";
}
export interface WarehouseFallbackAuthorization { type: "policy_once"; use: WarehouseFallbackUse }
