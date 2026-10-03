import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { offlineHostBuild } from "./offline-host-build.mjs";
const root = resolve(import.meta.dirname, ".."), output = resolve(process.argv[2] || "");
if (dirname(output) !== resolve(root, ".artifacts/query-fallback49") || !/^frontend-final-build-[a-z0-9-]+$/.test(relative(dirname(output), output)) || existsSync(output)) throw new Error("Fresh isolated frontend build output required.");
mkdirSync(output, { recursive: true });
const sha = bytes => createHash("sha256").update(bytes).digest("hex"), source = readFileSync(resolve(root, "scripts/offline-host-build.mjs"), "utf8");
const names = new Set([...source.matchAll(/"((?:apps|packages|scripts)\/[^"\r\n]+)"/g)].map(match => match[1]));
for (const platform of ["web", "desktop", "mobile"]) { names.add(`apps/${platform}/package.json`); names.add(`apps/${platform}/${platform === "web" ? "next.config.ts" : "vite.config.ts"}`); names.add(`apps/${platform}/tsconfig.json`); }
for (const name of ["tsconfig.json", "apps/desktop/src/main.tsx", "apps/mobile/src/main.tsx", "apps/web/app/globals.css"]) if (existsSync(resolve(root, name))) names.add(name);
const sources = Object.fromEntries([...names].sort().map(name => [name, sha(readFileSync(resolve(root, name)))]));
const report = { schema: "query-fallback49-frontend-build@1", state: "running", scope: "Web typecheck; fresh desktop/mobile Vite production frontend only; no native host acceptance", source_sha256: sources,
  host_build: Object.fromEntries(["web", "desktop", "mobile"].map(platform => [platform, offlineHostBuild(root, platform)])), checks: [], source_drift: [] };
const save = () => writeFileSync(resolve(output, "verification.json"), JSON.stringify(report, null, 2) + "\n"); save();
function run(name, args, cwd = root) {
  const result = spawnSync(process.execPath, args, { cwd, encoding: "utf8", windowsHide: true });
  writeFileSync(resolve(output, name + ".log"), (result.stdout || "") + (result.stderr || "") + (result.error?.stack || ""));
  report.checks.push({ name, exit_code: result.status }); save();
  console.log(JSON.stringify({ name, exit_code: result.status }));
  if (result.status !== 0) throw new Error(name + " failed");
}
function manifest(directory) {
  const files = [], walk = folder => { for (const entry of readdirSync(folder, { withFileTypes: true })) { const path = resolve(folder, entry.name); if (entry.isDirectory()) walk(path); else if (entry.isFile()) files.push(path); } }; walk(directory);
  const entries = files.sort().map(path => ({ path: relative(directory, path).replaceAll("\\", "/"), byte_count: readFileSync(path).length, sha256: sha(readFileSync(path)) }));
  return { files: entries, sha256: sha(Buffer.from(JSON.stringify(entries))) };
}
try {
  for (const platform of ["web", "desktop", "mobile"]) run(platform + "-typecheck", [resolve(root, "node_modules/typescript/bin/tsc"), "--noEmit", "--incremental", "false", "-p", resolve(root, `apps/${platform}/tsconfig.json`)]);
  for (const platform of ["desktop", "mobile"]) {
    const dist = resolve(output, platform + "-dist");
    run(platform + "-vite-build", [resolve(root, "node_modules/vite/bin/vite.js"), "build", "--outDir", dist], resolve(root, `apps/${platform}`));
    const result = manifest(dist); report[platform + "_dist"] = { absolute_path: dist, ...result };
    const js = result.files.filter(file => file.path.endsWith(".js")).map(file => readFileSync(resolve(dist, file.path), "utf8")).join("\n");
    report[platform + "_dist"].embedded_host_build_verified = js.includes(report.host_build[platform]); save();
    if (!report[platform + "_dist"].embedded_host_build_verified) throw new Error(platform + " host fingerprint missing");
  }
  report.source_drift = Object.entries(sources).filter(([name, expected]) => sha(readFileSync(resolve(root, name))) !== expected).map(([name]) => name);
  if (report.source_drift.length) throw new Error("Frontend source changed during verification.");
  report.state = "passed"; save(); console.log(JSON.stringify({ report: resolve(output, "verification.json"), state: report.state, host_build: report.host_build }));
} catch (error) { report.state = "failed"; report.error = String(error); save(); throw error; }
