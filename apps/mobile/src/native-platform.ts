import { createNativeOfflineStorage, createNativeSave, NativeError, type NativeInvoke, type NativeResponse } from "@tire/native-client";
import type { OfflineHostStatus, OfflineHostList, OfflineInstallRequest, OfflineSlot, OfflineSearchRequest, OfflineSearchResult,
  OfflineReadRequest, OfflineReadResult, OfflineSlotRequest, OfflineRemoveResult, OfflineUnlockRequest } from "@tire/domain-types";
import type { WorkbenchPlatform } from "../../web/components/workbench-platform";
import type { LocalFallbackDecideRequest, LocalFallbackGrant, LocalFallbackConsumeRequest, LocalFallbackResult,
  LocalFallbackRevokeRequest, LocalFallbackRevokeResult } from "@tire/domain-types";
import type { DeviceSyncStatus, DeviceSyncPreviewRequest, DeviceSyncPreview, DeviceSyncApplyRequest, DeviceSyncPolicy,
  DeviceSyncPolicyRequest, DeviceSyncRunRequest, DeviceSyncRun } from "@tire/domain-types";
import type { DeviceFallbackStatus, DeviceFallbackSourceAuthority, DeviceFallbackPolicyPreviewRequest, DeviceFallbackPolicyPreview,
  DeviceFallbackPolicyApplyRequest, DeviceFallbackPolicyRequest, DeviceFallbackPolicy, DeviceFallbackNativeWire, DeviceFallbackAuthorizeRequest,
  DeviceFallbackAuthorizeResult, DeviceFallbackDecideRequestV2, DeviceFallbackGrantV2, DeviceFallbackConsumeRequestV2, DeviceFallbackResultV2 } from "@tire/domain-types";

export interface MobileStatus {
  api_base_url: string;
  session_persistent: boolean;
  session_store: "android_keystore";
  version: string;
  platform: "android";
  mode: "debug-local" | "release-unconfigured";
  error?: string;
}

export interface TireNativePlugin {
  offlineFallbackStatus(): Promise<DeviceFallbackStatus>;
  offlineFallbackAuthorityRefresh(): Promise<DeviceFallbackSourceAuthority>;
  offlineFallbackPolicyPreview(options: { request: DeviceFallbackPolicyPreviewRequest }): Promise<DeviceFallbackPolicyPreview>;
  offlineFallbackPolicyApply(options: { request: DeviceFallbackPolicyApplyRequest }): Promise<DeviceFallbackPolicy>;
  offlineFallbackPolicyPause(options: { request: DeviceFallbackPolicyRequest }): Promise<DeviceFallbackPolicy>;
  offlineFallbackPolicyRevoke(options: { request: DeviceFallbackPolicyRequest }): Promise<DeviceFallbackPolicy>;
  offlineFallbackAuthorize(options: { request: DeviceFallbackNativeWire<DeviceFallbackAuthorizeRequest> }): Promise<DeviceFallbackAuthorizeResult | DeviceFallbackNativeWire<DeviceFallbackAuthorizeResult>>;
  offlineSyncStatus(): Promise<DeviceSyncStatus>;
  offlineSyncPreview(options: { request: DeviceSyncPreviewRequest }): Promise<DeviceSyncPreview>;
  offlineSyncApply(options: { request: DeviceSyncApplyRequest }): Promise<DeviceSyncPolicy>;
  offlineSyncPause(options: { request: DeviceSyncPolicyRequest }): Promise<DeviceSyncPolicy>;
  offlineSyncRevoke(options: { request: DeviceSyncPolicyRequest }): Promise<DeviceSyncPolicy>;
  offlineSyncRun(options: { request: DeviceSyncRunRequest }): Promise<DeviceSyncRun>;
  offlineSyncRevalidate(): Promise<DeviceSyncStatus>;
  offlineStatus(): Promise<OfflineHostStatus>;
  offlineList(): Promise<OfflineHostList>;
  offlineInstall(options: { request: OfflineInstallRequest }): Promise<OfflineSlot>;
  offlineSearch(options: { request: OfflineSearchRequest }): Promise<OfflineSearchResult>;
  offlineRead(options: { request: OfflineReadRequest }): Promise<OfflineReadResult>;
  offlineRemove(options: { request: OfflineSlotRequest }): Promise<OfflineRemoveResult>;
  offlineUnlockPreviousOwner(options: { request: OfflineUnlockRequest }): Promise<OfflineSlot>;
  offlineFallbackDecide(options: { request: LocalFallbackDecideRequest | DeviceFallbackNativeWire<DeviceFallbackDecideRequestV2> }): Promise<LocalFallbackGrant | DeviceFallbackNativeWire<DeviceFallbackGrantV2>>;
  offlineFallbackConsume(options: { request: LocalFallbackConsumeRequest | DeviceFallbackNativeWire<DeviceFallbackConsumeRequestV2> }): Promise<LocalFallbackResult | DeviceFallbackNativeWire<DeviceFallbackResultV2>>;
  offlineFallbackRevoke(options: { request: LocalFallbackRevokeRequest }): Promise<LocalFallbackRevokeResult>;
  status(options: Record<string, never>): Promise<MobileStatus>;
  // device-ai host bridge (round 50): the Java command entries. The wire
  // is not frozen (roundtable D15); the request/response payloads are the raw
  // four-domain closed-DTO JSON the Java layer validates again.
  deviceAiPrepare(options: { request: Record<string, unknown> }): Promise<Record<string, unknown>>;
  deviceAiSubmitStream(options: { request: Record<string, unknown> }): Promise<Record<string, unknown>>;
  deviceAiLookup(options: { request: Record<string, unknown> }): Promise<Record<string, unknown>>;
  deviceAiJournalRead(options: { request: Record<string, unknown> }): Promise<Record<string, unknown>>;
  deviceAiJournalAppend(options: { request: Record<string, unknown> }): Promise<Record<string, unknown>>;
  deviceAiResolveUnknown(options: { request: Record<string, unknown> }): Promise<Record<string, unknown>>;
  apiRequest(options: { request: { id: string; path: string; method: string; headers: Record<string, string>; body_base64?: string } }): Promise<NativeResponse>;
  apiCancel(options: { id: string }): Promise<void>;
  resetSession(options: Record<string, never>): Promise<void>;
  saveDownload(options: { filename: string; mime: string; body_base64: string }): Promise<{ saved: boolean }>;
  openExternal(options: { url: string }): Promise<void>;
  resolveBack(options: { id: string; handled: boolean }): Promise<void>;
  setSystemTheme(options: { theme: "light" | "dark" }): Promise<void>;
  addListener(event: "backRequested", listener: (event: { id: string }) => void): Promise<{ remove: () => Promise<void> }>;
  addListener(event: "resume", listener: () => void): Promise<{ remove: () => Promise<void> }>;
}

export function mobileError(cause: unknown): NativeError {
  if (cause instanceof NativeError) return cause;
  if (typeof cause === "string") return new NativeError(cause);
  if (cause && typeof cause === "object") {
    const failure = cause as { code?: unknown; message?: unknown };
    // Capacitor rejects Error objects; only the shared fixed-code map supplies UI text.
    if (typeof failure.code === "string") {
      const byCode = new NativeError(failure.code);
      if (byCode.code !== "request_failed") return byCode;
    }
    if (typeof failure.message === "string") return new NativeError(failure.message);
  }
  return new NativeError("request_failed");
}

/** Adapter only: encoding, cancellation, headers, errors and binary handling live in the shared package. */
export function createMobileInvoke(plugin: TireNativePlugin): NativeInvoke {
  return async <T>(command: string, args: Record<string, unknown> = {}): Promise<T> => {
    try {
      switch (command) {
        case "offline_fallback_status": return await plugin.offlineFallbackStatus() as T;
        case "offline_fallback_authority_refresh": return await plugin.offlineFallbackAuthorityRefresh() as T;
        case "offline_fallback_policy_preview": return await plugin.offlineFallbackPolicyPreview(args as Parameters<TireNativePlugin["offlineFallbackPolicyPreview"]>[0]) as T;
        case "offline_fallback_policy_apply": return await plugin.offlineFallbackPolicyApply(args as Parameters<TireNativePlugin["offlineFallbackPolicyApply"]>[0]) as T;
        case "offline_fallback_policy_pause": return await plugin.offlineFallbackPolicyPause(args as Parameters<TireNativePlugin["offlineFallbackPolicyPause"]>[0]) as T;
        case "offline_fallback_policy_revoke": return await plugin.offlineFallbackPolicyRevoke(args as Parameters<TireNativePlugin["offlineFallbackPolicyRevoke"]>[0]) as T;
        case "offline_fallback_authorize": return await plugin.offlineFallbackAuthorize(args as Parameters<TireNativePlugin["offlineFallbackAuthorize"]>[0]) as T;
        case "offline_sync_status": return await plugin.offlineSyncStatus() as T;
        case "offline_sync_preview": return await plugin.offlineSyncPreview(args as Parameters<TireNativePlugin["offlineSyncPreview"]>[0]) as T;
        case "offline_sync_apply": return await plugin.offlineSyncApply(args as Parameters<TireNativePlugin["offlineSyncApply"]>[0]) as T;
        case "offline_sync_pause": return await plugin.offlineSyncPause(args as Parameters<TireNativePlugin["offlineSyncPause"]>[0]) as T;
        case "offline_sync_revoke": return await plugin.offlineSyncRevoke(args as Parameters<TireNativePlugin["offlineSyncRevoke"]>[0]) as T;
        case "offline_sync_run": return await plugin.offlineSyncRun(args as Parameters<TireNativePlugin["offlineSyncRun"]>[0]) as T;
        case "offline_sync_revalidate": return await plugin.offlineSyncRevalidate() as T;
        case "offline_status": return await plugin.offlineStatus() as T;
        case "offline_list": return await plugin.offlineList() as T;
        case "offline_install": return await plugin.offlineInstall(args as Parameters<TireNativePlugin["offlineInstall"]>[0]) as T;
        case "offline_search": return await plugin.offlineSearch(args as Parameters<TireNativePlugin["offlineSearch"]>[0]) as T;
        case "offline_read": return await plugin.offlineRead(args as Parameters<TireNativePlugin["offlineRead"]>[0]) as T;
        case "offline_remove": return await plugin.offlineRemove(args as Parameters<TireNativePlugin["offlineRemove"]>[0]) as T;
        case "offline_unlock_previous_owner": return await plugin.offlineUnlockPreviousOwner(args as Parameters<TireNativePlugin["offlineUnlockPreviousOwner"]>[0]) as T;
        case "offline_fallback_decide": return await plugin.offlineFallbackDecide(args as Parameters<TireNativePlugin["offlineFallbackDecide"]>[0]) as T;
        case "offline_fallback_consume": return await plugin.offlineFallbackConsume(args as Parameters<TireNativePlugin["offlineFallbackConsume"]>[0]) as T;
        case "offline_fallback_revoke": return await plugin.offlineFallbackRevoke(args as Parameters<TireNativePlugin["offlineFallbackRevoke"]>[0]) as T;
        case "api_request": return await plugin.apiRequest(args as Parameters<TireNativePlugin["apiRequest"]>[0]) as T;
        case "api_cancel": return await plugin.apiCancel(args as Parameters<TireNativePlugin["apiCancel"]>[0]) as T;
        case "save_download": return await plugin.saveDownload(args as Parameters<TireNativePlugin["saveDownload"]>[0]) as T;
        case "open_external": return await plugin.openExternal(args as Parameters<TireNativePlugin["openExternal"]>[0]) as T;
        case "device_ai_prepare": return await plugin.deviceAiPrepare(args as Parameters<TireNativePlugin["deviceAiPrepare"]>[0]) as T;
        case "device_ai_submit_stream": return await plugin.deviceAiSubmitStream(args as Parameters<TireNativePlugin["deviceAiSubmitStream"]>[0]) as T;
        case "device_ai_lookup": return await plugin.deviceAiLookup(args as Parameters<TireNativePlugin["deviceAiLookup"]>[0]) as T;
        case "device_ai_journal_read": return await plugin.deviceAiJournalRead(args as Parameters<TireNativePlugin["deviceAiJournalRead"]>[0]) as T;
        case "device_ai_journal_append": return await plugin.deviceAiJournalAppend(args as Parameters<TireNativePlugin["deviceAiJournalAppend"]>[0]) as T;
        case "device_ai_resolve_unknown": return await plugin.deviceAiResolveUnknown(args as Parameters<TireNativePlugin["deviceAiResolveUnknown"]>[0]) as T;
        default: throw new NativeError("NATIVE_COMMAND_UNAVAILABLE");
      }
    } catch (cause) { if (command.startsWith("offline_") || command.startsWith("device_ai_")) throw cause; throw mobileError(cause); }
  };
}

export function createMobilePlatform(invoke: NativeInvoke): WorkbenchPlatform {
  return { kind: "mobile", sessionLabel: "本机 Android 安全会话", saveDownload: createNativeSave(invoke), offline: createNativeOfflineStorage(invoke) };
}

export function validateMobileStatus(status: MobileStatus): void {
  if (!status || status.platform !== "android" || status.session_store !== "android_keystore") throw new NativeError("INVALID_NATIVE_STATUS");
  if (status.mode === "release-unconfigured") throw new NativeError("RELEASE_API_NOT_CONFIGURED");
  if (status.error) throw new NativeError(status.error);
  if (status.mode !== "debug-local" || !status.session_persistent) throw new NativeError("SESSION_STORE_UNAVAILABLE");
  try {
    const url = new URL(status.api_base_url);
    if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || url.username || url.password || url.pathname !== "/" || url.search || url.hash) throw new Error();
  } catch { throw new NativeError("INVALID_NATIVE_STATUS"); }
}
