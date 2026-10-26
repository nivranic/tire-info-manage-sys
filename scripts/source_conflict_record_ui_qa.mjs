/** R131: current production Workbench source conflict wording and bounded compatibility DTO coverage.
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
if (origin !== 'http://127.0.0.1:18987' || dirname(output) !== artifacts || !/^r131browser-[a-f0-9]{16}$/.test(basename(output))
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
  resolve(root, '.artifacts/r127-variant-context-menu-20261022/run-ui-host.py'), resolve(root, '.artifacts/r131-source-conflict-records-20261023/run-ui-host.py'),
  resolve(root, '.artifacts/r118-material-workbench-20261021/serve-web-v1.py'), resolve(root, 'docs/plans/2026-10-23-source-conflict-record-wording.md'),
  resolve(root, '.artifacts/r131-source-conflict-records-20261023/product-review.json')]) };
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
const requiredGates = 11;
const receipt = { schema: 'r131-source-conflict-records-production-workbench@1', state: 'running', started_utc: new Date().toISOString(), origin, fixture_origin: fixtureOrigin,
  build, build_report_sha256: reportSha, input_pins: inputPins, runtime_pins: runtimePins, checks: [], scenarios: [], observations: [], screenshots: [], http_events: [], ui_request_windows: [],
  request_gates: [], synthetic_payloads: [], harness_http: [], unexpected_origins: [], unexpected_http_statuses: [], page_errors: [], console_errors: [],
  gate_failures: [], coverage_failures: [], cleanup_failures: [], browser_generated_sidecars: [], browser_generated_sidecar_policy: sidecarPolicy,
  browser: { playwright: '1.63.0', chromium_revision: '1243', headless: true }, browser_close_returned: false, fixture_shutdown_requested: false,
  inputs_unchanged: false, prepared_runtimes_unchanged: false, synthetic_only: true, production_workbench_verified: false,
  product_review_basis: 'product-review.json', explicit_limitations: [
    'real_http_uses_project_owned_synthetic_fixture_not_real_external_sources',
    'resolved_missing_null_empty_unknown_case_and_whitespace_states_are_bounded_compatibility_route_synthesis_not_observed_production_incidents',
    'query_watch_current_comparison_saved_list_and_detail_injections_never_dispatch_to_backend',
    'current_comparison_uses_sdk_read_only_POST_not_a_saved_comparison_write',
    'one_private_account_registration_and_initial_history_preview_are_real_other_business_writes_forbidden',
    'service_workers_blocked_matching_build_public_served_by_page_route',
    'screenshots_require_root_visual_inspection_no_full_wcag_reader_device_native_host_pwa_or_complete_v1_claim',
    'cleanup_is_owned_process_and_input_summary_not_per_react_resource_or_per_dbapi_handle_proof' ] };
const save = () => writeFileSync(resolve(output, 'result.json'), JSON.stringify(receipt, null, 2) + '\n');
const check = (label, condition) => { if (!condition) throw Error(label); receipt.checks.push(label); save(); };
const observe = (label, value) => { receipt.observations.push({ label, ...value }); save(); };
const api = path => origin + '/api' + path;
const wait = ms => new Promise(done => setTimeout(done, ms));
const bounded = async promise => { let timer; try { return await Promise.race([promise, new Promise((_, reject) => {
  timer = setTimeout(() => reject(Error('request_gate_timeout')), 12000); })]); } finally { clearTimeout(timer); } };
const privatePlaywright = resolve(output, 'runtime/playwright-core'), privateBrowser = resolve(output, 'runtime/chromium_headless_shell-1243');
let browser, browserServer, browserProcess, context, page, stage = 'runtime_copy', phase = 'initialization', password = randomBytes(24).toString('base64url');
const inFlight = new Set(), heldRequests = new Set(), gates = new Set(), activeRecords = new Map(), requestRecords = new WeakMap(), requestIds = new WeakMap();
let requestSequence = 0, protectedReads = false;
const postRows = () => receipt.http_events.filter(row => row.event === 'request' && row.method === 'POST');
const queryRows = () => postRows().filter(row => /\/live-query$/.test(row.path));
const businessRows = () => receipt.http_events.filter(row => row.event === 'request' && row.business);
const gatesPassed = () => receipt.request_gates.length === requiredGates && gates.size === 0 && activeRecords.size === 0 && receipt.request_gates.every(record =>
  record.claimed && record.requests === 1 && record.observed_responses === 1 && record.finished_events === 1 && record.completed && record.released
  && record.route_removed && !record.active && record.body_matched && Number.isInteger(record.request_id) && record.request_id > 0
  && record.response_bytes > 0 && record.response_bytes <= record.max_response_bytes && record.status === 200
  && (record.origin === 'real_private_fixture_http' ? record.real_fetches === 1 && record.injected_responses === 0 : record.real_fetches === 0 && record.injected_responses === 1));
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
    const request = route.request(), url = new URL(request.url());
    if (!['http:', 'https:'].includes(url.protocol) || ![origin, fixtureOrigin].includes(url.origin)) { receipt.unexpected_origins.push('blocked_external_origin'); await route.abort(); return; }
    const business = url.origin === fixtureOrigin || url.pathname.startsWith('/api/');
    const initialPreview = phase === 'initialization' && url.href === api('/v1/personal-feed/preview?mode=history') && request.method() === 'POST';
    const guardedRead = protectedReads && /^\/api\/v1\/(?:watchlists|saved-comparisons|evidence)(?:\/|$)/.test(url.pathname);
    // Later exact route handlers claim planned requests. Any fall-through write,
    // repeated protected read or wrong-method request fails before dispatch.
    if (business && (request.method() !== 'GET' && !initialPreview || guardedRead)) {
      receipt.gate_failures.push({ label: 'unplanned_business_request', method: request.method(), path: url.pathname }); await route.abort('failed'); return;
    }
    const name = url.pathname.slice(1);
    if (url.origin === origin && ['favicon.ico', 'sw.js', 'icons/icon-180.png', 'icons/icon-192.png', 'icons/icon-512.png'].includes(name)) {
      const path = resolve(publicRoot, name); if (existsSync(path)) { await route.fulfill({ status: 200, body: readFileSync(path) }); return; }
    }
    await route.continue();
  });
  const recordEvent = (event, request, status) => {
    const url = new URL(request.url()); if (!requestIds.has(request)) requestIds.set(request, ++requestSequence);
    const row = { sequence: receipt.http_events.length + 1, request_id: requestIds.get(request), phase, event, method: request.method(),
      path: [origin, fixtureOrigin].includes(url.origin) ? url.pathname : 'blocked', query: [origin, fixtureOrigin].includes(url.origin) ? url.search : '',
      business: [origin, fixtureOrigin].includes(url.origin) && (url.origin === fixtureOrigin || url.pathname.startsWith('/api/')),
      ...(status === undefined ? {} : { status }), ...(event === 'failed' ? { failure: request.failure()?.errorText === 'net::ERR_ABORTED' ? 'aborted' : 'other' } : {}) };
    receipt.http_events.push(row);
    if (event === 'response' && status >= 400) receipt.unexpected_http_statuses.push({ request_id: row.request_id, phase, method: row.method, path: row.path, status });
  };
  page.on('request', request => { recordEvent('request', request); if (new URL(request.url()).pathname.startsWith('/api/')) inFlight.add(request); });
  page.on('response', response => {
    const request = response.request(), record = requestRecords.get(request);
    if (record?.active && activeRecords.get(response.url()) === record && phase === record.phase && request.method() === record.method
      && requestIds.get(request) === record.request_id && response.status() === 200 && record.requests === 1 && record.observed_responses === 0
      && (record.origin === 'real_private_fixture_http' ? record.real_fetches === 1 : record.injected_responses === 1)) record.observed_responses++;
    recordEvent('response', request, response.status());
  });
  page.on('requestfinished', request => { inFlight.delete(request); const record = requestRecords.get(request); if (record) record.finished_events++; recordEvent('finished', request); });
  page.on('requestfailed', request => { inFlight.delete(request); recordEvent('failed', request); });
  page.on('pageerror', error => receipt.page_errors.push(error?.name || 'PageError'));
  page.on('console', message => { if (message.type() === 'error') receipt.console_errors.push('browser_console_error'); });
  const frames = () => page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
  const idle = async () => { for (let attempt = 0; attempt < 100; attempt++) { await frames(); if ([...inFlight].every(request => heldRequests.has(request))) {
    await wait(100); if ([...inFlight].every(request => heldRequests.has(request))) return; } await wait(50); } throw Error('business_requests_did_not_settle'); };
  const scenario = label => { stage = label; phase = 'scenario:' + label; receipt.scenarios.push(label); save(); };
  const choiceState = () => page.evaluate(() => ({ selected: [...document.querySelectorAll('input[data-query-selection-id]:checked')].map(node => node.getAttribute('data-query-selection-row')).sort(),
    compared: [...document.querySelectorAll('.variant-actions button[aria-pressed="true"]')].map(node => node.closest('.variant-card')?.querySelector('[data-variant-preview-trigger]')?.getAttribute('data-variant-preview-trigger')).sort() }));
  const uiOnly = async (label, operation, choicesMayChange = false) => {
    await idle(); const start = receipt.http_events.length, before = await choiceState(); phase = 'ui:' + label;
    const inputsPresent = await page.evaluate(() => { const selectors = ['.size-field input', '.model-field select', '.region-selector select']; const nodes = selectors.map(selector => document.querySelector(selector));
      window.__r131Inputs = nodes.every(Boolean) ? { selectors, nodes, values: nodes.map(node => node.value) } : null; return !!window.__r131Inputs; });
    await operation(); await frames(); await wait(250); await idle();
    const requests = receipt.http_events.slice(start).filter(row => row.event === 'request' && row.business), after = await choiceState();
    const inputState = await page.evaluate(() => { const old = window.__r131Inputs; return old ? { nodes: old.nodes.every((node, index) => node === document.querySelector(old.selectors[index])),
      values: old.nodes.every((node, index) => node.value === old.values[index]) } : null; });
    receipt.ui_request_windows.push({ label, start_sequence: start + 1, end_sequence: receipt.http_events.length, business_requests: requests,
      choices_before: before, choices_after: after, choices_may_change: choicesMayChange, query_input_baseline_present: inputsPresent, input_state: inputState });
    check(label + '_zero_business_requests', requests.length === 0);
    check(label + '_query_inputs_preserved', !inputsPresent || inputState.nodes && inputState.values);
    check(label + '_choices_preserved_or_explicit_change', choicesMayChange || equal(before, after));
  };
  const shot = async (label, target) => {
    await target.evaluate(node => node.scrollIntoView({ block: 'start', inline: 'nearest', behavior: 'instant' })); await frames();
    const alignment = await target.evaluate(node => {
      const dialog = node.closest('dialog[open]'), title = node.matches('summary') ? node : node.querySelector(':scope > strong');
      if (!title) throw Error('screenshot_title_required');
      const heading = dialog?.querySelector('.fact-review-heading'), before = title.getBoundingClientRect().top;
      const sticky = heading?.getBoundingClientRect(), desiredTop = sticky ? sticky.bottom + 8 : null;
      const previousScroll = dialog?.scrollTop ?? null;
      // Scroll the actual modal, leaving its measured sticky heading intact.
      // Subsequent frame and hit tests decide acceptance, not this adjustment.
      if (dialog && desiredTop !== null && before < desiredTop) dialog.scrollTop += before - desiredTop;
      return { modal: !!dialog, title_top_before: before, sticky_heading_height: sticky?.height ?? null,
        sticky_heading_bottom: sticky?.bottom ?? null, desired_title_top: desiredTop, scroll_before: previousScroll, scroll_after: dialog?.scrollTop ?? null };
    });
    await frames(); observe(label + '_measured_sticky_heading_alignment', alignment);
    const visibleTitle = await target.evaluate(node => {
      const title = node.matches('summary') ? node : node.querySelector(':scope > strong'), dialog = node.closest('dialog[open]');
      const heading = dialog?.querySelector('.fact-review-heading'), sticky = heading?.getBoundingClientRect(), modal = dialog?.getBoundingClientRect();
      const clip = { top: Math.max(0, sticky?.bottom ?? 0, modal ? modal.top + dialog.clientTop : 0),
        bottom: Math.min(innerHeight, modal ? modal.top + dialog.clientTop + dialog.clientHeight : innerHeight),
        left: Math.max(0, modal ? modal.left + dialog.clientLeft : 0),
        right: Math.min(innerWidth, modal ? modal.left + dialog.clientLeft + dialog.clientWidth : innerWidth) };
      const range = document.createRange(); range.selectNodeContents(title);
      const fragments = [...range.getClientRects()].filter(rect => rect.width > 0 && rect.height > 0).map(rect => ({
        left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
        probes: [.1, .5, .9].map(fraction => { const x = rect.left + rect.width * fraction, y = rect.top + rect.height / 2;
          const hit = document.elementFromPoint(x, y); return { x, y, title_hit: !!hit && (hit === title || title.contains(hit)), hit_tag: hit?.tagName ?? null }; }) }));
      return { text: title.textContent, clip, fragments };
    });
    observe(label + '_title_visibility_and_hit_tests', visibleTitle);
    check(label + '_title_vertically_visible_and_unobscured', visibleTitle.fragments.length > 0 && visibleTitle.fragments.every(rect =>
      rect.top >= visibleTitle.clip.top && rect.bottom <= visibleTitle.clip.bottom && rect.left >= visibleTitle.clip.left && rect.right <= visibleTitle.clip.right
      && rect.probes.every(probe => probe.title_hit)));
    const geometry = await target.evaluate(node => { const rect = node.getBoundingClientRect();
      const textNodes = [...(node.matches('summary') ? [node] : []), ...node.querySelectorAll('strong,p,li b,li span')];
      const text = textNodes.map(item => { const r = item.getBoundingClientRect(); const css = getComputedStyle(item);
        return { text: item.textContent, left: r.left, right: r.right, width: r.width, height: r.height, font_px: parseFloat(css.fontSize),
          client_width: item.clientWidth, scroll_width: item.scrollWidth, overflow_x: css.overflowX }; });
      return { viewport_width: innerWidth, viewport_height: innerHeight, document_width: document.documentElement.scrollWidth,
        left: rect.left, right: rect.right, width: rect.width, height: rect.height, text }; });
    observe(label + '_horizontal_readability', geometry);
    check(label + '_no_horizontal_text_clipping', geometry.left >= -1 && geometry.right <= geometry.viewport_width + 1
      && geometry.document_width <= geometry.viewport_width + 1 && geometry.text.every(item => item.width > 0 && item.height > 0
        && item.left >= geometry.left - 1 && item.right <= geometry.right + 1 && (item.client_width === 0 || item.scroll_width <= item.client_width + 1)));
    const name = label + '.png'; await page.screenshot({ path: resolve(output, name) }); receipt.screenshots.push(name); save();
  };
  const makeGate = async ({ label, path, method = 'POST', expectedBody = null, body, real = false }) => {
    const url = api(path); if (activeRecords.has(url) || !['GET', 'POST'].includes(method)) throw Error('duplicate_or_invalid_gate');
    const encoded = real ? null : JSON.stringify(body), maxBytes = real ? 4194304 : 131072;
    if (!real && (!encoded || Buffer.byteLength(encoded) > maxBytes)) throw Error('synthetic_response_size_bound');
    let enter, release, finish, payload;
    const entered = new Promise(done => { enter = done; }), released = new Promise(done => { release = done; }), completed = new Promise(done => { finish = done; });
    const record = { label, method, url, status: 200, phase, origin: real ? 'real_private_fixture_http' : 'synthetic_browser_route_injection_without_backend_dispatch', expected_body: expectedBody,
      active: true, route_removed: false, claimed: false, requests: 0, request_id: null, body_matched: false, real_fetches: 0, injected_responses: 0,
      observed_responses: 0, finished_events: 0, released: false, completed: false, max_response_bytes: maxBytes, response_bytes: 0, response_sha256: null };
    receipt.request_gates.push(record); activeRecords.set(url, record);
    if (!real) receipt.synthetic_payloads.push({ label, exact_url: url, method, bytes: Buffer.byteLength(encoded), sha256: sha(Buffer.from(encoded)), delivery: 'single_browser_route_fulfill_no_backend_dispatch' });
    const handler = async route => {
      const request = route.request(); record.requests++; heldRequests.add(request);
      try {
        if (request.url() !== url || request.method() !== method || !record.active || phase !== record.phase || record.claimed) throw Error('duplicate_wrong_method_or_phase_request');
        if (!requestIds.has(request)) requestIds.set(request, ++requestSequence);
        record.claimed = true; record.request_id = requestIds.get(request); requestRecords.set(request, record);
        record.body_matched = method === 'GET' ? request.postData() === null : Buffer.byteLength(request.postData() || '') <= 4096 && equal(request.postDataJSON(), expectedBody);
        if (!record.body_matched) throw Error('exact_request_body_mismatch');
        let response, bytes;
        if (real) { record.real_fetches++; response = await route.fetch({ timeout: 12000, maxRetries: 0, maxRedirects: 0 });
          if (response.status() !== 200) throw Error('real_private_http_status_mismatch'); bytes = await response.body(); payload = JSON.parse(bytes.toString('utf8')); }
        else { bytes = Buffer.from(encoded); payload = body; }
        record.response_bytes = bytes.length; record.response_sha256 = sha(bytes);
        if (!bytes.length || bytes.length > maxBytes) throw Error('response_size_bound');
        enter(); await released; record.released = true;
        if (real) await route.fulfill({ response });
        else { record.injected_responses++; await route.fulfill({ status: 200, contentType: 'application/json', headers: { 'cache-control': 'no-store' }, body: encoded }); }
      } catch (error) { receipt.gate_failures.push({ label, type: /^[a-z_]+$/.test(error?.message || '') ? error.message : error?.name || 'Error' }); try { await route.abort('failed'); } catch {} }
      finally { heldRequests.delete(request); record.completed = true; enter(); finish(); }
    };
    await context.route(url, handler);
    const gate = { record, entered: () => bounded(entered), release, settle: () => bounded(completed), payload: () => payload,
      remove: async () => { await context.unroute(url, handler); record.active = false; record.route_removed = true; activeRecords.delete(url); gates.delete(gate); save(); } };
    gates.add(gate); save(); return gate;
  };
  const releaseGates = async values => { values.forEach(gate => gate.release()); await Promise.all(values.map(gate => gate.settle())); await idle();
    for (const gate of values) { check(gate.record.label + '_one_exact_response_finished', gate.record.requests === 1 && gate.record.observed_responses === 1 && gate.record.finished_events === 1); await gate.remove(); } };
  const harnessJson = async (label, method, path, data) => {
    const response = await context.request.fetch(api(path), { method, ...(data ? { data } : {}), timeout: 12000, maxRedirects: 0 });
    receipt.harness_http.push({ label, method, path, status: response.status(), origin: 'real_private_fixture_http', credential_body_not_recorded: true });
    if (!response.ok()) throw Error('harness_http_status'); return response.json();
  };
  const fixture = await harnessJson('initial_fixture_state', 'GET', '/fixture/state');
  check('private_fixture_zero_real_usage_exact_two_sources', fixture.synthetic_only && !fixture.normal_database_used && fixture.source_calls === 0 && fixture.real_source_calls === 0
    && fixture.provider_calls === 0 && fixture.model_requests === 0 && fixture.embedding_requests === 0
    && equal(fixture.source_ids, ['r122-selection-a', 'r122-selection-b']) && equal(fixture.source_row_counts, [26, 3]));
  const admin = await harnessJson('one_private_admin_registration', 'POST', '/v1/auth/register', { username: 'r131_admin_' + randomBytes(4).toString('hex'), password }); password = null;
  check('admin_registered_real_private_http', admin.user?.is_admin === true);
  check('production_document_http_200', (await page.goto(origin, { waitUntil: 'domcontentloaded' }))?.status() === 200);
  await page.locator('.sidebar-foot small').filter({ hasText: '管理员 · 本机工作台' }).waitFor(); await page.locator('.home-counts').waitFor(); await idle();
  const initializationEnd = receipt.http_events.length, preview = postRows()[0];
  check('initialization_exact_single_finished_history_preview', postRows().length === 1 && preview.path === '/api/v1/personal-feed/preview' && preview.query === '?mode=history'
    && receipt.http_events.some(row => row.request_id === preview.request_id && row.event === 'response' && row.status === 200)
    && receipt.http_events.some(row => row.request_id === preview.request_id && row.event === 'finished'));
  receipt.initialization_business_window = { end_sequence: initializationEnd, preview_request_id: preview.request_id };
  protectedReads = true;
  phase = 'navigation:query'; await page.locator('.main-nav').getByRole('button', { name: /轮胎查询/ }).click(); await idle();
  await page.locator('.model-field select').selectOption(fixture.model); await page.locator('.region-selector select').selectOption('US'); await page.locator('.size-field input').fill('265/40R20');
  const expectedQuery = { query: { size: '265/40R20', model: fixture.model }, filters: [], fallback_policy: 'ask' };
  const queryPair = async (label, bodies, first = false) => { scenario(label); const pair = [];
    for (let index = 0; index < 2; index++) pair.push(await makeGate({ label: label + '_' + index, path: '/v1/sources/' + fixture.source_ids[index] + '/live-query',
      expectedBody: expectedQuery, ...(bodies ? { body: bodies[index] } : { real: true }) }));
    await (first ? page.locator('.query-submit') : page.getByRole('button', { name: '按本次条件重新在线查询', exact: true })).click();
    await Promise.all(pair.map(gate => gate.entered())); await releaseGates(pair);
    await page.waitForFunction(() => document.querySelector('.results-heading [role="status"]')?.getAttribute('data-query-state') === 'complete');
    return pair.map(gate => gate.payload()); };
  const real = await queryPair('real_private_live_query', null, true);
  check('real_http_26_3_shared_sku_distinct_sources', real.every((dto, index) => dto.data_state === 'live' && dto.source_id === fixture.source_ids[index] && dto.variants.length === [26, 3][index])
    && real[0].variants[0].id === real[1].variants[0].id && real[0].variants[0].snapshot_id !== real[1].variants[0].snapshot_id);
  const groups = ['A', 'B'].map(letter => page.locator('.source-result').filter({ has: page.getByRole('heading', { name: 'R122 合成来源 ' + letter, exact: true }) }));
  const card = (index, id) => groups[index].locator('.variant-card').filter({ has: page.locator(`input[data-query-selection-id="${id}"]`) });
  await groups[0].locator('.variant-card').first().waitFor();
  check('real_query_existing_20_3_card_paging', await groups[0].locator('.variant-card').count() === 20 && await groups[1].locator('.variant-card').count() === 3);
  const originalTrigger = card(0, real[0].variants[0].id).locator('[data-variant-preview-trigger]');
  phase = 'action:real_evidence';
  const evidence = await makeGate({ label: 'real_evidence_original_button', path: '/v1/evidence/' + real[0].variants[0].snapshot_id, method: 'GET', real: true });
  await originalTrigger.click(); await evidence.entered(); await releaseGates([evidence]); await page.locator('.evidence-detail').waitFor();
  check('real_evidence_matches_original_snapshot', evidence.payload()?.id === real[0].variants[0].snapshot_id);
  await uiOnly('original_evidence_close_focus', async () => {
    await page.getByRole('button', { name: '关闭证据', exact: true }).click(); await page.locator('.evidence-detail').waitFor({ state: 'detached' });
    check('close_returns_focus_to_original_evidence_button', await originalTrigger.evaluate(node => document.activeElement === node));
  });

  // Each expected label is authored in the matrix. Missing resolution is an
  // omitted property, distinct from explicit null and empty string.
  const statusMatrix = [
    { name: '精确已解决', value: 'resolved', expected: '原记录标记已解决' },
    { name: '未解决', value: 'unresolved', expected: '待核验' },
    { name: '缺失状态', absent: true, expected: '待核验' },
    { name: '空值状态', value: null, expected: '待核验' },
    { name: '空串状态', value: '', expected: '待核验' },
    { name: '未知状态', value: 'r131_unknown_state', expected: '待核验' },
    { name: '首字母大写', value: 'Resolved', expected: '待核验' },
    { name: '全部大写', value: 'RESOLVED', expected: '待核验' },
    { name: '前置空格', value: ' resolved', expected: '待核验' },
    { name: '后置空格', value: 'resolved ', expected: '待核验' },
    { name: '只有空白', value: ' ', expected: '待核验' },
  ];
  const makeConflicts = entries => entries.map((entry, index) => ({ field: entry.name + ' ' + (index + 1),
    values: [{ source_field: '合成布尔来源', value: false }, { source_field: '合成数值来源', value: 0 }, { source_field: '合成空值来源', value: null }],
    ...(entry.absent ? {} : { resolution: entry.value }) }));
  const cases = [
    { name: 'empty', source: 0, base: real[0].variants[0], entries: [] },
    { name: 'all_unresolved', source: 1, base: real[1].variants[1], entries: [statusMatrix[1], { ...statusMatrix[1], name: '另一未解决' }] },
    { name: 'all_resolved', source: 0, base: real[0].variants[1], entries: [statusMatrix[0], { ...statusMatrix[0], name: '另一精确已解决' }] },
    { name: 'mixed_compatibility', source: 1, base: real[1].variants[2], entries: statusMatrix },
  ];
  const stamp = '2026-10-23T00:00:00Z';
  for (const item of cases) {
    item.conflicts = makeConflicts(item.entries); item.variant = structuredClone(item.base);
    item.variant.facts = { ...item.variant.facts, source_field_conflicts: item.conflicts, r131_choice: 'R131原始值' };
    // The explicit synthetic default and independent curation share no conflict
    // resolution mutation. Full candidate shape allows real detail rendering.
    const authority = { tier: 1, rule: 'R131_SYNTHETIC', explanation: '仅兼容UI合成依据' };
    const candidate = { id: 'r131-candidate-' + item.name, variant_id: item.variant.id, source_id: fixture.source_ids[item.source], source_name: 'R131合成字段来源',
      source_class: 'manufacturer', source_region: 'US', field: 'r131_choice', source_field: 'r131_choice', present: true, value: 'R131默认值',
      snapshot_id: item.variant.snapshot_id, fact_version_id: null, source_url: '', raw_hash: null, parser_version: null, observed_at: stamp, verified_at: null, published_at: null,
      evidence_locator: null, identity_match: 'exact', region_match: 'exact', evidence_valid: false, missing_evidence: ['synthetic_compatibility_input'],
      source_conflicted: true, curation_field: 'r131_choice', eligible: true, exclusion_reasons: [], authority,
      dimensions: { authority, identity: { match: 'exact', explanation: '合成兼容记录' }, region: { match: 'exact', source_region: 'US', explanation: '合成兼容记录' },
        time: { ranked_at: stamp, basis: 'observed_at', verified_at: null, verification_used_for_rank: false }, evidence: { valid: false, missing: ['synthetic_compatibility_input'], explanation: '不冒充正式证据' } } };
    item.variant.field_resolution = { policy: { version: 'R131_SYNTHETIC', digest: 'r131-synthetic-policy' }, variant_id: item.variant.id, scope: 'current_source', data_state: 'local_snapshot',
      fields: [{ field: 'r131_choice', label: '合成默认字段', unit: null, category: 'technical', identity_bound: false, source_scope_only: true, state: 'conflict_preferred',
        has_default: true, default_value: 'R131默认值', default_candidate_ids: [candidate.id], candidates: [candidate], reasons: ['合成UI兼容用例；没有产生裁定'] }],
      fingerprint: 'r131-synthetic-' + item.name, notice: 'R131合成默认展示，不改变原冲突记录' };
    item.variant.effective_facts = { ...item.variant.facts, r131_choice: 'R131人工值' };
    item.variant.curation = { source_id: fixture.source_ids[item.source], revision: 1, base_fact_id: 'r131-synthetic-base',
      fields: { r131_choice: { revision_id: 'r131-synthetic-revision', revision: 1, status: 'manual_override', operator: 'R131合成', reason: '仅兼容UI用例',
        after: { present: true, value: 'R131人工值' }, base_fact_id: 'r131-synthetic-base', evidence: [] } } };
    item.dto = { ...structuredClone(real[item.source]), query_id: randomUUID(), variants: [item.variant], conflicts: item.conflicts,
      selection: { filters: [], source_count: 1, matched_count: 1, excluded_count: 0, undetermined_count: 0 } };
  }
  receipt.compatibility_matrix = cases.map(item => ({ name: item.name, origin: 'synthetic_browser_route_only', states: item.entries,
    conflict_count: item.conflicts.length, field_default: 'R131默认值', independent_manual_value: 'R131人工值' })); save();
  const assertItems = async (target, entries, label) => {
    await target.locator('.conflict-item').first().waitFor();
    const actual = await target.locator('.conflict-item').evaluateAll(nodes => nodes.map(node => ({ heading: node.querySelector(':scope > strong')?.textContent,
      values: [...node.querySelectorAll('li b')].map(value => value.textContent), sources: [...node.querySelectorAll('li span')].map(value => value.textContent) })));
    observe(label + '_rendered_conflict_records', { actual, expected_count: entries.length });
    check(label + '_exact_status_per_record_and_false_zero_null_preserved', equal(actual, entries.map((entry, index) => ({ heading: entry.name + ' ' + (index + 1) + '：' + entry.expected,
      values: ['否（false）', '0', '来源未标明'], sources: ['合成布尔来源', '合成数值来源', '合成空值来源'] }))));
    check(label + '_no_unqualified_adjudication_or_arbitrary_unknown_state', !/(?:尚未裁定|已有裁定记录|未自动裁定|r131_unknown_state)/.test(await target.innerText()));
  };
  const cardCopy = '下列保留原记录的不同取值及处理状态；默认展示值和人工核验不会改写这些记录。';
  const assertCard = async (target, item, label) => {
    await target.waitFor(); const section = target.locator('section.source-conflict[aria-label="来源字段冲突"]');
    if (!item.entries.length) { check(label + '_empty_has_no_conflict_section', await section.count() === 0); return; }
    check(label + '_neutral_original_record_title_and_explanation', await section.locator(':scope > strong').innerText() === '原记录中的来源字段冲突'
      && await section.locator(':scope > p').innerText() === cardCopy);
    await assertItems(section, item.entries, label);
    check(label + '_separate_default_visible_without_changing_original_status', (await target.locator('.field-card-defaults').innerText()).includes('R131默认值'));
  };
  const assertQuery = async item => {
    const target = card(item.source, item.variant.id), details = groups[item.source].locator(':scope > .conflict-details');
    // Workbench's source-level details is a sibling of the individual cards.
    await assertCard(target, item, 'query_' + item.name);
    if (!item.entries.length) { check('empty_query_source_has_no_conflict_summary', await details.count() === 0); return; }
    check('query_' + item.name + '_neutral_counted_summary', await details.locator(':scope > summary').innerText() === `当前来源快照有 ${item.entries.length} 项字段冲突记录`);
    await details.locator(':scope > summary').click(); await assertItems(details, item.entries, 'summary_' + item.name);
    await details.locator(':scope > summary').click(); check('query_' + item.name + '_summary_closed', await details.getAttribute('open') === null);
  };
  await queryPair('synthetic_empty_and_all_unresolved', cases.slice(0, 2).map(item => item.dto));
  await uiOnly('empty_unresolved_query_read_and_summary_toggle', async () => { for (const item of cases.slice(0, 2)) await assertQuery(item); });
  await queryPair('synthetic_all_resolved_and_mixed', cases.slice(2).map(item => item.dto));
  await uiOnly('resolved_mixed_query_read_and_summary_toggle', async () => { for (const item of cases.slice(2)) await assertQuery(item); });
  await uiOnly('query_conflict_wide_screenshot', async () => { await shot('query-all-resolved-wide', card(0, cases[2].variant.id).locator('[aria-label="来源字段冲突"]'));
    await shot('query-mixed-wide', card(1, cases[3].variant.id).locator('[aria-label="来源字段冲突"]'));
    await shot('query-summary-wide', groups[1].locator(':scope > .conflict-details > summary')); });
  await uiOnly('query_conflict_320_screenshot_and_local_preview', async () => {
    await page.setViewportSize({ width: 320, height: 844 });
    const target = card(1, cases[3].variant.id), trigger = target.locator('[data-variant-preview-trigger]');
    await shot('query-mixed-320', target.locator('[aria-label="来源字段冲突"]'));
    await shot('query-summary-320', groups[1].locator(':scope > .conflict-details > summary'));
    await trigger.hover(); const tooltip = page.locator('.variant-preview[role="tooltip"]'); await tooltip.waitFor();
    check('mixed_compatibility_preview_retains_unresolved_risk', (await tooltip.innerText()).includes('来源冲突待核验'));
    await page.keyboard.press('Escape'); await page.mouse.move(0, 0); await tooltip.waitFor({ state: 'detached' });
    await page.setViewportSize({ width: 1365, height: 900 });
  });
  await uiOnly('explicit_query_selection_and_compare_add', async () => {
    for (const item of cases.slice(2)) { const target = card(item.source, item.variant.id); await target.locator('input[data-query-selection-id]').check();
      await target.getByRole('button', { name: '加入比较', exact: true }).click(); }
    check('two_checked_and_two_compared', (await choiceState()).selected.length === 2 && (await choiceState()).compared.length === 2);
  }, true);

  scenario('synthetic_watch_four_record_contexts');
  const watchRows = cases.map(item => ({ id: randomUUID(), variant_id: item.variant.id, variant: item.variant, tracking_state: 'current' }));
  const watch = await makeGate({ label: 'synthetic_watch_read', path: '/v1/watchlists', method: 'GET', body: { items: watchRows } });
  await page.locator('.main-nav').getByRole('button', { name: /关注/ }).click(); await watch.entered(); await releaseGates([watch]);
  await uiOnly('watch_all_contexts_read_only', async () => {
    for (let index = 0; index < cases.length; index++) {
      const target = page.locator('.variant-card').filter({ has: page.locator(`[data-variant-preview-trigger="watch:${watchRows[index].id}"]`) });
      await assertCard(target, cases[index], 'watch_' + cases[index].name);
    }
    const target = page.locator('.variant-card').filter({ has: page.locator(`[data-variant-preview-trigger="watch:${watchRows[3].id}"]`) });
    await shot('watch-mixed-wide', target.locator('[aria-label="来源字段冲突"]'));
  });
  scenario('synthetic_current_and_saved_comparison_contexts');
  const chosen = cases.slice(2), comparison = { data_state: 'local_snapshot', variant_ids: chosen.map(item => item.variant.id), include_manual: false,
    resolve_identities: false, identity_mappings: [], fingerprint: 'r131-synthetic-current', variants: chosen.map(item => item.variant), excluded_variants: [], provenance: [],
    conflicts: chosen.flatMap(item => item.conflicts), notice: '仅R131兼容UI合成比较' };
  const savedRecord = { id: randomUUID(), title: 'R131合成固定比较', notes: '仅兼容UI输入，不代表实际保存记录', revision: 1, archived: false,
    created_at: stamp, updated_at: stamp, fingerprint: 'r131-synthetic-saved', variant_count: 2, include_manual: true };
  const compareGate = await makeGate({ label: 'synthetic_readonly_compare_post', path: '/v1/compare', expectedBody: { variant_ids: comparison.variant_ids, include_manual: false, resolve_identities: false }, body: comparison });
  const savedList = await makeGate({ label: 'synthetic_saved_list_get', path: '/v1/saved-comparisons?archived=false&offset=0', method: 'GET',
    body: { items: [savedRecord], total: 1, offset: 0, limit: 20 } });
  await page.locator('.main-nav').getByRole('button', { name: /规格比较/ }).click();
  await Promise.all([compareGate.entered(), savedList.entered()]); await releaseGates([compareGate, savedList]);
  const current = page.locator('section[aria-label="本次比较的来源字段冲突"]'); await current.waitFor();
  // Separate lists retain their original field labels and indices when combined.
  const assertComparisonItems = async (target, label) => {
    const nodes = target.locator('.conflict-item');
    const headings = await nodes.locator(':scope > strong').allTextContents();
    const expected = chosen.flatMap(item => item.entries.map((entry, index) => entry.name + ' ' + (index + 1) + '：' + entry.expected));
    observe(label + '_headings', { actual: headings, expected }); check(label + '_exact_original_statuses_with_default_and_manual', equal(headings, expected));
    check(label + '_false_zero_null_retained_each_record', equal(await nodes.locator('li b').allTextContents(), expected.flatMap(() => ['否（false）', '0', '来源未标明'])));
    check(label + '_no_old_blanket_or_arbitrary_state_text', !/(?:尚未裁定|已有裁定记录|未自动裁定|r131_unknown_state)/.test(await target.innerText()));
  };
  await uiOnly('current_comparison_records_read_only', async () => {
    check('current_comparison_keeps_default_is_not_adjudication', await current.locator(':scope > strong').innerText() === '本次比较的来源字段冲突 · 默认值不代表裁定');
    await assertComparisonItems(current, 'current');
    check('current_comparison_default_and_manual_separate', (await page.getByRole('region', { name: '当前规格对照表', exact: true }).innerText()).includes('R131默认值'));
    await shot('current-comparison-wide', current);
  });
  phase = 'action:saved_detail';
  const savedDetail = await makeGate({ label: 'synthetic_saved_detail_get', path: '/v1/saved-comparisons/' + savedRecord.id + '?mode=history', method: 'GET',
    body: { ...savedRecord, data_state: 'local_snapshot', comparison: { ...comparison, include_manual: true, fingerprint: savedRecord.fingerprint },
      current_lifecycle: {}, current_identity_resolutions: {}, history_truncated: false, history: [] } });
  const savedOpen = page.getByRole('button', { name: '打开保存的比较', exact: true });
  await savedOpen.click(); await savedDetail.entered(); await releaseGates([savedDetail]);
  const dialog = page.getByRole('dialog', { name: savedRecord.title, exact: true }), saved = dialog.locator('section[aria-label="保存时的来源字段冲突"]');
  await saved.waitFor();
  await uiOnly('saved_comparison_fixed_context_and_320', async () => {
    check('saved_heading_uses_saved_original_conflict_records', await saved.locator(':scope > strong').innerText() === '保存时的来源字段冲突记录');
    check('saved_fixed_version_context_visible', (await dialog.locator('.snapshot-banner').first().innerText()).includes('固定保存版本'));
    await assertComparisonItems(saved, 'saved');
    const tableText = await dialog.getByRole('region', { name: '已保存规格对照表', exact: true }).innerText();
    check('saved_default_and_manual_remain_independent', tableText.includes('R131默认值') && tableText.includes('R131人工值') && tableText.includes('独立于来源默认'));
    await shot('saved-comparison-wide', saved); await page.setViewportSize({ width: 320, height: 844 }); await shot('saved-comparison-320', saved);
  });
  await uiOnly('saved_dialog_close_returns_focus', async () => {
    await dialog.getByRole('button', { name: '关闭比较记录窗口', exact: true }).click(); await dialog.waitFor({ state: 'detached' });
    check('saved_dialog_focus_returns_to_open_button', await savedOpen.evaluate(node => document.activeElement === node));
  });
  const finalFixture = await harnessJson('final_fixture_state', 'GET', '/fixture/state');
  receipt.final_fixture = { counters: finalFixture.counters, source_calls: finalFixture.source_calls, real_source_calls: finalFixture.real_source_calls,
    provider_calls: finalFixture.provider_calls, model_requests: finalFixture.model_requests, embedding_requests: finalFixture.embedding_requests };
  check('only_two_real_source_calls_zero_external_child_normal_db_model', finalFixture.source_calls === 2 && finalFixture.real_source_calls === 0
    && Object.values(finalFixture.counters).every(value => value === 0) && finalFixture.provider_calls === 0 && finalFixture.model_requests === 0 && finalFixture.embedding_requests === 0);
  check('six_query_posts_one_readonly_compare_no_watch_or_saved_writes', queryRows().length === 6 && postRows().filter(row => row.path === '/api/v1/compare').length === 1
    && postRows().every(row => row.request_id === preview.request_id && row.sequence <= initializationEnd
      || receipt.request_gates.some(record => record.method === 'POST' && record.request_id === row.request_id && record.claimed && record.body_matched)));
  check('business_requests_all_finished_once', businessRows().every(row => receipt.http_events.filter(event => event.request_id === row.request_id && event.event === 'finished').length === 1));
  check('eleven_exact_planned_requests_finished_removed', gatesPassed());
  check('ten_specific_ui_windows_zero_business_requests', receipt.ui_request_windows.length === 10 && receipt.ui_request_windows.every(row => row.business_requests.length === 0));
  check('strict_browser_network_gate_zero_errors', !receipt.page_errors.length && !receipt.console_errors.length && !receipt.unexpected_origins.length
    && !receipt.unexpected_http_statuses.length && !receipt.gate_failures.length && receipt.http_events.every(row => row.event !== 'failed'));
  receipt.production_workbench_verified = true; receipt.state = 'passed';
} catch (error) {
  receipt.state = 'failed'; receipt.failure = { stage, phase, type: ['Error', 'TimeoutError', 'TypeError', 'SyntaxError'].includes(error?.name) ? error.name : 'Error',
    check: /^[a-zA-Z0-9_:-]+$/.test(error?.message || '') ? error.message : null,
    source_frames: [...String(error?.stack || '').matchAll(/source_conflict_record_ui_qa\.mjs:(\d+):(\d+)/g)].map(match => ({ line: Number(match[1]), column: Number(match[2]) })),
    inflight_count: inFlight.size, last_http_events: receipt.http_events.slice(-16), active_gate_labels: [...gates].map(gate => gate.record.label) };
  if (page) try { receipt.failure.dom = await page.evaluate(() => ({ view: document.querySelector('.main-nav .active')?.textContent,
    conflict_summaries: [...document.querySelectorAll('.conflict-details > summary')].map(node => node.textContent),
    card_count: document.querySelectorAll('.variant-card').length, dialog_count: document.querySelectorAll('dialog[open]').length,
    loading: [...document.querySelectorAll('.run-loading,[role="status"]')].slice(0, 8).map(node => node.textContent?.slice(0, 200)) }));
    await page.screenshot({ path: resolve(output, 'failure.png') }); receipt.screenshots.push('failure.png'); } catch {}
} finally {
  password = null;
  for (const gate of gates) gate.release();
  for (const gate of [...gates]) { try { if (gate.record.claimed) await gate.settle(); await gate.remove(); } catch { receipt.cleanup_failures.push('pending_gate_cleanup_failed'); } }
  try { if (context) { const response = await context.request.post(fixtureOrigin + '/fixture/shutdown', { timeout: 5000 }); receipt.fixture_shutdown_requested = response.ok();
    receipt.harness_http.push({ label: 'fixture_shutdown', method: 'POST', path: '/fixture/shutdown', status: response.status(), origin: 'real_private_fixture_control' }); } } catch { receipt.cleanup_failures.push('fixture_shutdown_request_failed'); }
  let closeTimer;
  try { await Promise.race([(async () => { if (context) await context.close(); if (browser) await browser.close(); if (browserServer) await browserServer.close(); })(),
    new Promise((_, reject) => { closeTimer = setTimeout(() => reject(Error('browser_close_timeout')), 20000); })]);
    receipt.browser_close_returned = !!browserProcess && browserProcess.exitCode === 0 && browserProcess.signalCode === null && receipt.browser.server_close_observed === true;
  } catch { receipt.cleanup_failures.push('browser_close_failed'); if (browserServer) { receipt.browser.forced_kill_requested = true; try { await browserServer.kill(); } catch { receipt.cleanup_failures.push('browser_kill_failed'); } } }
  finally { clearTimeout(closeTimer); }
  receipt.request_gate_coverage = { required: requiredGates, recorded: receipt.request_gates.length, state: gatesPassed() ? 'passed' : 'failed', routes_removed: gates.size === 0 && activeRecords.size === 0 };
  if (!gatesPassed()) receipt.coverage_failures.push('eleven_exact_planned_requests_not_satisfied');
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
