import type { FitmentCandidateSelection, FitmentCandidates } from "./personalization";
import type { TestMetricDimension, TestPreferenceInterpretation } from "./test-preference-interpretation";
import type { BridgeBoundary, TestSkuLinkView } from "./test-sku-links";

/** References identify current revisions; the server derives participants and all evidence. */
export interface TestCandidateReference {
  variant_id: string;
  link_id: string;
  expected_link_revision_id: string;
  expected_link_revision: number;
  expected_link_fingerprint: string;
}

export interface TestCandidateInterpretationRequest {
  selection: FitmentCandidateSelection;
  expected_event_revision_id: string;
  expected_event_revision: number;
  expected_event_fingerprint: string;
  expected_preference_revision: number;
  expected_preference_fingerprint: string;
  candidates: TestCandidateReference[];
  metric_dimensions: TestMetricDimension[];
}

/** Compact current bridge evidence; no management actions or repeated full event payload. */
export type TestCandidateLinkEvidence = Pick<TestSkuLinkView,
  "id" | "revision_id" | "revision" | "fingerprint" | "binding_hash" | "selection" |
  "review_state" | "effective_state" | "eligibility" | "evidence_level" | "materials" |
  "material_evidence" | "assertions" | "checks" | "required_identity_fields" | "unknown_fields" |
  "blockers" | "stale_reasons" | "boundary" | "declaration_revision_id"> & {
    id: string;
    revision_id: string;
    confirmed_event_revision_id: string;
    confirmed_participant_hash: string;
  };

export interface TestCandidateInterpretation {
  schema: "test-candidate-interpretation@1";
  policy_version: "same-event-candidate-interpretation@1";
  data_state: "local_snapshot";
  scope: "actor";
  evidence_scope: "local_workspace";
  comparison_scope: "same_event_only";
  status: "conditional_observations" | "insufficient_evidence";
  ranking: "source_reported_only";
  performance_score: null;
  official_oe: FitmentCandidates["official_oe"];
  boundary: BridgeBoundary;
  selection: FitmentCandidateSelection;
  binding: {
    event: TestPreferenceInterpretation["binding"]["event"];
    preference: TestPreferenceInterpretation["binding"]["preference"];
    candidate_fingerprint: string;
    interpretation_fingerprint: string;
  };
  candidate_projection: FitmentCandidates;
  items: {
    variant_id: string;
    participant_id: string;
    participant_key: string;
    eligible: boolean;
    reason_codes: string[];
    link: TestCandidateLinkEvidence;
  }[];
  requested_count: number;
  eligible_count: number;
  excluded: { variant_id: string; link_id: string; reason_codes: string[] }[];
  reason_codes: string[];
  source_evidence: TestPreferenceInterpretation["source_evidence"];
  personal_interpretation: TestPreferenceInterpretation["personal_interpretation"] | null;
  notices: string[];
}
