/** R98 exact checks/build candidate. No execution authorization is inherited. */
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync, unlinkSync, rmdirSync, lstatSync, realpathSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { offlineHostBuild } from "./offline-host-build.mjs";

const root = resolve(import.meta.dirname, "..");
const self = resolve(import.meta.filename), supervisor = resolve(root, "scripts/binary_quarantine_review_native_verify.py");
const node = "C:/Program Files/nodejs/node.exe", python = resolve(root, "apps/api/.venv/Scripts/python.exe");
const nextNodePhysical = "E:/DevTools/nvm/v22.22.1/node.exe";
const nextNodeInput = { bytes: 87059456, sha256: "923a41f268ab49ede2e3363fbdd9e790609e385c6f3ca880b4ee9a56a8133e5a" };
const [action, mode, rawOutput, reviewedSha] = process.argv.slice(2);
if (!["freeze", "run"].includes(action) || !["checks", "build"].includes(mode) || process.argv.length !== (action === "freeze" ? 5 : 6)) throw Error("Usage: node candidate.mjs freeze checks|build fresh-output OR run checks|build frozen-output reviewed-freeze-sha256");
const output = resolve(rawOutput), prefix = mode === "checks" ? "r98fc" : "r98fb";
if (dirname(output) !== resolve(root, ".artifacts") || !new RegExp(`^${prefix}-[a-f0-9]{16}$`).test(relative(dirname(output), output))) throw Error("Exact short private output required");
if (resolve(process.execPath).toLowerCase() !== resolve(node).toLowerCase()) throw Error("Reviewed Node executable required");
if (existsSync(output) && lstatSync(output).isSymbolicLink()) throw Error("Reparse/symlink output rejected");
const hash = bytes => createHash("sha256").update(bytes).digest("hex");
function input(path) {
  if (!existsSync(path) || !lstatSync(path).isFile() || lstatSync(path).isSymbolicLink()) throw Error("Missing/nonregular input: " + path);
  const bytes = readFileSync(path); return { bytes: bytes.length, sha256: hash(bytes) };
}
function files(directory) {
  if (!existsSync(directory) || !lstatSync(directory).isDirectory() || lstatSync(directory).isSymbolicLink()) throw Error("Missing/nonregular directory: " + directory);
  return readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name)).flatMap(entry => {
    const path = resolve(directory, entry.name);
    if (entry.isSymbolicLink()) throw Error("Reparse/symlink input: " + path);
    if (entry.isDirectory()) return files(path);
    if (!entry.isFile()) throw Error("Nonregular input: " + path);
    return [path];
  });
}
const sourceRoots = ["apps/web/app", "apps/web/components", "apps/web/tests", "apps/web/pwa", "apps/desktop/src", "apps/desktop/tests", "apps/mobile/src", "apps/mobile/tests", "packages/api-client/src", "packages/api-client/tests", "packages/domain-types/src", "packages/native-client/src", "packages/native-client/tests"];
const sourceNames = ["package.json", "package-lock.json", "tsconfig.json", "scripts/build-pwa.mjs", "scripts/offline-host-build.mjs", "scripts/binary_quarantine_review_frontend_verify.mjs", "scripts/binary_quarantine_review_native_verify.py", "packages/native-client/tsconfig.json", "apps/desktop/index.html", "apps/mobile/index.html", "apps/mobile/capacitor.config.ts",
  ...["api-client", "domain-types", "native-client"].map(p => `packages/${p}/package.json`),
  ...["web", "desktop", "mobile"].flatMap(p => [`apps/${p}/package.json`, `apps/${p}/tsconfig.json`, `apps/${p}/${p === "web" ? "next.config.ts" : "vite.config.ts"}`])];
function sources() { return Object.fromEntries([...new Set([...sourceNames.map(p => resolve(root, p)), ...sourceRoots.flatMap(p => files(resolve(root, p)))])].sort().map(p => [p, input(p)])); }
const consoleHelper = { executable: resolve("C:/Windows/System32/conhost.exe"), bytes: 1003520, sha256: "c86146188b78e484f32cc29e2331689659943b47689a85570342044f499938ac", raw_commandline: String.raw`\??\C:\WINDOWS\system32\conhost.exe 0xffffffff -ForceV1`, max_per_phase: 1 };
const frontendNextConsolePolicy = { schema: "r98-frontend-next-console-policy@1", executable: consoleHelper.executable, bytes: consoleHelper.bytes, sha256: consoleHelper.sha256, raw_commandlines: [consoleHelper.raw_commandline, String.raw`\??\C:\WINDOWS\system32\conhost.exe 0x4`], max_per_phase: 48, product_process_cap: 48, job_process_cap: 96, ownership_scope: "Aggregate console budget only; no per-Node parent attribution" };
const toolNames = [node, python, consoleHelper.executable, ...(mode === "build" ? [nextNodePhysical] : []), ...["typescript/bin/tsc", "typescript/lib/typescript.js", ...(mode === "build" ? ["typescript/lib/tsc.js", "typescript/lib/_tsc.js"] : []), "typescript/package.json", "next/dist/bin/next", "next/dist/lib/worker.js", "next/dist/compiled/jest-worker/index.js", "next/dist/compiled/jest-worker/processChild.js", "next/package.json", "vite/bin/vite.js", "vite/dist/node/chunks/node.js", "vite/package.json"].map(p => resolve(root, "node_modules", p))];
const webDistName = ".next-r98-" + output.slice(-16), webDist = resolve(root, "apps/web", webDistName);
const buildTsconfig = resolve(root, "apps/web/tsconfig.json");
const generatedPaths = ["apps/web/public/favicon.ico", "apps/web/public/sw.js", "apps/web/next-env.d.ts", ...(mode === "build" ? ["apps/web/tsconfig.json"] : [])].map(p => resolve(root, p));
const icons = resolve(root, "apps/web/public/icons"), knownIcons = [192, 512, 180].map(n => resolve(icons, `icon-${n}.png`));
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const saveJson = (path, value) => writeFileSync(path, JSON.stringify(value, null, 2) + "\n");
function frontendNextPolicy() {
  const preload = resolve(output, "r98-preload.cjs"), worker = resolve(root, "node_modules/next/dist/compiled/jest-worker/processChild.js");
  return { schema: "r98-frontend-next-policy@1", node_lexical: resolve(node), node_physical: resolve(nextNodePhysical), executable_input: nextNodeInput, preload, worker, exec_argv_variants: [[], ["--enable-source-maps"]], worker_args: [], argv_variants: [[resolve(node), "--require", preload, worker], [resolve(node), "--require", preload, "--enable-source-maps", worker]], path_equivalence: "Windows slash/case only" };
}
function frontendNextTypescriptCliPolicy() {
  const preload = resolve(output, "r98-preload.cjs"), cwd = resolve(root, "apps/web"), tsc = resolve(root, "node_modules/typescript/bin/tsc"), config = resolve(cwd, "tsconfig.json");
  const roles = [
    { role: "next-ts-show-config", request_args: [tsc, "--showConfig", "--project", config, "--pretty", "false"], path_request_indices: [0, 3] },
    { role: "next-ts-typecheck", request_args: [tsc, "--project", config, "--noEmit", "--declarationMap", "false", "--emitDeclarationOnly", "false", "--tsBuildInfoFile", resolve(webDist, "cache/.tsbuildinfo")], path_request_indices: [0, 2, 9] },
  ].map(role => ({ ...role, actual_argv: [resolve(node), "--require", preload, ...role.request_args], path_argv_indices: [0, 2, ...role.path_request_indices.map(index => index + 3)] }));
  return { schema: "r98-frontend-next-typescript-cli-policy@1", node_lexical: resolve(node), node_physical: resolve(nextNodePhysical), executable_input: nextNodeInput, cwd, options: { own_keys: ["cwd", "detached", "env", "shell", "stdio"], detached: false, shell: false, stdio: ["ignore", "pipe", "pipe"], env_contract: "Exact shallow copy of current process.env; values never audited" }, roles, repetition: "No exact invocation count asserted; existing phase time/process/console limits remain" };
}
function frontendNextWorkerLifecyclePolicy() {
  return { schema: "r98-frontend-next-worker-lifecycle-policy@1", role: "next-worker", parent_role: "web-next-root", signal: "SIGINT", terminal_kinds: ["own-exit-0", "framework-parent-observed-sigint", "framework-parent-requested-sigint-native-job-closed"], require_native_exact_identity_and_complete_inventory: true, require_all_node_exact_unique_started: true, require_exact_fork_start_and_worker_started: true, require_parent_own_exit_zero: true, other_roots_and_cli_require_own_exit_zero: true, require_cli_original_spawn_start_and_parent_exit: true, contradictory_visible_exit_or_signal_fails: true, kill_return_and_throw_preserved: true, audit_failure_fails_parent: true, framework_cleanup_is_not_worker_own_exit_zero: true };
}
function envFilesAbsent() {
  for (const dir of [root, ...["web", "desktop", "mobile"].map(p => resolve(root, "apps", p))]) {
    for (const name of [".env", ".env.local", ".env.production", ".env.production.local"]) if (existsSync(resolve(dir, name))) throw Error("Private build refuses ambient env file: " + resolve(dir, name));
  }
}
function environment() {
  const allowed = new Set(["SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "SYSTEMDRIVE"]);
  const clean = Object.fromEntries(Object.entries(process.env).filter(([key]) => allowed.has(key.toUpperCase())));
  return { ...clean, PATH: "C:/Program Files/nodejs;C:/Windows/System32", HOME: resolve(output, "home"), USERPROFILE: resolve(output, "home"), APPDATA: resolve(output, "home/AppData/Roaming"), LOCALAPPDATA: resolve(output, "home/AppData/Local"), TEMP: resolve(output, "tmp"), TMP: resolve(output, "tmp"), TMPDIR: resolve(output, "tmp"), CI: "1", NEXT_TELEMETRY_DISABLED: "1", TI_API_BASE_URL: "http://127.0.0.1:18986", TI_NEXT_DIST_DIR: webDistName, R98_PRIVATE_ROOT: output, R98_REPO_ROOT: root, R98_MODE: mode, R98_WEB_DIST: webDist };
}

// A fresh JS API guard, independent of the old regression guard. It is not an OS sandbox.
const preloadSource = String.raw`'use strict';
const fs = require('node:fs'), path = require('node:path'), cp = require('node:child_process');
const { syncBuiltinESMExports } = require('node:module');
const out = process.env.R98_PRIVATE_ROOT, repo = process.env.R98_REPO_ROOT, build = process.env.R98_MODE === 'build';
if (!out || !repo || !/^r98f[bc]-[a-f0-9]{16}$/.test(path.basename(out))) throw Error('r98_guard_configuration');
const originalAppend = fs.appendFileSync.bind(fs);
const audit = value => originalAppend(path.join(out, 'guard-' + process.pid + '.jsonl'), JSON.stringify({ at: new Date().toISOString(), pid: process.pid, ...value }) + '\n');
let workerStopAuditFailed = false;
function deny(category) { audit({ event: 'denied', category }); throw Error('r98_boundary:' + category); }
const block = (target, names, category) => { for (const name of names) if (name in target) target[name] = () => deny(category); };
for (const name of ['node:net', 'node:tls']) { const m = require(name); block(m, ['connect', 'createConnection', 'createServer'], 'network'); if (m.Socket) block(m.Socket.prototype, ['connect'], 'network'); if (m.Server) block(m.Server.prototype, ['listen'], 'network'); }
for (const name of ['node:http', 'node:https', 'node:http2']) block(require(name), ['request', 'get', 'connect', 'createServer', 'createSecureServer'], 'network');
block(require('node:dgram'), ['createSocket'], 'network');
for (const target of [require('node:dns'), require('node:dns').promises]) { const names = Object.keys(target).filter(n => n === 'lookup' || n === 'lookupService' || n === 'reverse' || n.startsWith('resolve')); block(target, names, 'dns'); if (target.Resolver) block(target.Resolver.prototype, Object.getOwnPropertyNames(target.Resolver.prototype).filter(n => n.startsWith('resolve') || n === 'reverse'), 'dns'); }
globalThis.fetch = () => deny('fetch'); globalThis.WebSocket = class { constructor() { deny('websocket'); } };
const { registerHooks } = require('node:module');
registerHooks({ resolve(specifier, context, nextResolve) { if (/^(?:node:sqlite|better-sqlite3|sqlite3|pg|mysql2?)(?:\/|$)/.test(specifier)) deny('database_module'); return nextResolve(specifier, context); } });
if (process.getBuiltinModule) { const original = process.getBuiltinModule; process.getBuiltinModule = name => { if (name === 'sqlite' || name === 'node:sqlite') deny('database_module'); return original(name); }; }
const originalSpawn = cp.spawn;
block(cp, ['exec', 'execSync', 'execFile', 'execFileSync', 'spawn', 'spawnSync'], 'unreviewed_child');
const blockedExec = cp.exec;
let optionalProbeBlocks = 0;
cp.exec = function(command, options, callback) {
  const phase = process.env.R98_PHASE_NAME;
  if (build && ['desktop-vite', 'mobile-vite'].includes(phase) && arguments.length === 3 && command === 'net use' &&
      options && Object.getPrototypeOf(options) === Object.prototype && Reflect.ownKeys(options).length === 1 && Object.hasOwn(options, 'windowsHide') && options.windowsHide === true && typeof callback === 'function') {
    if (++optionalProbeBlocks > 1) return deny('repeated_optional_probe');
    audit({ event: 'optional_probe_blocked', phase, command, options, not_executed: true });
    const error = Object.assign(new Error('R98 guard denied the optional net use probe; no child was created'), { code: 'EACCES' });
    queueMicrotask(() => callback(error)); // Vite's existing callback returns immediately on error.
    return undefined; // This exact Vite call does not consume a ChildProcess return value.
  }
  return blockedExec.apply(this, arguments);
};
const blockedSpawn = cp.spawn;
const samePath = (actual, expected) => typeof actual === 'string' && actual.replace(/\//g, '\\').toLowerCase() === expected.replace(/\//g, '\\').toLowerCase();
const spawnOptionKeys = value => value && typeof value === 'object' ? Reflect.ownKeys(value).map(String).sort() : [];
function diagnosticArgs(value) {
  let hideNext = false;
  return (Array.isArray(value) ? value : []).slice(0, 32).map(item => {
    const text = typeof item === 'string' ? item.slice(0, 1024) : '[non-string]';
    if (hideNext) { hideNext = false; return '[REDACTED_SECRET]'; }
    hideNext = /^--?(?:password|passwd|token|secret|api[-_]?key|authorization)$/i.test(text);
    return text.replace(/((?:password|passwd|token|secret|api[-_]?key|authorization)\s*[=:]\s*)\S+/gi, '$1[REDACTED_SECRET]').replace(/:\/\/[^\s/:@]+:[^\s/@]+@/g, '://[REDACTED_SECRET]@');
  });
}
cp.spawn = function(command, args, options) {
  const phase = process.env.R98_PHASE_NAME, tsc = path.join(repo, 'node_modules/typescript/bin/tsc'), config = path.join(repo, 'apps/web/tsconfig.json');
  const roles = [
    { role: 'next-ts-show-config', args: [tsc, '--showConfig', '--project', config, '--pretty', 'false'], paths: [0, 3] },
    { role: 'next-ts-typecheck', args: [tsc, '--project', config, '--noEmit', '--declarationMap', 'false', '--emitDeclarationOnly', 'false', '--tsBuildInfoFile', path.join(process.env.R98_WEB_DIST, 'cache/.tsbuildinfo')], paths: [0, 2, 9] },
  ];
  const role = Array.isArray(args) && roles.find(role => args.length === role.args.length && args.every((arg, index) => role.paths.includes(index) ? samePath(arg, role.args[index]) : arg === role.args[index]));
  const keys = spawnOptionKeys(options), env = options?.env, envKeys = env && typeof env === 'object' ? Reflect.ownKeys(env) : [];
  const exactOptions = options && Object.getPrototypeOf(options) === Object.prototype && JSON.stringify(keys) === JSON.stringify(['cwd', 'detached', 'env', 'shell', 'stdio']) &&
    samePath(options.cwd, path.join(repo, 'apps/web')) && options.detached === false && options.shell === false && JSON.stringify(options.stdio) === JSON.stringify(['ignore', 'pipe', 'pipe']) &&
    env && Object.getPrototypeOf(env) === Object.prototype && envKeys.every(key => typeof key === 'string') && envKeys.length === Object.keys(process.env).length && envKeys.every(key => Object.hasOwn(process.env, key) && env[key] === process.env[key]);
  if (build && phase === 'web-next' && arguments.length === 3 && samePath(command, 'C:/Program Files/nodejs/node.exe') && role && exactOptions) {
    const bytes = fs.readFileSync(command), digest = require('node:crypto').createHash('sha256').update(bytes).digest('hex');
    if (samePath(fs.realpathSync(command), 'E:/DevTools/nvm/v22.22.1/node.exe') && bytes.length === 87059456 && digest === '923a41f268ab49ede2e3363fbdd9e790609e385c6f3ca880b4ee9a56a8133e5a') {
      const actualArgs = ['--require', path.join(out, 'r98-preload.cjs'), ...args];
      audit({ event: 'child_requested', api: 'spawn', role: role.role, original_request: { command, args, option_keys: keys, cwd: options.cwd, detached: false, shell: false, stdio: ['ignore', 'pipe', 'pipe'], env_matches_current: true }, actual_argv: [command, ...actualArgs] });
      const child = originalSpawn.call(this, command, actualArgs, options);
      audit({ event: 'child_started', api: 'spawn', role: role.role, child_pid: child.pid });
      child.once('exit', (code, signal) => audit({ event: 'child_exit', api: 'spawn', role: role.role, child_pid: child.pid, code, signal }));
      return child;
    }
  }
  audit({ event: 'spawn_request_rejected', api: 'spawn', command: diagnosticArgs([command])[0], args: diagnosticArgs(args), option_keys: keys.slice(0, 32), stack: String(new Error('Unreviewed spawn request').stack).slice(0, 4096) });
  return blockedSpawn.apply(this, arguments);
};
const originalFork = cp.fork;
cp.fork = function(modulePath, args, options) {
  if (!build || path.resolve(modulePath) !== path.join(repo, 'node_modules/next/dist/compiled/jest-worker/processChild.js')) return deny('unreviewed_fork');
  if (!Array.isArray(args)) { options = args; args = []; }
  if (args.length || options?.shell || (options?.execPath && path.resolve(options.execPath).toLowerCase() !== process.execPath.toLowerCase())) return deny('fork_arguments');
  const execArgv = options?.execArgv || [];
  if (!Array.isArray(execArgv) || !(execArgv.length === 0 || (execArgv.length === 1 && execArgv[0] === '--enable-source-maps'))) return deny('fork_exec_argv');
  const childEnv = { ...(options?.env || process.env), R98_PRIVATE_ROOT: out, R98_REPO_ROOT: repo, R98_MODE: 'build', R98_WEB_DIST: process.env.R98_WEB_DIST, R98_PHASE_NAME: process.env.R98_PHASE_NAME };
  // Next rewrites NODE_OPTIONS; carry the new guard as a literal execArgv pair.
  const argv = ['--require', path.join(out, 'r98-preload.cjs'), ...execArgv];
  audit({ event: 'child_requested', api: 'fork', role: 'next-worker', module: modulePath, args, execArgv: argv });
  const child = originalFork.call(this, modulePath, args, { ...options, env: childEnv, execArgv: argv, windowsHide: true });
  audit({ event: 'child_started', api: 'fork', role: 'next-worker', child_pid: child.pid });
  const originalKill = child.kill;
  child.kill = function(...killArgs) {
    const actualArgs = killArgs.map(value => typeof value === 'string' || typeof value === 'number' ? value : { type: typeof value });
    const details = { event: 'worker_stop_result', api: 'fork', role: 'next-worker', phase: process.env.R98_PHASE_NAME, child_pid: child.pid, receiver_is_exact_child: this === child, actual_arguments: actualArgs };
    let accepted;
    try {
      accepted = Reflect.apply(originalKill, this, killArgs);
    } catch (error) {
      try { audit({ ...details, outcome: 'threw' }); }
      catch { workerStopAuditFailed = true; process.exitCode = 1; }
      throw error;
    }
    // An audit failure fails the parent process without replacing kill's return/throw.
    try { audit({ ...details, outcome: 'returned', accepted }); }
    catch { workerStopAuditFailed = true; process.exitCode = 1; }
    return accepted;
  };
  child.once('exit', (code, signal) => audit({ event: 'child_exit', api: 'fork', role: 'next-worker', child_pid: child.pid, code, signal }));
  return child;
};
block(require('node:cluster'), ['fork', 'setupPrimary', 'setupMaster'], 'cluster');
require('node:worker_threads').Worker = class { constructor() { deny('worker_thread'); } };
const inside = (p, base) => { const rel = path.relative(base, path.resolve(p)); return rel === '' || (rel !== '..' && !rel.startsWith('..' + path.sep) && !path.isAbsolute(rel)); };
const generated = new Set(['apps/web/public/favicon.ico', 'apps/web/public/sw.js', 'apps/web/next-env.d.ts', ...[192, 512, 180].map(n => 'apps/web/public/icons/icon-' + n + '.png')].map(p => path.resolve(repo, p)));
function writeAllowed(value, directory = false) {
  if (typeof value !== 'string' && !(value instanceof URL) && !Buffer.isBuffer(value)) return deny('fd_mutation');
  const p = path.resolve(value instanceof URL ? require('node:url').fileURLToPath(value) : value.toString());
  if (inside(p, out)) return;
  if (build && process.env.R98_PHASE_NAME === 'web-next' && p === path.join(repo, 'apps/web/tsconfig.json')) return;
  if (build && (inside(p, process.env.R98_WEB_DIST) || generated.has(p) || (directory && p === path.join(repo, 'apps/web/public/icons')))) return;
  deny('write_outside_private_or_generated');
}
for (const name of ['writeFile', 'appendFile', 'mkdir', 'mkdtemp', 'rm', 'rmdir', 'unlink', 'truncate', 'chmod', 'chown', 'utimes']) {
  for (const key of [name, name + 'Sync']) if (fs[key]) { const original = fs[key]; fs[key] = function(p, ...rest) { writeAllowed(p, name === 'mkdir'); return original.call(this, p, ...rest); }; }
  if (fs.promises[name]) { const original = fs.promises[name]; fs.promises[name] = function(p, ...rest) { writeAllowed(p, name === 'mkdir'); return original.call(this, p, ...rest); }; }
}
for (const name of ['rename', 'copyFile', 'cp', 'link', 'symlink']) {
  for (const target of [fs, fs.promises]) for (const key of target === fs ? [name, name + 'Sync'] : [name]) if (target[key]) { const original = target[key]; target[key] = function(a, b, ...rest) { if (name !== 'copyFile' && name !== 'cp') writeAllowed(a); writeAllowed(b); return original.call(this, a, b, ...rest); }; }
}
for (const target of [fs, fs.promises]) for (const key of target === fs ? ['open', 'openSync'] : ['open']) { const original = target[key]; target[key] = function(p, flags, ...rest) { if (!(flags === undefined || flags === 'r' || flags === 'rs' || flags === fs.constants.O_RDONLY)) writeAllowed(p); return original.call(this, p, flags, ...rest); }; }
const originalWriteStream = fs.createWriteStream; fs.createWriteStream = function(p, ...args) { writeAllowed(p); return originalWriteStream.call(this, p, ...args); };
// No environment-file credentials are needed for these tests/builds.
for (const target of [fs, fs.promises]) for (const key of target === fs ? ['readFile', 'readFileSync'] : ['readFile']) { const original = target[key]; target[key] = function(p, ...rest) { if (typeof p !== 'number' && /^\.env(?:\.|$)/i.test(path.basename(p instanceof URL ? require('node:url').fileURLToPath(p) : p.toString())) && fs.existsSync(p)) return deny('environment_file'); return original.call(this, p, ...rest); }; }
audit({ event: 'started', argv: process.argv, execArgv: process.execArgv });
process.on('exit', code => { if (workerStopAuditFailed) process.exitCode = 1; audit({ event: 'exit', code, worker_stop_audit_failed: workerStopAuditFailed, active_resource_types: process.getActiveResourcesInfo() }); });
syncBuiltinESMExports();
`;

function commandPlan() {
  const preload = ["--require", resolve(output, "r98-preload.cjs")];
  const actualTestCounts = { "web-review-helper": 12, "web-raw-helper": 10, "native-js-adapters": 39, "transport-authority": 2 };
  const phase = (name, args, cwd = root, timeout = 300, descendants = "none") => ({ name, argv: [node, ...preload, ...args], cwd, timeout_seconds: timeout, descendants, ...(name in actualTestCounts ? { expected_tap_tests: actualTestCounts[name] } : {}), ...(name === "sdk-review" ? { evidence_kind: "one sequential .mts selftest; no node:test nodes or asserted test count" } : {}) });
  if (mode === "checks") return [
    phase("sdk-review", ["--experimental-transform-types", "--import", "./packages/api-client/tests/device-ai/json-esm-hook.mjs", "./packages/api-client/tests/quarantine-review-v2.mts"]),
    phase("web-review-helper", ["--experimental-strip-types", "--import", "./packages/api-client/tests/device-ai/json-esm-hook.mjs", "--experimental-test-isolation=none", "--test-reporter=tap", "--test", "apps/web/tests/binary-quarantine-review.test.ts"]),
    phase("web-raw-helper", ["--experimental-strip-types", "--experimental-test-isolation=none", "--test-reporter=tap", "--test", "apps/web/tests/raw-evidence-v2.test.ts"]),
    phase("native-js-adapters", ["--experimental-test-isolation=none", "--test-reporter=tap", "--test", "packages/native-client/tests/transport.test.mjs", "apps/desktop/tests/native-platform.test.mjs", "apps/mobile/tests/native-platform.test.mjs"]),
    phase("transport-authority", ["--experimental-transform-types", "--import", "./packages/api-client/tests/device-ai/json-esm-hook.mjs", "--experimental-test-isolation=none", "--test-reporter=tap", "--test", "packages/api-client/tests/transport-authority.mts"]),
    ...["apps/web", "apps/desktop", "apps/mobile", "packages/native-client"].map(project => phase(project.replaceAll("/", "-") + "-typecheck", [resolve(root, "node_modules/typescript/bin/tsc"), "--noEmit", "--incremental", "false", "-p", resolve(root, project, "tsconfig.json")])),
    phase("sdk-review-typecheck", [resolve(root, "node_modules/typescript/bin/tsc"), "--noEmit", "--incremental", "false", "-p", resolve(output, "sdk-tsconfig.json")]),
  ];
  return [
    ...["desktop", "mobile"].map(platform => phase(platform + "-vite", [resolve(root, "node_modules/vite/bin/vite.js"), "build", "--configLoader", "native", "--outDir", resolve(output, platform + "-dist")], resolve(root, "apps", platform), 600)),
    phase("web-icons", [resolve(root, "scripts/build-pwa.mjs"), "--icons"], resolve(root, "apps/web"), 180),
    phase("web-next", [resolve(root, "node_modules/next/dist/bin/next"), "build", "--webpack"], resolve(root, "apps/web"), 1200, "frontend-next"),
    phase("web-pwa", [resolve(root, "scripts/build-pwa.mjs")], resolve(root, "apps/web"), 180),
  ];
}
function assertInputs(plan, duringBuild = false) {
  const actual = sources(), expected = { ...plan.sources };
  if (!equal(plan.console_helper, consoleHelper) || !equal(input(consoleHelper.executable), { bytes: consoleHelper.bytes, sha256: consoleHelper.sha256 })) throw Error("Exact native System32 console-helper policy/hash required");
  if (mode === "build" && !equal(plan.frontend_next_console_policy, frontendNextConsolePolicy)) throw Error("Exact frontend-next console policy required");
  if (mode === "build" && !equal(plan.frontend_next_typescript_cli_policy, frontendNextTypescriptCliPolicy())) throw Error("Exact frontend-next TypeScript CLI policy required");
  if (mode === "build" && !equal(plan.frontend_next_worker_lifecycle_policy, frontendNextWorkerLifecyclePolicy())) throw Error("Exact frontend-next worker lifecycle policy required");
  if (mode === "build" && (!equal(plan.frontend_next_policy, frontendNextPolicy()) || resolve(realpathSync(node)).toLowerCase() !== resolve(nextNodePhysical).toLowerCase() || !equal(input(node), nextNodeInput) || !equal(input(nextNodePhysical), nextNodeInput) || !equal(plan.executables[resolve(node)], nextNodeInput) || !equal(plan.executables[resolve(nextNodePhysical)], nextNodeInput))) throw Error("Fixed frontend-next lexical/physical Node policy and equal hash pins required");
  if (duringBuild && mode === "build") {
    const record = plan.generated_before?.records.find(item => item.path === buildTsconfig);
    if (!record?.exists || !equal({ bytes: record.bytes, sha256: record.sha256 }, expected[buildTsconfig]) || !equal(plan.generated_inputs[record.backup], expected[buildTsconfig])) throw Error("Build tsconfig must preserve original source and complete before backup pins");
    delete actual[buildTsconfig]; delete expected[buildTsconfig];
  }
  if (!equal(actual, expected)) throw Error("Frozen source set/bytes changed");
  for (const section of ["executables", "generated_inputs"]) for (const [name, expected] of Object.entries(plan[section])) if (!equal(input(name), expected)) throw Error("Frozen input drift: " + name);
}
function generatedBefore() {
  const iconFiles = existsSync(icons) ? files(icons) : [];
  const all = [...new Set([...generatedPaths, ...knownIcons, ...iconFiles])].sort();
  const records = all.map(path => ({ path, exists: existsSync(path), ...(existsSync(path) ? input(path) : {}) }));
  const dirs = [];
  function walk(dir) { if (!existsSync(dir)) return; dirs.push(dir); for (const e of readdirSync(dir, { withFileTypes: true })) if (e.isDirectory()) walk(resolve(dir, e.name)); }
  walk(icons);
  for (const item of records) if (item.exists) { const backup = resolve(output, "before", relative(root, item.path)); mkdirSync(dirname(backup), { recursive: true }); writeFileSync(backup, readFileSync(item.path)); item.backup = backup; }
  return { records, icons_existed: existsSync(icons), icon_directories: dirs, icon_files: iconFiles };
}
function restoreGenerated(before) {
  const current = existsSync(icons) ? files(icons) : [];
  const unknown = current.filter(p => !before.icon_files.includes(p) && !knownIcons.includes(p));
  const unexpectedDirs = [];
  function walk(dir) { if (!existsSync(dir)) return; if (!before.icon_directories.includes(dir) && dir !== icons) unexpectedDirs.push(dir); for (const e of readdirSync(dir, { withFileTypes: true })) if (e.isDirectory()) walk(resolve(dir, e.name)); }
  walk(icons);
  for (const item of before.records) {
    if (item.exists) {
      if (!equal(input(item.backup), { bytes: item.bytes, sha256: item.sha256 })) throw Error("Before backup drift");
      if (!generatedPaths.includes(item.path) && !knownIcons.includes(item.path) && (!existsSync(item.path) || !equal(input(item.path), { bytes: item.bytes, sha256: item.sha256 }))) {
        unknown.push(item.path); continue; // Preserve a newly changed unknown file; retain its frozen before bytes separately.
      }
      mkdirSync(dirname(item.path), { recursive: true }); writeFileSync(item.path, readFileSync(item.backup));
    } else if (existsSync(item.path)) { if (!lstatSync(item.path).isFile() || lstatSync(item.path).isSymbolicLink()) throw Error("Unsafe generated restore"); unlinkSync(item.path); }
  }
  if (!before.icons_existed && existsSync(icons) && readdirSync(icons).length === 0) rmdirSync(icons);
  const mismatches = before.records.filter(item => existsSync(item.path) !== item.exists || (item.exists && !equal(input(item.path), { bytes: item.bytes, sha256: item.sha256 }))).map(item => item.path);
  return { exact_original_files: !mismatches.length, icons_directory_restored: existsSync(icons) === before.icons_existed, mismatches, unexpected_files_preserved: unknown, unexpected_directories_preserved: unexpectedDirs, passed: !mismatches.length && !unknown.length && !unexpectedDirs.length && existsSync(icons) === before.icons_existed };
}
function artifactManifest(path) { return { path, files: Object.fromEntries(files(path).map(p => [relative(path, p).replaceAll("\\", "/"), input(p)])) }; }
function guardTerminals(plan, logs) {
  const ownZero = log => { const exits = log.events.filter(event => event.event === "exit"); return exits.length === 1 && exits[0].code === 0 && exits[0].worker_stop_audit_failed !== true; };
  if (mode !== "build") {
    if (logs.some(log => !ownZero(log))) throw Error("Missing/nonzero own guard exit");
    return logs.map(log => ({ name: log.name, kind: "own-exit-0" }));
  }
  const samePath = (actual, expected) => typeof actual === "string" && typeof expected === "string" && actual.replaceAll("/", "\\").toLowerCase() === expected.replaceAll("/", "\\").toLowerCase();
  const sameArgv = (actual, expected, paths) => Array.isArray(actual) && actual.length === expected.length && actual.every((value, index) => paths.includes(index) ? samePath(value, expected[index]) : value === expected[index]);
  const childEvents = (eventName, pid) => logs.flatMap(log => log.events.flatMap((event, index) => event.event === eventName && event.child_pid === pid ? [{ log, event, index }] : []));
  const evidence = item => ({ guard: item.log.name, event_index: item.index, event: item.event });
  const native = new Map(), byPid = new Map();
  let next = null;
  for (const phase of plan.phases) {
    const receipt = JSON.parse(readFileSync(resolve(output, phase.name + ".process.json"), "utf8"));
    if (receipt.name !== phase.name || !equal(receipt.argv, phase.argv) || receipt.cwd !== phase.cwd || receipt.state !== "passed" || receipt.exit_code !== 0 || receipt.final_exit_code !== 0 || receipt.natural_resources_closed !== true || receipt.forced_job_close !== false || receipt.owned_popen_termination_requested || receipt.cleanup_error || receipt.cleanup_query_error || receipt.classification_error || receipt.all_processes_observed !== true || receipt.all_observed_classified !== true || receipt.job_total_processes !== receipt.observed_processes || receipt.active_pids_after_natural_grace?.length !== 0) throw Error("Complete natural Native receipt required for guard lifecycle audit");
    const classified = [receipt.pid, ...receipt.children.map(child => child.pid), ...receipt.console_helpers.map(child => child.pid)].sort((a, b) => a - b);
    if (classified.some(pid => !Number.isSafeInteger(pid) || pid <= 0) || new Set(classified).size !== classified.length || !equal(classified, receipt.classified_observed_pids) || classified.length !== receipt.observed_processes || receipt.console_helpers.some(child => child.allowed !== true)) throw Error("Complete classified Native PID inventory required");
    const add = (pid, value) => { if (native.has(pid)) throw Error("Duplicate Native Node PID"); native.set(pid, value); };
    add(receipt.pid, { role: phase.name === "web-next" ? "web-next-root" : "phase-root", phase: phase.name, phase_argv: phase.argv, executable_input: receipt.executable_input });
    for (const child of receipt.children) {
      if (phase.name !== "web-next" || child.allowed !== true || !["next-worker", "next-ts-show-config", "next-ts-typecheck"].includes(child.role)) throw Error("Unknown Native child role in guard lifecycle audit");
      add(child.pid, { ...child, phase: phase.name });
    }
    if (phase.name === "web-next") next = receipt;
  }
  for (const log of logs) {
    const pid = Number(/^guard-([0-9]+)\.jsonl$/.exec(log.name)?.[1]);
    if (!native.has(pid) || byPid.has(pid) || log.events.some(event => event.pid !== pid)) throw Error("Guard PID absent from complete Native inventory");
    byPid.set(pid, log);
  }
  if (!next || byPid.size !== native.size || !ownZero(byPid.get(next.pid))) throw Error("Every Native Node and exact Next root own exit audit required");
  const policy = plan.frontend_next_policy;
  const execVariants = policy.exec_argv_variants.map(args => ["--require", policy.preload, ...args]);
  const terminals = [];
  for (const [pid, entry] of native) {
    const log = byPid.get(pid);
    const ownStarts = log.events.filter(event => event.event === "started");
    if (ownStarts.length !== 1) throw Error("Unique own guard startup required: " + pid);
    if (["phase-root", "web-next-root"].includes(entry.role)) {
      if (!equal(entry.executable_input, policy.executable_input) || !sameArgv(ownStarts[0].argv, [entry.phase_argv[0], ...entry.phase_argv.slice(3)], [0, 1]) || !sameArgv(ownStarts[0].execArgv, entry.phase_argv.slice(1, 3), [1])) throw Error("Exact frozen root guard startup required");
      if (!ownZero(log)) throw Error("Root/CLI own exit zero required: " + pid);
      terminals.push({ pid, role: entry.role, guard: log.name, kind: "own-exit-0" });
      continue;
    }
    if (entry.phase !== "web-next" || !samePath(entry.executable, policy.node_physical) || !equal(entry.executable_input, policy.executable_input)) throw Error("Exact Native worker/CLI identity required");
    const starts = childEvents("child_started", pid), parentExits = childEvents("child_exit", pid), stops = childEvents("worker_stop_result", pid);
    if (starts.length !== 1) throw Error("Unique parent child start required: " + pid);
    const start = starts[0], request = start.log.events[start.index - 1];
    if (entry.role !== "next-worker") {
      const cli = plan.frontend_next_typescript_cli_policy, role = cli.roles.find(role => role.role === entry.role), parentRole = native.get(start.event.pid)?.role;
      if (!role || !["web-next-root", "next-worker"].includes(parentRole) || start.event.api !== "spawn" || start.event.role !== role.role || request?.event !== "child_requested" || request.api !== "spawn" || request.role !== role.role || !sameArgv(request.actual_argv, role.actual_argv, role.path_argv_indices)) throw Error("Exact paired CLI spawn request/start required");
      const original = request.original_request;
      if (!original || !samePath(original.command, cli.node_lexical) || !sameArgv(original.args, role.request_args, role.path_request_indices) || !equal(original.option_keys, cli.options.own_keys) || !samePath(original.cwd, cli.cwd) || original.detached !== false || original.shell !== false || !equal(original.stdio, cli.options.stdio) || original.env_matches_current !== true) throw Error("Exact original CLI request contract required");
      const argvPaths = role.path_argv_indices.filter(index => index !== 2).map(index => index >= 3 ? index - 2 : index);
      if (!sameArgv(ownStarts[0].argv, [role.actual_argv[0], ...role.actual_argv.slice(3)], argvPaths) || !sameArgv(ownStarts[0].execArgv, ["--require", policy.preload], [1]) || !ownZero(log) || stops.length || parentExits.length !== 1 || parentExits[0].event.pid !== start.event.pid || parentExits[0].event.api !== "spawn" || parentExits[0].event.role !== role.role || parentExits[0].event.code !== 0 || parentExits[0].event.signal !== null) throw Error("CLI own exit zero and exact parent exit required");
      terminals.push({ pid, role: entry.role, guard: log.name, parent_pid: start.event.pid, kind: "own-exit-0", parent_start: evidence(start), parent_exit: evidence(parentExits[0]) });
      continue;
    }
    if (start.event.pid !== next.pid || start.event.api !== "fork" || start.event.role !== "next-worker") throw Error("Unique exact Next-root worker start required");
    if (request?.event !== "child_requested" || request.api !== "fork" || request.role !== "next-worker" || !samePath(request.module, policy.worker) || !equal(request.args, []) || !execVariants.some(argv => sameArgv(request.execArgv, argv, [1]))) throw Error("Exact paired Next-root fork request required");
    if (!sameArgv(ownStarts[0].argv, [policy.node_lexical, policy.worker], [0, 1]) || !sameArgv(ownStarts[0].execArgv, request.execArgv, [1])) throw Error("Exact worker own guard startup required");
    const ownExits = log.events.filter(event => event.event === "exit");
    if (ownExits.length > 1 || ownExits.some(event => event.code !== 0 || event.worker_stop_audit_failed === true) || parentExits.length > 1 || parentExits.some(({ event }) => event.pid !== next.pid || event.api !== "fork" || event.role !== "next-worker" || !((event.code === 0 && event.signal === null) || (event.code === null && event.signal === "SIGINT"))) || stops.some(({ event }) => event.pid !== next.pid || event.api !== "fork" || event.role !== "next-worker" || event.phase !== "web-next" || event.receiver_is_exact_child !== true || !equal(event.actual_arguments, ["SIGINT"]) || event.outcome !== "returned" || typeof event.accepted !== "boolean")) throw Error("Contradictory worker terminal evidence");
    let kind;
    if (ownZero(log)) kind = "own-exit-0";
    else if (parentExits.some(({ event }) => event.code === null && event.signal === "SIGINT")) kind = "framework-parent-observed-sigint";
    else if (stops.some(({ event }) => event.accepted === true)) kind = "framework-parent-requested-sigint-native-job-closed";
    else throw Error("Worker lacks exact terminal evidence: " + pid);
    terminals.push({ pid, role: "next-worker", guard: log.name, parent_pid: next.pid, kind, worker_own_exit_zero: ownZero(log), native_inventory_complete: true, supervisor_forced_close: false, parent_start: evidence(start), parent_exit_events: parentExits.map(evidence), stop_results: stops.map(evidence) });
  }
  for (const log of logs) for (const [index, event] of log.events.entries()) {
    if (event.event === "child_requested" && log.events[index + 1]?.event !== "child_started") throw Error("Unpaired child request audit");
    if (["child_started", "child_exit", "worker_stop_result"].includes(event.event) && !["next-worker", "next-ts-show-config", "next-ts-typecheck"].includes(native.get(event.child_pid)?.role)) throw Error("Unknown child lifecycle audit");
  }
  return terminals;
}

if (action === "freeze") {
  if (existsSync(output)) throw Error("Fresh private output required");
  if (mode === "build") { envFilesAbsent(); if (existsSync(webDist)) throw Error("Fresh isolated Next output required"); }
  const before = sources();
  mkdirSync(output);
  for (const name of ["tmp", "home", "home/AppData/Local", "home/AppData/Roaming"]) mkdirSync(resolve(output, name), { recursive: true });
  const preload = resolve(output, "r98-preload.cjs"), config = resolve(output, "sdk-tsconfig.json");
  writeFileSync(preload, preloadSource);
  saveJson(config, { extends: resolve(root, "tsconfig.json"), compilerOptions: { noEmit: true, incremental: false, allowImportingTsExtensions: true, types: ["node"], typeRoots: [resolve(root, "node_modules/@types")] }, files: [resolve(root, "packages/api-client/tests/quarantine-review-v2.mts")], include: [], exclude: [] });
  const plan = { schema: "r98-exact-frontend-freeze@1", kind: mode, output, frozen_at: new Date().toISOString(), sources: before, executables: Object.fromEntries(toolNames.map(p => [resolve(p), input(p)])), generated_inputs: { [preload]: input(preload), [config]: input(config) }, phases: commandPlan(), environment: environment(), generated_before: mode === "build" ? generatedBefore() : null, console_helper: consoleHelper, frontend_next_console_policy: mode === "build" ? frontendNextConsolePolicy : null, frontend_next_policy: mode === "build" ? frontendNextPolicy() : null, frontend_next_typescript_cli_policy: mode === "build" ? frontendNextTypescriptCliPolicy() : null, frontend_next_worker_lifecycle_policy: mode === "build" ? frontendNextWorkerLifecyclePolicy() : null, web_dist: webDist, api_base: "http://127.0.0.1:18986", web_origin: "http://127.0.0.1:18987", host_build: Object.fromEntries(["web", "desktop", "mobile"].map(p => [p, offlineHostBuild(root, p)])), vite_config_loader: mode === "build" ? "native" : null, scope: mode === "build" ? "Real Vite production builds with the official native config loader and Next Webpack production build; default Vite bundle config loader/Turbopack are not covered. No HTTP/UI/browser/Native host/device acceptance." : "Node helper/SDK/transport and exact noEmit TypeScript only; no HTTP/UI/browser/Native host/device acceptance." };
  if (plan.generated_before) for (const item of plan.generated_before.records) if (item.exists) plan.generated_inputs[item.backup] = input(item.backup);
  assertInputs(plan);
  saveJson(resolve(output, "freeze.json"), plan);
  console.log(JSON.stringify({ state: "frozen-not-run", output, freeze: input(resolve(output, "freeze.json")) }));
} else {
  if (!/^[a-f0-9]{64}$/.test(reviewedSha || "") || input(resolve(output, "freeze.json")).sha256 !== reviewedSha) throw Error("Independently reviewed freeze SHA required");
  if (existsSync(resolve(output, "verification.json"))) throw Error("Single-use frozen output required");
  const plan = JSON.parse(readFileSync(resolve(output, "freeze.json"), "utf8"));
  if (plan.output !== output || plan.kind !== mode || !equal(plan.phases, commandPlan())) throw Error("Literal command plan drift");
  assertInputs(plan);
  if (mode === "build") { envFilesAbsent(); if (existsSync(webDist)) throw Error("Next output already exists"); for (const item of plan.generated_before.records) if (existsSync(item.path) !== item.exists || (item.exists && !equal(input(item.path), { bytes: item.bytes, sha256: item.sha256 }))) throw Error("Generated-before drift before build"); }
  const report = { schema: "r98-frontend-verification@1", mode, state: "running", started: new Date().toISOString(), freeze_sha256: reviewedSha, scope: plan.scope, vite_config_loader: plan.vite_config_loader, phases: [], artifacts: {}, source_stable: null, generated_restore: null };
  const save = () => saveJson(resolve(output, "verification.json"), report); save();
  let failure = null;
  try {
    for (const phase of plan.phases) {
      assertInputs(plan, mode === "build");
      const argv = ["-I", "-X", "utf8", "-B", supervisor, "frontend-phase", output, phase.name, reviewedSha];
      const child = spawnSync(python, argv, { cwd: root, env: plan.environment, windowsHide: true, stdio: "pipe", timeout: (phase.timeout_seconds + 30) * 1000, maxBuffer: 4 * 1024 * 1024 });
      writeFileSync(resolve(output, phase.name + ".supervisor.stdout.log"), child.stdout || Buffer.alloc(0));
      writeFileSync(resolve(output, phase.name + ".supervisor.stderr.log"), child.stderr || Buffer.alloc(0));
      report.phases.push({ name: phase.name, supervisor_argv: [python, ...argv], supervisor_exit: child.status, supervisor_signal: child.signal, supervisor_error: child.error ? String(child.error) : null, receipt: resolve(output, phase.name + ".process.json") }); save();
      if (child.status !== 0 || child.error || child.signal) throw Error(phase.name + " failed; inspect exact retained process/log receipts");
      const receipt = JSON.parse(readFileSync(resolve(output, phase.name + ".process.json"), "utf8"));
      if (receipt.state !== "passed" || !receipt.natural_resources_closed || receipt.exit_code !== 0) throw Error("Child resource/exit receipt failed");
    }
    const guardLogs = readdirSync(output).filter(p => /^guard-[0-9]+\.jsonl$/.test(p));
    report.guard_audits = guardLogs.map(name => ({ name, events: readFileSync(resolve(output, name), "utf8").trim().split("\n").map(line => JSON.parse(line)) }));
    report.unexpected_denied = report.guard_audits.flatMap(log => log.events.filter(e => e.event === "denied"));
    report.optional_probe_blocks = report.guard_audits.flatMap(log => log.events.filter(e => e.event === "optional_probe_blocked"));
    if (!guardLogs.length || report.unexpected_denied.length) throw Error("Missing/unexpected-denied guard audit");
    report.guard_terminals = guardTerminals(plan, report.guard_audits);
    report.framework_worker_cleanups = report.guard_terminals.filter(terminal => terminal.role === "next-worker" && terminal.kind !== "own-exit-0");
    const allowedOptionalPhases = mode === "build" ? ["desktop-vite", "mobile-vite"] : [];
    if (report.optional_probe_blocks.length > allowedOptionalPhases.length || report.optional_probe_blocks.some(e => !allowedOptionalPhases.includes(e.phase) || e.command !== "net use" || e.not_executed !== true || !e.options || Object.keys(e.options).length !== 1 || e.options.windowsHide !== true) || allowedOptionalPhases.some(phase => report.optional_probe_blocks.filter(e => e.phase === phase).length > 1)) throw Error("Optional probe refusal exceeds the reviewed exact scope or budget");
    if (mode === "build") {
      for (const p of ["desktop", "mobile", "web"]) {
        const dir = p === "web" ? webDist : resolve(output, p + "-dist");
        report.artifacts[p] = artifactManifest(dir);
        const js = files(dir).filter(name => name.endsWith(".js")).map(name => readFileSync(name, "utf8")).join("\n");
        report.artifacts[p].host_fingerprint_found = js.includes(plan.host_build[p]);
        if (!report.artifacts[p].host_fingerprint_found) throw Error(p + " host fingerprint absent");
      }
      report.generated_after_build = Object.fromEntries([...generatedPaths, ...files(icons)].map(p => [p, existsSync(p) ? input(p) : null]));
    }
  } catch (error) { failure = error; report.error = String(error); }
  finally {
    if (mode === "build") try { report.generated_restore = restoreGenerated(plan.generated_before); if (!report.generated_restore.passed) throw Error("Strict generated restore failed; unknown files preserved"); } catch (error) { failure ||= error; report.restore_error = String(error); }
    try { assertInputs(plan); report.source_stable = true; report.source_after = sources(); } catch (error) { failure ||= error; report.source_stable = false; report.source_error = String(error); }
    report.state = failure ? "failed" : "passed"; report.ended = new Date().toISOString(); report.retained_outputs = true; save();
  }
  if (failure) { console.error(String(failure)); process.exitCode = 1; }
}
