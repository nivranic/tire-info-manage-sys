export interface IdentityResolution {
  state: "independent" | "cleared" | "redirected" | "needs_review";
  revision: number; target_id: string | null; event_id: string | null;
  action?: "correct" | "merge" | "clear"; changed_at?: string; notice?: string;
}
export interface IdentityEndpoint {
  identity_contract?: import("./identity-contract").IdentityContract;
  id: string; identity: Record<string, unknown>; identity_status: string;
  facts: { id: string; source_id: string; version: number; snapshot_id: string }[];
  lifecycle: { revision: number; state: "active" | "revoked" };
}
export interface IdentityDifference {
  field: string; before: { present: boolean; value: unknown }; after: { present: boolean; value: unknown };
}
export interface IdentityBinding { source: IdentityEndpoint; target: IdentityEndpoint | null; target_resolution_revision: number }
export interface IdentityPreview {
  data_state: "local_snapshot"; binding: IdentityBinding; revision: number; fingerprint: string;
  differences: IdentityDifference[]; unknown_fields: string[]; stable_anchors: string[]; known_contradictions: string[];
  blockers: string[]; can_merge: boolean; can_correct: boolean; can_clear: boolean; notice: string;
}
export interface IdentityDecision {
  mode: "history"; action: "correct" | "merge" | "clear"; target_id: string | null;
  expected_revision: number; expected_fingerprint: string; operator: string; reason: string;
  field_reasons: Record<string, string>; acknowledge_unknowns: boolean; acknowledged: boolean;
  evidence: { snapshot_id: string; locator: string }[];
}
export interface IdentityRevision {
  id: string; variant_id: string; target_id: string | null; revision: number; action: IdentityDecision["action"];
  binding: IdentityBinding; binding_hash: string; differences: IdentityDifference[]; field_reasons: Record<string, string>;
  acknowledged_unknowns: boolean; operator: string; reason: string; created_at: string;
  evidence: { snapshot_id: string; raw_hash: string; locator: string; variant_ids: string[]; source_id: string; observed_at: string }[];
}
export interface IdentityReview {
  data_state: "local_snapshot"; scope: "local_workspace"; source: IdentityEndpoint; resolution: IdentityResolution;
  history: IdentityRevision[]; history_truncated: boolean;
  incoming: (IdentityResolution & { variant_id: string })[]; incoming_truncated: boolean; notice: string;
}
export interface IdentityMapping { requested_id: string; resolved_id: string; revision: number; event_id: string | null }
export interface IdentityCandidates {
  items: { id: string; identity: Record<string, unknown>; identity_status: string; identity_resolution?: IdentityResolution; identity_contract?: import("./identity-contract").IdentityContract }[];
  total: number; offset: number; limit: number;
}
export interface IdentityDecisionResult { event: IdentityRevision; review: IdentityReview; idempotent_replay: boolean }
