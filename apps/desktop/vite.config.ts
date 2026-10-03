import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { offlineHostBuild } from "../../scripts/offline-host-build.mjs";
import { fileURLToPath } from "node:url";

export default defineConfig({
  define: { "process.env.NEXT_PUBLIC_TI_OFFLINE_HOST_BUILD": JSON.stringify(offlineHostBuild(fileURLToPath(new URL("../..", import.meta.url)), "desktop")) },
  plugins: [react()],
  clearScreen: false,
  server: { host: "127.0.0.1", port: 1420, strictPort: true },
  build: { target: "es2022" },
});
