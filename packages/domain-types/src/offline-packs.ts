import type { GarageProfile, GarageRecord } from "./index";
import type { DeviceFallbackStorageV2 } from "./device-fallback";

export type OfflineReference =
  | { kind: "tire"; snapshot_id: string; variant_id: string; verification_id?: string }
  | { kind: "vehicle"; snapshot_id: string; verification_id?: string }
  | { kind: "test_event"; event_id: string; event_revision: number }
  | { kind: "recall"; snapshot_id: string; recall_revision_id: string | null; verification_id?: string };
export type ResolvedOfflineReference =
  | (Exclude<OfflineReference, { kind: "test_event" }> & { verification_id: string })
  | Extract<OfflineReference, { kind: "test_event" }>;
export interface OfflineScope {
  garage: { include: boolean; vehicle_ids: string[] | null };
  watchlist: { include: boolean; item_ids: string[] | null };
  recent: { include: boolean; limit: number };
  references: OfflineReference[];
}
export interface OfflineCapacity {
  version: "offline-policy@1"; max_package_bytes: number; max_distinct_evidence: number;
  max_garage_profiles: number; max_watch_items: number; max_recent_query_candidates: number;
  max_searchable_documents: number;
  plan_ttl_seconds: number; raw_policy: "exclude";
}
export interface OfflineCounts { garage_profiles: number; watch_items: number; recent_queries: number; distinct_evidence: number; searchable_documents: number }
export interface OfflineMemberReason {
  selector: "garage" | "watchlist" | "recent" | "explicit";
  scope: "local_workspace" | "current_session" | "explicit";
  object_id: string | null; revision: number | null; axle: "front" | "rear" | null;
}
export interface OfflineResolvedMember {
  key: string; reference: ResolvedOfflineReference; member_reasons: OfflineMemberReason[];
  privacy_class: "public" | "private" | "restricted"; raw_included: false;
}
export interface OfflineOmission { selector: string; object_id: string | null; reason: string; blocking: boolean }
export interface OfflinePlanRequest { mode: "history"; scope: OfflineScope; base_pack_id: string | null }
export interface OfflinePlan {
  schema: "offline-pack-plan@1"; id: string; package_id: string; state: "ready" | "blocked";
  created_at: string; expires_at: string; fingerprint: string; owner_scope_id: string;
  privacy_class: "private" | "restricted"; requested_scope: OfflineScope; base_pack_id: string | null;
  resolved: OfflineResolvedMember[]; omissions: OfflineOmission[]; counts: OfflineCounts;
  contexts: OfflineContext[]; documents: OfflineDocument[];
  measured_bytes: number; content_sha256: string | null; capacity: OfflineCapacity; can_confirm: boolean;
  privacy_notice: string; rights_notice: string; diff: { added: string[]; removed: string[]; changed: string[] };
}
export interface OfflineConfirmRequest { plan_id: string; expected_fingerprint: string; allow_device_storage: true }
export interface OfflinePackDescriptor {
  schema: "offline-pack-descriptor@1"; id: string; plan_id: string; created_at: string; content_created_at: string;
  plan_fingerprint: string; owner_scope_id: string; privacy_class: "private" | "restricted";
  sha256: string; byte_count: number; base_pack_id: string | null; counts: OfflineCounts;
  download_path: string; data_state: "local_snapshot"; source_refresh_performed: false;
}
export type OfflineContext = { id: string; privacy_class: "private"; evidence_keys: string[] } & (
  { kind: "garage"; scope: "local_workspace"; payload: {
    vehicle_id: string; revision: number; basis: GarageRecord["basis"]; profile: GarageProfile;
    fitment_reference: GarageRecord["fitment_reference"]; created_at: string;
  } } |
  { kind: "watchlist"; scope: "current_session"; payload: { item_id: string; variant_id: string; created_at: string } }
);
export interface OfflineSource {
  source_id: string | null; source_url: string | null; raw_hash: string | null; parser_version: string | null;
  parser_identity: Record<string, unknown> | null; observed_at: string; verified_at: string | null; verification_id: string | null;
}
export interface OfflineMember extends OfflineResolvedMember { source: OfflineSource; payload: Record<string, unknown> }
export interface OfflineDocument {
  id: string; category: "evidence" | "garage" | "watchlist";
  kind: "tire" | "vehicle" | "test_event" | "recall" | "garage" | "watchlist";
  member_key: string | null; context_id: string | null; record_index: number | null; title: string; text: string;
  facets: { brand: string | null; model: string | null; size: string | null; source_id: string | null; campaign_number: string | null };
  membership: OfflineMemberReason["selector"][]; privacy_class: "public" | "private" | "restricted";
  observed_at: string | null; verified_at: string | null;
}
export interface OfflineEnvelope {
  schema: "offline-pack@1"; package_id: string; created_at: string; plan_fingerprint: string; owner_scope_id: string;
  privacy_class: "private" | "restricted"; data_state: "local_snapshot"; source_refresh_performed: false;
  base_pack_id: string | null; scope: OfflineScope;
  contracts: { offline_policy: "offline-policy@1"; field_policy: Record<string, unknown>; recall_policy: Record<string, unknown> };
  contexts: OfflineContext[]; members: OfflineMember[]; documents: OfflineDocument[]; omissions: OfflineOmission[];
}

// Host-only contract, shared by IndexedDB, Tauri and Capacitor. Independent of API health.
export interface OfflineHostStatus {
  schema: "offline-host@1"; available: boolean; state: "ready" | "unavailable" | "error";
  storage: "indexeddb" | "native_encrypted_files"; profile_id: string | null; owner_epoch: number;
  // Committed original bytes, excluding AEAD/catalog overhead and bounded staging.
  total_bytes: number; max_store_bytes: number; max_package_bytes: number; max_slots: number;
  encryption: "webcrypto" | "os_secure_store" | "android_keystore";
  persistence: "best_effort" | "persistent_granted" | "app_private";
  manual_updates: true; background_updates: false; error: string | null;
}
export interface OfflineSlot {
  slot_id: string; generation: number; package_id: string; sha256: string; byte_count: number;
  title: string; created_at: string; installed_at: string; privacy_class: "private" | "restricted";
  owner_scope_id: string; locked: boolean; previous_owner: boolean; counts: OfflineCounts;
}
export interface OfflineHostList {
  schema: "offline-host@1"; data_state: "local_snapshot";
  profile_id: string; owner_epoch: number; items: OfflineSlot[];
}
export interface OfflineInstallRequest {
  package_id: string; expected_sha256: string; expected_byte_count: number; approved_plan_fingerprint: string;
  slot_id: string; expected_generation: number; allow_device_storage: true;
}
export interface OfflineSlotRequest { slot_id: string; expected_generation: number }
export interface OfflineSearchRequest extends OfflineSlotRequest {
  query: string; kind?: import("./offline-packs-v2").OfflineDocumentV2["kind"]; limit: number; offset: number;
}
export interface OfflineSearchResult {
  data_state: "local_snapshot"; slot: OfflineSlot; items: import("./offline-packs-v2").OfflineDocumentV2[];
  total: number; offset: number; limit: number; has_more: boolean;
}
export interface OfflineReadRequest extends OfflineSlotRequest { document_id: string }
export interface OfflineReadResult {
  data_state: "local_snapshot"; slot: OfflineSlot; document: import("./offline-packs-v2").OfflineDocumentV2;
  member: import("./offline-packs-v2").OfflineMemberV2 | null; context: OfflineContext | null;
}
export interface OfflineRemoveResult { removed: true; slot_id: string; generation: number }
export interface OfflineUnlockRequest extends OfflineSlotRequest { allow_previous_owner: true }
export interface OfflineStorage extends Partial<DeviceFallbackStorageV2> {
  status(): Promise<OfflineHostStatus>;
  list(): Promise<OfflineHostList>;
  install(request: OfflineInstallRequest, signal?: AbortSignal): Promise<OfflineSlot>;
  search(request: OfflineSearchRequest): Promise<OfflineSearchResult>;
  read(request: OfflineReadRequest): Promise<OfflineReadResult>;
  remove(request: OfflineSlotRequest): Promise<OfflineRemoveResult>;
  unlockPreviousOwner(request: OfflineUnlockRequest): Promise<OfflineSlot>;
  decideFallback?(request: import("./local-fallback").LocalFallbackDecideRequest): Promise<import("./local-fallback").LocalFallbackGrant>;
  consumeFallback?(request: import("./local-fallback").LocalFallbackConsumeRequest): Promise<import("./local-fallback").LocalFallbackResult>;
  revokeFallback?(request: import("./local-fallback").LocalFallbackRevokeRequest): Promise<import("./local-fallback").LocalFallbackRevokeResult>;
  syncStatus?(): Promise<import("./device-sync").DeviceSyncStatus>;
  previewSyncPolicy?(request: import("./device-sync").DeviceSyncPreviewRequest): Promise<import("./device-sync").DeviceSyncPreview>;
  applySyncPolicy?(request: import("./device-sync").DeviceSyncApplyRequest): Promise<import("./device-sync").DeviceSyncPolicy>;
  pauseSyncPolicy?(request: import("./device-sync").DeviceSyncPolicyRequest): Promise<import("./device-sync").DeviceSyncPolicy>;
  revokeSyncPolicy?(request: import("./device-sync").DeviceSyncPolicyRequest): Promise<import("./device-sync").DeviceSyncPolicy>;
  runSyncPolicy?(request: import("./device-sync").DeviceSyncRunRequest): Promise<import("./device-sync").DeviceSyncRun>;
  revalidateSync?(): Promise<import("./device-sync").DeviceSyncStatus>;
}
