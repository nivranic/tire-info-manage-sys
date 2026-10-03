export interface FieldPolicy { version: string; digest: string }

export type FieldResolutionState = "uncontested" | "conflict_preferred" | "conflict_tied" | "unknown" | "unavailable";
export type FieldResolutionScope = "history" | "compare" | "current_source" | "accepted_heads" | "selected_evidence";

export interface FieldCandidate {
  id: string; variant_id: string; source_id: string; source_name: string; source_class: string; source_region: string | null;
  field: string; source_field: string; present: boolean; value: unknown;
  snapshot_id: string | null; fact_version_id: string | null; source_url: string; raw_hash: string | null;
  parser_version: string | null; observed_at: string | null; verified_at: string | null; published_at: string | null;
  evidence_locator: unknown; identity_match: string; region_match: string;
  evidence_valid: boolean; missing_evidence: string[]; source_conflicted: boolean;
  equivalence_event_id?: string | null; curation_field?: string | null;
  eligible: boolean; exclusion_reasons: string[];
  authority: { tier: number | null; rule: string; explanation: string };
  dimensions: {
    authority: FieldCandidate["authority"];
    identity: { match: string; explanation: string };
    region: { match: string; source_region: string | null; explanation: string };
    time: { ranked_at: string | null; basis: "published_at" | "observed_at" | "unknown"; verified_at: string | null; verification_used_for_rank: false };
    evidence: { valid: boolean; missing: string[]; explanation: string };
  };
}

export interface FieldDecision {
  field: string; label: string; unit: string | null; category: string; identity_bound: boolean; source_scope_only: boolean; state: FieldResolutionState;
  has_default: boolean; default_value: unknown; default_candidate_ids: string[];
  candidates: FieldCandidate[]; reasons: string[];
}

export interface FieldResolution {
  policy: FieldPolicy; variant_id: string; scope: FieldResolutionScope; data_state: string;
  fields: FieldDecision[]; fingerprint: string; notice: string;
}

export interface FieldPolicyDefinition {
  field: string; canonical_field: string; label: string; unit: string | null;
  category: string; identity_bound: boolean; source_scope_only: boolean;
}

export interface FieldPolicyCatalog {
  policy: FieldPolicy; fields: FieldPolicyDefinition[];
  information_categories: { id: string; label: string; source_tiers: Record<string, number>; projection_available: boolean }[];
  criteria: string[]; coverage: string; notice: string;
  [key: string]: unknown;
}

export interface FieldConflictPage {
  data_state: "local_snapshot"; scope: "history"; policy: FieldPolicy;
  items: FieldResolution[]; offset: number; limit: number; total: number;
  filters: { field: string | null; source_id: string | null }; notice: string;
}
