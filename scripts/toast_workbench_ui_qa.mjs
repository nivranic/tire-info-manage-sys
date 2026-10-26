/** R128: current production Workbench, real private-fixture watch HTTP and toast integration.
 * Root alone runs after independent review and a passed current-source build.
 * No controlled clock, product-code injection, database wrapper or process supervisor lives here.
 * One explicitly bounded browser-route watch503 exercises the existing error toast.
 */
import { createHash, randomBytes } from 'node:crypto';
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
if (origin !== 'http://127.0.0.1:18987' || dirname(output) !== artifacts || !/^r128browser-[a-f0-9]{16}$/.test(basename(output))
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
  resolve(root, '.artifacts/r127-variant-context-menu-20261022/run-ui-host.py'), resolve(root, '.artifacts/r128-toast-lifecycle-layout-20261023/run-ui-host.py'),
  resolve(root, '.artifacts/r118-material-workbench-20261021/serve-web-v1.py'), resolve(root, 'docs/plans/2026-10-23-toast-lifecycle-layout.md'),
  resolve(root, '.artifacts/r128-toast-lifecycle-layout-20261023/product-review.json')]) };
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
const receipt = { schema: 'r128-toast-production-workbench@1', state: 'running', started_utc: new Date().toISOString(), origin, fixture_origin: fixtureOrigin,
  build, build_report_sha256: reportSha, input_pins: inputPins, runtime_pins: runtimePins, checks: [], scenarios: [], observations: [], screenshots: [], http_events: [], ui_request_windows: [],
  unexpected_origins: [], unexpected_http_statuses: [], synthetic_http_faults: [], page_errors: [], console_errors: [], gate_failures: [], coverage_failures: [], cleanup_failures: [], browser_generated_sidecars: [], browser_generated_sidecar_policy: sidecarPolicy,
  browser: { playwright: '1.63.0', chromium_revision: '1243', headless: true }, browser_close_returned: false, fixture_shutdown_requested: false,
  inputs_unchanged: false, prepared_runtimes_unchanged: false, synthetic_only: true, production_workbench_verified: false,
  explicit_limitations: ['project_owned_synthetic_sources_accounts_only', 'service_workers_blocked_matching_build_public_served_by_page_route',
    'real_clock_bounded_hover_focus_observation_not_full_timer_boundary_suite', 'price_draft_checked_in_sources_view_after_intentional_navigation_query_dom_not_claimed_across_views',
    'one_exact_watch_post_503_is_browser_route_injection_without_backend_dispatch_not_a_real_backend_failure',
    'screenshots_require_root_visual_inspection', 'no_real_provider_normal_database_native_host_device_ime_reader_pwa_or_complete_v1_claim'] };
const save = () => writeFileSync(resolve(output, 'result.json'), JSON.stringify(receipt, null, 2) + '\n');
const check = (label, condition) => { if (!condition) throw Error(label); receipt.checks.push(label); save(); };
const observe = (label, value) => { receipt.observations.push({ label, ...value }); save(); };
const api = path => origin + '/api' + path;
const json = async response => { if (!response.ok()) throw Error('HTTP_' + response.status()); return response.json(); };
const wait = ms => new Promise(done => setTimeout(done, ms));
const privatePlaywright = resolve(output, 'runtime/playwright-core'), privateBrowser = resolve(output, 'runtime/chromium_headless_shell-1243');
let browser, browserServer, browserProcess, context, page, stage = 'runtime_copy', phase = 'initialization', password = randomBytes(24).toString('base64url');
const inFlight = new Set(), heldRequests = new Set(), gates = new Set(), expectedHttpFaults = new Map(), expectedFaultRequests = new WeakMap(), requestIds = new WeakMap();
let requestSequence = 0;
const faultBoundsPassed = () => receipt.synthetic_http_faults.length === 1 && expectedHttpFaults.size === 0 && receipt.synthetic_http_faults.every(fault =>
  fault.method === 'POST' && fault.url === api('/v1/watchlists') && fault.status === 503 && fault.phase === 'action:synthetic_watch_503'
  && fault.origin === 'synthetic_browser_route_injection_without_backend_dispatch' && !fault.active && fault.route_removed && fault.claimed
  && fault.requests === 1 && fault.injected_responses === 1 && fault.observed_responses === 1 && fault.completed
  && fault.console_errors >= 0 && fault.console_errors <= 1 && Number.isInteger(fault.request_id) && fault.request_id > 0);
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
  context = await browser.newContext({ baseURL: origin, serviceWorkers: 'block', colorScheme: 'light', viewport: { width: 1365, height: 900 } });
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
  const record = (event, request, status, expectedStatus = false) => { const url = new URL(request.url()); const business = [origin, fixtureOrigin].includes(url.origin) && (url.origin === fixtureOrigin || url.pathname.startsWith('/api/'));
    if (!requestIds.has(request)) requestIds.set(request, ++requestSequence);
    const row = { sequence: receipt.http_events.length + 1, request_id: requestIds.get(request), phase, event, method: request.method(), path: [origin, fixtureOrigin].includes(url.origin) ? url.pathname : 'blocked', business,
      ...(url.pathname === '/api/v1/personal-feed/preview' ? { query: url.search } : {}),
      ...(status === undefined ? {} : { status, expected_status: expectedStatus }), ...(event === 'failed' ? { failure: request.failure()?.errorText === 'net::ERR_ABORTED' ? 'aborted' : 'other' } : {}) };
    receipt.http_events.push(row);
    if (event === 'response' && status >= 400 && !expectedStatus) receipt.unexpected_http_statuses.push({ sequence: row.sequence, request_id: row.request_id, phase, method: row.method, path: row.path, status }); };
  page.on('request', request => { record('request', request); if (new URL(request.url()).pathname.startsWith('/api/')) inFlight.add(request); });
  page.on('response', response => { const request = response.request(), fault = expectedHttpFaults.get(response.url());
    const expected = !!fault?.active && expectedFaultRequests.get(request) === fault && phase === fault.phase && request.method() === fault.method
      && requestIds.get(request) === fault.request_id && response.status() === fault.status && fault.requests === 1 && fault.injected_responses === 1 && fault.observed_responses === 0;
    if (expected) fault.observed_responses++;
    record('response', request, response.status(), expected);
  });
  page.on('requestfinished', request => { inFlight.delete(request); record('finished', request); });
  page.on('requestfailed', request => { inFlight.delete(request); record('failed', request); });
  page.on('pageerror', error => receipt.page_errors.push(error?.name || 'PageError'));
  page.on('console', message => {
    if (message.type() !== 'error') return;
    // ConsoleMessage exposes a resource URL, not a Request object. Match the
    // exact URL, the sole claimed POST's active phase and one bounded 503
    // resource error, following the reviewed R127 fault association contract.
    const fault = expectedHttpFaults.get(message.location().url);
    if (fault?.active && phase === fault.phase && fault.method === 'POST' && fault.claimed && fault.requests === 1 && fault.injected_responses === 1
        && fault.console_errors < 1 && /^Failed to load resource: the server responded with a status of 503\b/.test(message.text())) fault.console_errors++;
    else receipt.console_errors.push('browser_console_error');
  });
  const frames = () => page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
  const idle = async () => { for (let attempt = 0; attempt < 100; attempt++) { await frames(); if ([...inFlight].every(request => heldRequests.has(request))) { await wait(100); if ([...inFlight].every(request => heldRequests.has(request))) return; } await wait(50); } throw Error('business_requests_did_not_settle'); };
  const shot = async label => { const name = label + '.png'; await page.screenshot({ path: resolve(output, name) }); receipt.screenshots.push(name); save(); };
  const scenario = label => { stage = label; receipt.scenarios.push(label); save(); };
  const uiOnly = async (label, operation) => { await idle(); const start = receipt.http_events.length; phase = 'ui:' + label; await operation(); await frames(); await wait(100);
    const requests = receipt.http_events.slice(start).filter(row => row.event === 'request' && row.business); receipt.ui_request_windows.push({ label, start_sequence: start + 1, end_sequence: receipt.http_events.length, business_requests: requests });
    check(label + '_zero_new_business_requests', requests.length === 0); };
  const makeGate = async method => {
    const pattern = method === 'POST' ? '**/api/v1/watchlists' : '**/api/v1/watchlists/*';
    let enter, release, finish, requestCount = 0, status, payload;
    const entered = new Promise(done => { enter = done; }), released = new Promise(done => { release = done; }), completed = new Promise(done => { finish = done; });
    const observation = { label: 'real_http_gate', method, pattern, requests: 0, released: false, completed: false }; receipt.observations.push(observation);
    const handler = async route => { if (route.request().method() !== method) { await route.fallback(); return; } requestCount++; observation.requests = requestCount; heldRequests.add(route.request());
      try { const response = await route.fetch(); status = response.status(); observation.real_http_status = status; if (status === 204) await response.body(); else payload = await response.json(); enter(); await released; observation.released = true; await route.fulfill({ response }); }
      catch (error) { receipt.gate_failures.push({ method, type: error?.name || 'Error' }); try { await route.abort('failed'); } catch {} }
      finally { heldRequests.delete(route.request()); observation.completed = true; enter(); finish(); }
    };
    await context.route(pattern, handler);
    const bounded = async promise => { let timer; try { await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(Error('http_gate_timeout')), 10000); })]); } finally { clearTimeout(timer); } };
    const gate = { entered: () => bounded(entered), release, settle: () => bounded(completed), status: () => status, payload: () => payload, count: () => requestCount,
      remove: async () => { await context.unroute(pattern, handler); gates.delete(gate); } }; gates.add(gate); return gate;
  };
  const fixture = await json(await context.request.get(api('/fixture/state')));
  check('private_synthetic_fixture_zero_real_model_usage', fixture.synthetic_only && !fixture.normal_database_used && fixture.real_source_calls === 0 && fixture.provider_calls === 0 && fixture.model_requests === 0 && fixture.embedding_requests === 0);
  const admin = await json(await context.request.post(api('/v1/auth/register'), { data: { username: 'r128_admin_' + randomBytes(4).toString('hex'), password } })); password = null;
  check('admin_registered_real_private_http', admin.user?.is_admin === true);
  stage = 'production_document_initialization';
  check('production_document_http_200', (await page.goto(origin, { waitUntil: 'domcontentloaded' }))?.status() === 200);
  await page.locator('.sidebar-foot small').filter({ hasText: '管理员 · 本机工作台' }).waitFor();
  // Let the existing home-feed effect complete before intentional navigation.
  // Its exact history preview is initialization, never a toast POST allowance.
  stage = 'initialization_history_preview';
  await page.locator('.home-counts').waitFor(); await idle();
  const initializationEnd = receipt.http_events.length;
  const initializationPosts = receipt.http_events.slice(0, initializationEnd).filter(row => row.event === 'request' && row.method === 'POST');
  const previewRequest = initializationPosts[0];
  check('initialization_exact_single_history_preview_200_finished', initializationPosts.length === 1
    && previewRequest.path === '/api/v1/personal-feed/preview' && previewRequest.query === '?mode=history' && previewRequest.phase === 'initialization'
    && receipt.http_events.some(row => row.request_id === previewRequest.request_id && row.event === 'response' && row.status === 200)
    && receipt.http_events.some(row => row.request_id === previewRequest.request_id && row.event === 'finished'));
  receipt.initialization_business_window = { start_sequence: 1, end_sequence: initializationEnd, phase: 'initialization',
    preview_request_id: previewRequest.request_id, business_requests: receipt.http_events.slice(0, initializationEnd).filter(row => row.event === 'request' && row.business) };
  save();
  const isInitializationPreview = row => row.request_id === previewRequest.request_id && row.sequence <= initializationEnd
    && row.phase === 'initialization' && row.path === '/api/v1/personal-feed/preview' && row.query === '?mode=history';
  const navigate = async view => { phase = 'navigation:' + view; const wide = await page.evaluate(() => innerWidth >= 768);
    await page.locator(wide ? '.main-nav' : '.mobile-nav').getByRole('button', { name: wide ? view === 'query' ? /轮胎查询/ : /来源与证据/ : view === 'query' ? '查询' : '来源', exact: !wide }).click(); await idle(); };
  await navigate('query');
  await page.locator('.model-field select').selectOption(fixture.model); await page.locator('.region-selector select').selectOption('US'); await page.locator('.size-field input').fill('265/40R20');
  scenario('real_query_selection_and_comparison'); phase = 'action:query';
  const pendingQueries = fixture.source_ids.map(id => page.waitForResponse(response => response.url() === api('/v1/sources/' + id + '/live-query') && response.request().method() === 'POST'));
  stage = 'query_submit'; await page.locator('.query-submit').click();
  stage = 'query_response_payloads';
  const values = await Promise.all(pendingQueries.map(async (pending, index) => { const response = await pending; check('query_http_200_' + receipt.checks.length, response.status() === 200);
    const value = await response.json(); observe('query_response_payload', { expected_source_id: fixture.source_ids[index], source_id: value.source_id ?? null,
      data_state: value.data_state ?? null, variant_count: Array.isArray(value.variants) ? value.variants.length : null,
      reason: /^[a-z0-9_:-]{1,100}$/i.test(value.reason || '') ? value.reason : null, reason_present: !!value.reason }); return value; }));
  stage = 'query_live_payload_contract';
  check('two_exact_sources_return_real_live_variant_arrays', values.length === 2 && values.every((value, index) => value.source_id === fixture.source_ids[index]
    && value.data_state === 'live' && Array.isArray(value.variants)));
  const a = values[0].variants.map(row => row.id), b = values[1].variants.map(row => row.id);
  check('synthetic_26_plus_3_rows_and_shared_exact_id', a.length === 26 && b.length === 3 && a[0] === b[0] && new Set([...a, ...b]).size === 28);
  stage = 'query_selection_toolbar'; await page.locator('[data-query-selection-toolbar]').waitFor(); await idle();
  stage = 'query_source_groups_and_visible_cards';
  const groupA = page.locator('.source-result').filter({ has: page.getByRole('heading', { name: 'R122 合成来源 A', exact: true }) });
  const groupB = page.locator('.source-result').filter({ has: page.getByRole('heading', { name: 'R122 合成来源 B', exact: true }) });
  check('query_source_groups_and_visible_cards_match_live_payload', await groupA.count() === 1 && await groupB.count() === 1
    && await groupA.locator('input[data-query-selection-id]').count() === 20 && await groupB.locator('input[data-query-selection-id]').count() === 3);
  const card = id => groupA.locator('article.variant-card').filter({ has: page.locator(`input[data-query-selection-id="${id}"]`) });
  stage = 'query_real_checkbox_and_compare_actions';
  await groupA.locator(`input[data-query-selection-id="${a[0]}"]`).check(); await card(a[1]).getByRole('button', { name: '加入比较', exact: true }).click();
  await page.locator('.comparison-tray').waitFor();
  const choiceState = () => page.evaluate(() => ({ selected: [...document.querySelectorAll('input[data-query-selection-id]:checked')].map(node => node.getAttribute('data-query-selection-row')).sort(),
    compared: [...document.querySelectorAll('.results-list .variant-actions button[aria-pressed="true"]')].map(node => node.closest('[data-variant-menu-owner]').getAttribute('data-variant-menu-owner')).sort(),
    sources: [...document.querySelectorAll('.source-selector input')].map(node => node.checked) }));
  const choices = await choiceState();
  check('real_checkbox_and_compare_state_established', await groupA.locator(`input[data-query-selection-id="${a[0]}"]`).isChecked()
    && await groupB.locator(`input[data-query-selection-id="${a[0]}"]`).isChecked() && !await groupA.locator(`input[data-query-selection-id="${a[1]}"]`).isChecked()
    && await card(a[1]).getByRole('button', { name: '已加入比较', exact: true }).getAttribute('aria-pressed') === 'true'
    && choices.selected.length === 2 && choices.compared.length === 1 && choices.sources.length === 2 && choices.sources.every(Boolean));
  const captureQuery = () => page.evaluate(() => { const selectors = ['.size-field input', '.model-field select', '.region-selector select'];
    const nodes = selectors.map(selector => document.querySelector(selector)); const input = nodes[0]; input.focus({ preventScroll: true }); input.setSelectionRange(2, 7);
    window.__r128Retained = { selectors, nodes, values: nodes.map(node => node.value), active: input, start: input.selectionStart, end: input.selectionEnd, scrollY };
    return { values: nodes.map(node => node.value), start: input.selectionStart, end: input.selectionEnd, scrollY }; });
  const prepareInputBeforeRelease = async (inputLocator, start, end, label) => {
    check(label + '_capture_before_release_has_one_held_request_' + receipt.checks.length, heldRequests.size === 1);
    // Earlier bookmark/fill actions can leave the document's default smooth
    // scroll in flight. Establish a visible, settled input before the held
    // response is released; never scroll or rewrite this baseline on appearance.
    await inputLocator.evaluate((input, range) => {
      input.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
      input.focus({ preventScroll: true }); input.setSelectionRange(range.start, range.end);
    }, { start, end });
    const sample = () => inputLocator.evaluate(input => {
      const rect = input.getBoundingClientRect(), scroller = document.scrollingElement;
      return { scrollY, maximum: Math.max(0, scroller.scrollHeight - scroller.clientHeight), top: rect.top, bottom: rect.bottom,
        left: rect.left, right: rect.right, width: document.documentElement.clientWidth, height: document.documentElement.clientHeight,
        focused: document.activeElement === input, start: input.selectionStart, end: input.selectionEnd };
    });
    await frames(); const first = await sample(); await wait(100); await frames(); const second = await sample();
    observe(label + '_capture_prebaseline_scroll_samples', { method: 'public_input_scrollIntoView_instant_before_held_response_release', first, second });
    check(label + '_capture_prebaseline_visible_and_stable_' + receipt.checks.length, heldRequests.size === 1
      && Math.abs(first.scrollY - second.scrollY) <= 1 && Math.abs(first.maximum - second.maximum) <= 1
      && first.width === second.width && first.height === second.height
      && second.top >= 0 && second.bottom <= second.height && second.left >= 0 && second.right <= second.width
      && second.focused && second.start === start && second.end === end);
    return second;
  };
  const captureQueryBeforeRelease = async () => {
    const second = await prepareInputBeforeRelease(page.locator('.size-field input'), 2, 7, 'query');
    const baseline = await captureQuery();
    check('query_capture_baseline_matches_settled_sample_' + receipt.checks.length, heldRequests.size === 1 && Math.abs(baseline.scrollY - second.scrollY) <= 1);
    return baseline;
  };
  const retained = async (label, focus = true) => { const value = await page.evaluate(needFocus => { const old = window.__r128Retained; return { same_nodes: old.selectors.every((selector, index) => document.querySelector(selector) === old.nodes[index]),
    same_values: old.nodes.every((node, index) => node.value === old.values[index]), same_focus: !needFocus || document.activeElement === old.active,
    same_selection: old.active.selectionStart === old.start && old.active.selectionEnd === old.end, scrollY, original_scroll_y: old.scrollY }; }, focus);
    observe(label, value); check(label + '_dom_values_selection_focus', value.same_nodes && value.same_values && value.same_focus && value.same_selection); };
  const geometry = () => page.evaluate(() => { const rect = node => { if (!node || !node.getClientRects().length) return null; const r = node.getBoundingClientRect(); if (!r.width || !r.height) return null; return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height }; };
    const stack = document.querySelector('.toast-stack'), layout = document.querySelector('.toast-layout'), style = getComputedStyle(layout);
    return { width: document.documentElement.clientWidth, H: document.documentElement.clientHeight, scroll_width: document.documentElement.scrollWidth,
      nav: rect(document.querySelector('.mobile-nav')), stack: stack.childElementCount ? rect(stack) : null, tray: rect(document.querySelector('.comparison-tray')),
      T: stack.childElementCount ? stack.getBoundingClientRect().height : 0, b: parseFloat(style.getPropertyValue('--toast-base-bottom')), O: parseFloat(style.getPropertyValue('--toast-content-offset')),
      budget: parseFloat(style.getPropertyValue('--toast-stack-max-height')), padding: parseFloat(getComputedStyle(document.querySelector('.app-shell')).paddingBottom),
      close: [...document.querySelectorAll('.toast-close')].map(node => { const r = rect(node), hit = r && document.elementFromPoint((r.left + r.right) / 2, (r.top + r.bottom) / 2); return { ...r, center_hit: !!hit && node.contains(hit) }; }) }; });
  const assertGeometry = async label => { await frames();
    const animations = await page.locator('.toast').evaluateAll(async nodes => { const running = nodes.flatMap(node => node.getAnimations());
      await Promise.all(running.map(animation => animation.finished)); return { count: running.length, final_states: running.map(animation => animation.playState) }; });
    observe(label + '_default_toast_animation_finished', animations);
    check(label + '_default_animation_naturally_finished', animations.final_states.every(state => state === 'finished'));
    await frames(); const value = await geometry(); observe(label, value); const near = (a, b) => Math.abs(a - b) <= 1.1;
    check(label + '_no_horizontal_overflow_and_shared_padding', value.scroll_width <= value.width + 1 && near(value.padding, value.O));
    check(label + '_comparison_on_screen_above_toast', !!value.tray && value.tray.top >= 0 && value.tray.bottom <= value.H && near(value.H - value.tray.bottom, value.b + (value.T ? value.T + 8 : 0)));
    if (value.T) check(label + '_toast_budget_gap_and_44_targets', near(value.H - value.stack.bottom, value.b) && value.T <= value.budget + 1.1 && value.close.length > 0 && value.close.every(item => item.width >= 44 && item.height >= 44)
      && (!value.nav || near(value.nav.top - value.stack.bottom, 8)) && near(value.stack.top - value.tray.bottom, 8));
    return value; };
  const clearToasts = async label => { await uiOnly(label, async () => { while (await page.locator('.toast-close').count()) await page.locator('.toast-close').last().click(); }); };
  const pendingWatch = async id => { const gate = await makeGate('POST'); phase = 'action:watch'; await card(id).locator('.bookmark-button').click(); await gate.entered();
    check('watch_one_real_post_201_' + receipt.checks.length, gate.count() === 1 && gate.status() === 201 && gate.payload()?.variant_id === id); return gate; };
  const finishWatch = async gate => { gate.release(); await gate.settle(); await gate.remove(); await idle(); await page.locator('.toast-success').last().waitFor(); };
  for (const [index, [width, height]] of [[1365, 900], [390, 844], [320, 844], [320, 420]].entries()) {
    const label = `workbench-${width}-${height}`; scenario(label); await clearToasts(label + '_clear_before'); await page.setViewportSize({ width, height }); await frames();
    const gate = await pendingWatch(a[index + 2]);
    await page.locator('.size-field input').fill('225/45 R18 draft'); observe(label + '_query_before', await captureQueryBeforeRelease());
    await finishWatch(gate); await retained(label + '_appearance');
    check(label + '_no_appearance_scroll', await page.evaluate(() => Math.abs(scrollY - window.__r128Retained.scrollY) <= 1));
    check(label + '_query_and_comparison_preserved', equal(await choiceState(), choices));
    await assertGeometry(label + '_layers');
    // Actual hover/focus events pause the one production toast while other
    // real product controls are exercised; no timer patch is installed.
    if (index === 0) {
      await uiOnly('production_hover_pause', async () => { await page.locator('.toast').last().hover(); await wait(4800); check('production_hover_survives_original_lifetime', await page.locator('.toast-success').count() === 1); });
      await retained('query_input_while_hover_paused'); await page.mouse.move(0, 0);
    }
    await uiOnly(label + '_focus_pause_and_viewport_reflow', async () => {
      await page.locator('.toast-close').last().evaluate(node => node.focus({ preventScroll: true }));
      if (index === 0) { await wait(4800); check('production_focus_survives_original_lifetime', await page.locator('.toast-success').count() === 1); }
      await page.setViewportSize({ width: width === 1365 ? 1200 : width + 1, height }); await frames(); await page.setViewportSize({ width, height }); await frames();
      await retained(label + '_reflow', false); check(label + '_close_focus_remains', await page.locator('.toast-close').last().evaluate(node => document.activeElement === node));
    });
    await assertGeometry(label + '_paused_layers'); await shot(label + '-layers');
    // Source B is the final result group. Its final real compare operation is
    // a body-tail control; use observed rectangles for a reachable document
    // scroll and verify its whole 44px target before native Enter activation.
    const tail = page.locator('.results-list .source-result').last().locator('.variant-card').last().locator('.variant-actions button[aria-pressed]').last();
    await uiOnly(label + '_real_body_tail_operation', async () => {
      await tail.evaluate(node => { node.scrollIntoView({ block: 'end', behavior: 'instant' }); }); await frames();
      const requested = await tail.evaluate(node => { const scroller = document.scrollingElement; const layers = [...document.querySelectorAll('.mobile-nav,.toast-stack,.comparison-tray')].filter(item => item.getClientRects().length && item.getBoundingClientRect().height > 0);
        const upper = Math.min(document.documentElement.clientHeight, ...layers.map(item => item.getBoundingClientRect().top)); const before = scroller.scrollTop;
        const target = before + Math.max(0, node.getBoundingClientRect().bottom - upper + 8); window.scrollTo({ top: target, behavior: 'instant' });
        return { before, requested: target, maximum: Math.max(0, scroller.scrollHeight - scroller.clientHeight) }; });
      await frames(); const firstScroll = await page.evaluate(() => ({ actual: document.scrollingElement.scrollTop, maximum: Math.max(0, document.scrollingElement.scrollHeight - document.scrollingElement.clientHeight) }));
      await wait(100); await frames(); const secondScroll = await page.evaluate(() => ({ actual: document.scrollingElement.scrollTop, maximum: Math.max(0, document.scrollingElement.scrollHeight - document.scrollingElement.clientHeight) }));
      check(label + '_body_tail_instant_scroll_reachable_and_settled', requested.requested >= 0 && requested.requested <= secondScroll.maximum + 1.1
        && Math.abs(secondScroll.actual - requested.requested) <= 1.1 && Math.abs(firstScroll.actual - secondScroll.actual) <= 1.1 && Math.abs(firstScroll.maximum - secondScroll.maximum) <= 1.1);
      const target = await tail.evaluate(node => { const r = node.getBoundingClientRect(), hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        const upper = Math.min(document.documentElement.clientHeight, ...[...document.querySelectorAll('.mobile-nav,.toast-stack,.comparison-tray')].filter(item => item.getClientRects().length && item.getBoundingClientRect().height > 0).map(item => item.getBoundingClientRect().top));
        return { top: r.top, bottom: r.bottom, width: r.width, height: r.height, upper, hit: !!hit && node.contains(hit), scroll_top: document.scrollingElement.scrollTop, maximum: Math.max(0, document.scrollingElement.scrollHeight - document.scrollingElement.clientHeight) }; });
      observe(label + '_body_tail_rect_hit_scroll', { requested, first_scroll: firstScroll, second_scroll: secondScroll, method: 'window_scrollTo_instant_default_css_and_toast_animation_preserved', target });
      check(label + '_body_tail_full_44_target_reachable', target.width >= 44 && target.height >= 44 && target.top >= 0 && target.bottom <= target.upper - 7 && target.hit && requested.requested <= target.maximum + 1.1 && Math.abs(target.scroll_top - requested.requested) <= 1.1);
      await shot(label + '-body-tail'); await tail.evaluate(node => node.focus({ preventScroll: true })); await page.keyboard.press('Enter');
      check(label + '_native_enter_compared_tail', await tail.getAttribute('aria-pressed') === 'true'); await page.keyboard.press('Enter'); check(label + '_tail_compare_reverted', await tail.getAttribute('aria-pressed') === 'false');
    });
    await retained(label + '_tail_did_not_remount_inputs', false); check(label + '_choices_after_tail', equal(await choiceState(), choices));
    await uiOnly(label + '_explicit_keyboard_close', async () => { await captureQuery(); await page.locator('.toast-close').last().evaluate(node => node.focus({ preventScroll: true })); await page.keyboard.press('Enter');
      check(label + '_manual_close_removed_target', await page.locator('.toast').count() === 0); await retained(label + '_close_returned_query_focus'); });
    await assertGeometry(label + '_empty_toast_releases_height');
  }
  scenario('one_browser_route_watch503_error_toast_and_restored_real_201_path');
  await page.setViewportSize({ width: 1365, height: 900 }); await frames(); await idle();
  const beforeFaultWatches = (await json(await context.request.get(api('/v1/watchlists')))).items.map(item => ({ id: item.id, variant_id: item.variant_id })).sort((left, right) => left.id.localeCompare(right.id));
  check('synthetic_fault_starts_with_four_existing_real_watches', beforeFaultWatches.length === 4 && equal(beforeFaultWatches.map(item => item.variant_id).sort(), a.slice(2, 6).sort()));
  const watchFault = { method: 'POST', url: api('/v1/watchlists'), status: 503, phase: 'action:synthetic_watch_503',
    origin: 'synthetic_browser_route_injection_without_backend_dispatch', active: true, route_removed: false, claimed: false, requests: 0,
    injected_responses: 0, observed_responses: 0, console_errors: 0, maximum_console_errors: 1, completed: false, request_id: null,
    console_association: 'exact_resource_url_and_active_single_post_phase_maximum_one_not_request_object' };
  receipt.synthetic_http_faults.push(watchFault); expectedHttpFaults.set(watchFault.url, watchFault);
  let enterFault, releaseFault, finishFault;
  const faultEntered = new Promise(done => { enterFault = done; }), faultReleased = new Promise(done => { releaseFault = done; }), faultCompleted = new Promise(done => { finishFault = done; });
  const faultHandler = async route => {
    const request = route.request();
    if (request.url() !== watchFault.url || request.method() !== watchFault.method) { await route.fallback(); return; }
    watchFault.requests++;
    if (!watchFault.active || phase !== watchFault.phase || watchFault.claimed) { receipt.gate_failures.push({ method: 'POST', type: 'synthetic_fault_duplicate_or_wrong_phase' }); await route.abort('failed'); enterFault(); finishFault(); return; }
    if (!requestIds.has(request)) requestIds.set(request, ++requestSequence);
    watchFault.claimed = true; watchFault.request_id = requestIds.get(request); expectedFaultRequests.set(request, watchFault); heldRequests.add(request); enterFault();
    try { await faultReleased; watchFault.injected_responses++;
      // Deliberately no route.fetch(): this one response is browser-injected,
      // so existing backend watch records and five real201 calls stay exact.
      await route.fulfill({ status: 503, contentType: 'application/json', headers: { 'cache-control': 'no-store' },
        body: JSON.stringify({ detail: 'R128 intentional synthetic watch503 for error toast acceptance' }) });
    } catch (error) { receipt.gate_failures.push({ method: 'POST', type: error?.name || 'Error' }); try { await route.abort('failed'); } catch {} }
    finally { heldRequests.delete(request); watchFault.completed = true; enterFault(); finishFault(); }
  };
  const boundedFault = async promise => { let timer; try { await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(Error('synthetic_watch_fault_timeout')), 10000); })]); } finally { clearTimeout(timer); } };
  const syntheticGate = { release: releaseFault, settle: () => boundedFault(faultCompleted), remove: async () => {
    await context.unroute(watchFault.url, faultHandler); watchFault.route_removed = true; watchFault.active = false; expectedHttpFaults.delete(watchFault.url); gates.delete(syntheticGate);
  } };
  await context.route(watchFault.url, faultHandler); gates.add(syntheticGate); phase = watchFault.phase;
  await card(a[6]).locator('.bookmark-button').click(); await boundedFault(faultEntered); observe('synthetic_watch503_query_before', await captureQueryBeforeRelease());
  syntheticGate.release(); await syntheticGate.settle(); await idle();
  const errorToast = page.locator('.toast-error').filter({ hasText: 'R128 intentional synthetic watch503 for error toast acceptance' });
  await errorToast.waitFor(); await retained('synthetic_watch503_error_preserves_query_input');
  check('synthetic_watch503_one_injection_response_and_bounded_console', watchFault.requests === 1 && watchFault.injected_responses === 1 && watchFault.observed_responses === 1 && watchFault.console_errors <= 1
    && await errorToast.getAttribute('role') === 'alert' && await card(a[6]).locator('.bookmark-button').getAttribute('aria-pressed') === 'false');
  const afterFaultWatches = (await json(await context.request.get(api('/v1/watchlists')))).items.map(item => ({ id: item.id, variant_id: item.variant_id })).sort((left, right) => left.id.localeCompare(right.id));
  check('synthetic_watch503_preserves_all_existing_backend_watches_and_choices', equal(beforeFaultWatches, afterFaultWatches) && equal(await choiceState(), choices));
  await shot('workbench-single-synthetic-watch503-error'); await syntheticGate.remove();
  await uiOnly('synthetic_watch503_close_only', async () => { await errorToast.locator('.toast-close').evaluate(node => node.click()); await frames();
    check('synthetic_watch503_error_toast_closed', await page.locator('.toast-error').count() === 0); await retained('synthetic_watch503_close_preserves_query_input'); });
  check('synthetic_watch503_route_and_exception_removed_before_real_recovery', !watchFault.active && watchFault.route_removed && expectedHttpFaults.size === 0);
  scenario('unsubmitted_real_price_form_preserved_during_pending_watch_completion');
  await page.setViewportSize({ width: 1365, height: 900 }); await frames(); const priceGate = await pendingWatch(a[6]); await navigate('sources');
  check('same_target_real201_recovered_after_synthetic_watch503_route_removed', priceGate.count() === 1 && priceGate.status() === 201 && priceGate.payload()?.variant_id === a[6] && !watchFault.active && watchFault.route_removed);
  stage = 'sources_price_form_ready_while_real_watch_held';
  const price = page.locator('.ai-price-admin'), vendor = price.getByLabel('人工厂商 / 计费方', { exact: true }), rate = price.getByLabel('输入费率（每百万 tokens）', { exact: true });
  await price.waitFor();
  await vendor.fill('R128 unsubmitted synthetic draft'); await price.getByLabel('精确模型标识（区分大小写）', { exact: true }).fill('r128-draft-model'); await rate.fill('123.45000000');
  await price.getByLabel('人工来源说明（必填，未在线核验）', { exact: true }).fill('R128 synthetic draft only; never submitted.');
  const pricePrepared = await prepareInputBeforeRelease(rate, 1, 5, 'price');
  const priceBaseline = await page.evaluate(() => { const nodes = [...document.querySelectorAll('.ai-price-admin input,.ai-price-admin select,.ai-price-admin textarea')], active = document.activeElement;
    window.__r128Price = { nodes, values: nodes.map(node => node.value), active, start: active.selectionStart, end: active.selectionEnd, scrollY }; return { scrollY }; });
  check('price_capture_baseline_matches_settled_sample', heldRequests.size === 1 && Math.abs(priceBaseline.scrollY - pricePrepared.scrollY) <= 1);
  const priceRetained = async label => { const value = await page.evaluate(() => { const old = window.__r128Price, nodes = [...document.querySelectorAll('.ai-price-admin input,.ai-price-admin select,.ai-price-admin textarea')]; return { same_nodes: nodes.length === old.nodes.length && nodes.every((node, index) => node === old.nodes[index]), same_values: nodes.every((node, index) => node.value === old.values[index]), same_focus: document.activeElement === old.active, same_selection: old.active.selectionStart === old.start && old.active.selectionEnd === old.end, scroll_stable: Math.abs(scrollY - old.scrollY) <= 1 }; });
    observe(label, value); check(label, Object.values(value).every(Boolean)); };
  await finishWatch(priceGate); await priceRetained('price_draft_appearance_preserved');
  await uiOnly('price_draft_toast_resize_and_close', async () => { await page.setViewportSize({ width: 390, height: 844 }); await frames();
    // A real viewport resize may change document scroll clamping. Establish its
    // settled scroll before testing toast removal, without changing field data.
    await page.evaluate(() => { window.__r128Price.scrollY = scrollY; }); await priceRetained('price_draft_resize_preserved');
    await page.locator('.toast-close').last().evaluate(node => node.click()); await frames(); await priceRetained('price_draft_programmatic_close_preserves_new_external_focus'); });
  check('no_price_or_planning_or_other_unplanned_post', !receipt.http_events.some(row => row.event === 'request' && row.method === 'POST' && !isInitializationPreview(row)
    && row.path !== '/api/v1/watchlists' && !/^\/api\/v1\/sources\/r122-selection-[ab]\/live-query$/.test(row.path)));
  await navigate('query'); await page.setViewportSize({ width: 1365, height: 900 }); await frames(); await idle(); check('choices_survive_intentional_view_navigation', equal(await choiceState(), choices));
  scenario('real_unwatch_confirmation_and_success_toast');
  const watched = card(a[2]); phase = 'action:unwatch_confirm_open'; await watched.locator('.bookmark-button').click();
  const confirmation = watched.getByRole('group', { name: '取消关注此规格？', exact: true }); await confirmation.waitFor();
  const deletesBefore = receipt.http_events.filter(row => row.event === 'request' && row.method === 'DELETE').length;
  await uiOnly('unwatch_cancel_never_deletes', async () => { await confirmation.getByRole('button', { name: '取消', exact: true }).click(); });
  check('cancel_confirmation_no_delete', receipt.http_events.filter(row => row.event === 'request' && row.method === 'DELETE').length === deletesBefore);
  await watched.locator('.bookmark-button').click(); const deleteGate = await makeGate('DELETE'); phase = 'action:unwatch'; await confirmation.getByRole('button', { name: '确认取消关注', exact: true }).click(); await deleteGate.entered();
  check('unwatch_one_real_delete_204', deleteGate.count() === 1 && deleteGate.status() === 204); await captureQueryBeforeRelease(); deleteGate.release(); await deleteGate.settle(); await deleteGate.remove(); await idle();
  await page.locator('.toast-success').filter({ hasText: '已取消关注。' }).waitFor(); await retained('unwatch_success_retained_input');
  check('unwatch_bookmark_false_and_single_delete', await watched.locator('.bookmark-button').getAttribute('aria-pressed') === 'false' && receipt.http_events.filter(row => row.event === 'request' && row.method === 'DELETE').length === deletesBefore + 1);
  await clearToasts('close_unwatch_toast');
  scenario('frozen_menu_targeted_regression');
  const trigger = watched.locator('[data-variant-menu-trigger]'), menu = page.getByRole('menu');
  for (const mode of ['button', 'right', 'Shift+F10']) await uiOnly('menu_' + mode, async () => {
    const target = mode === 'right' ? watched.locator('.variant-size strong') : trigger;
    await target.scrollIntoViewIfNeeded(); await frames(); await wait(150); await frames();
    if (mode === 'button') await target.click(); else if (mode === 'right') await target.click({ button: 'right' }); else { await target.evaluate(node => node.focus({ preventScroll: true })); await page.keyboard.press('Shift+F10'); }
    await menu.waitFor(); await frames();
    check('menu_seven_frozen_actions_' + mode, equal(await menu.locator('[data-variant-menu-action]').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-variant-menu-action'))), ['evidence', 'compare', 'watch', 'review', 'lifecycle', 'ai', 'garage']));
    check('menu_first_focus_and_trigger_aria_' + mode, await menu.locator('[data-variant-menu-action="evidence"]').evaluate(node => document.activeElement === node) && await trigger.getAttribute('aria-expanded') === 'true' && await trigger.getAttribute('aria-controls') === await menu.getAttribute('id'));
    await page.keyboard.press('Escape'); await menu.waitFor({ state: 'detached' }); check('menu_escape_return_' + mode, await trigger.evaluate(node => document.activeElement === node));
  });
  check('menu_regression_keeps_choices', equal(await choiceState(), choices)); await shot('workbench-menu-regression-desktop');
  const finalFixture = await json(await context.request.get(api('/fixture/state'))); receipt.final_fixture = { counters: finalFixture.counters, source_calls: finalFixture.source_calls, real_source_calls: finalFixture.real_source_calls, provider_calls: finalFixture.provider_calls, model_requests: finalFixture.model_requests, embedding_requests: finalFixture.embedding_requests };
  const counts = { watch_posts: receipt.http_events.filter(row => row.event === 'request' && row.method === 'POST' && row.path === '/api/v1/watchlists').length,
    real_watch_201: receipt.http_events.filter(row => row.event === 'response' && row.method === 'POST' && row.path === '/api/v1/watchlists' && row.status === 201).length,
    synthetic_watch_503: receipt.http_events.filter(row => row.event === 'response' && row.method === 'POST' && row.path === '/api/v1/watchlists' && row.status === 503 && row.expected_status === true).length,
    watch_deletes: receipt.http_events.filter(row => row.event === 'request' && row.method === 'DELETE' && row.path.startsWith('/api/v1/watchlists/')).length,
    query_posts: receipt.http_events.filter(row => row.event === 'request' && row.method === 'POST' && /\/live-query$/.test(row.path)).length };
  observe('whole_suite_business_counts', counts); check('exact_five_real_watch201_one_synthetic503_one_delete_two_queries', counts.watch_posts === 6 && counts.real_watch_201 === 5 && counts.synthetic_watch_503 === 1 && counts.watch_deletes === 1 && counts.query_posts === 2);
  check('fixture_zero_external_child_normal_db_provider_model_embedding', Object.values(finalFixture.counters).every(value => value === 0) && finalFixture.source_calls === 2 && finalFixture.real_source_calls === 0 && finalFixture.provider_calls === 0 && finalFixture.model_requests === 0 && finalFixture.embedding_requests === 0);
  check('single_exact_synthetic_watch503_finished_and_exception_removed', faultBoundsPassed());
  check('strict_http_status_gate_no_unexpected_400_or_higher', !receipt.unexpected_http_statuses.length && !receipt.http_events.some(row => row.event === 'response' && row.status >= 400 && row.expected_status !== true));
  check('strict_network_gate_zero_failures_errors_external', receipt.http_events.every(row => row.event !== 'failed') && !receipt.page_errors.length && !receipt.console_errors.length && !receipt.unexpected_origins.length && !receipt.gate_failures.length);
  receipt.production_workbench_verified = true; receipt.state = 'passed';
} catch (error) {
  receipt.state = 'failed'; receipt.failure = { stage, type: ['Error', 'TimeoutError', 'TypeError', 'SyntaxError'].includes(error?.name) ? error.name : 'Error',
    check: /^[a-zA-Z0-9_:-]+$/.test(error?.message || '') ? error.message : null };
  if (page) try { await page.screenshot({ path: resolve(output, 'failure.png') }); receipt.screenshots.push('failure.png'); } catch {}
} finally {
  password = null;
  for (const gate of gates) gate.release();
  for (const gate of [...gates]) { try { await gate.settle(); await gate.remove(); } catch { receipt.cleanup_failures.push('pending_gate_cleanup_failed'); } }
  try { if (context) { const response = await context.request.post(fixtureOrigin + '/fixture/shutdown', { timeout: 5000 }); receipt.fixture_shutdown_requested = response.ok(); } } catch { receipt.cleanup_failures.push('fixture_shutdown_request_failed'); }
  let closeTimer;
  try { await Promise.race([(async () => { if (context) await context.close(); if (browser) await browser.close(); if (browserServer) await browserServer.close(); })(),
      new Promise((_, reject) => { closeTimer = setTimeout(() => reject(Error('browser_close_timeout')), 20000); })]);
    receipt.browser_close_returned = !!browserProcess && browserProcess.exitCode === 0 && browserProcess.signalCode === null && receipt.browser.server_close_observed === true;
  } catch { receipt.cleanup_failures.push('browser_close_failed'); if (browserServer) { receipt.browser.forced_kill_requested = true; try { await browserServer.kill(); } catch { receipt.cleanup_failures.push('browser_kill_failed'); } } }
  finally { clearTimeout(closeTimer); }
  if (receipt.unexpected_http_statuses.length || receipt.http_events.some(row => row.event === 'response' && row.status >= 400 && row.expected_status !== true)) receipt.cleanup_failures.push('terminal_unexpected_http_status_400_or_higher');
  const faultPassed = faultBoundsPassed(), faultRecorded = receipt.synthetic_http_faults.length > 0;
  receipt.synthetic_http_fault_coverage = { required: true, state: faultPassed ? 'passed' : faultRecorded ? 'failed' : 'not_executed',
    recorded_faults: receipt.synthetic_http_faults.length, route_cleanup_complete: expectedHttpFaults.size === 0 && receipt.synthetic_http_faults.every(fault => !fault.active && fault.route_removed) };
  if (!faultPassed) receipt.coverage_failures.push(faultRecorded ? 'synthetic_watch503_contract_not_satisfied' : 'synthetic_watch503_not_executed');
  if (!receipt.synthetic_http_fault_coverage.route_cleanup_complete) receipt.cleanup_failures.push('terminal_synthetic_watch503_route_cleanup_failed');
  if (receipt.page_errors.length || receipt.console_errors.length || receipt.unexpected_origins.length || receipt.gate_failures.length || receipt.http_events.some(row => row.event === 'failed')) receipt.cleanup_failures.push('terminal_browser_or_network_error');
  try { receipt.inputs_unchanged = equal(snapshot(Object.keys(inputPins)), inputPins); } catch { receipt.inputs_unchanged = false; }
  if (!receipt.inputs_unchanged) receipt.cleanup_failures.push('input_drift');
  try { receipt.prepared_runtimes_unchanged = equal(tree(playwrightRoot), runtimePins.playwright) && equal(tree(browserRoot), runtimePins.browser) && equal(tree(privatePlaywright), runtimePins.playwright)
      && equal(tree(privateBrowser, undefined, receipt.browser_generated_sidecars, runtimePins.browser), runtimePins.browser); } catch { receipt.prepared_runtimes_unchanged = false; }
  if (!receipt.prepared_runtimes_unchanged) receipt.cleanup_failures.push('runtime_drift_or_copy_incomplete');
  if (!receipt.browser_close_returned || !receipt.fixture_shutdown_requested || receipt.browser.forced_kill_requested || receipt.coverage_failures.length || receipt.cleanup_failures.length) receipt.state = 'failed';
  receipt.artifact_hashes = snapshot(receipt.screenshots.map(name => resolve(output, name))); receipt.finished_utc = new Date().toISOString(); save();
  writeFileSync(resolve(output, 'browsercleanup.json'), JSON.stringify({ state: receipt.state, browser: receipt.browser, browser_close_returned: receipt.browser_close_returned,
    fixture_shutdown_requested: receipt.fixture_shutdown_requested, coverage_failures: receipt.coverage_failures, synthetic_http_fault_coverage: receipt.synthetic_http_fault_coverage,
    cleanup_failures: receipt.cleanup_failures, inputs_unchanged: receipt.inputs_unchanged,
    prepared_runtimes_unchanged: receipt.prepared_runtimes_unchanged, browser_generated_sidecars: receipt.browser_generated_sidecars, browser_generated_sidecar_policy: sidecarPolicy }, null, 2) + '\n');
}
console.log(JSON.stringify({ state: receipt.state, output, checks: receipt.checks.length, failure: receipt.failure || null }));
if (receipt.state !== 'passed') process.exitCode = 3;
