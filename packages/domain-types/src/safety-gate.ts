export type SafetyGateQuery = { operation: "reports" } | {
  operation: "report";
  report_id: string;
  reference: string;
};

export interface SafetyGateAnalysisReference {
  kind: "safety_gate";
  snapshot_id: string;
  alert_id: string;
}

export interface SafetyGateAnalysisTarget {
  query: Extract<SafetyGateQuery, { operation: "report" }>;
  reference: SafetyGateAnalysisReference;
}

export interface SafetyGateAnalysisBoundary {
  policy: "safety-gate-fact-selection@1";
  applicability: "not_assessed";
  mode: "announcement_facts_only";
  notice: string;
}

export interface SafetyGateReport {
  report_id: string;
  reference: string;
  published_date: string;
  publication_date_raw: string;
  url: string;
  addendum_raw?: string | null;
}

export interface SafetyGateAlert {
  alert_id: string;
  case_number: string;
  published_date: string;
  source_url: string;
  fields: Record<string, string | null>;
  pictures: string[];
  applicability: "not_assessed";
}

export interface SafetyGateDocument {
  operation: "reports" | "report";
  reports: SafetyGateReport[];
  report: SafetyGateReport | null;
  alerts: SafetyGateAlert[];
}

export interface SafetyGateProvenance {
  snapshot_id: string;
  source_id: "eu-safety-gate";
  source_url: string;
  raw_hash: string;
  observed_at: string;
  parser_version: string;
  parser_identity: Record<string, unknown> | null;
  license_basis: { distribution_id: string; license_uri: string; metadata_url: string };
  attribution: string;
  evidence_path: string;
}

export interface SafetyGateResult {
  query_id: string | null;
  source_id: "eu-safety-gate";
  query: SafetyGateQuery;
  data_state: "live" | "live_verified_304" | "local_snapshot" | "consent_required" | "source_unavailable";
  reason: string | null;
  consent_id: string | null;
  fallback_authorization?: import("./warehouse-fallback").WarehouseFallbackAuthorization;
  verified_at: string | null;
  snapshot_observed_at: string | null;
  document: SafetyGateDocument | null;
  notices: string[];
  provenance: SafetyGateProvenance[];
}

export interface SafetyGateEvidence extends SafetyGateProvenance {
  id: string;
  query: SafetyGateQuery;
  body: string;
  content_type: "application/xml";
  data_state: "local_snapshot";
}

export interface SafetyGateAlertObservation {
  id: string;
  sequence: number;
  snapshot_id: string;
  position: number;
  report: SafetyGateReport;
  observed_at: string;
  evidence_path: string;
  revision: {
    id: string;
    revision: number;
    content_hash: string;
    alert: SafetyGateAlert;
    first_snapshot_id: string;
  };
  event: {
    id: string;
    kind: "first_observed" | "content_changed" | "conflict_observed" | "conflict_resolved";
    before_revision_ids: string[];
    after_revision_ids: string[];
    changes: Record<string, { before: unknown; after: unknown }>;
  } | null;
}

export interface SafetyGateAlertHistory {
  source_id: "eu-safety-gate";
  alert_id: string;
  data_state: "local_snapshot";
  applicability: "not_assessed";
  state: "observed" | "conflicting";
  offset: number;
  limit: number;
  total: number;
  through_sequence: number;
  heads: SafetyGateAlertObservation[];
  observations: SafetyGateAlertObservation[];
  notices: string[];
}

export interface SafetyGateMonitorQuery {
  report_limit: number;
  text: string;
}

export interface SafetyGateRuleSettings {
  name: string;
  enabled: boolean;
  interval_seconds: number;
  archived: boolean;
}

export interface SafetyGateMonitorRun {
  id: string;
  attempt_id: string;
  state: string;
  reason: string | null;
  started_at: string;
  finished_at: string;
  coverage: "complete" | "incomplete";
  selected_reports: SafetyGateReport[];
  notification_count: number;
  checks: {
    query_id: string;
    snapshot_id: string | null;
    query: SafetyGateQuery;
    state: string;
    reason: string | null;
    observed_at: string;
  }[];
}

export interface SafetyGateMonitorRule extends SafetyGateRuleSettings {
  id: string;
  source_id: "eu-safety-gate";
  query: SafetyGateMonitorQuery;
  revision: number;
  created_at: string;
  job: {
    id: string;
    next_due_at: string | null;
    lease_until: string | null;
    last_run: SafetyGateMonitorRun | null;
  };
  notice: string;
}

export interface SafetyGateRuleDetail extends SafetyGateMonitorRule {
  history: (SafetyGateRuleSettings & { revision: number; created_at: string })[];
  history_truncated: boolean;
}

export interface SafetyGateRuleWrite extends SafetyGateMonitorRule {
  write_result: { revision_id: string; revision: number };
}

export interface SafetyGateNotification {
  id: string;
  rule_id: string;
  rule_name: string;
  run_id: string;
  delivered_at: string;
  read_at: string | null;
  observation: SafetyGateAlertObservation;
  applicability: "not_assessed";
}

export interface SafetyGatePage<T> {
  scope: "session";
  data_state: "local_snapshot";
  items: T[];
  total: number;
  offset: number;
  limit: number;
}
