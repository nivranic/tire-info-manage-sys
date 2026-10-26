/** R123 actual Vite frontend QA. Root alone executes prepare/review/run. No native or API service. */
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, realpathSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, dirname, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";

const require = createRequire(import.meta.url), root = resolve(import.meta.dirname, "..");
const [action, rawOutput, reviewedSha] = process.argv.slice(2);
const buildRoot = resolve(root, ".artifacts/query-fallback49/frontend-final-build-r123-d67c");
const buildReceipt = resolve(buildRoot, "verification.json");
const productPins = resolve(root, ".artifacts/r123-theme-preferences-20261022/product-source-pins-v3.json");
const distRoots = { desktop: resolve(buildRoot, "desktop-dist"), mobile: resolve(buildRoot, "mobile-dist") };
const origins = { desktop: "http://127.0.0.1:19024", mobile: "http://127.0.0.1:19025" };
const playwrightRoot = "E:/Mix/project/fnxt-platform-mobile/node_modules/.pnpm/playwright-core@1.63.0/node_modules/playwright-core";
const browserRoot = "C:/Users/11585/AppData/Local/ms-playwright/chromium_headless_shell-1243";
const browserExe = "chrome-headless-shell-win64/chrome-headless-shell.exe";
const labels = new Set(), sha = bytes => createHash("sha256").update(bytes).digest("hex");
let output, stage = "arguments", receipt, createdOutput = false;
const check = (label, okay) => { labels.add(label); if (!okay) throw Error(label); };
const equal = (a, b) => isDeepStrictEqual(a, b);
const file = path => { check("regular_input", lstatSync(path).isFile() && !lstatSync(path).isSymbolicLink()); const bytes = readFileSync(path); return { bytes: bytes.length, sha256: sha(bytes) }; };
const snapshot = paths => Object.fromEntries([...new Set(paths)].sort().map(path => [path, file(path)]));
const save = (name, value) => writeFileSync(resolve(output, name), JSON.stringify(value, null, 2) + "\n");
function tree(base, target, prefix = "") {
  check("regular_tree_directory", lstatSync(base).isDirectory() && !lstatSync(base).isSymbolicLink());
  if (target) mkdirSync(target, { recursive: true });
  const result = {};
  for (const item of readdirSync(base, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const name = prefix + item.name;
    check("regular_tree_entry", !item.isSymbolicLink());
    const source = resolve(base, item.name), destination = target ? resolve(target, item.name) : undefined;
    if (item.isDirectory()) Object.assign(result, tree(source, destination, name + "/"));
    else { check("regular_tree_file", item.isFile()); result[name] = file(source); if (destination) copyFileSync(source, destination); }
  }
  return result;
}
// Runtime entries include empty directories. The browser's exact debug.log is
// generated output, so omit it from source inputs and the pre-launch copy only.
function runtimeManifest(base, target, omitBrowserDebug = false, prefix = "") {
  check("regular_runtime_directory", lstatSync(base).isDirectory() && !lstatSync(base).isSymbolicLink());
  if (target) mkdirSync(target, { recursive: true });
  const result = {};
  for (const item of readdirSync(base, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    check("regular_runtime_entry", !item.isSymbolicLink());
    const name = prefix + item.name, source = resolve(base, item.name), destination = target ? resolve(target, item.name) : undefined;
    if (item.isDirectory()) {
      result[name + "/"] = { kind: "directory" };
      Object.assign(result, runtimeManifest(source, destination, omitBrowserDebug, name + "/"));
    } else {
      check("regular_runtime_file", item.isFile());
      if (omitBrowserDebug && name === "chrome-headless-shell-win64/debug.log") continue;
      result[name] = { kind: "file", ...file(source) };
      if (destination) copyFileSync(source, destination);
    }
  }
  return result;
}
function packageRoot(name) {
  let directory = dirname(realpathSync(require.resolve(name)));
  for (;;) {
    const candidate = resolve(directory, "package.json");
    if (existsSync(candidate) && JSON.parse(readFileSync(candidate, "utf8")).name === name) return directory;
    const parent = dirname(directory); check("dependency_package_root", parent !== directory); directory = parent;
  }
}
function safeError(error) {
  return { stage, type: ["AssertionError", "TimeoutError", "TypeError", "SyntaxError"].includes(error?.name) ? error.name : "Error",
    source_lines: [...String(error?.stack || "").matchAll(/theme_preferences_native_frontend_qa\.mjs:(\d+):(\d+)/g)].map(match => ({ line: Number(match[1]), column: Number(match[2]) })),
    ...(labels.has(error?.message) ? { assertion: error.message } : {}) };
}

async function prepare() {
  check("fresh_output", !existsSync(output)); mkdirSync(output); createdOutput = true; stage = "prepare_root_build_binding";
  const build = JSON.parse(readFileSync(buildReceipt, "utf8")), products = JSON.parse(readFileSync(productPins, "utf8"));
  check("root_v3_frontend_build_passed", build.schema === "query-fallback49-frontend-build@1" && build.state === "passed" && build.source_drift.length === 0
    && ["web-typecheck", "desktop-typecheck", "mobile-typecheck", "desktop-vite-build", "mobile-vite-build"].every(name => build.checks.some(item => item.name === name && item.exit_code === 0)));
  const paths = [import.meta.filename, process.execPath, buildReceipt, productPins, resolve(root, "package-lock.json"), resolve(root, "package.json"), resolve(root, "tsconfig.json")];
  for (const [name, value] of Object.entries(products)) { const path = resolve(root, name); check("product_v3_matches_live", equal(file(path), value)); paths.push(path); }
  for (const [name, digest] of Object.entries(build.source_sha256)) { const path = resolve(root, name); check("build_sources_match_live", file(path).sha256 === digest); paths.push(path); }
  const sources = ["apps/desktop/src", "apps/mobile/src", "apps/web/components", "packages/api-client/src", "packages/domain-types/src", "packages/native-client/src"].map(name => resolve(root, name));
  const dependencies = ["react", "react-dom", "@tauri-apps/api", "@capacitor/core"].map(packageRoot);
  const trackedTrees = Object.fromEntries([...sources, ...dependencies].map(path => [path, tree(path)]));
  for (const [base, entries] of Object.entries(trackedTrees)) paths.push(...Object.keys(entries).map(name => resolve(base, name)));
  for (const host of ["desktop", "mobile"]) paths.push(...["package.json", "tsconfig.json", "vite.config.ts"].map(name => resolve(root, `apps/${host}/${name}`)));
  paths.push(resolve(root, "apps/web/app/globals.css"), resolve(root, "scripts/offline-host-build.mjs"));
  const info = JSON.parse(readFileSync(resolve(playwrightRoot, "package.json"), "utf8"));
  check("reviewed_playwright_163", info.name === "playwright-core" && info.version === "1.63.0");
  const inputs = snapshot(paths), dist = {};
  for (const host of ["desktop", "mobile"]) {
    const bound = build[`${host}_dist`];
    check("root_dist_identity", resolve(bound.absolute_path) === distRoots[host] && bound.embedded_host_build_verified === true);
    const expected = Object.fromEntries(bound.files.map(item => [item.path, { bytes: item.byte_count, sha256: item.sha256 }]));
    dist[host] = tree(distRoots[host]); check("root_dist_exact_bytes", equal(dist[host], expected));
    check("private_dist_copy", equal(tree(distRoots[host], resolve(output, `${host}-dist`)), dist[host]) && equal(tree(resolve(output, `${host}-dist`)), dist[host]));
  }
  const runtime = { playwright: runtimeManifest(playwrightRoot), browser: runtimeManifest(browserRoot, undefined, true) };
  check("prepare_inputs_stable", equal(snapshot(Object.keys(inputs)), inputs));
  save("prepare.json", { schema: "theme-preferences-native-frontend-qa@1", output, node: realpathSync(process.execPath), inputs, tracked_trees: trackedTrees, dist, runtime, origins,
    root_build: { path: buildReceipt, sha256: file(buildReceipt).sha256 }, product_pins_v3: { path: productPins, sha256: file(productPins).sha256 },
    scope: "actual Root-bound desktop/mobile Vite dist; no-bridge connection pages and explicitly synthetic Tauri/Capacitor frontend paths",
    browser: { playwright: "1.63.0", chromium_revision: "1243", headless: true, test_timeout_ms: 300000, close_timeout_ms: 10000 },
    runtime_manifest: { schema: "runtime-entries@1", includes_directories: true, excluded_source_browser_output: "chrome-headless-shell-win64/debug.log", prelaunch_browser_copy_omits_same_output: true },
    generated_private_browser_sidecars: { pattern: "^chrome-headless-shell-win64/(?:debug\\.log|chrome-headless-shell\\.\\d{8}-\\d{6}-\\d{3}\\.log)$", maximum_count: 4, minimum_bytes: 1, maximum_bytes: 1048576 },
    no_fixture_http_listener: true, no_api_sqlite_provider_service: true, native_acceptance: false, titlebar_android_bars_pwa_wcag_acceptance: false,
    preparation_only: "pins and copies existing Root-built dist; does not rebuild or rerun typechecks" });
  console.log(JSON.stringify({ prepared_not_launched: true, output, prepare_sha256: file(resolve(output, "prepare.json")).sha256, input_count: Object.keys(inputs).length }));
}

/** Runs before the unmodified production bundle. Every native value below is synthetic. */
function instrumentation(options) {
  const key = "tire-theme-v1", get = Storage.prototype.getItem, set = Storage.prototype.setItem;
  if (!get.call(sessionStorage, "theme-native-qa-seeded")) {
    if (options.seed === null) localStorage.removeItem(key); else set.call(localStorage, key, options.seed);
    set.call(sessionStorage, "theme-native-qa-seeded", "yes");
  }
  const qa = { synthetic: options.bridge !== "none", bridge: options.bridge, reads: 0, writes: 0, media: { adds: 0, removes: 0, active: 0, maximum: 0 },
    ipc: [], api: [], themeCalls: [], expectedDenials: [], unexpected: [], mutationAttempts: 0, providerAttempts: 0 };
  window.nativeThemeQA = qa;
  Storage.prototype.getItem = function (name) { if (name === key) qa.reads++; return get.call(this, name); };
  Storage.prototype.setItem = function (name, value) { if (name === key) qa.writes++; return set.call(this, name, value); };
  const match = window.matchMedia.bind(window);
  window.matchMedia = query => {
    const media = match(query); if (query !== "(prefers-color-scheme: dark)") return media;
    const listeners = new Set(), add = media.addEventListener.bind(media), remove = media.removeEventListener.bind(media);
    media.addEventListener = (type, callback, config) => { if (type === "change" && callback && !listeners.has(callback)) { listeners.add(callback); qa.media.adds++; qa.media.active++; qa.media.maximum = Math.max(qa.media.maximum, qa.media.active); } return add(type, callback, config); };
    media.removeEventListener = (type, callback, config) => { if (type === "change" && listeners.delete(callback)) { qa.media.removes++; qa.media.active--; } return remove(type, callback, config); };
    return media;
  };
  if (options.noResizeObserver) Object.defineProperty(window, "ResizeObserver", { configurable: true, value: undefined });
  const forbidden = (kind, command) => { qa.unexpected.push({ kind, command: /^[a-zA-Z_]{1,64}$/.test(command) ? command : "other" }); throw Error("synthetic_bridge_forbidden"); };
  if (options.bridge === "capacitor-synthetic") {
    window.androidBridge = {};
    window.Capacitor = {
      PluginHeaders: [{ name: "TireNative", methods: [{ name: "setSystemTheme", rtype: "promise" }, { name: "status", rtype: "promise" }, { name: "addListener", rtype: "callback" }, { name: "removeListener", rtype: "promise" }] }],
      async nativePromise(plugin, method, args) {
        if (plugin !== "TireNative") return forbidden("plugin", "other"); qa.ipc.push(method);
        if (method === "setSystemTheme") {
          if (!args || Object.keys(args).length !== 1 || !["light", "dark"].includes(args.theme)) return forbidden("native_brightness", method);
          qa.themeCalls.push({ theme: args.theme, palette: document.documentElement.dataset.theme, preference: document.documentElement.dataset.themePreference, synthetic: true, rejected: !!options.rejectTheme });
          if (options.rejectTheme) throw { code: "INVALID_THEME" }; return {};
        }
        if (method === "status") { qa.expectedDenials.push("synthetic_mobile_status_unavailable"); throw { code: "MOBILE_UNAVAILABLE" }; }
        if (method === "removeListener") return {};
        return forbidden("capacitor_method", method);
      },
      nativeCallback(plugin, method, args) {
        if (plugin !== "TireNative" || method !== "addListener" || !["backRequested", "resume"].includes(args?.eventName)) return Promise.reject(forbidden("capacitor_callback", method));
        qa.ipc.push(method); return Promise.resolve(`synthetic-${args.eventName}`);
      },
    };
  }
  if (options.bridge !== "tauri-synthetic") return;
  const instant = "2026-10-22T00:00:00.000Z";
  const slot = { slot_id: "theme-ui-only-slot", generation: 1, package_id: "theme-ui-only-empty-material", sha256: "0".repeat(64), byte_count: 0,
    title: "主题验证合成本地资料槽", created_at: instant, installed_at: instant, privacy_class: "private", owner_scope_id: "theme-ui-only-owner", locked: false, previous_owner: false,
    counts: { garage_profiles: 0, watch_items: 0, recent_queries: 0, distinct_evidence: 0, searchable_documents: 1 } };
  const record = { id: "theme-ui-only-document", category: "evidence", kind: "tire", member_key: "theme-ui-only-member", context_id: null, record_index: null,
    title: "仅用于显示本机问题字段的空载荷", text: "Synthetic UI fixture; no tire facts.", facets: { brand: null, model: null, size: null, source_id: null, campaign_number: null },
    membership: ["explicit"], privacy_class: "private", observed_at: instant, verified_at: null };
  const gets = {
    "/health": { status: "ok", service: "synthetic-read-only", version: "synthetic" },
    "/v1/auth/me": { authenticated: false, user: null }, "/v1/sources": { sources: [] }, "/v1/watchlists": { items: [] },
    "/v1/source-settings": { scope: "local_workspace", items: [], total: 0, notice: "Synthetic UI-only empty source directory" },
    "/v1/tire-query-filters": { version: "tire-query-filters@1", max_conditions: 16, fields: [{ key: "brand", label: "品牌", type: "text", operators: ["eq", "is_known", "is_unknown"] }], notice: "Synthetic filter metadata; no query" },
  };
  window.isTauri = true;
  window.__TAURI_INTERNALS__ = {
    async invoke(command, args) {
      qa.ipc.push(command);
      if (command === "desktop_status") return { api_base_url: "http://127.0.0.1:18986/", session_persistent: true, session_store: "os_secure_store", version: "synthetic-theme-qa" };
      if (command === "api_cancel") return null;
      if (command === "offline_sync_revalidate") { qa.expectedDenials.push("synthetic_sync_revalidation_disabled"); throw "NATIVE_COMMAND_UNAVAILABLE"; }
      if (command === "api_request") {
        const request = args?.request;
        if (request?.method !== "GET" || request.body_base64 !== undefined) { qa.mutationAttempts++; return forbidden("api_mutation", command); }
        if (typeof request.path !== "string" || !Object.hasOwn(gets, request.path)) {
          if (/ai|embedding|provider/.test(request?.path || "")) qa.providerAttempts++;
          return forbidden("api_route", command);
        }
        qa.api.push({ method: "GET", path: request.path, synthetic: true });
        const bytes = new TextEncoder().encode(JSON.stringify(gets[request.path]));
        return { status: 200, headers: { "content-type": "application/json; charset=utf-8" }, body_base64: btoa(String.fromCharCode(...bytes)) };
      }
      if (command === "device_ai_read_journal") return { schema: "device-ai-journal@1", owner: "synthetic", generation: 1, session_id: "00000000-0000-4000-8000-000000000001", length: 0, entries: [], verification: { ok: true, length: 0, violations: [], cross_session_entries: [] } };
      if (command === "offline_list") return { schema: "offline-host@1", data_state: "local_snapshot", profile_id: "synthetic-theme-profile", owner_epoch: 1, items: [slot] };
      if (command === "offline_search" && args?.request?.slot_id === slot.slot_id && args.request.expected_generation === 1 && args.request.kind === "tire") return { data_state: "local_snapshot", slot, items: [record], total: 1, offset: 0, limit: 20, has_more: false };
      if (command === "offline_read" && args?.request?.slot_id === slot.slot_id && args.request.expected_generation === 1 && args.request.document_id === record.id) return { data_state: "local_snapshot", slot, document: record, context: null,
        member: { key: "theme-ui-only-member", reference: { kind: "tire", snapshot_id: "theme-ui-only-snapshot", variant_id: "theme-ui-only-variant", verification_id: "theme-ui-only-verification" }, member_reasons: [], privacy_class: "private", raw_included: false,
          source: { source_id: null, source_url: null, raw_hash: null, parser_version: null, parser_identity: null, observed_at: instant, verified_at: null, verification_id: null }, payload: {} } };
      if (/prepare|submit|append|save|reset|remove|install|revoke|apply|run/.test(command)) qa.mutationAttempts++;
      return forbidden("tauri_command", command);
    },
    transformCallback() { return forbidden("tauri_callback", "transformCallback"); }, unregisterCallback() { return forbidden("tauri_callback", "unregisterCallback"); },
  };
}

async function run() {
  check("regular_output", lstatSync(output).isDirectory() && !lstatSync(output).isSymbolicLink());
  check("reviewed_prepare", /^[a-f0-9]{64}$/.test(reviewedSha || "") && file(resolve(output, "prepare.json")).sha256 === reviewedSha);
  const prepared = JSON.parse(readFileSync(resolve(output, "prepare.json"), "utf8"));
  check("prepared_identity", prepared.schema === "theme-preferences-native-frontend-qa@1" && prepared.output === output && prepared.node === realpathSync(process.execPath) && equal(prepared.origins, origins)
    && prepared.runtime_manifest?.schema === "runtime-entries@1" && prepared.runtime_manifest.includes_directories === true && prepared.runtime_manifest.excluded_source_browser_output === "chrome-headless-shell-win64/debug.log");
  const stable = () => equal(snapshot(Object.keys(prepared.inputs)), prepared.inputs)
    && Object.entries(prepared.tracked_trees).every(([base, entries]) => equal(tree(base), entries))
    && ["desktop", "mobile"].every(host => equal(tree(distRoots[host]), prepared.dist[host]) && equal(tree(resolve(output, `${host}-dist`)), prepared.dist[host]));
  check("prepared_inputs", stable()); check("single_use_run", !existsSync(resolve(output, "result.json")) && !existsSync(resolve(output, "runtime")));
  receipt = { schema: prepared.schema, state: "running", scope: prepared.scope, started_utc: new Date().toISOString(), checks: [], screenshots: [], computed: [], scenarios: [], unexpected_requests: [], page_errors: [], console_errors: [], cleanup_failures: [],
    browser: { playwright: "1.63.0", chromium_revision: "1243", headless: true, forced_kill_requested: false },
    fixture_http_listener: false, api_sqlite_provider_service: false, real_native_verified: false, tauri_ipc: "synthetic-only", capacitor_bridge: "synthetic-only",
    desktop_titlebar_verified: false, android_system_bars_verified: false, mobile_ai_portal_verified: false, pwa_chrome_verified: false, complete_wcag_verified: false };
  const persist = () => save("result.json", receipt), contexts = new Set();
  let timedOut = false, browserServer, browserProcess, browser, deadline;
  const checked = name => { check("suite_active", !timedOut); receipt.checks.push(name); persist(); };
  const privatePlaywright = resolve(output, "runtime/playwright-core"), privateBrowser = resolve(output, "runtime/chromium_headless_shell-1243"); persist();
  try {
    stage = "private_runtime_copy";
    for (const name of ["runtime", "tmp", "downloads"]) mkdirSync(resolve(output, name));
    check("source_runtimes_pinned", equal(runtimeManifest(playwrightRoot), prepared.runtime.playwright) && equal(runtimeManifest(browserRoot, undefined, true), prepared.runtime.browser));
    check("private_runtime_copies", equal(runtimeManifest(playwrightRoot, privatePlaywright), prepared.runtime.playwright) && equal(runtimeManifest(browserRoot, privateBrowser, true), prepared.runtime.browser)
      && equal(runtimeManifest(privatePlaywright), prepared.runtime.playwright) && equal(runtimeManifest(privateBrowser, undefined, true), prepared.runtime.browser));
    const { chromium } = await import(pathToFileURL(resolve(privatePlaywright, "index.mjs")).href); stage = "browser_start";
    const privateTemp = resolve(output, "tmp");
    browserServer = await chromium.launchServer({ executablePath: resolve(privateBrowser, browserExe), headless: true, host: "127.0.0.1", port: 0, artifactsDir: privateTemp, downloadsPath: resolve(output, "downloads"), timeout: 20000,
      env: { ...process.env, TEMP: privateTemp, TMP: privateTemp, TMPDIR: privateTemp }, args: ["--no-first-run", "--disable-background-networking", "--disable-breakpad", "--disable-crash-reporter", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"] });
    browserProcess = browserServer.process(); receipt.browser.pid = browserProcess.pid;
    browserServer.once("close", () => { receipt.browser.server_close_observed = true; });
    browserProcess.once("exit", (code, signal) => { receipt.browser.exit_code = code; receipt.browser.exit_signal = signal; });
    browser = await chromium.connect(browserServer.wsEndpoint());
    const body = Object.fromEntries(["desktop", "mobile"].map(host => [host, Object.fromEntries(Object.keys(prepared.dist[host]).map(name => ["/" + name, readFileSync(resolve(output, `${host}-dist`, name))]))]));
    const metrics = page => page.evaluate(() => { const qa = window.nativeThemeQA; return { synthetic: qa.synthetic, bridge: qa.bridge, reads: qa.reads, writes: qa.writes, media: qa.media, ipc: qa.ipc, api: qa.api, themeCalls: qa.themeCalls, expectedDenials: qa.expectedDenials, unexpected: qa.unexpected, mutationAttempts: qa.mutationAttempts, providerAttempts: qa.providerAttempts }; });
    const fresh = async (host, config = {}) => {
      check("suite_active", !timedOut);
      const options = { seed: null, bridge: "none", colorScheme: "dark", width: host === "desktop" ? 1200 : 390, noResizeObserver: false, rejectTheme: false, ...config };
      const context = await browser.newContext({ serviceWorkers: "block", colorScheme: options.colorScheme, viewport: { width: options.width, height: 720 } }); contexts.add(context);
      await context.addInitScript(instrumentation, options);
      await context.routeWebSocket("**/*", socket => { receipt.unexpected_requests.push({ kind: "websocket", host }); socket.close(); });
      await context.route("**/*", async route => {
        const request = route.request(), url = new URL(request.url());
        const pathname = url.pathname === "/" ? "/index.html" : url.pathname;
        if (request.method() === "GET" && url.origin === origins[host] && !url.search && !url.hash) {
          if (Object.hasOwn(body[host], pathname)) { const type = pathname.endsWith(".html") ? "text/html; charset=utf-8" : pathname.endsWith(".js") ? "text/javascript; charset=utf-8" : pathname.endsWith(".css") ? "text/css; charset=utf-8" : "image/x-icon"; await route.fulfill({ contentType: type, body: body[host][pathname] }); return; }
          if (pathname === "/favicon.ico") { await route.fulfill({ status: 204 }); return; }
        }
        receipt.unexpected_requests.push({ host, method: ["GET", "POST"].includes(request.method()) ? request.method() : "other", origin: url.origin === origins[host] ? "virtual-static" : "other", route: "blocked" }); await route.abort();
      });
      const page = await context.newPage(); page.setDefaultTimeout(9000);
      page.on("pageerror", error => receipt.page_errors.push({ host, type: ["TypeError", "SyntaxError"].includes(error.name) ? error.name : "PageError" }));
      page.on("console", event => { if (event.type() === "error") receipt.console_errors.push({ host, type: "browser_console_error" }); });
      await page.goto(origins[host] + "/#/query", { waitUntil: "load" });
      await page.locator(host === "desktop" ? ".desktop-root" : ".mobile-native-root").waitFor();
      await page.locator(host === "desktop" && options.bridge === "tauri-synthetic" ? ".desktop-connection.ready" : host === "desktop" ? ".desktop-connection.failed" : ".mobile-connection.failed").waitFor();
      return { page, context, options, host, close: async name => { receipt.scenarios.push({ name, host, options, observation: await metrics(page) }); await context.close(); contexts.delete(context); persist(); } };
    };
    const settle = page => page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    const appearance = async (page, preference, palette) => {
      await page.waitForFunction(value => document.documentElement.dataset.themePreference === value.preference && document.documentElement.dataset.theme === value.palette, { preference, palette });
      check("actual_color_scheme", await page.evaluate(value => document.documentElement.style.colorScheme === value, palette === "light" ? "light" : "dark")); await settle(page);
    };
    const control = (page, host) => page.locator(host === "desktop" ? ".desktop-bar [data-theme-preference-control] select" : ".mobile-connection-bar [data-theme-preference-control] select");
    const choose = (page, host, value) => control(page, host).selectOption(value);
    const screenshot = async (page, name, fullPage = false) => { await page.screenshot({ path: resolve(output, name), fullPage }); receipt.screenshots.push(name); persist(); };
    const retryButton = (page, host) => page.locator(host === "desktop" ? ".desktop-retry" : ".mobile-connect-screen button.mobile-primary");
    const retryAppearance = (page, host) => retryButton(page, host).evaluate(node => {
      const style = getComputedStyle(node), box = node.getBoundingClientRect();
      const transparent = color => color === "transparent" || /^rgba\([^)]*,\s*0(?:\.0+)?\)$/.test(color);
      let ancestor = node.parentElement, adjacentBackground = getComputedStyle(document.documentElement).backgroundColor;
      while (ancestor) { const color = getComputedStyle(ancestor).backgroundColor; if (!transparent(color)) { adjacentBackground = color; break; } ancestor = ancestor.parentElement; }
      return { text: node.textContent.trim(), enabled: !node.disabled, foreground: style.color, background: style.backgroundColor, adjacentBackground, forcedColorAdjust: style.forcedColorAdjust,
        visible: node.getClientRects().length > 0 && box.width > 0 && box.height > 0 && style.display !== "none" && style.visibility === "visible" && parseFloat(style.opacity) >= .99,
        borders: ["Top", "Right", "Bottom", "Left"].map(side => ({ color: style[`border${side}Color`], style: style[`border${side}Style`], width: parseFloat(style[`border${side}Width`]) })) };
    });
    const layout = async page => {
      await page.waitForFunction(() => { const root = document.querySelector(".desktop-root"), header = document.querySelector(".desktop-bar"); return root && header && Math.abs(parseFloat(root.style.getPropertyValue("--desktop-header-height")) - header.getBoundingClientRect().height) < .5; });
      return page.evaluate(() => { const header = document.querySelector(".desktop-bar"), sidebar = document.querySelector(".sidebar"), box = header.getBoundingClientRect(); return {
        width: innerWidth, viewportHeight: innerHeight, headerHeight: box.height, headerBottom: box.bottom, headerTop: box.top,
        value: parseFloat(document.querySelector(".desktop-root").style.getPropertyValue("--desktop-header-height")),
        rows: new Set([...header.children].map(node => { const child = node.getBoundingClientRect(); return Math.round(child.top + child.height / 2); })).size,
        sidebarTop: sidebar?.getBoundingClientRect().top ?? null, sidebarOffset: sidebar ? parseFloat(getComputedStyle(sidebar).top) : null,
        sidebarHeight: sidebar ? parseFloat(getComputedStyle(sidebar).height) : null, scrollY, documentScroll: document.scrollingElement.scrollTop,
        workspaceScroll: document.querySelector(".workspace")?.scrollTop ?? null, workspaceOverflow: document.querySelector(".workspace") ? getComputedStyle(document.querySelector(".workspace")).overflowY : null,
      }; });
    };
    const suite = async () => {
      stage = "no_bridge_actual_dist";
      for (const host of ["desktop", "mobile"]) {
        const current = await fresh(host), page = current.page; await appearance(page, "system", "dark");
        const initial = await metrics(page); check("no_bridge_system_initial_no_storage_write_single_owner", initial.writes === 0 && initial.media.active === 1 && initial.media.maximum === 1 && !initial.synthetic);
        await page.emulateMedia({ colorScheme: "light" }); await appearance(page, "system", "light");
        check("system_media_does_not_persist_palette", await page.evaluate(() => localStorage.getItem("tire-theme-v1") === null && window.nativeThemeQA.writes === 0));
        for (const preference of ["light", "dark", "high-contrast", "system"]) {
          await choose(page, host, preference); await page.emulateMedia({ colorScheme: "dark" });
          await appearance(page, preference, preference === "system" ? "dark" : preference);
          check("canonical_preference_saved", await page.evaluate(value => localStorage.getItem("tire-theme-v1") === value, preference));
          await page.reload({ waitUntil: "load" }); await appearance(page, preference, preference === "system" ? "dark" : preference);
          check("reload_keeps_saved_preference", await control(page, host).inputValue() === preference);
          if (preference !== "system") { await page.emulateMedia({ colorScheme: "light" }); await appearance(page, preference, preference); check("explicit_native_host_has_no_system_listener", (await metrics(page)).media.active === 0); }
        }
        const settings = host === "desktop" ? page.locator(".desktop-settings > div") : page.getByRole("dialog", { name: "连接与安全会话", exact: true });
        await (host === "desktop" ? page.locator(".desktop-settings > summary") : page.locator(".mobile-connection-bar").getByRole("button", { name: "连接与会话", exact: true })).click();
        await settings.waitFor(); const focus = settings.getByRole("button").first(); await focus.focus();
        await settings.evaluate(node => { window.qaSettingsNode = node; window.qaSettingsFocus = document.activeElement; });
        await page.emulateMedia({ colorScheme: "light" }); await appearance(page, "system", "light");
        check("open_native_settings_live_media_same_node_focus", await settings.evaluate(node => node === window.qaSettingsNode && document.activeElement === window.qaSettingsFocus));
        await screenshot(page, `${host}-no-bridge-settings-light.png`);
        if (host === "desktop") await page.locator(".desktop-settings > summary").click(); else await settings.getByRole("button", { name: "关闭", exact: true }).click();
        await current.close(`${host}-actual-dist-no-bridge-four-preferences-reload-system-settings`); checked(`${host}_actual_dist_connection_page_four_preferences_reload_and_open_settings_media`);
      }
      stage = "host_high_contrast_narrow";
      for (const host of ["desktop", "mobile"]) for (const width of [390, 320]) {
        const current = await fresh(host, { width, seed: "high-contrast" }), page = current.page; await appearance(page, "high-contrast", "high-contrast");
        await control(page, host).focus(); await page.keyboard.press("Tab"); await page.keyboard.press("Shift+Tab");
        const computed = await page.evaluate(host => {
          const root = getComputedStyle(document.documentElement), select = document.querySelector(host === "desktop" ? ".desktop-bar select" : ".mobile-connection-bar select"), style = getComputedStyle(select), box = select.getBoundingClientRect();
          const panel = document.querySelector(host === "desktop" ? ".desktop-connect-card" : ".mobile-connect-error"), panelStyle = getComputedStyle(panel);
          return { width: innerWidth, scrollWidth: document.documentElement.scrollWidth, rootColor: root.color, rootBackground: root.backgroundColor, selectColor: style.color, selectBackground: style.backgroundColor,
            outlineColor: style.outlineColor, outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth, focusVisible: select.matches(":focus-visible"), left: box.left, right: box.right,
            panelBorder: panelStyle.borderTopColor, panelBorderStyle: panelStyle.borderTopStyle, panelBorderWidth: panelStyle.borderTopWidth };
        }, host);
        const luminance = value => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number).map(part => { const v = part / 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }).reduce((sum, part, index) => sum + part * [.2126, .7152, .0722][index], 0);
        const contrast = (a, b) => { const values = [luminance(a), luminance(b)].sort((x, y) => y - x); return (values[0] + .05) / (values[1] + .05); };
        computed.contrast = { body: contrast(computed.rootColor, computed.rootBackground), select: contrast(computed.selectColor, computed.selectBackground), focus: contrast(computed.outlineColor, computed.selectBackground), border: contrast(computed.panelBorder, computed.rootBackground) };
        computed.retry = await retryAppearance(page, host);
        computed.retry.textContrast = contrast(computed.retry.foreground, computed.retry.background);
        computed.retry.borderContrasts = computed.retry.borders.map(border => contrast(border.color, computed.retry.adjacentBackground));
        check("native_host_hc_local_contrast_and_focus", computed.contrast.body >= 4.5 && computed.contrast.select >= 4.5 && computed.contrast.focus >= 3 && computed.contrast.border >= 3 && computed.panelBorderStyle !== "none" && parseFloat(computed.panelBorderWidth) > 0 && computed.focusVisible && computed.outlineStyle !== "none" && parseFloat(computed.outlineWidth) > 0);
        check("native_host_hc_retry_actual_text_and_visible_border", computed.retry.text === "重新检查连接" && computed.retry.enabled && computed.retry.visible && computed.retry.textContrast >= 4.5
          && computed.retry.borders.every(border => border.style !== "none" && border.style !== "hidden" && border.width > 0) && computed.retry.borderContrasts.every(ratio => ratio >= 3));
        check("native_host_320_390_no_overall_overflow", computed.scrollWidth <= width && computed.left >= 0 && computed.right <= width); receipt.computed.push({ host, mode: "high-contrast", ...computed });
        await screenshot(page, `${host}-high-contrast-${width}.png`, true);
        await page.emulateMedia({ forcedColors: "active" }); await settle(page);
        const forced = await control(page, host).evaluate(node => { const style = getComputedStyle(node); return { active: matchMedia("(forced-colors: active)").matches, forcedColorAdjust: style.forcedColorAdjust, outline: style.outlineStyle, width: style.outlineWidth }; });
        check("native_host_forced_colors_auto_visible_focus", forced.active && forced.forcedColorAdjust !== "none" && forced.outline !== "none" && parseFloat(forced.width) > 0);
        forced.retry = await retryAppearance(page, host);
        forced.retry.textContrast = contrast(forced.retry.foreground, forced.retry.background);
        forced.retry.borderContrasts = forced.retry.borders.map(border => contrast(border.color, forced.retry.adjacentBackground));
        check("native_host_forced_colors_retry_actual_text_border_auto", forced.retry.text === "重新检查连接" && forced.retry.enabled && forced.retry.visible && forced.retry.forcedColorAdjust === "auto" && forced.retry.textContrast >= 4.5
          && forced.retry.borders.every(border => border.style !== "none" && border.style !== "hidden" && border.width > 0) && forced.retry.borderContrasts.every(ratio => ratio >= 3));
        receipt.computed.push({ host, width, mode: "forced-colors", ...forced });
        await screenshot(page, `${host}-forced-colors-${width}.png`, true);
        const retryShot = `${host}-retry-forced-colors-${width}.png`; await retryButton(page, host).screenshot({ path: resolve(output, retryShot) }); receipt.screenshots.push(retryShot); persist();
        await current.close(`${host}-hc-forced-${width}`);
      }
      checked("both_actual_dist_320_390_hc_local_computed_borders_keyboard_focus_forced_colors");
      stage = "desktop_resize_fallback";
      const fallback = await fresh("desktop", { seed: "high-contrast", noResizeObserver: true });
      await appearance(fallback.page, "high-contrast", "high-contrast"); const fallbackBefore = await layout(fallback.page);
      await fallback.page.setViewportSize({ width: 320, height: 640 }); const fallbackAfter = await layout(fallback.page);
      check("desktop_missing_resizeobserver_window_resize_fallback", Math.abs(fallbackAfter.value - fallbackAfter.headerHeight) < .5 && fallbackAfter.headerHeight > fallbackBefore.headerHeight && fallbackAfter.rows >= 2);
      receipt.computed.push({ mode: "desktop-no-resizeobserver", before: fallbackBefore, after: fallbackAfter }); await fallback.close("desktop-no-resizeobserver-fallback"); checked("desktop_actual_dist_initial_and_window_resize_fallback");
      stage = "desktop_synthetic_tauri_actual_app";
      const desktop = await fresh("desktop", { bridge: "tauri-synthetic" }), page = desktop.page;
      await appearance(page, "system", "dark"); await page.locator('.app-shell[data-theme="dark"]').waitFor();
      check("synthetic_tauri_workbench_reuses_outer_provider", (await metrics(page)).media.active === 1 && (await metrics(page)).media.maximum === 1);
      check("host_and_workbench_controls_have_distinct_labels_ids", await page.evaluate(() => { const selects = [...document.querySelectorAll("[data-theme-preference-control] select")]; return selects.length === 2 && new Set(selects.map(node => node.id)).size === 2 && selects.every(node => node.labels.length === 1 && node.labels[0].textContent === "主题" && node.value === "system"); }));
      const wide = await layout(page); await page.setViewportSize({ width: 900, height: 640 });
      for (const preference of ["light", "dark", "high-contrast"]) {
        await choose(page, "desktop", preference); await appearance(page, preference, preference); const box = await layout(page);
        check("desktop_wrapped_header_sidebar_offsets_match", box.rows >= 2 && box.headerHeight >= wide.headerHeight && Math.abs(box.sidebarOffset - box.headerHeight) < .5 && Math.abs(box.sidebarHeight - (box.viewportHeight - box.headerHeight)) < 1);
        await page.locator(".desktop-settings > summary").click();
        const settings = await page.locator(".desktop-settings > div").boundingBox();
        check("desktop_settings_below_actual_header", settings && settings.y >= box.headerBottom - 2); receipt.computed.push({ mode: "synthetic-desktop-layout", preference, ...box, settingsTop: settings.y });
        if (preference === "high-contrast") await screenshot(page, "desktop-synthetic-hc-wrapped-settings-900.png");
        await page.locator(".desktop-settings > summary").click();
      }
      await page.mouse.wheel(0, 650); await page.waitForFunction(() => scrollY > 20); const scrolled = await layout(page);
      check("desktop_window_scroll_and_sticky_sidebar_below_header", scrolled.scrollY === scrolled.documentScroll && scrolled.workspaceScroll === 0 && scrolled.workspaceOverflow !== "auto" && scrolled.sidebarTop >= scrolled.headerBottom - 2);
      receipt.computed.push({ mode: "synthetic-desktop-window-scroll", ...scrolled }); await screenshot(page, "desktop-synthetic-window-scroll-900.png");
      await page.setViewportSize({ width: 390, height: 640 }); await settle(page); await page.mouse.wheel(0, 500); await page.waitForFunction(() => scrollY > 20);
      await page.getByRole("navigation", { name: "移动导航", exact: true }).getByRole("button", { name: "查询", exact: true }).click();
      await page.waitForFunction(() => location.hash === "#/query" && scrollY < 2); check("desktop_narrow_navigation_still_scrolls_window", await page.evaluate(() => document.querySelector(".workspace").scrollTop === 0));
      await page.setViewportSize({ width: 980, height: 420 });
      await choose(page, "desktop", "system"); await page.emulateMedia({ colorScheme: "dark" }); await appearance(page, "system", "dark");
      await page.locator(".desktop-bar").getByRole("button", { name: "设备 AI 分析", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "设备 AI 分析", exact: true }); await dialog.waitFor();
      await dialog.getByRole("button", { name: /主题验证合成本地资料槽/ }).click(); await dialog.getByRole("button", { name: /仅用于显示本机问题字段的空载荷/ }).click();
      const field = dialog.locator("#desktop-device-ai-question"); await field.fill("synthetic desktop theme retention"); await field.focus();
      await dialog.evaluate(node => { window.qaPortalNode = node; window.qaPortalField = document.activeElement; node.scrollTop = Math.min(60, node.scrollHeight - node.clientHeight); window.qaPortalScroll = node.scrollTop; });
      check("desktop_real_dialog_scroll_precondition", await dialog.evaluate(() => window.qaPortalScroll > 0)); const beforeMedia = await metrics(page);
      for (const palette of ["light", "dark"]) {
        await page.emulateMedia({ colorScheme: palette }); await appearance(page, "system", palette);
        check("desktop_actual_open_ai_portal_retains_dom_focus_scroll_field", await dialog.evaluate((node, expected) => node === window.qaPortalNode && node.parentElement.parentElement === document.body && node.parentElement.dataset.theme === expected
          && document.activeElement === window.qaPortalField && window.qaPortalField.value === "synthetic desktop theme retention" && node.scrollTop === window.qaPortalScroll, palette));
      }
      check("desktop_ai_theme_media_does_not_trigger_business_requests", equal((await metrics(page)).api, beforeMedia.api)); await screenshot(page, "desktop-synthetic-real-ai-question-dark.png");
      await dialog.getByRole("button", { name: "关闭", exact: true }).click(); await dialog.waitFor({ state: "detached" }); await desktop.close("actual-desktop-app-synthetic-tauri-readonly-ai-empty-material");
      checked("actual_desktop_app_synthetic_ipc_wrapped_layout_window_scroll_open_ai_dom_focus_value_scroll_media");
      stage = "mobile_synthetic_brightness_contract";
      for (const rejectTheme of [false, true]) {
        const current = await fresh("mobile", { bridge: "capacitor-synthetic", rejectTheme }), view = current.page; await appearance(view, "system", "dark");
        await view.waitForFunction(() => window.nativeThemeQA.themeCalls.length >= 1); check("synthetic_mobile_no_placeholder_light", (await metrics(view)).themeCalls[0].theme === "dark");
        await choose(view, "mobile", "light"); await appearance(view, "light", "light"); await view.waitForFunction(() => window.nativeThemeQA.themeCalls.at(-1)?.theme === "light");
        await choose(view, "mobile", "high-contrast"); await appearance(view, "high-contrast", "high-contrast"); await view.waitForFunction(() => window.nativeThemeQA.themeCalls.at(-1)?.theme === "dark");
        const high = await metrics(view); check("synthetic_mobile_hc_maps_dark_two_value_single_argument", high.themeCalls.every(item => ["light", "dark"].includes(item.theme) && item.synthetic) && high.themeCalls.at(-1).palette === "high-contrast");
        await choose(view, "mobile", "system"); await view.emulateMedia({ colorScheme: "light" }); await appearance(view, "system", "light"); await view.waitForFunction(() => window.nativeThemeQA.themeCalls.at(-1)?.theme === "light");
        check("synthetic_bridge_rejection_keeps_preference_and_connection_state", await view.evaluate(() => localStorage.getItem("tire-theme-v1") === "system" && !document.documentElement.hasAttribute("data-mobile-theme") && !!document.querySelector(".mobile-connection.failed")));
        await screenshot(view, `mobile-synthetic-brightness-${rejectTheme ? "rejected" : "accepted"}.png`); await current.close(`mobile-synthetic-capacitor-brightness-${rejectTheme ? "rejected" : "accepted"}`);
      }
      checked("synthetic_capacitor_only_light_dark_hc_dark_system_updates_and_rejection_safety");
      check("no_unexpected_network_or_browser_errors", receipt.unexpected_requests.length === 0 && receipt.page_errors.length === 0 && receipt.console_errors.length === 0);
      check("no_unexpected_ipc_mutation_or_provider_attempts", receipt.scenarios.every(item => item.observation.unexpected.length === 0 && item.observation.mutationAttempts === 0 && item.observation.providerAttempts === 0));
    };
    await Promise.race([suite(), new Promise((_, reject) => { deadline = setTimeout(() => { timedOut = true; reject(Error("suite_deadline")); }, prepared.browser.test_timeout_ms); })]); receipt.state = "passed";
  } catch (error) { receipt.state = "failed"; receipt.failure = safeError(error); }
  finally {
    clearTimeout(deadline); stage = "cleanup"; let closeTimer;
    try {
      check("browser_started", !!browserServer && !!browserProcess);
      await Promise.race([(async () => { for (const context of contexts) { try { await context.close(); } catch { receipt.cleanup_failures.push("context_close_failed"); } } if (browser) await browser.close(); await browserServer.close(); })(),
        new Promise((_, reject) => { closeTimer = setTimeout(() => reject(Error("browser_close_timeout")), prepared.browser.close_timeout_ms); })]);
      receipt.browser.natural_close = browserProcess.exitCode === 0 && browserProcess.signalCode === null && receipt.browser.server_close_observed === true; check("browser_natural_terminal", receipt.browser.natural_close);
    } catch { receipt.cleanup_failures.push("browser_close_failed"); if (browserServer) { receipt.browser.forced_kill_requested = true; try { await browserServer.kill(); } catch { receipt.cleanup_failures.push("browser_kill_failed"); } } }
    finally { clearTimeout(closeTimer); }
    try { check("final_sources_dist_and_dependencies_stable", stable()); receipt.inputs_unchanged = true; } catch { receipt.inputs_unchanged = false; receipt.cleanup_failures.push("input_or_dist_drift"); }
    try {
      check("source_runtime_inputs_strictly_unchanged", equal(runtimeManifest(playwrightRoot), prepared.runtime.playwright) && equal(runtimeManifest(browserRoot, undefined, true), prepared.runtime.browser)); receipt.source_runtime_inputs_unchanged = true;
      check("private_playwright_strictly_unchanged", equal(runtimeManifest(privatePlaywright), prepared.runtime.playwright));
      const actual = runtimeManifest(privateBrowser), original = prepared.runtime.browser;
      check("prepared_private_browser_files_unchanged", Object.entries(original).every(([name, value]) => Object.hasOwn(actual, name) && equal(actual[name], value)));
      receipt.generated_runtime_sidecars = Object.entries(actual).filter(([name]) => !Object.hasOwn(original, name)).map(([name, value]) => ({ path: name, ...value }));
      check("only_bounded_generated_private_browser_log_sidecars", receipt.generated_runtime_sidecars.length <= 4 && receipt.generated_runtime_sidecars.every(item => item.kind === "file" && /^chrome-headless-shell-win64\/(?:debug\.log|chrome-headless-shell\.\d{8}-\d{6}-\d{3}\.log)$/.test(item.path) && item.bytes >= 1 && item.bytes <= 1048576));
      receipt.prepared_private_runtime_files_unchanged = true; receipt.private_browser_tree_unchanged = receipt.generated_runtime_sidecars.length === 0; receipt.runtime_inputs_unchanged = true;
    } catch { receipt.runtime_inputs_unchanged = false; receipt.cleanup_failures.push("runtime_drift_or_unexpected_sidecar"); }
    receipt.artifact_hashes = snapshot(receipt.screenshots.map(name => resolve(output, name)));
    if (receipt.cleanup_failures.length || !receipt.browser.natural_close || receipt.browser.forced_kill_requested) receipt.state = "failed";
    receipt.finished_utc = new Date().toISOString(); persist(); save("browsercleanup.json", { state: receipt.state, browser: receipt.browser, cleanup_failures: receipt.cleanup_failures, inputs_unchanged: receipt.inputs_unchanged,
      source_runtime_inputs_unchanged: receipt.source_runtime_inputs_unchanged, excluded_source_browser_output: prepared.runtime_manifest.excluded_source_browser_output,
      prepared_private_runtime_files_unchanged: receipt.prepared_private_runtime_files_unchanged, private_browser_tree_unchanged: receipt.private_browser_tree_unchanged,
      runtime_inputs_unchanged: receipt.runtime_inputs_unchanged, generated_runtime_sidecars: receipt.generated_runtime_sidecars });
  }
  console.log(JSON.stringify({ state: receipt.state, output, checks: receipt.checks.length, natural_close: receipt.browser.natural_close === true, inputs_unchanged: receipt.inputs_unchanged, failure: receipt.failure || null }));
  if (receipt.state !== "passed") process.exitCode = 3;
}

async function main() {
  check("usage", ["prepare", "run"].includes(action) && process.argv.length === (action === "prepare" ? 4 : 5) && typeof rawOutput === "string"); output = resolve(rawOutput);
  check("direct_fresh_artifact_slot", dirname(output) === resolve(root, ".artifacts") && /^theme-native-qa-[a-z0-9-]+$/.test(basename(output)));
  if (action === "prepare") await prepare(); else await run();
}
await main().catch(error => { const failure = safeError(error); if (createdOutput && !receipt) save("prepare-or-input-failure.json", { state: "failed", failure }); console.log(JSON.stringify({ state: "failed", failure })); process.exitCode = 3; });
