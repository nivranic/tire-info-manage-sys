/** R133 component QA. prepare compiles only; run requires the reviewed prepare SHA. No HTTP/API/DB process. */
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, isAbsolute, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";

const require = createRequire(import.meta.url), root = resolve(import.meta.dirname, "..");
const base = resolve(root, ".artifacts/r133-owned-watch-state-20261025");
const entry = resolve(base, "component-fixture.tsx");
const esbuildRoot = "E:/Mix/project/fnxt-platform-mobile/node_modules/.pnpm/esbuild@0.21.5/node_modules/esbuild";
const playwrightRoot = "E:/Mix/project/fnxt-platform-mobile/node_modules/.pnpm/playwright-core@1.63.0/node_modules/playwright-core";
const browserExe = "C:/Users/11585/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe";
const [action, target = "component-qa-v1", reviewedSha] = process.argv.slice(2);
const output = resolve(base, target), bundle = resolve(output, "fixture.js");
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
const file = path => { const bytes = readFileSync(path); return { bytes: bytes.length, sha256: sha(bytes) }; };
const snapshot = paths => Object.fromEntries([...new Set(paths.map(path => resolve(path)))].sort().map(path => [path, file(path)]));
const save = (name, value) => writeFileSync(resolve(output, name), JSON.stringify(value, null, 2) + "\n");
const assertions = [], scenarios = [];
let stage = "arguments", scenario = null, receipt = null;
function check(label, condition, detail) {
  assertions.push({ scenario, label, passed: !!condition, ...(detail === undefined ? {} : { detail }) });
  if (!condition) throw Error(label);
}
const rel = relative(base, output);
if (!rel || rel.startsWith("..") || isAbsolute(rel)) throw Error("output_must_be_a_child_of_r133_artifact_directory");
if (!["prepare", "run"].includes(action)) throw Error("usage: node scripts/watch_owner_component_qa.mjs prepare|run <output-name> [prepare-sha256]");

function namedRuntime() {
  const esbuildRequire = createRequire(resolve(esbuildRoot, "package.json"));
  const native = esbuildRequire.resolve("@esbuild/win32-x64/esbuild.exe");
  return snapshot([process.execPath, resolve(esbuildRoot, "package.json"), resolve(esbuildRoot, "lib/main.js"), native,
    resolve(playwrightRoot, "package.json"), resolve(playwrightRoot, "index.mjs"), browserExe]);
}
async function prepare() {
  check("fresh_output", !existsSync(output)); mkdirSync(output, { recursive: true });
  stage = "prepare_types";
  const ts = require("typescript"), configPath = resolve(root, "tsconfig.json");
  const config = ts.readConfigFile(configPath, ts.sys.readFile);
  check("base_tsconfig_readable", !config.error);
  const options = ts.convertCompilerOptionsFromJson({ ...config.config.compilerOptions,
    jsx: "react-jsx", types: ["react", "react-dom", "node"], incremental: false }, root);
  const program = ts.createProgram([entry], options.options);
  const diagnostics = [...options.errors, ...ts.getPreEmitDiagnostics(program)];
  const errors = diagnostics.filter(item => item.category === ts.DiagnosticCategory.Error).map(item => ({
    code: item.code, message: ts.flattenDiagnosticMessageText(item.messageText, " "),
    source: item.file ? relative(root, item.file.fileName).replaceAll("\\", "/") : null,
    line: item.file && item.start !== undefined ? item.file.getLineAndCharacterOfPosition(item.start).line + 1 : null,
  }));
  save("typecheck.json", { scope: "fixture plus actual AuthProvider / useOwnedWatch / SDK imports", errors });
  check("target_typecheck", errors.length === 0);
  stage = "prepare_bundle";
  const esbuild = require(resolve(esbuildRoot, "lib/main.js"));
  check("named_esbuild_version", esbuild.version === "0.21.5");
  check("named_playwright_version", JSON.parse(readFileSync(resolve(playwrightRoot, "package.json"), "utf8")).version === "1.63.0");
  const runtime = namedRuntime();
  const consumed = new Map();
  const pinSourceBytes = { name: "record-consumed-source-bytes", setup(build) {
    build.onLoad({ filter: /\.(?:tsx?|[cm]?js|json)$/ }, ({ path }) => {
      const contents = readFileSync(path), extension = path.split(".").at(-1);
      consumed.set(resolve(path), { bytes: contents.length, sha256: sha(contents) });
      return { contents, loader: ["ts", "tsx", "json"].includes(extension) ? extension : "js" };
    });
  } };
  const result = await esbuild.build({ absWorkingDir: root, entryPoints: [entry], outfile: bundle,
    bundle: true, platform: "browser", format: "iife", target: "es2022", jsx: "automatic",
    define: { "process.env.NODE_ENV": '"development"' }, metafile: true, logLevel: "silent", plugins: [pinSourceBytes] });
  save("metafile.json", result.metafile);
  const sources = Object.keys(result.metafile.inputs).map(path => resolve(root, path));
  const inputs = snapshot([...sources, import.meta.filename, configPath, require.resolve("typescript"),
    resolve(root, "apps/web/components/auth.tsx"), resolve(root, "apps/web/components/use-owned-watch.ts"),
    resolve(root, "apps/web/components/workbench.tsx")]);
  check("consumed_sources_stable_through_prepare", [...consumed].every(([path, metadata]) => isDeepStrictEqual(metadata, inputs[path])));
  check("real_production_owner_hook_bundled", Object.keys(inputs).some(path => path.endsWith("use-owned-watch.ts")));
  check("prepare_named_runtimes_stable", isDeepStrictEqual(runtime, namedRuntime()));
  save("prepare.json", { schema: "watch-owner-component-qa@1", created_at: new Date().toISOString(), output,
    scope: "real React StrictMode / AuthProvider / actual owned-watch hook, synthetic accounts and in-memory responses",
    no_http_service: true, no_api_database_or_model: true, backend_account_acceptance: false,
    node: realpathSync(process.execPath), browser: { executable: browserExe, headless: true, revision: "1243" },
    playwright_version: JSON.parse(readFileSync(resolve(playwrightRoot, "package.json"), "utf8")).version,
    esbuild_version: esbuild.version, named_runtime_only: true, runtime, inputs,
    outputs: snapshot([bundle, resolve(output, "metafile.json"), resolve(output, "typecheck.json")]) });
  console.log(JSON.stringify({ prepared_not_launched: true, output, type_errors: 0,
    bundle_bytes: file(bundle).bytes, consumed_input_count: Object.keys(inputs).length,
    prepare_sha256: file(resolve(output, "prepare.json")).sha256 }));
}

const auth = name => ({ authenticated: true, user: { id: `synthetic-${name}`, username: `synthetic_${name}`,
  display_name: `Synthetic ${name}`, is_admin: false } });
const watch = (name, key = "x") => ({ id: `watch-${name}-${key}`, variant_id: `variant-${key}`, created_at: "2026-10-25T00:00:00Z" });
const change = name => ({ id: `change-${name}`, variant_id: "variant-x", field: "synthetic_component_value", kind: "facts_changed" });
const paths = { me: "/v1/auth/me", login: "/v1/auth/login", logout: "/v1/auth/logout", watch: "/v1/watchlists", changes: "/v1/changes" };
const state = page => page.locator("#state").textContent().then(JSON.parse);
const requests = page => page.evaluate(() => structuredClone(window.watchQA.requests));
const count = async (page, path, method = "GET") => (await requests(page)).filter(item => item.path === path && item.method === method).length;
const tick = page => page.evaluate(async () => { await new Promise(done => setTimeout(done, 0)); await new Promise(done => setTimeout(done, 0)); });
async function waitState(page, expected) {
  await page.waitForFunction(values => {
    const node = document.getElementById("state"); if (!node) return false;
    const actual = JSON.parse(node.textContent);
    return Object.entries(values).every(([key, value]) => JSON.stringify(actual[key]) === JSON.stringify(value));
  }, expected, { timeout: 10000 });
  return state(page);
}
async function pending(page, path, method = "GET", after = 0) {
  await page.waitForFunction(({ path, method, after }) => window.watchQA.requests.some(item => item.id > after
    && item.path === path && item.method === method && !item.delivered && !item.aborted), { path, method, after }, { timeout: 10000 });
  return (await requests(page)).find(item => item.id > after && item.path === path && item.method === method && !item.delivered && !item.aborted);
}
async function deliver(page, request, body, status = 200) {
  await page.evaluate(({ id, body, status }) => window.watchQA.resolve(id, body, status), { id: request.id, body, status });
  await tick(page);
}
async function fail(page, request) { await page.evaluate(id => window.watchQA.reject(id), request.id); await tick(page); }
async function readPair(page, name, items, { changes = false, after = 0 } = {}) {
  const get = await pending(page, paths.watch, "GET", after);
  const getChanges = changes ? await pending(page, paths.changes, "GET", after) : null;
  await deliver(page, get, { items });
  if (getChanges) await deliver(page, getChanges, { items: [change(name)] });
  await waitState(page, { loading: false, pending: [] });
  return { get, getChanges };
}
async function initial(page, name = "A", items = []) {
  const me = await pending(page, paths.me);
  await deliver(page, me, auth(name));
  await readPair(page, name, items);
  await waitState(page, { ready: true, ownerReady: true, user: `synthetic-${name}`, reason: null });
}
async function login(page, name) {
  const after = (await requests(page)).length;
  await page.locator(`#login-${name.toLowerCase()}`).click();
  const request = await pending(page, paths.login, "POST", after);
  await deliver(page, request, auth(name));
  return request;
}
async function screenshot(page, name) {
  const path = resolve(output, `${name}.png`);
  await page.screenshot({ path, fullPage: true });
  receipt.screenshots.push({ path, ...file(path) });
}

async function run() {
  stage = "verify_reviewed_prepare";
  const preparePath = resolve(output, "prepare.json");
  check("reviewed_prepare_sha", /^[a-f0-9]{64}$/.test(reviewedSha || "") && file(preparePath).sha256 === reviewedSha);
  const prepared = JSON.parse(readFileSync(preparePath, "utf8"));
  check("correct_prepare_schema", prepared.schema === "watch-owner-component-qa@1" && prepared.output === output);
  check("prepared_sources_unchanged", isDeepStrictEqual(prepared.inputs, snapshot(Object.keys(prepared.inputs))));
  check("prepared_bundle_unchanged", isDeepStrictEqual(prepared.outputs, snapshot(Object.keys(prepared.outputs))));
  check("prepared_named_runtimes_unchanged", isDeepStrictEqual(prepared.runtime, namedRuntime()));
  const { chromium } = await import(pathToFileURL(resolve(playwrightRoot, "index.mjs")).href);
  receipt = { schema: "watch-owner-component-result@1", scope: prepared.scope, started_at: new Date().toISOString(),
    reviewed_prepare_sha256: reviewedSha, output, assertions, scenarios, screenshots: [],
    no_http_service: true, no_api_database_or_model: true, backend_account_acceptance: false,
    browser: { launched: false, closed: false, executable: browserExe }, passed: false };
  let browser;
  async function exercise(name, body) {
    scenario = name; stage = name;
    const context = await browser.newContext({ viewport: { width: 1200, height: 900 } });
    const page = await context.newPage(); page.setDefaultTimeout(10000);
    const record = { name, strict_mode: true, page_errors: [], console_errors: [], network_requests: [],
      requests: [], context_closed: false, passed: false };
    scenarios.push(record);
    page.on("pageerror", error => record.page_errors.push(String(error)));
    page.on("console", message => { if (message.type() === "error") record.console_errors.push(message.text()); });
    await context.route("**/*", route => { record.network_requests.push(route.request().url()); return route.abort(); });
    try {
      await page.setContent('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>body{font:16px system-ui;margin:24px;max-width:1100px}button{padding:8px;margin:4px}section{margin:16px 0}pre{padding:16px;background:#eef2f7;white-space:pre-wrap}p{line-height:1.5}</style></head><body><div id="root"></div></body></html>');
      await page.addScriptTag({ path: bundle }); await page.evaluate(() => window.watchQA.mount(true));
      await page.locator("#state").waitFor(); await pending(page, paths.me);
      await body(page);
      await tick(page);
      check("no_page_errors", record.page_errors.length === 0, record.page_errors);
      check("no_console_errors", record.console_errors.length === 0, record.console_errors);
      check("no_network_requests", record.network_requests.length === 0, record.network_requests);
      await screenshot(page, name); record.passed = true;
    } catch (error) {
      try { await screenshot(page, `${name}-failure`); } catch { /* Original failure remains primary. */ }
      throw error;
    } finally {
      record.requests = await requests(page).catch(() => []);
      await context.close(); record.context_closed = true;
    }
  }
  try {
    stage = "launch_browser";
    browser = await chromium.launch({ executablePath: browserExe, headless: true }); receipt.browser.launched = true;
    await exercise("unready-and-single-initial-read", async page => {
      check("not_ready_before_me", (await state(page)).ready === false);
      check("unconfirmed_reason_is_not_loading", (await state(page)).reason?.includes("账户尚未确认"));
      await page.locator("#attempt-toggle-x").click();
      check("no_private_read_before_ready", await count(page, paths.watch) === 0 && await count(page, paths.changes) === 0);
      check("no_write_before_ready", await count(page, paths.watch, "POST") === 0);
      await deliver(page, await pending(page, paths.me), auth("A"));
      const first = await pending(page, paths.watch);
      check("one_strictmode_initial_watch_read", await count(page, paths.watch) === 1);
      check("query_does_not_read_changes", await count(page, paths.changes) === 0);
      check("loading_reason_after_identity", (await state(page)).reason?.includes("正在加载"));
      await page.locator("#attempt-toggle-x").click();
      check("no_write_before_initial_watch_loaded", await count(page, paths.watch, "POST") === 0);
      await deliver(page, first, { items: [watch("A")] }); await waitState(page, { loading: false, reason: null });
      await page.locator("#query-view").click(); await tick(page);
      check("no_duplicate_watch_from_rerender", await count(page, paths.watch) === 1);
      check("loaded_initial_owner_watch", (await state(page)).watches[0]?.id === "watch-A-x");
    });

    await exercise("old-account-get-after-new-owner", async page => {
      await initial(page, "A", [watch("A")]);
      await page.locator("#watch-view").click();
      const oldWatch = await pending(page, paths.watch), oldChanges = await pending(page, paths.changes);
      await page.locator("#login-b-and-old-toggle").click();
      await waitState(page, { ready: false, ownerReady: false, watches: [], changes: [], pending: [] });
      const probe = await page.evaluate(() => window.watchQA.authBeginProbe);
      check("begin_synchronously_revokes_signal_and_epoch", probe.signalAborted && probe.previousEpochInvalid);
      check("same_event_stale_handler_cannot_write", await count(page, paths.watch, "POST") === 0);
      check("old_watch_and_changes_aborted", (await requests(page)).filter(item => [oldWatch.id, oldChanges.id].includes(item.id)).every(item => item.aborted));
      const identity = await pending(page, paths.login, "POST"); await deliver(page, identity, auth("B"));
      await readPair(page, "B", [watch("B")], { changes: true, after: identity.id });
      await deliver(page, oldWatch, { items: [watch("OLD-A")] }); await deliver(page, oldChanges, { items: [change("OLD-A")] });
      const actual = await state(page);
      check("late_A_watch_cannot_replace_B", actual.watches[0]?.id === "watch-B-x");
      check("late_A_changes_cannot_replace_B", actual.changes[0]?.id === "change-B");
      check("canceled_responses_were_really_delivered", (await requests(page)).filter(item => [oldWatch.id, oldChanges.id].includes(item.id)).every(item => item.deliveredAfterAbort));
    });

    await exercise("same-user-refresh-and-A-B-A", async page => {
      await initial(page, "A", [watch("A")]);
      await page.locator("#watch-view").click();
      const oldWatch = await pending(page, paths.watch), oldChanges = await pending(page, paths.changes), firstEpoch = (await state(page)).epoch;
      await page.locator("#refresh-and-old-toggle").click();
      await waitState(page, { ready: false, watches: [], changes: [], pending: [] });
      check("same_ID_refresh_blocks_old_handler", await count(page, paths.watch, "POST") === 0);
      const recheck = await pending(page, paths.me); await deliver(page, recheck, auth("A"));
      await readPair(page, "A2", [watch("A2")], { changes: true, after: recheck.id });
      await deliver(page, oldWatch, { items: [watch("OLD-A")] }); await deliver(page, oldChanges, { items: [change("OLD-A")] });
      check("same_ID_epoch_advanced", (await state(page)).epoch > firstEpoch);
      check("same_ID_old_read_fenced", (await state(page)).watches[0]?.id === "watch-A2-x" && (await state(page)).changes[0]?.id === "change-A2");
      await page.locator("#reload").click();
      const staleA = await pending(page, paths.watch), staleAC = await pending(page, paths.changes);
      const b = await login(page, "B"); await readPair(page, "B", [watch("B")], { changes: true, after: b.id });
      await page.locator("#reload").click();
      const staleB = await pending(page, paths.watch), staleBC = await pending(page, paths.changes);
      const a = await login(page, "A"); await readPair(page, "A3", [watch("A3")], { changes: true, after: a.id });
      for (const [request, body] of [[staleA, { items: [watch("OLD-A2")] }], [staleAC, { items: [change("OLD-A2")] }],
        [staleB, { items: [watch("OLD-B")] }], [staleBC, { items: [change("OLD-B")] }]]) await deliver(page, request, body);
      check("A_B_A_does_not_reuse_first_A", (await state(page)).watches[0]?.id === "watch-A3-x" && (await state(page)).changes[0]?.id === "change-A3");
      check("A_B_A_all_old_reads_canceled_and_late_delivered", (await requests(page)).filter(item => [staleA.id, staleAC.id, staleB.id, staleBC.id].includes(item.id)).every(item => item.deliveredAfterAbort));
    });

    for (const outcome of ["success", "failure"]) await exercise(`old-mutation-${outcome}-cannot-release-new-lock`, async page => {
      await initial(page);
      await page.locator("#toggle-x").click(); const oldWrite = await pending(page, paths.watch, "POST");
      await waitState(page, { pending: ["variant-x"] });
      check("old_write_has_abort_signal", oldWrite.hasSignal);
      await page.locator("#login-b-and-old-toggle").click();
      await waitState(page, { ready: false, watches: [], changes: [], pending: [] });
      check("old_mutation_aborted_at_begin", (await requests(page)).find(item => item.id === oldWrite.id).aborted);
      check("identity_gap_did_not_start_second_write", await count(page, paths.watch, "POST") === 1);
      const identity = await pending(page, paths.login, "POST"); await deliver(page, identity, auth("B"));
      await readPair(page, "B", [], { after: identity.id });
      await page.locator("#toggle-x").click(); const ownWrite = await pending(page, paths.watch, "POST", oldWrite.id);
      await waitState(page, { pending: ["variant-x"] });
      if (outcome === "success") await deliver(page, oldWrite, watch("OLD-A"), 201); else await fail(page, oldWrite);
      const actual = await state(page);
      check("old_mutation_cannot_change_new_owner_items", actual.watches.length === 0);
      check("old_finally_keeps_new_same_variant_lock", actual.pending.length === 1 && actual.pending[0] === "variant-x");
      check("old_success_or_error_cannot_toast", actual.toasts.length === 0 && actual.watchError === "");
      await page.locator("#attempt-toggle-x").click();
      check("new_lock_still_prevents_duplicate_write", await count(page, paths.watch, "POST") === 2);
      await deliver(page, ownWrite, watch("B"), 201);
      await waitState(page, { pending: [] });
      check("new_owner_own_mutation_succeeds", (await state(page)).watches[0]?.id === "watch-B-x");
      check("only_new_owner_success_toasts", (await state(page)).toasts.length === 1 && (await state(page)).toasts[0].kind === "success");
      await readPair(page, "B", [watch("B")], { after: ownWrite.id });
      check("new_owner_lock_released_by_own_finally", await page.locator("#toggle-x").isEnabled());
      check("old_mutation_really_delivered_after_cancel", (await requests(page)).find(item => item.id === oldWrite.id).deliveredAfterAbort);
    });

    await exercise("same-owner-get-cannot-undo-post-or-delete", async page => {
      await initial(page);
      await page.locator("#watch-view").click();
      const oldGet = await pending(page, paths.watch), oldChanges = await pending(page, paths.changes);
      await page.locator("#toggle-x").click(); const post = await pending(page, paths.watch, "POST");
      check("mutation_aborts_preexisting_GET", (await requests(page)).find(item => item.id === oldGet.id).aborted);
      await deliver(page, post, watch("A"), 201); await waitState(page, { pending: [] });
      await deliver(page, oldGet, { items: [] }); await deliver(page, oldChanges, { items: [change("STALE-EMPTY")] });
      check("late_GET_does_not_remove_completed_POST", (await state(page)).watches[0]?.id === "watch-A-x");
      await readPair(page, "A", [watch("A")], { changes: true, after: post.id });
      await page.locator("#reload").click();
      const beforeDelete = await pending(page, paths.watch), beforeDeleteC = await pending(page, paths.changes);
      await page.locator("#toggle-x").click(); const deletion = await pending(page, "/v1/watchlists/watch-A-x", "DELETE");
      check("DELETE_has_abort_signal", deletion.hasSignal);
      await deliver(page, deletion, null, 204); await waitState(page, { pending: [] });
      await deliver(page, beforeDelete, { items: [watch("A")] }); await deliver(page, beforeDeleteC, { items: [change("STALE-WATCHED")] });
      check("late_GET_does_not_restore_completed_DELETE", (await state(page)).watches.length === 0);
      await readPair(page, "AFTER-DELETE", [], { changes: true, after: deletion.id });
      check("only_current_reconcile_changes_visible", (await state(page)).changes[0]?.id === "change-AFTER-DELETE");
      check("one_POST_one_DELETE_no_retry", await count(page, paths.watch, "POST") === 1 && await count(page, "/v1/watchlists/watch-A-x", "DELETE") === 1);
      check("both_current_mutations_toast", (await state(page)).toasts.length === 2);
    });

    await exercise("logout-failure-rechecks-before-private-read", async page => {
      await initial(page, "A", [watch("A")]); const previousReads = await count(page, paths.watch);
      await page.locator("#logout").click(); const logout = await pending(page, paths.logout, "POST");
      await waitState(page, { ready: false, ownerReady: false, watches: [], changes: [], pending: [] });
      await fail(page, logout); const me = await pending(page, paths.me, "GET", logout.id);
      await page.locator("#attempt-toggle-x").click();
      check("failed_logout_waits_for_me_before_read", await count(page, paths.watch) === previousReads);
      check("failed_logout_waits_for_me_before_write", await count(page, paths.watch, "POST") === 0);
      await deliver(page, me, auth("A")); await readPair(page, "RECONFIRMED-A", [watch("RECONFIRMED-A")], { after: me.id });
      check("failed_logout_restores_only_reconfirmed_owner", (await state(page)).watches[0]?.id === "watch-RECONFIRMED-A-x");
    });

    await exercise("read-error-reason-and-explicit-retry", async page => {
      await deliver(page, await pending(page, paths.me), auth("A"));
      await deliver(page, await pending(page, paths.watch), { detail: "synthetic_watch_read_failed" }, 503);
      await waitState(page, { loading: false });
      check("watch_read_error_is_visible", (await state(page)).watchError === "synthetic_watch_read_failed");
      check("read_error_reason_is_distinct", (await state(page)).reason?.includes("未能读取"));
      check("read_error_has_no_pending_write", (await state(page)).pending.length === 0);
      await page.locator("#attempt-toggle-x").click();
      check("failed_initial_read_blocks_write", await count(page, paths.watch, "POST") === 0);
      await page.locator("#reload").click(); await readPair(page, "A", []);
      check("explicit_retry_restores_available_controls", (await state(page)).reason === null && await page.locator("#toggle-x").isEnabled());
      await page.locator("#watch-view").click();
      const get = await pending(page, paths.watch), getChanges = await pending(page, paths.changes);
      await deliver(page, get, { items: [] }); await deliver(page, getChanges, { detail: "synthetic_changes_read_failed" }, 503);
      await waitState(page, { loading: false });
      check("changes_error_does_not_replace_watch_error", (await state(page)).watchError === "" && (await state(page)).changesError === "synthetic_changes_read_failed");
      await page.locator("#login-b").click();
      await waitState(page, { ready: false, watches: [], changes: [], pending: [], watchError: "", changesError: "" });
      check("identity_begin_clears_previous_errors", (await state(page)).reason?.includes("账户尚未确认"));
      const identity = await pending(page, paths.login, "POST"); await deliver(page, identity, auth("B"));
      await readPair(page, "B", [], { changes: true, after: identity.id });
    });

    await exercise("leave-watch-and-unmount-cancel-reads", async page => {
      await initial(page, "A", [watch("A")]);
      await page.locator("#watch-view").click();
      const oldGet = await pending(page, paths.watch), oldChanges = await pending(page, paths.changes), beforeLeave = await count(page, paths.watch);
      await page.locator("#query-view").click(); await tick(page);
      check("leaving_watch_aborts_both_reads", (await requests(page)).filter(item => [oldGet.id, oldChanges.id].includes(item.id)).every(item => item.aborted));
      check("leaving_loaded_watch_does_not_duplicate_GET", await count(page, paths.watch) === beforeLeave);
      check("leaving_watch_clears_loading_and_keeps_loaded_controls_available", (await state(page)).loading === false && (await state(page)).reason === null);
      await deliver(page, oldGet, { items: [watch("STALE-LEAVE")] }); await deliver(page, oldChanges, { items: [change("STALE-LEAVE")] });
      check("late_left_view_read_cannot_change_items", (await state(page)).watches[0]?.id === "watch-A-x" && (await state(page)).changes.length === 0);
      await page.locator("#watch-view").click();
      const unmountedGet = await pending(page, paths.watch), unmountedChanges = await pending(page, paths.changes);
      await page.evaluate(() => window.watchQA.unmount());
      check("unmount_aborts_inflight_private_reads", (await requests(page)).filter(item => [unmountedGet.id, unmountedChanges.id].includes(item.id)).every(item => item.aborted));
      await deliver(page, unmountedGet, { items: [watch("STALE-UNMOUNT")] }); await deliver(page, unmountedChanges, { items: [change("STALE-UNMOUNT")] });
      check("unmount_late_delivery_does_not_remount_or_toast", await page.locator("#state").count() === 0 && await page.evaluate(() => window.watchQA.toasts.length) === 0);
    });
    scenario = null; stage = "verify_final_inputs";
    check("sources_stayed_unchanged_during_browser_run", isDeepStrictEqual(prepared.inputs, snapshot(Object.keys(prepared.inputs))));
    check("named_runtimes_stayed_unchanged", isDeepStrictEqual(prepared.runtime, namedRuntime()));
    receipt.passed = true;
  } finally {
    if (browser) { await browser.close(); receipt.browser.closed = !browser.isConnected(); }
    receipt.finished_at = new Date().toISOString(); receipt.assertion_count = assertions.length;
    receipt.passed_assertion_count = assertions.filter(item => item.passed).length;
    receipt.scenario_count = scenarios.length;
    receipt.synthetic_canceled_responses_delivered = scenarios.flatMap(item => item.requests).filter(item => item.deliveredAfterAbort).length;
    save("result.json", receipt);
  }
  console.log(JSON.stringify({ passed: receipt.passed, output, assertions: receipt.assertion_count,
    scenarios: receipt.scenario_count, screenshots: receipt.screenshots.length, browser_closed: receipt.browser.closed,
    canceled_responses_delivered: receipt.synthetic_canceled_responses_delivered }));
}

try { if (action === "prepare") await prepare(); else await run(); }
catch (error) {
  const failure = { stage, scenario, error: String(error?.message || error), assertions,
    stack: String(error?.stack || ""), browser: receipt?.browser ?? { launched: false, closed: false } };
  if (existsSync(output)) save("failure.json", failure);
  console.error(JSON.stringify(failure)); process.exitCode = 1;
}
