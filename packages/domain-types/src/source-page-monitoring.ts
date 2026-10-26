import type { TireQuery } from "./index";

/** References accepted UTF-8 source text; observation and verification are distinct times. */
export interface SourcePageEvidenceSide {
  snapshot_id: string;
  verification_id: string;
  raw_hash: string;
  observed_at: string;
  verified_at: string;
  parser_version: string;
}

/** A page event has no SKU identity or parameter diff. */
export interface SourcePageChange {
  id: string;
  kind: "page_changed";
  source_id: string;
  query: TireQuery;
  source_url: string;
  before: SourcePageEvidenceSide;
  after: SourcePageEvidenceSide;
}

export interface SourcePageNotification {
  id: string;
  rule_id: string;
  rule_name: string;
  rule_revision: number;
  read_at: string | null;
  delivered_at: string;
  event: SourcePageChange;
}

export interface SourcePageNotifications {
  scope: "local_workspace";
  data_state: "local_snapshot";
  items: SourcePageNotification[];
  total: number;
  offset: number;
  limit: number;
}

/** The detail endpoint checks the historical references and source text hashes. */
export interface SourcePageNotificationDetail {
  scope: "local_workspace";
  data_state: "local_snapshot";
  item: SourcePageNotification;
}

export interface SourcePageNotificationRead {
  id: string;
  read_at: string | null;
}
