import type { AxleSpecification, Provenance, VehicleDescription, VehicleTrim, WheelFitment } from "./index";

export type FitmentRelationAction = "create" | "revise" | "review" | "revoke" | "restore";
export type FitmentRelationState = "pending_review" | "reviewed" | "revoked" | "needs_review";
export interface FitmentRelationPage<T> {
  data_state: "local_snapshot"; scope: "local_workspace"; items: T[]; total: number; offset: number; limit: number;
}
export interface FitmentRelationProvenance extends Provenance {
  parser_identity?: Record<string, unknown> | null; evidence_path?: string; source_page?: string;
}
export interface FitmentVehicleSnapshot {
  id: string; vehicle_id: string; vehicle: VehicleDescription; fact_version: number; fact_hash: string;
  provenance: FitmentRelationProvenance; fitment_count: number;
}
export interface FitmentVehicleSnapshotDetail extends FitmentVehicleSnapshot {
  data_state: "local_snapshot"; scope: "local_workspace"; trims: VehicleTrim[]; fitments: WheelFitment[];
  coverage: Record<string, unknown> | null;
}
export interface FitmentTireEvidenceChoice {
  snapshot_id: string; source_id: string; provenance: FitmentRelationProvenance;
  fact_version_id: string; fact_version: number; facts_hash: string;
}
export interface FitmentTireEvidencePage extends FitmentRelationPage<FitmentTireEvidenceChoice> {
  identity_contract?: import("./identity-contract").IdentityContract;
  variant_id: string; identity: Record<string, unknown>;
}
export interface FitmentRelationSelection {
  vehicle_id: string; vehicle_snapshot_id: string; trim_id: string; wheel_option_id: string;
  axle: "front" | "rear"; variant_id: string; tire_snapshot_id: string; fact_version_id: string;
}
export interface FitmentVehicleEvidence {
  role: "vehicle_requirement"; vehicle: VehicleDescription; trim: VehicleTrim; wheel: WheelFitment;
  axle: "front" | "rear"; requirements: AxleSpecification; fact_version: number; fact_hash: string;
  provenance: FitmentRelationProvenance;
  structured_locator: { kind: "vehicle_snapshot_payload"; json_pointer: string; snapshot_id: string; fitment_index: number; wheel_option_id: string; axle: "front" | "rear" };
  source_locator_marker: string | null; source_locator_notice: string;
}
export interface FitmentTireEvidence {
  identity_contract?: import("./identity-contract").IdentityContract;
  identity_contract_version?: string | null;
  role: "tire_sku_fact"; variant_id: string; identity: Record<string, unknown>; identity_status: string;
  facts: Record<string, unknown>; fact_version_id: string; fact_version: number; facts_hash: string;
  provenance: FitmentRelationProvenance; query_key: string;
  structured_locator: { kind: "tire_snapshot_parsed_variants"; json_pointer: string; snapshot_id: string; variant_index: number; variant_id: string };
  source_locator_markers: unknown[]; source_locator_notice: string;
}
export interface FitmentRelationCheck {
  field: string; status: "match" | "conflict" | "unknown" | "not_declared"; vehicle_value: unknown; tire_value: unknown;
}
export interface FitmentOfficialOE { state: "not_established"; missing_evidence: string[] }
export interface FitmentRelationPreviewRequest {
  mode: "history"; action: FitmentRelationAction; relation_id?: string; selection: FitmentRelationSelection;
}
export interface FitmentRelationPreview {
  data_state: "local_snapshot"; scope: "local_workspace"; selection: FitmentRelationSelection;
  revision: number; fingerprint: string; vehicle_evidence: FitmentVehicleEvidence; tire_evidence: FitmentTireEvidence;
  checks: FitmentRelationCheck[]; unknown_fields: string[]; blockers: string[];
  blocker_messages?: { code: string; message: string }[]; can_submit: boolean; official_oe: FitmentOfficialOE; notice: string;
}
export interface FitmentRelationDecision extends FitmentRelationPreviewRequest {
  expected_revision: number; expected_fingerprint: string; operator: string; reason: string;
  acknowledged: boolean; acknowledge_unknowns: boolean;
}
export interface FitmentRelation {
  data_state: "local_snapshot"; scope: "local_workspace"; id: string; vehicle_id: string; trim_id: string;
  wheel_option_id: string; axle: "front" | "rear"; variant_id: string; revision: number;
  review_state: Exclude<FitmentRelationState, "needs_review">; effective_state: FitmentRelationState;
  needs_review: boolean; stale_reasons: string[]; selection: FitmentRelationSelection;
  vehicle_evidence: FitmentVehicleEvidence; tire_evidence: FitmentTireEvidence; checks: FitmentRelationCheck[];
  official_oe: FitmentOfficialOE; operator: string; reason: string; updated_at: string; fingerprint: string; notice: string;
}
export interface FitmentRelationRevision {
  id: string; relation_id: string; revision: number; action: FitmentRelationAction;
  review_state: FitmentRelation["review_state"]; selection: FitmentRelationSelection;
  vehicle_evidence: FitmentVehicleEvidence; tire_evidence: FitmentTireEvidence; checks: FitmentRelationCheck[];
  binding: Record<string, unknown>; binding_hash: string; before: Record<string, unknown> | null; after: Record<string, unknown>;
  acknowledged_unknowns: boolean; operator: string; reason: string;
  idempotency_key: string; created_at: string; official_oe: FitmentOfficialOE;
}
export interface FitmentRelationDetail extends FitmentRelation { history: FitmentRelationRevision[]; history_truncated: boolean }
export interface FitmentRelationDecisionResult { relation: FitmentRelationDetail; event: FitmentRelationRevision; idempotent_replay: boolean }
