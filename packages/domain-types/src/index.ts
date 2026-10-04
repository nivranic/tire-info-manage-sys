export type DataState = "live" | "live_verified_304" | "consent_required" | "source_unavailable" | "local_snapshot";
export type { WarehouseFallbackPolicyPreviewRequest, WarehouseFallbackPolicy, WarehouseFallbackPolicyPreview,
  WarehouseFallbackPolicyApplyRequest, WarehouseFallbackPolicyList, WarehouseFallbackUse, WarehouseFallbackAuthorization } from "./warehouse-fallback";
export type { OfflinePackUpdateRequest, OfflinePackUpdate, DeviceSyncConditions, DeviceSyncCapabilities, DeviceSyncPreviewRequest,
  DeviceSyncPreview, DeviceSyncApplyRequest, DeviceSyncPolicy, DeviceSyncPolicyRequest, DeviceSyncTrigger, DeviceSyncRunRequest,
  DeviceSyncRun, DeviceSyncReleaseCheck, DeviceSyncStatus } from "./device-sync";
export type { OfflineReference, ResolvedOfflineReference, OfflineScope, OfflineCapacity, OfflineCounts,
  OfflineMemberReason, OfflineResolvedMember, OfflineOmission, OfflinePlanRequest, OfflinePlan, OfflineConfirmRequest,
  OfflinePackDescriptor, OfflineContext, OfflineSource, OfflineMember, OfflineDocument, OfflineEnvelope,
  OfflineHostStatus, OfflineSlot, OfflineHostList, OfflineInstallRequest, OfflineSlotRequest, OfflineSearchRequest,
  OfflineSearchResult, OfflineReadRequest, OfflineReadResult, OfflineRemoveResult, OfflineUnlockRequest, OfflineStorage } from "./offline-packs";
export type { MonitorTaskKind, MonitorTaskScope, MonitorTaskPhase, MonitorAttemptState, MonitorTaskState, MonitorTaskAttempt, MonitorTaskEvent, MonitorTaskLegacyRun, MonitorTask, MonitorTaskFilters, MonitorTaskList, MonitorTaskDetail, MonitorTaskEvents, MonitorTaskStreamMessage } from "./monitor-tasks";
export type { LocalFallbackFailure, LocalFallbackIntent, LocalFallbackDecideRequest, LocalFallbackGrant,
  LocalFallbackConsumeRequest, LocalFallbackRevokeRequest, LocalFallbackRevokeResult, LocalFallbackResult } from "./local-fallback";
export type { DeviceFallbackQueryKind, DeviceFallbackPolicyMode, DeviceFallbackCanonicalTireQuery,
  DeviceFallbackCanonicalVehicleQuery, DeviceFallbackCanonicalRecallQuery, DeviceFallbackCanonicalSearchQuery,
  DeviceFallbackSourcePin, DeviceFallbackSourceSelection, DeviceFallbackPolicyScope, DeviceFallbackSourceAuthority,
  DeviceFallbackAuthorityBinding, DeviceFallbackIntentV2, DeviceFallbackSlotBindingRequest, DeviceFallbackDecideRequestV2,
  DeviceFallbackAuthorization, DeviceFallbackGrantV2, DeviceFallbackConsumeRequestV2, DeviceFallbackNativeWire, DeviceFallbackRevokeRequestV2,
  DeviceFallbackRevokeResultV2, DeviceFallbackCitationV2, DeviceFallbackHistoricalMember, DeviceFallbackResultV2, DeviceFallbackPackageBinding,
  DeviceFallbackPolicyChoice, DeviceFallbackPolicy, DeviceFallbackPolicyPreviewRequest, DeviceFallbackPolicyPreview,
  DeviceFallbackPolicyApplyRequest, DeviceFallbackPolicyRequest, DeviceFallbackAuthorizeRequest, DeviceFallbackAuthorizeResult,
  DeviceFallbackCapabilities, DeviceFallbackStatus, DeviceFallbackStorageV2 } from "./device-fallback";
export type { OfflinePackSchema, OfflineRecallSearchReference, OfflineReferenceV2, ResolvedOfflineReferenceV2,
  OfflineScopeV2, OfflineResolvedMemberV2, OfflineRecallSearchPayload, OfflineMemberV2, OfflineDocumentV2,
  OfflinePlanRequestV2, OfflinePlanV2, OfflinePackDescriptorV2, OfflineEnvelopeV2, OfflinePackUpdateRequestV2,
  OfflinePackUpdateV2, AnyOfflinePlan, AnyOfflinePackDescriptor, AnyOfflineEnvelope, OfflineReadResultV2 } from "./offline-packs-v2";
export type { SourceSettingState, SourceSettingAction, SourceSettingSnapshot, SourceSettingView, SourceSettingCatalog, SourceSettingIntent, SourceSettingPreview, SourceSettingRevisionRequest, SourceSettingEvent, SourceSettingHistory, SourceSettingRevisionResult } from "./source-management";
export type { FieldPolicy, FieldCandidate, FieldDecision, FieldResolution, FieldResolutionState, FieldResolutionScope,
  FieldPolicyDefinition, FieldPolicyCatalog, FieldConflictPage } from "./field-authority";
export type { IdentityContract, IdentityMigrationSummary, IdentityMigrationAssessment, IdentityMigrationPreview,
  IdentityMigrationApply, IdentityMigrationApplication } from "./identity-contract";
export type { GoldenKind, GoldenVariantInput, GoldenTireExpected, GoldenVehicleExpected, GoldenExpected,
  GoldenSigned, GoldenRevisionBinding, GoldenCaseEdit, GoldenCaseCreate, GoldenCaseReviewRequest,
  GoldenCaseReview, GoldenCaseSummary, GoldenCase, GoldenCaseRef, GoldenSetCreate, GoldenSetRevision, GoldenSet, GoldenGate,
  GoldenAggregateReport, GoldenCaseReport } from "./golden";
export type { FitmentRelationAction, FitmentRelationState, FitmentRelationPage, FitmentRelationProvenance, FitmentVehicleSnapshot, FitmentVehicleSnapshotDetail, FitmentTireEvidenceChoice, FitmentTireEvidencePage, FitmentRelationSelection, FitmentVehicleEvidence, FitmentTireEvidence, FitmentRelationCheck, FitmentOfficialOE, FitmentRelationPreviewRequest, FitmentRelationPreview, FitmentRelationDecision, FitmentRelation, FitmentRelationRevision, FitmentRelationDetail, FitmentRelationDecisionResult } from "./fitment-relations";
export type { TireFilter, TireFilterValue, ExactNumericToken, TireFilterOperator, TireFilterField, TireFilterCatalog, TireQuerySelection } from "./filters";
export type { RecallQuery, RecallRecord, RecallRevision, RecallResult, RecallHistory, RecallEvidence, RecallRuleSettings, RecallRule, RecallRuleDetail, RecallNotification, RecallPage, RecallAnalysisReference, RecallBoundary } from "./recalls";
export type { RecallSearchQuery, RecallSearchCampaign, RecallSearchProduct, RecallSearchResult, RecallSearchEvidence } from "./recalls";
export type { RecallDiscoveryQuery, RecallDiscoveryBudget, RecallDiscoveryCoverage, RecallDiscoveryRun,
  RecallDiscoveryRuleSettings, RecallDiscoveryRuleRevision, RecallDiscoveryRule, RecallDiscoveryRuleDetail, RecallDiscoveryRuleWrite,
  RecallDiscoveryPage, RecallDiscoveryCandidate, RecallDiscoveryRunDetail, RecallDiscoveryNotification,
  RecallDiscoveryList } from "./recall-discovery-monitor";

export interface Source {
  source_setting?: import("./source-management").SourceSettingView;
  target_kind?: "tire" | "vehicle" | "recall";
  id: string;
  name: string;
  region: string;
  source_class: string;
  status: string;
  homepage: string;
  description: string;
  supported_models?: string[];
  default_model?: string | null;
  requires_size?: boolean;
  parser_version?: string;
  product_page_urls?: Record<string, string>;
}

export interface TireQuery { size?: string; model?: string }

export type AIPackReference = { kind: "tire"; snapshot_id: string; variant_id: string } | { kind: "vehicle"; snapshot_id: string } | { kind: "test_event"; event_id: string; event_revision: number } | import("./recalls").RecallAnalysisReference;
export type AIAnalysisReference = AIPackReference | { kind: "change_event"; change_id: string };
export interface KnowledgeFilters {
  kind?: "tire" | "vehicle" | "test_event" | "recall";
  brand?: string; model?: string; size?: string; region?: string; product_code?: string;
  source_id?: string; variant_id?: string; technology?: string; field?: string; campaign_number?: string;
}
export interface KnowledgeSearchRequest {
  mode: "history"; text: string; filters: KnowledgeFilters; limit?: number; offset?: number;
}
export interface KnowledgeSearchItem {
  recall?: {
    campaign_number: string; recall_revision_id: string | null; recall_revision: number | null;
    observation_kind: "records" | "empty"; record_count: number; record_key: string | null; applicability: "not_assessed";
    latest_observation: { snapshot_id: string; observation_kind: "records" | "empty"; observed_at: string; verified_at: string };
  };
  field_resolution?: import("./field-authority").FieldResolution;
  identity_contract?: import("./identity-contract").IdentityContract;
  id: string; reference: AIPackReference; kind: NonNullable<KnowledgeFilters["kind"]>; label: string; excerpt: string;
  source_id: string | null; source_url: string; region: string | null;
  observed_at: string; verified_at: string | null; privacy_class: "public" | "private";
  conflicts: Record<string, unknown>[];
  match: { method: "structured" | "fts" | "dense" | "hybrid"; matched_terms: string[]; authority_tier: number | null; authority_rule: string; explanation: string[] };
}
export interface KnowledgeSearchResult {
  mode: "history"; data_state: "local_snapshot"; text: string;
  applied_filters: KnowledgeFilters; inferred_filters: KnowledgeFilters;
  items: KnowledgeSearchItem[]; total: number; has_more: boolean; offset?: number; limit?: number;
  index: { engine: string; documents: number; version: string };
  stages: { name: string; state: "succeeded" | "not_needed" | "unavailable"; reason: string }[];
  notice: string;
  total_scope?: "candidates" | "matches" | "structured_matches";
  external_processing?: { query_text_sent: boolean };
  coverage?: VectorCoverage | null;
  candidate_counts?: { fts: number; dense: number; merged: number; limit: number };
}
export interface VectorCoverage { eligible_documents: number; indexed_documents: number; missing_documents: number }
export interface VectorStatus {
  backend: string; available: boolean; reason: string | null;
  model: { state: string; model: string | null; dimensions: number | null };
  coverage: VectorCoverage | null;
  budget: { day_utc: string; requests: number; accounted_tokens: number; has_pending_request: boolean };
  notice: string;
}
export interface EmbeddingPlan {
  id: string; model: string; dimensions: number; expires_at: string;
  documents: { id: string; label: string; privacy_class: string; chunks: { text: string; hash: string; cached: boolean }[] }[];
  pending_chunks: number; reserved_tokens: number;
}
export interface EmbeddingIndexResult { cached_chunks: number; written_chunks: number; documents: number }
export interface EmbeddingRun {
  id: string; kind: "index" | "hybrid"; state: "pending" | "outcome_unknown" | "completed" | "failed";
  error_code: string | null; usage: { input_tokens: number; output_tokens: number; total_tokens: number } | null;
  result: EmbeddingIndexResult | KnowledgeSearchResult | null;
  created_at: string; completed_at: string | null; reserved_tokens: number;
}
export type AIPrepareRequest = { mode: "history"; references: AIAnalysisReference[] }
  | { mode: "current"; query_kind?: "tire"; source_id: string; query: TireQuery; variant_ids: string[]; consent_id?: string }
  | { mode: "current"; query_kind: "recall_by_campaign"; source_id: "nhtsa-us-recalls"; query: import("./recalls").RecallQuery; consent_id?: string };
export interface AIEvidence {
  evidence_type?: "recall"; source_class?: "regulatory"; region?: "US";
  campaign_number?: string; query_key?: string; content_type?: string; records_hash?: string;
  verification_id?: string; verification_query_id?: string; parser_identity?: unknown;
  recall_revision_id?: string | null; recall_revision?: number | null;
  revision_snapshot_id?: string | null; revision_observed_at?: string | null;
  applicability?: "not_assessed"; observation_kind?: "records" | "empty"; record_count?: number;
  record_scopes?: { record_key: string; record_hash: string; occurrence: number; index: number }[];
  identity_contract?: import("./identity-contract").IdentityContract;
  id: string; kind: string; label: string; source_url: string; source_id?: string;
  observed_at: string; verified_at: string | null; snapshot_id?: string; variant_id?: string;
  event_id?: string; revision?: number; parser_version?: string; raw_hash?: string;
  change_id?: string; change_observed_at?: string;
  previous_snapshot_id?: string | null; previous_source_url?: string | null;
  previous_raw_hash?: string | null; previous_observed_at?: string | null;
}
export interface AIPack {
  purpose?: string;
  recall_policy?: { version: "recall-fact-selection@1"; digest: string };
  recall_boundary?: import("./recalls").RecallBoundary;
  field_policy?: import("./field-authority").FieldPolicy;
  field_resolutions?: import("./field-authority").FieldResolution[];
  id: string; mode: "current" | "history"; data_state: DataState; privacy_class: "public" | "private" | "restricted";
  created_at: string; expires_at: string; fingerprint: string; evidence: AIEvidence[];
  facts: { id: string; evidence_id: string; field: string; field_code?: string; value: unknown; text: string;
    domain?: "recall"; scope?: "observation" | "record"; record_key?: string | null }[];
  conflicts: Record<string, unknown>[]; source_state: "snapshot" | "live";
  query_id: string | null; consent_id: string | null;
}
export interface AIStatus {
  model: { provider: string; state: string; model: string | null; connection_verified: boolean; daily_token_limit?: number; daily_request_limit?: number; allowed_privacy_classes?: string[] };
  budget: { day_utc: string; requests: number; accounted_tokens: number; has_pending_request: boolean };
  notice: string;
}
export interface AIClaim {
  type: "fact" | "inference"; text: string; fact_ids: string[]; evidence_ids: string[];
}
export interface AIAnalysis {
  id: string; pack_id: string; question: string; provider: string; model: string;
  created_at: string; completed_at: string | null; state: "pending" | "outcome_unknown" | "failed" | "completed";
  reserved_tokens: number; usage: { input_tokens: number; output_tokens: number; total_tokens: number } | null;
  error_code: string | null; answer: {
    recall_boundary?: import("./recalls").RecallBoundary;
    claims: AIClaim[];
    uncertainty: string; conflicts: Record<string, unknown>[]; source_state: string; data_state: DataState; notice: string;
  } | null;
  pack?: AIPack;
  request_contract?: Record<string, unknown> & { delivery_mode?: string };
}

export type AIStreamState = "accepted" | "running" | "completed" | "failed" | "outcome_unknown";
export interface AIStreamExecution {
  state: AIStreamState; terminal: boolean; deadline_at: string;
  last_event_at: string | null; projection_only: boolean;
}
export interface AIStreamDraftClaim { index: number; claim: AIClaim }
export interface AIStreamDetail {
  schema: "ai-streams@1"; scope: "session"; analysis: AIAnalysis;
  execution: AIStreamExecution; draft_claims: AIStreamDraftClaim[];
  draft_uncertainty: string | null; cursor: string; server_time: string;
}
export interface AIStreamAcceptance extends AIStreamDetail { replayed: boolean }
export type AIStreamEvent = {
  id: string; request_id: string; sequence: number; cursor: string; created_at: string;
} & (
  { type: "accepted" | "started"; payload: Record<string, never> }
  | { type: "claim_draft"; payload: AIStreamDraftClaim }
  | { type: "uncertainty_draft"; payload: { text: string } }
  | { type: "completed" | "failed" | "outcome_unknown"; payload: { state: "completed" | "failed" | "outcome_unknown"; error_code: string | null } }
);
export interface AIStreamEvents {
  schema: "ai-streams@1"; scope: "session"; request_id: string;
  items: AIStreamEvent[]; next_cursor: string; latest_cursor: string; has_more: boolean;
  execution: AIStreamExecution; server_time: string;
}
export type AIStreamMessage =
  | { type: "ai_event"; data: AIStreamEvent }
  | { type: "heartbeat"; data: { cursor: string; server_time: string } }
  | { type: "stream_end"; data: { cursor: string; server_time: string; reason: "window_complete" } }
  | { type: "reset"; data: { code: "ai_stream_cursor_reset_required"; server_time: string } };

export type ReportFormat = "markdown" | "html" | "pdf";
export interface ReportCreate {
  mode: "history"; pack_id: string; analysis_id?: string | null; title: string; notes: string;
}
export interface EvidenceReportRecord {
  id: string; title: string; notes: string; revision: number; archived: boolean;
  created_at: string; updated_at: string; body_hash: string; privacy_class: "private";
  pack_id: string; analysis_id: string | null; data_state: "local_snapshot";
}
export interface ReportExport {
  id: string; report_id: string; revision: number; format: ReportFormat; renderer_version: string;
  content_type: string; byte_count: number; sha256: string; created_at: string; content_url: string;
}
export interface EvidenceReportDetail extends EvidenceReportRecord {
  body: {
    recall_boundary?: import("./recalls").RecallBoundary;
    recall_policy?: { version: "recall-fact-selection@1"; digest: string };
    field_policy?: import("./field-authority").FieldPolicy;
    field_resolutions?: import("./field-authority").FieldResolution[];
    data_state: "local_snapshot"; source_pack: Pick<AIPack, "id" | "fingerprint" | "mode" | "data_state" | "privacy_class" | "created_at" | "expires_at">;
    privacy_class: "private"; evidence: AIEvidence[]; facts: AIPack["facts"]; conflicts: AIPack["conflicts"];
    analysis: (Pick<AIAnalysis, "id" | "question" | "provider" | "model" | "created_at" | "completed_at" | "usage"> & {
      claims: NonNullable<AIAnalysis["answer"]>["claims"]; uncertainty: string;
    }) | null;
    notice: string;
  };
  metadata_history: { revision: number; title: string; notes: string; archived: boolean; operation: string; created_at: string }[];
  history_truncated: boolean; exports: ReportExport[];
  current_lifecycle: { variant_id: string; state: string; revision: number }[];
}
export interface EvidenceReportList {
  scope: "browser_session"; data_state: "local_snapshot"; items: EvidenceReportRecord[]; total: number; offset: number;
}

export interface EvidenceDocumentMetadata {
  title: string; source_url: string; operator: string; rights_basis: string;
}
export interface EvidenceDocument extends EvidenceDocumentMetadata {
  id: string; raw_hash: string; byte_count: number; content_type: string; created_at: string;
  status: "unparsed_receipt"; accepted_as_facts: false;
}

export interface AlertRuleSettings {
  name: string;
  interval_seconds: number;
  enabled: boolean;
  kinds: ("facts_changed" | "variant_observed")[];
  fields: string[];
  conditions: { technology?: string };
}
export interface AlertRuleCreate extends AlertRuleSettings {
  source_id: string;
  query: TireQuery;
  variant_id?: string | null;
}
export interface AlertRuleRecord extends AlertRuleCreate {
  tracking_state?: "current" | "identity_review_required";
  tracking_notice?: string; identity_contract?: import("./identity-contract").IdentityContract | null;
  id: string;
  revision: number;
  archived: boolean;
  created_at: string;
  origin: { kind: "ai_rule_draft"; draft_id: string; application_id: string } | null;
  job: { id: string; next_due_at: string | null; lease_until: string | null; last_run: { state: string; reason: string | null; finished_at: string } | null };
}
export interface AlertRuleDetail extends AlertRuleRecord {
  history: (AlertRuleSettings & { revision: number; archived: boolean; created_at: string })[];
  history_truncated: boolean;
}
export interface AIRuleDraftPack {
  id: string; purpose: "rule_draft"; mode: "history"; data_state: "local_snapshot"; privacy_class: "private";
  created_at: string; expires_at: string; fingerprint: string; catalog_hash: string;
  source: { id: string; name: string; region: string; homepage: string; requires_size?: boolean };
  supported_models: string[]; instruction: string;
  capabilities: {
    kinds: AlertRuleSettings["kinds"]; fields: { key: string; label: string }[]; technologies: string[];
    interval_seconds: { minimum: number; maximum: number; default: number };
    notification_channels: string[]; unsupported_features: string[];
  };
}
export interface AIRuleDraftApplication {
  id: string; rule_id: string; created_at: string; reviewed_rule: AlertRuleCreate; payload_hash: string;
}
export interface AIRuleDraftRun {
  id: string; pack_id: string; state: "pending" | "outcome_unknown" | "failed" | "completed";
  created_at: string; completed_at: string | null; reserved_tokens: number;
  provider?: string; model?: string;
  usage: { input_tokens: number; output_tokens: number; total_tokens: number } | null;
  error_code: string | null;
  draft: { rule: AlertRuleCreate | null; summary: string; unsupported_requirements: string[]; clarifications: string[]; can_apply: boolean } | null;
  pack?: AIRuleDraftPack;
  application?: AIRuleDraftApplication | null;
}
export interface LocalNotification {
  identity_contract?: import("./identity-contract").IdentityContract;
  id: string; rule_id: string; rule_name: string; rule_revision: number;
  read_at: string | null; delivered_at: string; observed_at: string;
  change_id: string; kind: "facts_changed" | "variant_observed";
  source_id: string; variant_id: string; identity: Record<string, unknown>;
  changes: Record<string, { before: unknown; after: unknown; before_present: boolean; after_present: boolean }>;
  snapshot_id: string; previous_snapshot_id: string | null;
}

export interface Variant {
  field_resolution?: import("./field-authority").FieldResolution;
  identity_contract?: import("./identity-contract").IdentityContract;
  identity_contract_version?: string | null;
  identity_resolution?: IdentityResolution;
  id: string;
  brand: string;
  model: string;
  manufacturer_product_code: string | null;
  region: string;
  size: string;
  load_index: string | number | null;
  speed_rating: string | null;
  xl: boolean | null;
  hl: boolean | null;
  oe_mark: string | null;
  acoustic_technology: string | null;
  run_flat: boolean | null;
  facts: Record<string, unknown>;
  snapshot_id: string;
  source_id?: string;
  effective_facts?: Record<string, unknown>;
  curation?: { source_id: string; revision: number; base_fact_id: string; fields: Record<string, CuratedField> };
  lifecycle?: VariantLifecycle;
}

export interface VariantLifecycle {
  state: "active" | "revoked";
  revision: number;
  event_id: string | null;
  operator: string | null;
  reason: string | null;
  changed_at: string | null;
}
export type ExcludedVariant = Pick<Variant, "id" | "brand" | "model" | "size" | "region" | "manufacturer_product_code" | "identity_contract"> & { lifecycle: VariantLifecycle };
export interface LifecycleReview {
  identity_contract?: import("./identity-contract").IdentityContract;
  data_state: "local_snapshot";
  variant_id: string;
  identity: Record<string, unknown>;
  lifecycle: VariantLifecycle;
  provenance: Provenance | null;
  history_truncated: boolean;
  history: { id: string; revision: number; action: "revoke" | "restore"; before_state: "active" | "revoked"; after_state: "active" | "revoked"; operator: string; reason: string; created_at: string; evidence: (Provenance & { locator: string })[] }[];
}
export interface LifecycleRequest {
  action: "revoke" | "restore";
  expected_revision: number;
  operator: string;
  reason: string;
  evidence: { snapshot_id: string; locator: string }[];
}

export interface Provenance {
  snapshot_id: string;
  source_id: string;
  source_url: string;
  parser_version: string;
  observed_at: string;
  raw_hash: string;
}

export type RevisionAction = "manual_override" | "revoke" | "clear_override";
export interface FieldValue { present: boolean; value: unknown }
export interface CuratedField {
  revision_id: string; revision: number; status: "manual_override" | "revoked" | "cleared" | "needs_review";
  operator: string; reason: string; after: FieldValue; base_fact_id: string;
  evidence: (Provenance & { locator: string })[];
}
export interface FactFieldDefinition {
  label: string; type: "number" | "string" | "boolean" | "measurement";
  unit?: string; units?: string[]; choices?: string[];
}
export interface FactReview {
  identity_contract?: import("./identity-contract").IdentityContract;
  data_state: "local_snapshot"; mode: "local_single_user_poc";
  variant_id: string; source_id: string; base_fact_id: string; fact_version: number; revision: number;
  source_facts: Record<string, unknown>; effective_facts: Record<string, unknown>;
  fields: Record<string, CuratedField>; field_catalog: Record<string, FactFieldDefinition>;
  provenance: Provenance; history_truncated: boolean;
  history: { id: string; revision: number; field: string; action: RevisionAction; operator: string; reason: string;
    before: FieldValue; after: FieldValue; source_before: FieldValue; base_fact_id: string;
    evidence: (Provenance & { locator: string })[]; created_at: string; valid_from: string; valid_to: string | null }[];
}
export interface FactRevisionRequest {
  source_id: string; base_fact_id: string; expected_revision: number; field: string; action: RevisionAction;
  value?: unknown; operator: string; reason: string; evidence: { snapshot_id: string; locator: string }[];
}

export interface QueryResult {
  fallback_authorization?: import("./warehouse-fallback").WarehouseFallbackAuthorization;
  query_id: string;
  source_id: string;
  data_state: DataState;
  reason?: string | null;
  verified_at?: string | null;
  snapshot_observed_at?: string | null;
  snapshot_age_seconds?: number | null;
  consent_id?: string | null;
  variants: Variant[];
  provenance: Provenance[];
  conflicts: unknown[];
  selection: import("./filters").TireQuerySelection;
}

export interface Evidence {
  quality_review?: QuarantineReviewEvent | null;
  id: string;
  source_id: string;
  source_url: string;
  observed_at: string;
  verified_at: string | null;
  parser_version: string;
  raw_hash: string;
  content_type: string;
  body: string;
}

export interface WatchItem { id: string; variant_id: string; created_at?: string; variant?: Variant; tracking_state?: "current" | "identity_review_required"; identity_contract?: import("./identity-contract").IdentityContract }
export interface ChangeItem { id: string; variant_id?: string; field?: string; observed_at?: string; kind?: string; identity_contract?: import("./identity-contract").IdentityContract; [key: string]: unknown }
export interface Health { status: string; mode: string; database: string }

export interface TestParticipant { key: string; brand: string; model: string; source_designation: string }
export interface TestMetricDefinition { key: string; label: string; unit: string; protocol: string; direction: "lower" | "higher" | "unspecified" }
export interface TestMeasurement { participant_key: string; metric_key: string; raw_value: string; source_rank: number | null; evidence_span: string; evidence_locator: string }
export interface TestEventPayload {
  title: string; organization: string; relationship: "independent" | "manufacturer_commissioned" | "unknown";
  publication_date: string | null; source_url: string; rights_basis: string; tested_size: string;
  vehicle: string | null; surface: string | null; conditions: string;
  coverage: "selected_results" | "full_event"; reported_participants: number | null;
  participants: TestParticipant[]; metrics: TestMetricDefinition[]; measurements: TestMeasurement[];
}
export interface TestEventRecord {
  id: string; revision: number; revision_id: string; state: "active" | "revoked";
  title: string; organization: string; tested_size: string; publication_date: string | null;
  relationship: TestEventPayload["relationship"]; coverage: TestEventPayload["coverage"];
  participant_count: number; metric_count: number; recorded_at: string; fingerprint: string;
  record_kind: "manual_transcription"; verification_status: "unverified"; verified_at: null;
}
export interface TestEventDetail extends TestEventRecord {
  data_state: "local_snapshot"; scope: "local_workspace"; event: TestEventPayload;
  participants: (TestParticipant & { id: string; identity_status: "participant_only" })[];
  history: { id: string; revision: number; action: string; state: string; operator: string; reason: string; recorded_at: string; fingerprint: string }[];
  history_truncated: boolean;
}
export interface SaveTestEvent { event: TestEventPayload; operator: string; reason: string }
export interface TestEventComparison extends TestEventRecord {
  data_state: "local_snapshot"; comparison_scope: "same_event_only";
  event: Omit<TestEventPayload, "participants" | "metrics" | "measurements">;
  participants: (TestParticipant & { id: string })[]; metrics: TestMetricDefinition[]; measurements: TestMeasurement[];
  ranking: "source_reported_only"; notice: string;
}

export interface VehicleCandidate {
  source_setting?: import("./source-management").SourceSettingView;
  id: string;
  manufacturer: string;
  model: string;
  generation: string;
  model_year: number | null;
  region: string;
  status: string;
  source_id: string;
  source_page: string;
  description: string;
}

export interface VehicleDescription extends Omit<VehicleCandidate, "manufacturer" | "status" | "source_id" | "source_page" | "description"> {
  manufacturer: { id: string; name: string };
  source_vehicle_id: string;
  source_version?: string | number | null;
}

export interface VehicleTrim {
  id: string;
  name: string;
  source_trim_id: string;
  model_year: number | null;
  wheel_option_ids: string[];
}

export interface AxleSpecification {
  size: string;
  load_index: string | null;
  speed_rating: string | null;
  oe_mark: string | null;
  manufacturer_product_code: string | null;
  matched_tire_variant_id: string | null;
}

export interface WheelFitment {
  id: string;
  trim_id: string;
  trim_name: string;
  wheel_option_name: string;
  wheel_diameter_inches: number;
  availability: "standard" | "optional" | "unavailable";
  front: AxleSpecification;
  rear: AxleSpecification;
  staggered: boolean;
  source_tire_description: string | null;
  constraints: string[];
  source_description: string;
  evidence_locator: string;
}

export interface VehicleFitmentResult {
  fallback_authorization?: import("./warehouse-fallback").WarehouseFallbackAuthorization;
  fallback_failure?: import("./local-fallback").LocalFallbackFailure;
  query_id: string;
  vehicle_id: string;
  source_id: string;
  data_state: DataState;
  reason: string | null;
  consent_id: string | null;
  verified_at: string | null;
  snapshot_observed_at: string | null;
  snapshot_age_seconds: number | null;
  fact_version: number | null;
  vehicle: VehicleDescription | null;
  trims: VehicleTrim[];
  fitments: WheelFitment[];
  coverage: { notice?: string; [key: string]: unknown } | null;
  documents: { url: string; title?: string; status: string }[];
  footnotes: unknown[];
  provenance: (Provenance & { source_page?: string; evidence_path?: string })[];
}

export interface SourceFieldConflict {
  field: string;
  values: { source_field?: string; source_id?: string; value: unknown }[];
  resolution: string;
  variant_id?: string;
  snapshot_id?: string;
  source_id?: string;
  scope?: string;
}

export interface SourceHealthRecord {
  source_id: string;
  status: "unknown" | "healthy" | "degraded" | "quarantined";
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_reason: string | null;
  attempts: number;
  successes: number;
  failures: number;
  quarantined_count: number;
  rejected_count: number;
}

export interface SourceHealthResult {
  window: { kind: "rolling_24h"; since: string; until: string };
  sources: SourceHealthRecord[];
}

export interface SourceHealthTrendDay {
  date: string; attempts: number; successes: number; failures: number; rejected: number;
}
export interface SourceHealthTrends {
  window: { kind: "daily"; days: number; since_date: string; until_date: string };
  sources: { source_id: string; days: SourceHealthTrendDay[] }[];
}
export interface AIUsageHistory {
  since_date: string; until_date: string; accounting: string;
  days: { date: string; requests: number; accounted_tokens: number }[];
}

export interface QualityMetrics {
  baseline_rows: number;
  candidate_rows: number;
  aligned_rows: number;
  lost_rows: number;
  row_loss_ratio: number;
  known_fields: number;
  lost_fields: number;
  field_loss_ratio: number;
}

export interface QuarantineRecord {
  id: string;
  source_id: string;
  query_id: string;
  source_url: string;
  parser_version: string;
  observed_at: string;
  raw_hash: string;
  previous_snapshot_id: string | null;
  status: "quarantined";
  kind: "field_loss" | "response_rejected";
  stage?: "parser" | "schema";
  target_kind?: "tire" | "vehicle" | "recall";
  reason_codes: string[];
  metrics: QualityMetrics | null;
  evidence_path: string;
}

export interface QuarantineEvidence extends QuarantineRecord {
  data_state: "local_snapshot";
  accepted: false;
  body: string;
  content_type: string;
  candidates: Record<string, unknown>[];
  quality: QualityReport | null;
}

export interface QuarantineReviewEvent {
  id: string;
  quarantine_id: string;
  revision: number;
  action: "approve" | "keep_quarantined";
  operator: string;
  reason: string;
  created_at: string;
  expires_at: string;
}
export interface QuarantineReviewState {
  quarantine_id: string;
  scope: "local_workspace";
  state: "pending" | "restricted" | "stale_baseline" | "kept_quarantined" | "expired" | "approved_waiting_online" | "applied_on_online_fetch";
  revision: number;
  can_approve: boolean;
  restriction: string | null;
  baseline_snapshot_id: string;
  current_snapshot_id: string | null;
  applied_query_id: string | null;
  comparison: { before: unknown; candidate: unknown };
  history: QuarantineReviewEvent[];
  history_truncated: boolean;
}
export interface QuarantineReviewRequest {
  action: "approve" | "keep_quarantined";
  expected_revision: number;
  operator: string;
  reason: string;
  confirmed_loss: boolean;
}

export type QualityReport = Omit<QualityMetrics, "lost_fields"> & {
    ruleset: string;
    threshold: number;
    lost_field_count: number;
    reason_codes: string[];
    lost_fields: { row_key: string; paths: string[] }[];
    lost_row_keys: string[];
    ambiguous_keys: string[];
    groups?: Record<string, QualityReport>;
  };

export interface RawCaptureRecord {
  id: string;
  query_id: string;
  query?: Record<string, string>;
  source_id: string;
  target_kind: "tire" | "vehicle" | "recall";
  source_url: string;
  raw_hash: string;
  byte_count: number;
  content_type: string;
  parser_version: string;
  parser_identity?: ParserIdentity | null;
  observed_at: string;
  query_state: string;
  query_reason: string | null;
  processing_unconfirmed: boolean;
  evidence_path: string;
}

export interface RawCaptureEvidence extends RawCaptureRecord {
  data_state: "local_snapshot";
  receipt_only: true;
  body: string;
}

export interface ReparseParser {
  source_id: string;
  target_kind: "tire" | "vehicle" | "recall";
  parser_version: string;
  parser_digest: string;
  bundle_id?: string;
  execution_digest?: string;
  isolation: "process_fault_isolation";
  network_enforced: boolean;
}
export interface ReparseCatalog {
  scope: "workspace";
  data_state: "local_snapshot";
  accepted_as_facts: false;
  available: boolean;
  parsers: ReparseParser[];
  limits: { max_body_bytes: number; max_output_bytes: number; timeout_seconds: number;
    max_stderr_bytes?: number; cpu_seconds?: number; max_memory_bytes?: number; max_concurrency?: number;
    max_candidate_bytes?: number; max_baseline_bytes?: number; unknown_after_seconds?: number };
  notice: string;
}
export interface ReparseCreate {
  mode: "history";
  capture_id: string;
  parser_version: string;
  parser_digest: string;
  bundle_id?: string;
}
export type ReparseReviewStatus = "reviewed" | "needs_fix" | "rejected";
export interface ReparseReview {
  id: string;
  revision: number;
  status: ReparseReviewStatus;
  operator: string;
  reason: string;
  created_at: string;
}
export interface ReparseInput {
  capture_id: string; query_id: string; source_id: string; target_kind: "tire" | "vehicle" | "recall";
  query: Record<string, unknown>; query_key: string; source_url: string; content_type: string;
  raw_hash: string; byte_count: number; observed_at: string; storage_kind: string; original_parser_version: string;
}
export interface ReparseBaseline {
  snapshot_id: string; verification_id: string | null; verified_at: string | null;
  observed_at: string; raw_hash: string; selected_at: string;
  source_url: string; parser_version: string;
}
export interface ReparseCompletionSummary {
  error_code: string | null; completed_at: string; candidate_hash: string | null;
  quality_reason_codes: string[]; quality_blocked: boolean | null;
}
export interface ReparseDiff {
  baseline_available: boolean;
  added_row_keys: string[];
  removed_row_keys: string[];
  changed_rows: { row_key: string; changes: { path: string; before: unknown; after: unknown; before_present: boolean; after_present: boolean }[] }[];
  identity_changed_row_keys: string[];
  total_changed_fields: number;
  truncated: boolean;
}
export interface ReparseSummary {
  id: string; scope: "workspace"; data_state: "local_snapshot"; accepted_as_facts: false;
  state: "pending" | "unknown" | "completed" | "failed";
  created_at: string; started_at: string; input: ReparseInput; parser: { version: string; digest: string; bundle_id?: string };
  baseline: ReparseBaseline | null; completion: ReparseCompletionSummary | null;
  review_revision: number; latest_review: ReparseReview | null; notice: string;
}
export interface ReparseDetail extends ReparseSummary {
  baseline: (ReparseBaseline & { payload: unknown }) | null;
  baseline_current: boolean;
  completion: (ReparseCompletionSummary & { candidate: unknown; quality: (QualityReport & { blocked: boolean }) | null;
    diff: ReparseDiff | null; receipt: Record<string, unknown>; fingerprint: string }) | null;
  reviews: ReparseReview[];
  reviews_truncated?: boolean;
}
export interface ReparseList {
  scope: "workspace"; data_state: "local_snapshot"; accepted_as_facts: false;
  items: ReparseSummary[]; total: number; offset: number; limit: number;
}
export interface ReparseReviewRequest {
  mode: "history"; expected_revision: number; status: ReparseReviewStatus; operator: string; reason: string;
}

export interface ParserIdentity { bundle_id: string; parser_digest: string; deployment_revision: number }
export interface ParserPage<T> { items: T[]; total: number; offset: number; limit: number }
export interface ParserBundle {
  id: string; created_at: string; origin: string; operator: string; reason: string;
  parsers: ReparseParser[]; environment: Record<string, unknown>; notice: string;
  scope: "local_workspace"; production_deployment: false;
}
export interface ParserDeploymentRevision {
  golden_gate?: import("./golden").GoldenGate;
  source_id: string; revision: number; state: "active" | "paused"; bundle_id: string; parser: ReparseParser;
  action: "bootstrap" | "activate" | "pause" | "resume" | "rollback";
  evaluation_review_id: string | null; rollback_revision: number | null;
  operator: string; reason: string; created_at: string; notice: string;
}
export interface ParserDeployment {
  golden_gate?: import("./golden").GoldenGate;
  source_id: string; revision: number; state: "active" | "paused" | "builtin_unsealed";
  bundle_id?: string; parser?: ReparseParser; history: ParserDeploymentRevision[];
  history_truncated: boolean; notice: string;
}
export interface ParserEvaluationReview {
  id: string; revision: number; action: "approve" | "reject"; completion_fingerprint: string;
  acknowledged_reference_gaps: boolean; operator: string; reason: string; created_at: string;
}
export interface ParserEvaluationResult {
  golden_report?: import("./golden").GoldenCaseReport | null;
  capture_id: string; reference_kind: "accepted_same_raw" | "control_same_raw" | "unavailable";
  candidate: unknown; control: unknown; quality: QualityReport | null; diff: ReparseDiff | null;
  candidate_receipt: Record<string, unknown>; control_receipt: Record<string, unknown>;
  candidate_error: string | null; control_error: string | null;
}
export interface ParserEvaluation {
  golden_gate?: import("./golden").GoldenGate;
  id: string; source_id: string; target_bundle_id: string; control_bundle_id: string;
  deployment_revision: number; deployment_stale: boolean; created_at: string; capture_ids: string[];
  state: "pending" | "unknown" | "completed" | "failed"; review_revision: number;
  latest_review: ParserEvaluationReview | null; can_approve: boolean; accepted_as_facts: false; notice: string;
  completion: { fingerprint: string; hard_blocks: { capture_id?: string; code: string }[];
    reference_gaps: string[]; completed_at: string; results?: ParserEvaluationResult[] } | null;
  bindings?: { input: ReparseInput; reference: { snapshot_id: string; raw_hash: string; observed_at: string; payload: unknown } | null;
    golden?: { set_id: string; set_revision: number; set_fingerprint: string; contract: Record<string, unknown>;
      parser: ReparseParser; case: { expected: import("./golden").GoldenExpected; [key: string]: unknown } } }[];
  reviews?: ParserEvaluationReview[]; reviews_truncated?: boolean;
}
export interface ParserEvaluationCreate {
  golden_set_id?: string; expected_golden_set_revision?: number; golden_set_fingerprint?: string;
  mode: "history"; source_id: string; target_bundle_id: string; capture_ids: string[];
  expected_deployment_revision: number;
}
export interface ParserSignedAction { operator: string; reason: string }
export interface ParserEvaluationReviewCreate extends ParserSignedAction {
  mode: "history"; expected_revision: number; completion_fingerprint: string;
  action: "approve" | "reject"; acknowledged: true; acknowledge_reference_gaps: boolean;
}
export type ParserTransition = ParserSignedAction & { expected_revision: number } & (
  { action: "activate"; target_bundle_id: string; evaluation_id: string; expected_review_revision: number } |
  { action: "rollback"; target_revision: number } | { action: "pause" | "resume" }
);

export interface GarageAxle { size: string | null; current_variant_id: string | null }
export interface GarageProfile {
  nickname: string; manufacturer: string; model: string; model_year: number | null;
  generation: string | null; trim: string | null; wheel_option: string | null; optional_wheels: string[];
  front: GarageAxle; rear: GarageAxle;
}
export type GarageTire = Omit<Variant, "facts" | "snapshot_id">;
export interface GarageRecord {
  id: string; revision: number; archived: boolean; profile: GarageProfile;
  basis: "user_entry" | "copied_fitment"; updated_at: string; data_state: "local_snapshot";
  fitment_reference: (Provenance & { fitment_id: string; availability: string; constraints: string[]; source_description: string }) | null;
  current_tires: { front: GarageTire | null; rear: GarageTire | null };
}
export interface GarageDetail extends GarageRecord {
  history_truncated: boolean;
  history: { revision: number; operation: string; archived: boolean; profile: GarageProfile; basis: string; created_at: string }[];
}
export interface GarageList { data_state: "local_snapshot"; scope: "local_workspace"; items: GarageRecord[]; limit: number; offset: number; total: number }

export type { IdentityResolution, IdentityEndpoint, IdentityDifference, IdentityBinding, IdentityPreview, IdentityDecision,
  IdentityRevision, IdentityReview, IdentityMapping, IdentityCandidates, IdentityDecisionResult } from "./identity";
import type { IdentityResolution, IdentityMapping } from "./identity";

export interface ComparisonView {
  resolve_identities?: boolean; identity_mappings?: IdentityMapping[];
  data_state: "local_snapshot"; variant_ids: string[]; include_manual: boolean; fingerprint: string;
  variants: Variant[]; excluded_variants: ExcludedVariant[]; provenance: Provenance[]; conflicts: SourceFieldConflict[]; notice: string;
}
export interface SaveComparisonRequest {
  resolve_identities?: boolean;
  variant_ids: string[]; include_manual: boolean; expected_fingerprint: string; title: string; notes: string;
}
export interface SavedComparisonRecord {
  id: string; title: string; notes: string; revision: number; archived: boolean;
  created_at: string; updated_at: string; fingerprint: string; variant_count: number; include_manual: boolean;
}
export interface SavedComparisonDetail extends SavedComparisonRecord {
  current_identity_resolutions?: Record<string, IdentityResolution>;
  data_state: "local_snapshot"; comparison: ComparisonView; current_lifecycle: Record<string, VariantLifecycle>;
  history_truncated: boolean;
  history: { revision: number; title: string; notes: string; operation: string; archived: boolean; created_at: string }[];
}
export type DrivingWeightKey = "dry" | "wet" | "quiet" | "comfort" | "wear" | "energy" | "appearance";
export type DrivingWeights = Record<DrivingWeightKey, number>;
export interface DrivingPreferenceState {
  scope: "local_workspace"; revision: number; weights: DrivingWeights | null; updated_at: string | null;
  history_truncated: boolean; notice: string;
  history: { revision: number; weights: DrivingWeights | null; created_at: string }[];
}
export interface AuthUser { id: string; username: string; display_name: string; is_admin: boolean; }
export interface AuthState { authenticated: boolean; user: AuthUser | null; }
export interface AuthUserListItem { id: string; username: string; display_name: string; is_admin: boolean; session_count: number; }
export interface RoleUpdateRequest { is_admin: boolean }
export interface PasswordResetRequest { new_password: string }
