import type { SamrNoticeObservation, SamrRecallNoticeSummary, SamrRecallQuery } from "./samr-recalls";

export type SamrMonitorQuery = {
  operation: "search";
  keyword: string;
  page_limit: number;
  notice_limit: number;
  text: string;
} | {
  operation: "notice";
  reference: string;
  text: string;
};

export interface SamrRuleSettings {
  name: string;
  enabled: boolean;
  interval_seconds: number;
  archived: boolean;
}

export interface SamrMonitorCoverage {
  status: "complete" | "incomplete";
  listing_consistency: "not_applicable" | "unconfirmed" | "two_pass_equal" | "changed";
  declared_total: number | null;
  source_navigation_page_limit: 60;
  source_navigation_pages?: number;
  expected_pages: number;
  accepted_search_checks: number;
  selected_notice_count: number;
  checked_notice_count: number;
  discovered_notice_count?: number;
  source_results_fully_covered: boolean;
}

export interface SamrMonitorRun {
  id: string;
  attempt_id: string;
  state: string;
  reason: string | null;
  started_at: string;
  finished_at: string;
  coverage: SamrMonitorCoverage;
  selected_notices: SamrRecallNoticeSummary[];
  notification_count: number;
  checks: {
    query_id: string;
    snapshot_id: string | null;
    verification_id: string | null;
    query: SamrRecallQuery;
    state: string;
    reason: string | null;
    observed_at: string;
  }[];
}

export interface SamrMonitorRule extends SamrRuleSettings {
  id: string;
  source_id: "samr-cn-recalls";
  query: SamrMonitorQuery;
  revision: number;
  created_at: string;
  job: {
    id: string;
    next_due_at: string | null;
    lease_until: string | null;
    last_run: SamrMonitorRun | null;
  };
  notice: string;
}

export interface SamrRuleDetail extends SamrMonitorRule {
  history: (SamrRuleSettings & { revision: number; created_at: string })[];
  history_truncated: boolean;
}

export interface SamrRuleWrite extends SamrMonitorRule {
  write_result: { revision_id: string; revision: number };
}

export interface SamrNotification {
  id: string;
  rule_id: string;
  rule_name: string;
  attempt_id: string;
  run_id: string | null;
  observed_at: string;
  queued_at: string;
  delivered_at: string;
  lag_seconds: number;
  read_at: string | null;
  observation: SamrNoticeObservation;
  applicability: "not_assessed";
}

export interface SamrPage<T> {
  scope: "session";
  data_state: "local_snapshot";
  items: T[];
  total: number;
  offset: number;
  limit: number;
}
