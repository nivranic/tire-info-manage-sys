/** R129: current production Workbench query summary and bounded synthetic state coverage.
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
if (origin !== 'http://127.0.0.1:18987' || dirname(output) !== artifacts || !/^r129browser-[a-f0-9]{16}$/.test(basename(output))
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
  resolve(root, '.artifacts/r127-variant-context-menu-20261022/run-ui-host.py'), resolve(root, '.artifacts/r129-query-summary-20261023/run-ui-host.py'),
  resolve(root, '.artifacts/r118-material-workbench-20261021/serve-web-v1.py'), resolve(root, 'docs/plans/2026-10-23-query-summary-state.md'),
  resolve(root, '.artifacts/r129-query-summary-20261023/product-review.json'),
  resolve(root, '.artifacts/r129-query-summary-20261023/scope-amendment-1.json'),
  resolve(root, '.artifacts/r129-query-summary-20261023/readable-review.json')]) };
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
const receipt = { schema: 'r129-query-summary-production-workbench@1', state: 'running', started_utc: new Date().toISOString(), origin, fixture_origin: fixtureOrigin,
  build, build_report_sha256: reportSha, input_pins: inputPins, runtime_pins: runtimePins, checks: [], scenarios: [], observations: [], screenshots: [], http_events: [], ui_request_windows: [],
  query_windows: [], consent_windows: [], request_gates: [], synthetic_http_faults: [], unexpected_origins: [], unexpected_http_statuses: [], page_errors: [], console_errors: [],
  gate_failures: [], coverage_failures: [], cleanup_failures: [], browser_generated_sidecars: [], browser_generated_sidecar_policy: sidecarPolicy,
  browser: { playwright: '1.63.0', chromium_revision: '1243', headless: true }, browser_close_returned: false, fixture_shutdown_requested: false,
  inputs_unchanged: false, prepared_runtimes_unchanged: false, synthetic_only: true, production_workbench_verified: false,
  product_review_basis: { baseline: 'product-review.json_is_historical_pre_readability_review', differential: 'readable-review.json_covers_current_summary_class_and_css' },
  explicit_limitations: ['project_owned_synthetic_sources_accounts_only_not_real_external_sources', 'service_workers_blocked_matching_build_public_served_by_page_route',
    'query_dto_and_consent_faults_are_exact_browser_route_injections_without_backend_dispatch', 'synthetic_consent_201_is_real_ui_sdk_flow_not_backend_authorization_acceptance',
    'real_live_responses_use_unchanged_private_fixture_with_26_and_3_project_authored_rows', 'http_503_is_not_a_transport_failure_requestfailed_must_remain_empty',
    'summary_typography_and_computed_solid_color_contrast_default_light_only_not_all_themes_or_complete_wcag',
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
const gatesPassed = () => receipt.request_gates.length === 20 && gates.size === 0 && activeRecords.size === 0 && receipt.request_gates.every(record =>
  record.claimed && record.requests === 1 && record.observed_responses === 1 && record.finished_events === 1 && record.completed && record.released
  && record.route_removed && !record.active && record.body_matched && Number.isInteger(record.request_id) && record.request_id > 0
  && (record.origin === 'real_private_fixture_http' ? record.real_fetches === 1 && record.injected_responses === 0 && record.status === 200
    : record.real_fetches === 0 && record.injected_responses === 1)
  && record.console_errors >= 0 && record.console_errors <= (record.status === 503 ? 1 : 0));
const faultsPassed = () => receipt.synthetic_http_faults.length === 4 && receipt.synthetic_http_faults.every(record =>
  record.status === 503 && record.origin === 'synthetic_browser_route_injection_without_backend_dispatch' && record.observed_responses === 1
  && record.requests === 1 && record.injected_responses === 1 && record.console_errors <= 1 && record.completed && record.route_removed && !record.active);
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
  const shot = async label => { await page.locator('.results-heading').scrollIntoViewIfNeeded(); const name = label + '.png';
    await page.screenshot({ path: resolve(output, name) }); receipt.screenshots.push(name); save(); };
  const scenario = label => { stage = label; phase = 'scenario:' + label; receipt.scenarios.push(label); save(); };
  const uiOnly = async (label, operation) => { await idle(); const start = receipt.http_events.length, before = requestCounts(); phase = 'ui:' + label;
    await operation(); await frames(); await wait(250); await idle();
    const requests = receipt.http_events.slice(start).filter(row => row.event === 'request' && row.business);
    receipt.ui_request_windows.push({ label, start_sequence: start + 1, end_sequence: receipt.http_events.length, before, after: requestCounts(), business_requests: requests });
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
  const summary = page.locator('.results-heading [role="status"]');
  const assertSummary = async (label, { state, busy, exact, includes = [], excludes = [] }) => {
    await page.waitForFunction(expected => { const node = document.querySelector('.results-heading [role="status"]'); const text = node?.textContent || '';
      return !!node && node.getAttribute('data-query-state') === expected.state && node.getAttribute('aria-busy') === String(expected.busy)
        && (!expected.exact || text === expected.exact) && expected.includes.every(value => text.includes(value)) && expected.excludes.every(value => !text.includes(value));
    }, { state, busy, exact, includes, excludes });
    const actual = await summary.evaluate(node => ({ text: node.textContent, role: node.getAttribute('role'), atomic: node.getAttribute('aria-atomic'), busy: node.getAttribute('aria-busy'), state: node.getAttribute('data-query-state'), focused: node === document.activeElement }));
    observe(label, actual); check(label + '_state_busy_atomic_no_focus', actual.state === state && actual.busy === String(busy) && actual.atomic === 'true' && !actual.focused);
  };
  const assertSummaryTypography = async label => {
    const value = await summary.evaluate(node => {
      const style = getComputedStyle(node), chain = [];
      for (let current = node; current; current = current.parentElement) { const css = getComputedStyle(current);
        chain.push({ tag: current.tagName, background: css.backgroundColor, background_image: css.backgroundImage, opacity: css.opacity,
          filter: css.filter, blend: css.mixBlendMode, visibility: css.visibility, display: css.display }); }
      return { width: innerWidth, palette: document.documentElement.dataset.theme, prefers_dark: matchMedia('(prefers-color-scheme: dark)').matches,
        forced_colors: matchMedia('(forced-colors: active)').matches, text: node.textContent, font_size: style.fontSize, font_px: parseFloat(style.fontSize),
        line_height: style.lineHeight, line_px: parseFloat(style.lineHeight), foreground: style.color, text_fill: style.webkitTextFillColor,
        text_stroke_width: style.webkitTextStrokeWidth, background_chain: chain, connected: node.isConnected, rect_count: node.getClientRects().length };
    });
    // Reuse the existing theme QA sRGB luminance/contrast calculation. The
    // current summary uses solid paint: fail closed on alpha/image/filter/blend
    // cases rather than treating a nominal CSS token as the displayed color.
    const rgba = color => {
      if (!/^rgba?\([\d.,\s]+\)$/.test(color || '')) return null;
      const parts = (color.match(/[\d.]+/g) || []).map(Number);
      if (![3, 4].includes(parts.length) || parts.slice(0, 3).some(part => !Number.isFinite(part) || part < 0 || part > 255)) return null;
      const alpha = parts[3] ?? 1; return Number.isFinite(alpha) && alpha >= 0 && alpha <= 1 ? [...parts.slice(0, 3), alpha] : null;
    };
    const foreground = rgba(value.text_fill || value.foreground), backgroundLayers = value.background_chain.map(layer => ({ ...layer, rgba: rgba(layer.background) }));
    const paintedIndex = backgroundLayers.findIndex(layer => layer.rgba && layer.rgba[3] > 0), background = backgroundLayers[paintedIndex]?.rgba;
    const supportedPaint = foreground?.[3] === 1 && background?.[3] === 1 && paintedIndex >= 0
      && backgroundLayers.slice(0, paintedIndex + 1).every(layer => layer.rgba && layer.background_image === 'none')
      && value.background_chain.every(layer => Number(layer.opacity) === 1 && layer.filter === 'none' && layer.blend === 'normal' && layer.visibility === 'visible' && layer.display !== 'none')
      && parseFloat(value.text_stroke_width) === 0;
    const luminance = rgb => rgb.slice(0, 3).map(part => { const unit = part / 255; return unit <= .04045 ? unit / 12.92 : ((unit + .055) / 1.055) ** 2.4; })
      .reduce((total, part, index) => total + part * [.2126, .7152, .0722][index], 0);
    const light = supportedPaint ? [luminance(foreground), luminance(background)].sort((a, b) => b - a) : null;
    value.effective_background = backgroundLayers[paintedIndex]?.background ?? null; value.solid_paint_supported = supportedPaint;
    value.contrast_ratio = light ? (light[0] + .05) / (light[1] + .05) : null;
    observe(label, value);
    check(label + '_default_light_visible_current_text', value.palette === 'light' && !value.prefers_dark && !value.forced_colors
      && value.connected && value.rect_count > 0 && value.text.includes('26 MATCHED SKU / 2 SOURCES'));
    check(label + '_font_12px_line_height_1_5', Number.isFinite(value.font_px) && value.font_px >= 12 && Number.isFinite(value.line_px) && value.line_px >= value.font_px * 1.5);
    check(label + '_actual_solid_text_background_contrast_4_5', supportedPaint && value.contrast_ratio >= 4.5);
  };
  const fixture = await json(await context.request.get(api('/fixture/state')));
  check('private_fixture_starts_zero_real_model_usage_and_two_exact_sources', fixture.synthetic_only && !fixture.normal_database_used && fixture.real_source_calls === 0
    && fixture.provider_calls === 0 && fixture.model_requests === 0 && fixture.embedding_requests === 0 && fixture.source_calls === 0
    && equal(fixture.source_ids, ['r122-selection-a', 'r122-selection-b']) && equal(fixture.source_row_counts, [26, 3]));
  const admin = await json(await context.request.post(api('/v1/auth/register'), { data: { username: 'r129_admin_' + randomBytes(4).toString('hex'), password } })); password = null;
  check('admin_registered_real_private_http', admin.user?.is_admin === true);
  stage = 'production_document_initialization';
  check('production_document_http_200', (await page.goto(origin, { waitUntil: 'domcontentloaded' }))?.status() === 200);
  await page.locator('.sidebar-foot small').filter({ hasText: '管理员 · 本机工作台' }).waitFor(); await page.locator('.home-counts').waitFor(); await idle();
  const initializationEnd = receipt.http_events.length, initializationPosts = postRows(), preview = initializationPosts[0];
  check('initialization_exact_single_history_preview_200_finished', initializationPosts.length === 1 && preview.path === '/api/v1/personal-feed/preview'
    && preview.query === '?mode=history' && preview.phase === 'initialization'
    && receipt.http_events.some(row => row.request_id === preview.request_id && row.event === 'response' && row.status === 200)
    && receipt.http_events.some(row => row.request_id === preview.request_id && row.event === 'finished'));
  receipt.initialization_business_window = { end_sequence: initializationEnd, preview_request_id: preview.request_id,
    requests: receipt.http_events.slice(0, initializationEnd).filter(row => row.event === 'request' && row.business) };
  phase = 'navigation:query'; await page.locator('.main-nav').getByRole('button', { name: /轮胎查询/ }).click(); await idle();
  await page.locator('.model-field select').selectOption(fixture.model); await page.locator('.region-selector select').selectOption('US'); await page.locator('.size-field input').fill('265/40R20');
  await assertSummary('initial_idle', { state: 'idle', busy: false, exact: 'LIVE FIRST / EVIDENCE ALWAYS' });
  const expectedQuery = { query: { size: '265/40R20', model: fixture.model }, filters: [], fallback_policy: 'ask' };
  const groups = ['A', 'B'].map(letter => page.locator('.source-result').filter({ has: page.getByRole('heading', { name: 'R122 合成来源 ' + letter, exact: true }) }));
  const syntheticDto = (index, dataState, reason = null) => ({ query_id: randomUUID(), source_id: fixture.source_ids[index], data_state: dataState, reason,
    variants: [], provenance: [], conflicts: [], verified_at: dataState === 'live' ? new Date().toISOString() : null, snapshot_observed_at: null, snapshot_age_seconds: null, consent_id: null,
    selection: { filters: [], source_count: dataState === 'live' ? 0 : null, matched_count: dataState === 'live' ? 0 : null, excluded_count: dataState === 'live' ? 0 : null, undetermined_count: dataState === 'live' ? 0 : null } });
  const queryPair = async (label, specs, first = false) => {
    await idle(); scenario(label); const before = requestCounts();
    const pair = [];
    for (let index = 0; index < 2; index++) pair.push(await makeGate({ label: label + '_' + index,
      path: '/v1/sources/' + fixture.source_ids[index] + '/live-query', expectedBody: expectedQuery, ...specs[index] }));
    if (first) await page.locator('.query-submit').click(); else await page.getByRole('button', { name: '按本次条件重新在线查询', exact: true }).click();
    await Promise.all(pair.map(gate => gate.entered()));
    check(label + '_exact_two_queries_from_explicit_ui_submit', requestCounts().query_posts === before.query_posts + 2 && pair.every(gate => gate.record.body_matched));
    await assertSummary(label + '_both_held', { state: 'querying', busy: true, exact: '正在在线查询 / 2 SOURCES' });
    receipt.query_windows.push({ label, before, after_submit: requestCounts(), request_ids: pair.map(gate => gate.record.request_id) }); return pair;
  };
  const releaseGates = async values => { for (const gate of values) gate.release(); await Promise.all(values.map(gate => gate.settle())); await idle();
    for (const gate of values) { check(gate.record.label + '_one_response_and_finished', gate.record.requests === 1 && gate.record.observed_responses === 1 && gate.record.finished_events === 1); await gate.remove(); } };
  const completeLive = async (label, pair) => { const values = pair.map(gate => gate.payload());
    check(label + '_real_live_26_3', values.every((value, index) => value.source_id === fixture.source_ids[index] && value.data_state === 'live' && value.variants.length === [26, 3][index])
      && values[0].variants[0].id === values[1].variants[0].id && new Set(values.flatMap(value => value.variants.map(row => row.id))).size === 28);
    await assertSummary(label + '_complete', { state: 'complete', busy: false, exact: '29 MATCHED SKU / 2 SOURCES' });
    check(label + '_cards_match_existing_20_3_paging', await groups[0].locator('.variant-card').count() === 20 && await groups[1].locator('.variant-card').count() === 3); };
  const first = await queryPair('real_private_live_initial_loading', [{ real: true }, { real: true }], true);
  await shot('summary-real-loading-wide'); await releaseGates(first); await completeLive('initial', first);

  const errors = await queryPair('two_synthetic_http503', [0, 1].map(index => ({ status: 503, body: { detail: 'R129 synthetic query HTTP503 ' + index } })));
  await releaseGates(errors); await assertSummary('all_http_errors_terminal', { state: 'unavailable', busy: false, exact: '本次未获得可核验结果 / 2 SOURCES' });
  check('two_http_error_cards_keep_exact_cause', await groups[0].locator('.inline-error').innerText() === 'R129 synthetic query HTTP503 0' && await groups[1].locator('.inline-error').innerText() === 'R129 synthetic query HTTP503 1');
  await shot('summary-http-errors-wide');
  await uiOnly('failed_query_idle_no_retry_or_snapshot', async () => { await wait(300); });

  const unavailable = await queryPair('two_synthetic_source_unavailable', [0, 1].map(index => ({ body: syntheticDto(index, 'source_unavailable', 'upstream_timeout') })));
  await releaseGates(unavailable); await assertSummary('all_business_unavailable_terminal', { state: 'unavailable', busy: false, exact: '本次未获得可核验结果 / 2 SOURCES' });
  check('two_unavailable_cards_preserve_reason', (await groups[0].locator('.source-reason').innerText()).includes('来源响应超时') && (await groups[1].locator('.source-reason').innerText()).includes('来源响应超时'));

  const consentDtos = [0, 1].map(index => syntheticDto(index, 'consent_required', 'upstream_timeout'));
  const consentPair = await queryPair('two_synthetic_consent_required', consentDtos.map(body => ({ body })));
  await releaseGates(consentPair); await assertSummary('awaiting_explicit_fallback_authorization', { state: 'consent_required', busy: false, exact: '在线查询未完成，等待回退授权 / 2 SOURCES' });
  check('authorization_controls_preserved_for_both_sources', await page.getByRole('button', { name: '仅本次允许', exact: true }).count() === 2
    && await page.getByRole('button', { name: '拒绝，保持无结果', exact: true }).count() === 2);
  const submittedConsentText = await groups[0].locator('.consent-card').innerText();
  await uiOnly('unsubmitted_draft_changes_no_query_or_snapshot', async () => {
    await page.locator('.size-field input').fill('245/40R20'); await frames();
    check('draft_does_not_change_submitted_consent_scope', await groups[0].locator('.consent-card').innerText() === submittedConsentText);
    await page.locator('.size-field input').fill('265/40R20');
  });
  const decide = async (label, index, dto, decision, status) => {
    scenario(label); const before = requestCounts();
    const gate = await makeGate({ label, path: '/v1/fallback-consents', status,
      expectedBody: { query_id: dto.query_id, decision, scope: 'once' }, body: status === 201 ? { id: randomUUID(), decision, scope: 'once' } : { detail: 'R129 synthetic consent HTTP503' } });
    await groups[index].getByRole('button', { name: decision === 'deny' ? '拒绝，保持无结果' : '仅本次允许', exact: true }).click(); await gate.entered();
    await assertSummary(label + '_decision_pending', { state: 'fallback_pending', busy: true, includes: ['正在处理回退决定 / 2 SOURCES'], excludes: ['正在在线查询', 'MATCHED SKU'] });
    check(label + '_both_controls_disabled_while_pending', await groups[index].getByRole('button', { name: '处理中…', exact: true }).isDisabled()
      && await groups[index].getByRole('button', { name: '拒绝，保持无结果', exact: true }).isDisabled());
    await releaseGates([gate]); const after = requestCounts();
    receipt.consent_windows.push({ label, source_id: dto.source_id, query_id: dto.query_id, decision, status, request_id: gate.record.request_id, before, after });
    check(label + '_one_exact_consent_no_followup_query_or_snapshot', after.consent_posts === before.consent_posts + 1 && after.query_posts === before.query_posts && after.snapshot_reads === before.snapshot_reads);
  };
  await decide('synthetic_deny_A201', 0, consentDtos[0], 'deny', 201);
  await assertSummary('one_denied_other_waiting', { state: 'consent_required', busy: false, includes: ['在线查询未完成，等待回退授权', '1 个来源已拒绝回退'] });
  await decide('synthetic_deny_B201', 1, consentDtos[1], 'deny', 201);
  await assertSummary('all_denied_terminal', { state: 'denied', busy: false, exact: '已拒绝全部回退，本次无可核验结果 / 2 SOURCES' });
  check('both_denied_cards_keep_no_local_read_explanation', await page.locator('.source-result .result-explanation').filter({ hasText: '没有读取本地参数' }).count() === 2);
  await shot('summary-all-denied-wide'); await uiOnly('all_denied_no_implicit_retry_or_snapshot', async () => { await wait(300); });

  const failedConsentDto = syntheticDto(0, 'consent_required', 'upstream_timeout');
  const failPair = await queryPair('synthetic_consent_with_other_unavailable', [{ body: failedConsentDto }, { body: syntheticDto(1, 'source_unavailable', 'upstream_network_error') }]);
  await releaseGates(failPair);
  await assertSummary('one_waiting_one_unavailable', { state: 'consent_required', busy: false, includes: ['在线查询未完成，等待回退授权', '1 个来源未获得可核验结果'] });
  await decide('synthetic_allow_A503', 0, failedConsentDto, 'allow', 503);
  await assertSummary('failed_consent_residual_dto_is_terminal', { state: 'unavailable', busy: false, exact: '本次未获得可核验结果 / 2 SOURCES' });
  check('failed_consent_card_retains_cause_and_original_actions', await groups[0].locator('.inline-error').innerText() === 'R129 synthetic consent HTTP503'
    && await groups[0].getByRole('button', { name: '仅本次允许', exact: true }).isEnabled());
  await uiOnly('failed_consent_no_implicit_live_or_snapshot', async () => { await wait(300); });

  const empty = await queryPair('two_synthetic_live_zero_rows', [0, 1].map(index => ({ body: syntheticDto(index, 'live') })));
  await releaseGates(empty); await assertSummary('successful_zero_is_complete', { state: 'complete', busy: false, exact: '0 MATCHED SKU / 2 SOURCES' });
  check('successful_zero_cards_are_explained', await page.locator('.variant-card').count() === 0
    && await page.locator('.source-result .result-explanation').filter({ hasText: '来源未返回匹配的精确规格' }).count() === 2);

  const partial = await queryPair('real_A_with_synthetic_pending_then_unavailable_B', [{ real: true }, { body: syntheticDto(1, 'source_unavailable', 'upstream_timeout') }]);
  // Release A while B's exact request remains held; its state is genuine UI pending.
  partial[0].release(); await partial[0].settle(); await idle();
  await assertSummary('partial_success_and_real_ui_pending', { state: 'querying', busy: true, exact: '26 MATCHED SKU / 2 SOURCES · 1 个来源正在在线查询' });
  check('partial_A_is_real_live_26', partial[0].payload().data_state === 'live' && partial[0].payload().variants.length === 26 && partial[0].record.real_fetches === 1);
  await assertSummaryTypography('summary_typography_default_light_wide');
  await shot('summary-partial-pending-wide'); await partial[0].remove();
  await releaseGates([partial[1]]);
  await assertSummary('partial_success_and_failure', { state: 'partial', busy: false, exact: '26 MATCHED SKU / 2 SOURCES · 1 个来源未获得可核验结果' });
  for (const width of [390, 320]) { await page.setViewportSize({ width, height: 844 }); await frames(); await summary.scrollIntoViewIfNeeded();
    const geometry = await summary.evaluate(node => { const rect = node.getBoundingClientRect(), style = getComputedStyle(node);
      return { width: innerWidth, x: rect.x, right: rect.right, height: rect.height, scroll_width: node.scrollWidth, client_width: node.clientWidth,
        page_width: document.documentElement.scrollWidth, white_space: style.whiteSpace, overflow_x: style.overflowX, text: node.textContent }; });
    observe('summary_narrow_' + width, geometry);
    check('summary_readable_without_horizontal_clipping_' + width, geometry.x >= -1 && geometry.right <= width + 1 && geometry.height > 0 && geometry.page_width <= width + 1
      && (geometry.client_width === 0 || geometry.scroll_width <= geometry.client_width + 1));
    await assertSummaryTypography('summary_typography_default_light_' + width); await shot('summary-partial-failure-' + width);
  }
  await page.setViewportSize({ width: 1365, height: 900 }); await frames();

  await idle(); scenario('synthetic_directory_check_failure'); const directoryBefore = requestCounts();
  const directoryGate = await makeGate({ label: 'directory_get503', path: '/v1/source-settings', method: 'GET', status: 503, body: { detail: 'R129 synthetic directory HTTP503' } });
  await page.getByRole('button', { name: '按本次条件重新在线查询', exact: true }).click(); await directoryGate.entered();
  await assertSummary('directory_check_pending', { state: 'querying', busy: true, exact: '正在在线查询 / 2 SOURCES' });
  await releaseGates([directoryGate]); await assertSummary('directory_check_failed_terminal', { state: 'unavailable', busy: false, exact: '本次未获得可核验结果 / 2 SOURCES' });
  check('directory_failure_did_not_dispatch_source_query_or_snapshot', equal(requestCounts(), directoryBefore));
  check('directory_failure_preserves_source_card_reason', await groups[0].locator('.inline-error').innerText() === 'R129 synthetic directory HTTP503' && await groups[1].locator('.inline-error').innerText() === 'R129 synthetic directory HTTP503');
  await uiOnly('directory_failure_no_implicit_retry_or_snapshot', async () => { await wait(300); });

  const restored = await queryPair('restored_real_private_live_after_all_injections_removed', [{ real: true }, { real: true }]);
  await releaseGates(restored); await completeLive('restored', restored); await shot('summary-restored-real-live-wide');
  await uiOnly('restored_draft_no_implicit_queries', async () => { await page.locator('.size-field input').fill('245/40R20'); await frames();
    await assertSummary('restored_summary_uses_submitted_result', { state: 'complete', busy: false, exact: '29 MATCHED SKU / 2 SOURCES' }); await page.locator('.size-field input').fill('265/40R20'); });
  const finalFixture = await json(await context.request.get(api('/fixture/state')));
  receipt.final_fixture = { counters: finalFixture.counters, source_calls: finalFixture.source_calls, real_source_calls: finalFixture.real_source_calls, provider_calls: finalFixture.provider_calls, model_requests: finalFixture.model_requests, embedding_requests: finalFixture.embedding_requests };
  const counts = requestCounts(); observe('whole_suite_business_counts', counts);
  check('exact_16_query_posts_3_consents_zero_snapshot_reads', counts.query_posts === 16 && counts.consent_posts === 3 && counts.snapshot_reads === 0);
  check('every_post_is_initial_preview_or_one_exact_planned_gate', postRows().every(row => row.request_id === preview.request_id && row.sequence <= initializationEnd
    || receipt.request_gates.some(record => record.method === 'POST' && record.request_id === row.request_id && record.claimed && record.body_matched))
    && receipt.http_events.every(row => row.event !== 'request' || !row.business || ['GET', 'POST'].includes(row.method)));
  check('fixture_zero_external_child_normal_db_provider_model_embedding_exact_five_real_source_calls', Object.values(finalFixture.counters).every(value => value === 0)
    && finalFixture.source_calls === 5 && finalFixture.real_source_calls === 0 && finalFixture.provider_calls === 0 && finalFixture.model_requests === 0 && finalFixture.embedding_requests === 0);
  check('all_twenty_request_gates_are_exact_finished_removed', gatesPassed()); check('all_four_503_injections_are_exact_bounded_removed', faultsPassed());
  check('strict_http_status_gate_no_unexpected_400_or_higher', !receipt.unexpected_http_statuses.length && !receipt.http_events.some(row => row.event === 'response' && row.status >= 400 && row.expected_status !== true));
  check('strict_browser_network_gate_zero_failures_errors_external', !receipt.page_errors.length && !receipt.console_errors.length && !receipt.unexpected_origins.length
    && !receipt.gate_failures.length && receipt.http_events.every(row => row.event !== 'failed'));
  receipt.production_workbench_verified = true; receipt.state = 'passed';
} catch (error) {
  receipt.state = 'failed'; receipt.failure = { stage, type: ['Error', 'TimeoutError', 'TypeError', 'SyntaxError'].includes(error?.name) ? error.name : 'Error',
    check: /^[a-zA-Z0-9_:-]+$/.test(error?.message || '') ? error.message : null,
    source_frames: [...String(error?.stack || '').matchAll(/query_summary_ui_qa\.mjs:(\d+):(\d+)/g)].map(match => ({ line: Number(match[1]), column: Number(match[2]) })) };
  if (page) try { await page.screenshot({ path: resolve(output, 'failure.png') }); receipt.screenshots.push('failure.png'); } catch {}
} finally {
  password = null;
  for (const gate of gates) gate.release();
  for (const gate of [...gates]) { try { if (gate.record.claimed) await gate.settle(); await gate.remove(); } catch { receipt.cleanup_failures.push('pending_gate_cleanup_failed'); } }
  try { if (context) { const response = await context.request.post(fixtureOrigin + '/fixture/shutdown', { timeout: 5000 }); receipt.fixture_shutdown_requested = response.ok(); } } catch { receipt.cleanup_failures.push('fixture_shutdown_request_failed'); }
  let closeTimer;
  try { await Promise.race([(async () => { if (context) await context.close(); if (browser) await browser.close(); if (browserServer) await browserServer.close(); })(),
    new Promise((_, reject) => { closeTimer = setTimeout(() => reject(Error('browser_close_timeout')), 20000); })]);
    receipt.browser_close_returned = !!browserProcess && browserProcess.exitCode === 0 && browserProcess.signalCode === null && receipt.browser.server_close_observed === true;
  } catch { receipt.cleanup_failures.push('browser_close_failed'); if (browserServer) { receipt.browser.forced_kill_requested = true; try { await browserServer.kill(); } catch { receipt.cleanup_failures.push('browser_kill_failed'); } } }
  finally { clearTimeout(closeTimer); }
  if (receipt.unexpected_http_statuses.length || receipt.http_events.some(row => row.event === 'response' && row.status >= 400 && row.expected_status !== true)) receipt.cleanup_failures.push('terminal_unexpected_http_status_400_or_higher');
  receipt.request_gate_coverage = { required: 20, recorded: receipt.request_gates.length, state: gatesPassed() ? 'passed' : 'failed', routes_removed: gates.size === 0 && activeRecords.size === 0 };
  receipt.synthetic_http_fault_coverage = { required: 4, recorded_faults: receipt.synthetic_http_faults.length, state: faultsPassed() ? 'passed' : 'failed',
    route_cleanup_complete: activeRecords.size === 0 && receipt.request_gates.every(record => !record.active && record.route_removed) };
  if (!gatesPassed() || !faultsPassed()) receipt.coverage_failures.push('exact_planned_request_or_fault_contract_not_satisfied');
  if (!receipt.synthetic_http_fault_coverage.route_cleanup_complete) receipt.cleanup_failures.push('terminal_route_cleanup_failed');
  if (receipt.page_errors.length || receipt.console_errors.length || receipt.unexpected_origins.length || receipt.gate_failures.length || receipt.http_events.some(row => row.event === 'failed')) receipt.cleanup_failures.push('terminal_browser_or_network_error');
  try { receipt.inputs_unchanged = equal(snapshot(Object.keys(inputPins)), inputPins); } catch { receipt.inputs_unchanged = false; }
  if (!receipt.inputs_unchanged) receipt.cleanup_failures.push('input_drift');
  try { receipt.prepared_runtimes_unchanged = equal(tree(playwrightRoot), runtimePins.playwright) && equal(tree(browserRoot), runtimePins.browser) && equal(tree(privatePlaywright), runtimePins.playwright)
    && equal(tree(privateBrowser, undefined, receipt.browser_generated_sidecars, runtimePins.browser), runtimePins.browser); } catch { receipt.prepared_runtimes_unchanged = false; }
  if (!receipt.prepared_runtimes_unchanged) receipt.cleanup_failures.push('runtime_drift_or_copy_incomplete');
  if (!receipt.browser_close_returned || !receipt.fixture_shutdown_requested || receipt.browser.forced_kill_requested || receipt.coverage_failures.length || receipt.cleanup_failures.length) receipt.state = 'failed';
  receipt.artifact_hashes = snapshot(receipt.screenshots.map(name => resolve(output, name))); receipt.finished_utc = new Date().toISOString(); save();
  writeFileSync(resolve(output, 'browsercleanup.json'), JSON.stringify({ state: receipt.state, browser: receipt.browser, browser_close_returned: receipt.browser_close_returned,
    fixture_shutdown_requested: receipt.fixture_shutdown_requested, coverage_failures: receipt.coverage_failures, request_gate_coverage: receipt.request_gate_coverage, synthetic_http_fault_coverage: receipt.synthetic_http_fault_coverage,
    cleanup_failures: receipt.cleanup_failures, inputs_unchanged: receipt.inputs_unchanged, prepared_runtimes_unchanged: receipt.prepared_runtimes_unchanged,
    browser_generated_sidecars: receipt.browser_generated_sidecars, browser_generated_sidecar_policy: sidecarPolicy }, null, 2) + '\n');
}
console.log(JSON.stringify({ state: receipt.state, output, checks: receipt.checks.length, failure: receipt.failure || null }));
if (receipt.state !== 'passed') process.exitCode = 3;
