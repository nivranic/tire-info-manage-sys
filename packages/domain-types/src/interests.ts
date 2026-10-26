import type { QualityMetrics, TireQuery } from "./index";

/** Actor-private interests. Text values use complete server-side matching, never aliases. */
export type InterestTextKind = "brand" | "size" | "oe" | "technology" | "test_organization";
export type InterestKind = InterestTextKind | "model" | "vehicle_fitment";

export interface InterestModelValue { brand: string; model: string }
export interface InterestVehicleValue {
  vehicle_id: string;
  trim_id?: string;
  wheel_option_id?: string;
  axle?: "front" | "rear";
}

/** Alternatives within one group are OR; groups are AND. */
export type InterestCondition =
  | { kind: InterestTextKind; values: string[] }
  | { kind: "model"; values: InterestModelValue[] }
  | { kind: "vehicle_fitment"; values: InterestVehicleValue[] };

export type InterestChangedField =
  | "identity.brand" | "identity.model" | "identity.size" | "identity.oe_mark"
  | "identity.acoustic_technology" | "identity.technology_features" | "facts"
  | "facts.utqg_treadwear" | "facts.utqg_traction" | "facts.utqg_temperature"
  | "facts.tread_depth" | "facts.tread_depths"
  | "event.organization" | "event.participants" | "event.metrics" | "event.measurements"
  | "event.metadata" | "state" | "vehicle" | "trims" | "fitments" | "footnotes"
  | "selection" | "review_state" | "vehicle_evidence" | "tire_evidence" | "binding"
  | "curation" | "identity_resolution" | "catalog_membership" | "curation_applicability";

export interface InterestSettings {
  name: string;
  enabled: boolean;
  /** 1–8 AND groups, each with 1–20 OR alternatives; repeated kinds remain separate. */
  conditions: InterestCondition[];
  metric_keys: string[];
  changed_fields: InterestChangedField[];
  /** Omitted on create means false; omitted on edit preserves the existing option. */
  source_quality_notifications?: boolean;
}
export type InterestPreviewRequest = Pick<InterestSettings, "conditions" | "metric_keys" | "changed_fields">;
export interface InterestRevision extends InterestSettings {
  revision: number;
  archived: boolean;
  fingerprint: string;
  created_at: string;
}
export interface InterestRecord extends InterestRevision {
  id: string;
  scope: "actor";
  updated_at: string;
  /** Saving interests never creates a fetch job. */
  monitoring_enabled: false;
}
export interface InterestDetail extends InterestRecord {
  history: InterestRevision[];
  history_truncated: boolean;
}
export type InterestDomain = "tire" | "test_event" | "vehicle" | "fitment"
  | "tire_curation" | "tire_lifecycle" | "tire_identity" | "tire_catalog" | "tire_curation_validity" | "tire_source_quality";
export interface InterestCapabilities {
  schema: "interest-capabilities@1";
  kinds: InterestKind[];
  domains: { domain: InterestDomain; supported: boolean; event_kinds: string[]; limitations: string[] }[];
  changed_fields: InterestChangedField[];
  unsupported_events: { kind: string; reason: string }[];
  network_refresh: false;
  notice: string;
}
export interface InterestList {
  scope: "actor";
  data_state: "local_snapshot";
  items: InterestRecord[];
  total: number;
  offset: number;
  limit: number;
  capabilities: InterestCapabilities;
}
export type InterestOriginalEvidenceKind = "tire_curation_revision" | "tire_lifecycle_event"
  | "tire_identity_revision" | "tire_catalog_revision" | "tire_curation_applicability_event";
export interface InterestEvidence {
  kind: "tire_change" | "test_revision" | "vehicle_snapshot" | "fitment_relation_revision"
    | InterestOriginalEvidenceKind | "tire_source_quarantine" | "tire_source_quality_baseline";
  record_id: string;
  entity_id: string;
  revision: number | null;
  snapshot_id: string | null;
  previous_snapshot_id: string | null;
  source_id: string | null;
  source_url: string | null;
  verification_ids: string[];
  fingerprint: string | null;
  contract_version: string | null;
}
/** Public immutable origin row, reread independently of a stored interest notification. */
export interface InterestOriginalEvidence {
  schema: "interest-original-evidence@1";
  scope: "local_workspace";
  data_state: "local_snapshot";
  kind: InterestOriginalEvidenceKind;
  record_id: string;
  entity_id: string;
  revision: number;
  /** Server digest of record, excluding internal session IDs and derived validity end times. */
  fingerprint: string;
  record: Record<string, unknown>;
  evidence: InterestEvidence[];
}
export interface InterestCurationApplicabilityAffected {
  manual_revision_id: string;
  manual_revision: number;
  field: string;
  action: "manual_override" | "revoke";
  before_status: "manual_override" | "revoked";
  after_status: "needs_review";
  manual_fingerprint: string;
}
/** Each side keeps its own query; actual fact and snapshot member versions can differ. */
export interface InterestCurationApplicabilityBasis extends Record<string, unknown> {
  snapshot_id: string | null;
  source_id: string;
  query_key: string | null;
  source_url: string | null;
  raw_hash: string | null;
  identity_contract_version: string | null;
  parsed_variants_hash: string | null;
  verification_id: string | null;
  verification_status: string | null;
  verified_at: string | null;
  present: boolean;
  member_hash: string | null;
  structured_locator: string | null;
  fact_version_id: string;
  fact_version: number | null;
  facts_hash: string | null;
  snapshot_member_fact_version: number | null;
}
/** An independent derived ledger row; its revision is never a manual decision revision. */
export interface InterestCurationApplicabilityRecord extends Record<string, unknown> {
  id: string;
  variant_id: string;
  source_id: string;
  before_fact_id: string;
  after_fact_id: string;
  verification_id: string;
  revision: number;
  action: "invalidate";
  manual_revision_watermark: number;
  affected: InterestCurationApplicabilityAffected[];
  binding: { before: InterestCurationApplicabilityBasis; after: InterestCurationApplicabilityBasis };
  created_at: string;
}
/** Frozen event facts and historical evidence bindings, never current-object substitutes. */
export interface InterestAcceptedEvent {
  schema: "interest-event@1";
  id: string;
  domain: Exclude<InterestDomain, "tire_source_quality">;
  action: string;
  state: string;
  revision: number;
  observed_at: string;
  subject_id: string;
  label: string;
  event_hash: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown>;
  changed_paths: string[];
  evidence: InterestEvidence[];
}

export interface InterestSourceQualityQuarantine {
  id: string; query_id: string; source_id: string; query_key: string; query: TireQuery;
  source_url: string; raw_hash: string; parser_version: string; observed_at: string;
  reason_codes: string[]; metrics: QualityMetrics; previous_snapshot_id: string;
}
export interface InterestSourceQualityBaseline {
  snapshot_id: string; source_id: string; query_key: string; source_url: string; raw_hash: string;
  identity_contract_version: string; parsed_variants_hash: string; verification_id: string;
  verification_status: "ok" | "not_modified"; verified_at: string; observed_at: string; parser_version: string;
}
export interface InterestSourceQualityMemberReference {
  variant_id: string; structured_locator: string; member_hash: string;
}
export interface InterestSourceQualityMember extends InterestSourceQualityMemberReference {
  identity: Record<string, unknown>; facts: Record<string, unknown>;
  fact_version_id: string; fact_version: number; facts_hash: string; evidence_valid: true;
}
export type InterestSourceQualityCondition =
  | { kind: Exclude<InterestTextKind, "test_organization">; values: string[] }
  | { kind: "model"; values: InterestModelValue[] };
export interface InterestSourceQualityCriteria {
  conditions: InterestSourceQualityCondition[];
  metric_keys: []; changed_fields: []; source_quality_notifications: true;
}
export interface InterestSourceQualityAfter extends Record<string, unknown> {
  accepted: false; state: "quarantined"; evidence_valid: true;
  quarantine: InterestSourceQualityQuarantine; baseline: InterestSourceQualityBaseline;
  baseline_members: InterestSourceQualityMember[];
}
/** Query status only: the candidate is unaccepted and baseline members are historical. */
export interface InterestSourceQualityEvent extends Omit<InterestAcceptedEvent, "domain" | "action" | "state" | "revision" | "before" | "after" | "changed_paths"> {
  domain: "tire_source_quality"; action: "quarantined"; state: "quarantined"; revision: 1;
  before: null; after: InterestSourceQualityAfter; changed_paths: ["source_quality"];
}
export type InterestEvent = InterestAcceptedEvent | InterestSourceQualityEvent;

interface InterestMatchBase {
  state: "matched" | "no_match" | "indeterminate";
  matched_sides: ("before" | "after")[];
  reasons: string[];
}
export interface InterestExplicitMatch extends InterestMatchBase {
  /** Criteria frozen with this evaluation, independent of later interest revisions. */
  criteria: InterestPreviewRequest;
  policy_version: "explicit-interest@1";
}
export interface InterestSourceQualityMatch extends InterestMatchBase {
  state: "matched"; criteria: InterestSourceQualityCriteria;
  matched_sides: ["after"]; reasons: ["matches_baseline_member"];
  policy_version: "source-quality-interest@1";
  matched_baseline_members: InterestSourceQualityMemberReference[];
}
export type InterestMatch = InterestExplicitMatch | InterestSourceQualityMatch;
export interface InterestPreviewItem { event: InterestEvent; match: InterestMatch }
export interface InterestPreview {
  schema: "interest-preview@1";
  scope: "actor";
  data_state: "local_snapshot";
  items: InterestPreviewItem[];
  scanned_count: number;
  matched_count: number;
  indeterminate_count: number;
  next_offset: number | null;
  capabilities: InterestCapabilities;
}
export interface InterestNotification extends InterestPreviewItem {
  id: string;
  interest_id: string;
  interest_revision: number;
  interest_name: string;
  delivered_at: string;
  read_at: string | null;
}
export interface InterestNotificationList {
  scope: "actor";
  data_state: "local_snapshot";
  items: InterestNotification[];
  total: number;
  offset: number;
  limit: number;
}
