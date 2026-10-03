import type { OfflineCapacity, OfflineCounts, OfflinePackDescriptor, OfflinePlan, OfflineScope as LegacyOfflineScope, OfflineSlotRequest } from "./offline-packs";
import type { OfflineScopeV2 as OfflineScope } from "./offline-packs-v2";

export interface OfflinePackUpdateRequest { mode: "history"; base_pack_id: string; expected_base_sha256: string; scope: LegacyOfflineScope }
export interface OfflinePackUpdate {
  schema: "offline-pack-update@1"; state: "no_change" | "planned"; mode: "history";
  base_pack_id: string; base_semantic_digest: string; current_semantic_digest: string;
  base_pack: OfflinePackDescriptor; plan: OfflinePlan | null; source_refresh_performed: false;
}
export interface DeviceSyncConditions { network: "any" | "wifi"; power: "any" | "external_power" | "battery_charging" }
export interface DeviceSyncCapabilities {
  schema: "device-sync-capabilities@1"; scheduler: "page_open" | "native_app_open" | "os_background" | "unsupported";
  wifi: boolean; external_power: boolean; battery_charging: boolean; min_interval_seconds: number; max_interval_seconds: number;
  host_build: string; validator_version: "offline-validator@2";
}
export interface DeviceSyncPreviewRequest extends OfflineSlotRequest {
  expected_profile_id: string; expected_owner_epoch: number; interval_seconds: number; conditions: DeviceSyncConditions;
}
export interface DeviceSyncPreview {
  schema: "device-sync-preview@1"; preview_id: string; fingerprint: string; expires_at: string; expected_policy_revision: number;
  profile_id: string; owner_epoch: number; owner_scope_id: string; slot_id: string; generation: number; package_sha256: string;
  scope: OfflineScope; capacity: OfflineCapacity; interval_seconds: number; conditions: DeviceSyncConditions;
  capabilities: DeviceSyncCapabilities; counts: OfflineCounts; notice: string;
}
export interface DeviceSyncApplyRequest {
  preview_id: string; expected_fingerprint: string; expected_policy_revision: number; allow_continuous_history_updates: true;
}
export interface DeviceSyncPolicy {
  schema: "device-sync-policy@1"; policy_id: string; policy_revision: number; state: "enabled" | "paused" | "revoked";
  profile_id: string; owner_epoch: number; owner_scope_id: string; slot_id: string; scope: OfflineScope; capacity: OfflineCapacity;
  interval_seconds: number; conditions: DeviceSyncConditions; approved_at: string; updated_at: string;
  binding: { binding_revision: number; generation: number; package_id: string; sha256: string };
  next_due_at: string | null; reason: string | null;
}
export interface DeviceSyncPolicyRequest { policy_id: string; expected_policy_revision: number }
export type DeviceSyncTrigger = "manual" | "timer" | "resume" | "online" | "os_job";
export interface DeviceSyncRunRequest extends DeviceSyncPolicyRequest { trigger: DeviceSyncTrigger }
export interface DeviceSyncRun {
  schema: "device-sync-run@1"; run_id: string; policy_id: string; policy_revision: number; trigger: DeviceSyncTrigger;
  state: "running" | "succeeded" | "no_change" | "deferred" | "blocked" | "failed" | "cancelled" | "interrupted";
  stage: "checking" | "preparing" | "confirming" | "downloading" | "committing" | "finished";
  reason: string | null; started_at: string; finished_at: string | null; before_generation: number; after_generation: number | null;
  plan_id: string | null; package_id: string | null;
}
export interface DeviceSyncReleaseCheck {
  slot_id: string; generation: number; sha256: string | null; host_build: string; validator_version: "offline-validator@2";
  checked_at: string; state: "passed" | "failed"; reason: string | null;
}
export interface DeviceSyncStatus {
  schema: "device-sync-status@1"; capabilities: DeviceSyncCapabilities; profile_id: string; owner_epoch: number;
  policies: DeviceSyncPolicy[]; runs: DeviceSyncRun[]; release_checks: DeviceSyncReleaseCheck[];
}
