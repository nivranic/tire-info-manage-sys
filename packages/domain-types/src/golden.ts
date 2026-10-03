import type { ReparseInput, VehicleDescription, VehicleTrim, WheelFitment } from "./index";

export type GoldenKind = "tire" | "vehicle";
/** Complete parser input shape. Unknown identity attributes stay null, never false. */
export interface GoldenVariantInput {
  brand: string; model: string; manufacturer_product_code: string | null; region: string; size: string;
  load_index: string | null; speed_rating: string | null; xl: boolean | null; hl: boolean | null;
  oe_mark: string | null; acoustic_technology: string | null; run_flat: boolean | null;
  source_variant_name: string | null; facts: Record<string, unknown>;
}
export interface GoldenTireExpected { records: { golden_sku_id: string; value: GoldenVariantInput }[] }
export interface GoldenVehicleExpected { vehicle: VehicleDescription; trims: VehicleTrim[]; fitments: WheelFitment[] }
export type GoldenExpected = GoldenTireExpected | GoldenVehicleExpected;
export interface GoldenSigned { operator: string; reason: string }
export interface GoldenRevisionBinding { expected_revision: number; expected_fingerprint: string | null }
export interface GoldenCaseEdit extends GoldenSigned, GoldenRevisionBinding {
  title: string; capture_id: string; evidence_note: string; expected: GoldenExpected;
}
export interface GoldenCaseCreate extends GoldenCaseEdit { kind: GoldenKind; source_id: string }
export interface GoldenCaseReviewRequest extends GoldenSigned, GoldenRevisionBinding {
  case_revision: number; case_fingerprint: string; action: "approve" | "reject" | "revoke"; acknowledged: true;
}
export interface GoldenCaseReview extends GoldenSigned {
  revision: number; fingerprint: string; action: "approve" | "reject" | "revoke";
  case_revision: number; case_fingerprint: string; created_at: string;
}
export interface GoldenCaseSummary {
  id: string; kind: GoldenKind; source_id: string; title: string; revision: number; fingerprint: string;
  capture_id: string; evidence_note: string; current_revision: number; is_current: boolean;
  review_revision: number; review_fingerprint: string | null; latest_review: GoldenCaseReview | null;
  status: "pending" | "approved" | "rejected" | "revoked"; created_at: string;
}
export interface GoldenCase extends GoldenCaseSummary {
  expected: GoldenExpected; input: ReparseInput;
  history?: (GoldenSigned & { revision: number; fingerprint: string; title: string; capture_id: string; created_at: string })[];
  history_truncated?: boolean;
  reviews?: GoldenCaseReview[]; reviews_truncated?: boolean; recorded_review?: GoldenCaseReview;
}
export interface GoldenCaseRef {
  case_id: string; case_revision: number; case_fingerprint: string; review_revision: number; review_fingerprint: string;
}
export interface GoldenSetCreate extends GoldenSigned, GoldenRevisionBinding {
  title: string; source_id: string; case_refs: GoldenCaseRef[]; acknowledged: true;
}
export interface GoldenSetRevision extends GoldenSetCreate { action: "freeze" | "revoke" }
export interface GoldenSet {
  id: string; title: string; source_id: string; kind: GoldenKind; revision: number; fingerprint: string;
  action: "freeze" | "revoke"; state: "frozen" | "revoked"; case_refs: GoldenCaseRef[]; capture_ids: string[];
  eligible: boolean; blockers: string[]; created_at: string;
  history?: (GoldenSigned & { revision: number; fingerprint: string; action: "freeze" | "revoke"; created_at: string })[];
  history_truncated?: boolean; cases?: unknown[];
}
export interface GoldenGate {
  state: "unverified" | "pending" | "passed" | "stale" | "failed" | "inconclusive" | "not_applicable";
  applicable?: boolean; scope?: string; notice?: string; blockers?: string[]; report?: GoldenAggregateReport | null;
  set_id?: string; set_revision?: number; set_fingerprint?: string;
}
export interface GoldenAggregateReport {
  state: "passed" | "failed" | "inconclusive"; scope: string;
  expected_case_count: number; completed_case_count: number; expected_distinct_pairs: number; checked_distinct_pairs: number;
  wrong_merge_count: number | null; failure_codes: string[]; case_ids: string[]; contract: Record<string, unknown>;
}
export interface GoldenCaseReport {
  kind: GoldenKind; case_id: string; state: "passed" | "failed"; scope: string; contract: Record<string, unknown>;
  failures: { code: string; path: string; expected: unknown; actual: unknown }[];
  failure_count: number; failures_truncated: boolean; expected_records?: number; actual_records?: number | null;
  matched_records?: number; expected_distinct_pairs?: number; checked_distinct_pairs?: number; wrong_merge_count?: number | null;
  identity_bindings: Record<string, unknown>[];
}
