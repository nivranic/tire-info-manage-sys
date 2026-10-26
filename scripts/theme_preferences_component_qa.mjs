/** R123 component-only QA. Root executes prepare/review/run; no HTTP/API/SQLite service. */
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, realpathSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, dirname, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";

const require = createRequire(import.meta.url), root = resolve(import.meta.dirname, "..");
const [action, rawOutput, reviewedSha] = process.argv.slice(2);
const entry = resolve(root, "scripts/theme_preferences_browser_fixture.tsx");
const loader = resolve(root, "scripts/command_palette_browser_qa_loader.cjs");
const css = resolve(root, "apps/web/app/globals.css"), origin = "http://127.0.0.1:19023";
const playwrightRoot = "E:/Mix/project/fnxt-platform-mobile/node_modules/.pnpm/playwright-core@1.63.0/node_modules/playwright-core";
const browserRoot = "C:/Users/11585/AppData/Local/ms-playwright/chromium_headless_shell-1243";
const browserExe = "chrome-headless-shell-win64/chrome-headless-shell.exe";
const labels = new Set(), sha = bytes => createHash("sha256").update(bytes).digest("hex");
let output, stage = "arguments", receipt, createdOutput = false;
const check = (label, okay) => { labels.add(label); if (!okay) throw Error(label); };
const file = path => { check("regular_input", lstatSync(path).isFile() && !lstatSync(path).isSymbolicLink()); const bytes = readFileSync(path); return { bytes: bytes.length, sha256: sha(bytes) }; };
const snapshot = paths => Object.fromEntries([...new Set(paths)].sort().map(path => [path, file(path)]));
const equal = (a, b) => isDeepStrictEqual(a, b);
const save = (name, value) => writeFileSync(resolve(output, name), JSON.stringify(value, null, 2) + "\n");
function tree(base, target, prefix = "", generatedBrowserFiles) {
  check("regular_runtime_directory", lstatSync(base).isDirectory() && !lstatSync(base).isSymbolicLink());
  if (target) mkdirSync(target, { recursive: true });
  const result = {};
  for (const item of readdirSync(base, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const name = prefix + item.name;
    if (name === "chrome-headless-shell-win64/debug.log" && !generatedBrowserFiles) continue;
    check("regular_runtime_entry", !item.isSymbolicLink());
    const source = resolve(base, item.name), destination = target ? resolve(target, item.name) : undefined;
    if (item.isDirectory()) {
      check("prepared_runtime_directory", !generatedBrowserFiles || Object.hasOwn(generatedBrowserFiles.prepared, name + "/"));
      result[name + "/"] = { kind: "directory" };
      Object.assign(result, tree(source, destination, name + "/", generatedBrowserFiles));
    } else {
      check("regular_runtime_file", item.isFile());
      if (generatedBrowserFiles && !Object.hasOwn(generatedBrowserFiles.prepared, name)) {
        const metadata = lstatSync(source);
        check("bounded_generated_browser_sidecar", /^chrome-headless-shell-win64\/(?:debug\.log|chrome-headless-shell\.\d{8}-\d{6}-\d{3}\.log)$/.test(name)
          && metadata.isFile() && !metadata.isSymbolicLink() && metadata.size >= 1 && metadata.size <= 1024 * 1024
          && generatedBrowserFiles.records.length < 4);
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
  return { stage, type, source_lines: [...String(error?.stack || "").matchAll(/theme_preferences_component_qa\.mjs:(\d+):(\d+)/g)]
    .map(match => ({ line: Number(match[1]), column: Number(match[2]) })),
    ...(labels.has(error?.message) ? { assertion: error.message } : {}) };
}

async function prepare() {
  check("fresh_output", !existsSync(output)); mkdirSync(output); createdOutput = true;
  stage = "prepare_inputs";
  const info = JSON.parse(readFileSync(resolve(playwrightRoot, "package.json"), "utf8"));
  check("reviewed_playwright_163", info.name === "playwright-core" && info.version === "1.63.0");
  const before = snapshot([import.meta.filename, entry, loader, css, resolve(root, "tsconfig.json"), resolve(root, "package-lock.json"),
    require.resolve("typescript"), require.resolve("next/dist/compiled/webpack/webpack"), require.resolve("next/dist/compiled/webpack/bundle5"), process.execPath]);
  const runtime = { playwright: tree(playwrightRoot), browser: tree(browserRoot) };
  const pinned = { ...before }, pin = path => { if (existsSync(path) && lstatSync(path).isFile() && !pinned[path]) pinned[path] = file(path); };
  stage = "prepare_types";
  const ts = require("typescript"), config = ts.readConfigFile(resolve(root, "tsconfig.json"), ts.sys.readFile);
  check("base_config", !config.error);
  const converted = ts.convertCompilerOptionsFromJson({ ...config.config.compilerOptions, jsx: "react-jsx", types: ["react", "react-dom", "node"], incremental: false }, root);
  const host = ts.createCompilerHost(converted.options), originalRead = host.readFile.bind(host);
  host.readFile = path => { pin(resolve(path)); return originalRead(path); };
  const program = ts.createProgram([entry], converted.options, host);
  const diagnostics = [...converted.errors, ...ts.getPreEmitDiagnostics(program)];
  const errors = diagnostics.filter(item => item.category === ts.DiagnosticCategory.Error).map(item => ({ code: item.code,
    source: item.file ? relative(root, item.file.fileName).replaceAll("\\", "/") : null,
    line: item.file && item.start !== undefined ? item.file.getLineAndCharacterOfPosition(item.start).line + 1 : null }));
  save("typecheck.json", { scope: "real theme/control/Web portal imports", errors, warning_count: diagnostics.length - errors.length });
  check("target_types", errors.length === 0);
  stage = "prepare_bundle";
  const { webpack } = require("next/dist/compiled/webpack/webpack");
  Object.keys(require.cache).forEach(pin);
  const compiler = webpack({ mode: "development", context: root, target: "web", entry, cache: false, devtool: false,
    output: { path: output, filename: "fixture.js" }, optimization: { minimize: false }, performance: false,
    resolve: { extensions: [".tsx", ".ts", ".js"], extensionAlias: { ".js": [".js", ".ts", ".tsx"] } },
    infrastructureLogging: { level: "none" },
    module: { rules: [{ test: /\.tsx?$/, include: [resolve(root, "apps/web/components"), resolve(root, "packages"), resolve(root, "scripts")], use: [loader] }] },
  });
  const fsRead = compiler.inputFileSystem.readFile.bind(compiler.inputFileSystem);
  compiler.inputFileSystem.readFile = (path, ...args) => { if (typeof path === "string") pin(path); return fsRead(path, ...args); };
  let stats;
  try { stats = await new Promise((done, fail) => compiler.run((error, value) => error ? fail(error) : done(value))); }
  finally { await new Promise((done, fail) => compiler.close(error => error ? fail(error) : done())); }
  const summary = stats.toJson({ all: false, errors: true, warnings: true });
  save("compile.json", { error_count: summary.errors?.length || 0, warning_count: summary.warnings?.length || 0 });
  check("fixture_bundle", !stats.hasErrors());
  const dependencies = [...stats.compilation.fileDependencies].filter(path => existsSync(path) && lstatSync(path).isFile());
  const missingInputs = [...stats.compilation.missingDependencies].filter(path => !existsSync(path)).sort();
  dependencies.forEach(pin); Object.keys(require.cache).forEach(pin);
  check("prepare_sources_stable", equal(snapshot(Object.keys(pinned)), pinned));
  check("prepare_runtimes_stable", equal(tree(playwrightRoot), runtime.playwright) && equal(tree(browserRoot), runtime.browser));
  const inputs = { ...pinned, ...snapshot(["fixture.js", "typecheck.json", "compile.json"].map(name => resolve(output, name))) };
  save("prepare.json", { schema: "theme-preferences-component-qa@1", output, node: realpathSync(process.execPath), origin, inputs, missing_inputs: missingInputs, runtime,
    scope: "real React theme/control/Web body portals plus synthetic local empty payload; no production or native acceptance",
    browser: { playwright: "1.63.0", chromium_revision: "1243", headless: true, test_timeout_ms: 240000, close_timeout_ms: 10000 },
    no_http_service: true, no_api_sqlite_provider: true, desktop_portal: "separate_host_gate", ssr_hydration_verified: false });
  console.log(JSON.stringify({ prepared_not_launched: true, output, prepare_sha256: file(resolve(output, "prepare.json")).sha256,
    input_count: Object.keys(inputs).length, type_errors: 0, bundle_errors: 0 }));
}

function instrumentation(options) {
  const key = "tire-theme-v1", storage = window.localStorage;
  const nativeGet = Storage.prototype.getItem, nativeSet = Storage.prototype.setItem;
  if (!nativeGet.call(sessionStorage, "theme-fixture-seeded")) {
    if (options.seed === null) storage.removeItem(key); else nativeSet.call(storage, key, options.seed);
    nativeSet.call(sessionStorage, "theme-fixture-seeded", "yes");
  }
  const observed = { adds: 0, removes: 0, active: 0, maximum: 0, reads: 0, writes: 0, attrWrites: [] };
  window.themeInstrumentation = observed;
  Storage.prototype.getItem = function (name) { if (name === key) { observed.reads++; if (options.storage === "get") throw new DOMException("fixture", "SecurityError"); } return nativeGet.call(this, name); };
  Storage.prototype.setItem = function (name, value) { if (name === key) { observed.writes++; if (options.storage === "write") throw new DOMException("fixture", "QuotaExceededError"); } return nativeSet.call(this, name, value); };
  if (options.storage === "unavailable") Object.defineProperty(window, "localStorage", { configurable: true, get() { throw new DOMException("fixture", "SecurityError"); } });
  const originalMedia = window.matchMedia.bind(window);
  window.matchMedia = query => {
    const media = originalMedia(query);
    if (query !== "(prefers-color-scheme: dark)") return media;
    const listeners = new Set(), add = media.addEventListener.bind(media), remove = media.removeEventListener.bind(media);
    media.addEventListener = (type, listener, config) => { if (type === "change" && listener && !listeners.has(listener)) { listeners.add(listener); observed.adds++; observed.active++; observed.maximum = Math.max(observed.maximum, observed.active); } return add(type, listener, config); };
    media.removeEventListener = (type, listener, config) => { if (type === "change" && listeners.delete(listener)) { observed.removes++; observed.active--; } return remove(type, listener, config); };
    if (options.media === "legacy") {
      const legacyAdd = media.addListener.bind(media), legacyRemove = media.removeListener.bind(media);
      Object.defineProperty(media, "addEventListener", { value: undefined }); Object.defineProperty(media, "removeEventListener", { value: undefined });
      media.addListener = listener => { if (listener && !listeners.has(listener)) { listeners.add(listener); observed.adds++; observed.active++; observed.maximum = Math.max(observed.maximum, observed.active); } return legacyAdd(listener); };
      media.removeListener = listener => { if (listeners.delete(listener)) { observed.removes++; observed.active--; } return legacyRemove(listener); };
    }
    return media;
  };
  if (options.media === "missing") Object.defineProperty(window, "matchMedia", { configurable: true, value: undefined });
  if (options.media === "throws") window.matchMedia = () => { throw new DOMException("fixture", "NotSupportedError"); };
  const set = Element.prototype.setAttribute, remove = Element.prototype.removeAttribute;
  Element.prototype.setAttribute = function (name, value) { if (this === document.documentElement && ["data-theme", "data-theme-preference"].includes(name)) observed.attrWrites.push({ name, value }); return set.call(this, name, value); };
  Element.prototype.removeAttribute = function (name) { if (this === document.documentElement && ["data-theme", "data-theme-preference"].includes(name)) observed.attrWrites.push({ name, value: null }); return remove.call(this, name); };
}

async function run() {
  check("regular_output", lstatSync(output).isDirectory() && !lstatSync(output).isSymbolicLink());
  check("reviewed_prepare", /^[a-f0-9]{64}$/.test(reviewedSha || "") && file(resolve(output, "prepare.json")).sha256 === reviewedSha);
  const prepared = JSON.parse(readFileSync(resolve(output, "prepare.json"), "utf8"));
  check("prepared_identity", prepared.schema === "theme-preferences-component-qa@1" && prepared.output === output && prepared.node === realpathSync(process.execPath));
  check("prepared_inputs", equal(snapshot(Object.keys(prepared.inputs)), prepared.inputs));
  check("prepared_missing_inputs", prepared.missing_inputs.every(path => !existsSync(path)));
  check("single_use_run", !existsSync(resolve(output, "result.json")) && !existsSync(resolve(output, "runtime")));
  receipt = { schema: prepared.schema, state: "running", scope: prepared.scope, started_utc: new Date().toISOString(),
    checks: [], screenshots: [], computed: [], unexpected_requests: [], page_errors: [], console_errors: [], cleanup_failures: [],
    browser: { playwright: "1.63.0", chromium_revision: "1243", headless: true, forced_kill_requested: false },
    browser_generated_sidecars: [],
    browser_generated_sidecar_policy: "Private browser only: exact chrome-headless-shell-win64/debug.log or chrome-headless-shell-win64/chrome-headless-shell.YYYYMMDD-HHMMSS-mmm.log; regular non-symlink files; 1..1048576 bytes each; at most 4 files combined; bytes/hash recorded without interpreting contents",
    api_sqlite_provider_calls: 0, real_native_verified: false, complete_wcag_verified: false, ssr_hydration_verified: false, desktop_portal: "separate_host_gate" };
  let timedOut = false;
  const persist = () => save("result.json", receipt), checked = name => { check("suite_active", !timedOut); receipt.checks.push(name); persist(); };
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
    const fixtureJs = readFileSync(resolve(output, "fixture.js")), fixtureCss = readFileSync(css);
    const html = '<!doctype html><html lang="zh-CN" data-theme="baseline" data-theme-preference="baseline" style="color-scheme:light dark!important"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/fixture.css"><title>主题组件隔离验证</title><style>#theme-fixture{padding:16px;min-height:100dvh;box-sizing:border-box;background:var(--paper);color:var(--ink)}.qa-tools{display:flex;flex-wrap:wrap;gap:12px;align-items:center}.qa-sample{margin-top:20px;padding:12px;border:1px solid var(--border);background:var(--surface)}#theme-state{display:block;margin-block:12px}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>';
    const fresh = async (config = {}) => {
      check("suite_active", !timedOut);
      const options = { seed: null, colorScheme: "dark", storage: "normal", media: "normal", width: 980, ...config };
      const context = await browser.newContext({ serviceWorkers: "block", colorScheme: options.colorScheme, viewport: { width: options.width, height: 900 } }); contexts.add(context);
      await context.addInitScript(instrumentation, options);
      await context.route("**/*", async route => {
        const request = route.request(), url = new URL(request.url());
        if (request.method() === "GET" && url.origin === origin && !url.search && !url.hash) {
          if (url.pathname === "/") { await route.fulfill({ contentType: "text/html; charset=utf-8", body: html }); return; }
          if (url.pathname === "/fixture.js") { await route.fulfill({ contentType: "text/javascript; charset=utf-8", body: fixtureJs }); return; }
          if (url.pathname === "/fixture.css") { await route.fulfill({ contentType: "text/css; charset=utf-8", body: fixtureCss }); return; }
          if (url.pathname === "/favicon.ico") { await route.fulfill({ status: 204 }); return; }
        }
        receipt.unexpected_requests.push({ method: ["GET", "POST"].includes(request.method()) ? request.method() : "other", origin: url.origin === origin ? "fixture" : "other", route: "blocked" });
        await route.abort();
      });
      const page = await context.newPage(); page.setDefaultTimeout(7000);
      page.on("pageerror", error => receipt.page_errors.push(["TypeError", "SyntaxError"].includes(error.name) ? error.name : "PageError"));
      page.on("console", event => { if (event.type() === "error") receipt.console_errors.push("browser_console_error"); });
      await page.goto(origin, { waitUntil: "load" }); await page.locator('#theme-state[data-ready="true"]').waitFor();
      return { page, context, close: async () => { await context.close(); contexts.delete(context); } };
    };
    const settle = page => page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    const appearance = async (page, preference, palette) => {
      await page.waitForFunction(expected => document.documentElement.dataset.themePreference === expected.preference && document.documentElement.dataset.theme === expected.palette
        && document.querySelector("#theme-state")?.getAttribute("data-palette") === expected.palette, { preference, palette });
      check("matching_color_scheme", await page.evaluate(value => document.documentElement.style.colorScheme === value, palette === "light" ? "light" : "dark"));
    };
    const choose = async (page, value) => page.getByRole("combobox", { name: "主题", exact: true }).selectOption(value);
    const suite = async () => {
      stage = "canonical_and_media";
      const base = await fresh(); const page = base.page;
      await appearance(page, "system", "dark");
      let metrics = await page.evaluate(() => ({ callbacks: window.themeQA.callbacks, media: window.themeInstrumentation, saved: localStorage.getItem("tire-theme-v1") }));
      check("system_initial_dark_no_placeholder_callback", equal(metrics.callbacks.map(item => item.brightness), ["dark"]) && metrics.callbacks.every(item => item.owner === "provider" && item.mounted));
      check("nested_boundaries_strict_single_listener_no_init_write", metrics.media.active === 1 && metrics.media.maximum === 1 && metrics.media.writes === 0 && metrics.saved === null);
      await page.emulateMedia({ colorScheme: "light" }); await appearance(page, "system", "light");
      check("system_media_never_persists_resolved_palette", await page.evaluate(() => localStorage.getItem("tire-theme-v1") === null && window.themeInstrumentation.writes === 0));
      for (const [preference, palette] of [["light", "light"], ["dark", "dark"], ["high-contrast", "high-contrast"]]) {
        await choose(page, preference); await appearance(page, preference, palette);
        await page.emulateMedia({ colorScheme: "dark" }); await appearance(page, preference, palette);
        await page.emulateMedia({ colorScheme: "light" }); await appearance(page, preference, palette);
        check("explicit_palette_has_no_media_listener", await page.evaluate(() => window.themeInstrumentation.active === 0));
        check("canonical_string_storage", await page.evaluate(value => localStorage.getItem("tire-theme-v1") === value, preference));
      }
      check("high_contrast_native_dark", await page.evaluate(() => window.themeQA.callbacks.at(-1)?.brightness === "dark" && window.themeQA.callbacks.every(item => ["light", "dark"].includes(item.brightness))));
      await choose(page, "system"); await appearance(page, "system", "light");
      const offset = await page.evaluate(() => window.themeInstrumentation.attrWrites.length);
      await page.emulateMedia({ colorScheme: "dark" }); await appearance(page, "system", "dark");
      check("palette_change_has_no_restore_cleanup", await page.evaluate(start => window.themeInstrumentation.attrWrites.slice(start).every(item => item.value !== "baseline" && item.value !== null), offset));
      checked("four_preferences_three_palettes_two_native_values_real_media");
      stage = "real_portals";
      await page.setViewportSize({ width: 980, height: 600 });
      for (const kind of ["offline", "ai"]) {
        await page.locator(`#open-${kind}`).click();
        const dialog = page.getByRole("dialog", { name: kind === "offline" ? "设备离线资料库" : "设备 AI 分析", exact: true }); await dialog.waitFor();
        await dialog.getByRole("button", { name: /主题验证合成本地资料槽/ }).click();
        if (kind === "ai") await dialog.getByRole("button", { name: /仅用于显示本机问题字段的空载荷/ }).click();
        const field = kind === "offline" ? dialog.getByRole("textbox", { name: "包内关键词", exact: true }) : dialog.locator("#device-ai-question");
        await field.fill(`theme-${kind}-retained`); await field.focus();
        await dialog.evaluate(node => { window.themePortalNode = node; window.themePortalScroller = node; node.scrollTop = Math.min(50, node.scrollHeight - node.clientHeight); window.themePortalScroll = node.scrollTop; window.themePortalField = document.activeElement; });
        check("real_portal_scroll_is_nonzero", await dialog.evaluate(() => window.themePortalScroll > 0));
        await page.emulateMedia({ colorScheme: "light" }); await appearance(page, "system", "light"); await settle(page);
        check("live_real_body_portal_state_retained", await dialog.evaluate(node => node === window.themePortalNode && node.parentElement.parentElement === document.body
          && node.parentElement.dataset.theme === "light" && document.activeElement === window.themePortalField
          && window.themePortalField.value.startsWith("theme-") && window.themePortalScroller.scrollTop === window.themePortalScroll));
        check("real_field_value_retained", await field.inputValue() === `theme-${kind}-retained`);
        await page.emulateMedia({ colorScheme: "dark" }); await appearance(page, "system", "dark");
        check("real_portal_same_node_dark", await dialog.evaluate(node => node === window.themePortalNode && node.parentElement.dataset.theme === "dark"));
        const portalShot = `portal-${kind}-dark.png`; await page.screenshot({ path: resolve(output, portalShot) }); receipt.screenshots.push(portalShot);
        await dialog.getByRole("button", { name: "关闭", exact: true }).click(); await dialog.waitFor({ state: "detached" });
      }
      checked("real_offline_search_and_device_ai_question_nodes_focus_values_scroll_survive_media");
      stage = "ownership_unmount_remount";
      for (let index = 0; index < 2; index++) {
        const before = await page.evaluate(() => window.themeQA.callbacks.length);
        await page.evaluate(() => window.themeQA.unmount());
        check("unmount_listener_removed_root_baseline_restored", await page.evaluate(() => window.themeInstrumentation.active === 0
          && document.documentElement.dataset.theme === "baseline" && document.documentElement.dataset.themePreference === "baseline"
          && document.documentElement.style.getPropertyValue("color-scheme") === "light dark" && document.documentElement.style.getPropertyPriority("color-scheme") === "important"));
        await page.emulateMedia({ colorScheme: "light" }); await settle(page);
        check("unmount_has_no_native_callback", await page.evaluate(count => window.themeQA.callbacks.length === count, before));
        await page.evaluate(() => window.themeQA.mount()); await page.locator('#theme-state[data-ready="true"]').waitFor(); await appearance(page, "system", "light");
        check("remount_single_media_owner", await page.evaluate(() => window.themeInstrumentation.active === 1 && window.themeInstrumentation.maximum === 1));
      }
      await page.evaluate(() => { document.documentElement.setAttribute("data-theme", "external"); document.documentElement.setAttribute("data-theme-preference", "external"); document.documentElement.style.setProperty("color-scheme", "light", "important"); window.themeQA.unmount(); });
      check("external_owner_changes_preserved", await page.evaluate(() => document.documentElement.dataset.theme === "external" && document.documentElement.dataset.themePreference === "external" && document.documentElement.style.getPropertyValue("color-scheme") === "light" && document.documentElement.style.getPropertyPriority("color-scheme") === "important"));
      checked("strictmode_unmount_remount_ownership_restore_and_foreign_changes"); await base.close();

      stage = "storage_reload_fallbacks";
      for (const seed of ["light", "dark", "not-a-theme", "LIGHT"]) {
        const current = await fresh({ seed }); const wanted = ["light", "dark"].includes(seed) ? seed : "system";
        await appearance(current.page, wanted, wanted === "light" ? "light" : "dark");
        check("initialization_does_not_overwrite_storage", await current.page.evaluate(value => localStorage.getItem("tire-theme-v1") === value && window.themeInstrumentation.writes === 0, seed));
        await current.page.reload({ waitUntil: "load" }); await current.page.locator('#theme-state[data-ready="true"]').waitFor(); await appearance(current.page, wanted, wanted === "light" ? "light" : "dark");
        check("reload_native_has_no_placeholder_light", await current.page.evaluate(value => window.themeQA.callbacks.length === 1 && window.themeQA.callbacks[0].brightness === value, wanted === "light" ? "light" : "dark"));
        await current.close();
      }
      for (const storage of ["get", "write", "unavailable"]) {
        const current = await fresh({ storage }); await appearance(current.page, "system", "dark");
        await choose(current.page, "high-contrast"); await appearance(current.page, "high-contrast", "high-contrast"); await current.close();
      }
      for (const media of ["missing", "throws"]) {
        const current = await fresh({ media }); await appearance(current.page, "system", "light");
        await choose(current.page, "dark"); await appearance(current.page, "dark", "dark"); await current.close();
      }
      const legacy = await fresh({ media: "legacy" }); await appearance(legacy.page, "system", "dark");
      await legacy.page.emulateMedia({ colorScheme: "light" }); await appearance(legacy.page, "system", "light");
      await choose(legacy.page, "dark"); await appearance(legacy.page, "dark", "dark");
      check("legacy_media_listener_pair_removed", await legacy.page.evaluate(() => window.themeInstrumentation.active === 0 && window.themeInstrumentation.adds === window.themeInstrumentation.removes));
      await legacy.close();
      checked("legacy_reload_invalid_storage_and_get_write_matchmedia_failures");

      stage = "high_contrast_responsive_forced_colors";
      for (const width of [390, 320]) {
        const current = await fresh({ width, seed: "high-contrast" }); const view = current.page;
        await appearance(view, "high-contrast", "high-contrast");
        await view.getByRole("combobox", { name: "主题", exact: true }).focus(); await view.keyboard.press("Tab"); await view.keyboard.press("Shift+Tab");
        const computed = await view.evaluate(() => {
          const style = selector => { const node = document.querySelector(selector), value = getComputedStyle(node), box = node.getBoundingClientRect(); return { color: value.color, background: value.backgroundColor, border: value.borderTopColor, borderStyle: value.borderTopStyle, borderWidth: value.borderTopWidth,
            outline: value.outlineColor, outlineStyle: value.outlineStyle, outlineWidth: value.outlineWidth, focusVisible: node.matches(":focus-visible"), left: box.left, right: box.right }; };
          return { width: innerWidth, scrollWidth: document.documentElement.scrollWidth, text: style("#qa-text"), muted: style("#qa-muted"), link: style("#qa-link"), sample: style(".qa-sample"), select: style('.theme-preference-control select') };
        });
        const rgb = value => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
        const luminance = value => rgb(value).map(part => { const normalized = part / 255; return normalized <= .04045 ? normalized / 12.92 : ((normalized + .055) / 1.055) ** 2.4; }).reduce((sum, part, index) => sum + part * [.2126, .7152, .0722][index], 0);
        const contrast = (a, b) => { const values = [luminance(a), luminance(b)].sort((x, y) => y - x); return (values[0] + .05) / (values[1] + .05); };
        computed.ratios = { text: contrast(computed.text.color, computed.sample.background), muted: contrast(computed.muted.color, computed.sample.background), link: contrast(computed.link.color, computed.sample.background), border: contrast(computed.sample.border, computed.sample.background), focus: contrast(computed.select.outline, computed.select.background) };
        check("hc_local_text_contrast", [computed.ratios.text, computed.ratios.muted, computed.ratios.link].every(value => value >= 4.5));
        check("hc_visible_border_focus_and_narrow_layout", computed.ratios.border >= 3 && computed.ratios.focus >= 3 && computed.select.focusVisible && computed.select.outlineStyle !== "none" && parseFloat(computed.select.outlineWidth) > 0 && computed.scrollWidth <= width && computed.select.left >= 0 && computed.select.right <= width);
        receipt.computed.push({ width, mode: "high-contrast", ...computed });
        const shot = `high-contrast-${width}.png`; await view.screenshot({ path: resolve(output, shot), fullPage: true }); receipt.screenshots.push(shot);
        await view.emulateMedia({ forcedColors: "active" }); await settle(view);
        const forced = await view.evaluate(() => { const node = document.querySelector('.theme-preference-control select'), style = getComputedStyle(node); return { active: matchMedia("(forced-colors: active)").matches, color: style.color, background: style.backgroundColor, outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth, forcedColorAdjust: style.forcedColorAdjust }; });
        check("forced_colors_actual_emulation_keeps_focus_auto", forced.active && forced.forcedColorAdjust !== "none" && forced.outlineStyle !== "none" && parseFloat(forced.outlineWidth) > 0);
        receipt.computed.push({ width, mode: "forced-colors", ...forced });
        const forcedShot = `forced-colors-${width}.png`; await view.screenshot({ path: resolve(output, forcedShot), fullPage: true }); receipt.screenshots.push(forcedShot);
        await current.close();
      }
      checked("320_390_high_contrast_local_computed_focus_borders_forced_colors_screenshots");
      check("no_browser_errors_or_network", receipt.page_errors.length === 0 && receipt.console_errors.length === 0 && receipt.unexpected_requests.length === 0);
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
      check("final_source_and_playwright_runtimes_stable", equal(tree(playwrightRoot), prepared.runtime.playwright) && equal(tree(browserRoot), prepared.runtime.browser)
        && equal(tree(privatePlaywright), prepared.runtime.playwright));
      check("final_prepared_browser_runtime_stable", equal(tree(privateBrowser, undefined, "", {
        prepared: prepared.runtime.browser, records: receipt.browser_generated_sidecars,
      }), prepared.runtime.browser));
      receipt.prepared_runtimes_unchanged = true;
    } catch { receipt.prepared_runtimes_unchanged = false; receipt.cleanup_failures.push("runtime_drift_or_copy_incomplete"); }
    receipt.artifact_hashes = snapshot(receipt.screenshots.map(name => resolve(output, name)));
    if (receipt.cleanup_failures.length || !receipt.browser.natural_close || receipt.browser.forced_kill_requested) receipt.state = "failed";
    receipt.finished_utc = new Date().toISOString(); persist();
    save("browsercleanup.json", { state: receipt.state, browser: receipt.browser, cleanup_failures: receipt.cleanup_failures, inputs_unchanged: receipt.inputs_unchanged,
      prepared_runtimes_unchanged: receipt.prepared_runtimes_unchanged, browser_generated_sidecars: receipt.browser_generated_sidecars,
      browser_generated_sidecar_policy: receipt.browser_generated_sidecar_policy });
  }
  console.log(JSON.stringify({ state: receipt.state, output, checks: receipt.checks.length, natural_close: receipt.browser.natural_close === true, inputs_unchanged: receipt.inputs_unchanged, failure: receipt.failure || null }));
  if (receipt.state !== "passed") process.exitCode = 3;
}

async function main() {
  check("usage", ["prepare", "run"].includes(action) && process.argv.length === (action === "prepare" ? 4 : 5) && typeof rawOutput === "string");
  output = resolve(rawOutput);
  check("direct_fresh_artifact_slot", dirname(output) === resolve(root, ".artifacts") && /^theme-component-qa-[a-z0-9-]+$/.test(basename(output)));
  if (action === "prepare") await prepare(); else await run();
}
await main().catch(error => {
  const failure = safeError(error);
  if (createdOutput && !receipt) save("prepare-or-input-failure.json", { state: "failed", failure });
  console.log(JSON.stringify({ state: "failed", failure })); process.exitCode = 3;
});
