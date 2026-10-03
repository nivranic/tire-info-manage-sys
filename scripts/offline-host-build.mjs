import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

export function offlineHostBuild(root, platform = "web") {
  const files = ["apps/web/components/browser-offline-store.ts", "apps/web/components/browser-device-sync.ts", "apps/web/components/browser-device-fallback.ts",
    "apps/web/components/device-sync-values.ts", "apps/web/components/device-sync-lifecycle.tsx", "apps/web/components/device-sync-panel.tsx",
    "apps/web/components/offline-library.tsx", "apps/web/components/workbench-platform.tsx", "apps/web/components/workbench.tsx",
    "apps/web/components/query-fallback-policy.tsx", "apps/web/components/query-fallback-device.tsx", "apps/web/components/local-fallback-controller.ts", "apps/web/components/local-fallback-panel.tsx", "apps/web/components/vehicle-fitments.tsx", "apps/web/components/recalls.tsx", "apps/web/components/query-filters.tsx", "apps/web/components/reparse-review.tsx",
    "apps/web/components/offline-values.ts", "apps/web/components/offline-crypto.ts",
    "packages/domain-types/src/device-sync.ts", "packages/domain-types/src/offline-packs.ts", "packages/domain-types/src/device-fallback.ts", "packages/domain-types/src/offline-packs-v2.ts", "packages/domain-types/src/filters.ts", "packages/domain-types/src/warehouse-fallback.ts", "packages/domain-types/src/index.ts",
    "packages/domain-types/src/query-filter-unicode.json", "packages/api-client/src/index.ts", "packages/api-client/src/exact-json.ts", "packages/api-client/src/device-criteria.ts", "packages/api-client/src/device-fallback-values.ts",
    "packages/native-client/src/index.ts", "apps/desktop/src/native-platform.ts", "apps/mobile/src/native-platform.ts", "scripts/offline-host-build.mjs", `apps/${platform}/package.json`,
    platform === "web" ? "apps/web/next.config.ts" : `apps/${platform}/vite.config.ts`];
  const hash = createHash("sha256"); hash.update("tire-offline-host-build@1\0" + platform);
  for (const name of files.sort()) { hash.update("\0" + name + "\0"); hash.update(readFileSync(resolve(root, name))); }
  return hash.digest("hex");
}
