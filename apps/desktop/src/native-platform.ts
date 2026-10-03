import { createNativeOfflineStorage, createNativeSave, type NativeInvoke } from "@tire/native-client";
import type { WorkbenchPlatform } from "../../web/components/workbench-platform";

export { bytesToBase64, createNativeTransport, externalLink, openNativeExternal, NativeError as DesktopError } from "@tire/native-client";
export type { NativeInvoke } from "@tire/native-client";

export interface DesktopStatus {
  api_base_url: string;
  session_persistent: boolean;
  session_store: "os_secure_store";
  version: string;
  error?: string;
}

export function createNativePlatform(invoke: NativeInvoke): WorkbenchPlatform {
  return { kind: "desktop", sessionLabel: "本机桌面安全会话", saveDownload: createNativeSave(invoke), offline: createNativeOfflineStorage(invoke) };
}
