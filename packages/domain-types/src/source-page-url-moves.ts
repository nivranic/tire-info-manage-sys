import type { TireQuery } from "./index";

/** A URL move never compares content; each side keeps its own accepted address. */
export interface SourcePageUrlMoveSide {
  snapshot_id: string;
  verification_id: string;
  source_url: string;
  observed_at: string;
  verified_at: string;
  parser_version: string;
}

/** A url_moved event carries two accepted addresses for one canonical query. */
export interface SourcePageUrlMove {
  id: string;
  kind: "url_moved";
  source_id: string;
  query: TireQuery;
  previous_source_url: string;
  source_url: string;
  before: SourcePageUrlMoveSide;
  after: SourcePageUrlMoveSide;
}

export interface SourcePageUrlMoveNotification {
  id: string;
  rule_id: string;
  rule_name: string;
  rule_revision: number;
  read_at: string | null;
  delivered_at: string;
  event: SourcePageUrlMove;
}

export interface SourcePageUrlMoveNotifications {
  scope: "local_workspace";
  data_state: "local_snapshot";
  items: SourcePageUrlMoveNotification[];
  total: number;
  offset: number;
  limit: number;
}

/** The detail endpoint checks historical references and both retained texts. */
export interface SourcePageUrlMoveNotificationDetail {
  scope: "local_workspace";
  data_state: "local_snapshot";
  item: SourcePageUrlMoveNotification;
}

export interface SourcePageUrlMoveNotificationRead {
  id: string;
  read_at: string | null;
}
