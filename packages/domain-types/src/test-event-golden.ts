import type { BridgeMaterial, BridgeOpenedMaterial } from "./test-sku-links";
import type { TestEventPayload } from "./index";
import type { GoldenRevisionBinding, GoldenSigned } from "./golden";

/** This contract is separate from tire/vehicle Parser Golden and its RawCapture input. */
export interface TestEventGoldenEventRef {
  event_id: string;
  event_revision_id: string;
  event_fingerprint: string;
}
export interface TestEventGoldenLinkRef {
  participant_key: string;
  link_id: string;
  link_revision_id: string;
  link_fingerprint: string;
}
export interface TestEventGoldenIdentityExpectation {
  participant_key: string;
  truth: "linked" | "not_linked" | "unknown";
  sku_label: string | null;
  expected_variant_id: string | null;
}
export interface TestEventGoldenExpected {
  event: TestEventPayload;
  identity_assertions: TestEventGoldenIdentityExpectation[];
  distinct_pairs: { left_sku_label: string; right_sku_label: string }[];
}
export interface TestEventGoldenMaterial extends Omit<BridgeMaterial, "rights"> {
  rights: BridgeMaterial["rights"] & { quote_test_results: true };
}
export interface TestEventGoldenContent extends GoldenSigned, GoldenRevisionBinding {
  title: string;
  event_ref: TestEventGoldenEventRef;
  materials: TestEventGoldenMaterial[];
  link_refs: TestEventGoldenLinkRef[];
  expected: TestEventGoldenExpected;
  evidence_note: string;
}
export interface TestEventGoldenReviewRequest extends GoldenSigned, GoldenRevisionBinding {
  case_revision: number;
  case_fingerprint: string;
  action: "approve" | "reject" | "revoke";
  acknowledged: true;
  opened_materials: BridgeOpenedMaterial[];
}
export interface TestEventGoldenCaseRef {
  case_id: string;
  case_revision: number;
  case_fingerprint: string;
  review_revision: number;
  review_fingerprint: string;
}
export interface TestEventGoldenSetWrite extends GoldenSigned, GoldenRevisionBinding {
  title: string;
  action: "freeze" | "revoke";
  case_refs: TestEventGoldenCaseRef[];
  acknowledged: true;
}
export interface TestEventGoldenEvaluateRequest {
  expected_set_revision: number;
  expected_set_fingerprint: string;
  target: "frozen_revision" | "current_head";
}
export interface TestEventGoldenBoundary {
  scope: "local_workspace";
  data_state: "local_snapshot";
  accepted_as_facts: false;
  review_identity: "self_reported_local_operator";
  human_truth_status: "pending_external_review";
  provider_use: false;
  export: false;
  [key: string]: unknown;
}
export interface TestEventGoldenPage<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
  boundary?: TestEventGoldenBoundary;
}
export interface TestEventGoldenReview extends GoldenSigned {
  id: string;
  revision: number;
  fingerprint: string;
  case_revision: number;
  case_fingerprint: string;
  action: "approve" | "reject" | "revoke";
  actor_user_id: string;
  created_at: string;
}
export interface TestEventGoldenCaseSummary {
  id: string;
  event_id: string;
  revision_id: string;
  revision: number;
  fingerprint: string;
  title: string;
  review_status: "pending" | "approved" | "rejected" | "revoked";
  review_revision: number;
  review_fingerprint: string | null;
  blockers: string[];
  operator: string;
  reason: string;
  created_at: string;
}
export interface TestEventGoldenCase extends TestEventGoldenCaseSummary {
  event_ref: TestEventGoldenEventRef;
  event_snapshot: TestEventPayload;
  materials: TestEventGoldenMaterial[];
  link_refs: TestEventGoldenLinkRef[];
  expected: TestEventGoldenExpected;
  evidence_note: string;
  operator: string;
  reason: string;
  actor_user_id: string;
  latest_review: TestEventGoldenReview | null;
  recorded_review?: TestEventGoldenReview;
  history: TestEventGoldenCaseSummary[];
  reviews: TestEventGoldenReview[];
  history_truncated: boolean;
  reviews_truncated: boolean;
  is_current: boolean;
  boundary: TestEventGoldenBoundary;
}
export interface TestEventGoldenSetSummary {
  id: string;
  revision: number;
  fingerprint: string;
  title: string;
  action: "freeze" | "revoke";
  state: "frozen" | "revoked";
  case_refs: TestEventGoldenCaseRef[];
  cases: TestEventGoldenCaseSummary[];
  eligible: boolean;
  blockers: string[];
  operator: string;
  reason: string;
  created_at: string;
  boundary: TestEventGoldenBoundary;
}
export interface TestEventGoldenSet extends TestEventGoldenSetSummary {
  history: (GoldenSigned & { id: string; revision: number; fingerprint: string; title: string;
    action: "freeze" | "revoke"; state: "frozen" | "revoked"; created_at: string })[];
  history_truncated: boolean;
}
export interface TestEventGoldenDifference {
  path: string;
  expected: unknown;
  actual: unknown;
  code: string;
}
export interface TestEventGoldenCaseResult {
  case_id: string;
  event_id: string;
  expected_event_revision_id: string;
  actual_event_revision_id: string | null;
  review_status: TestEventGoldenCaseSummary["review_status"];
  eligible: boolean;
  blockers: string[];
  state: "passed" | "failed" | "inconclusive";
  differences: TestEventGoldenDifference[];
  comparison: Record<string, unknown> | null;
  identity_results: Record<string, unknown>[];
  distinct_results: Record<string, unknown>[];
  differences_truncated: boolean;
}
export interface TestEventGoldenEvaluation {
  schema: "test-event-golden-evaluation@1";
  set_id: string;
  set_revision: number;
  set_fingerprint: string;
  target: TestEventGoldenEvaluateRequest["target"];
  state: "passed" | "failed" | "inconclusive";
  case_results: TestEventGoldenCaseResult[];
  observed_wrong_merge_count: number | null;
  checked_distinct_pair_count: number;
  wrong_merge_count: null;
  human_truth_status: "pending_external_review";
  boundary: TestEventGoldenBoundary;
}
