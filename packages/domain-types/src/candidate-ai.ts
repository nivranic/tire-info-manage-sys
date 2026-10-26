import type { DrivingWeights } from "./index";
import type { FitmentCandidateSelection } from "./personalization";

/** Independent C specification assistance; no test, streaming or report contract. */
export type CandidateAiValue = string | number | boolean | null | (string | number | boolean | null)[];
export interface CandidateAiPrepareRequest {
  selection: FitmentCandidateSelection;
  expected_preference_revision: number;
  expected_preference_fingerprint: string;
  variant_ids: string[];
  question: string;
}
export interface CandidateAiReason {
  id: string;
  text: string;
  reference: {
    variant_id: string;
    relation_id: string;
    relation_revision_id: string;
    relation_revision: number;
    selection: FitmentCandidateSelection;
    field: string;
    status: "match";
    value: CandidateAiValue;
  };
}
export interface CandidateAiCandidate {
  variant_id: string;
  identity: Record<string, CandidateAiValue>;
  reasons: CandidateAiReason[];
  unknown_fields: string[];
}
export interface CandidateAiAuthorizationHead {
  state: "granted" | "revoked" | "expired";
  revision_id: string;
  revision: number;
  expires_at: string;
}
export interface CandidateAiDependency {
  id: string;
  source_kind: "vehicle" | "tire" | "relation";
  snapshot_id: string;
  raw_hash: string;
  projection_hash: string;
  fields: string[];
  authorization: CandidateAiAuthorizationHead | null;
}
export interface CandidateAiPreparation {
  schema: "candidate-ai-preparation@1";
  purpose: "candidate_spec_assistance@1";
  preparation_id: string;
  pack_id: string;
  fingerprint: string;
  selection: FitmentCandidateSelection;
  preference: { revision: number; fingerprint: string; weights: DrivingWeights | null };
  candidates: CandidateAiCandidate[];
  dependencies: CandidateAiDependency[];
  blockers: string[];
  provider: {
    provider: string;
    model: string;
    endpoint_host: string;
    state: "configured";
    policy_fingerprint: string;
    body_hash: string;
    reserved_tokens: number;
  } | null;
  consent_hash: string | null;
  expires_at: string;
  sendable: boolean;
}
interface CandidateAiAuthorizationCommand {
  dependency_id: string;
  provider: string;
  expected_revision: number;
  acknowledged: true;
}
export type CandidateAiAuthorizationRequest = CandidateAiAuthorizationCommand & ({
  action: "grant";
  rights_holder: string;
  license_basis_url: string;
  license_basis_note: string;
  license_evidence_sha256: string;
  expires_at: string;
} | {
  action: "revoke";
  revocation_note: string;
});
export interface CandidateAiAuthorization {
  schema: "candidate-ai-authorization@1";
  purpose: "candidate_spec_assistance@1";
  dependency_id: string;
  provider: string;
  state: "granted" | "revoked" | "expired";
  revision_id: string;
  revision: number;
  recipient_fingerprint: string | null;
  rights_holder: string;
  license_basis_url: string;
  license_basis_note: string;
  license_evidence_sha256: string;
  expires_at: string;
}
export interface CandidateAiSubmitRequest {
  preparation_id: string;
  consent_hash: string;
  allow_external_processing: true;
}
export type CandidateAiUncertaintyCode = "performance_evidence_unavailable" | "installation_safety_unestablished" | "official_oe_unestablished" | "insufficient_spec_evidence" | "no_supported_selection" | "preference_performance_unestablished";
export interface CandidateAiAnswer {
  decision: "choose" | "abstain";
  selections: { variant_id: string; reasons: CandidateAiReason[] }[];
  not_selected_variant_ids: string[];
  uncertainty: { code: CandidateAiUncertaintyCode; text: string }[];
  ranking: "not_computed";
  performance_score: null;
  performance_evidence: "not_established";
  notice: string;
}
export interface CandidateAiRecommendation {
  schema: "candidate-ai-recommendation@1";
  id: string;
  pack_id: string;
  state: "pending" | "outcome_unknown" | "completed" | "failed";
  usage: { input_tokens: number; output_tokens: number; total_tokens: number } | null;
  reserved_tokens: number;
  error_code: string | null;
  created_at: string;
  completed_at: string | null;
  purpose: "candidate_spec_assistance@1";
  answer: CandidateAiAnswer | null;
  current: false;
  preparation: CandidateAiPreparation;
  current_status: { state: "unchanged" | "stale"; blockers: string[] };
}
