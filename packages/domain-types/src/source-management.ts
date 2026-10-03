export type SourceSettingState = "enabled" | "paused" | "archived";
export type SourceSettingAction = "enable" | "pause" | "archive" | "restore" | "edit_notes";
export interface SourceSettingSnapshot { state: SourceSettingState; notes: string; access_generation: number }
export interface SourceSettingView {
  scope: "local_workspace"; source_id: string; name: string; region: string;
  target_kind: "tire" | "recall" | "vehicle"; source_class: string; homepage: string; description: string;
  supported_models: string[]; registered_status: string; environment_disabled: boolean;
  management: SourceSettingSnapshot & { revision: number; event_id: string | null; operator: string | null; reason: string | null; changed_at: string | null };
  effective_status: string; can_fetch: boolean; blockers: string[]; fingerprint: string; notice: string;
  parser_deployment?: { revision: number; state: string; bundle_id: string; parser_digest: string } | null;
}
export interface SourceSettingCatalog { scope: "local_workspace"; items: SourceSettingView[]; total: number; notice: string }
export interface SourceSettingIntent { action: SourceSettingAction; notes?: string | null }
export interface SourceSettingPreview {
  scope: "local_workspace"; source_id: string; action: SourceSettingAction; revision: number; fingerprint: string;
  before: SourceSettingSnapshot; after: SourceSettingSnapshot; can_submit: boolean; blockers: string[];
  source: SourceSettingView; effective_after: { effective_status: string; can_fetch: boolean; blockers: string[] }; notice: string;
}
export interface SourceSettingRevisionRequest extends SourceSettingIntent {
  expected_revision: number; expected_fingerprint: string; operator: string; reason: string;
}
export interface SourceSettingEvent extends SourceSettingSnapshot {
  id: string; source_id: string; revision: number; action: SourceSettingAction; idempotency_key: string;
  before: SourceSettingSnapshot; after: SourceSettingSnapshot; operator: string; reason: string; created_at: string; fingerprint: string;
}
export interface SourceSettingHistory { scope: "local_workspace"; source_id: string; items: SourceSettingEvent[]; offset: number; limit: number; total: number }
export interface SourceSettingRevisionResult { source: SourceSettingView; event: SourceSettingEvent; replayed: boolean }
