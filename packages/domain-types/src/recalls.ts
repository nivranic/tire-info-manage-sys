import type { DataState, Evidence, Provenance } from "./index";

export interface RecallQuery { campaign_number: string }
export interface RecallAnalysisReference { kind: "recall"; snapshot_id: string; recall_revision_id: string | null }
export interface RecallBoundary {
  policy: "recall-fact-selection@1"; applicability: "not_assessed";
  mode: "announcement_facts_only"; notice: string;
}
export interface RecallRecord {
  campaign_number: string;
  manufacturer: string | null;
  report_received_date: string | null;
  report_received_date_raw: string | null;
  component: string | null;
  potential_units: number | null;
  summary: string | null;
  consequence: string | null;
  remedy: string | null;
  notes: string | null;
  make: string | null;
  model: string | null;
  model_year_raw: string | null;
  applicability: "not_assessed";
}
export interface RecallRevision {
  id: string; revision: number; snapshot_id: string; previous_snapshot_id: string | null;
  records: RecallRecord[]; observed_at: string; kind: "first_observed" | "content_changed";
}
export interface RecallResult {
  fallback_authorization?: import("./warehouse-fallback").WarehouseFallbackAuthorization;
  analysis_reference?: RecallAnalysisReference | null;
  query_id: string | null; source_id: string; query: RecallQuery; data_state: DataState;
  reason: string | null; verified_at: string | null; snapshot_observed_at: string | null;
  snapshot_age_seconds: number | null; consent_id: string | null; revision: number | null;
  provenance: (Provenance & { evidence_path?: string })[];
  records: RecallRecord[]; notices: string[];
}
export interface RecallHistory extends RecallResult { revisions: RecallRevision[]; revisions_truncated?: boolean }
export interface RecallEvidence extends Evidence { data_state: "local_snapshot"; campaign_number: string; parser_identity?: unknown }
export interface RecallRuleSettings { name: string; enabled: boolean; archived: boolean; interval_seconds: number }
export interface RecallRule extends RecallRuleSettings {
  id: string; source_id: string; query: RecallQuery; revision: number; created_at: string;
  job: { id: string; next_due_at: string | null; lease_until: string | null;
    last_run: { state: string; reason: string | null; finished_at: string | null } | null };
}
export interface RecallRuleDetail extends RecallRule { history: unknown[]; history_truncated?: boolean }
export interface RecallNotification {
  id: string; rule_id: string; rule_name: string; kind: "first_observed" | "content_changed";
  campaign_number: string; source_id: string; snapshot_id: string; previous_snapshot_id: string | null;
  revision: number; observed_at: string; delivered_at: string; read_at: string | null;
  changes: { before: RecallRecord[] | null; after: RecallRecord[] };
}
export interface RecallPage<T> { scope: "session"; data_state: "local_snapshot"; items: T[]; total: number; offset: number; limit: number }

export interface RecallSearchQuery { search: string; offset: number }
export interface RecallSearchCampaign {
  campaign_number: string; subject: string; report_received_at: string;
  summary: string; consequence: string; remedy: string;
  manufacturer: string; notes: string | null;
  documents: { url: string; title: string }[]; associated_products: Record<string, unknown>[];
}
export interface RecallSearchProduct {
  id: number; artemis_id: number; brand: string;
  tireline: string; size: string | null; recalls_count: number;
  campaigns: RecallSearchCampaign[]; applicability: "not_assessed";
}
export interface RecallSearchResult {
  fallback_authorization?: import("./warehouse-fallback").WarehouseFallbackAuthorization;
  query_id: string | null; source_id: string; query: { search: string; offset: string };
  data_state: DataState; reason: string | null; verified_at: string | null;
  snapshot_observed_at: string | null; consent_id: string | null;
  snapshot_age_seconds: number | null;
  provenance: (Provenance & { evidence_path?: string })[];
  products: RecallSearchProduct[];
  pagination: { offset: number; max: number; count: number; total: number; has_next: boolean; has_previous: boolean } | null;
  notices: string[];
}
export interface RecallSearchEvidence extends Evidence { data_state: "local_snapshot"; query?: { search: string; offset: string }; parser_identity?: unknown }
