import type { DrivingWeightKey, DrivingWeights } from "./index";
import type { InterestDomain, InterestEvent, InterestEvidence, InterestMatch } from "./interests";
import type { FitmentOfficialOE, FitmentRelationCheck, FitmentRelationSelection, FitmentTireEvidence, FitmentVehicleEvidence } from "./fitment-relations";

/** Server session decides the owner; limit is the per-page candidate scan budget. */
export interface PersonalFeedRequest { domain?: InterestDomain | null; limit?: number; cursor?: string | null }
export interface PersonalFeedMatch {
  interest_id: string; interest_revision: number; interest_fingerprint: string; interest_name: string;
  match: InterestMatch;
}
export interface PersonalFeedItem {
  state: "matched" | "indeterminate"; event: InterestEvent; matches: PersonalFeedMatch[];
}
export interface PersonalFeed {
  schema: "personal-feed@1"; policy_version: "current-interests-history@1";
  data_state: "local_snapshot"; scope: "actor"; feed_scope: "current_interests_history";
  domain: InterestDomain | null; limit: number; active_interest_count: number;
  items: PersonalFeedItem[]; scanned_count: number; matched_count: number; indeterminate_count: number;
  has_more: boolean; next_cursor: string | null;
  binding: { interests_fingerprint: string; candidates_fingerprint: string }; notices: string[];
}
export type FitmentCandidateSelection = Pick<FitmentRelationSelection,
  "vehicle_id" | "vehicle_snapshot_id" | "trim_id" | "wheel_option_id" | "axle">;
export interface FitmentCandidatesRequest {
  selection: FitmentCandidateSelection; expected_preference_revision: number; expected_preference_fingerprint: string;
}
export interface FitmentCandidateRelation {
  relation_id: string; revision_id: string; revision: number; binding_hash: string;
  selection: FitmentRelationSelection; vehicle_evidence: FitmentVehicleEvidence; tire_evidence: FitmentTireEvidence;
  checks: FitmentRelationCheck[]; unknown_fields: string[]; acknowledged_unknowns: boolean; evidence: InterestEvidence[];
}
export interface FitmentCandidate {
  variant_id: string; identity: Record<string, unknown>; relations: FitmentCandidateRelation[];
  performance_score: null; ranking: "not_computed"; official_oe: FitmentOfficialOE;
}
export interface FitmentCandidateExclusion {
  relation_id: string; revision: number; variant_id: string; effective_state: string; reason_codes: string[];
}
export interface FitmentCandidates {
  schema: "fitment-candidates@1"; policy_version: "reviewed-exact-axle@1";
  data_state: "local_snapshot"; scope: "actor"; evidence_scope: "local_workspace";
  selection: FitmentCandidateSelection;
  vehicle_binding: { snapshot_id: string; current_snapshot_id: string; fact_hash: string; fact_version: number; scope: Record<string, unknown> };
  preference: { revision: number; fingerprint: string; weights: DrivingWeights | null };
  research_focus: { dimension: DrivingWeightKey; weight: number | null; evidence_status: "exact_sku_performance_not_established" }[];
  items: FitmentCandidate[]; excluded_relations: FitmentCandidateExclusion[];
  inspected_count: number; relation_count: number; truncated: boolean;
  ranking: "not_computed"; performance_score: null; official_oe: FitmentOfficialOE; notices: string[];
}
