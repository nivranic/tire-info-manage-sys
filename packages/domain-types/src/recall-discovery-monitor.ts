/** A durable name-discovery target always starts at the first source page. */
export interface RecallDiscoveryQuery { search: string }

export interface RecallDiscoveryBudget {
  max_pages_per_pass: number; max_products_per_pass: number; required_passes: number;
  max_page_operations: number; max_elapsed_seconds: number; max_raw_bytes: number; lease_seconds: number;
}
export interface RecallDiscoveryCoverage {
  status: "complete" | "incomplete"; passes_required: 2; passes_completed: number;
  pass_fingerprints: string[]; page_operations: number; pages_completed: number;
  products_count: number; candidates_count: number; new_candidates_count: number;
  raw_bytes: number; elapsed_seconds: number; budget: RecallDiscoveryBudget;
  baseline_advanced: boolean; is_initial_baseline: boolean;
}
export interface RecallDiscoveryRun {
  id: string; job_id: string; attempt_id: string; state: string; reason: string | null;
  started_at: string; finished_at: string | null; previous_complete_id: string | null;
  coverage: RecallDiscoveryCoverage;
}
export interface RecallDiscoveryRuleSettings { name: string; enabled: boolean; archived: boolean; interval_seconds: number }
export interface RecallDiscoveryRuleRevision extends RecallDiscoveryRuleSettings { revision: number; created_at: string }
export interface RecallDiscoveryRule extends RecallDiscoveryRuleRevision {
  id: string; source_id: string; query: RecallDiscoveryQuery;
  job: { id: string; next_due_at: string | null; lease_until: string | null; last_run: RecallDiscoveryRun | null };
  baseline: RecallDiscoveryRun | null; budget: RecallDiscoveryBudget; notice: string;
}
export interface RecallDiscoveryRuleDetail extends RecallDiscoveryRule { history: RecallDiscoveryRuleRevision[]; history_truncated: boolean }
export interface RecallDiscoveryRuleWrite extends RecallDiscoveryRule { write_result: { revision_id: string; revision: number; replayed: boolean } }
export interface RecallDiscoveryPage {
  id: string; attempt_id: string; pass_number: 1 | 2; offset: number;
  query_id: string | null; verification_id: string | null; snapshot_id: string | null;
  total: number | null; count: number | null; content_fingerprint: string | null;
  raw_bytes: number; observed_at: string;
}
export interface RecallDiscoveryCandidate {
  id: string; campaign_number: string; first_seen_run_id: string; first_seen_at: string;
  campaign: Record<string, unknown>;
  evidence: { page_id: string; snapshot_id: string; query_id: string; product_ids: number[] }[];
  applicability: "not_assessed";
}
export interface RecallDiscoveryRunDetail extends RecallDiscoveryRun {
  scope: "session"; query: RecallDiscoveryQuery; source_id: string;
  pages: RecallDiscoveryPage[]; pages_total: number; page_offset: number; page_limit: number;
  candidates: RecallDiscoveryCandidate[]; candidates_total: number; candidates_truncated: boolean;
}
export interface RecallDiscoveryNotification {
  id: string; rule_id: string; rule_name: string; rule_revision: number; job_id: string;
  query: RecallDiscoveryQuery; candidate: RecallDiscoveryCandidate;
  delivered_at: string; read_at: string | null; kind: "candidate_first_observed";
}
export interface RecallDiscoveryList<T> { scope: "session"; items: T[]; total: number; offset: number; limit: number }
