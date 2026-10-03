"use client";
import { useEffect } from "react";
import type { WorkbenchPlatform } from "./workbench-platform";
import type { DeviceSyncTrigger } from "@tire/domain-types";

/** Web has no persistent worker. Native hosts own their own scheduler. */
export default function DeviceSyncLifecycle({ platform }: { platform: WorkbenchPlatform }) {
  useEffect(() => {
    const storage = platform.offline;
    if (!storage?.revalidateSync) return;
    let stopped = false, checking = false;
    async function check(trigger: DeviceSyncTrigger) {
      if (stopped || checking || !storage?.syncStatus) return;
      checking = true;
      try {
        const status = await storage.syncStatus();
        if (stopped || platform.kind !== "web" || status.capabilities.scheduler !== "page_open" || !storage.runSyncPolicy) return;
        for (const policy of status.policies) {
          if (stopped) return;
          if (policy.state !== "enabled" || !policy.next_due_at || Date.parse(policy.next_due_at) > Date.now()) continue;
          await storage.runSyncPolicy({ policy_id: policy.policy_id, expected_policy_revision: policy.policy_revision, trigger }).catch(() => {});
        }
      } catch { /* The library exposes durable failure; timers never create consent. */ }
      finally { checking = false; }
    }
    void storage.revalidateSync().then(() => check("resume")).catch(() => {});
    if (platform.kind !== "web") return () => { stopped = true; };
    const resume = () => { if (document.visibilityState === "visible") void check("resume"); };
    const online = () => { void check("online"); };
    const changed = () => { void check("timer"); };
    const timer = window.setInterval(() => { void check("timer"); }, 30_000);
    document.addEventListener("visibilitychange", resume); window.addEventListener("online", online); window.addEventListener("tire-offline-sync-changed", changed);
    return () => { stopped = true; clearInterval(timer); document.removeEventListener("visibilitychange", resume); window.removeEventListener("online", online); window.removeEventListener("tire-offline-sync-changed", changed); };
  }, [platform]);
  return null;
}
