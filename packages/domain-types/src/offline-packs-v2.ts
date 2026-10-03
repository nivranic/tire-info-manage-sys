import type { OfflineReference, ResolvedOfflineReference, OfflineScope, OfflineResolvedMember, OfflineMember,
  OfflinePlan, OfflinePackDescriptor, OfflineDocument, OfflineEnvelope, OfflineReadResult } from "./offline-packs";
import type { RecallSearchProduct, RecallSearchResult } from "./recalls";
import type { ExactNumericToken } from "./filters";

/** Historical business payload numbers retain their exact JSON token; host metadata stays bounded. */
export type DeviceHistoricalValue<T> = T extends number ? number | ExactNumericToken
  : T extends readonly unknown[] ? { [Index in keyof T]: DeviceHistoricalValue<T[Index]> }
  : T extends object ? { [Key in keyof T]: DeviceHistoricalValue<T[Key]> } : T;

/** New schema, never a new reference kind inside an offline-pack@1 envelope. */
export type OfflinePackSchema = "offline-pack@1" | "offline-pack@2";
export interface OfflineRecallSearchReference {
  kind: "recall_search";
  snapshot_id: string;
  verification_id: string;
}
export type OfflineReferenceV2 = OfflineReference | OfflineRecallSearchReference;
export type ResolvedOfflineReferenceV2 = ResolvedOfflineReference | OfflineRecallSearchReference;
export interface OfflineScopeV2 extends Omit<OfflineScope, "references"> { references: OfflineReferenceV2[] }
export interface OfflineResolvedMemberV2 extends Omit<OfflineResolvedMember, "reference"> { reference: ResolvedOfflineReferenceV2 }
export interface OfflineRecallSearchPayload extends Record<string, unknown> {
  query: { search: string; offset: string };
  discovery: DeviceHistoricalValue<{ products: RecallSearchProduct[]; pagination: NonNullable<RecallSearchResult["pagination"]> }>;
  discovery_hash: string;
  notices: string[];
  evidence: { snapshot_id: string; query_id: string; verification_id: string; data_state: "local_snapshot";
    observed_at: string; verified_at: string };
  empty_observation: boolean;
  boundary: { kind: "recall_search_candidate_page"; formal_campaign_revision: false; applicability: "not_assessed"; complete_query_result: false };
}
export type OfflineMemberV2 = OfflineMember | (Omit<OfflineMember, "reference" | "payload"> & {
  reference: OfflineRecallSearchReference;
  payload: OfflineRecallSearchPayload;
});
export interface OfflineDocumentV2 extends Omit<OfflineDocument, "kind"> { kind: OfflineDocument["kind"] | "recall_search" }
export interface OfflinePlanRequestV2 {
  mode: "history";
  scope: OfflineScopeV2;
  base_pack_id: string | null;
  /** Omission in the legacy DTO means @1 only; new callers explicitly negotiate. */
  supported_pack_schemas: OfflinePackSchema[];
}
export interface OfflinePlanV2 extends Omit<OfflinePlan, "schema" | "requested_scope" | "resolved" | "documents"> {
  schema: "offline-pack-plan@2";
  requested_scope: OfflineScopeV2;
  resolved: OfflineResolvedMemberV2[];
  documents: OfflineDocumentV2[];
}
export interface OfflinePackDescriptorV2 extends Omit<OfflinePackDescriptor, "schema"> { schema: "offline-pack-descriptor@2" }
export interface OfflineEnvelopeV2 extends Omit<OfflineEnvelope, "schema" | "scope" | "members" | "documents"> {
  schema: "offline-pack@2";
  scope: OfflineScopeV2;
  members: OfflineMemberV2[];
  documents: OfflineDocumentV2[];
}
export interface OfflinePackUpdateRequestV2 {
  mode: "history";
  base_pack_id: string;
  expected_base_sha256: string;
  scope: OfflineScopeV2;
  supported_pack_schemas: OfflinePackSchema[];
}
export interface OfflinePackUpdateV2 {
  schema: "offline-pack-update@2";
  state: "no_change" | "planned";
  mode: "history";
  base_pack_id: string;
  base_semantic_digest: string;
  current_semantic_digest: string;
  base_pack: OfflinePackDescriptorV2;
  plan: OfflinePlanV2 | null;
  source_refresh_performed: false;
}
export type AnyOfflinePlan = OfflinePlan | OfflinePlanV2;
export type AnyOfflinePackDescriptor = OfflinePackDescriptor | OfflinePackDescriptorV2;
export type AnyOfflineEnvelope = OfflineEnvelope | OfflineEnvelopeV2;
export interface OfflineReadResultV2 extends OfflineReadResult {
  schema: "offline-read-result@2";
  package_schema: "offline-pack@2";
}
