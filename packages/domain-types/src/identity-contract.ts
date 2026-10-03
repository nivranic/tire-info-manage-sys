export interface IdentityContract {
  schema: "variant-identity@2";
  state: "current" | "legacy_unbound" | "legacy_needs_review";
  current_key: string | null; current_identity: Record<string, unknown> | null;
  identity_status: string | null; origin: string | null; reason_codes: string[];
  related_candidates: { variant_id: string; relationship: "unconfirmed_legacy" | "unconfirmed_current"; product_code_type: string | null }[];
  tracking_state: "current" | "identity_review_required"; notice: string;
}
export interface IdentityMigrationSummary {
  legacy_total: number; eligible: number; needs_review: number; already_bound: number;
  watch_risk_count: number; rule_risk_count: number;
}
export interface IdentityMigrationAssessment {
  variant_id: string; state: "eligible" | "needs_review" | "already_bound"; reason_codes: string[];
  current_identity: Record<string, unknown> | null; current_key: string | null; identity_status: string | null;
  proof_fingerprint: string; affected_watch_count: number; affected_rule_count: number;
}
export interface IdentityMigrationPreview {
  scope: "local_workspace"; data_state: "local_snapshot"; schema: "variant-identity@2"; contract_digest: string;
  revision: number; preview_fingerprint: string; summary: IdentityMigrationSummary;
  items: IdentityMigrationAssessment[]; can_apply: boolean; notice: string;
}
export interface IdentityMigrationApply {
  mode: "history"; schema: "variant-identity@2"; expected_revision: number; expected_preview_fingerprint: string;
  acknowledged: true; operator: string; reason: string;
}
export interface IdentityMigrationApplication {
  id: string; revision: number; schema: "variant-identity@2"; contract_digest: string; preview_fingerprint: string;
  summary: IdentityMigrationSummary; assessments: IdentityMigrationAssessment[]; binding_ids: string[];
  fingerprint: string; operator: string; reason: string; created_at: string; idempotent_replay: boolean; current_revision: number;
}
