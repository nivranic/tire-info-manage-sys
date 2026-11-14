export type SamrRecallQuery = {
  operation: "search";
  keyword: string;
  page: string;
} | {
  operation: "notice";
  reference: string;
};

export interface SamrRecallNoticeSummary {
  article_id: string;
  reference: string;
  source_url: string;
  title: string;
  published_date: string;
  publication_date_raw: string;
  applicability: "not_assessed";
}

export interface SamrRecallAsset {
  kind: "image" | "link";
  source_reference: string;
  url: string | null;
  label: string;
  fetch_status: "not_fetched";
}

export interface SamrRecallNotice extends SamrRecallNoticeSummary {
  deployed_at_raw: string;
  pub_date_raw: string;
  content_source_raw: string;
  text: string;
  assets: SamrRecallAsset[];
  metadata: Record<string, string>;
}

export type SamrRecallDocument = {
  operation: "search";
  keyword: string;
  page: number;
  page_size: 15;
  declared_total: number;
  source_navigation_page_limit: 60;
  source_navigation_pages: number;
  notices: SamrRecallNoticeSummary[];
  notice: null;
} | {
  operation: "notice";
  notices: [];
  notice: SamrRecallNotice;
};

export interface SamrRecallProvenance {
  snapshot_id: string;
  source_id: "samr-cn-recalls";
  source_url: string;
  raw_hash: string;
  observed_at: string;
  parser_version: string;
  parser_identity: Record<string, unknown> | null;
  access_basis: {
    kind: "official_public_recall_pages";
    homepage: string;
    redistribution_license: "unverified";
    ai_provider_use: "requires_separate_authorization";
  };
  attribution: string;
  evidence_path: string;
}

export interface SamrRecallResult {
  query_id: string | null;
  source_id: "samr-cn-recalls";
  query: SamrRecallQuery;
  data_state: "live" | "live_verified_304" | "local_snapshot" | "consent_required" | "source_unavailable";
  reason: string | null;
  consent_id: string | null;
  fallback_authorization?: import("./warehouse-fallback").WarehouseFallbackAuthorization;
  verified_at: string | null;
  snapshot_observed_at: string | null;
  document: SamrRecallDocument | null;
  notices: string[];
  provenance: SamrRecallProvenance[];
}

export interface SamrRecallEvidence extends SamrRecallProvenance {
  id: string;
  query: SamrRecallQuery;
  body: string;
  content_type: "application/json" | "text/html";
  data_state: "local_snapshot";
}

export interface SamrNoticeObservation {
  id: string;
  sequence: number;
  snapshot_id: string;
  verification_id: string;
  observed_at: string;
  evidence_path: string;
  revision: {
    id: string;
    revision: number;
    content_hash: string;
    notice: SamrRecallNotice;
    first_snapshot_id: string;
  };
  event: {
    id: string;
    kind: "first_observed" | "content_changed";
    before_revision_id: string | null;
    after_revision_id: string;
    previous_snapshot_id: string | null;
    changes: Record<string, { before: unknown; after: unknown }>;
  } | null;
}

export interface SamrNoticeHistory {
  source_id: "samr-cn-recalls";
  article_id: string;
  data_state: "local_snapshot";
  applicability: "not_assessed";
  offset: number;
  limit: number;
  total: number;
  through_sequence: number;
  head: SamrNoticeObservation;
  observations: SamrNoticeObservation[];
  notices: string[];
}
