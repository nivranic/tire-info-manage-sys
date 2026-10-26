"use client";

import { createContext, useContext } from "react";
import type { OfflineStorage } from "@tire/domain-types";
import { browserOfflineStorage } from "./browser-offline-store";
import { deliverBrowserRawDownload } from "./raw-evidence-v2-context";

export interface SaveDownload {
  blob: Blob;
  filename: string;
  signal?: AbortSignal;
  assertCurrent?: () => void;
}

export interface WorkbenchPlatform {
  kind: "web" | "desktop" | "mobile";
  sessionLabel: string;
  saveDownload: (download: SaveDownload) => Promise<{ saved: boolean }>;
  offline?: OfflineStorage;
  registerBackHandler?: (handler: () => boolean) => () => void;
  onThemeChange?: (theme: "light" | "dark") => void;
}

export const browserPlatform: WorkbenchPlatform = {
  kind: "web",
  sessionLabel: "本浏览器会话",
  offline: browserOfflineStorage,
  async saveDownload(download) {
    return deliverBrowserRawDownload(download, {
      createObjectURL: blob => URL.createObjectURL(blob), revokeObjectURL: url => URL.revokeObjectURL(url),
      createLink: () => document.createElement("a"), appendLink: link => document.body.appendChild(link as HTMLAnchorElement),
      deferRevoke: callback => { window.setTimeout(callback, 60000); },
    });
  },
};

export const WorkbenchPlatformContext = createContext<WorkbenchPlatform>(browserPlatform);
export const useWorkbenchPlatform = () => useContext(WorkbenchPlatformContext);
