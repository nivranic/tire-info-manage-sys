import type { OfflineMember, OfflineSlot } from "./offline-packs";

/** Caller-observed API failure and formal source response remain different evidence scopes. */
export type LocalFallbackFailure =
  | { scope: "api_transport"; reason: "api_network_unavailable" | "api_timeout"; query_id: null }
  | { scope: "source_response"; reason: "upstream_timeout" | "upstream_network_error"; query_id: string };

export interface LocalFallbackIntent {
  schema: "device-fallback-intent@1";
  attempt_id: string;
  query_fingerprint: string;
  source_id: string;
  source_access_generation: number;
  query: { model: string; size: string | null };
  filters: [];
  failure: LocalFallbackFailure;
}

export interface LocalFallbackDecideRequest {
  intent: LocalFallbackIntent;
  slot_id: string;
  expected_generation: number;
  expected_sha256: string;
  expected_profile_id: string;
  expected_owner_epoch: number;
  decision: "allow" | "deny";
}

export interface LocalFallbackGrant {
  schema: "device-fallback-grant@1";
  id: string;
  scope: "local_once";
  state: "allowed" | "denied" | "consumed" | "revoked";
  intent: LocalFallbackIntent;
  profile_id: string;
  owner_epoch: number;
  slot_id: string;
  generation: number;
  package_sha256: string;
  decided_at: string;
  expires_at: string;
  consumed_at: string | null;
}

export interface LocalFallbackConsumeRequest { grant_id: string; intent: LocalFallbackIntent }
export interface LocalFallbackRevokeRequest { grant_id: string }
export interface LocalFallbackRevokeResult { revoked: true; grant_id: string }
export interface LocalFallbackResult {
  schema: "device-fallback-result@1";
  data_state: "local_snapshot";
  fallback_consent: "local_once";
  grant: LocalFallbackGrant & { state: "consumed"; consumed_at: string };
  slot: OfflineSlot;
  members: OfflineMember[];
  complete_query_result: false;
  notice: string;
}
