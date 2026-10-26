import type { EvidenceDocument } from "./index";

/** A configured rights declaration, not a platform grant or copyright verification. */
export interface SourceMaterialRights {
  rights_holder: string;
  basis: string;
  license_url: string | null;
  store_original: true;
  workspace_reopen: true;
  quote_identifiers: true;
  provider_use: false;
  export: false;
}

export interface SourceMaterialPolicy {
  policy_id: string;
  title: string;
  publisher: string;
  edition: string | null;
  published_at: string | null;
  source_reference_url: string;
  download_url: string;
  redirect_urls: string[];
  rights: SourceMaterialRights;
  policy_fingerprint: string;
}

export interface SourceMaterialPolicies {
  scope: "local_workspace";
  items: SourceMaterialPolicy[];
  notice: string;
}

export interface SourceMaterialPreviewRequest {
  policy_id: string;
  expected_policy_fingerprint: string;
}

export interface SourceMaterialPreview {
  policy: SourceMaterialPolicy;
  can_capture: boolean;
  blockers: string[];
  notice: string;
}

export interface SourceMaterialCaptureRequest extends SourceMaterialPreviewRequest {
  idempotency_key: string;
  operator: string;
  rights_confirmed: true;
}

/** Stops future adoption for the original request; it does not confirm a network outcome. */
export interface SourceMaterialStopRequest {
  expected_request_id: string;
  operator: string;
  reason: string;
}

export interface SourceMaterialStop {
  schema: "source-material-stop@1";
  request_id: string;
  idempotency_key: string;
  operator: string;
  reason: string;
  stopped_at: string;
}

export interface SourceMaterialRedirect {
  from_url: string;
  to_url: string;
  status: number;
}

export interface SourceMaterialRobots {
  url: string;
  status: number;
  raw_hash: string | null;
  byte_count: number;
  allowed: true;
  minimum_interval: number;
  target_url: string;
}

export interface SourceMaterialReceipt {
  schema: "source-material-receipt@1";
  request_id: string;
  policy_fingerprint: string;
  source_reference_url: string;
  initial_url: string;
  final_url: string;
  redirects: SourceMaterialRedirect[];
  robots: SourceMaterialRobots[];
  started_at: string;
  completed_at: string;
  raw_hash: string;
  byte_count: number;
  content_type: "application/pdf";
  content_encoding: "identity";
  document_id: string;
  document_metadata_hash: string;
  transport_verification: "https_transport_observed";
  content_authenticity: "unverified";
  source_reference_relation: "operator_configured";
  fingerprint: string;
}

export interface SourceMaterialRequestView {
  request_id: string;
  idempotency_key: string;
  state: "processing_unconfirmed" | "stopped_unconfirmed" | "succeeded" | "failed";
  policy: SourceMaterialPolicy;
  policy_fingerprint: string;
  operator: string;
  requested_at: string;
  completed_at: string | null;
  failure_code: string | null;
  document: EvidenceDocument | null;
  receipt: SourceMaterialReceipt | null;
  /** Old three-state responses may omit this field, which means null. */
  stop?: SourceMaterialStop | null;
  notice: string;
}

export interface SourceMaterialStopResult {
  request: SourceMaterialRequestView;
  effect: "stopped" | "already_stopped" | "already_terminal";
}

/** Only POST /captures adds replayed; reads retain the shared RequestView. */
export interface SourceMaterialCaptureResult extends SourceMaterialRequestView {
  replayed: boolean;
}

export interface SourceMaterialRequests {
  scope: "current_user";
  items: SourceMaterialRequestView[];
  offset: number;
  total: number;
  notice: string;
}
