/** R130: current production Workbench local variant preview and bounded synthetic DTO coverage.
 * Root alone runs after independent review and a passed current-source build.
 * No controlled clock, product-code injection, database wrapper or process supervisor lives here.
 * Synthetic responses are per-request records; real responses use the unchanged private fixture.
 */
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { copyFileSync, existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { basename, dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { isDeepStrictEqual as equal } from 'node:util';

const root = resolve(import.meta.dirname, '..'), artifacts = resolve(root, '.artifacts');
const flags = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  const key = process.argv[index];
  if (!['--origin', '--output', '--build', '--build-report-sha'].includes(key) || !process.argv[index + 1] || flags.has(key)) throw Error('reviewed_arguments_required');
  flags.set(key, process.argv[index + 1]);
}
const origin = flags.get('--origin'), output = resolve(flags.get('--output') || ''), build = resolve(flags.get('--build') || '');
const reportSha = flags.get('--build-report-sha'), fixtureOrigin = 'http://127.0.0.1:18986';
if (origin !== 'http://127.0.0.1:18987' || dirname(output) !== artifacts || !/^r130browser-[a-f0-9]{16}$/.test(basename(output))
    || existsSync(output) || !build.startsWith(artifacts + '\\') && !build.startsWith(artifacts + '/')
    || !/^web-build-[a-f0-9]{16}$/.test(basename(build)) || !/^[a-f0-9]{64}$/.test(reportSha || '')) throw Error('fresh_reviewed_private_inputs_required');
const playwrightRoot = 'E:/Mix/project/fnxt-platform-mobile/node_modules/.pnpm/playwright-core@1.63.0/node_modules/playwright-core';
const browserRoot = 'C:/Users/11585/AppData/Local/ms-playwright/chromium_headless_shell-1243';
const browserExe = 'chrome-headless-shell-win64/chrome-headless-shell.exe';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const digest = path => { const stat = lstatSync(path); if (!stat.isFile() || stat.isSymbolicLink()) throw Error('regular_input_required'); const bytes = readFileSync(path); return { bytes: bytes.length, sha256: sha(bytes) }; };
const snapshot = paths => Object.fromEntries([...new Set(paths)].sort().map(path => [path, digest(path)]));
const exactFiles = base => { if (!lstatSync(base).isDirectory() || lstatSync(base).isSymbolicLink()) throw Error('regular_directory_required'); return readdirSync(base, { withFileTypes: true }).flatMap(entry => {
  if (entry.isSymbolicLink()) throw Error('reparse_input_rejected'); const path = resolve(base, entry.name);
  if (entry.isDirectory()) return exactFiles(path); if (!entry.isFile()) throw Error('regular_file_required'); return [path];
}).sort(); };
const reportPath = resolve(build, 'verification.json'), freezePath = resolve(build, 'freeze.json');
if (digest(reportPath).sha256 !== reportSha) throw Error('reviewed_build_report_mismatch');
const report = JSON.parse(readFileSync(reportPath, 'utf8')), freeze = JSON.parse(readFileSync(freezePath, 'utf8'));
if (report.schema !== 'r118-web-build-verification@2' || report.state !== 'passed' || !report.source_stable || !report.dependencies_stable
    || !report.generated_restore?.passed || digest(freezePath).sha256 !== report.freeze_sha256) throw Error('passed_stable_build_required');
const webDist = resolve(report.artifacts.web.path), publicRoot = resolve(build, 'web-public');
if (freeze.web_dist !== webDist || freeze.api_base !== fixtureOrigin || freeze.web_origin !== origin || resolve(report.artifacts.web_public.path) !== publicRoot) throw Error('matching_build_origin_required');
const productPins = { ...freeze.sources, ...freeze.dependencies, ...freeze.executables, ...freeze.generated_inputs }, outputPins = {};
for (const [path, expected] of Object.entries(productPins)) if (!equal(digest(path), expected)) throw Error('product_input_drift');
for (const [base, files] of [[webDist, report.artifacts.web.files], [publicRoot, report.artifacts.web_public.files]]) {
  if (!equal(exactFiles(base), Object.keys(files).map(name => resolve(base, name)).sort())) throw Error('build_output_keyset_drift');
  for (const [name, expected] of Object.entries(files)) { const path = resolve(base, name); if (!equal(digest(path), expected)) throw Error('build_output_drift'); outputPins[path] = expected; }
}
const inputPins = { ...productPins, ...outputPins, ...snapshot([import.meta.filename, process.execPath, reportPath, freezePath,
  resolve(root, 'scripts/query_selection_web_fixture.py'), resolve(root, 'scripts/query_filter_browser_qa.py'),
  resolve(root, '.artifacts/r127-variant-context-menu-20261022/run-ui-host.py'), resolve(root, '.artifacts/r130-variant-hover-preview-20261023/run-ui-host.py'),
  resolve(root, '.artifacts/r118-material-workbench-20261021/serve-web-v1.py'), resolve(root, 'docs/plans/2026-10-23-variant-hover-preview.md'),
  resolve(root, '.artifacts/r130-variant-hover-preview-20261023/product-review.json'),
  resolve(root, '.artifacts/r130-variant-hover-preview-20261023/product-review-final.json'),
  resolve(root, '.artifacts/r130-variant-hover-preview-20261023/plan-freeze.json'),
  resolve(root, '.artifacts/r130-variant-hover-preview-20261023/plan-review.json')]) };
const sidecarPattern = /^chrome-headless-shell-win64\/(?:debug\.log|chrome-headless-shell\.\d{8}-\d{6}-\d{3}\.log)$/;
const sidecarPolicy = { new_private_browser_files_only: true, regular_non_symlink_only: true,
  allowed_paths: ['chrome-headless-shell-win64/debug.log', 'chrome-headless-shell-win64/chrome-headless-shell.YYYYMMDD-HHMMSS-mmm.log'],
  min_bytes: 1, max_bytes: 1048576, max_files: 4, prepared_files_and_directories_unchanged: true };
const tree = (base, target, generated, prepared = {}, prefix = '') => {
  const stat = lstatSync(base); if (!stat.isDirectory() || stat.isSymbolicLink()) throw Error('regular_runtime_directory_required');
  if (target) mkdirSync(target, { recursive: true }); const result = {};
  for (const entry of readdirSync(base, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const name = prefix ? prefix + '/' + entry.name : entry.name, path = resolve(base, entry.name), value = lstatSync(path);
    if (value.isSymbolicLink()) throw Error('runtime_reparse_rejected');
    if (value.isDirectory()) { result[name] = { kind: 'directory' }; Object.assign(result, tree(path, target ? resolve(target, entry.name) : undefined, generated, prepared, name)); continue; }
    if (!value.isFile()) throw Error('regular_runtime_file_required');
    if (!generated && name === 'chrome-headless-shell-win64/debug.log') continue;
    const record = digest(path);
    if (generated && !Object.hasOwn(prepared, name) && sidecarPattern.test(name)) {
      if (generated.length >= 4 || record.bytes < 1 || record.bytes > 1048576) throw Error('runtime_sidecar_bounds'); generated.push({ path: name, ...record });
    } else result[name] = record;
    if (target) copyFileSync(path, resolve(target, entry.name));
  }
  return result;
};
const runtimePins = { playwright: tree(playwrightRoot), browser: tree(browserRoot) };
const info = JSON.parse(readFileSync(resolve(playwrightRoot, 'package.json'), 'utf8'));
if (info.name !== 'playwright-core' || info.version !== '1.63.0') throw Error('reviewed_playwright_required');
mkdirSync(output); for (const name of ['runtime', 'tmp', 'downloads']) mkdirSync(resolve(output, name));
const receipt = { schema: 'r130-variant-hover-preview-production-workbench@1', state: 'running', started_utc: new Date().toISOString(), origin, fixture_origin: fixtureOrigin,
  build, build_report_sha256: reportSha, input_pins: inputPins, runtime_pins: runtimePins, checks: [], scenarios: [], observations: [], screenshots: [], http_events: [], ui_request_windows: [],
  query_windows: [], consent_windows: [], request_gates: [], synthetic_http_faults: [], unexpected_origins: [], unexpected_http_statuses: [], page_errors: [], console_errors: [],
  gate_failures: [], coverage_failures: [], cleanup_failures: [], browser_generated_sidecars: [], browser_generated_sidecar_policy: sidecarPolicy,
  browser: { playwright: '1.63.0', chromium_revision: '1243', headless: true }, browser_close_returned: false, fixture_shutdown_requested: false,
  inputs_unchanged: false, prepared_runtimes_unchanged: false, synthetic_only: true, production_workbench_verified: false,
  product_review_basis: { current: 'product-review-final.json', initial_request_changes_preserved: 'product-review.json', frozen_plan: 'plan-freeze.json' },
  explicit_limitations: ['project_owned_synthetic_sources_accounts_only_not_real_external_sources', 'service_workers_blocked_matching_build_public_served_by_page_route',
    'long_fields_risks_duplicate_watch_records_are_exact_browser_route_injections_without_backend_dispatch',
    'real_clock_timing_uses_browser_event_and_mutation_observations_not_controlled_time', 'touch_is_playwright_emulation_not_device_acceptance',
    'local_200_percent_font_style_is_synthetic_typography_stress_not_browser_zoom', 'blur_hidden_visual_viewport_supplement_is_synthetic_event_delivery',
    'contextmenu_default_prevented_is_observed_native_os_menu_is_not_inspected', 'navigation_observes_bounded_absence_not_per_react_resource_release_counts',
    'screenshots_require_root_visual_inspection', 'no_real_provider_normal_database_native_host_device_reader_pwa_or_complete_v1_claim'] };
const save = () => writeFileSync(resolve(output, 'result.json'), JSON.stringify(receipt, null, 2) + '\n');
const check = (label, condition) => { if (!condition) throw Error(label); receipt.checks.push(label); save(); };
const observe = (label, value) => { receipt.observations.push({ label, ...value }); save(); };
const api = path => origin + '/api' + path;
const json = async response => { if (!response.ok()) throw Error('HTTP_' + response.status()); return response.json(); };
const wait = ms => new Promise(done => setTimeout(done, ms));
const bounded = async promise => { let timer; try { return await Promise.race([promise, new Promise((_, reject) => {
  timer = setTimeout(() => reject(Error('request_gate_timeout')), 12000); })]); } finally { clearTimeout(timer); } };
const privatePlaywright = resolve(output, 'runtime/playwright-core'), privateBrowser = resolve(output, 'runtime/chromium_headless_shell-1243');
let browser, browserServer, browserProcess, context, page, stage = 'runtime_copy', phase = 'initialization', password = randomBytes(24).toString('base64url');
const inFlight = new Set(), heldRequests = new Set(), gates = new Set(), activeRecords = new Map(), requestRecords = new WeakMap(), requestIds = new WeakMap();
let requestSequence = 0;
const postRows = () => receipt.http_events.filter(row => row.event === 'request' && row.method === 'POST');
const queryRows = () => postRows().filter(row => /\/live-query$/.test(row.path));
const snapshotRows = () => receipt.http_events.filter(row => row.event === 'request' && row.business
  && /\/(?:evidence|snapshots|local-snapshots|history)(?:\/|$)/.test(row.path));
const requestCounts = () => ({ query_posts: queryRows().length, consent_posts: postRows().filter(row => row.path === '/api/v1/fallback-consents').length, snapshot_reads: snapshotRows().length });
const gatesPassed = () => receipt.request_gates.length === 9 && gates.size === 0 && activeRecords.size === 0 && receipt.request_gates.every(record =>
  record.claimed && record.requests === 1 && record.observed_responses === 1 && record.finished_events === 1 && record.completed && record.released
  && record.route_removed && !record.active && record.body_matched && Number.isInteger(record.request_id) && record.request_id > 0
  && (record.origin === 'real_private_fixture_http' ? record.real_fetches === 1 && record.injected_responses === 0 && [200, 201].includes(record.status)
    : record.real_fetches === 0 && record.injected_responses === 1)
  && record.console_errors >= 0 && record.console_errors <= (record.status === 503 ? 1 : 0));
try {
  check('private_playwright_copy_pinned', equal(tree(playwrightRoot, privatePlaywright), runtimePins.playwright) && equal(tree(privatePlaywright), runtimePins.playwright));
  check('private_browser_copy_pinned', equal(tree(browserRoot, privateBrowser), runtimePins.browser) && equal(tree(privateBrowser), runtimePins.browser));
  const { chromium } = await import(pathToFileURL(resolve(privatePlaywright, 'index.mjs')).href);
  stage = 'browser_start';
  browserServer = await chromium.launchServer({ executablePath: resolve(privateBrowser, browserExe), headless: true, host: '127.0.0.1', port: 0,
    artifactsDir: resolve(output, 'tmp'), downloadsPath: resolve(output, 'downloads'),
    env: { ...process.env, TEMP: resolve(output, 'tmp'), TMP: resolve(output, 'tmp'), TMPDIR: resolve(output, 'tmp') },
    args: ['--no-first-run', '--disable-background-networking', '--disable-breakpad', '--disable-crash-reporter', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'] });
  browserProcess = browserServer.process(); receipt.browser.pid = browserProcess.pid;
  browserServer.once('close', () => { receipt.browser.server_close_observed = true; });
  browserProcess.once('exit', (code, signal) => { receipt.browser.exit_code = code; receipt.browser.exit_signal = signal; });
  browser = await chromium.connect(browserServer.wsEndpoint());
  context = await browser.newContext({ baseURL: origin, serviceWorkers: 'block', colorScheme: 'light', viewport: { width: 1365, height: 900 }, hasTouch: true });
  page = await context.newPage(); page.setDefaultTimeout(12000);
  await context.routeWebSocket('**/*', socket => { receipt.unexpected_origins.push('blocked_websocket'); socket.close(); });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!['http:', 'https:'].includes(url.protocol) || ![origin, fixtureOrigin].includes(url.origin)) { receipt.unexpected_origins.push('blocked_external_origin'); await route.abort(); return; }
    const name = url.pathname.slice(1);
    if (url.origin === origin && ['favicon.ico', 'sw.js', 'icons/icon-180.png', 'icons/icon-192.png', 'icons/icon-512.png'].includes(name)) {
      const path = resolve(publicRoot, name); if (existsSync(path)) { await route.fulfill({ status: 200, body: readFileSync(path) }); return; }
    }
    await route.continue();
  });
  const recordEvent = (event, request, status, expectedStatus = false) => {
    const url = new URL(request.url());
    if (!requestIds.has(request)) requestIds.set(request, ++requestSequence);
    const row = { sequence: receipt.http_events.length + 1, request_id: requestIds.get(request), phase, event, method: request.method(),
      path: [origin, fixtureOrigin].includes(url.origin) ? url.pathname : 'blocked', business: [origin, fixtureOrigin].includes(url.origin) && (url.origin === fixtureOrigin || url.pathname.startsWith('/api/')),
      ...(url.pathname === '/api/v1/personal-feed/preview' ? { query: url.search } : {}), ...(status === undefined ? {} : { status, expected_status: expectedStatus }),
      ...(event === 'failed' ? { failure: request.failure()?.errorText === 'net::ERR_ABORTED' ? 'aborted' : 'other' } : {}) };
    receipt.http_events.push(row);
    if (event === 'response' && status >= 400 && !expectedStatus) receipt.unexpected_http_statuses.push({ request_id: row.request_id, phase, method: row.method, path: row.path, status });
  };
  page.on('request', request => { recordEvent('request', request); if (new URL(request.url()).pathname.startsWith('/api/')) inFlight.add(request); });
  page.on('response', response => {
    const request = response.request(), record = requestRecords.get(request);
    const exact = !!record?.active && activeRecords.get(response.url()) === record && phase === record.phase && request.method() === record.method
      && requestIds.get(request) === record.request_id && response.status() === record.status && record.requests === 1 && record.observed_responses === 0
      && (record.origin === 'real_private_fixture_http' ? record.real_fetches === 1 : record.injected_responses === 1);
    if (exact) record.observed_responses++;
    recordEvent('response', request, response.status(), exact && record.status === 503);
  });
  page.on('requestfinished', request => { inFlight.delete(request); const record = requestRecords.get(request); if (record) record.finished_events++; recordEvent('finished', request); });
  page.on('requestfailed', request => { inFlight.delete(request); recordEvent('failed', request); });
  page.on('pageerror', error => receipt.page_errors.push(error?.name || 'PageError'));
  page.on('console', message => {
    if (message.type() !== 'error') return;
    // Console has no Request object. Permit only the exact active resource URL,
    // its one claimed request/phase, and at most one precise 503 resource error.
    const record = activeRecords.get(message.location().url);
    if (record?.active && record.status === 503 && phase === record.phase && record.claimed && record.requests === 1 && record.injected_responses === 1
      && record.console_errors < 1 && /^Failed to load resource: the server responded with a status of 503\b/.test(message.text())) record.console_errors++;
    else receipt.console_errors.push('browser_console_error');
  });
  const frames = () => page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
  const idle = async () => { for (let attempt = 0; attempt < 100; attempt++) { await frames(); if ([...inFlight].every(request => heldRequests.has(request))) {
    await wait(100); if ([...inFlight].every(request => heldRequests.has(request))) return; } await wait(50); } throw Error('business_requests_did_not_settle'); };
  const shot = async label => { const name = label + '.png';
    await page.screenshot({ path: resolve(output, name) }); receipt.screenshots.push(name); save(); };
  const scenario = label => { stage = label; phase = 'scenario:' + label; receipt.scenarios.push(label); save(); };
  const uiOnly = async (label, operation) => { await idle(); const start = receipt.http_events.length, before = requestCounts(); phase = 'ui:' + label;
    const choicesBefore = await choiceState();
    const inputsPresent = await page.evaluate(() => {
      const selectors = ['.size-field input', '.model-field select', '.region-selector select'], nodes = selectors.map(selector => document.querySelector(selector));
      window.__r130WindowInputs = nodes.every(Boolean) ? { selectors, nodes, values: nodes.map(node => node.value) } : null;
      return !!window.__r130WindowInputs;
    });
    await operation(); await frames(); await wait(250); await idle();
    const requests = receipt.http_events.slice(start).filter(row => row.event === 'request' && row.business);
    const inputState = await page.evaluate(() => { const old = window.__r130WindowInputs; return old ? {
      nodes: old.nodes.every((node, index) => node === document.querySelector(old.selectors[index])), values: old.nodes.every((node, index) => node.value === old.values[index]) } : null; });
    const choicesAfter = await choiceState();
    receipt.ui_request_windows.push({ label, start_sequence: start + 1, end_sequence: receipt.http_events.length, before, after: requestCounts(), business_requests: requests,
      query_input_baseline_present: inputsPresent, input_state: inputState, choices_before: choicesBefore, choices_after: choicesAfter,
      focus_policy: 'explicit_keyboard_or_pointer_actions_may_move_focus_mouse_only_and_response_holds_have_separate_strict_focus_checks' });
    if (inputsPresent) check(label + '_retains_query_nodes_values_and_choices', inputState.nodes && inputState.values && equal(choicesBefore, choicesAfter));
    check(label + '_zero_new_business_requests', requests.length === 0 && equal(before, requestCounts())); };
  const payloadSummary = body => ({ source_id: body.source_id ?? null, query_id: body.query_id ?? null, data_state: body.data_state ?? null,
    variant_count: Array.isArray(body.variants) ? body.variants.length : null, reason: body.reason ?? null });
  const makeGate = async ({ label, path, method = 'POST', status = 200, expectedBody = null, body, real = false }) => {
    const url = api(path); if (activeRecords.has(url)) throw Error('duplicate_active_gate_url');
    let enter, release, finish, payload;
    const entered = new Promise(done => { enter = done; }), released = new Promise(done => { release = done; }), completed = new Promise(done => { finish = done; });
    const record = { label, method, url, status, phase, origin: real ? 'real_private_fixture_http' : 'synthetic_browser_route_injection_without_backend_dispatch',
      expected_body: expectedBody, response: body ? payloadSummary(body) : null, response_body_sha256: body ? sha(Buffer.from(JSON.stringify(body))) : null,
      active: true, route_removed: false, claimed: false, requests: 0, request_id: null, body_matched: false, real_fetches: 0, injected_responses: 0,
      observed_responses: 0, finished_events: 0, console_errors: 0, maximum_console_errors: status === 503 ? 1 : 0, released: false, completed: false,
      console_association: status === 503 ? 'exact_resource_url_and_single_claimed_request_active_phase_maximum_one_not_request_object' : null };
    receipt.request_gates.push(record); if (status === 503) receipt.synthetic_http_faults.push(record); activeRecords.set(url, record);
    const handler = async route => {
      const request = route.request(); if (request.url() !== url || request.method() !== method) { await route.fallback(); return; }
      record.requests++; heldRequests.add(request);
      try {
        if (!record.active || phase !== record.phase || record.claimed) throw Error('duplicate_or_wrong_phase_request');
        if (!requestIds.has(request)) requestIds.set(request, ++requestSequence);
        record.claimed = true; record.request_id = requestIds.get(request); requestRecords.set(request, record);
        record.body_matched = method === 'GET' ? request.postData() === null : equal(request.postDataJSON(), expectedBody);
        if (!record.body_matched) throw Error('exact_request_body_mismatch');
        let response;
        if (real) { record.real_fetches++; response = await route.fetch({ timeout: 12000, maxRetries: 0, maxRedirects: 0 });
          if (response.status() !== status) throw Error('real_private_http_status_mismatch'); payload = await response.json(); record.response = payloadSummary(payload); }
        else payload = body;
        enter(); await released; record.released = true;
        if (real) await route.fulfill({ response });
        else { record.injected_responses++; await route.fulfill({ status, contentType: 'application/json', headers: { 'cache-control': 'no-store' }, body: JSON.stringify(body) }); }
      } catch (error) { receipt.gate_failures.push({ label, type: /^[a-z_]+$/.test(error?.message || '') ? error.message : error?.name || 'Error' }); try { await route.abort('failed'); } catch {} }
      finally { heldRequests.delete(request); record.completed = true; enter(); finish(); }
    };
    await context.route(url, handler);
    const gate = { record, entered: () => bounded(entered), release, settle: () => bounded(completed), payload: () => payload,
      remove: async () => { await context.unroute(url, handler); record.active = false; record.route_removed = true; activeRecords.delete(url); gates.delete(gate); save(); } };
    gates.add(gate); save(); return gate;
  };
  const tooltip = page.locator('.variant-preview[role="tooltip"]');
  const knownTooltipIds = new Set();
  const trigger = target => target.locator('[data-variant-preview-trigger]');
  const noPreview = async label => { await tooltip.waitFor({ state: 'detached' });
    check(label + '_no_tooltip_or_stale_description', await page.evaluate(ids => !document.querySelector('.variant-preview')
      && ![...document.querySelectorAll('[data-variant-preview-trigger]')].some(node => (node.getAttribute('aria-describedby') || '').split(/\s+/).some(id => ids.includes(id))), [...knownTooltipIds])); };
  const framesSettled = async () => { await frames(); await wait(100); await frames(); };
  const prepare = async target => { await page.mouse.move(0, 0); await target.evaluate(node => node.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' })); await framesSettled(); };
  const closePreview = async label => { await page.keyboard.press('Escape'); await page.mouse.move(0, 0); await noPreview(label); };
  const focusByTab = async (target, preservePreparedViewport = false) => {
    if (!preservePreparedViewport) await prepare(target);
    const focusState = () => target.evaluate(node => { const active = document.activeElement; return {
      target_focused: active === node, target_focus_visible: node.matches(':focus-visible'), target_connected: node.isConnected,
      active_tag: active?.tagName ?? null, active_class: typeof active?.className === 'string' ? active.className : null,
      active_owner: active?.getAttribute('data-variant-preview-trigger') ?? null,
      active_name: (active?.getAttribute('aria-label') || active?.textContent || '').replace(/\s+/g, ' ').slice(0, 100),
      tooltip_count: document.querySelectorAll('.variant-preview[role="tooltip"]').length };
    });
    // Let Chromium determine the real predecessor, including closed <details>.
    // Programmatic focus is setup only; the final entry is an actual Tab event.
    await target.evaluate(node => node.focus({ preventScroll: true }));
    const setup = await focusState(); observe('keyboard_programmatic_setup_' + receipt.checks.length, setup);
    check('keyboard_setup_focus_reaches_original_trigger_' + receipt.checks.length, setup.target_connected && setup.target_focused);
    await page.keyboard.press('Shift+Tab');
    const previous = await focusState(); observe('keyboard_actual_shift_tab_predecessor_' + receipt.checks.length, previous);
    check('keyboard_actual_shift_tab_leaves_trigger_' + receipt.checks.length, !previous.target_focused && previous.active_tag !== 'BODY');
    await noPreview('keyboard_setup_preview_closed_' + receipt.checks.length);
    await page.keyboard.press('Tab');
    const entered = await focusState(); observe('keyboard_actual_tab_entry_' + receipt.checks.length, entered);
    check('actual_tab_focus_visible_' + receipt.checks.length, entered.target_connected && entered.target_focused && entered.target_focus_visible);
  };
  const open = async (target, method, label, preservePreparedViewport = false) => {
    if (!preservePreparedViewport) await prepare(target);
    // Passive timing instrumentation only: no product state/event/CSS alteration.
    await target.evaluate(node => {
      window.__r130Timing?.dispose();
      const state = { start: null, shown: null, event: null, dispose: null };
      const begin = event => { if (event.target !== node) return; state.start = performance.now(); state.shown = null; state.event = event.type; };
      const observer = new MutationObserver(() => { if (state.start !== null && state.shown === null && document.querySelector('.variant-preview[role="tooltip"]')) state.shown = performance.now(); });
      node.addEventListener('pointerenter', begin); node.addEventListener('focus', begin); observer.observe(document.body, { childList: true, subtree: true });
      state.dispose = () => { observer.disconnect(); node.removeEventListener('pointerenter', begin); node.removeEventListener('focus', begin); };
      window.__r130Timing = state;
    });
    if (method === 'keyboard') await focusByTab(target, preservePreparedViewport);
    else { await target.hover(); await wait(120); check(label + '_not_open_at_120ms', await tooltip.count() === 0); }
    await tooltip.waitFor(); await frames();
    const timing = await page.evaluate(() => { const state = window.__r130Timing; const result = { event: state.event, elapsed_ms: state.shown - state.start }; state.dispose(); return result; });
    observe(label + '_real_clock_timing', timing);
    check(label + '_open_delay_contract', timing.elapsed_ms >= 0 && timing.elapsed_ms < 1800 && (method === 'keyboard' ? timing.elapsed_ms < 250 : timing.elapsed_ms >= 260));
    const owner = await target.getAttribute('data-variant-preview-trigger');
    const state = await tooltip.evaluate((node, expected) => ({ owner: node.getAttribute('data-variant-preview-owner'), id: node.id,
      connected: node.parentElement === document.body, interactive: node.querySelectorAll('button,a[href],input,select,textarea,[tabindex]').length,
      text: node.textContent, trigger_count: [...document.querySelectorAll('[data-variant-preview-trigger]')].filter(item => (item.getAttribute('aria-describedby') || '').split(/\s+/).includes(node.id)).length,
      described: [...document.querySelectorAll('[data-variant-preview-trigger]')].find(item => item.getAttribute('data-variant-preview-trigger') === expected)?.getAttribute('aria-describedby'),
      wrong_popup_semantics: [...document.querySelectorAll('[data-variant-preview-trigger]')].some(item => item.hasAttribute('aria-haspopup') || item.hasAttribute('aria-expanded')) }), owner);
    observe(label + '_aria_owner', state);
    knownTooltipIds.add(state.id);
    const stableId = await target.evaluate((node, currentId) => {
      window.__r130MountedIds ||= new WeakMap(); const previousId = window.__r130MountedIds.get(node);
      window.__r130MountedIds.set(node, currentId); return { same_mounted_node_seen: previousId !== undefined, previous_id: previousId ?? null, current_id: currentId };
    }, state.id);
    observe(label + '_mounted_node_id_observation', stableId);
    check(label + '_stable_tooltip_id_for_same_mounted_trigger', !stableId.same_mounted_node_seen || stableId.previous_id === stableId.current_id);
    check(label + '_one_portal_tooltip_original_trigger_described', await tooltip.count() === 1 && state.owner === owner && !!state.id && state.connected
      && state.interactive === 0 && state.trigger_count === 1 && state.described.split(/\s+/).includes(state.id) && !state.wrong_popup_semantics
      && state.text.includes('已加载规格摘要') && state.text.includes('摘要节选，完整信息见卡片'));
    return owner;
  };
  const geometry = async (target, label, minimumFont = 13) => {
    const targetRect = await target.boundingBox();
    const value = await tooltip.evaluate(node => {
      const rect = node.getBoundingClientRect(), viewport = visualViewport;
      const rectOf = item => { const r = item.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height }; };
      const leaves = [...node.querySelectorAll('*')].filter(item => item.childElementCount === 0 && item.textContent?.trim());
      return { rect: rectOf(node), viewport: { left: viewport?.offsetLeft || 0, top: viewport?.offsetTop || 0, width: viewport?.width || innerWidth, height: viewport?.height || innerHeight },
        page_width: document.documentElement.scrollWidth, width: innerWidth, client_height: node.clientHeight, scroll_height: node.scrollHeight,
        palette: document.documentElement.dataset.theme, forced_colors: matchMedia('(forced-colors: active)').matches,
        foreground: getComputedStyle(node).color, background: getComputedStyle(node).backgroundColor,
        leaves: leaves.map(item => ({ text: item.textContent, rect: rectOf(item), font_px: parseFloat(getComputedStyle(item).fontSize),
          client_width: item.clientWidth, scroll_width: item.scrollWidth, overflow: getComputedStyle(item).overflowY })) };
    });
    observe(label + '_actual_geometry', value);
    const r = value.rect, v = value.viewport;
    check(label + '_inside_eight_pixel_viewport_no_internal_scroll', r.width > 0 && r.height > 0 && r.left >= v.left + 7.5 && r.right <= v.left + v.width - 7.5
      && r.top >= v.top + 7.5 && r.bottom <= v.top + v.height - 7.5 && value.page_width <= value.width + 1 && value.scroll_height <= value.client_height + 1);
    check(label + '_trigger_not_occluded', targetRect && (r.right <= targetRect.x || r.left >= targetRect.x + targetRect.width
      || r.bottom <= targetRect.y || r.top >= targetRect.y + targetRect.height));
    check(label + '_all_text_visible_without_hidden_overflow', value.leaves.every(item => item.rect.width > 0 && item.rect.height > 0
      && item.rect.left >= r.left - 1 && item.rect.right <= r.right + 1 && item.rect.top >= r.top - 1 && item.rect.bottom <= r.bottom + 1
      && (item.client_width === 0 || item.scroll_width <= item.client_width + 1)));
    check(label + '_body_and_hint_font_floor', value.leaves.every(item => item.font_px >= (item.text.includes('摘要节选') ? minimumFont * 12 / 13 : minimumFont)));
  };
  const choiceState = () => page.evaluate(() => ({ selected: [...document.querySelectorAll('input[data-query-selection-id]:checked')].map(node => node.getAttribute('data-query-selection-row')).sort(),
    compared: [...document.querySelectorAll('.variant-actions button[aria-pressed="true"]')].map(node => node.closest('.variant-card')?.querySelector('[data-query-selection-id]')?.getAttribute('data-query-selection-id')).sort(),
    sources: [...document.querySelectorAll('.source-selector input')].map(node => node.checked) }));
  const captureInputs = async focus => page.evaluate(shouldFocus => {
    const selectors = ['.size-field input', '.model-field select', '.region-selector select']; const nodes = selectors.map(selector => document.querySelector(selector));
    if (shouldFocus) { nodes[0].focus({ preventScroll: true }); nodes[0].setSelectionRange(2, 7); }
    window.__r130Inputs = { selectors, nodes, values: nodes.map(node => node.value), active: document.activeElement,
      start: nodes[0].selectionStart, end: nodes[0].selectionEnd, scrollY };
    return { values: window.__r130Inputs.values, focused: document.activeElement === nodes[0], scrollY };
  }, focus);
  const retained = async (label, focus) => { const value = await page.evaluate(needFocus => { const old = window.__r130Inputs;
    return { nodes: old.nodes.every((node, index) => node === document.querySelector(old.selectors[index])), values: old.nodes.every((node, index) => node.value === old.values[index]),
      focus: !needFocus || document.activeElement === old.active, selection: old.nodes[0].selectionStart === old.start && old.nodes[0].selectionEnd === old.end,
      scroll_delta: scrollY - old.scrollY }; }, focus); observe(label + '_input_preservation', value);
    check(label + '_same_input_nodes_values_selection_and_required_focus', value.nodes && value.values && value.focus && value.selection);
    if (['mouse_open', 'mouse_hover', 'popup_hover', 'escape'].includes(label)) check(label + '_preview_does_not_scroll_page', Math.abs(value.scroll_delta) <= 1); };
  const releaseGates = async values => { values.forEach(gate => gate.release()); await Promise.all(values.map(gate => gate.settle())); await idle();
    for (const gate of values) { check(gate.record.label + '_one_exact_response_finished', gate.record.requests === 1 && gate.record.observed_responses === 1 && gate.record.finished_events === 1); await gate.remove(); } };
  const fixture = await json(await context.request.get(api('/fixture/state')));
  check('private_fixture_zero_real_usage_exact_two_sources', fixture.synthetic_only && !fixture.normal_database_used && fixture.source_calls === 0 && fixture.real_source_calls === 0
    && fixture.provider_calls === 0 && fixture.model_requests === 0 && fixture.embedding_requests === 0
    && equal(fixture.source_ids, ['r122-selection-a', 'r122-selection-b']) && equal(fixture.source_row_counts, [26, 3]));
  const admin = await json(await context.request.post(api('/v1/auth/register'), { data: { username: 'r130_admin_' + randomBytes(4).toString('hex'), password } })); password = null;
  check('admin_registered_real_private_http', admin.user?.is_admin === true);
  check('production_document_http_200', (await page.goto(origin, { waitUntil: 'domcontentloaded' }))?.status() === 200);
  await page.locator('.sidebar-foot small').filter({ hasText: '管理员 · 本机工作台' }).waitFor(); await page.locator('.home-counts').waitFor(); await idle();
  const initializationEnd = receipt.http_events.length, preview = postRows()[0];
  check('initialization_exact_single_finished_history_preview', postRows().length === 1 && preview.path === '/api/v1/personal-feed/preview' && preview.query === '?mode=history'
    && receipt.http_events.some(row => row.request_id === preview.request_id && row.event === 'response' && row.status === 200)
    && receipt.http_events.some(row => row.request_id === preview.request_id && row.event === 'finished'));
  receipt.initialization_business_window = { end_sequence: initializationEnd, preview_request_id: preview.request_id };
  const navigate = async view => { phase = 'navigation:' + view; const names = { query: /轮胎查询/, watch: /关注/, home: /工作台/ };
    await page.locator('.main-nav').getByRole('button', { name: names[view] }).click(); await idle(); };
  await navigate('query'); await page.locator('.model-field select').selectOption(fixture.model); await page.locator('.region-selector select').selectOption('US');
  await page.locator('.size-field input').fill('265/40R20');
  const expectedQuery = { query: { size: '265/40R20', model: fixture.model }, filters: [], fallback_policy: 'ask' };
  const queryPair = async (label, bodies, first = false) => { scenario(label); const pair = [];
    for (let index = 0; index < 2; index++) pair.push(await makeGate({ label: label + '_' + index, path: '/v1/sources/' + fixture.source_ids[index] + '/live-query',
      expectedBody: expectedQuery, ...(bodies ? { body: bodies[index] } : { real: true }) }));
    await (first ? page.locator('.query-submit') : page.getByRole('button', { name: '按本次条件重新在线查询', exact: true })).click();
    await Promise.all(pair.map(gate => gate.entered())); await releaseGates(pair); return pair.map(gate => gate.payload()); };
  const real = await queryPair('real_private_live_query', null, true);
  check('real_http_26_3_shared_sku_distinct_sources', real.every((dto, index) => dto.data_state === 'live' && dto.source_id === fixture.source_ids[index] && dto.variants.length === [26, 3][index])
    && real[0].variants[0].id === real[1].variants[0].id && real[0].variants[0].snapshot_id !== real[1].variants[0].snapshot_id);
  const groups = ['A', 'B'].map(letter => page.locator('.source-result').filter({ has: page.getByRole('heading', { name: 'R122 合成来源 ' + letter, exact: true }) }));
  const card = (index, id) => groups[index].locator('.variant-card').filter({ has: page.locator(`input[data-query-selection-id="${id}"]`) });
  const firstCard = card(0, real[0].variants[0].id), secondCard = card(0, real[0].variants[1].id), duplicateCard = card(1, real[1].variants[0].id);
  const firstTrigger = trigger(firstCard), secondTrigger = trigger(secondCard), duplicateTrigger = trigger(duplicateCard);
  const prepareMenuPair = async label => {
    await closePreview(label + '_before_pair_setup');
    const union = await firstCard.evaluate(node => {
      const evidence = node.querySelector('[data-variant-preview-trigger]').getBoundingClientRect();
      const menu = node.querySelector('[data-variant-menu-trigger]').getBoundingClientRect();
      const top = Math.min(evidence.top, menu.top), bottom = Math.max(evidence.bottom, menu.bottom);
      window.scrollTo({ top: scrollY + (top + bottom) / 2 - innerHeight / 2, behavior: 'instant' });
      return { required_height: bottom - top, viewport_height: innerHeight, method: 'both_original_buttons_centered_before_any_preview_open' };
    });
    observe(label + '_pair_setup', union); check(label + '_both_buttons_can_fit_current_viewport', union.required_height <= union.viewport_height - 32);
    let previous, consecutive = 0; const samples = [];
    for (let attempt = 0; attempt < 12; attempt++) {
      await frames(); await wait(50);
      const sample = await firstCard.evaluate(node => ({ scroll_y: scrollY,
        buttons: ['[data-variant-preview-trigger]', '[data-variant-menu-trigger]'].map(selector => {
          const button = node.querySelector(selector), rect = button.getBoundingClientRect();
          const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
          return { x: rect.x, y: rect.y, width: rect.width, height: rect.height,
            visible: rect.width > 0 && rect.height > 0 && rect.left >= 8 && rect.right <= innerWidth - 8 && rect.top >= 8 && rect.bottom <= innerHeight - 8,
            center_hits_button: !!hit && button.contains(hit) };
        }) }));
      samples.push(sample);
      const motion = [sample.scroll_y, ...sample.buttons.flatMap(button => [button.x, button.y, button.width, button.height])];
      consecutive = sample.buttons.every(button => button.visible && button.center_hits_button)
        ? previous && motion.every((value, index) => Math.abs(value - previous[index]) <= .25) ? consecutive + 1 : 1 : 0;
      previous = motion; if (consecutive >= 4) break;
    }
    observe(label + '_pair_stability', { samples, consecutive, required_consecutive: 4 });
    check(label + '_both_original_buttons_visible_hit_tested_and_stable', consecutive >= 4);
  };
  const observeMenuTransition = async (label, operation) => {
    await page.evaluate(() => {
      window.__r130MenuProbe?.dispose();
      const state = { events: [], dropped: 0, dispose: null };
      const add = (type, event) => {
        if (state.events.length >= 128) { state.dropped++; return; }
        const target = event?.target, active = document.activeElement;
        state.events.push({ type, at_ms: performance.now(), scroll_y: scrollY,
          menu_count: document.querySelectorAll('[role="menu"]').length, preview_count: document.querySelectorAll('.variant-preview').length,
          trusted: event?.isTrusted ?? null, key: event?.key ?? null,
          target: target instanceof Element ? target.hasAttribute('data-variant-menu-trigger') ? 'menu_trigger' : target.closest('.variant-preview') ? 'preview' : target.tagName : 'document_or_window',
          active: active?.getAttribute('data-variant-preview-trigger') ? 'preview_trigger' : active?.hasAttribute('data-variant-menu-trigger') ? 'menu_trigger' : active?.getAttribute('role') || active?.tagName || null });
      };
      let last = '';
      const observer = new MutationObserver(() => { const signature = document.querySelectorAll('[role="menu"]').length + ':' + document.querySelectorAll('.variant-preview').length;
        if (signature !== last) { last = signature; add('overlay_mutation'); } });
      const handler = event => add(event.type, event), types = ['scroll', 'pointerdown', 'click', 'focusin', 'keydown'];
      types.forEach(type => document.addEventListener(type, handler, true)); observer.observe(document.body, { childList: true, subtree: true });
      state.dispose = () => { types.forEach(type => document.removeEventListener(type, handler, true)); observer.disconnect(); };
      window.__r130MenuProbe = state; add('before_operation');
    });
    try { await operation(); }
    finally {
      const probe = await page.evaluate(() => { const state = window.__r130MenuProbe; state.dispose(); return { events: state.events, dropped: state.dropped }; });
      observe(label + '_passive_menu_scroll_events', probe);
      check(label + '_passive_event_buffer_not_truncated', probe.dropped === 0);
    }
  };
  await firstCard.locator('input[data-query-selection-id]').check(); await secondCard.getByRole('button', { name: '加入比较', exact: true }).click();
  const choices = await choiceState();
  await firstTrigger.evaluate(node => { window.__r130OriginalTrigger = node; });
  scenario('mouse_delay_keep_open_gap_escape_and_input_preservation');
  await uiOnly('mouse_preview_lifecycle', async () => {
    await prepare(firstTrigger); observe('query_input_baseline', await captureInputs(true));
    await open(firstTrigger, 'mouse', 'mouse_first'); await retained('mouse_open', true); await geometry(firstTrigger, 'mouse_wide');
    await wait(650); check('hover_does_not_timeout', await tooltip.count() === 1); await retained('mouse_hover', true);
    const p = await tooltip.boundingBox(), t = await firstTrigger.boundingBox();
    const gapY = p.y > t.y ? (t.y + t.height + p.y) / 2 : (p.y + p.height + t.y) / 2;
    await page.mouse.move(t.x + t.width / 2, gapY); await wait(55); check('close_gap_under_150ms_keeps_popup', await tooltip.count() === 1);
    await page.mouse.move(p.x + p.width / 2, p.y + p.height / 2); await wait(450); check('popup_hover_keeps_popup', await tooltip.count() === 1); await retained('popup_hover', true);
    await page.mouse.move(0, 0); await noPreview('last_hover_exit');
    await open(firstTrigger, 'mouse', 'mouse_reenter'); await page.keyboard.press('Escape'); await noPreview('escape'); await wait(450);
    check('escape_same_hover_does_not_reopen', await tooltip.count() === 0); await retained('escape', true);
    check('mouse_same_compare_selection', equal(await choiceState(), choices));
  });
  scenario('keyboard_focus_hover_overlap_and_owner_replacement');
  await uiOnly('keyboard_and_owners', async () => {
    await open(firstTrigger, 'keyboard', 'keyboard_first'); await firstTrigger.hover(); await page.mouse.move(0, 0); await wait(400);
    check('keyboard_focus_keeps_popup_after_pointer_exit', await tooltip.count() === 1 && await firstTrigger.evaluate(node => document.activeElement === node));
    await page.keyboard.press('Escape'); await noPreview('keyboard_escape'); await wait(400); check('escape_same_focus_does_not_reopen', await tooltip.count() === 0);
    await open(firstTrigger, 'keyboard', 'keyboard_reentry'); const firstOwner = await tooltip.getAttribute('data-variant-preview-owner');
    await closePreview('before_owner_race'); await prepare(firstTrigger); await firstTrigger.hover(); await wait(80);
    await open(secondTrigger, 'keyboard', 'pending_A_to_B'); await wait(450);
    check('old_pending_timer_does_not_replace_B', await tooltip.getAttribute('data-variant-preview-owner') === await secondTrigger.getAttribute('data-variant-preview-trigger'));
    await closePreview('before_duplicate_source'); const duplicateOwner = await open(duplicateTrigger, 'keyboard', 'same_sku_source_B');
    check('same_sku_sources_have_exact_distinct_owner', firstOwner === 'query:' + JSON.stringify([fixture.source_ids[0], real[0].variants[0].id])
      && duplicateOwner === 'query:' + JSON.stringify([fixture.source_ids[1], real[1].variants[0].id]) && firstOwner !== duplicateOwner);
    await wait(450); check('old_owner_cleanup_does_not_close_new_owner', await tooltip.count() === 1); await closePreview('owners_end');
  });
  scenario('menu_dialog_contextmenu_and_external_dismissals');
  await uiOnly('menus_dialogs_native_contextmenu', async () => {
    await prepareMenuPair('open_preview_menu_pair');
    await open(firstTrigger, 'keyboard', 'menu_open_preview', true);
    await observeMenuTransition('menu_from_open_preview', async () => {
      check('menu_click_starts_with_open_preview', await tooltip.count() === 1);
      await firstCard.locator('[data-variant-menu-trigger]').click(); await page.getByRole('menu').waitFor(); await noPreview('menu_closes_preview');
    });
    await wait(450); check('menu_blocks_preview_reopen', await tooltip.count() === 0); await page.keyboard.press('Escape'); await page.getByRole('menu').waitFor({ state: 'detached' });
    await prepareMenuPair('pending_preview_menu_pair');
    await observeMenuTransition('menu_from_pending_preview', async () => {
      await firstTrigger.hover(); await wait(60); check('menu_click_starts_before_pending_preview_opens', await tooltip.count() === 0);
      await firstCard.locator('[data-variant-menu-trigger]').click(); await page.getByRole('menu').waitFor();
    });
    await wait(450); await noPreview('menu_blocks_pending_timer'); await page.keyboard.press('Escape'); await page.getByRole('menu').waitFor({ state: 'detached' });
    await prepareMenuPair('keyboard_menu_pair');
    await observeMenuTransition('menu_actual_enter_then_tab', async () => {
      await firstCard.locator('[data-variant-menu-trigger]').evaluate(node => node.focus({ preventScroll: true }));
      await page.keyboard.press('Enter'); await page.getByRole('menu').waitFor();
      await page.keyboard.press('Tab'); await page.getByRole('menu').waitFor({ state: 'detached' });
    });
    await wait(450); await noPreview('menu_real_tab_dismissal_no_preview');
    await prepare(firstTrigger); await firstTrigger.hover(); await wait(60); await page.keyboard.press('Control+k'); await page.getByRole('dialog').waitFor();
    await wait(450); await noPreview('command_dialog_blocks_pending_timer'); await page.keyboard.press('Escape'); await page.getByRole('dialog').waitFor({ state: 'detached' });
    await open(firstTrigger, 'keyboard', 'command_after_open'); await page.keyboard.press('Control+k'); await page.getByRole('dialog').waitFor(); await noPreview('command_dialog_closes_open');
    await page.keyboard.press('Tab'); await page.keyboard.press('Escape'); await page.getByRole('dialog').waitFor({ state: 'detached' });
    await wait(450); await noPreview('command_dialog_tab_then_escape_programmatic_return_no_reopen');
    check('command_dialog_keyboard_close_returns_original_trigger', await firstTrigger.evaluate(node => document.activeElement === node));
    await open(firstTrigger, 'mouse', 'popup_contextmenu');
    await page.evaluate(() => { window.__r130Context = []; window.__r130ContextHandler = event => { const row = { target: event.target.closest('.variant-preview') ? 'popup' : event.target.closest('[data-variant-preview-trigger]') ? 'trigger' : 'other', trusted: event.isTrusted };
      window.__r130Context.push(row); queueMicrotask(() => { row.prevented = event.defaultPrevented; }); }; document.addEventListener('contextmenu', window.__r130ContextHandler, true); });
    await tooltip.click({ button: 'right' }); await wait(100); check('popup_right_click_no_card_menu', await page.getByRole('menu').count() === 0);
    await firstTrigger.click({ button: 'right' }); await wait(100); check('trigger_right_click_no_card_menu', await page.getByRole('menu').count() === 0);
    const rightClicks = await page.evaluate(() => { document.removeEventListener('contextmenu', window.__r130ContextHandler, true); return window.__r130Context; });
    observe('trusted_contextmenu_default_behavior', { events: rightClicks }); check('popup_and_trigger_preserve_native_contextmenu_default', rightClicks.length === 2 && rightClicks.every(row => row.trusted && row.prevented === false)
      && rightClicks[0].target === 'popup' && rightClicks[1].target === 'trigger'); await closePreview('right_click_end');
    await open(firstTrigger, 'mouse', 'outside_focus'); await page.locator('.size-field input').evaluate(node => node.focus({ preventScroll: true })); await noPreview('outside_focus_closes');
    await open(firstTrigger, 'mouse', 'outside_pointer'); await page.mouse.click(4, 4); await noPreview('outside_pointer_closes');
    await open(firstTrigger, 'mouse', 'page_scroll'); await page.mouse.wheel(0, 40); await noPreview('outside_scroll_closes');
    await open(firstTrigger, 'mouse', 'resize'); await page.setViewportSize({ width: 1355, height: 900 }); await noPreview('resize_closes'); await page.setViewportSize({ width: 1365, height: 900 });
    for (const event of ['blur', 'visualViewport_resize', 'hidden']) { await open(firstTrigger, 'mouse', 'synthetic_' + event);
      const syntheticState = await page.evaluate(type => {
        if (type === 'hidden') {
          const keys = ['hidden', 'visibilityState'], original = keys.map(key => Object.getOwnPropertyDescriptor(document, key));
          const sample = () => ({ hidden: document.hidden, visibility_state: document.visibilityState });
          const record = { before: sample(), during: null, after: null, original_own_descriptors: original.map(Boolean), descriptors_restored: false };
          try {
            Object.defineProperty(document, 'hidden', { configurable: true, value: true });
            Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
            record.during = sample(); document.dispatchEvent(new Event('visibilitychange'));
          } finally {
            keys.forEach((key, index) => { if (original[index]) Object.defineProperty(document, key, original[index]); else delete document[key]; });
            record.after = sample();
            record.descriptors_restored = keys.every((key, index) => {
              const current = Object.getOwnPropertyDescriptor(document, key), expected = original[index];
              return !expected ? current === undefined : !!current && ['configurable', 'enumerable', 'writable', 'value', 'get', 'set'].every(field => current[field] === expected[field]);
            });
          }
          return record;
        }
        if (type === 'visualViewport_resize') visualViewport.dispatchEvent(new Event('resize')); else window.dispatchEvent(new Event('blur'));
        return null;
      }, event);
      if (event === 'hidden') {
        observe('synthetic_visibility_hidden_pair_and_restoration', syntheticState);
        check('synthetic_visibility_pair_consistent_and_original_descriptors_restored', syntheticState.during.hidden === true && syntheticState.during.visibility_state === 'hidden'
          && equal(syntheticState.before, syntheticState.after) && syntheticState.descriptors_restored);
      }
      await noPreview('synthetic_' + event + '_closes'); }
  });
  scenario('real_evidence_http_close_focus_and_touch');
  const evidencePath = '/v1/evidence/' + real[0].variants[0].snapshot_id;
  for (const mode of ['mouse', 'touch', 'keyboard']) {
    phase = 'action:evidence_' + mode;
    const gate = await makeGate({ label: 'real_evidence_' + mode, path: evidencePath, method: 'GET', real: true });
    if (mode !== 'touch') await uiOnly('preview_before_real_evidence_' + mode, () => open(firstTrigger, 'keyboard', 'before_evidence_' + mode));
    else await uiOnly('synthetic_touch_enter_no_hover', async () => { await prepare(firstTrigger); await firstTrigger.dispatchEvent('pointerenter', { pointerType: 'touch', pointerId: 9, isPrimary: true, buttons: 0 });
      await wait(420); await noPreview('synthetic_touch_enter_no_hover'); });
    phase = gate.record.phase;
    const remembered = await firstTrigger.evaluate(node => node === window.__r130OriginalTrigger); check(mode + '_original_evidence_button_not_remounted', remembered);
    if (mode === 'touch') { const r = await firstTrigger.boundingBox(); await page.touchscreen.tap(r.x + r.width / 2, r.y + r.height / 2); }
    else if (mode === 'keyboard') await page.keyboard.press('Enter'); else await firstTrigger.click();
    await gate.entered(); await noPreview(mode + '_click_closes_immediately'); await releaseGates([gate]);
    check(mode + '_real_evidence_matches_snapshot', gate.payload()?.id === real[0].variants[0].snapshot_id);
    await page.locator('.evidence-detail').waitFor();
    await uiOnly(mode + '_close_real_evidence', async () => {
      const close = page.getByRole('button', { name: '关闭证据', exact: true });
      if (mode === 'keyboard') {
        let tabs = 0;
        while (!await close.evaluate(node => node === document.activeElement) && tabs < 600) { await page.keyboard.press('Tab'); tabs++; }
        observe('real_keyboard_navigation_to_evidence_close', { actual_tab_presses: tabs, bound: 600 });
        check('real_tab_reaches_evidence_close', tabs > 0 && tabs < 600 && await close.evaluate(node => node === document.activeElement));
        await page.keyboard.press('Enter');
      } else await close.click();
      await wait(450); await noPreview(mode + '_programmatic_return_focus_no_reopen');
      check(mode + '_close_returns_same_original_button', await firstTrigger.evaluate(node => document.activeElement === node && node === window.__r130OriginalTrigger)); });
  }
  await uiOnly('explicit_tab_after_evidence_return_reopens', async () => {
    await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab'); await tooltip.waitFor();
    check('post_evidence_real_tab_uses_original_button', await firstTrigger.evaluate(node => node === window.__r130OriginalTrigger && node === document.activeElement && node.matches(':focus-visible'))
      && await tooltip.getAttribute('data-variant-preview-owner') === await firstTrigger.getAttribute('data-variant-preview-trigger'));
    await closePreview('post_evidence_real_tab_end');
  });
  scenario('held_real_watch_response_preserves_query_input');
  phase = 'action:real_watch';
  const watchGate = await makeGate({ label: 'real_watch', path: '/v1/watchlists', status: 201, expectedBody: { variant_id: real[0].variants[0].id }, real: true });
  await firstCard.locator('.bookmark-button').click(); await watchGate.entered();
  await page.locator('.size-field input').evaluate(node => { node.scrollIntoView({ block: 'center', behavior: 'instant' }); node.focus({ preventScroll: true }); node.setSelectionRange(2, 7); });
  await framesSettled(); observe('held_response_input_baseline', await captureInputs(true));
  check('held_watch_has_exact_one_request_and_real_201', heldRequests.size === 1 && watchGate.payload()?.variant_id === real[0].variants[0].id);
  await releaseGates([watchGate]); await retained('real_watch_response', true); check('real_watch_preserves_selection_and_comparison', equal(await choiceState(), choices));

  // Only these bounded, explicitly synthetic HTTP payloads carry long values or
  // multiple risk states. They are never persisted and do not alter the fixture.
  const long = structuredClone(real[0].variants[0]);
  Object.assign(long, { brand: '原品牌🛞'.repeat(12), model: '原记录型号'.repeat(16), size: '265/40R20 ' + '原尺寸'.repeat(20), load_index: 0,
    speed_rating: null, region: '原地区'.repeat(20), manufacturer_product_code: 'ORIGINAL-<b>-🛞-'.repeat(8),
    lifecycle: { state: 'revoked', revision: 1, event_id: null, operator: 'R130 synthetic', reason: 'R130 synthetic revoked', changed_at: null },
    identity_resolution: { state: 'needs_review', revision: 1, target_id: null, event_id: null },
    identity_contract: { schema: 'variant-identity@2', state: 'current', current_key: null,
      current_identity: { product_code_type: 'TYPE-'.repeat(20), manufacturer_product_code: 'MUST-NOT-REPLACE-ORIGINAL' },
      identity_status: 'source_scoped', origin: 'R130 synthetic browser DTO', reason_codes: [], related_candidates: [], tracking_state: 'identity_review_required', notice: 'R130 synthetic' },
    facts: { source_field_conflicts: [{ field: 'xl', values: [{ source_field: 'extraLoad', value: true }, { source_field: 'manufMarkings', value: false }], resolution: 'unresolved' }],
      source_field_anomalies: [{ field: 'utqg_temperature', raw_value: 'D', reason: 'source_temperature_outside_standard_enum' }], do_not_preview: 'FACTS-SECRET-SENTINEL' },
    effective_facts: { do_not_preview: 'EFFECTIVE-SECRET-SENTINEL' },
    field_resolution: { policy: { version: 'R130 synthetic', digest: 'synthetic' }, variant_id: long.id, scope: 'current_source', data_state: 'live', fingerprint: 'synthetic', notice: 'R130 synthetic',
      fields: [{ field: 'load_index', label: '载重', unit: null, category: 'identity', identity_bound: true, source_scope_only: false, state: 'conflict_tied',
        has_default: true, default_value: 999, default_candidate_ids: [], candidates: [], reasons: [] }] } });
  const syntheticDtos = real.map((dto, index) => ({ ...structuredClone(dto), variants: [index === 0 ? long : { ...structuredClone(real[1].variants[0]), brand: '来源B原品牌' }], provenance: [], conflicts: [],
    selection: { filters: [], source_count: 1, matched_count: 1, excluded_count: 0, undetermined_count: 0 } }));
  check('synthetic_query_payloads_bounded_one_row_each_under_64KiB', syntheticDtos.every(dto => dto.variants.length === 1 && Buffer.byteLength(JSON.stringify(dto)) <= 65536));
  receipt.synthetic_payloads = syntheticDtos.map((dto, index) => ({ label: 'long_risks_source_' + index, exact_url: api('/v1/sources/' + fixture.source_ids[index] + '/live-query'),
    bytes: Buffer.byteLength(JSON.stringify(dto)), sha256: sha(Buffer.from(JSON.stringify(dto))), variant_count: 1, delivery: 'single_browser_route_fulfill_no_backend_dispatch' }));
  await queryPair('synthetic_long_original_fields_and_six_risks', syntheticDtos);
  const longTrigger = trigger(card(0, long.id));
  const expectedRisks = {
    revoked: '已撤销', identity: '身份修订/待核对，未替换原规格', 'source-conflict': '来源冲突待核验',
    anomaly: '参数异常，保留原文', 'field-conflict': '字段判定仍有冲突', tracking: '关注需要身份复核',
  };
  const assertContent = async label => {
    const value = await tooltip.evaluate(node => ({ text: node.textContent,
      fields: Object.fromEntries([...node.querySelectorAll('[data-variant-preview-field]')].map(item => [item.dataset.variantPreviewField, item.textContent])),
      risks: Object.fromEntries([...node.querySelectorAll('[data-variant-preview-risk]')].map(item => [item.dataset.variantPreviewRisk, item.textContent])),
      identity: node.querySelector('[data-variant-preview-identity] p')?.textContent, note: node.querySelector('.variant-preview-note')?.textContent,
      field_titles: [...node.querySelectorAll('[data-variant-preview-field]')].filter(item => item.hasAttribute('title')).length,
      injected_elements: node.querySelectorAll('b,script,img,iframe').length }));
    observe(label + '_excerpt_content', value);
    check(label + '_seven_original_fields_zero_missing_and_code_preserved', equal(Object.keys(value.fields).sort(), ['brand', 'model', 'size', 'load_index', 'speed_rating', 'region', 'manufacturer_product_code'].sort())
      && value.fields.load_index === '0' && (value.fields.speed_rating === '来源未标明' || value.fields.speed_rating.endsWith('…') && '来源未标明'.startsWith(value.fields.speed_rating.slice(0, -1)))
      && value.fields.manufacturer_product_code.endsWith('…') && long.manufacturer_product_code.startsWith(value.fields.manufacturer_product_code.slice(0, -1)));
    for (const key of ['brand', 'model', 'size', 'region', 'manufacturer_product_code']) check(label + '_' + key + '_explicit_unicode_bounded_excerpt',
      [...value.fields[key]].length <= 33 && value.fields[key].endsWith('…') && long[key].startsWith(value.fields[key].slice(0, -1)));
    check(label + '_identity_status_prefix_bounded_and_all_risks_intact', value.identity.startsWith('现行身份 v2') && [...value.identity].length <= 65
      && equal(value.risks, expectedRisks) && value.note === '摘要节选，完整信息见卡片');
    check(label + '_no_fact_default_current_code_html_or_title_substitution', !['MUST-NOT-REPLACE-ORIGINAL', 'FACTS-SECRET-SENTINEL', 'EFFECTIVE-SECRET-SENTINEL', '999'].some(text => value.text.includes(text))
      && value.injected_elements === 0 && value.field_titles === 0);
  };
  scenario('four_viewports_long_excerpts_all_risks_and_typography');
  for (const [width, height] of [[1365, 900], [390, 844], [320, 844], [320, 420]]) {
    const label = 'long_risks_' + width + 'x' + height;
    await uiOnly(label, async () => {
      await closePreview(label + '_before_resize'); await page.setViewportSize({ width, height }); await open(longTrigger, 'keyboard', label);
      await assertContent(label); await geometry(longTrigger, label); await shot(label); await closePreview(label + '_closed');
    });
  }
  await page.setViewportSize({ width: 1365, height: 900 });
  scenario('light_dark_high_contrast_forced_colors_and_local_200_percent_text');
  for (const preference of ['light', 'dark', 'high-contrast']) {
    await uiOnly('theme_' + preference, async () => {
      await page.getByRole('combobox', { name: '主题', exact: true }).selectOption(preference); await frames();
      check('actual_theme_' + preference, await page.evaluate(() => document.documentElement.dataset.theme) === preference);
      await open(longTrigger, 'keyboard', 'theme_' + preference); await assertContent('theme_' + preference); await geometry(longTrigger, 'theme_' + preference);
      await shot('preview-' + preference); await closePreview('theme_' + preference + '_end');
    });
  }
  await uiOnly('forced_colors', async () => {
    await page.emulateMedia({ forcedColors: 'active' }); await open(longTrigger, 'keyboard', 'forced_colors'); await geometry(longTrigger, 'forced_colors');
    check('forced_colors_media_actual', await page.evaluate(() => matchMedia('(forced-colors: active)').matches)); await shot('preview-forced-colors');
    await closePreview('forced_colors_end'); await page.emulateMedia({ forcedColors: 'none' });
  });
  await uiOnly('synthetic_local_200_percent_text', async () => {
    await page.getByRole('combobox', { name: '主题', exact: true }).selectOption('light');
    await open(longTrigger, 'keyboard', 'font_stress');
    const baseline = await tooltip.evaluate(node => {
      const elements = [node, ...node.querySelectorAll('*')], saved = elements.map(item => ({ item, style: item.getAttribute('style'), font: parseFloat(getComputedStyle(item).fontSize) }));
      window.__r130FontRestore = () => saved.forEach(({ item, style }) => { if (style === null) item.removeAttribute('style'); else item.setAttribute('style', style); });
      saved.forEach(({ item, font }) => item.style.setProperty('font-size', (font * 2) + 'px', 'important'));
      return saved.map(({ item, font }) => ({ tag: item.tagName, before_px: font, after_px: parseFloat(getComputedStyle(item).fontSize) }));
    });
    observe('synthetic_local_200_percent_text_not_browser_zoom', { elements: baseline });
    check('every_measured_preview_font_doubled', baseline.every(row => Math.abs(row.after_px - row.before_px * 2) < .1));
    await framesSettled(); await geometry(longTrigger, 'synthetic_local_200_percent_text', 26); await assertContent('synthetic_local_200_percent_text'); await shot('preview-synthetic-local-200-percent-text');
    await page.evaluate(() => { window.__r130FontRestore(); delete window.__r130FontRestore; }); await closePreview('font_stress_end');
  });

  scenario('synthetic_duplicate_watch_records_and_outer_tracking_risk');
  const watchId = watchGate.payload().id, duplicateId = randomUUID();
  const watchVariant = structuredClone(long); watchVariant.identity_contract.tracking_state = 'current';
  const duplicateVariant = structuredClone(real[0].variants[0]); duplicateVariant.brand = '第二关注记录原品牌';
  const watchBody = { items: [
    { id: watchId, variant_id: long.id, variant: watchVariant, tracking_state: 'identity_review_required' },
    { id: duplicateId, variant_id: long.id, variant: duplicateVariant, tracking_state: 'current' },
  ] };
  check('synthetic_watch_exact_two_same_sku_records_under_64KiB', watchId !== duplicateId && Buffer.byteLength(JSON.stringify(watchBody)) <= 65536);
  receipt.synthetic_payloads.push({ label: 'duplicate_watch_records', exact_url: api('/v1/watchlists'), bytes: Buffer.byteLength(JSON.stringify(watchBody)),
    sha256: sha(Buffer.from(JSON.stringify(watchBody))), record_count: 2, delivery: 'single_browser_route_fulfill_no_backend_dispatch' });
  phase = 'navigation:watch';
  const watchRead = await makeGate({ label: 'synthetic_duplicate_watch_read', path: '/v1/watchlists', method: 'GET', body: watchBody });
  // Click without waiting for idle: the gate deliberately holds this response.
  await page.locator('.main-nav').getByRole('button', { name: /关注/ }).click(); await watchRead.entered(); await releaseGates([watchRead]);
  const watchTrigger = page.locator(`[data-variant-preview-trigger="watch:${watchId}"]`), duplicateWatchTrigger = page.locator(`[data-variant-preview-trigger="watch:${duplicateId}"]`);
  await uiOnly('watch_record_owners_and_tracking', async () => {
    await open(watchTrigger, 'keyboard', 'watch_first'); await assertContent('watch_outer_tracking');
    check('watch_outer_tracking_preserved_without_contract_merge', await tooltip.locator('[data-variant-preview-risk="tracking"]').count() === 1);
    await geometry(watchTrigger, 'watch_risks_wide'); await shot('preview-watch-outer-tracking');
    await closePreview('watch_between'); await open(duplicateWatchTrigger, 'keyboard', 'watch_same_sku_second_record'); await wait(420);
    check('watch_same_sku_second_record_owns_unique_popup', await tooltip.getAttribute('data-variant-preview-owner') === 'watch:' + duplicateId
      && await tooltip.locator('[data-variant-preview-field="brand"]').innerText() === '第二关注记录原品牌'
      && await tooltip.locator('[data-variant-preview-risk="tracking"]').count() === 0);
    await closePreview('watch_owner_end');
  });
  await uiOnly('navigation_unmount_pending_preview_bounded_absence', async () => {
    await prepare(duplicateWatchTrigger); await duplicateWatchTrigger.hover(); await wait(60);
    await page.locator('.main-nav').getByRole('button', { name: /轮胎查询/ }).click(); await wait(650); await noPreview('watch_unmount_no_late_open');
    check('old_watch_trigger_unmounted', await duplicateWatchTrigger.count() === 0);
  });
  await uiOnly('drag_pointer_buttons_suppress_hover', async () => {
    await prepare(longTrigger); await page.mouse.move(0, 0); await page.mouse.down(); await longTrigger.hover(); await wait(420);
    await noPreview('held_pointer_does_not_open'); await page.mouse.up(); await page.mouse.move(0, 0);
  });
  const finalFixture = await json(await context.request.get(api('/fixture/state')));
  receipt.final_fixture = { counters: finalFixture.counters, source_calls: finalFixture.source_calls, real_source_calls: finalFixture.real_source_calls,
    provider_calls: finalFixture.provider_calls, model_requests: finalFixture.model_requests, embedding_requests: finalFixture.embedding_requests };
  check('only_two_real_source_calls_zero_external_child_normal_db_model', finalFixture.source_calls === 2 && finalFixture.real_source_calls === 0
    && Object.values(finalFixture.counters).every(value => value === 0) && finalFixture.provider_calls === 0 && finalFixture.model_requests === 0 && finalFixture.embedding_requests === 0);
  check('exact_four_query_posts_three_evidence_reads_one_watch_post', queryRows().length === 4 && snapshotRows().length === 3
    && postRows().filter(row => row.path === '/api/v1/watchlists').length === 1);
  check('every_mutation_is_initial_preview_or_exact_planned_gate', postRows().every(row => row.request_id === preview.request_id && row.sequence <= initializationEnd
    || receipt.request_gates.some(record => record.method === 'POST' && record.request_id === row.request_id && record.claimed && record.body_matched))
    && receipt.http_events.every(row => row.event !== 'request' || !row.business || ['GET', 'POST'].includes(row.method)));
  check('all_nine_request_gates_exact_finished_removed', gatesPassed());
  check('all_ui_windows_zero_business_requests', receipt.ui_request_windows.length >= 18 && receipt.ui_request_windows.every(row => row.business_requests.length === 0));
  check('strict_browser_network_gate_zero_errors_external_unexpected_http', !receipt.page_errors.length && !receipt.console_errors.length && !receipt.unexpected_origins.length
    && !receipt.unexpected_http_statuses.length && !receipt.gate_failures.length && receipt.http_events.every(row => row.event !== 'failed'));
  receipt.production_workbench_verified = true; receipt.state = 'passed';
} catch (error) {
  receipt.state = 'failed'; receipt.failure = { stage, type: ['Error', 'TimeoutError', 'TypeError', 'SyntaxError'].includes(error?.name) ? error.name : 'Error',
    check: /^[a-zA-Z0-9_:-]+$/.test(error?.message || '') ? error.message : null,
    source_frames: [...String(error?.stack || '').matchAll(/variant_preview_ui_qa\.mjs:(\d+):(\d+)/g)].map(match => ({ line: Number(match[1]), column: Number(match[2]) })) };
  if (page) try { await page.screenshot({ path: resolve(output, 'failure.png') }); receipt.screenshots.push('failure.png'); } catch {}
} finally {
  password = null;
  for (const gate of gates) gate.release();
  for (const gate of [...gates]) { try { if (gate.record.claimed) await gate.settle(); await gate.remove(); } catch { receipt.cleanup_failures.push('pending_gate_cleanup_failed'); } }
  if (page) try { await page.evaluate(() => { window.__r130Timing?.dispose(); window.__r130FontRestore?.(); window.__r130MenuProbe?.dispose();
    if (window.__r130ContextHandler) document.removeEventListener('contextmenu', window.__r130ContextHandler, true); }); } catch { receipt.cleanup_failures.push('qa_observer_cleanup_failed'); }
  try { if (context) { const response = await context.request.post(fixtureOrigin + '/fixture/shutdown', { timeout: 5000 }); receipt.fixture_shutdown_requested = response.ok(); } } catch { receipt.cleanup_failures.push('fixture_shutdown_request_failed'); }
  let closeTimer;
  try { await Promise.race([(async () => { if (context) await context.close(); if (browser) await browser.close(); if (browserServer) await browserServer.close(); })(),
    new Promise((_, reject) => { closeTimer = setTimeout(() => reject(Error('browser_close_timeout')), 20000); })]);
    receipt.browser_close_returned = !!browserProcess && browserProcess.exitCode === 0 && browserProcess.signalCode === null && receipt.browser.server_close_observed === true;
  } catch { receipt.cleanup_failures.push('browser_close_failed'); if (browserServer) { receipt.browser.forced_kill_requested = true; try { await browserServer.kill(); } catch { receipt.cleanup_failures.push('browser_kill_failed'); } } }
  finally { clearTimeout(closeTimer); }
  receipt.request_gate_coverage = { required: 9, recorded: receipt.request_gates.length, state: gatesPassed() ? 'passed' : 'failed', routes_removed: gates.size === 0 && activeRecords.size === 0 };
  if (!gatesPassed()) receipt.coverage_failures.push('nine_exact_planned_requests_not_satisfied');
  if (gates.size || activeRecords.size || receipt.request_gates.some(record => record.active || !record.route_removed)) receipt.cleanup_failures.push('terminal_route_cleanup_failed');
  if (receipt.page_errors.length || receipt.console_errors.length || receipt.unexpected_origins.length || receipt.unexpected_http_statuses.length || receipt.gate_failures.length
    || receipt.http_events.some(row => row.event === 'failed' || row.event === 'response' && row.status >= 400)) receipt.cleanup_failures.push('terminal_browser_or_network_error');
  try { receipt.inputs_unchanged = equal(snapshot(Object.keys(inputPins)), inputPins); } catch { receipt.inputs_unchanged = false; }
  if (!receipt.inputs_unchanged) receipt.cleanup_failures.push('input_drift');
  try { receipt.prepared_runtimes_unchanged = equal(tree(playwrightRoot), runtimePins.playwright) && equal(tree(browserRoot), runtimePins.browser) && equal(tree(privatePlaywright), runtimePins.playwright)
    && equal(tree(privateBrowser, undefined, receipt.browser_generated_sidecars, runtimePins.browser), runtimePins.browser); } catch { receipt.prepared_runtimes_unchanged = false; }
  if (!receipt.prepared_runtimes_unchanged) receipt.cleanup_failures.push('runtime_drift_or_copy_incomplete');
  if (!receipt.browser_close_returned || !receipt.fixture_shutdown_requested || receipt.browser.forced_kill_requested || receipt.coverage_failures.length || receipt.cleanup_failures.length) receipt.state = 'failed';
  receipt.artifact_hashes = snapshot(receipt.screenshots.map(name => resolve(output, name))); receipt.finished_utc = new Date().toISOString(); save();
  writeFileSync(resolve(output, 'browsercleanup.json'), JSON.stringify({ state: receipt.state, browser: receipt.browser, browser_close_returned: receipt.browser_close_returned,
    fixture_shutdown_requested: receipt.fixture_shutdown_requested, coverage_failures: receipt.coverage_failures, request_gate_coverage: receipt.request_gate_coverage,
    cleanup_failures: receipt.cleanup_failures, inputs_unchanged: receipt.inputs_unchanged, prepared_runtimes_unchanged: receipt.prepared_runtimes_unchanged,
    browser_generated_sidecars: receipt.browser_generated_sidecars, browser_generated_sidecar_policy: sidecarPolicy }, null, 2) + '\n');
}
console.log(JSON.stringify({ state: receipt.state, output, checks: receipt.checks.length, failure: receipt.failure || null }));
if (receipt.state !== 'passed') process.exitCode = 3;
