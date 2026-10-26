/** R124 component-only QA. Root executes prepare/review/run; no product service. */
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, realpathSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, dirname, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";

const require = createRequire(import.meta.url), root = resolve(import.meta.dirname, "..");
const [action, rawOutput, reviewedSha] = process.argv.slice(2);
const entry = resolve(root, "scripts/web_theme_color_browser_fixture.tsx");
const loader = resolve(root, "scripts/command_palette_browser_qa_loader.cjs");
const css = resolve(root, "apps/web/app/globals.css"), origin = "http://127.0.0.1:19024";
const playwrightRoot = "E:/Mix/project/fnxt-platform-mobile/node_modules/.pnpm/playwright-core@1.63.0/node_modules/playwright-core";
const browserRoot = "C:/Users/11585/AppData/Local/ms-playwright/chromium_headless_shell-1243";
const browserExe = "chrome-headless-shell-win64/chrome-headless-shell.exe";
const colors = { light: "#f6f5f1", dark: "#191d1c", "high-contrast": "#000000" };
const labels = new Set(), sha = bytes => createHash("sha256").update(bytes).digest("hex");
let output, stage = "arguments", receipt, createdOutput = false;
const check = (label, okay) => { labels.add(label); if (!okay) throw Error(label); };
const file = path => { check("regular_input", lstatSync(path).isFile() && !lstatSync(path).isSymbolicLink()); const bytes = readFileSync(path); return { bytes: bytes.length, sha256: sha(bytes) }; };
const snapshot = paths => Object.fromEntries([...new Set(paths)].sort().map(path => [path, file(path)]));
const equal = (a, b) => isDeepStrictEqual(a, b);
const save = (name, value) => writeFileSync(resolve(output, name), JSON.stringify(value, null, 2) + "\n");

// The reviewed R123 policy: directory markers and every original file stay pinned;
// only bounded regular browser logs may be added, and are preserved with hashes.
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
  return { stage, type, source_lines: [...String(error?.stack || "").matchAll(/web_theme_color_qa\.mjs:(\d+):(\d+)/g)]
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
  save("typecheck.json", { scope: "real WebThemeBoundary, nested Workbench boundaries and input", errors, warning_count: diagnostics.length - errors.length });
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
  save("prepare.json", { schema: "web-theme-color-component-qa@1", output, node: realpathSync(process.execPath), origin, inputs, missing_inputs: missingInputs, runtime,
    scope: "real WebThemeBoundary and nested WorkbenchThemeBoundary in synthetic document; no production hydration or browser chrome acceptance",
    expected_colors: colors, browser: { playwright: "1.63.0", chromium_revision: "1243", headless: true, test_timeout_ms: 120000, close_timeout_ms: 10000 },
    no_http_service: true, no_api_sqlite_provider: true, ssr_hydration_verified: false, installed_pwa_verified: false });
  console.log(JSON.stringify({ prepared_not_launched: true, output, prepare_sha256: file(resolve(output, "prepare.json")).sha256,
    input_count: Object.keys(inputs).length, type_errors: 0, bundle_errors: 0 }));
}

function instrumentation({ seed }) {
  const key = "tire-theme-v1", storage = window.localStorage;
  const nativeGet = Storage.prototype.getItem, nativeSet = Storage.prototype.setItem;
  if (!nativeGet.call(sessionStorage, "web-theme-fixture-seeded")) {
    if (seed === null) storage.removeItem(key); else nativeSet.call(storage, key, seed);
    nativeSet.call(sessionStorage, "web-theme-fixture-seeded", "yes");
  }
  const observed = { active: 0, maximum: 0, adds: 0, removes: 0, writes: 0, metaWrites: [] };
  window.webThemeInstrumentation = observed;
  Storage.prototype.setItem = function (name, value) { if (name === key) observed.writes++; return nativeSet.call(this, name, value); };
  const originalMedia = window.matchMedia.bind(window);
  window.matchMedia = query => {
    const media = originalMedia(query);
    if (query !== "(prefers-color-scheme: dark)") return media;
    const listeners = new Set(), add = media.addEventListener.bind(media), remove = media.removeEventListener.bind(media);
    media.addEventListener = (type, listener, config) => { if (type === "change" && listener && !listeners.has(listener)) { listeners.add(listener); observed.adds++; observed.active++; observed.maximum = Math.max(observed.maximum, observed.active); } return add(type, listener, config); };
    media.removeEventListener = (type, listener, config) => { if (type === "change" && listeners.delete(listener)) { observed.removes++; observed.active--; } return remove(type, listener, config); };
    return media;
  };
  const originalSet = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    if (this.tagName === "META" && this.getAttribute("name") === "theme-color" && name === "content") {
      observed.metaWrites.push({ value, ready: document.querySelector("#theme-state")?.getAttribute("data-ready") === "true" });
    }
    return originalSet.call(this, name, value);
  };
}

async function run() {
  check("regular_output", lstatSync(output).isDirectory() && !lstatSync(output).isSymbolicLink());
  check("reviewed_prepare", /^[a-f0-9]{64}$/.test(reviewedSha || "") && file(resolve(output, "prepare.json")).sha256 === reviewedSha);
  const prepared = JSON.parse(readFileSync(resolve(output, "prepare.json"), "utf8"));
  check("prepared_identity", prepared.schema === "web-theme-color-component-qa@1" && prepared.output === output && prepared.node === realpathSync(process.execPath) && equal(prepared.expected_colors, colors));
  check("prepared_inputs", equal(snapshot(Object.keys(prepared.inputs)), prepared.inputs));
  check("prepared_missing_inputs", prepared.missing_inputs.every(path => !existsSync(path)));
  check("single_use_run", !existsSync(resolve(output, "result.json")) && !existsSync(resolve(output, "runtime")));
  receipt = { schema: prepared.schema, state: "running", scope: prepared.scope, started_utc: new Date().toISOString(),
    checks: [], observations: [], screenshots: [], unexpected_requests: [], page_errors: [], console_errors: [], cleanup_failures: [],
    browser: { playwright: "1.63.0", chromium_revision: "1243", headless: true, forced_kill_requested: false }, browser_generated_sidecars: [],
    browser_generated_sidecar_policy: "Private browser only: exact chrome-headless-shell-win64/debug.log or chrome-headless-shell-win64/chrome-headless-shell.YYYYMMDD-HHMMSS-mmm.log; regular non-symlink; 1..1048576 bytes each; at most 4 combined; bytes/hash preserved",
    api_sqlite_provider_calls: 0, real_browser_chrome_verified: false, installed_pwa_verified: false, ssr_hydration_verified: false, real_native_verified: false };
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
    const fresh = async (config = {}) => {
      check("suite_active", !timedOut);
      const options = { seed: null, colorScheme: "dark", meta: 'content="#fixture-original"', ...config };
      const meta = options.meta === null ? "" : `<meta name="theme-color" ${options.meta}>`;
      const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${meta}<link rel="stylesheet" href="/fixture.css"><title>Web主题色组件验证</title><style>body{margin:0;background:var(--paper);color:var(--ink)}#web-theme-fixture{padding:24px;max-width:720px}#web-theme-fixture label,#theme-state{display:block;margin-top:16px}#retained-input{color:inherit;background:var(--surface);border:1px solid var(--border);padding:8px}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>`;
      const context = await browser.newContext({ serviceWorkers: "block", colorScheme: options.colorScheme, viewport: { width: 920, height: 640 } }); contexts.add(context);
      await context.addInitScript(instrumentation, { seed: options.seed });
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
      return { page, close: async () => { await context.close(); contexts.delete(context); } };
    };
    const settle = page => page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    const observe = async (page, scenario) => {
      const value = await page.evaluate(() => ({ preference: document.documentElement.dataset.themePreference, palette: document.documentElement.dataset.theme,
        metas: [...document.head.querySelectorAll('meta[name="theme-color"]')].map(node => ({ content: node.getAttribute("content"), media: node.getAttribute("media") })),
        shared: document.querySelector("#theme-state")?.getAttribute("data-shared"), listeners: window.webThemeInstrumentation.active,
        maximum_listeners: window.webThemeInstrumentation.maximum, writes: window.webThemeInstrumentation.writes }));
      receipt.observations.push({ scenario, ...value }); persist(); return value;
    };
    const appearance = async (page, preference, palette) => {
      await page.waitForFunction(expected => document.documentElement.dataset.themePreference === expected.preference && document.documentElement.dataset.theme === expected.palette
        && document.querySelector("#theme-state")?.getAttribute("data-palette") === expected.palette, { preference, palette });
      await page.waitForFunction(color => { const nodes = document.head.querySelectorAll('meta[name="theme-color"]'); return nodes.length === 1 && nodes[0].getAttribute("content") === color; }, colors[palette])
        .catch(async error => { await observe(page, `${preference}:${palette}:meta-failure`); throw error; });
      const value = await observe(page, `${preference}:${palette}`);
      check("single_shared_provider_and_meta", value.shared === "true" && value.metas.length === 1 && value.metas[0].media === null
        && value.maximum_listeners <= 1 && await page.evaluate(() => window.webThemeQA.nestedCallbacks.length === 0));
    };
    const choose = (page, value) => page.getByRole("combobox", { name: "主题", exact: true }).selectOption(value);
    const unmount = page => page.evaluate(() => window.webThemeQA.unmount());
    const suite = async () => {
      stage = "legacy_and_four_preferences";
      const legacy = await fresh({ seed: "dark", colorScheme: "light" }), page = legacy.page;
      await appearance(page, "dark", "dark");
      check("legacy_dark_no_initial_storage_write", await page.evaluate(() => localStorage.getItem("tire-theme-v1") === "dark" && window.webThemeInstrumentation.writes === 0));
      for (const preference of ["light", "dark", "high-contrast", "system"]) {
        await choose(page, preference); await appearance(page, preference, preference === "system" ? "light" : preference);
        check("canonical_preference_persisted", await page.evaluate(value => localStorage.getItem("tire-theme-v1") === value, preference));
      }
      await choose(page, "high-contrast"); await page.reload({ waitUntil: "load" }); await appearance(page, "high-contrast", "high-contrast");
      const screenshot = "web-theme-color-high-contrast.png"; await page.screenshot({ path: resolve(output, screenshot) }); receipt.screenshots.push(screenshot);
      await legacy.close(); checked("legacy_dark_four_explicit_colors_unique_meta_and_reload");

      stage = "system_media_and_input";
      const system = await fresh(), systemPage = system.page;
      await appearance(systemPage, "system", "dark");
      check("strict_single_live_media_listener", await systemPage.evaluate(() => window.webThemeInstrumentation.active === 1 && window.webThemeInstrumentation.maximum === 1
        && window.webThemeQA.mounts === 2 && window.webThemeQA.cleanups === 1));
      await systemPage.getByLabel("保留中的输入", { exact: true }).fill("input-survives-theme");
      await systemPage.getByLabel("保留中的输入", { exact: true }).focus();
      await systemPage.evaluate(() => { window.webThemeQA.retainedInput = document.querySelector("#retained-input"); });
      await systemPage.emulateMedia({ colorScheme: "light" }); await appearance(systemPage, "system", "light");
      await systemPage.emulateMedia({ colorScheme: "dark" }); await appearance(systemPage, "system", "dark");
      check("missing_system_media_never_persists_palette", await systemPage.evaluate(() => localStorage.getItem("tire-theme-v1") === null && window.webThemeInstrumentation.writes === 0));
      for (const preference of ["light", "high-contrast", "system"]) {
        await choose(systemPage, preference); await appearance(systemPage, preference, preference === "system" ? "dark" : preference);
        check("input_dom_value_focus_preserved", await systemPage.evaluate(() => window.webThemeQA.retainedInput === document.querySelector("#retained-input")
          && window.webThemeQA.retainedInput.value === "input-survives-theme" && document.activeElement === window.webThemeQA.retainedInput));
      }
      check("meta_ready_before_palette_writes_and_no_update_restore", await systemPage.evaluate(expected => window.webThemeInstrumentation.metaWrites.length > 0
        && window.webThemeInstrumentation.metaWrites.every(item => expected.includes(item.value) && item.ready), Object.values(colors)));
      const inputShot = "web-theme-color-system-input.png"; await systemPage.screenshot({ path: resolve(output, inputShot) }); receipt.screenshots.push(inputShot);
      await unmount(systemPage); await settle(systemPage);
      check("unmount_restores_original_content_and_listener", await systemPage.evaluate(() => document.head.querySelectorAll('meta[name="theme-color"]').length === 1
        && document.head.querySelector('meta[name="theme-color"]') === window.webThemeQA.originalMeta
        && window.webThemeQA.originalMeta.getAttribute("content") === "#fixture-original" && window.webThemeInstrumentation.active === 0
        && window.webThemeQA.mounts === window.webThemeQA.cleanups));
      await system.close(); checked("missing_system_real_media_strict_mode_input_and_original_restore");

      stage = "content_attribute_absent";
      const absent = await fresh({ seed: "dark", meta: "" }); await appearance(absent.page, "dark", "dark");
      await choose(absent.page, "light"); await appearance(absent.page, "light", "light");
      await unmount(absent.page); await settle(absent.page);
      check("unmount_restores_absent_content_attribute", await absent.page.evaluate(() => document.head.querySelector('meta[name="theme-color"]') === window.webThemeQA.originalMeta
        && !window.webThemeQA.originalMeta.hasAttribute("content")));
      await absent.close(); checked("strict_mode_original_absent_content_restored_without_new_meta");

      stage = "external_content_ownership";
      const external = await fresh({ seed: "dark" }); await appearance(external.page, "dark", "dark");
      await external.page.evaluate(() => window.webThemeQA.originalMeta.setAttribute("content", "#fixture-external"));
      for (const preference of ["light", "high-contrast"]) {
        await choose(external.page, preference); await settle(external.page);
        check("external_content_not_overwritten_on_palette_change", await external.page.evaluate(value => document.documentElement.dataset.theme === value
          && window.webThemeQA.originalMeta.getAttribute("content") === "#fixture-external", preference));
      }
      await unmount(external.page); await settle(external.page);
      check("external_content_not_overwritten_on_unmount", await external.page.evaluate(() => document.head.querySelector('meta[name="theme-color"]') === window.webThemeQA.originalMeta
        && window.webThemeQA.originalMeta.getAttribute("content") === "#fixture-external"));
      await observe(external.page, "external-content-after-unmount"); await external.close(); checked("external_content_owner_preserved_on_updates_and_unmount");

      stage = "external_node_replacement";
      const replacement = await fresh({ seed: "dark" }); await appearance(replacement.page, "dark", "dark");
      await replacement.page.evaluate(() => { const next = document.createElement("meta"); next.name = "theme-color"; next.content = "#fixture-replacement";
        next.id = "external-meta"; window.webThemeQA.originalMeta.replaceWith(next); });
      for (const preference of ["high-contrast", "light"]) {
        await choose(replacement.page, preference); await settle(replacement.page);
        check("replacement_meta_not_adopted_on_palette_change", await replacement.page.evaluate(value => document.documentElement.dataset.theme === value
          && document.head.querySelectorAll('meta[name="theme-color"]').length === 1 && document.querySelector("#external-meta").getAttribute("content") === "#fixture-replacement", preference));
      }
      await unmount(replacement.page); await settle(replacement.page);
      check("replacement_meta_not_overwritten_on_unmount", await replacement.page.evaluate(() => document.querySelector("#external-meta").getAttribute("content") === "#fixture-replacement"));
      await observe(replacement.page, "replacement-after-unmount"); await replacement.close(); checked("external_node_replacement_never_overwritten_or_removed");

      stage = "missing_duplicate_conditional_meta";
      for (const [name, meta, expected] of [
        ["missing", null, []],
        ["duplicate", 'content="#fixture-a"><meta name="theme-color" content="#fixture-b"', ["#fixture-a", "#fixture-b"]],
        ["conditional", 'content="#fixture-conditional" media="(prefers-color-scheme: dark)"', ["#fixture-conditional"]],
      ]) {
        const negative = await fresh({ meta });
        const initial = await observe(negative.page, `${name}-initial-noop`);
        check("unsafe_initial_meta_shape_left_untouched", equal(initial.metas.map(item => item.content), expected));
        for (const preference of ["light", "high-contrast", "system"]) {
          await choose(negative.page, preference); await settle(negative.page);
          const current = await observe(negative.page, `${name}:${preference}:noop`);
          check("unsafe_meta_shape_never_written", current.preference === preference && equal(current.metas.map(item => item.content), expected)
            && await negative.page.evaluate(() => window.webThemeInstrumentation.metaWrites.length === 0));
        }
        await unmount(negative.page); await settle(negative.page);
        const value = await observe(negative.page, `${name}-safe-noop`);
        check("unsafe_meta_shape_left_untouched", equal(value.metas.map(item => item.content), expected));
        if (name === "conditional") check("conditional_media_attribute_preserved", value.metas[0].media === "(prefers-color-scheme: dark)");
        await negative.close();
      }
      checked("missing_duplicate_and_media_meta_are_safe_noop");
      check("no_product_api_provider_or_unexpected_requests", receipt.unexpected_requests.length === 0 && receipt.page_errors.length === 0 && receipt.console_errors.length === 0);
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
      check("final_prepared_browser_runtime_stable", equal(tree(privateBrowser, undefined, "", { prepared: prepared.runtime.browser, records: receipt.browser_generated_sidecars }), prepared.runtime.browser));
      receipt.prepared_runtimes_unchanged = true;
    } catch { receipt.prepared_runtimes_unchanged = false; receipt.cleanup_failures.push("runtime_drift_or_copy_incomplete"); }
    receipt.artifact_hashes = snapshot(receipt.screenshots.map(name => resolve(output, name)));
    if (receipt.cleanup_failures.length || !receipt.browser.natural_close || receipt.browser.forced_kill_requested) receipt.state = "failed";
    receipt.finished_utc = new Date().toISOString(); persist();
    save("browsercleanup.json", { state: receipt.state, browser: receipt.browser, cleanup_failures: receipt.cleanup_failures, inputs_unchanged: receipt.inputs_unchanged,
      prepared_runtimes_unchanged: receipt.prepared_runtimes_unchanged, browser_generated_sidecars: receipt.browser_generated_sidecars, browser_generated_sidecar_policy: receipt.browser_generated_sidecar_policy });
  }
  console.log(JSON.stringify({ state: receipt.state, output, checks: receipt.checks.length, natural_close: receipt.browser.natural_close === true, inputs_unchanged: receipt.inputs_unchanged, failure: receipt.failure || null }));
  if (receipt.state !== "passed") process.exitCode = 3;
}

async function main() {
  check("usage", ["prepare", "run"].includes(action) && process.argv.length === (action === "prepare" ? 4 : 5) && typeof rawOutput === "string");
  output = resolve(rawOutput);
  check("direct_fresh_artifact_slot", dirname(output) === resolve(root, ".artifacts") && /^web-theme-color-qa-[a-z0-9-]+$/.test(basename(output)));
  if (action === "prepare") await prepare(); else await run();
}

await main().catch(error => {
  const failure = safeError(error);
  if (createdOutput && !receipt) save("prepare-or-input-failure.json", { state: "failed", failure });
  console.log(JSON.stringify({ state: "failed", failure })); process.exitCode = 3;
});
