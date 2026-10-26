/**
 * R128 component QA. Root alone executes prepare/review/run.
 * prepare component <fresh .artifacts/toast-component-qa-...> <live|archived-baseline>
 * run     component <same slot> <reviewed prepare.json SHA256>
 * Inline TSX imports the real Provider; no API, SQLite, HTTP server or product scheduler.
 */
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, realpathSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, dirname, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";

const require = createRequire(import.meta.url), root = resolve(import.meta.dirname, "..");
const [action, mode, rawOutput, selection] = process.argv.slice(2);
const origin = "http://127.0.0.1:19028", schema = "toast-lifecycle-component-qa@1";
const artifact = resolve(root, ".artifacts/r128-toast-lifecycle-layout-20261023");
const plan = resolve(root, "docs/plans/2026-10-23-toast-lifecycle-layout.md");
const loader = resolve(root, "scripts/command_palette_browser_qa_loader.cjs");
const virtualEntry = resolve(root, "scripts/__r128_inline_toast_fixture__.tsx");
const playwrightRoot = "E:/Mix/project/fnxt-platform-mobile/node_modules/.pnpm/playwright-core@1.63.0/node_modules/playwright-core";
const browserRoot = "C:/Users/11585/AppData/Local/ms-playwright/chromium_headless_shell-1243";
const browserExe = "chrome-headless-shell-win64/chrome-headless-shell.exe";
const labels = new Set(), sha = bytes => createHash("sha256").update(bytes).digest("hex");
let output, stage = "arguments", receipt, createdOutput = false;
const check = (label, okay) => { labels.add(label); if (!okay) throw Error(label); };
const file = path => { const item = lstatSync(path); check("regular_input", item.isFile() && !item.isSymbolicLink()); const bytes = readFileSync(path); return { bytes: bytes.length, sha256: sha(bytes) }; };
const snapshot = paths => Object.fromEntries([...new Set(paths)].sort().map(path => [path, file(path)]));
const equal = (a, b) => isDeepStrictEqual(a, b);
const save = (name, value) => writeFileSync(resolve(output, name), JSON.stringify(value, null, 2) + "\n");

// Same private runtime/sidecar policy as the reviewed R123/R124 component tools.
function tree(base, target, prefix = "", generatedBrowserFiles) {
  check("regular_runtime_directory", lstatSync(base).isDirectory() && !lstatSync(base).isSymbolicLink());
  if (target) mkdirSync(target, { recursive: true });
  const result = {};
  for (const item of readdirSync(base, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const name = prefix + item.name;
    check("regular_runtime_entry", !item.isSymbolicLink());
    const source = resolve(base, item.name), destination = target ? resolve(target, item.name) : undefined;
    if (item.isDirectory()) {
      check("prepared_runtime_directory", !generatedBrowserFiles || Object.hasOwn(generatedBrowserFiles.prepared, name + "/"));
      result[name + "/"] = { kind: "directory" };
      Object.assign(result, tree(source, destination, name + "/", generatedBrowserFiles));
    } else {
      check("regular_runtime_file", item.isFile());
      if (name === "chrome-headless-shell-win64/debug.log" && !generatedBrowserFiles) continue;
      if (generatedBrowserFiles && !Object.hasOwn(generatedBrowserFiles.prepared, name)) {
        const metadata = lstatSync(source);
        check("bounded_generated_browser_sidecar", /^chrome-headless-shell-win64\/(?:debug\.log|chrome-headless-shell\.\d{8}-\d{6}-\d{3}\.log)$/.test(name)
          && metadata.isFile() && !metadata.isSymbolicLink() && metadata.size >= 1 && metadata.size <= 1024 * 1024 && generatedBrowserFiles.records.length < 4);
        const generated = file(source);
        check("bounded_generated_browser_sidecar_bytes", generated.bytes >= 1 && generated.bytes <= 1024 * 1024);
        generatedBrowserFiles.records.push({ path: name, ...generated });
      } else {
        result[name] = file(source);
        if (destination) copyFileSync(source, destination);
      }
    }
  }
  return result;
}
function safeError(error) {
  const type = ["AssertionError", "TimeoutError", "TypeError", "SyntaxError"].includes(error?.name) ? error.name : "Error";
  return { stage, type, source_lines: [...String(error?.stack || "").matchAll(/toast_lifecycle_ui_qa\.mjs:(\d+):(\d+)/g)]
    .map(match => ({ line: Number(match[1]), column: Number(match[2]) })), ...(labels.has(error?.message) ? { assertion: error.message } : {}) };
}

function fixtureSource(toastPath) {
  // Absolute imports also work from Webpack's data URI entry. TypeScript sees this
  // exact string at virtualEntry; no extra repository fixture is written.
  const quoted = path => JSON.stringify(path.replaceAll("\\", "/"));
  return `import React, { StrictMode, useLayoutEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { flushSync } from "react-dom";
import * as Toast from ${quoted(toastPath)};
type Layout = { navigationRef: (element: HTMLElement | null) => void; comparisonRef: (element: HTMLElement | null) => void; mainRef: (element: HTMLElement | null) => void };
type Options = { nav: boolean; tray: boolean; native: boolean; theme: string; originPresent: boolean };
declare global { interface Window { toastQA: any; toastOptions: Partial<Options>; } }
const api: any = { mounts: 0, cleanups: 0, actions: 0, configure: null, show: null };
window.toastQA = api;
let reactRoot: Root | null = null;
const initial: Options = { nav: true, tray: false, native: false, theme: "light", originPresent: true, ...window.toastOptions };
function Fixture({ options }: { options: Options }) {
  const show = Toast.useToast();
  const useLayout = Reflect.get(Toast, "useToastLayout") as (() => Layout) | undefined;
  const layout = useLayout ? useLayout() : null;
  api.hasLayoutHook = !!layout;
  api.show = (text: string, kind?: Toast.ToastKind) => flushSync(() => show(text, kind));
  api.rawShow = show;
  useLayoutEffect(() => { api.mounts++; return () => { api.cleanups++; }; }, []);
  return <div className="app-shell" data-theme={options.theme}>
    <aside className="sidebar" aria-label="组件夹具侧栏">R128 component fixture</aside>
    <div className="workspace"><main id="main-content" className="main-content" tabIndex={-1} ref={layout?.mainRef}>
      <h1>真实 ToastProvider 组件夹具</h1>
      <p>此页面不是生产 Workbench；没有业务请求。</p>
      <button id="qa-event-order" type="button" onClick={() => { show("event-order-D"); (document.querySelector(".toast-close") as HTMLButtonElement | null)?.focus(); }}>合成事件顺序应力</button>
      <div className="qa-fields">
        {options.originPresent && <label>保留输入<input id="retained-input" defaultValue="225/45 retained draft" /></label>}
        <label>未提交价格<input id="price-draft" defaultValue="123.45" /></label>
        <label>型号<select id="model-draft" defaultValue="model-b"><option value="model-a">型号 A</option><option value="model-b">型号 B</option></select></label>
        <label>区域<select id="region-draft" defaultValue="US"><option value="US">美国</option><option value="CN">中国</option></select></label>
        <label><input id="compare-draft" type="checkbox" defaultChecked />保留比较选择</label>
      </div>
      <div className="qa-spacer" aria-hidden="true" />
      <button id="end-action" className="primary-button" data-count={api.actions} onClick={() => { api.actions++; document.querySelector("#end-action")?.setAttribute("data-count", String(api.actions)); }}>正文末尾操作</button>
    </main></div>
    {options.tray && <div className="comparison-tray" ref={layout?.comparisonRef}><span>已选 <strong>2</strong> 项规格</span><button className="primary-button compact" type="button">查看比较</button></div>}
    {options.nav && <nav className="mobile-nav" aria-label="组件移动导航" ref={layout?.navigationRef}>{["查询", "关注", "比较", "资料", "价格", "模型", "设置"].map(text => <button type="button" key={text}><span>{text}</span></button>)}</nav>}
  </div>;
}
function App() {
  const [options, setOptions] = useState(initial);
  api.configure = (patch: Partial<Options>) => flushSync(() => setOptions(previous => ({ ...previous, ...patch })));
  return <div id="native-fixture" className={options.native ? "mobile-native-root" : undefined}><Toast.ToastProvider><Fixture options={options} /></Toast.ToastProvider></div>;
}
api.mount = () => { if (reactRoot) throw Error("fixture_already_mounted"); reactRoot = createRoot(document.querySelector("#root")!); flushSync(() => reactRoot!.render(<StrictMode><App /></StrictMode>)); };
api.unmount = () => { if (!reactRoot) throw Error("fixture_not_mounted"); flushSync(() => reactRoot!.unmount()); reactRoot = null; };
api.mount();
`;
}

async function prepare() {
  check("source_selection", ["live", "archived-baseline"].includes(selection));
  check("fresh_output", !existsSync(output)); mkdirSync(output); createdOutput = true;
  stage = "prepare_inputs";
  check("frozen_plan_pin", equal(file(plan), { bytes: 25817, sha256: "6fa5e396b4b8c1a9716e64aad15db34d6b7667a4877e676e9352e6de426d07dc" }));
  check("virtual_entry_absent", !existsSync(virtualEntry));
  const archived = selection === "archived-baseline", sourceBase = archived ? resolve(artifact, "before") : root;
  const toast = resolve(sourceBase, "apps/web/components/toast.tsx"), css = resolve(sourceBase, "apps/web/app/globals.css");
  const mobileCss = resolve(sourceBase, "apps/mobile/src/styles.css"), icons = resolve(root, "apps/web/components/icons.tsx");
  const beforeManifest = resolve(artifact, "before-manifest.json");
  if (archived) {
    const before = JSON.parse(readFileSync(beforeManifest, "utf8"));
    for (const path of [toast, css, mobileCss]) {
      const row = before.product_sources.find(pair => resolve(root, pair.archive.path) === path)?.archive;
      check("exact_archived_baseline", !!row && equal(file(path), { bytes: row.bytes, sha256: row.sha256 }));
    }
  }
  const info = JSON.parse(readFileSync(resolve(playwrightRoot, "package.json"), "utf8"));
  check("reviewed_playwright_163", info.name === "playwright-core" && info.version === "1.63.0");
  const initialPins = snapshot([import.meta.filename, loader, toast, css, mobileCss, icons, plan, beforeManifest,
    resolve(artifact, "implementation-start.json"), resolve(artifact, "plan-freeze.json"), resolve(artifact, "plan-review-qa-final.json"),
    resolve(root, "tsconfig.json"), resolve(root, "package-lock.json"), require.resolve("typescript"),
    require.resolve("next/dist/compiled/webpack/webpack"), require.resolve("next/dist/compiled/webpack/bundle5"), process.execPath]);
  const runtime = { playwright: tree(playwrightRoot), browser: tree(browserRoot) }, pinned = { ...initialPins };
  const pin = path => { if (existsSync(path) && lstatSync(path).isFile() && !pinned[path]) pinned[path] = file(path); };
  const source = fixtureSource(toast), ts = require("typescript");
  stage = "prepare_types";
  const config = ts.readConfigFile(resolve(root, "tsconfig.json"), ts.sys.readFile); check("base_config", !config.error);
  const converted = ts.convertCompilerOptionsFromJson({ ...config.config.compilerOptions, jsx: "react-jsx", types: ["react", "react-dom", "node"],
    allowImportingTsExtensions: true, incremental: false, noEmit: true }, root);
  const host = ts.createCompilerHost(converted.options), originalRead = host.readFile.bind(host), originalExists = host.fileExists.bind(host);
  host.readFile = path => resolve(path) === virtualEntry ? source : (pin(resolve(path)), originalRead(path));
  host.fileExists = path => resolve(path) === virtualEntry || originalExists(path);
  host.resolveModuleNames = (names, containingFile) => names.map(name => {
    if (archived && resolve(containingFile) === toast && name === "./icons") return { resolvedFileName: icons, extension: ts.Extension.Tsx };
    return ts.resolveModuleName(name, containingFile, converted.options, host).resolvedModule;
  });
  const program = ts.createProgram([virtualEntry], converted.options, host), diagnostics = [...converted.errors, ...ts.getPreEmitDiagnostics(program)];
  const errors = diagnostics.filter(item => item.category === ts.DiagnosticCategory.Error).map(item => ({ code: item.code,
    source: item.file ? relative(root, item.file.fileName).replaceAll("\\", "/") : null,
    line: item.file && item.start !== undefined ? item.file.getLineAndCharacterOfPosition(item.start).line + 1 : null }));
  save("typecheck.json", { scope: "inline fixture and real ToastProvider imports; no Workbench production acceptance", errors, warning_count: diagnostics.length - errors.length });
  check("target_types", errors.length === 0);
  const transpiled = ts.transpileModule(source, { fileName: virtualEntry, compilerOptions: { target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX, isolatedModules: true }, reportDiagnostics: true });
  check("inline_transpile", !(transpiled.diagnostics || []).some(item => item.category === ts.DiagnosticCategory.Error));
  stage = "prepare_bundle";
  const { webpack } = require("next/dist/compiled/webpack/webpack"); Object.keys(require.cache).forEach(pin);
  const plugins = archived ? [new webpack.NormalModuleReplacementPlugin(/^\.\/icons$/, resource => {
    if (resolve(resource.context) === dirname(toast)) resource.request = icons;
  })] : [];
  const compiler = webpack({ mode: "development", context: root, target: "web", cache: false, devtool: false,
    entry: "data:text/javascript;base64," + Buffer.from(transpiled.outputText, "utf8").toString("base64"), output: { path: output, filename: "fixture.js" },
    optimization: { minimize: false }, performance: false, infrastructureLogging: { level: "none" }, plugins,
    resolve: { extensions: [".tsx", ".ts", ".js"], extensionAlias: { ".js": [".js", ".ts", ".tsx"] }, modules: [resolve(root, "node_modules"), "node_modules"] },
    module: { rules: [{ test: /\.tsx?$/, include: [resolve(root, "apps/web/components"), resolve(root, "packages"), ...(archived ? [toast] : [])], use: [loader] }] },
  });
  const fsRead = compiler.inputFileSystem.readFile.bind(compiler.inputFileSystem);
  compiler.inputFileSystem.readFile = (path, ...args) => { if (typeof path === "string") pin(path); return fsRead(path, ...args); };
  let stats;
  try { stats = await new Promise((done, fail) => compiler.run((error, value) => error ? fail(error) : done(value))); }
  finally { await new Promise((done, fail) => compiler.close(error => error ? fail(error) : done())); }
  const summary = stats.toJson({ all: false, errors: true, warnings: true });
  save("compile.json", { error_count: summary.errors?.length || 0, warning_count: summary.warnings?.length || 0 });
  check("fixture_bundle", !stats.hasErrors());
  [...stats.compilation.fileDependencies].filter(path => existsSync(path) && lstatSync(path).isFile()).forEach(pin);
  Object.keys(require.cache).forEach(pin);
  const missingInputs = [...new Set([...stats.compilation.missingDependencies].filter(path => !existsSync(path)).concat(virtualEntry))].sort();
  check("prepare_sources_stable", equal(snapshot(Object.keys(pinned)), pinned));
  check("prepare_runtimes_stable", equal(tree(playwrightRoot), runtime.playwright) && equal(tree(browserRoot), runtime.browser));
  const inputs = { ...pinned, ...snapshot(["fixture.js", "typecheck.json", "compile.json"].map(name => resolve(output, name))) };
  save("prepare.json", { schema, mode: "component", selection, output, node: realpathSync(process.execPath), origin, inputs, missing_inputs: missingInputs, runtime,
    virtual_fixture: { path_not_written: virtualEntry, bytes: Buffer.byteLength(source), sha256: sha(source), source_in_script: true },
    source: { toast, css, mobile_css: mobileCss, icons, baseline_icons_resolution: archived ? "exact live icons dependency pinned; archived Provider and CSS unchanged" : null },
    scope: archived ? "archived-baseline real original ToastProvider/CSS; independently record three old defects; entire result remains failed" : "real live ToastProvider and CSS in synthetic component document; separate from production Workbench",
    browser: { playwright: "1.63.0", chromium_revision: "1243", headless: true, test_timeout_ms: 240000, close_timeout_ms: 10000 },
    clock: "Playwright Clock controls performance/timers; wrappers observe and expose cleared callbacks for explicitly synthetic queued-callback races; no product scheduler copy",
    visibility: "synthetic document visibilityState/hidden properties plus visibilitychange; actual browser hidden/restore NOT VERIFIED",
    native_flag: "synthetic flag with exact real mobile CSS loaded only in native fixture contexts; real IME/safe-area/device NOT VERIFIED",
    no_http_service: true, no_api_sqlite_provider: true, real_workbench_verified: false, real_native_verified: false });
  console.log(JSON.stringify({ prepared_not_launched: true, output, selection, prepare_sha256: file(resolve(output, "prepare.json")).sha256,
    input_count: Object.keys(inputs).length, type_errors: 0, bundle_errors: 0 }));
}

// Installed after Playwright Clock, before the real component bundle. Wrappers
// delegate all scheduling. They never implement a replacement timer algorithm.
function instrumentation({ hidden }) {
  const timers = new Map(), frames = new Map(), observers = [], listeners = [];
  const nativeSet = window.setTimeout.bind(window), nativeClear = window.clearTimeout.bind(window);
  const nativeFrame = window.requestAnimationFrame.bind(window), nativeCancel = window.cancelAnimationFrame.bind(window);
  const observed = { timer_created: 0, timer_cleared: 0, timer_fired: 0, stale_invocations: [], visibility_events: [], maximum_active_timers: 0,
    native_initial_visibility: document.visibilityState, visibility_mode: "synthetic_property_override", frame_created: 0, frame_cancelled: 0, frame_fired: 0 };
  window.setTimeout = (callback, delay = 0, ...args) => {
    let id;
    const entry = { id: null, callback, args, delay: Number(delay), created: performance.now(), due: performance.now() + Number(delay), active: true, status: "active" };
    id = nativeSet(() => { entry.active = false; entry.status = "fired"; observed.timer_fired++; if (typeof callback === "function") callback(...args); else throw Error("string_timeout_not_supported"); }, delay);
    entry.id = id; timers.set(id, entry); observed.timer_created++;
    observed.maximum_active_timers = Math.max(observed.maximum_active_timers, [...timers.values()].filter(value => value.active).length);
    return id;
  };
  window.clearTimeout = id => { const entry = timers.get(id); if (entry?.active) { entry.active = false; entry.status = "cleared"; observed.timer_cleared++; } return nativeClear(id); };
  window.requestAnimationFrame = callback => { let id; id = nativeFrame(time => { frames.delete(id); observed.frame_fired++; callback(time); }); frames.set(id, true); observed.frame_created++; return id; };
  window.cancelAnimationFrame = id => { if (frames.delete(id)) observed.frame_cancelled++; return nativeCancel(id); };
  for (const name of ["ResizeObserver", "MutationObserver"]) {
    const Original = window[name];
    window[name] = class extends Original {
      constructor(callback) { super(callback); this.entry = { kind: name, targets: new Set() }; observers.push(this.entry); }
      observe(target, options) { const result = super.observe(target, options); this.entry.targets.add(target); return result; }
      unobserve(target) { this.entry.targets.delete(target); return super.unobserve(target); }
      disconnect() { const result = super.disconnect(); this.entry.targets.clear(); return result; }
    };
  }
  for (const target of [document, window]) {
    const add = target.addEventListener.bind(target), remove = target.removeEventListener.bind(target);
    const capture = options => typeof options === "boolean" ? options : !!options?.capture;
    target.addEventListener = (type, callback, options) => {
      if (["visibilitychange", "resize", "pageshow", "pagehide"].includes(type) && callback
        && !listeners.some(entry => entry.active && entry.target === target && entry.type === type && entry.callback === callback && entry.capture === capture(options)))
        listeners.push({ target, type, callback, capture: capture(options), active: true });
      return add(type, callback, options);
    };
    target.removeEventListener = (type, callback, options) => {
      for (const entry of listeners) if (entry.target === target && entry.type === type && entry.callback === callback && entry.capture === capture(options)) entry.active = false;
      return remove(type, callback, options);
    };
  }
  let isHidden = !!hidden;
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => isHidden ? "hidden" : "visible" });
  Object.defineProperty(document, "hidden", { configurable: true, get: () => isHidden });
  window.toastInstrumentation = {
    snapshot: () => ({ ...observed, now: performance.now(), hidden: document.hidden, active_timers: [...timers.values()].filter(value => value.active).map(({ id, delay, created, due }) => ({ id, delay, created, due })),
      timers: [...timers.values()].map(({ id, delay, created, due, active, status }) => ({ id, delay, created, due, active, status })), active_frames: frames.size,
      active_observers: observers.filter(entry => entry.targets.size > 0).map(entry => ({ kind: entry.kind, targets: entry.targets.size })),
      active_listeners: listeners.filter(entry => entry.active).map(entry => ({ target: entry.target === document ? "document" : "window", type: entry.type })) }),
    visibility: value => { isHidden = value; observed.visibility_events.push({ synthetic: true, hidden: value, time: performance.now() }); document.dispatchEvent(new Event("visibilitychange")); },
    fireStale: id => { const entry = timers.get(id); if (!entry || entry.active || typeof entry.callback !== "function") throw Error("only_inactive_observed_callback_allowed"); observed.stale_invocations.push({ id, status: entry.status, synthetic_queued_callback: true }); entry.callback(...entry.args); },
  };
}

async function run() {
  check("regular_output", lstatSync(output).isDirectory() && !lstatSync(output).isSymbolicLink());
  check("reviewed_prepare", /^[a-f0-9]{64}$/.test(selection || "") && file(resolve(output, "prepare.json")).sha256 === selection);
  const prepared = JSON.parse(readFileSync(resolve(output, "prepare.json"), "utf8"));
  check("prepared_identity", prepared.schema === schema && prepared.mode === "component" && ["live", "archived-baseline"].includes(prepared.selection)
    && prepared.output === output && prepared.origin === origin && prepared.node === realpathSync(process.execPath));
  check("prepared_inputs", equal(snapshot(Object.keys(prepared.inputs)), prepared.inputs));
  check("prepared_missing_inputs", prepared.missing_inputs.every(path => !existsSync(path)));
  check("single_use_run", !existsSync(resolve(output, "result.json")) && !existsSync(resolve(output, "runtime")));
  receipt = { schema, mode: "component", selection: prepared.selection, state: "running", scope: prepared.scope, started_utc: new Date().toISOString(),
    prepare_sha256: selection, checks: [], observations: [], baseline_requirements: [], screenshots: [], teardown: [],
    unexpected_requests: [], request_failures: [], page_errors: [], console_errors: [], cleanup_failures: [],
    browser: { playwright: "1.63.0", chromium_revision: "1243", headless: true, forced_kill_requested: false }, browser_generated_sidecars: [],
    browser_generated_sidecar_policy: "Private browser only: exact chrome-headless-shell-win64/debug.log or chrome-headless-shell-win64/chrome-headless-shell.YYYYMMDD-HHMMSS-mmm.log; regular non-symlink; 1..1048576 bytes each; at most 4 combined; bytes/hash preserved",
    visibility_evidence: "synthetic document property override plus visibilitychange; real browser hidden/restore not verified",
    clock_evidence: prepared.clock, native_flag_evidence: prepared.native_flag, visual_review: "screenshots require Root inspection; no automatic visual acceptance",
    no_http_service: true, api_sqlite_provider_calls: 0, real_workbench_verified: false, real_native_verified: false,
    real_safe_area_verified: false, real_ime_verified: false, screen_reader_verified: false, complete_wcag_verified: false,
    not_covered: ["production Workbench business HTTP/focus/state acceptance on a fresh build", "actual Page Visibility hidden/restore and browser suspension",
      "real device IME, safe-area, rotation, touch/assistive technology", "production SSR/hydration", "a second internal focus target: current toast markup contains only one focusable close control"] };
  let timedOut = false;
  const persist = () => save("result.json", receipt);
  const checked = name => { check("suite_active", !timedOut); receipt.checks.push(name); persist(); };
  const observe = (scenario, value) => { receipt.observations.push({ scenario, ...value }); persist(); return value; };
  persist();
  let browserServer, browserProcess, browser, deadline;
  const privatePlaywright = resolve(output, "runtime/playwright-core"), privateBrowser = resolve(output, "runtime/chromium_headless_shell-1243");
  const contexts = new Set();
  try {
    stage = "private_runtime_copy";
    for (const name of ["runtime", "tmp", "downloads"]) mkdirSync(resolve(output, name));
    check("source_runtimes_pinned", equal(tree(playwrightRoot), prepared.runtime.playwright) && equal(tree(browserRoot), prepared.runtime.browser));
    check("copied_runtime_sources", equal(tree(playwrightRoot, privatePlaywright), prepared.runtime.playwright) && equal(tree(browserRoot, privateBrowser), prepared.runtime.browser));
    check("private_runtimes_pinned", equal(tree(privatePlaywright), prepared.runtime.playwright) && equal(tree(privateBrowser), prepared.runtime.browser));
    const { chromium } = await import(pathToFileURL(resolve(privatePlaywright, "index.mjs")).href);
    stage = "browser_start";
    const privateTemp = resolve(output, "tmp");
    browserServer = await chromium.launchServer({ executablePath: resolve(privateBrowser, browserExe), headless: true, host: "127.0.0.1", port: 0,
      artifactsDir: privateTemp, downloadsPath: resolve(output, "downloads"), timeout: 20000,
      env: { ...process.env, TEMP: privateTemp, TMP: privateTemp, TMPDIR: privateTemp },
      args: ["--no-first-run", "--disable-background-networking", "--disable-breakpad", "--disable-crash-reporter", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"] });
    browserProcess = browserServer.process(); receipt.browser.pid = browserProcess.pid;
    browserServer.once("close", () => { receipt.browser.server_close_observed = true; });
    browserProcess.once("exit", (code, signal) => { receipt.browser.exit_code = code; receipt.browser.exit_signal = signal; });
    browser = await chromium.connect(browserServer.wsEndpoint());
    const fixtureJs = readFileSync(resolve(output, "fixture.js")), fixtureCss = readFileSync(prepared.source.css), mobileCss = readFileSync(prepared.source.mobile_css);
    const html = native => `<!doctype html><html lang="zh-CN" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/fixture.css">${native ? '<link rel="stylesheet" href="/mobile.css">' : ""}<title>Toast component QA</title><style>.qa-fields{display:grid;gap:12px;max-width:360px}.qa-fields label{display:block}.qa-fields input:not([type=checkbox]),.qa-fields select{display:block;min-height:44px;width:100%;max-width:100%}.qa-spacer{height:1200px}#end-action{min-height:44px;max-width:100%}</style></head><body><div id="root"></div></body></html>`;
    const tick = (page, ms) => page.clock.runFor(ms);
    const metrics = page => page.evaluate(() => window.toastInstrumentation.snapshot());
    const texts = page => page.locator(".toast-text").allTextContents();
    const show = (page, text, kind) => page.evaluate(({ text, kind }) => window.toastQA.show(text, kind), { text, kind });
    const visibility = (page, hidden) => page.evaluate(value => window.toastInstrumentation.visibility(value), hidden);
    const shoot = async (page, name) => { await page.screenshot({ path: resolve(output, name), animations: "disabled" }); receipt.screenshots.push(name); persist(); };
    const fresh = async (config = {}) => {
      check("suite_active", !timedOut);
      const options = { width: 390, height: 844, nav: true, tray: false, native: false, theme: "light", hidden: false, touch: false, ...config };
      const context = await browser.newContext({ serviceWorkers: "block", colorScheme: options.theme === "light" ? "light" : "dark",
        viewport: { width: options.width, height: options.height }, hasTouch: options.touch, isMobile: options.touch }); contexts.add(context);
      await context.routeWebSocket("**/*", socket => { receipt.unexpected_requests.push({ kind: "blocked_websocket" }); socket.close(); });
      await context.route("**/*", async route => {
        const request = route.request(), url = new URL(request.url());
        if (request.method() === "GET" && url.origin === origin && !url.search && !url.hash) {
          if (url.pathname === "/") { await route.fulfill({ contentType: "text/html; charset=utf-8", body: html(options.native) }); return; }
          if (url.pathname === "/fixture.js") { await route.fulfill({ contentType: "text/javascript; charset=utf-8", body: fixtureJs }); return; }
          if (url.pathname === "/fixture.css") { await route.fulfill({ contentType: "text/css; charset=utf-8", body: fixtureCss }); return; }
          if (options.native && url.pathname === "/mobile.css") { await route.fulfill({ contentType: "text/css; charset=utf-8", body: mobileCss }); return; }
          if (url.pathname === "/favicon.ico") { await route.fulfill({ status: 204 }); return; }
        }
        receipt.unexpected_requests.push({ method: ["GET", "POST"].includes(request.method()) ? request.method() : "other", origin: url.origin === origin ? "fixture" : "other", route: "blocked" });
        await route.abort();
      });
      const page = await context.newPage(); page.setDefaultTimeout(7000);
      page.on("pageerror", error => receipt.page_errors.push(["TypeError", "SyntaxError"].includes(error.name) ? error.name : "PageError"));
      page.on("console", event => { if (event.type() === "error") receipt.console_errors.push("browser_console_error"); });
      page.on("requestfailed", request => receipt.request_failures.push({ method: request.method(), origin: new URL(request.url()).origin === origin ? "fixture" : "other" }));
      await page.clock.install({ time: new Date("2026-10-23T00:00:00Z") });
      await page.goto(origin, { waitUntil: "load" });
      // The document has no product script yet; pause before mounting the Provider.
      await page.clock.pauseAt(new Date("2026-10-23T01:00:00Z"));
      // addScriptTag creates a main-world ElementHandle whose preview lazily
      // installs Playwright's document observer. Initialize it before observing
      // product resources; the following same-world evaluation is a barrier.
      // No Provider is mounted yet, and the zero-resource teardown gate remains.
      const bootstrap = await page.addScriptTag({ content: "/* R128 automation bootstrap before resource observation */" });
      await bootstrap.evaluate(node => node.remove()); await bootstrap.dispose();
      await page.evaluate(instrumentation, { hidden: options.hidden });
      await page.evaluate(value => { window.toastOptions = value; document.documentElement.dataset.theme = value.theme; }, options);
      await page.addScriptTag({ url: origin + "/fixture.js" }); await tick(page, 32);
      check("real_provider_fixture_ready", await page.evaluate(() => typeof window.toastQA?.show === "function"));
      if (options.nav) check("fixture_unicode_navigation_exact", equal(await page.locator(".mobile-nav button span").allTextContents(), ["查询", "关注", "比较", "资料", "价格", "模型", "设置"]));
      if (prepared.selection === "live") check("live_real_layout_hook", await page.evaluate(() => window.toastQA.hasLayoutHook === true));
      const close = async (label = "component") => {
        await page.evaluate(() => window.toastQA.unmount());
        const before = await metrics(page);
        observe(label + "_unmount", before);
        const released = before.active_timers.length === 0 && before.active_frames === 0 && before.active_listeners.length === 0 && before.active_observers.length === 0;
        receipt.teardown.push({ scenario: label, released, ...before }); persist();
        check("provider_resources_released", released);
        await tick(page, 10000);
        check("released_provider_stays_empty", await page.locator(".toast").count() === 0 && (await metrics(page)).active_timers.length === 0);
        await context.close(); contexts.delete(context);
      };
      return { page, context, close, options };
    };

    const baseline = async () => {
      stage = "archived_baseline_three_independent_defects";
      const target = await fresh(), page = target.page;
      await show(page, "归档原组件：关闭目标"); await tick(page, 240);
      const rect = await page.locator(".toast-close").evaluate(node => { const box = node.getBoundingClientRect(); return { width: box.width, height: box.height }; });
      receipt.baseline_requirements.push({ requirement: "close_target_at_least_44", satisfied: rect.width >= 44 && rect.height >= 44, observed: rect }); persist();
      await page.locator(".toast-close").click({ force: true });
      await show(page, "归档原组件：hover 与 focus 暂停"); await tick(page, 4200);
      await page.locator(".toast").hover({ force: true }); await page.locator(".toast-close").focus(); await tick(page, 800);
      receipt.baseline_requirements.push({ requirement: "hover_focus_survives_original_deadline", satisfied: await page.locator(".toast").count() === 1,
        observed: { visible: await texts(page), synthetic_elapsed_since_show_ms: 5000 } }); persist();
      await page.mouse.move(0, 0); await page.locator("#retained-input").focus();
      for (const text of ["baseline-A", "baseline-B", "baseline-C"]) await show(page, text);
      const first = (await metrics(page)).active_timers[0]?.id;
      await show(page, "baseline-D");
      const after = await metrics(page), visible = await texts(page);
      receipt.baseline_requirements.push({ requirement: "eviction_immediately_clears_old_timer", satisfied: !!first && !after.active_timers.some(item => item.id === first),
        observed: { visible, active_timer_count: after.active_timers.length, evicted_timer_still_active: after.active_timers.some(item => item.id === first) } }); persist();
      await shoot(page, "archived-baseline.png"); await target.close("archived_baseline");
      // This mode never produces a green baseline, including if an input was
      // unexpectedly repaired. Failures are evidence, not expected-pass aliases.
      receipt.baseline_defect_count = receipt.baseline_requirements.filter(item => !item.satisfied).length;
      persist(); check("archived_baseline_is_not_live_acceptance", false);
    };

    const lifecycle = async () => {
      stage = "lifetime_trim_strictmode";
      let current = await fresh(), page = current.page;
      await page.locator("#retained-input").focus();
      await show(page, "   "); check("empty_trim_does_not_add", await page.locator(".toast").count() === 0);
      await show(page, "  lifetime-A  ");
      let state = await metrics(page); observe(stage, state);
      check("trim_role_no_autofocus_one_timer", equal(await texts(page), ["lifetime-A"]) && await page.locator('.toast[role="status"]').count() === 1
        && state.active_timers.length === 1 && await page.locator("#retained-input").evaluate(node => document.activeElement === node));
      check("strict_item_effect_replay_clears_prior_timer", state.timer_created >= 2 && state.timer_cleared >= 1 && state.active_timers[0].delay === 4600);
      const replay = state.timers.find(item => item.status === "cleared");
      await page.evaluate(id => window.toastInstrumentation.fireStale(id), replay.id);
      check("strict_cleanup_callback_cannot_remove_current_item", await page.locator(".toast").count() === 1 && (await metrics(page)).active_timers.length === 1);
      await tick(page, 4599); check("full_lifetime_not_early", await page.locator(".toast").count() === 1);
      await tick(page, 1); check("full_lifetime_expires_at_remaining_boundary", await page.locator(".toast").count() === 0);
      await current.close(stage); checked("trim_full_lifetime_strict_replay_and_stale_callback");

      for (const reason of ["hover", "focus"]) {
        stage = reason + "_remaining_and_queued_callback"; current = await fresh(); page = current.page;
        await page.locator("#retained-input").focus(); await show(page, reason + "-remaining"); await tick(page, 4200);
        const prior = (await metrics(page)).active_timers[0].id;
        if (reason === "hover") await page.locator(".toast").hover({ force: true }); else await page.locator(".toast-close").focus();
        check("single_reason_clears_timer", (await metrics(page)).active_timers.length === 0);
        await page.evaluate(id => window.toastInstrumentation.fireStale(id), prior); await tick(page, 8000);
        check("paused_old_callback_cannot_expire", await page.locator(".toast").count() === 1);
        if (reason === "hover") await page.mouse.move(0, 0); else await page.locator("#retained-input").focus();
        state = await metrics(page); observe(stage, state);
        check("resume_only_remaining_400", state.active_timers.length === 1 && Math.abs(state.active_timers[0].delay - 400) <= 0.01);
        await tick(page, 399); check("remaining_not_early", await page.locator(".toast").count() === 1);
        await tick(page, 1); check("remaining_not_reset_to_full", await page.locator(".toast").count() === 0);
        await current.close(stage); checked(reason + "_pause_remaining_queued_callback");
      }
      for (const order of ["hover_focus_hidden", "hidden_focus_hover"]) {
        stage = "overlap_" + order; current = await fresh(); page = current.page;
        await show(page, order); await tick(page, 4000);
        if (order === "hover_focus_hidden") { await page.locator(".toast").hover({ force: true }); await page.locator(".toast-close").focus(); await visibility(page, true); }
        else { await visibility(page, true); await page.locator(".toast-close").focus(); await page.locator(".toast").hover({ force: true }); }
        check("three_reasons_have_no_timer", (await metrics(page)).active_timers.length === 0); await tick(page, 9000);
        if (order === "hover_focus_hidden") { await page.mouse.move(0, 0); await page.locator("#retained-input").focus(); }
        else { await visibility(page, false); await page.locator("#retained-input").focus(); }
        await tick(page, 9000); check("last_reason_still_pauses", (await metrics(page)).active_timers.length === 0 && await page.locator(".toast").count() === 1);
        if (order === "hover_focus_hidden") await visibility(page, false); else await page.mouse.move(0, 0);
        state = await metrics(page); observe(stage, state);
        check("overlap_deducts_once_remaining_600", state.active_timers.length === 1 && Math.abs(state.active_timers[0].delay - 600) <= 0.01);
        await tick(page, 599); check("overlap_remaining_not_early", await page.locator(".toast").count() === 1);
        await tick(page, 1); check("overlap_remaining_expires", await page.locator(".toast").count() === 0);
        await current.close(stage); checked(stage + "_synthetic_visibility");
      }
      stage = "initial_synthetic_hidden_and_remount"; current = await fresh({ hidden: true }); page = current.page;
      await show(page, "hidden-created"); state = await metrics(page); observe(stage, state);
      check("hidden_created_strict_item_starts_no_timer", state.active_timers.length === 0);
      await tick(page, 12000); check("hidden_created_full_lifetime_preserved", await page.locator(".toast").count() === 1);
      await visibility(page, false); check("hidden_created_visible_starts_full_4600", (await metrics(page)).active_timers[0]?.delay === 4600);
      await tick(page, 4599); check("hidden_created_not_early", await page.locator(".toast").count() === 1);
      await tick(page, 1); check("hidden_created_expires", await page.locator(".toast").count() === 0);
      await show(page, "unmount-active"); const old = (await metrics(page)).active_timers[0].id;
      await page.evaluate(() => window.toastQA.unmount()); state = await metrics(page);
      check("unmount_clears_all_observed_resources", state.active_timers.length === 0 && state.active_frames === 0 && state.active_observers.length === 0 && state.active_listeners.length === 0);
      await page.evaluate(() => window.toastQA.mount()); await tick(page, 32); await show(page, "remounted-new");
      await page.evaluate(id => window.toastInstrumentation.fireStale(id), old);
      check("old_unmounted_callback_cannot_remove_remounted_provider", equal(await texts(page), ["remounted-new"]) && (await metrics(page)).active_timers.length === 1);
      await current.close(stage); checked("initial_hidden_full_lifetime_unmount_remount_resources");

      stage = "touch_no_permanent_hover"; current = await fresh({ touch: true }); page = current.page;
      await show(page, "touch-lifetime"); await tick(page, 240); await page.locator(".toast-text").tap({ force: true });
      check("touch_does_not_pause_hover", (await metrics(page)).active_timers.length === 1);
      await tick(page, 4360); check("touch_lifetime_expires", await page.locator(".toast").count() === 0);
      await current.close(stage); checked("emulated_touch_does_not_leave_hover");
    };

    const focusAndCapacity = async () => {
      stage = "capacity_real_focus_and_immediate_timer_release";
      let current = await fresh(), page = current.page;
      await page.locator("#retained-input").focus();
      const ids = [];
      for (const text of ["capacity-A", "capacity-B", "capacity-C"]) { await show(page, text); ids.push((await metrics(page)).active_timers.at(-1).id); }
      await page.locator(".toast-close").first().focus(); await show(page, "capacity-D");
      let state = await metrics(page); observe(stage, state);
      check("fourth_protects_actual_focus_and_evicts_oldest_nonfocused", equal(await texts(page), ["capacity-A", "capacity-C", "capacity-D"])
        && await page.locator(".toast").first().evaluate(node => node.contains(document.activeElement)) && state.active_timers.length === 2);
      check("evicted_timer_released_immediately", !state.active_timers.some(item => item.id === ids[1]));
      await page.evaluate(id => window.toastInstrumentation.fireStale(id), ids[1]);
      check("evicted_queued_callback_cannot_remove_other_item", equal(await texts(page), ["capacity-A", "capacity-C", "capacity-D"]));
      await page.locator("#retained-input").focus(); await show(page, "capacity-E");
      check("old_focus_marker_does_not_protect_after_focus_left", equal(await texts(page), ["capacity-C", "capacity-D", "capacity-E"]) && (await metrics(page)).active_timers.length === 3);
      await current.close(stage); checked("capacity_actual_focus_eviction_release_and_queued_callback");

      stage = "synthetic_react_event_show_then_focus_before_commit"; current = await fresh(); page = current.page;
      for (const text of ["event-order-A", "event-order-B", "event-order-C"]) await show(page, text);
      await page.locator("#retained-input").focus();
      // A real React onClick directly calls show (without the fixture flushSync
      // command), then focuses the still-connected oldest close in that event.
      await page.evaluate(() => document.querySelector("#qa-event-order").click()); await tick(page, 0);
      const eventTexts = await texts(page); observe(stage, { synthetic_event_order_stress: true, visible: eventTexts });
      check("event_batched_new_focus_not_evicted_at_commit", eventTexts.length === 3 && eventTexts.includes("event-order-A") && eventTexts.includes("event-order-D")
        && await page.locator(".toast").filter({ hasText: "event-order-A" }).evaluate(node => node.contains(document.activeElement)));
      await current.close(stage); checked("synthetic_react_event_show_fourth_then_focus_oldest_before_commit");

      stage = "synthetic_neighbor_focus_handler_reentrant_show"; current = await fresh(); page = current.page;
      await page.locator("#retained-input").focus(); await show(page, "reentrant-A"); await show(page, "reentrant-B");
      await page.locator(".toast-close").first().focus();
      await page.evaluate(() => { const neighbor = document.querySelectorAll(".toast-close")[1]; neighbor.addEventListener("focus", () => window.toastQA.rawShow("reentrant-new"), { once: true }); });
      await page.locator(".toast-close").first().press("Enter"); await tick(page, 0);
      const reentrantTexts = await texts(page); observe(stage, { synthetic_event_order_stress: true, visible: reentrantTexts });
      check("outer_dismiss_keeps_reentrant_new_item_and_never_revives_removed", equal(reentrantTexts, ["reentrant-B", "reentrant-new"])
        && await page.locator(".toast").first().evaluate(node => node.contains(document.activeElement)));
      await current.close(stage); checked("synthetic_neighbor_focus_reentrant_show_survives_outer_dismiss");

      stage = "manual_close_neighbors_external_origin_and_main"; current = await fresh(); page = current.page;
      await page.locator("#retained-input").focus();
      for (const text of ["close-A", "close-B", "close-C"]) await show(page, text);
      await page.locator(".toast-close").nth(1).focus(); await page.locator(".toast-close").nth(1).press("Enter");
      check("keyboard_close_moves_to_surviving_neighbor", await page.evaluate(() => document.activeElement?.matches(".toast-close") && document.activeElement.isConnected) && await page.locator(".toast").count() === 2);
      while (await page.locator(".toast").count()) await page.locator(".toast-close:focus").press("Enter");
      check("last_close_returns_to_connected_external_origin", await page.locator("#retained-input").evaluate(node => document.activeElement === node));
      await show(page, "external-focus-close"); const old = (await metrics(page)).active_timers[0].id;
      await page.evaluate(() => document.querySelector(".toast-close").click());
      await page.evaluate(id => window.toastInstrumentation.fireStale(id), old);
      check("external_new_focus_not_stolen_by_programmatic_close_or_stale_callback", await page.locator("#retained-input").evaluate(node => document.activeElement === node));
      await show(page, "missing-origin-main-fallback"); await page.locator(".toast-close").focus();
      await page.evaluate(() => window.toastQA.configure({ originPresent: false })); await page.locator(".toast-close").press("Enter");
      check("disconnected_origin_uses_registered_main", await page.locator("#main-content").evaluate(node => document.activeElement === node));
      await current.close(stage); checked("keyboard_close_neighbors_origin_main_and_external_focus");
    };

    const geometry = page => page.evaluate(() => {
      const box = node => { if (!node || getComputedStyle(node).display === "none" || !node.getClientRects().length) return null; const r = node.getBoundingClientRect(); return { top: r.top, right: r.right, bottom: r.bottom, left: r.left, width: r.width, height: r.height }; };
      const stack = document.querySelector(".toast-stack"), nav = document.querySelector(".mobile-nav"), tray = document.querySelector(".comparison-tray");
      const probe = document.createElement("div"); probe.style.cssText = "position:fixed;visibility:hidden;pointer-events:none;padding-bottom:env(safe-area-inset-bottom)"; document.body.append(probe);
      const safe = parseFloat(getComputedStyle(probe).paddingBottom) || 0; probe.remove();
      const shell = document.querySelector(".app-shell"), wrapper = document.querySelector(".toast-layout"), H = document.documentElement.clientHeight;
      const N = box(nav)?.height || 0, T = stack?.querySelector(".toast") ? box(stack)?.height || 0 : 0, C = box(tray)?.height || 0;
      const narrow = matchMedia("(max-width:767px)").matches, nativeKeyboard = !!document.querySelector(".mobile-native-root") && document.documentElement.dataset.keyboardOpen === "true";
      const b = N > 0 ? N + 8 : narrow ? (nativeKeyboard ? 12 : 12 + safe) : 20;
      const O = T > 0 || C > 0 ? b + T + C + (T > 0 && C > 0 ? 8 : 0) + 8 : N > 0 ? N + 8 : narrow ? (nativeKeyboard ? 12 : 12 + safe) : 0;
      const close = [...document.querySelectorAll(".toast-close")].map(button => { const r = box(button), hit = r ? document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) : null; return { ...r, center_hit: !!hit && button.contains(hit) }; });
      const end = document.querySelector("#end-action"), endRect = box(end), endHit = endRect && document.elementFromPoint(endRect.left + endRect.width / 2, endRect.top + endRect.height / 2);
      const scrollports = [...document.querySelectorAll(".toast-stack,.toast,.toast-text")].filter(node => ["auto", "scroll"].includes(getComputedStyle(node).overflowY) && node.scrollHeight > node.clientHeight + 1);
      return { H, width: document.documentElement.clientWidth, scroll_width: document.documentElement.scrollWidth, N, T, C, safe_area: safe, b, O,
        budget: H - b - C - (C > 0 ? 8 : 0) - 44 - 8, nav: box(nav), stack: T ? box(stack) : null, tray: box(tray), close,
        shell_padding_bottom: parseFloat(getComputedStyle(shell).paddingBottom), local_variables: wrapper ? Object.fromEntries(["--toast-base-bottom", "--toast-tray-bottom", "--toast-content-offset", "--toast-stack-max-height"].map(name => [name, getComputedStyle(wrapper).getPropertyValue(name).trim()])) : null,
        end: endRect, end_center_hit: !!endHit && end.contains(endHit), scrollports: scrollports.length, stack_scroll_height: stack?.scrollHeight || 0,
        stack_client_height: stack?.clientHeight || 0, stack_scroll_top: stack?.scrollTop || 0, outer_scroll_y: scrollY, native_keyboard: nativeKeyboard };
    });
    const assertGeometry = async (page, name, operate = true) => {
      // Playwright Clock controls JS timers, not the CSS animation timeline.
      // Observe the default entry animation after its natural completion.
      await page.locator(".toast").evaluateAll(nodes => Promise.all(nodes.flatMap(node => node.getAnimations().map(animation => animation.finished))));
      let value = await geometry(page); observe(name, value);
      const near = (a, b) => Math.abs(a - b) <= 1.1;
      check("no_horizontal_overflow", value.scroll_width <= value.width + 1);
      check("body_uses_same_total_occupancy", near(value.shell_padding_bottom, value.O));
      if (value.T) {
        check("toast_fixed_bottom_matches_measured_base", near(value.H - value.stack.bottom, value.b));
        check("toast_respects_available_height_budget", value.T <= value.budget + 1.1 && value.budget >= 44);
        check("close_rects_at_least_44", value.close.every(item => item.width >= 43.99 && item.height >= 43.99));
      }
      if (value.C) check("tray_above_current_toast_or_base", near(value.H - value.tray.bottom, value.T > 0 ? value.b + value.T + 8 : value.b) && value.tray.top >= 0);
      if (value.N && value.T) check("nav_toast_gap_is_8", near(value.nav.top - value.stack.bottom, 8));
      if (value.C && value.T) check("toast_tray_gap_is_8", near(value.stack.top - value.tray.bottom, 8));
      if (operate) {
        await page.evaluate(() => document.querySelector("#end-action").scrollIntoView({ block: "end", behavior: "instant" })); await tick(page, 64);
        observe(name + "_initial_end_alignment_diagnostic", await geometry(page));
        // The contract is reachable content. A user's further document scroll
        // is separate from scrollIntoView's alignment with the viewport edge.
        // Use actual target/layer rects, without changing CSS or target layout.
        const requested = await page.evaluate(() => {
          const scroller = document.scrollingElement, end = document.querySelector("#end-action");
          if (!scroller || !end) throw Error("end_scroll_target_missing");
          const layers = [...document.querySelectorAll(".mobile-nav,.toast-stack,.comparison-tray")]
            .filter(node => node.getClientRects().length && node.getBoundingClientRect().height > 0);
          const upper = Math.min(document.documentElement.clientHeight, ...layers.map(node => node.getBoundingClientRect().top));
          const before = scroller.scrollTop, maximum = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
          const delta = Math.max(0, end.getBoundingClientRect().bottom - (upper - (layers.length ? 8 : 0)));
          const target = before + delta;
          // scrollTop uses CSS scroll-behavior:auto, which resolves to the
          // product's smooth preference. Request instant movement explicitly.
          window.scrollTo({ top: target, behavior: "instant" });
          return { before, delta, requested: target, maximum_before: maximum, actual_immediate: scroller.scrollTop, method: "explicit_document_scroll_from_observed_rects" };
        });
        await tick(page, 64);
        const settledScroll = () => page.evaluate(() => { const node = document.scrollingElement; return {
          actual: node.scrollTop, maximum: Math.max(0, node.scrollHeight - node.clientHeight) }; });
        const first = await settledScroll(); await tick(page, 32); const second = await settledScroll();
        observe(name + "_explicit_document_scroll", { ...requested, first, second });
        check("end_operation_document_scroll_is_reachable_and_settled", requested.requested >= 0 && requested.requested <= second.maximum + 1.1
          && near(second.actual, requested.requested) && near(first.actual, second.actual) && near(first.maximum, second.maximum));
        value = await geometry(page); observe(name + "_end_operation", value);
        const upper = Math.min(value.H, ...[value.nav, value.stack, value.tray].filter(Boolean).map(item => item.top));
        check("end_action_complete_above_fixed_layers", value.end.height >= 44 && value.end.top >= -0.1 && value.end.bottom <= upper - (value.N || value.T || value.C ? 7 : 0) + 1.1 && value.end_center_hit);
        await page.locator("#end-action").click({ force: true }); check("end_action_real_click_completed", await page.locator("#end-action").getAttribute("data-count") === "1");
      }
      return value;
    };
    const layout = async () => {
      stage = "viewport_layer_combinations";
      const cases = [];
      for (const [width, height] of [[1365, 900], [390, 844], [320, 844], [320, 420]])
        for (const [count, nav, tray] of [[0, false, false], [1, true, false], [1, false, true], [3, true, true]]) cases.push({ width, height, count, nav, tray });
      for (const [count, nav, tray] of [[3, false, false], [0, true, false], [0, false, true], [0, true, true]]) cases.push({ width: 320, height: 420, count, nav, tray });
      for (let index = 0; index < cases.length; index++) {
        const config = cases[index], current = await fresh(config), page = current.page;
        const name = `geometry-${config.width}-${config.height}-${config.count}-${Number(config.nav)}-${Number(config.tray)}`;
        for (let n = 0; n < config.count; n++) await show(page, `布局 ${n + 1} 长中文换行与 token-${"ABCDEF0123456789".repeat(8)}`, n === 2 ? "error" : "info");
        await tick(page, 240); await assertGeometry(page, name);
        if (config.width === 320 && config.height === 420 && config.count === 3 && config.nav && config.tray) await shoot(page, name + ".png");
        await current.close(name);
      }
      checked("four_viewports_single_three_empty_layers_measured_rect_hit_and_real_end_action");

      for (const font of [14, 22]) {
        stage = "single_long_text_short_viewport_" + font;
        const current = await fresh({ width: 320, height: 420, nav: true, tray: true }), page = current.page;
        await page.evaluate(value => { document.body.style.fontSize = value + "px"; }, font);
        const long = "完整长文须可滚读，关闭入口保持可达。".repeat(180) + "X".repeat(600);
        await show(page, long); await tick(page, 240);
        let value = await assertGeometry(page, stage); check("one_real_stack_scrollport", value.scrollports === 1 && value.stack_scroll_height > value.stack_client_height);
        await page.evaluate(() => { document.querySelector(".toast-stack").scrollTop = 0; }); await tick(page, 32);
        value = await geometry(page); check("long_item_initial_sticky_close_hit", value.close[0].center_hit);
        await page.evaluate(() => { const node = document.querySelector(".toast-stack"); node.scrollTop = node.scrollHeight - node.clientHeight; }); await tick(page, 32);
        value = await geometry(page); observe(stage + "_scroll_end", value);
        check("long_item_final_text_and_sticky_close_reachable", value.stack_scroll_top > 0 && value.close[0].center_hit
          && await page.locator(".toast-text").textContent() === long && await page.locator(".toast-text").evaluate(node => node.getBoundingClientRect().bottom <= node.closest(".toast-stack").getBoundingClientRect().bottom + 1.1));
        await shoot(page, stage + ".png");
        await page.locator(".toast-close").click({ force: true }); check("long_scrolled_item_close_operates", await page.locator(".toast").count() === 0);
        await current.close(stage);
      }
      checked("long_single_item_one_scrollport_sticky_44_close_complete_text_normal_large_font");

      stage = "short_stack_manual_close_neighbor_visibility";
      {
        const current = await fresh({ width: 320, height: 420, nav: true, tray: true }), page = current.page;
        for (const text of ["neighbor-A", "neighbor-B", "neighbor-C"]) await show(page, text + " 相邻提示长文滚读。".repeat(180));
        await tick(page, 240);
        const before = await page.evaluate(() => {
          const stack = document.querySelector(".toast-stack"); stack.scrollTop = 0;
          const button = stack.querySelector(".toast-close"), s = stack.getBoundingClientRect(), r = button.getBoundingClientRect();
          const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          // Do not ask a Locator to reveal/scroll the target. It is already
          // visible; native focus explicitly preserves both scroll positions.
          button.focus({ preventScroll: true });
          return { outer_scroll_y: scrollY, stack_scroll_top: stack.scrollTop, stack_client_height: stack.clientHeight, stack_scroll_height: stack.scrollHeight,
            overflow: stack.scrollHeight > stack.clientHeight + 1, close_visible: r.top >= s.top && r.bottom <= s.bottom && r.width >= 44 && r.height >= 44 && !!hit && button.contains(hit) };
        });
        observe(stage + "_before", before);
        check("three_long_items_overflow_with_current_close_already_visible", before.overflow && before.close_visible);
        await page.keyboard.press("Enter"); await tick(page, 64);
        const value = await page.evaluate(() => {
          const button = document.activeElement, stack = document.querySelector(".toast-stack"), s = stack.getBoundingClientRect(), r = button?.getBoundingClientRect();
          const hit = r && document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          return { focused_close: !!button?.matches(".toast-close"), connected: !!button?.isConnected, count: document.querySelectorAll(".toast").length,
            close: r ? { top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height } : null,
            stack: { top: s.top, bottom: s.bottom, left: s.left, right: s.right }, center_hit: !!hit && button.contains(hit), outer_scroll_y: scrollY, stack_scroll_top: stack.scrollTop };
        });
        observe(stage, { before, after: value }); await shoot(page, stage + ".png");
        check("manual_close_neighbor_focus_is_actually_visible_and_hit", value.focused_close && value.connected && value.count === 2 && value.center_hit
          && value.close.width >= 44 && value.close.height >= 44 && value.close.top >= value.stack.top - 0.1 && value.close.bottom <= value.stack.bottom + 0.1
          && value.close.left >= value.stack.left && value.close.right <= value.stack.right && Math.abs(value.outer_scroll_y - before.outer_scroll_y) <= 1);
        await current.close(stage);
      }
      checked("short_stack_manual_close_neighbor_real_focus_rect_and_hit");

      stage = "input_identity_and_dynamic_reflow";
      let current = await fresh({ tray: true }), page = current.page;
      await page.locator("#retained-input").focus();
      await page.evaluate(() => { const input = document.querySelector("#retained-input"); input.setSelectionRange(2, 9); window.retainedQA = { input, price: document.querySelector("#price-draft"), model: document.querySelector("#model-draft"), region: document.querySelector("#region-draft"), compared: document.querySelector("#compare-draft") }; window.scrollTo({ top: 180, behavior: "instant" }); });
      const assertRetained = async () => check("input_dom_value_selection_focus_and_choices_preserved", await page.evaluate(() => {
        const old = window.retainedQA, input = document.querySelector("#retained-input");
        return input === old.input && document.activeElement === input && input.value === "225/45 retained draft" && input.selectionStart === 2 && input.selectionEnd === 9
          && document.querySelector("#price-draft") === old.price && old.price.value === "123.45" && document.querySelector("#model-draft") === old.model && old.model.value === "model-b"
          && document.querySelector("#region-draft") === old.region && old.region.value === "US" && document.querySelector("#compare-draft") === old.compared && old.compared.checked;
      }));
      await show(page, "输入保全 " + "动态换行长内容".repeat(12)); await tick(page, 240); await assertRetained();
      check("toast_did_not_force_page_scroll", Math.abs(await page.evaluate(() => scrollY) - 180) <= 1);
      const withToast = await geometry(page);
      await page.setViewportSize({ width: 320, height: 844 }); await tick(page, 64); await assertRetained();
      await page.evaluate(() => window.toastQA.configure({ tray: false, nav: false, theme: "dark" })); await tick(page, 64); await assertRetained();
      await page.evaluate(() => document.querySelector(".toast-close").click()); await tick(page, 64); await assertRetained();
      const empty = await geometry(page); observe(stage, { with_toast: withToast, empty });
      check("removed_layers_release_occupancy", empty.T === 0 && empty.C === 0 && empty.N === 0 && Math.abs(empty.shell_padding_bottom - empty.O) <= 1.1 && empty.O < withToast.O);
      await current.close(stage); checked("synthetic_input_nodes_selection_choices_scroll_and_dynamic_occupancy_preserved");

      const settleNativeFlag = async (page, name, keyboardOpen, navigationHeight) => {
        // Native ResizeObserver delivery needs a real rendering opportunity;
        // its product callback then schedules a Clock-controlled animation frame.
        // Give both schedulers bounded turns, without invoking product measure.
        const realStart = performance.now(), virtualStart = (await metrics(page)).now;
        const polls = [], near = (a, b) => Math.abs(a - b) <= 1.1;
        let consecutive = 0, settled = false;
        for (let attempt = 1; attempt <= 25; attempt++) {
          await new Promise(resolve => setTimeout(resolve, 20)); // Node timer, outside page Clock.
          await tick(page, 32);
          const value = await geometry(page), state = await metrics(page);
          const local = value.local_variables || {};
          const matches = value.native_keyboard === keyboardOpen
            && (keyboardOpen ? value.N === 0 : value.N > 0 && near(value.N, navigationHeight))
            && near(value.shell_padding_bottom, value.O)
            && near(parseFloat(local["--toast-base-bottom"]), value.b)
            && near(parseFloat(local["--toast-tray-bottom"]), value.b + (value.T > 0 ? value.T + 8 : 0))
            && near(parseFloat(local["--toast-content-offset"]), value.O)
            && near(parseFloat(local["--toast-stack-max-height"]), value.budget)
            && state.active_frames === 0;
          consecutive = matches ? consecutive + 1 : 0;
          polls.push({ attempt, real_elapsed_ms: Math.round((performance.now() - realStart) * 100) / 100,
            virtual_elapsed_ms: state.now - virtualStart, matches, consecutive_matches: consecutive,
            active_frames: state.active_frames, frame_created: state.frame_created, frame_fired: state.frame_fired,
            native_keyboard: value.native_keyboard, N: value.N, b: value.b, T: value.T, C: value.C, O: value.O,
            shell_padding_bottom: value.shell_padding_bottom, local_variables: value.local_variables });
          if (consecutive >= 2) { settled = true; break; }
        }
        observe(name + "_render_settle", { settled, expected_keyboard_open: keyboardOpen, expected_visible_navigation_height: navigationHeight,
          required_consecutive_matches: 2, poll_limit: 25, real_yield_ms_per_poll: 20, virtual_step_ms_per_poll: 32,
          maximum_requested_real_wait_ms: 500, maximum_virtual_advance_ms: 800,
          requested_real_wait_ms: polls.length * 20, real_elapsed_ms: Math.round((performance.now() - realStart) * 100) / 100,
          virtual_elapsed_ms: polls.at(-1).virtual_elapsed_ms, polls });
        check("native_flag_render_settles_within_bound", settled);
      };

      stage = "real_mobile_css_synthetic_keyboard_flag"; current = await fresh({ native: true, tray: true }); page = current.page;
      for (const text of ["native-A", "native-B", "native-C"]) await show(page, text); await tick(page, 240);
      const visible = await geometry(page); check("mobile_css_loaded_nav_visible", visible.N > 0);
      await page.evaluate(() => { document.documentElement.dataset.keyboardOpen = "true"; });
      await settleNativeFlag(page, stage + "_open", true, visible.N);
      let value = await assertGeometry(page, stage + "_open"); check("native_flag_hides_navigation_and_base_12", value.N === 0 && value.b === 12 && value.native_keyboard);
      await page.evaluate(() => { document.documentElement.dataset.keyboardOpen = "false"; });
      await settleNativeFlag(page, stage + "_restored", false, visible.N);
      value = await assertGeometry(page, stage + "_restored", false); check("native_flag_restore_measures_real_nav_height", Math.abs(value.N - visible.N) <= 1.1);
      await shoot(page, stage + ".png"); await current.close(stage); checked("actual_mobile_css_flag_branch_only_not_real_ime");
    };

    const themes = async () => {
      stage = "themes_and_forced_colors";
      const current = await fresh({ width: 390, height: 844 }), page = current.page;
      await show(page, "主题提示：可见文本与关闭图标", "error"); await tick(page, 240);
      const rgb = value => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
      const luminance = value => rgb(value).map(part => { const n = part / 255; return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4; }).reduce((sum, part, i) => sum + part * [.2126, .7152, .0722][i], 0);
      const contrast = (a, b) => { const [low, high] = [luminance(a), luminance(b)].sort((x, y) => x - y); return (high + .05) / (low + .05); };
      await page.keyboard.press("Tab"); await page.locator(".toast-close").focus();
      for (const theme of ["light", "dark", "high-contrast", "forced-colors"]) {
        if (theme === "forced-colors") await page.emulateMedia({ forcedColors: "active" });
        else await page.evaluate(value => { document.documentElement.dataset.theme = value; window.toastQA.configure({ theme: value }); }, theme);
        await tick(page, 32);
        const value = await page.locator(".toast-close").evaluate(node => { const close = getComputedStyle(node), toast = getComputedStyle(node.closest(".toast")), text = getComputedStyle(node.closest(".toast").querySelector(".toast-text"));
          return { background: toast.backgroundColor, text: text.color, icon: close.color, outline: close.outlineColor, outlineStyle: close.outlineStyle, outlineWidth: close.outlineWidth, focusVisible: node.matches(":focus-visible"),
            borderStyle: toast.borderTopStyle, borderWidth: toast.borderTopWidth, forced: matchMedia("(forced-colors: active)").matches, forcedColorAdjust: close.forcedColorAdjust, svg_count: node.querySelectorAll("svg").length }; });
        value.ratios = { text: contrast(value.text, value.background), icon: contrast(value.icon, value.background), focus: contrast(value.outline, value.background) };
        observe("theme_" + theme, value);
        check("theme_text_icon_focus_visible", value.ratios.text >= 4.5 && value.ratios.icon >= 3 && value.ratios.focus >= 3 && value.focusVisible && value.outlineStyle !== "none" && parseFloat(value.outlineWidth) > 0 && value.svg_count === 1);
        if (theme === "forced-colors") check("forced_colors_emulated_not_opted_out", value.forced && value.forcedColorAdjust !== "none" && value.borderStyle !== "none" && parseFloat(value.borderWidth) > 0);
        await shoot(page, "toast-theme-" + theme + ".png");
      }
      check("no_modal_or_keyboard_trap_added", await page.getByRole("dialog").count() === 0 && await page.locator('.toast-stack[aria-live="polite"]').count() === 1 && await page.locator('.toast[role="alert"]').count() === 1);
      await page.keyboard.press("Tab"); check("tab_can_leave_toast", await page.evaluate(() => !document.activeElement?.closest(".toast")));
      await current.close(stage); checked("theme_computed_contrast_focus_forced_colors_screenshots_pending_root_visual_review");
    };

    const suite = async () => {
      if (prepared.selection === "archived-baseline") await baseline();
      else { await lifecycle(); await focusAndCapacity(); await layout(); await themes(); }
      check("no_browser_errors_or_unexpected_requests", receipt.page_errors.length === 0 && receipt.console_errors.length === 0 && receipt.unexpected_requests.length === 0 && receipt.request_failures.length === 0);
    };
    await Promise.race([suite(), new Promise((_, reject) => { deadline = setTimeout(() => { timedOut = true; reject(Error("suite_deadline")); }, prepared.browser.test_timeout_ms); })]);
    receipt.state = "passed";
  } catch (error) {
    receipt.state = "failed"; receipt.failure = safeError(error);
  } finally {
    clearTimeout(deadline); stage = "cleanup";
    let closeTimer;
    try {
      check("browser_started", !!browserServer && !!browserProcess);
      await Promise.race([(async () => {
        for (const context of contexts) { try { await context.close(); } catch { receipt.cleanup_failures.push("context_close_failed"); } }
        if (browser) await browser.close(); await browserServer.close();
      })(), new Promise((_, reject) => { closeTimer = setTimeout(() => reject(Error("browser_close_timeout")), prepared.browser.close_timeout_ms); })]);
      receipt.browser.natural_close = browserProcess.exitCode === 0 && browserProcess.signalCode === null && receipt.browser.server_close_observed === true;
      check("browser_natural_terminal", receipt.browser.natural_close);
    } catch {
      receipt.cleanup_failures.push("browser_close_failed");
      if (browserServer) { receipt.browser.forced_kill_requested = true; try { await browserServer.kill(); } catch { receipt.cleanup_failures.push("browser_kill_failed"); } }
    } finally { clearTimeout(closeTimer); }
    try { check("final_sources_stable", equal(snapshot(Object.keys(prepared.inputs)), prepared.inputs) && prepared.missing_inputs.every(path => !existsSync(path))); receipt.inputs_unchanged = true; }
    catch { receipt.inputs_unchanged = false; receipt.cleanup_failures.push("source_drift"); }
    try {
      check("final_source_and_playwright_runtimes_stable", equal(tree(playwrightRoot), prepared.runtime.playwright) && equal(tree(browserRoot), prepared.runtime.browser) && equal(tree(privatePlaywright), prepared.runtime.playwright));
      check("final_prepared_browser_runtime_stable", equal(tree(privateBrowser, undefined, "", { prepared: prepared.runtime.browser, records: receipt.browser_generated_sidecars }), prepared.runtime.browser));
      receipt.prepared_runtimes_unchanged = true;
    } catch { receipt.prepared_runtimes_unchanged = false; receipt.cleanup_failures.push("runtime_drift_or_copy_incomplete"); }
    // Recheck after all contexts/browser have closed so late errors cannot be
    // hidden by an earlier green request gate.
    if (receipt.page_errors.length || receipt.console_errors.length || receipt.unexpected_requests.length || receipt.request_failures.length)
      receipt.cleanup_failures.push("late_or_unexpected_browser_event");
    receipt.artifact_hashes = snapshot(receipt.screenshots.map(name => resolve(output, name)));
    if (receipt.cleanup_failures.length || !receipt.browser.natural_close || receipt.browser.forced_kill_requested) receipt.state = "failed";
    receipt.finished_utc = new Date().toISOString(); persist();
    save("browsercleanup.json", { state: receipt.state, browser: receipt.browser, cleanup_failures: receipt.cleanup_failures, inputs_unchanged: receipt.inputs_unchanged,
      prepared_runtimes_unchanged: receipt.prepared_runtimes_unchanged, browser_generated_sidecars: receipt.browser_generated_sidecars, browser_generated_sidecar_policy: receipt.browser_generated_sidecar_policy });
  }
  console.log(JSON.stringify({ state: receipt.state, output, selection: prepared.selection, checks: receipt.checks.length, baseline_defects: receipt.baseline_defect_count ?? null,
    natural_close: receipt.browser.natural_close === true, inputs_unchanged: receipt.inputs_unchanged, failure: receipt.failure || null }));
  if (receipt.state !== "passed") process.exitCode = 3;
}

async function main() {
  check("usage", ["prepare", "run"].includes(action) && mode === "component" && process.argv.length === 6 && typeof rawOutput === "string");
  output = resolve(rawOutput);
  check("direct_fresh_artifact_slot", dirname(output) === resolve(root, ".artifacts") && /^toast-component-qa-[a-z0-9-]+$/.test(basename(output)));
  if (action === "prepare") await prepare(); else await run();
}
await main().catch(error => {
  const failure = safeError(error);
  if (createdOutput && !receipt) save("prepare-or-input-failure.json", { state: "failed", failure });
  console.log(JSON.stringify({ state: "failed", failure })); process.exitCode = 3;
});
