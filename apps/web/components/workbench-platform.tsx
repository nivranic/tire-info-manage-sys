"use client";

import { createContext, useContext } from "react";
import type { OfflineStorage } from "@tire/domain-types";
import { browserOfflineStorage } from "./browser-offline-store";

export interface SaveDownload {
  blob: Blob;
  filename: string;
  signal?: AbortSignal;
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
  async saveDownload({ blob, filename, signal }) {
    if (signal?.aborted) throw new DOMException("操作已取消", "AbortError");
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    try { link.click(); }
    finally {
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    }
    return { saved: true };
  },
};

export const WorkbenchPlatformContext = createContext<WorkbenchPlatform>(browserPlatform);
export const useWorkbenchPlatform = () => useContext(WorkbenchPlatformContext);
