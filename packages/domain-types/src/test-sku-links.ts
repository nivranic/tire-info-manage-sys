import type { EvidenceDocument, Provenance, TestEventPayload, TestParticipant } from "./index";

/** R71: supplied-material identity declarations, never online verification. */
export type BridgeAction = "create" | "revise" | "review" | "revoke" | "restore";
export type BridgeReviewState = "pending_review" | "reviewed" | "revoked";
export type BridgeEffectiveState = BridgeReviewState | "needs_review";
export type BridgeEvidenceLevel = "manual_assertion" | "source_explicit_identifiers_in_supplied_material";

export interface BridgeSelection {
  event_id: string; event_revision_id: string; participant_key: string;
  variant_id: string; tire_snapshot_id: string; fact_version_id: string;
}
export interface BridgeLocator { page: number; region: string; quote: string }
export interface BridgeRights {
  rights_holder: string; basis: string;
  store_original: true; workspace_reopen: true; quote_identifiers: true;
}
export interface BridgeMaterial {
  document_id: string; expected_raw_hash: string; expected_metadata_hash: string;
  event_locator: BridgeLocator; participant_locator: BridgeLocator; rights: BridgeRights;
}
export type BridgeIdentityField = "brand" | "model" | "manufacturer_product_code" | "region" | "size" |
  "load_index" | "speed_rating" | "xl" | "hl" | "oe_mark" | "acoustic_technology" | "run_flat" |
  "product_code_type" | "gtin" | "technology_features" | "eprel_id";
export interface BridgeAssertion {
  field: BridgeIdentityField; material_document_id: string; material_value: string | boolean;
  quote: string; page: number; region: string;
}
export interface BridgePreviewRequest {
  mode: "history"; action: BridgeAction; link_id: string | null;
  selection: BridgeSelection; materials: BridgeMaterial[];
  assertions: BridgeAssertion[]; evidence_level: BridgeEvidenceLevel;
}
export interface BridgeOpenedMaterial { document_id: string; raw_hash: string; metadata_hash: string }
export interface BridgeDecision extends BridgePreviewRequest {
  expected_revision: number; expected_fingerprint: string; declaration_revision_id: string | null;
  operator: string; reason: string; acknowledged: true;
  opened_materials: BridgeOpenedMaterial[];
  confirmed_event_revision_id: string; confirmed_participant_hash: string;
}

export interface BridgeBoundary {
  material_origin: "operator_supplied"; origin_verification: "unverified"; read_scope: "local_workspace";
  test_record_kind: "manual_transcription"; test_verification: "unverified";
  provider_use: false; export: false; notice: string;
}
export interface BridgeMaterialChoice extends EvidenceDocument { metadata_hash: string }
export interface BridgeMaterialsPage {
  scope: "local_workspace"; items: BridgeMaterialChoice[]; offset: number; total: number; boundary: BridgeBoundary;
}
export interface BridgeMaterialEvidence {
  document_id: string; metadata: EvidenceDocument; raw_hash: string; metadata_hash: string;
  event_locator: BridgeLocator & { quote_sha256: string };
  participant_locator: BridgeLocator & { quote_sha256: string };
  rights: BridgeRights; material_origin: "operator_supplied";
  origin_verification: "unverified"; read_scope: "local_workspace";
}
export interface BridgeTestEvidence {
  event_id: string; revision_id: string; revision: number; state: "active" | "revoked"; fingerprint: string;
  event: TestEventPayload; participant: TestParticipant; participant_hash: string; participant_present: boolean;
}
export interface BridgeTireEvidence {
  variant_id: string; snapshot_id: string; source_id: string; query_key: string; raw_hash: string;
  identity_contract_version: string | null; identity: Record<string, unknown>;
  identity_key: string; identity_status: string; facts: Record<string, unknown>; facts_hash: string;
  fact_version_id: string; fact_version: number; snapshot_member: Record<string, unknown>;
  parsed_variants_hash: string; structured_locator: Record<string, unknown>; provenance: Provenance;
}
export interface BridgeCheck {
  field: string; status: "match" | "conflict" | "unknown" | "unsupported";
  material_value: string | boolean | null; sku_value: unknown;
}
export interface BridgeHistoryItem {
  revision_id: string; revision: number; action: BridgeAction; review_state: BridgeReviewState;
  declaration_revision_id: string; declared_by_user_id: string; actor_user_id: string;
  operator: string; reason: string; created_at: string; fingerprint: string;
}
export interface TestSkuLinkView {
  schema: "test-sku-link@1"; scope: "local_workspace"; data_state: "local_snapshot";
  id: string | null; revision: number; revision_id: string | null;
  review_state: BridgeReviewState | null; effective_state: BridgeEffectiveState;
  eligibility: "none" | "conditional_reviewed_transcription"; boundary: BridgeBoundary;
  selection: BridgeSelection; materials: BridgeMaterial[];
  assertions: (BridgeAssertion & { quote_sha256: string })[]; evidence_level: BridgeEvidenceLevel;
  frozen_evidence: { test: BridgeTestEvidence; tire: BridgeTireEvidence };
  material_evidence: BridgeMaterialEvidence[]; checks: BridgeCheck[];
  required_identity_fields: string[]; unknown_fields: string[]; blockers: string[]; stale_reasons: string[];
  binding_hash: string; fingerprint: string; declared_by_user_id: string | null;
  declaration_revision_id: string | null; allowed_actions: BridgeAction[];
}
export interface TestSkuLinkPreview extends TestSkuLinkView {
  can_submit: boolean; confirmed_participant_hash: string; confirmed_event_revision_id: string;
}
export interface TestSkuLinkDetail extends TestSkuLinkView {
  id: string; revision_id: string; review_state: BridgeReviewState;
  declared_by_user_id: string; declaration_revision_id: string;
  history: BridgeHistoryItem[]; history_truncated: boolean;
}
export interface TestSkuLinkPage {
  schema: "test-sku-link@1"; scope: "local_workspace"; items: TestSkuLinkView[];
  offset: number; total: number; boundary: BridgeBoundary;
}
export interface TestSkuLinkDecisionResult { link: TestSkuLinkDetail; event: BridgeHistoryItem; idempotent_replay: boolean }
