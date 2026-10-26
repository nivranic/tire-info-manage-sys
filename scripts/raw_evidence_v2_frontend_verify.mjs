/** R96 exact frontend checks/builds. Run only after independent source/argv review. */
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync, unlinkSync, rmdirSync, lstatSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { offlineHostBuild } from "./offline-host-build.mjs";

const root = resolve(import.meta.dirname, ".."), node = "C:/Program Files/nodejs/node.exe";
const output = resolve(process.argv[2] || ""), api = process.argv[3], mode = process.argv[4];
if (process.argv.length !== 5 || dirname(output) !== resolve(root, ".artifacts") || !/^r96-frontend-[a-f0-9]{32}$/.test(relative(dirname(output), output)) || existsSync(output)) throw Error("Fresh r96-frontend-GUID output required");
if (api !== "http://127.0.0.1:18966" || !["checks", "build"].includes(mode)) throw Error("Exact private API and checks/build mode required");
if (resolve(process.execPath).toLowerCase() !== resolve(node).toLowerCase()) throw Error("Reviewed Node executable required");
mkdirSync(output);
const hash = bytes => createHash("sha256").update(bytes).digest("hex");
function files(directory) {
  if (!existsSync(directory)) return [];
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = resolve(directory, entry.name);
    if (entry.isSymbolicLink()) throw Error("Symlink in source/output tree: " + path);
    return entry.isDirectory() ? files(path) : entry.isFile() ? [path] : [];
  });
}
const sourceRoots = ["apps/web/app", "apps/web/components", "apps/web/tests", "apps/web/pwa", "apps/desktop/src", "apps/desktop/tests", "apps/mobile/src", "apps/mobile/tests", "packages/api-client/src", "packages/api-client/tests", "packages/domain-types/src", "packages/native-client/src", "packages/native-client/tests"];
const sourceNames = ["package.json", "package-lock.json", "tsconfig.json", "scripts/build-pwa.mjs", "scripts/offline-host-build.mjs", "scripts/raw_evidence_v2_frontend_verify.mjs", "packages/native-client/tsconfig.json", ...["web", "desktop", "mobile"].flatMap(p => [`apps/${p}/package.json`, `apps/${p}/tsconfig.json`, `apps/${p}/${p === "web" ? "next.config.ts" : "vite.config.ts"}`])];
function sources() {
  const names = [...new Set([...sourceNames.map(p => resolve(root, p)), ...sourceRoots.flatMap(p => files(resolve(root, p)))])].sort();
  return Object.fromEntries(names.map(p => [relative(root, p).replaceAll("\\", "/"), existsSync(p) ? { bytes: readFileSync(p).length, sha256: hash(readFileSync(p)) } : null]));
}
function manifest(directory) {
  const entries = files(directory).sort().map(p => ({ path: relative(directory, p).replaceAll("\\", "/"), bytes: readFileSync(p).length, sha256: hash(readFileSync(p)) }));
  return { absolute_path: directory, entries, sha256: hash(Buffer.from(JSON.stringify(entries))) };
}
const cleanEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(TI_|TIRE_|OPENAI_|ANTHROPIC_|AZURE_OPENAI_|OTEL_|SENTRY_|NODE_OPTIONS$|NEXT_PUBLIC_)/i.test(key) && !/^(DATABASE_URL|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY)$/i.test(key)));
const temporary = resolve(output, "tmp"); mkdirSync(temporary);
const webDistName = ".next-r96-" + relative(dirname(output), output).slice("r96-frontend-".length);
const webDist = resolve(root, "apps/web", webDistName);
if (existsSync(webDist)) throw Error("Fresh Next directory required");
const env = { ...cleanEnv, TI_API_BASE_URL: api, TI_NEXT_DIST_DIR: webDistName, NEXT_TELEMETRY_DISABLED: "1", CI: "1", TEMP: temporary, TMP: temporary, TMPDIR: temporary };
const report = { schema: "r96-frontend@1", mode, state: "running", source_before: sources(), source_after: null, source_stable: null, checks: [], artifacts: {}, generated_restore: null, api_base: api, web_origin: "http://127.0.0.1:18967", web_dist_name: webDistName, host_build: Object.fromEntries(["web", "desktop", "mobile"].map(p => [p, offlineHostBuild(root, p)])), scope: "Current-source Node/TypeScript/frontend production builds only; no Native host or device acceptance." };
const save = () => writeFileSync(resolve(output, "verification.json"), JSON.stringify(report, null, 2) + "\n"); save();
function run(name, args, cwd = root) {
  if (JSON.stringify(sources()) !== JSON.stringify(report.source_before)) throw Error("Source changed before " + name);
  const started = new Date().toISOString();
  const result = spawnSync(node, args, { cwd, env, windowsHide: true, encoding: null, timeout: 1_200_000, maxBuffer: 128 * 1024 * 1024 });
  writeFileSync(resolve(output, name + ".stdout.log"), result.stdout || Buffer.alloc(0));
  writeFileSync(resolve(output, name + ".stderr.log"), result.stderr || Buffer.alloc(0));
  const record = { name, executable: node, executable_sha256: hash(readFileSync(node)), argv: args, cwd, started, ended: new Date().toISOString(), exit_code: result.status, signal: result.signal, spawn_error: result.error ? String(result.error) : null };
  report.checks.push(record); save(); console.log(JSON.stringify(record));
  if (result.status !== 0 || result.error) throw Error(name + " failed");
}
const generatedPaths = ["apps/web/public/favicon.ico", "apps/web/public/sw.js", "apps/web/next-env.d.ts"];
const icons = resolve(root, "apps/web/public/icons");
let backup = null;
function backupGenerated() {
  const iconFiles = files(icons), names = [...generatedPaths.map(p => resolve(root, p)), ...iconFiles];
  const saved = names.map(path => ({ path, exists: existsSync(path), bytes: existsSync(path) ? readFileSync(path) : null }));
  const backupRoot = resolve(output, "generated-before"); mkdirSync(backupRoot);
  for (const item of saved) if (item.exists) { const p = resolve(backupRoot, relative(root, item.path)); mkdirSync(dirname(p), { recursive: true }); writeFileSync(p, item.bytes); }
  backup = { saved, icons_existed: existsSync(icons), icon_dirs: existsSync(icons) ? [icons, ...directoryTree(icons)] : [], icon_files: new Set(iconFiles) };
  report.generated_before = saved.map(({ path, exists, bytes }) => ({ path: relative(root, path).replaceAll("\\", "/"), exists, bytes: bytes?.length ?? null, sha256: bytes ? hash(bytes) : null })); save();
}
function directoryTree(dir) { return readdirSync(dir, { withFileTypes: true }).filter(e => e.isDirectory()).flatMap(e => { const p = resolve(dir, e.name); return [p, ...directoryTree(p)]; }); }
function restoreGenerated() {
  if (!backup) return;
  const knownGenerated = new Set([192, 512, 180].map(n => resolve(icons, `icon-${n}.png`)));
  const unknown = files(icons).filter(p => !backup.icon_files.has(p) && !knownGenerated.has(p));
  for (const item of backup.saved) { if (item.exists) { mkdirSync(dirname(item.path), { recursive: true }); writeFileSync(item.path, item.bytes); } else if (existsSync(item.path)) { if (!lstatSync(item.path).isFile()) throw Error("Unsafe generated restore target"); unlinkSync(item.path); } }
  for (const p of knownGenerated) if (!backup.icon_files.has(p) && existsSync(p)) unlinkSync(p);
  if (!backup.icons_existed && existsSync(icons) && readdirSync(icons).length === 0) rmdirSync(icons);
  const mismatches = backup.saved.filter(item => existsSync(item.path) !== item.exists || (item.exists && !readFileSync(item.path).equals(item.bytes))).map(i => relative(root, i.path));
  report.generated_restore = { completed: true, exact_original_files: mismatches.length === 0, mismatches, unexpected_files_preserved: unknown.map(p => relative(root, p)) }; save();
  if (mismatches.length || unknown.length || existsSync(icons) !== backup.icons_existed) throw Error("Generated files did not restore exactly");
}
let failure = null;
try {
  if (mode === "checks") {
    for (const project of ["apps/web", "apps/desktop", "apps/mobile", "packages/native-client"]) run(project.replaceAll("/", "-") + "-typecheck", [resolve(root, "node_modules/typescript/bin/tsc"), "--noEmit", "--incremental", "false", "-p", resolve(root, project, "tsconfig.json")]);
    run("web-raw-helper", ["--experimental-strip-types", "--test", "apps/web/tests/raw-evidence-v2.test.ts"]);
    run("native-js-adapters", ["--test", "packages/native-client/tests/transport.test.mjs", "apps/desktop/tests/native-platform.test.mjs", "apps/mobile/tests/native-platform.test.mjs"]);
    run("transport-authority", ["--experimental-transform-types", "--import", "./packages/api-client/tests/device-ai/json-esm-hook.mjs", "--test", resolve(root, "packages/api-client/tests/transport-authority.mts")]);
  } else {
    backupGenerated();
    for (const platform of ["desktop", "mobile"]) {
      const dist = resolve(output, platform + "-dist");
      run(platform + "-vite", [resolve(root, "node_modules/vite/bin/vite.js"), "build", "--outDir", dist], resolve(root, "apps", platform));
      report.artifacts[platform] = manifest(dist);
      const js = report.artifacts[platform].entries.filter(p => p.path.endsWith(".js")).map(p => readFileSync(resolve(dist, p.path), "utf8")).join("\n");
      report.artifacts[platform].host_fingerprint_found = js.includes(report.host_build[platform]); save();
      if (!report.artifacts[platform].host_fingerprint_found) throw Error(platform + " fingerprint absent");
    }
    run("web-icons", [resolve(root, "scripts/build-pwa.mjs"), "--icons"], resolve(root, "apps/web"));
    run("web-next", [resolve(root, "node_modules/next/dist/bin/next"), "build"], resolve(root, "apps/web"));
    run("web-pwa", [resolve(root, "scripts/build-pwa.mjs")], resolve(root, "apps/web"));
    report.artifacts.web = manifest(webDist);
    const webJs = files(resolve(webDist, "static")).filter(p => p.endsWith(".js")).map(p => readFileSync(p, "utf8")).join("\n");
    report.artifacts.web.host_fingerprint_found = webJs.includes(report.host_build.web); save();
    if (!report.artifacts.web.host_fingerprint_found) throw Error("web fingerprint absent");
    report.generated_after_build = manifest(resolve(root, "apps/web/public")); save();
  }
} catch (error) { failure = error; report.error = String(error); }
finally {
  try { restoreGenerated(); } catch (error) { report.restore_error = String(error); failure ||= error; }
  report.source_after = sources(); report.source_stable = JSON.stringify(report.source_before) === JSON.stringify(report.source_after);
  if (!report.source_stable) { report.drift = [...new Set([...Object.keys(report.source_before), ...Object.keys(report.source_after)])].filter(p => JSON.stringify(report.source_before[p]) !== JSON.stringify(report.source_after[p])); failure ||= Error("Source drift"); }
  report.state = failure ? "failed" : "passed"; report.ended = new Date().toISOString(); save();
}
if (failure) { console.error(String(failure)); process.exitCode = 1; }
