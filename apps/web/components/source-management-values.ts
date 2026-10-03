import type { SourceSettingIntent, SourceSettingPreview, SourceSettingRevisionRequest, SourceSettingRevisionResult, SourceSettingSnapshot, SourceSettingView } from "@tire/domain-types";

export type SourceSettingAttempt = { sourceId: string; key: string; payload: SourceSettingRevisionRequest; before: SourceSettingSnapshot; after: SourceSettingSnapshot };
export const sourceStateLabels = { enabled: "本机已启用", paused: "本机已暂停", archived: "本机已归档" };
export const sourceCapabilityLabels: Record<string, string> = { ready: "已接入", available: "已接入", enabled: "已接入", configuration_required: "待配置", not_implemented: "待接入", disabled: "底层已停用", planned: "待接入", paused: "已暂停", archived: "已归档" };
export const sourceBlockerText = (code: string) => ({ source_paused: "来源已在本机暂停", source_archived: "来源已在本机归档", source_access_changed: "来源状态已变化，请重新提交在线请求", source_access_pin_missing: "原请求缺少当前来源授权，请重新提交", disabled: "环境配置已停用此来源", source_disabled: "环境配置已停用此来源", configuration_required: "必要配置尚未完成", not_implemented: "来源尚未接入", source_environment_disabled: "环境配置已停用此来源", parser_deployment_paused: "当前 Parser 部署已暂停", source_setting_not_archived: "此来源尚未归档，无需恢复", source_setting_restore_required: "请先将归档来源恢复为暂停", source_setting_no_changes: "当前内容没有变化", source_setting_revision_conflict: "来源已被其他操作更新，请重新读取", source_setting_preview_stale: "预览已过期，请重新读取并预览" } as Record<string, string>)[code] || code;
export const canFetchSource = (source: SourceSettingView | undefined, fresh: boolean) => fresh && source?.management.state === "enabled" && source.can_fetch === true;
export const hasSourceManagementAccess = (source: SourceSettingView | undefined, fresh: boolean) => fresh && source?.management.state === "enabled";
export const canQuerySource = (source: SourceSettingView | undefined, fresh: boolean) => hasSourceManagementAccess(source, fresh) && !!source && !source.environment_disabled && ["ready", "available", "enabled"].includes(source.registered_status);
export const sourceAccessChanged = (before: SourceSettingView | undefined, after: SourceSettingView | undefined) => before?.management.access_generation !== after?.management.access_generation;
const sameSnapshot = (a: SourceSettingSnapshot, b: SourceSettingSnapshot) => a.state === b.state && a.notes === b.notes && a.access_generation === b.access_generation;
export const matchesSourceSettingPreview = (preview: SourceSettingPreview, source: SourceSettingView, intent: SourceSettingIntent) => preview.source_id === source.source_id && preview.action === intent.action && preview.revision === source.management.revision && preview.source.fingerprint === source.fingerprint && (intent.action !== "edit_notes" || preview.after.notes === intent.notes);
export function matchesSourceSettingAttempt(result: SourceSettingRevisionResult, attempt: SourceSettingAttempt): boolean {
  const event = result?.event;
  return !!event && event.source_id === attempt.sourceId && event.idempotency_key === attempt.key && event.action === attempt.payload.action
    && event.revision === attempt.payload.expected_revision + 1 && event.operator === attempt.payload.operator && event.reason === attempt.payload.reason
    && !!event.before && !!event.after && sameSnapshot(event.before, attempt.before) && sameSnapshot(event.after, attempt.after) && sameSnapshot(event, event.after)
    && result.source?.source_id === attempt.sourceId && result.source.management.revision >= event.revision;
}
