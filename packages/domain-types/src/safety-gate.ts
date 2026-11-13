export type SafetyGateQuery = { operation: "reports" } | {
  operation: "report";
  report_id: string;
  reference: string;
};

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
