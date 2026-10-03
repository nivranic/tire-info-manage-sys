import type { NextConfig } from "next";
import { offlineHostBuild } from "../../scripts/offline-host-build.mjs";
import { resolve } from "node:path";

const distDir = process.env.TI_NEXT_DIST_DIR || ".next";
if (!/^[.a-zA-Z0-9_-]+$/.test(distDir) || distDir === "." || distDir === "..") {
  throw new Error("TI_NEXT_DIST_DIR must name a build directory inside apps/web.");
}
const nextConfig: NextConfig = {
  env: { NEXT_PUBLIC_TI_OFFLINE_HOST_BUILD: offlineHostBuild(resolve(process.cwd(), process.cwd().endsWith("web") ? "../.." : "."), "web") },
  distDir,
  transpilePackages: ["@tire/domain-types", "@tire/api-client"],
  poweredByHeader: false,
  // Keep development controls clear of the mobile bottom navigation.
  devIndicators: false,
  // The provider is bounded to 60 s; preserve its validated response through the local proxy.
  experimental: { proxyTimeout: 75000 },
  async headers() {
    return [{ source: "/sw.js", headers: [
      { key: "Content-Type", value: "application/javascript; charset=utf-8" },
      { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
      { key: "Service-Worker-Allowed", value: "/" },
      { key: "Content-Security-Policy", value: "default-src 'none'; script-src 'self'; connect-src 'self'" },
    ] }];
  },
  async rewrites() {
    const apiBase = (process.env.TI_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
    return [{ source: "/api/:path*", destination: `${apiBase}/:path*` }];
  },
};

export default nextConfig;
